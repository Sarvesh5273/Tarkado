import io
import csv
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from engine.cli import main, render_text
from engine.exporters import export_jsonl, export_policy
from engine.history import PolicyStore
from engine.importers import CSV_FIELDS, load_policy, load_traces, parse_json
from engine.privacy import PrivacyError, ensure_safe, redact_text
from engine.replay import replay
from engine.schemas import Policy, TaskTrace, text


FIXTURES = Path(__file__).parent / "fixtures"
FAKE_KEY = "sk-" + "A" * 32


class SecretTests(unittest.TestCase):
    def test_supported_fake_secret_patterns_are_blocked_and_redacted(self):
        samples = (
            FAKE_KEY, "sk-ant-api03-" + "A" * 32, "ghp_" + "A" * 32,
            "github_pat_" + "A" * 40, "AKIA" + "A" * 16,
            "AIza" + "A" * 35, "xoxb-" + "A" * 20,
            "Bearer " + "A" * 20, "eyJ" + "A" * 12 + "." + "B" * 12 + "." + "C" * 12,
            "-----BEGIN PRIVATE KEY-----", "password=fixture-secret", "api_key: fixture-secret",
            '{"api_key":"fixture-secret"}', "token = 'fixture-secret'",
            "--password fixture-secret", "https://user:fixture-secret@example.invalid",
            "https://example.invalid?access_token=fixture-secret",
        )
        for sample in samples:
            with self.subTest(sample_kind=sample[:10]):
                with self.assertRaises(PrivacyError) as error:
                    ensure_safe(sample)
                self.assertNotIn(sample, str(error.exception))
                self.assertNotIn(sample, redact_text(sample))
                self.assertIn("[REDACTED]", redact_text(sample))

    def test_nested_metadata_and_credential_field_names_are_scanned(self):
        for value in ({"source": ["ok", {"label": FAKE_KEY}]}, {"password": "fixture-secret"},
                      {"API-Key": "fixture-secret"}, {"Authorization": "fixture-secret"}):
            with self.subTest(keys=list(value)):
                with self.assertRaises(PrivacyError):
                    ensure_safe(value)

    def test_quoted_passphrases_are_redacted_in_full(self):
        for value in ('password="synthetic phrase with spaces"', "--password 'synthetic phrase with spaces'"):
            with self.subTest(value=value):
                self.assertEqual(redact_text(value), "[REDACTED]")

    def test_private_key_body_and_truncated_block_are_redacted_in_full(self):
        for suffix in ("\n-----END PRIVATE KEY-----", ""):
            value = "-----BEGIN PRIVATE KEY-----\nsynthetic-private-data" + suffix
            self.assertEqual(redact_text(value), "[REDACTED]")
            with self.assertRaises(PrivacyError):
                ensure_safe(value)

    def test_harmless_counts_fingerprints_and_fixture_metadata_are_accepted(self):
        ensure_safe({"input_tokens": 1000, "output_tokens": 200, "developer_override": False,
                     "policy_sha256": "a" * 64, "score": Decimal("0.8"), "source": ["synthetic fixture"]})
        for path in ("policy.json", "rollout-policy.json", "rollout-plan.json"):
            ensure_safe(parse_json((FIXTURES / path).read_text()))

    def test_metadata_controls_and_excessive_length_are_blocked(self):
        for value in ("line\nline", "tab\tvalue", "nul\x00value", "escape\x1b[31mvalue", "A" * 1025):
            with self.subTest(length=len(value)):
                with self.assertRaises(PrivacyError):
                    text(value, "metadata")
        self.assertEqual(text("A" * 1024, "metadata"), "A" * 1024)

    def test_nonfinite_and_unsupported_metadata_types_cannot_be_serialized(self):
        for value in (float("nan"), float("inf"), Decimal("NaN"), object(), {1: "not a string key"}):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(PrivacyError):
                    ensure_safe(value)

    def test_schema_blocks_secret_in_each_trace_string_field(self):
        original = parse_json((FIXTURES / "synthetic.jsonl").read_text().splitlines()[0])
        for field in ("trace_id", "task_id", "task_type", "selected_model", "sample_id"):
            with self.subTest(field=field):
                with self.assertRaises(PrivacyError):
                    TaskTrace.from_dict(dict(original, **{field: FAKE_KEY}))
        for field in ("risk_tags", "required_tools"):
            with self.subTest(field=field):
                with self.assertRaises(PrivacyError):
                    TaskTrace.from_dict(dict(original, **{field: [FAKE_KEY]}))

    def test_direct_python_trace_cannot_bypass_secret_checks(self):
        trace = load_traces(FIXTURES / "synthetic.jsonl")[0]
        policy = load_policy(FIXTURES / "policy.json")
        with self.assertRaises(PrivacyError):
            replay([replace(trace, task_id=FAKE_KEY)], policy)

    def test_rendering_a_modified_report_cannot_leak_metadata(self):
        policy = load_policy(FIXTURES / "policy.json")
        report = replay(load_traces(FIXTURES / "synthetic.jsonl"), policy)
        with self.assertRaises(PrivacyError):
            render_text(replace(report, policy_version=FAKE_KEY))

    def test_fingerprint_remains_canonical_and_changes_with_policy_content(self):
        policy = load_policy(FIXTURES / "policy.json")
        self.assertEqual(policy.fingerprint(), Policy.from_dict(policy.to_dict()).fingerprint())
        self.assertNotEqual(policy.fingerprint(), replace(policy, rules=()).fingerprint())


class PrivacyStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-privacy-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.policy = load_policy(FIXTURES / "policy.json")

    def test_secret_policy_export_is_blocked_before_creating_files(self):
        path = self.directory / "not-created" / "policy.json"
        with self.assertRaises(PrivacyError):
            export_policy(replace(self.policy, policy_version=FAKE_KEY), path)
        self.assertFalse(path.parent.exists())

    def test_secret_jsonl_export_is_blocked_before_creating_files(self):
        path = self.directory / "not-created" / "audit.jsonl"
        with self.assertRaises(PrivacyError):
            export_jsonl([{"label": FAKE_KEY}], path)
        self.assertFalse(path.parent.exists())

    def test_secret_review_metadata_is_not_persisted(self):
        store = PolicyStore(self.directory / "history")
        store.save(self.policy)
        original = store.state_path.read_bytes()
        with self.assertRaises(PrivacyError):
            store.review(self.policy.policy_version, "fixture-reviewer", FAKE_KEY)
        self.assertEqual(store.state_path.read_bytes(), original)
        self.assertNotIn(FAKE_KEY, store.state_path.read_text())

    def test_private_export_is_complete_and_never_overwrites(self):
        path = self.directory / "export.jsonl"
        export_jsonl([{"task_count": 7}, {"score_change": "-0.2"}], path)
        self.assertEqual([json.loads(line) for line in path.read_text().splitlines()],
                         [{"task_count": 7}, {"score_change": "-0.2"}])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            export_jsonl([{"task_count": 0}], path)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.directory.glob(".export-*")), [])

    def test_publish_or_flush_failure_does_not_leave_partial_exports(self):
        path = self.directory / "audit.jsonl"
        for function in ("os.link", "os.fsync"):
            with self.subTest(function=function):
                with patch("engine.exporters." + function, side_effect=OSError("synthetic failure")):
                    with self.assertRaises(OSError):
                        export_jsonl([{"task_count": 7}], path)
                self.assertFalse(path.exists())
                self.assertEqual(list(self.directory.glob(".export-*")), [])


