"""Joined privacy, monitoring and versioned handoff on isolated synthetic stores."""

import copy
from datetime import timedelta

import test_company as support
import test_delivery as d
import test_connectors as c
from django.db import connections
from django.test import TestCase, override_settings
from django.utils import timezone

from engine.company import operations, policy_handoff, delivery, selection
from engine.company.models import DeliveryBinding, OperationalControl, ScopedSelectionRuntime
from engine.company.tasks import record_response, record_execution, record_result
from engine.feedback import _fingerprint


def setUpModule(): support.setUpModule()
def tearDownModule(): connections.close_all()


class DeliveryOperationsTests(TestCase):
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

    def test_monitor_retains_junior_unknown_obligations_and_no_synthetic_success(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, failed=True)
        monitored = operations.monitor(self.request())
        self.assertTrue(any(row["developer"] == "junior" and row["signal"] == "unknown_provider_obligation" for row in monitored["alerts"]))
        self.assertFalse(monitored["automatic_expansion"])
        self.assertEqual(monitored["deliveries"][0]["unknown_attempts"], 1)
        page = self.client.get("/monitoring/")
        self.assertContains(page, "unknown")
        self.assertNotContains(page, self.bound["task_token"])

    def test_privacy_pause_stops_new_metadata_and_paid_attempts_but_preserves_settlement(self):
        self.binding()
        request = self.physical()
        self.sensitive(operations.privacy_control, "pause_collection", "Pause approved collection without deleting records", 0)
        with self.assertRaises(support.PermissionDenied): self.physical()
        self.hooks.settle(request, self.provider.send(request))
        delivery.close_delivery(self.gateway_token, self.bound["binding_ref"])
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["spent_usd"], "0.002")
        self.assertEqual(len(DeliveryBinding.objects.get().journal), 4)
        self.assertTrue(operations.privacy_state(self.gateway.company)["collection_paused"])

    def test_retention_reminder_cannot_delete_expire_or_rewrite_journals(self):
        self.binding()
        before = copy.deepcopy(DeliveryBinding.objects.get().data)
        state = self.sensitive(operations.privacy_control, "review_retention", "Owner must decide deletion separately", 0, timezone.now() + timedelta(days=1))
        self.assertFalse(state["automatic_deletion_supported"])
        self.assertFalse(state["raw_content_supported"])
        self.assertEqual(state["retention_policy"], "manual")
        self.assertEqual(DeliveryBinding.objects.get().data, before)
        with self.assertRaises(support.ValidationError): self.sensitive(operations.privacy_control, "delete", "Not authorized", 1)
        self.assertEqual(OperationalControl.objects.get().journal[-1]["action"], "review_retention")

    def test_stale_privacy_change_and_nonadmin_control_refused(self):
        self.binding()
        self.sensitive(operations.privacy_control, "pause_collection", "Pause current scope", 0)
        with self.assertRaises(support.ValidationError): self.sensitive(operations.privacy_control, "resume_collection", "Stale resume", 0)
        junior = support.LocalClient(); junior.force_login(self.junior)
        self.assertEqual(junior.get("/privacy/").status_code, 403)
        self.assertEqual(junior.get("/monitoring/").status_code, 403)

    def test_handoff_is_versioned_exact_private_and_not_portable_live_authority(self):
        self.binding()
        exported = policy_handoff.build(self.request(), self.approval.reference)
        self.assertEqual(exported["schema_version"], 1)
        self.assertEqual(exported["policy_sha256"], self.policy.fingerprint())
        self.assertFalse(exported["execution_credential"])
        self.assertFalse(exported["portable_live_approval"])
        self.assertFalse(exported["routing_enabled"])
        self.assertTrue(exported["unsupported"])
        self.assertEqual([row["model_id"] for row in exported["model_bindings"]], [model.model_id for model in self.policy.models])
        response = self.client.get(f"/pilots/{self.approval.reference}/handoff/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertNotContains(response, self.gateway_token)
        self.assertNotContains(response, self.bound["task_token"])

    def test_handoff_cannot_be_rehashed_to_add_execution_credentials_or_change_contract(self):
        self.binding()
        value = policy_handoff.build(self.request(), self.approval.reference)
        changed = copy.deepcopy(value)
        changed["routing_enabled"] = True
        changed["sha256"] = _fingerprint({k: v for k, v in changed.items() if k != "sha256"})
        with self.assertRaises(support.ValidationError): policy_handoff.validate(changed)
        changed = copy.deepcopy(value); changed["compatibility"]["model_switching"] = True
        changed["sha256"] = _fingerprint({k: v for k, v in changed.items() if k != "sha256"})
        with self.assertRaises(support.ValidationError): policy_handoff.validate(changed)

    def test_unknown_cost_cannot_be_refunded_with_an_unverified_reference(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, failed=True)
        attempt = next(iter(self.state()["attempts"]))
        with self.assertRaisesMessage(support.ValidationError, "unconfigured"):
            delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], attempt, "0", None, "cancelled", None, "guess-zero-cost")
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")

    def test_unknown_cost_cannot_be_bypassed_by_resume(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, failed=True)
        revision = selection._state(ScopedSelectionRuntime.objects.get())["revision"]
        with self.assertRaisesMessage(support.ValidationError, "forbid unchanged resume"):
            self.sensitive(selection.control, self.approval.reference, "resume", revision, "No refund or unobserved continuation")
        self.assertEqual(selection._state(ScopedSelectionRuntime.objects.get())["status"], "paused")

    def test_late_response_cannot_be_claimed_as_pre_execution_acceptance(self):
        self.binding()
        self.physical()
        with self.assertRaisesMessage(support.ValidationError, "precede paid"):
            record_response(self.junior, self.link.task.reference, "accept", self.link.task.revision)

    def test_known_usage_and_explicit_owner_close_link_to_reported_result_without_fabrication(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, self.provider.send(request))
        event = c.ConnectorTests.event(self, {"connector_task_ref": str(self.link.reference)}, kind="close")
        closed = self.api(self.connector_token, "observation", event)
        self.assertEqual(closed.status_code, 200, closed.content)
        task = record_execution(self.junior, self.link.task.reference, "fixture/cheap", self.link.task.revision)
        recorded = record_result(self.junior, task.reference, c.ConnectorTests.result_value(self, desired_result=True, evidence_ref="controlled-human-task-review"), task.revision)
        self.assertEqual(recorded.revision, 3)
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["spent_usd"], "0.002")
        page = self.client.get(f"/tasks/{task.reference}/")
        self.assertContains(page, "Supported gateway request/usage accounting")
