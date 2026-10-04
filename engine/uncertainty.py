"""A simple bounded-mean baseline, with repeated runs grouped inside each task."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any, Dict, List, Optional, Protocol, Sequence

from .schemas import TaskTrace, ValidationError, boolean, number, object_fields


METRIC_ORDER = (
    "score_change", "test_pass_change", "developer_override_change",
    "cost_reduction_usd", "latency_change_ms",
)
BOUNDED_METRICS = METRIC_ORDER[:3]


@dataclass(frozen=True)
class UncertaintySettings:
    confidence_level: Decimal = Decimal("0.95")
    independent_tasks_attested: bool = False
    fixed_sampling_attested: bool = False

    @classmethod
    def from_dict(cls, value: Any) -> "UncertaintySettings":
        fields = ("confidence_level", "independent_tasks_attested", "fixed_sampling_attested")
        data = object_fields(value, fields, fields)
        confidence = number(data["confidence_level"], "confidence_level")
        if not Decimal("0.5") <= confidence <= Decimal("0.999"):
            raise ValidationError("confidence_level must be between 0.5 and 0.999.")
        return cls(confidence, boolean(data["independent_tasks_attested"], "independent_tasks_attested"),
                   boolean(data["fixed_sampling_attested"], "fixed_sampling_attested"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confidence_level": str(self.confidence_level),
            "independent_tasks_attested": self.independent_tasks_attested,
            "fixed_sampling_attested": self.fixed_sampling_attested,
        }


class Comparison(Protocol):
    task_id: str
    sample_id: str
    baseline: Optional[TaskTrace]
    candidate: Optional[TaskTrace]

    @property
    def paired(self) -> bool:
        ...


def hoeffding_interval(mean: Decimal, task_count: int, confidence_level: Decimal) -> Dict[str, str]:
    """Two-sided pointwise interval for independent task means in [-1, 1]."""
    confidence_level = UncertaintySettings.from_dict(UncertaintySettings(confidence_level).to_dict()).confidence_level
    if type(task_count) is not int or task_count < 2:
        raise ValidationError("An uncertainty interval requires at least two distinct tasks.")
    if not isinstance(mean, Decimal) or not mean.is_finite() or not Decimal(-1) <= mean <= Decimal(1):
        raise ValidationError("Bounded-quality task mean must be finite and in [-1, 1].")
    with localcontext() as context:
        context.prec = 50
        # Hoeffding 1963, Theorem 2, plus a union bound for the two tails.
        radius = Decimal(2) * ((Decimal(2) / (1 - confidence_level)).ln() / (2 * task_count)).sqrt()
        lower = max(Decimal(-1), mean - radius)
        upper = min(Decimal(1), mean + radius)
        return {"method": "hoeffding_two_sided", "confidence_level": str(confidence_level),
                "radius": str(radius), "lower": str(lower), "upper": str(upper),
                "coverage": "pointwise", "value_range_lower": "-1", "value_range_upper": "1"}


def _delta(row: Comparison, metric: str) -> Optional[Decimal]:
    if not row.paired:
        return None
    baseline, candidate = row.baseline, row.candidate
    if metric == "score_change":
        if baseline.outcome.score is None or candidate.outcome.score is None:
            return None
        return candidate.outcome.score - baseline.outcome.score
    if metric == "test_pass_change":
        if baseline.outcome.tests_passed is None or candidate.outcome.tests_passed is None:
            return None
        return Decimal(int(candidate.outcome.tests_passed) - int(baseline.outcome.tests_passed))
    if metric == "developer_override_change":
        return Decimal(int(candidate.outcome.developer_override) - int(baseline.outcome.developer_override))
    if metric == "cost_reduction_usd":
        return baseline.cost_usd - candidate.cost_usd
    return Decimal(candidate.latency_ms - baseline.latency_ms)


def summarize_uncertainty(rows: Sequence[Comparison], settings: UncertaintySettings) -> Dict[str, Any]:
    validated = UncertaintySettings.from_dict(settings.to_dict())
    groups: Dict[str, List[Comparison]] = {}
    identities = set()
    for row in rows:
        identity = (row.task_id, row.sample_id)
        if identity in identities:
            raise ValidationError("Uncertainty inputs have duplicate task/sample pairs.")
        identities.add(identity)
        groups.setdefault(row.task_id, []).append(row)
        for trace in (row.baseline, row.candidate):
            if trace is not None:
                TaskTrace.from_dict(trace.to_dict())
                if (trace.task_id, trace.sample_id) != identity:
                    raise ValidationError("Uncertainty comparisons must share task/sample identifiers.")
        if row.baseline is not None and row.candidate is not None:
            if row.baseline.task_metadata() != row.candidate.task_metadata():
                raise ValidationError("Uncertainty outcomes must share task requirements and risk metadata.")

    metrics = {}
    for metric in METRIC_ORDER:
        values: List[Decimal] = []
        included_samples = 0
        excluded_samples = 0
        for task_id in sorted(groups):
            task_rows = sorted(groups[task_id], key=lambda row: row.sample_id)
            with localcontext() as context:
                context.prec = 50
                changes = [_delta(row, metric) for row in task_rows]
            if any(value is None for value in changes):
                # Partial task averages can select easier runs. Exclude and disclose the whole task.
                excluded_samples += len(task_rows)
                continue
            with localcontext() as context:
                context.prec = 50
                values.append(sum(changes, Decimal(0)) / len(changes))
            included_samples += len(changes)
        count = len(values)
        with localcontext() as context:
            context.prec = 50
            mean = sum(values, Decimal(0)) / count if count else None
            variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / (count - 1) if count > 1 else None
            stddev = variance.sqrt() if variance is not None else None
        interval = None
        if metric not in BOUNDED_METRICS:
            status = "no_declared_hard_bounds"
        elif not count:
            status = "no_complete_tasks"
        elif count != len(groups):
            status = "incomplete_task_coverage"
        elif count < 2:
            status = "too_few_distinct_tasks"
        elif not validated.independent_tasks_attested or not validated.fixed_sampling_attested:
            status = "sampling_assumptions_unconfirmed"
        else:
            status = "available_under_attested_assumptions"
            interval = hoeffding_interval(mean, count, validated.confidence_level)
        metrics[metric] = {
            "complete_tasks": count, "excluded_tasks": len(groups) - count,
            "included_samples": included_samples, "excluded_samples": excluded_samples,
            "task_weighted_mean": str(mean) if mean is not None else None,
            "minimum_task_mean": str(min(values)) if values else None,
            "maximum_task_mean": str(max(values)) if values else None,
            "sample_stddev_of_task_means": str(stddev) if stddev is not None else None,
            "interval_status": status, "interval": interval,
        }
    return {
        "unit": "distinct_task", "weighting": "equal_task_after_within_task_mean",
        "scope_tasks": len(groups), "scope_samples": len(rows), "settings": validated.to_dict(),
        "metrics": metrics, "affects_recommendation": False, "deployment_authorized": False,
        "notes": [
            "Repeated samples contribute to a task mean, never to the independent-task count.",
            "Every recorded sample of a task must be paired and known for the relevant metric; partial tasks are excluded and disclosed.",
            "Distinct task IDs do not verify independence, representative sampling, or a fixed evaluation design.",
            "Intervals are pointwise and conditional on attested independence/fixed sampling; no multiple-model or multiple-metric guarantee.",
            "Uniform task weighting can differ from pooled sample-weighted report totals.",
            "Zero observed spread is not certainty; bounded-quality intervals retain a nonzero radius.",
            "No cost/latency interval is claimed without justified hard bounds; sample ranges are not such bounds.",
            "Reporting intervals never approves a rollout or changes conservative per-sample regression checks.",
        ],
    }
