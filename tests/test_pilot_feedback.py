"""Routine progress is a bounded freshness exception, never human-outcome truth."""

import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch

import test_company as support
import test_acceptance_freshness as a
import test_connectors as c
import test_delivery as d
import test_delivery_review as r
import test_selection as s
import test_tool_observations as t
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from engine.company import authorization, company_learning, delivery, pilot_feedback, selection
from engine.company.live_authorization import live_guard
from engine.company.models import Company, CompanyTask, ConnectorTask, DeliveryBinding, ScopedSelectionRuntime, TaskEvent
from engine.company.services import current_member
from engine.company.tasks import company_ledger, recommend_task, record_execution, record_result, task_ledger
from engine.learning import LearnedModel


def setUpModule(): support.setUpModule()
def tearDownModule(): connections.close_all()


class FeedbackFixture(r.DeliveryFixture):
    accept = a.AcceptanceFreshnessTests.accept

    def active(self):
        approval = r.DeliveryFixture.active(self)
        self.publication = self.sensitive(company_learning.change, "team", 0, "Publish controlled manual suggestions",
            review_ref=approval.review.reference, repositories=["synthetic-repository"])
        return approval

    def close(self):
        self.link.refresh_from_db()
        event = c.ConnectorTests.event(self, {"connector_task_ref": str(self.link.reference)}, sequence=self.link.sequence + 1, kind="close")
        response = self.api(self.connector_token, "observation", event)
        self.assertEqual(response.status_code, 200, response.content)
        self.link.refresh_from_db(); self.link.task.refresh_from_db()

    def healthy(self, accept=True):
        self.binding()
        if accept: self.assertEqual(self.accept().status_code, 200)
        request = self.physical()
        self.hooks.settle(request, self.provider.send(request))
        self.close()
        return request

    def report(self, model="fixture/cheap"):
        self.link.task.refresh_from_db()
        self.link.task = record_execution(self.junior, self.link.task.reference, model, self.link.task.revision)
        return self.link.task

    def result(self, **updates):
        self.link.task.refresh_from_db()
        value = {"desired_result": True, "tests_passed": None, "score": None, "cost_usd": None, "latency_ms": None,
            "evidence_ref": "controlled-human-result-unverified", "supersedes": None, **updates}
        self.link.task = record_result(self.junior, self.link.task.reference, value, self.link.task.revision)
        return self.link.task

    def status(self): return selection.status(self.request(), self.approval.reference)

    def next_task(self, number=2, user=None, override=None, reserve="0.10"):
        user = user or self.junior
        if user == self.junior:
            credential, token = self.link.credential, self.connector_token
        else:
            credential, token, _ = self.pair(source_kind="team", user=user)
        source = self.task_source(required_tools=[], task_label=f"controlled-future-task-{number}",
            session_ref=delivery.connectors.digest(f"controlled-future-session-{number}-{user.username}"))
        started = self.api(token, "start", source)
        self.assertEqual(started.status_code, 200, started.content)
        link = ConnectorTask.objects.get(reference=started.json()["connector_task_ref"])
        proposal = self.value(number, task=task_ledger(link.task).recommendations[0].task.to_dict(), reserve_usd=reserve, override_model=override)
        selected = selection.select(current_member(user), self.approval.reference, proposal, connector_link=link)
        return credential, token, link, selected, proposal

    def bound_next(self, number=2, user=None, override=None):
        credential, token, link, selected, proposal = self.next_task(number, user, override)
        user = user or self.junior
        self.assertTrue(selected["new_reservation"], selected)
        claim = selection.claim(current_member(user), self.approval.reference, proposal["selection_id"])
        self.assertTrue(claim["new_claim"])
        bound = delivery.bind(credential, current_member(user), link, str(self.approval.reference), proposal["selection_id"], str(self.gateway.reference))
        return bound, link, token


