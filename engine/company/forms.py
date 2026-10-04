import json

from django import forms
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError

from engine.importers import parse_json
from engine.privacy import PrivacyError, ensure_safe, redact_text
from engine.schemas import ValidationError

from .models import Membership
from .services import SUPPORTED_COLLECTION_FIELDS, validate_configuration, validate_permissions, validate_username


class StrictForm(forms.Form):
    multiple_fields = ()

    def add_error(self, field, error):
        if not isinstance(error, DjangoValidationError):
            error = DjangoValidationError(error)
        super().add_error(field, [redact_text(message) for message in error.messages])

    def sanitize_display(self):
        if not self.is_bound:
            return
        data = self.data.copy()
        for field, definition in self.fields.items():
            if isinstance(definition.widget, forms.PasswordInput):
                continue
            values = data.getlist(field)
            try:
                if field == "confirmation_token" and data.get(field):
                    try:
                        signed = signing.loads(data[field], salt="company-browser-confirmation", max_age=900)
                    except signing.BadSignature:
                        data[field] = ""
                    else:
                        # Redisplay only a genuine, safe metadata envelope, not arbitrary token-like input.
                        ensure_safe(signed)
                elif field == "policy_json":
                    value = data.get(field, "")
                    try:
                        ensure_safe(parse_json(value))
                    except ValidationError:
                        for line in value.splitlines():
                            ensure_safe(line)
                elif field == "repositories":
                    for line in data.get(field, "").splitlines():
                        ensure_safe(line)
                else:
                    for value in values:
                        ensure_safe(value)
            except PrivacyError:
                data[field] = ""
        # This changes only refused form display, never accepted routing/configuration data.
        self.data = data

    def clean(self):
        data = super().clean()
        if set(self.data) - set(self.fields) - {"csrfmiddlewaretoken"}:
            raise DjangoValidationError("Unexpected form fields; this operation was refused.")
        if any((len(self.data.getlist(field)) != 1 if field not in self.multiple_fields else
                len(self.data.getlist(field)) != len(set(self.data.getlist(field))))
               for field in self.data if field != "csrfmiddlewaretoken"):
            raise DjangoValidationError("Duplicate form values are not supported.")
        return data


class SelectorMultipleField(forms.MultipleChoiceField):
    def clean(self, value):
        # Preserve old single comma-list submissions; the browser uses labeled choices.
        if isinstance(value, list) and len(value) == 1 and "," in value[0]:
            value = [item.strip() for item in value[0].split(",") if item.strip()]
        if value and len(value) != len(set(value)):
            raise DjangoValidationError("Duplicate selections are not supported.")
        return super().clean(value)


class LoginForm(StrictForm):
    username = forms.CharField(max_length=64)
    password = forms.CharField(widget=forms.PasswordInput, max_length=1024)


class JoinForm(StrictForm):
    invitation = forms.CharField(widget=forms.PasswordInput, max_length=43, min_length=43,
                                 help_text="Paste the private invitation supplied by your administrator.")
    password1 = forms.CharField(widget=forms.PasswordInput, max_length=1024, label="Choose a password")
    password2 = forms.CharField(widget=forms.PasswordInput, max_length=1024, label="Repeat password")

    def clean(self):
        data = super().clean()
        if data.get("password1") != data.get("password2"):
            raise DjangoValidationError("The passwords do not match.")
        return data


class AdministratorForm(StrictForm):
    expected_revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    reason = forms.CharField(max_length=256, label="Reason for this change")
    confirm_password = forms.CharField(widget=forms.PasswordInput, max_length=1024,
                                       label="Confirm your administrator password")


class InvitationForm(AdministratorForm):
    username = forms.CharField(max_length=64)
    role = forms.ChoiceField(choices=Membership.ROLES)
    participating = forms.BooleanField(required=False, label="Participating developer (approved collection)")
    can_manage_company = forms.BooleanField(required=False, label="May administer company setup")
    can_approve_pilots = forms.BooleanField(required=False, label="Designated pilot approver (does not enable routing)")
    expires_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
                                    label="Invitation expiry (UTC, within seven days)")

    def clean(self):
        data = super().clean()
        try:
            if "username" in data:
                validate_username(data["username"])
            if "role" in data:
                validate_permissions(data["role"], data["participating"], data["can_manage_company"], data["can_approve_pilots"])
        except (ValidationError, PrivacyError) as error:
            raise DjangoValidationError(str(error)) from None
        return data


class MemberForm(AdministratorForm):
    role = forms.ChoiceField(choices=Membership.ROLES)
    active = forms.BooleanField(required=False)
    participating = forms.BooleanField(required=False)
    can_manage_company = forms.BooleanField(required=False)
    can_approve_pilots = forms.BooleanField(required=False)


class ConfigurationForm(AdministratorForm):
    name = forms.CharField(max_length=128, label="Company name")
    policy_json = forms.CharField(widget=forms.Textarea(attrs={"rows": 16, "cols": 70}), label="Existing engine policy JSON")
    repositories = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), help_text="One explicit approved repository reference per line.")
    collection_fields = forms.MultipleChoiceField(choices=[(field, field) for field in SUPPORTED_COLLECTION_FIELDS],
                                                   widget=forms.CheckboxSelectMultiple)
    company_api_attested = forms.BooleanField(label="Confirm company-managed API/gateway use, not consumer subscriptions")

    def clean(self):
        # Multiple checkboxes are intentional; other form fields must still be unique.
        data = forms.Form.clean(self)
        if set(self.data) - set(self.fields) - {"csrfmiddlewaretoken"} or any(
            len(self.data.getlist(field)) != 1 for field in self.data if field not in ("collection_fields", "csrfmiddlewaretoken")
        ):
            raise DjangoValidationError("Unexpected or duplicate form fields; this operation was refused.")
        if all(field in data for field in ("name", "policy_json", "repositories", "collection_fields", "company_api_attested")):
            try:
                config = validate_configuration(data["name"], parse_json(data["policy_json"]),
                                                [line.strip() for line in data["repositories"].splitlines() if line.strip()],
                                                data["collection_fields"], data["company_api_attested"])
            except (ValidationError, PrivacyError) as error:
                # Refuse unsafe input; do not redisplay suspected secrets in bound fields.
                self.data = self.data.copy()
                for field in ("name", "policy_json", "repositories"):
                    self.data[field] = ""
                raise DjangoValidationError(str(error)) from None
            data["configuration"] = config
        return data

    @classmethod
    def initial_for(cls, company):
        return {"expected_revision": company.revision, "name": company.name,
                "policy_json": json.dumps(company.policy, indent=2), "repositories": "\n".join(company.repository_refs),
                "collection_fields": company.collection_fields, "company_api_attested": company.company_api_attested}
