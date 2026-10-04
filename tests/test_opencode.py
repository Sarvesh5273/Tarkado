import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from engine.cli import main
from engine.importers import load_policy
from engine.opencode import AdapterError, OpenCodeReader, SNAPSHOT_FIELDS, SessionSnapshot, load_snapshot
from engine.privacy import PrivacyError
from engine.schemas import ValidationError


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SESSION_ID = "ses_fixture"
FAKE_KEY = "sk-" + "A" * 32


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-observer-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.policy = load_policy(FIXTURES / "policy.json")
        self.session = {
            "id": SESSION_ID, "projectID": "project-fixture", "agent": "build",
            "model": {"providerID": "fixture", "id": "premium"},
            "time": {"created": 1000, "updated": 2000}, "location": {"directory": str(self.directory)},
            "tokens": {"input": 1000, "output": 200, "reasoning": 50, "cache": {"read": 100, "write": 20}},
            "cost": 0.1, "outcome": "succeeded",
            "title": "private title should not be read or persisted",
            "metadata": {"api_key": FAKE_KEY, "prompt": "private prompt should not be copied"},
            "permissions": [{"resource": "private/source.py"}],
        }
        self.catalog_entry = {
            "id": "premium", "modelID": "underlying-provider-model", "providerID": "fixture",
            "name": "not persisted", "enabled": True,
            "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
            "limit": {"context": 64000, "output": 8192},
            "headers": {"authorization": "Bearer " + FAKE_KEY},
            "settings": {"apiKey": FAKE_KEY}, "body": {"prompt": "private"},
        }
        self.responses = []
        self.which = patch("engine.opencode.shutil.which", return_value="/fake/opencode")
        self.which.start()
        self.addCleanup(self.which.stop)

    def transport(self, command, **kwargs):
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["timeout"], 30)
        self.responses.append(command)
        if command[1:] == ["--version"]:
            output = "opencode v2.0.21\n"
        elif command[1:3] == ["api", "get"] and command[3] == "/api/session/" + SESSION_ID:
            output = json.dumps({"data": self.session})
        elif command[1:3] == ["api", "get"] and command[3].startswith("/api/model?"):
            output = json.dumps({"location": {"directory": str(self.directory)}, "data": [self.catalog_entry]})
        else:
            self.fail("Observer attempted an unsupported or mutating command: " + repr(command))
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    def observe(self, policy=None, company_api=True):
        with patch("engine.opencode.subprocess.run", side_effect=self.transport):
            return OpenCodeReader().observe(SESSION_ID, self.directory, policy or self.policy, company_api)

    def test_only_version_and_allowlisted_gets_are_called(self):
        snapshot = self.observe().to_dict()
        self.assertEqual(len(self.responses), 3)
        self.assertEqual(self.responses[1][1:], ["api", "get", "/api/session/" + SESSION_ID])
        self.assertTrue(self.responses[2][3].startswith("/api/model?location%5Bdirectory%5D="))
        self.assertEqual(snapshot["selected_model"], "fixture/premium")
        self.assertEqual(snapshot["mode"], "observe")
        self.assertFalse(snapshot["task_boundary_observed"])
        self.assertFalse(snapshot["deployment_authorized"])

    def test_snapshot_projects_no_prompts_credentials_titles_or_raw_paths(self):
        data = json.dumps(self.observe().to_dict())
        for private in (FAKE_KEY, "private prompt", "private title", "private/source.py", str(self.directory), SESSION_ID):
            self.assertNotIn(private, data)
        for field in ('"prompt"', '"headers"', '"body"', '"settings"', '"permissions"', '"title"'):
            self.assertNotIn(field, data)

    def test_original_session_catalog_and_team_policy_are_unchanged(self):
        before = copy.deepcopy(self.session)
        catalog = copy.deepcopy(self.catalog_entry)
        policy = self.policy.to_dict()
        self.observe()
        self.assertEqual(self.session, before)
        self.assertEqual(self.catalog_entry, catalog)
        self.assertEqual(self.policy.to_dict(), policy)

    def test_unknown_explicit_model_does_not_trigger_catalog_or_approval(self):
        self.session["model"] = {"providerID": "unknown", "id": "new-model"}
        snapshot = self.observe().to_dict()
        self.assertEqual(len(self.responses), 2)
        self.assertEqual(snapshot["selected_model"], "unknown/new-model")
        self.assertFalse(snapshot["model_in_team_registry"])
        self.assertIsNone(snapshot["team_model_status"])
        self.assertIsNone(snapshot["catalog"])

    def test_unset_session_model_is_not_inferred_from_default(self):
        del self.session["model"]
        snapshot = self.observe().to_dict()
        self.assertIsNone(snapshot["selected_model"])
        self.assertIsNone(snapshot["catalog"])
        self.assertEqual(len(self.responses), 2)

    def test_variant_is_preserved_without_changing_session_model(self):
        self.session["model"]["variant"] = "high"
        snapshot = self.observe().to_dict()
        self.assertEqual(snapshot["variant"], "high")
        self.assertEqual(self.session["model"]["variant"], "high")

    def test_child_session_reference_does_not_claim_a_subagent_task_boundary(self):
        self.session["parentID"] = "ses_parent_fixture"
        snapshot = self.observe().to_dict()
        self.assertEqual(snapshot["scope"], "child_session")
        self.assertIsNotNone(snapshot["parent_session_ref"])
        self.assertNotIn("ses_parent_fixture", json.dumps(snapshot))
        self.assertFalse(snapshot["task_boundary_observed"])

    def test_cumulative_usage_includes_reasoning_cache_and_no_quality_claim(self):
        snapshot = self.observe().to_dict()
        self.assertEqual(snapshot["tokens"], {"input": 1000, "output": 200, "reasoning": 50, "cache_read": 100, "cache_write": 20})
        self.assertEqual(snapshot["cost_usd"], "0.1")
        self.assertEqual(snapshot["session_outcome"], "succeeded")
        self.assertIsNone(snapshot["tests_passed"])
        self.assertIsNone(snapshot["score"])

    def test_missing_usage_is_unknown_not_zero(self):
        del self.session["tokens"]
        del self.session["cost"]
        snapshot = self.observe().to_dict()
        self.assertIsNone(snapshot["tokens"])
        self.assertIsNone(snapshot["cost_usd"])

    def test_unverified_catalog_never_updates_approved_limits(self):
        self.catalog_entry["limit"]["context"] = 200000
        self.catalog_entry["capabilities"]["tools"] = False
        snapshot = self.observe().to_dict()
        self.assertEqual(snapshot["catalog"]["context_tokens"], 200000)
        self.assertFalse(snapshot["catalog"]["supports_tools"])
        self.assertEqual(snapshot["catalog"]["provenance"], "resolved_catalog_unverified")
        self.assertEqual(self.policy.model("fixture/premium").max_context_tokens, 64000)

    def test_missing_catalog_capabilities_remain_unknown(self):
        del self.catalog_entry["capabilities"]
        del self.catalog_entry["limit"]
        snapshot = self.observe().to_dict()
        self.assertIsNone(snapshot["catalog"]["supports_tools"])
        self.assertIsNone(snapshot["catalog"]["context_tokens"])

    def test_missing_selected_catalog_entry_is_not_fabricated(self):
        self.catalog_entry["id"] = "other-model"
        self.assertIsNone(self.observe().to_dict()["catalog"])

    def test_catalog_wrong_location_and_duplicate_entries_are_refused(self):
        for response in (
            {"location": {"directory": "/another-location"}, "data": [self.catalog_entry]},
            {"location": {"directory": str(self.directory)}, "data": [self.catalog_entry, self.catalog_entry]},
        ):
            with self.subTest(location=response["location"], count=len(response["data"])):
                def transport(command, **kwargs):
                    if command[1:3] == ["api", "get"] and command[3].startswith("/api/model?"):
                        return subprocess.CompletedProcess(command, 0, json.dumps(response), "")
                    return self.transport(command, **kwargs)
                with patch("engine.opencode.subprocess.run", side_effect=transport):
                    with self.assertRaises(AdapterError):
                        OpenCodeReader().observe(SESSION_ID, self.directory, self.policy, True)

    def test_invalid_timeout_cannot_disable_read_limits(self):
        for timeout in (0, -1, 121, True):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValidationError):
                    OpenCodeReader(timeout_seconds=timeout)

    def test_company_attestation_is_required_before_reading_opencode(self):
        with self.assertRaises(ValidationError):
            self.observe(company_api=False)
        self.assertEqual(self.responses, [])

    def test_cross_project_or_missing_location_is_refused(self):
        for location in ({"directory": "/different-project"}, None):
            with self.subTest(location=location):
                self.session["location"] = location
                self.responses = []
                with self.assertRaises(AdapterError):
                    self.observe()
                self.assertEqual(len(self.responses), 2)

    def test_session_response_mismatch_is_not_silently_observed(self):
        self.session["id"] = "ses_other"
        with self.assertRaises(AdapterError):
            self.observe()

    def test_bad_tokens_timestamps_and_outcomes_are_rejected(self):
        original = copy.deepcopy(self.session)
        mutations = (
            lambda: self.session["tokens"].update(input=-1),
            lambda: self.session["tokens"].update(reasoning=1.5),
            lambda: self.session.update(cost="NaN"),
            lambda: self.session["time"].update(updated=0),
            lambda: self.session.update(outcome="tests_passed"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.session = copy.deepcopy(original)
                mutation()
                with self.assertRaises((ValidationError, AdapterError)):
                    self.observe()

    def test_secrets_in_projected_model_fields_are_blocked(self):
        self.session["model"]["id"] = FAKE_KEY
        with self.assertRaises(PrivacyError) as error:
            self.observe()
        self.assertNotIn(FAKE_KEY, str(error.exception))

    def test_v1_missing_executable_timeout_and_bad_response_do_not_fall_back(self):
        with patch("engine.opencode.shutil.which", return_value=None):
            with self.assertRaises(AdapterError):
                OpenCodeReader()
        reader = OpenCodeReader()
        for output in ("opencode v1.18.29\n", "unknown version", FAKE_KEY):
            with self.subTest(output_kind=output[:8]):
                with patch("engine.opencode.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output, "")):
                    with self.assertRaises(AdapterError):
                        reader.version()
        with patch("engine.opencode.subprocess.run", side_effect=subprocess.TimeoutExpired("opencode", 30, output=FAKE_KEY)):
            with self.assertRaises(AdapterError) as error:
                reader.version()
            self.assertNotIn(FAKE_KEY, str(error.exception))
        with patch("engine.opencode.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "invalid json " + FAKE_KEY, "")):
            with self.assertRaises(AdapterError) as error:
                reader.get("/api/session/" + SESSION_ID)
            self.assertNotIn(FAKE_KEY, str(error.exception))

    def test_raw_process_failure_diagnostics_are_withheld(self):
        with patch("engine.opencode.subprocess.run", return_value=subprocess.CompletedProcess([], 1, FAKE_KEY, FAKE_KEY)):
            with self.assertRaises(AdapterError) as error:
                OpenCodeReader().version()
        self.assertNotIn(FAKE_KEY, str(error.exception))

    def test_invalid_session_ids_and_get_endpoints_are_never_run(self):
        with patch("engine.opencode.subprocess.run") as run:
            reader = OpenCodeReader()
            for session_id in ("ses?query=1", "../ses_fixture", "not-a-session"):
                with self.subTest(session_id=session_id):
                    with self.assertRaises(ValidationError):
                        reader.observe(session_id, self.directory, self.policy, True)
            for path in ("/api/session", "/api/config", "/api/integration", "/api/model/default",
                         "/api/session/ses_fixture/message", "/api/model?location[directory]=/project&secret=x"):
                with self.subTest(path=path):
                    with self.assertRaises(AdapterError):
                        reader.get(path)
            run.assert_not_called()

    def test_snapshot_contract_blocks_raw_content_false_quality_and_enforcement(self):
        data = self.observe().to_dict()
        self.assertEqual(tuple(data), SNAPSHOT_FIELDS)
        for update in ({"prompt": "not accepted"}, {"mode": "pilot"}, {"deployment_authorized": True},
                       {"tests_passed": True}, {"task_boundary_observed": True}, {"company_api_attested": False},
                       {"session_ref": "raw-session"}, {"scope": "child_session"}):
            with self.subTest(update=update):
                with self.assertRaises(ValidationError):
                    SessionSnapshot.from_dict(dict(data, **update))

    def test_private_snapshot_export_roundtrips_and_never_overwrites(self):
        snapshot = self.observe()
        path = self.directory / "snapshot.jsonl"
        snapshot.export(path)
        self.assertEqual(SessionSnapshot.from_dict(json.loads(path.read_text())), snapshot)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            snapshot.export(path)
        self.assertEqual(path.read_bytes(), original)

    def test_empty_or_multiple_snapshot_records_are_rejected(self):
        path = self.directory / "snapshot.jsonl"
        path.write_text("", encoding="utf-8")
        with self.assertRaises(ValidationError):
            load_snapshot(path)
        snapshot = self.observe().to_dict()
        path.write_text(json.dumps(snapshot) + "\n" + json.dumps(snapshot), encoding="utf-8")
        with self.assertRaises(ValidationError):
            load_snapshot(path)


class MockExecutableIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-mock-opencode-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.state = self.directory / "mock-state.json"
        self.commands = self.directory / "mock-commands.jsonl"
        self.executable = self.directory / "mock-opencode"
        self.original = {
            "session": {"id": SESSION_ID, "projectID": "fixture-project",
                        "model": {"providerID": "fixture", "id": "premium"},
                        "time": {"created": 1000, "updated": 2000},
                        "location": {"directory": str(self.directory)},
                        "title": "not exported", "metadata": {"api_key": FAKE_KEY}},
            "models": [{"providerID": "fixture", "id": "premium", "enabled": True,
                       "capabilities": {"tools": True}, "limit": {"context": 64000},
                       "headers": {"api-key": FAKE_KEY}}],
        }
        self.state.write_text(json.dumps(self.original), encoding="utf-8")
        # This local fake API executable never calls a model or starts a service.
        script = "#!" + sys.executable + "\n" + '''import json, sys
from pathlib import Path
root = Path(__file__).parent
with (root / "mock-commands.jsonl").open("a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
state = json.loads((root / "mock-state.json").read_text())
if sys.argv[1:] == ["--version"]:
    print("opencode v2.0.21")
elif sys.argv[1:3] == ["api", "get"] and sys.argv[3] == "/api/session/ses_fixture":
    print(json.dumps({"data": state["session"]}))
elif sys.argv[1:3] == ["api", "get"] and sys.argv[3].startswith("/api/model?"):
    print(json.dumps({"location": {"directory": str(root)}, "data": state["models"]}))
else:
    sys.exit(9)
'''
        self.executable.write_text(script, encoding="utf-8")
        self.executable.chmod(0o700)

    def arguments(self):
        return ["opencode", "observe", "--session", SESSION_ID, "--directory", str(self.directory),
                "--policy", str(FIXTURES / "policy.json"), "--company-api", "--executable", str(self.executable)]

    def test_cli_observes_mock_without_changing_selection_or_exposing_secrets(self):
        output = self.directory / "observed.jsonl"
        stdout = io.StringIO()
        before = self.state.read_bytes()
        with redirect_stdout(stdout):
            code = main(self.arguments() + ["--output", str(output)])
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["selected_model"], "fixture/premium")
        self.assertEqual(data["catalog"]["context_tokens"], 64000)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertNotIn(FAKE_KEY, stdout.getvalue())
        self.assertNotIn(FAKE_KEY, output.read_text())
        commands = [json.loads(line) for line in self.commands.read_text().splitlines()]
        self.assertEqual(len(commands), 3)
        self.assertTrue(all(command[:2] == ["api", "get"] for command in commands[1:]))

    def test_cli_refuses_existing_snapshot_and_preserves_it(self):
        output = self.directory / "observed.jsonl"
        output.write_text("user-owned file", encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(self.arguments() + ["--output", str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(output.read_text(), "user-owned file")
        self.assertEqual(json.loads(stdout.getvalue())["selected_model"], "fixture/premium")

    def test_privacy_check_validates_snapshot_without_revealing_selected_model(self):
        output = self.directory / "observed.jsonl"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(self.arguments() + ["--output", str(output)]), 0)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["privacy", "check", str(output), "--kind", "snapshot"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["records_checked"], 1)
        self.assertNotIn("fixture/premium", stdout.getvalue())

    def test_cli_company_api_flag_is_required_and_no_process_is_started_without_it(self):
        args = self.arguments()
        args.remove("--company-api")
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(args)
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.commands.exists())

    def test_module_cli_runs_against_local_mock_executable(self):
        result = subprocess.run([sys.executable, "-m", "engine"] + self.arguments(), cwd=ROOT,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["task_boundary_observed"])
        self.assertFalse(json.loads(result.stdout)["deployment_authorized"])


if __name__ == "__main__":
    unittest.main()
