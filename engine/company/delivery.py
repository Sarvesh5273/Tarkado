"""Authoritative attempt accounting for the existing gateway, never inference transport."""

import secrets
from abc import ABC, abstractmethod
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from engine.delivery_contract import REQUEST_KINDS, TextChatEnvelope, LocalFunctionChatEnvelope, bind_tools, delivery_envelope
from engine.feedback import _fingerprint, _timestamp
from engine.pilot import _money_total
from engine.schemas import ValidationError, boolean, choice, integer, number, object_fields, text

from . import connectors, selection
from .admission_gate import AdmissionVerifier, AdmissionAssessment
from .live_authorization import live_guard
from .mfa import require_request_mfa
from .models import DeliveryBinding, GatewayCredential, MFAState, ScopedSelectionRuntime
from .recovery import _password_ref
from .security import sensitive_actor
from .services import current_member, member_snapshot


class DeliveryVerifier(ABC):
    """Trusted operator integration: independently checked host and billing envelope.

    No browser/config booleans implement this. Installed-host rejection/retry,
    lowering, logging, credentials, ceilings/prices/extra charges and bypass paths
    need validation before returning an envelope. Both launchers leave it unset.
    This is separate from company evidence readiness and human pilot approval.
    A local-function envelope additionally requires exact definition/capability
    validation and an independently enforced client-tool boundary: no extra model
    calls, hosted charges, network/subagent inference or unbounded shell side effects.
    Function names or hashes alone cannot establish that boundary.
    """

    @abstractmethod
    def envelope(self, company_id, deployment_id, model_id) -> TextChatEnvelope:
        raise NotImplementedError


def envelope_for(company, model):
    verifier = getattr(settings, "TARKADO_DELIVERY_VERIFIER", None)
    if not isinstance(verifier, DeliveryVerifier):
        raise ValidationError("Host/billing delivery verification is unconfigured; no paid attempt is allowed.")
    try:
        envelope = verifier.envelope(str(company.company_id), str(company.deployment_id), model)
    except ValidationError:
        raise
    except Exception:
        raise ValidationError("Host/billing verification unavailable; delivery is refused.") from None
    if not isinstance(envelope, TextChatEnvelope) or envelope.model_id != model:
        raise ValidationError("Delivery verifier returned no exact typed model envelope.")
    envelope.to_dict()
    if not _timestamp(envelope.verified_at) <= timezone.now() < _timestamp(envelope.valid_until):
        raise ValidationError("Reviewed host/billing envelope expired.")
    return envelope


class NarrowDeliveryAdmissionVerifier(AdmissionVerifier):
    """Concrete descriptor admission for the fresh-session/LiteLLM source.

    Task truth is an explicit unused company descriptor, not inferred idleness.
    Its source only creates a new isolated root, never changes an active session.
    Independent host/billing validation still defaults to refusal; installing this
    class alone cannot approve a pilot, validate evidence, or permit a paid call.
    """

    def verify(self, request):
        from .models import Company, ConnectorTask
        from .tasks import task_ledger
        company = Company.objects.filter(company_id=request.company_id, deployment_id=request.deployment_id).first()
        if company is None:
            raise ValidationError("Admission names a different company/deployment.")
        request.to_dict()
        matching = []
        for link in ConnectorTask.objects.select_related("task__company", "credential__user").filter(task__company=company, task__source_kind="team", closed_at__isnull=True, sequence=0):
            if task_ledger(link.task).recommendations[0].task.to_dict() == request.selection_request["task"]:
                matching.append(link)
        if len(matching) != 1 or request.selection_request["boundary"] != "new_task":
            raise ValidationError("Only one exact unused explicit fresh-task descriptor is supported.")
        link = matching[0]
        _, member = connectors.authenticate_value(link.credential)
        envelope = bind_tools(envelope_for(company, request.model_id), request.selection_request["task"]["required_tools"])
        if (request.selection_request["repository_ref"] != link.task.repository_ref
            or request.selection_request["task"]["developer_id"] != member.developer_id):
            raise ValidationError("Task owner/repository capability differs from this delivery descriptor.")
        from .models import PilotAuthorization
        approval = PilotAuthorization.objects.filter(company=company, data__sha256=request.scope_record_sha256).first()
        if approval is None or live_guard(approval, company, allow_future_recommendations=True)["status"] != "current":
            raise ValidationError("No current separate live approval matches this delivery descriptor.")
        # Stable proof fields survive claim retries/restarts; every verification
        # rechecks current credentials, host envelope, and separate live authority.
        verified = max(link.task.events.first().timestamp, _timestamp(envelope.verified_at))
        expires = min(link.credential.expires_at, _timestamp(envelope.valid_until))
        adapter = "tarkado-litellm-functions-v2:" if isinstance(envelope, LocalFunctionChatEnvelope) else "tarkado-litellm-text-v1:"
        return AdmissionAssessment(adapter + envelope.sha256, "connector-task:" + str(link.reference), request.sha256,
            verified.isoformat(), expires.isoformat(), True, True, True, True, True)


