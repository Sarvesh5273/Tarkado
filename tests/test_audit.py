import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path

from engine.audit import (
    EVENT_FIELDS, MANIFEST_FIELDS, AuditBatch, AuditEvent, load_audit, replay_audit, rollout_audit,
)
from engine.cli import main
from engine.importers import load_policy, load_traces, parse_json
from engine.replay import replay
from engine.rollout import EvaluationPlan, evaluate
from engine.schemas import ValidationError


FIXTURES = Path(__file__).parent / "fixtures"


class ReplayAuditTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        self.traces = load_traces(FIXTURES / "synthetic.jsonl")
        self.report = replay(self.traces, self.policy)
        self.batch = replay_audit(self.report, self.policy)

    def test_one_decision_per_task_and_explicit_override_record(self):
        manifest = self.batch.to_records()[0]
        self.assertEqual(manifest["decision_count"], 7)
        self.assertEqual(manifest["override_count"], 1)
        self.assertEqual(manifest["event_count"], 8)
        self.assertEqual(manifest["evaluation_count"], 0)
        self.assertEqual(len({event.event_id for event in self.batch.events}), 8)
        override = next(event for event in self.batch.events if event.event_type == "override")
        self.assertTrue(override.developer_override)
        self.assertEqual(override.recorded_model, "fixture/standard")
        self.assertEqual(override.effective_model, "fixture/standard")

    def test_raw_task_sample_and_trace_ids_are_not_exported(self):
        data = json.dumps(self.batch.to_records())
        for trace in self.traces:
            self.assertNotIn(trace.task_id, data)
            self.assertNotIn(trace.trace_id, data)
        self.assertNotIn('"task_id"', data)
        self.assertNotIn('"trace_id"', data)
        self.assertNotIn('"prompt"', data)
        self.assertNotIn('"source_code"', data)

    def test_missing_suggestion_preserves_actual_fallback_and_unknown_outcomes(self):
        fallback = self.batch.events[4]
        self.assertEqual(fallback.suggested_model, "fixture/cheap")
        self.assertEqual(fallback.effective_model, "fixture/premium")
        self.assertTrue(fallback.missing_outcome)
        self.assertTrue(fallback.used_fallback)
        self.assertEqual(str(fallback.measurement.cost_usd), "0.05")
        unknown = self.batch.events[3]
        self.assertIsNone(unknown.measurement.outcome.tests_passed)
        self.assertIsNone(unknown.measurement.outcome.score)

    def test_audit_roundtrip_and_canonical_field_order(self):
        records = self.batch.to_records()
        self.assertEqual(tuple(records[0]), MANIFEST_FIELDS)
        self.assertEqual(tuple(records[1]), EVENT_FIELDS)
        self.assertEqual(AuditBatch.from_records(records), self.batch)
        self.assertEqual(AuditEvent.from_dict(records[1]), self.batch.events[0])

    def test_audit_is_deterministic_for_fixed_data_and_policy(self):
        reordered = replay_audit(replay(list(reversed(self.traces)), self.policy), self.policy)
        self.assertEqual(self.batch.to_records(), reordered.to_records())

    def test_same_named_but_changed_policy_cannot_relabel_an_old_report(self):
        changed = replace(self.policy, rules=())
        with self.assertRaisesRegex(ValidationError, "policy content disagree"):
            replay_audit(self.report, changed)
        new_report = replay(self.traces, changed)
        self.assertNotEqual(new_report.policy_sha256, self.report.policy_sha256)

    def test_observe_shadow_audits_preserve_recorded_selection(self):
        for mode in ("observe", "shadow"):
            with self.subTest(mode=mode):
                batch = replay_audit(replay(self.traces, self.policy, mode), self.policy)
                for event in batch.events:
                    self.assertEqual(event.effective_model, event.recorded_model)
                    self.assertEqual(event.mode, mode)

    def test_unpaired_and_blocked_replay_gets_an_audit_without_invented_measurement(self):
        trace = replace(self.traces[0], context_tokens=None)
        batch = replay_audit(replay([trace], self.policy), self.policy)
        event = batch.events[0]
        self.assertTrue(event.blocked)
        self.assertTrue(event.missing_outcome)
        self.assertIsNone(event.effective_model)
        self.assertIsNone(event.evaluated_model)
        self.assertIsNone(event.measurement)

    def test_invalid_or_modified_audit_fields_are_rejected(self):
        original = self.batch.to_records()[1]
        for updates in ({"event_id": "0" * 64}, {"task_ref": "raw-task-id"}, {"deployment_authorized": True},
                        {"schema_version": True}, {"mode": "enforce"}, {"reason": "modified reason"},
                        {"prompt": "not accepted"}, {"evaluated_model": None}, {"timestamp": "not-a-date"}):
            with self.subTest(updates=tuple(updates)):
                with self.assertRaises(ValidationError):
                    AuditEvent.from_dict(dict(original, **updates))

    def test_consistent_new_fingerprint_cannot_bypass_mode_and_override_rules(self):
        payload = dict(self.batch.to_records()[1])
        del payload["event_id"]
        for updates in ({"mode": "shadow"}, {"event_type": "override"},
                        {"mode": "evaluate", "event_type": "candidate_evaluation"},
                        {"baseline_model": None}, {"blocked": True}):
            with self.subTest(updates=updates):
                with self.assertRaises(ValidationError):
                    AuditEvent.create(dict(payload, **updates))

    def test_manifest_count_duplicates_or_policy_mismatch_are_rejected(self):
        for mutation in (
            lambda records: records[0].update(event_count=9),
            lambda records: records[0].update(override_count=0),
            lambda records: records[0].update(policy_sha256="0" * 64),
            lambda records: records.append(records[1]),
            lambda records: records[0].update(retention_policy="automatically_deleted"),
        ):
            with self.subTest(mutation=mutation):
                records = json.loads(json.dumps(self.batch.to_records()))
                mutation(records)
                with self.assertRaises(ValidationError):
                    AuditBatch.from_records(records)

    def test_private_export_reloads_exactly_and_never_overwrites(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-audit-file-") as directory:
            path = Path(directory) / "audit.jsonl"
            self.batch.export(path)
            self.assertEqual(load_audit(path), self.batch)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                self.batch.export(path)
            self.assertEqual(path.read_bytes(), original)


class CandidateAuditTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "rollout-policy.json")
        self.traces = load_traces(FIXTURES / "rollout.jsonl", repeated=True)
        self.plan = EvaluationPlan.from_dict(parse_json((FIXTURES / "rollout-plan.json").read_text()))

    def test_rejected_candidate_audits_all_samples_without_an_effective_route(self):
        report = evaluate(self.traces, self.policy, "fixture/candidate", self.plan)
        batch = rollout_audit(report, self.policy)
        self.assertEqual(batch.to_records()[0]["evaluation_count"], 6)
        self.assertEqual(batch.to_records()[0]["decision_count"], 0)
        for event in batch.events:
            self.assertEqual(event.mode, "evaluate")
            self.assertIsNone(event.effective_model)
            self.assertEqual(event.evaluated_model, "fixture/candidate")
        self.assertFalse(batch.events[3].measurement.outcome.tests_passed)
        self.assertEqual(batch.events[3].baseline_model, "fixture/premium")
        self.assertTrue(batch.events[3].baseline_measurement.outcome.tests_passed)
        self.assertEqual(str(batch.events[3].measurement.outcome.score), "0.7")
        self.assertEqual(self.policy.model("fixture/candidate").status, "candidate")

    def test_candidate_missing_outcomes_are_audited_explicitly(self):
        traces = [trace for trace in self.traces if trace.is_baseline]
        batch = rollout_audit(evaluate(traces, self.policy, "fixture/candidate", self.plan), self.policy)
        self.assertEqual(len(batch.events), 6)
        self.assertTrue(all(event.missing_outcome and event.blocked for event in batch.events))
        self.assertTrue(all(event.measurement is None for event in batch.events))
        self.assertTrue(all(event.baseline_measurement is not None for event in batch.events))

    def test_candidate_override_gets_separate_historical_record(self):
        traces = list(self.traces)
        traces[1] = replace(traces[1], outcome=replace(traces[1].outcome, developer_override=True))
        batch = rollout_audit(evaluate(traces, self.policy, "fixture/candidate", self.plan), self.policy)
        self.assertEqual(batch.to_records()[0]["override_count"], 1)
        self.assertEqual(batch.to_records()[0]["event_count"], 7)
        override = next(event for event in batch.events if event.event_type == "override")
        self.assertEqual(override.mode, "evaluate")
        self.assertIsNone(override.effective_model)

    def test_changed_same_version_policy_cannot_relabel_candidate_report(self):
        report = evaluate(self.traces, self.policy, "fixture/candidate", self.plan)
        changed = replace(self.policy, models=(replace(self.policy.models[0], max_context_tokens=8000), self.policy.models[1]))
        with self.assertRaisesRegex(ValidationError, "policy content disagree"):
            rollout_audit(report, changed)


class AuditCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-audit-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "audit.jsonl"

    def run_cli(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(arguments)
        return code, output.getvalue(), error.getvalue()

    def test_replay_exports_audit_and_keeps_stdout_valid_json(self):
        code, output, _ = self.run_cli(["replay", str(FIXTURES / "synthetic.jsonl"), "--policy", str(FIXTURES / "policy.json"),
                                      "--format", "json", "--audit", str(self.path)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["comparison_policy"]["tests_failed"], 1)
        self.assertEqual(load_audit(self.path).to_records()[0]["event_count"], 8)

    def test_audit_file_existing_returns_error_but_preserves_report_and_file(self):
        self.path.write_text("user-owned content", encoding="utf-8")
        code, output, error = self.run_cli(["replay", str(FIXTURES / "synthetic.jsonl"), "--policy", str(FIXTURES / "policy.json"),
                                          "--format", "json", "--audit", str(self.path)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["comparison_policy"]["tests_failed"], 1)
        self.assertIn("audit export failed", error)
        self.assertEqual(self.path.read_text(), "user-owned content")

    def test_rejected_candidate_still_writes_audit_with_negative_results(self):
        code, output, _ = self.run_cli([
            "evaluate", str(FIXTURES / "rollout.jsonl"), "--policy", str(FIXTURES / "rollout-policy.json"),
            "--candidate", "fixture/candidate", "--plan", str(FIXTURES / "rollout-plan.json"),
            "--format", "json", "--audit", str(self.path),
        ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["recommendation"], "reject")
        self.assertEqual(load_audit(self.path).to_records()[0]["evaluation_count"], 6)

    def test_privacy_check_validates_saved_audit_without_echoing_identifiers(self):
        policy = load_policy(FIXTURES / "policy.json")
        replay_audit(replay(load_traces(FIXTURES / "synthetic.jsonl"), policy), policy).export(self.path)
        code, output, _ = self.run_cli(["privacy", "check", str(self.path), "--kind", "audit"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["records_checked"], 8)
        self.assertNotIn("fixture/premium", output)


if __name__ == "__main__":
    unittest.main()
