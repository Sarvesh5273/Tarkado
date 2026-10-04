"""Explicit reviewed learner publication; never pilot approval or background retraining."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from engine.feedback import _fingerprint
from engine.learning import LearnedModel, learned_decision
from engine.schemas import Policy, ValidationError, boolean, choice, integer, object_fields, strings, text

from .models import EvidenceReview, LearningPublication
from .services import current_member, member_snapshot
from .security import sensitive_actor
from .mfa import _audit, require_request_mfa


def history(company, source_kind):
    rows = list(LearningPublication.objects.filter(company=company, source_kind=source_kind).select_related("review", "actor"))
    previous = None
    for sequence, row in enumerate(rows, 1):
        data = row.data
        fields = ("action", "source_kind", "sequence", "company_id", "deployment_id", "company_revision", "actor", "mfa_generation", "created_at",
                  "reason", "repositories", "review_ref", "review_sha256", "learner_sha256", "previous_sha256", "sha256")
        object_fields(data, fields, fields)
        for key in ("sequence", "company_revision", "mfa_generation"):
            integer(data[key], key)
        actor_fields = ("account_id", "developer_id", "role", "active", "participating", "can_manage_company", "can_approve_pilots")
        object_fields(data["actor"], actor_fields, actor_fields)
        for key in ("active", "participating", "can_manage_company", "can_approve_pilots"):
            boolean(data["actor"][key], key)
        actor = data["actor"]
        if not actor["active"] or not (actor["role"] == "admin" and actor["can_manage_company"] or actor["role"] in ("senior", "admin") and actor["can_approve_pilots"]):
            raise ValidationError("Publication has no permitted historical reviewer authority.")
        if (data["sha256"] != _fingerprint({key: val for key, val in data.items() if key != "sha256"})
            or data["previous_sha256"] != previous or sequence != row.sequence or data["sequence"] != sequence
            or data["source_kind"] != source_kind or data["actor"]["account_id"] != row.actor_id
            or data["created_at"] != row.created_at.isoformat() or data["company_id"] != str(company.company_id)
            or data["deployment_id"] != str(company.deployment_id)):
            raise ValidationError("Learner publication history is inconsistent; it will not be reset.")
        if data["action"] == "publish":
            if row.review is None or data["review_ref"] != str(row.review.reference) or data["review_sha256"] != row.review.data["sha256"]:
                raise ValidationError("Published learner differs from its exact retained review.")
            learner = LearnedModel.from_dict(row.review.data["learner"])
            if learner.sha256 != data["learner_sha256"] or learner.plan.source_kind != source_kind:
                raise ValidationError("Published learner snapshot differs from its version/source.")
            if row.review.company_id != company.pk or data["actor"]["role"] not in ("senior", "admin"):
                raise ValidationError("Published learner has no matching company/reviewer attribution.")
            if _fingerprint({key: value for key, value in row.review.data.items() if key != "sha256"}) != data["review_sha256"]:
                raise ValidationError("Published review content differs from its immutable source binding.")
        elif data["action"] != "default_only" or row.review is not None or data["learner_sha256"] is not None:
            raise ValidationError("Unsupported learner publication transition.")
        previous = data["sha256"]
    return rows


def change(request, password, code, source_kind, expected_sequence, reason, review_ref=None, repositories=()):
    sensitive_actor(request, password, code)
    with transaction.atomic():
        from .authorization import _reviewer, verify_review
        member = _reviewer(request)
        require_request_mfa(request, member.user)
        choice(source_kind, "source_kind", ("synthetic", "team"))
        rows = history(member.company, source_kind)
        sequence = rows[-1].sequence if rows else 0
        if type(expected_sequence) is not int or expected_sequence != sequence:
            raise ValidationError("Published learner changed; reload before a stale publication/rollback.")
        review = None
        learner = None
        if review_ref is not None:
            review = EvidenceReview.objects.filter(company=member.company, reference=review_ref).first()
            if review is None:
                raise PermissionDenied("Review is not stored for this company.")
            _, learner, _ = verify_review(review, member.company)
            if learner.plan.source_kind != source_kind:
                raise ValidationError("Cannot publish a learner under a different source label.")
            repositories = strings(list(repositories), "repository_refs")
            if not repositories or set(repositories) - set(member.company.repository_refs):
                raise ValidationError("Publication needs explicit currently approved repositories.")
            other = LearningPublication.objects.filter(company=member.company, data__learner_sha256=learner.sha256).exclude(review=review)
            if other.exists():
                raise ValidationError("Learner fingerprint was published from another review binding.")
            conflicting = EvidenceReview.objects.filter(company=member.company, data__learner__plan__learner_version=learner.plan.learner_version).exclude(data__learner__learner_sha256=learner.sha256)
            if conflicting.exists():
                raise ValidationError("Learner version names conflicting artifacts; refit with a new version before publishing.")
        now = timezone.now()
        data = {"action": "publish" if review else "default_only", "source_kind": source_kind, "sequence": sequence + 1,
                "company_id": str(member.company.company_id), "deployment_id": str(member.company.deployment_id),
                "company_revision": member.company.revision, "actor": member_snapshot(member), "created_at": now.isoformat(),
                "mfa_generation": member.user.mfastate.generation,
                "reason": text(reason, "reason"), "repositories": list(repositories) if review else [],
                "review_ref": str(review.reference) if review else None, "review_sha256": review.data["sha256"] if review else None,
                "learner_sha256": learner.sha256 if learner else None, "previous_sha256": rows[-1].data["sha256"] if rows else None}
        data["sha256"] = _fingerprint(data)
        publication = LearningPublication.objects.create(company=member.company, review=review, source_kind=source_kind,
            sequence=sequence + 1, actor=member.user, created_at=now, data=data)
        _audit(member, "learner_" + data["action"], publication_ref=str(publication.reference), learner_sha256=data["learner_sha256"],
               sequence=sequence + 1, manual_suggestions_only=True, reason=data["reason"])
        return publication


def guard(publication, company):
    if publication is None or publication.data["action"] != "publish":
        return {"status": "default_only", "reason": "No learner is published; retain the static/default baseline."}
    try:
        history(company, publication.source_kind)
        from .tasks import company_ledger
        from .authorization import _review_payload
        actor = current_member(publication.actor)
        if (not (actor.role == "admin" and actor.can_manage_company) and not (actor.role in ("senior", "admin") and actor.can_approve_pilots)):
            raise ValidationError("Publisher authority was removed; separately publish after review.")
        if member_snapshot(actor) != publication.data["actor"] or company.revision != publication.data["company_revision"]:
            raise ValidationError("Company/publisher configuration changed; re-review publication.")
        from .models import MFAState
        from django_otp.plugins.otp_totp.models import TOTPDevice
        if (MFAState.objects.filter(user=actor.user).values_list("generation", flat=True).first() != publication.data["mfa_generation"]
            or not TOTPDevice.objects.filter(user=actor.user, confirmed=True).exists()):
            raise ValidationError("Publisher MFA/recovery changed; re-review the published learner.")
        learner = LearnedModel.from_dict(publication.review.data["learner"])
        ledger = company_ledger(company, learner.plan.source_kind)
        learner.verify_source(ledger)
        if Policy.from_dict(company.policy).fingerprint() != learner.policy.sha256:
            raise ValidationError("Current policy differs from the published learner.")
        # Future recommendations alone do not invalidate the fixed validation view.
        # New feedback and changed observations still invalidate it; no negatives are omitted.
        old = publication.review.data.get("connector_observations", [])
        reviewed = _review_payload(company, ledger, learner)
        current = reviewed.get("connector_observations", [])
        by_ref = {item["task_ref"]: item for item in current}
        if any(by_ref.get(item["task_ref"], {}).get("observations") != item["observations"] for item in old):
            raise ValidationError("Bound connector observations changed after publication.")
        for item in current:
            if item["task_ref"] not in {row["task_ref"] for row in old} and (item["state"]["gap_count"] or item["state"]["multiple_models"]
                or any((row["payload"].get("http_status") or 0) >= 400 for row in item["observations"])):
                raise ValidationError("New connector gaps/errors/multiple-model evidence requires another validation review.")
        from .delivery_evidence import verify_frozen
        deliveries = reviewed.get("delivery_observations", [])
        verify_frozen(publication.review.data.get("delivery_observations", []), deliveries)
        if any(item["negative_signals"] and item["task_type"] in learner.plan.task_types for item in deliveries):
            raise ValidationError("Retained gateway delivery failures/unknown obligations block this learned suggestion; investigate them without fabricating desired results.")
        from .tool_observations import verify_execution
        verify_execution(publication.review.data.get("tool_observations", []), reviewed.get("tool_observations", []), task_types=learner.plan.task_types)
        return {"status": "current", "reason": "Published validation artifact and current negative/unknown feedback checks match. Confidence remains experimental."}
    except (ValidationError, PermissionDenied) as error:
        return {"status": "blocked", "reason": str(error)}


def suggestion(member, source, task):
    rows = history(member.company, source["source_kind"])
    publication = rows[-1] if rows else None
    if publication is None or publication.data["action"] != "publish" or source["repository_ref"] not in publication.data["repositories"]:
        return None, {}
    current = guard(publication, member.company)
    context = {"publication_ref": str(publication.reference), "publication_sha256": publication.data["sha256"],
               "status": current["status"], "reason": current["reason"]}
    if current["status"] != "current":
        return None, context
    learner = LearnedModel.from_dict(publication.review.data["learner"])
    try:
        learned_decision(task, Policy.from_dict(member.company.policy), learner)
    except ValidationError as error:
        context.update(status="blocked", reason=str(error))
        return None, context
    return learner.to_dict(), context


def current_status(company, source_kind):
    rows = history(company, source_kind)
    publication = rows[-1] if rows else None
    return {"sequence": publication.sequence if publication else 0, "guard": guard(publication, company),
            "learner_version": publication.review.data["learner"]["plan"]["learner_version"] if publication and publication.review else None}
