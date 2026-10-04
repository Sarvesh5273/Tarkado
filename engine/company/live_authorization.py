"""Live scope approval mechanics, separate from any routing activation or model call."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from engine.feedback import TaskRequest, _fingerprint, _timestamp
from engine.history import PolicySnapshot
from engine.policy import incompatibility
from engine.privacy import ensure_safe
from engine.readiness import PilotScope
from engine.schemas import Policy, ValidationError, boolean, choice, integer, object_fields, text

from .mfa import _audit, require_request_mfa
from .models import AuthorizationEvent, MFAState, Membership, PilotAuthorization
from .readiness_gate import ReadinessAssessment, ReadinessRequest, verify_readiness
from .services import current_member, member_snapshot


LIVE_FIELDS = ("schema_version", "record_type", "company_id", "deployment_id", "review_ref", "review_sha256",
               "policy", "scope", "routes", "approver", "approver_roster", "mfa_generation", "company_revision",
               "approved_at", "expires_at", "reason", "target", "decision", "readiness_request", "readiness_assessment",
               "scope_approved", "routing_enabled", "deployment_authorized", "sha256")


def readiness_request(company, review, scope):
    report = review.data["report"]
    return ReadinessRequest(str(company.company_id), str(company.deployment_id), company.revision,
                            str(review.reference), review.data["sha256"], report["report_sha256"],
                            report["policy_sha256"], report["feedback_sha256"], report["learner_sha256"],
                            _fingerprint(scope.to_dict()))


def _event(authorization, member, action, reason):
    payload = {"authorization_sha256": authorization.data["sha256"], "reason": reason,
               "actor": member_snapshot(member), "company_revision": member.company.revision}
    ensure_safe(payload)
    event = AuthorizationEvent.objects.create(authorization=authorization,
                                              sequence=authorization.authorization_revision,
                                              action=action, actor=member.user, timestamp=timezone.now(), payload=payload)
    return event


def record_live(member, review, scope, report, expires_at, reason, decision):
    from .authorization import _roster

    company = member.company
    if timezone.now() < _timestamp(report.data["observed_through"]):
        raise ValidationError("Live scope approval cannot precede the evidence/validation cutoff it claims to review.")
    policy = Policy.from_dict(company.policy)
    categories = {item["task_type"]: item for item in report.data["categories"]}
    if set(scope.task_types) - set(categories):
        raise ValidationError("Live scope contains categories absent from the exact reviewed report.")
    if decision == "approve" and any(categories[item]["status"] != "ready_for_local_review" for item in scope.task_types):
        raise ValidationError("Blocked category evidence cannot be granted live scope approval.")
    # A local positive report is still not verification. Synthetic sources cannot
    # enter this path even if a broken checker says they are ready.
    assessment = None
    check = readiness_request(company, review, scope)
    routes = []
    if decision == "approve":
        if report.data["source_kind"] != "team":
            raise ValidationError("Synthetic evidence cannot authorize a live pilot; independently verified company readiness is required.")
        for item in scope.task_types:
            model_id = categories[item]["suggested_model"]
            model = policy.model(model_id)
            if model is None or not model.approved:
                raise ValidationError("A live approval cannot grant an unapproved category/model route.")
            routes.append({"task_type": item, "model": model_id})
        assessment = verify_readiness(check)
        if _timestamp(expires_at.isoformat()) > _timestamp(assessment.valid_until):
            raise ValidationError("Pilot approval validity cannot outlast its independently verified readiness evidence.")
    now = timezone.now()
    data = {"schema_version": 1, "record_type": "company_live_pilot_authorization",
            "company_id": str(company.company_id), "deployment_id": str(company.deployment_id),
            "review_ref": str(review.reference), "review_sha256": review.data["sha256"],
            "policy": PolicySnapshot.create(policy).to_dict(), "scope": scope.to_dict(), "routes": routes,
            "approver": member_snapshot(member), "approver_roster": _roster(company).to_dict(),
            "mfa_generation": MFAState.objects.get(user=member.user).generation, "company_revision": company.revision,
            "approved_at": now.isoformat(), "expires_at": expires_at.isoformat(), "reason": reason,
            "target": "live", "decision": decision, "readiness_request": check.to_dict(),
            "readiness_assessment": assessment.to_dict() if assessment else None, "scope_approved": decision == "approve",
            "routing_enabled": False, "deployment_authorized": False}
    data["sha256"] = _fingerprint(data)
    authorization = PilotAuthorization.objects.create(company=company, review=review, approver=member.user,
                                                        pilot_id=scope.pilot_id, data=data)
    _event(authorization, member, "approve" if decision == "approve" else "reject", reason)
    validate_live(authorization)
    _audit(member, "pilot_authorize", authorization_ref=str(authorization.reference),
           authorization_sha256=data["sha256"], target="live", decision=decision,
           execution_enabled=False)
    return authorization


def validate_live(authorization):
    data = object_fields(authorization.data, LIVE_FIELDS, LIVE_FIELDS)
    ensure_safe(data)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValidationError("Unsupported live-authorization record version.")
    choice(data["record_type"], "record_type", ("company_live_pilot_authorization",))
    choice(data["target"], "target", ("live",))
    decision = choice(data["decision"], "decision", ("approve", "reject"))
    if _fingerprint({key: data[key] for key in LIVE_FIELDS if key != "sha256"}) != data["sha256"]:
        raise ValidationError("Live-authorization content fingerprint differs from its exact recorded content.")
    for field in ("company_id", "deployment_id", "review_ref", "review_sha256", "reason"):
        text(data[field], field)
    if data["review_ref"] != str(authorization.review.reference) or data["review_sha256"] != authorization.review.data["sha256"]:
        raise ValidationError("Live authorization differs from its stored evidence review.")
    policy = PolicySnapshot.from_dict(data["policy"])
    scope = PilotScope.from_dict(data["scope"])
    if scope.pilot_id != authorization.pilot_id or policy.sha256 != authorization.review.data["report"]["policy_sha256"]:
        raise ValidationError("Live scope/policy binding differs from its pilot or report.")
    from engine.readiness import ApproverRoster
    roster = ApproverRoster.from_dict(data["approver_roster"])
    actor_fields = ("account_id", "developer_id", "role", "active", "participating", "can_manage_company", "can_approve_pilots")
    actor = object_fields(data["approver"], actor_fields, actor_fields)
    if type(actor["account_id"]) is not int or actor["account_id"] != authorization.approver_id:
        raise ValidationError("Live approval has no matching authenticated human approver.")
    for field in ("active", "participating", "can_manage_company", "can_approve_pilots"):
        boolean(actor[field], field)
    designated = roster.designated(actor["developer_id"])
    if actor["role"] != designated[1] or not actor["active"] or not actor["can_approve_pilots"]:
        raise ValidationError("Live approval actor differs from the designated permission snapshot.")
    integer(data["company_revision"], "company_revision")
    integer(data["mfa_generation"], "mfa_generation")
    start, end = _timestamp(data["approved_at"]), _timestamp(data["expires_at"])
    if end <= start or end - start > timedelta(days=7):
        raise ValidationError("Live approval validity must be positive and bounded.")
    if boolean(data["scope_approved"], "scope_approved") != (decision == "approve"):
        raise ValidationError("Live scope approval contradicts the human decision.")
    if boolean(data["routing_enabled"], "routing_enabled") or boolean(data["deployment_authorized"], "deployment_authorized"):
        raise ValidationError("Live scope approval alone cannot enable execution or company deployment.")
    check_fields = tuple(ReadinessRequest.__dataclass_fields__)
    check = ReadinessRequest(**object_fields(data["readiness_request"], check_fields, check_fields))
    expected_check = ReadinessRequest(data["company_id"], data["deployment_id"], data["company_revision"],
                                      data["review_ref"], data["review_sha256"], authorization.review.data["report"]["report_sha256"],
                                      policy.sha256, authorization.review.data["report"]["feedback_sha256"],
                                      authorization.review.data["report"]["learner_sha256"], _fingerprint(scope.to_dict()))
    if check != expected_check:
        raise ValidationError("Live readiness request does not bind this exact company/evidence/policy/scope.")
    categories = {item["task_type"]: item for item in authorization.review.data["report"]["categories"]}
    if set(scope.task_types) - set(categories):
        raise ValidationError("Live approval names unreviewed categories.")
    expected_routes = [{"task_type": item, "model": categories[item]["suggested_model"]} for item in scope.task_types] if decision == "approve" else []
    if data["routes"] != expected_routes:
        raise ValidationError("Live routes differ from the exact approved category/model scope.")
    if decision == "approve":
        if authorization.review.data["report"]["source_kind"] != "team" or any(
            categories[item]["status"] != "ready_for_local_review" for item in scope.task_types
        ):
            raise ValidationError("Synthetic or blocked category evidence cannot support live scope approval.")
        if any(policy.policy.model(item["model"]) is None or not policy.policy.model(item["model"]).approved for item in data["routes"]):
            raise ValidationError("Live authorization contains a category/model route not approved in its saved company policy.")
        assessment = ReadinessAssessment.from_dict(data["readiness_assessment"])
        if assessment.request_sha256 != check.sha256 or not _timestamp(assessment.verified_at) <= start < end <= _timestamp(assessment.valid_until):
            raise ValidationError("Live approval differs from its readiness assessment binding/validity.")
    elif data["readiness_assessment"] is not None:
        raise ValidationError("Rejected live scope cannot grant a readiness assessment or routes.")
    events = list(authorization.authority_events.select_related("actor").all())
    if not events or len(events) != authorization.authorization_revision:
        raise ValidationError("Live authorization history is incomplete; it cannot be reset.")
    previous = start
    for sequence, event in enumerate(events, 1):
        fields = ("authorization_sha256", "reason", "actor", "company_revision")
        payload = object_fields(event.payload, fields, fields)
        ensure_safe(payload)
        integer(payload["company_revision"], "company_revision")
        recorded_actor = object_fields(payload["actor"], actor_fields, actor_fields)
        for flag in ("active", "participating", "can_manage_company", "can_approve_pilots"):
            boolean(recorded_actor[flag], flag)
        if recorded_actor["account_id"] != event.actor_id or recorded_actor["role"] not in ("senior", "admin"):
            raise ValidationError("Live authorization event actor does not match its recorded identity.")
        if recorded_actor["active"] is not True or recorded_actor["can_approve_pilots"] is not True:
            raise ValidationError("Live authorization event has no designated approver authority.")
        text(payload["reason"], "reason")
        if event.sequence != sequence or payload["authorization_sha256"] != data["sha256"] or event.timestamp < previous:
            raise ValidationError("Live authorization event order/content binding is inconsistent.")
        if sequence == 1:
            if event.action != decision or event.actor_id != authorization.approver_id or recorded_actor != actor:
                raise ValidationError("Live authorization must start with its separately authenticated human decision.")
            if payload["company_revision"] != data["company_revision"] or payload["reason"] != data["reason"]:
                raise ValidationError("Initial live decision's reviewed revision/reason differs from its approval record.")
        elif sequence != 2 or event.action not in ("revoke", "rollback"):
            raise ValidationError("Revoked live approval cannot restart, resume, or silently expand.")
        previous = event.timestamp
    if (len(events) == 2) != (authorization.revoked_at is not None) or (
        len(events) == 2 and events[-1].timestamp != authorization.revoked_at
    ):
        raise ValidationError("Live revocation differs from its ordered history.")
    return data


def live_guard(authorization, company, allow_future_recommendations=False):
    try:
        data = validate_live(authorization)
        if not data["scope_approved"]:
            raise ValidationError("The designated reviewer rejected this live scope; no authority was granted.")
        if authorization.company_id != company.pk or (data["company_id"], data["deployment_id"]) != (
            str(company.company_id), str(company.deployment_id)
        ):
            raise ValidationError("Live approval belongs to a different company/deployment.")
        if authorization.revoked_at is not None or timezone.now() >= _timestamp(data["expires_at"]):
            raise ValidationError("Live scope approval is revoked or expired.")
        if company.revision != data["company_revision"]:
            raise ValidationError("Company permissions/configuration changed; new live approval is required.")
        approver = current_member(authorization.approver, "approve")
        if member_snapshot(approver) != data["approver"]:
            raise ValidationError("Current designated approver authority differs from the live approval.")
        mfa = MFAState.objects.filter(user=approver.user).first()
        if mfa is None or mfa.generation != data["mfa_generation"] or not TOTPDevice.objects.filter(user=approver.user, confirmed=True).exists():
            raise ValidationError("Approver MFA/recovery authority changed; the live approval is no longer current.")
        from .authorization import _roster, verify_review
        if _roster(company).to_dict() != data["approver_roster"]:
            raise ValidationError("Current designation roster differs from the live approval.")
        verify_review(authorization.review, company, allow_future_recommendations=allow_future_recommendations)
        scope = PilotScope.from_dict(data["scope"])
        for developer in scope.developer_ids:
            if not Membership.objects.filter(company=company, developer_id=developer, active=True, user__is_active=True,
                                              participating=True, role__in=("junior", "developer", "senior")).exists():
                raise ValidationError("A live-scoped developer's current collection permission was removed.")
        check = readiness_request(company, authorization.review, scope)
        verify_readiness(check, expected=data["readiness_assessment"])
        return {"status": "current", "reason": "Exact human live-scope approval and independent readiness assessment are current; execution remains a separate gate."}
    except (ValidationError, PermissionDenied, KeyError, TypeError, ValueError, AttributeError):
        # Unknown/corrupt/outage conditions must not turn into scope permission.
        return {"status": "blocked", "reason": "Live scope authority is unavailable, stale, revoked, expired, inconsistent, or not verified; no execution is authorized."}


def reverse_live(member, authorization, action, expected_revision, reason):
    validate_live(authorization)
    if action not in ("revoke", "rollback"):
        raise ValidationError("Live approval mechanics allow revoke/default-only withdrawal, not routing activation or resume.")
    if type(expected_revision) is not int or expected_revision != authorization.authorization_revision:
        raise ValidationError("Live authorization changed; reload before a stale withdrawal.")
    if authorization.revoked_at is not None:
        raise ValidationError("Live approval is already withdrawn and cannot be revived.")
    authorization.authorization_revision += 1
    event = _event(authorization, member, action, reason)
    authorization.revoked_at = event.timestamp
    authorization.save(update_fields=("authorization_revision", "revoked_at"))
    validate_live(authorization)
    _audit(member, "pilot_" + action, authorization_ref=str(authorization.reference), target="live", reason=reason)


def live_status(authorization, company):
    data = validate_live(authorization)
    guard = live_guard(authorization, company)
    state = "approved" if data["scope_approved"] else "rejected"
    if authorization.revoked_at is not None:
        state = "withdrawn"
    elif timezone.now() >= _timestamp(data["expires_at"]):
        state = "expired"
    elif guard["status"] != "current" and data["scope_approved"]:
        state = "blocked"
    return {"authorization": authorization, "pilot": None, "revision": authorization.authorization_revision,
            "status": state, "guard": guard, "scope": data["scope"],
            "scope_approved": data["scope_approved"], "live_execution_enabled": False,
            "routing_enabled": False, "deployment_authorized": False}


def check_live_scope(request, reference, task_value, repository_ref, boundary, model_id):
    """B-02 authority check for a future adapter, not a task/budget execution ticket."""
    with transaction.atomic():
        member = current_member(request.user)
        require_request_mfa(request, member.user)
        from .authorization import _pilot
        authorization = _pilot(member, reference)
        if authorization.data.get("target") != "live":
            raise ValidationError("Simulation approval cannot authenticate live scope.")
        guard = live_guard(authorization, member.company)
        scope_current = False
        if guard["status"] == "current":
            task = TaskRequest.from_dict(task_value)
            scope = PilotScope.from_dict(authorization.data["scope"])
            choice(boundary, "boundary", ("new_task", "new_run", "subagent", "continuation"))
            text(repository_ref, "repository_ref")
            text(model_id, "model_id")
            route = next((item for item in authorization.data["routes"] if item["task_type"] == task.task_type), None)
            policy = Policy.from_dict(member.company.policy)
            scope_current = (member.participating and task.developer_id == member.developer_id
                             and member.developer_id in scope.developer_ids and repository_ref == scope.repository_ref
                             and repository_ref in member.company.repository_refs and boundary != "continuation"
                             and set(task.risk_tags) == {"low"} and route is not None and route["model"] == model_id
                             and incompatibility(policy.model(model_id), task) is None)
        return {"authorization_ref": str(authorization.reference), "authority_current": guard["status"] == "current",
                "scope_current": scope_current, "guard": guard, "new_reservation": False,
                "execution_authorized": False, "routing_enabled": False, "deployment_authorized": False,
                "note": "Authority/scope check only; a trusted new-task adapter, atomic runtime reservation, and approved deployment are still required before execution."}
