"""Fixed reviewed evidence, incoming learning feedback, and current execution checks are distinct."""

from decimal import Decimal

from engine.feedback import Execution, Response, TaskResult, _fingerprint, _timestamp
from engine.learning import LearnedModel
from engine.schemas import ValidationError


def new_category_feedback(ledger, learner):
    recommendations = {item.recommendation_id: item for item in ledger.recommendations}
    executions = {item.execution_id: item for item in ledger.executions}
    for item in (*ledger.responses, *ledger.executions, *ledger.results):
        identifier = executions[item.execution_id].recommendation_id if isinstance(item, TaskResult) else item.recommendation_id
        rec = recommendations[identifier]
        if rec.task.task_type in learner.plan.task_types and _timestamp(item.timestamp) > _timestamp(learner.plan.cutoff):
            yield item, rec


def _routine_binding(review, rec, authorization):
    from .models import DeliveryBinding
    if authorization is None or authorization.review_id != review.pk or authorization.data.get("target") != "live":
        raise ValidationError("Routine feedback needs the exact separately approved pilot, not a review or another pilot's task.")
    reviewed = {item["recommendation_id"] for item in review.data["report"]["observations"]}
    if rec.recommendation_id in reviewed or _timestamp(rec.task.timestamp) <= _timestamp(review.data["report"]["observed_through"]):
        raise ValidationError("Previously reviewed tasks do not qualify for routine progress.")
    scope = authorization.data["scope"]
    if rec.task.task_type not in scope["task_types"] or rec.task.developer_id not in scope["developer_ids"] or set(rec.task.risk_tags) != {"low"}:
        raise ValidationError("Routine feedback is outside this pilot's exact approved task/developer scope.")
    # Resolve service-owned bindings, never a feedback caller's task/model label.
    from .tasks import task_ledger
    bindings = [binding for binding in DeliveryBinding.objects.filter(runtime__authorization=authorization,
        connector_task__task__repository_ref=scope["repository_ref"]).select_related("connector_task__task__company", "runtime__authorization", "gateway__company")
        if task_ledger(binding.connector_task.task).recommendations[0].recommendation_id == rec.recommendation_id]
    if len(bindings) != 1:
        raise ValidationError("Routine feedback needs one exact owned delivery binding from this pilot.")
    binding = bindings[0]
    from .selection import _state
    selected = _state(binding.runtime)
    row = selected["decisions"].get(binding.selection_id)
    if row is None or row["override"] or binding.selection_id not in selected["claims"] or binding.selection_id not in selected["settlements"]:
        raise ValidationError("Unclaimed/unsettled/overridden delivery does not qualify for routine progress.")
    return binding


def _healthy_delivery(binding, at):
    from .delivery import state
    from .connectors import task_state
    from .tool_observations import state as tool_state
    from engine.delivery_contract import delivery_envelope
    captured = state(binding)
    earlier = state(binding, until=at)
    link = binding.connector_task
    if link.closed_at is None or link.closed_at > at or not earlier["closed"] or captured["unknown_attempts"] or not earlier["attempts"]:
        raise ValidationError("Routine feedback requires explicit owner close and complete delivery evidence before reporting.")
    observed = task_state(link)
    if observed["gap_count"] or observed["multiple_models"] or any(
        (row.payload.get("http_status") or 0) >= 400 or row.payload.get("retry") is True
        or row.payload.get("model") not in (None, binding.data["envelope"]["model_id"]) for row in link.observations.all()):
        raise ValidationError("Connector gaps/errors/retries/model mismatches still require review.")
    tools = tool_state(binding)
    if tools["continuation_blocked"] or tools["negative_signals"]:
        raise ValidationError("Retained tool failures/unknowns still block new tasks; routine feedback cannot widen bound-task repair.")
    if captured["historical_task_overrun"] or captured["historical_attempt_overrun"] or any(event["action"] == "correct_cost" for event in binding.journal):
        raise ValidationError("Corrected billing or retained overruns require review, not a routine-feedback exception.")
    envelope = delivery_envelope(binding.data["envelope"])
    primary = False
    for event in binding.journal:
        if event["action"] == "settle" and event["payload"]["outcome"] != "completed":
            raise ValidationError("Retained failed/retried/unknown provider history still requires review.")
    for row in earlier["attempts"].values():
        request = earlier["requests"][row["request_id"]]
        primary = primary or request["kind"] == "primary"
        if (row["outcome"] != "completed" or row["cost_usd"] is None or row["usage"] is None
            or row["actual_model"] != envelope.provider_model or Decimal(row["cost_usd"]) != envelope.cost(row["usage"])
            or row["usage"]["input_tokens"] > envelope.input_token_ceiling or row["usage"]["output_tokens"] > request["output_limit"]):
            raise ValidationError("Routine feedback requires complete matching primary and auxiliary usage/cost/model evidence.")
    if not primary or earlier["unknown_attempts"]:
        raise ValidationError("No complete primary delivery exists for routine feedback.")
    return captured


