import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path

from engine.cli import main
from engine.exporters import export_policy
from engine.importers import load_policy, parse_json
from engine.schemas import ValidationError


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="tarkado-export-test-")
        self.addCleanup(self.directory.cleanup)
        self.destination = Path(self.directory.name) / "local" / "proposal.json"
        self.policy = load_policy(FIXTURES / "policy.json")

    def test_versioned_policy_round_trip_preserves_canonical_fields(self):
        export_policy(self.policy, self.destination)
        self.assertEqual(load_policy(self.destination), self.policy)
        data = json.loads(self.destination.read_text())
        self.assertEqual(tuple(data), ("policy_version", "default_model", "models", "rules"))
        self.assertEqual(tuple(data["models"][0]),
                         ("model_id", "tier", "approved", "task_types", "tools", "max_context_tokens"))
        self.assertEqual(tuple(data["rules"][0]), ("task_type", "model", "evidence_refs"))

    def test_export_never_overwrites_an_existing_file(self):
        self.destination.parent.mkdir()
        self.destination.write_text("original user file", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            export_policy(self.policy, self.destination)
        self.assertEqual(self.destination.read_text(), "original user file")

    def test_invalid_policy_is_rejected_before_creating_files(self):
        with self.assertRaises(ValidationError):
            export_policy(replace(self.policy, default_model="fixture/cheap"), self.destination)
        self.assertFalse(self.destination.parent.exists())

    def test_cli_exports_without_polluting_json_stdout(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "replay", str(FIXTURES / "synthetic.jsonl"), "--policy", str(FIXTURES / "policy.json"),
                "--format", "json", "--export-policy", str(self.destination),
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["evaluated_tasks"], 7)
        self.assertEqual(load_policy(self.destination), self.policy)

    def test_cli_preserves_existing_export_and_reports_error(self):
        self.destination.parent.mkdir()
        self.destination.write_text("original user file", encoding="utf-8")
        error = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(error):
            code = main([
                "replay", str(FIXTURES / "synthetic.jsonl"), "--policy", str(FIXTURES / "policy.json"),
                "--export-policy", str(self.destination),
            ])
        self.assertEqual(code, 2)
        self.assertIn("policy export failed", error.getvalue())
        self.assertEqual(self.destination.read_text(), "original user file")

    def test_incomplete_comparison_is_printed_but_cannot_be_exported(self):
        data = parse_json((FIXTURES / "synthetic.jsonl").read_text().splitlines()[8])
        data["outcome"]["developer_override"] = False
        traces = Path(self.directory.name) / "metadata.jsonl"
        traces.write_text(json.dumps(data), encoding="utf-8")
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main([
                "replay", str(traces), "--policy", str(FIXTURES / "policy.json"),
                "--format", "json", "--export-policy", str(self.destination),
            ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["unevaluated_tasks"], 1)
        self.assertIn("export refused", error.getvalue())
        self.assertFalse(self.destination.exists())

    def test_renamed_module_entrypoint_runs(self):
        result = subprocess.run([
            sys.executable, "-m", "engine", "replay", "tests/fixtures/synthetic.jsonl",
            "--policy", "tests/fixtures/policy.json", "--format", "json",
        ], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["cost_reduction_usd"], "0.115")


if __name__ == "__main__":
    unittest.main()
