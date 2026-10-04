"""Conservative, offline candidate evaluation without approval or API calls."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .importers import validate_dataset
from .policy import capability_issue, incompatibility
from .replay import Metrics, decimal_text, replay
from .schemas import (
    MODEL_STATES, Policy, TaskTrace, ValidationError, choice, integer,
    object_fields, strings, text,
)
from .uncertainty import UncertaintySettings, summarize_uncertainty


@dataclass(frozen=True)
class EvaluationPlan:
    source: str
    source_kind: str
    dataset_split: str
    task_types: Tuple[str, ...]
    min_tasks: int
    min_samples_per_task: int
    uncertainty: UncertaintySettings = UncertaintySettings()

    @classmethod
    def from_dict(cls, value: Any) -> "EvaluationPlan":
        fields = ("source", "source_kind", "dataset_split", "task_types", "min_tasks", "min_samples_per_task")
        data = object_fields(value, fields + ("uncertainty",), fields)
        task_types = strings(data["task_types"], "task_types")
        if not task_types or "*" in task_types:
            raise ValidationError("Evaluation scope must name explicit task types, not a wildcard.")
        minimum = integer(data["min_tasks"], "min_tasks")
        samples = integer(data["min_samples_per_task"], "min_samples_per_task")
        if minimum == 0 or samples == 0:
            raise ValidationError("Evaluation minimum counts must be positive.")
        return cls(
            text(data["source"], "source"),
            choice(data["source_kind"], "source_kind", ("synthetic", "public_benchmark", "team")),
            choice(data["dataset_split"], "dataset_split", ("validation", "test")),
            task_types, minimum, samples,
            UncertaintySettings.from_dict(data["uncertainty"]) if "uncertainty" in data else UncertaintySettings(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source, "source_kind": self.source_kind,
            "dataset_split": self.dataset_split, "task_types": list(self.task_types),
            "min_tasks": self.min_tasks, "min_samples_per_task": self.min_samples_per_task,
            "uncertainty": self.uncertainty.to_dict(),
        }


@dataclass(frozen=True)
class EvaluationRow:
    task_id: str
    sample_id: str
    recorded: TaskTrace
    baseline: Optional[TaskTrace]
    candidate: Optional[TaskTrace]
    baseline_reason: str
    compatibility_failure: Optional[str]
    baseline_failure: Optional[str]

    @property
    def paired(self) -> bool:
        return (self.baseline is not None and self.candidate is not None
                and self.compatibility_failure is None and self.baseline_failure is None)

    @property
    def score_change(self) -> Optional[Decimal]:
        if not self.paired or self.baseline.outcome.score is None or self.candidate.outcome.score is None:
            return None
        return self.candidate.outcome.score - self.baseline.outcome.score

    @property
    def known_quality(self) -> bool:
        return (self.paired and self.baseline.outcome.tests_passed is not None
                and self.candidate.outcome.tests_passed is not None and self.score_change is not None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id, "sample_id": self.sample_id,
            "recorded_model": self.recorded.selected_model,
            "baseline_model": self.baseline.selected_model if self.baseline else None,
            "candidate_model": self.candidate.selected_model if self.candidate else None,
            "paired": self.paired, "known_quality": self.known_quality,
            "baseline_reason": self.baseline_reason,
            "compatibility_failure": self.compatibility_failure,
            "baseline_failure": self.baseline_failure,
            "missing_candidate_outcome": self.candidate is None,
            "score_change": decimal_text(self.score_change),
            "baseline_tests_passed": self.baseline.outcome.tests_passed if self.baseline else None,
            "candidate_tests_passed": self.candidate.outcome.tests_passed if self.candidate else None,
            "baseline_developer_override": self.baseline.outcome.developer_override if self.baseline else None,
            "candidate_developer_override": self.candidate.outcome.developer_override if self.candidate else None,
            "baseline_score": decimal_text(self.baseline.outcome.score) if self.baseline else None,
            "candidate_score": decimal_text(self.candidate.outcome.score) if self.candidate else None,
            "baseline_cost_usd": str(self.baseline.cost_usd) if self.baseline else None,
            "candidate_cost_usd": str(self.candidate.cost_usd) if self.candidate else None,
        }


@dataclass(frozen=True)
class RolloutReport:
    policy_version: str
    policy_sha256: str
    candidate_model: str
    candidate_status: str
    plan: EvaluationPlan
    total_tasks: int
    excluded_tasks: int
    rows: Tuple[EvaluationRow, ...]
    recommendation: str
    reasons: Tuple[str, ...]

    def __post_init__(self) -> None:
        text(self.policy_version, "policy_version")
        text(self.policy_sha256, "policy_sha256")
        text(self.candidate_model, "candidate_model")
        choice(self.candidate_status, "candidate_status", MODEL_STATES)
        choice(self.recommendation, "recommendation", ("shadow", "collect_more_evidence", "reject"))
        integer(self.total_tasks, "total_tasks")
        integer(self.excluded_tasks, "excluded_tasks")
        EvaluationPlan.from_dict(self.plan.to_dict())
        strings(list(self.reasons), "reasons")
        if not self.reasons:
            raise ValidationError("Rollout reports require explanatory reasons.")
        pairs = [(row.task_id, row.sample_id) for row in self.rows]
        if len(set(pairs)) != len(pairs):
            raise ValidationError("Report task/sample pairs must be unique.")
        if self.total_tasks != self.excluded_tasks + len({row.task_id for row in self.rows}):
            raise ValidationError("Report task coverage counts disagree.")
        for row in self.rows:
            if row.recorded.task_id != row.task_id or row.recorded.sample_id != row.sample_id:
                raise ValidationError("Report row and recorded task/sample disagree.")
            for trace in (row.baseline, row.candidate):
                if trace is not None and (trace.task_id, trace.sample_id) != (row.task_id, row.sample_id):
                    raise ValidationError("Report outcomes must refer to the same task/sample.")
            if row.candidate is not None and row.candidate.selected_model != self.candidate_model:
                raise ValidationError("Report candidate model disagrees with an outcome.")
        if self.recommendation == "shadow" and (
            any(not row.known_quality for row in self.rows) or not self.rows
            or self.candidate_status not in ("candidate", "shadow")
        ):
            raise ValidationError("A shadow recommendation requires complete candidate evidence.")
        if self.recommendation == "shadow":
            task_ids = {row.task_id for row in self.rows}
            if set(self.plan.task_types) - {row.recorded.task_type for row in self.rows}:
                raise ValidationError("A shadow recommendation must cover every requested task type.")
            if len(task_ids) < self.plan.min_tasks or any(
                sum(row.task_id == task_id for row in self.rows) < self.plan.min_samples_per_task
                for task_id in task_ids
            ):
                raise ValidationError("A shadow recommendation must meet the predeclared sample gates.")
            if any(row.score_change < 0 or row.candidate.outcome.tests_passed is False for row in self.rows):
                raise ValidationError("A shadow recommendation cannot hide a failed test or score regression.")
            if any(row.candidate.outcome.developer_override and not row.baseline.outcome.developer_override
                   for row in self.rows):
                raise ValidationError("A shadow recommendation cannot hide a new developer override.")

    def to_dict(self) -> Dict[str, Any]:
        paired = [row for row in self.rows if row.paired]
        baseline = Metrics.from_traces([row.baseline for row in paired])
        candidate = Metrics.from_traces([row.candidate for row in paired])
        changes = [row.score_change for row in paired if row.score_change is not None]
        task_stats = []
        for task_id in sorted({row.task_id for row in self.rows}):
            task_rows = [row for row in self.rows if row.task_id == task_id]
            values = [row.score_change for row in task_rows if row.score_change is not None]
            known = [row for row in task_rows if row.known_quality]
            failures = [row.candidate.outcome.tests_passed is False for row in task_rows if row.paired]
            task_stats.append({
                "task_id": task_id, "samples": len(task_rows),
                "paired_samples": sum(row.paired for row in task_rows),
                "known_quality_samples": len(known),
                "score_pairs": len(values),
                "mean_score_change": decimal_text(sum(values, Decimal(0)) / len(values)) if values else None,
                "min_score_change": decimal_text(min(values)) if values else None,
                "max_score_change": decimal_text(max(values)) if values else None,
                "candidate_test_failures": sum(failures),
                "candidate_test_unknown": sum(row.candidate.outcome.tests_passed is None for row in task_rows if row.paired),
                "meets_sample_minimum": len(known) >= self.plan.min_samples_per_task,
            })
        known_test_pairs = [row for row in paired if row.baseline.outcome.tests_passed is not None
                            and row.candidate.outcome.tests_passed is not None]
        baseline_known_tests = baseline.tests_passed + baseline.tests_failed
        candidate_known_tests = candidate.tests_passed + candidate.tests_failed
        return {
            "policy_version": self.policy_version,
            "policy_sha256": self.policy_sha256,
            "candidate_model": self.candidate_model, "candidate_status": self.candidate_status,
            "evaluation_plan": self.plan.to_dict(),
            "recommendation": self.recommendation, "reasons": list(self.reasons),
            "deployment_authorized": False,
            "total_tasks": self.total_tasks, "excluded_tasks": self.excluded_tasks,
            "scope_tasks": len(task_stats), "evaluation_samples": len(self.rows),
            "task_type_coverage": [
                {
                    "task_type": task_type,
                    "distinct_tasks": len({row.task_id for row in self.rows if row.recorded.task_type == task_type}),
                    "known_quality_samples": sum(row.known_quality for row in self.rows
                                                 if row.recorded.task_type == task_type),
                }
                for task_type in self.plan.task_types
            ],
            "paired_samples": len(paired), "unpaired_samples": len(self.rows) - len(paired),
            "missing_candidate_outcomes": sum(row.candidate is None for row in self.rows),
            "compatibility_failures": sum(row.compatibility_failure is not None for row in self.rows),
            "baseline_failures": sum(row.baseline_failure is not None for row in self.rows),
            "observed_candidate_test_failures": sum(row.candidate is not None
                                                    and row.candidate.outcome.tests_passed is False for row in self.rows),
            "recorded_no_change": Metrics.from_traces([row.recorded for row in paired]).to_dict(),
            "baseline": baseline.to_dict(), "candidate": candidate.to_dict(),
            "baseline_models": sorted({row.baseline.selected_model for row in paired}),
            "cost_reduction_usd": str(baseline.cost_usd - candidate.cost_usd) if paired else None,
            "total_latency_change_ms": candidate.total_latency_ms - baseline.total_latency_ms if paired else None,
            "known_test_pairs": len(known_test_pairs),
            "baseline_test_failure_rate": decimal_text(Decimal(baseline.tests_failed) / baseline_known_tests)
            if baseline_known_tests else None,
            "candidate_test_failure_rate": decimal_text(Decimal(candidate.tests_failed) / candidate_known_tests)
            if candidate_known_tests else None,
            "developer_override_change": candidate.developer_overrides - baseline.developer_overrides,
            "override_regressions": sum(row.candidate.outcome.developer_override
                                        and not row.baseline.outcome.developer_override for row in paired),
            "test_regressions": sum(row.baseline.outcome.tests_passed is True
                                    and row.candidate.outcome.tests_passed is False for row in known_test_pairs),
            "score_pairs": len(changes),
            "score_regressions": sum(value < 0 for value in changes),
            "mean_score_change": decimal_text(sum(changes, Decimal(0)) / len(changes)) if changes else None,
            "task_variation": task_stats,
            "uncertainty": summarize_uncertainty(self.rows, self.plan.uncertainty),
            "notes": [
                "Offline advisory evaluation: no API calls, approval-state changes, or live routing.",
                "Baseline is the current versioned policy; recorded no-change selection is shown separately.",
                "All totals use the same paired samples; missing candidate results are never replaced by fallback outcomes.",
                "Metric task_count counts sampled outcomes; scope_tasks counts distinct engineering tasks.",
                "Sample counts and min/max are descriptive variation, not a statistical safety guarantee.",
                "Minimum counts are predeclared evidence gates, not proof of statistical sufficiency.",
                "Evaluation-plan provenance and dataset split are supplied by the team, not verified.",
                "A shadow recommendation still requires human review; enable is deliberately unsupported.",
                "Synthetic and public-benchmark results do not establish production savings.",
            ],
            "samples": [row.to_dict() for row in self.rows],
        }


def evaluate(traces: List[TaskTrace], policy: Policy, candidate_id: str, plan: EvaluationPlan) -> RolloutReport:
    fingerprint = policy.fingerprint()
    validate_dataset(traces, repeated=True)
    EvaluationPlan.from_dict(plan.to_dict())
    candidate = policy.model(candidate_id)
    if candidate is None:
        raise ValidationError("Candidate must be explicitly registered with declared capabilities.")
    groups = {}
    for trace in traces:
        model = policy.model(trace.selected_model)
        if model is not None and model.tier != trace.model_tier:
            raise ValidationError("A recorded model tier disagrees with the policy registry.")
        groups.setdefault((trace.task_id, trace.sample_id), []).append(trace)

    rows = []
    excluded = set()
    for task_id, sample_id in sorted(groups):
        sample = groups[(task_id, sample_id)]
        recorded = next(trace for trace in sample if trace.is_baseline)
        if recorded.task_type not in plan.task_types:
            excluded.add(task_id)
            continue
        result = replay(sample, policy).rows[0]
        baseline = result.evaluated
        candidate_trace = next((trace for trace in sample if trace.selected_model == candidate_id), None)
        baseline_failure = incompatibility(policy.model(baseline.selected_model), recorded) if baseline else (
            "Current-policy route has no compatible recorded outcome."
        )
        if baseline is not None and baseline.selected_model == candidate_id:
            raise ValidationError("Candidate is already the baseline for a scoped sample; self-comparison is invalid.")
        issue = capability_issue(candidate, recorded)
        if set(recorded.risk_tags) != {"low"}:
            issue = "Candidate evaluation is restricted to explicitly low-risk tasks."
        if candidate.status == "disabled":
            issue = "Candidate model is disabled."
        rows.append(EvaluationRow(task_id, sample_id, recorded, baseline, candidate_trace,
                                  result.decision.reason, issue, baseline_failure))

    report = RolloutReport(policy.policy_version, fingerprint, candidate_id, candidate.status, plan,
                           len({trace.task_id for trace in traces}), len(excluded), tuple(rows),
                           "collect_more_evidence", ("Evaluation is incomplete until evidence gates are checked.",))
    data = report.to_dict()
    reasons = []
    reject = False
    if candidate.status == "disabled":
        reasons.append("Candidate is disabled; it cannot be proposed for rollout.")
        reject = True
    if data["compatibility_failures"]:
        reasons.append("Candidate is incompatible with part of the explicitly requested task scope.")
        reject = True
    if data["test_regressions"] or data["score_regressions"]:
        reasons.append("Candidate has a paired test or score regression; lower cost cannot justify it.")
        reject = True
    if data["observed_candidate_test_failures"]:
        reasons.append("Candidate has recorded test failures in the requested scope.")
        reject = True
    if data["override_regressions"]:
        reasons.append("Candidate introduces a developer override on a paired task/sample.")
        reject = True
    if reject:
        recommendation = "reject"
    else:
        if data["scope_tasks"] < plan.min_tasks:
            reasons.append("Too few distinct scoped tasks for the predeclared evidence gate.")
        if any(item["known_quality_samples"] == 0 for item in data["task_type_coverage"]):
            reasons.append("Some requested task types have no complete recorded quality evidence.")
        if data["unpaired_samples"] or any(not row.known_quality for row in rows):
            reasons.append("Some scoped samples lack compatible paired outcomes or known tests/scores.")
        if any(not stats["meets_sample_minimum"] for stats in data["task_variation"]):
            reasons.append("Some tasks have fewer complete repeated samples than the predeclared minimum.")
        if candidate.status == "approved":
            reasons.append("Model is already approved; this evaluator does not authorize a policy expansion.")
        if reasons:
            recommendation = "collect_more_evidence"
        else:
            recommendation = "shadow"
            reasons.append("Evidence gates pass without observed quality regressions; propose a reviewed shadow test only.")
    if plan.source_kind != "team":
        reasons.append("This is synthetic or public evidence, not a production savings or safety claim.")
    return RolloutReport(policy.policy_version, fingerprint, candidate_id, candidate.status, plan,
                         report.total_tasks, report.excluded_tasks, tuple(rows), recommendation, tuple(reasons))