def _routine_progress(review, ledger, item, rec, authorization):
    binding = _routine_binding(review, rec, authorization)
    captured = _healthy_delivery(binding, _timestamp(item.timestamp))
    reports = [row for row in ledger.executions if row.recommendation_id == rec.recommendation_id]
    results = [row for row in ledger.results if any(row.execution_id == report.execution_id for report in reports)]
    if len(reports) != 1 or reports[0].actual_model != binding.data["envelope"]["model_id"] or len(results) > 1:
        raise ValidationError("Wrong/missing model reports or result revisions require review.")
    if isinstance(item, TaskResult):
        if (item.supersedes is not None or results != [item] or item.desired_result is not True or item.tests_passed is False
            or item.cost_usd is not None and item.cost_usd != Decimal(captured["known_cost_usd"])):
            raise ValidationError("Only a first positive human result with matching accounting is routine; negatives/unknowns/corrections require review.")
        _healthy_delivery(binding, _timestamp(reports[0].timestamp))
    return str(binding.reference)


def feedback_classification(review, ledger, learner, authorization=None):
    """Readable exact-record classification, never outcome verification or a permission."""
    reviewed = {item["recommendation_id"] for item in review.data["report"]["observations"]}
    observed_through = _timestamp(review.data["report"]["observed_through"])
    rows = []
    for item, rec in new_category_feedback(ledger, learner):
        kind = "response" if isinstance(item, Response) else "execution" if isinstance(item, Execution) else "result"
        record_id = rec.recommendation_id if kind == "response" else getattr(item, kind + "_id")
        actor = item.reviewer_id if kind == "result" else item.developer_id
        status, reason, binding_ref = "review_required", "New category feedback requires explicit review before execution.", None
        if (isinstance(item, Response) and item.response == "accept" and rec.recommendation_id not in reviewed
            and _timestamp(rec.task.timestamp) > observed_through and _timestamp(item.timestamp) >= _timestamp(rec.task.timestamp)):
            status, reason = "routine_pending_learning", "Timely per-task acceptance is preference, not outcome truth or pilot approval."
        elif isinstance(item, (Execution, TaskResult)):
            try:
                binding_ref = _routine_progress(review, ledger, item, rec, authorization)
            except ValidationError as error:
                reason = str(error)
            else:
                status, reason = "routine_pending_learning", "Exact closed healthy bound-task report; retained for explicit learning review, not verified success."
        rows.append({"record_kind": kind, "record_id": record_id, "record_sha256": _fingerprint(item.to_dict()),
            "recommendation_id": rec.recommendation_id, "task_id": rec.task.task_id, "developer_id": actor,
            "historical_role": ledger.record_role(kind, record_id, actor), "timestamp": item.timestamp,
            "status": status, "reason": reason, "binding_ref": binding_ref, "outcome_verified": False})
    rows.sort(key=lambda row: (row["historical_role"] != "senior", row["developer_id"], row["timestamp"], row["record_id"]))
    return rows


def verify_for_execution(review, ledger, learner, authorization=None):
    # This reconstructs/checks only the original validation view and plan. It
    # cannot fit new data, replace the saved learner/hash or grant pilot authority.
    learner.verify_fitted_source(ledger)
    if any(row["status"] != "routine_pending_learning" for row in feedback_classification(review, ledger, learner, authorization)):
        raise ValidationError("New category feedback outside timely acceptance or exact healthy bound-task routine progress requires review before execution.")
    learner.verify_negative_evidence(ledger)


def pending_review(authorization, ledger):
    """Expose incoming history under existing reviewer access; never mutate it."""
    review = authorization.review
    learner = LearnedModel.from_dict(review.data["learner"])
    rows = feedback_classification(review, ledger, learner, authorization)
    from .models import CompanyTask
    from .tasks import task_ledger
    tasks, task_refs = {}, {}
    for task in CompanyTask.objects.filter(company=authorization.company, source_kind=learner.plan.source_kind).select_related("company"):
        local = task_ledger(task)
        rec = local.recommendations[0]
        task_refs[rec.recommendation_id] = str(task.reference)
        if rec.task.task_type in learner.plan.task_types and _timestamp(rec.task.timestamp) > _timestamp(review.data["report"]["observed_through"]):
            tasks[rec.recommendation_id] = (task, local)
    for row in rows:
        row["task_ref"] = task_refs.get(row["recommendation_id"])
    waiting = [{"task_ref": str(task.reference), "task_id": task.task_id, "developer_id": rec.task.developer_id,
        "historical_role": local.record_role("recommendation", rec.recommendation_id, rec.task.developer_id),
        "state": "awaiting_actual_model" if not local.executions else "awaiting_human_result", "outcome_verified": False}
        for task, local in tasks.values() for rec in local.recommendations if not local.executions or not local.results]
    waiting.sort(key=lambda row: (row["historical_role"] != "senior", row["developer_id"], row["task_id"]))
    return {"rule_version": "routine_bound_feedback_v1", "records": rows, "waiting_tasks": waiting,
        "routine_records": sum(row["status"] == "routine_pending_learning" for row in rows),
        "review_required_records": sum(row["status"] == "review_required" for row in rows),
        "learner_changed": False, "execution_permission": False, "automatic_resume": False}


def learning_freshness(review, ledger):
    """Display-only status for subsequent learning, never an execution veto or permission."""
    learner = LearnedModel.from_dict(review.data["learner"])
    changes = list(new_category_feedback(ledger, learner))
    try:
        learner.verify_source(ledger)
    except ValidationError as error:
        status, reason = "needs_review", str(error)
    else:
        status, reason = "current", "The fixed-cutoff learning artifact still matches its fitting source."
    return {"status": status, "reason": reason, "reviewed_learner_sha256": learner.sha256,
            "new_feedback_records": len(changes), "execution_permission": False,
            "note": "New feedback is retained for the next explicit learning/review. Freshness alone does not pause an otherwise safe approved pilot."}
