"""Authenticated browser workflow around the existing company authority and engine."""

from functools import wraps
from pathlib import Path

from django.contrib.auth import login, logout
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from engine.privacy import PrivacyError, redact_text
from engine.schemas import Policy, ValidationError

from .forms import AdministratorForm, ConfigurationForm, InvitationForm, JoinForm, LoginForm, MemberForm
from .models import CompanyEvent, Invitation, Membership, SecurityEvent
from .services import accept_invitation, checked_login, create_invitation, current_member, revoke_invitation, update_company, update_member


def protected(permission=None):
    def decorate(view):
        @wraps(view)
        def authenticated(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("company-login")
            request.company_member = current_member(request.user, permission)
            from .mfa import required_redirect
            destination = required_redirect(request, request.company_member)
            if destination:
                return redirect(destination)
            return view(request, *args, **kwargs)
        return authenticated
    return decorate


def _form_error(form, error):
    # All visible diagnostics are metadata-only; passwords and invitations never redisplay.
    form.add_error(None, str(error))


def _form_page(request, template, context):
    context["form"].sanitize_display()
    return render(request, template, context)


@sensitive_post_parameters("__ALL__")
@require_http_methods(["GET", "POST"])
def sign_in(request):
    form = LoginForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = checked_login(request, form.cleaned_data["username"], form.cleaned_data["password"])
        if user is not None:
            login(request, user)
            return redirect("company-home")
        form.add_error(None, "Login failed. Check your credentials or try again later if attempts are limited.")
    return _form_page(request, "company/form.html", {"title": "Individual account login", "form": form})


@sensitive_post_parameters("__ALL__")
@require_http_methods(["GET", "POST"])
def join(request):
    form = JoinForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            accept_invitation(form.cleaned_data["invitation"], form.cleaned_data["password1"])
        except (ValidationError, DjangoValidationError, PermissionDenied, PrivacyError) as error:
            _form_error(form, error)
        else:
            # Enrollment does not create an implicitly authenticated browser session.
            return redirect("company-login")
    return _form_page(request, "company/form.html", {"title": "Join by private invitation", "form": form})


@require_POST
def sign_out(request):
    logout(request)
    return redirect("company-login")


@protected()
@require_http_methods(["GET"])
def home(request):
    member = request.company_member
    policy = Policy.from_dict(member.company.policy)
    context = {"member": member, "company": member.company, "policy": policy, "fingerprint": policy.fingerprint()}
    if member.participating or member.can_manage_company:
        from .tasks import company_feedback, task_ledger
        from .presentation import task_card
        feedback = company_feedback(request.user, request=request)
        context["summary"] = feedback["summary"]
        rows = {row["recommendation_id"]: row for row in feedback["summary"]["tasks"]}
        context["cards"] = [task_card(task, rows[task_ledger(task).recommendations[0].recommendation_id]) for task in feedback["tasks"][:5]]
    if member.participating:
        from .models import PilotAuthorization
        context["developer_pilots"] = [item for item in PilotAuthorization.objects.filter(company=member.company)
                                       if item.data.get("target") == "simulation" and member.developer_id in item.data["receipt"]["scope"]["developer_ids"]]
    return render(request, "company/home.html", context)


@sensitive_post_parameters("__ALL__")
@protected("manage")
@require_http_methods(["GET", "POST"])
def invitations(request):
    member = request.company_member
    form = InvitationForm(request.POST if request.method == "POST" else None,
                          initial={"expected_revision": member.company.revision, "role": "developer", "participating": True})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            invitation, value = create_invitation(request.user, data["confirm_password"], data["username"], data["role"],
                                                   data["participating"], data["can_manage_company"], data["can_approve_pilots"],
                                                   data["expires_at"], data["expected_revision"], request=request, reason=data["reason"])
        except (ValidationError, PrivacyError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return render(request, "company/invitation_created.html", {"invitation": invitation, "invitation_value": value})
    return _form_page(request, "company/invitations.html", {"title": "Invite a team member", "form": form,
                                                        "invitations": Invitation.objects.filter(company=member.company).order_by("-created_at")})


@sensitive_post_parameters("__ALL__")
@protected("manage")
@require_http_methods(["GET", "POST"])
def revoke(request, invitation_id):
    form = AdministratorForm(request.POST if request.method == "POST" else None,
                              initial={"expected_revision": request.company_member.company.revision})
    if request.method == "POST" and form.is_valid():
        try:
            revoke_invitation(request.user, form.cleaned_data["confirm_password"], invitation_id,
                              form.cleaned_data["expected_revision"], request=request, reason=form.cleaned_data["reason"])
        except (ValidationError, PrivacyError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-invitations")
    return _form_page(request, "company/form.html", {"title": "Revoke this invitation", "form": form})


@sensitive_post_parameters("__ALL__")
@protected("manage")
@require_http_methods(["GET", "POST"])
def configuration(request):
    company = request.company_member.company
    from .configuration_forms import BrowserConfigurationForm
    legacy = request.method == "POST" and "policy_json" in request.POST
    form = (ConfigurationForm(request.POST, initial=ConfigurationForm.initial_for(company)) if legacy else
            BrowserConfigurationForm(request.POST if request.method == "POST" else None, company=company))
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        config = data["configuration"]
        try:
            update_company(request.user, data["confirm_password"], config["name"], config["policy"],
                           config["repository_refs"], config["collection_fields"], config["company_api_attested"],
                           data["expected_revision"], request=request, reason=data["reason"])
        except (ValidationError, PrivacyError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-home")
    return _form_page(request, "company/form.html" if legacy else "company/configuration.html", {
        "title": "Company policy and collection scope", "form": form, **({} if legacy else form.sections())})


@protected("manage")
@require_http_methods(["GET"])
def members(request):
    return render(request, "company/members.html", {"members": Membership.objects.filter(
        company=request.company_member.company).select_related("user").order_by("developer_id")})


@sensitive_post_parameters("__ALL__")
@protected("manage")
@require_http_methods(["GET", "POST"])
def member_edit(request, account_id):
    target = Membership.objects.filter(company=request.company_member.company, user_id=account_id).first()
    if target is None:
        raise PermissionDenied("Account is outside this company.")
    initial = {field: getattr(target, field) for field in ("role", "active", "participating", "can_manage_company", "can_approve_pilots")}
    initial["expected_revision"] = request.company_member.company.revision
    form = MemberForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            update_member(request.user, data["confirm_password"], account_id, data["role"], data["active"],
                          data["participating"], data["can_manage_company"], data["can_approve_pilots"],
                          data["expected_revision"], request=request, reason=data["reason"])
        except (ValidationError, PrivacyError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-members")
    return _form_page(request, "company/form.html", {"title": "Change account permissions: " + target.developer_id, "form": form})


@protected("manage")
@require_http_methods(["GET"])
def history(request):
    return render(request, "company/history.html", {"events": CompanyEvent.objects.filter(company=request.company_member.company),
                  "security_events": SecurityEvent.objects.filter(company=request.company_member.company).select_related("user")})


@require_http_methods(["GET"])
def stylesheet(request):
    return HttpResponse((Path(__file__).parent / "style.css").read_text(encoding="utf-8"), content_type="text/css")


def forbidden(request, exception):
    return render(request, "company/error.html", {"title": "This action is not permitted", "message": redact_text(str(exception))}, status=403)


def not_found(request, exception):
    return render(request, "company/error.html", {"title": "Page not found", "message": "Use the company navigation to open an available task or review."}, status=404)
