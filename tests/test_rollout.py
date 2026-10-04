import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from engine.cli import main, render_rollout
from engine.exporters import export_policy
from engine.importers import load_policy, load_traces, parse_json, validate_dataset
from engine.policy import decide
from engine.replay import METRIC_FIELDS
from engine.rollout import EvaluationPlan, evaluate
from engine.schemas import Model, Policy, Rule, TaskTrace, ValidationError


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


class RegistryTests(unittest.TestCase):
    def data(self, status="candidate"):
        return {
            "model_id": "fixture/new", "tier": "standard", "status": status,
            "task_types": ["documentation"], "tools": ["read"], "max_context_tokens": 16000,
        }

    def test_states_do_not_imply_routing_approval(self):
        for status in ("candidate", "shadow", "approved", "disabled"):
            with self.subTest(status=status):
                model = Model.from_dict(self.data(status))
                self.assertEqual(model.approved, status == "approved")
                self.assertEqual(Model.from_dict(model.to_dict()), model)

    def test_legacy_approval_maps_to_safe_states(self):
        for approval in (True, False):
            with self.subTest(approval=approval):
                data = self.data()
                del data["status"]
                data["approved"] = approval
                self.assertEqual(Model.from_dict(data).status, "approved" if approval else "disabled")

    def test_conflicting_or_missing_states_are_rejected(self):
        cases = (dict(self.data(), approved=True), dict(self.data("approved"), approved=False),
                 self.data("unknown"), self.data(True))
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(ValidationError):
                    Model.from_dict(data)
        data = self.data()
        del data["status"]
        with self.assertRaises(ValidationError):
            Model.from_dict(data)

    def test_candidate_and_shadow_cannot_be_routed_even_with_a_rule(self):
        original = load_policy(FIXTURES / "rollout-policy.json")
        trace = load_traces(FIXTURES / "synthetic.jsonl")[0]
        for status in ("candidate", "shadow", "disabled"):
            with self.subTest(status=status):
                candidate = replace(original.models[0], status=status)
                policy = replace(original, models=(candidate, original.models[1]),
                                 rules=(Rule("documentation", candidate.model_id, ("validation-evidence",)),))
                decision = decide(policy, trace)
                self.assertTrue(decision.used_fallback)
                self.assertEqual(decision.recommended_model, "fixture/premium")

    def test_nonapproved_premium_cannot_be_the_default(self):
        data = parse_json((FIXTURES / "rollout-policy.json").read_text())
        for status in ("candidate", "shadow", "disabled"):
            with self.subTest(status=status):
                data["models"][1]["status"] = status
                with self.assertRaises(ValidationError):
                    Policy.from_dict(data)

    def test_policy_export_preserves_candidate_state(self):
        policy = load_policy(FIXTURES / "rollout-policy.json")
        with tempfile.TemporaryDirectory(prefix="tarkado-registry-test-") as directory:
            destination = Path(directory) / "proposal.json"
            export_policy(policy, destination)
            self.assertEqual(load_policy(destination), policy)
            self.assertEqual(json.loads(destination.read_text())["models"][0]["status"], "candidate")


