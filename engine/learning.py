"""Experimental count-based feedback learning; suggestions only, never routing approval."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .exporters import _write_private
from .feedback import FeedbackLedger, TaskRequest, TaskResult, _fingerprint, _policy_input, _timestamp, feedback_summary
from .history import PolicySnapshot
from .importers import parse_json
from .policy import fallback, incompatibility
from .privacy import ensure_safe
from .schemas import Policy, PolicyDecision, ValidationError, boolean, choice, integer, object_fields, strings, text


EVIDENCE_FIELDS = (
    "task_type", "model", "suggestions", "accepts", "rejects", "senior_accepts", "senior_rejects",
    "unanswered_suggestions", "accepted_without_execution", "accepted_but_different_model",
    "executions", "confirmed_successes", "confirmed_failures", "unknown_results", "senior_adopted_successes",
    "senior_success_sessions", "non_senior_failures", "incompatible_executions", "status", "reasons",
)


@dataclass(frozen=True)
class LearningPlan:
    learner_version: str
    source_kind: str
    dataset_split: str
    cutoff: str
    session_ids: Tuple[str, ...]
    task_types: Tuple[str, ...]
    min_senior_successes: int
    min_senior_sessions: int

    @classmethod
    def from_dict(cls, value: Any) -> "LearningPlan":
        fields = ("learner_version", "source_kind", "dataset_split", "cutoff", "session_ids", "task_types",
                  "min_senior_successes", "min_senior_sessions")
        data = object_fields(value, fields, fields)
        if data["source_kind"] not in ("synthetic", "team"):
            raise ValidationError("Learning source_kind must be synthetic or team; provenance is caller-declared.")
        if data["dataset_split"] != "validation":
            raise ValidationError("This experimental fitting command accepts validation data only, never held-out test data.")
        _timestamp(data["cutoff"])
        sessions = strings(data["session_ids"], "session_ids")
        categories = strings(data["task_types"], "task_types")
        if not sessions or not categories or "*" in categories:
            raise ValidationError("Predeclare explicit nonempty learning sessions and task categories, without wildcards.")
        minimum = integer(data["min_senior_successes"], "min_senior_successes")
        minimum_sessions = integer(data["min_senior_sessions"], "min_senior_sessions")
        if minimum == 0 or minimum_sessions == 0:
            raise ValidationError("Declare positive senior-success/session evidence requirements.")
        return cls(text(data["learner_version"], "learner_version"), data["source_kind"], data["dataset_split"],
                   data["cutoff"], sessions, categories, minimum, minimum_sessions)

    def to_dict(self) -> Dict[str, Any]:
        return {"learner_version": self.learner_version, "source_kind": self.source_kind,
                "dataset_split": self.dataset_split, "cutoff": self.cutoff,
                "session_ids": list(self.session_ids), "task_types": list(self.task_types),
                "min_senior_successes": self.min_senior_successes, "min_senior_sessions": self.min_senior_sessions}


def _view(ledger: FeedbackLedger, plan: LearningPlan) -> FeedbackLedger:
    cutoff = _timestamp(plan.cutoff)
    recommendations = tuple(rec for rec in ledger.recommendations
                            if rec.task.session_id in plan.session_ids and rec.task.task_type in plan.task_types
                            and _timestamp(rec.task.timestamp) <= cutoff)
    identifiers = {rec.recommendation_id for rec in recommendations}
    responses = tuple(item for item in ledger.responses
                      if item.recommendation_id in identifiers and _timestamp(item.timestamp) <= cutoff)
    executions = tuple(item for item in ledger.executions
                       if item.recommendation_id in identifiers and _timestamp(item.timestamp) <= cutoff)
    execution_ids = {item.execution_id for item in executions}
    results = tuple(item for item in ledger.results
                    if item.execution_id in execution_ids and _timestamp(item.timestamp) <= cutoff)
    used_policies = {rec.policy_sha256 for rec in recommendations}
    attributions = None
    if ledger.role_attributions is not None:
        kept = {("recommendation", item.recommendation_id) for item in recommendations}
        kept.update(("response", item.recommendation_id) for item in responses)
        kept.update(("execution", item.execution_id) for item in executions)
        kept.update(("result", item.result_id) for item in results)
        attributions = tuple(item for item in ledger.role_attributions if (item.record_kind, item.record_id) in kept)
    subset = FeedbackLedger(ledger.team, tuple(item for item in ledger.policies if item.sha256 in used_policies),
                             recommendations, responses, executions, results, attributions)
    return FeedbackLedger.from_dict(subset.to_dict())


def _source_digest(ledger: FeedbackLedger) -> str:
    data = ledger.to_dict()
    data["team"]["members"].sort(key=lambda item: item["developer_id"])
    for collection, key in (("policies", "sha256"), ("recommendations", "recommendation_id"),
                            ("responses", "recommendation_id"), ("executions", "execution_id")):
        data[collection].sort(key=lambda item: item[key])
    data["results"].sort(key=lambda item: (item["execution_id"], _timestamp(item["timestamp"]), item["result_id"]))
    if "role_attributions" in data:
        data["role_attributions"].sort(key=lambda item: (item["record_kind"], item["record_id"]))
    return _fingerprint(data)


def _rules(evidence: List[Dict[str, Any]], plan: LearningPlan) -> List[Dict[str, Any]]:
    rules = []
    for category in plan.task_types:
        evaluated = []
        for group in evidence:
            if group["task_type"] != category:
                continue
            reasons = []
            if group["confirmed_failures"]:
                reasons.append("Recorded task failures, including non-senior outcomes, veto this candidate.")
            if group["rejects"]:
                reasons.append("Recorded rejections require investigation before learning this suggestion.")
            if group["incompatible_executions"]:
                reasons.append("Some recorded executions are not currently compatible/approved.")
            if group["unknown_results"]:
                reasons.append("Executed tasks with unknown desired results cannot justify a learned suggestion.")
            if group["senior_adopted_successes"] < plan.min_senior_successes:
                reasons.append("Too few accepted/used/senior-confirmed successes for the declared learning plan.")
            if group["senior_success_sessions"] < plan.min_senior_sessions:
                reasons.append("Too few supporting senior sessions for the declared learning plan.")
            evaluated.append({"model": group["model"], "eligible": not reasons, "reasons": reasons})
        candidates = [item for item in evaluated if item["eligible"]]
        statistics = {item["model"]: item for item in evidence if item["task_type"] == category}
        candidates.sort(key=lambda item: (-statistics[item["model"]]["senior_adopted_successes"],
                                           -statistics[item["model"]]["senior_success_sessions"],
                                           -statistics[item["model"]]["confirmed_successes"], item["model"]))
        chosen = candidates[0]["model"] if candidates else None
        rules.append({"task_type": category, "recommended_model": chosen,
                      "status": "manual_suggestion_only" if chosen else "withheld",
                      "candidates": evaluated})
    return rules


@dataclass(frozen=True)
class LearnedModel:
    plan: LearningPlan
    policy: PolicySnapshot
    source_sha256: str
    roster_sha256: str
    counts: Dict[str, int]
    evidence: Tuple[Dict[str, Any], ...]

    def payload(self) -> Dict[str, Any]:
        return {"schema_version": 1, "record_type": "experimental_feedback_learner",
                "algorithm": "senior_count_baseline_v1", "plan": self.plan.to_dict(),
                "policy": self.policy.to_dict(), "source_sha256": self.source_sha256,
                "roster_sha256": self.roster_sha256, "training_counts": self.counts,
                "evidence": list(self.evidence), "rules": _rules(list(self.evidence), self.plan),
                "roles_source": "declared_local_roster_unverified", "outcomes_source": "declared_local_confirmation_unverified",
                "confidence": "low", "deployment_authorized": False}

    @property
    def sha256(self) -> str:
        return _fingerprint(self.payload())

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.payload(), learner_sha256=self.sha256)

    @classmethod
    def from_dict(cls, value: Any) -> "LearnedModel":
        fields = ("schema_version", "record_type", "algorithm", "plan", "policy", "source_sha256", "roster_sha256",
                  "training_counts", "evidence", "rules", "roles_source", "outcomes_source", "confidence",
                  "deployment_authorized", "learner_sha256")
        data = object_fields(value, fields, fields)
        ensure_safe(data)
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValidationError("Unsupported learned-model schema version.")
        plan = LearningPlan.from_dict(data["plan"])
        policy = PolicySnapshot.from_dict(data["policy"])
        for field in ("source_sha256", "roster_sha256", "learner_sha256"):
            if not isinstance(data[field], str) or not re.fullmatch(r"[a-f0-9]{64}", data[field]):
                raise ValidationError("Learning references must be SHA-256 fingerprints.")
        count_fields = ("recommendations", "responses", "executions", "current_results", "result_revisions",
                        "pending_executions", "pending_results", "model_overrides")
        counts = object_fields(data["training_counts"], count_fields, count_fields)
        for field in count_fields:
            integer(counts[field], field)
        if counts["responses"] > counts["recommendations"] or counts["executions"] + counts["pending_executions"] != counts["recommendations"]:
            raise ValidationError("Learning recommendation/response/execution coverage counts disagree.")
        if counts["current_results"] > counts["executions"] or counts["result_revisions"] < counts["current_results"]:
            raise ValidationError("Learning result counts exceed executions or omit revision history.")
        if boolean(data["deployment_authorized"], "deployment_authorized"):
            raise ValidationError("A learned recommendation model cannot authorize deployment.")
        if not isinstance(data["evidence"], list):
            raise ValidationError("Learning evidence must be an array.")
        identities = set()
        for item in data["evidence"]:
            group = object_fields(item, EVIDENCE_FIELDS, EVIDENCE_FIELDS)
            if group["task_type"] not in plan.task_types:
                raise ValidationError("Learning evidence is outside the predeclared category scope.")
            identity = (group["task_type"], text(group["model"], "model"))
            if identity in identities:
                raise ValidationError("Learning evidence has duplicate category/model groups.")
            identities.add(identity)
            for field in EVIDENCE_FIELDS[2:-2]:
                integer(group[field], field)
            strings(group["reasons"], "reasons")
            choice(group["status"], "status", ("candidate_for_manual_review", "collect_more_evidence", "investigate_failures"))
            if group["senior_adopted_successes"] > group["confirmed_successes"] or group["confirmed_successes"] > group["executions"]:
                raise ValidationError("Learning success counts cannot exceed actually recorded executions.")
            if group["senior_success_sessions"] > group["senior_adopted_successes"]:
                raise ValidationError("Supporting sessions cannot exceed successful senior task examples.")
            if group["confirmed_successes"] + group["confirmed_failures"] + group["unknown_results"] != group["executions"]:
                raise ValidationError("Learning outcomes do not account for every execution.")
            if group["accepts"] + group["rejects"] + group["unanswered_suggestions"] != group["suggestions"]:
                raise ValidationError("Learning responses do not account for every suggestion.")
            if group["senior_accepts"] > group["accepts"] or group["senior_rejects"] > group["rejects"]:
                raise ValidationError("Senior response counts exceed total responses.")
            if group["non_senior_failures"] > group["confirmed_failures"] or group["incompatible_executions"] > group["executions"]:
                raise ValidationError("Learning failure/compatibility counts disagree with recorded executions.")
        model = cls(plan, policy, data["source_sha256"], data["roster_sha256"], dict(counts), tuple(data["evidence"]))
        if model.to_dict() != data:
            raise ValidationError("Learned-model rules or content fingerprint disagree; refit from valid evidence.")
        for rule in _rules(list(model.evidence), model.plan):
            selected = policy.policy.model(rule["recommended_model"]) if rule["recommended_model"] else None
            if selected is not None and not selected.approved:
                raise ValidationError("Learned suggestions cannot approve a disabled/candidate model.")
            if rule["recommended_model"] and selected is None:
                raise ValidationError("Learned suggestion is outside the saved model registry.")
        return model

    def export(self, path: Path) -> None:
        validated = LearnedModel.from_dict(self.to_dict())
        _write_private(json.dumps(validated.to_dict(), indent=2, ensure_ascii=False) + "\n", path)

    def verify_fitted_source(self, ledger: FeedbackLedger) -> None:
        """Check the exact fixed-cutoff fit, without deciding whether new feedback may execute."""
        ledger = FeedbackLedger.from_dict(ledger.to_dict())
        if _fingerprint(ledger.team.to_dict()) != self.roster_sha256 or _source_digest(_view(ledger, self.plan)) != self.source_sha256:
            raise ValidationError("Learner source/roster no longer matches this feedback store; refit explicitly.")
        expected = fit_feedback(ledger, self.policy.policy, self.plan)
        if self.to_dict() != expected.to_dict():
            raise ValidationError("Learner evidence does not match its actual source records; refit rather than editing counts.")

    def verify_source(self, ledger: FeedbackLedger) -> None:
        # Future learning/publication retains the original strict freshness rule.
        self.verify_fitted_source(ledger)
        recommendations = {item.recommendation_id: item for item in ledger.recommendations}
        executions = {item.execution_id: item for item in ledger.executions}
        cutoff = _timestamp(self.plan.cutoff)
        for item in (*ledger.responses, *ledger.executions, *ledger.results):
            recommendation_id = (executions[item.execution_id].recommendation_id if isinstance(item, TaskResult)
                                 else item.recommendation_id)
            rec = recommendations[recommendation_id]
            if rec.task.task_type in self.plan.task_types and _timestamp(item.timestamp) > cutoff:
                raise ValidationError("New category feedback/results arrived after fitting; refit before making another learned suggestion.")
        self.verify_negative_evidence(ledger)

    def verify_negative_evidence(self, ledger: FeedbackLedger) -> None:
        # A chosen fitting subset must not hide known negative feedback elsewhere in the same store.
        full_evidence = feedback_summary(ledger, self.policy.policy)["groups"]
        for rule in _rules(list(self.evidence), self.plan):
            selected = rule["recommended_model"]
            group = next((item for item in full_evidence
                          if (item["task_type"], item["model"]) == (rule["task_type"], selected)), None)
            if group and (group["confirmed_failures"] or group["rejects"]):
                raise ValidationError(
                    f"Known category feedback blocks this learner: failures={group['confirmed_failures']}, "
                    f"rejects={group['rejects']}. A fitting subset cannot discard those signals."
                )


def fit_feedback(ledger: FeedbackLedger, policy: Policy, plan: LearningPlan) -> LearnedModel:
    ledger = FeedbackLedger.from_dict(ledger.to_dict())
    plan = LearningPlan.from_dict(plan.to_dict())
    policy_snapshot = PolicySnapshot.create(policy)
    present_sessions = {item.task.session_id for item in ledger.recommendations}
    if set(plan.session_ids) - present_sessions:
        raise ValidationError("A declared learning session is absent from the feedback store.")
    view = _view(ledger, plan)
    for session_id in plan.session_ids:
        if not any(rec.task.session_id == session_id for rec in view.recommendations):
            raise ValidationError("A declared learning session has no category records at/before the cutoff.")
    summary = feedback_summary(view, policy_snapshot.policy)
    fields = ("recommendations", "responses", "executions", "current_results", "result_revisions",
              "pending_executions", "pending_results", "model_overrides")
    model = LearnedModel(plan, policy_snapshot, _source_digest(view), _fingerprint(ledger.team.to_dict()),
                         {field: summary[field] for field in fields}, tuple(summary["groups"]))
    return LearnedModel.from_dict(model.to_dict())


def learned_decision(task: TaskRequest, policy: Policy, model: LearnedModel) -> PolicyDecision:
    task = TaskRequest.from_dict(task.to_dict())
    model = LearnedModel.from_dict(model.to_dict())
    context = _policy_input(task, policy)
    if policy.fingerprint() != model.policy.sha256:
        return fallback(policy, context, "shadow", "Learner was fitted against different policy content; refit before relying on it.")
    if _timestamp(task.timestamp) <= _timestamp(model.plan.cutoff) or task.session_id in model.plan.session_ids:
        raise ValidationError("Learned suggestions require a future task in a session not used for fitting; do not report in-sample predictions as evaluation.")
    if set(task.risk_tags) != {"low"} or task.task_type not in model.plan.task_types:
        return fallback(policy, context, "shadow", "Task risk/category is outside the learned suggestion scope; retain the safe default recommendation.")
    rule = next(rule for rule in _rules(list(model.evidence), model.plan) if rule["task_type"] == task.task_type)
    if rule["recommended_model"] is None:
        return fallback(policy, context, "shadow", "Feedback learner withheld this category because of failures, rejects, gaps, or insufficient declared evidence.")
    candidate = policy.model(rule["recommended_model"])
    issue = incompatibility(candidate, context)
    if issue:
        return fallback(policy, context, "shadow", "Learned model is not compatible with this task. " + issue)
    evidence = next(item for item in model.evidence if (item["task_type"], item["model"]) == (task.task_type, candidate.model_id))
    reason = (f"Experimental feedback baseline: {evidence['senior_adopted_successes']} accepted/used/senior-confirmed successes "
              f"across {evidence['senior_success_sessions']} sessions meet the caller's validation plan. "
              "Manual suggestion only; not validated production confidence or pilot approval.")
    return PolicyDecision(policy.policy_version, candidate.model_id, candidate.tier, "low", reason,
                          policy.default_model, "shadow", task.selected_model, False,
                          ("learner:" + model.sha256, "feedback-source:" + model.source_sha256))


def load_learner(path: Path) -> LearnedModel:
    ensure_safe(str(path))
    return LearnedModel.from_dict(parse_json(path.read_text(encoding="utf-8")))
