"""Append independently verified cost revisions; never grant execution or rewrite settlements."""

from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from engine.feedback import _fingerprint, _timestamp
from engine.pilot import _money_total
from engine.schemas import ValidationError, integer, number, object_fields, text

from . import billing_gate, delivery, selection
from .models import DeliveryBinding
from .security import sensitive_actor
from .services import current_member, member_snapshot


INPUT_FIELDS = ("correction_id", "attempt_id", "request_id", "expected_revision", "supersedes_sha256", "cost_usd", "evidence_ref")
PAYLOAD_FIELDS = INPUT_FIELDS + ("cost_revision", "previous_cost_usd", "pilot_revision", "actor", "billing_assessment")


def _actor(actor, gateway):
    if "gateway_ref" in actor:
        object_fields(actor, ("gateway_ref", "gateway_id"), ("gateway_ref", "gateway_id"))
        if actor != {"gateway_ref": str(gateway.reference), "gateway_id": gateway.gateway_id}:
            raise ValidationError("Correction actor differs from its historical machine identity.")
    else:
        fields = ("account_id", "developer_id", "role", "active", "participating", "can_manage_company", "can_approve_pilots")
        object_fields(actor, fields, fields)
        integer(actor["account_id"], "account_id")
        text(actor["developer_id"], "developer_id")
        if actor["role"] != "admin" or actor["active"] is not True or actor["can_manage_company"] is not True or actor["participating"] is not False or type(actor["can_approve_pilots"]) is not bool:
            raise ValidationError("Correction has no historical company-administrator authority.")


def correction_request(binding, row, payload):
    # The verifier receives only approved accounting metadata, never invoice bodies.
    return {"schema_version": 1, "kind": "known_cost_correction",
        **billing_gate.reconciliation_request(binding, row, payload),
        "task_ref": str(binding.connector_task.task.reference), "owner": binding.data["owner"],
        "logical_request": next(event["payload"] for event in binding.journal if event["action"] == "request" and event["payload"]["request_id"] == row["request_id"]),
        "original_settlement": row["original_settlement"], "previous_corrections": row["corrections"]}


def replay_correction(binding, attempts, event):
    payload = object_fields(event["payload"], PAYLOAD_FIELDS, PAYLOAD_FIELDS)
    row = attempts.get(payload["attempt_id"])
    delivery.connectors.uuid_value(payload["correction_id"])
    integer(payload["expected_revision"], "expected_revision")
    integer(payload["cost_revision"], "cost_revision")
    integer(payload["pilot_revision"], "pilot_revision")
    if (row is None or row["cost_usd"] is None or payload["request_id"] != row["request_id"]
        or payload["expected_revision"] != event["sequence"] - 1 or payload["supersedes_sha256"] != row["cost_head_sha256"]
        or payload["cost_revision"] != row["cost_revision"] + 1 or payload["previous_cost_usd"] != row["cost_usd"]
        or any(item["payload"]["correction_id"] == payload["correction_id"] for attempt in attempts.values() for item in attempt["corrections"])):
        raise ValidationError("Correction is stale, branched, duplicated or belongs to another task/request/attempt.")
    if not isinstance(payload["cost_usd"], str):
        raise ValidationError("Corrected cost must be an exact decimal string, never a float.")
    number(payload["cost_usd"], "cost_usd")
    text(payload["evidence_ref"], "evidence_ref")
    gateway = delivery.GatewayCredential.objects.get(reference=event["gateway_ref"])
    _actor(payload["actor"], gateway)
    assessment = billing_gate.BillingAssessment.from_dict(payload["billing_assessment"])
    if (assessment.evidence_sha256 is None or assessment.request_sha256 != _fingerprint(correction_request(binding, row, payload))
        or not _timestamp(assessment.verified_at) <= _timestamp(event["timestamp"]) < _timestamp(assessment.valid_until)):
        raise ValidationError("Correction has no exact historical independent billing evidence.")
    # Only the current cost projection changes. Original usage/outcome/evidence stay intact.
    row["cost_usd"] = payload["cost_usd"]
    row["cost_revision"] = payload["cost_revision"]
    row["cost_head_sha256"] = event["sha256"]
    row["corrections"] = row["corrections"] + [{key: event[key] for key in ("sequence", "timestamp", "sha256", "payload")}]


