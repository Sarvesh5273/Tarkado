"""Replay fixed rules using recorded outcomes, never invented model results."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .importers import validate_dataset
from .policy import decide, fallback
from .schemas import MODES, Policy, PolicyDecision, TaskTrace, ValidationError, choice


METRIC_FIELDS = (
    "task_count", "cost_usd", "total_latency_ms", "mean_latency_ms",
    "input_tokens", "output_tokens", "tests_passed", "tests_failed",
    "tests_unknown", "scored_tasks", "mean_score", "developer_overrides",
)


def decimal_text(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


@dataclass(frozen=True)
class Metrics:
    task_count: int
    cost_usd: Decimal
    total_latency_ms: int
    mean_latency_ms: Optional[Decimal]
    input_tokens: int
    output_tokens: int
    tests_passed: int
    tests_failed: int
    tests_unknown: int
    scored_tasks: int
    mean_score: Optional[Decimal]
    developer_overrides: int

    @classmethod
    def from_traces(cls, traces: List[TaskTrace]) -> "Metrics":
        count = len(traces)
        latency = sum(trace.latency_ms for trace in traces)
        scores = [trace.outcome.score for trace in traces if trace.outcome.score is not None]
        return cls(
            count, sum((trace.cost_usd for trace in traces), Decimal(0)), latency,
            Decimal(latency) / count if count else None,
            sum(trace.input_tokens for trace in traces),
            sum(trace.output_tokens for trace in traces),
            sum(trace.outcome.tests_passed is True for trace in traces),
            sum(trace.outcome.tests_passed is False for trace in traces),
            sum(trace.outcome.tests_passed is None for trace in traces), len(scores),
            sum(scores, Decimal(0)) / len(scores) if scores else None,
            sum(trace.outcome.developer_override for trace in traces),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {name: decimal_text(getattr(self, name)) if name in (
            "cost_usd", "mean_latency_ms", "mean_score"
        ) else getattr(self, name) for name in METRIC_FIELDS}


@dataclass(frozen=True)
class ReplayRow:
    task_id: str
    baseline: TaskTrace
    suggested_model: Optional[str]
    decision: PolicyDecision
    evaluated: Optional[TaskTrace]
    missing_suggested_outcome: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "baseline_model": self.baseline.selected_model,
            "suggested_model": self.suggested_model,
            "decision": self.decision.to_dict(),
            "evaluated_model": self.evaluated.selected_model if self.evaluated else None,
            "missing_suggested_outcome": self.missing_suggested_outcome,
            "baseline_cost_usd": str(self.baseline.cost_usd),
            "evaluated_cost_usd": str(self.evaluated.cost_usd) if self.evaluated else None,
            "baseline_tests_passed": self.baseline.outcome.tests_passed,
            "evaluated_tests_passed": self.evaluated.outcome.tests_passed if self.evaluated else None,
            "baseline_score": decimal_text(self.baseline.outcome.score),
            "evaluated_score": decimal_text(self.evaluated.outcome.score) if self.evaluated else None,
        }


@dataclass(frozen=True)
class ReplayReport:
    policy_version: str
    policy_sha256: str
    mode: str
    rows: Tuple[ReplayRow, ...]
    recorded_baseline: Metrics
    comparison_baseline: Metrics
    comparison_policy: Metrics
    score_pairs: int
    mean_score_change: Optional[Decimal]

    @property
    def unevaluated_tasks(self) -> int:
        return sum(row.evaluated is None for row in self.rows)

    def to_dict(self) -> Dict[str, Any]:
        paired_count = self.comparison_baseline.task_count
        return {
            "policy_version": self.policy_version,
            "policy_sha256": self.policy_sha256,
            "mode": self.mode,
            "total_tasks": len(self.rows),
            "evaluated_tasks": paired_count,
            "unevaluated_tasks": self.unevaluated_tasks,
            "rule_matches": sum(bool(row.decision.evidence_refs) for row in self.rows),
            "fallbacks": sum(row.decision.used_fallback for row in self.rows),
            "missing_suggested_outcomes": sum(row.missing_suggested_outcome for row in self.rows),
            "recorded_baseline": self.recorded_baseline.to_dict(),
            "comparison_baseline": self.comparison_baseline.to_dict(),
            "comparison_policy": self.comparison_policy.to_dict(),
            "cost_reduction_usd": decimal_text(
                self.comparison_baseline.cost_usd - self.comparison_policy.cost_usd
            ) if paired_count else None,
            "total_latency_change_ms": (
                self.comparison_policy.total_latency_ms - self.comparison_baseline.total_latency_ms
            ) if paired_count else None,
            "score_pairs": self.score_pairs,
            "mean_score_change": decimal_text(self.mean_score_change),
            "notes": [
                "Offline comparison only: no API calls and no live model changes.",
                "Observe/shadow totals describe the recorded selection, not hypothetical suggested savings.",
                "Only tasks with recorded outcomes for both compared routes enter comparison totals.",
                "In replay mode, missing suggested outcomes trigger default fallback, not an invented cheaper result.",
                "Scores and test outcomes may be unknown; their counts are reported explicitly.",
                "Evidence references and local-file provenance are team-supplied, not verified here.",
                "Confidence is a rule label, not a statistical estimate or rollout approval.",
                "Policy export preserves supplied rules as a local proposal; it does not approve deployment.",
                "Synthetic or historical results do not establish production savings.",
            ],
            "decisions": [row.to_dict() for row in self.rows],
        }


def replay(traces: List[TaskTrace], policy: Policy, mode: str = "replay") -> ReplayReport:
    choice(mode, "mode", MODES)
    fingerprint = policy.fingerprint()
    validate_dataset(traces)
    tasks = {}
    for trace in traces:
        model = policy.model(trace.selected_model)
        if model is not None and trace.model_tier != model.tier:
            raise ValidationError("A recorded model tier disagrees with the policy registry.")
        tasks.setdefault(trace.task_id, {})[trace.selected_model] = trace

    rows = []
    baselines = []
    paired_baselines = []
    evaluated_traces = []
    score_changes = []
    for task_id in sorted(tasks):
        outcomes = tasks[task_id]
        baseline = next(trace for trace in outcomes.values() if trace.is_baseline)
        baselines.append(baseline)
        decision = decide(policy, baseline, mode)
        suggested = decision.recommended_model
        evaluated = outcomes.get(decision.effective_model)
        missing = suggested is not None and suggested not in outcomes
        if decision.effective_model is not None and evaluated is None and mode == "replay":
            decision = fallback(
                policy, baseline, mode,
                "Suggested task/model outcome is missing; evaluate the approved default instead.",
            )
            evaluated = outcomes.get(decision.effective_model)
        if evaluated is not None:
            paired_baselines.append(baseline)
            evaluated_traces.append(evaluated)
            if baseline.outcome.score is not None and evaluated.outcome.score is not None:
                score_changes.append(evaluated.outcome.score - baseline.outcome.score)
        rows.append(ReplayRow(task_id, baseline, suggested, decision, evaluated, missing))

    return ReplayReport(
        policy.policy_version, fingerprint, mode, tuple(rows), Metrics.from_traces(baselines),
        Metrics.from_traces(paired_baselines), Metrics.from_traces(evaluated_traces),
        len(score_changes), sum(score_changes, Decimal(0)) / len(score_changes) if score_changes else None,
    )
