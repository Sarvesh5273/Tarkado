"""Fresh human verification for sensitive company actions, separate from task feedback."""

from django.core.exceptions import PermissionDenied

from .mfa import _fresh_password, primary_verified, verify_mfa
from .services import current_member


def sensitive_actor(request, password, code, permission=None):
    member = current_member(request.user, permission)
    if not primary_verified(request, member):
        raise PermissionDenied("This operation requires current primary authenticator verification, not a recovery ticket.")
    _fresh_password(request, password)
    if not verify_mfa(request, code):
        raise PermissionDenied("A fresh unused authenticator code is required for this sensitive action.")
    return member
