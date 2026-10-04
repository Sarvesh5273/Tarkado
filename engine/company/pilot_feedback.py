"""Fixed reviewed evidence, incoming learning feedback, and current execution checks are distinct."""

from engine.feedback import Response, TaskResult, _timestamp
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


def verify_for_execution(review, ledger, learner):
    # This reconstructs/checks only the original validation view and plan. It
    # cannot fit new data, replace the saved learner/hash or grant pilot authority.
    learner.verify_fitted_source(ledger)
    reviewed = {item["recommendation_id"] for item in review.data["report"]["observations"]}
    observed_through = _timestamp(review.data["report"]["observed_through"])
    for item, rec in new_category_feedback(ledger, learner):
        # Only timely preference on a genuinely new recommendation is benign.
        # Earlier reviewed tasks, rejects, executions and result revisions get
        # no exception, even when they concern the currently running task.
        if (isinstance(item, Response) and item.response == "accept" and rec.recommendation_id not in reviewed
            and _timestamp(rec.task.timestamp) > observed_through and _timestamp(item.timestamp) >= _timestamp(rec.task.timestamp)):
            continue
        raise ValidationError("New category feedback other than timely acceptance on a new task requires another review before execution.")
    learner.verify_negative_evidence(ledger)


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
