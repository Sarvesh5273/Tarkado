"""Authenticated manual records using the existing feedback contracts, without model calls."""

import uuid
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from engine.feedback import (
    Execution, FeedbackLedger, Recommendation, Response, RoleAttribution, TaskRequest,
    TaskResult, TeamConfig, _fingerprint, feedback_summary,
)
from engine.history import PolicySnapshot
from engine.privacy import ensure_safe
from engine.schemas import Policy, ValidationError, boolean, choice, integer, object_fields, text

from .models import CompanyTask, Membership, TaskEvent
from .services import COLLECTION_REQUIRED, current_member, member_snapshot, require_collection


INPUT_FIELDS = ("repository_ref", "source_kind", "boundary", "task_id", "session_id", "task_type",
                "risk_tags", "selected_model", "required_tools", "context_tokens")
RESULT_FIELDS = ("desired_result", "tests_passed", "score", "cost_usd", "latency_ms", "evidence_ref", "supersedes")
KINDS = {"recommendation": "recommendations", "response": "responses", "execution": "executions", "result": "results"}


def _authenticated_transaction(operation):
    @wraps(operation)
    def checked(user, *args, **kwargs):
        request = kwargs.pop("request", None)
        with transaction.atomic():
            from .mfa import require_request_mfa
            require_request_mfa(request, user)
            return operation(user, *args, **kwargs)
    return checked


def _participant(user):
    member = current_member(user)
    if not member.participating or member.role not in ("junior", "developer", "senior"):
        raise PermissionDenied("This account is not a participating developer or engineering reviewer.")
    return member


def _scope(member, repository_ref, values):
    if not member.company.company_api_attested or repository_ref not in member.company.repository_refs:
        raise PermissionDenied("Repository or API collection permission is no longer approved.")
    allowed = set(member.company.collection_fields)
    if not set(COLLECTION_REQUIRED).issubset(allowed):
        raise ValidationError("Current collection configuration is missing required linkage fields.")
    # Null/empty placeholders mean uncollected information, never fabricated values.
    if any(key not in allowed and value is not None and value != [] for key, value in values.items()):
        raise PermissionDenied("This record contains metadata outside the current collection field scope.")


def _session_ref(company, developer_id, supplied):
    # Namespace caller-declared references; identical labels from two developers are not one session.
    return "company_session_" + _fingerprint({"company_id": str(company.company_id),
                                              "developer_id": developer_id, "session_id": supplied})


def _task_request(task, actor, timestamp):
    source = task.request
    return TaskRequest.from_dict({"task_id": source["task_id"],
                                  "session_id": _session_ref(task.company, actor["developer_id"], source["session_id"]),
                                  "developer_id": actor["developer_id"], "timestamp": timestamp.isoformat(),
                                  **{field: source[field] for field in ("task_type", "risk_tags", "selected_model", "required_tools", "context_tokens")}})


