"""Browser-issued scoped credentials and a narrow bearer-only observation API."""

from functools import wraps

from django import forms
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from engine.importers import parse_json
from engine.privacy import PrivacyError, redact_text
from engine.schemas import Policy, ValidationError, object_fields

from . import connectors
from .forms import StrictForm
from .models import ConnectorCredential, ConnectorTask, PilotAuthorization
from .tasks import _participant
from .views import _form_error, _form_page, protected


class PairForm(StrictForm):
    name = forms.CharField(max_length=128, label="Connector name (metadata only)")
    repository_ref = forms.ChoiceField(choices=(), label="Approved repository")
    directory = forms.CharField(max_length=1024, label="Exact OpenCode directory", help_text="Absolute directory on the machine running OpenCode. Only its hash is retained; this is a declared scope, not independent device identity.")
    expires_at = forms.DateTimeField(label="Expiry (UTC, within 24 hours)")
    source_kind = forms.ChoiceField(choices=(("team", "Permitted team observations (outcomes unverified)"), ("synthetic", "Isolated synthetic demonstration")))
    expected_revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput, max_length=1024)
    confirmation = forms.BooleanField(label="I approve this connector scope; no prompts/code/outputs or provider credentials will be stored")

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["repository_ref"].choices = [(item, item) for item in company.repository_refs]


class RevokeForm(StrictForm):
    confirm_password = forms.CharField(widget=forms.PasswordInput, max_length=1024)
    confirmation = forms.BooleanField(label="Revoke this connector; preserve all observation and task history")


