"""Owner-reported delivery-learning/export regressions on isolated synthetic stores."""

import copy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import test_company as support
import test_delivery as delivery_support
from django.db import connections
from django.test import TestCase, override_settings
from django.utils import timezone

from engine.company import authorization, company_learning, delivery, policy_handoff, selection
from engine.company.models import Company, PilotAuthorization, ScopedSelectionRuntime
from engine.company.services import current_member
from engine.company.tasks import recommend_task, task_ledger
from engine.feedback import _fingerprint
from engine.history import PolicySnapshot
from engine.schemas import Policy


def setUpModule():
    support.setUpModule()


def tearDownModule():
    connections.close_all()


class DeliveryFixture:
    setUp = delivery_support.DeliveryTests.setUp
    enroll = delivery_support.DeliveryTests.enroll
    request = delivery_support.DeliveryTests.request
    sensitive = delivery_support.DeliveryTests.sensitive
    source = delivery_support.DeliveryTests.source
    evidence = delivery_support.DeliveryTests.evidence
    approve = delivery_support.DeliveryTests.approve
    scope = delivery_support.DeliveryTests.scope
    developer_request = delivery_support.DeliveryTests.developer_request
    task = delivery_support.DeliveryTests.task
    active = delivery_support.DeliveryTests.active
    value = delivery_support.DeliveryTests.value
    pair = delivery_support.DeliveryTests.pair
    api = delivery_support.DeliveryTests.api
    task_source = delivery_support.DeliveryTests.task_source
    binding = delivery_support.DeliveryTests.binding
    body = delivery_support.DeliveryTests.body
    physical = delivery_support.DeliveryTests.physical
    state = delivery_support.DeliveryTests.state