def task_ledger(task):
    """Verify stored links and historical roles; no caller-supplied ledger can authenticate here."""
    object_fields(task.request, INPUT_FIELDS, INPUT_FIELDS)
    ensure_safe(task.request)
    choice(task.source_kind, "source_kind", ("synthetic", "team"))
    choice(task.request["boundary"], "boundary", ("new_task", "new_run", "subagent"))
    if (task.task_id, task.session_id, task.repository_ref, task.source_kind) != tuple(
        task.request[field] for field in ("task_id", "session_id", "repository_ref", "source_kind")
    ):
        raise ValidationError("Stored task metadata differs from its immutable request.")
    policy = PolicySnapshot.from_dict(task.policy_snapshot)
    data = {"schema_version": 2, "team": None, "policies": [policy.to_dict()],
            "recommendations": [], "responses": [], "executions": [], "results": [], "role_attributions": []}
    roles = {}
    events = list(task.events.select_related("actor").all())
    if not events or len(events) != task.revision:
        raise ValidationError("Task history is incomplete; existing records will not be reset.")
    previous_time = None
    for sequence, event in enumerate(events, 1):
        actor = event.actor_snapshot
        fields = ("account_id", "developer_id", "role", "active", "participating", "can_manage_company", "can_approve_pilots")
        object_fields(actor, fields, fields)
        ensure_safe(actor)
        integer(actor["account_id"], "account_id")
        for flag in ("active", "participating", "can_manage_company", "can_approve_pilots"):
            boolean(actor[flag], flag)
        integer(event.company_revision, "company_revision")
        if event.sequence != sequence or event.kind not in KINDS or actor["account_id"] != event.actor_id:
            raise ValidationError("Task event sequence or actor binding is inconsistent.")
        if previous_time is not None and event.timestamp < previous_time:
            raise ValidationError("Task event time precedes its prior recorded action.")
        if actor["role"] not in ("junior", "developer", "senior") or not actor["active"] or not actor["participating"]:
            raise ValidationError("Task event has no permitted engineering-role snapshot.")
        if sequence == 1:
            if event.kind != "recommendation" or event.actor_id != task.owner_id:
                raise ValidationError("Task history must begin with its owner's recommendation.")
            if task.suggestion_context:
                object_fields(task.suggestion_context, ("publication_ref", "publication_sha256", "status", "reason"),
                              ("publication_ref", "publication_sha256", "status", "reason"))
                choice(task.suggestion_context["status"], "suggestion_status", ("current", "blocked"))
                from .models import LearningPublication
                from .company_learning import history
                history(task.company, task.source_kind)
                publication = LearningPublication.objects.filter(company=task.company,
                    reference=task.suggestion_context.get("publication_ref")).first()
                if publication is None or publication.data["sha256"] != task.suggestion_context.get("publication_sha256") or publication.source_kind != task.source_kind or publication.data["action"] != "publish":
                    raise ValidationError("Task suggestion has no matching historical company publication.")
                if task.learning_snapshot is not None and task.learning_snapshot != publication.review.data["learner"]:
                    raise ValidationError("Task learner differs from its exact published artifact.")
            elif task.learning_snapshot is not None:
                raise ValidationError("Company learned task is missing its publication binding.")
            refusal = ("Published learner unavailable; approved fallback recommendation. " + task.suggestion_context["reason"]
                       if task.suggestion_context.get("status") == "blocked" else None)
            expected = Recommendation.create(_task_request(task, actor, event.timestamp), policy.policy, task.learning_snapshot, refusal)
            if event.payload != expected.to_dict():
                raise ValidationError("Task recommendation differs from its saved request/policy.")
        elif event.kind == "recommendation":
            raise ValidationError("A task cannot have another recommendation event.")
        elif event.kind in ("response", "execution") and event.actor_id != task.owner_id:
            raise ValidationError("Only the task owner may supply a per-task response or actual-model record.")
        elif event.kind == "result" and event.actor_id != task.owner_id and actor["role"] != "senior":
            raise ValidationError("Another task's result requires an active senior reviewer.")
        payload = event.payload
        ensure_safe(payload)
        if event.kind != "recommendation":
            {"response": Response, "execution": Execution, "result": TaskResult}[event.kind].from_dict(payload)
        record_id = payload["recommendation_id"] if event.kind in ("recommendation", "response") else payload[event.kind + "_id"]
        identifier = payload["task"]["developer_id"] if event.kind == "recommendation" else payload[
            "reviewer_id" if event.kind == "result" else "developer_id"]
        timestamp = payload["task"]["timestamp"] if event.kind == "recommendation" else payload["timestamp"]
        if identifier != actor["developer_id"] or timestamp != event.timestamp.isoformat():
            raise ValidationError("Task payload identity/time differs from its authenticated event.")
        roles[identifier] = actor["role"]
        data[KINDS[event.kind]].append(payload)
        data["role_attributions"].append(RoleAttribution(event.kind, record_id, identifier, actor["role"]).to_dict())
        previous_time = event.timestamp
    data["team"] = {"company_api_attested": True,
                    "members": [{"developer_id": identifier, "role": role} for identifier, role in sorted(roles.items())]}
    return FeedbackLedger.from_dict(data)


def visible_tasks(user):
    member = current_member(user)
    query = CompanyTask.objects.filter(company=member.company).select_related("company", "owner")
    if member.role == "admin" and member.can_manage_company:
        return query.order_by("-id")
    _participant(user)
    query = query.filter(repository_ref__in=member.company.repository_refs)
    if member.role != "senior":
        query = query.filter(owner_id=member.user_id)
    return query.order_by("-id")


def get_task(user, reference, write=False, own=False):
    task = visible_tasks(user).filter(reference=reference).first()
    if task is None:
        raise PermissionDenied("Task is unavailable for this account.")
    if own and task.owner_id != user.pk:
        raise PermissionDenied("Only the task owner may record this action.")
    if write:
        member = _participant(user)
        owner = Membership.objects.select_related("user").filter(user_id=task.owner_id, company=member.company).first()
        if owner is None or not owner.active or not owner.user.is_active or not owner.participating:
            raise PermissionDenied("Task owner's collection permission is no longer active; history is retained.")
        _scope(member, task.repository_ref, {})
    task_ledger(task)
    return task


def _append(task, member, kind, payload, timestamp):
    ensure_safe(payload)
    TaskEvent.objects.create(task=task, sequence=task.revision, kind=kind, actor=member.user,
                             actor_snapshot=member_snapshot(member), company_revision=member.company.revision,
                             timestamp=timestamp, payload=payload)
    task_ledger(task)


