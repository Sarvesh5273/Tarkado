"""Exact permitted tool status diagnostics. No arguments, outputs or engineering labels."""

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from engine.delivery_contract import LocalFunctionChatEnvelope, delivery_envelope
from engine.feedback import _fingerprint, _timestamp
from engine.schemas import ValidationError, choice, integer, object_fields
from .connectors import _link, uuid_value
from .models import DeliveryBinding, ToolObservation
from .services import TOOL_CAPTURE_FIELDS, member_snapshot


SOFT = ("execution_error", "test_failed")
HARD = ("permission_refused", "interrupted", "unknown", "gap")
SOURCES = ("opencode_v2_hook", "reviewed_tool_metadata", "missing_after_hook", "delivery_gap", "adapter_lifecycle")


def validate_payload(binding, payload):
    object_fields(payload, TOOL_CAPTURE_FIELDS, TOOL_CAPTURE_FIELDS)
    _fingerprint(payload)
    envelope = delivery_envelope(binding.data["envelope"])
    if not isinstance(envelope, LocalFunctionChatEnvelope):
        raise ValidationError("Tool capture requires the existing bound local-function contract.")
    phase = choice(payload["tool_phase"], "tool_phase", ("open", "start", "result", "gap"))
    status = choice(payload["tool_status"], "tool_status", ("capture_open", "started", "completed", *SOFT, *HARD))
    source = choice(payload["tool_status_source"], "tool_status_source", SOURCES)
    _timestamp(payload["tool_observed_at"])
    # Native hooks cannot authenticate a physical model attempt link. Do not
    # guess the most recent request; explicit linkage remains unavailable.
    if payload["tool_attempt_ref"] is not None:
        raise ValidationError("This V2 hook has no exact physical-attempt identity; keep linkage unknown.")
    if phase in ("open", "gap"):
        if status != ("capture_open" if phase == "open" else "gap") or source != ("adapter_lifecycle" if phase == "open" else "delivery_gap") or payload["tool_invocation_ref"] is not None or payload["tool_contract_ref"] is not None:
            raise ValidationError("Coverage gap cannot fabricate an invocation or result.")
        return
    ref = payload["tool_invocation_ref"]
    if not isinstance(ref, str) or len(ref) != 64 or any(ch not in "0123456789abcdef" for ch in ref):
        raise ValidationError("Tool invocation must use its opaque exact task/message/call reference.")
    contracts = {_fingerprint(tool.to_dict()): tool for tool in envelope.local_tools}
    tool = contracts.get(payload["tool_contract_ref"]) if isinstance(payload["tool_contract_ref"], str) else None
    if tool is None:
        raise ValidationError("Tool observation differs from its exact task-bound tool contract.")
    if phase == "start":
        if status != "started" or source != "opencode_v2_hook":
            raise ValidationError("Before hook records only an invocation start, not a result or permission.")
    elif status in ("capture_open", "started", "gap"):
        raise ValidationError("Result has no supported result status.")
    elif status == "test_failed" or status in ("permission_refused", "interrupted"):
        if source != "reviewed_tool_metadata" or tool.status_metadata_key is None or status == "test_failed" and tool.capability != "test":
            raise ValidationError("Finer tool status needs an explicitly reviewed metadata source and matching capability.")
    elif source == "missing_after_hook":
        if status != "unknown":
            raise ValidationError("Missing after hook is unknown, never inferred cancellation/error.")
    elif source != "opencode_v2_hook":
        raise ValidationError("Unrecognized provenance for native tool status.")


def state(binding, until=None):
    rows = list(binding.tool_observations.all())
    invocations, events, signals = {}, [], []
    previous, received, gaps = 0, None, 0
    for row in rows:
        validate_payload(binding, row.payload)
        actor = row.actor_snapshot
        object_fields(actor, tuple(binding.data["owner"]), tuple(binding.data["owner"]))
        if (row.sequence <= previous or row.missing_before != row.sequence - previous - 1
            or actor != binding.data["owner"] or received and row.received_at < received):
            raise ValidationError("Tool event sequence/actor/time differs from retained task history; do not reset.")
        previous, received = row.sequence, row.received_at
        if until is not None and row.received_at > until:
            continue
        gaps += row.missing_before
        payload = row.payload
        ref, phase, status = payload["tool_invocation_ref"], payload["tool_phase"], payload["tool_status"]
        if phase == "open":
            if row.sequence != 1:
                raise ValidationError("Capture initialization cannot restart historical tool observations.")
        elif phase == "gap":
            gaps += 1
        elif phase == "start":
            if ref in invocations:
                raise ValidationError("Invocation start cannot be repeated with another event identity.")
            invocations[ref] = {"contract_ref": payload["tool_contract_ref"], "started_at": payload["tool_observed_at"], "status": "started", "missing_start": False}
        else:
            prior = invocations.get(ref)
            if prior is None:
                if not gaps:
                    raise ValidationError("Tool result has no exact previously observed invocation start.")
                invocations[ref] = prior = {"contract_ref": payload["tool_contract_ref"], "started_at": None, "status": "started", "missing_start": True}
            if (prior["contract_ref"] != payload["tool_contract_ref"] or prior["status"] not in ("started", "unknown")
                or prior["started_at"] and _timestamp(payload["tool_observed_at"]) < _timestamp(prior["started_at"])):
                raise ValidationError("Late/changed tool result contradicts its immutable invocation or timing.")
            prior["status"] = status
        if status in (*SOFT, *HARD): signals.append(status)
        events.append({"event_id": str(row.event_id), "sequence": row.sequence, "received_at": row.received_at.isoformat(),
                       "actor": actor, "missing_before": row.missing_before, "payload": payload})
    if gaps: signals.append("gap")
    pending = sum(item["status"] == "started" for item in invocations.values())
    return {"sequence": events[-1]["sequence"] if events else 0, "invocations": invocations, "events": events,
            "negative_signals": list(dict.fromkeys(signals)), "gap_count": gaps, "pending_invocations": pending,
            "continuation_blocked": pending > 0 or any(status in HARD for status in signals),
            "test_outcome_verified": False, "final_task_outcome": None, "physical_attempt_linkage": "unavailable"}


