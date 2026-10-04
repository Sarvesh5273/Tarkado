"""Joined recovery, category review, and separately authorized pilot controls."""

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.db import transaction
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from engine.privacy import PrivacyError
from engine.schemas import ValidationError

from . import authorization, recovery
from .forms import SelectorMultipleField, StrictForm
from .models import EvidenceReview, Membership, PilotAuthorization
from .services import current_member
from .task_forms import TaskForm
from .tasks import INPUT_FIELDS, task_ledger
from .views import _form_error, _form_page, protected
from .presentation import developer_pilot, pilot_details, review_page
from . import confirmation


class SensitiveForm(StrictForm):
    confirm_password = forms.CharField(widget=forms.PasswordInput, max_length=1024)
    code = forms.CharField(widget=forms.PasswordInput, max_length=64, label="Fresh unused authenticator code")


class ResetForm(StrictForm):
    username = forms.CharField(max_length=64)
    recovery_credential = forms.CharField(widget=forms.PasswordInput, max_length=64)
    password1 = forms.CharField(widget=forms.PasswordInput, max_length=1024, label="New password")
    password2 = forms.CharField(widget=forms.PasswordInput, max_length=1024, label="Repeat new password")
    factor_kind = forms.ChoiceField(choices=(("authenticator", "Authenticator"), ("backup", "One-use backup code")))
    code = forms.CharField(widget=forms.PasswordInput, max_length=64, required=False)

    def clean(self):
        data = super().clean()
        if data.get("password1") != data.get("password2"):
            raise DjangoValidationError("New passwords must match.")
        return data


