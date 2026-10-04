"""Conditional scoped model selection/accounting, not provider transport or a live-session switch."""

from decimal import Decimal
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from engine.feedback import TaskRequest, _fingerprint, _policy_input, _timestamp
from engine.pilot import _money_total
from engine.policy import incompatibility
from engine.schemas import Policy, ValidationError, boolean, choice, integer, number, object_fields, text

from .admission_gate import AdmissionAssessment, AdmissionRequest, verify_admission
from .live_authorization import live_guard, validate_live
from .models import ConnectorTask, ScopedSelectionRuntime
from .security import sensitive_actor
from .services import current_member, member_snapshot
from .mfa import _audit, require_request_mfa


def delegated_transaction(operation):
    @wraps(operation)
    def checked(member, *args, **kwargs):
        with transaction.atomic():
            member = current_member(member.user)
            if not member.participating:
                raise PermissionDenied("Only currently participating developers may use scoped selection accounting.")
            return operation(member, *args, **kwargs)
    return checked


def _state(runtime):
    validate_live(runtime.authorization)
    data = runtime.journal
    fields = ("schema_version", "scope_sha256", "events")
    object_fields(data, fields, fields)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["scope_sha256"] != runtime.authorization.data["sha256"] or not isinstance(data["events"], list):
        raise ValidationError("Selection history differs from its exact live scope approval.")
    state = {"status": "uninitialized", "revision": 0, "decisions": {}, "settlements": {}, "claims": set()}
    previous, timestamp = None, None
    for sequence, event in enumerate(data["events"], 1):
        object_fields(event, ("sequence", "timestamp", "action", "actor", "payload", "previous_sha256", "sha256"),
                      ("sequence", "timestamp", "action", "actor", "payload", "previous_sha256", "sha256"))
        at = _timestamp(event["timestamp"])
        integer(event["sequence"], "sequence")
        if event["sequence"] != sequence or event["previous_sha256"] != previous or event["sha256"] != _fingerprint({key: value for key, value in event.items() if key != "sha256"}) or timestamp and at < timestamp:
            raise ValidationError("Selection journal sequence/time/content is inconsistent; history cannot be reset.")
        action = choice(event["action"], "selection_action", ("activate", "pause", "resume", "revoke", "rollback", "select", "claim", "settle", "monitor", "delivery_monitor", "delivery_settle", "delivery_cost_correction"))
        payload = event["payload"]
        actor = event["actor"]
        if action in ("delivery_monitor", "delivery_settle", "delivery_cost_correction"):
            # A gateway is a machine principal, not a developer or human approver.
            from .models import DeliveryBinding, GatewayCredential
            from .delivery import state as delivery_state
            object_fields(actor, ("gateway_ref", "gateway_id"), ("gateway_ref", "gateway_id"))
            gateway = GatewayCredential.objects.filter(reference=actor["gateway_ref"], gateway_id=actor["gateway_id"], company=runtime.authorization.company).first()
            binding = DeliveryBinding.objects.filter(reference=payload.get("binding_ref"), runtime=runtime, gateway__gateway_id=actor["gateway_id"]).first()
            if gateway is None or binding is None or binding.selection_id not in state["claims"]:
                raise ValidationError("Delivery accounting has no exact historical machine/task/claim binding.")
            if action == "delivery_monitor":
                object_fields(payload, ("reason", "binding_ref"), ("reason", "binding_ref"))
                text(payload["reason"], "reason")
                if state["status"] != "active":
                    raise ValidationError("Only active delivery can be paused by monitoring.")
                state["status"] = "paused"
            else:
                keys = ("selection_id", "cost_usd", "outcome", "binding_ref") if action == "delivery_settle" else (
                    "selection_id", "cost_usd", "binding_ref", "correction_id", "correction_sha256", "delivery_revision", "delivery_sha256")
                object_fields(payload, keys + ("delivery_revision", "delivery_sha256"), keys)
                key = payload["selection_id"]
                # Recheck the exact historical prefix, not today's corrected total.
                if "delivery_revision" in payload:
                    delivery = delivery_state(binding, revision=payload["delivery_revision"], until=at)
                    if delivery["sha256"] != payload.get("delivery_sha256") or payload["delivery_revision"] == 0 or _timestamp(binding.journal[payload["delivery_revision"] - 1]["timestamp"]) > at:
                        raise ValidationError("Selection accounting differs from its historical delivery revision.")
                else:
                    # Legacy initial settlements predate correction events. Even
                    # equal clock timestamps cannot pull a later correction back.
                    original_end = next((index for index, item in enumerate(binding.journal) if item["action"] == "correct_cost"), len(binding.journal))
                    delivery = delivery_state(binding, until=at, revision=original_end)
                rows = list(delivery["attempts"].values())
                expected_outcome = "failed" if any(row["outcome"] in ("failed", "retryable_failure") for row in rows) else "completed" if rows else "cancelled"
                if key != binding.selection_id or number(payload["cost_usd"], "cost_usd") != Decimal(delivery["known_cost_usd"]):
                    raise ValidationError("Gateway settlement differs from closed complete attempt accounting.")
                if action == "delivery_settle":
                    if key in state["settlements"] or not delivery["closed"] or delivery["unknown_attempts"] or payload["outcome"] != expected_outcome:
                        raise ValidationError("Gateway settlement differs from closed complete attempt accounting.")
                    state["settlements"][key] = {k: payload[k] for k in ("selection_id", "cost_usd", "outcome")}
                else:
                    correction = binding.journal[payload["delivery_revision"] - 1]
                    if (correction["action"] != "correct_cost" or correction["sha256"] != payload["correction_sha256"]
                        or correction["payload"]["correction_id"] != payload["correction_id"]
                        or correction["payload"]["pilot_revision"] != sequence - 1
                        or any(old["action"] == action and old["payload"].get("correction_sha256") == payload["correction_sha256"] for old in data["events"][:sequence - 1])):
                        raise ValidationError("Selection cost correction has no exact unique delivery correction.")
                    if key in state["settlements"]:
                        state["settlements"][key] = {**state["settlements"][key], "cost_usd": payload["cost_usd"]}
                if state["status"] == "active" and (expected_outcome == "failed" or Decimal(payload["cost_usd"]) > Decimal(state["decisions"][key]["reserve_usd"])):
                    state["status"] = "paused"
            state["revision"] = sequence
            previous, timestamp = event["sha256"], at
            continue
        actor_fields = ("account_id", "developer_id", "role", "active", "participating", "can_manage_company", "can_approve_pilots")
        object_fields(actor, actor_fields, actor_fields)
        integer(actor["account_id"], "account_id")
        for key in ("active", "participating", "can_manage_company", "can_approve_pilots"):
            boolean(actor[key], key)
        if actor["active"] is not True or actor["role"] not in ("junior", "developer", "senior", "admin"):
            raise ValidationError("Selection event has no permitted historical actor.")
        if action in ("activate", "pause", "resume", "revoke", "rollback"):
            if actor["role"] not in ("senior", "admin") or actor["can_approve_pilots"] is not True:
                raise ValidationError("Selection control has no designated human authority snapshot.")
            object_fields(payload, ("reason",), ("reason",))
            text(payload["reason"], "reason")
        elif actor["participating"] is not True:
            raise ValidationError("Selection/accounting event has no participating developer snapshot.")
        if action == "activate":
            if sequence != 1:
                raise ValidationError("Selection activation cannot restart lifetime accounting.")
            state["status"] = "active"
        elif action in ("pause", "resume", "revoke", "rollback"):
            if action == "pause" and state["status"] != "active" or action == "resume" and state["status"] != "paused" or action in ("revoke", "rollback") and state["status"] not in ("active", "paused"):
                raise ValidationError("Invalid selection control transition.")
            if action == "resume" and any(item["outcome"] == "failed" or Decimal(item["cost_usd"]) > Decimal(state["decisions"][key]["reserve_usd"])
                                          for key, item in state["settlements"].items()):
                raise ValidationError("Recorded failure/overrun requires a new scope, not unchanged resume.")
            if action == "resume":
                from .delivery import resume_blocked
                if resume_blocked(runtime, at=at):
                    raise ValidationError("Unknown/failed delivery obligations forbid unchanged resume.")
            state["status"] = {"pause": "paused", "resume": "active", "revoke": "revoked", "rollback": "rolled_back"}[action]
        elif action == "monitor":
            object_fields(payload, ("reason", "connector_task_ref"), ("reason", "connector_task_ref"))
            text(payload["reason"], "reason")
            if state["status"] != "active":
                raise ValidationError("Only active selection can be paused by new monitoring evidence.")
            state["status"] = "paused"
        elif action == "select":
            record_fields = ("selection_id", "identity", "request", "model", "reserve_usd", "assessment", "admission_request", "scope_sha256", "policy_sha256", "selected_at", "override", "connector_task_ref")
            object_fields(payload, record_fields, record_fields)
            key = payload["selection_id"]
            request = payload["request"]
            request_fields = ("selection_id", "task", "repository_ref", "boundary", "reserve_usd", "override_model")
            object_fields(request, request_fields, request_fields)
            task = TaskRequest.from_dict(request["task"])
            proof = AdmissionAssessment.from_dict(payload["assessment"])
            check = AdmissionRequest(**payload["admission_request"])
            if (task.developer_id != actor["developer_id"] or payload["scope_sha256"] != data["scope_sha256"]
                or check.selection_request_sha256 != _fingerprint(request) or check.scope_record_sha256 != data["scope_sha256"]
                or check.sha256 != proof.request_sha256 or check.company_id != runtime.authorization.data["company_id"]
                or check.deployment_id != runtime.authorization.data["deployment_id"]
                or check.model_id != payload["model"] or check.commitment_usd != payload["reserve_usd"]
                or not _timestamp(proof.verified_at) <= at < _timestamp(proof.valid_until)
                or payload["selection_id"] != request["selection_id"]
                or payload["identity"] != _fingerprint({"developer_id": task.developer_id, "session_id": task.session_id, "task_id": task.task_id})
                or boolean(payload["override"], "override") != (request["override_model"] is not None)):
                raise ValidationError("Selection scope/actor/admission evidence is inconsistently bound.")
            scope = runtime.authorization.data["scope"]
            route = next((row for row in runtime.authorization.data["routes"] if row["task_type"] == task.task_type), None)
            policy = Policy.from_dict(runtime.authorization.data["policy"]["policy"])
            # Replay historical admission against its then-current reservations,
            # not delayed obligations that arrived after this event.
            totals = accounting(runtime, state, include_delivery=False)
            reserve = number(payload["reserve_usd"], "reserve_usd")
            if (route is None or task.developer_id not in scope["developer_ids"] or request["repository_ref"] != scope["repository_ref"]
                or request["boundary"] != "new_task" or set(task.risk_tags) != {"low"}
                or payload["model"] != (request["override_model"] or route["model"])
                or payload["policy_sha256"] != policy.fingerprint() or reserve <= 0
                or reserve != number(request["reserve_usd"], "reserve_usd") or totals["remaining_task_slots"] <= 0
                or reserve > Decimal(totals["remaining_usd"]) or incompatibility(policy.model(payload["model"]), _policy_input(task, policy))):
                raise ValidationError("Selection journal contains an invalid route/scope/compatibility/budget decision.")
            if key in state["decisions"] or any(item["identity"] == payload["identity"] or item["assessment"]["boundary_ref"] == proof.boundary_ref for item in state["decisions"].values()):
                raise ValidationError("Selection/task identity was reused; budget cannot be reserved twice.")
            if state["status"] != "active":
                raise ValidationError("Selection requires active runtime state.")
            state["decisions"][key] = payload
        elif action == "claim":
            object_fields(payload, ("selection_id", "assessment_sha256"), ("selection_id", "assessment_sha256"))
            key = payload["selection_id"]
            if key not in state["decisions"] or key in state["claims"] or key in state["settlements"] or state["status"] != "active":
                raise ValidationError("Selection claim is missing, already consumed, settled, or inactive.")
            if payload["assessment_sha256"] != _fingerprint(state["decisions"][key]["assessment"]):
                raise ValidationError("Selection claim differs from its original admission assessment.")
            assessment = state["decisions"][key]["assessment"]
            if not _timestamp(assessment["verified_at"]) <= at < _timestamp(assessment["valid_until"]):
                raise ValidationError("Selection claim outlived its trusted boundary/cap assessment.")
            state["claims"].add(key)
        else:
            object_fields(payload, ("selection_id", "cost_usd", "outcome"), ("selection_id", "cost_usd", "outcome"))
            key = payload["selection_id"]
            if key not in state["decisions"] or key in state["settlements"]:
                raise ValidationError("Settlement must identify one unsettled selection reservation.")
            number(payload["cost_usd"], "cost_usd")
            choice(payload["outcome"], "outcome", ("completed", "failed", "cancelled"))
            if payload["outcome"] == "cancelled" and Decimal(payload["cost_usd"]) != 0 or payload["outcome"] == "completed" and key not in state["claims"]:
                raise ValidationError("Settlement contradicts incurred cost or unclaimed delivery.")
            state["settlements"][key] = payload
            if state["status"] == "active" and (payload["outcome"] == "failed" or Decimal(payload["cost_usd"]) > Decimal(state["decisions"][key]["reserve_usd"])):
                state["status"] = "paused"
        if action in ("claim", "settle") and state["decisions"][payload["selection_id"]]["request"]["task"]["developer_id"] != actor["developer_id"]:
            raise ValidationError("Selection claim/settlement actor differs from the owning developer.")
        state["revision"] = sequence
        previous, timestamp = event["sha256"], at
    return state