class DeliveryLearningReviewTests(DeliveryFixture, TestCase):
    def active(self):
        approval = super().active()
        self.publication = self.sensitive(company_learning.change, "team", 0, "Publish reviewed test suggestions only",
            review_ref=approval.review.reference, repositories=["synthetic-repository"])
        return approval

    def test_provider_timeout_blocks_published_learner_without_fabricating_outcome(self):
        self.binding()
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "current")
        request = self.physical()
        with self.assertRaises(TimeoutError):
            self.provider.send(request, fail=True)
        self.hooks.settle(request, failed=True)
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "blocked")
        future = recommend_task(self.senior, self.source(30))
        self.assertIsNone(future.learning_snapshot)
        self.assertEqual(task_ledger(future).recommendations[0].decision["recommended_model"], "fixture/premium")
        self.assertEqual(task_ledger(future).recommendations[0].decision["effective_model"], "fixture/premium")
        self.assertEqual(task_ledger(self.link.task).executions, ())
        self.assertEqual(task_ledger(self.link.task).results, ())
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")

    def test_refitting_cannot_hide_junior_delivery_failure_in_excluded_sessions(self):
        self.binding()
        original = copy.deepcopy(self.publication.review.data)
        request = self.physical()
        self.hooks.settle(request, failed=True)
        plan = dict(original["learner"]["plan"], learner_version="delivery-review-v2", cutoff=timezone.now().isoformat())
        review = authorization.prepare_review(self.request(), plan)
        self.assertEqual(review.data["report"]["categories"][0]["status"], "blocked")
        observed = review.data["delivery_observations"][0]
        self.assertEqual(observed["owner"]["role"], "junior")
        self.assertIn("unknown_provider_obligation", observed["negative_signals"])
        self.assertEqual(review.data["learner"]["training_counts"], original["learner"]["training_counts"])
        publication = self.sensitive(company_learning.change, "team", 1, "Retain failed diagnostics in new review",
            review_ref=review.reference, repositories=["synthetic-repository"])
        self.assertEqual(company_learning.guard(publication, Company.objects.get())["status"], "blocked")
        self.publication.review.refresh_from_db()
        self.assertEqual(self.publication.review.data, original)
        with self.assertRaises(support.ValidationError):
            self.approve(review=review, scope=self.scope(pilot_id="failed-delivery-must-not-approve"))

    def test_healthy_delivery_and_pending_attempt_do_not_invent_positive_training(self):
        self.binding()
        original = copy.deepcopy(self.publication.review.data["learner"])
        request = self.physical()
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "current")
        self.hooks.settle(request, self.provider.send(request))
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "current")
        self.publication.review.refresh_from_db()
        self.assertEqual(self.publication.review.data["learner"], original)
        self.assertEqual(task_ledger(self.link.task).results, ())

    def test_reconciled_timeout_remains_a_retained_learning_signal_after_withdrawal(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, failed=True)
        revision = selection._state(ScopedSelectionRuntime.objects.get())["revision"]
        self.sensitive(selection.control, self.approval.reference, "rollback", revision, "Withdraw without discarding failure evidence")
        attempt_id = next(iter(self.state()["attempts"]))
        with override_settings(TARKADO_BILLING_VERIFIER=delivery_support.ControlledBillingVerifier()):
            delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], attempt_id, "0", None, "cancelled", None, "controlled-cancellation-receipt")
        self.assertEqual(self.state()["unknown_attempts"], 0)
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "blocked")
        plan = dict(self.publication.review.data["learner"]["plan"], learner_version="post-reconciliation-v2", cutoff=timezone.now().isoformat())
        review = authorization.prepare_review(self.request(), plan)
        self.assertIn("unknown_provider_obligation", review.data["delivery_observations"][0]["negative_signals"])
        self.assertEqual(review.data["report"]["categories"][0]["status"], "blocked")

    def test_known_retryable_failure_blocks_new_suggestions_but_keeps_bounded_same_task_retry(self):
        self.binding()
        logical = self.hooks.pre_call(self.body(), SimpleNamespace(user_id="employee-junior"))
        logical["model"] = "fixture-provider-cheap"
        self.hooks.pre_attempt(logical)
        attempt_id = next(iter(self.state()["attempts"]))
        delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], attempt_id, "0",
            {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "reasoning_tokens": 0},
            "retryable_failure", 0, "controlled-known-retry-receipt", "fixture-provider-cheap")
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "blocked")
        with self.assertRaises(support.ValidationError):
            self.physical()
        retried = self.hooks.pre_attempt(logical)
        self.assertIsNotNone(retried)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.assertEqual(len(self.state()["attempts"]), 2)

    def test_company_simulation_receipt_retains_diagnostics_and_refuses_failed_approval(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, failed=True)
        plan = dict(self.publication.review.data["learner"]["plan"], learner_version="failed-simulation-review-v2", cutoff=timezone.now().isoformat())
        review = authorization.prepare_review(self.request(), plan)
        args = (review.reference, self.scope(pilot_id="failed-simulation-review"), timezone.now() + timedelta(hours=1),
                "Retain provider diagnostics in separate simulation decision", Company.objects.get().revision, "simulation")
        with self.assertRaisesMessage(support.ValidationError, "blocked category"):
            self.sensitive(authorization.authorize, *args)
        rejected = self.sensitive(authorization.authorize, *args, decision="reject")
        self.assertEqual(rejected.data["receipt"]["report"], review.data["report"])
        self.assertEqual(rejected.data["receipt"]["routes"], [])
        self.assertFalse(rejected.data["receipt"]["approved_for_local_simulation"])

    def test_healthy_company_simulation_review_still_approves_without_live_authority(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, self.provider.send(request))
        plan = dict(self.publication.review.data["learner"]["plan"], learner_version="healthy-simulation-review-v2", cutoff=timezone.now().isoformat())
        review = authorization.prepare_review(self.request(), plan)
        approved = self.sensitive(authorization.authorize, review.reference, self.scope(pilot_id="healthy-simulation-review"),
            timezone.now() + timedelta(hours=1), "Only a reviewed simulation decision", Company.objects.get().revision, "simulation")
        self.assertEqual(approved.data["receipt"]["report"], review.data["report"])
        self.assertTrue(approved.data["receipt"]["approved_for_local_simulation"])
        self.assertFalse(approved.data["routing_enabled"])
        self.assertEqual(authorization._validate_authorization(approved).data["report"], review.data["report"])

    def test_unknown_usage_wrong_model_and_overrun_all_reach_category_review(self):
        self.binding(reserve="0.20")
        requests = [self.physical() for _ in range(3)]
        self.hooks.settle(requests[0], self.provider.send(requests[0], missing_usage=True))
        response = self.provider.send(requests[1])
        response["usage"]["prompt_tokens"] = 10000
        response["usage"]["total_tokens"] = 10050
        self.hooks.settle(requests[1], response)
        self.hooks.settle(requests[2], self.provider.send(requests[2], model="different-provider-model"))
        plan = dict(self.publication.review.data["learner"]["plan"], learner_version="adverse-delivery-signals-v2", cutoff=timezone.now().isoformat())
        review = authorization.prepare_review(self.request(), plan)
        signals = review.data["delivery_observations"][0]["negative_signals"]
        for signal in ("unknown_provider_obligation", "provider_model_mismatch", "provider_cost_overrun", "provider_usage_bound_exceeded"):
            self.assertIn(signal, signals)
        self.assertEqual(review.data["report"]["categories"][0]["status"], "blocked")
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "blocked")
        self.assertEqual(self.state()["known_cost_usd"], "0.101")
        self.assertEqual(self.state()["unknown_attempts"], 2)
        self.assertEqual(self.provider.calls, 3)