class SampleTests(unittest.TestCase):
    def setUp(self):
        self.traces = load_traces(FIXTURES / "rollout.jsonl", repeated=True)

    def test_repeated_import_pairs_by_task_and_sample(self):
        self.assertEqual(len(self.traces), 12)
        self.assertEqual(len({trace.task_id for trace in self.traces}), 3)
        self.assertEqual(sum(trace.is_baseline for trace in self.traces), 6)

    def test_phase_one_replay_import_still_rejects_repeated_pairs(self):
        with self.assertRaises(ValidationError):
            load_traces(FIXTURES / "rollout.jsonl")

    def test_each_sample_requires_its_own_baseline(self):
        traces = [trace for trace in self.traces if trace.trace_id != "docs-2-base"]
        with self.assertRaisesRegex(ValidationError, "exactly one baseline"):
            validate_dataset(traces, repeated=True)

    def test_duplicate_outcome_within_one_sample_is_rejected(self):
        traces = self.traces + [replace(self.traces[0], trace_id="different-id")]
        with self.assertRaisesRegex(ValidationError, "Duplicate task/model"):
            validate_dataset(traces, repeated=True)

    def test_task_metadata_cannot_change_between_samples(self):
        traces = list(self.traces)
        traces[2] = replace(traces[2], context_tokens=3000)
        traces[3] = replace(traces[3], context_tokens=3000)
        with self.assertRaisesRegex(ValidationError, "same task metadata"):
            validate_dataset(traces, repeated=True)

    def test_sample_id_is_optional_but_cannot_be_empty(self):
        data = parse_json((FIXTURES / "rollout.jsonl").read_text().splitlines()[0])
        data["sample_id"] = ""
        with self.assertRaises(ValidationError):
            TaskTrace.from_dict(data)
        del data["sample_id"]
        self.assertEqual(TaskTrace.from_dict(data).sample_id, "single")


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "rollout-policy.json")
        self.traces = load_traces(FIXTURES / "rollout.jsonl", repeated=True)
        self.plan = EvaluationPlan.from_dict(parse_json((FIXTURES / "rollout-plan.json").read_text()))

    def run_evaluation(self, traces=None, policy=None, plan=None):
        return evaluate(self.traces if traces is None else traces,
                        self.policy if policy is None else policy,
                        "fixture/candidate", self.plan if plan is None else plan)

    def passing_traces(self):
        # Separate hand-written scenarios test the gates; the regression fixture stays unchanged.
        return [replace(trace, outcome=replace(trace.outcome, tests_passed=True, score=Decimal("1")))
                if trace.selected_model == "fixture/candidate" else trace for trace in self.traces]

    def test_cheaper_candidate_is_rejected_with_exact_quality_and_cost_results(self):
        report = self.run_evaluation()
        data = report.to_dict()
        self.assertEqual(report.recommendation, "reject")
        self.assertFalse(data["deployment_authorized"])
        self.assertEqual(data["baseline"]["cost_usd"], "0.60")
        self.assertEqual(data["candidate"]["cost_usd"], "0.19")
        self.assertEqual(data["cost_reduction_usd"], "0.41")
        self.assertEqual(data["baseline"]["total_latency_ms"], 6000)
        self.assertEqual(data["candidate"]["total_latency_ms"], 2500)
        self.assertEqual(data["total_latency_change_ms"], -3500)
        self.assertEqual(data["baseline"]["tests_passed"], 6)
        self.assertEqual(data["candidate"]["tests_passed"], 5)
        self.assertEqual(data["candidate"]["tests_failed"], 1)
        self.assertEqual(data["test_regressions"], 1)
        self.assertEqual(data["baseline_test_failure_rate"], "0")
        self.assertEqual(data["candidate_test_failure_rate"], str(Decimal(1) / 6))
        self.assertEqual(data["developer_override_change"], 0)
        self.assertEqual(data["score_regressions"], 2)
        self.assertEqual(data["mean_score_change"], str(Decimal("-0.4") / 6))
        self.assertEqual(data["scope_tasks"], 3)
        self.assertEqual(data["paired_samples"], 6)

    def test_variation_reports_distinct_tasks_and_all_sample_counts(self):
        stats = self.run_evaluation().to_dict()["task_variation"]
        self.assertEqual([item["samples"] for item in stats], [2, 2, 2])
        self.assertEqual(stats[1]["min_score_change"], "-0.3")
        self.assertEqual(stats[1]["max_score_change"], "0")
        self.assertEqual(stats[1]["mean_score_change"], "-0.15")
        self.assertEqual(stats[2]["mean_score_change"], "-0.05")

    def test_healthy_candidate_can_only_recommend_shadow(self):
        report = self.run_evaluation(traces=self.passing_traces())
        self.assertEqual(report.recommendation, "shadow")
        self.assertFalse(report.to_dict()["deployment_authorized"])
        self.assertEqual(self.policy.model("fixture/candidate").status, "candidate")

    def test_evaluation_never_mutates_registry_policy_or_plan(self):
        before = self.policy.to_dict()
        plan_before = self.plan.to_dict()
        self.run_evaluation()
        self.run_evaluation(traces=self.passing_traces())
        self.assertEqual(self.policy.to_dict(), before)
        self.assertEqual(self.plan.to_dict(), plan_before)

    def test_reordering_input_cannot_change_recommendation_or_report(self):
        self.assertEqual(self.run_evaluation().to_dict(),
                         self.run_evaluation(traces=list(reversed(self.traces))).to_dict())

    def test_missing_candidate_outcomes_never_use_default_as_candidate_evidence(self):
        traces = [trace for trace in self.passing_traces() if trace.trace_id != "docs-2-candidate"]
        report = self.run_evaluation(traces=traces)
        data = report.to_dict()
        self.assertEqual(report.recommendation, "collect_more_evidence")
        self.assertEqual(data["missing_candidate_outcomes"], 1)
        self.assertEqual(data["paired_samples"], 5)
        self.assertEqual(data["unpaired_samples"], 1)
        self.assertEqual(data["baseline"]["cost_usd"], "0.50")
        self.assertEqual(data["candidate"]["cost_usd"], "0.16")
        self.assertIsNone(report.rows[1].candidate)

    def test_no_candidate_outcomes_does_not_claim_zero_cost_savings(self):
        report = self.run_evaluation(traces=[trace for trace in self.traces if trace.is_baseline])
        data = report.to_dict()
        self.assertEqual(report.recommendation, "collect_more_evidence")
        self.assertEqual(data["missing_candidate_outcomes"], 6)
        self.assertEqual(data["paired_samples"], 0)
        self.assertIsNone(data["cost_reduction_usd"])
        self.assertIsNone(data["mean_score_change"])

    def test_unknown_scores_or_tests_collect_more_evidence(self):
        for field in ("score", "tests_passed"):
            with self.subTest(field=field):
                traces = self.passing_traces()
                traces[1] = replace(traces[1], outcome=replace(traces[1].outcome, **{field: None}))
                report = self.run_evaluation(traces=traces)
                self.assertEqual(report.recommendation, "collect_more_evidence")
                self.assertFalse(report.rows[0].known_quality)

    def test_unknown_tests_are_excluded_from_failure_rate_denominator(self):
        traces = self.passing_traces()
        traces[1] = replace(traces[1], outcome=replace(traces[1].outcome, tests_passed=None))
        traces[3] = replace(traces[3], outcome=replace(traces[3].outcome, tests_passed=False))
        data = self.run_evaluation(traces=traces).to_dict()
        self.assertEqual(data["candidate"]["tests_unknown"], 1)
        self.assertEqual(data["candidate_test_failure_rate"], "0.2")
        self.assertEqual(data["known_test_pairs"], 5)

    def test_already_approved_candidate_does_not_receive_new_enablement(self):
        candidate = replace(self.policy.models[0], status="approved")
        policy = replace(self.policy, models=(candidate, self.policy.models[1]))
        report = self.run_evaluation(traces=self.passing_traces(), policy=policy)
        self.assertEqual(report.recommendation, "collect_more_evidence")
        self.assertFalse(report.to_dict()["deployment_authorized"])

    def test_minimum_counts_are_predeclared_not_chosen_from_results(self):
        for plan in (replace(self.plan, min_tasks=4), replace(self.plan, min_samples_per_task=3)):
            with self.subTest(plan=plan):
                report = self.run_evaluation(traces=self.passing_traces(), plan=plan)
                self.assertEqual(report.recommendation, "collect_more_evidence")
                self.assertEqual(report.plan, plan)

    def test_requested_scope_is_explicit_and_exclusions_are_counted(self):
        plan = replace(self.plan, task_types=("documentation",), min_tasks=2)
        data = self.run_evaluation(traces=self.passing_traces(), plan=plan).to_dict()
        self.assertEqual(data["recommendation"], "shadow")
        self.assertEqual(data["total_tasks"], 3)
        self.assertEqual(data["excluded_tasks"], 1)
        self.assertEqual(data["scope_tasks"], 2)
        self.assertEqual(data["evaluation_samples"], 4)

    def test_missing_requested_task_type_cannot_be_hidden_by_total_task_count(self):
        traces = [trace for trace in self.passing_traces() if trace.task_type == "documentation"]
        data = self.run_evaluation(traces=traces, plan=replace(self.plan, min_tasks=2)).to_dict()
        self.assertEqual(data["scope_tasks"], 2)
        self.assertEqual(data["recommendation"], "collect_more_evidence")
        self.assertEqual(data["task_type_coverage"][1]["known_quality_samples"], 0)

    def test_new_override_is_not_masked_by_an_override_disappearing_elsewhere(self):
        traces = self.passing_traces()
        traces[0] = replace(traces[0], outcome=replace(traces[0].outcome, developer_override=True))
        traces[3] = replace(traces[3], outcome=replace(traces[3].outcome, developer_override=True))
        data = self.run_evaluation(traces=traces).to_dict()
        self.assertEqual(data["developer_override_change"], 0)
        self.assertEqual(data["override_regressions"], 1)
        self.assertEqual(data["recommendation"], "reject")

    def test_no_matching_scope_collects_evidence_without_hypothetical_savings(self):
        data = self.run_evaluation(plan=replace(self.plan, task_types=("other",))).to_dict()
        self.assertEqual(data["recommendation"], "collect_more_evidence")
        self.assertEqual(data["excluded_tasks"], 3)
        self.assertEqual(data["scope_tasks"], 0)
        self.assertIsNone(data["cost_reduction_usd"])

    def test_disabled_candidate_is_rejected(self):
        candidate = replace(self.policy.models[0], status="disabled")
        policy = replace(self.policy, models=(candidate, self.policy.models[1]))
        self.assertEqual(self.run_evaluation(traces=self.passing_traces(), policy=policy).recommendation, "reject")

    def test_shadow_state_remains_shadow_and_does_not_become_approved(self):
        candidate = replace(self.policy.models[0], status="shadow")
        policy = replace(self.policy, models=(candidate, self.policy.models[1]))
        report = self.run_evaluation(traces=self.passing_traces(), policy=policy)
        self.assertEqual(report.recommendation, "shadow")
        self.assertFalse(policy.model("fixture/candidate").approved)

    def test_unknown_candidate_is_configuration_error(self):
        with self.assertRaisesRegex(ValidationError, "explicitly registered"):
            evaluate(self.traces, self.policy, "missing/model", self.plan)

    def test_incompatible_tool_context_and_task_types_reject_scope(self):
        updates = ({"tools": ("read",)}, {"max_context_tokens": 1000}, {"task_types": ("documentation",)})
        for update in updates:
            with self.subTest(update=update):
                candidate = replace(self.policy.models[0], **update)
                policy = replace(self.policy, models=(candidate, self.policy.models[1]))
                data = self.run_evaluation(traces=self.passing_traces(), policy=policy).to_dict()
                self.assertEqual(data["recommendation"], "reject")
                self.assertGreater(data["compatibility_failures"], 0)

    def test_high_unknown_or_missing_risk_is_not_a_safe_candidate_scope(self):
        for tags in (("high",), (), ("low", "security")):
            with self.subTest(tags=tags):
                traces = [replace(trace, risk_tags=tags) for trace in self.passing_traces()]
                data = self.run_evaluation(traces=traces).to_dict()
                self.assertEqual(data["recommendation"], "reject")
                self.assertEqual(data["compatibility_failures"], 6)
                self.assertEqual(data["paired_samples"], 0)

    def test_increased_candidate_overrides_are_not_ignored(self):
        traces = self.passing_traces()
        traces[1] = replace(traces[1], outcome=replace(traces[1].outcome, developer_override=True))
        report = self.run_evaluation(traces=traces)
        self.assertEqual(report.recommendation, "reject")
        self.assertEqual(report.to_dict()["candidate"]["developer_overrides"], 1)

    def test_current_policy_baseline_is_separate_from_recorded_no_change(self):
        approved = Model("fixture/standard", "standard", "approved", ("documentation",), ("read",), 16000)
        policy = replace(self.policy, models=self.policy.models + (approved,),
                         rules=(Rule("documentation", approved.model_id, ("validation-example",)),))
        traces = self.passing_traces()
        for trace in list(traces):
            if trace.is_baseline and trace.task_type == "documentation":
                traces.append(replace(trace, trace_id=trace.trace_id + "-standard", selected_model="fixture/standard",
                                      model_tier="standard", cost_usd=Decimal("0.02"), is_baseline=False))
        data = self.run_evaluation(traces=traces, policy=policy).to_dict()
        self.assertEqual(data["recorded_no_change"]["cost_usd"], "0.60")
        self.assertEqual(data["baseline"]["cost_usd"], "0.28")
        self.assertEqual(data["candidate"]["cost_usd"], "0.19")
        self.assertEqual(data["baseline_models"], ["fixture/premium", "fixture/standard"])

    def test_missing_baseline_outcome_collects_evidence_instead_of_using_recorded_route(self):
        traces = []
        policy = replace(self.policy, models=self.policy.models + (
            Model("fixture/standard", "standard", "approved", ("documentation", "test_generation"),
                  ("read", "edit", "test"), 16000),
        ))
        for trace in self.passing_traces():
            traces.append(replace(trace, selected_model="fixture/standard", model_tier="standard")
                          if trace.is_baseline else trace)
        data = self.run_evaluation(traces=traces, policy=policy).to_dict()
        self.assertEqual(data["recommendation"], "collect_more_evidence")
        self.assertEqual(data["baseline_failures"], 6)
        self.assertEqual(data["paired_samples"], 0)
        self.assertIsNone(data["cost_reduction_usd"])

    def test_failed_candidate_is_visible_even_if_baseline_cannot_be_paired(self):
        policy = replace(self.policy, models=(self.policy.models[0], replace(self.policy.models[1], tools=())))
        data = self.run_evaluation(policy=policy).to_dict()
        self.assertEqual(data["recommendation"], "reject")
        self.assertEqual(data["observed_candidate_test_failures"], 1)
        self.assertEqual(data["paired_samples"], 0)
        self.assertEqual(data["samples"][3]["candidate_score"], "0.7")

    def test_candidate_already_used_as_baseline_is_not_compared_to_itself(self):
        candidate = replace(self.policy.models[0], status="approved")
        policy = replace(self.policy, models=(candidate, self.policy.models[1]),
                         rules=(Rule("documentation", candidate.model_id, ("validation-example",)),))
        with self.assertRaisesRegex(ValidationError, "self-comparison"):
            self.run_evaluation(policy=policy)

    def test_report_contract_rejects_invalid_counts_enable_and_hidden_regressions(self):
        report = self.run_evaluation()
        for updates in ({"total_tasks": 4}, {"recommendation": "enable"}, {"reasons": ()},
                        {"recommendation": "shadow"}, {"rows": report.rows + (report.rows[0],)}):
            with self.subTest(updates=tuple(updates)):
                with self.assertRaises(ValidationError):
                    replace(report, **updates)

    def test_text_prints_all_metrics_and_negative_score_change(self):
        text_report = render_rollout(self.run_evaluation())
        names = [line.split(" | ")[0] for line in text_report.splitlines() if line.split(" | ")[0] in METRIC_FIELDS]
        self.assertEqual(tuple(names), METRIC_FIELDS)
        self.assertIn("Deployment authorized: NO", text_report)
        self.assertIn("mean_score_change: -0.06666666666666666666666666667", text_report)


