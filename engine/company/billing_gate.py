"""Independent reconciliation gate: a gateway error or reference is not a zero-cost receipt."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re

from django.conf import settings
from django.utils import timezone

from engine.feedback import _fingerprint, _timestamp
from engine.schemas import ValidationError, object_fields, text


@dataclass(frozen=True)
class BillingAssessment:
    request_sha256: str
    evidence_ref: str
    verifier_id: str
    verified_at: str
    valid_until: str
    evidence_sha256: str | None = None

    def to_dict(self):
        # Preserve the original unknown-cost assessment format when no snapshot exists.
        return {key: getattr(self, key) for key in self.__dataclass_fields__ if key != "evidence_sha256" or self.evidence_sha256 is not None}

    @classmethod
    def from_dict(cls, value):
        fields = tuple(cls.__dataclass_fields__)
        result = cls(**object_fields(value, fields, fields[:-1]))
        for key in fields[:-1]: text(getattr(result, key), key)
        if result.evidence_sha256 is not None and (not isinstance(result.evidence_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", result.evidence_sha256)):
            raise ValidationError("Billing evidence snapshot must have an exact SHA-256 fingerprint.")
        if _timestamp(result.valid_until) <= _timestamp(result.verified_at):
            raise ValidationError("Billing reconciliation has no positive verified interval.")
        return result


class BillingVerifier(ABC):
    @abstractmethod
    def verify(self, request) -> BillingAssessment:
        """Independently check the exact obligation. For known-cost corrections,
        also return a fingerprint of the evidence actually checked, and refuse
        changed account/attempt ownership, superseded invoices or unverified amounts.
        A submitted amount, checkbox, reference or evidence hash is never truth.
        """
        raise NotImplementedError


def reconciliation_request(binding, attempt, payload):
    return {"company_id": binding.data["company_id"], "deployment_id": binding.data["deployment_id"],
            "binding_ref": str(binding.reference), "selection_id": binding.selection_id, "envelope": binding.data["envelope"],
            "attempt_id": attempt["attempt_id"], "request_id": attempt["request_id"], "reserve_usd": attempt["reserve_usd"],
            "settlement": {key: value for key, value in payload.items() if key != "billing_assessment"}}


def verify(request, expected=None, require_snapshot=False):
    verifier = getattr(settings, "TARKADO_BILLING_VERIFIER", None)
    if not isinstance(verifier, BillingVerifier):
        raise ValidationError("Independent billing reconciliation is unconfigured. Unknown cost stays unknown; a reference cannot refund it.")
    try:
        assessment = verifier.verify(request)
    except ValidationError:
        raise
    except Exception:
        raise ValidationError("Billing evidence unavailable; preserve the obligation.") from None
    if not isinstance(assessment, BillingAssessment):
        raise ValidationError("No typed independent billing assessment was returned.")
    assessment = BillingAssessment.from_dict(assessment.to_dict())
    if assessment.request_sha256 != _fingerprint(request) or not _timestamp(assessment.verified_at) <= timezone.now() < _timestamp(assessment.valid_until):
        raise ValidationError("Billing assessment is wrong-bound or expired.")
    if require_snapshot and assessment.evidence_sha256 is None:
        raise ValidationError("Known-cost correction requires independently checked billing evidence content, not only a reference.")
    if expected is not None:
        previous = BillingAssessment.from_dict(expected)
        fields = ("request_sha256", "evidence_ref", "verifier_id", "evidence_sha256")
        if (any(getattr(previous, key) != getattr(assessment, key) for key in fields)
            or not _timestamp(previous.verified_at) <= timezone.now() < _timestamp(previous.valid_until)):
            raise ValidationError("Reviewed billing evidence changed or expired; review the correction again.")
    return assessment.to_dict()
