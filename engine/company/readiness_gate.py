"""A server-owned readiness check; metadata, confidence, and user roles cannot install it."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

from django.conf import settings
from django.utils import timezone

from engine.feedback import _fingerprint, _timestamp
from engine.privacy import ensure_safe
from engine.schemas import ValidationError, boolean, object_fields, text


@dataclass(frozen=True)
class ReadinessRequest:
    company_id: str
    deployment_id: str
    company_revision: int
    review_ref: str
    review_sha256: str
    report_sha256: str
    policy_sha256: str
    feedback_sha256: str
    learner_sha256: str
    scope_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return {"company_id": self.company_id, "deployment_id": self.deployment_id,
                "company_revision": self.company_revision, "review_ref": self.review_ref,
                "review_sha256": self.review_sha256, "report_sha256": self.report_sha256,
                "policy_sha256": self.policy_sha256, "feedback_sha256": self.feedback_sha256,
                "learner_sha256": self.learner_sha256, "scope_sha256": self.scope_sha256}

    @property
    def sha256(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True)
class ReadinessAssessment:
    """An independent check's stable evidence reference, not a caller attestation."""

    verifier_id: str
    evidence_ref: str
    criteria_version: str
    request_sha256: str
    verified_at: str
    valid_until: str
    outcomes_verified: bool
    evaluation_design_verified: bool
    criteria_validated: bool

    @classmethod
    def from_dict(cls, value: Any) -> "ReadinessAssessment":
        fields = ("verifier_id", "evidence_ref", "criteria_version", "request_sha256", "verified_at", "valid_until",
                  "outcomes_verified", "evaluation_design_verified", "criteria_validated")
        data = object_fields(value, fields, fields)
        ensure_safe(data)
        for field in fields[:6]:
            text(data[field], field)
        digest = data["request_sha256"]
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValidationError("Readiness assessment must bind the exact requested company/evidence/scope fingerprint.")
        if _timestamp(data["valid_until"]) <= _timestamp(data["verified_at"]):
            raise ValidationError("Readiness assessment validity must follow its verification time.")
        for field in fields[6:]:
            if not boolean(data[field], field):
                raise ValidationError("Independent outcomes, evaluation design, and criteria validation are required for live approval.")
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {"verifier_id": self.verifier_id, "evidence_ref": self.evidence_ref,
                "criteria_version": self.criteria_version, "request_sha256": self.request_sha256,
                "verified_at": self.verified_at, "valid_until": self.valid_until,
                "outcomes_verified": self.outcomes_verified,
                "evaluation_design_verified": self.evaluation_design_verified, "criteria_validated": self.criteria_validated}


class ReadinessVerifier(ABC):
    """Implement in trusted server code when real company evaluation is approved.

    Return a stable assessment for this exact request, or raise ValidationError.
    Rechecking must consult current evidence/criteria validity and revocation.
    This must not infer verification from imported booleans, synthetic examples,
    per-task acceptance, or the caller's claimed source_kind.
    """

    @abstractmethod
    def verify(self, request: ReadinessRequest) -> ReadinessAssessment:
        raise NotImplementedError


class UnconfiguredReadinessVerifier(ReadinessVerifier):
    def verify(self, request: ReadinessRequest) -> ReadinessAssessment:
        raise ValidationError("Live pilot authorization requires independently verified company readiness; the trusted readiness verifier is not configured. The task/provider adapter and real deployment remain separate gates.")


def verify_readiness(request: ReadinessRequest, expected=None) -> ReadinessAssessment:
    # This setting is installed by trusted application code only. There is no
    # form, JSON config import path, or CLI switch that installs a verifier.
    verifier = getattr(settings, "TARKADO_READINESS_VERIFIER", None)
    if verifier is None:
        verifier = UnconfiguredReadinessVerifier()
    if not isinstance(verifier, ReadinessVerifier):
        raise ValidationError("The configured readiness verifier is not a supported trusted implementation.")
    try:
        supplied = verifier.verify(request)
    except ValidationError:
        raise
    except Exception:
        # Do not expose checker exceptions or ignore an outage as evidence of safety.
        raise ValidationError("Trusted readiness verification failed; live approval remains blocked.") from None
    if not isinstance(supplied, ReadinessAssessment):
        raise ValidationError("The trusted readiness verifier returned no valid assessment.")
    assessment = ReadinessAssessment.from_dict(supplied.to_dict())
    now = timezone.now()
    if assessment.request_sha256 != request.sha256:
        raise ValidationError("Readiness assessment is for different company/evidence/policy/scope content.")
    if not _timestamp(assessment.verified_at) <= now < _timestamp(assessment.valid_until):
        raise ValidationError("Readiness assessment is expired or claims future verification.")
    if expected is not None and assessment.to_dict() != ReadinessAssessment.from_dict(expected).to_dict():
        raise ValidationError("Readiness evidence or criteria changed; an old approval cannot use a replacement assessment.")
    return assessment
