"""Retained gateway diagnostics for review, not invented human task outcomes."""

from decimal import Decimal

from engine.feedback import _fingerprint
from engine.schemas import ValidationError

from .delivery import state
from .models import DeliveryBinding


def observations(company, source_kind):
    rows = DeliveryBinding.objects.select_related("connector_task__task__company", "gateway__company", "runtime").filter(
        connector_task__task__company=company, connector_task__task__source_kind=source_kind).order_by("id")
    result = []
    for binding in rows:
        current = state(binding)
        task, envelope = binding.connector_task.task, binding.data["envelope"]
        signals = []
        # Read all retained settlements, not only the latest accounting status.
        # Later billing reconciliation must not erase a timeout/failure/retry.
        for event in binding.journal:
            if event["action"] != "settle":
                continue
            payload = event["payload"]
            attempt = current["attempts"][payload["attempt_id"]]
            request = current["requests"][attempt["request_id"]]
            if payload["outcome"] == "unknown":
                signals.append("unknown_provider_obligation")
            if payload["outcome"] == "failed":
                signals.append("provider_failure")
            if payload["outcome"] == "retryable_failure":
                signals.append("provider_retryable_failure")
            if payload["actual_model"] not in (None, envelope["provider_model"]):
                signals.append("provider_model_mismatch")
            if payload["cost_usd"] is not None and Decimal(payload["cost_usd"]) > Decimal(attempt["reserve_usd"]):
                signals.append("provider_cost_overrun")
            if payload["usage"] is not None and (payload["usage"]["input_tokens"] > envelope["input_token_ceiling"]
                or payload["usage"]["output_tokens"] > request["output_limit"]):
                signals.append("provider_usage_bound_exceeded")
        if Decimal(current["remaining_task_usd"]) < 0:
            signals.append("task_budget_overrun")
        result.append({"binding_ref": str(binding.reference), "task_ref": str(task.reference), "task_type": task.request["task_type"],
            "repository_ref": task.repository_ref, "owner": binding.data["owner"], "selection_id": binding.selection_id,
            "policy_model": envelope["model_id"], "gateway_model": envelope["gateway_model"], "provider_model": envelope["provider_model"],
            "state": current, "negative_signals": list(dict.fromkeys(signals)), "events": binding.journal})
    _fingerprint(result)
    return result


def verify_frozen(previous, current, retry_binding_ref=None):
    by_ref = {item["binding_ref"]: item for item in current}
    def bounded_retry(item):
        # Only a separately reserved same-task retry may continue after a known
        # retryable failure. New tasks and learner publication get no exemption.
        return item is not None and item["binding_ref"] == retry_binding_ref and item["negative_signals"] == ["provider_retryable_failure"]
    if any(by_ref.get(item["binding_ref"]) != item and not bounded_retry(by_ref.get(item["binding_ref"])) for item in previous):
        raise ValidationError("Previously reviewed gateway delivery evidence changed; retain it and review again.")
    previous_refs = {item["binding_ref"] for item in previous}
    if any(item["negative_signals"] and not bounded_retry(item) for item in current if item["binding_ref"] not in previous_refs):
        raise ValidationError("New gateway delivery failures/unknown obligations require another validation review.")