def _check_revision(task, expected_revision):
    if type(expected_revision) is not int or task.revision != expected_revision:
        raise ValidationError("Task changed; reload before recording a stale action or correction.")


@_authenticated_transaction
def recommend_task(user, value):
    source = dict(object_fields(value, INPUT_FIELDS, INPUT_FIELDS))
    ensure_safe(source)
    member = _participant(user)
    require_collection(user, source["repository_ref"], member.developer_id)
    source["source_kind"] = choice(source["source_kind"], "source_kind", ("synthetic", "team"))
    source["boundary"] = choice(source["boundary"], "boundary", ("new_task", "new_run", "subagent"))
    for field in ("task_id", "session_id"):
        text(source[field], field)
        if len(source[field]) > 128:
            raise ValidationError("Manual task/session references must be at most 128 characters.")
    task = CompanyTask(company=member.company, owner=member.user, task_id=source["task_id"], session_id=source["session_id"],
                       repository_ref=source["repository_ref"], source_kind=source["source_kind"], request=source,
                       policy_snapshot=PolicySnapshot.create(Policy.from_dict(member.company.policy)).to_dict())
    timestamp = timezone.now()
    request = _task_request(task, member_snapshot(member), timestamp)
    _scope(member, task.repository_ref, {field: val for field, val in request.to_dict().items()})
    existing = CompanyTask.objects.filter(company=member.company, owner=member.user, task_id=task.task_id, session_id=task.session_id).first()
    if existing is not None:
        if existing.request != source:
            raise ValidationError("This task/session already has different metadata; history cannot be overwritten.")
        task_ledger(existing)
        return existing
    from .company_learning import suggestion
    task.learning_snapshot, task.suggestion_context = suggestion(member, source, request)
    refusal = ("Published learner unavailable; approved fallback recommendation. " + task.suggestion_context["reason"]
               if task.suggestion_context.get("status") == "blocked" else None)
    rec = Recommendation.create(request, PolicySnapshot.from_dict(task.policy_snapshot).policy, task.learning_snapshot, refusal)
    task.save()
    _append(task, member, "recommendation", rec.to_dict(), timestamp)
    return task


@_authenticated_transaction
def record_response(user, reference, response, expected_revision):
    task = get_task(user, reference, write=True, own=True)
    member = _participant(user)
    ledger = task_ledger(task)
    from .connectors import check_feedback_task
    check_feedback_task(task, "response")
    response = choice(response, "response", ("accept", "reject"))
    timestamp = timezone.now()
    item = Response(ledger.recommendations[0].recommendation_id, member.developer_id, timestamp.isoformat(), response)
    _scope(member, task.repository_ref, item.to_dict())
    if ledger.responses:
        if ledger.responses[0].response != response:
            raise ValidationError("This task already has a different immutable response.")
        return task
    _check_revision(task, expected_revision)
    if ledger.executions:
        raise ValidationError("A new accept/reject action cannot be added after actual-model use was recorded.")
    task.revision += 1
    task.save(update_fields=("revision",))
    _append(task, member, "response", item.to_dict(), timestamp)
    from .selection import monitor_feedback
    monitor_feedback(member, task)
    return task


@_authenticated_transaction
def record_execution(user, reference, actual_model, expected_revision):
    task = get_task(user, reference, write=True, own=True)
    member = _participant(user)
    ledger = task_ledger(task)
    timestamp = timezone.now()
    item = Execution("company_exec_" + task.reference.hex, ledger.recommendations[0].recommendation_id,
                     member.developer_id, timestamp.isoformat(), text(actual_model, "actual_model"))
    _scope(member, task.repository_ref, item.to_dict())
    if ledger.executions:
        if ledger.executions[0].actual_model != actual_model:
            raise ValidationError("Actual-model record already differs; it cannot be overwritten.")
        return task
    _check_revision(task, expected_revision)
    task.revision += 1
    task.save(update_fields=("revision",))
    _append(task, member, "execution", item.to_dict(), timestamp)
    return task


@_authenticated_transaction
def record_result(user, reference, value, expected_revision):
    source = dict(object_fields(value, RESULT_FIELDS, RESULT_FIELDS))
    ensure_safe(source)
    task = get_task(user, reference, write=True)
    from .connectors import check_feedback_task
    check_feedback_task(task, "result", source)
    member = _participant(user)
    ledger = task_ledger(task)
    if not ledger.executions:
        raise ValidationError("Record the model actually used before recording its result.")
    timestamp = timezone.now()
    item = TaskResult.from_dict({"result_id": "company_result_" + uuid.uuid4().hex,
                                 "execution_id": ledger.executions[0].execution_id,
                                 "reviewer_id": member.developer_id, "timestamp": timestamp.isoformat(), **source})
    _scope(member, task.repository_ref, item.to_dict())
    previous = ledger.results[-1] if ledger.results else None
    if previous is not None:
        if previous.reviewer_id != member.developer_id:
            raise PermissionDenied("Cross-reviewer outcome replacement is not supported; keep the existing result and history.")
        if {field: previous.to_dict()[field] for field in RESULT_FIELDS} == {field: item.to_dict()[field] for field in RESULT_FIELDS}:
            return task
    _check_revision(task, expected_revision)
    if item.supersedes != (previous.result_id if previous else None):
        raise ValidationError("Correction must reference the current result, not a stale or unrelated one.")
    task.revision += 1
    task.save(update_fields=("revision",))
    _append(task, member, "result", item.to_dict(), timestamp)
    from .selection import monitor_feedback
    monitor_feedback(member, task)
    return task


