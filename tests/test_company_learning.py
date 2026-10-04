"""Joined published experimental learning, immutable future suggestions, and reversals."""

from unittest.mock import patch
import json

import test_company as support
from django.db import connections
from django.test import TestCase
from django.core.management import call_command
from django.utils import timezone

from engine.company import company_learning
from engine.company.models import Company, LearningPublication, CompanyTask, EvidenceReview
from engine.company.tasks import recommend_task, record_response, record_execution, record_result, task_ledger


def setUpModule():
    support.setUpModule()


def tearDownModule():
    connections.close_all()


class CompanyLearningTests(TestCase):
    setUp = support.CompanyControlTests.setUp
    enroll = support.CompanyControlTests.enroll
    request = support.CompanyControlTests.request
    sensitive = support.CompanyControlTests.sensitive
    source = support.CompanyControlTests.source
    evidence = support.CompanyControlTests.evidence
    developer_request = support.CompanyControlTests.developer_request

    def publish(self, review=None, expected=0):
        review = review or self.evidence()
        return self.sensitive(company_learning.change, "synthetic", expected, "Explicit experimental suggestions only",
                              review_ref=review.reference, repositories=["synthetic-repository"])

    def test_publication_binds_review_version_scope_and_cannot_authorize_pilot(self):
        publication = self.publish()
        self.assertEqual(publication.data["sequence"], 1)
        self.assertEqual(publication.data["learner_sha256"], publication.review.data["learner"]["learner_sha256"])
        self.assertEqual(company_learning.guard(publication, Company.objects.get())["status"], "current")
        self.assertEqual(support.PilotAuthorization.objects.count(), 0)
        self.assertEqual(support.AuthorizedPilot.objects.count(), 0)

    def test_future_manual_suggestion_uses_exact_published_learner_and_preserves_selection(self):
        publication = self.publish()
        task = recommend_task(self.junior, self.source(3))
        rec = task_ledger(task).recommendations[0]
        self.assertEqual(rec.learning["learner_sha256"], publication.data["learner_sha256"])
        self.assertEqual(rec.decision["recommended_model"], "fixture/cheap")
        self.assertEqual(rec.decision["effective_model"], "fixture/premium")
        self.assertEqual(rec.decision["confidence"], "low")
        self.assertEqual(task.suggestion_context["publication_ref"], str(publication.reference))
        another = recommend_task(self.senior, self.source(4))
        self.assertIsNotNone(task_ledger(another).recommendations[0].learning)

    def test_high_unknown_risk_or_unsupported_category_retains_learned_fallback(self):
        self.publish()
        for number, updates in ((3, {"risk_tags": ["high"]}), (4, {"task_type": "test_generation"}), (5, {"context_tokens": None})):
            task = recommend_task(self.junior, self.source(number, **updates))
            rec = task_ledger(task).recommendations[0]
            self.assertIn(rec.decision["recommended_model"], ("fixture/premium", None))
            self.assertEqual(rec.decision["effective_model"], "fixture/premium")

    def test_same_training_session_refuses_learned_use_without_losing_task(self):
        self.publish()
        task = recommend_task(self.senior, self.source(3, session_id="session-1"))
        rec = task_ledger(task).recommendations[0]
        self.assertIsNone(rec.learning)
        self.assertEqual(rec.decision["recommended_model"], "fixture/premium")
        self.assertEqual(task.suggestion_context["status"], "blocked")
        self.assertIsNotNone(rec.suggestion_refusal)

    def test_new_feedback_stales_publication_and_still_uses_safe_fallback(self):
        publication = self.publish()
        task = recommend_task(self.junior, self.source(3))
        record_response(self.junior, task.reference, "reject", task.revision)
        self.assertEqual(company_learning.guard(publication, Company.objects.get())["status"], "blocked")
        future = recommend_task(self.senior, self.source(4))
        self.assertIsNone(future.learning_snapshot)
        self.assertEqual(task_ledger(future).recommendations[0].decision["recommended_model"], "fixture/premium")
        task.refresh_from_db()
        self.assertEqual(len(task_ledger(task).responses), 1)

    def test_default_only_reversal_preserves_learned_historical_snapshots_and_retries(self):
        publication = self.publish()
        task = recommend_task(self.junior, self.source(3))
        before = task_ledger(task).to_dict()
        self.sensitive(company_learning.change, "synthetic", 1, "Stop experimental suggestions")
        self.assertEqual(task_ledger(task).to_dict(), before)
        self.assertEqual(recommend_task(self.junior, self.source(3)).reference, task.reference)
        new = recommend_task(self.junior, self.source(4))
        self.assertIsNone(new.learning_snapshot)
        self.assertEqual(len(company_learning.history(Company.objects.get(), "synthetic")), 2)

    def test_stale_publication_reversal_and_ordinary_developer_changes_refused(self):
        self.publish()
        with self.assertRaisesMessage(support.ValidationError, "changed"):
            self.sensitive(company_learning.change, "synthetic", 0, "Stale reversal")
        client = support.LocalClient(); client.force_login(self.junior)
        self.assertEqual(client.get("/learning/").status_code, 403)
        self.assertEqual(LearningPublication.objects.count(), 1)

    def test_removed_publisher_role_and_mfa_generation_refuse_future_learning(self):
        publication = self.publish()
        state = support.MFAState.objects.get(user=self.owner)
        state.generation += 1; state.save()
        self.assertEqual(company_learning.guard(publication, Company.objects.get())["status"], "blocked")
        task = recommend_task(self.junior, self.source(3))
        self.assertIsNone(task.learning_snapshot)

    def test_conflicting_version_and_source_label_cannot_be_published(self):
        review = self.evidence()
        with self.assertRaisesMessage(support.ValidationError, "different source"):
            self.sensitive(company_learning.change, "team", 0, "Wrong label", review_ref=review.reference, repositories=["synthetic-repository"])
        from engine.company.tasks import company_ledger
        ledger = company_ledger(Company.objects.get(), "synthetic")
        plan = dict(review.data["learner"]["plan"], min_senior_successes=3)
        other = support.authorization.prepare_review(self.request(), plan)
        with self.assertRaisesMessage(support.ValidationError, "conflicting artifacts"):
            self.publish(review)
        self.assertEqual(LearningPublication.objects.count(), 0)

    def test_browser_publishes_joined_review_with_actual_mfa_and_no_json(self):
        review = self.evidence()
        path = f"/learning/reviews/{review.reference}/publish/"
        self.assertContains(self.client.get(path), "Publish reviewed manual suggestions")
        device = support.TOTPDevice.objects.get(user=self.owner, confirmed=True)
        code, at = support.device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = self.client.post(path, {"confirm_password": support.PASSWORD, "code": code,
                "repositories": ["synthetic-repository"], "action": "publish", "expected_sequence": 0,
                "reason": "Browser artifact review", "confirmation": "on"})
        self.assertEqual(response.status_code, 302, response.content)
        self.assertContains(self.client.get("/learning/"), "synthetic-control-v1")
        self.assertEqual(LearningPublication.objects.count(), 1)

    def test_corrupt_publication_history_refused_not_reset(self):
        row = self.publish()
        row.data["sequence"] = 7; row.save()
        with self.assertRaisesMessage(support.ValidationError, "inconsistent"):
            recommend_task(self.junior, self.source(3))
        self.assertEqual(LearningPublication.objects.get().data["sequence"], 7)

    def test_additive_migration_and_no_external_model_calls(self):
        call_command("makemigrations", "company", dry_run=True, check=True, verbosity=0)
        with patch("socket.socket", side_effect=AssertionError("No network")), patch("subprocess.run", side_effect=AssertionError("No model/client")):
            self.publish()
            recommend_task(self.junior, self.source(3))

    def test_connected_new_task_receives_published_learner_and_gap_blocks_future_suggestions(self):
        from test_connectors import ConnectorTests
        _, value, browser = ConnectorTests.pair(self)
        publication = self.publish()
        source = ConnectorTests.task_source(self)
        response = ConnectorTests.api(self, value, "start", source)
        self.assertEqual(response.status_code, 200, response.content)
        state = response.json()
        self.assertEqual(state["learning"]["version"], "synthetic-control-v1")
        self.assertEqual(state["recommendation"]["effective_model"], "fixture/premium")
        event = ConnectorTests.event(self, state, kind="gap")
        self.assertEqual(ConnectorTests.api(self, value, "observation", event).status_code, 200)
        self.assertEqual(company_learning.guard(publication, Company.objects.get())["status"], "blocked")
        future = recommend_task(self.senior, self.source(4))
        self.assertIsNone(future.learning_snapshot)
        self.assertEqual(task_ledger(future).recommendations[0].decision["recommended_model"], "fixture/premium")

    def test_recorded_junior_failure_not_dropped_when_refitting_new_version(self):
        old = self.publish()
        task = recommend_task(self.junior, self.source(3))
        task = record_response(self.junior, task.reference, "accept", task.revision)
        task = record_execution(self.junior, task.reference, "fixture/cheap", task.revision)
        record_result(self.junior, task.reference, {"desired_result": False, "tests_passed": False, "score": None,
            "cost_usd": "0.01", "latency_ms": None, "evidence_ref": "synthetic-junior-failure", "supersedes": None}, task.revision)
        from engine.company.tasks import company_ledger
        ledger = company_ledger(Company.objects.get(), "synthetic")
        plan = dict(old.review.data["learner"]["plan"], learner_version="synthetic-refit-v2", cutoff=timezone.now().isoformat(),
                    session_ids=[rec.task.session_id for rec in ledger.recommendations])
        review = support.authorization.prepare_review(self.request(), plan)
        self.assertEqual(review.data["report"]["categories"][0]["status"], "blocked")
        self.assertEqual(review.data["report"]["categories"][0]["evidence"][0]["non_senior_failures"], 1)
        self.publish(review, expected=1)
        task = recommend_task(self.senior, self.source(4))
        self.assertEqual(task_ledger(task).recommendations[0].decision["recommended_model"], "fixture/premium")
