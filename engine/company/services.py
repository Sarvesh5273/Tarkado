"""Recheck current company permission inside each serialized state change."""

import hashlib
import re
import secrets
from datetime import timedelta
from functools import wraps

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from engine.feedback import TeamConfig
from engine.privacy import ensure_safe
from engine.schemas import Policy, ValidationError, boolean, strings, text

from .models import Company, CompanyEvent, CompanyTask, Invitation, LoginAttempt, Membership


COLLECTION_FIELDS = (
    "task_id", "session_id", "developer_id", "timestamp", "task_type", "risk_tags",
    "selected_model", "required_tools", "context_tokens", "recommendation_id",
    "response", "execution_id", "actual_model", "result_id", "reviewer_id",
    "desired_result", "tests_passed", "score", "cost_usd", "latency_ms", "evidence_ref", "supersedes",
)
COLLECTION_REQUIRED = ("task_id", "session_id", "developer_id", "timestamp", "selected_model")
CONNECTOR_FIELDS = ("observation_kind", "request_kind", "http_status", "attempt", "retry", "coverage_status")
# Additive fields do not expand any existing installation's approved collection scope.
COLLECTION_FIELDS += CONNECTOR_FIELDS
# These supported measurements remain unapproved in existing stores/pairings.
DELIVERY_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
COLLECTION_FIELDS += DELIVERY_FIELDS
DEFAULT_COLLECTION_FIELDS = COLLECTION_FIELDS
# New capture is unapproved even in a freshly bootstrapped installation until
# the administrator explicitly changes its collection list and the owner pairs.
TOOL_CAPTURE_FIELDS = ("tool_invocation_ref", "tool_contract_ref", "tool_phase", "tool_status", "tool_observed_at", "tool_attempt_ref", "tool_status_source")
SUPPORTED_COLLECTION_FIELDS = COLLECTION_FIELDS + TOOL_CAPTURE_FIELDS
LOGIN_FAILURE_LIMIT = 8
LOGIN_FAILURE_WINDOW = timedelta(minutes=15)


