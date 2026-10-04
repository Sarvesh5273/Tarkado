"""Separate human controls for conditional selection, never a browser execution endpoint."""

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from engine.privacy import PrivacyError, ensure_safe
from engine.schemas import ValidationError

from . import selection
from . import confirmation
from .control_views import SensitiveForm
from .views import protected, _form_error
from django import forms


class SelectionControlForm(SensitiveForm):
    action = forms.ChoiceField(choices=())
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(max_length=256)
    confirmation = forms.BooleanField(label="I reviewed this exact scope and conditional selection state; no model request is sent")
    preview = forms.ChoiceField(choices=(("scope", "scope"), ("confirm", "confirm")), required=False, widget=forms.HiddenInput)
    confirmation_token = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["action"].choices = choices
        self.confirmation_options = {"choices": choices}
        if self.data.get("preview") == "scope" or not self.is_bound:
            for key in ("confirm_password", "code", "confirmation"):
                self.fields[key].required = False


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def controls(request, reference):
    state = selection.status(request, reference)
    if state["scope_record"].data.get("target") != "live":
        raise PermissionDenied("Conditional selection requires separate live-scope approval, not a simulation receipt.")
    actions = []
    if state["selection_status"] == "unactivated" and state["guard"]["status"] == "current":
        actions = [("activate", "Activate conditional selection (admission still required)")]
    elif state["selection_status"] in ("active", "paused"):
        actions = [("revoke", "Revoke runtime and live scope"), ("rollback", "Withdraw to default-only")]
        if state["selection_status"] == "active":
            actions.insert(0, ("pause", "Pause"))
        elif state["guard"]["status"] == "current":
            from .models import ScopedSelectionRuntime
            runtime = ScopedSelectionRuntime.objects.get(authorization=state["scope_record"])
            current = selection._state(runtime)
            from decimal import Decimal
            if not any(item["outcome"] == "failed" or Decimal(item["cost_usd"]) > Decimal(current["decisions"][key]["reserve_usd"])
                       for key, item in current["settlements"].items()):
                actions.insert(0, ("resume", "Resume after current scope checks"))
    form = SelectionControlForm(request.POST if request.method == "POST" else None, choices=actions,
                                initial={"expected_revision": state["revision"], "preview": "scope"})
    if request.method == "POST":
        from .services import current_member
        current_member(request.user, "approve")
        if form.is_valid():
            data = form.cleaned_data
            try:
                binding = {"scope_ref": str(reference), "scope_sha256": state["scope_record"].data["sha256"]}
                if data.get("preview") == "scope":
                    if data["expected_revision"] != state["revision"]:
                        raise ValidationError("Selection state changed; reload before previewing stale control.")
                    return render(request, "company/selection_control.html", {**state, "form": confirmation.prepare(form, request, binding),
                                  "actions": actions, "confirming": True, "preview_values": data})
                confirmation.verify(form, request, binding)
                if data["action"] == "activate":
                    if data["expected_revision"] != 0:
                        raise ValidationError("Unactivated runtime must be reviewed at revision zero.")
                    selection.activate(request, data["confirm_password"], data["code"], reference, data["reason"], expected_revision=data["expected_revision"])
                else:
                    selection.control(request, data["confirm_password"], data["code"], reference, data["action"], data["expected_revision"], data["reason"])
            except (ValidationError, PrivacyError, PermissionDenied) as error:
                _form_error(form, error)
            else:
                return redirect("company-selection-control", reference=reference)
    form.sanitize_display()
    context = {**state, "form": form, "actions": actions}
    if request.method == "POST" and request.POST.get("preview") == "confirm" and all(
        key in form.cleaned_data for key in ("action", "expected_revision", "reason")
    ):
        try:
            ensure_safe(confirmation.payload(form, request, {"scope_ref": str(reference)}))
        except PrivacyError:
            pass
        else:
            confirmation.hide_metadata(form)
            context.update(confirming=True, preview_values=form.cleaned_data)
    return render(request, "company/selection_control.html", context)