def accounting(runtime, state=None, include_delivery=True):
    state = state or _state(runtime)
    scope = runtime.authorization.data["scope"]
    pending = {key: row for key, row in state["decisions"].items() if key not in state["settlements"]}
    from .models import DeliveryBinding
    from .delivery import state as delivery_state
    deliveries = {row.selection_id: delivery_state(row) for row in DeliveryBinding.objects.filter(runtime=runtime)} if include_delivery else {}
    spent = _money_total([Decimal(deliveries[key]["known_cost_usd"] if key in deliveries else row["cost_usd"]) for key, row in state["settlements"].items()])
    obligations = {key: Decimal(row["obligation_usd"]) for key, row in deliveries.items() if key in pending}
    held = _money_total([max(Decimal(row["reserve_usd"]), obligations.get(key, Decimal(0))) for key, row in pending.items()])
    committed = _money_total([spent, held])
    return {"selected_tasks": len(state["decisions"]), "claimed_tasks": len(state["claims"]), "pending_tasks": len(pending),
            "settled_tasks": len(state["settlements"]), "spent_usd": str(spent), "reserved_usd": str(held),
            "committed_usd": str(committed), "remaining_usd": str(_money_total([Decimal(scope["max_cost_usd"]), committed.copy_negate()])),
            "remaining_task_slots": scope["max_tasks"] - len(state["decisions"])}