class PolicyExportReviewTests(DeliveryFixture, TestCase):
    def rehash(self, value):
        # Recompute every fingerprint, not merely the outer envelope. Invalid
        # semantics must still be refused after consistency checks would pass.
        value["learner"]["learner_sha256"] = _fingerprint({key: val for key, val in value["learner"].items() if key != "learner_sha256"})
        value["learner_content_sha256"] = _fingerprint(value["learner"])
        value["sha256"] = _fingerprint({key: val for key, val in value.items() if key != "sha256"})
        return value

    def test_invalid_rehashed_learner_rule_is_not_a_valid_handoff(self):
        self.binding()
        value = policy_handoff.build(self.request(), self.approval.reference)
        changed = copy.deepcopy(value)
        changed["learner"]["rules"][0]["recommended_model"] = "missing/model"
        changed["learner"]["learner_sha256"] = _fingerprint({key: val for key, val in changed["learner"].items() if key != "learner_sha256"})
        changed["learner_content_sha256"] = _fingerprint(changed["learner"])
        changed["sha256"] = _fingerprint({key: val for key, val in changed.items() if key != "sha256"})
        with self.assertRaises(support.ValidationError):
            policy_handoff.validate(changed)

    def test_rehashed_scope_rejects_empty_duplicate_wildcard_and_unlearned_categories(self):
        self.binding()
        original = policy_handoff.build(self.request(), self.approval.reference)
        cases = (("task_types", []), ("task_types", ["*"]), ("task_types", ["documentation", "documentation"]),
                 ("task_types", ["unreviewed-category"]), ("developer_ids", []), ("developer_ids", ["junior", "junior"]),
                 ("developer_ids", ["jun*"]), ("developer_ids", ["x" * 65]), ("max_tasks", True), ("max_tasks", 0),
                 ("max_cost_usd", "0"), ("max_cost_usd", "-1"), ("max_cost_usd", "NaN"), ("max_cost_usd", 1.0),
                 ("pilot_id", ""), ("pilot_id", "x" * 129), ("repository_ref", "*"), ("repository_ref", "repo[ab]"))
        for field, value in cases:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(original)
                changed["scope"][field] = value
                self.rehash(changed)
                with self.assertRaises(support.ValidationError):
                    policy_handoff.validate(changed)
        self.assertEqual(policy_handoff.validate(original), original)

    def test_rehashed_invalid_learner_counts_plan_and_extra_fields_are_refused(self):
        self.binding()
        original = policy_handoff.build(self.request(), self.approval.reference)
        for section, field, value in (("training_counts", "recommendations", 0), ("plan", "dataset_split", "test"),
                                      ("plan", "task_types", []), ("plan", "min_senior_sessions", 0)):
            with self.subTest(section=section, field=field):
                changed = copy.deepcopy(original)
                changed["learner"][section][field] = value
                self.rehash(changed)
                with self.assertRaises(support.ValidationError): policy_handoff.validate(changed)
        changed = copy.deepcopy(original)
        changed["learner"]["execution_authorized"] = True
        self.rehash(changed)
        with self.assertRaises(support.ValidationError): policy_handoff.validate(changed)

    def test_individually_valid_learner_and_export_policy_must_match(self):
        self.binding()
        changed = policy_handoff.build(self.request(), self.approval.reference)
        changed["policy"]["policy_version"] = "different-valid-policy"
        changed["policy_sha256"] = Policy.from_dict(changed["policy"]).fingerprint()
        self.rehash(changed)
        with self.assertRaisesMessage(support.ValidationError, "Exact policy/learner"):
            policy_handoff.validate(changed)

    def test_rehashed_aggregate_counts_cannot_contradict_individually_valid_groups(self):
        self.binding()
        changed = policy_handoff.build(self.request(), self.approval.reference)
        changed["learner"]["training_counts"].update(executions=1, pending_executions=1, current_results=1, result_revisions=1)
        self.rehash(changed)
        with self.assertRaisesMessage(support.ValidationError, "aggregate evidence"):
            policy_handoff.validate(changed)

    def test_rehashed_policy_rule_cannot_reference_missing_or_incompatible_models(self):
        self.binding()
        original = policy_handoff.build(self.request(), self.approval.reference)
        for changes in ({"model": "missing/model"}, {"task_type": "unsupported-category"}, {"evidence_refs": []}):
            with self.subTest(changes=changes):
                changed = copy.deepcopy(original)
                changed["policy"]["rules"][1].update(changes)
                policy = Policy.from_dict(changed["policy"])
                changed["policy_sha256"] = policy.fingerprint()
                changed["learner"]["policy"] = PolicySnapshot.create(policy).to_dict()
                self.rehash(changed)
                with self.assertRaisesMessage(support.ValidationError, "Policy handoff rule"):
                    policy_handoff.validate(changed)

    def test_rehashed_nested_metadata_and_unknown_bound_omission_are_refused_cleanly(self):
        self.binding()
        original = policy_handoff.build(self.request(), self.approval.reference)
        changes = (("company_id", "not-a-uuid"), ("deployment_id", []), ("scope_ref", ""), ("company_revision", True),
                   ("company_revision", 0), ("model_bindings", [None]), ("unsupported", {}),
                   ("unsupported", [{"model_id": "missing/model", "reason": "unknown"}]),
                   ("unsupported", [{"model_id": None, "reason": "", "extra": "invalid"}]), ("unsupported", []))
        for field, value in changes:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(original); changed[field] = value; self.rehash(changed)
                with self.assertRaises(support.ValidationError): policy_handoff.validate(changed)
        changed = copy.deepcopy(original)
        changed["model_bindings"][0]["envelope"]["verified_at"] = changed["model_bindings"][0]["envelope"]["valid_until"]
        self.rehash(changed)
        with self.assertRaises(support.ValidationError): policy_handoff.validate(changed)