def issue_gateway(request, password, code, gateway_id, repository, user_mapping, expires_at, expected_revision):
    sensitive_actor(request, password, code, "manage")
    with transaction.atomic():
        member = current_member(request.user, "manage")
        require_request_mfa(request, member.user)
        if member.company.revision != expected_revision or repository not in member.company.repository_refs:
            raise ValidationError("Review the current company/repository before issuing gateway access.")
        if not isinstance(user_mapping, dict) or not user_mapping or len(set(user_mapping.values())) != len(user_mapping):
            raise ValidationError("Gateway user mapping must be explicit and one-to-one.")
        from .models import Membership
        for developer, gateway_user in user_mapping.items():
            text(gateway_user, "gateway_user_ref")
            if not Membership.objects.filter(company=member.company, developer_id=developer, active=True, participating=True).exists():
                raise ValidationError("Map only current permitted developers, not a payload-supplied role.")
        now = timezone.now()
        if expires_at is None or timezone.is_naive(expires_at) or not now < expires_at <= now + timedelta(hours=24):
            raise ValidationError("Gateway identity requires an explicit expiry within 24 hours.")
        gateway_id = text(gateway_id, "gateway_id")
        if len(gateway_id) > 128:
            raise ValidationError("Gateway identifier is too long.")
        value = secrets.token_urlsafe(32)
        scope = {"company_id": str(member.company.company_id), "deployment_id": str(member.company.deployment_id),
                 "repository_ref": repository, "user_mapping": user_mapping, "issuer": member_snapshot(member),
                 "password_ref": _password_ref(member.user),
                 "mfa_generation": MFAState.objects.get(user=member.user).generation}
        gateway = GatewayCredential.objects.create(company=member.company, issuer=member.user, gateway_id=gateway_id,
            digest=connectors.digest(value), scope=scope, expires_at=expires_at)
        from .mfa import _audit
        _audit(member, "gateway_issue", gateway_ref=str(gateway.reference), gateway_id=gateway_id, repository_ref=repository,
               feedback_authority=False, pilot_authority=False)
        return gateway, value


def authenticate_gateway(value):
    if not isinstance(value, str) or len(value) != 43:
        raise PermissionDenied("Current scoped gateway identity is required.")
    gateway = GatewayCredential.objects.select_related("company", "issuer").filter(digest=connectors.digest(value)).first()
    if gateway is None or gateway.revoked_at or timezone.now() >= gateway.expires_at:
        raise PermissionDenied("Gateway identity is expired, revoked, or unknown.")
    issuer = current_member(gateway.issuer, "manage")
    if (gateway.scope["issuer"] != member_snapshot(issuer) or gateway.scope["password_ref"] != _password_ref(issuer.user)
        or gateway.scope["mfa_generation"] != MFAState.objects.get(user=issuer.user).generation
        or (gateway.scope["company_id"], gateway.scope["deployment_id"]) != (str(issuer.company.company_id), str(issuer.company.deployment_id))):
        raise PermissionDenied("Gateway issuer/company/recovery authority changed.")
    return gateway


def revoke_gateway(request, password, code, reference):
    sensitive_actor(request, password, code, "manage")
    with transaction.atomic():
        member = current_member(request.user, "manage")
        gateway = GatewayCredential.objects.filter(company=member.company, reference=reference).first()
        if gateway is None:
            raise PermissionDenied("Gateway is outside this company.")
        if gateway.revoked_at is None:
            gateway.revoked_at = timezone.now()
            gateway.save(update_fields=("revoked_at",))


