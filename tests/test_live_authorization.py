"""B-02 approval mechanics with isolated, deliberately test-only readiness verification."""

import copy
from dataclasses import replace
from datetime import timedelta
import io
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

import test_company as support
from engine.company import authorization
from engine.company.live_authorization import check_live_scope, validate_live
from engine.company.models import AuthorizationEvent, AuthorizedPilot, Company, EvidenceReview, MFAState, Membership, PilotAuthorization, SecurityEvent
from engine.company.readiness_gate import ReadinessAssessment, ReadinessVerifier, verify_readiness
from engine.company.tasks import company_ledger, recommend_task, record_response, record_execution, record_result
from engine.feedback import _fingerprint
from engine.schemas import ValidationError


class ControlledReadinessVerifier(ReadinessVerifier):
    """Not shipped by the application, not configurable through forms or CLI."""

    def __init__(self):
        self.assessments = {}
        self.calls = []
        self.revoked = False
        self.alter = None

    def verify(self, request):
        self.calls.append(request)
        if self.revoked:
            raise ValidationError("Test evidence was withdrawn.")
        if request.sha256 not in self.assessments:
            now = timezone.now()
            self.assessments[request.sha256] = ReadinessAssessment(
                "controlled-test-verifier", "synthetic-test-verification:" + request.sha256,
                "illustrative-test-criteria-v1", request.sha256, now.isoformat(),
                (now + timedelta(hours=4)).isoformat(), True, True, True,
            )
        assessment = self.assessments[request.sha256]
        return self.alter(assessment) if self.alter else assessment


def setUpModule():
    support.setUpModule()


def tearDownModule():
    connections.close_all()


