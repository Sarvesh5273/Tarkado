"""Separate machine-only metadata API. Never accepts inference bodies or human feedback."""

from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from engine.importers import parse_json
from engine.privacy import PrivacyError, redact_text
from engine.schemas import ValidationError, object_fields

from . import delivery
from .connector_views import delegated, _conditional_scope
from .connectors import _link


@delegated
def tool_status(credential, member, value):
    from .tool_observations import observe
    return observe(credential, member, value)


@delegated
def options(credential, member, value):
    """Guided metadata choices are not execution permission or human approval."""
    from .models import GatewayCredential, ScopedSelectionRuntime
    from .services import member_snapshot, current_member
    from .live_authorization import live_guard
    from . import selection
    from .mfa import MFAState
    from .recovery import _password_ref
    from django.utils import timezone
    object_fields(value, ("location_sha256",), ("location_sha256",))
    if value["location_sha256"] != credential.scope["location_sha256"]:
        raise PermissionDenied("Delivery choices are outside this paired repository/directory.")
    scopes = []
    if credential.scope["source_kind"] == "team":
        for runtime in ScopedSelectionRuntime.objects.filter(authorization__company=member.company).select_related("authorization"):
            approval = runtime.authorization
            scope = approval.data["scope"]
            if scope["repository_ref"] != credential.scope["repository_ref"] or member.developer_id not in scope["developer_ids"]:
                continue
            current = selection._state(runtime)
            guard = live_guard(approval, member.company, allow_future_recommendations=True)
            routes = []
            for route in approval.data["routes"]:
                if live_guard(approval, member.company, allow_future_recommendations=True, tool_task_types=(route["task_type"],))["status"] != "current":
                    continue
                try:
                    envelope = delivery.envelope_for(member.company, route["model"])
                except ValidationError:
                    continue
                from engine.delivery_contract import LocalFunctionChatEnvelope
                tools = [tool.to_dict() for tool in envelope.local_tools] if isinstance(envelope, LocalFunctionChatEnvelope) else []
                routes.append({"task_type": route["task_type"], "model": route["model"], "output_token_ceiling": envelope.output_token_ceiling,
                               "minimum_attempt_reserve_usd": str(envelope.maximum(1)), "local_tools": tools})
            scopes.append({"scope_ref": str(approval.reference), "pilot_id": scope["pilot_id"], "status": current["status"],
                "authority_current": guard["status"] == "current" or bool(routes), "routes": routes, "accounting": selection.accounting(runtime, current)})
    gateways = []
    for gateway in GatewayCredential.objects.filter(company=member.company, revoked_at__isnull=True, expires_at__gt=timezone.now()):
        if gateway.scope["repository_ref"] != credential.scope["repository_ref"] or member.developer_id not in gateway.scope["user_mapping"]:
            continue
        try:
            issuer = current_member(gateway.issuer, "manage")
            if (gateway.scope["issuer"] != member_snapshot(issuer) or gateway.scope["password_ref"] != _password_ref(issuer.user)
                or gateway.scope["mfa_generation"] != MFAState.objects.get(user=issuer.user).generation):
                continue
        except PermissionDenied:
            continue
        gateways.append({"gateway_ref": str(gateway.reference), "gateway_id": gateway.gateway_id, "expires_at": gateway.expires_at.isoformat()})
    from engine.schemas import Policy
    policy = Policy.from_dict(member.company.policy)
    required = ("actual_model", "request_kind", "cost_usd", "latency_ms", "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
    from .services import TOOL_CAPTURE_FIELDS
    from .models import DeliveryBinding
    from .tool_observations import state as tool_state
    capture_tasks = []
    if set(TOOL_CAPTURE_FIELDS).issubset(credential.scope["collection_fields"]):
        for binding in DeliveryBinding.objects.filter(connector_task__credential=credential, connector_task__closed_at__isnull=True,
            tool_observations__isnull=False).select_related("connector_task").distinct():
            capture_tasks.append({"connector_task_ref": str(binding.connector_task.reference), "session_ref": binding.connector_task.session_ref,
                                  "sequence": tool_state(binding)["sequence"]})
    return {"schema_version": 1, "company_id": str(member.company.company_id), "deployment_id": str(member.company.deployment_id),
            "company_revision": member.company.revision, "developer_id": member.developer_id, "repository_ref": credential.scope["repository_ref"],
            "source_kind": credential.scope["source_kind"], "scopes": scopes, "gateways": gateways,
            "models": [model.model_id for model in policy.models if model.approved],
            "collection_supported": set(required).issubset(credential.scope["collection_fields"]),
            "tool_capture_approved": set(TOOL_CAPTURE_FIELDS).issubset(credential.scope["collection_fields"]),
            "tool_capture_tasks": capture_tasks,
            "new_reservation": False, "execution_sent": False, "note": "Choices only. Each new task still rechecks independent verification, separate human approval and shared accounting."}


@delegated
def bind(credential, member, value):
    fields = ("scope_ref", "selection_id", "connector_task_ref", "location_sha256", "gateway_ref")
    object_fields(value, fields, fields)
    _conditional_scope(credential, value)
    required = ("actual_model", "request_kind", "cost_usd", "latency_ms", "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
    if not set(required).issubset(credential.scope["collection_fields"]):
        raise PermissionDenied("Explicit billing/usage metadata collection approval is required before delivery binding.")
    link = _link(credential, value["connector_task_ref"], value["location_sha256"])
    return delivery.bind(credential, member, link, value["scope_ref"], value["selection_id"], value["gateway_ref"])


@delegated
def preflight(credential, member, value):
    """Read-only trusted capability check. Never reserves, claims, or executes."""
    from engine.feedback import TaskRequest, _fingerprint
    from .admission_gate import AdmissionRequest, verify_admission
    from .live_authorization import live_guard
    from .models import ScopedSelectionRuntime
    from . import selection
    from .tasks import task_ledger
    fields = ("scope_ref", "connector_task_ref", "location_sha256", "selection_request", "gateway_ref")
    object_fields(value, fields, fields)
    _conditional_scope(credential, value)
    link = _link(credential, value["connector_task_ref"], value["location_sha256"])
    request = value["selection_request"]
    request_fields = ("selection_id", "task", "repository_ref", "boundary", "reserve_usd", "override_model")
    object_fields(request, request_fields, request_fields)
    task = TaskRequest.from_dict(request["task"])
    runtime = ScopedSelectionRuntime.objects.select_related("authorization").filter(authorization__reference=value["scope_ref"], authorization__company=member.company).first()
    if (runtime is None or selection._state(runtime)["status"] != "active" or link.sequence or link.closed_at
        or request["boundary"] != "new_task" or task.to_dict() != task_ledger(link.task).recommendations[0].task.to_dict()
        or live_guard(runtime.authorization, member.company, allow_future_recommendations=True, tool_task_types=(task.task_type,))["status"] != "current"):
        raise ValidationError("No current independently approved unused task boundary is available.")
    route = next((row for row in runtime.authorization.data["routes"] if row["task_type"] == task.task_type), None)
    if route is None:
        raise ValidationError("This task has no supported delivery route.")
    model = request["override_model"] or route["model"]
    from engine.delivery_contract import bind_tools
    bind_tools(delivery.envelope_for(member.company, model), task.required_tools)
    proof = verify_admission(AdmissionRequest(str(member.company.company_id), str(member.company.deployment_id),
        runtime.authorization.data["sha256"], _fingerprint(request), request, model, request["reserve_usd"]))
    return {"requestID": request["selection_id"], "newTask": proof.new_task_verified,
            "capEnforced": proof.provider_cap_enforced, "atomicModelBinding": proof.atomic_model_binding_supported,
            "new_reservation": False, "execution_sent": False}


@delegated
def task(credential, member, value):
    from .connectors import task_state
    from .models import DeliveryBinding
    from .operations import delivery_summary
    fields = ("connector_task_ref", "location_sha256")
    object_fields(value, fields, fields)
    link = _link(credential, value["connector_task_ref"], value["location_sha256"])
    binding = DeliveryBinding.objects.filter(connector_task=link).first()
    return {"task": task_state(link), "delivery": delivery_summary(binding) if binding else None,
            "execution_sent": False, "outcome_verified": False}


OPERATIONS = {
    "begin": (delivery.begin_request, ("task_token", "binding_ref", "session_ref", "gateway_user_ref", "request_id", "kind", "output_limit", "stream")),
    "attempt": (delivery.admit_attempt, ("task_token", "binding_ref", "session_ref", "request_id", "attempt_id", "provider_model", "output_limit", "stream")),
    "settle": (delivery.settle_attempt, ("binding_ref", "attempt_id", "cost_usd", "usage", "outcome", "latency_ms", "evidence_ref", "actual_model")),
    "close": (delivery.close_delivery, ("binding_ref",)),
}

from .billing_corrections import INPUT_FIELDS, review_machine, correct_machine
OPERATIONS["review-cost"] = (review_machine, ("binding_ref",) + INPUT_FIELDS)
OPERATIONS["correct-cost"] = (correct_machine, ("binding_ref", "expected_assessment") + INPUT_FIELDS)


@transaction.atomic
def describe(gateway_token, task_token, binding_ref, session_ref, gateway_user_ref):
    gateway = delivery.authenticate_gateway(gateway_token)
    binding = delivery._binding(gateway, binding_ref)
    envelope = delivery._current(gateway, binding, task_token, session_ref)
    if gateway_user_ref != binding.data["gateway_user_ref"]:
        raise PermissionDenied("Gateway authenticated user is not this task owner.")
    return {"envelope": envelope.to_dict()}


OPERATIONS["describe"] = (describe, ("task_token", "binding_ref", "session_ref", "gateway_user_ref"))


def invoke(gateway_token, operation, value):
    if operation not in OPERATIONS:
        raise PermissionDenied("This machine identity has no human feedback or pilot-control operation.")
    function, fields = OPERATIONS[operation]
    object_fields(value, fields, fields)
    return function(gateway_token, **value)


def machine(operation):
    def decorate(view):
        @wraps(view)
        @csrf_exempt
        @require_POST
        def endpoint(request):
            try:
                if request.headers.get("Origin") or request.COOKIES.get(settings.SESSION_COOKIE_NAME):
                    raise PermissionDenied("Gateway metadata API refuses browser sessions and cross-origin requests.")
                if request.content_type != "application/json" or len(request.body) > 16384:
                    raise ValidationError("Only bounded metadata-only JSON is accepted.")
                auth = request.headers.get("Authorization", "")
                if not auth.startswith("Bearer "):
                    raise PermissionDenied("A scoped gateway machine credential is required.")
                value = parse_json(request.body.decode("utf-8"))
                result = invoke(auth[7:], operation, value)
                # Internal state includes no secrets but should not be a credential response.
                return JsonResponse(result)
            except PermissionDenied as error:
                return JsonResponse({"error": redact_text(str(error)), "execution_sent": False}, status=403)
            except (ValidationError, PrivacyError, UnicodeError) as error:
                return JsonResponse({"error": redact_text(str(error)), "execution_sent": False}, status=400)
        return endpoint
    return decorate


@machine("describe")
def describe_view(request): pass


@machine("begin")
def begin_view(request): pass


@machine("attempt")
def attempt_view(request): pass


@machine("settle")
def settle_view(request): pass


@machine("close")
def close_view(request): pass


@machine("review-cost")
def review_cost_view(request): pass


@machine("correct-cost")
def correct_cost_view(request): pass
