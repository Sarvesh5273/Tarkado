"""Audited, single-use password recovery; never changes roles or bypasses MFA."""

import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from django_otp import verify_token
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from engine.schemas import ValidationError, text

from .mfa import _audit, _state, require_request_mfa
from .models import LoginAttempt, Membership, RecoveryGrant
from .security import sensitive_actor
from .services import LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW, current_member


def _password_ref(user):
    return hashlib.sha256(user.password.encode()).hexdigest()


def _new_grant(member, issuer, kind, expiry):
    now = timezone.now()
    RecoveryGrant.objects.filter(user=member.user, kind=kind, consumed_at__isnull=True, revoked_at__isnull=True).update(revoked_at=now)
    value = secrets.token_urlsafe(32)
    grant = RecoveryGrant.objects.create(company=member.company, user=member.user, issuer=issuer,
                                          kind=kind, digest=hashlib.sha256(value.encode()).hexdigest(),
                                          password_ref=_password_ref(member.user), issued_at=now, expires_at=expiry)
    return grant, value


def issue_personal(request, password, code):
    sensitive_actor(request, password, code)
    with transaction.atomic():
        member = current_member(request.user)
        require_request_mfa(request, member.user)
        grant, value = _new_grant(member, member.user, "personal", None)
        _audit(member, "password_recovery_issue", grant_ref=str(grant.reference), method="offline_personal")
        return value


def issue_assisted(request, password, code, account_id, expires_at, reason, identity_ref):
    sensitive_actor(request, password, code, "manage")
    reason, identity_ref = text(reason, "reason"), text(identity_ref, "identity_confirmation_ref")
    with transaction.atomic():
        operator = current_member(request.user, "manage")
        require_request_mfa(request, operator.user)
        target = Membership.objects.select_related("user", "company").filter(company=operator.company, user_id=account_id,
                                                                              active=True, user__is_active=True).first()
        if target is None:
            raise ValidationError("Recovery is available only for an active account in this company.")
        now = timezone.now()
        if expires_at is None or timezone.is_naive(expires_at) or not now < expires_at <= now + timedelta(hours=1):
            raise ValidationError("Administrator recovery requires an explicit expiry within one hour.")
        grant, value = _new_grant(target, operator.user, "admin", expires_at)
        _audit(operator, "password_recovery_grant", grant_ref=str(grant.reference), target_ref=target.developer_id,
               expires_at=expires_at.isoformat(), reason=reason, identity_confirmation_ref=identity_ref)
        return value


def reset_password(username, value, password, factor_code, factor_kind):
    # Refused verification returns normally, so attempt/OTP counters are committed.
    # Only a verified grant reaches a password change; no public account locks/reset.
    with transaction.atomic():
        now = timezone.now()
        ref = hashlib.sha256(("password-recovery:" + str(username)).encode()).hexdigest()
        failures = LoginAttempt.objects.filter(account_ref=ref, result="failed", timestamp__gt=now - LOGIN_FAILURE_WINDOW)
        if failures.count() >= LOGIN_FAILURE_LIMIT:
            return False
        grant = RecoveryGrant.objects.select_related("user", "company", "issuer").filter(
            digest=hashlib.sha256(str(value).encode()).hexdigest(), user__username=username,
            consumed_at__isnull=True, revoked_at__isnull=True).first()
        valid = grant is not None
        member = None
        if valid:
            member = Membership.objects.filter(user=grant.user, company=grant.company, active=True, user__is_active=True).first()
            valid = member is not None and grant.password_ref == _password_ref(grant.user) and (
                grant.expires_at is None or grant.expires_at > now)
        if valid and grant.kind == "admin":
            issuer = Membership.objects.filter(user=grant.issuer, company=grant.company, active=True, user__is_active=True,
                                               role="admin", can_manage_company=True).first()
            valid = issuer is not None
        if valid:
            validate_password(password, user=grant.user)
            device = TOTPDevice.objects.filter(user=grant.user, confirmed=True).first()
            if device is None and (member.role == "admin" or member.can_approve_pilots or grant.kind == "personal"):
                # A missing/revoked factor cannot turn a privileged or previously
                # MFA-issued recovery grant into password-only account recovery.
                valid = False
            if device is not None:
                if factor_kind == "backup":
                    device = StaticDevice.objects.filter(user=grant.user, confirmed=True).first()
                elif factor_kind != "authenticator":
                    device = None
                valid = device is not None and verify_token(grant.user, device.persistent_id, factor_code) is not None
        if not valid:
            LoginAttempt.objects.create(account_ref=ref, timestamp=now, result="failed")
            return False
        grant.user.set_password(password)
        grant.user.save(update_fields=("password",))
        grant.consumed_at = now
        grant.save(update_fields=("consumed_at",))
        RecoveryGrant.objects.filter(user=grant.user, consumed_at__isnull=True, revoked_at__isnull=True).update(revoked_at=now)
        state = _state(grant.user)
        state.generation += 1
        state.save(update_fields=("generation",))
        LoginAttempt.objects.create(account_ref=ref, timestamp=now, result="success")
        _audit(member, "password_recovered", grant_ref=str(grant.reference), method=grant.kind,
               issuer_id=grant.issuer_id, old_sessions_invalidated=True)
        return True