class LiveApprovalTests(TestCase):
    setUp = support.CompanyControlTests.setUp
    enroll = support.CompanyControlTests.enroll
    request = support.CompanyControlTests.request
    sensitive = support.CompanyControlTests.sensitive
    developer_request = support.CompanyControlTests.developer_request

    def source(self, number=1, **updates):
        return support.CompanyControlTests.source(self, number, source_kind="team", **updates)

    def evidence(self):
        for number in (1, 2):
            task = recommend_task(self.senior, self.source(number))
            task = record_response(self.senior, task.reference, "accept", task.revision)
            task = record_execution(self.senior, task.reference, "fixture/cheap", task.revision)
            record_result(self.senior, task.reference, {"desired_result": True, "tests_passed": None, "score": None,
                          "cost_usd": "0.006", "latency_ms": 200, "evidence_ref": "synthetic-test-confirmation-" + str(number),
                          "supersedes": None}, task.revision)
        ledger = company_ledger(Company.objects.get(), "team")
        plan = {"learner_version": "controlled-live-mechanics-test-v1", "source_kind": "team", "dataset_split": "validation",
                "cutoff": timezone.now().isoformat(), "session_ids": sorted({item.task.session_id for item in ledger.recommendations}),
                "task_types": ["documentation"], "min_senior_successes": 2, "min_senior_sessions": 2}
        return authorization.prepare_review(self.request(), plan)

    def scope(self, **updates):
        return {"pilot_id": "controlled-live-scope-test", "repository_ref": "synthetic-repository", "task_types": ["documentation"],
                "developer_ids": ["junior", "senior"], "max_tasks": 3, "max_cost_usd": "1.00", **updates}

    def approve(self, review=None, scope=None, expires=None, decision="approve"):
        review = review or self.evidence()
        return self.sensitive(authorization.authorize, review.reference, scope or self.scope(),
                              expires or timezone.now() + timedelta(hours=1), "Test live scope; no execution",
                              Company.objects.get().revision, "live", decision)

    def task(self, user=None, **updates):
        user = user or self.junior
        return {"task_id": "future-test-task", "session_id": "future-test-session", "developer_id": user.username,
                "timestamp": timezone.now().isoformat(), "task_type": "documentation", "risk_tags": ["low"],
                "selected_model": "fixture/premium", "required_tools": ["read"], "context_tokens": 2000, **updates}

    def check(self, approval, **updates):
        values = {"task_value": self.task(), "repository_ref": "synthetic-repository", "boundary": "new_task",
                  "model_id": "fixture/cheap", **updates}
        return check_live_scope(self.developer_request(), approval.reference, **values)

    def test_live_positive_approval_binds_human_readiness_policy_scope_and_never_executes(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            with patch("socket.socket", side_effect=AssertionError("No external calls")), patch("subprocess.run", side_effect=AssertionError("No model execution")):
                approval = self.approve()
                state = authorization.status(self.request(), approval.reference)
                scope_check = self.check(approval)
        self.assertEqual(approval.data["record_type"], "company_live_pilot_authorization")
        self.assertTrue(approval.data["scope_approved"])
        self.assertEqual(approval.data["approver"]["account_id"], self.owner.pk)
        self.assertEqual(approval.data["scope"], self.scope())
        self.assertEqual(approval.data["policy"]["sha256"], self.policy.fingerprint())
        self.assertEqual(state["status"], "approved")
        self.assertEqual(state["revision"], 1)
        self.assertTrue(scope_check["scope_current"])
        self.assertTrue(scope_check["authority_current"])
        self.assertFalse(scope_check["execution_authorized"])
        self.assertFalse(scope_check["new_reservation"])
        self.assertFalse(approval.data["routing_enabled"])
        self.assertFalse(approval.data["deployment_authorized"])
        self.assertEqual(AuthorizedPilot.objects.count(), 0)
        self.assertEqual(AuthorizationEvent.objects.get().actor_id, self.owner.pk)

    def test_default_unconfigured_verifier_refuses_positive_live_approval(self):
        with self.assertRaisesRegex(ValidationError, "verifier is not configured"):
            self.approve()
        self.assertEqual(PilotAuthorization.objects.count(), 0)
        self.assertEqual(AuthorizationEvent.objects.count(), 0)

    def test_synthetic_source_cannot_be_enabled_by_a_broken_positive_checker(self):
        # The source label is deliberately synthetic; a checker cannot override the boundary.
        for number in (1, 2):
            task = recommend_task(self.senior, support.CompanyControlTests.source(self, number))
            task = record_response(self.senior, task.reference, "accept", task.revision)
            task = record_execution(self.senior, task.reference, "fixture/cheap", task.revision)
            record_result(self.senior, task.reference, {"desired_result": True, "tests_passed": None, "score": None,
                          "cost_usd": None, "latency_ms": None, "evidence_ref": "synthetic-only", "supersedes": None}, task.revision)
        ledger = company_ledger(Company.objects.get(), "synthetic")
        plan = {"learner_version": "synthetic-only-v1", "source_kind": "synthetic", "dataset_split": "validation",
                "cutoff": timezone.now().isoformat(), "session_ids": [item.task.session_id for item in ledger.recommendations],
                "task_types": ["documentation"], "min_senior_successes": 2, "min_senior_sessions": 2}
        review = authorization.prepare_review(self.request(), plan)
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            with self.assertRaisesRegex(ValidationError, "Synthetic evidence"):
                self.approve(review=review)
        self.assertEqual(verifier.calls, [])
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_team_label_alone_is_not_independent_verification(self):
        review = self.evidence()
        self.assertFalse(review.data["outcome_truth_verified"])
        self.assertFalse(review.data["report"]["deployment_ready"])
        with self.assertRaises(ValidationError):
            self.approve(review=review)

    def test_browser_cannot_supply_assessment_or_install_its_own_verifier(self):
        review = self.evidence()
        response = self.client.post("/pilots/reviews/" + str(review.reference) + "/authorize/", {
            "target": "live", "verified": "true", "readiness_assessment": "forged", "verifier": "anything",
            "confirm_password": support.PASSWORD, "code": "000000",
        })
        self.assertContains(response, "Unexpected form fields")
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_wrong_readiness_binding_cannot_authorize_even_when_checker_returns_positive(self):
        verifier = ControlledReadinessVerifier()
        verifier.alter = lambda assessment: replace(assessment, request_sha256="0" * 64)
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            with self.assertRaisesRegex(ValidationError, "different company"):
                self.approve()
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_missing_outcome_design_or_criteria_checks_are_not_ready(self):
        review = self.evidence()
        for field in ("outcomes_verified", "evaluation_design_verified", "criteria_validated"):
            with self.subTest(field=field):
                verifier = ControlledReadinessVerifier()
                verifier.alter = lambda assessment, name=field: replace(assessment, **{name: False})
                with override_settings(TARKADO_READINESS_VERIFIER=verifier):
                    with self.assertRaises(ValidationError):
                        self.approve(review=review)
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_expired_and_future_assessments_are_refused(self):
        review = self.evidence()
        for offset in (-5, 5):
            verifier = ControlledReadinessVerifier()
            verifier.alter = lambda assessment, hours=offset: replace(
                assessment, verified_at=(timezone.now() + timedelta(hours=hours)).isoformat(),
                valid_until=(timezone.now() + timedelta(hours=hours + 1)).isoformat())
            with override_settings(TARKADO_READINESS_VERIFIER=verifier):
                with self.assertRaises(ValidationError):
                    self.approve(review=review)
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_human_approval_cannot_outlive_verified_readiness(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            with self.assertRaisesRegex(ValidationError, "outlast"):
                self.approve(expires=timezone.now() + timedelta(hours=5))
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_untyped_or_malformed_checker_results_are_refused(self):
        review = self.evidence()
        for value in (object(), {"verified": True}, True):
            with override_settings(TARKADO_READINESS_VERIFIER=value):
                with self.assertRaises(ValidationError):
                    self.approve(review=review)
        verifier = ControlledReadinessVerifier()
        verifier.alter = lambda _: {"verified": True}
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            with self.assertRaises(ValidationError):
                self.approve(review=review)

    def test_checker_outage_fails_closed_and_does_not_echo_exception_content(self):
        verifier = ControlledReadinessVerifier()
        secret = "sk-" + "A" * 32
        with override_settings(TARKADO_READINESS_VERIFIER=verifier), patch.object(verifier, "verify", side_effect=RuntimeError(secret)):
            with self.assertRaises(ValidationError) as error:
                self.approve()
        self.assertNotIn(secret, str(error.exception))
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_live_rejection_records_no_readiness_or_routes_without_a_checker(self):
        approval = self.approve(decision="reject")
        self.assertFalse(approval.data["scope_approved"])
        self.assertIsNone(approval.data["readiness_assessment"])
        self.assertEqual(approval.data["routes"], [])
        self.assertEqual(authorization.status(self.request(), approval.reference)["status"], "rejected")

    def test_only_designated_fresh_mfa_human_can_approve_live_scope(self):
        review = self.evidence()
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            with self.assertRaises(PermissionDenied):
                authorization.authorize(self.developer_request(self.senior), support.PASSWORD, "000000", review.reference,
                                        self.scope(), timezone.now() + timedelta(hours=1), "Invalid", Company.objects.get().revision, "live")
        self.assertEqual(verifier.calls, [])

    def test_positive_readiness_does_not_create_approval_or_activate_policy_on_its_own(self):
        review = self.evidence()
        from engine.company.live_authorization import readiness_request
        from engine.readiness import PilotScope
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            verify_readiness(readiness_request(Company.objects.get(), review, PilotScope.from_dict(self.scope())))
        self.assertEqual(PilotAuthorization.objects.count(), 0)
        self.assertEqual(AuthorizedPilot.objects.count(), 0)

    def test_approval_is_immutable_and_duplicate_ids_cannot_reset_lifetime_scope(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            before = copy.deepcopy(approval.data)
            with self.assertRaises(ValidationError):
                self.approve(review=approval.review)
        approval.refresh_from_db()
        self.assertEqual(approval.data, before)
        self.assertEqual(PilotAuthorization.objects.count(), 1)
        self.assertEqual(AuthorizationEvent.objects.count(), 1)

    def test_scope_checks_include_developer_repository_category_model_risk_and_boundary(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            for update in ({"repository_ref": "another-repository"}, {"boundary": "continuation"}, {"model_id": "fixture/premium"},
                           {"task_value": self.task(developer_id="senior")}, {"task_value": self.task(task_type="test_generation")},
                           {"task_value": self.task(risk_tags=["high"])}, {"task_value": self.task(context_tokens=None)}):
                with self.subTest(update=update):
                    check = self.check(approval, **update)
                    self.assertTrue(check["authority_current"])
                    self.assertFalse(check["scope_current"])
                    self.assertFalse(check["execution_authorized"])
            for boundary in ("new_task", "new_run", "subagent"):
                self.assertTrue(self.check(approval, boundary=boundary)["scope_current"])

    def test_live_approval_is_not_a_simulation_or_execution_ticket(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            for operation in (
                lambda: self.sensitive(authorization.activate, approval.reference, "Cannot activate live through simulation"),
                lambda: authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.1"),
                lambda: authorization.settle(self.developer_request(), approval.reference, "missing-decision", "0", "cancelled"),
            ):
                with self.assertRaises(ValidationError):
                    operation()
        self.assertEqual(AuthorizedPilot.objects.count(), 0)

    def test_revocation_is_ordered_immutable_and_blocks_old_scope_checks(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            before = copy.deepcopy(approval.data)
            self.sensitive(authorization.control, approval.reference, "revoke", 1, "Withdraw only this live scope")
            check = self.check(approval)
            state = authorization.status(self.request(), approval.reference)
            self.assertFalse(check["authority_current"])
            self.assertFalse(check["scope_current"])
            self.assertEqual(state["status"], "withdrawn")
            self.assertEqual(state["revision"], 2)
        approval.refresh_from_db()
        self.assertEqual(approval.data, before)
        self.assertEqual(list(approval.authority_events.values_list("action", flat=True)), ["approve", "revoke"])

    def test_revocation_does_not_need_a_still_available_evidence_checker(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
        self.sensitive(authorization.control, approval.reference, "revoke", 1, "Withdraw during checker outage")
        approval.refresh_from_db()
        self.assertIsNotNone(approval.revoked_at)

    def test_revoked_or_withdrawn_authorizations_cannot_resume_or_be_reapproved(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            self.sensitive(authorization.control, approval.reference, "rollback", 1, "Default-only withdrawal")
            with self.assertRaises(ValidationError):
                self.sensitive(authorization.control, approval.reference, "resume", 2, "Must not revive")
            with self.assertRaises(ValidationError):
                self.approve(review=approval.review)
        self.assertEqual(AuthorizedPilot.objects.count(), 0)

    def test_stale_withdrawal_cannot_overwrite_a_newer_revocation(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            self.sensitive(authorization.control, approval.reference, "revoke", 1, "First withdrawal")
            with self.assertRaises(ValidationError):
                self.sensitive(authorization.control, approval.reference, "revoke", 1, "Stale withdrawal")
        self.assertEqual(AuthorizationEvent.objects.count(), 2)

    def test_checker_revocation_and_criteria_replacement_invalidate_old_live_approval(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            verifier.revoked = True
            self.assertFalse(self.check(approval)["authority_current"])
            verifier.revoked = False
            verifier.alter = lambda item: replace(item, criteria_version="changed-test-criteria")
            self.assertFalse(self.check(approval)["authority_current"])

    def test_checker_outage_after_approval_is_not_reused_as_cached_permission(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
        self.assertFalse(self.check(approval)["authority_current"])

    def test_expiry_prevents_reuse_without_mutating_historical_approval(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            before = copy.deepcopy(approval.data)
            with patch("engine.company.live_authorization.timezone.now", return_value=timezone.now() + timedelta(hours=2)):
                self.assertFalse(self.check(approval)["authority_current"])
        approval.refresh_from_db()
        self.assertEqual(approval.data, before)
        self.assertIsNone(approval.revoked_at)

    def test_approver_permission_mfa_and_deployment_changes_each_block_old_approval(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            Membership.objects.filter(user=self.owner).update(can_approve_pilots=False)
            self.assertFalse(self.check(approval)["authority_current"])
            Membership.objects.filter(user=self.owner).update(can_approve_pilots=True)
            MFAState.objects.filter(user=self.owner).update(generation=2)
            self.assertFalse(self.check(approval)["authority_current"])
            MFAState.objects.filter(user=self.owner).update(generation=1)
            company = Company.objects.get()
            company.deployment_id = "00000000-0000-0000-0000-000000000000"
            company.save(update_fields=("deployment_id",))
            self.assertFalse(self.check(approval)["authority_current"])

    def test_current_company_revision_and_scoped_member_revocation_are_checked(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            company = Company.objects.get()
            Company.objects.filter(pk=company.pk).update(revision=company.revision + 1)
            self.assertFalse(self.check(approval)["authority_current"])
            Company.objects.filter(pk=company.pk).update(revision=company.revision)
            Membership.objects.filter(user=self.senior).update(participating=False)
            self.assertFalse(self.check(approval)["authority_current"])

    def test_old_approval_cannot_ignore_new_category_failure(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            from engine.company.models import CompanyTask
            from engine.company.tasks import task_ledger
            task = CompanyTask.objects.filter(owner=self.senior).first()
            record_result(self.senior, task.reference, {"desired_result": False, "tests_passed": False, "score": None,
                          "cost_usd": "0.006", "latency_ms": None, "evidence_ref": "new-test-negative-result",
                          "supersedes": task_ledger(task).results[-1].result_id}, task.revision)
            self.assertFalse(self.check(approval)["authority_current"])

    def test_altered_readiness_routes_or_scope_even_with_new_hash_do_not_pass_validation(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            original = copy.deepcopy(approval.data)
            for change in (
                lambda data: data["scope"].update(repository_ref="different-repository"),
                lambda data: data.update(routes=[{"task_type": "documentation", "model": "fixture/premium"}]),
                lambda data: data.update(routing_enabled=True),
                lambda data: data.update(deployment_authorized=True),
                lambda data: data["readiness_assessment"].update(request_sha256="0" * 64),
                lambda data: data["approver"].update(account_id=self.junior.pk),
            ):
                with self.subTest(change=change):
                    altered = copy.deepcopy(original)
                    change(altered)
                    altered["sha256"] = _fingerprint({key: value for key, value in altered.items() if key != "sha256"})
                    approval.data = altered
                    with self.assertRaises(ValidationError):
                        validate_live(approval)
            approval.data = original

    def test_missing_or_modified_revocation_history_is_refused_not_repaired(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()
            original = copy.deepcopy(approval.data)
            approval.authority_events.all().delete()
            with self.assertRaises(ValidationError):
                validate_live(approval)
            self.assertFalse(self.check(approval)["authority_current"])
            approval.refresh_from_db()
            self.assertEqual(approval.data, original)

    def test_live_positive_browser_approval_and_withdrawal_keep_simulation_links_hidden(self):
        review = self.evidence()
        verifier = ControlledReadinessVerifier()
        from django_otp.plugins.otp_totp.models import TOTPDevice
        device = TOTPDevice.objects.get(user=self.owner, confirmed=True)
        code, at = support.device_code(device)
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
                response = self.client.post("/pilots/reviews/" + str(review.reference) + "/authorize/", {
                    "confirm_password": support.PASSWORD, "code": code, "pilot_id": "live-browser-test",
                    "repository_ref": "synthetic-repository", "task_types": "documentation", "developer_ids": "junior,senior",
                    "max_tasks": 3, "max_cost_usd": "1.00", "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
                    "reason": "Controlled browser live-approval test", "expected_revision": Company.objects.get().revision,
                    "target": "live", "decision": "approve",
                })
            self.assertEqual(response.status_code, 302)
            path = response["Location"]
            page = self.client.get(path)
            self.assertContains(page, "not an execution/reservation ticket")
            self.assertNotContains(page, "Scoped simulated new-task admission</a>")
            device.refresh_from_db()
            code, at = support.device_code(device)
            with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
                response = self.client.post(path, {"confirm_password": support.PASSWORD, "code": code,
                                                 "action": "revoke", "expected_revision": 1, "reason": "Controlled browser withdrawal"})
            self.assertEqual(response.status_code, 302)
            self.assertContains(self.client.get(path), "withdrawn")
        self.assertEqual(AuthorizedPilot.objects.count(), 0)

    def test_migration_matches_models_and_live_revision_defaults_to_one(self):
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            call_command("makemigrations", "company", check=True, dry_run=True, verbosity=1)
        self.assertIn("No changes detected", output.getvalue())
        self.assertEqual(PilotAuthorization._meta.get_field("authorization_revision").default, 1)


class LiveApprovalConcurrencyTests(TransactionTestCase):
    setUp = LiveApprovalTests.setUp
    enroll = LiveApprovalTests.enroll
    request = LiveApprovalTests.request
    sensitive = LiveApprovalTests.sensitive
    developer_request = LiveApprovalTests.developer_request
    source = LiveApprovalTests.source
    evidence = LiveApprovalTests.evidence
    scope = LiveApprovalTests.scope
    approve = LiveApprovalTests.approve
    task = LiveApprovalTests.task
    check = LiveApprovalTests.check

    def test_committed_revocation_in_another_connection_blocks_next_scope_check(self):
        verifier = ControlledReadinessVerifier()
        with override_settings(TARKADO_READINESS_VERIFIER=verifier):
            approval = self.approve()

            def revoke():
                try:
                    self.sensitive(authorization.control, approval.reference, "revoke", 1, "Concurrent live withdrawal")
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(revoke).result()
            self.assertFalse(self.check(approval)["scope_current"])
        self.assertEqual(AuthorizationEvent.objects.count(), 2)

    def test_one_fresh_mfa_code_cannot_create_duplicate_live_approvals_concurrently(self):
        review = self.evidence()
        verifier = ControlledReadinessVerifier()
        request = self.request()
        code, at = support.device_code(request.user.otp_device)

        def approve(_):
            try:
                current = self.request()
                authorization.authorize(current, support.PASSWORD, code, review.reference, self.scope(),
                                        timezone.now() + timedelta(hours=1), "Concurrent exact live scope",
                                        Company.objects.get().revision, "live")
                return "approved"
            except (PermissionDenied, ValidationError):
                return "refused"
            finally:
                connections.close_all()

        with override_settings(TARKADO_READINESS_VERIFIER=verifier), patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(approve, range(2)))
        self.assertEqual(sorted(results), ["approved", "refused"])
        self.assertEqual(PilotAuthorization.objects.count(), 1)
        self.assertEqual(AuthorizationEvent.objects.count(), 1)