def observe(credential, member, value):
    fields = ("connector_task_ref", "location_sha256", "session_ref", "event_id", "sequence", "payload")
    object_fields(value, fields, fields)
    if not set(TOOL_CAPTURE_FIELDS).issubset(credential.scope["collection_fields"]):
        raise PermissionDenied("Explicit approval of tool-status metadata fields and a new pairing are required.")
    link = _link(credential, value["connector_task_ref"], value["location_sha256"])
    if value["session_ref"] != link.session_ref:
        raise PermissionDenied("Tool status belongs to a different explicit task session.")
    binding = DeliveryBinding.objects.filter(connector_task=link).first()
    if binding is None or member_snapshot(member) != binding.data["owner"]:
        raise PermissionDenied("Tool status requires the exact bound task owner/historical identity.")
    payload = value["payload"]
    validate_payload(binding, payload)
    if _timestamp(payload["tool_observed_at"]) > timezone.now():
        raise ValidationError("Tool observation timing is future dated.")
    if _timestamp(payload["tool_observed_at"]) < link.task.events.first().timestamp:
        raise ValidationError("Tool observation cannot precede its task recommendation.")
    identifier, sequence = uuid_value(value["event_id"]), integer(value["sequence"], "sequence")
    previous = state(binding)
    existing = binding.tool_observations.filter(event_id=identifier).first()
    if existing:
        if existing.sequence != sequence or existing.payload != payload:
            raise ValidationError("Tool-status retry changed immutable event identity/content.")
        return previous
    if sequence <= previous["sequence"] or sequence == 0:
        raise ValidationError("Tool-status sequence is stale; append delayed results in ingestion order.")
    if link.closed_at and payload["tool_phase"] in ("open", "start"):
        raise ValidationError("Closed tasks cannot acquire a new tool invocation.")
    if link.closed_at and payload["tool_phase"] == "result" and payload["tool_invocation_ref"] not in previous["invocations"]:
        raise ValidationError("Late closed-task status must belong to an already observed invocation.")
    ToolObservation.objects.create(binding=binding, event_id=identifier, sequence=sequence, received_at=timezone.now(),
        actor_snapshot=member_snapshot(member), payload=payload, missing_before=sequence - previous["sequence"] - 1)
    result = state(binding)
    if result["continuation_blocked"] and payload["tool_phase"] != "start":
        from . import selection
        runtime = binding.runtime
        runtime.refresh_from_db()
        if selection._state(runtime)["status"] == "active":
            selection._append(runtime, member, "monitor", {"reason": "Tool refusal/interruption/missing result or coverage gap blocks future paid continuation; retain pending provider accounting.",
                                                        "connector_task_ref": str(link.reference)})
    return result


def observations(company, source_kind):
    return [{"binding_ref": str(binding.reference), "task_ref": str(binding.connector_task.task.reference),
             "task_type": binding.connector_task.task.request["task_type"], "state": state(binding)}
            for binding in DeliveryBinding.objects.filter(connector_task__task__company=company,
                connector_task__task__source_kind=source_kind, tool_observations__isnull=False).select_related("connector_task__task").distinct().order_by("id")]


def verify_execution(previous, current, binding_ref=None, task_types=()):
    previous_refs = {item["binding_ref"]: item for item in previous}
    current_refs = {item["binding_ref"]: item for item in current}
    if any(current_refs.get(ref) != old for ref, old in previous_refs.items()):
        raise ValidationError("Previously reviewed tool evidence changed; require another exact review.")
    for item in current:
        if item["task_type"] not in task_types:
            continue
        captured = item["state"]
        if captured["continuation_blocked"]:
            raise ValidationError("Tool refusal/interruption/unknown result or gap blocks paid continuation.")
        if captured["negative_signals"] and item["binding_ref"] != binding_ref:
            raise ValidationError("Retained intermediate tool failures block new automatic tasks in this category; only the exact bound task may repair.")
