from base64 import b32encode
from functools import wraps

from django import forms
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django_otp.plugins.otp_totp.models import TOTPDevice

from engine.schemas import ValidationError

from .forms import StrictForm
from .mfa import begin_enrollment, cancel_enrollment, confirm_enrollment, recover_factor, verify_mfa
from .services import current_member
from .views import _form_error, _form_page


class PasswordForm(StrictForm):
    confirm_password = forms.CharField(widget=forms.PasswordInput, max_length=1024, label="Confirm your account password")


class CodeForm(StrictForm):
    code = forms.CharField(widget=forms.PasswordInput, max_length=64, label="Current authenticator code")


class RecoveryForm(PasswordForm):
    code = forms.CharField(widget=forms.PasswordInput, max_length=16, label="One-use backup code (case-sensitive)")


def security_account(view):
    @wraps(view)
    def authenticated(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("company-login")
        request.company_member = current_member(request.user)
        return view(request, *args, **kwargs)
    return authenticated


@sensitive_post_parameters("__ALL__")
@security_account
@require_http_methods(["GET", "POST"])
def setup(request):
    form = PasswordForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            device = begin_enrollment(request, form.cleaned_data["confirm_password"])
        except (ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return render(request, "company/mfa_enrollment.html", {"setup_secret": b32encode(device.bin_key).decode("ascii")})
    form.sanitize_display()
    return render(request, "company/mfa_setup.html", {"company": request.company_member.company, "form": form,
                  "has_factor": TOTPDevice.objects.filter(user=request.user, confirmed=True).exists(),
                  "pending": TOTPDevice.objects.filter(user=request.user, confirmed=False).exists()})


@sensitive_post_parameters("__ALL__")
@security_account
@require_http_methods(["GET", "POST"])
def confirm(request):
    form = CodeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            codes = confirm_enrollment(request, form.cleaned_data["code"])
        except (ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            if codes is not None:
                return render(request, "company/mfa_backup_codes.html", {"codes": codes})
            form.add_error(None, "Code verification failed or is temporarily limited. Codes are never displayed back.")
    return _form_page(request, "company/form.html", {"title": "Confirm your new authenticator", "form": form})


@sensitive_post_parameters("__ALL__")
@security_account
@require_http_methods(["GET", "POST"])
def verify(request):
    if not TOTPDevice.objects.filter(user=request.user, confirmed=True).exists():
        return redirect("company-mfa-setup")
    form = CodeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        if verify_mfa(request, form.cleaned_data["code"]):
            return redirect("company-home")
        form.add_error(None, "Code verification failed or is temporarily limited. Try a current unused code later.")
    return _form_page(request, "company/mfa_verify.html", {"title": "Verify your authenticator", "form": form})


@sensitive_post_parameters("__ALL__")
@security_account
@require_http_methods(["GET", "POST"])
def recover(request):
    form = RecoveryForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            accepted = recover_factor(request, form.cleaned_data["confirm_password"], form.cleaned_data["code"])
        except (ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            if accepted:
                return redirect("company-mfa-setup")
            form.add_error(None, "Backup-code verification failed or is temporarily limited.")
    return _form_page(request, "company/mfa_recover.html", {"title": "Recover a lost authenticator", "form": form})


@sensitive_post_parameters("__ALL__")
@security_account
@require_http_methods(["GET", "POST"])
def cancel(request):
    form = PasswordForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            cancel_enrollment(request, form.cleaned_data["confirm_password"])
        except (ValidationError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-mfa-setup")
    return _form_page(request, "company/form.html", {"title": "Cancel your pending authenticator enrollment", "form": form})