class AssistedRecoveryForm(SensitiveForm):
    account_id = forms.TypedChoiceField(choices=(), coerce=int, label="Intended company account")
    expires_at = forms.DateTimeField(help_text="Explicit expiry within one hour, UTC.")
    reason = forms.CharField(max_length=256)
    identity_ref = forms.CharField(max_length=256, label="Private identity-confirmation reference (metadata only)")

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account_id"].choices = [(item.user_id, f"{item.developer_id} — {item.get_role_display()}") for item in Membership.objects.filter(company=company).order_by("developer_id")]


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def personal_recovery(request):
    form = SensitiveForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            value = recovery.issue_personal(request, form.cleaned_data["confirm_password"], form.cleaned_data["code"])
        except (ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return render(request, "company/private_recovery.html", {"value": value})
    return _form_page(request, "company/form.html", {"title": "Issue your private offline password-recovery credential", "form": form})


@sensitive_post_parameters("__ALL__")
@protected("manage")
@require_http_methods(["GET", "POST"])
def assisted_recovery(request):
    form = AssistedRecoveryForm(request.POST if request.method == "POST" else None, company=request.company_member.company)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            value = recovery.issue_assisted(request, data["confirm_password"], data["code"], data["account_id"],
                                            data["expires_at"], data["reason"], data["identity_ref"])
        except (ValidationError, PermissionDenied, PrivacyError) as error:
            _form_error(form, error)
        else:
            return render(request, "company/private_recovery.html", {"value": value, "assisted": True})
    return _form_page(request, "company/form.html", {"title": "Issue recovery only after verifying the intended person's identity", "form": form})


@sensitive_post_parameters("__ALL__")
@require_http_methods(["GET", "POST"])
def password_reset(request):
    form = ResetForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            accepted = recovery.reset_password(data["username"], data["recovery_credential"], data["password1"], data["code"], data["factor_kind"])
        except DjangoValidationError as error:
            _form_error(form, error)
        else:
            if accepted:
                return redirect("company-login")
            form.add_error(None, "Recovery verification failed or is temporarily limited. No account changes were made.")
    return _form_page(request, "company/form.html", {"title": "Recover your password; enrolled MFA is still required", "form": form})


class ReviewForm(StrictForm):
    multiple_fields = ("session_ids", "task_types")
    learner_version = forms.CharField(max_length=128)
    source_kind = forms.ChoiceField(choices=(("synthetic", "Synthetic demonstration"), ("team", "Manually declared team records (unverified)")))
    cutoff = forms.DateTimeField(help_text="Explicit validation cutoff, UTC")
    session_ids = SelectorMultipleField(choices=(), widget=forms.CheckboxSelectMultiple, label="Validation work sessions")
    task_types = SelectorMultipleField(choices=(), widget=forms.CheckboxSelectMultiple, label="Categories to review")
    min_senior_successes = forms.IntegerField(min_value=1, help_text="Experimental validation parameter, not production-approved")
    min_senior_sessions = forms.IntegerField(min_value=1, help_text="Experimental validation parameter, not production-approved")

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import CompanyTask
        source = self.data.get("source_kind", self.initial.get("source_kind", "synthetic"))
        sessions, categories = {}, set()
        for task in CompanyTask.objects.filter(company=company, source_kind=source).select_related("company", "owner"):
            rec = task_ledger(task).recommendations[0]
            sessions.setdefault(rec.task.session_id, {"owner": task.owner.username, "label": task.session_id, "count": 0})["count"] += 1
            if rec.task.task_type:
                categories.add(rec.task.task_type)
        self.fields["session_ids"].choices = [(key, f"{item['owner']} / {item['label']} — {item['count']} task(s)") for key, item in sessions.items()]
        self.fields["task_types"].choices = [(item, item) for item in sorted(categories)]
        self.fields["session_ids"].help_text = "References are resolved internally. All source records, including excluded failures, remain available to the existing learner checks."

    def plan(self):
        data = dict(self.cleaned_data, dataset_split="validation")
        data["cutoff"] = data["cutoff"].isoformat()
        return data


class AuthorizationForm(SensitiveForm):
    multiple_fields = ("task_types", "developer_ids")
    pilot_id = forms.CharField(max_length=128)
    repository_ref = forms.ChoiceField(choices=(), label="Approved repository")
    task_types = SelectorMultipleField(choices=(), widget=forms.CheckboxSelectMultiple, label="Exact category / model mappings")
    developer_ids = SelectorMultipleField(choices=(), widget=forms.CheckboxSelectMultiple, label="Permitted developers")
    max_tasks = forms.IntegerField(min_value=1)
    max_cost_usd = forms.DecimalField(min_value=0.000001)
    expires_at = forms.DateTimeField(help_text="Explicit expiry within seven days, UTC")
    reason = forms.CharField(max_length=256)
    expected_revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    target = forms.ChoiceField(choices=(("simulation", "Authenticated simulation only"), ("live", "Live scope approval (requires server-verified readiness; does not enable execution)")))
    decision = forms.ChoiceField(choices=(("approve", "Approve this exact scope"), ("reject", "Reject this scope; grant no routes")))
    preview = forms.ChoiceField(choices=(("scope", "scope"), ("confirm", "confirm")), required=False, widget=forms.HiddenInput)
    confirmation_token = forms.CharField(required=False, widget=forms.HiddenInput)
    confirmation = forms.BooleanField(required=False, label="I confirm this exact scope and separate pilot decision")

    def __init__(self, *args, company, review, **kwargs):
        super().__init__(*args, **kwargs)
        self.confirmation_options = {"company": company, "review": review}
        self.fields["repository_ref"].choices = [(item, item) for item in company.repository_refs]
        self.fields["task_types"].choices = [(item["task_type"], f"{item['task_type']} → {item['suggested_model'] or 'No eligible model'} — {item['status'].replace('_', ' ')}") for item in review.data["report"]["categories"]]
        members = Membership.objects.filter(company=company, active=True, user__is_active=True, participating=True, role__in=("junior", "developer", "senior")).order_by("developer_id")
        self.fields["developer_ids"].choices = [(item.developer_id, f"{item.developer_id} — {item.get_role_display()}") for item in members]
        if self.data.get("preview") == "scope" or not self.is_bound:
            for field in ("confirm_password", "code"):
                self.fields[field].required = False

    def scope(self):
        return {"pilot_id": self.cleaned_data["pilot_id"], "repository_ref": self.cleaned_data["repository_ref"],
                 "task_types": self.cleaned_data["task_types"],
                 "developer_ids": self.cleaned_data["developer_ids"],
                "max_tasks": self.cleaned_data["max_tasks"], "max_cost_usd": str(self.cleaned_data["max_cost_usd"])}


class PilotControlForm(SensitiveForm):
    action = forms.ChoiceField(choices=[(item, item) for item in ("activate", "pause", "resume", "revoke", "rollback")])
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(max_length=256)
    preview = forms.ChoiceField(choices=(("scope", "scope"), ("confirm", "confirm")), required=False, widget=forms.HiddenInput)
    confirmation_token = forms.CharField(required=False, widget=forms.HiddenInput)
    confirmation = forms.BooleanField(required=False, label="I confirm this exact pilot control and revision")

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["action"].choices = choices
        self.confirmation_options = {"choices": choices}
        if self.data.get("preview") == "scope" or not self.is_bound:
            for field in ("confirm_password", "code"):
                self.fields[field].required = False


class DecisionForm(TaskForm):
    reserve_usd = forms.DecimalField(min_value=0.000001)
    override_model = forms.CharField(max_length=1024, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_kind"].choices = (("synthetic", "Synthetic simulation only"),)
        self.fields["override_model"].widget = forms.Select(choices=[("", "No override")] + list(self.fields["selected_model"].widget.choices))
        self.fields["reserve_usd"].help_text = "Explicit simulated maximum cost commitment. Unknown is not zero; no provider cap or model call exists here."


class SettlementForm(StrictForm):
    decision_id = forms.ChoiceField(choices=(), label="Your recorded simulated task")
    actual_cost_usd = forms.DecimalField(min_value=0)
    outcome = forms.ChoiceField(choices=[(item, item) for item in ("completed", "failed", "cancelled")])

    def __init__(self, *args, decisions, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decision_id"].choices = [(row["id"], f"{row['task']['task_id']} — {row['result']['simulated_model']}, reserved USD {row['request']['reserve_usd']} — {'Settled (immutable retry only)' if row['settlement'] else 'Awaiting settlement'}") for row in decisions if row["result"]["status"] == "reserved"]
        self.fields["actual_cost_usd"].help_text = "Record the complete incurred cost, including overruns. Cancellation before use requires zero cost."


@protected()
@require_http_methods(["GET"])
def pilots(request):
    member = authorization._reviewer(request)
    reviews = EvidenceReview.objects.filter(company=member.company).order_by("-id")
    approvals = PilotAuthorization.objects.filter(company=member.company).order_by("-id")
    return render(request, "company/pilots.html", {"reviews": [review_page(item, member.company) for item in reviews],
                  "approvals": [pilot_details(authorization.status(request, item.reference)) for item in approvals]})


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def new_review(request):
    member = authorization._reviewer(request)
    source = request.GET.get("source", "synthetic")
    if source not in ("synthetic", "team"):
        source = "synthetic"
    form = ReviewForm(request.POST if request.method == "POST" else None, company=member.company,
                      initial={"source_kind": source, "cutoff": timezone.now()})
    if request.method == "POST" and form.is_valid():
        try:
            review = authorization.prepare_review(request, form.plan())
        except (ValidationError, PrivacyError) as error:
            _form_error(form, error)
        else:
            return redirect("company-review-detail", reference=review.reference)
    form.sanitize_display()
    return render(request, "company/review_form.html", {"form": form})


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def review_detail(request, reference):
    member = authorization._reviewer(request)
    review = EvidenceReview.objects.filter(company=member.company, reference=reference).first()
    if review is None:
        raise PermissionDenied("Review is unavailable for this company.")
    if request.method == "POST":
        # Preserve existing protected form submissions; ordinary navigation uses the separate scope page.
        return approve(request, reference)
    return render(request, "company/review_detail.html", review_page(review, member.company))


@sensitive_post_parameters("__ALL__")
@protected("approve")
@require_http_methods(["GET", "POST"])
def approve(request, reference):
    member = current_member(request.user, "approve")
    review = EvidenceReview.objects.filter(company=member.company, reference=reference).first()
    if review is None:
        raise PermissionDenied("This review is unavailable for the company.")
    form = AuthorizationForm(request.POST if request.method == "POST" else None,
                               company=member.company, review=review,
                               initial={"expected_revision": member.company.revision, "target": "simulation", "decision": "approve", "preview": "scope"})
    context = review_page(review, member.company)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            binding = {"review": str(review.reference), "sha256": review.data["sha256"]}
            if data.get("preview") == "scope":
                authorization.verify_review(review, member.company)
                form.sanitize_display()
                return render(request, "company/authorize_form.html", {**context, "form": confirmation.prepare(form, request, binding),
                              "confirming": True, "preview_scope": form.scope(), "preview_values": data,
                              "preview_routes": [item for item in review.data["report"]["categories"] if item["task_type"] in data["task_types"]]})
            confirmation.verify(form, request, binding)
            approval = authorization.authorize(request, data["confirm_password"], data["code"], reference,
                                                form.scope(), data["expires_at"], data["reason"], data["expected_revision"], data["target"], data["decision"])
        except (ValidationError, PrivacyError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-pilot-control", reference=approval.reference)
    form.sanitize_display()
    if request.method == "POST" and request.POST.get("preview") == "confirm" and all(
        key in form.cleaned_data for key in ("pilot_id", "repository_ref", "task_types", "developer_ids", "max_tasks", "max_cost_usd", "expires_at", "reason", "expected_revision", "target", "decision")
    ):
        try:
            from engine.privacy import ensure_safe
            ensure_safe(confirmation.payload(form, request, {"review": str(review.reference)}))
        except PrivacyError:
            pass
        else:
            confirmation.hide_metadata(form)
            context.update(confirming=True, preview_scope=form.scope(), preview_values=form.cleaned_data,
                           preview_routes=[item for item in review.data["report"]["categories"] if item["task_type"] in form.cleaned_data["task_types"]])
    return render(request, "company/authorize_form.html", {**context, "form": form})


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def pilot_control(request, reference):
    if request.method == "POST":
        current_member(request.user, "approve")
    state = pilot_details(authorization.status(request, reference))
    form = PilotControlForm(request.POST if request.method == "POST" else None, choices=state["control_choices"],
                            initial={"expected_revision": state["revision"], "preview": "scope"})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            binding = {"pilot_ref": str(reference), "sha256": state["authorization"].data["sha256"]}
            if data.get("preview") == "scope":
                if data["expected_revision"] != state["revision"]:
                    raise ValidationError("Pilot state changed; reload before reviewing a stale control.")
                form.sanitize_display()
                return render(request, "company/pilot_control.html", {**state, "form": confirmation.prepare(form, request, binding),
                              "confirming": True, "preview_values": data})
            confirmation.verify(form, request, binding)
            if data["action"] == "activate":
                authorization.activate(request, data["confirm_password"], data["code"], reference, data["reason"], expected_revision=data["expected_revision"])
            else:
                authorization.control(request, data["confirm_password"], data["code"], reference, data["action"], data["expected_revision"], data["reason"])
        except (ValidationError, PrivacyError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-pilot-control", reference=reference)
    form.sanitize_display()
    context = {"form": form, **state}
    if request.method == "POST" and request.POST.get("preview") == "confirm" and all(
        key in form.cleaned_data for key in ("action", "reason", "expected_revision")
    ):
        try:
            from engine.privacy import ensure_safe
            ensure_safe(confirmation.payload(form, request, {"pilot_ref": str(reference)}))
        except PrivacyError:
            pass
        else:
            confirmation.hide_metadata(form)
            context.update(confirming=True, preview_values=form.cleaned_data)
    return render(request, "company/pilot_control.html", context)


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def pilot_decision(request, reference):
    with transaction.atomic():
        state = developer_pilot(request, reference)
    if not request.company_member.participating:
        raise PermissionDenied("Only participating developers may use simulation admission.")
    form = DecisionForm(request.POST if request.method == "POST" else None, company=request.company_member.company,
                        initial={"repository_ref": state["scope"]["repository_ref"], "source_kind": "synthetic", "boundary": "new_task"})
    result = None
    if request.method == "POST" and form.is_valid():
        data = form.payload()
        try:
            result = authorization.decide(request, reference, {key: data[key] for key in INPUT_FIELDS},
                                           str(form.cleaned_data["reserve_usd"]), form.cleaned_data["override_model"] or None)
        except (ValidationError, PrivacyError) as error:
            _form_error(form, error)
    form.sanitize_display()
    if result:
        with transaction.atomic():
            state = developer_pilot(request, reference)
    return render(request, "company/pilot_decision.html", {**state, "form": form, "result": result, "reference": reference})


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def pilot_settlement(request, reference):
    with transaction.atomic():
        state = developer_pilot(request, reference)
    form = SettlementForm(request.POST if request.method == "POST" else None, decisions=state["decisions"])
    result = None
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            result = authorization.settle(request, reference, data["decision_id"], str(data["actual_cost_usd"]), data["outcome"])
        except (ValidationError, PrivacyError) as error:
            _form_error(form, error)
        else:
            state = developer_pilot(request, reference)
    form.sanitize_display()
    return render(request, "company/pilot_decision.html", {**state, "form": form, "result": result, "reference": reference, "settlement": True})
