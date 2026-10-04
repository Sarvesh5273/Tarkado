"""Bind browser confirmations to the exact metadata reviewed, never to passwords or MFA codes."""

from django.core import signing

from engine.schemas import ValidationError
from engine.privacy import ensure_safe


def payload(form, request, binding):
    return {"account_id": request.user.pk, "binding": binding,
            "values": {key: str(value) if not isinstance(value, (list, bool, int)) and value is not None else value
                       for key, value in form.cleaned_data.items()
                       if key not in ("confirm_password", "code", "preview", "confirmation", "confirmation_token")}}


def prepare(form, request, binding):
    value = payload(form, request, binding)
    ensure_safe(value)
    token = signing.dumps(value, salt="company-browser-confirmation")
    data = form.data.copy()
    data["preview"] = "confirm"
    data["confirmation_token"] = token
    data.pop("confirm_password", None)
    data.pop("code", None)
    data.pop("confirmation", None)
    confirmed = type(form)(data, **form.confirmation_options)
    for key, definition in confirmed.fields.items():
        if key in ("confirm_password", "code"):
            definition.required = False
    hide_metadata(confirmed)
    # Password/code are deliberately blank at the confirmation stage.
    return confirmed


def hide_metadata(form):
    for key, definition in form.fields.items():
        if key not in ("confirm_password", "code", "confirmation"):
            from django import forms
            definition.widget = forms.MultipleHiddenInput() if key in form.multiple_fields else forms.HiddenInput()


def verify(form, request, binding):
    if form.cleaned_data.get("preview") != "confirm":
        return
    try:
        saved = signing.loads(form.cleaned_data.get("confirmation_token", ""), salt="company-browser-confirmation", max_age=900)
    except signing.BadSignature:
        raise ValidationError("Confirmation expired or changed; review the exact content again.") from None
    if saved != payload(form, request, binding) or not form.cleaned_data.get("confirmation"):
        raise ValidationError("Confirm the exact displayed content; changed scope requires a new review.")
