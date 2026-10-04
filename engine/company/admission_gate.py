"""Trusted new-task capability checks. The observe-only connector cannot install or satisfy this gate."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from engine.feedback import _fingerprint, _timestamp
from engine.schemas import ValidationError, boolean, object_fields, text


@dataclass(frozen=True)
class AdmissionRequest:
    company_id: str
    deployment_id: str
    scope_record_sha256: str
    selection_request_sha256: str
    selection_request: dict
    model_id: str
    commitment_usd: str

    @property
    def sha256(self):
        return _fingerprint(self.to_dict())

    def to_dict(self):
        if _fingerprint(self.selection_request) != self.selection_request_sha256:
            raise ValidationError("Admission task metadata differs from its request binding.")
        return {"company_id": self.company_id, "deployment_id": self.deployment_id,
                "scope_record_sha256": self.scope_record_sha256, "selection_request_sha256": self.selection_request_sha256,
                "selection_request": self.selection_request, "model_id": self.model_id, "commitment_usd": self.commitment_usd}


@dataclass(frozen=True)
class AdmissionAssessment:
    adapter_id: str
    boundary_ref: str
    request_sha256: str
    verified_at: str
    valid_until: str
    new_task_verified: bool
    owner_scope_verified: bool
    atomic_model_binding_supported: bool
    provider_cap_enforced: bool
    deployment_validated: bool

    def to_dict(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value):
        fields = tuple(cls.__dataclass_fields__)
        data = object_fields(value, fields, fields)
        _fingerprint(data)
        for key in fields[:5]:
            text(data[key], key)
        if len(data["request_sha256"]) != 64 or any(ch not in "0123456789abcdef" for ch in data["request_sha256"]):
            raise ValidationError("Admission assessment must bind the exact scoped selection request.")
        if _timestamp(data["valid_until"]) <= _timestamp(data["verified_at"]):
            raise ValidationError("Admission assessment has no positive validity interval.")
        for key in fields[5:]:
            if not boolean(data[key], key):
                raise ValidationError("Trusted new-task, scope, atomic model binding, provider cap, and deployment checks are required.")
        return cls(**data)


class AdmissionVerifier(ABC):
    """Read-only verification by a trusted delivery adapter, never a browser/connector assertion.

    Must verify the new-task boundary, employee/repository scope, bounded provider
    capability, and deployment. It cannot claim that selecting a model dispatched
    it. Actual delivery must consume the matching one-use selection before sending
    its exact selected model and enforce its cap; this service performs no dispatch.
    """

    @abstractmethod
    def verify(self, request: AdmissionRequest) -> AdmissionAssessment:
        raise NotImplementedError


def verify_admission(request, expected=None):
    verifier = getattr(settings, "TARKADO_ADMISSION_VERIFIER", None)
    if not isinstance(verifier, AdmissionVerifier):
        raise ValidationError("Trusted task/provider admission is unconfigured. Observe-only OpenCode metadata cannot enable automatic selection or execution.")
    try:
        value = verifier.verify(request)
    except ValidationError:
        raise
    except Exception:
        raise ValidationError("Trusted admission verification failed; selection remains unavailable.") from None
    if not isinstance(value, AdmissionAssessment):
        raise ValidationError("Trusted admission verifier returned no typed assessment.")
    assessment = AdmissionAssessment.from_dict(value.to_dict())
    if assessment.request_sha256 != request.sha256 or not _timestamp(assessment.verified_at) <= timezone.now() < _timestamp(assessment.valid_until):
        raise ValidationError("Admission assessment is wrong-bound, expired, or future dated.")
    if expected is not None and assessment.to_dict() != AdmissionAssessment.from_dict(expected).to_dict():
        raise ValidationError("Admission capability changed; the old selection cannot be delivered.")
    return assessment
