import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from engine.cli import main, render_text
from engine.importers import load_policy, load_traces, parse_json
from engine.replay import METRIC_FIELDS, replay
from engine.schemas import ValidationError


FIXTURES = Path(__file__).parent / "fixtures"


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        self.traces = load_traces(FIXTURES / "synthetic.jsonl")

    def test_synthetic_comparison_reports_quality_regression_alongside_cost(self):
        report = replay(self.traces, self.policy)
        # These are the exact sums of the hand-written fixture costs.
        self.assertEqual(report.recorded_baseline.cost_usd, Decimal("0.46"))
        self.assertEqual(report.comparison_policy.cost_usd, Decimal("0.345"))
        self.assertEqual(report.to_dict()["cost_reduction_usd"], "0.115")
        self.assertEqual(report.comparison_baseline.tests_passed, 6)
        self.assertEqual(report.comparison_policy.tests_passed, 5)
        self.assertEqual(report.comparison_policy.tests_failed, 1)
        self.assertEqual(report.comparison_policy.tests_unknown, 1)
        self.assertEqual(report.comparison_policy.developer_overrides, 1)
        self.assertEqual(report.recorded_baseline.total_latency_ms, 6450)
        self.assertEqual(report.comparison_policy.total_latency_ms, 5250)
        self.assertEqual(report.score_pairs, 6)
        self.assertEqual(report.mean_score_change, Decimal("-0.2") / 6)
        self.assertEqual(report.to_dict()["fallbacks"], 4)
        self.assertEqual(report.to_dict()["missing_suggested_outcomes"], 1)
        self.assertEqual(report.to_dict()["rule_matches"], 2)

    def test_replay_is_deterministic_and_independent_of_input_order(self):
        first = replay(self.traces, self.policy).to_dict()
        self.assertEqual(first, replay(self.traces, self.policy).to_dict())
        self.assertEqual(first, replay(list(reversed(self.traces)), self.policy).to_dict())
        self.assertEqual([row["task_id"] for row in first["decisions"]], sorted({trace.task_id for trace in self.traces}))

    def test_observe_and_shadow_have_no_applied_cost_or_quality_change(self):
        for mode in ("observe", "shadow"):
            with self.subTest(mode=mode):
                report = replay(self.traces, self.policy, mode)
                self.assertEqual(report.comparison_baseline, report.comparison_policy)
                self.assertEqual(report.to_dict()["cost_reduction_usd"], "0.00")
                for row in report.rows:
                    self.assertEqual(row.decision.effective_model, row.baseline.selected_model)

    def test_missing_suggestion_uses_measured_default_not_an_estimate(self):
        report = replay(self.traces, self.policy)
        row = next(row for row in report.rows if row.task_id == "05-missing-outcome")
        self.assertEqual(row.suggested_model, "fixture/cheap")
        self.assertTrue(row.missing_suggested_outcome)
        self.assertTrue(row.decision.used_fallback)
        self.assertEqual(row.evaluated, row.baseline)

    def test_missing_default_outcome_is_explicit_and_not_a_zero_cost_gain(self):
        original = next(trace for trace in self.traces if trace.task_id == "06-override")
        trace = replace(original, outcome=replace(original.outcome, developer_override=False))
        report = replay([trace], self.policy)
        self.assertEqual(report.unevaluated_tasks, 1)
        self.assertEqual(report.recorded_baseline.task_count, 1)
        self.assertEqual(report.comparison_baseline.task_count, 0)
        self.assertEqual(report.comparison_policy.task_count, 0)
        self.assertIsNone(report.to_dict()["cost_reduction_usd"])
        self.assertIsNone(report.mean_score_change)
        self.assertIsNone(report.rows[0].evaluated)

    def test_blocked_route_stays_unevaluated(self):
        trace = replace(self.traces[0], context_tokens=None)
        report = replay([trace], self.policy)
        self.assertEqual(report.unevaluated_tasks, 1)
        self.assertIsNone(report.rows[0].decision.effective_model)

    def test_cost_increase_is_reported_as_negative_reduction(self):
        traces = [self.traces[0], replace(self.traces[1], cost_usd=Decimal("0.08"))]
        report = replay(traces, self.policy)
        self.assertEqual(report.to_dict()["cost_reduction_usd"], "-0.02")
        self.assertIn("cost_reduction_usd: -0.02", render_text(report))

    def test_score_delta_uses_only_paired_known_scores(self):
        traces = [self.traces[0], replace(self.traces[1], outcome=replace(self.traces[1].outcome, score=None))]
        report = replay(traces, self.policy)
        self.assertEqual(report.comparison_baseline.scored_tasks, 1)
        self.assertEqual(report.comparison_policy.scored_tasks, 0)
        self.assertEqual(report.score_pairs, 0)
        self.assertIsNone(report.mean_score_change)

    def test_tier_mismatch_stops_instead_of_silently_fixing_data(self):
        with self.assertRaisesRegex(ValidationError, "tier disagrees"):
            replay([replace(self.traces[0], model_tier="cheap")], self.policy)

    def test_text_report_contains_all_metrics_in_canonical_order(self):
        report = replay(self.traces, self.policy)
        lines = render_text(report).splitlines()
        metric_names = [line.split(" | ")[0] for line in lines if line.split(" | ")[0] in METRIC_FIELDS]
        self.assertEqual(tuple(metric_names), METRIC_FIELDS)
        self.assertIn("mean_score_change: -0.03333333333333333333333333333", lines)
        self.assertIn("tests_failed | 0 | 0 | 1", lines)

    def test_metadata_report_does_not_emit_raw_content(self):
        data = json.dumps(replay(self.traces, self.policy).to_dict())
        for field in ("prompt", "source_code", "raw_content_ref", "api_key"):
            self.assertNotIn('"' + field + '"', data)

    def test_cli_runs_without_network_and_emits_valid_json(self):
        output = io.StringIO()
        with patch("socket.socket", side_effect=AssertionError("Network use is not allowed")), redirect_stdout(output):
            code = main(["replay", str(FIXTURES / "synthetic.jsonl"), "--policy", str(FIXTURES / "policy.json"), "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["evaluated_tasks"], 7)
        self.assertEqual(data["comparison_policy"]["tests_failed"], 1)

    def test_cli_invalid_input_returns_an_error(self):
        error = io.StringIO()
        with redirect_stderr(error):
            code = main(["replay", str(FIXTURES / "missing.jsonl"), "--policy", str(FIXTURES / "policy.json")])
        self.assertEqual(code, 2)
        self.assertIn("Tarkado:", error.getvalue())

    def test_cli_incomplete_comparison_returns_nonzero_and_reports_it(self):
        data = parse_json((FIXTURES / "synthetic.jsonl").read_text().splitlines()[8])
        data["outcome"]["developer_override"] = False
        with tempfile.TemporaryDirectory(prefix="tarkado-test-") as directory:
            path = Path(directory) / "metadata.jsonl"
            path.write_text(json.dumps(data), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["replay", str(path), "--policy", str(FIXTURES / "policy.json"), "--format", "json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["unevaluated_tasks"], 1)


if __name__ == "__main__":
    unittest.main()
