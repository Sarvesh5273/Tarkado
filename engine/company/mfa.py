"""Use django-otp's device verification; never put seeds or codes in metadata/audits."""

from base64 import b32encode
from datetime import timedelta
import secrets

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY, login as otp_login, verify_token
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from engine.privacy import ensure_safe
from engine.schemas import ValidationError

from .models import MFAState, SecurityEvent
from .services import checked_login, current_member


PROOF_MAX_AGE = timedelta(minutes=15)
RECOVERY_MAX_AGE = timedelta(minutes=5)
ENROLLMENT_MAX_AGE = timedelta(minutes=15)
BACKUP_CODE_COUNT = 8
PROOF_KEY = "tarkado_mfa_proof"
RECOVERY_KEY = "tarkado_mfa_recovery"


def _audit(member, action, **details):
    ensure_safe(details)
    SecurityEvent.objects.create(company=member.company, user=member.user, timestamp=timezone.now(), action=action, details=details)


def _state(user):
    state, _ = MFAState.objects.get_or_create(user_id=user.pk)
    return state


def _recent(stamp, user, generation, max_age):
    if not isinstance(stamp, dict) or set(stamp) != {"account_id", "generation", "at"}:
        return False
    if type(stamp["account_id"]) is not int or type(stamp["generation"]) is not int:
        return False
    if stamp["account_id"] != user.pk or stamp["generation"] != generation:
        return False
    try:
        when = timezone.datetime.fromisoformat(stamp["at"])
        elapsed = timezone.now() - when
    except (TypeError, ValueError):
        return False
    return timedelta(0) <= elapsed <= max_age


def mfa_required(member):
    return (member.role == "admin" or member.can_approve_pilots
            or TOTPDevice.objects.filter(user_id=member.user_id, confirmed=True).exists())


def primary_verified(request, member=None):
    member = member or current_member(request.user)
    state = MFAState.objects.filter(user_id=member.user_id).first()
    if state is None or not _recent(request.session.get(PROOF_KEY), member.user, state.generation, PROOF_MAX_AGE):
        return False
    device = getattr(request.user, "otp_device", None)
    if not isinstance(device, TOTPDevice) or device.user_id != member.user_id or not device.confirmed:
        return False
    if request.session.get(DEVICE_ID_SESSION_KEY) != device.persistent_id:
        return False
    # Reload current confirmation: a revoked device or old generation cannot keep access.
    return TOTPDevice.objects.filter(pk=device.pk, user_id=member.user_id, confirmed=True).exists()


def recovery_verified(request, member=None):
    member = member or current_member(request.user)
    state = MFAState.objects.filter(user_id=member.user_id).first()
    return state is not None and _recent(request.session.get(RECOVERY_KEY), member.user, state.generation, RECOVERY_MAX_AGE)


def required_redirect(request, member):
    if not mfa_required(member) or primary_verified(request, member):
        return None
    if not TOTPDevice.objects.filter(user_id=member.user_id, confirmed=True).exists():
        return "company-mfa-setup"
    return "company-mfa-verify"


def require_request_mfa(request, user=None):
    # Internal operator-owned Python calls are not public entry points. Every browser
    # administration operation passes its real request and must satisfy this check.
    if request is not None:
        member = current_member(request.user)
        if user is not None and member.user_id != user.pk:
            raise PermissionDenied("Authenticated request does not belong to the operation's account.")
        if mfa_required(member) and not primary_verified(request, member):
            raise PermissionDenied("Complete current authenticator verification before this protected operation.")


def _fresh_password(request, password):
    member = current_member(request.user)
    verified = checked_login(request, member.user.username, password)
    if verified is None or verified.pk != member.user_id:
        raise PermissionDenied("Fresh account verification failed; enrollment/recovery was refused.")


def begin_enrollment(request, password):
    _fresh_password(request, password)
    with transaction.atomic():
        member = current_member(request.user)
        state = _state(member.user)
        active = TOTPDevice.objects.filter(user_id=member.user_id, confirmed=True).exists()
        if active and not (primary_verified(request, member) or recovery_verified(request, member)):
            raise PermissionDenied("Replacing a factor requires current MFA or a valid one-use recovery ticket.")
        pending = TOTPDevice.objects.filter(user_id=member.user_id, confirmed=False).first()
        if pending is not None:
            raise ValidationError("An enrollment is already pending. Finish confirmation or explicitly cancel it before restarting.")
        device = TOTPDevice.objects.create(user=member.user, name="Tarkado authenticator", confirmed=False, tolerance=0)
        state.pending_since = timezone.now()
        state.save(update_fields=("pending_since",))
        _audit(member, "mfa_enrollment_begin", device_ref=device.persistent_id, generation=state.generation)
        return device