def _append(runtime, member, action, payload):
    events = runtime.journal["events"]
    event = {"sequence": len(events) + 1, "timestamp": timezone.now().isoformat(), "action": action,
             "actor": member_snapshot(member), "payload": payload, "previous_sha256": events[-1]["sha256"] if events else None}
    event["sha256"] = _fingerprint(event)
    runtime.journal = {**runtime.journal, "events": events + [event]}
    _state(runtime)
    runtime.save(update_fields=("journal",))


def activate(request, password, code, reference, reason, expected_revision=0):
    sensitive_actor(request, password, code, "approve")
    with transaction.atomic():
        from .authorization import _pilot
        member = current_member(request.user, "approve")
        require_request_mfa(request, member.user)
        approval = _pilot(member, reference)
        if type(expected_revision) is not int or expected_revision != 0:
            raise ValidationError("Conditional activation must be reviewed at unactivated revision zero.")
        if approval.data.get("target") != "live":
            raise ValidationError("Simulation approval cannot enable conditional live model selection.")
        guard = live_guard(approval, member.company)
        if guard["status"] != "current":
            raise ValidationError(guard["reason"])
        if ScopedSelectionRuntime.objects.filter(authorization=approval).exists():
            raise ValidationError("Selection runtime already exists; activation cannot reset its budget/history.")
        for other in ScopedSelectionRuntime.objects.filter(authorization__company=member.company).select_related("authorization"):
            if _state(other)["status"] in ("active", "paused"):
                raise ValidationError("Another selection pilot is active/paused; end it before starting another.")
        runtime = ScopedSelectionRuntime.objects.create(authorization=approval,
            journal={"schema_version": 1, "scope_sha256": approval.data["sha256"], "events": []})
        _append(runtime, member, "activate", {"reason": text(reason, "reason")})
        _audit(member, "selection_activate", scope_ref=str(reference), execution_sent=False)
        return runtime