class PrivacyCliTests(unittest.TestCase):
    def capture(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(arguments)
        return code, output.getvalue(), error.getvalue()

    def test_input_secret_is_not_printed_in_either_stream_or_export(self):
        record = parse_json((FIXTURES / "synthetic.jsonl").read_text().splitlines()[0])
        record["task_id"] = FAKE_KEY
        with tempfile.TemporaryDirectory(prefix="tarkado-secret-input-") as directory:
            path = Path(directory) / "metadata.jsonl"
            path.write_text(json.dumps(record), encoding="utf-8")
            output = Path(directory) / "audit.jsonl"
            code, stdout, stderr = self.capture(["replay", str(path), "--policy", str(FIXTURES / "policy.json"),
                                                 "--audit", str(output)])
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertNotIn(FAKE_KEY, stderr)
            self.assertFalse(output.exists())

    def test_argument_secret_is_blocked_before_parsing(self):
        code, stdout, stderr = self.capture(["policy", "review", "v1", "--reviewer", "fixture", "--reason", FAKE_KEY])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn(FAKE_KEY, stderr)

    def test_csv_secret_is_blocked_without_echoing_row_values(self):
        row = {field: "" for field in CSV_FIELDS}
        row.update(trace_id="fixture-trace", task_id=FAKE_KEY, timestamp="2026-10-03T10:00:00Z",
                   task_type="documentation", risk_tags='["low"]', selected_model="fixture/premium",
                   model_tier="premium", input_tokens="1000", output_tokens="200", cost_usd="0.1",
                   latency_ms="1000", tests_passed="true", developer_override="false", score="1",
                   is_baseline="true", required_tools='["read"]', context_tokens="2000")
        with tempfile.TemporaryDirectory(prefix="tarkado-csv-secret-") as directory:
            path = Path(directory) / "metadata.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
                writer.writeheader()
                writer.writerow(row)
            code, stdout, stderr = self.capture(["privacy", "check", str(path), "--kind", "traces"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn(FAKE_KEY, stderr)

    def test_malformed_csv_is_a_safe_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-bad-csv-") as directory:
            path = Path(directory) / "metadata.csv"
            path.write_text(",".join(CSV_FIELDS) + '\n"unterminated ' + FAKE_KEY, encoding="utf-8")
            code, stdout, stderr = self.capture(["privacy", "check", str(path), "--kind", "traces"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn(FAKE_KEY, stderr)
        self.assertNotIn("Traceback", stderr)

    def test_invalid_arguments_do_not_echo_unknown_credentials(self):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            with self.assertRaises(SystemExit) as result:
                main(["privacy", "check", "fixture.json", "--kind", "policy", "--password", "fixture-secret"])
        self.assertEqual(result.exception.code, 2)
        self.assertNotIn("fixture-secret", error.getvalue())
        self.assertEqual(output.getvalue(), "")

    def test_os_error_diagnostics_redact_known_secret_values(self):
        with patch("engine.cli.load_policy", side_effect=OSError("Cannot read " + FAKE_KEY)):
            code, stdout, stderr = self.capture(["replay", str(FIXTURES / "synthetic.jsonl"),
                                                 "--policy", str(FIXTURES / "policy.json")])
        self.assertEqual(code, 2)
        self.assertNotIn(FAKE_KEY, stderr)
        self.assertIn("[REDACTED]", stderr)
        self.assertEqual(stdout, "")

    def test_privacy_check_validates_supported_contracts_without_echoing_values(self):
        for kind, name, extra, count in (
            ("traces", "synthetic.jsonl", [], 10),
            ("traces", "rollout.jsonl", ["--repeated"], 12),
            ("policy", "policy.json", [], 1), ("plan", "rollout-plan.json", [], 1),
        ):
            with self.subTest(kind=kind, name=name):
                code, stdout, _ = self.capture(["privacy", "check", str(FIXTURES / name), "--kind", kind] + extra)
                self.assertEqual(code, 0)
                data = json.loads(stdout)
                self.assertEqual(data["records_checked"], count)
                self.assertTrue(data["metadata_only"])
                self.assertFalse(data["supported_secret_patterns_detected"])
                self.assertNotIn("fixture/premium", stdout)
                self.assertNotIn("01-documentation", stdout)


if __name__ == "__main__":
    unittest.main()
