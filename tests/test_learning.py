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
from engine.feedback import FeedbackLedger, FeedbackStore, TaskRequest, _policy_input, import_scenario
from engine.importers import load_policy, parse_json
from engine.learning import LearnedModel, LearningPlan, fit_feedback, learned_decision, load_learner
from engine.policy import decide
from engine.schemas import ValidationError


FIXTURES = Path(__file__).parent / "fixtures"


class LearnerTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        self.scenario = parse_json((FIXTURES / "feedback-demo.json").read_text())
        self.ledger = import_scenario(self.scenario, self.policy)
        self.plan = LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text()))
        self.docs_task = TaskRequest.from_dict(parse_json((FIXTURES / "learning-docs-task.json").read_text()))
        self.tests_task = TaskRequest.from_dict(parse_json((FIXTURES / "learning-tests-task.json").read_text()))
        self.model = fit_feedback(self.ledger, self.policy, self.plan)

    def rule(self, category, model=None):
        return next(item for item in (model or self.model).to_dict()["rules"] if item["task_type"] == category)

    def test_fit_learns_docs_and_withholds_failed_test_category(self):
        self.assertEqual(self.rule("documentation")["recommended_model"], "fixture/cheap")
        self.assertEqual(self.rule("test_generation")["status"], "withheld")
        self.assertIsNone(self.rule("test_generation")["recommended_model"])
        group = next(item for item in self.model.evidence if item["model"] == "fixture/cheap")
        self.assertEqual(group["accepts"], 4)
        self.assertEqual(group["senior_adopted_successes"], 2)
        self.assertEqual(group["executions"], 2)
        self.assertEqual(group["senior_success_sessions"], 2)

    def test_junior_failure_and_senior_rejection_veto_even_a_low_declared_gate(self):
        model = fit_feedback(self.ledger, self.policy, replace(self.plan, min_senior_successes=1, min_senior_sessions=1))
        self.assertIsNone(self.rule("test_generation", model)["recommended_model"])
        reasons = self.rule("test_generation", model)["candidates"][0]["reasons"]
        self.assertTrue(any("failures" in reason for reason in reasons))
        self.assertTrue(any("rejections" in reason for reason in reasons))

    def test_future_docs_manual_suggestion_preserves_original_model_and_low_confidence(self):
        decision = learned_decision(self.docs_task, self.policy, self.model)
        self.assertEqual(decision.recommended_model, "fixture/cheap")
        self.assertEqual(decision.effective_model, "fixture/premium")
        self.assertEqual(decision.enforcement, "shadow")
        self.assertEqual(decision.confidence, "low")
        self.assertIn("2 accepted/used/senior-confirmed", decision.reason)
        self.assertEqual(decision.evidence_refs[0], "learner:" + self.model.sha256)

    def test_feedback_changes_future_suggestion_where_static_rule_ignores_failure(self):
        static = decide(self.policy, _policy_input(self.tests_task, self.policy), "shadow")
        learned = learned_decision(self.tests_task, self.policy, self.model)
        self.assertEqual(static.recommended_model, "fixture/standard")
        self.assertEqual(learned.recommended_model, "fixture/premium")
        self.assertTrue(learned.used_fallback)
        self.assertEqual(learned.effective_model, self.tests_task.selected_model)

    def test_learning_can_propose_model_without_an_existing_static_task_rule(self):
        policy = replace(self.policy, policy_version="synthetic-no-rules-v1", rules=())
        model = fit_feedback(self.ledger, policy, self.plan)
        static = decide(policy, _policy_input(self.docs_task, policy), "shadow")
        learned = learned_decision(self.docs_task, policy, model)
        self.assertEqual(static.recommended_model, "fixture/premium")
        self.assertEqual(learned.recommended_model, "fixture/cheap")

    def test_holdout_data_cannot_be_used_by_fit_command(self):
        original = self.plan.to_dict()
        for split in ("test", "training", "unknown"):
            with self.subTest(split=split):
                with self.assertRaisesRegex(ValidationError, "validation data only"):
                    LearningPlan.from_dict(dict(original, dataset_split=split))

    def test_invalid_missing_or_automatic_gate_fields_are_rejected(self):
        for updates in ({"min_senior_successes": 0}, {"min_senior_sessions": True}, {"session_ids": []},
                        {"task_types": ["*"]}, {"source_kind": "public_benchmark"}, {"cutoff": "2026-10-03"},
                        {"enable_routing": True}):
            with self.subTest(updates=updates):
                with self.assertRaises(ValidationError):
                    LearningPlan.from_dict(dict(self.plan.to_dict(), **updates))
        data = self.plan.to_dict()
        del data["min_senior_successes"]
        with self.assertRaises(ValidationError):
            LearningPlan.from_dict(data)

    def test_predeclared_parameters_are_preserved_without_tuning_to_outcomes(self):
        plan = replace(self.plan, min_senior_successes=3, min_senior_sessions=3)
        model = fit_feedback(self.ledger, self.policy, plan)
        self.assertEqual(model.plan, plan)
        self.assertIsNone(self.rule("documentation", model)["recommended_model"])

    def test_cutoff_does_not_credit_later_successes(self):
        plan = replace(self.plan, session_ids=("synthetic-session-1",), task_types=("documentation",),
                       cutoff="2026-10-03T10:02:00Z", min_senior_successes=1, min_senior_sessions=1)
        model = fit_feedback(self.ledger, self.policy, plan)
        self.assertEqual(model.counts["executions"], 1)
        self.assertEqual(model.counts["current_results"], 0)
        self.assertEqual(model.counts["pending_results"], 1)
        self.assertIsNone(self.rule("documentation", model)["recommended_model"])

    def test_absent_session_and_no_records_at_cutoff_are_not_silently_ignored(self):
        for plan in (replace(self.plan, session_ids=("absent-session",)),
                     replace(self.plan, cutoff="2026-10-03T09:00:00Z")):
            with self.subTest(plan=plan):
                with self.assertRaises(ValidationError):
                    fit_feedback(self.ledger, self.policy, plan)

    def test_learned_suggestions_refuse_in_sample_session_or_past_time(self):
        for task in (replace(self.docs_task, session_id="synthetic-session-1"),
                     replace(self.docs_task, timestamp=self.plan.cutoff)):
            with self.subTest(task=task):
                with self.assertRaisesRegex(ValidationError, "future task"):
                    learned_decision(task, self.policy, self.model)

    def test_unknown_high_risk_tools_and_context_fall_back_without_switching(self):
        for changes in ({"task_type": "authentication"}, {"task_type": None}, {"risk_tags": ("high",)},
                        {"required_tools": ("edit",)}, {"context_tokens": 9000}):
            with self.subTest(changes=changes):
                task = replace(self.docs_task, **changes)
                decision = learned_decision(task, self.policy, self.model)
                self.assertTrue(decision.used_fallback)
                self.assertEqual(decision.recommended_model, "fixture/premium")
                self.assertEqual(decision.effective_model, "fixture/premium")
        blocked = learned_decision(replace(self.docs_task, context_tokens=None), self.policy, self.model)
        self.assertIsNone(blocked.recommended_model)
        self.assertEqual(blocked.effective_model, self.docs_task.selected_model)

    def test_changed_policy_or_revoked_model_is_not_enabled_by_old_learner(self):
        changed = replace(self.policy, policy_version="changed-v2", models=(replace(self.policy.models[0], status="disabled"),) + self.policy.models[1:])
        decision = learned_decision(self.docs_task, changed, self.model)
        self.assertTrue(decision.used_fallback)
        self.assertEqual(decision.recommended_model, "fixture/premium")
        self.assertEqual(decision.effective_model, self.docs_task.selected_model)

    def test_fixed_data_reordering_cannot_change_fitted_artifact(self):
        reversed_scenario = copy.deepcopy(self.scenario)
        reversed_scenario["tasks"].reverse()
        other = fit_feedback(import_scenario(reversed_scenario, self.policy), self.policy, self.plan)
        self.assertEqual(other.to_dict(), self.model.to_dict())

    def test_fitting_does_not_modify_ledger_roster_or_policy(self):
        before = self.ledger.to_dict()
        policy_before = self.policy.to_dict()
        fit_feedback(self.ledger, self.policy, self.plan)
        self.assertEqual(self.ledger.to_dict(), before)
        self.assertEqual(self.policy.to_dict(), policy_before)
        self.assertFalse(self.model.to_dict()["deployment_authorized"])

    def test_artifact_contract_and_fingerprint_reject_altered_rules_or_enablement(self):
        for changes in ({"algorithm": "automatic-router"}, {"confidence": "high"}, {"deployment_authorized": True},
                        {"learner_sha256": "0" * 64}, {"rules": []}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    LearnedModel.from_dict(dict(self.model.to_dict(), **changes))

    def test_same_source_hash_cannot_be_used_to_forge_evidence_counts(self):
        evidence = copy.deepcopy(list(self.model.evidence))
        evidence[0].update(senior_adopted_successes=1, senior_success_sessions=1)
        forged = replace(self.model, evidence=tuple(evidence))
        LearnedModel.from_dict(forged.to_dict())
        with self.assertRaisesRegex(ValidationError, "actual source records"):
            forged.verify_source(self.ledger)

    def test_roster_mismatch_and_different_source_store_are_rejected(self):
        modified = replace(self.ledger, team=replace(self.ledger.team,
                           members=(("synthetic-senior", "developer"), ("synthetic-junior", "junior"))))
        with self.assertRaises(ValidationError):
            self.model.verify_source(modified)
        other = import_scenario(dict(self.scenario, tasks=self.scenario["tasks"][:-1]), self.policy)
        with self.assertRaises(ValidationError):
            self.model.verify_source(other)

    def test_selected_senior_only_fitting_subset_cannot_hide_existing_junior_failure(self):
        plan = replace(self.plan, session_ids=("synthetic-session-5",), task_types=("test_generation",),
                       min_senior_successes=1, min_senior_sessions=1)
        model = fit_feedback(self.ledger, self.policy, plan)
        self.assertEqual(self.rule("test_generation", model)["recommended_model"], "fixture/standard")
        with self.assertRaisesRegex(ValidationError, "failures=1, rejects=1"):
            model.verify_source(self.ledger)

    def test_fresh_result_correction_requires_refitting_before_more_suggestions(self):
        correction = replace(self.ledger.results[0], result_id="later-failure", timestamp="2026-10-04T09:00:00Z",
                             desired_result=False, tests_passed=False, score=None,
                             supersedes=self.ledger.results[0].result_id)
        changed = replace(self.ledger, results=self.ledger.results + (correction,))
        with self.assertRaisesRegex(ValidationError, "arrived after fitting"):
            self.model.verify_source(changed)
        updated = fit_feedback(changed, self.policy, replace(self.plan, learner_version="refit-v2", cutoff="2026-10-04T09:01:00Z"))
        self.assertIsNone(self.rule("documentation", updated)["recommended_model"])

    def test_private_artifact_export_is_immutable_and_roundtrips(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-learned-file-") as directory:
            path = Path(directory) / "learner.json"
            self.model.export(path)
            self.assertEqual(load_learner(path), self.model)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                self.model.export(path)
            self.assertEqual(path.read_bytes(), original)


class LearnedFeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-learned-store-")
        self.addCleanup(self.temporary.cleanup)
        self.store = FeedbackStore(Path(self.temporary.name) / "feedback")
        self.policy = load_policy(FIXTURES / "policy.json")
        self.ledger = import_scenario(parse_json((FIXTURES / "feedback-demo.json").read_text()), self.policy)
        self.plan = LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text()))
        self.model = fit_feedback(self.ledger, self.policy, self.plan)
        self.task = TaskRequest.from_dict(parse_json((FIXTURES / "learning-docs-task.json").read_text()))
        self.store.import_ledger(self.ledger)

    def test_future_learned_recommendation_is_saved_and_roundtrips_with_snapshot(self):
        rec = self.store.recommend(self.task, self.policy, self.model.to_dict())
        self.assertEqual(rec.decision["recommended_model"], "fixture/cheap")
        self.assertEqual(rec.decision["effective_model"], "fixture/premium")
        self.assertEqual(rec.learning["learner_sha256"], self.model.sha256)
        loaded = self.store.read()
        self.assertEqual(FeedbackLedger.from_dict(loaded.to_dict()), loaded)
        self.assertEqual(len(loaded.recommendations), 8)

    def test_learned_response_and_result_remain_linked_without_rewriting_old_decision(self):
        rec = self.store.recommend(self.task, self.policy, self.model.to_dict())
        self.store.record("response", {"recommendation_id": rec.recommendation_id, "developer_id": "synthetic-junior",
                                      "timestamp": "2026-10-04T10:01:00Z", "response": "accept"})
        self.store.record("execution", {"execution_id": "learned-exec", "recommendation_id": rec.recommendation_id,
                                       "developer_id": "synthetic-junior", "timestamp": "2026-10-04T10:02:00Z", "actual_model": "fixture/cheap"})
        self.store.record("result", {"result_id": "learned-result", "execution_id": "learned-exec", "reviewer_id": "synthetic-senior",
                                    "timestamp": "2026-10-04T10:03:00Z", "desired_result": True, "tests_passed": None,
                                    "score": "1", "cost_usd": "0.006", "latency_ms": 200, "evidence_ref": "synthetic:learned-use", "supersedes": None})
        loaded = self.store.read()
        self.assertEqual(loaded.recommendations[-1], rec)
        self.assertEqual(loaded.results[-1].execution_id, "learned-exec")
        self.assertEqual(self.store.recommend(self.task, self.policy, self.model.to_dict()), rec)
        with self.assertRaisesRegex(ValidationError, "arrived after fitting"):
            self.store.recommend(replace(self.task, task_id="another-task", session_id="another-session"), self.policy, self.model.to_dict())

    def test_no_learner_argument_preserves_existing_static_behavior(self):
        task = TaskRequest.from_dict(parse_json((FIXTURES / "learning-tests-task.json").read_text()))
        rec = self.store.recommend(task, self.policy)
        self.assertIsNone(rec.learning)
        self.assertEqual(rec.decision["recommended_model"], "fixture/standard")
        self.assertEqual(rec.decision["effective_model"], "fixture/premium")

    def test_bad_source_refuses_write_without_damaging_existing_feedback(self):
        original = self.store.path.read_bytes()
        evidence = copy.deepcopy(list(self.model.evidence))
        evidence[0].update(senior_adopted_successes=1, senior_success_sessions=1)
        forged = replace(self.model, evidence=tuple(evidence))
        with self.assertRaises(ValidationError):
            self.store.recommend(self.task, self.policy, forged.to_dict())
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_refit_can_use_new_resolved_feedback_without_recursive_approval(self):
        rec = self.store.recommend(self.task, self.policy, self.model.to_dict())
        self.store.record("response", {"recommendation_id": rec.recommendation_id, "developer_id": "synthetic-junior",
                                      "timestamp": "2026-10-04T10:01:00Z", "response": "reject"})
        plan = replace(self.plan, learner_version="synthetic-v2", cutoff="2026-10-04T12:00:00Z",
                       session_ids=self.plan.session_ids + (self.task.session_id,))
        updated = fit_feedback(self.store.read(), self.policy, plan)
        self.assertIsNone(next(rule for rule in updated.to_dict()["rules"] if rule["task_type"] == "documentation")["recommended_model"])
        self.assertFalse(updated.to_dict()["deployment_authorized"])


class LearningCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-learning-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.store = self.directory / "feedback"
        self.output = self.directory / "learner.json"
        policy = load_policy(FIXTURES / "policy.json")
        FeedbackStore(self.store).import_ledger(import_scenario(parse_json((FIXTURES / "feedback-demo.json").read_text()), policy))

    def run_cli(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(["feedback"] + arguments + ["--store", str(self.store)])
        return code, json.loads(output.getvalue()) if output.getvalue() else None, error.getvalue()

    def fit_args(self):
        return ["learn", "--policy", str(FIXTURES / "policy.json"), "--plan", str(FIXTURES / "learning-plan.json"),
                "--output", str(self.output)]

    def test_cli_fits_and_applies_future_manual_suggestion_without_model_calls(self):
        with patch("socket.socket", side_effect=AssertionError("No network allowed")), patch("subprocess.run", side_effect=AssertionError("No execution allowed")):
            code, artifact, _ = self.run_cli(self.fit_args())
            self.assertEqual(code, 0)
            self.assertFalse(artifact["deployment_authorized"])
            code, rec, _ = self.run_cli(["recommend", str(FIXTURES / "learning-docs-task.json"), "--policy", str(FIXTURES / "policy.json"), "--learner", str(self.output)])
        self.assertEqual(code, 0)
        self.assertEqual(rec["decision"]["recommended_model"], "fixture/cheap")
        self.assertEqual(rec["decision"]["effective_model"], "fixture/premium")
        self.assertFalse(rec["deployment_authorized"])
        self.assertEqual(rec["learning"]["learner_sha256"], artifact["learner_sha256"])

    def test_cli_failed_category_uses_fallback_and_keeps_negative_evidence_in_output(self):
        self.run_cli(self.fit_args())
        code, rec, _ = self.run_cli(["recommend", str(FIXTURES / "learning-tests-task.json"), "--policy", str(FIXTURES / "policy.json"), "--learner", str(self.output)])
        self.assertEqual(code, 0)
        self.assertTrue(rec["decision"]["used_fallback"])
        self.assertEqual(rec["decision"]["recommended_model"], "fixture/premium")
        self.assertEqual(rec["learning"]["evidence"][0]["confirmed_failures"], 1)
        self.assertEqual(rec["learning"]["evidence"][0]["senior_rejects"], 1)

    def test_cli_never_overwrites_existing_learner_or_changes_training_ledger(self):
        before = (self.store / "feedback.json").read_bytes()
        self.run_cli(self.fit_args())
        artifact = self.output.read_bytes()
        code, data, error = self.run_cli(self.fit_args())
        self.assertEqual(code, 2)
        self.assertIsNone(data)
        self.assertEqual(self.output.read_bytes(), artifact)
        self.assertEqual((self.store / "feedback.json").read_bytes(), before)

    def test_invalid_holdout_plan_does_not_write_a_learner(self):
        plan = parse_json((FIXTURES / "learning-plan.json").read_text())
        plan["dataset_split"] = "test"
        path = self.directory / "holdout-plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        args = self.fit_args()
        args[args.index("--plan") + 1] = str(path)
        code, data, _ = self.run_cli(args)
        self.assertEqual(code, 2)
        self.assertIsNone(data)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
