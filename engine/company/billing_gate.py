"""Independent reconciliation gate: a gateway error or reference is not a zero-cost receipt."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

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

    def to_dict(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value):
        fields = tuple(cls.__dataclass_fields__)
        result = cls(**object_fields(value, fields, fields))
        for key in fields: text(getattr(result, key), key)
        if _timestamp(result.valid_until) <= _timestamp(result.verified_at):
            raise ValidationError("Billing reconciliation has no positive verified interval.")
        return result


class BillingVerifier(ABC):
    @abstractmethod
    def verify(self, request) -> BillingAssessment:
        """Check actual provider/accounting evidence for this exact obligation, not a submitted checkbox/reference."""
        raise NotImplementedError


def reconciliation_request(binding, attempt, payload):
    return {"company_id": binding.data["company_id"], "deployment_id": binding.data["deployment_id"],
            "binding_ref": str(binding.reference), "selection_id": binding.selection_id, "envelope": binding.data["envelope"],
            "attempt_id": attempt["attempt_id"], "request_id": attempt["request_id"], "reserve_usd": attempt["reserve_usd"],
            "settlement": {key: value for key, value in payload.items() if key != "billing_assessment"}}


def verify(request):
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
    return assessment.to_dict()