class ContinuousFeedbackTests(FeedbackFixture, TestCase):
    def test_matching_model_and_first_positive_result_leave_pilot_eligible(self):
        self.healthy()
        approved, reviewed = copy.deepcopy(self.approval.data), copy.deepcopy(self.approval.review.data)
        self.report()
        after_model = self.status()
        self.assertEqual(after_model["selection_status"], "active")
        self.assertEqual(after_model["guard"]["status"], "current")
        self.assertEqual(after_model["incoming_feedback"]["routine_records"], 2)
        self.assertEqual(after_model["incoming_feedback"]["waiting_tasks"][0]["state"], "awaiting_human_result")
        self.result(tests_passed=True)
        after_result = self.status()
        self.assertEqual(after_result["selection_status"], "active")
        self.assertEqual(after_result["guard"]["status"], "current")
        self.assertEqual(after_result["incoming_feedback"]["routine_records"], 3)
        self.assertEqual(after_result["incoming_feedback"]["review_required_records"], 0)
        self.assertEqual(after_result["incoming_feedback"]["waiting_tasks"], [])
        self.assertEqual(after_result["learning_freshness"]["status"], "needs_review")
        self.approval.refresh_from_db(); self.approval.review.refresh_from_db()
        self.assertEqual(self.approval.data, approved)
        self.assertEqual(self.approval.review.data, reviewed)
        self.assertEqual(self.readiness.calls[-1].to_dict(), approved["readiness_request"])
        self.assertEqual(after_result["accounting"]["spent_usd"], "0.002")
        self.assertEqual(after_result["accounting"]["remaining_task_slots"], 2)

    def test_next_new_task_reaches_controlled_provider_with_fresh_bound_reservation(self):
        from engine.litellm_delivery import AttemptHooks
        from types import SimpleNamespace
        self.healthy(); self.report(); self.result()
        bound, link, _ = self.bound_next()
        hooks = AttemptHooks(d.LocalBackend(self.gateway_token))
        body = {"model": "company-cheap", "messages": [{"role": "user", "content": "Controlled private task"}],
            "max_completion_tokens": 1000, "metadata": {"tarkado_binding": bound["binding_ref"], "tarkado_task": bound["task_token"],
            "tarkado_session": bound["session_ref"], "tarkado_request": str(uuid.uuid4()), "tarkado_kind": "primary"}}
        logical = hooks.pre_call(body, SimpleNamespace(user_id="employee-junior")); logical["model"] = "fixture-provider-cheap"
        physical = hooks.pre_attempt(logical)
        state = delivery.state(DeliveryBinding.objects.get(reference=bound["binding_ref"]))
        self.assertEqual(state["attempt_reserved_usd"], "0.04")
        self.assertEqual(self.provider.calls, 1)
        hooks.settle(physical, self.provider.send(physical))
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(self.status()["selection_status"], "active")
        self.assertEqual(self.status()["guard"]["status"], "current")
        self.assertEqual(self.status()["accounting"]["claimed_tasks"], 2)
        self.assertEqual(task_ledger(link.task).executions, ())
        self.assertEqual(task_ledger(link.task).results, ())

    def test_no_acceptance_is_not_fabricated_as_adoption_or_required_for_actual_model_truth(self):
        self.healthy(accept=False); self.report(); self.result()
        state = self.status()
        self.assertEqual(state["guard"]["status"], "current")
        self.assertEqual(state["incoming_feedback"]["routine_records"], 2)
        self.assertEqual(task_ledger(self.link.task).responses, ())
        self.assertEqual(state["incoming_feedback"]["records"][1]["outcome_verified"], False)

    def test_duplicate_owned_reports_and_results_do_not_change_history_or_claims(self):
        self.healthy(); self.report(); first = self.result()
        before = copy.deepcopy(ScopedSelectionRuntime.objects.get().journal)
        records = copy.deepcopy(list(TaskEvent.objects.filter(task=first).values("sequence", "timestamp", "payload")))
        self.report(); self.result()
        self.assertEqual(list(TaskEvent.objects.filter(task=first).values("sequence", "timestamp", "payload")), records)
        self.assertEqual(ScopedSelectionRuntime.objects.get().journal, before)
        self.assertFalse(selection.claim(current_member(self.junior), self.approval.reference, "synthetic-selection-1")["new_claim"])
        self.assertEqual(self.status()["accounting"]["remaining_task_slots"], 2)

    def test_stale_changed_wrong_owner_reports_are_refused_without_new_evidence(self):
        self.healthy(); self.report()
        count = TaskEvent.objects.filter(task=self.link.task).count()
        with self.assertRaises(support.ValidationError): self.report("fixture/premium")
        with self.assertRaises(support.PermissionDenied):
            record_execution(self.senior, self.link.task.reference, "fixture/cheap", self.link.task.revision)
        with self.assertRaises(support.ValidationError):
            record_result(self.junior, self.link.task.reference, c.ConnectorTests.result_value(self), 1)
        self.assertEqual(TaskEvent.objects.filter(task=self.link.task).count(), count)
        self.assertEqual(self.status()["selection_status"], "active")

    def test_first_unknown_result_pauses_and_stays_visible(self):
        self.healthy(); self.report(); self.result(desired_result=None, evidence_ref=None)
        state = self.status()
        self.assertEqual(state["selection_status"], "paused")
        self.assertEqual(state["guard"]["status"], "blocked")
        self.assertEqual(state["incoming_feedback"]["review_required_records"], 1)
        self.assertEqual(task_ledger(self.link.task).results[0].desired_result, None)

    def test_first_negative_result_and_test_failure_still_pause(self):
        self.healthy(); self.report(); self.result(desired_result=False, tests_passed=False)
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertFalse(task_ledger(self.link.task).results[0].desired_result)

    def test_positive_result_revision_still_blocks_and_preserves_original(self):
        self.healthy(); self.report(); self.result()
        old = task_ledger(self.link.task).results[0]
        self.result(supersedes=old.result_id, evidence_ref="controlled-revised-positive")
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertEqual(task_ledger(self.link.task).results[0], old)
        self.assertEqual(len(task_ledger(self.link.task).results), 2)

    def test_negative_then_positive_revision_does_not_resume_or_erase_failure(self):
        self.healthy(); self.report(); self.result(desired_result=False)
        old = task_ledger(self.link.task).results[0]
        self.result(supersedes=old.result_id, evidence_ref="controlled-later-positive")
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertEqual(task_ledger(self.link.task).results[0], old)

    def test_model_report_before_close_cannot_be_retroactively_qualified(self):
        self.binding()
        physical = self.physical(); self.hooks.settle(physical, self.provider.send(physical))
        self.report()
        self.assertEqual(self.status()["selection_status"], "paused")
        self.close()
        self.assertEqual(self.status()["guard"]["status"], "blocked")

    def test_pending_unknown_or_auxiliary_only_delivery_cannot_qualify(self):
        self.binding()
        self.physical(kind="title")
        self.close(); self.report()
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["accounting"]["reserved_usd"], "0.10")

    def test_complete_auxiliary_only_delivery_has_no_primary_exception(self):
        self.binding()
        physical = self.physical(kind="title"); self.hooks.settle(physical, self.provider.send(physical))
        self.close(); self.report()
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")

    def test_auxiliary_failure_cannot_be_hidden_by_primary_success_report(self):
        self.binding()
        primary, auxiliary = self.physical(), self.physical(kind="title")
        self.hooks.settle(primary, self.provider.send(primary)); self.hooks.settle(auxiliary, failed=True)
        self.close(); self.report()
        with self.assertRaisesMessage(support.ValidationError, "Incomplete/failed/wrong-model"):
            self.result()
        self.result(desired_result=None, evidence_ref=None)
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertEqual(self.status()["accounting"]["reserved_usd"], "0.10")

    def test_wrong_bound_model_report_pauses_immediately_not_only_on_later_result(self):
        self.healthy(); self.report("fixture/premium")
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertEqual(task_ledger(self.link.task).executions[0].actual_model, "fixture/premium")

    def test_unbound_positive_task_is_not_a_routine_exemption(self):
        self.binding()
        other = recommend_task(self.junior, self.source(30))
        other = record_execution(self.junior, other.reference, "fixture/cheap", other.revision)
        record_result(self.junior, other.reference, c.ConnectorTests.result_value(self, desired_result=True, evidence_ref="unbound-controlled-positive"), other.revision)
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")

    def test_previously_reviewed_task_changes_never_get_routine_exception(self):
        earlier = recommend_task(self.junior, self.source(40))
        self.binding()
        record_execution(self.junior, earlier.reference, "fixture/cheap", earlier.revision)
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")

    def test_matching_human_cost_is_not_invoice_truth_and_conflicting_cost_requires_review(self):
        self.healthy(); self.report(); self.result(cost_usd="0.003")
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["accounting"]["spent_usd"], "0.002")
        self.assertEqual(task_ledger(self.link.task).results[0].cost_usd, Decimal("0.003"))

    def test_first_positive_with_matching_accounting_remains_unverified(self):
        self.healthy(); self.report(); self.result(cost_usd="0.002")
        self.assertEqual(self.status()["guard"]["status"], "current")
        self.assertTrue(all(not row["outcome_verified"] for row in self.status()["incoming_feedback"]["records"]))

    def test_another_developers_reject_still_blocks_routine_success(self):
        self.healthy(); self.report(); self.result()
        other = recommend_task(self.senior, self.source(30))
        from engine.company.tasks import record_response
        record_response(self.senior, other.reference, "reject", other.revision)
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        rows = self.status()["incoming_feedback"]["records"]
        self.assertEqual(rows[0]["historical_role"], "senior")
        self.assertEqual(rows[0]["status"], "review_required")

    def test_strict_future_publication_stays_stale_and_next_explicit_fit_retains_reports(self):
        self.healthy(); self.report(); self.result(tests_passed=True)
        original = copy.deepcopy(self.approval.review.data)
        ledger = company_ledger(Company.objects.get(), "team")
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "blocked")
        with self.assertRaises(support.ValidationError): LearnedModel.from_dict(original["learner"]).verify_source(ledger)
        plan = {**original["learner"]["plan"], "learner_version": "controlled-routine-feedback-v2", "cutoff": timezone.now().isoformat(),
            "session_ids": sorted({row.task.session_id for row in ledger.recommendations})}
        review = authorization.prepare_review(self.request(), plan)
        self.assertEqual(review.data["learner"]["training_counts"]["responses"], original["learner"]["training_counts"]["responses"] + 1)
        self.assertEqual(review.data["learner"]["training_counts"]["executions"], original["learner"]["training_counts"]["executions"] + 1)
        self.assertEqual(review.data["learner"]["training_counts"]["current_results"], original["learner"]["training_counts"]["current_results"] + 1)
        self.approval.review.refresh_from_db(); self.assertEqual(self.approval.review.data, original)
        self.assertEqual(self.status()["selection_status"], "active")

    def test_closed_task_feedback_cannot_resume_paused_revoked_or_withdrawn_pilot(self):
        self.healthy()
        self.sensitive(selection.control, self.approval.reference, "pause", self.status()["revision"], "Pause before human report")
        self.report(); self.result()
        self.assertEqual(self.status()["selection_status"], "paused")
        self.sensitive(selection.control, self.approval.reference, "revoke", self.status()["revision"], "Revoke after human report")
        self.assertEqual(self.status()["selection_status"], "revoked")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertFalse(selection.claim(current_member(self.junior), self.approval.reference, "synthetic-selection-1")["new_claim"])

    def test_expired_approval_or_readiness_outage_not_fixed_by_routine_feedback(self):
        self.healthy(); self.report(); self.result()
        expired = timezone.datetime.fromisoformat(self.approval.data["expires_at"]) + timedelta(seconds=1)
        with patch("django.utils.timezone.now", return_value=expired):
            self.assertEqual(live_guard(self.approval, Company.objects.get(), allow_future_recommendations=True)["status"], "blocked")
        with override_settings(TARKADO_READINESS_VERIFIER=None):
            self.assertEqual(self.status()["guard"]["status"], "blocked")

    def test_unapproved_model_or_removed_authority_stays_blocked(self):
        self.healthy(); self.report(); self.result()
        company = Company.objects.get(); company.policy["models"][0]["approved"] = False; company.save(update_fields=("policy",))
        self.assertEqual(self.status()["guard"]["status"], "blocked")

    def test_routine_feedback_does_not_restore_lifetime_task_or_budget_capacity(self):
        self.healthy(); self.report(); self.result()
        with override_settings(TARKADO_ADMISSION_VERIFIER=s.ControlledAdmissionVerifier()):
            selection.select(current_member(self.junior), self.approval.reference, self.value(2, reserve_usd="0.998"))
            result = selection.select(current_member(self.junior), self.approval.reference, self.value(3, reserve_usd="0.001"))
            self.assertFalse(result["new_reservation"])
        self.assertEqual(self.status()["accounting"]["remaining_usd"], "0.000")
        self.assertEqual(self.status()["accounting"]["selected_tasks"], 2)

    def test_bare_review_cannot_establish_bound_task_exception(self):
        self.healthy(); self.report(); self.result()
        ledger = company_ledger(Company.objects.get(), "team")
        with self.assertRaises(support.ValidationError):
            pilot_feedback.verify_for_execution(self.approval.review, ledger, LearnedModel.from_dict(self.approval.review.data["learner"]))
        self.assertEqual(self.status()["guard"]["status"], "current")

    def test_browser_shows_pending_review_links_exact_record_roles_and_no_secrets(self):
        self.healthy(); self.report(); self.result()
        path = f"/pilots/{self.approval.reference}/selection/"
        page = self.client.get(path)
        self.assertContains(page, "Incoming pilot feedback")
        self.assertContains(page, "Routine records pending learning: 3")
        self.assertContains(page, "historical junior")
        self.assertContains(page, "not verified outcomes")
        self.assertContains(page, "Runtime active")
        self.assertContains(page, f"/tasks/{self.link.task.reference}/")
        for secret in (self.gateway_token, self.connector_token, self.bound["task_token"], "Synthetic private prompt", "Synthetic private output"):
            self.assertNotContains(page, secret)
            self.assertNotIn(secret, json.dumps(self.status()["incoming_feedback"]))
        client = support.LocalClient(); client.force_login(self.junior)
        self.assertEqual(client.get(path).status_code, 403)

    def test_connector_api_model_report_and_initial_result_use_same_routine_rules(self):
        self.healthy()
        def feedback(kind, value):
            self.link.task.refresh_from_db()
            return self.api(self.connector_token, "feedback", {"connector_task_ref": str(self.link.reference),
                "location_sha256": self.link.credential.scope["location_sha256"], "action": kind, "value": value,
                "expected_revision": self.link.task.revision})
        self.assertEqual(feedback("actual_model", "fixture/cheap").status_code, 200)
        self.assertEqual(feedback("result", c.ConnectorTests.result_value(self, desired_result=True, evidence_ref="controlled-connector-positive")).status_code, 200)
        self.assertEqual(self.status()["guard"]["status"], "current")
        self.assertEqual(self.status()["selection_status"], "active")

    def test_separately_reviewed_other_pilot_cannot_reuse_routine_bindings(self):
        self.healthy(); self.report(); self.result()
        # Construct no new authority: use a different historical identity only
        # as an internal negative test. Its tasks cannot belong to this runtime.
        other = copy.copy(self.approval)
        other.pk = self.approval.pk + 10000
        ledger = company_ledger(Company.objects.get(), "team")
        learner = LearnedModel.from_dict(self.approval.review.data["learner"])
        with self.assertRaises(support.ValidationError): pilot_feedback.verify_for_execution(self.approval.review, ledger, learner, other)
        self.assertEqual(self.status()["guard"]["status"], "current")

    def test_model_report_after_gap_does_not_gain_a_routine_exception(self):
        self.binding()
        physical = self.physical(); self.hooks.settle(physical, self.provider.send(physical))
        event = c.ConnectorTests.event(self, {"connector_task_ref": str(self.link.reference)}, kind="gap")
        self.assertEqual(self.api(self.connector_token, "observation", event).status_code, 200)
        self.close(); self.report()
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertEqual(self.status()["incoming_feedback"]["review_required_records"], 1)

    def test_retained_retry_failure_does_not_become_healthy_after_success(self):
        from types import SimpleNamespace
        self.binding()
        logical = self.hooks.pre_call(self.body(), SimpleNamespace(user_id="employee-junior")); logical["model"] = "fixture-provider-cheap"
        self.hooks.pre_attempt(logical)
        attempt_id = next(iter(self.state()["attempts"]))
        delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], attempt_id, "0",
            {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "reasoning_tokens": 0},
            "retryable_failure", 0, "controlled-retryable-receipt", "fixture-provider-cheap")
        physical = self.hooks.pre_attempt(logical); self.hooks.settle(physical, self.provider.send(physical))
        self.close(); self.report()
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertEqual(self.status()["accounting"]["spent_usd"], "0.002")

    def test_explicit_override_is_retained_and_cannot_become_routine_progress(self):
        self.healthy(); self.report(); self.result()
        bound, link, _ = self.bound_next(override="fixture/cheap")
        request_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        delivery.begin_request(self.gateway_token, bound["task_token"], bound["binding_ref"], bound["session_ref"], "employee-junior", request_id, "primary", 1000, False)
        delivery.admit_attempt(self.gateway_token, bound["task_token"], bound["binding_ref"], bound["session_ref"], request_id, attempt_id, "fixture-provider-cheap", 1000, False)
        delivery.settle_attempt(self.gateway_token, bound["binding_ref"], attempt_id, "0.002",
            {"input_tokens": 100, "output_tokens": 50, "cached_input_tokens": 0, "reasoning_tokens": 10},
            "completed", 1, "controlled-override-usage", "fixture-provider-cheap")
        event = c.ConnectorTests.event(self, {"connector_task_ref": str(link.reference)}, kind="close")
        self.assertEqual(self.api(self.connector_token, "observation", event).status_code, 200)
        link.task.refresh_from_db()
        record_execution(self.junior, link.task.reference, "fixture/cheap", link.task.revision)
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertTrue(selection._state(ScopedSelectionRuntime.objects.get())["decisions"]["synthetic-selection-2"]["override"])

    def test_senior_model_report_and_result_reuse_exact_scope_and_historical_role(self):
        self.healthy(); self.report(); self.result()
        gateway, token = self.sensitive(delivery.issue_gateway, "controlled-gateway", "synthetic-repository",
            {"junior": "employee-junior", "senior": "employee-senior"}, timezone.now() + timedelta(hours=1), Company.objects.get().revision)
        self.gateway, self.gateway_token = gateway, token
        bound, link, connector_token = self.bound_next(user=self.senior)
        request_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        delivery.begin_request(token, bound["task_token"], bound["binding_ref"], bound["session_ref"], "employee-senior", request_id, "primary", 1000, False)
        delivery.admit_attempt(token, bound["task_token"], bound["binding_ref"], bound["session_ref"], request_id, attempt_id, "fixture-provider-cheap", 1000, False)
        delivery.settle_attempt(token, bound["binding_ref"], attempt_id, "0.002",
            {"input_tokens": 100, "output_tokens": 50, "cached_input_tokens": 0, "reasoning_tokens": 10},
            "completed", 1, "controlled-senior-usage", "fixture-provider-cheap")
        event = c.ConnectorTests.event(self, {"connector_task_ref": str(link.reference)}, kind="close")
        self.assertEqual(self.api(connector_token, "observation", event).status_code, 200)
        link.task.refresh_from_db()
        task = record_execution(self.senior, link.task.reference, "fixture/cheap", link.task.revision)
        record_result(self.senior, task.reference, c.ConnectorTests.result_value(self, desired_result=True, evidence_ref="controlled-senior-positive"), task.revision)
        state = self.status()
        self.assertEqual(state["selection_status"], "active")
        self.assertEqual(state["guard"]["status"], "current")
        self.assertEqual(state["incoming_feedback"]["routine_records"], 5)
        self.assertEqual(state["incoming_feedback"]["records"][0]["historical_role"], "senior")
        self.assertEqual(state["accounting"]["spent_usd"], "0.004")
        self.assertEqual(state["accounting"]["remaining_usd"], "0.996")

    def test_known_cost_correction_never_implicitly_expands_routine_feedback(self):
        import test_billing_corrections as billing
        from engine.company import billing_corrections
        self.healthy(); self.report(); self.result()
        binding = DeliveryBinding.objects.get()
        state = delivery.state(binding); row = next(iter(state["attempts"].values()))
        value = {"correction_id": str(uuid.uuid4()), "attempt_id": row["attempt_id"], "request_id": row["request_id"],
            "expected_revision": state["revision"], "supersedes_sha256": row["cost_head_sha256"], "cost_usd": "0.001", "evidence_ref": "controlled-cost-decrease"}
        ledger = billing.EvidenceLedger(); ledger.record(binding, value, "0.001")
        with override_settings(TARKADO_BILLING_VERIFIER=ledger):
            review = billing_corrections.review_machine(self.gateway_token, self.bound["binding_ref"], **value)
            billing_corrections.correct_machine(self.gateway_token, self.bound["binding_ref"], review["correction"]["billing_assessment"], **value)
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertEqual(self.status()["accounting"]["spent_usd"], "0.001")
        self.assertEqual(len(task_ledger(self.link.task).results), 1)
        self.assertEqual(self.status()["incoming_feedback"]["review_required_records"], 2)

    def test_synthetic_or_other_category_records_are_not_new_live_quality(self):
        self.healthy(); self.report(); self.result()
        other = recommend_task(self.junior, {**self.source(30), "source_kind": "synthetic"})
        record_execution(self.junior, other.reference, "fixture/premium", other.revision)
        self.assertEqual(self.status()["selection_status"], "active")
        self.assertEqual(self.status()["guard"]["status"], "current")
        self.assertEqual(len(self.status()["incoming_feedback"]["records"]), 3)

    def test_senior_first_result_review_is_prioritized_but_not_independently_verified(self):
        self.healthy(); task = self.report()
        record_result(self.senior, task.reference, c.ConnectorTests.result_value(self, desired_result=True, evidence_ref="controlled-senior-review"), task.revision)
        state = self.status()
        self.assertEqual(state["selection_status"], "active")
        self.assertEqual(state["guard"]["status"], "current")
        self.assertEqual(state["incoming_feedback"]["records"][0]["developer_id"], "senior")
        self.assertEqual(state["incoming_feedback"]["records"][0]["historical_role"], "senior")
        self.assertFalse(state["incoming_feedback"]["records"][0]["outcome_verified"])
        self.assertEqual(state["accounting"]["spent_usd"], "0.002")

    def test_another_juniors_failure_cannot_be_hidden_by_senior_routine_progress(self):
        self.healthy(); task = self.report()
        record_result(self.senior, task.reference, c.ConnectorTests.result_value(self, desired_result=True, evidence_ref="controlled-senior-review"), task.revision)
        other = recommend_task(self.junior, self.source(31))
        other = record_execution(self.junior, other.reference, "fixture/cheap", other.revision)
        record_result(self.junior, other.reference, c.ConnectorTests.result_value(self, desired_result=False, tests_passed=False,
            evidence_ref="controlled-junior-failure"), other.revision)
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertTrue(any(row["historical_role"] == "junior" and row["status"] == "review_required" for row in self.status()["incoming_feedback"]["records"]))

    def test_late_delivery_evidence_does_not_retroactively_qualify_an_early_report(self):
        self.healthy(); self.report(); self.result()
        ledger = company_ledger(Company.objects.get(), "team")
        learner = LearnedModel.from_dict(self.approval.review.data["learner"])
        execution = task_ledger(self.link.task).executions[0]
        rec = task_ledger(self.link.task).recommendations[0]
        early = replace(execution, timestamp=rec.task.timestamp)
        with self.assertRaisesMessage(support.ValidationError, "before reporting"):
            pilot_feedback._routine_progress(self.approval.review, ledger, early, rec, self.approval)
        self.assertEqual(self.status()["guard"]["status"], "current")

    def test_delivery_history_corruption_is_not_repaired_by_human_reports(self):
        self.healthy(); self.report(); self.result()
        binding = DeliveryBinding.objects.get()
        original = copy.deepcopy(binding.journal)
        binding.journal[-1]["payload"]["cost_usd"] = "0.003"
        binding.save(update_fields=("journal",))
        with self.assertRaises(support.ValidationError): self.status()
        self.assertNotEqual(DeliveryBinding.objects.get().journal, original)
        self.assertEqual(TaskEvent.objects.filter(task=self.link.task, kind="result").count(), 1)