def validate_username(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{2,63}", value):
        raise ValidationError("Use a lowercase account name of 3–64 letters, digits, dots, underscores, or hyphens.")
    return text(value, "username")


def validate_permissions(role, participating, manage, approve):
    if role not in dict(Membership.ROLES):
        raise ValidationError("Declare a supported company role.")
    for name, value in (("participating", participating), ("can_manage_company", manage), ("can_approve_pilots", approve)):
        boolean(value, name)
    if manage and role != "admin":
        raise ValidationError("Only an explicitly appointed administrator may manage company setup.")
    if approve and role not in ("senior", "admin"):
        raise ValidationError("Only a designated senior or administrator may approve pilots.")
    if participating and role == "admin":
        raise ValidationError("Administrator-only accounts do not have an engineering feedback role.")


def validate_configuration(name, policy, repositories, fields, attested):
    name = text(name, "company_name")
    if len(name) > 128:
        raise ValidationError("Company name must be at most 128 characters.")
    policy = Policy.from_dict(policy).to_dict()
    repositories = strings(repositories, "repository_refs")
    if not repositories or any(any(mark in item for mark in ("*", "?", "[", "]")) for item in repositories):
        raise ValidationError("Collection repositories must be explicit nonempty references, without patterns.")
    fields = strings(fields, "collection_fields")
    if set(fields) - set(SUPPORTED_COLLECTION_FIELDS) or not set(COLLECTION_REQUIRED).issubset(fields):
        raise ValidationError("Collection must use supported metadata fields and retain required task/model identifiers.")
    if not boolean(attested, "company_api_attested"):
        raise ValidationError("Company-managed API/gateway attestation is required; no consumer subscriptions.")
    return {"name": name, "policy": policy, "repository_refs": list(repositories),
            "collection_fields": [field for field in SUPPORTED_COLLECTION_FIELDS if field in fields],
            "company_api_attested": True, "retention_policy": "manual"}


def current_member(user, permission=None):
    # This is called only after Django verifies the login; role labels are not login proof.
    if user is None or not user.is_authenticated or not user.pk:
        raise PermissionDenied("Company access requires an individual login.")
    member = Membership.objects.select_related("company", "user").filter(user_id=user.pk).first()
    if member is None or not member.active or not member.user.is_active or member.company_id != 1:
        raise PermissionDenied("This account has no active company access.")
    if permission == "manage" and not (member.role == "admin" and member.can_manage_company):
        raise PermissionDenied("Company administration is not permitted for this account.")
    if permission == "approve" and not (member.role in ("senior", "admin") and member.can_approve_pilots):
        raise PermissionDenied("This account is not a designated pilot approver.")
    if permission not in (None, "manage", "approve"):
        raise PermissionDenied("Unsupported company permission.")
    return member


def _account_ref(username):
    return hashlib.sha256(str(username).encode("utf-8")).hexdigest()


def checked_login(request, username, password):
    """Django verifies passwords; the database serializes the attempt limit."""
    with transaction.atomic():
        now = timezone.now()
        ref = _account_ref(username)
        recent = LoginAttempt.objects.filter(account_ref=ref, timestamp__gt=now - LOGIN_FAILURE_WINDOW)
        last_success = recent.filter(result="success").order_by("-timestamp", "-id").first()
        failures = recent.filter(result="failed")
        if last_success:
            failures = failures.filter(id__gt=last_success.id)
        if failures.count() >= LOGIN_FAILURE_LIMIT:
            return None
        user = authenticate(request=request, username=username, password=password)
        if user is not None:
            try:
                current_member(user)
            except PermissionDenied:
                user = None
        LoginAttempt.objects.create(account_ref=ref, timestamp=now, result="success" if user else "failed")
        return user


def _fresh_administrator(user, password, request=None):
    member = current_member(user, "manage")
    from .mfa import require_request_mfa
    require_request_mfa(request, user)
    confirmed = checked_login(request, member.user.username, password)
    if confirmed is None or confirmed.pk != member.user_id:
        raise PermissionDenied("Fresh administrator verification failed. Try again later if login is limited.")
    return member


def _administrator_change(operation):
    @wraps(operation)
    def verified(user, password, *args, **kwargs):
        # Failed login attempts must survive a refused or rolled-back state change.
        _fresh_administrator(user, password, kwargs.get("request"))
        with transaction.atomic():
            current_member(user, "manage")
            from .mfa import require_request_mfa
            require_request_mfa(kwargs.get("request"), user)
            return operation(user, password, *args, **kwargs)
    return verified


def member_snapshot(member):
    return {"account_id": member.user_id, "developer_id": member.developer_id,
            "role": member.role, "active": member.active, "participating": member.participating,
            "can_manage_company": member.can_manage_company, "can_approve_pilots": member.can_approve_pilots}


def _record(company, actor, action, details, initial=False, reason=None):
    details = {"reason": text(reason, "reason"), **details}
    ensure_safe(details)
    if not initial:
        company.revision += 1
        company.save(update_fields=("revision",))
    CompanyEvent.objects.create(company=company, revision=company.revision, actor=actor,
                                actor_username=actor.username, timestamp=timezone.now(), action=action, details=details)


def _check_revision(company, expected_revision):
    if type(expected_revision) is not int or expected_revision != company.revision:
        raise ValidationError("Company state changed; reload before retrying this operation.")


@transaction.atomic
def bootstrap_company(username, password, name, policy, repositories, pilot_approver=False):
    username = validate_username(username)
    boolean(pilot_approver, "pilot_approver")
    config = validate_configuration(name, policy, repositories, list(DEFAULT_COLLECTION_FIELDS), True)
    if Company.objects.exists() or get_user_model().objects.exists() or Membership.objects.exists():
        raise ValidationError("This installation already has account/company state; bootstrap cannot replace it.")
    user = get_user_model()(username=username)
    validate_password(password, user=user)
    user.set_password(password)
    user.save()
    company = Company.objects.create(**config)
    member = Membership.objects.create(company=company, user=user, developer_id=username, role="admin",
                                        participating=False, can_manage_company=True, can_approve_pilots=pilot_approver)
    _record(company, user, "bootstrap", {"configuration": config, "member": member_snapshot(member)}, initial=True,
            reason="The installation operator explicitly enrolled the first administrator.")
    return company


@_administrator_change
def create_invitation(user, password, username, role, participating, manage, approve, expires_at,
                      expected_revision, request=None, reason=None):
    member = current_member(user, "manage")
    company = member.company
    _check_revision(company, expected_revision)
    username = validate_username(username)
    validate_permissions(role, participating, manage, approve)
    now = timezone.now()
    if expires_at is None or timezone.is_naive(expires_at) or not now < expires_at <= now + timedelta(days=7):
        raise ValidationError("Declare an invitation expiry within the next seven days, with a timezone.")
    if get_user_model().objects.filter(username=username).exists() or Invitation.objects.filter(
        username=username, consumed_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now
    ).exists():
        raise ValidationError("This account already exists or has a pending invitation.")
    value = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(company=company, username=username, role=role, participating=participating,
                                             can_manage_company=manage, can_approve_pilots=approve,
                                             digest=hashlib.sha256(value.encode("ascii")).hexdigest(),
                                             created_by=member.user, created_at=now, expires_at=expires_at)
    _record(company, member.user, "invite", {"invitation_id": str(invitation.invitation_id), "username": username,
                                            "role": role, "participating": participating, "can_manage_company": manage,
                                            "can_approve_pilots": approve, "expires_at": expires_at.isoformat()}, reason=reason)
    return invitation, value


@transaction.atomic
def accept_invitation(value, password):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ValidationError("Invitation is invalid, expired, revoked, or already used.")
    invitation = Invitation.objects.select_related("company", "created_by").filter(
        digest=hashlib.sha256(value.encode("ascii")).hexdigest()).first()
    now = timezone.now()
    if invitation is None or invitation.consumed_at or invitation.revoked_at or invitation.expires_at <= now:
        raise ValidationError("Invitation is invalid, expired, revoked, or already used.")
    # A removed administrator's old invitations cannot continue enrolling privileged users.
    current_member(invitation.created_by, "manage")
    validate_permissions(invitation.role, invitation.participating, invitation.can_manage_company, invitation.can_approve_pilots)
    if get_user_model().objects.filter(username=invitation.username).exists():
        raise ValidationError("Invitation is invalid, expired, revoked, or already used.")
    user = get_user_model()(username=invitation.username)
    validate_password(password, user=user)
    user.set_password(password)
    user.save()
    member = Membership.objects.create(company=invitation.company, user=user, developer_id=invitation.username,
                                        role=invitation.role, participating=invitation.participating,
                                        can_manage_company=invitation.can_manage_company, can_approve_pilots=invitation.can_approve_pilots)
    invitation.consumed_at = now
    invitation.save(update_fields=("consumed_at",))
    _record(invitation.company, user, "invite_accept", {"invitation_id": str(invitation.invitation_id), "member": member_snapshot(member)},
            reason="The invited account completed individual enrollment.")
    return user


@_administrator_change
def revoke_invitation(user, password, invitation_id, expected_revision, request=None, reason=None):
    member = current_member(user, "manage")
    _check_revision(member.company, expected_revision)
    invitation = Invitation.objects.filter(company=member.company, invitation_id=invitation_id).first()
    if invitation is None or invitation.consumed_at or invitation.revoked_at:
        raise ValidationError("This invitation is unavailable for revocation.")
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=("revoked_at",))
    _record(member.company, member.user, "invite_revoke", {"invitation_id": str(invitation.invitation_id)}, reason=reason)