class SimulationExportReviewTests(TestCase):
    setUp = support.CompanyControlTests.setUp
    enroll = support.CompanyControlTests.enroll
    request = support.CompanyControlTests.request
    sensitive = support.CompanyControlTests.sensitive
    source = support.CompanyControlTests.source
    evidence = support.CompanyControlTests.evidence
    approve = support.CompanyControlTests.approve

    def test_simulation_handoff_is_a_controlled_response_not_a_live_record_crash(self):
        approval = self.approve()
        response = self.client.get(f"/pilots/{approval.reference}/handoff/")
        self.assertEqual(response.status_code, 200)
        value = response.json()
        self.assertFalse(value["routing_enabled"])
        self.assertFalse(value["portable_live_approval"])
        self.assertEqual(value["scope"], approval.data["receipt"]["scope"])
        self.assertTrue(any("simulation" in item["reason"].lower() for item in value["unsupported"]))
        self.assertTrue(all(item["envelope"] is None for item in value["model_bindings"]))
        self.assertEqual(policy_handoff.validate(value), value)
        self.assertEqual(ScopedSelectionRuntime.objects.count(), 0)

    def test_active_simulation_export_never_consults_live_provider_envelopes(self):
        approval = self.approve()
        self.sensitive(authorization.activate, approval.reference, "Activate existing simulation only")
        before = copy.deepcopy(PilotAuthorization.objects.get(pk=approval.pk).data)
        with patch("engine.company.policy_handoff.envelope_for", side_effect=AssertionError("Simulation must not resolve live provider mappings")):
            response = self.client.get(f"/pilots/{approval.reference}/handoff/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertFalse(response.json()["execution_credential"])
        self.assertTrue(all(item["envelope"] is None for item in response.json()["model_bindings"]))
        self.assertEqual(PilotAuthorization.objects.get(pk=approval.pk).data, before)
        self.assertEqual(ScopedSelectionRuntime.objects.count(), 0)

    def test_rejected_simulation_can_export_history_but_never_live_mappings(self):
        review = self.evidence()
        approval = self.sensitive(authorization.authorize, review.reference,
            {"pilot_id": "rejected-simulation", "repository_ref": "synthetic-repository", "task_types": ["documentation"],
             "developer_ids": ["junior"], "max_tasks": 1, "max_cost_usd": "0.10"},
            timezone.now() + timedelta(hours=1), "Reject synthetic pilot", Company.objects.get().revision, "simulation", "reject")
        value = policy_handoff.build(self.request(), approval.reference)
        self.assertFalse(value["portable_live_approval"])
        self.assertTrue(all(item["envelope"] is None for item in value["model_bindings"]))
        self.assertEqual(approval.data["receipt"]["routes"], [])

    def test_malformed_stored_simulation_handoff_is_refused_without_reset(self):
        approval = self.approve()
        changed = copy.deepcopy(approval.data)
        changed["receipt"]["scope"]["max_tasks"] = 0
        PilotAuthorization.objects.filter(pk=approval.pk).update(data=changed)
        response = self.client.get(f"/pilots/{approval.reference}/handoff/")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["routing_enabled"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(PilotAuthorization.objects.get(pk=approval.pk).data, changed)

    def test_nonreviewer_cannot_export_simulation_history(self):
        approval = self.approve()
        junior = support.LocalClient(); junior.force_login(self.junior)
        self.assertEqual(junior.get(f"/pilots/{approval.reference}/handoff/").status_code, 403)