class EndInterruptedForm(RevokeForm):
    expected_sequence = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    confirmation = forms.BooleanField(label="End interrupted observation with a permanent gap; no success or missing measurements will be invented")


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def pairing(request):
    member = request.company_member
    query = ConnectorCredential.objects.filter(company=member.company).select_related("user").order_by("-id")
    admin = member.role == "admin" and member.can_manage_company
    if not admin:
        query = query.filter(user=member.user)
    form = None
    if member.participating:
        _participant(request.user)
        form = PairForm(request.POST if request.method == "POST" else None, company=member.company,
                        initial={"expected_revision": member.company.revision, "source_kind": "team"})
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            try:
                credential, value = connectors.issue(request, data["name"], data["repository_ref"], data["directory"],
                    data["expires_at"], data["expected_revision"], data["confirm_password"], data["source_kind"])
            except (PrivacyError, ValidationError, PermissionDenied) as error:
                _form_error(form, error)
            else:
                return render(request, "company/connector_created.html", {"credential": credential, "pairing_value": value})
        form.sanitize_display()
    elif request.method == "POST":
        raise PermissionDenied("Only participating developers may pair their own connector.")
    return render(request, "company/connectors.html", {"form": form, "credentials": query})


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def revoke(request, reference):
    member = request.company_member
    query = ConnectorCredential.objects.filter(company=member.company, reference=reference)
    if not (member.role == "admin" and member.can_manage_company):
        query = query.filter(user=member.user)
    credential = query.first()
    if credential is None:
        raise PermissionDenied("Connector is unavailable for this account.")
    form = RevokeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            connectors.revoke(request, reference, form.cleaned_data["confirm_password"])
        except (PrivacyError, ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-connectors")
    return _form_page(request, "company/form.html", {"title": "Revoke connector: " + credential.name, "form": form})


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def end_interrupted(request, reference):
    from .tasks import get_task
    task = get_task(request.user, reference, write=True, own=True)
    link = ConnectorTask.objects.filter(task=task).first()
    if link is None:
        raise PermissionDenied("Task has no connector observation interval.")
    form = EndInterruptedForm(request.POST if request.method == "POST" else None, initial={"expected_sequence": link.sequence})
    if request.method == "POST" and form.is_valid():
        try:
            connectors.end_interrupted(request, reference, form.cleaned_data["expected_sequence"], form.cleaned_data["confirm_password"])
        except (PrivacyError, ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-task-detail", reference=reference)
    return _form_page(request, "company/form.html", {"title": "End interrupted connector observation: " + task.task_id, "form": form})


def delegated(view):
    @wraps(view)
    @csrf_exempt
    @require_http_methods(["POST"])
    def endpoint(request):
        try:
            if request.headers.get("Origin") or request.COOKIES.get(settings.SESSION_COOKIE_NAME):
                raise PermissionDenied("Connector API accepts scoped bearer credentials, never browser sessions or cross-origin requests.")
            if request.content_type != "application/json" or len(request.body) > 16384:
                raise ValidationError("Use a bounded metadata-only JSON connector request.")
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                raise PermissionDenied("A scoped connector credential is required.")
            value = parse_json(request.body.decode("utf-8"))
            with transaction.atomic():
                credential, member = connectors.authenticate(auth[7:])
                result = view(credential, member, value)
            return JsonResponse(result)
        except PermissionDenied as error:
            return JsonResponse({"error": redact_text(str(error)), "routing_enabled": False}, status=403)
        except (PrivacyError, ValidationError, UnicodeError) as error:
            return JsonResponse({"error": redact_text(str(error)), "routing_enabled": False}, status=400)
    return endpoint


@delegated
def status(credential, member, value):
    object_fields(value, ("location_sha256",), ("location_sha256",))
    if value["location_sha256"] != credential.scope["location_sha256"]:
        raise PermissionDenied("Connector directory is outside paired scope.")
    policy = Policy.from_dict(member.company.policy)
    from .company_learning import current_status
    return {"schema_version": 1, "developer_id": member.developer_id, "role": member.role,
            "company_id": str(member.company.company_id), "deployment_id": str(member.company.deployment_id),
            "repository_ref": credential.scope["repository_ref"], "expires_at": credential.expires_at.isoformat(),
            "source_kind": credential.scope["source_kind"], "collection_fields": credential.scope["collection_fields"],
            "learning_status": current_status(member.company, credential.scope["source_kind"]),
            "conditional_selection_available": False,
            "policy_version": policy.policy_version, "models": [model.model_id for model in policy.models],
            "categories": sorted({rule.task_type for rule in policy.rules}), "fallback_model": policy.default_model,
            "open_tasks": [connectors.task_state(link) for link in ConnectorTask.objects.select_related("task__company").filter(credential=credential, closed_at__isnull=True)],
            "recent_tasks": [connectors.task_state(link) for link in ConnectorTask.objects.select_related("task__company").filter(credential=credential).order_by("-id")[:20]],
            "routing_enabled": False, "automatic_boundary_detection": False, "subagent_capture_supported": False,
            "provider_usage_capture_supported": False}


@delegated
def start(credential, member, value):
    return connectors.start(credential, member, value)


@delegated
def observation(credential, member, value):
    return connectors.observe(credential, member, value)


@delegated
def feedback(credential, member, value):
    return connectors.feedback(credential, member, value)


@delegated
def task(credential, member, value):
    fields = ("connector_task_ref", "location_sha256")
    object_fields(value, fields, fields)
    return connectors.task_state(connectors._link(credential, value["connector_task_ref"], value["location_sha256"]))


def _conditional_scope(credential, value):
    if value["location_sha256"] != credential.scope["location_sha256"] or credential.scope["source_kind"] != "team":
        raise PermissionDenied("Conditional selection needs exact paired team scope; synthetic connector labels cannot enter live accounting.")
    approval = PilotAuthorization.objects.filter(company=credential.company, reference=connectors.uuid_value(value["scope_ref"])).first()
    if approval is None or approval.data.get("target") != "live" or approval.data["scope"]["repository_ref"] != credential.scope["repository_ref"]:
        raise PermissionDenied("Conditional selection/claim/settlement scope differs from this pairing's repository.")


@delegated
def conditional_select(credential, member, value):
    fields = ("scope_ref", "location_sha256", "connector_task_ref", "selection_request")
    object_fields(value, fields, fields)
    _conditional_scope(credential, value)
    link = connectors._link(credential, value["connector_task_ref"], value["location_sha256"])
    data = value["selection_request"]
    if not isinstance(data, dict) or data.get("repository_ref") != credential.scope["repository_ref"]:
        raise PermissionDenied("Selection proposal repository is outside the paired collection scope.")
    from .tasks import _scope
    _scope(member, credential.scope["repository_ref"], data.get("task", {}))
    from .selection import select
    return select(member, connectors.uuid_value(value["scope_ref"]), data, connector_link=link)


@delegated
def conditional_claim(credential, member, value):
    fields = ("scope_ref", "location_sha256", "selection_id")
    object_fields(value, fields, fields)
    _conditional_scope(credential, value)
    from .selection import claim
    return claim(member, connectors.uuid_value(value["scope_ref"]), value["selection_id"])


@delegated
def conditional_settle(credential, member, value):
    fields = ("scope_ref", "location_sha256", "selection_id", "cost_usd", "outcome")
    object_fields(value, fields, fields)
    _conditional_scope(credential, value)
    if "cost_usd" not in credential.scope["collection_fields"]:
        raise PermissionDenied("Reported cost collection is not approved for this pairing.")
    from .tasks import _scope
    _scope(member, credential.scope["repository_ref"], {"cost_usd": value["cost_usd"]})
    from .selection import settle
    return settle(member, connectors.uuid_value(value["scope_ref"]), value["selection_id"], value["cost_usd"], value["outcome"])
