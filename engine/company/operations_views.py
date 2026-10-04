from django import forms
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from engine.privacy import PrivacyError
from engine.schemas import ValidationError
from . import delivery, operations, policy_handoff
from .forms import StrictForm
from .models import GatewayCredential, Membership
from .views import _form_error, _form_page, protected


class PrivacyForm(StrictForm):
    action = forms.ChoiceField(choices=(("pause_collection", "Pause new task collection and delivery"), ("resume_collection", "Resume approved collection only; no pilot activation"),
                                       ("review_retention", "Set a manual retention-review reminder; never delete")))
    reason = forms.CharField(max_length=1024)
    review_at = forms.DateTimeField(required=False, label="Review reminder (UTC, only for retention review)")
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)
    code = forms.CharField(widget=forms.PasswordInput, label="Fresh unused authenticator code")
    confirmation = forms.BooleanField(label="Preserve all records, failures, reservations, keys and backups. No automatic deletion or raw-content collection.")


class GatewayForm(StrictForm):
    gateway_id = forms.CharField(max_length=128, label="Stable company gateway identity")
    repository_ref = forms.ChoiceField(choices=())
    expires_at = forms.DateTimeField(label="Expiry (UTC, within 24 hours)")
    expected_revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)
    code = forms.CharField(widget=forms.PasswordInput, label="Fresh unused authenticator code")
    confirmation = forms.BooleanField(label="Grant gateway metadata/delivery accounting only, not employee feedback or human pilot approval")

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["repository_ref"].choices = [(ref, ref) for ref in company.repository_refs]
        self.members = list(Membership.objects.filter(company=company, active=True, participating=True).order_by("developer_id"))
        for member in self.members:
            self.fields[f"user_{member.pk}"] = forms.CharField(required=False, max_length=128, label=f"LiteLLM authenticated user ID for {member.developer_id}",
                help_text="Use the existing gateway's authenticated user identity; leave unmapped developers blank. A request's user field is not authentication.")

    def mapping(self):
        return {member.developer_id: self.cleaned_data[f"user_{member.pk}"] for member in self.members if self.cleaned_data[f"user_{member.pk}"]}


class GatewayRevokeForm(StrictForm):
    confirm_password = forms.CharField(widget=forms.PasswordInput)
    code = forms.CharField(widget=forms.PasswordInput)
    confirmation = forms.BooleanField(label="Stop new use of this machine credential; retain its task obligations and renew separately for late reconciliation")


@protected()
@require_http_methods(["GET"])
def monitoring(request):
    return render(request, "company/monitoring.html", operations.monitor(request))


@sensitive_post_parameters("__ALL__")
@protected("manage")
@require_http_methods(["GET", "POST"])
def privacy(request):
    state = operations.privacy_state(request.company_member.company)
    form = PrivacyForm(request.POST if request.method == "POST" else None, initial={"expected_revision": state["revision"]})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            operations.privacy_control(request, data["confirm_password"], data["code"], data["action"], data["reason"], data["expected_revision"], data["review_at"])
        except (PrivacyError, ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-monitoring")
    return _form_page(request, "company/form.html", {"title": "Explicit privacy/retention controls — no deletion", "form": form})


@sensitive_post_parameters("__ALL__")
@protected("manage")
@require_http_methods(["GET", "POST"])
def gateways(request):
    company = request.company_member.company
    form = GatewayForm(request.POST if request.method == "POST" else None, company=company, initial={"expected_revision": company.revision})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            gateway, value = delivery.issue_gateway(request, data["confirm_password"], data["code"], data["gateway_id"], data["repository_ref"], form.mapping(), data["expires_at"], data["expected_revision"])
        except (PrivacyError, ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return render(request, "company/gateway_created.html", {"gateway": gateway, "machine_value": value})
    form.sanitize_display()
    return render(request, "company/gateways.html", {"form": form, "gateways": GatewayCredential.objects.filter(company=company).order_by("-id")})


@sensitive_post_parameters("__ALL__")
@protected("manage")
@require_http_methods(["GET", "POST"])
def revoke_gateway(request, reference):
    form = GatewayRevokeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            delivery.revoke_gateway(request, form.cleaned_data["confirm_password"], form.cleaned_data["code"], reference)
        except (PrivacyError, ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-gateways")
    return _form_page(request, "company/form.html", {"title": "Revoke gateway metadata credential", "form": form})


@protected()
@require_http_methods(["GET"])
def handoff(request, reference):
    return JsonResponse(policy_handoff.build(request, reference), json_dumps_params={"ensure_ascii": True})
