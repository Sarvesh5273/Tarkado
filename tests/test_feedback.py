import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from engine.cli import main
from engine.feedback import FeedbackLedger, FeedbackStore, TaskRequest, TaskResult, TeamConfig, feedback_summary, import_scenario
from engine.importers import load_policy, parse_json
from engine.privacy import PrivacyError
from engine.schemas import ValidationError


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
FAKE_KEY = "sk-" + "A" * 32


def scenario():
    return parse_json((FIXTURES / "feedback-demo.json").read_text())


class FeedbackSchemaTests(unittest.TestCase):
    def setUp(self):
        self.data = scenario()
        self.policy = load_policy(FIXTURES / "policy.json")

    def test_team_roles_and_company_attestation_are_explicit(self):
        team = TeamConfig.from_dict(self.data["team"])
        self.assertEqual(team.role("synthetic-senior"), "senior")
        self.assertEqual(team.role("synthetic-junior"), "junior")
        self.assertEqual(TeamConfig.from_dict(team.to_dict()), team)
        with self.assertRaises(ValidationError):
            team.role("not-in-roster")
        for data in (dict(self.data["team"], company_api_attested=False),
                     dict(self.data["team"], members=[]),
                     dict(self.data["team"], members=[{"developer_id": "one", "role": "admin"}])):
            with self.subTest(data=data):
                with self.assertRaises(ValidationError):
                    TeamConfig.from_dict(data)

    def test_duplicate_developer_and_self_declared_role_fields_are_rejected(self):
        team = copy.deepcopy(self.data["team"])
        team["members"].append(team["members"][0])
        with self.assertRaises(ValidationError):
            TeamConfig.from_dict(team)
        task = dict(self.data["tasks"][0]["task"], role="senior")
        with self.assertRaises(ValidationError):
            TaskRequest.from_dict(task)

    def test_requests_are_metadata_only_and_do_not_require_invented_usage(self):
        task = TaskRequest.from_dict(self.data["tasks"][0]["task"])
        self.assertEqual(TaskRequest.from_dict(task.to_dict()), task)
        for field in ("prompt", "source_code", "output", "api_key", "cost_usd", "result"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    TaskRequest.from_dict(dict(task.to_dict(), **{field: "not accepted"}))

    def test_invalid_dates_tokens_risk_and_model_input_are_rejected(self):
        for updates in ({"timestamp": "2026-10-03"}, {"context_tokens": -1}, {"risk_tags": "low"},
                        {"task_id": ""}, {"selected_model": "unknown/model"}):
            with self.subTest(updates=updates):
                data = copy.deepcopy(self.data)
                data["tasks"][0]["task"].update(updates)
                with self.assertRaises(ValidationError):
                    import_scenario(data, self.policy)

    def test_unknown_quality_and_cost_are_not_zero_or_success(self):
        data = dict(self.data["tasks"][0]["result"], desired_result=None, tests_passed=None,
                    score=None, cost_usd=None, latency_ms=None, evidence_ref=None)
        result = TaskResult.from_dict(data)
        self.assertIsNone(result.desired_result)
        self.assertIsNone(result.cost_usd)
        self.assertEqual(TaskResult.from_dict(result.to_dict()), result)

    def test_quality_requires_evidence_and_cannot_contradict_failed_tests(self):
        original = self.data["tasks"][0]["result"]
        for updates in ({"evidence_ref": None}, {"tests_passed": False}, {"score": "1.1"},
                        {"cost_usd": "NaN"}, {"latency_ms": -1}, {"desired_result": "true"}):
            with self.subTest(updates=updates):
                with self.assertRaises(ValidationError):
                    TaskResult.from_dict(dict(original, **updates))

    def test_secrets_are_rejected_before_persistence(self):
        for path in ("developer", "task", "evidence"):
            with self.subTest(path=path):
                data = copy.deepcopy(self.data)
                if path == "developer":
                    data["team"]["members"][0]["developer_id"] = FAKE_KEY
                elif path == "task":
                    data["tasks"][0]["task"]["task_id"] = FAKE_KEY
                else:
                    data["tasks"][0]["result"]["evidence_ref"] = FAKE_KEY
                with self.assertRaises(PrivacyError) as error:
                    import_scenario(data, self.policy)
                self.assertNotIn(FAKE_KEY, str(error.exception))


class FeedbackLedgerTests(unittest.TestCase):
    def setUp(self):
        self.data = scenario()
        self.policy = load_policy(FIXTURES / "policy.json")
        self.ledger = import_scenario(self.data, self.policy)

    def test_roundtrip_preserves_all_canonical_record_collections(self):
        data = self.ledger.to_dict()
        self.assertEqual(tuple(data), ("schema_version", "team", "policies", "recommendations", "responses", "executions", "results"))
        self.assertEqual(FeedbackLedger.from_dict(data), self.ledger)
        self.assertEqual(len(self.ledger.recommendations), 7)
        self.assertEqual(len(self.ledger.responses), 7)
        self.assertEqual(len(self.ledger.executions), 5)
        self.assertEqual(len(self.ledger.results), 5)

    def test_recommendations_preserve_manual_model_choice_and_unknown_outcome(self):
        for rec in self.ledger.recommendations:
            self.assertEqual(rec.decision["enforcement"], "shadow")
            self.assertEqual(rec.decision["effective_model"], "fixture/premium")
        self.assertEqual(self.ledger.recommendations[0].decision["recommended_model"], "fixture/cheap")

    def test_recommendation_edits_and_changed_policy_content_are_not_trusted(self):
        original = self.ledger.to_dict()
        for mutation in (
            lambda data: data["recommendations"][0]["decision"].update(recommended_model="fixture/premium"),
            lambda data: data["recommendations"][0]["task"].update(task_type="other"),
            lambda data: data["recommendations"][0].update(policy_sha256="0" * 64),
            lambda data: data["policies"][0]["policy"].update(rules=[]),
        ):
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(original)
                mutation(data)
                with self.assertRaises(ValidationError):
                    FeedbackLedger.from_dict(data)

    def test_unknown_actor_or_impersonated_task_response_is_rejected(self):
        for mutation in (
            lambda data: data["tasks"][0]["task"].update(developer_id="not-in-roster"),
            lambda data: data["tasks"][0]["response"].update(developer_id="synthetic-junior"),
            lambda data: data["tasks"][0]["execution"].update(developer_id="synthetic-junior"),
            lambda data: data["tasks"][0]["result"].update(reviewer_id="not-in-roster"),
        ):
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(self.data)
                mutation(data)
                with self.assertRaises(ValidationError):
                    import_scenario(data, self.policy)

    def test_unlinked_results_duplicate_tasks_or_execution_ids_are_rejected(self):
        for mutation in (
            lambda data: data["tasks"][0]["result"].update(execution_id="exec-docs-2"),
            lambda data: data["tasks"].append(copy.deepcopy(data["tasks"][0])),
            lambda data: data["tasks"][1]["execution"].update(execution_id="exec-docs-1"),
            lambda data: data["tasks"][0].update(execution=None),
        ):
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(self.data)
                mutation(data)
                with self.assertRaises(ValidationError):
                    import_scenario(data, self.policy)

    def test_posthoc_acceptance_and_preexecution_outcome_are_rejected(self):
        for field, timestamp in (("response", "2026-10-03T10:04:00Z"),
                                 ("execution", "2026-10-03T09:59:00Z"),
                                 ("result", "2026-10-03T10:01:00Z")):
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                data["tasks"][0][field]["timestamp"] = timestamp
                with self.assertRaises(ValidationError):
                    import_scenario(data, self.policy)

    def test_duplicate_responses_and_branched_result_revisions_are_rejected(self):
        data = self.ledger.to_dict()
        data["responses"].append(copy.deepcopy(data["responses"][0]))
        with self.assertRaises(ValidationError):
            FeedbackLedger.from_dict(data)
        data = self.ledger.to_dict()
        data["results"].append(dict(data["results"][0], result_id="new-result", supersedes=None))
        with self.assertRaises(ValidationError):
            FeedbackLedger.from_dict(data)

    def test_no_response_or_result_is_allowed_without_inventing_feedback(self):
        data = copy.deepcopy(self.data)
        data["tasks"][0]["response"] = None
        data["tasks"][0]["result"] = None
        report = feedback_summary(import_scenario(data, self.policy), self.policy)
        first = report["tasks"][0]
        self.assertIsNone(first["response"])
        self.assertTrue(first["pending_result"])
        self.assertEqual(first["result_status"], "unknown")
        self.assertIsNone(first["score"])
        self.assertIsNone(first["cost_usd"])


class FeedbackSummaryTests(unittest.TestCase):
    def setUp(self):
        self.data = scenario()
        self.policy = load_policy(FIXTURES / "policy.json")
        self.ledger = import_scenario(self.data, self.policy)

    def group(self, report, model, task_type="documentation"):
        return next(item for item in report["groups"] if item["model"] == model and item["task_type"] == task_type)

    def test_accepted_unused_or_wrong_model_never_counts_as_suggested_success(self):
        report = feedback_summary(self.ledger, self.policy)
        cheap = self.group(report, "fixture/cheap")
        self.assertEqual(cheap["accepts"], 4)
        self.assertEqual(cheap["executions"], 2)
        self.assertEqual(cheap["confirmed_successes"], 2)
        self.assertEqual(cheap["senior_adopted_successes"], 2)
        self.assertEqual(cheap["senior_success_sessions"], 2)
        self.assertEqual(cheap["accepted_without_execution"], 1)
        self.assertEqual(cheap["accepted_but_different_model"], 1)
        premium = self.group(report, "fixture/premium")
        self.assertEqual(premium["confirmed_successes"], 1)
        self.assertEqual(premium["senior_adopted_successes"], 0)
        self.assertEqual(report["model_overrides"], 1)

    def test_junior_failure_and_senior_rejection_are_not_hidden_by_senior_success(self):
        report = feedback_summary(self.ledger, self.policy)
        standard = self.group(report, "fixture/standard", "test_generation")
        self.assertEqual(standard["senior_adopted_successes"], 1)
        self.assertEqual(standard["non_senior_failures"], 1)
        self.assertEqual(standard["confirmed_failures"], 1)
        self.assertEqual(standard["rejects"], 1)
        self.assertEqual(standard["senior_rejects"], 1)
        self.assertEqual(standard["status"], "investigate_failures")
        self.assertEqual(report["tasks"][5]["tests_passed"], False)
        self.assertEqual(report["tasks"][5]["score"], "0.7")

    def test_pending_counts_and_revision_counts_are_complete(self):
        report = feedback_summary(self.ledger, self.policy)
        self.assertEqual(report["recommendations"], 7)
        self.assertEqual(report["responses"], 7)
        self.assertEqual(report["executions"], 5)
        self.assertEqual(report["current_results"], 5)
        self.assertEqual(report["result_revisions"], 5)
        self.assertEqual(report["pending_executions"], 2)
        self.assertEqual(report["pending_results"], 0)

    def test_role_and_confirmation_source_do_not_become_authenticated_approval(self):
        report = feedback_summary(self.ledger, self.policy)
        self.assertEqual(report["roles_source"], "declared_local_roster_unverified")
        self.assertFalse(report["changes_policy"])
        self.assertFalse(report["deployment_authorized"])
        self.assertEqual(self.group(report, "fixture/cheap")["status"], "candidate_for_manual_review")

    def test_junior_success_without_senior_adoption_does_not_invent_senior_evidence(self):
        data = copy.deepcopy(self.data)
        for field in ("task", "response", "execution"):
            data["tasks"][0][field]["developer_id"] = "synthetic-junior"
        data["tasks"][0]["result"]["reviewer_id"] = "synthetic-junior"
        data["tasks"] = data["tasks"][:1]
        report = feedback_summary(import_scenario(data, self.policy), self.policy)
        cheap = self.group(report, "fixture/cheap")
        self.assertEqual(cheap["confirmed_successes"], 1)
        self.assertEqual(cheap["senior_adopted_successes"], 0)
        self.assertEqual(cheap["status"], "collect_more_evidence")

    def test_senior_acceptance_with_unknown_actual_result_is_not_positive_quality_evidence(self):
        data = copy.deepcopy(self.data)
        data["tasks"] = data["tasks"][:1]
        data["tasks"][0]["result"].update(desired_result=None, tests_passed=None, score=None, evidence_ref=None)
        cheap = self.group(feedback_summary(import_scenario(data, self.policy), self.policy), "fixture/cheap")
        self.assertEqual(cheap["accepts"], 1)
        self.assertEqual(cheap["unknown_results"], 1)
        self.assertEqual(cheap["confirmed_successes"], 0)
        self.assertEqual(cheap["senior_adopted_successes"], 0)

    def test_revoked_or_incompatible_current_model_cannot_receive_review_recommendation(self):
        for update in ({"status": "disabled"}, {"max_context_tokens": 1000}):
            with self.subTest(update=update):
                changed = replace(self.policy, models=(replace(self.policy.models[0], **update),) + self.policy.models[1:])
                cheap = self.group(feedback_summary(self.ledger, changed), "fixture/cheap")
                self.assertEqual(cheap["senior_adopted_successes"], 0)
                self.assertEqual(cheap["status"], "collect_more_evidence")
                self.assertEqual(cheap["incompatible_executions"], 2)

    def test_unapproved_actual_model_is_recorded_but_never_treated_as_allowed(self):
        data = copy.deepcopy(self.data)
        data["tasks"] = data["tasks"][:1]
        data["tasks"][0]["execution"]["actual_model"] = "unknown/observed-model"
        report = feedback_summary(import_scenario(data, self.policy), self.policy)
        unknown = self.group(report, "unknown/observed-model")
        self.assertEqual(unknown["executions"], 1)
        self.assertEqual(unknown["incompatible_executions"], 1)
        self.assertEqual(unknown["senior_adopted_successes"], 0)
        self.assertFalse(report["deployment_authorized"])

    def test_input_reordering_is_deterministic_without_policy_mutation(self):
        reordered = copy.deepcopy(self.data)
        reordered["tasks"].reverse()
        before = self.policy.to_dict()
        self.assertEqual(feedback_summary(import_scenario(reordered, self.policy), self.policy),
                         feedback_summary(self.ledger, self.policy))
        self.assertEqual(self.policy.to_dict(), before)


class FeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-feedback-store-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "feedback"
        self.store = FeedbackStore(self.directory)
        self.data = scenario()
        self.policy = load_policy(FIXTURES / "policy.json")
        self.ledger = import_scenario(self.data, self.policy)

    def prepare_one(self):
        self.store.initialize(self.ledger.team)
        return self.store.recommend(self.ledger.recommendations[0].task, self.policy)

    def record_one(self):
        rec = self.prepare_one()
        self.store.record("response", self.ledger.responses[0].to_dict())
        self.store.record("execution", self.ledger.executions[0].to_dict())
        self.store.record("result", self.ledger.results[0].to_dict())
        return rec

    def test_store_requires_collection_setup_and_rejects_changed_roster(self):
        with self.assertRaises(ValidationError):
            self.store.read()
        self.assertFalse(self.directory.exists())
        self.store.initialize(self.ledger.team)
        self.assertEqual(len(self.store.read().recommendations), 0)
        self.store.initialize(self.ledger.team)
        changed = replace(self.ledger.team, members=(("another-senior", "senior"),))
        with self.assertRaises(ValidationError):
            self.store.initialize(changed)

    def test_recommendation_and_record_retries_are_idempotent(self):
        rec = self.record_one()
        original = self.store.path.read_bytes()
        self.assertEqual(self.store.recommend(rec.task, self.policy), rec)
        for kind, item in (("response", self.ledger.responses[0]), ("execution", self.ledger.executions[0]),
                           ("result", self.ledger.results[0])):
            self.store.record(kind, item.to_dict())
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(len(self.store.read().recommendations), 1)

    def test_different_response_same_id_never_overwrites_history(self):
        self.record_one()
        original = self.store.path.read_bytes()
        with self.assertRaises(ValidationError):
            self.store.record("response", dict(self.ledger.responses[0].to_dict(), response="reject"))
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_changed_task_or_policy_requires_new_identity_without_overwriting(self):
        rec = self.prepare_one()
        original = self.store.path.read_bytes()
        with self.assertRaises(ValidationError):
            self.store.recommend(replace(rec.task, context_tokens=3000), self.policy)
        with self.assertRaises(ValidationError):
            self.store.recommend(replace(rec.task, task_id="new-task"), replace(self.policy, rules=()))
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_late_result_can_arrive_after_execution_and_updates_pending_summary(self):
        self.prepare_one()
        self.store.record("response", self.ledger.responses[0].to_dict())
        self.store.record("execution", self.ledger.executions[0].to_dict())
        report = feedback_summary(self.store.read(), self.policy)
        self.assertEqual(report["pending_results"], 1)
        self.store.record("result", dict(self.ledger.results[0].to_dict(), timestamp="2026-10-04T10:00:00Z"))
        report = feedback_summary(self.store.read(), self.policy)
        self.assertEqual(report["pending_results"], 0)
        self.assertEqual(report["groups"][0]["senior_adopted_successes"], 1)

    def test_result_correction_retains_history_and_counts_only_latest_evidence(self):
        self.record_one()
        correction = dict(self.ledger.results[0].to_dict(), result_id="corrected-result",
                          desired_result=False, tests_passed=False, score="0.4",
                          timestamp="2026-10-04T10:00:00Z", evidence_ref="synthetic-correction",
                          supersedes=self.ledger.results[0].result_id)
        self.store.record("result", correction)
        self.store.record("result", correction)
        report = feedback_summary(self.store.read(), self.policy)
        self.assertEqual(report["result_revisions"], 2)
        self.assertEqual(report["current_results"], 1)
        self.assertEqual(report["groups"][0]["senior_adopted_successes"], 0)
        self.assertEqual(report["groups"][0]["confirmed_failures"], 1)
        self.assertEqual(report["groups"][0]["status"], "investigate_failures")
        self.assertEqual(len(report["result_history"]), 2)
        self.assertTrue(report["result_history"][0]["desired_result"])
        self.assertFalse(report["result_history"][0]["is_current"])
        self.assertFalse(report["result_history"][1]["desired_result"])
        self.assertTrue(report["result_history"][1]["is_current"])

    def test_stale_result_correction_is_rejected(self):
        self.record_one()
        original = self.store.path.read_bytes()
        with self.assertRaises(ValidationError):
            self.store.record("result", dict(self.ledger.results[0].to_dict(), result_id="stale-result", supersedes="old-result"))
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_bulk_import_is_atomic_and_never_replaces_existing_feedback(self):
        self.store.import_ledger(self.ledger)
        original = self.store.path.read_bytes()
        self.store.import_ledger(self.ledger)
        self.assertEqual(self.store.path.read_bytes(), original)
        with self.assertRaises(ValidationError):
            self.store.import_ledger(FeedbackLedger(self.ledger.team))
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_corrupt_state_and_interrupted_write_do_not_erase_user_data(self):
        self.record_one()
        original = self.store.path.read_bytes()
        with patch("engine.feedback.os.replace", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                self.store.recommend(self.ledger.recommendations[1].task, self.policy)
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(list(self.directory.glob(".feedback-*")), [])
        data = parse_json(self.store.path.read_text())
        data["recommendations"][0]["decision"]["recommended_model"] = "fixture/premium"
        self.store.path.write_text(json.dumps(data), encoding="utf-8")
        corrupt = self.store.path.read_bytes()
        with self.assertRaises(ValidationError):
            self.store.read()
        with self.assertRaises(ValidationError):
            self.store.initialize(self.ledger.team)
        self.assertEqual(self.store.path.read_bytes(), corrupt)

    def test_private_permissions_and_symlink_state_are_protected(self):
        self.store.initialize(self.ledger.team)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.directory / ".lock").stat().st_mode & 0o777, 0o600)
        target = Path(self.temporary.name) / "user.json"
        target.write_text("user-owned data", encoding="utf-8")
        alias = Path(self.temporary.name) / "alias"
        alias.mkdir()
        (alias / "feedback.json").symlink_to(target)
        with self.assertRaises(ValidationError):
            FeedbackStore(alias).initialize(self.ledger.team)
        self.assertEqual(target.read_text(), "user-owned data")

    def test_parallel_recommendations_do_not_lose_records(self):
        self.store.initialize(self.ledger.team)
        tasks = [rec.task for rec in self.ledger.recommendations]
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(lambda task: self.store.recommend(task, self.policy), tasks))
        self.assertEqual(len(self.store.read().recommendations), 7)


class FeedbackCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-feedback-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.store = self.directory / "feedback"

    def run_cli(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(["feedback"] + arguments + ["--store", str(self.store)])
        return code, json.loads(output.getvalue()) if output.getvalue() else None, error.getvalue()

    def arguments(self):
        return ["import", str(FIXTURES / "feedback-demo.json"), "--policy", str(FIXTURES / "policy.json")]

    def test_demo_import_runs_offline_and_never_authorizes_routing(self):
        with patch("socket.socket", side_effect=AssertionError("No network permitted")):
            code, data, _ = self.run_cli(self.arguments())
        self.assertEqual(code, 0)
        self.assertEqual(data["recommendations"], 7)
        self.assertEqual(data["executions"], 5)
        self.assertEqual(data["pending_executions"], 2)
        self.assertFalse(data["deployment_authorized"])
        self.assertFalse(data["changes_policy"])
        self.assertTrue(data["local_only"])

    def test_summarizing_does_not_change_saved_feedback(self):
        self.run_cli(self.arguments())
        path = self.store / "feedback.json"
        original = path.read_bytes()
        code, data, _ = self.run_cli(["summary", "--policy", str(FIXTURES / "policy.json")])
        self.assertEqual(code, 0)
        self.assertEqual(data["groups"][2]["status"], "investigate_failures")
        self.assertEqual(path.read_bytes(), original)

    def test_bad_import_is_rejected_without_partial_store(self):
        data = scenario()
        data["tasks"][5]["result"]["execution_id"] = "wrong-execution"
        path = self.directory / "bad.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        code, report, _ = self.run_cli(["import", str(path), "--policy", str(FIXTURES / "policy.json")])
        self.assertEqual(code, 2)
        self.assertIsNone(report)
        self.assertFalse(self.store.exists())

    def test_individual_init_recommend_record_commands_link_without_execution(self):
        data = scenario()
        team_path = self.directory / "team.json"
        task_path = self.directory / "task.json"
        team_path.write_text(json.dumps(data["team"]), encoding="utf-8")
        task_path.write_text(json.dumps(data["tasks"][0]["task"]), encoding="utf-8")
        code, report, _ = self.run_cli(["init", "--team", str(team_path)])
        self.assertEqual(code, 0)
        self.assertEqual(report["members"], 2)
        code, rec, _ = self.run_cli(["recommend", str(task_path), "--policy", str(FIXTURES / "policy.json")])
        self.assertEqual(code, 0)
        self.assertEqual(rec["decision"]["effective_model"], "fixture/premium")
        response_path = self.directory / "response.json"
        response_path.write_text(json.dumps(dict(data["tasks"][0]["response"], recommendation_id=rec["recommendation_id"])), encoding="utf-8")
        code, report, _ = self.run_cli(["record", str(response_path), "--kind", "response"])
        self.assertEqual(code, 0)
        code, report, _ = self.run_cli(["summary", "--policy", str(FIXTURES / "policy.json")])
        self.assertEqual(report["pending_executions"], 1)
        self.assertEqual(report["executions"], 0)
        self.assertEqual(report["groups"][0]["senior_adopted_successes"], 0)

    def test_module_entrypoint_imports_local_demo(self):
        result = subprocess.run([sys.executable, "-m", "engine", "feedback"] + self.arguments() + ["--store", str(self.store)],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["deployment_authorized"])


if __name__ == "__main__":
    unittest.main()
