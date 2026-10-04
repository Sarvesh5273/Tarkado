"""Tarkado's simple rules with explicit approval, evidence, and fallback."""

from typing import Optional, Protocol, Tuple

from .schemas import MODES, Model, Outcome, Policy, PolicyDecision, choice


class RoutingTask(Protocol):
    task_type: Optional[str]
    risk_tags: Tuple[str, ...]
    selected_model: str
    model_tier: str
    required_tools: Tuple[str, ...]
    context_tokens: Optional[int]
    outcome: Outcome


def capability_issue(model: Optional[Model], trace: RoutingTask) -> Optional[str]:
    if model is None:
        return "Model is not registered."
    if "*" not in model.task_types and trace.task_type not in model.task_types:
        return "Model is not approved for this task type."
    if not set(trace.required_tools).issubset(model.tools):
        return "Model does not support all required tools."
    if trace.context_tokens is None:
        return "Task context requirement is unknown."
    if trace.context_tokens > model.max_context_tokens:
        return "Task exceeds the model's approved context capacity."
    return None


def incompatibility(model: Optional[Model], trace: RoutingTask) -> Optional[str]:
    if model is None:
        return "Model is not registered."
    if not model.approved:
        return "Model is not approved."
    return capability_issue(model, trace)


def fallback(policy: Policy, trace: RoutingTask, mode: str, reason: str) -> PolicyDecision:
    default = policy.model(policy.default_model)
    issue = incompatibility(default, trace)
    recommended = None if issue else default
    if issue:
        reason += " Default is also incompatible; no route is authorized. " + issue
    effective = trace.selected_model if mode in ("observe", "shadow") else (
        recommended.model_id if recommended else None
    )
    return PolicyDecision(
        policy.policy_version, recommended.model_id if recommended else None,
        recommended.tier if recommended else None, "low", reason,
        policy.default_model, mode, effective, True,
    )


def decide(policy: Policy, trace: RoutingTask, mode: str = "replay") -> PolicyDecision:
    choice(mode, "mode", MODES)
    if mode == "observe":
        return PolicyDecision(
            policy.policy_version, trace.selected_model, trace.model_tier, "low",
            "Observe-only: retain the recorded model without applying routing rules.",
            policy.default_model, mode, trace.selected_model, False,
        )
    if trace.outcome.developer_override:
        model = policy.model(trace.selected_model)
        issue = incompatibility(model, trace)
        if issue:
            return fallback(policy, trace, mode, "Recorded override is not an approved compatible route. " + issue)
        return PolicyDecision(
            policy.policy_version, model.model_id, model.tier, "low",
            "Recorded developer override retained; no automatic model change.",
            policy.default_model, mode, model.model_id, False,
        )
    if trace.task_type is None:
        return fallback(policy, trace, mode, "Task type is unknown; use the approved default.")
    if set(trace.risk_tags) != {"low"}:
        return fallback(policy, trace, mode, "Risk is high, missing, or unknown; use the approved default.")
    rule = next((rule for rule in policy.rules if rule.task_type == trace.task_type), None)
    if rule is None:
        return fallback(policy, trace, mode, "No task-type rule; use the approved default.")
    if not rule.evidence_refs:
        return fallback(policy, trace, mode, "Rule has no evidence references; use the approved default.")
    model = policy.model(rule.model)
    issue = incompatibility(model, trace)
    if issue:
        return fallback(policy, trace, mode, issue + " Use the approved default.")
    return PolicyDecision(
        policy.policy_version, model.model_id, model.tier, "medium",
        "Matched an explicitly low-risk task rule with team-supplied evidence references.",
        policy.default_model, mode, trace.selected_model if mode == "shadow" else model.model_id,
        False, rule.evidence_refs,
    )