def control(request, password, code, reference, action, expected_revision, reason):
    sensitive_actor(request, password, code, "approve")
    with transaction.atomic():
        from .authorization import _pilot
        member = current_member(request.user, "approve")
        require_request_mfa(request, member.user)
        approval = _pilot(member, reference)
        runtime = ScopedSelectionRuntime.objects.select_related("authorization").filter(authorization=approval).first()
        if runtime is None:
            raise ValidationError("No conditional selection runtime is activated.")
        state = _state(runtime)
        if type(expected_revision) is not int or expected_revision != state["revision"]:
            raise ValidationError("Selection runtime changed; reload before stale control.")
        choice(action, "action", ("pause", "resume", "revoke", "rollback"))
        if action == "resume":
            from .delivery import resume_blocked
            if resume_blocked(runtime):
                raise ValidationError("Unknown/failed delivery obligations forbid unchanged resume.")
            if live_guard(approval, member.company, allow_future_recommendations=True)["status"] != "current":
                raise ValidationError("Current live scope/readiness is required for resume.")
        _append(runtime, member, action, {"reason": text(reason, "reason")})
        if action in ("revoke", "rollback") and approval.revoked_at is None:
            from .live_authorization import reverse_live
            reverse_live(member, approval, action, approval.authorization_revision, reason)


