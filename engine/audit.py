"""Validated local audit snapshots with hashed task IDs and no raw task content."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .exporters import export_jsonl
from .history import PolicySnapshot
from .importers import parse_json
from .privacy import ensure_safe
from .replay import ReplayReport
from .rollout import RolloutReport
from .schemas import (
    Outcome, Policy, TaskTrace, ValidationError, boolean, choice, integer,
    number, object_fields, strings, text,
)


AUDIT_MODES = ("observe", "replay", "shadow", "evaluate")
EVENT_FIELDS = (
    "schema_version", "record_type", "event_id", "event_type", "mode",
    "task_ref", "sample_ref", "trace_ref", "timestamp", "policy_version", "policy_sha256",
    "recorded_model", "baseline_model", "suggested_model", "effective_model", "evaluated_model",
    "fallback_model", "used_fallback", "blocked", "developer_override", "missing_outcome",
    "confidence", "reason", "evidence_refs", "measurement", "baseline_measurement", "local_only", "deployment_authorized",
)
MANIFEST_FIELDS = (
    "schema_version", "record_type", "mode", "policy_version", "policy_sha256",
    "event_count", "decision_count", "override_count", "evaluation_count",
    "identifier_handling", "retention_policy", "local_only", "deployment_authorized",
)


def _hash(data: Any) -> str:
    ensure_safe(data)
    content = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _digest(value: Any, name: str) -> str:
    result = text(value, name)
    if not re.fullmatch(r"[a-f0-9]{64}", result):
        raise ValidationError(f"{name} must be a SHA-256 fingerprint.")
    return result


def _envelope(data: Dict[str, Any], record_type: str) -> None:
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValidationError("Unsupported audit schema version.")
    if data["record_type"] != record_type:
        raise ValidationError("Unexpected audit record type.")
    if not boolean(data["local_only"], "local_only") or boolean(data["deployment_authorized"], "deployment_authorized"):
        raise ValidationError("Offline audit records cannot authorize live deployment.")


@dataclass(frozen=True)
class AuditMeasurement:
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    outcome: Outcome

    @classmethod
    def from_trace(cls, trace: TaskTrace) -> "AuditMeasurement":
        return cls.from_dict({"input_tokens": trace.input_tokens, "output_tokens": trace.output_tokens,
                              "cost_usd": str(trace.cost_usd), "latency_ms": trace.latency_ms,
                              "outcome": trace.outcome.to_dict()})

    @classmethod
    def from_dict(cls, value: Any) -> "AuditMeasurement":
        fields = ("input_tokens", "output_tokens", "cost_usd", "latency_ms", "outcome")
        data = object_fields(value, fields, fields)
        return cls(integer(data["input_tokens"], "input_tokens"), integer(data["output_tokens"], "output_tokens"),
                   number(data["cost_usd"], "cost_usd"), integer(data["latency_ms"], "latency_ms"),
                   Outcome.from_dict(data["outcome"]))

    def to_dict(self) -> Dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cost_usd": str(self.cost_usd), "latency_ms": self.latency_ms,
                "outcome": self.outcome.to_dict()}


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    event_type: str
    mode: str
    task_ref: str
    sample_ref: str
    trace_ref: str
    timestamp: str
    policy_version: str
    policy_sha256: str
    recorded_model: str
    baseline_model: Optional[str]
    suggested_model: Optional[str]
    effective_model: Optional[str]
    evaluated_model: Optional[str]
    fallback_model: str
    used_fallback: bool
    blocked: bool
    developer_override: bool
    missing_outcome: bool
    confidence: str
    reason: str
    evidence_refs: Tuple[str, ...]
    measurement: Optional[AuditMeasurement]
    baseline_measurement: Optional[AuditMeasurement]

    @classmethod
    def create(cls, payload: Dict[str, Any]) -> "AuditEvent":
        return cls.from_dict(dict(payload, event_id=_hash(payload)))

    @classmethod
    def from_dict(cls, value: Any) -> "AuditEvent":
        data = object_fields(value, EVENT_FIELDS, EVENT_FIELDS)
        ensure_safe(data)
        _envelope(data, "event")
        mode = choice(data["mode"], "mode", AUDIT_MODES)
        event_type = choice(data["event_type"], "event_type", ("decision", "override", "candidate_evaluation"))
        if (event_type == "candidate_evaluation" and mode != "evaluate") or (event_type == "decision" and mode == "evaluate"):
            raise ValidationError("Audit event type and operating mode disagree.")
        timestamp = text(data["timestamp"], "timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError("Audit timestamp must be ISO-8601.") from None
        if parsed.tzinfo is None:
            raise ValidationError("Audit timestamp must include a timezone.")
        optional_models = {}
        for field in ("baseline_model", "suggested_model", "effective_model", "evaluated_model"):
            optional_models[field] = None if data[field] is None else text(data[field], field)
        measurement = None if data["measurement"] is None else AuditMeasurement.from_dict(data["measurement"])
        baseline_measurement = (None if data["baseline_measurement"] is None
                                else AuditMeasurement.from_dict(data["baseline_measurement"]))
        event = cls(
            _digest(data["event_id"], "event_id"), event_type, mode,
            _digest(data["task_ref"], "task_ref"), _digest(data["sample_ref"], "sample_ref"),
            _digest(data["trace_ref"], "trace_ref"), timestamp,
            text(data["policy_version"], "policy_version"), _digest(data["policy_sha256"], "policy_sha256"),
            text(data["recorded_model"], "recorded_model"), optional_models["baseline_model"], optional_models["suggested_model"],
            optional_models["effective_model"], optional_models["evaluated_model"],
            text(data["fallback_model"], "fallback_model"), boolean(data["used_fallback"], "used_fallback"),
            boolean(data["blocked"], "blocked"), boolean(data["developer_override"], "developer_override"),
            boolean(data["missing_outcome"], "missing_outcome"),
            choice(data["confidence"], "confidence", ("low", "medium", "high")),
            text(data["reason"], "reason"), strings(data["evidence_refs"], "evidence_refs"), measurement, baseline_measurement,
        )
        if (event.evaluated_model is None) != (measurement is None):
            raise ValidationError("Evaluated model and measurement must both be present or absent.")
        if (event.baseline_model is None) != (baseline_measurement is None):
            raise ValidationError("Baseline model and measurement must both be present or absent.")
        if event.event_type == "override" and not event.developer_override:
            raise ValidationError("Override records require a recorded developer override.")
        if mode in ("observe", "shadow") and event.effective_model != event.recorded_model:
            raise ValidationError("Observe/shadow audit records must preserve recorded selection.")
        if mode == "evaluate" and event.effective_model is not None:
            raise ValidationError("Candidate evaluation cannot claim an effective live route.")
        if mode == "replay" and event.blocked and event.effective_model is not None:
            raise ValidationError("Blocked replay audit cannot claim an effective route.")
        canonical = event.to_dict()
        del canonical["event_id"]
        if event.event_id != _hash(canonical):
            raise ValidationError("Audit event content fingerprint disagrees.")
        return event

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": 1, "record_type": "event", "event_id": self.event_id,
            "event_type": self.event_type, "mode": self.mode,
            "task_ref": self.task_ref, "sample_ref": self.sample_ref, "trace_ref": self.trace_ref,
            "timestamp": self.timestamp, "policy_version": self.policy_version, "policy_sha256": self.policy_sha256,
            "recorded_model": self.recorded_model, "baseline_model": self.baseline_model, "suggested_model": self.suggested_model,
            "effective_model": self.effective_model, "evaluated_model": self.evaluated_model,
            "fallback_model": self.fallback_model, "used_fallback": self.used_fallback,
            "blocked": self.blocked, "developer_override": self.developer_override,
            "missing_outcome": self.missing_outcome, "confidence": self.confidence, "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "measurement": self.measurement.to_dict() if self.measurement else None,
            "baseline_measurement": self.baseline_measurement.to_dict() if self.baseline_measurement else None,
            "local_only": True, "deployment_authorized": False,
        }


@dataclass(frozen=True)
class AuditBatch:
    mode: str
    policy_version: str
    policy_sha256: str
    events: Tuple[AuditEvent, ...]

    def to_records(self) -> List[Dict[str, Any]]:
        manifest = {
            "schema_version": 1, "record_type": "manifest", "mode": self.mode,
            "policy_version": self.policy_version, "policy_sha256": self.policy_sha256,
            "event_count": len(self.events),
            "decision_count": sum(event.event_type == "decision" for event in self.events),
            "override_count": sum(event.event_type == "override" for event in self.events),
            "evaluation_count": sum(event.event_type == "candidate_evaluation" for event in self.events),
            "identifier_handling": "sha256", "retention_policy": "manual",
            "local_only": True, "deployment_authorized": False,
        }
        return [manifest] + [event.to_dict() for event in self.events]

    @classmethod
    def from_records(cls, records: List[Any]) -> "AuditBatch":
        if not records:
            raise ValidationError("Audit file must include a manifest.")
        manifest = object_fields(records[0], MANIFEST_FIELDS, MANIFEST_FIELDS)
        ensure_safe(manifest)
        _envelope(manifest, "manifest")
        choice(manifest["identifier_handling"], "identifier_handling", ("sha256",))
        choice(manifest["retention_policy"], "retention_policy", ("manual",))
        mode = choice(manifest["mode"], "mode", AUDIT_MODES)
        version = text(manifest["policy_version"], "policy_version")
        digest = _digest(manifest["policy_sha256"], "policy_sha256")
        events = tuple(AuditEvent.from_dict(record) for record in records[1:])
        if len({event.event_id for event in events}) != len(events):
            raise ValidationError("Audit file contains duplicate event IDs.")
        if any((event.mode, event.policy_version, event.policy_sha256) != (mode, version, digest) for event in events):
            raise ValidationError("Audit event policy/mode disagrees with the manifest.")
        batch = cls(mode, version, digest, events)
        expected = batch.to_records()[0]
        for field in ("event_count", "decision_count", "override_count", "evaluation_count"):
            if integer(manifest[field], field) != expected[field]:
                raise ValidationError("Audit manifest counts disagree with its events.")
        return batch

    def export(self, path: Path) -> None:
        validated = AuditBatch.from_records(self.to_records())
        export_jsonl(validated.to_records(), path)


def _base_payload(trace: TaskTrace, policy: Policy, digest: str, mode: str) -> Dict[str, Any]:
    return {
        "schema_version": 1, "record_type": "event", "mode": mode,
        "task_ref": _hash(trace.task_id), "sample_ref": _hash([trace.task_id, trace.sample_id]),
        "trace_ref": _hash(trace.trace_id), "timestamp": trace.timestamp,
        "policy_version": policy.policy_version, "policy_sha256": digest,
        "fallback_model": policy.default_model, "local_only": True, "deployment_authorized": False,
    }


def replay_audit(report: ReplayReport, policy: Policy) -> AuditBatch:
    snapshot = PolicySnapshot.create(policy)
    if (report.policy_version, report.policy_sha256) != (policy.policy_version, snapshot.sha256):
        raise ValidationError("Audit report and policy content disagree.")
    events = []
    for row in report.rows:
        if row.decision.policy_version != policy.policy_version:
            raise ValidationError("Audit decision and policy version disagree.")
        payload = _base_payload(row.baseline, policy, snapshot.sha256, report.mode)
        payload.update(
            event_type="decision", recorded_model=row.baseline.selected_model,
            baseline_model=row.baseline.selected_model, suggested_model=row.suggested_model,
            effective_model=row.decision.effective_model,
            evaluated_model=row.evaluated.selected_model if row.evaluated else None,
            used_fallback=row.decision.used_fallback, blocked=row.decision.recommended_model is None,
            developer_override=row.baseline.outcome.developer_override,
            missing_outcome=row.missing_suggested_outcome or row.evaluated is None,
            confidence=row.decision.confidence, reason=row.decision.reason,
            evidence_refs=list(row.decision.evidence_refs),
            measurement=AuditMeasurement.from_trace(row.evaluated).to_dict() if row.evaluated else None,
            baseline_measurement=AuditMeasurement.from_trace(row.baseline).to_dict(),
        )
        events.append(AuditEvent.create(payload))
        if row.baseline.outcome.developer_override:
            events.append(AuditEvent.create(dict(payload, event_type="override")))
    return AuditBatch.from_records(AuditBatch(report.mode, policy.policy_version, snapshot.sha256, tuple(events)).to_records())


def rollout_audit(report: RolloutReport, policy: Policy) -> AuditBatch:
    snapshot = PolicySnapshot.create(policy)
    if (report.policy_version, report.policy_sha256) != (policy.policy_version, snapshot.sha256):
        raise ValidationError("Audit report and policy content disagree.")
    events = []
    for row in report.rows:
        trace = row.candidate or row.recorded
        payload = _base_payload(trace, policy, snapshot.sha256, "evaluate")
        reason = (row.compatibility_failure or row.baseline_failure
                  or f"Offline candidate comparison; recommendation: {report.recommendation}.")
        payload.update(
            event_type="candidate_evaluation", recorded_model=row.recorded.selected_model,
            baseline_model=row.baseline.selected_model if row.baseline else None,
            suggested_model=report.candidate_model, effective_model=None,
            evaluated_model=row.candidate.selected_model if row.candidate else None,
            used_fallback=False, blocked=not row.paired,
            developer_override=row.candidate.outcome.developer_override if row.candidate else False,
            missing_outcome=row.candidate is None or row.baseline is None,
            confidence="low", reason=reason, evidence_refs=[],
            measurement=AuditMeasurement.from_trace(row.candidate).to_dict() if row.candidate else None,
            baseline_measurement=AuditMeasurement.from_trace(row.baseline).to_dict() if row.baseline else None,
        )
        events.append(AuditEvent.create(payload))
        if payload["developer_override"]:
            events.append(AuditEvent.create(dict(payload, event_type="override")))
    return AuditBatch.from_records(AuditBatch("evaluate", policy.policy_version, snapshot.sha256, tuple(events)).to_records())


def load_audit(path: Path) -> AuditBatch:
    ensure_safe(str(path))
    records = [parse_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return AuditBatch.from_records(records)
