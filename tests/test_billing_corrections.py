"""Known-cost corrections against isolated independent evidence, never real invoices/providers."""

import copy
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import test_company as support
import test_delivery as d
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from engine.company import billing_corrections as costs, delivery, delivery_views, delivery_evidence, operations, selection
from engine.company.billing_gate import BillingAssessment, BillingVerifier
from engine.company.models import Company, DeliveryBinding, GatewayCredential, Membership, ScopedSelectionRuntime, SecurityEvent
from engine.company.services import current_member
from engine.company.tasks import task_ledger
from engine.feedback import _fingerprint, _timestamp


def setUpModule(): support.setUpModule()
def tearDownModule(): connections.close_all()


class EvidenceLedger(BillingVerifier):
    """A test-only independently supplied receipt; submitted amounts cannot create one."""
    def __init__(self):
        self.receipts = {}
        self.calls = []

    def record(self, binding, value, amount):
        row = delivery.state(binding)["attempts"][value["attempt_id"]]
        receipt = {"company_id": binding.data["company_id"], "deployment_id": binding.data["deployment_id"],
            "binding_ref": str(binding.reference), "task_ref": str(binding.connector_task.task.reference),
            "request_id": row["request_id"], "attempt_id": row["attempt_id"], "owner": binding.data["owner"],
            "supersedes_sha256": row["cost_head_sha256"], "cost_usd": amount, "revision": "independent-receipt-v1"}
        self.receipts[(str(binding.reference), row["attempt_id"], value["evidence_ref"])] = receipt

    def verify(self, request):
        self.calls.append(copy.deepcopy(request))
        submitted = request["settlement"]
        receipt = self.receipts.get((request["binding_ref"], request["attempt_id"], submitted["evidence_ref"]))
        if receipt is None or any(request.get(key) != receipt[key] for key in (
            "company_id", "deployment_id", "binding_ref", "task_ref", "request_id", "attempt_id", "owner")) or any(
                submitted[key] != receipt[key] for key in ("cost_usd", "supersedes_sha256")):
            raise support.ValidationError("Independent receipt does not verify this exact amount/ownership/history.")
        now = timezone.now()
        return BillingAssessment(_fingerprint(request), "test-only-checked-invoice", "test-only-independent-ledger",
            now.isoformat(), (now + timedelta(minutes=5)).isoformat(), _fingerprint(receipt))


class CorrectionFixture:
    setUp = d.DeliveryTests.setUp
    enroll = d.DeliveryTests.enroll
    request = d.DeliveryTests.request
    sensitive = d.DeliveryTests.sensitive
    source = d.DeliveryTests.source
    evidence = d.DeliveryTests.evidence
    approve = d.DeliveryTests.approve
    scope = d.DeliveryTests.scope
    developer_request = d.DeliveryTests.developer_request
    task = d.DeliveryTests.task
    active = d.DeliveryTests.active
    value = d.DeliveryTests.value
    pair = d.DeliveryTests.pair
    api = d.DeliveryTests.api
    task_source = d.DeliveryTests.task_source
    binding = d.DeliveryTests.binding
    body = d.DeliveryTests.body
    physical = d.DeliveryTests.physical
    state = d.DeliveryTests.state

    def known(self, close=False):
        self.binding()
        physical = self.physical()
        self.hooks.settle(physical, self.provider.send(physical))
        if close: delivery.close_delivery(self.gateway_token, self.bound["binding_ref"])
        self.ledger = EvidenceLedger()
        setting = override_settings(TARKADO_BILLING_VERIFIER=self.ledger)
        setting.enable(); self.addCleanup(setting.disable)
        return DeliveryBinding.objects.get()

    def change(self, amount="0.003", **updates):
        binding = DeliveryBinding.objects.get()
        state = delivery.state(binding)
        row = next(iter(state["attempts"].values()))
        return {"correction_id": str(uuid.uuid4()), "attempt_id": row["attempt_id"], "request_id": row["request_id"],
            "expected_revision": state["revision"], "supersedes_sha256": row["cost_head_sha256"], "cost_usd": amount,
            "evidence_ref": "test-only-invoice-reference", **updates}

    def review(self, value):
        return costs.review_machine(self.gateway_token, self.bound["binding_ref"], **value)

    def correct(self, value, review=None):
        review = review or self.review(value)
        return costs.correct_machine(self.gateway_token, self.bound["binding_ref"], review["correction"]["billing_assessment"], **value)

    def approved_change(self, amount):
        value = self.change(amount)
        self.ledger.record(DeliveryBinding.objects.get(), value, amount)
        return value, self.review(value)

    def money(self): return selection.accounting(ScopedSelectionRuntime.objects.get())

    def second_binding(self):
        started = self.api(self.connector_token, "start", self.task_source(required_tools=[], session_ref=delivery.connectors.digest("second-test-session"))).json()
        link = delivery.connectors.ConnectorTask.objects.get(reference=started["connector_task_ref"])
        member = current_member(self.junior)
        proposal = self.value(number=2, task=task_ledger(link.task).recommendations[0].task.to_dict())
        selection.select(member, self.approval.reference, proposal, connector_link=link)
        selection.claim(member, self.approval.reference, proposal["selection_id"])
        bound = delivery.bind(self.link.credential, member, link, str(self.approval.reference), proposal["selection_id"], str(self.gateway.reference))
        return DeliveryBinding.objects.get(reference=bound["binding_ref"]), bound


