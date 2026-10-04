import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from engine.cli import main
from engine.feedback import FeedbackStore, _fingerprint, import_scenario
from engine.importers import load_policy, parse_json
from engine.learning import LearningPlan, fit_feedback
from engine.readiness import (
    ApproverRoster, PilotReview, PilotScope, ReadinessReport, build_readiness,
    load_pilot_review, load_readiness, review_pilot,
)
from engine.schemas import ValidationError


FIXTURES = Path(__file__).parent / "fixtures"


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        self.ledger = import_scenario(parse_json((FIXTURES / "feedback-demo.json").read_text()), self.policy)
        self.plan = LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text()))
        self.learner = fit_feedback(self.ledger, self.policy, self.plan)
        self.report = build_readiness(self.ledger, self.policy, self.learner)

    def category(self, name, report=None):
        return next(item for item in (report or self.report).data["categories"] if item["task_type"] == name)

    def test_ready_category_is_local_review_only_and_gaps_remain_visible(self):
        docs = self.category("documentation")
        self.assertEqual(docs["status"], "ready_for_local_review")
        self.assertEqual(docs["suggested_model"], "fixture/cheap")
        self.assertEqual(docs["gaps"]["pending_executions"], 1)
        self.assertEqual(docs["gaps"]["accepted_but_different_model"], 1)
        self.assertEqual(self.report.data["counts"]["pending_executions"], 2)
        self.assertEqual(len(self.report.data["observations"]), 7)
        self.assertEqual(self.report.data["observations"][5]["score"], "0.7")
        self.assertEqual(self.report.data["observations"][5]["cost_usd"], "0.03")
        self.assertEqual(len(self.report.data["result_history"]), 5)
        self.assertFalse(self.report.data["deployment_ready"])
        self.assertFalse(self.report.data["deployment_authorized"])

    def test_junior_failure_and_senior_rejection_keep_category_blocked(self):
        tests = self.category("test_generation")
        self.assertEqual(tests["status"], "blocked")
        self.assertIsNone(tests["suggested_model"])
        self.assertTrue(any("failures" in reason for reason in tests["blockers"]))
        self.assertTrue(any("rejections" in reason for reason in tests["blockers"]))
        self.assertEqual(tests["evidence"][0]["non_senior_failures"], 1)

    def test_readiness_does_not_mutate_feedback_learner_or_policy(self):
        original = self.ledger.to_dict()
        model = self.learner.to_dict()
        policy = self.policy.to_dict()
        build_readiness(self.ledger, self.policy, self.learner)
        self.assertEqual(self.ledger.to_dict(), original)
        self.assertEqual(self.learner.to_dict(), model)
        self.assertEqual(self.policy.to_dict(), policy)

    def test_report_is_deterministic_and_roundtrips(self):
        self.assertEqual(self.report.to_dict(), build_readiness(self.ledger, self.policy, self.learner).to_dict())
        self.assertEqual(ReadinessReport.from_dict(self.report.to_dict()), self.report)
        self.assertEqual(self.report.data["feedback_sha256"], self.learner.source_sha256)

    def test_stale_feedback_blocks_review_report_not_silently_ignoring_correction(self):
        old = self.ledger.results[0]
        correction = replace(old, result_id="later-negative", timestamp="2026-10-04T09:00:00Z", desired_result=False,
                             tests_passed=False, score=None, supersedes=old.result_id)
        ledger = replace(self.ledger, results=self.ledger.results + (correction,))
        report = build_readiness(ledger, self.policy, self.learner)
        self.assertEqual(report.data["source_status"], "blocked")
        self.assertEqual(self.category("documentation", report)["status"], "blocked")
        self.assertEqual(report.data["counts"]["result_revisions"], 6)
        self.assertEqual(report.data["observed_through"], "2026-10-04T09:00:00Z")

    def test_changed_policy_cannot_reuse_old_ready_report(self):
        policy = replace(self.policy, policy_version="changed-v2", rules=())
        report = build_readiness(self.ledger, policy, self.learner)
        self.assertEqual(report.data["source_status"], "blocked")
        self.assertEqual(self.category("documentation", report)["status"], "blocked")
        with self.assertRaisesRegex(ValidationError, "no longer matches"):
            self.report.verify(self.ledger, policy, self.learner)

    def test_wrong_policy_learner_or_feedback_fingerprint_cannot_pass_verification(self):
        for field in ("policy_sha256", "learner_sha256", "feedback_sha256"):
            with self.subTest(field=field):
                data = copy.deepcopy(self.report.to_dict())
                data[field] = "0" * 64
                payload = {key: value for key, value in data.items() if key != "report_sha256"}
                data["report_sha256"] = _fingerprint(payload)
                altered = ReadinessReport.from_dict(data)
                with self.assertRaises(ValidationError):
                    altered.verify(self.ledger, self.policy, self.learner)

    def test_structural_contract_refuses_forged_readiness_with_new_hash(self):
        changes = (
            lambda data: data.update(deployment_ready=True),
            lambda data: data.update(deployment_authorized=True),
            lambda data: data.update(local_only=False),
            lambda data: data.update(schema_version=True),
            lambda data: data["categories"][1].update(status="ready_for_local_review", suggested_model="fixture/standard", blockers=[]),
            lambda data: data["categories"][0]["evidence"][0].update(confirmed_failures=1),
            lambda data: data["categories"][0].update(evidence=[]),
            lambda data: data["categories"].append(copy.deepcopy(data["categories"][0])),
            lambda data: data["counts"].update(executions=7),
        )
        for change in changes:
            with self.subTest(change=change):
                data = copy.deepcopy(self.report.to_dict())
                change(data)
                data["report_sha256"] = _fingerprint({key: value for key, value in data.items() if key != "report_sha256"})
                with self.assertRaises(ValidationError):
                    ReadinessReport.from_dict(data)

    def test_report_export_is_private_and_never_overwrites(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-readiness-file-") as directory:
            path = Path(directory) / "review.json"
            self.report.export(path)
            self.assertEqual(load_readiness(path), self.report)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                self.report.export(path)
            self.assertEqual(path.read_bytes(), original)


class PilotReviewTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        self.ledger = import_scenario(parse_json((FIXTURES / "feedback-demo.json").read_text()), self.policy)
        self.plan = LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text()))
        self.learner = fit_feedback(self.ledger, self.policy, self.plan)
        self.report = build_readiness(self.ledger, self.policy, self.learner)
        self.scope = PilotScope.from_dict(parse_json((FIXTURES / "pilot-scope.json").read_text()))
        self.approvers = ApproverRoster.from_dict(parse_json((FIXTURES / "pilot-approvers.json").read_text()))

    def review(self, reviewer="synthetic-senior", decision="approve", scope=None, report=None,
               timestamp="2026-10-04T12:00:00Z", reason="Synthetic local simulation only"):
        return review_pilot(report or self.report, scope or self.scope, self.approvers, reviewer, decision,
                            timestamp, reason, self.ledger, self.policy, self.learner)

    def test_separate_senior_approval_is_limited_to_local_simulation(self):
        review = self.review()
        self.assertEqual(review.data["decision"], "approve")
        self.assertTrue(review.data["approved_for_local_simulation"])
        self.assertFalse(review.data["routing_enabled"])
        self.assertFalse(review.data["deployment_authorized"])
        self.assertFalse(review.data["limits_enforced"])
        self.assertEqual(review.data["reviewer_identity_source"], "declared_local_allowlist_unverified")
        self.assertEqual(review.data["routes"], [{"task_type": "documentation", "model": "fixture/cheap"}])
        self.assertEqual(review.data["scope"]["developer_ids"], ["synthetic-senior", "synthetic-junior"])
        self.assertEqual(PilotReview.from_dict(review.to_dict()), review)

    def test_designated_admin_can_review_without_being_a_task_feedback_developer(self):
        review = self.review(reviewer="synthetic-admin")
        self.assertEqual(review.data["reviewer_role"], "admin")
        self.assertFalse(review.data["deployment_authorized"])

    def test_seniority_or_task_acceptance_alone_does_not_grant_pilot_authority(self):
        for reviewer in ("synthetic-junior", "synthetic-other-senior", "not-designated"):
            with self.subTest(reviewer=reviewer):
                with self.assertRaisesRegex(ValidationError, "explicitly designated"):
                    self.review(reviewer=reviewer)

    def test_blocked_category_cannot_be_approved_even_for_simulation(self):
        with self.assertRaisesRegex(ValidationError, "blocked category"):
            self.review(scope=replace(self.scope, task_types=("test_generation",)))
        with self.assertRaises(ValidationError):
            self.review(scope=replace(self.scope, task_types=("documentation", "test_generation")))

    def test_scope_cannot_add_unknown_categories_or_unapproved_developers(self):
        for scope in (replace(self.scope, task_types=("authentication",)),
                      replace(self.scope, developer_ids=("outside-roster",))):
            with self.subTest(scope=scope):
                with self.assertRaises(ValidationError):
                    self.review(scope=scope)

    def test_reject_can_record_blocked_category_without_creating_routes(self):
        review = self.review(decision="reject", scope=replace(self.scope, task_types=("test_generation",)))
        self.assertEqual(review.data["routes"], [])
        self.assertFalse(review.data["approved_for_local_simulation"])
        self.assertEqual(review.data["decision"], "reject")

    def test_review_time_and_reason_must_be_explicit_and_consistent(self):
        for timestamp, reason in (("2026-10-03T16:00:00Z", "Before fitting"),
                                  ("2026-10-04", "No timezone"), ("2026-10-04T12:00:00Z", "")):
            with self.subTest(timestamp=timestamp, reason=reason):
                with self.assertRaises(ValidationError):
                    self.review(timestamp=timestamp, reason=reason)

    def test_changed_evidence_after_report_generation_cannot_be_approved(self):
        old = self.ledger.results[0]
        self.ledger = replace(self.ledger, results=self.ledger.results + (
            replace(old, result_id="late-failure", timestamp="2026-10-04T09:00:00Z", desired_result=False,
                    tests_passed=False, score=None, supersedes=old.result_id),
        ))
        with self.assertRaisesRegex(ValidationError, "no longer matches"):
            self.review()

    def test_new_receipt_hash_cannot_enable_routing_or_expand_routes(self):
        original = self.review().to_dict()
        for update in ({"routing_enabled": True}, {"deployment_authorized": True}, {"approved_for_local_simulation": False},
                       {"reviewer_role": "junior"}, {"routes": [{"task_type": "authentication", "model": "fixture/cheap"}]}):
            with self.subTest(update=update):
                data = copy.deepcopy(original)
                data.update(update)
                data["review_sha256"] = _fingerprint({key: value for key, value in data.items() if key != "review_sha256"})
                with self.assertRaises(ValidationError):
                    PilotReview.from_dict(data)

    def test_scope_requires_positive_limits_and_no_wildcards(self):
        for updates in ({"max_tasks": 0}, {"max_cost_usd": "0"}, {"max_cost_usd": "NaN"},
                        {"task_types": ["*"]}, {"developer_ids": []}, {"repository_ref": ""}):
            with self.subTest(updates=updates):
                with self.assertRaises(ValidationError):
                    PilotScope.from_dict(dict(self.scope.to_dict(), **updates))

    def test_approver_roster_is_distinct_validated_metadata_not_authenticated_identity(self):
        for updates in (
            {"approvers": []},
            {"approvers": [{"approver_id": "one", "role": "junior", "can_approve_pilots": True}]},
            {"approvers": [{"approver_id": "one", "role": "senior", "can_approve_pilots": "true"}]},
        ):
            with self.subTest(updates=updates):
                with self.assertRaises(ValidationError):
                    ApproverRoster.from_dict(updates)
        data = self.approvers.to_dict()
        data["approvers"].append(copy.deepcopy(data["approvers"][0]))
        with self.assertRaises(ValidationError):
            ApproverRoster.from_dict(data)

    def test_receipt_export_preserves_existing_file_and_policy_feedback_states(self):
        original = self.ledger.to_dict()
        policy = self.policy.to_dict()
        review = self.review()
        with tempfile.TemporaryDirectory(prefix="tarkado-pilot-review-file-") as directory:
            path = Path(directory) / "approval.json"
            review.export(path)
            self.assertEqual(load_pilot_review(path), review)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            old = path.read_bytes()
            with self.assertRaises(FileExistsError):
                review.export(path)
            self.assertEqual(path.read_bytes(), old)
        self.assertEqual(self.ledger.to_dict(), original)
        self.assertEqual(self.policy.to_dict(), policy)


class ReadinessCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-review-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.store = self.directory / "feedback"
        self.policy = load_policy(FIXTURES / "policy.json")
        ledger = import_scenario(parse_json((FIXTURES / "feedback-demo.json").read_text()), self.policy)
        FeedbackStore(self.store).import_ledger(ledger)
        learner = fit_feedback(ledger, self.policy, LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text())))
        self.learner_path = self.directory / "learner.json"
        learner.export(self.learner_path)
        self.report_path = self.directory / "readiness.json"
        self.review_path = self.directory / "pilot-review.json"

    def run_cli(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(arguments + ["--store", str(self.store)])
        return code, json.loads(output.getvalue()) if output.getvalue() else None, error.getvalue()

    def readiness_args(self):
        return ["feedback", "readiness", "--policy", str(FIXTURES / "policy.json"),
                "--learner", str(self.learner_path), "--output", str(self.report_path)]

    def review_args(self):
        return ["pilot", "review", "--report", str(self.report_path), "--policy", str(FIXTURES / "policy.json"),
                "--learner", str(self.learner_path), "--scope", str(FIXTURES / "pilot-scope.json"),
                "--approvers", str(FIXTURES / "pilot-approvers.json"), "--reviewer", "synthetic-senior",
                "--decision", "approve", "--timestamp", "2026-10-04T12:00:00Z", "--reason", "Synthetic local review only",
                "--local-simulation", "--output", str(self.review_path)]

    def test_cli_readiness_and_separate_review_run_without_network_or_execution(self):
        before = (self.store / "feedback.json").read_bytes()
        with patch("socket.socket", side_effect=AssertionError("No network allowed")), patch("subprocess.run", side_effect=AssertionError("No execution allowed")):
            code, report, _ = self.run_cli(self.readiness_args())
            self.assertEqual(code, 0)
            self.assertFalse(report["deployment_ready"])
            self.assertFalse(report["deployment_authorized"])
            code, receipt, _ = self.run_cli(self.review_args())
        self.assertEqual(code, 0)
        self.assertTrue(receipt["approved_for_local_simulation"])
        self.assertFalse(receipt["routing_enabled"])
        self.assertFalse(receipt["deployment_authorized"])
        self.assertEqual((self.store / "feedback.json").read_bytes(), before)

    def test_cli_wrong_reviewer_does_not_publish_receipt(self):
        self.run_cli(self.readiness_args())
        args = self.review_args()
        args[args.index("--reviewer") + 1] = "synthetic-junior"
        code, data, error = self.run_cli(args)
        self.assertEqual(code, 2)
        self.assertIsNone(data)
        self.assertIn("explicitly designated", error)
        self.assertFalse(self.review_path.exists())

    def test_cli_requires_acknowledgement_of_local_only_approval(self):
        args = self.review_args()
        args.remove("--local-simulation")
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                main(args)
        self.assertEqual(result.exception.code, 2)
        self.assertFalse(self.review_path.exists())

    def test_cli_refuses_existing_reports_and_receipts_without_overwrite(self):
        self.run_cli(self.readiness_args())
        original = self.report_path.read_bytes()
        code, data, _ = self.run_cli(self.readiness_args())
        self.assertEqual(code, 2)
        self.assertIsNone(data)
        self.assertEqual(self.report_path.read_bytes(), original)
        self.run_cli(self.review_args())
        original = self.review_path.read_bytes()
        code, data, _ = self.run_cli(self.review_args())
        self.assertEqual(code, 2)
        self.assertIsNone(data)
        self.assertEqual(self.review_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