@transaction.atomic
def bind(credential, member, link, scope_ref, selection_id, gateway_ref):
    # The existing independent admission/one-use claim owns new-task truth.
    # This does not convert an ordinary observer's idle check into proof.
    credential, member = connectors.authenticate_value(credential, member)
    runtime = ScopedSelectionRuntime.objects.select_related("authorization").filter(authorization__reference=scope_ref,
        authorization__company=member.company).first()
    if runtime is None:
        raise ValidationError("No separately activated conditional scope exists.")
    state = selection._state(runtime)
    row = state["decisions"].get(selection_id)
    if (row is None or row["connector_task_ref"] != str(link.reference) or link.credential_id != credential.pk
        or row["request"]["task"]["developer_id"] != member.developer_id or selection_id not in state["claims"]):
        raise PermissionDenied("Delivery must consume the exact owned linked one-use selection claim.")
    if DeliveryBinding.objects.filter(runtime=runtime, selection_id=selection_id).exists():
        raise ValidationError("Selection already bound; retries cannot mint another delivery credential.")
    if state["status"] != "active" or selection_id in state["settlements"] or link.closed_at or link.sequence != 0:
        raise ValidationError("Delivery binding must precede activity/close on a fresh task.")
    if live_guard(runtime.authorization, member.company, allow_future_recommendations=True)["status"] != "current":
        raise ValidationError("Current separate live scope/readiness is required for delivery binding.")
    gateway = GatewayCredential.objects.filter(reference=connectors.uuid_value(gateway_ref), company=member.company).first()
    if gateway is None or gateway.revoked_at or timezone.now() >= gateway.expires_at or gateway.scope["repository_ref"] != link.task.repository_ref:
        raise PermissionDenied("Current repository-scoped gateway is required.")
    gateway_user = gateway.scope["user_mapping"].get(member.developer_id)
    if not gateway_user:
        raise PermissionDenied("Administrator has not mapped this developer to a gateway-authenticated user.")
    envelope = bind_tools(envelope_for(member.company, row["model"]), row["request"]["task"]["required_tools"])
    value = secrets.token_urlsafe(32)
    data = {"schema_version": 1, "company_id": str(member.company.company_id), "deployment_id": str(member.company.deployment_id),
            "selection_sha256": _fingerprint(row), "session_ref": link.session_ref, "gateway_user_ref": gateway_user,
            "owner": member_snapshot(member), "envelope": envelope.to_dict(), "task_cap_usd": row["reserve_usd"]}
    binding = DeliveryBinding.objects.create(connector_task=link, runtime=runtime, gateway=gateway, selection_id=selection_id,
        digest=connectors.digest(value), data=data)
    result = {"binding_ref": str(binding.reference), "task_token": value, "model": envelope.model_id,
            "gateway_model": envelope.gateway_model, "provider_model": envelope.provider_model, "session_ref": link.session_ref,
            "task_cap_usd": row["reserve_usd"], "envelope_sha256": envelope.sha256, "execution_sent": False}
    if isinstance(envelope, LocalFunctionChatEnvelope):
        result["local_tools"] = [tool.to_dict() for tool in envelope.local_tools]
        result["local_execution_evidence_ref"] = envelope.local_execution_evidence_ref
    return result


def _binding(gateway, reference):
    binding = DeliveryBinding.objects.select_related("connector_task__task__company", "connector_task__credential__user",
        "runtime__authorization", "gateway").filter(reference=connectors.uuid_value(reference), gateway__company=gateway.company,
        gateway__gateway_id=gateway.gateway_id).first()
    if binding is None or gateway.scope["repository_ref"] != binding.connector_task.task.repository_ref:
        raise PermissionDenied("Gateway cannot access this task binding.")
    if gateway.scope["user_mapping"].get(binding.data["owner"]["developer_id"]) != binding.data["gateway_user_ref"]:
        raise PermissionDenied("Gateway has no approved mapping to this historical task owner.")
    return binding


def _current(gateway, binding, task_token, session_ref, retry_request_id=None):
    if not isinstance(task_token, str) or gateway.pk != binding.gateway_id or not secrets.compare_digest(connectors.digest(task_token), binding.digest) or session_ref != binding.data["session_ref"]:
        raise PermissionDenied("Wrong task, session, or gateway delivery credential.")
    credential = binding.connector_task.credential
    connectors.authenticate_value(credential, None)
    runtime = binding.runtime
    selected_state = selection._state(runtime)
    row = selected_state["decisions"].get(binding.selection_id)
    if row is None or _fingerprint(row) != binding.data["selection_sha256"] or binding.selection_id not in selected_state["claims"]:
        raise ValidationError("Delivery binding differs from its original selection/claim.")
    prior = [attempt for attempt in state(binding)["attempts"].values() if attempt["request_id"] == retry_request_id]
    retry_ref = str(binding.reference) if prior and all(attempt["outcome"] == "retryable_failure" and attempt["cost_usd"] is not None for attempt in prior) else None
    if (selected_state["status"] != "active" or binding.selection_id in selected_state["settlements"] or binding.connector_task.closed_at
        or live_guard(runtime.authorization, gateway.company, allow_future_recommendations=True, delivery_retry_ref=retry_ref)["status"] != "current"):
        raise ValidationError("Delivery is paused, withdrawn, closed, settled, or stale; never switch its model.")
    envelope = bind_tools(envelope_for(gateway.company, row["model"]), row["request"]["task"]["required_tools"])
    if envelope.to_dict() != binding.data["envelope"]:
        raise ValidationError("Host/pricing/model envelope changed; no mid-task rebinding.")
    if any(row["outcome"] == "unknown" for row in state(binding)["attempts"].values()):
        raise ValidationError("Unknown provider obligation forbids unsafe continuation, even after a requested resume.")
    return envelope


