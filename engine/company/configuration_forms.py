"""Guided editing of the existing policy contract, without a browser JSON editor."""

from django import forms
from django.core.exceptions import ValidationError as DjangoValidationError

from engine.privacy import PrivacyError
from engine.schemas import Policy, ValidationError

from .forms import AdministratorForm, SelectorMultipleField
from .services import COLLECTION_FIELDS, validate_configuration


class BrowserConfigurationForm(AdministratorForm):
    multiple_fields = ("collection_fields",)
    name = forms.CharField(max_length=128, label="Company name")
    policy_version = forms.CharField(max_length=128, help_text="Use a new version whenever model capabilities, approval, fallback, or rules change. Old task snapshots remain immutable.")
    default_model = forms.ChoiceField(choices=(), label="Approved premium fallback")
    repositories = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="One explicit approved repository reference per line; no wildcards.")
    collection_fields = SelectorMultipleField(choices=[(item, item.replace("_", " ")) for item in COLLECTION_FIELDS], widget=forms.CheckboxSelectMultiple)
    company_api_attested = forms.BooleanField(label="Confirm company-managed API/gateway use, never consumer subscriptions")

    def __init__(self, *args, company, **kwargs):
        self.company = company
        self.policy = Policy.from_dict(company.policy)
        initial = {"expected_revision": company.revision, "name": company.name, "policy_version": self.policy.policy_version,
                   "default_model": self.policy.default_model, "repositories": "\n".join(company.repository_refs),
                   "collection_fields": company.collection_fields, "company_api_attested": company.company_api_attested}
        initial.update(kwargs.pop("initial", {}))
        super().__init__(*args, initial=initial, **kwargs)
        choices = [(model.model_id, f"{model.model_id} — {model.status}, {model.tier}") for model in self.policy.models]
        self.fields["default_model"].choices = choices
        self.model_sections, self.rule_sections = [], []
        for index, model in enumerate(self.policy.models):
            prefix = f"model_{index}_"
            fields = self._model_fields(prefix)
            self.model_sections.append((model.model_id, fields))
            for field, value in (("tier", model.tier), ("status", model.status), ("task_types", ",".join(model.task_types)),
                                 ("tools", ",".join(model.tools)), ("max_context_tokens", model.max_context_tokens)):
                self.initial[prefix + field] = value
        self.fields["new_model_id"] = forms.CharField(required=False, max_length=1024, label="Optional new provider/model ID")
        self.new_model_fields = self._model_fields("new_model_", required=False)
        for index, rule in enumerate(self.policy.rules):
            prefix = f"rule_{index}_"
            self.fields[prefix + "model"] = forms.ChoiceField(choices=choices, label="Suggested model")
            self.fields[prefix + "evidence_refs"] = forms.CharField(required=False, max_length=1024, label="Declared evidence references", help_text="Comma-separated metadata references; a label is not verified evidence.")
            self.initial[prefix + "model"] = rule.model
            self.initial[prefix + "evidence_refs"] = ",".join(rule.evidence_refs)
            self.rule_sections.append((rule.task_type, [prefix + "model", prefix + "evidence_refs"]))
        self.fields["new_rule_category"] = forms.CharField(required=False, max_length=128, label="Optional new category rule")
        self.fields["new_rule_model"] = forms.ChoiceField(required=False, choices=[("", "No new rule")] + choices, label="New rule's suggested model")
        self.fields["new_rule_evidence_refs"] = forms.CharField(required=False, max_length=1024, label="New rule's declared evidence references")

    def _model_fields(self, prefix, required=True):
        self.fields[prefix + "tier"] = forms.ChoiceField(required=required, choices=([("", "Choose tier")] if not required else []) + [(item, item) for item in ("cheap", "standard", "premium")], label="Tier")
        self.fields[prefix + "status"] = forms.ChoiceField(required=required, choices=([("", "Choose state")] if not required else []) + [(item, item) for item in ("candidate", "shadow", "approved", "disabled")], label="Approval state", help_text="Candidate/shadow/disabled models are not authorized for suggestions or routing.")
        self.fields[prefix + "task_types"] = forms.CharField(required=False, max_length=1024, label="Supported categories", help_text="Comma-separated capability declarations. * means all categories for this model, not pilot scope.")
        self.fields[prefix + "tools"] = forms.CharField(required=False, max_length=1024, label="Supported tools", help_text="Comma-separated capabilities; no capability is independently discovered here.")
        self.fields[prefix + "max_context_tokens"] = forms.IntegerField(required=required, min_value=1, label="Maximum context tokens")
        return [prefix + field for field in ("tier", "status", "task_types", "tools", "max_context_tokens")]

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        def items(field):
            return [value.strip() for value in data[field].split(",") if value.strip()]
        models = []
        for index, model in enumerate(self.policy.models):
            prefix = f"model_{index}_"
            models.append({"model_id": model.model_id, "tier": data[prefix + "tier"], "status": data[prefix + "status"],
                           "task_types": items(prefix + "task_types"), "tools": items(prefix + "tools"),
                           "max_context_tokens": data[prefix + "max_context_tokens"]})
        if data["new_model_id"]:
            if not all(data["new_model_" + key] for key in ("tier", "status", "max_context_tokens")):
                raise DjangoValidationError("A new model needs an explicit tier, approval state, and context capacity.")
            models.append({"model_id": data["new_model_id"], "tier": data["new_model_tier"], "status": data["new_model_status"],
                           "task_types": items("new_model_task_types"), "tools": items("new_model_tools"),
                           "max_context_tokens": data["new_model_max_context_tokens"]})
        elif any(data.get(key) for key in self.new_model_fields):
            raise DjangoValidationError("Supply a new model ID or leave all new-model fields blank.")
        rules = [{"task_type": rule.task_type, "model": data[f"rule_{index}_model"], "evidence_refs": items(f"rule_{index}_evidence_refs")} for index, rule in enumerate(self.policy.rules)]
        if data["new_rule_category"]:
            if not data["new_rule_model"]:
                raise DjangoValidationError("A new category rule needs an explicit model.")
            rules.append({"task_type": data["new_rule_category"], "model": data["new_rule_model"], "evidence_refs": items("new_rule_evidence_refs")})
        elif data["new_rule_model"] or data["new_rule_evidence_refs"]:
            raise DjangoValidationError("Supply a new rule category or leave new-rule fields blank.")
        policy = {"policy_version": data["policy_version"], "default_model": data["default_model"], "models": models, "rules": rules}
        try:
            data["configuration"] = validate_configuration(data["name"], policy,
                [line.strip() for line in data["repositories"].splitlines() if line.strip()], data["collection_fields"], data["company_api_attested"])
        except (ValidationError, PrivacyError) as error:
            raise DjangoValidationError(str(error)) from None
        return data

    def sections(self):
        return {"model_sections": [(label, [self[key] for key in fields]) for label, fields in self.model_sections],
                "rule_sections": [(label, [self[key] for key in fields]) for label, fields in self.rule_sections],
                "new_model_fields": [self["new_model_id"]] + [self[key] for key in self.new_model_fields],
                "new_rule_fields": [self[key] for key in ("new_rule_category", "new_rule_model", "new_rule_evidence_refs")],
                "configuration_fields": [self[key] for key in ("name", "policy_version", "default_model", "repositories", "collection_fields", "company_api_attested")],
                "confirmation_fields": [self[key] for key in ("reason", "confirm_password")]}
