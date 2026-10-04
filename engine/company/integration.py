"""Explicit operator-reviewed verifier startup, not form-supplied live permission."""

import hashlib
import importlib.util
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from django.conf import settings

from engine.schemas import ValidationError, object_fields, text
from engine.startup_config import private_json
from .billing_gate import BillingVerifier
from .connectors import uuid_value
from .delivery import DeliveryVerifier, NarrowDeliveryAdmissionVerifier
from .readiness_gate import ReadinessVerifier


@dataclass(frozen=True)
class CompanyIntegration:
    company_id: str
    deployment_id: str
    integration_id: str
    readiness: ReadinessVerifier
    delivery: DeliveryVerifier
    billing: BillingVerifier | None = None


def install(company, integration):
    if not isinstance(integration, CompanyIntegration):
        raise ValidationError("Trusted startup must return a typed company integration, not verified/ready booleans.")
    if (integration.company_id, integration.deployment_id) != (str(company.company_id), str(company.deployment_id)):
        raise ValidationError("Reviewed integration belongs to a different company/deployment.")
    text(integration.integration_id, "integration_id")
    if not isinstance(integration.readiness, ReadinessVerifier) or not isinstance(integration.delivery, DeliveryVerifier) or (
        integration.billing is not None and not isinstance(integration.billing, BillingVerifier)
    ):
        raise ValidationError("Independent readiness/host/billing verifier interfaces are required; labels cannot substitute for evidence.")
    if any(getattr(settings, name, None) is not None for name in ("TARKADO_READINESS_VERIFIER", "TARKADO_ADMISSION_VERIFIER", "TARKADO_DELIVERY_VERIFIER", "TARKADO_BILLING_VERIFIER")):
        raise ValidationError("Verifier startup already configured; never replace a running company's authority silently.")
    settings.TARKADO_READINESS_VERIFIER = integration.readiness
    settings.TARKADO_ADMISSION_VERIFIER = NarrowDeliveryAdmissionVerifier()
    settings.TARKADO_DELIVERY_VERIFIER = integration.delivery
    settings.TARKADO_BILLING_VERIFIER = integration.billing
    return {"integration_id": integration.integration_id, "configured": True, "routing_enabled": False, "execution_sent": False,
            "note": "Verifier wiring only. Exact evidence, fresh human scope approval, activation and per-attempt checks still apply."}


def load_reviewed(path, company, *, operator_approved=False):
    if operator_approved is not True:
        raise ValidationError("Explicit operator approval is required before loading reviewed server integration code.")
    value = private_json(path)
    fields = ("schema_version", "company_id", "deployment_id", "module", "factory", "source_sha256")
    object_fields(value, fields, fields)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationError("Unsupported reviewed integration manifest version.")
    for field in ("company_id", "deployment_id"):
        uuid_value(value[field])
    if (value["company_id"], value["deployment_id"]) != (str(company.company_id), str(company.deployment_id)):
        raise ValidationError("Reviewed manifest names another company/deployment.")
    for field in ("module", "factory"):
        text(value[field], field)
        if not value[field].isascii() or not value[field].isidentifier():
            raise ValidationError("Use explicit simple module/factory identifiers; package discovery/executable paths are unsupported.")
    digest = text(value["source_sha256"], "source_sha256")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValidationError("Reviewed module source fingerprint is required.")
    if value["module"] in sys.modules:
        raise ValidationError("Integration module is already loaded; use clean explicit service startup, not live replacement.")
    spec = importlib.util.find_spec(value["module"])
    if spec is None or spec.origin is None or not spec.origin.endswith(".py") or spec.submodule_search_locations is not None:
        raise ValidationError("Reviewed startup supports one explicit Python source module, not arbitrary packages/native loaders.")
    try:
        with os.fdopen(os.open(spec.origin, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > 131072:
                raise ValidationError("Reviewed source must be bounded operator-owned code, not group/world-writable.")
            source = stream.read(131073)
    except OSError:
        raise ValidationError("Reviewed source is unreadable; no code loaded or state repaired.") from None
    if len(source) > 131072 or hashlib.sha256(source).hexdigest() != digest:
        raise ValidationError("Reviewed source changed; no integration factory was executed.")
    module = ModuleType(value["module"])
    module.__file__ = str(Path(spec.origin))
    module.__spec__ = spec
    sys.modules[value["module"]] = module
    try:
        # Execute exactly the reviewed bytes, not a subsequently changed .py/.pyc.
        # Imports made by that trusted code remain an operator review responsibility.
        exec(compile(source, spec.origin, "exec"), module.__dict__)
        factory = getattr(module, value["factory"], None)
        if not callable(factory):
            raise ValidationError("Reviewed module has no configured integration factory.")
        integration = factory()
        return install(company, integration)
    except Exception:
        raise ValidationError("Reviewed integration startup failed. Verifiers were not authorized by a manifest or checkbox; inspect approved code without exporting private diagnostics.") from None