def state(binding, until=None):
    data = binding.data
    fields = ("schema_version", "company_id", "deployment_id", "selection_sha256", "session_ref", "gateway_user_ref", "owner", "envelope", "task_cap_usd")
    object_fields(data, fields, fields)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["company_id"] != str(binding.gateway.company.company_id) or data["deployment_id"] != str(binding.gateway.company.deployment_id):
        raise ValidationError("Delivery history company/deployment binding differs.")
    envelope = delivery_envelope(data["envelope"])
    cap = number(data["task_cap_usd"], "task_cap_usd")
    selected = next((event["payload"] for event in binding.runtime.journal["events"] if event["action"] == "select" and event["payload"]["selection_id"] == binding.selection_id), None)
    if (selected is None or _fingerprint(selected) != data["selection_sha256"] or selected["connector_task_ref"] != str(binding.connector_task.reference)
        or cap != Decimal(selected["reserve_usd"]) or selected["model"] != envelope.model_id
        or data["session_ref"] != binding.connector_task.session_ref or data["owner"]["account_id"] != binding.connector_task.task.owner_id
        or data["gateway_user_ref"] != binding.gateway.scope["user_mapping"].get(data["owner"]["developer_id"])):
        raise ValidationError("Delivery history differs from the original task/model/owner/budget selection.")
    requests, attempts, closed, previous, at = {}, {}, False, None, None
    events = binding.journal if until is None else [event for event in binding.journal if _timestamp(event["timestamp"]) <= until]
    for sequence, event in enumerate(events, 1):
        fields = ("sequence", "timestamp", "gateway_ref", "action", "payload", "previous_sha256", "sha256")
        object_fields(event, fields, fields)
        if event["sequence"] != sequence or event["previous_sha256"] != previous or event["sha256"] != _fingerprint({k: v for k, v in event.items() if k != "sha256"}):
            raise ValidationError("Delivery journal is inconsistent; never reset evidence.")
        now = _timestamp(event["timestamp"])
        if at and now < at:
            raise ValidationError("Delivery ingestion time is out of order.")
        gateway = GatewayCredential.objects.filter(reference=event["gateway_ref"], company=binding.gateway.company, gateway_id=binding.gateway.gateway_id).first()
        if gateway is None:
            raise ValidationError("Delivery event has no bound historical machine identity.")
        action, payload = event["action"], event["payload"]
        if action == "request":
            keys = ("request_id", "kind", "output_limit", "stream")
            object_fields(payload, keys, keys)
            connectors.uuid_value(payload["request_id"])
            choice(payload["kind"], "request_kind", REQUEST_KINDS)
            boolean(payload["stream"], "stream")
            envelope.maximum(payload["output_limit"])
            if closed or payload["request_id"] in requests:
                raise ValidationError("Logical delivery request is duplicate or task is closed.")
            requests[payload["request_id"]] = payload
        elif action == "attempt":
            keys = ("attempt_id", "request_id", "reserve_usd")
            object_fields(payload, keys, keys)
            connectors.uuid_value(payload["attempt_id"])
            request = requests.get(payload["request_id"])
            prior = [row for row in attempts.values() if row["request_id"] == payload["request_id"]]
            held = _money_total([number(row["reserve_usd"], "reserve_usd") if row["cost_usd"] is None else number(row["cost_usd"], "cost_usd") for row in attempts.values()])
            if closed or request is None or payload["attempt_id"] in attempts or any(row["outcome"] != "retryable_failure" or row["cost_usd"] is None for row in prior):
                raise ValidationError("Duplicate/unresolved/completed logical request cannot authorize another physical attempt.")
            reserve = envelope.maximum(request["output_limit"])
            if reserve <= 0 or Decimal(payload["reserve_usd"]) != reserve or _money_total([held, reserve]) > cap:
                raise ValidationError("Physical attempt has no justified pre-execution task budget reservation.")
            attempts[payload["attempt_id"]] = {**payload, "cost_usd": None, "usage": None, "outcome": "pending", "latency_ms": None, "evidence_ref": None, "actual_model": None, "billing_assessment": None}
        elif action == "settle":
            keys = ("attempt_id", "cost_usd", "usage", "outcome", "latency_ms", "evidence_ref", "actual_model", "billing_assessment")
            object_fields(payload, keys, keys)
            row = attempts.get(payload["attempt_id"])
            if row is None or row["cost_usd"] is not None:
                raise ValidationError("Settlement is missing or tries to replace known immutable accounting.")
            choice(payload["outcome"], "outcome", ("completed", "failed", "retryable_failure", "cancelled", "unknown"))
            if payload["cost_usd"] is None:
                if payload["outcome"] != "unknown" or payload["usage"] is not None:
                    raise ValidationError("Unknown obligation cannot become zero or a successful usage label.")
            else:
                number(payload["cost_usd"], "cost_usd")
                if payload["outcome"] == "unknown":
                    raise ValidationError("Known settlement must declare its accounting outcome.")
                text(payload["evidence_ref"], "evidence_ref")
                if payload["usage"] is not None:
                    envelope.cost(payload["usage"])
                calculated = payload["usage"] is not None and payload["actual_model"] == envelope.provider_model and Decimal(payload["cost_usd"]) == envelope.cost(payload["usage"])
                if not calculated:
                    from .billing_gate import BillingAssessment, reconciliation_request
                    assessment = BillingAssessment.from_dict(payload["billing_assessment"])
                    if assessment.request_sha256 != _fingerprint(reconciliation_request(binding, row, payload)) or not _timestamp(assessment.verified_at) <= now < _timestamp(assessment.valid_until):
                        raise ValidationError("External reconciled cost has no exact historical billing proof.")
                if payload["outcome"] == "cancelled" and Decimal(payload["cost_usd"]) != 0:
                    raise ValidationError("Cancellation before execution cannot erase incurred cost.")
            if payload["latency_ms"] is not None:
                integer(payload["latency_ms"], "latency_ms")
            if payload["actual_model"] is not None:
                text(payload["actual_model"], "actual_model")
            row.update(payload)
        elif action == "close":
            object_fields(payload, (), ())
            if closed:
                raise ValidationError("Delivery task is already permanently closed.")
            closed = True
        else:
            raise ValidationError("Unsupported delivery history action.")
        previous, at = event["sha256"], now
    spent = _money_total([number(row["cost_usd"], "cost_usd") for row in attempts.values() if row["cost_usd"] is not None])
    held = _money_total([number(row["reserve_usd"], "reserve_usd") for row in attempts.values() if row["cost_usd"] is None])
    return {"requests": requests, "attempts": attempts, "closed": closed or binding.connector_task.closed_at is not None, "known_cost_usd": str(spent),
            "unknown_attempts": sum(row["cost_usd"] is None for row in attempts.values()), "attempt_reserved_usd": str(held),
            "remaining_task_usd": str(_money_total([cap, spent.copy_negate(), held.copy_negate()])),
            "obligation_usd": str(max(cap, _money_total([spent, held])))}