class EvaluationPlanTests(unittest.TestCase):
    def test_invalid_evidence_plans_are_rejected(self):
        original = parse_json((FIXTURES / "rollout-plan.json").read_text())
        for updates in ({"min_tasks": 0}, {"min_samples_per_task": -1}, {"min_tasks": True},
                        {"task_types": []}, {"task_types": ["*"]}, {"source_kind": "unknown"},
                        {"dataset_split": "training"}, {"source": ""}, {"prompt": "not allowed"}):
            with self.subTest(updates=updates):
                with self.assertRaises(ValidationError):
                    EvaluationPlan.from_dict(dict(original, **updates))

    def test_held_out_test_plan_is_preserved_not_tuned(self):
        data = parse_json((FIXTURES / "rollout-plan.json").read_text())
        data["dataset_split"] = "test"
        plan = EvaluationPlan.from_dict(data)
        self.assertEqual(EvaluationPlan.from_dict(plan.to_dict()), plan)
        self.assertEqual(plan.min_tasks, 3)
        self.assertEqual(plan.min_samples_per_task, 2)


class EvaluationCliTests(unittest.TestCase):
    def arguments(self):
        return ["evaluate", str(FIXTURES / "rollout.jsonl"), "--policy", str(FIXTURES / "rollout-policy.json"),
                "--candidate", "fixture/candidate", "--plan", str(FIXTURES / "rollout-plan.json"), "--format", "json"]

    def test_reject_has_nonzero_exit_valid_json_and_no_network(self):
        output = io.StringIO()
        with patch("socket.socket", side_effect=AssertionError("No network allowed")), redirect_stdout(output):
            code = main(self.arguments())
        self.assertEqual(code, 1)
        data = json.loads(output.getvalue())
        self.assertEqual(data["recommendation"], "reject")
        self.assertFalse(data["deployment_authorized"])

    def test_unknown_candidate_has_configuration_error(self):
        arguments = self.arguments()
        arguments[arguments.index("--candidate") + 1] = "unknown/model"
        error = io.StringIO()
        with redirect_stderr(error):
            code = main(arguments)
        self.assertEqual(code, 2)
        self.assertIn("explicitly registered", error.getvalue())

    def test_missing_plan_is_an_error_not_a_default_threshold(self):
        arguments = self.arguments()
        arguments[arguments.index("--plan") + 1] = str(FIXTURES / "missing.json")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(arguments), 2)

    def test_healthy_shadow_report_has_zero_exit_but_no_deployment_authorization(self):
        records = [parse_json(line) for line in (FIXTURES / "rollout.jsonl").read_text().splitlines()]
        for record in records:
            if record["selected_model"] == "fixture/candidate":
                record["outcome"].update(tests_passed=True, score="1")
        with tempfile.TemporaryDirectory(prefix="tarkado-shadow-test-") as directory:
            path = Path(directory) / "metadata.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            arguments = self.arguments()
            arguments[1] = str(path)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(arguments)
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data["recommendation"], "shadow")
        self.assertFalse(data["deployment_authorized"])

    def test_module_evaluation_entrypoint_returns_reject(self):
        result = subprocess.run([sys.executable, "-m", "engine"] + self.arguments(),
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["recommendation"], "reject")


if __name__ == "__main__":
    unittest.main()
