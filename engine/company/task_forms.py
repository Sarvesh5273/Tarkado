"""Manual metadata forms; actors, record IDs, and timestamps come from the server."""

from django import forms

from .forms import StrictForm
from engine.schemas import Policy


class TaskForm(StrictForm):
    repository_ref = forms.CharField(max_length=1024, label="Approved repository reference")
    source_kind = forms.ChoiceField(choices=(("synthetic", "Synthetic demonstration"), ("team", "Approved manual team observation (unverified label)")))
    boundary = forms.ChoiceField(choices=(("new_task", "New task"), ("new_run", "New run"), ("subagent", "New subagent")))
    task_id = forms.CharField(max_length=128, help_text="Metadata reference only; do not paste task content.")
    session_id = forms.CharField(max_length=128, label="Manual session reference", help_text="This is not permission to read an OpenCode session.")
    task_type = forms.CharField(max_length=128, required=False)
    risk_tags = forms.CharField(max_length=1024, required=False, help_text="Comma-separated tags. Enter low only when justified; blank means unknown risk.")
    selected_model = forms.CharField(max_length=1024, label="Model you currently selected")
    required_tools = forms.CharField(max_length=1024, required=False, help_text="Comma-separated tool requirements.")
    context_tokens = forms.IntegerField(min_value=0, required=False, help_text="Leave blank when unknown; do not invent a capacity requirement.")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            policy = Policy.from_dict(company.policy)
            self.fields["repository_ref"] = forms.ChoiceField(
                choices=[(item, item) for item in company.repository_refs], label="Approved repository")
            self.fields["selected_model"].widget = forms.Select(choices=[
                (model.model_id, f"{model.model_id} — {model.tier}, {model.status}") for model in policy.models])
            categories = sorted({rule.task_type for rule in policy.rules} | {
                category for model in policy.models for category in model.task_types if category != "*"})
            self.fields["task_type"].widget.attrs["list"] = "task-categories"
            self.categories = categories
            for field in ("task_type", "risk_tags", "required_tools", "context_tokens"):
                if field not in company.collection_fields:
                    self.fields[field].widget = forms.HiddenInput()
                    self.fields[field].help_text = "Not approved for collection; leave unknown."
        self.fields["task_id"].label = "Task label"
        self.fields["session_id"].label = "Manual work-session label"
        self.fields["task_type"].label = "Task category (blank means unknown)"
        self.fields["selected_model"].help_text = "Your manual choice is retained. No model executes here."

    def payload(self):
        data = dict(self.cleaned_data)
        data["task_type"] = data["task_type"] or None
        for field in ("risk_tags", "required_tools"):
            data[field] = [value.strip() for value in data[field].split(",") if value.strip()]
        return data


class TaskActionForm(StrictForm):
    expected_revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class ResponseForm(TaskActionForm):
    response = forms.ChoiceField(choices=(("accept", "Accept this task's suggestion"), ("reject", "Reject this task's suggestion")))


class ExecutionForm(TaskActionForm):
    actual_model = forms.CharField(max_length=1024, label="Model actually used (reported, not executed here)")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            policy = Policy.from_dict(company.policy)
            self.fields["actual_model"].widget.attrs["list"] = "actual-models"
            self.models = [model.model_id for model in policy.models]
        self.fields["actual_model"].help_text = "Choose a known model or enter another reported model. Unapproved use is retained, never authorized."


class ResultForm(TaskActionForm):
    BOOLEAN_CHOICES = (("unknown", "Unknown"), ("true", "Yes"), ("false", "No"))
    desired_result = forms.ChoiceField(choices=BOOLEAN_CHOICES, label="Did the task meet its desired result?")
    tests_passed = forms.ChoiceField(choices=BOOLEAN_CHOICES)
    score = forms.DecimalField(min_value=0, max_value=1, required=False)
    cost_usd = forms.DecimalField(min_value=0, required=False, label="Reported cost in USD")
    latency_ms = forms.IntegerField(min_value=0, required=False)
    evidence_ref = forms.CharField(max_length=1024, required=False, help_text="Metadata-only confirmation reference, not code, output, or a secret.")
    supersedes = forms.CharField(max_length=128, required=False, widget=forms.HiddenInput)

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("score", "cost_usd", "latency_ms"):
            self.fields[field].help_text = "Leave blank when unknown. Zero is a reported measurement, not unknown."
        if company is not None:
            for field in ("desired_result", "tests_passed", "score", "cost_usd", "latency_ms", "evidence_ref"):
                if field not in company.collection_fields:
                    self.fields[field].widget = forms.HiddenInput()

    def payload(self):
        data = {field: value for field, value in self.cleaned_data.items() if field != "expected_revision"}
        for field in ("desired_result", "tests_passed"):
            data[field] = {"unknown": None, "true": True, "false": False}[data[field]]
        for field in ("score", "cost_usd"):
            data[field] = str(data[field]) if data[field] is not None else None
        for field in ("evidence_ref", "supersedes"):
            data[field] = data[field] or None
        return data
