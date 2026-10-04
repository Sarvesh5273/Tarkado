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
        or live_guard(runtime.authorization, member.company, allow_future_recommendations=True)["status"] != "current"):
        raise ValidationError("No current independently approved unused task boundary is available.")
    route = next((row for row in runtime.authorization.data["routes"] if row["task_type"] == task.task_type), None)
    if route is None or task.required_tools:
        raise ValidationError("This task has no supported text-only delivery route.")
    model = request["override_model"] or route["model"]
    delivery.envelope_for(member.company, model)
    proof = verify_admission(AdmissionRequest(str(member.company.company_id), str(member.company.deployment_id),
        runtime.authorization.data["sha256"], _fingerprint(request), request, model, request["reserve_usd"]))
    return {"requestID": request["selection_id"], "newTask": proof.new_task_verified,
            "capEnforced": proof.provider_cap_enforced, "atomicModelBinding": proof.atomic_model_binding_supported,
            "new_reservation": False, "execution_sent": False}


OPERATIONS = {
    "begin": (delivery.begin_request, ("task_token", "binding_ref", "session_ref", "gateway_user_ref", "request_id", "kind", "output_limit", "stream")),
    "attempt": (delivery.admit_attempt, ("task_token", "binding_ref", "session_ref", "request_id", "attempt_id", "provider_model", "output_limit", "stream")),
    "settle": (delivery.settle_attempt, ("binding_ref", "attempt_id", "cost_usd", "usage", "outcome", "latency_ms", "evidence_ref", "actual_model")),
    "close": (delivery.close_delivery, ("binding_ref",)),
}


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
