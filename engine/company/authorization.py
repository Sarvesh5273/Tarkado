"""Authoritative scoped approvals and B-01 journal reuse; no model dispatch."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from engine.feedback import TaskRequest, _fingerprint
from engine.history import PolicySnapshot
from engine.learning import LearnedModel, LearningPlan, _source_digest, fit_feedback
from engine.pilot import PilotJournal, PilotRequest, PilotState, _event, _settlement
from engine.readiness import ApproverRoster, PilotScope, ReadinessReport, build_readiness, review_pilot
from engine.schemas import Policy, ValidationError, choice, text

from .mfa import _audit, primary_verified, require_request_mfa
from .models import AuthorizedPilot, EvidenceReview, MFAState, Membership, PilotAuthorization
from .security import sensitive_actor
from .services import _check_revision, current_member, member_snapshot
from .tasks import company_ledger


def _reviewer(request):
    member = current_member(request.user)
    if not (member.can_manage_company and member.role == "admin") and not (
        member.can_approve_pilots and member.role in ("senior", "admin")
    ):
        raise PermissionDenied("Evidence/pilot administration requires explicit company or pilot-review authority.")
    if not primary_verified(request, member):
        raise PermissionDenied("Current primary MFA is required for company evidence and authorization.")
    return member


def _roster(company):
    entries = Membership.objects.filter(company=company, active=True, user__is_active=True,
                                        can_approve_pilots=True, role__in=("senior", "admin")).order_by("developer_id")
    return ApproverRoster.from_dict({"approvers": [{"approver_id": item.developer_id, "role": item.role,
                                                   "can_approve_pilots": True} for item in entries]})


def _review_payload(company, ledger, learner):
    payload = {"company_id": str(company.company_id), "deployment_id": str(company.deployment_id),
             "ledger_sha256": _source_digest(ledger), "learner": learner.to_dict(),
             "report": build_readiness(ledger, Policy.from_dict(company.policy), learner).to_dict(),
             "identity_source": "authenticated_company_event_snapshots", "outcome_truth_verified": False}
    from .models import ConnectorTask
    from .connectors import task_state
    links = ConnectorTask.objects.select_related("task__company", "credential").filter(task__company=company,
        task__source_kind=learner.plan.source_kind).order_by("id")
    observations = [{"task_ref": str(link.task.reference), "state": task_state(link),
                     "observations": [{"sequence": row.sequence, "received_at": row.received_at.isoformat(),
                        "payload": row.payload, "actor_snapshot": row.actor_snapshot, "missing_before": row.missing_before}
                        for row in link.observations.all()]} for link in links]
    if observations:
        # Binding sidecar observations prevents a report ignoring new gaps/failures.
        # These are diagnostics, not invented engineering-quality or usage labels.
        payload["connector_observations"] = observations
    return payload


def prepare_review(request, plan_value):
    with transaction.atomic():
        member = _reviewer(request)
        plan = LearningPlan.from_dict(plan_value)
        ledger = company_ledger(member.company, plan.source_kind)
        learner = fit_feedback(ledger, Policy.from_dict(member.company.policy), plan)
        data = _review_payload(member.company, ledger, learner)
        data["sha256"] = _fingerprint(data)
        existing = EvidenceReview.objects.filter(company=member.company, data__sha256=data["sha256"]).first()
        if existing:
            return existing
        review = EvidenceReview.objects.create(company=member.company, creator=member.user, created_at=timezone.now(), data=data)
        _audit(member, "evidence_review_prepare", review_ref=str(review.reference), report_sha256=data["report"]["report_sha256"])
        return review


def verify_review(review, company, allow_future_recommendations=False):
    if review.company_id != company.pk or review.data.get("company_id") != str(company.company_id) or (
        review.data.get("deployment_id") != str(company.deployment_id)
    ):
        raise ValidationError("Evidence review is outside this exact company/deployment.")
    payload = {key: value for key, value in review.data.items() if key != "sha256"}
    if _fingerprint(payload) != review.data.get("sha256"):
        raise ValidationError("Company evidence review content is inconsistent.")
    learner = LearnedModel.from_dict(review.data["learner"])
    if Policy.from_dict(company.policy).fingerprint() != learner.policy.sha256:
        raise ValidationError("Company policy content differs from the exact reviewed learner; new review is required.")
    ledger = company_ledger(company, learner.plan.source_kind)
    expected = _review_payload(company, ledger, learner)
    if payload != expected:
        if not allow_future_recommendations:
            raise ValidationError("Company task evidence or policy changed; regenerate and separately review before approval.")
        # B-05 freezes the validation artifact, while future pending recommendations
        # may be added. Existing observations and every new negative/gap still veto.
        fixed = ("company_id", "deployment_id", "learner", "identity_source", "outcome_truth_verified")
        if any(payload[key] != expected[key] for key in fixed):
            raise ValidationError("Frozen review identity/policy/learner changed; new scope approval is required.")
        source_rows = {row["recommendation_id"]: row for row in expected["report"]["observations"]}
        if any(source_rows.get(row["recommendation_id"]) != row for row in payload["report"]["observations"]):
            raise ValidationError("Previously reviewed task observations changed; new scope approval is required.")
        existing_refs = {item["task_ref"] for item in payload.get("connector_observations", [])}
        current_links = {item["task_ref"]: item for item in expected.get("connector_observations", [])}
        for item in payload.get("connector_observations", []):
            if current_links.get(item["task_ref"], {}).get("observations") != item["observations"]:
                raise ValidationError("Previously reviewed connector observations changed.")
        for ref, item in current_links.items():
            if ref not in existing_refs and (item["state"]["gap_count"] or item["state"]["multiple_models"] or
                any((row["payload"].get("http_status") or 0) >= 400 for row in item["observations"])):
                raise ValidationError("New connector negative/gap/multi-model observations require another scope review.")
    learner.verify_source(ledger)
    return ledger, learner, ReadinessReport.from_dict(review.data["report"])


def authorize(request, password, code, review_ref, scope_value, expires_at, reason, expected_revision, target="simulation", decision="approve"):
    sensitive_actor(request, password, code, "approve")
    reason = text(reason, "reason")
    with transaction.atomic():
        member = current_member(request.user, "approve")
        require_request_mfa(request, member.user)
        company = member.company
        _check_revision(company, expected_revision)
        choice(target, "authorization_target", ("simulation", "live"))
        choice(decision, "decision", ("approve", "reject"))
        review = EvidenceReview.objects.filter(company=company, reference=review_ref).first()
        if review is None:
            raise ValidationError("Review is not stored by this company; caller receipts/reports are not authorization.")
        ledger, learner, report = verify_review(review, company)
        scope = PilotScope.from_dict(scope_value)
        if len(scope.pilot_id) > 128:
            raise ValidationError("Pilot identifier must be at most 128 characters.")
        if scope.repository_ref not in company.repository_refs:
            raise ValidationError("Pilot repository is outside current company collection scope.")
        for developer in scope.developer_ids:
            if not Membership.objects.filter(company=company, developer_id=developer, active=True, user__is_active=True,
                                              participating=True, role__in=("junior", "developer", "senior")).exists():
                raise ValidationError("Pilot includes an inactive, unapproved, or nonparticipating developer.")
        now = timezone.now()
        if expires_at is None or timezone.is_naive(expires_at) or not now < expires_at <= now + timedelta(days=7):
            raise ValidationError("Pilot authorization requires an explicit expiry within seven days.")
        if PilotAuthorization.objects.filter(company=company, pilot_id=scope.pilot_id).exists():
            raise ValidationError("Pilot identifier already has an immutable company authorization; use its existing state, never restart the budget.")
        if target == "live":
            from .live_authorization import record_live
            return record_live(member, review, scope, report, expires_at, reason, decision)
        receipt = review_pilot(report, scope, _roster(company), member.developer_id, decision, now.isoformat(), reason,
                              ledger, Policy.from_dict(company.policy), learner)
        data = {"company_id": str(company.company_id), "deployment_id": str(company.deployment_id),
                "review_ref": str(review.reference), "review_sha256": review.data["sha256"], "receipt": receipt.to_dict(),
                "approver": member_snapshot(member), "mfa_generation": MFAState.objects.get(user=member.user).generation,
                "company_revision": company.revision, "approved_at": now.isoformat(), "expires_at": expires_at.isoformat(),
                "reason": reason, "target": target, "decision": decision, "routing_enabled": False, "deployment_authorized": False}
        data["sha256"] = _fingerprint(data)
        authorization = PilotAuthorization.objects.create(company=company, review=review, approver=member.user,
                                                            pilot_id=scope.pilot_id, data=data)
        _audit(member, "pilot_authorize", authorization_ref=str(authorization.reference), authorization_sha256=data["sha256"], target=target, decision=decision)
        return authorization


def _validate_authorization(authorization):
    if authorization.data.get("target") == "live":
        from .live_authorization import validate_live
        return validate_live(authorization)
    data = authorization.data
    payload = {key: value for key, value in data.items() if key != "sha256"}
    if _fingerprint(payload) != data.get("sha256") or data["review_ref"] != str(authorization.review.reference):
        raise ValidationError("Authorization contents or review binding are inconsistent.")
    if data["approver"]["account_id"] != authorization.approver_id or data["target"] != "simulation" or data["routing_enabled"] or data["deployment_authorized"]:
        raise ValidationError("Current authorization is not a valid authenticated simulation scope.")
    from engine.readiness import PilotReview
    receipt = PilotReview.from_dict(data["receipt"])
    if receipt.data["report"] != authorization.review.data["report"]:
        raise ValidationError("Receipt report differs from its stored company evidence review.")
    if receipt.data["reviewer_id"] != data["approver"]["developer_id"] or receipt.data["reviewer_role"] != data["approver"]["role"]:
        raise ValidationError("Receipt identity differs from its authenticated approver snapshot.")
    if data["decision"] != receipt.data["decision"]:
        raise ValidationError("Company authorization decision differs from its receipt.")
    if receipt.data["scope"]["pilot_id"] != authorization.pilot_id:
        raise ValidationError("Authorization pilot ID differs from its bound scope.")
    return receipt


def authorization_guard(authorization, company):
    if authorization.data.get("target") == "live":
        from .live_authorization import live_guard
        return live_guard(authorization, company)
    try:
        receipt = _validate_authorization(authorization)
        if not receipt.data["approved_for_local_simulation"]:
            raise ValidationError("This pilot scope was rejected; there is no admission authorization.")
        data = authorization.data
        if authorization.company_id != company.pk or (data["company_id"], data["deployment_id"]) != (
            str(company.company_id), str(company.deployment_id)
        ):
            raise ValidationError("Authorization belongs to a different company/deployment.")
        if authorization.revoked_at is not None or timezone.now() >= timezone.datetime.fromisoformat(data["expires_at"]):
            raise ValidationError("Authorization was revoked or expired.")
        if data["company_revision"] != company.revision:
            raise ValidationError("Company permissions/configuration changed; new review is required.")
        approver = current_member(authorization.approver, "approve")
        if member_snapshot(approver) != data["approver"]:
            raise ValidationError("Current approver authority differs from the exact approved identity/scope.")
        state = MFAState.objects.filter(user=approver.user).first()
        if state is None or state.generation != data["mfa_generation"] or not TOTPDevice.objects.filter(user=approver.user, confirmed=True).exists():
            raise ValidationError("Approver MFA/recovery authority changed; old approval cannot authorize new admissions.")
        verify_review(authorization.review, company)
        if authorization.review.data["sha256"] != data["review_sha256"]:
            raise ValidationError("Evidence review binding changed.")
        if receipt.data["approver_roster"] != _roster(company).to_dict():
            raise ValidationError("Current approver roster no longer matches this review.")
        return {"status": "current", "reason": "Current company authorization, evidence, identity, and validity match."}
    except (ValidationError, PermissionDenied) as error:
        return {"status": "blocked", "reason": str(error)}


def _pilot(member, reference):
    authorization = PilotAuthorization.objects.select_related("review", "approver", "company").filter(
        company=member.company, reference=reference).first()
    if authorization is None:
        raise PermissionDenied("Pilot authorization is unavailable for this company.")
    return authorization


def activate(request, password, code, reference, reason, expected_revision=None):
    sensitive_actor(request, password, code, "approve")
    reason = text(reason, "reason")
    with transaction.atomic():
        member = current_member(request.user, "approve")
        require_request_mfa(request, member.user)
        authorization = _pilot(member, reference)
        if authorization.data.get("target") == "live":
            raise ValidationError("Live scope approval does not activate simulation or routing. Trusted adapter/runtime and deployment gates remain separate.")
        existing = AuthorizedPilot.objects.filter(authorization=authorization).first()
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision != (
            _journal(existing).state().revision if existing else 0
        )):
            raise ValidationError("Pilot state changed; reload before a stale activation.")
        guard = authorization_guard(authorization, member.company)
        if guard["status"] != "current":
            raise ValidationError(guard["reason"])
        if existing is not None:
            if existing.activation_actor_id != member.user_id or existing.activation_reason != reason:
                raise ValidationError("This approval already has different activation content; budget/history cannot restart.")
            return existing
        for other in AuthorizedPilot.objects.filter(authorization__company=member.company):
            if PilotJournal.from_dict(other.journal).state().status in ("active", "paused"):
                raise ValidationError("This single-company installation already has an active/paused pilot; end it before activating another.")
        receipt = _validate_authorization(authorization)
        learner = LearnedModel.from_dict(authorization.review.data["learner"])
        state = PilotState(receipt, learner)
        event = _event(state, "activate", timezone.now().isoformat(), {"reviewer_id": member.developer_id,
                         "approver_roster": _roster(member.company).to_dict(), "reason": reason})
        journal = PilotJournal(receipt, learner, (event,))
        PilotJournal.from_dict(journal.to_dict())
        pilot = AuthorizedPilot.objects.create(authorization=authorization, journal=journal.to_dict(), activation_actor=member.user,
                                                activation_reason=reason)
        _audit(member, "pilot_activate", authorization_ref=str(reference))
        return pilot


def _journal(pilot):
    journal = PilotJournal.from_dict(pilot.journal)
    if journal.receipt != _validate_authorization(pilot.authorization):
        raise ValidationError("Runtime journal differs from the exact authoritative approval.")
    return journal


def _save(pilot, journal):
    pilot.journal = PilotJournal.from_dict(journal.to_dict()).to_dict()
    pilot.save(update_fields=("journal",))


def control(request, password, code, reference, action, expected_revision, reason):
    sensitive_actor(request, password, code, "approve")
    reason = text(reason, "reason")
    with transaction.atomic():
        member = current_member(request.user, "approve")
        require_request_mfa(request, member.user)
        authorization = _pilot(member, reference)
        choice(action, "action", ("pause", "resume", "revoke", "rollback"))
        if authorization.data.get("target") == "live":
            from .live_authorization import reverse_live
            reverse_live(member, authorization, action, expected_revision, reason)
            return
        pilot = AuthorizedPilot.objects.filter(authorization=authorization).first()
        if pilot is None:
            if action != "revoke" or expected_revision != 0:
                raise ValidationError("An unactivated authorization may only be revoked at revision zero.")
        else:
            journal = _journal(pilot)
            state = journal.state()
            if state.revision != expected_revision:
                raise ValidationError("Pilot state changed; reload before a stale control action.")
            if action == "resume":
                guard = authorization_guard(authorization, member.company)
                if guard["status"] != "current":
                    raise ValidationError(guard["reason"])
            event = _event(state, action, timezone.now().isoformat(), {"reviewer_id": member.developer_id,
                           "approver_roster": _roster(member.company).to_dict(), "reason": reason})
            _save(pilot, PilotJournal(journal.receipt, journal.learner, journal.events + (event,)))
        if action in ("revoke", "rollback"):
            authorization.revoked_at = timezone.now()
            authorization.save(update_fields=("revoked_at",))
        _audit(member, "pilot_" + action, authorization_ref=str(reference), reason=reason)


def status(request, reference):
    with transaction.atomic():
        member = _reviewer(request)
        authorization = _pilot(member, reference)
        if authorization.data.get("target") == "live":
            from .live_authorization import live_status
            return live_status(authorization, member.company)
        pilot = AuthorizedPilot.objects.filter(authorization=authorization).first()
        guard = authorization_guard(authorization, member.company)
        if pilot is None:
            return {"authorization": authorization, "pilot": None, "revision": 0, "status": "unactivated", "guard": guard,
                    "routing_enabled": False, "deployment_authorized": False}
        journal = _journal(pilot)
        state = journal.state()
        return {"authorization": authorization, "pilot": pilot, "revision": state.revision, "status": state.status,
                "guard": guard, "accounting": state.accounting(), "journal": journal.to_dict(),
                "routing_enabled": False, "deployment_authorized": False}


def decide(request, reference, task_value, reserve_usd, override_model=None):
    with transaction.atomic():
        member = current_member(request.user)
        require_request_mfa(request, member.user)
        if not member.participating:
            raise PermissionDenied("Only a participating developer may submit a new scoped simulated task.")
        authorization = _pilot(member, reference)
        if authorization.data.get("target") == "live":
            raise ValidationError("Live approval cannot be executed through a simulation endpoint; no trusted live adapter/reservation is available here.")
        pilot = AuthorizedPilot.objects.filter(authorization=authorization).first()
        if pilot is None:
            raise ValidationError("Separate authorization must be explicitly activated before simulation admission.")
        # Validate the same manual task metadata shape without creating feedback or
        # claiming an execution. Adding simulated outcomes to training would be false.
        from .tasks import INPUT_FIELDS, _session_ref, _scope
        from engine.schemas import object_fields
        source = object_fields(task_value, INPUT_FIELDS, INPUT_FIELDS)
        choice(source["boundary"], "boundary", ("new_task", "new_run", "subagent", "continuation"))
        if source["source_kind"] != "synthetic":
            raise ValidationError("The runtime has no trusted live task adapter; simulated admissions must be labeled synthetic.")
        task = TaskRequest.from_dict({"task_id": source["task_id"], "session_id": _session_ref(member.company, member.developer_id, source["session_id"]),
                                      "developer_id": member.developer_id, "timestamp": timezone.now().isoformat(),
                                      **{field: source[field] for field in ("task_type", "risk_tags", "selected_model", "required_tools", "context_tokens")}})
        _scope(member, source["repository_ref"], task.to_dict())
        identity = "company_decision_" + _fingerprint({"task": {key: value for key, value in task.to_dict().items() if key != "timestamp"},
                                                       "repository": source["repository_ref"], "boundary": source["boundary"]})
        journal = _journal(pilot)
        state = journal.state()
        historical = state.decisions.get(identity)
        if historical is not None:
            normalized = None if reserve_usd is None else str(reserve_usd)
            if historical["request"]["reserve_usd"] != normalized or historical["request"]["override_model"] != override_model:
                raise ValidationError("This decision already has different reservation/override content.")
            return {"historical_replay": True, "simulation_admitted": False, "decision_id": identity, "result": historical["result"]}
        proposal = PilotRequest.from_dict({"decision_id": identity, "task": task.to_dict(), "repository_ref": source["repository_ref"],
                                           "boundary": source["boundary"], "reserve_usd": reserve_usd, "override_model": override_model})
        policy = Policy.from_dict(member.company.policy)
        guard = authorization_guard(authorization, member.company)
        payload = {"request": proposal.to_dict(), "policy": PolicySnapshot.create(policy).to_dict(), "guard": guard,
                   "result": state.decision(proposal, policy, guard)}
        event = _event(state, "decision", task.timestamp, payload)
        _save(pilot, PilotJournal(journal.receipt, journal.learner, journal.events + (event,)))
        _audit(member, "pilot_decide", authorization_ref=str(reference), decision_id=identity, result=payload["result"]["status"])
        return {"historical_replay": False, "simulation_admitted": payload["result"]["status"] == "reserved", "decision_id": identity,
                "result": payload["result"], "routing_enabled": False, "deployment_authorized": False}


def settle(request, reference, decision_id, cost, outcome):
    with transaction.atomic():
        member = current_member(request.user)
        require_request_mfa(request, member.user)
        authorization = _pilot(member, reference)
        if authorization.data.get("target") == "live":
            raise ValidationError("A live scope approval creates no simulation accounting or settlement authority.")
        pilot = AuthorizedPilot.objects.filter(authorization=authorization).first()
        if pilot is None:
            raise ValidationError("Unactivated authorization has no recorded task accounting to settle.")
        journal = _journal(pilot)
        state = journal.state()
        decision = state.decisions.get(decision_id)
        if decision is None or decision["request"]["task"]["developer_id"] != member.developer_id:
            raise PermissionDenied("Only the original simulated task's developer may settle its accounting.")
        settlement = _settlement({"settlement_id": "company_settlement_" + decision_id, "decision_id": decision_id,
                                  "timestamp": timezone.now().isoformat(), "actual_cost_usd": cost, "outcome": outcome})
        existing = state.settlements.get(decision_id)
        if existing is not None:
            if (existing["actual_cost_usd"], existing["outcome"]) != (settlement["actual_cost_usd"], settlement["outcome"]):
                raise ValidationError("Settlement already has different cost/outcome; history cannot be overwritten.")
            return state.accounting()
        _save(pilot, PilotJournal(journal.receipt, journal.learner, journal.events + (_event(state, "settle", settlement["timestamp"], settlement),)))
        _audit(member, "pilot_settle", authorization_ref=str(reference), decision_id=decision_id, cost_usd=settlement["actual_cost_usd"])
        return _journal(pilot).state().accounting()
