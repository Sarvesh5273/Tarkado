"""Guided administrative billing review, not a manual billing-truth or delivery permission."""

import uuid

from django import forms
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from engine.privacy import PrivacyError
from engine.schemas import ValidationError

from . import billing_corrections, confirmation, delivery
from .control_views import SensitiveForm
from .operations import delivery_summary
from .views import _form_error, protected


class CostCorrectionForm(SensitiveForm):
    attempt_id = forms.ChoiceField(choices=(), label="Exact request / physical attempt")
    cost_usd = forms.CharField(max_length=256, label="Correct total cost of this attempt (USD, exact decimal)",
        help_text="Not an extra charge or a delta. Both increases and decreases require independent billing evidence.")
    evidence_ref = forms.CharField(max_length=256, label="Billing evidence reference (metadata only)",
        help_text="Never paste invoice bodies, outputs or credentials. A reference alone cannot verify a cost.")
    correction_id = forms.UUIDField(widget=forms.HiddenInput)
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    request_id = forms.CharField(required=False, widget=forms.HiddenInput)
    supersedes_sha256 = forms.CharField(required=False, widget=forms.HiddenInput)
    preview = forms.ChoiceField(choices=(("scope", "Review"), ("confirm", "Confirm")), widget=forms.HiddenInput)
    confirmation_token = forms.CharField(required=False, widget=forms.HiddenInput)
    confirmation = forms.BooleanField(label="Append only this verified correction. Preserve failures, pilot state, lifetime task slots and consumed delivery claims.")

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attempt_id"].choices = choices
        self.confirmation_options = {"choices": choices}
        if not self.is_bound or self.data.get("preview") == "scope":
            for key in ("confirm_password", "code", "confirmation"):
                self.fields[key].required = False

    def value(self):
        return {key: str(self.cleaned_data[key]) if key == "correction_id" else self.cleaned_data[key] for key in billing_corrections.INPUT_FIELDS}


@sensitive_post_parameters("__ALL__")
@protected("manage")
@require_http_methods(["GET", "POST"])
def correction(request, reference):
    binding = billing_corrections._human_binding(request.company_member, reference)
    current = delivery.state(binding)
    choices = [(key, f"{row['request_id']} / {key} — {row['outcome']}, current USD {row['cost_usd']}, cost revision {row['cost_revision']}")
        for key, row in current["attempts"].items() if row["cost_usd"] is not None]
    form = CostCorrectionForm(request.POST if request.method == "POST" else None, choices=choices,
        initial={"correction_id": str(uuid.uuid4()), "expected_revision": current["revision"], "preview": "scope"})
    context = {"form": form, "task": binding.connector_task.task, "delivery_state": delivery_summary(binding)}
    if request.method == "POST" and form.is_valid():
        try:
            data = form.cleaned_data
            if data["preview"] == "scope":
                row = current["attempts"][data["attempt_id"]]
                if data["expected_revision"] != current["revision"]:
                    raise ValidationError("Accounting changed; reload before reviewing a stale correction.")
                for key, value in (("request_id", row["request_id"]), ("supersedes_sha256", row["cost_head_sha256"])):
                    if data[key] and data[key] != value:
                        raise ValidationError("Selected attempt differs from the submitted cost history.")
                    data[key] = value
                form.data = form.data.copy()
                form.data.update({key: data[key] for key in ("request_id", "supersedes_sha256")})
                review = billing_corrections.review_human(request, reference, **form.value())
                confirmed_binding = {"binding_ref": str(reference), "billing_assessment": review["correction"]["billing_assessment"]}
                return render(request, "company/cost_correction.html", {**context, "form": confirmation.prepare(form, request, confirmed_binding),
                    "confirming": True, "review": review})
            try:
                saved = signing.loads(data["confirmation_token"], salt="company-browser-confirmation", max_age=900)
            except signing.BadSignature:
                raise ValidationError("Confirmation expired or changed; review the exact billing evidence again.") from None
            confirmed_binding = saved.get("binding", {})
            if confirmed_binding.get("binding_ref") != str(reference):
                raise ValidationError("Billing confirmation belongs to another task binding.")
            confirmation.verify(form, request, confirmed_binding)
            billing_corrections.correct_human(request, data["confirm_password"], data["code"], reference,
                confirmed_binding.get("billing_assessment"), **form.value())
        except (ValidationError, PrivacyError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-task-detail", reference=binding.connector_task.task.reference)
    form.sanitize_display()
    return render(request, "company/cost_correction.html", context)