def retained_overrun(binding, current):
    return current["historical_task_overrun"] or current["historical_attempt_overrun"]


def _prepare(binding, gateway, actor, value):
    value = dict(object_fields(value, INPUT_FIELDS, INPUT_FIELDS))
    _fingerprint(value)
    delivery.connectors.uuid_value(value["correction_id"])
    _actor(actor, gateway)
    before = delivery.state(binding)
    # An exact retry returns its historical receipt, even after subsequent revisions.
    for event in binding.journal:
        if event["action"] == "correct_cost" and event["payload"]["correction_id"] == value["correction_id"]:
            if {key: event["payload"][key] for key in INPUT_FIELDS} != value or event["payload"]["actor"] != actor:
                raise ValidationError("Correction retry changed immutable content or actor.")
            return before, event["payload"], True
    row = before["attempts"].get(value["attempt_id"])
    if row is None or row["cost_usd"] is None or row["request_id"] != value["request_id"]:
        raise ValidationError("Correct only a known cost on the exact owned request/physical attempt; unknowns use existing reconciliation.")
    if type(value["expected_revision"]) is not int or value["expected_revision"] != before["revision"] or value["supersedes_sha256"] != row["cost_head_sha256"]:
        raise ValidationError("Correction is stale or branched; reload the exact cost history before review.")
    if not isinstance(value["cost_usd"], str):
        raise ValidationError("Corrected cost must be an exact decimal string, never a float.")
    number(value["cost_usd"], "cost_usd")
    text(value["evidence_ref"], "evidence_ref")
    return before, {**value, "cost_revision": row["cost_revision"] + 1, "previous_cost_usd": row["cost_usd"],
        "pilot_revision": len(binding.runtime.journal["events"]), "actor": actor}, False


def _review(binding, gateway, actor, value):
    before, payload, retry = _prepare(binding, gateway, actor, value)
    if not retry:
        payload["billing_assessment"] = billing_gate.verify(correction_request(binding, before["attempts"][payload["attempt_id"]], payload), require_snapshot=True)
    cost = _money_total([Decimal(payload["cost_usd"] if not retry and row["attempt_id"] == payload["attempt_id"] else row["cost_usd"])
        for row in before["attempts"].values() if row["cost_usd"] is not None])
    runtime_state = selection._state(binding.runtime)
    totals = selection.accounting(binding.runtime, runtime_state)
    proposed = dict(totals)
    if binding.selection_id in runtime_state["settlements"]:
        proposed["spent_usd"] = str(_money_total([cost if key == binding.selection_id else Decimal(row["cost_usd"])
            for key, row in runtime_state["settlements"].items()]))
    else:
        obligation = max(Decimal(binding.data["task_cap_usd"]), _money_total([cost, Decimal(before["attempt_reserved_usd"])]))
        other = {row.selection_id: delivery.state(row) for row in DeliveryBinding.objects.filter(runtime=binding.runtime).exclude(pk=binding.pk)}
        proposed["reserved_usd"] = str(_money_total([obligation if key == binding.selection_id else max(Decimal(row["reserve_usd"]), Decimal(other[key]["obligation_usd"]) if key in other else Decimal(0))
            for key, row in runtime_state["decisions"].items() if key not in runtime_state["settlements"]]))
    proposed["committed_usd"] = str(_money_total([Decimal(proposed["spent_usd"]), Decimal(proposed["reserved_usd"])]))
    proposed["remaining_usd"] = str(_money_total([Decimal(binding.runtime.authorization.data["scope"]["max_cost_usd"]), Decimal(proposed["committed_usd"]).copy_negate()]))
    return {"binding_ref": str(binding.reference), "correction": payload, "historical_replay": retry,
        "current_task_cost_usd": before["known_cost_usd"], "proposed_task_cost_usd": str(cost),
        "proposed_remaining_task_usd": str(_money_total([Decimal(binding.data["task_cap_usd"]), cost.copy_negate(), Decimal(before["attempt_reserved_usd"]).copy_negate()])),
        "pilot_accounting": totals, "proposed_pilot_accounting": proposed, "execution_sent": False}