class ContinuousFeedbackConcurrencyTests(FeedbackFixture, TransactionTestCase):
    def test_parallel_duplicate_model_reports_have_one_record_and_no_new_claim(self):
        self.healthy()
        def report(_):
            try:
                task = CompanyTask.objects.get(pk=self.link.task.pk)
                return record_execution(self.junior, task.reference, "fixture/cheap", task.revision).reference
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(report, range(2)))
        self.assertEqual(records[0], records[1])
        self.assertEqual(TaskEvent.objects.filter(task=self.link.task, kind="execution").count(), 1)
        self.assertEqual(self.status()["guard"]["status"], "current")
        self.assertEqual(self.status()["accounting"]["claimed_tasks"], 1)
        self.assertEqual(self.status()["accounting"]["spent_usd"], "0.002")

    def test_parallel_negative_and_positive_result_corrections_cannot_branch_or_resume(self):
        self.healthy(); self.report(); self.result()
        task = CompanyTask.objects.get(pk=self.link.task.pk)
        previous = task_ledger(task).results[0]
        def correct(desired):
            try:
                try:
                    record_result(self.junior, task.reference, c.ConnectorTests.result_value(self, desired_result=desired,
                        evidence_ref="controlled-concurrent-correction", supersedes=previous.result_id), task.revision)
                    return True
                except support.ValidationError:
                    return False
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(correct, (True, False)))
        self.assertEqual(sum(results), 1)
        task.refresh_from_db()
        self.assertEqual(task_ledger(task).results[0], previous)
        self.assertEqual(len(task_ledger(task).results), 2)
        self.assertEqual(self.status()["selection_status"], "paused")
        self.assertEqual(self.status()["guard"]["status"], "blocked")
        self.assertEqual(self.status()["accounting"]["spent_usd"], "0.002")


