"""Acceptance is preference, not a pilot-staleness trigger or execution permission."""

import copy
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import test_company as support
import test_delivery_review as review_support
import test_delivery as delivery_support
import test_connectors as connector_support
import test_selection as selection_support
from django.db import connections
from django.test import TestCase, override_settings
from django.utils import timezone

from engine.company import authorization, company_learning, delivery, selection
from engine.company.live_authorization import live_guard
from engine.company.models import Company, ConnectorTask, ScopedSelectionRuntime, TaskEvent
from engine.company.services import current_member
from engine.company.tasks import company_ledger, recommend_task, record_execution, record_response, record_result, task_ledger
from engine.learning import LearnedModel
from engine.litellm_delivery import AttemptHooks


def setUpModule():
    support.setUpModule()


def tearDownModule():
    connections.close_all()


class AcceptanceFreshnessTests(review_support.DeliveryFixture, TestCase):
    def approve(self, *args, **kwargs):
        if getattr(self, "short_authority", False):
            kwargs["expires"] = timezone.now() + timedelta(minutes=5)
        return review_support.DeliveryFixture.approve(self, *args, **kwargs)

    def active(self):
        approval = super().active()
        self.publication = self.sensitive(company_learning.change, "team", 0, "Publish controlled reviewed manual suggestions",
            review_ref=approval.review.reference, repositories=["synthetic-repository"])
        return approval

    def accept(self):
        self.link.task.refresh_from_db()
        return self.api(self.connector_token, "feedback", {"connector_task_ref": str(self.link.reference),
            "location_sha256": self.link.credential.scope["location_sha256"], "action": "response",
            "expected_revision": self.link.task.revision, "value": "accept"})

    def test_acceptance_preserves_approved_pilot_and_reaches_controlled_provider(self):
        self.binding()
        approved = copy.deepcopy(self.approval.data)
        reviewed = copy.deepcopy(self.approval.review.data)
        response = self.accept()
        self.assertEqual(response.status_code, 200, response.content)
        current = selection.status(self.request(), self.approval.reference)
        self.assertEqual(current["selection_status"], "active", f"Acceptance changed pilot state: {current['selection_status']}; guard={current['guard']}")
        request = self.physical()
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.hooks.settle(request, self.provider.send(request))
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")
        self.approval.refresh_from_db(); self.approval.review.refresh_from_db()
        self.assertEqual(self.approval.data, approved)
        self.assertEqual(self.approval.review.data, reviewed)
        self.assertEqual(self.readiness.calls[-1].to_dict(), approved["readiness_request"])
        self.link.task.refresh_from_db()
        self.assertEqual(task_ledger(self.link.task).executions, ())
        self.assertEqual(task_ledger(self.link.task).results, ())

    def test_acceptance_before_selection_and_claim_is_not_a_new_task_activity_veto(self):
        approval = self.active()
        with override_settings(TARKADO_ADMISSION_VERIFIER=delivery.NarrowDeliveryAdmissionVerifier(), TARKADO_DELIVERY_VERIFIER=delivery_support.ControlledDeliveryVerifier()):
            credential, token, _ = self.pair(source_kind="team")
            started = self.api(token, "start", self.task_source(required_tools=[])).json()
            link = ConnectorTask.objects.get(reference=started["connector_task_ref"])
            proposal = self.value(task=task_ledger(link.task).recommendations[0].task.to_dict())
            response = self.api(token, "feedback", {"connector_task_ref": str(link.reference), "location_sha256": credential.scope["location_sha256"],
                "action": "response", "expected_revision": link.task.revision, "value": "accept"})
            self.assertEqual(response.status_code, 200, response.content)
            link.task.refresh_from_db()
            chosen = selection.select(current_member(self.junior), approval.reference, proposal, connector_link=link)
            self.assertTrue(chosen["new_reservation"])
            self.assertTrue(selection.claim(current_member(self.junior), approval.reference, proposal["selection_id"])["new_claim"])
            gateway, gateway_token = self.sensitive(delivery.issue_gateway, "controlled-accepted-gateway", "synthetic-repository",
                {"junior": "employee-junior"}, timezone.now() + timedelta(hours=1), Company.objects.get().revision)
            binding = delivery.bind(credential, current_member(self.junior), link, str(approval.reference), proposal["selection_id"], str(gateway.reference))
            hooks, provider = AttemptHooks(delivery_support.LocalBackend(gateway_token)), delivery_support.ControlledProvider()
            body = {"model": "company-cheap", "messages": [{"role": "user", "content": "Controlled accepted task"}], "max_completion_tokens": 1000,
                "metadata": {"tarkado_binding": binding["binding_ref"], "tarkado_task": binding["task_token"], "tarkado_session": binding["session_ref"],
                             "tarkado_request": str(uuid.uuid4()), "tarkado_kind": "primary"}}
            logical = hooks.pre_call(body, SimpleNamespace(user_id="employee-junior")); logical["model"] = "fixture-provider-cheap"
            attempt = hooks.pre_attempt(logical)
            hooks.settle(attempt, provider.send(attempt))
            self.assertEqual(provider.calls, 1)
            self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")

    def stopped_acceptance(self, action):
        self.binding()
        revision = selection._state(ScopedSelectionRuntime.objects.get())["revision"]
        self.sensitive(selection.control, self.approval.reference, action, revision, "Stop controlled scope before feedback")
        before = copy.deepcopy(ScopedSelectionRuntime.objects.get().journal)
        self.assertEqual(self.accept().status_code, 200)
        self.assertEqual(ScopedSelectionRuntime.objects.get().journal, before)
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(self.provider.calls, 0)

    def test_acceptance_cannot_revive_paused_runtime(self):
        self.stopped_acceptance("pause")

    def test_acceptance_cannot_revive_revoked_runtime_or_authority(self):
        self.stopped_acceptance("revoke")

    def test_acceptance_cannot_outlive_authority(self):
        self.binding()
        self.assertEqual(self.accept().status_code, 200)
        past_expiry = timezone.datetime.fromisoformat(self.approval.data["expires_at"]) + timedelta(seconds=1)
        with patch("django.utils.timezone.now", return_value=past_expiry):
            self.assertEqual(live_guard(self.approval, Company.objects.get(), allow_future_recommendations=True)["status"], "blocked")
            with self.assertRaises((support.ValidationError, support.PermissionDenied)): self.physical()
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")

    def test_new_acceptance_under_expired_scope_cannot_revive_it(self):
        self.short_authority = True
        self.binding()
        after_expiry = timezone.datetime.fromisoformat(self.approval.data["expires_at"]) + timedelta(seconds=1)
        # Pairing, provider envelope and machine identity still have hour-long
        # validity. Only the independently approved pilot scope has expired.
        with patch("django.utils.timezone.now", return_value=after_expiry):
            response = self.accept()
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(live_guard(self.approval, Company.objects.get(), allow_future_recommendations=True)["status"], "blocked")
            with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(selection._state(ScopedSelectionRuntime.objects.get())["status"], "paused")
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")

    def test_acceptance_cannot_bypass_another_developers_reject(self):
        self.binding()
        other = recommend_task(self.senior, self.source(30))
        record_response(self.senior, other.reference, "reject", other.revision)
        self.assertEqual(self.accept().status_code, 200)
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(selection.status(self.request(), self.approval.reference)["selection_status"], "paused")
        self.assertEqual(self.provider.calls, 0)

    def test_acceptance_cannot_bypass_junior_failure(self):
        self.binding()
        other = recommend_task(self.junior, self.source(30))
        other = record_execution(self.junior, other.reference, "fixture/cheap", other.revision)
        other = record_result(self.junior, other.reference, {"desired_result": False, "tests_passed": False, "score": None,
            "cost_usd": None, "latency_ms": None, "evidence_ref": "controlled-junior-failure", "supersedes": None}, other.revision)
        self.assertEqual(self.accept().status_code, 200)
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(len(task_ledger(other).results), 1)
        self.assertEqual(task_ledger(other).record_role("result", task_ledger(other).results[0].result_id, self.junior.username), "junior")
        self.assertEqual(self.provider.calls, 0)

    def test_acceptance_does_not_bypass_later_unknown_obligations_or_failures(self):
        self.binding()
        self.assertEqual(self.accept().status_code, 200)
        request = self.physical()
        with self.assertRaises(TimeoutError): self.provider.send(request, fail=True)
        self.hooks.settle(request, failed=True)
        self.assertEqual(self.accept().status_code, 200)
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")

    def test_acceptance_cannot_bypass_observation_gaps(self):
        self.binding()
        self.assertEqual(self.accept().status_code, 200)
        gap = connector_support.ConnectorTests.event(self, {"connector_task_ref": str(self.link.reference)}, kind="gap")
        self.assertEqual(self.api(self.connector_token, "observation", gap).status_code, 200)
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(self.provider.calls, 0)

    def test_acceptance_cannot_bypass_actual_provider_model_mismatch(self):
        self.binding()
        self.assertEqual(self.accept().status_code, 200)
        request = self.physical()
        self.hooks.settle(request, self.provider.send(request, model="different-provider-model"))
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(self.provider.calls, 1)

    def test_acceptance_cannot_bypass_incompatible_or_revoked_models(self):
        self.binding()
        self.assertEqual(self.accept().status_code, 200)
        company = Company.objects.get()
        company.policy["models"][0]["approved"] = False
        company.save(update_fields=("policy",))
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(self.provider.calls, 0)

    def test_acceptance_cannot_bypass_exhausted_task_budget(self):
        self.binding(reserve="0.05")
        self.assertEqual(self.accept().status_code, 200)
        request = self.physical()
        self.provider.send(request)
        with self.assertRaises(support.ValidationError): self.physical(kind="title")
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(len(self.state()["attempts"]), 1)
        self.assertEqual(self.state()["remaining_task_usd"], "0.01")

    def test_acceptance_cannot_bypass_exhausted_pilot_budget(self):
        self.binding()
        with override_settings(TARKADO_ADMISSION_VERIFIER=selection_support.ControlledAdmissionVerifier()):
            additional = selection.select(current_member(self.junior), self.approval.reference, self.value(2, reserve_usd="0.90"))
            self.assertTrue(additional["new_reservation"])
            self.assertEqual(self.accept().status_code, 200)
            blocked = selection.select(current_member(self.junior), self.approval.reference, self.value(3, reserve_usd="0.01"))
            self.assertFalse(blocked["new_reservation"])
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["remaining_usd"], "0.00")
        self.assertEqual(self.provider.calls, 0)

    def test_new_acceptance_stales_learning_separately_and_next_review_keeps_it(self):
        self.binding()
        original = copy.deepcopy(self.approval.review.data)
        approved = copy.deepcopy(self.approval.data)
        self.assertEqual(self.accept().status_code, 200)
        state = selection.status(self.request(), self.approval.reference)
        self.assertEqual(state["selection_status"], "active")
        self.assertEqual(state["guard"]["status"], "current")
        self.assertEqual(state["learning_freshness"]["status"], "needs_review")
        self.assertEqual(state["learning_freshness"]["new_feedback_records"], 1)
        self.assertEqual(state["learning_freshness"]["reviewed_learner_sha256"], original["learner"]["learner_sha256"])
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "blocked")
        page = self.client.get(f"/pilots/{self.approval.reference}/selection/")
        self.assertContains(page, "Next learning review")
        self.assertContains(page, "needs_review")
        self.assertContains(page, "Runtime active")
        ledger = company_ledger(Company.objects.get(), "team")
        with self.assertRaises(support.ValidationError): LearnedModel.from_dict(original["learner"]).verify_source(ledger)
        plan = dict(original["learner"]["plan"], learner_version="accepted-task-next-review-v2", cutoff=timezone.now().isoformat(),
            session_ids=sorted({rec.task.session_id for rec in ledger.recommendations}))
        next_review = authorization.prepare_review(self.request(), plan)
        self.assertEqual(next_review.data["learner"]["training_counts"]["responses"], original["learner"]["training_counts"]["responses"] + 1)
        self.assertEqual(next_review.data["learner"]["training_counts"]["executions"], original["learner"]["training_counts"]["executions"])
        observed = [row for row in next_review.data["report"]["observations"] if row["task_id"] == self.link.task.task_id]
        self.assertEqual(observed[0]["response"], "accept")
        self.assertEqual(observed[0]["result_status"], "unknown")
        self.approval.refresh_from_db(); self.approval.review.refresh_from_db()
        self.assertEqual(self.approval.data, approved)
        self.assertEqual(self.approval.review.data, original)

    def test_duplicate_stale_changed_and_wrong_owner_responses_preserve_timing_roles(self):
        self.binding()
        body = {"connector_task_ref": str(self.link.reference), "location_sha256": self.link.credential.scope["location_sha256"],
                "action": "response", "expected_revision": 0, "value": "accept"}
        self.assertEqual(self.api(self.connector_token, "feedback", body).status_code, 400)
        self.assertEqual(self.accept().status_code, 200)
        self.link.task.refresh_from_db()
        before = task_ledger(self.link.task).to_dict()
        self.assertEqual(self.api(self.connector_token, "feedback", {**body, "expected_revision": 1}).status_code, 200)
        self.assertEqual(self.api(self.connector_token, "feedback", {**body, "expected_revision": 2, "value": "reject"}).status_code, 400)
        with self.assertRaises(support.PermissionDenied):
            record_response(self.senior, self.link.task.reference, "accept", 2)
        self.link.task.refresh_from_db()
        self.assertEqual(task_ledger(self.link.task).to_dict(), before)
        event = TaskEvent.objects.get(task=self.link.task, kind="response")
        self.assertEqual(event.actor_snapshot["role"], "junior")
        self.assertEqual(event.actor_id, self.junior.pk)
        request = self.physical()
        self.assertEqual(self.accept().status_code, 200)
        self.assertEqual(TaskEvent.objects.filter(task=self.link.task, kind="response").count(), 1)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")

    def test_new_response_after_paid_attempt_remains_refused(self):
        self.binding()
        self.physical()
        self.assertEqual(self.accept().status_code, 400)
        self.link.task.refresh_from_db()
        self.assertEqual(task_ledger(self.link.task).responses, ())
        self.assertEqual(selection._state(ScopedSelectionRuntime.objects.get())["status"], "active")

    def test_acceptance_on_previously_reviewed_pending_task_is_not_exempt(self):
        previous = recommend_task(self.junior, self.source(42))
        self.binding()
        record_response(self.junior, previous.reference, "accept", previous.revision)
        self.assertEqual(selection.status(self.request(), self.approval.reference)["selection_status"], "paused")
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(self.provider.calls, 0)

    def test_new_result_revision_cannot_use_the_acceptance_exception(self):
        self.binding()
        self.assertEqual(self.accept().status_code, 200)
        other = recommend_task(self.junior, self.source(30))
        other = record_execution(self.junior, other.reference, "fixture/cheap", other.revision)
        other = record_result(self.junior, other.reference, {"desired_result": None, "tests_passed": None, "score": None,
            "cost_usd": None, "latency_ms": None, "evidence_ref": None, "supersedes": None}, other.revision)
        original_result = task_ledger(other).results[-1]
        other = record_result(self.junior, other.reference, {"desired_result": False, "tests_passed": False, "score": None,
            "cost_usd": None, "latency_ms": None, "evidence_ref": "controlled-appended-failure", "supersedes": original_result.result_id}, other.revision)
        self.assertEqual(len(task_ledger(other).results), 2)
        self.assertEqual(task_ledger(other).results[0], original_result)
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(self.provider.calls, 0)

    def test_known_failed_paid_attempt_is_not_bypassed_by_acceptance_retry(self):
        self.binding()
        self.assertEqual(self.accept().status_code, 200)
        request = self.physical()
        response = self.provider.send(request)
        attempt_id = next(iter(self.state()["attempts"]))
        delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], attempt_id, "0.002",
            {"input_tokens": 100, "output_tokens": 50, "cached_input_tokens": 0, "reasoning_tokens": 10},
            "failed", 1, "controlled-paid-failure", response["model"])
        self.assertEqual(self.accept().status_code, 200)
        with self.assertRaises(support.ValidationError): self.physical()
        self.assertEqual(self.state()["known_cost_usd"], "0.002")
        self.assertEqual(selection.status(self.request(), self.approval.reference)["selection_status"], "paused")
        self.assertEqual(self.provider.calls, 1)
