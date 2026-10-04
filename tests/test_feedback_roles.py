import copy
import tempfile
import unittest
from pathlib import Path

from engine.feedback import FeedbackLedger, FeedbackStore, RoleAttribution, TaskRequest, feedback_summary, import_scenario
from engine.importers import load_policy, parse_json
from engine.learning import LearningPlan, _source_digest, fit_feedback
from engine.schemas import ValidationError


FIXTURES = Path(__file__).parent / "fixtures"


class HistoricalRoleTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        self.legacy = import_scenario(parse_json((FIXTURES / "feedback-demo.json").read_text()), self.policy)
        self.data = self.legacy.to_dict()
        self.data["schema_version"] = 2
        self.data["role_attributions"] = []
        for kind, records in (("recommendation", self.legacy.recommendations), ("response", self.legacy.responses),
                              ("execution", self.legacy.executions), ("result", self.legacy.results)):
            for record in records:
                identifier = record.task.developer_id if kind == "recommendation" else getattr(record, "reviewer_id" if kind == "result" else "developer_id")
                record_id = record.recommendation_id if kind in ("recommendation", "response") else getattr(record, kind + "_id")
                self.data["role_attributions"].append(RoleAttribution(kind, record_id, identifier, self.legacy.team.role(identifier)).to_dict())

    def test_legacy_format_and_counts_remain_unchanged(self):
        self.assertEqual(FeedbackLedger.from_dict(self.legacy.to_dict()), self.legacy)
        self.assertEqual(tuple(self.legacy.to_dict()), ("schema_version", "team", "policies", "recommendations", "responses", "executions", "results"))
        report = feedback_summary(self.legacy, self.policy)
        self.assertEqual(report["roles_source"], "declared_local_roster_unverified")
        self.assertFalse(report["deployment_authorized"])

    def test_schema_two_roundtrips_and_agrees_with_legacy_counts_when_roles_match(self):
        ledger = FeedbackLedger.from_dict(self.data)
        self.assertEqual(ledger.to_dict(), self.data)
        self.assertEqual(feedback_summary(ledger, self.policy)["groups"], feedback_summary(self.legacy, self.policy)["groups"])
        self.assertEqual(feedback_summary(ledger, self.policy)["roles_source"], "declared_event_role_attributions_unverified")

    def test_schema_two_requires_exact_complete_nonduplicated_role_coverage(self):
        for change in (
            lambda data: data["role_attributions"].pop(),
            lambda data: data["role_attributions"].append(data["role_attributions"][0]),
            lambda data: data["role_attributions"][0].update(developer_id="another-developer"),
            lambda data: data["role_attributions"][0].update(record_id="missing-record"),
            lambda data: data["role_attributions"][0].update(role="admin"),
        ):
            with self.subTest(change=change):
                data = copy.deepcopy(self.data)
                change(data)
                with self.assertRaises(ValidationError):
                    FeedbackLedger.from_dict(data)

    def test_schema_one_cannot_silently_accept_event_roles_and_schema_two_cannot_omit_them(self):
        data = dict(self.data, schema_version=1)
        with self.assertRaises(ValidationError):
            FeedbackLedger.from_dict(data)
        data = dict(self.legacy.to_dict(), schema_version=2)
        with self.assertRaises(ValidationError):
            FeedbackLedger.from_dict(data)

    def test_current_roster_promotion_cannot_relabel_historical_junior_failures(self):
        self.data["team"]["members"][1]["role"] = "senior"
        ledger = FeedbackLedger.from_dict(self.data)
        group = next(item for item in feedback_summary(ledger, self.policy)["groups"] if item["task_type"] == "test_generation")
        self.assertEqual(group["non_senior_failures"], 1)
        self.assertEqual(group["confirmed_failures"], 1)
        self.assertEqual(group["status"], "investigate_failures")

    def test_response_role_and_reviewer_role_are_record_specific(self):
        target = self.legacy.recommendations[0].recommendation_id
        for attribution in self.data["role_attributions"]:
            if attribution["record_kind"] == "response" and attribution["record_id"] == target:
                attribution["role"] = "junior"
        report = feedback_summary(FeedbackLedger.from_dict(self.data), self.policy)
        group = next(item for item in report["groups"] if item["model"] == "fixture/cheap")
        self.assertEqual(group["senior_adopted_successes"], 1)
        self.assertEqual(group["senior_accepts"], 3)
        self.assertEqual(group["confirmed_successes"], 2)

    def test_historical_result_review_role_is_not_inferred_from_current_directory(self):
        self.data["team"]["members"][0]["role"] = "junior"
        report = feedback_summary(FeedbackLedger.from_dict(self.data), self.policy)
        self.assertEqual(report["result_history"][0]["reviewer_role"], "senior")
        self.assertTrue(report["tasks"][0]["senior_confirmed"])

    def test_experimental_learner_retains_role_snapshots_through_cutoff_projection(self):
        ledger = FeedbackLedger.from_dict(self.data)
        plan = LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text()))
        learner = fit_feedback(ledger, self.policy, plan)
        self.assertEqual(learner.counts["recommendations"], 7)
        self.assertEqual(learner.payload()["rules"][0]["recommended_model"], "fixture/cheap")
        learner.verify_source(ledger)
        self.assertFalse(learner.payload()["deployment_authorized"])

    def test_role_snapshot_edits_change_source_and_make_old_learner_stale(self):
        ledger = FeedbackLedger.from_dict(self.data)
        plan = LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text()))
        learner = fit_feedback(ledger, self.policy, plan)
        self.data["role_attributions"][0]["role"] = "junior"
        changed = FeedbackLedger.from_dict(self.data)
        self.assertNotEqual(_source_digest(ledger), _source_digest(changed))
        with self.assertRaises(ValidationError):
            learner.verify_source(changed)

    def test_source_digest_does_not_depend_on_role_snapshot_array_order(self):
        ledger = FeedbackLedger.from_dict(self.data)
        self.data["role_attributions"].reverse()
        self.assertEqual(_source_digest(ledger), _source_digest(FeedbackLedger.from_dict(self.data)))

    def test_legacy_recommendation_writer_cannot_drop_historical_role_snapshots(self):
        ledger = FeedbackLedger.from_dict(self.data)
        task_data = self.legacy.recommendations[0].task.to_dict()
        task_data.update(task_id="future-task", session_id="future-session", timestamp="2026-10-05T12:00:00Z")
        with tempfile.TemporaryDirectory(prefix="tarkado-role-history-") as directory:
            store = FeedbackStore(Path(directory) / "feedback")
            store.import_ledger(ledger)
            before = store.path.read_bytes()
            with self.assertRaises(ValidationError):
                store.recommend(TaskRequest.from_dict(task_data), self.policy)
            self.assertEqual(store.path.read_bytes(), before)
            self.assertEqual(store.read().role_attributions, ledger.role_attributions)