class BillingCorrectionTests(CorrectionFixture, TestCase):
    def test_increase_and_decrease_append_exact_history_and_preserve_original(self):
        binding = self.known(close=True)
        old = copy.deepcopy(binding.journal)
        selection_old = copy.deepcopy(ScopedSelectionRuntime.objects.get().journal["events"])
        for amount in ("0.006", "0.001"):
            value, review = self.approved_change(amount)
            result = self.correct(value, review)
            self.assertTrue(result["new_correction"])
            self.assertEqual(result["delivery"]["known_cost_usd"], amount)
            self.assertEqual(self.money()["spent_usd"], amount)
        current = self.state()
        row = next(iter(current["attempts"].values()))
        self.assertEqual(row["original_settlement"]["payload"]["cost_usd"], "0.002")
        self.assertEqual(row["cost_revision"], 2)
        self.assertEqual(row["outcome"], "completed")
        self.assertEqual(len(row["corrections"]), 2)
        self.assertEqual(DeliveryBinding.objects.get().journal[:len(old)], old)
        self.assertEqual(ScopedSelectionRuntime.objects.get().journal["events"][:len(selection_old)], selection_old)
        self.assertEqual(self.money()["selected_tasks"], 1)
        self.assertEqual(self.money()["claimed_tasks"], 1)
        self.assertEqual(self.money()["remaining_task_slots"], 2)

    def test_duplicate_retry_after_other_corrections_is_receipt_not_new_charge(self):
        self.known(close=True)
        value, review = self.approved_change("0.006")
        self.correct(value, review)
        second, later = self.approved_change("0.001")
        self.correct(second, later)
        count = len(DeliveryBinding.objects.get().journal)
        with override_settings(TARKADO_BILLING_VERIFIER=None):
            retry = self.correct(value, review)
        self.assertTrue(retry["historical_replay"])
        self.assertFalse(retry["new_correction"])
        self.assertEqual(retry["correction"]["cost_usd"], "0.006")
        self.assertEqual(retry["delivery"]["known_cost_usd"], "0.001")
        self.assertEqual(len(DeliveryBinding.objects.get().journal), count)
        self.assertEqual(self.money()["spent_usd"], "0.001")

    def test_changed_duplicate_id_and_actor_refused(self):
        self.known()
        value, review = self.approved_change("0.006")
        self.correct(value, review)
        with self.assertRaisesMessage(support.ValidationError, "retry changed"):
            self.correct({**value, "cost_usd": "0.005"}, review)
        with self.assertRaisesMessage(support.ValidationError, "retry changed"):
            costs.review_human(self.request(), self.bound["binding_ref"], **value)

    def test_stale_global_revision_and_branched_head_refused(self):
        self.known()
        first, review = self.approved_change("0.003")
        stale = self.change("0.001")
        self.correct(first, review)
        with self.assertRaisesMessage(support.ValidationError, "stale or branched"): self.review(stale)
        stale["expected_revision"] = self.state()["revision"]
        with self.assertRaisesMessage(support.ValidationError, "stale or branched"): self.review(stale)
        self.assertEqual(self.state()["known_cost_usd"], "0.003")

    def test_submitted_amount_reference_and_checkbox_are_not_billing_evidence(self):
        binding = self.known()
        value = self.change("0.001")
        with self.assertRaisesMessage(support.ValidationError, "Independent receipt"): self.review(value)
        self.ledger.record(binding, value, "0.009")
        with self.assertRaisesMessage(support.ValidationError, "Independent receipt"): self.review(value)
        with self.assertRaises(support.ValidationError): self.review({**value, "verified": True})
        self.assertEqual(self.state()["known_cost_usd"], "0.002")

    def test_unconfigured_and_reference_only_verifiers_cannot_correct(self):
        self.known()
        value = self.change()
        for verifier in (None, d.ControlledBillingVerifier()):
            with override_settings(TARKADO_BILLING_VERIFIER=verifier), self.assertRaises(support.ValidationError): self.review(value)
        self.assertEqual(len(DeliveryBinding.objects.get().journal), 3)

    def test_changed_independent_evidence_content_under_same_reference_refuses_confirmation(self):
        self.known()
        value, review = self.approved_change("0.003")
        next(iter(self.ledger.receipts.values()))["revision"] = "independent-receipt-v2"
        with self.assertRaisesMessage(support.ValidationError, "changed or expired"): self.correct(value, review)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")

    def test_expired_wrong_bound_or_untyped_assessment_refused(self):
        self.known()
        value, review = self.approved_change("0.003")
        proof = review["correction"]["billing_assessment"]
        for changed in ({**proof, "request_sha256": "0" * 64}, {**proof, "valid_until": (timezone.now() - timedelta(seconds=1)).isoformat()}, {"verified": True}):
            with self.assertRaises(support.ValidationError):
                costs.correct_machine(self.gateway_token, self.bound["binding_ref"], changed, **value)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")

    def test_no_confirmation_proof_cannot_apply_even_when_receipt_exists(self):
        self.known()
        value, _ = self.approved_change("0.003")
        with self.assertRaisesMessage(support.ValidationError, "Review and confirm"):
            costs.correct_machine(self.gateway_token, self.bound["binding_ref"], None, **value)

    def test_wrong_task_request_attempt_and_gateway_scope_refused(self):
        self.known()
        value = self.change()
        for key in ("attempt_id", "request_id"):
            with self.assertRaisesMessage(support.ValidationError, "exact owned"): self.review({**value, key: str(uuid.uuid4())})
        with self.assertRaises(support.PermissionDenied): costs.review_machine(self.gateway_token, str(uuid.uuid4()), **value)
        self.gateway.scope["user_mapping"] = {"junior": "different-authenticated-user"}
        self.gateway.save()
        with self.assertRaises(support.PermissionDenied): self.review(value)

    def test_verifier_independently_refuses_wrong_task_owner_receipt(self):
        self.known()
        value, _ = self.approved_change("0.003")
        next(iter(self.ledger.receipts.values()))["owner"] = {"developer_id": "someone-else"}
        with self.assertRaisesMessage(support.ValidationError, "ownership/history"): self.review(value)

    def test_closed_withdrawn_tasks_allow_late_corrections_without_reactivation(self):
        self.known(close=True)
        runtime = ScopedSelectionRuntime.objects.get()
        self.sensitive(selection.control, self.approval.reference, "rollback", selection._state(runtime)["revision"], "Withdraw test pilot")
        for amount in ("1.30", "0.0001"):
            value, review = self.approved_change(amount)
            self.correct(value, review)
            self.assertEqual(selection._state(ScopedSelectionRuntime.objects.get())["status"], "rolled_back")
            self.assertTrue(self.state()["closed"])
        self.assertEqual(self.money()["spent_usd"], "0.0001")
        self.assertEqual(self.money()["remaining_usd"], "0.9999")
        self.assertEqual(self.money()["remaining_task_slots"], 2)
        self.assertFalse(selection.claim(current_member(self.junior), self.approval.reference, "synthetic-selection-1")["new_claim"])
        with self.assertRaises(support.ValidationError): self.physical()

    def test_increase_exposes_complete_negative_totals_then_decrease_keeps_pause_and_overrun(self):
        self.known(close=True)
        value, review = self.approved_change("1.30")
        self.assertEqual(review["proposed_pilot_accounting"]["remaining_usd"], "-0.30")
        self.correct(value, review)
        self.assertEqual(self.state()["remaining_task_usd"], "-1.20")
        self.assertEqual(self.money()["remaining_usd"], "-0.30")
        value, review = self.approved_change("0.001")
        self.correct(value, review)
        runtime = ScopedSelectionRuntime.objects.get()
        self.assertEqual(selection._state(runtime)["status"], "paused")
        self.assertTrue(delivery.resume_blocked(runtime))
        with self.assertRaises(support.ValidationError):
            self.sensitive(selection.control, self.approval.reference, "resume", selection._state(runtime)["revision"], "Do not erase overrun")
        signals = delivery_evidence.observations(Company.objects.get(), "team")[0]["negative_signals"]
        self.assertIn("provider_cost_overrun", signals)
        self.assertTrue(any(alert["signal"] == "historical_provider_cost_overrun" for alert in operations.monitor(self.request())["alerts"]))

    def test_pending_other_attempt_and_task_reservation_remain_in_complete_totals(self):
        self.known()
        self.physical(kind="title")
        value, review = self.approved_change("0.003")
        self.correct(value, review)
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.assertEqual(self.state()["remaining_task_usd"], "0.057")
        self.assertEqual(self.money()["reserved_usd"], "0.10")
        self.assertEqual(self.money()["spent_usd"], "0")
        self.assertEqual(self.money()["committed_usd"], "0.10")
        self.assertEqual(self.money()["remaining_usd"], "0.90")

    def test_small_decimal_costs_are_never_rounded_away(self):
        self.known(close=True)
        amount = "0.000000000000000000000000000000000001"
        value, review = self.approved_change(amount)
        self.correct(value, review)
        self.assertEqual(self.money()["spent_usd"], "1E-36")
        self.assertEqual(self.money()["remaining_usd"], "0.999999999999999999999999999999999999")
        self.assertEqual(self.state()["remaining_task_usd"], "0.099999999999999999999999999999999999")

    def test_negative_nonfinite_and_float_amounts_refused_without_changing_history(self):
        self.known()
        for amount in ("-0.001", "NaN", "Infinity", 0.001, None):
            with self.assertRaises(support.ValidationError): self.review(self.change(amount))
        self.assertEqual(self.state()["known_cost_usd"], "0.002")

    def test_unknown_reconciliation_preserved_before_later_known_correction(self):
        self.binding()
        physical = self.physical()
        self.hooks.settle(physical, failed=True)
        value = self.change()
        with self.assertRaisesMessage(support.ValidationError, "unknowns use existing"): self.review(value)
        attempt = value["attempt_id"]
        with override_settings(TARKADO_BILLING_VERIFIER=d.ControlledBillingVerifier()):
            delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], attempt, "0.005", None, "failed", None, "test-only-legacy-invoice")
        self.ledger = EvidenceLedger()
        with override_settings(TARKADO_BILLING_VERIFIER=self.ledger):
            value, review = self.approved_change("0.001")
            self.correct(value, review)
        self.assertEqual(next(iter(self.state()["attempts"].values()))["outcome"], "failed")
        signals = delivery_evidence.observations(Company.objects.get(), "team")[0]["negative_signals"]
        self.assertIn("unknown_provider_obligation", signals)
        self.assertIn("provider_failure", signals)

    def test_historical_replay_survives_verifier_expiry_and_changed_current_evidence(self):
        binding = self.known(close=True)
        old_time = binding.journal[-1]["timestamp"]
        value, review = self.approved_change("0.004")
        self.correct(value, review)
        binding.refresh_from_db()
        with override_settings(TARKADO_BILLING_VERIFIER=None):
            self.assertEqual(delivery.state(binding, revision=4)["known_cost_usd"], "0.002")
            self.assertEqual(delivery.state(binding, until=_timestamp(old_time))["known_cost_usd"], "0.002")
            self.assertEqual(delivery.state(binding)["known_cost_usd"], "0.004")
            self.assertEqual(self.money()["spent_usd"], "0.004")

    def test_rehashed_branched_or_wrong_evidence_history_is_refused(self):
        self.known()
        value, review = self.approved_change("0.003")
        self.correct(value, review)
        for change in ({"previous_cost_usd": "0"}, {"request_id": str(uuid.uuid4())}, {"cost_usd": "0.004"}, {"cost_revision": 9}):
            binding = DeliveryBinding.objects.get()
            binding.journal = copy.deepcopy(binding.journal)
            event = binding.journal[-1]
            event["payload"].update(change)
            event["sha256"] = _fingerprint({key: item for key, item in event.items() if key != "sha256"})
            with self.assertRaises(support.ValidationError): delivery.state(binding)

    def test_current_gateway_revocation_blocks_correction_but_current_admin_can_review_late(self):
        self.known(close=True)
        value, _ = self.approved_change("0.003")
        self.gateway.revoked_at = timezone.now(); self.gateway.save()
        with self.assertRaises(support.PermissionDenied): self.review(value)
        review = costs.review_human(self.request(), self.bound["binding_ref"], **value)
        self.sensitive(costs.correct_human, self.bound["binding_ref"], review["correction"]["billing_assessment"], **value)
        event = DeliveryBinding.objects.get().journal[-1]
        self.assertEqual(event["payload"]["actor"]["developer_id"], "owner")
        self.assertEqual(event["payload"]["actor"]["role"], "admin")

    def test_privacy_pause_does_not_reactivate_or_block_late_cost_accounting(self):
        self.known(close=True)
        self.sensitive(operations.privacy_control, "pause_collection", "Preserve accounting only", 0)
        value, review = self.approved_change("0.001")
        self.correct(value, review)
        self.assertTrue(operations.privacy_state(Company.objects.get())["collection_paused"])
        self.assertEqual(self.money()["spent_usd"], "0.001")
        with self.assertRaises(support.PermissionDenied): self.physical()

    def test_machine_api_enforces_current_identity_metadata_and_review_confirmation(self):
        self.known()
        value, review = self.approved_change("0.003")
        client = support.LocalClient()
        def post(token, data, **headers):
            return client.post("/api/delivery/v1/correct-cost/", json.dumps(data), content_type="application/json", HTTP_AUTHORIZATION="Bearer " + token, **headers)
        body = {"binding_ref": self.bound["binding_ref"], "expected_assessment": review["correction"]["billing_assessment"], **value}
        self.assertEqual(post(self.connector_token, body).status_code, 403)
        self.assertEqual(post(self.gateway_token, {**body, "messages": ["private"]}).status_code, 400)
        self.assertEqual(post(self.gateway_token, body, HTTP_ORIGIN="https://untrusted.example").status_code, 403)
        self.assertEqual(post(self.gateway_token, body).status_code, 200)
        self.assertEqual(post(self.gateway_token, body).json()["new_correction"], False)

    def preview_browser(self, value):
        path = f"/delivery/{self.bound['binding_ref']}/correct-cost/"
        data = {**value, "preview": "scope"}
        response = self.client.post(path, data)
        self.assertContains(response, "Confirm independently verified cost correction")
        token = re.search(r'name="confirmation_token" value="([^"]+)"', response.content.decode()).group(1)
        return path, {**data, "preview": "confirm", "confirmation_token": token, "confirmation": "on"}

    def browser_confirm(self, path, data):
        device = support.TOTPDevice.objects.get(user=self.owner, confirmed=True)
        code, at = support.device_code(device)
        with patch("time.time", return_value=at):
            return self.client.post(path, {**data, "confirm_password": support.PASSWORD, "code": code})

    def test_guided_browser_review_exact_confirmation_and_readable_history(self):
        self.known(close=True)
        value, _ = self.approved_change("0.003")
        path, confirmed = self.preview_browser(value)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")
        response = self.browser_confirm(path, confirmed)
        self.assertEqual(response.status_code, 302, response.content)
        self.assertEqual(self.money()["spent_usd"], "0.003")
        page = self.client.get(f"/tasks/{self.link.task.reference}/")
        self.assertContains(page, "Verified cost correction history")
        self.assertContains(page, "USD 0.002 → 0.003")
        self.assertContains(page, "historical admin")
        self.assertContains(page, "test-only-independent-ledger")

    def test_browser_refuses_direct_forged_changed_and_stale_confirmation(self):
        self.known()
        value, _ = self.approved_change("0.003")
        path, confirmed = self.preview_browser(value)
        for updates in ({"confirmation_token": "forged"}, {"cost_usd": "0.001"}, {"confirmation": ""}):
            response = self.browser_confirm(path, {**confirmed, **updates})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.state()["known_cost_usd"], "0.002")
        other, review = self.approved_change("0.004")
        self.correct(other, review)
        self.assertContains(self.browser_confirm(path, confirmed), "stale or branched")
        self.assertEqual(self.state()["known_cost_usd"], "0.004")

    def test_browser_changed_evidence_and_nonadmin_or_changed_authority_refused(self):
        self.known()
        value, _ = self.approved_change("0.003")
        path, confirmed = self.preview_browser(value)
        next(iter(self.ledger.receipts.values()))["revision"] = "changed-independent-invoice"
        self.assertContains(self.browser_confirm(path, confirmed), "changed or expired")
        for user in (self.junior, self.senior):
            client = support.LocalClient(); client.force_login(user)
            self.assertEqual(client.get(path).status_code, 403)
        Membership.objects.filter(user=self.owner).update(can_manage_company=False)
        self.assertEqual(self.client.post(path, confirmed).status_code, 403)

    def test_privacy_correction_retains_only_metadata_and_refuses_secrets(self):
        self.known(close=True)
        value, review = self.approved_change("0.003")
        self.correct(value, review)
        serialized = json.dumps({"bindings": list(DeliveryBinding.objects.values("data", "journal")),
            "events": list(SecurityEvent.objects.values("details")), "summary": operations.delivery_summary(DeliveryBinding.objects.get())})
        for secret in (self.gateway_token, self.connector_token, self.bound["task_token"], "Synthetic private prompt", "Synthetic private output"):
            self.assertNotIn(secret, serialized)
        with self.assertRaises(support.PrivacyError): self.review(self.change(evidence_ref="sk-proj-" + "z" * 80))
        self.assertNotIn("invoice_body", serialized)

    def test_complete_multiple_task_totals_and_historical_admission_do_not_replay_at_new_prices(self):
        binding = self.known(close=True)
        second, bound = self.second_binding()
        request_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        delivery.begin_request(self.gateway_token, bound["task_token"], bound["binding_ref"], bound["session_ref"], "employee-junior", request_id, "primary", 1000, False)
        delivery.admit_attempt(self.gateway_token, bound["task_token"], bound["binding_ref"], bound["session_ref"], request_id, attempt_id, "fixture-provider-cheap", 1000, False)
        state = delivery.state(binding)
        row = next(iter(state["attempts"].values()))
        value = {"correction_id": str(uuid.uuid4()), "attempt_id": row["attempt_id"], "request_id": row["request_id"],
            "expected_revision": state["revision"], "supersedes_sha256": row["cost_head_sha256"], "cost_usd": "1.30", "evidence_ref": "test-only-overrun-invoice"}
        self.ledger.record(binding, value, "1.30")
        review = self.review(value)
        self.assertEqual(review["proposed_pilot_accounting"]["spent_usd"], "1.30")
        self.assertEqual(review["proposed_pilot_accounting"]["reserved_usd"], "0.10")
        self.assertEqual(review["proposed_pilot_accounting"]["committed_usd"], "1.40")
        self.assertEqual(review["proposed_pilot_accounting"]["remaining_usd"], "-0.40")
        self.correct(value, review)
        totals = self.money()
        self.assertEqual(totals["spent_usd"], "1.30")
        self.assertEqual(totals["reserved_usd"], "0.10")
        self.assertEqual(totals["committed_usd"], "1.40")
        self.assertEqual(totals["remaining_usd"], "-0.40")
        self.assertEqual(totals["selected_tasks"], 2)
        self.assertEqual(totals["claimed_tasks"], 2)
        self.assertEqual(totals["remaining_task_slots"], 1)
        second.refresh_from_db()
        self.assertEqual(delivery.state(second)["unknown_attempts"], 1)

    def test_cost_from_another_real_task_attempt_cannot_attach_to_original_binding(self):
        binding = self.known(close=True)
        second, bound = self.second_binding()
        request_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        delivery.begin_request(self.gateway_token, bound["task_token"], bound["binding_ref"], bound["session_ref"], "employee-junior", request_id, "primary", 1000, False)
        delivery.admit_attempt(self.gateway_token, bound["task_token"], bound["binding_ref"], bound["session_ref"], request_id, attempt_id, "fixture-provider-cheap", 1000, False)
        value = {"correction_id": str(uuid.uuid4()), "attempt_id": attempt_id, "request_id": request_id,
            "expected_revision": delivery.state(binding)["revision"], "supersedes_sha256": binding.journal[-1]["sha256"], "cost_usd": "0.001", "evidence_ref": "test-only-misowned-cost"}
        with self.assertRaisesMessage(support.ValidationError, "exact owned"): self.review(value)
        self.assertEqual(delivery.state(binding)["known_cost_usd"], "0.002")
        second.refresh_from_db()
        self.assertEqual(delivery.state(second)["unknown_attempts"], 1)

    def test_atomic_failure_of_pilot_append_does_not_leave_an_unlinked_cost_revision(self):
        self.known(close=True)
        value, review = self.approved_change("0.003")
        original = copy.deepcopy(DeliveryBinding.objects.get().journal)
        with patch("engine.company.selection.delivery_event", side_effect=support.ValidationError("Controlled accounting failure")), self.assertRaises(support.ValidationError):
            self.correct(value, review)
        self.assertEqual(DeliveryBinding.objects.get().journal, original)
        self.assertEqual(self.money()["spent_usd"], "0.002")

    def test_changed_authority_during_verification_refuses_and_rolls_back(self):
        self.known()
        value, review = self.approved_change("0.003")
        verify = self.ledger.verify
        def changed(request):
            result = verify(request)
            GatewayCredential.objects.filter(pk=self.gateway.pk).update(revoked_at=timezone.now())
            return result
        with patch.object(self.ledger, "verify", side_effect=changed), self.assertRaises(support.PermissionDenied): self.correct(value, review)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")

    def test_same_amount_new_verified_revision_never_double_charges(self):
        self.known(close=True)
        for _ in range(2):
            value, review = self.approved_change("0.003")
            self.correct(value, review)
        self.assertEqual(next(iter(self.state()["attempts"].values()))["cost_revision"], 2)
        self.assertEqual(self.money()["spent_usd"], "0.003")

    def test_legacy_selection_settlement_replays_original_cost_after_new_correction(self):
        self.known(close=True)
        runtime = ScopedSelectionRuntime.objects.get()
        final = runtime.journal["events"][-1]
        for key in ("delivery_revision", "delivery_sha256"): final["payload"].pop(key)
        final["sha256"] = _fingerprint({key: value for key, value in final.items() if key != "sha256"})
        runtime.save(update_fields=("journal",))
        value, review = self.approved_change("0.003")
        self.correct(value, review)
        self.assertEqual(self.money()["spent_usd"], "0.003")

    def test_cumulative_task_overrun_is_retained_after_decreasing_costs(self):
        self.known()
        # Spend six known low-cost requests so the eventual revised sum can
        # exceed the task cap without any single physical attempt exceeding its reserve.
        for _ in range(5):
            physical = self.physical()
            self.hooks.settle(physical, self.provider.send(physical))
        delivery.close_delivery(self.gateway_token, self.bound["binding_ref"])
        for row in list(self.state()["attempts"].values())[:3]:
            state = self.state()
            value = {"correction_id": str(uuid.uuid4()), "attempt_id": row["attempt_id"], "request_id": row["request_id"],
                "expected_revision": state["revision"], "supersedes_sha256": state["attempts"][row["attempt_id"]]["cost_head_sha256"],
                "cost_usd": "0.039", "evidence_ref": "test-only-cumulative-overrun"}
            self.ledger.record(DeliveryBinding.objects.get(), value, "0.039")
            self.correct(value)
        self.assertEqual(self.state()["known_cost_usd"], "0.123")
        value, review = self.approved_change("0.001")
        self.correct(value, review)
        self.assertEqual(self.state()["known_cost_usd"], "0.085")
        self.assertTrue(delivery.resume_blocked(ScopedSelectionRuntime.objects.get()))
        self.assertIn("task_budget_overrun", delivery_evidence.observations(Company.objects.get(), "team")[0]["negative_signals"])

    def test_revoked_pilot_and_renewed_scoped_gateway_do_not_grant_another_claim(self):
        self.known(close=True)
        runtime = ScopedSelectionRuntime.objects.get()
        self.sensitive(selection.control, self.approval.reference, "revoke", selection._state(runtime)["revision"], "Revoke controlled scope")
        self.gateway.revoked_at = timezone.now(); self.gateway.save()
        gateway, token = self.sensitive(delivery.issue_gateway, "controlled-gateway", "synthetic-repository", {"junior": "employee-junior"}, timezone.now() + timedelta(hours=1), Company.objects.get().revision)
        state = self.state(); row = next(iter(state["attempts"].values()))
        value = {"correction_id": str(uuid.uuid4()), "attempt_id": row["attempt_id"], "request_id": row["request_id"],
            "expected_revision": state["revision"], "supersedes_sha256": row["cost_head_sha256"], "cost_usd": "0.001", "evidence_ref": "test-only-renewed-invoice"}
        self.ledger.record(DeliveryBinding.objects.get(), value, "0.001")
        review = costs.review_machine(token, self.bound["binding_ref"], **value)
        costs.correct_machine(token, self.bound["binding_ref"], review["correction"]["billing_assessment"], **value)
        self.assertEqual(selection._state(ScopedSelectionRuntime.objects.get())["status"], "revoked")
        self.assertEqual(self.money()["spent_usd"], "0.001")
        self.assertEqual(self.money()["claimed_tasks"], 1)
        self.assertEqual(DeliveryBinding.objects.get().journal[-1]["gateway_ref"], str(gateway.reference))

    def test_zero_cost_correction_cannot_restore_consumed_claim_or_task_slots(self):
        self.known(close=True)
        value, review = self.approved_change("0")
        self.correct(value, review)
        self.assertEqual(self.money()["spent_usd"], "0")
        self.assertEqual(self.money()["remaining_usd"], "1.00")
        self.assertEqual(self.money()["selected_tasks"], 1)
        self.assertEqual(self.money()["claimed_tasks"], 1)
        self.assertEqual(self.money()["remaining_task_slots"], 2)
        with self.assertRaises(support.ValidationError): self.physical()

    def test_changed_pilot_totals_after_review_require_new_confirmation(self):
        self.known(close=True)
        value, review = self.approved_change("0.003")
        self.second_binding()
        with self.assertRaisesMessage(support.ValidationError, "changed or expired"): self.correct(value, review)
        self.assertEqual(delivery.state(DeliveryBinding.objects.get(reference=self.bound["binding_ref"]))["known_cost_usd"], "0.002")

    def test_equal_clock_timestamps_do_not_replace_legacy_historical_settlement(self):
        self.known(close=True)
        runtime = ScopedSelectionRuntime.objects.get()
        final = runtime.journal["events"][-1]
        fixed = _timestamp(final["timestamp"])
        for key in ("delivery_revision", "delivery_sha256"): final["payload"].pop(key)
        final["sha256"] = _fingerprint({key: value for key, value in final.items() if key != "sha256"})
        runtime.save(update_fields=("journal",))
        with patch("django.utils.timezone.now", return_value=fixed):
            value, review = self.approved_change("0.003")
            self.correct(value, review)
        self.assertEqual(self.money()["spent_usd"], "0.003")

    def test_browser_confirmation_requires_fresh_authenticator_not_only_checkbox(self):
        self.known()
        value, _ = self.approved_change("0.003")
        path, confirmed = self.preview_browser(value)
        response = self.client.post(path, {**confirmed, "confirm_password": support.PASSWORD, "code": "not-an-authenticator-code"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")
        self.assertEqual(len(DeliveryBinding.objects.get().journal), 3)


class BillingCorrectionConcurrencyTests(CorrectionFixture, TransactionTestCase):
    def test_concurrent_different_corrections_share_one_head_and_one_budget_update(self):
        binding = self.known(close=True)
        values = [self.change(amount, evidence_ref=f"test-only-invoice-{index}") for index, amount in enumerate(("0.003", "0.001"))]
        reviews = []
        for value in values:
            self.ledger.record(binding, value, value["cost_usd"])
            reviews.append(self.review(value))
        # Both amounts have independently reviewed receipts; each request keeps
        # its own reference rather than trusting whichever amount was submitted.
        def apply(pair):
            value, review = pair
            try:
                try: return self.correct(value, review)
                except support.ValidationError: return None
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(apply, zip(values, reviews)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(DeliveryBinding.objects.get().journal), 5)
        self.assertEqual(self.money()["spent_usd"], self.state()["known_cost_usd"])
        self.assertIn(self.money()["spent_usd"], ("0.003", "0.001"))

    def test_concurrent_duplicate_correction_is_one_revision_and_one_charge(self):
        self.known(close=True)
        value, review = self.approved_change("0.003")
        def apply(_):
            try: return self.correct(value, review)
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(apply, range(2)))
        self.assertEqual(sum(result["new_correction"] for result in results), 1)
        self.assertEqual(self.money()["spent_usd"], "0.003")
        self.assertEqual(next(iter(self.state()["attempts"].values()))["cost_revision"], 1)