class ToolFeedbackTests(TestCase):
    setUp = t.ToolObservationTests.setUp
    enroll = t.ToolObservationTests.enroll
    request = t.ToolObservationTests.request
    sensitive = t.ToolObservationTests.sensitive
    source = t.ToolObservationTests.source
    evidence = t.ToolObservationTests.evidence
    approve = t.ToolObservationTests.approve
    scope = t.ToolObservationTests.scope
    developer_request = t.ToolObservationTests.developer_request
    task = t.ToolObservationTests.task
    active = t.ToolObservationTests.active
    value = t.ToolObservationTests.value
    api = t.ToolObservationTests.api
    task_source = t.ToolObservationTests.task_source
    body = t.ToolObservationTests.body
    physical = t.ToolObservationTests.physical
    accept = t.ToolObservationTests.accept
    state = t.ToolObservationTests.state
    pair = t.ToolObservationTests.pair
    binding = t.ToolObservationTests.binding
    event = t.ToolObservationTests.event
    send = t.ToolObservationTests.send
    started = t.ToolObservationTests.started
    close_task = t.ToolObservationTests.close_task
    def test_closed_human_success_does_not_exempt_retained_intermediate_test_failure(self):
        from engine.company.tasks import record_execution, record_result
        self.binding(); self.started()
        self.assertEqual(self.send(self.event("result", "test_failed", 2, source="reviewed_tool_metadata")).status_code, 200)
        physical = self.physical(); self.hooks.settle(physical, self.provider.send(physical))
        self.close_task(); self.link.task.refresh_from_db()
        task = record_execution(self.junior, self.link.task.reference, "fixture/cheap", self.link.task.revision)
        record_result(self.junior, task.reference, c.ConnectorTests.result_value(self, desired_result=True, evidence_ref="controlled-human-after-repair"), task.revision)
        state = selection.status(self.request(), self.approval.reference)
        self.assertEqual(state["selection_status"], "paused")
        self.assertEqual(state["guard"]["status"], "blocked")
        task.refresh_from_db()
        self.assertTrue(task_ledger(task).results[0].desired_result)

    def test_completed_generic_tool_is_not_fabricated_as_passing_test(self):
        self.binding(); self.started()
        self.assertEqual(self.send(self.event("result", "completed", 2)).status_code, 200)
        physical = self.physical(); self.hooks.settle(physical, self.provider.send(physical))
        self.close_task(); self.link.task.refresh_from_db()
        task = record_execution(self.junior, self.link.task.reference, "fixture/cheap", self.link.task.revision)
        self.assertEqual(task_ledger(task).results, ())
        self.assertEqual(selection.status(self.request(), self.approval.reference)["guard"]["status"], "current")
