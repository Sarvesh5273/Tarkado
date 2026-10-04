"""Non-destructive privacy controls and explainable permitted monitoring."""

from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from engine.feedback import _fingerprint, _timestamp
from engine.schemas import ValidationError, object_fields, text
from .models import DeliveryBinding, OperationalControl, ScopedSelectionRuntime
from .security import sensitive_actor
from .services import current_member, member_snapshot


def privacy_state(company):
    control = OperationalControl.objects.filter(company=company).first()
    result = {"revision": 0, "collection_paused": False, "retention_policy": "manual", "retention_review_at": None,
              "automatic_deletion_supported": False, "raw_content_supported": False, "events": []}
    previous, at = None, None
    for sequence, event in enumerate(control.journal if control else [], 1):
        fields = ("sequence", "timestamp", "actor", "action", "reason", "retention_review_at", "previous_sha256", "sha256")
        object_fields(event, fields, fields)
        now, actor = _timestamp(event["timestamp"]), event["actor"]
        if event["sequence"] != sequence or event["previous_sha256"] != previous or event["sha256"] != _fingerprint({k: v for k, v in event.items() if k != "sha256"}) or at and now < at:
            raise ValidationError("Privacy-control history is inconsistent; do not reset records.")
        if actor.get("role") != "admin" or actor.get("can_manage_company") is not True or actor.get("active") is not True:
            raise ValidationError("Privacy control has no designated historical administrator.")
        text(event["reason"], "reason")
        if event["action"] in ("pause_collection", "resume_collection"):
            paused = event["action"] == "pause_collection"
            if result["collection_paused"] == paused or event["retention_review_at"] is not None:
                raise ValidationError("Privacy-control transition is invalid.")
            result["collection_paused"] = paused
        elif event["action"] == "review_retention":
            _timestamp(event["retention_review_at"])
            result["retention_review_at"] = event["retention_review_at"]
        else:
            raise ValidationError("Deletion/duration/raw-content policy is not authorized or implemented.")
        result["revision"] = sequence
        previous, at = event["sha256"], now
    result["events"] = control.journal if control else []
    return result


def require_collection_open(company):
    if privacy_state(company)["collection_paused"]:
        raise PermissionDenied("Administrator paused new task metadata collection/delivery. Preserve history and reconcile outstanding costs.")


def privacy_control(request, password, code, action, reason, expected_revision, review_at=None):
    sensitive_actor(request, password, code, "manage")
    with transaction.atomic():
        member = current_member(request.user, "manage")
        current = privacy_state(member.company)
        if type(expected_revision) is not int or expected_revision != current["revision"]:
            raise ValidationError("Privacy controls changed; review before a stale action.")
        if action == "review_retention":
            if review_at is None or timezone.is_naive(review_at) or review_at <= timezone.now():
                raise ValidationError("Select a future retention review reminder; this does not schedule deletion.")
        elif review_at is not None:
            raise ValidationError("Only retention review may set a reminder date.")
        control, _ = OperationalControl.objects.get_or_create(company=member.company)
        event = {"sequence": current["revision"] + 1, "timestamp": timezone.now().isoformat(), "actor": member_snapshot(member),
                 "action": action, "reason": text(reason, "reason"), "retention_review_at": review_at.isoformat() if review_at else None,
                 "previous_sha256": control.journal[-1]["sha256"] if control.journal else None}
        event["sha256"] = _fingerprint(event)
        control.journal += [event]
        control.save(update_fields=("journal",))
        return privacy_state(member.company)