@_authenticated_transaction
def task_detail(user, reference):
    task = get_task(user, reference)
    ledger = task_ledger(task)
    summary = feedback_summary(ledger, Policy.from_dict(task.company.policy))
    return {"task": task, "ledger": ledger, "summary": summary, "recommendation": ledger.recommendations[0],
            "events": list(task.events.all()), "current_result": ledger.results[-1] if ledger.results else None}


@_authenticated_transaction
def company_feedback(user):
    tasks = list(visible_tasks(user))
    member = current_member(user)
    ledgers = [task_ledger(task) for task in tasks]
    roles, policies = {}, {}
    for ledger in ledgers:
        roles.update(ledger.team.members)
        for snapshot in ledger.policies:
            if snapshot.policy.policy_version in policies and policies[snapshot.policy.policy_version] != snapshot:
                raise ValidationError("A policy version has conflicting task snapshots; history cannot be combined safely.")
            policies[snapshot.policy.policy_version] = snapshot
    # An empty projection needs no real participant; the placeholder cannot own a recorded action.
    roster = TeamConfig(True, tuple(sorted(roles.items()))) if roles else TeamConfig(True, (("empty_projection_placeholder", "developer"),))
    merged = FeedbackLedger(roster, tuple(policies.values()),
                            tuple(item for ledger in ledgers for item in ledger.recommendations),
                            tuple(item for ledger in ledgers for item in ledger.responses),
                            tuple(item for ledger in ledgers for item in ledger.executions),
                            tuple(item for ledger in ledgers for item in ledger.results),
                            tuple(item for ledger in ledgers for item in ledger.role_attributions))
    summary = feedback_summary(merged, Policy.from_dict(member.company.policy))
    summary["roles_source"] = "authenticated_company_event_snapshots"
    summary["outcome_source"] = "authenticated_submitter_manual_outcome_unverified"
    summary["notes"] = [note for note in summary["notes"] if not note.startswith("Local records do not")]
    summary["notes"].extend([
        "Company login binds each submitted actor and historical role; it does not verify actual-model use or desired-result truth.",
        "Task/session/boundary and source-kind labels are supplied manually, not observed from OpenCode.",
        "Historical roles, rejected suggestions, junior failures, overrides, and result corrections remain visible.",
        "Combined source counts are diagnostic only; synthetic examples are not verified company learning/readiness evidence.",
    ])
    summary["source_counts"] = {kind: sum(task.source_kind == kind for task in tasks) for kind in ("synthetic", "team")}
    ensure_safe(summary)
    return {"summary": summary, "tasks": tasks}


def company_ledger(company, source_kind):
    """Use every stored record of the declared source kind, including removed actors/failures."""
    tasks = CompanyTask.objects.filter(company=company, source_kind=source_kind).select_related("company").order_by("id")
    ledgers = [task_ledger(task) for task in tasks]
    # Approved participants may be eligible for a reviewed pilot before they have
    # recorded task evidence. Membership is not an invented successful outcome.
    roles = {member.developer_id: member.role for member in Membership.objects.filter(
        company=company, active=True, user__is_active=True, participating=True,
        role__in=("junior", "developer", "senior"))}
    policies = {}
    for ledger in ledgers:
        roles.update(ledger.team.members)
        for item in ledger.policies:
            other = policies.get(item.policy.policy_version)
            if other is not None and other != item:
                raise ValidationError("A stored policy version has inconsistent contents.")
            policies[item.policy.policy_version] = item
    if not ledgers:
        raise ValidationError("No authenticated task records exist for this declared source kind.")
    return FeedbackLedger.from_dict(FeedbackLedger(
        TeamConfig(True, tuple(sorted(roles.items()))), tuple(policies.values()),
        tuple(item for ledger in ledgers for item in ledger.recommendations),
        tuple(item for ledger in ledgers for item in ledger.responses),
        tuple(item for ledger in ledgers for item in ledger.executions),
        tuple(item for ledger in ledgers for item in ledger.results),
        tuple(item for ledger in ledgers for item in ledger.role_attributions),
    ).to_dict())