@_administrator_change
def update_member(user, password, account_id, role, active, participating, manage, approve,
                  expected_revision, request=None, reason=None):
    operator = current_member(user, "manage")
    company = operator.company
    _check_revision(company, expected_revision)
    validate_permissions(role, participating, manage, approve)
    boolean(active, "active")
    target = Membership.objects.select_related("user").filter(company=company, user_id=account_id).first()
    if target is None:
        raise ValidationError("Account is outside this company.")
    if target.active and target.role == "admin" and target.can_manage_company and not (active and role == "admin" and manage):
        other_admins = Membership.objects.filter(company=company, active=True, user__is_active=True,
                                                 role="admin", can_manage_company=True).exclude(pk=target.pk)
        if not other_admins.exists():
            raise ValidationError("Cannot remove the last active company administrator.")
    before = member_snapshot(target)
    target.role, target.active, target.participating = role, active, participating
    target.can_manage_company, target.can_approve_pilots = manage, approve
    target.save(update_fields=("role", "active", "participating", "can_manage_company", "can_approve_pilots"))
    _record(company, operator.user, "member_update", {"before": before, "after": member_snapshot(target)}, reason=reason)


@_administrator_change
def update_company(user, password, name, policy, repositories, fields, attested, expected_revision, request=None, reason=None):
    member = current_member(user, "manage")
    company = member.company
    _check_revision(company, expected_revision)
    config = validate_configuration(name, policy, repositories, fields, attested)
    new_policy = Policy.from_dict(config["policy"])
    old_policy = Policy.from_dict(company.policy)
    if old_policy.policy_version == new_policy.policy_version and old_policy.fingerprint() != new_policy.fingerprint():
        raise ValidationError("Changed policy content requires a new version; old task snapshots cannot be relabeled.")
    for snapshot in CompanyTask.objects.filter(company=company).values_list("policy_snapshot", flat=True):
        if snapshot["policy"]["policy_version"] == new_policy.policy_version and snapshot["sha256"] != new_policy.fingerprint():
            raise ValidationError("This policy version already has different recorded task content.")
    before = {field: getattr(company, field) for field in config}
    for field, value in config.items():
        setattr(company, field, value)
    company.save(update_fields=tuple(config))
    _record(company, member.user, "company_update", {"before": before, "after": config}, reason=reason)


def collection_team(company):
    """Project current participants into the existing contract, without relabeling old ledgers."""
    members = Membership.objects.filter(company=company, active=True, user__is_active=True,
                                         participating=True).order_by("developer_id")
    return TeamConfig.from_dict({"company_api_attested": company.company_api_attested,
                                 "members": [{"developer_id": member.developer_id, "role": member.role} for member in members]})


def require_collection(user, repository_ref, developer_id):
    member = current_member(user)
    if not member.participating or developer_id != member.developer_id:
        raise PermissionDenied("An individual account cannot submit another developer's observations.")
    text(repository_ref, "repository_ref")
    if repository_ref not in member.company.repository_refs:
        raise PermissionDenied("Repository is outside approved collection scope.")
    return member
