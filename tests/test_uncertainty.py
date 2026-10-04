import io
import json
import math
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
from unittest.mock import patch

from engine.cli import main, render_rollout
from engine.importers import load_policy, load_traces, parse_json
from engine.rollout import EvaluationPlan, EvaluationRow, evaluate
from engine.schemas import ValidationError
from engine.uncertainty import METRIC_ORDER, UncertaintySettings, hoeffding_interval, summarize_uncertainty


FIXTURES = Path(__file__).parent / "fixtures"
ATTESTED = UncertaintySettings(Decimal("0.95"), True, True)


class BoundedIntervalTests(unittest.TestCase):
    def test_radius_matches_independent_two_tail_formula(self):
        data = hoeffding_interval(Decimal(0), 100, Decimal("0.95"))
        expected = math.sqrt(2 * math.log(40) / 100)
        self.assertAlmostEqual(float(data["radius"]), expected, places=14)
        self.assertEqual(Decimal(data["lower"]), Decimal(data["upper"]).copy_negate())
        self.assertEqual(data["method"], "hoeffding_two_sided")
        self.assertEqual(data["coverage"], "pointwise")

    def test_interval_respects_logical_range_and_remains_wide_for_small_samples(self):
        for mean in (Decimal(-1), Decimal(0), Decimal(1)):
            with self.subTest(mean=mean):
                data = hoeffding_interval(mean, 3, Decimal("0.95"))
                self.assertGreaterEqual(Decimal(data["lower"]), Decimal(-1))
                self.assertLessEqual(Decimal(data["upper"]), Decimal(1))
                self.assertLessEqual(Decimal(data["lower"]), mean)
                self.assertGreaterEqual(Decimal(data["upper"]), mean)
        zero = hoeffding_interval(Decimal(0), 3, Decimal("0.95"))
        self.assertEqual(zero["lower"], "-1")
        self.assertEqual(zero["upper"], "1")

    def test_more_distinct_tasks_reduce_radius_but_not_by_repeating_runs(self):
        few = hoeffding_interval(Decimal(0), 10, Decimal("0.95"))
        many = hoeffding_interval(Decimal(0), 100, Decimal("0.95"))
        self.assertLess(Decimal(many["radius"]), Decimal(few["radius"]))

    def test_higher_confidence_requires_wider_interval(self):
        lower = hoeffding_interval(Decimal(0), 100, Decimal("0.90"))
        higher = hoeffding_interval(Decimal(0), 100, Decimal("0.99"))
        self.assertGreater(Decimal(higher["radius"]), Decimal(lower["radius"]))

    def test_zero_mean_does_not_imply_zero_radius(self):
        data = hoeffding_interval(Decimal(0), 100, Decimal("0.95"))
        self.assertGreater(Decimal(data["radius"]), Decimal(0))
        self.assertLess(Decimal(data["lower"]), Decimal(0))
        self.assertGreater(Decimal(data["upper"]), Decimal(0))

    def test_invalid_n_mean_and_confidence_are_rejected(self):
        for mean, count, confidence in (
            (Decimal(0), 0, Decimal("0.95")), (Decimal(0), 1, Decimal("0.95")),
            (Decimal(0), True, Decimal("0.95")), (Decimal(0), 2.5, Decimal("0.95")),
            (Decimal("NaN"), 3, Decimal("0.95")), (Decimal("1.1"), 3, Decimal("0.95")),
            (Decimal("-1.1"), 3, Decimal("0.95")), (Decimal(0), 3, Decimal(1)),
            (Decimal(0), 3, Decimal("0.49")), (Decimal(0), 3, Decimal("Infinity")),
        ):
            with self.subTest(mean=mean, count=count, confidence=confidence):
                with self.assertRaises(ValidationError):
                    hoeffding_interval(mean, count, confidence)

    def test_interval_calculation_does_not_mutate_caller_decimal_context(self):
        expected = hoeffding_interval(Decimal("-0.2"), 40, Decimal("0.95"))
        with localcontext() as context:
            context.prec = 8
            actual = hoeffding_interval(Decimal("-0.2"), 40, Decimal("0.95"))
            self.assertEqual(context.prec, 8)
        self.assertEqual(actual, expected)


class TaskSummaryTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "rollout-policy.json")
        self.traces = load_traces(FIXTURES / "rollout.jsonl", repeated=True)
        self.plan = EvaluationPlan.from_dict(parse_json((FIXTURES / "rollout-plan.json").read_text()))
        self.rows = evaluate(self.traces, self.policy, "fixture/candidate", self.plan).rows

    def metric(self, summary, name="score_change"):
        return summary["metrics"][name]

    def test_three_tasks_and_six_samples_not_six_independent_observations(self):
        summary = summarize_uncertainty(self.rows, ATTESTED)
        score = self.metric(summary)
        self.assertEqual(summary["scope_tasks"], 3)
        self.assertEqual(summary["scope_samples"], 6)
        self.assertEqual(score["complete_tasks"], 3)
        self.assertEqual(score["included_samples"], 6)
        with localcontext() as context:
            context.prec = 50
            expected_mean = Decimal("-0.2") / 3
        self.assertEqual(Decimal(score["task_weighted_mean"]), expected_mean)
        self.assertEqual(score["minimum_task_mean"], "-0.15")
        self.assertEqual(score["maximum_task_mean"], "0")
        self.assertEqual(score["interval"]["lower"], "-1")
        self.assertEqual(score["interval"]["upper"], "1")

    def test_repeating_identical_task_samples_does_not_shrink_interval(self):
        repeated = list(self.rows)
        for row in self.rows:
            repeated.append(replace(row, sample_id=row.sample_id + "-extra",
                                    recorded=replace(row.recorded, sample_id=row.sample_id + "-extra"),
                                    baseline=replace(row.baseline, sample_id=row.sample_id + "-extra"),
                                    candidate=replace(row.candidate, sample_id=row.sample_id + "-extra")))
        first = self.metric(summarize_uncertainty(self.rows, ATTESTED))
        more = self.metric(summarize_uncertainty(repeated, ATTESTED))
        self.assertEqual(first["interval"], more["interval"])
        self.assertEqual(first["task_weighted_mean"], more["task_weighted_mean"])
        self.assertEqual(more["included_samples"], 12)
        self.assertEqual(more["complete_tasks"], 3)

    def test_unequal_repeat_counts_use_equal_task_weighting(self):
        original = self.rows[0]
        first = replace(original, candidate=replace(original.candidate,
                        outcome=replace(original.candidate.outcome, score=Decimal(0))))
        rows = [first]
        for sample in ("one", "two", "three"):
            recorded = replace(original.recorded, task_id="another-task", sample_id=sample)
            baseline = replace(original.baseline, task_id="another-task", sample_id=sample)
            candidate = replace(original.candidate, task_id="another-task", sample_id=sample,
                                outcome=replace(original.candidate.outcome, score=Decimal(1)))
            rows.append(EvaluationRow("another-task", sample, recorded, baseline, candidate,
                                      "Explicit test baseline", None, None))
        score = self.metric(summarize_uncertainty(rows, ATTESTED))
        self.assertEqual(score["complete_tasks"], 2)
        self.assertEqual(score["included_samples"], 4)
        self.assertEqual(Decimal(score["task_weighted_mean"]), Decimal("-0.5"))
        self.assertNotEqual(Decimal(score["task_weighted_mean"]), Decimal("-0.25"))

    def test_unconfirmed_assumptions_withhold_intervals_but_show_estimates(self):
        for settings in (UncertaintySettings(), replace(ATTESTED, independent_tasks_attested=False),
                         replace(ATTESTED, fixed_sampling_attested=False)):
            with self.subTest(settings=settings):
                score = self.metric(summarize_uncertainty(self.rows, settings))
                self.assertEqual(score["interval_status"], "sampling_assumptions_unconfirmed")
                self.assertIsNone(score["interval"])
                self.assertIsNotNone(score["task_weighted_mean"])

    def test_cost_and_latency_never_infer_bounds_from_observed_range(self):
        summary = summarize_uncertainty(self.rows, ATTESTED)
        for name in ("cost_reduction_usd", "latency_change_ms"):
            with self.subTest(name=name):
                value = self.metric(summary, name)
                self.assertEqual(value["interval_status"], "no_declared_hard_bounds")
                self.assertIsNone(value["interval"])
                self.assertIsNotNone(value["task_weighted_mean"])
        with localcontext() as context:
            context.prec = 50
            expected_mean = Decimal("0.205") / 3
        self.assertEqual(Decimal(self.metric(summary, "cost_reduction_usd")["task_weighted_mean"]), expected_mean)

    def test_partial_missing_sample_excludes_whole_task_for_each_metric(self):
        rows = list(self.rows)
        rows[0] = replace(rows[0], candidate=None)
        summary = summarize_uncertainty(rows, ATTESTED)
        for metric in METRIC_ORDER:
            with self.subTest(metric=metric):
                value = self.metric(summary, metric)
                self.assertEqual(value["complete_tasks"], 2)
                self.assertEqual(value["excluded_tasks"], 1)
                self.assertEqual(value["included_samples"], 4)
                self.assertEqual(value["excluded_samples"], 2)
                self.assertIsNone(value["interval"])
        self.assertEqual(self.metric(summary)["interval_status"], "incomplete_task_coverage")

    def test_unknown_score_does_not_exclude_known_test_or_cost_metrics(self):
        rows = list(self.rows)
        rows[0] = replace(rows[0], candidate=replace(rows[0].candidate,
                          outcome=replace(rows[0].candidate.outcome, score=None)))
        summary = summarize_uncertainty(rows, ATTESTED)
        self.assertEqual(self.metric(summary)["complete_tasks"], 2)
        self.assertIsNone(self.metric(summary)["interval"])
        self.assertEqual(self.metric(summary, "test_pass_change")["complete_tasks"], 3)
        self.assertIsNotNone(self.metric(summary, "test_pass_change")["interval"])

    def test_no_complete_tasks_never_invents_zero_mean(self):
        rows = [replace(row, candidate=None) for row in self.rows]
        score = self.metric(summarize_uncertainty(rows, ATTESTED))
        self.assertEqual(score["complete_tasks"], 0)
        self.assertEqual(score["excluded_tasks"], 3)
        self.assertIsNone(score["task_weighted_mean"])
        self.assertIsNone(score["sample_stddev_of_task_means"])
        self.assertEqual(score["interval_status"], "no_complete_tasks")

    def test_one_task_many_runs_still_cannot_produce_an_interval(self):
        rows = [row for row in self.rows if row.task_id == self.rows[0].task_id]
        score = self.metric(summarize_uncertainty(rows, ATTESTED))
        self.assertEqual(score["complete_tasks"], 1)
        self.assertEqual(score["interval_status"], "too_few_distinct_tasks")
        self.assertIsNone(score["interval"])
        self.assertIsNone(score["sample_stddev_of_task_means"])

    def test_zero_observed_spread_does_not_collapse_inferential_interval(self):
        rows = [replace(row, candidate=replace(row.candidate, outcome=replace(row.candidate.outcome, score=Decimal(1))))
                for row in self.rows]
        score = self.metric(summarize_uncertainty(rows, ATTESTED))
        self.assertEqual(Decimal(score["sample_stddev_of_task_means"]), 0)
        self.assertGreater(Decimal(score["interval"]["radius"]), 0)
        self.assertEqual(score["interval"]["lower"], "-1")
        self.assertEqual(score["interval"]["upper"], "1")

    def test_reordering_is_deterministic_and_duplicate_sample_ids_are_rejected(self):
        self.assertEqual(summarize_uncertainty(self.rows, ATTESTED),
                         summarize_uncertainty(tuple(reversed(self.rows)), ATTESTED))
        with self.assertRaisesRegex(ValidationError, "duplicate task/sample"):
            summarize_uncertainty(self.rows + (self.rows[0],), ATTESTED)

    def test_metric_order_stays_canonical(self):
        summary = summarize_uncertainty(self.rows, ATTESTED)
        self.assertEqual(tuple(summary["metrics"]), METRIC_ORDER)

    def test_mismatched_task_metadata_or_sample_pairing_is_rejected(self):
        for candidate in (replace(self.rows[0].candidate, task_id="other"),
                          replace(self.rows[0].candidate, required_tools=("other_tool",))):
            with self.subTest(candidate_task=candidate.task_id):
                with self.assertRaises(ValidationError):
                    summarize_uncertainty([replace(self.rows[0], candidate=candidate)], ATTESTED)


class UncertaintyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "rollout-policy.json")
        self.traces = load_traces(FIXTURES / "rollout.jsonl", repeated=True)
        self.plan = EvaluationPlan.from_dict(parse_json((FIXTURES / "rollout-plan.json").read_text()))

    def test_legacy_plan_defaults_to_unconfirmed_assumptions_and_roundtrips(self):
        self.assertFalse(self.plan.uncertainty.independent_tasks_attested)
        self.assertFalse(self.plan.uncertainty.fixed_sampling_attested)
        self.assertEqual(EvaluationPlan.from_dict(self.plan.to_dict()), self.plan)

    def test_invalid_settings_fail_instead_of_tuning_to_dataset(self):
        original = ATTESTED.to_dict()
        for changes in ({"confidence_level": "0.49"}, {"confidence_level": "1"},
                        {"independent_tasks_attested": "true"}, {"fixed_sampling_attested": 1},
                        {"method": "bootstrap_runs"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    UncertaintySettings.from_dict(dict(original, **changes))
        with self.assertRaises(ValidationError):
            UncertaintySettings.from_dict({"confidence_level": "0.95"})

    def test_held_out_plan_is_preserved_without_mutating_gates(self):
        plan = replace(self.plan, dataset_split="test", uncertainty=ATTESTED)
        before = plan.to_dict()
        report = evaluate(self.traces, self.policy, "fixture/candidate", plan)
        self.assertEqual(report.plan.to_dict(), before)
        self.assertEqual(report.to_dict()["uncertainty"]["settings"], ATTESTED.to_dict())

    def test_bounds_cannot_override_failures_or_enable_model(self):
        report = evaluate(self.traces, self.policy, "fixture/candidate", replace(self.plan, uncertainty=ATTESTED))
        self.assertEqual(report.recommendation, "reject")
        self.assertFalse(report.to_dict()["deployment_authorized"])
        self.assertFalse(report.to_dict()["uncertainty"]["affects_recommendation"])
        self.assertEqual(self.policy.model("fixture/candidate").status, "candidate")

    def test_every_uncertainty_metric_is_printed_and_negative_results_remain(self):
        report = evaluate(self.traces, self.policy, "fixture/candidate", replace(self.plan, uncertainty=ATTESTED))
        output = render_rollout(report)
        self.assertIn("Independent-task uncertainty:", output)
        for metric in METRIC_ORDER:
            self.assertIn(metric + ": {", output)
        self.assertIn('"minimum_task_mean": "-0.15"', output)
        self.assertIn('"interval_status": "no_declared_hard_bounds"', output)

    def test_cli_reports_bounds_offline_and_still_rejects_negative_fixture(self):
        output = io.StringIO()
        with patch("socket.socket", side_effect=AssertionError("No network allowed")), redirect_stdout(output):
            code = main(["evaluate", str(FIXTURES / "rollout.jsonl"), "--policy", str(FIXTURES / "rollout-policy.json"),
                         "--candidate", "fixture/candidate", "--plan", str(FIXTURES / "uncertainty-plan.json"), "--format", "json"])
        self.assertEqual(code, 1)
        data = json.loads(output.getvalue())
        self.assertEqual(data["recommendation"], "reject")
        self.assertEqual(data["uncertainty"]["metrics"]["score_change"]["complete_tasks"], 3)
        self.assertEqual(data["uncertainty"]["metrics"]["score_change"]["interval"]["lower"], "-1")
        self.assertFalse(data["deployment_authorized"])


if __name__ == "__main__":
    unittest.main()
