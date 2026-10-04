"""Validated metadata contracts for Tarkado's offline simulator."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Dict, Optional, Tuple

from .privacy import ensure_safe


class ValidationError(ValueError):
    """Input is invalid or outside the metadata-only contract."""


def object_fields(value: Any, allowed: Tuple[str, ...], required: Tuple[str, ...]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("Expected a JSON object.")
    if set(value) - set(allowed):
        raise ValidationError("Unexpected fields; only declared metadata fields are accepted.")
    if set(required) - set(value):
        raise ValidationError("Missing required metadata fields.")
    return value


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a nonempty string.")
    ensure_safe(value)
    return value


def strings(value: Any, name: str) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise ValidationError(f"{name} must be an array of strings.")
    result = tuple(text(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValidationError(f"{name} must not contain duplicates.")
    return result


def boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{name} must be a boolean.")
    return value


def integer(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{name} must be a nonnegative integer.")
    return value


def number(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValidationError(f"{name} must be a finite, nonnegative number.")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValidationError(f"{name} must be a finite, nonnegative number.") from None
    if not result.is_finite() or result < 0:
        raise ValidationError(f"{name} must be a finite, nonnegative number.")
    return result


def choice(value: Any, name: str, options: Tuple[str, ...]) -> str:
    if value not in options:
        raise ValidationError(f"{name} must be one of: {', '.join(options)}.")
    return value


TIERS = ("cheap", "standard", "premium")
MODES = ("observe", "replay", "shadow")
MODEL_STATES = ("candidate", "shadow", "approved", "disabled")
TRACE_REQUIRED_FIELDS = (
    "trace_id", "task_id", "timestamp", "task_type", "risk_tags",
    "selected_model", "model_tier", "input_tokens", "output_tokens",
    "cost_usd", "latency_ms", "outcome", "is_baseline",
    "required_tools", "context_tokens",
)
TRACE_FIELDS = TRACE_REQUIRED_FIELDS + ("sample_id",)


@dataclass(frozen=True)
class Outcome:
    tests_passed: Optional[bool]
    developer_override: bool
    score: Optional[Decimal]

    @classmethod
    def from_dict(cls, value: Any) -> "Outcome":
        fields = ("tests_passed", "developer_override", "score")
        data = object_fields(value, fields, fields)
        passed = data["tests_passed"]
        if passed is not None:
            passed = boolean(passed, "tests_passed")
        score = None if data["score"] is None else number(data["score"], "score")
        if score is not None and score > 1:
            raise ValidationError("score must be between zero and one.")
        return cls(passed, boolean(data["developer_override"], "developer_override"), score)

    def to_dict(self) -> Dict[str, Any]:
        return {"tests_passed": self.tests_passed, "developer_override": self.developer_override,
                "score": str(self.score) if self.score is not None else None}


@dataclass(frozen=True)
class TaskTrace:
    trace_id: str
    task_id: str
    timestamp: str
    task_type: Optional[str]
    risk_tags: Tuple[str, ...]
    selected_model: str
    model_tier: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    outcome: Outcome
    is_baseline: bool
    required_tools: Tuple[str, ...]
    context_tokens: Optional[int]
    sample_id: str = "single"

    @classmethod
    def from_dict(cls, value: Any) -> "TaskTrace":
        data = object_fields(value, TRACE_FIELDS, TRACE_REQUIRED_FIELDS)
        timestamp = text(data["timestamp"], "timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError("timestamp must be an ISO-8601 timestamp.") from None
        if parsed.tzinfo is None:
            raise ValidationError("timestamp must include a timezone.")
        task_type = data["task_type"]
        if task_type is not None:
            task_type = text(task_type, "task_type")
        context = data["context_tokens"]
        if context is not None:
            context = integer(context, "context_tokens")
        return cls(
            text(data["trace_id"], "trace_id"), text(data["task_id"], "task_id"),
            timestamp, task_type, strings(data["risk_tags"], "risk_tags"),
            text(data["selected_model"], "selected_model"),
            choice(data["model_tier"], "model_tier", TIERS),
            integer(data["input_tokens"], "input_tokens"),
            integer(data["output_tokens"], "output_tokens"),
            number(data["cost_usd"], "cost_usd"), integer(data["latency_ms"], "latency_ms"),
            Outcome.from_dict(data["outcome"]), boolean(data["is_baseline"], "is_baseline"),
            strings(data["required_tools"], "required_tools"), context,
            text(data.get("sample_id", "single"), "sample_id"),
        )

    def task_metadata(self) -> Tuple[Any, ...]:
        return (self.task_type, frozenset(self.risk_tags),
                frozenset(self.required_tools), self.context_tokens)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id, "task_id": self.task_id, "timestamp": self.timestamp,
            "task_type": self.task_type, "risk_tags": list(self.risk_tags),
            "selected_model": self.selected_model, "model_tier": self.model_tier,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "cost_usd": str(self.cost_usd), "latency_ms": self.latency_ms,
            "outcome": self.outcome.to_dict(), "is_baseline": self.is_baseline,
            "required_tools": list(self.required_tools), "context_tokens": self.context_tokens,
            "sample_id": self.sample_id,
        }


@dataclass(frozen=True)
class Model:
    model_id: str
    tier: str
    status: str
    task_types: Tuple[str, ...]
    tools: Tuple[str, ...]
    max_context_tokens: int

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    @classmethod
    def from_dict(cls, value: Any) -> "Model":
        required = ("model_id", "tier", "task_types", "tools", "max_context_tokens")
        data = object_fields(value, required + ("approved", "status"), required)
        if "status" not in data and "approved" not in data:
            raise ValidationError("Model must declare status or approved.")
        legacy_approved = boolean(data["approved"], "approved") if "approved" in data else None
        status = choice(data["status"], "status", MODEL_STATES) if "status" in data else (
            "approved" if legacy_approved else "disabled"
        )
        if legacy_approved is not None and legacy_approved != (status == "approved"):
            raise ValidationError("Model status and approved flag disagree.")
        capacity = integer(data["max_context_tokens"], "max_context_tokens")
        if capacity == 0:
            raise ValidationError("max_context_tokens must be positive.")
        return cls(
            text(data["model_id"], "model_id"), choice(data["tier"], "tier", TIERS),
            status, strings(data["task_types"], "task_types"),
            strings(data["tools"], "tools"), capacity,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "model_id": self.model_id,
            "tier": self.tier,
            "approved": self.approved,
            "task_types": list(self.task_types),
            "tools": list(self.tools),
            "max_context_tokens": self.max_context_tokens,
        }
        # Preserve the Phase 1 export shape for approved models.
        if not self.approved:
            data["status"] = self.status
        return data


@dataclass(frozen=True)
class Rule:
    task_type: str
    model: str
    evidence_refs: Tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any) -> "Rule":
        fields = ("task_type", "model", "evidence_refs")
        data = object_fields(value, fields, fields)
        return cls(text(data["task_type"], "task_type"), text(data["model"], "model"),
                   strings(data["evidence_refs"], "evidence_refs"))


@dataclass(frozen=True)
class Policy:
    policy_version: str
    default_model: str
    models: Tuple[Model, ...]
    rules: Tuple[Rule, ...]

    @classmethod
    def from_dict(cls, value: Any) -> "Policy":
        fields = ("policy_version", "default_model", "models", "rules")
        data = object_fields(value, fields, fields)
        if not isinstance(data["models"], list) or not isinstance(data["rules"], list):
            raise ValidationError("models and rules must be arrays.")
        models = tuple(Model.from_dict(item) for item in data["models"])
        rules = tuple(Rule.from_dict(item) for item in data["rules"])
        if len({model.model_id for model in models}) != len(models):
            raise ValidationError("Model IDs must be unique.")
        if len({rule.task_type for rule in rules}) != len(rules):
            raise ValidationError("Only one rule per task type is supported.")
        default_id = text(data["default_model"], "default_model")
        default = next((model for model in models if model.model_id == default_id), None)
        if default is None or not default.approved or default.tier != "premium":
            raise ValidationError("default_model must be a registered, approved premium model.")
        return cls(text(data["policy_version"], "policy_version"), default_id, models, rules)

    def model(self, model_id: str) -> Optional[Model]:
        return next((model for model in self.models if model.model_id == model_id), None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "default_model": self.default_model,
            "models": [model.to_dict() for model in self.models],
            "rules": [
                {
                    "task_type": rule.task_type,
                    "model": rule.model,
                    "evidence_refs": list(rule.evidence_refs),
                }
                for rule in self.rules
            ],
        }

    def fingerprint(self) -> str:
        normalized = Policy.from_dict(self.to_dict()).to_dict()
        ensure_safe(normalized)
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PolicyDecision:
    policy_version: str
    recommended_model: Optional[str]
    recommended_tier: Optional[str]
    confidence: str
    reason: str
    fallback_model: str
    enforcement: str
    effective_model: Optional[str]
    used_fallback: bool
    evidence_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        text(self.policy_version, "policy_version")
        text(self.reason, "reason")
        text(self.fallback_model, "fallback_model")
        choice(self.enforcement, "enforcement", MODES)
        choice(self.confidence, "confidence", ("low", "medium", "high"))
        boolean(self.used_fallback, "used_fallback")
        if (self.recommended_model is None) != (self.recommended_tier is None):
            raise ValidationError("Recommended model and tier must both be present or absent.")
        if self.recommended_model is not None:
            text(self.recommended_model, "recommended_model")
            choice(self.recommended_tier, "recommended_tier", TIERS)
        if self.effective_model is not None:
            text(self.effective_model, "effective_model")
        strings(list(self.evidence_refs), "evidence_refs")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "recommended_model": self.recommended_model,
            "recommended_tier": self.recommended_tier,
            "confidence": self.confidence,
            "reason": self.reason,
            "fallback_model": self.fallback_model,
            "enforcement": self.enforcement,
            "effective_model": self.effective_model,
            "used_fallback": self.used_fallback,
            "evidence_refs": list(self.evidence_refs),
        }
