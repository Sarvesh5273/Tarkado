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
from engine.history import PolicyHistory, PolicySnapshot, PolicyStore, policy_digest
from engine.importers import load_policy, parse_json
from engine.schemas import ValidationError


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-history-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "policies"
        self.store = PolicyStore(self.directory)
        self.first = load_policy(FIXTURES / "policy.json")
        self.second = replace(self.first, policy_version="synthetic-static-v2", rules=())

    def save_and_review(self, policy):
        self.store.save(policy)
        self.store.review(policy.policy_version, "synthetic-reviewer", "Local fixture review only")

    def select_first(self):
        self.save_and_review(self.first)
        self.store.select(self.first.policy_version, "synthetic-reviewer", "Initial local selection", None)

    def select_second(self):
        self.select_first()
        self.save_and_review(self.second)
        self.store.select(self.second.policy_version, "synthetic-reviewer", "Second local selection",
                          self.first.policy_version)

    def state_data(self):
        return parse_json(self.store.state_path.read_text(encoding="utf-8"))

    def write_state(self, data):
        self.store.state_path.write_text(json.dumps(data), encoding="utf-8")

    def test_read_empty_store_does_not_create_a_directory_or_guess_a_policy(self):
        self.assertEqual(self.store.read(), PolicyHistory())
        self.assertIsNone(self.store.current_policy())
        self.assertFalse(self.directory.exists())

    def test_save_preserves_policy_content_and_does_not_select_it(self):
        snapshot = self.store.save(self.first)
        history = self.store.read()
        self.assertEqual(snapshot.policy, self.first)
        self.assertEqual(snapshot.sha256, policy_digest(self.first))
        self.assertEqual(history.snapshots, (snapshot,))
        self.assertIsNone(history.current_version)
        self.assertEqual([event.action for event in history.events], ["save"])
        self.assertEqual(PolicyHistory.from_dict(history.to_dict()), history)

    def test_identical_save_is_idempotent_without_extra_events(self):
        snapshot = self.store.save(self.first)
        original = self.store.state_path.read_bytes()
        self.assertEqual(self.store.save(self.first), snapshot)
        self.assertEqual(self.store.state_path.read_bytes(), original)
        self.assertEqual(len(self.store.read().events), 1)

    def test_reusing_version_with_different_content_is_rejected_without_changes(self):
        self.store.save(self.first)
        original = self.store.state_path.read_bytes()
        with self.assertRaisesRegex(ValidationError, "different content"):
            self.store.save(replace(self.first, rules=()))
        self.assertEqual(self.store.state_path.read_bytes(), original)

    def test_model_capability_changes_also_require_a_new_version(self):
        self.store.save(self.first)
        model = replace(self.first.models[0], max_context_tokens=4000)
        with self.assertRaises(ValidationError):
            self.store.save(replace(self.first, models=(model,) + self.first.models[1:]))

    def test_invalid_policy_does_not_create_store(self):
        with self.assertRaises(ValidationError):
            self.store.save(replace(self.first, default_model="fixture/cheap"))
        self.assertFalse(self.directory.exists())

    def test_version_labels_are_never_used_as_file_paths(self):
        policy = replace(self.first, policy_version="../../outside-version")
        self.store.save(policy)
        self.assertEqual(self.store.read().snapshot(policy.policy_version).policy, policy)
        self.assertFalse((Path(self.temporary.name) / "outside-version").exists())
        self.assertEqual({path.name for path in self.directory.iterdir()}, {".lock", "state.json"})

    def test_review_binds_content_and_never_mutates_approval_states(self):
        candidate_policy = load_policy(FIXTURES / "rollout-policy.json")
        snapshot = self.store.save(candidate_policy)
        event = self.store.review(candidate_policy.policy_version, "synthetic-reviewer", "Metadata label only")
        self.assertEqual(event.policy_sha256, snapshot.sha256)
        self.assertEqual(event.reviewer, "synthetic-reviewer")
        self.assertEqual(event.reason, "Metadata label only")
        self.assertIsNone(self.store.current_policy())
        self.assertEqual(self.store.read().snapshot(candidate_policy.policy_version).policy, candidate_policy)
        self.assertEqual(candidate_policy.model("fixture/candidate").status, "candidate")

    def test_review_requires_saved_snapshot_and_nonempty_metadata(self):
        with self.assertRaises(ValidationError):
            self.store.review(self.first.policy_version, "synthetic-reviewer", "Fixture review")
        self.assertFalse(self.directory.exists())
        self.store.save(self.first)
        for reviewer, reason in (("", "Fixture review"), ("synthetic-reviewer", "")):
            with self.subTest(reviewer=reviewer, reason=reason):
                with self.assertRaises(ValidationError):
                    self.store.review(self.first.policy_version, reviewer, reason)
        self.assertEqual(len(self.store.read().events), 1)

    def test_selection_requires_explicit_content_bound_review(self):
        self.store.save(self.first)
        original = self.store.state_path.read_bytes()
        with self.assertRaisesRegex(ValidationError, "explicit local review"):
            self.store.select(self.first.policy_version, "synthetic-reviewer", "Selection", None)
        self.assertEqual(self.store.state_path.read_bytes(), original)

    def test_local_selection_does_not_change_policy_or_model_states(self):
        self.select_first()
        self.assertEqual(self.store.current_policy(), self.first)
        history = self.store.read()
        self.assertEqual(history.events[-1].action, "select")
        self.assertIsNone(history.events[-1].previous_policy_version)
        self.assertEqual(history.snapshots[0].policy, self.first)

    def test_new_version_needs_its_own_review(self):
        self.select_first()
        self.store.save(self.second)
        with self.assertRaisesRegex(ValidationError, "explicit local review"):
            self.store.select(self.second.policy_version, "synthetic-reviewer", "Selection", self.first.policy_version)
        self.assertEqual(self.store.current_policy(), self.first)

    def test_stale_selection_is_refused_without_updating_history(self):
        self.select_second()
        original = self.store.state_path.read_bytes()
        with self.assertRaisesRegex(ValidationError, "Local selection changed"):
            self.store.select(self.first.policy_version, "synthetic-reviewer", "Stale selection", self.first.policy_version)
        self.assertEqual(self.store.state_path.read_bytes(), original)

    def test_initial_flag_cannot_overwrite_an_existing_local_selection(self):
        self.select_first()
        self.save_and_review(self.second)
        with self.assertRaises(ValidationError):
            self.store.select(self.second.policy_version, "synthetic-reviewer", "Second initial selection", None)
        self.assertEqual(self.store.current_policy(), self.first)

    def test_rollback_restores_exact_snapshot_and_records_previous_version(self):
        self.select_second()
        event = self.store.select(self.first.policy_version, "synthetic-reviewer", "Synthetic rollback",
                                  self.second.policy_version, rollback=True)
        self.assertEqual(event.action, "rollback")
        self.assertEqual(event.previous_policy_version, self.second.policy_version)
        self.assertEqual(self.store.current_policy(), self.first)
        self.assertEqual(len(self.store.read().snapshots), 2)
        self.assertEqual([event.sequence for event in self.store.read().events], list(range(1, 8)))

    def test_rollback_requires_a_previously_selected_target(self):
        self.select_first()
        self.save_and_review(self.second)
        original = self.store.state_path.read_bytes()
        with self.assertRaisesRegex(ValidationError, "previously selected"):
            self.store.select(self.second.policy_version, "synthetic-reviewer", "Not a rollback",
                              self.first.policy_version, rollback=True)
        self.assertEqual(self.store.state_path.read_bytes(), original)

    def test_rollback_cannot_be_an_initial_selection(self):
        self.save_and_review(self.first)
        with self.assertRaises(ValidationError):
            self.store.select(self.first.policy_version, "synthetic-reviewer", "Invalid rollback", None, rollback=True)
        self.assertIsNone(self.store.current_policy())

    def test_selecting_current_version_is_not_an_unrecorded_noop(self):
        self.select_first()
        with self.assertRaisesRegex(ValidationError, "already the local selection"):
            self.store.select(self.first.policy_version, "synthetic-reviewer", "Duplicate selection", self.first.policy_version)

    def test_export_restores_original_version_and_never_overwrites_files(self):
        self.select_second()
        output = Path(self.temporary.name) / "export.json"
        self.store.export(self.first.policy_version, output)
        self.assertEqual(load_policy(output), self.first)
        self.assertEqual(self.store.current_policy(), self.second)
        original = output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.store.export(self.second.policy_version, output)
        self.assertEqual(output.read_bytes(), original)

    def test_snapshot_digest_and_version_mismatch_are_rejected(self):
        data = PolicySnapshot.create(self.first).to_dict()
        for update in ({"sha256": "0" * 64}, {"policy_version": "other-version"}):
            with self.subTest(update=update):
                with self.assertRaises(ValidationError):
                    PolicySnapshot.from_dict(dict(data, **update))

    def test_corrupt_snapshot_is_not_silently_used_or_repaired(self):
        self.select_first()
        data = self.state_data()
        data["snapshots"][0]["policy"]["rules"] = []
        self.write_state(data)
        original = self.store.state_path.read_bytes()
        with self.assertRaisesRegex(ValidationError, "digest does not match"):
            self.store.current_policy()
        with self.assertRaises(ValidationError):
            self.store.save(self.second)
        self.assertEqual(self.store.state_path.read_bytes(), original)

    def test_malformed_user_file_is_never_overwritten(self):
        self.directory.mkdir()
        self.store.state_path.write_text('{"unrelated":"user work"}', encoding="utf-8")
        original = self.store.state_path.read_bytes()
        with self.assertRaises(ValidationError):
            self.store.save(self.first)
        self.assertEqual(self.store.state_path.read_bytes(), original)

    def test_invalid_history_links_and_event_shapes_are_rejected(self):
        self.select_first()
        original = self.state_data()
        mutations = (
            lambda data: data.update(schema_version=2),
            lambda data: data.update(schema_version=True),
            lambda data: data["events"][1].update(sequence=4),
            lambda data: data["events"][1].update(timestamp="2026-10-03"),
            lambda data: data["events"][1].update(reviewer=""),
            lambda data: data["events"][1].update(policy_sha256="0" * 64),
            lambda data: data["events"][2].update(previous_policy_version="missing/version"),
            lambda data: data["events"][2].update(action="rollback"),
            lambda data: data["events"][0].update(reviewer="unexpected-review"),
            lambda data: data["events"][1].update(previous_policy_version="other-version"),
            lambda data: data["events"][1].update(action="save", reviewer=None, reason=None),
            lambda data: data["snapshots"].append(data["snapshots"][0]),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                data = json.loads(json.dumps(original))
                mutation(data)
                with self.assertRaises(ValidationError):
                    PolicyHistory.from_dict(data)

    def test_review_event_cannot_be_deleted_to_bypass_gate(self):
        self.select_first()
        data = self.state_data()
        del data["events"][1]
        data["events"][1]["sequence"] = 2
        with self.assertRaisesRegex(ValidationError, "no prior content-bound review"):
            PolicyHistory.from_dict(data)

    def test_orphan_snapshot_or_missing_save_is_rejected(self):
        self.store.save(self.first)
        data = self.state_data()
        data["events"] = []
        with self.assertRaisesRegex(ValidationError, "without save records"):
            PolicyHistory.from_dict(data)

    def test_failed_atomic_replace_preserves_last_valid_state_and_cleans_temp_file(self):
        self.select_first()
        original = self.store.state_path.read_bytes()
        with patch("engine.history.os.replace", side_effect=OSError("simulated write failure")):
            with self.assertRaises(OSError):
                self.store.save(self.second)
        self.assertEqual(self.store.state_path.read_bytes(), original)
        self.assertEqual(self.store.current_policy(), self.first)
        self.assertEqual(list(self.directory.glob(".state-*.json")), [])

    def test_failed_flush_preserves_last_valid_state(self):
        self.store.save(self.first)
        original = self.store.state_path.read_bytes()
        with patch("engine.history.os.fsync", side_effect=OSError("simulated flush failure")):
            with self.assertRaises(OSError):
                self.store.save(self.second)
        self.assertEqual(self.store.state_path.read_bytes(), original)
        self.assertEqual(list(self.directory.glob(".state-*.json")), [])

    def test_state_and_lock_use_private_file_permissions(self):
        self.store.save(self.first)
        self.assertEqual(self.store.state_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.directory / ".lock").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)

    def test_state_and_store_symlinks_are_refused(self):
        target = Path(self.temporary.name) / "user.json"
        target.write_text("user-owned data", encoding="utf-8")
        self.directory.mkdir()
        self.store.state_path.symlink_to(target)
        with self.assertRaises(ValidationError):
            self.store.save(self.first)
        self.assertEqual(target.read_text(), "user-owned data")
        alias = Path(self.temporary.name) / "store-alias"
        alias.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(ValidationError):
            PolicyStore(alias).read()

    def test_lock_symlink_is_refused_without_modifying_target(self):
        target = Path(self.temporary.name) / "user-lock.txt"
        target.write_text("user-owned data", encoding="utf-8")
        self.directory.mkdir()
        (self.directory / ".lock").symlink_to(target)
        with self.assertRaises(OSError):
            self.store.save(self.first)
        self.assertEqual(target.read_text(), "user-owned data")

    def test_threaded_saves_are_serialized_without_lost_versions(self):
        policies = [replace(self.first, policy_version=f"parallel-v{index}") for index in range(6)]
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(self.store.save, policies))
        history = self.store.read()
        self.assertEqual(len(results), 6)
        self.assertEqual({snapshot.policy.policy_version for snapshot in history.snapshots},
                         {policy.policy_version for policy in policies})
        self.assertEqual([event.sequence for event in history.events], list(range(1, 7)))

    def test_two_stale_concurrent_selections_cannot_both_succeed(self):
        self.select_first()
        third = replace(self.first, policy_version="synthetic-static-v3")
        for policy in (self.second, third):
            self.save_and_review(policy)

        def select(policy):
            try:
                self.store.select(policy.policy_version, "synthetic-reviewer", "Concurrent fixture selection",
                                  self.first.policy_version)
                return True
            except ValidationError:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(select, (self.second, third)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(len([event for event in self.store.read().events if event.action == "select"]), 2)

    def test_unsupported_locking_fails_without_creating_store(self):
        with patch("engine.history.fcntl", None):
            with self.assertRaisesRegex(ValidationError, "macOS or Linux"):
                self.store.save(self.first)
        self.assertFalse(self.directory.exists())


class PolicyCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-policy-cli-test-")
        self.addCleanup(self.temporary.cleanup)
        self.store = Path(self.temporary.name) / "policies"

    def command(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(["policy"] + arguments + ["--store", str(self.store)])
        return code, json.loads(output.getvalue()) if output.getvalue() else None, error.getvalue()

    def test_save_review_select_history_and_export_work_without_network(self):
        with patch("socket.socket", side_effect=AssertionError("No network allowed")):
            code, data, _ = self.command(["save", str(FIXTURES / "policy.json")])
            self.assertEqual(code, 0)
            self.assertFalse(data["deployment_authorized"])
            self.assertTrue(data["local_only"])
            code, data, _ = self.command(["review", "synthetic-static-v1", "--reviewer", "synthetic-reviewer",
                                         "--reason", "Local fixture review"])
            self.assertEqual(code, 0)
            self.assertEqual(data["action"], "review")
            code, data, _ = self.command(["select", "synthetic-static-v1", "--initial", "--reviewer", "synthetic-reviewer",
                                         "--reason", "Local fixture selection"])
            self.assertEqual(code, 0)
            self.assertEqual(data["action"], "select")
            _, data, _ = self.command(["current"])
            self.assertEqual(data["current_policy_version"], "synthetic-static-v1")
            _, data, _ = self.command(["history"])
            self.assertEqual(data["snapshot_count"], 1)
            self.assertEqual(data["event_count"], 3)
            output = Path(self.temporary.name) / "restored.json"
            code, data, _ = self.command(["export", "synthetic-static-v1", "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(load_policy(output), load_policy(FIXTURES / "policy.json"))

    def test_cli_rollback_restores_previous_reviewed_selection(self):
        first = load_policy(FIXTURES / "policy.json")
        second = replace(first, policy_version="synthetic-static-v2", rules=())
        store = PolicyStore(self.store)
        for policy, previous in ((first, None), (second, first.policy_version)):
            store.save(policy)
            store.review(policy.policy_version, "synthetic-reviewer", "Fixture review")
            store.select(policy.policy_version, "synthetic-reviewer", "Fixture selection", previous)
        code, data, _ = self.command(["rollback", first.policy_version, "--expected-current", second.policy_version,
                                     "--reviewer", "synthetic-reviewer", "--reason", "Restore first fixture"])
        self.assertEqual(code, 0)
        self.assertEqual(data["action"], "rollback")
        self.assertFalse(data["deployment_authorized"])
        self.assertEqual(store.current_policy(), first)

    def test_read_commands_are_clear_when_no_selection_exists(self):
        code, data, _ = self.command(["current"])
        self.assertEqual(code, 0)
        self.assertIsNone(data["current_policy_version"])
        self.assertIsNone(data["last_selection"])
        self.assertFalse(self.store.exists())

    def test_unreviewed_cli_selection_returns_error_without_stdout(self):
        self.command(["save", str(FIXTURES / "policy.json")])
        code, data, error = self.command(["select", "synthetic-static-v1", "--initial", "--reviewer", "synthetic-reviewer",
                                         "--reason", "Unreviewed fixture"])
        self.assertEqual(code, 2)
        self.assertIsNone(data)
        self.assertIn("explicit local review", error)

    def test_parser_requires_initial_or_expected_current(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(["policy", "select", "v1", "--reviewer", "synthetic-reviewer", "--reason", "Fixture selection"])
        self.assertEqual(error.exception.code, 2)

    def test_module_policy_entrypoint_reads_empty_history(self):
        result = subprocess.run([sys.executable, "-m", "engine", "policy", "history", "--store", str(self.store)],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["snapshot_count"], 0)
        self.assertEqual(data["event_count"], 0)
        self.assertFalse(data["deployment_authorized"])


if __name__ == "__main__":
    unittest.main()