def delivery_summary(binding):
    from .delivery import state
    from .billing_corrections import retained_overrun
    current = state(binding)
    envelope = binding.data["envelope"]
    result = {"binding_ref": str(binding.reference), "policy_model": envelope["model_id"], "gateway_model": envelope["gateway_model"],
            "provider_model": envelope["provider_model"], "task_cap_usd": binding.data["task_cap_usd"],
            "known_cost_usd": current["known_cost_usd"], "unknown_attempts": current["unknown_attempts"],
            "attempt_reserved_usd": current["attempt_reserved_usd"], "remaining_task_usd": current["remaining_task_usd"],
            "closed": current["closed"], "requests": list(current["requests"].values()), "attempts": list(current["attempts"].values()),
            "revision": current["revision"],
            "corrections": [event for event in binding.journal if event["action"] == "correct_cost"],
            "historical_cost_overrun": retained_overrun(binding, current),
            "usage_source": "authenticated_gateway_metadata", "provider_invoice_verified": False, "engineering_outcome_verified": False}
    if envelope.get("schema_version") == 2:
        result["local_tools"] = envelope["local_tools"]
        result["local_execution_evidence_ref"] = envelope["local_execution_evidence_ref"]
    from .tool_observations import state as tool_state
    if binding.tool_observations.exists():
        result["tool_capture"] = tool_state(binding)
    return result


@transaction.atomic
def monitor(request):
    member = current_member(request.user)
    if not (member.can_manage_company or member.can_approve_pilots):
        raise PermissionDenied("Company monitoring requires explicit review/administrative permission.")
    from .tasks import company_feedback
    from .connectors import task_state
    from .selection import _state, accounting
    feedback = company_feedback(request.user, request=request)
    tasks = {str(task.reference): task for task in feedback["tasks"]}
    alerts, deliveries = [], []
    by_recommendation = {row["recommendation_id"]: row for row in feedback["summary"]["tasks"]}
    from .tasks import task_ledger
    for reference, task in tasks.items():
        row = by_recommendation[task_ledger(task).recommendations[0].recommendation_id]
        signals = []
        if row.get("response") == "reject": signals.append("rejected_suggestion")
        if row.get("model_override"): signals.append("developer_override")
        if row.get("desired_result") is False or row.get("tests_passed") is False: signals.append("reported_failure")
        if row.get("desired_result") is None: signals.append("unknown_outcome")
        if hasattr(task, "connector_link"):
            observed = task_state(task.connector_link)
            if observed["gap_count"]: signals.append("observation_gap")
            if observed["multiple_models"]: signals.append("multiple_primary_models")
            if any((event.payload.get("http_status") or 0) >= 400 for event in task.connector_link.observations.all()): signals.append("gateway_http_error")
        binding = DeliveryBinding.objects.filter(connector_task__task=task).first()
        if binding:
            summary = delivery_summary(binding)
            deliveries.append({"task_ref": reference, "developer": task.owner.username, **summary})
            if summary["unknown_attempts"]: signals.append("unknown_provider_obligation")
            if any(attempt["outcome"] in ("failed", "retryable_failure") for attempt in summary["attempts"]): signals.append("provider_failure")
            if Decimal(summary["remaining_task_usd"]) < 0: signals.append("provider_budget_overrun")
            if summary["historical_cost_overrun"]:
                signals.append("historical_provider_cost_overrun")
            if "tool_capture" in summary:
                signals.extend("tool_" + status for status in summary["tool_capture"]["negative_signals"])
                if summary["tool_capture"]["pending_invocations"]: signals.append("tool_missing_result")
        for signal in signals:
            alerts.append({"alert_ref": _fingerprint({"task_ref": reference, "signal": signal}), "task_ref": reference,
                           "developer": task.owner.username, "historical_role": row["developer_role"], "signal": signal})
    alerts.sort(key=lambda row: (row["historical_role"] != "senior", row["developer"], row["task_ref"], row["signal"]))
    pilots = [{"scope_ref": str(runtime.authorization.reference), "status": _state(runtime)["status"], "accounting": accounting(runtime)}
              for runtime in ScopedSelectionRuntime.objects.filter(authorization__company=member.company).select_related("authorization")]
    return {"alerts": alerts, "deliveries": deliveries, "pilots": pilots, "privacy": privacy_state(member.company),
            "feedback": feedback["summary"], "scope": "current_permitted_company_view", "automatic_expansion": False}