def cancel_enrollment(request, password):
    _fresh_password(request, password)
    with transaction.atomic():
        member = current_member(request.user)
        if TOTPDevice.objects.filter(user_id=member.user_id, confirmed=True).exists() and not (
            primary_verified(request, member) or recovery_verified(request, member)
        ):
            raise PermissionDenied("Cancel/restart requires current MFA or a valid recovery ticket.")
        pending = TOTPDevice.objects.filter(user_id=member.user_id, confirmed=False).first()
        if pending is None:
            raise ValidationError("There is no pending enrollment to cancel.")
        ref = pending.persistent_id
        pending.delete()
        state = _state(member.user)
        state.pending_since = None
        state.save(update_fields=("pending_since",))
        _audit(member, "mfa_enrollment_cancel", device_ref=ref, generation=state.generation)


def _stamp_primary(request, device, generation):
    request.session.cycle_key()
    otp_login(request, device)
    request.session[PROOF_KEY] = {"account_id": device.user_id, "generation": generation, "at": timezone.now().isoformat()}
    request.session.pop(RECOVERY_KEY, None)


def confirm_enrollment(request, code):
    # Return refused verification normally so the library's failed-attempt counters
    # commit. Raising inside the transaction would roll them back.
    with transaction.atomic():
        member = current_member(request.user)
        state = _state(member.user)
        if TOTPDevice.objects.filter(user_id=member.user_id, confirmed=True).exists() and not (
            primary_verified(request, member) or recovery_verified(request, member)
        ):
            raise PermissionDenied("Current MFA or recovery proof expired before factor replacement.")
        device = TOTPDevice.objects.filter(user_id=member.user_id, confirmed=False).first()
        now = timezone.now()
        if device is None or state.pending_since is None or not timedelta(0) <= now - state.pending_since <= ENROLLMENT_MAX_AGE:
            raise ValidationError("Enrollment is missing or expired; cancel pending enrollment explicitly and begin again.")
        accepted = verify_token(member.user, device.persistent_id, code)
        if accepted is None:
            _audit(member, "mfa_enrollment_failed", generation=state.generation)
            return None
        # Only a confirmed new factor revokes the old credentials. History and
        # business/task records remain untouched; old MFA sessions lose their generation.
        TOTPDevice.objects.filter(user_id=member.user_id, confirmed=True).delete()
        StaticDevice.objects.filter(user_id=member.user_id).delete()
        accepted.confirmed = True
        accepted.save(update_fields=("confirmed",))
        state.generation += 1
        state.pending_since = None
        state.save(update_fields=("generation", "pending_since"))
        recovery = StaticDevice.objects.create(user=member.user, name="Tarkado one-use backup codes", confirmed=True)
        codes = [b32encode(secrets.token_bytes(10)).decode("ascii") for _ in range(BACKUP_CODE_COUNT)]
        for value in codes:
            StaticToken.objects.create(device=recovery, token=value)
        _audit(member, "mfa_enrollment_confirm", generation=state.generation, backup_codes_created=len(codes))
        generation = state.generation
    _stamp_primary(request, accepted, generation)
    return codes


def verify_mfa(request, code):
    with transaction.atomic():
        member = current_member(request.user)
        state = _state(member.user)
        device = TOTPDevice.objects.filter(user_id=member.user_id, confirmed=True).first()
        if device is None:
            raise ValidationError("Enroll and confirm an authenticator before verification.")
        accepted = verify_token(member.user, device.persistent_id, code)
        _audit(member, "mfa_verify" if accepted else "mfa_verify_failed", generation=state.generation)
        generation = state.generation
    if accepted is not None:
        _stamp_primary(request, accepted, generation)
    return accepted is not None


def recover_factor(request, password, code):
    _fresh_password(request, password)
    with transaction.atomic():
        member = current_member(request.user)
        state = _state(member.user)
        device = StaticDevice.objects.filter(user_id=member.user_id, confirmed=True).first()
        if device is None:
            raise ValidationError("This account has no backup-code recovery device.")
        accepted = verify_token(member.user, device.persistent_id, code)
        _audit(member, "mfa_backup_used" if accepted else "mfa_backup_failed", generation=state.generation)
        generation = state.generation
    if accepted is None:
        return False
    request.session.cycle_key()
    request.session.pop(PROOF_KEY, None)
    request.session.pop(DEVICE_ID_SESSION_KEY, None)
    request.session[RECOVERY_KEY] = {"account_id": member.user_id, "generation": generation, "at": timezone.now().isoformat()}
    request.user.otp_device = None
    return True