@delegated_transaction
def select(member, reference, value, connector_link=None):
    """Called inside a serialized trusted service transaction; this never dispatches a model."""
    from .operations import require_collection_open
    require_collection_open(member.company)
    from .authorization import _pilot
    approval = _pilot(member, reference)
    if approval.data.get("target") != "live":
        raise ValidationError("Only separately approved live scope can enter conditional selection.")
    runtime = ScopedSelectionRuntime.objects.select_related("authorization").filter(authorization=approval).first()
    if runtime is None:
        raise ValidationError("Separately activate conditional selection after reviewing exact live scope.")
    fields = ("selection_id", "task", "repository_ref", "boundary", "reserve_usd", "override_model")
    data = dict(object_fields(value, fields, fields))
    _fingerprint(data)
    task = TaskRequest.from_dict(data["task"])
    text(data["selection_id"], "selection_id")
    text(data["repository_ref"], "repository_ref")
    choice(data["boundary"], "boundary", ("new_task", "new_run", "subagent", "continuation"))
    if data["override_model"] is not None:
        text(data["override_model"], "override_model")
    if not member.participating or task.developer_id != member.developer_id:
        raise PermissionDenied("Selection belongs to a different developer/collection scope.")
    state = _state(runtime)
    existing = state["decisions"].get(data["selection_id"])
    if existing:
        if existing["request"] != data:
            raise ValidationError("Selection retry changed immutable boundary/model/reservation data.")
        if existing["connector_task_ref"] != (str(connector_link.reference) if connector_link else None):
            raise ValidationError("Selection retry changed its linked connector task.")
        return {"historical_replay": True, "selection": existing, "new_reservation": False, "execution_authorized": False, "routing_enabled": False}
    if connector_link is not None:
        from .tasks import task_ledger
        if (connector_link.task.owner_id != member.user_id or connector_link.closed_at or connector_link.sequence != 0
            or connector_link.task.repository_ref != data["repository_ref"] or connector_link.task.source_kind != "team"
            or task_ledger(connector_link.task).recommendations[0].task.to_dict() != data["task"]):
            raise ValidationError("Conditional selection must precede observed activity on the exact owned linked task.")
    policy = Policy.from_dict(member.company.policy)
    issue = None
    scope = approval.data["scope"]
    route = next((row for row in approval.data["routes"] if row["task_type"] == task.task_type), None)
    model = data["override_model"] or (route["model"] if route else policy.default_model)
    guard = live_guard(approval, member.company, allow_future_recommendations=True, tool_task_types=(task.task_type,))
    money = accounting(runtime, state)
    reserve = number(data["reserve_usd"], "reserve_usd") if data["reserve_usd"] is not None else None
    if guard["status"] != "current": issue = guard["reason"]
    elif state["status"] != "active": issue = "Selection pilot is not active."
    elif data["boundary"] != "new_task": issue = "Only a verified new task is a supported selection boundary."
    elif data["repository_ref"] != scope["repository_ref"] or member.developer_id not in scope["developer_ids"]: issue = "Developer/repository is outside exact live scope."
    elif route is None or set(task.risk_tags) != {"low"}: issue = "Category/risk is outside exact evidenced scope."
    elif reserve is None or reserve <= 0: issue = "Unknown/zero provider commitment cannot reserve selection budget."
    elif money["remaining_task_slots"] <= 0 or reserve > Decimal(money["remaining_usd"]): issue = "Reviewed lifetime task/budget capacity is exhausted."
    elif incompatibility(policy.model(model), _policy_input(task, policy)): issue = "Selected/overridden model is not approved and compatible."
    if issue:
        fallback_issue = incompatibility(policy.model(policy.default_model), _policy_input(task, policy))
        return {"status": "blocked" if fallback_issue else "fallback", "fallback_model": None if fallback_issue else policy.default_model,
                "reason": issue + (" Fallback is also incompatible: " + fallback_issue if fallback_issue else ""),
                "new_reservation": False, "execution_authorized": False, "routing_enabled": False}
    admission = AdmissionRequest(str(member.company.company_id), str(member.company.deployment_id), approval.data["sha256"], _fingerprint(data), data, model, str(reserve))
    proof = verify_admission(admission)
    approval.refresh_from_db()
    fresh_member = current_member(member.user)
    if member_snapshot(fresh_member) != member_snapshot(member) or live_guard(approval, fresh_member.company, allow_future_recommendations=True, tool_task_types=(task.task_type,))["status"] != "current":
        raise ValidationError("Scope changed during admission verification; no reservation was created.")
    identity = _fingerprint({"developer_id": member.developer_id, "session_id": task.session_id, "task_id": task.task_id})
    if any(row["identity"] == identity or row["assessment"]["boundary_ref"] == proof.boundary_ref for row in state["decisions"].values()):
        raise ValidationError("Trusted boundary/task already consumed lifetime scope; cannot reserve again under another ID.")
    for other in ScopedSelectionRuntime.objects.filter(authorization__company=member.company).exclude(pk=runtime.pk).select_related("authorization"):
        if any(row["identity"] == identity or row["assessment"]["boundary_ref"] == proof.boundary_ref for row in _state(other)["decisions"].values()):
            raise ValidationError("This company task/boundary already has a historical selection under another pilot; do not duplicate delivery or spending.")
    record = {"selection_id": text(data["selection_id"], "selection_id"), "identity": identity, "request": data,
              "model": model, "reserve_usd": str(reserve), "assessment": proof.to_dict(), "admission_request": admission.to_dict(),
              "scope_sha256": approval.data["sha256"], "policy_sha256": policy.fingerprint(), "selected_at": timezone.now().isoformat(),
              "override": data["override_model"] is not None, "connector_task_ref": str(connector_link.reference) if connector_link else None}
    _append(runtime, member, "select", record)
    _audit(member, "selection_reserve", scope_ref=str(reference), selection_ref=data["selection_id"], model=model,
           reserve_usd=str(reserve), override=record["override"], execution_sent=False)
    return {"status": "selected", "selection": record, "new_reservation": True, "historical_replay": False,
            "execution_authorized": False, "routing_enabled": False,
            "note": "Conditional model selection only. Trusted delivery must claim this exact selection and enforce its provider cap; no request was sent."}