def _append(binding, gateway, action, payload):
    event = {"sequence": len(binding.journal) + 1, "timestamp": timezone.now().isoformat(), "gateway_ref": str(gateway.reference),
             "action": action, "payload": payload, "previous_sha256": binding.journal[-1]["sha256"] if binding.journal else None}
    event["sha256"] = _fingerprint(event)
    binding.journal = binding.journal + [event]
    state(binding)
    binding.save(update_fields=("journal",))


def resume_blocked(runtime, at=None):
    for binding in DeliveryBinding.objects.filter(runtime=runtime):
        if at is not None and not any(event["action"] == "select" and event["payload"]["selection_id"] == binding.selection_id and _timestamp(event["timestamp"]) <= at for event in runtime.journal["events"]):
            continue
        current = state(binding, until=at)
        if any(row["outcome"] in ("unknown", "failed") for row in current["attempts"].values()) or Decimal(current["remaining_task_usd"]) < 0:
            return True
    return False


@transaction.atomic
def begin_request(gateway_token, task_token, binding_ref, session_ref, gateway_user_ref, request_id, kind, output_limit, stream):
    gateway = authenticate_gateway(gateway_token)
    binding = _binding(gateway, binding_ref)
    _current(gateway, binding, task_token, session_ref)
    if gateway_user_ref != binding.data["gateway_user_ref"]:
        raise PermissionDenied("Authenticated LiteLLM user differs from administrator-mapped task owner.")
    _append(binding, gateway, "request", {"request_id": request_id, "kind": kind, "output_limit": output_limit, "stream": stream})
    return {"binding_ref": str(binding.reference), "request_id": request_id, "envelope": binding.data["envelope"]}