def _apply(binding, gateway, actor, value, expected_assessment, recheck):
    before, payload, retry = _prepare(binding, gateway, actor, value)
    if retry:
        return {"delivery": before, "correction": payload, "historical_replay": True, "new_correction": False, "execution_sent": False}
    if expected_assessment is None:
        raise ValidationError("Review and confirm independent billing evidence before applying a correction.")
    payload["billing_assessment"] = billing_gate.verify(correction_request(binding, before["attempts"][payload["attempt_id"]], payload), expected=expected_assessment, require_snapshot=True)
    recheck()
    binding.refresh_from_db()
    fresh, fresh_payload, _ = _prepare(binding, gateway, actor, value)
    if fresh != before or fresh_payload != {key: item for key, item in payload.items() if key != "billing_assessment"}:
        raise ValidationError("Accounting changed during billing verification; no correction was appended.")
    delivery._append(binding, gateway, "correct_cost", payload)
    after = delivery.state(binding)
    selection.delivery_event(binding, gateway, "delivery_cost_correction", {"selection_id": binding.selection_id,
        "correction_id": payload["correction_id"], "correction_sha256": after["sha256"], "cost_usd": after["known_cost_usd"],
        "delivery_revision": after["revision"], "delivery_sha256": after["sha256"]})
    delivery._finalize(binding, gateway)
    return {"delivery": after, "correction": payload, "historical_replay": False, "new_correction": True, "execution_sent": False}


@transaction.atomic
def review_machine(gateway_token, binding_ref, **value):
    gateway = delivery.authenticate_gateway(gateway_token)
    binding = delivery._binding(gateway, binding_ref)
    return _review(binding, gateway, {"gateway_ref": str(gateway.reference), "gateway_id": gateway.gateway_id}, value)


@transaction.atomic
def correct_machine(gateway_token, binding_ref, expected_assessment, **value):
    gateway = delivery.authenticate_gateway(gateway_token)
    binding = delivery._binding(gateway, binding_ref)
    def recheck():
        fresh = delivery.authenticate_gateway(gateway_token)
        delivery._binding(fresh, binding_ref)
    return _apply(binding, gateway, {"gateway_ref": str(gateway.reference), "gateway_id": gateway.gateway_id}, value, expected_assessment, recheck)


def _human_binding(member, reference):
    binding = DeliveryBinding.objects.select_related("connector_task__task", "gateway__company", "runtime__authorization").filter(
        reference=delivery.connectors.uuid_value(str(reference)), connector_task__task__company=member.company).first()
    if binding is None:
        raise PermissionDenied("Cost correction is outside this administrator's company.")
    return binding


@transaction.atomic
def review_human(request, binding_ref, **value):
    member = current_member(request.user, "manage")
    from .mfa import require_request_mfa
    require_request_mfa(request, member.user)
    binding = _human_binding(member, binding_ref)
    return _review(binding, binding.gateway, member_snapshot(member), value)


def correct_human(request, password, code, binding_ref, expected_assessment, **value):
    sensitive_actor(request, password, code, "manage")
    with transaction.atomic():
        member = current_member(request.user, "manage")
        from .mfa import require_request_mfa
        require_request_mfa(request, member.user)
        actor = member_snapshot(member)
        binding = _human_binding(member, binding_ref)
        def recheck():
            fresh = current_member(request.user, "manage")
            require_request_mfa(request, fresh.user)
            if member_snapshot(fresh) != actor:
                raise PermissionDenied("Administrator authority changed during billing verification.")
        result = _apply(binding, binding.gateway, actor, value, expected_assessment, recheck)
        if result["new_correction"]:
            from .mfa import _audit
            _audit(member, "delivery_cost_correction", binding_ref=str(binding.reference), correction_id=value["correction_id"],
                   cost_usd=value["cost_usd"], execution_sent=False)
        return result