@delegated_transaction
def claim(member, reference, selection_id):
    from .authorization import _pilot
    approval = _pilot(member, reference)
    runtime = ScopedSelectionRuntime.objects.select_related("authorization").filter(authorization=approval).first()
    if runtime is None:
        raise ValidationError("No conditional selection runtime exists for this scope.")
    state = _state(runtime)
    row = state["decisions"].get(selection_id)
    if row is None or row["request"]["task"]["developer_id"] != member.developer_id:
        raise PermissionDenied("Selection claim is not owned by this developer.")
    if selection_id in state["claims"]:
        return {"historical_replay": True, "new_claim": False, "execution_authorized": False}
    if state["status"] != "active" or live_guard(approval, member.company, allow_future_recommendations=True, tool_task_types=(row["request"]["task"]["task_type"],))["status"] != "current" or selection_id in state["settlements"]:
        raise ValidationError("Selection runtime/scope is inactive/stale/settled; delivery is refused.")
    if row["connector_task_ref"]:
        link = ConnectorTask.objects.filter(reference=row["connector_task_ref"], task__owner=member.user).first()
        if link is None or link.sequence != 0 or link.closed_at:
            raise ValidationError("Linked task already has observed activity/close; never apply a selection to running or historical work.")
    proof = verify_admission(AdmissionRequest(**row["admission_request"]), expected=row["assessment"])
    approval.refresh_from_db()
    fresh_member = current_member(member.user)
    if member_snapshot(fresh_member) != member_snapshot(member) or live_guard(approval, fresh_member.company, allow_future_recommendations=True, tool_task_types=(row["request"]["task"]["task_type"],))["status"] != "current":
        raise ValidationError("Scope changed during one-use claim verification; no delivery claim was created.")
    _append(runtime, member, "claim", {"selection_id": selection_id, "assessment_sha256": _fingerprint(proof.to_dict())})
    _audit(member, "selection_claim", scope_ref=str(reference), selection_ref=selection_id, model=row["model"], execution_sent=False)
    return {"new_claim": True, "historical_replay": False, "model": row["model"], "max_cost_usd": row["reserve_usd"],
            "execution_authorized": False, "note": "One-use delivery claim, not proof a provider request was sent. Only the trusted adapter can bind actual delivery/cap."}


