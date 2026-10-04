"""Controlled conditional selection proofs only; no provider dispatch or real deployment evidence."""

import copy
import json
from datetime import timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import test_company as support
import test_live_authorization as live
from django.test import TestCase, TransactionTestCase, override_settings
from django.db import connections
from django.utils import timezone

from engine.company import selection
from engine.company.admission_gate import AdmissionVerifier, AdmissionAssessment
from engine.company.models import Company, ScopedSelectionRuntime
from engine.company.services import current_member


def setUpModule():
    support.setUpModule()


def tearDownModule():
    connections.close_all()


class ControlledAdmissionVerifier(AdmissionVerifier):
    def __init__(self):
        self.proofs = {}
        self.revoked = False

    def verify(self, request):
        if self.revoked:
            raise support.ValidationError("Controlled boundary withdrawn")
        if request.sha256 not in self.proofs:
            now = timezone.now()
            self.proofs[request.sha256] = AdmissionAssessment("test-only-adapter", "boundary:" + request.sha256, request.sha256,
                now.isoformat(), (now + timedelta(minutes=5)).isoformat(), True, True, True, True, True)
        return self.proofs[request.sha256]


class SelectionTests(TestCase):
    setUp = live.LiveApprovalTests.setUp
    enroll = live.LiveApprovalTests.enroll
    request = live.LiveApprovalTests.request
    sensitive = live.LiveApprovalTests.sensitive
    source = live.LiveApprovalTests.source
    evidence = live.LiveApprovalTests.evidence
    approve = live.LiveApprovalTests.approve
    scope = live.LiveApprovalTests.scope
    developer_request = live.LiveApprovalTests.developer_request
    task = live.LiveApprovalTests.task

    def active(self):
        self.readiness = live.ControlledReadinessVerifier()
        self.settings_override = override_settings(TARKADO_READINESS_VERIFIER=self.readiness)
        self.settings_override.enable(); self.addCleanup(self.settings_override.disable)
        approval = self.approve()
        self.sensitive(selection.activate, approval.reference, "Activate conditional test selection only")
        return approval

    def value(self, number=1, **updates):
        return {"selection_id": f"synthetic-selection-{number}", "task": self.task(task_id=f"future-{number}", session_id=f"new-session-{number}"),
                "repository_ref": "synthetic-repository", "boundary": "new_task", "reserve_usd": "0.10", "override_model": None, **updates}

    def choose(self, approval, number=1, user=None, **updates):
        user = user or self.junior
        value = self.value(number, **updates)
        if user != self.junior:
            value["task"]["developer_id"] = user.username
        return selection.select(current_member(user), approval.reference, value)

    def test_live_scope_and_activation_alone_cannot_select_without_admission(self):
        approval = self.active()
        with self.assertRaisesMessage(support.ValidationError, "unconfigured"):
            self.choose(approval)
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["selected_tasks"], 0)

    def test_exact_conditional_choice_for_junior_and_senior_requires_independent_proof(self):
        approval = self.active()
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()):
            for number, user in ((1, self.junior), (2, self.senior)):
                result = self.choose(approval, number, user)
                self.assertEqual(result["selection"]["model"], "fixture/cheap")
                self.assertTrue(result["new_reservation"])
                self.assertFalse(result["execution_authorized"])
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.20")

    def test_override_and_unsupported_boundary_keep_default_or_manual_without_reservation(self):
        approval = self.active()
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()):
            chosen = self.choose(approval, override_model="fixture/standard")
            self.assertEqual(chosen["selection"]["model"], "fixture/standard")
            fallback = self.choose(approval, 2, boundary="continuation")
            self.assertFalse(fallback["new_reservation"])
            self.assertEqual(fallback["fallback_model"], "fixture/premium")
            unknown = self.choose(approval, 3, override_model="unknown/model")
            self.assertFalse(unknown["new_reservation"])

    def test_exact_retry_no_double_reservation_and_changed_content_refused(self):
        approval = self.active()
        value = self.value()
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()):
            selection.select(current_member(self.junior), approval.reference, value)
            retry = selection.select(current_member(self.junior), approval.reference, value)
            self.assertTrue(retry["historical_replay"])
            self.assertFalse(retry["new_reservation"])
            with self.assertRaisesMessage(support.ValidationError, "retry changed"):
                selection.select(current_member(self.junior), approval.reference, dict(value, reserve_usd="0.20"))

    def test_one_use_claim_rechecks_current_authority_and_does_not_send_model(self):
        approval = self.active()
        proof = ControlledAdmissionVerifier()
        with override_settings(TARKADO_ADMISSION_VERIFIER=proof), patch("socket.socket", side_effect=AssertionError("No provider")), patch("subprocess.run", side_effect=AssertionError("No client")):
            self.choose(approval)
            result = selection.claim(current_member(self.junior), approval.reference, "synthetic-selection-1")
            self.assertTrue(result["new_claim"])
            self.assertFalse(result["execution_authorized"])
            retry = selection.claim(current_member(self.junior), approval.reference, "synthetic-selection-1")
            self.assertFalse(retry["new_claim"])

    def test_claim_refuses_revoked_boundary_and_scope_and_retains_reserved_budget(self):
        approval = self.active()
        proof = ControlledAdmissionVerifier()
        with override_settings(TARKADO_ADMISSION_VERIFIER=proof):
            self.choose(approval)
            proof.revoked = True
            with self.assertRaises(support.ValidationError):
                selection.claim(current_member(self.junior), approval.reference, "synthetic-selection-1")
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")

    def test_cost_failure_overrun_negative_budget_pauses_and_remains_after_rollback(self):
        approval = self.active()
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()):
            self.choose(approval)
            selection.claim(current_member(self.junior), approval.reference, "synthetic-selection-1")
            result = selection.settle(current_member(self.junior), approval.reference, "synthetic-selection-1", "1.30", "failed")
        self.assertEqual(result["remaining_usd"], "-0.30")
        self.assertEqual(selection.status(self.request(), approval.reference)["selection_status"], "paused")
        self.sensitive(selection.control, approval.reference, "rollback", 4, "Default-only conditional withdrawal")
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["spent_usd"], "1.30")
        self.assertEqual(selection.status(self.request(), approval.reference)["selection_status"], "rolled_back")

    def test_stale_controls_and_illegal_resume_cannot_reset_runtime(self):
        approval = self.active()
        with self.assertRaisesMessage(support.ValidationError, "changed"):
            self.sensitive(selection.control, approval.reference, "pause", 0, "Stale pause")
        self.sensitive(selection.control, approval.reference, "revoke", 1, "End pilot")
        with self.assertRaises(support.ValidationError):
            self.sensitive(selection.control, approval.reference, "resume", 2, "Cannot revive")
        self.assertEqual(selection.status(self.request(), approval.reference)["selection_status"], "revoked")

    def test_selection_accounts_enforce_scope_budget_task_limit_and_owner(self):
        approval = self.active()
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()):
            self.choose(approval, reserve_usd="0.80")
            result = self.choose(approval, 2, reserve_usd="0.30")
            self.assertFalse(result["new_reservation"])
            with self.assertRaises(support.PermissionDenied):
                selection.settle(current_member(self.senior), approval.reference, "synthetic-selection-1", "0", "cancelled")

    def test_pending_settlement_survives_revoke_without_returning_live_authority(self):
        approval = self.active()
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()):
            self.choose(approval)
        self.sensitive(selection.control, approval.reference, "revoke", 2, "Stop new selection")
        result = selection.settle(current_member(self.junior), approval.reference, "synthetic-selection-1", "0", "cancelled")
        self.assertEqual(result["reserved_usd"], "0")
        self.assertEqual(result["remaining_task_slots"], 2)

    def test_untyped_wrong_bound_or_outage_admission_refused(self):
        approval = self.active()
        class Broken(AdmissionVerifier):
            def verify(self, request):
                return {"new_task_verified": True}
        with override_settings(TARKADO_ADMISSION_VERIFIER=Broken()):
            with self.assertRaisesMessage(support.ValidationError, "typed assessment"):
                self.choose(approval)
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["selected_tasks"], 0)

    def test_browser_conditional_controls_distinct_from_live_scope_and_private_apis(self):
        approval = self.active()
        path = f"/pilots/{approval.reference}/selection/"
        self.assertContains(self.client.get(path), "Conditional scoped selection")
        self.assertContains(self.client.get(path), "unconfigured")
        junior = support.LocalClient(); junior.force_login(self.junior)
        self.assertEqual(junior.get(path).status_code, 403)

    def test_bearer_conditional_api_refuses_synthetic_and_unconfigured_proof(self):
        approval = self.active()
        from test_connectors import ConnectorTests
        _, value, browser = ConnectorTests.pair(self, source_kind="team")
        source = ConnectorTests.task_source(self)
        started = ConnectorTests.api(self, value, "start", source).json()
        from engine.company.models import ConnectorTask
        from engine.company.tasks import task_ledger
        link = ConnectorTask.objects.get(reference=started["connector_task_ref"])
        proposal = self.value(task=task_ledger(link.task).recommendations[0].task.to_dict())
        body = {"scope_ref": str(approval.reference), "location_sha256": support.hashlib.sha256(b"/synthetic/work").hexdigest(),
                "connector_task_ref": started["connector_task_ref"], "selection_request": proposal}
        response = ConnectorTests.api(self, value, "conditional-select", body)
        self.assertEqual(response.status_code, 400)
        self.assertIn("unconfigured", response.json()["error"])
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()):
            response = ConnectorTests.api(self, value, "conditional-select", body)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["selection"]["model"], "fixture/cheap")
        self.assertFalse(response.json()["execution_authorized"])
        event = ConnectorTests.event(self, started, kind="http_status", http_status=500)
        response = ConnectorTests.api(self, value, "observation", event)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(selection.status(self.request(), approval.reference)["selection_status"], "paused")
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")

    def test_false_admission_flag_and_expired_assessment_cannot_reserve(self):
        approval = self.active()
        class MissingCap(ControlledAdmissionVerifier):
            def verify(self, request):
                result = super().verify(request).to_dict()
                result["provider_cap_enforced"] = False
                return AdmissionAssessment(**result)
        with override_settings(TARKADO_ADMISSION_VERIFIER=MissingCap()):
            with self.assertRaisesMessage(support.ValidationError, "provider cap"):
                self.choose(approval)
        class Expired(ControlledAdmissionVerifier):
            def verify(self, request):
                result = super().verify(request).to_dict()
                result.update(verified_at=(timezone.now() - timedelta(hours=2)).isoformat(), valid_until=(timezone.now() - timedelta(hours=1)).isoformat())
                return AdmissionAssessment(**result)
        with override_settings(TARKADO_ADMISSION_VERIFIER=Expired()):
            with self.assertRaisesMessage(support.ValidationError, "expired"):
                self.choose(approval)
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["selected_tasks"], 0)

    def test_selection_journal_modified_route_refused_even_with_rehashed_events(self):
        approval = self.active()
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()):
            self.choose(approval)
        runtime = ScopedSelectionRuntime.objects.get()
        runtime.journal["events"][-1]["payload"]["model"] = "fixture/premium"
        event = runtime.journal["events"][-1]
        event["sha256"] = support.hashlib.sha256(json.dumps({key: value for key, value in event.items() if key != "sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        runtime.save()
        with self.assertRaisesMessage(support.ValidationError, "inconsistently bound"):
            selection.accounting(ScopedSelectionRuntime.objects.get())
        self.assertEqual(ScopedSelectionRuntime.objects.get().journal["events"][-1]["payload"]["model"], "fixture/premium")

    def test_new_negative_feedback_stops_selection_and_claim_without_losing_costs(self):
        approval = self.active()
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()):
            self.choose(approval)
            task = support.recommend_task(self.junior, self.source(3))
            support.record_response(self.junior, task.reference, "reject", task.revision)
            result = self.choose(approval, 2)
            self.assertFalse(result["new_reservation"])
            with self.assertRaisesMessage(support.ValidationError, "inactive/stale"):
                selection.claim(current_member(self.junior), approval.reference, "synthetic-selection-1")
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")

    def test_concurrent_scope_change_during_verifier_cannot_leave_reservation(self):
        approval = self.active()
        class Revoking(ControlledAdmissionVerifier):
            def verify(self, request):
                result = super().verify(request)
                support.PilotAuthorization.objects.filter(pk=approval.pk).update(revoked_at=timezone.now())
                return result
        with override_settings(TARKADO_ADMISSION_VERIFIER=Revoking()):
            with self.assertRaises(support.ValidationError):
                self.choose(approval)
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["selected_tasks"], 0)

    def test_browser_controls_preview_exact_scope_then_require_fresh_mfa(self):
        approval = self.active()
        path = f"/pilots/{approval.reference}/selection/"
        preview = self.client.post(path, {"preview": "scope", "action": "pause", "expected_revision": 1, "reason": "Pause exact conditional pilot"})
        self.assertContains(preview, "Confirm conditional control")
        from test_browser_workflow import BrowserForms
        values = BrowserForms(preview).containing("confirmation_token")["values"]
        device = support.TOTPDevice.objects.get(user=self.owner, confirmed=True)
        code, at = support.device_code(device)
        values.update(confirmation="on", confirm_password=support.PASSWORD, code=code)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = self.client.post(path, values)
        self.assertEqual(response.status_code, 302, response.content)
        self.assertEqual(selection.status(self.request(), approval.reference)["selection_status"], "paused")


class SelectionConcurrencyTests(TransactionTestCase):
    setUp = SelectionTests.setUp
    enroll = SelectionTests.enroll
    request = SelectionTests.request
    sensitive = SelectionTests.sensitive
    source = SelectionTests.source
    evidence = SelectionTests.evidence
    approve = SelectionTests.approve
    scope = SelectionTests.scope
    developer_request = SelectionTests.developer_request
    task = SelectionTests.task
    active = SelectionTests.active
    value = SelectionTests.value
    choose = SelectionTests.choose

    def test_parallel_reservations_cannot_exceed_one_shared_budget(self):
        approval = self.active()
        def choose(number):
            try:
                return self.choose(approval, number, reserve_usd="0.75")
            finally:
                connections.close_all()
        with override_settings(TARKADO_ADMISSION_VERIFIER=ControlledAdmissionVerifier()), ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(choose, (1, 2)))
        self.assertEqual(sum(item["new_reservation"] for item in results), 1)
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.75")

    def test_parallel_one_use_claims_allow_exactly_one_new_claim(self):
        approval = self.active()
        verifier = ControlledAdmissionVerifier()
        def claim():
            try:
                return selection.claim(current_member(self.junior), approval.reference, "synthetic-selection-1")
            finally:
                connections.close_all()
        with override_settings(TARKADO_ADMISSION_VERIFIER=verifier):
            self.choose(approval)
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: claim(), (1, 2)))
        self.assertEqual(sum(result["new_claim"] for result in results), 1)
