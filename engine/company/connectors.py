"""Scoped delegated observation, never provider credentials, model calls, or pilot authority."""

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from engine.privacy import ensure_safe
from engine.schemas import Policy, ValidationError, boolean, choice, integer, object_fields, text

from .mfa import _audit, _fresh_password, mfa_required, require_request_mfa
from .models import CompanyTask, ConnectorCredential, ConnectorObservation, ConnectorTask, MFAState
from .recovery import _password_ref
from .services import CONNECTOR_FIELDS, current_member, member_snapshot
from .tasks import (_participant, _scope, get_task, recommend_task, record_execution, record_response, record_result, task_ledger)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def uuid_value(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Use the connector's canonical UUID reference.") from None


def issue(request, name, repository, directory, expires_at, expected_revision, password, source_kind="team"):
    _fresh_password(request, password)
    with transaction.atomic():
        member = _participant(request.user)
        require_request_mfa(request, member.user)
        if member.company.revision != expected_revision:
            raise ValidationError("Company state changed; review the connector scope again.")
        _scope(member, repository, {})
        if not set(("observation_kind", "request_kind", "coverage_status", "actual_model")).issubset(member.company.collection_fields):
            raise ValidationError("An administrator must explicitly approve connector observation fields in Policy & collection first.")
        name, directory = text(name, "connector_name"), text(directory, "directory")
        if len(name) > 128 or not directory.startswith("/") or directory.endswith("/") and directory != "/":
            raise ValidationError("Use a short connector name and an exact absolute OpenCode working directory without a trailing slash.")
        choice(source_kind, "source_kind", ("synthetic", "team"))
        now = timezone.now()
        if expires_at is None or timezone.is_naive(expires_at) or not now < expires_at <= now + timedelta(hours=24):
            raise ValidationError("Connector access requires an explicit expiry within 24 hours; renew through browser authentication.")
        scope = {"repository_ref": repository, "location_sha256": digest(directory), "source_kind": source_kind,
                 "collection_fields": list(member.company.collection_fields), "member": member_snapshot(member),
                 "password_ref": _password_ref(member.user), "mfa_generation": MFAState.objects.filter(user=member.user).values_list("generation", flat=True).first() or 0,
                 "mfa_required": mfa_required(member), "company_id": str(member.company.company_id), "deployment_id": str(member.company.deployment_id)}
        value = secrets.token_urlsafe(32)
        credential = ConnectorCredential.objects.create(company=member.company, user=member.user, digest=digest(value),
            name=name, scope=scope, issued_at=now, expires_at=expires_at)
        _audit(member, "connector_issue", connector_ref=str(credential.reference), repository_ref=repository,
               expires_at=expires_at.isoformat(), source_kind=source_kind, delegated_observation_only=True)
        return credential, value


def authenticate(value):
    # Called inside the same writer transaction as every delegated operation.
    if not isinstance(value, str) or len(value) != 43:
        raise PermissionDenied("Connector verification failed; pair again through your browser.")
    credential = ConnectorCredential.objects.select_related("user", "company").filter(digest=digest(value)).first()
    if credential is None or credential.revoked_at or timezone.now() >= credential.expires_at:
        raise PermissionDenied("Connector verification failed; pair again through your browser.")
    member = _participant(credential.user)
    scope = credential.scope
    if member_snapshot(member) != scope["member"] or _password_ref(member.user) != scope["password_ref"]:
        raise PermissionDenied("Connector account permission or recovery changed; pair again.")
    generation = MFAState.objects.filter(user=member.user).values_list("generation", flat=True).first() or 0
    if generation != scope["mfa_generation"] or mfa_required(member) != scope["mfa_required"] or (
        scope["mfa_required"] and not TOTPDevice.objects.filter(user=member.user, confirmed=True).exists()
    ):
        raise PermissionDenied("Connector MFA/recovery changed; pair again through the browser.")
    if (scope["company_id"], scope["deployment_id"]) != (str(member.company.company_id), str(member.company.deployment_id)):
        raise PermissionDenied("Connector belongs to another company/deployment.")
    _scope(member, scope["repository_ref"], {})
    if not set(scope["collection_fields"]).issubset(member.company.collection_fields):
        raise PermissionDenied("Approved connector collection scope was reduced; pair again.")
    return credential, member


def authenticate_value(credential, member=None):
    """Recheck an already resolved delegation without retaining its usable token."""
    credential.refresh_from_db()
    if credential.revoked_at or timezone.now() >= credential.expires_at:
        raise PermissionDenied("Connector delivery delegation expired or was revoked.")
    current = _participant(credential.user)
    scope = credential.scope
    if (member_snapshot(current) != scope["member"] or _password_ref(current.user) != scope["password_ref"]
        or (MFAState.objects.filter(user=current.user).values_list("generation", flat=True).first() or 0) != scope["mfa_generation"]
        or mfa_required(current) != scope["mfa_required"]
        or scope["mfa_required"] and not TOTPDevice.objects.filter(user=current.user, confirmed=True).exists()
        or (scope["company_id"], scope["deployment_id"]) != (str(current.company.company_id), str(current.company.deployment_id))
        or not set(scope["collection_fields"]).issubset(current.company.collection_fields)):
        raise PermissionDenied("Connector account/company/MFA/collection scope changed.")
    _scope(current, scope["repository_ref"], {})
    return credential, current


def revoke(request, reference, password):
    _fresh_password(request, password)
    with transaction.atomic():
        member = current_member(request.user)
        require_request_mfa(request, member.user)
        query = ConnectorCredential.objects.filter(company=member.company, reference=reference)
        if not (member.role == "admin" and member.can_manage_company):
            query = query.filter(user=member.user)
        credential = query.first()
        if credential is None:
            raise PermissionDenied("Connector is unavailable for this account.")
        if credential.revoked_at is None:
            credential.revoked_at = timezone.now()
            credential.save(update_fields=("revoked_at",))
            _audit(member, "connector_revoke", connector_ref=str(reference), history_retained=True)


def _link(credential, reference, location):
    if credential.scope["location_sha256"] != location:
        raise PermissionDenied("Connector working directory differs from its approved pairing scope.")
    link = ConnectorTask.objects.select_related("task__company", "credential").filter(credential=credential, reference=uuid_value(reference)).first()
    if link is None:
        raise PermissionDenied("This task does not belong to the connector account/scope.")
    task_ledger(link.task)
    return link


def task_state(link):
    ledger = task_ledger(link.task)
    rows = list(link.observations.all())
    previous = 0
    for row in rows:
        ensure_safe(row.payload)
        actor = object_fields(row.actor_snapshot, ("account_id", "developer_id", "role", "active", "participating", "can_manage_company", "can_approve_pilots"),
                              ("account_id", "developer_id", "role", "active", "participating", "can_manage_company", "can_approve_pilots"))
        if (row.sequence <= previous or row.missing_before != row.sequence - previous - 1
            or actor["account_id"] != link.task.owner_id or actor["developer_id"] != link.credential.scope["member"]["developer_id"]
            or actor["role"] not in ("junior", "developer", "senior") or actor["active"] is not True or actor["participating"] is not True):
            raise ValidationError("Connector observation history is inconsistent; do not repair/reset existing records.")
        previous = row.sequence
    if previous != link.sequence or bool(link.closed_at) != bool(rows and rows[-1].payload["observation_kind"] == "close"):
        raise ValidationError("Connector sequence/close state differs from retained history.")
    models = list(dict.fromkeys(row.payload["model"] for row in rows if row.payload.get("model") and row.payload["request_kind"] == "primary"))
    gaps = sum(row.missing_before for row in rows) + sum(row.payload["observation_kind"] == "gap" for row in rows)
    incomplete = bool(gaps or not link.closed_at)
    return {"connector_task_ref": str(link.reference), "task_ref": str(link.task.reference), "task_label": link.task.task_id,
            "session_ref": link.session_ref,
            "browser_path": f"/tasks/{link.task.reference}/", "task_revision": link.task.revision, "sequence": link.sequence,
            "closed": link.closed_at is not None, "recommendation": ledger.recommendations[0].decision,
            "policy_current": Policy.from_dict(link.task.company.policy).fingerprint() == ledger.recommendations[0].policy_sha256,
            "response": ledger.responses[0].response if ledger.responses else None,
            "reported_actual_model": ledger.executions[0].actual_model if ledger.executions else None,
            "current_result": ledger.results[-1].to_dict() if ledger.results else None,
            "learning": {"version": ledger.recommendations[0].learning["plan"]["learner_version"],
                         "sha256": ledger.recommendations[0].learning["learner_sha256"]} if ledger.recommendations[0].learning else None,
            "suggestion_context": link.task.suggestion_context,
            "conditional_task_request": ledger.recommendations[0].task.to_dict(),
            "observed_attempt_models": models, "multiple_models": len(models) > 1, "observation_count": len(rows),
            "gap_count": gaps, "coverage_status": "incomplete" if incomplete else "limited_hook_coverage",
            "actual_execution_verified": False, "usage_verified": False, "outcome_verified": False,
            "routing_enabled": False, "note": "Hook observations are model attempts/status, not proof of completion. Per-request usage/cost and subagent attribution are unavailable. Outcomes remain reported."}


def start(credential, member, value):
    fields = ("client_task_id", "session_ref", "location_sha256", "task_label", "task_type", "risk_tags", "selected_model", "required_tools", "context_tokens", "boundary")
    data = object_fields(value, fields, fields)
    ensure_safe(data)
    identifier = uuid_value(data["client_task_id"])
    if data["location_sha256"] != credential.scope["location_sha256"]:
        raise PermissionDenied("OpenCode working directory is outside the paired scope.")
    if data["boundary"] != "new_task":
        raise ValidationError("Only explicit root-task starts are supported; new-run/subagent inference is not verified.")
    if not isinstance(data["session_ref"], str) or len(data["session_ref"]) != 64 or any(ch not in "0123456789abcdef" for ch in data["session_ref"]):
        raise ValidationError("Use a hashed OpenCode session reference.")
    if ConnectorTask.objects.filter(credential=credential, session_ref=data["session_ref"], closed_at__isnull=True).exclude(client_task_id=identifier).exists():
        raise ValidationError("End the previous explicit task before starting another in this session.")
    # Reuse immutable authenticated task records, without certifying delegated data as engineering truth.
    source = {"repository_ref": credential.scope["repository_ref"], "source_kind": credential.scope["source_kind"], "boundary": "new_task",
              "task_id": text(data["task_label"], "task_label"), "session_id": "oc_" + data["session_ref"],
              **{key: data[key] for key in ("task_type", "risk_tags", "selected_model", "required_tools", "context_tokens")}}
    existing = ConnectorTask.objects.filter(credential=credential, client_task_id=identifier).first()
    if existing:
        if existing.task.request != source:
            raise ValidationError("This task-start retry has changed metadata; history cannot be overwritten.")
        return task_state(existing)
    if ConnectorTask.objects.filter(credential__company=member.company, session_ref=data["session_ref"], closed_at__isnull=True,
                                     task__owner=member.user).exists():
        raise ValidationError("This account/session already has an open task under another pairing.")
    if CompanyTask.objects.filter(company=member.company, owner=member.user, session_id=source["session_id"], task_id=source["task_id"]).exists():
        raise ValidationError("This task label already names historical/manual work; a new connector boundary cannot reuse it.")
    task = recommend_task(member.user, source)
    if ConnectorTask.objects.filter(task=task).exists():
        raise ValidationError("Task labels already identify another linked record; use a distinct task label.")
    link = ConnectorTask.objects.create(credential=credential, task=task, client_task_id=identifier, session_ref=data["session_ref"])
    return task_state(link)


def observe(credential, member, value):
    data = object_fields(value, ("connector_task_ref", "location_sha256", "event_id", "sequence", "payload"),
                         ("connector_task_ref", "location_sha256", "event_id", "sequence", "payload"))
    link = _link(credential, data["connector_task_ref"], data["location_sha256"])
    payload = object_fields(data["payload"], ("observation_kind", "request_kind", "model", "http_status", "attempt", "retry", "coverage_status"),
                            ("observation_kind", "request_kind", "model", "http_status", "attempt", "retry", "coverage_status"))
    ensure_safe(payload)
    kind = choice(payload["observation_kind"], "observation_kind", ("model_attempt", "http_status", "retry", "gap", "close"))
    choice(payload["request_kind"], "request_kind", ("primary", "compaction", "title", "generate", "unknown"))
    choice(payload["coverage_status"], "coverage_status", ("limited_hook_coverage", "incomplete"))
    for field in CONNECTOR_FIELDS:
        if payload[field] is not None and field not in credential.scope["collection_fields"]:
            raise PermissionDenied("Observation includes a field outside approved collection scope.")
    if payload["model"] is not None:
        text(payload["model"], "observed_model")
        if "actual_model" not in credential.scope["collection_fields"]:
            raise PermissionDenied("Actual-model metadata is not approved for observation.")
    if payload["http_status"] is not None and not 100 <= integer(payload["http_status"], "http_status") <= 599:
        raise ValidationError("HTTP status is outside the supported range.")
    if payload["attempt"] is not None and integer(payload["attempt"], "attempt") == 0:
        raise ValidationError("Retry attempt must be positive.")
    if payload["retry"] is not None:
        boolean(payload["retry"], "retry")
    event_id, sequence = uuid_value(data["event_id"]), integer(data["sequence"], "sequence")
    if sequence == 0:
        raise ValidationError("Observation sequence starts at one.")
    existing = link.observations.filter(event_id=event_id).first()
    if existing:
        if existing.sequence != sequence or existing.payload != payload:
            raise ValidationError("Observation retry changed immutable event data.")
        return task_state(link)
    if link.closed_at or sequence <= link.sequence:
        raise ValidationError("Task closed or sequence is stale; refused events do not overwrite history.")
    if kind == "model_attempt" and not payload["model"]:
        raise ValidationError("A model attempt requires the observed model, not a guessed default.")
    if kind == "http_status" and payload["http_status"] is None:
        raise ValidationError("A response-status observation requires its actual HTTP status.")
    if kind == "retry" and (payload["attempt"] is None or payload["retry"] is None):
        raise ValidationError("A retry observation requires the observed attempt and retry decision.")
    if kind in ("gap", "close") and (payload["request_kind"] != "unknown" or any(
        payload[key] is not None for key in ("model", "http_status", "attempt", "retry")
    )):
        raise ValidationError("Gap/close controls cannot contain fabricated model/status/usage measurements.")
    ConnectorObservation.objects.create(task=link, event_id=event_id, sequence=sequence, received_at=timezone.now(),
        actor_snapshot=member_snapshot(member), payload=payload, missing_before=sequence - link.sequence - 1)
    link.sequence = sequence
    if kind == "close":
        link.closed_at = timezone.now()
    link.save(update_fields=("sequence", "closed_at"))
    state = task_state(link)
    from .selection import monitor_observation
    monitor_observation(member, link, {"payload": payload, "gap_count": state["gap_count"], "multiple_models": state["multiple_models"]})
    if kind == "close":
        from .models import DeliveryBinding
        from .delivery import _finalize
        binding = DeliveryBinding.objects.filter(connector_task=link).first()
        if binding:
            _finalize(binding, binding.gateway)
    return state


def feedback(credential, member, value):
    fields = ("connector_task_ref", "location_sha256", "action", "expected_revision", "value")
    data = object_fields(value, fields, fields)
    link = _link(credential, data["connector_task_ref"], data["location_sha256"])
    action = choice(data["action"], "action", ("response", "actual_model", "result"))
    ensure_safe(data["value"])
    revision = integer(data["expected_revision"], "expected_revision")
    state = task_state(link)
    if action == "response":
        if link.observations.exclude(payload__observation_kind__in=("gap", "close")).exists() and not state["response"]:
            raise ValidationError("A new response must precede observed model activity; unanswered remains unknown.")
        record_response(member.user, link.task.reference, data["value"], revision)
    elif action == "actual_model":
        record_execution(member.user, link.task.reference, data["value"], revision)
    else:
        result = data["value"]
        if isinstance(result, dict) and result.get("desired_result") is True and state["gap_count"]:
            raise ValidationError("Incomplete observed coverage cannot establish an adopted success; keep result unknown or report failure until separately reviewed.")
        record_result(member.user, link.task.reference, result, revision)
    link.task.refresh_from_db()
    return task_state(link)


def check_feedback_task(task, kind, value=None):
    """The browser cannot bypass connected-task gaps or reattribute a multi-model result."""
    link = ConnectorTask.objects.filter(task=task).first()
    if not link:
        return
    state = task_state(link)
    from .models import DeliveryBinding
    from .delivery import state as delivery_state
    binding = DeliveryBinding.objects.filter(connector_task=link).first()
    if binding:
        captured = delivery_state(binding)
        if kind == "response" and not state["response"] and captured["attempts"]:
            raise ValidationError("A new response must precede paid delivery attempts; unanswered stays unknown.")
        if kind == "result" and isinstance(value, dict) and value.get("desired_result") is True:
            primary = [attempt for attempt in captured["attempts"].values() if captured["requests"][attempt["request_id"]]["kind"] == "primary"]
            if (not captured["closed"] or captured["unknown_attempts"] or not state["closed"] or state["gap_count"] or state["multiple_models"]
                or not primary or any(attempt["outcome"] != "completed" or attempt["actual_model"] != binding.data["envelope"]["provider_model"] for attempt in primary)
                or state["reported_actual_model"] != binding.data["envelope"]["model_id"]):
                raise ValidationError("Incomplete/failed/wrong-model gateway attribution cannot establish one model's adopted success; preserve negative/unknown results.")
            # The new gateway path has exact independent request records; an
            # empty old hook-attempt list is not a missing gateway measurement.
            return
    if kind == "response" and not state["response"] and link.observations.exclude(payload__observation_kind__in=("gap", "close")).exists():
        raise ValidationError("A new response must precede observed model activity; unanswered remains unknown.")
    if kind == "result":
        if state["multiple_models"] and isinstance(value, dict) and value.get("desired_result") is True:
            raise ValidationError("Multiple observed models cannot establish one model's success; preserve negative/unknown reports until per-attempt attribution is supported.")
        if isinstance(value, dict) and value.get("desired_result") is True and (state["gap_count"] or not state["closed"]):
            raise ValidationError("Open/incomplete observation coverage cannot establish an adopted success. Close the explicit task; keep gaps, unknowns, and failures visible.")
        if (isinstance(value, dict) and value.get("desired_result") is True and state["observed_attempt_models"]
            and state["reported_actual_model"] not in state["observed_attempt_models"]):
            raise ValidationError("Reported actual model differs from observed primary attempts; inconsistent attribution cannot establish adopted success.")
        if isinstance(value, dict) and value.get("desired_result") is True and not state["observed_attempt_models"]:
            raise ValidationError("No primary model attempt was observed; an empty interval cannot establish adopted success.")


def end_interrupted(request, reference, expected_sequence, password):
    """Browser recovery closes an expired/unreachable connector with a permanent gap, not fabricated completeness."""
    _fresh_password(request, password)
    with transaction.atomic():
        member = _participant(request.user)
        require_request_mfa(request, member.user)
        task = get_task(member.user, reference, write=True, own=True)
        link = ConnectorTask.objects.filter(task=task).first()
        if link is None:
            raise ValidationError("This task has no connector observation interval.")
        task_state(link)
        if link.closed_at or type(expected_sequence) is not int or link.sequence != expected_sequence:
            raise ValidationError("Connector task changed/ended; reload before closing interrupted observation.")
        _scope(member, task.repository_ref, {"observation_kind": "gap", "request_kind": "unknown", "coverage_status": "incomplete"})
        for kind in ("gap", "close"):
            link.sequence += 1
            ConnectorObservation.objects.create(task=link, event_id=uuid.uuid4(), sequence=link.sequence, received_at=timezone.now(),
                actor_snapshot=member_snapshot(member), payload={"observation_kind": kind, "request_kind": "unknown", "model": None,
                  "http_status": None, "attempt": None, "retry": None, "coverage_status": "incomplete"})
        link.closed_at = timezone.now()
        link.save(update_fields=("sequence", "closed_at"))
        _audit(member, "connector_end_interrupted", task_ref=str(task.reference), observation_gap=True, history_retained=True)
        return task_state(link)