@delegated_transaction
def settle(member, reference, selection_id, cost, outcome):
    from .authorization import _pilot
    approval = _pilot(member, reference)
    runtime = ScopedSelectionRuntime.objects.select_related("authorization").filter(authorization=approval).first()
    if runtime is None:
        raise ValidationError("No conditional accounting runtime exists for this scope.")
    from .models import DeliveryBinding
    if DeliveryBinding.objects.filter(runtime=runtime, selection_id=selection_id).exists():
        raise ValidationError("Bound delivery must settle its physical attempts through the authenticated gateway; manual settlement cannot release its budget.")
    state = _state(runtime)
    row = state["decisions"].get(selection_id)
    if row is None or row["request"]["task"]["developer_id"] != member.developer_id:
        raise PermissionDenied("Only the reservation's developer can settle its accounting.")
    cost = number(cost, "cost_usd")
    choice(outcome, "outcome", ("completed", "failed", "cancelled"))
    if outcome == "cancelled" and cost != 0:
        raise ValidationError("Cancellation before delivery must have zero cost; retain incurred costs as completed/failed.")
    existing = state["settlements"].get(selection_id)
    if existing:
        if existing["cost_usd"] != str(cost) or existing["outcome"] != outcome:
            raise ValidationError("Selection settlement changed immutable accounting.")
        return accounting(runtime, state)
    if outcome == "completed" and selection_id not in state["claims"]:
        raise ValidationError("Completion cannot precede a one-use delivery claim.")
    _append(runtime, member, "settle", {"selection_id": selection_id, "cost_usd": str(cost), "outcome": outcome})
    _audit(member, "selection_settle", scope_ref=str(reference), selection_ref=selection_id, cost_usd=str(cost), outcome=outcome)
    return accounting(runtime)