@transaction.atomic
def admit_attempt(gateway_token, task_token, binding_ref, session_ref, request_id, attempt_id, provider_model, output_limit, stream):
    gateway = authenticate_gateway(gateway_token)
    binding = _binding(gateway, binding_ref)
    envelope = _current(gateway, binding, task_token, session_ref, retry_request_id=request_id)
    request = state(binding)["requests"].get(request_id)
    if request is None or provider_model != envelope.provider_model or (request["output_limit"], request["stream"]) != (output_limit, stream):
        raise ValidationError("Physical provider model/request differs from its exact logical request binding.")
    _append(binding, gateway, "attempt", {"attempt_id": attempt_id, "request_id": request_id, "reserve_usd": str(envelope.maximum(output_limit))})
    return {"attempt_id": attempt_id, "reserve_usd": str(envelope.maximum(output_limit)), "provider_model": envelope.provider_model}


@transaction.atomic
def settle_attempt(gateway_token, binding_ref, attempt_id, cost_usd, usage, outcome, latency_ms, evidence_ref, actual_model=None):
    # Current machine authentication remains required. Renewal with the same
    # scoped gateway identity may reconcile old obligations, never revive delivery.
    gateway = authenticate_gateway(gateway_token)
    binding = _binding(gateway, binding_ref)
    before = state(binding)
    row = before["attempts"].get(attempt_id)
    if row is None:
        raise ValidationError("Settlement must identify a reserved physical attempt.")
    payload = {"attempt_id": attempt_id, "cost_usd": cost_usd, "usage": usage, "outcome": outcome,
               "latency_ms": latency_ms, "evidence_ref": evidence_ref, "actual_model": actual_model}
    if cost_usd is not None and not isinstance(cost_usd, str):
        raise ValidationError("Actual cost must be an exact decimal string, never a float.")
    if any(event["action"] == "settle" and {k: v for k, v in event["payload"].items() if k != "billing_assessment"} == payload for event in binding.journal):
        return before
    envelope = delivery_envelope(binding.data["envelope"])
    payload["billing_assessment"] = None
    if cost_usd is not None and not (usage is not None and actual_model == envelope.provider_model and number(cost_usd, "cost_usd") == envelope.cost(usage)):
        from .billing_gate import verify, reconciliation_request
        payload["billing_assessment"] = verify(reconciliation_request(binding, row, payload))
    _append(binding, gateway, "settle", payload)
    after = state(binding)
    request = after["requests"][row["request_id"]]
    bound_broken = actual_model not in (None, envelope.provider_model) or usage is not None and (usage["input_tokens"] > envelope.input_token_ceiling or usage["output_tokens"] > request["output_limit"])
    if cost_usd is None or outcome == "failed" or Decimal(after["remaining_task_usd"]) < 0 or bound_broken:
        selection.delivery_event(binding, gateway, "delivery_monitor", {"reason": "Unknown/failed/overrun provider obligation; refuse future paid attempts and preserve settlement."})
    _finalize(binding, gateway)
    return after


@transaction.atomic
def close_delivery(gateway_token, binding_ref):
    gateway = authenticate_gateway(gateway_token)
    binding = _binding(gateway, binding_ref)
    if not state(binding)["closed"]:
        _append(binding, gateway, "close", {})
    _finalize(binding, gateway)
    return state(binding)


def _finalize(binding, gateway):
    current = state(binding)
    if not current["closed"] or current["unknown_attempts"]:
        return
    rows = list(current["attempts"].values())
    outcome = "failed" if any(row["outcome"] in ("failed", "retryable_failure") for row in rows) else "completed" if rows else "cancelled"
    selection.delivery_event(binding, gateway, "delivery_settle", {"selection_id": binding.selection_id, "cost_usd": current["known_cost_usd"], "outcome": outcome})