def delivery_event(binding, gateway, action, payload):
    """Append machine accounting only. No human response/approval is fabricated."""
    runtime = binding.runtime
    runtime.refresh_from_db()
    current = _state(runtime)
    if action == "delivery_monitor" and current["status"] != "active":
        return
    if action == "delivery_settle" and binding.selection_id in current["settlements"]:
        existing = current["settlements"][binding.selection_id]
        if existing != payload:
            raise ValidationError("Closed gateway settlement changed; preserve immutable accounting.")
        return
    events = runtime.journal["events"]
    event = {"sequence": len(events) + 1, "timestamp": timezone.now().isoformat(), "action": action,
             "actor": {"gateway_ref": str(gateway.reference), "gateway_id": gateway.gateway_id},
             "payload": {**payload, "binding_ref": str(binding.reference)}, "previous_sha256": events[-1]["sha256"]}
    event["sha256"] = _fingerprint(event)
    runtime.journal = {**runtime.journal, "events": events + [event]}
    _state(runtime)
    runtime.save(update_fields=("journal",))


@transaction.atomic
def status(request, reference):
    from .authorization import _reviewer, _pilot
    member = _reviewer(request)
    approval = _pilot(member, reference)
    if approval.data.get("target") != "live":
        raise ValidationError("Conditional selection status requires a live scope record, not a simulation.")
    validate_live(approval)
    runtime = ScopedSelectionRuntime.objects.filter(authorization=approval).first()
    if runtime is None:
        return {"scope_record": approval, "selection_status": "unactivated", "revision": 0,
                "guard": live_guard(approval, member.company), "accounting": None, "events": []}
    state = _state(runtime)
    from .pilot_feedback import learning_freshness
    from .tasks import company_ledger
    return {"scope_record": approval, "selection_status": state["status"], "revision": state["revision"],
        "guard": live_guard(approval, member.company, allow_future_recommendations=True), "accounting": accounting(runtime, state), "events": runtime.journal["events"],
        "learning_freshness": learning_freshness(approval.review, company_ledger(member.company, approval.review.data["learner"]["plan"]["source_kind"]))}


def monitor_observation(member, link, observation):
    """Negative/gap diagnostics pause future selection without rewriting an in-flight model."""
    payload = observation["payload"]
    if not (observation["gap_count"] or observation["multiple_models"] or (payload.get("http_status") or 0) >= 400):
        return
    for runtime in ScopedSelectionRuntime.objects.filter(authorization__company=member.company).select_related("authorization"):
        scope = runtime.authorization.data["scope"]
        if scope["repository_ref"] != link.task.repository_ref or member.developer_id not in scope["developer_ids"]:
            continue
        state = _state(runtime)
        if state["status"] != "active":
            continue
        _append(runtime, member, "monitor", {"reason": "New connected task observation contains a gap, HTTP error, or multiple primary models; stop future selection for review.",
                                            "connector_task_ref": str(link.reference)})
        _audit(member, "selection_monitor_pause", scope_ref=str(runtime.authorization.reference), task_ref=str(link.task.reference),
               in_flight_model_changed=False, incurred_costs_retained=True)


def monitor_feedback(member, task):
    """Current safety can pause execution; pending learning freshness alone cannot."""
    for runtime in ScopedSelectionRuntime.objects.filter(authorization__company=member.company,
        authorization__review__data__learner__plan__source_kind=task.source_kind).select_related("authorization"):
        state = _state(runtime)
        if state["status"] != "active" or task.request["task_type"] not in runtime.authorization.data["scope"]["task_types"]:
            continue
        if live_guard(runtime.authorization, member.company, allow_future_recommendations=True)["status"] == "current":
            continue
        _append(runtime, member, "monitor", {"reason": "Current category feedback/evidence or authority failed execution safety checks. Stop future selection; preserve rejects, failures, unknowns, and costs for another review.",
                                            "connector_task_ref": str(task.reference)})
        _audit(member, "selection_feedback_pause", scope_ref=str(runtime.authorization.reference), task_ref=str(task.reference),
               in_flight_model_changed=False)
