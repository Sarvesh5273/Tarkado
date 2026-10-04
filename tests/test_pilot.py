import copy
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from engine.cli import main
from engine.feedback import FeedbackStore, _fingerprint, import_scenario
from engine.importers import load_policy, parse_json
from engine.learning import LearningPlan, fit_feedback
from engine.pilot import PilotJournal, PilotRequest, PilotStore, _money_total
from engine.readiness import ApproverRoster, PilotScope, build_readiness, review_pilot
from engine.schemas import ValidationError


FIXTURES = Path(__file__).parent / "fixtures"


class PilotRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-pilot-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.store = PilotStore(self.directory / "pilot")
        self.policy = load_policy(FIXTURES / "policy.json")
        self.ledger = import_scenario(parse_json((FIXTURES / "feedback-demo.json").read_text()), self.policy)
        self.learner = fit_feedback(self.ledger, self.policy,
                                    LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text())))
        self.roster = ApproverRoster.from_dict(parse_json((FIXTURES / "pilot-approvers.json").read_text()))
        self.scope = PilotScope.from_dict(parse_json((FIXTURES / "pilot-scope.json").read_text()))
        self.receipt = review_pilot(build_readiness(self.ledger, self.policy, self.learner), self.scope, self.roster,
                                   "synthetic-senior", "approve", "2026-10-04T12:00:00Z", "Local fixture review",
                                   self.ledger, self.policy, self.learner)
        self.request = PilotRequest.from_dict(parse_json((FIXTURES / "pilot-request.json").read_text()))

    def activate(self):
        self.store.activate(self.receipt, self.learner, self.ledger, self.policy, self.roster,
                            "synthetic-senior", "2026-10-04T12:01:00Z", "Local fixture activation")

    def request_for(self, number=1, reserve="0.10", timestamp="2026-10-04T13:00:00Z", **updates):
        task = replace(self.request.task, task_id=f"task-{number}", session_id=f"session-{number}", timestamp=timestamp)
        return replace(self.request, decision_id=f"decision-{number}", task=task,
                       reserve_usd=Decimal(reserve) if reserve is not None else None, **updates)

    def decide(self, request=None, policy=None, ledger=None, roster=None):
        return self.store.decide(request or self.request, policy or self.policy, ledger or self.ledger, roster or self.roster)

    def settle(self, decision_id, cost="0.006", outcome="completed", timestamp="2026-10-04T14:00:00Z", identifier="settlement-1"):
        return self.store.settle({"settlement_id": identifier, "decision_id": decision_id, "timestamp": timestamp,
                                  "actual_cost_usd": cost, "outcome": outcome})

    def control(self, action, timestamp="2026-10-04T14:00:00Z", revision=None, reviewer="synthetic-senior", roster=None):
        self.store.control(action, self.store.status()["revision"] if revision is None else revision,
                           roster or self.roster, reviewer, timestamp, "Local control only",
                           self.ledger if action == "resume" else None, self.policy if action == "resume" else None)

    def test_empty_store_never_guesses_an_active_pilot(self):
        with self.assertRaises(ValidationError):
            self.store.status()
        with self.assertRaises(ValidationError):
            self.decide()
        self.assertFalse(self.store.directory.exists())

    def test_activation_requires_separate_review_and_does_not_change_policy_or_feedback(self):
        policy = self.policy.to_dict()
        ledger = self.ledger.to_dict()
        self.activate()
        state = self.store.status()
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["accounting"]["admitted_tasks"], 0)
        self.assertEqual(state["accounting"]["remaining_usd"], "1.00")
        self.assertFalse(state["routing_enabled"])
        self.assertFalse(state["deployment_authorized"])
        self.assertEqual(self.policy.to_dict(), policy)
        self.assertEqual(self.ledger.to_dict(), ledger)

    def test_rejected_receipt_and_wrong_activation_reviewer_are_refused(self):
        rejected = review_pilot(build_readiness(self.ledger, self.policy, self.learner), self.scope, self.roster,
                                "synthetic-senior", "reject", "2026-10-04T12:00:00Z", "Reject synthetic pilot",
                                self.ledger, self.policy, self.learner)
        with self.assertRaises(ValidationError):
            self.store.activate(rejected, self.learner, self.ledger, self.policy, self.roster,
                                "synthetic-senior", "2026-10-04T12:01:00Z", "Attempted activation")
        with self.assertRaises(ValidationError):
            self.store.activate(self.receipt, self.learner, self.ledger, self.policy, self.roster,
                                "synthetic-junior", "2026-10-04T12:01:00Z", "Attempted activation")
        self.assertFalse(self.store.directory.exists())

    def test_activation_retry_is_idempotent_and_cannot_reset_budget_or_revoke(self):
        self.activate()
        original = self.store.path.read_bytes()
        self.activate()
        self.assertEqual(self.store.path.read_bytes(), original)
        self.decide()
        self.control("revoke")
        self.activate()
        self.assertEqual(self.store.status()["status"], "revoked")
        self.assertEqual(self.store.status()["accounting"]["admitted_tasks"], 1)
        with self.assertRaises(ValidationError):
            self.store.activate(self.receipt, self.learner, self.ledger, self.policy, self.roster,
                                "synthetic-senior", "2026-10-04T15:00:00Z", "Different activation")

    def test_new_task_admission_reserves_budget_and_never_switches_selected_model(self):
        self.activate()
        result = self.decide()
        self.assertTrue(result["simulation_admitted"])
        self.assertEqual(result["result"]["simulated_model"], "fixture/cheap")
        self.assertEqual(result["result"]["actual_selected_model"], "fixture/premium")
        self.assertFalse(result["result"]["model_request_sent"])
        state = self.store.status()
        self.assertEqual(state["accounting"]["reserved_usd"], "0.10")
        self.assertEqual(state["accounting"]["remaining_usd"], "0.90")
        self.assertEqual(state["accounting"]["remaining_task_slots"], 4)

    def test_both_junior_and_senior_developers_use_the_same_scoped_simulation(self):
        self.activate()
        junior = self.decide(self.request_for(1))
        senior_task = replace(self.request_for(2), task=replace(self.request_for(2).task, developer_id="synthetic-senior"))
        senior = self.decide(senior_task)
        self.assertEqual(junior["result"]["simulated_model"], "fixture/cheap")
        self.assertEqual(senior["result"]["simulated_model"], "fixture/cheap")
        self.assertEqual(self.store.status()["accounting"]["admitted_tasks"], 2)

    def test_retrying_decision_is_history_not_another_admission(self):
        self.activate()
        self.decide()
        original = self.store.path.read_bytes()
        replayed = self.decide()
        self.assertTrue(replayed["historical_replay"])
        self.assertFalse(replayed["simulation_admitted"])
        self.assertFalse(replayed["new_reservation"])
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(self.store.status()["accounting"]["admitted_tasks"], 1)

    def test_same_task_with_different_decision_id_cannot_consume_another_slot(self):
        self.activate()
        self.decide()
        original = self.store.path.read_bytes()
        with self.assertRaises(ValidationError):
            self.decide(replace(self.request, decision_id="other-decision"))
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_existing_decision_id_cannot_change_cost_or_model_content(self):
        self.activate()
        self.decide()
        with self.assertRaises(ValidationError):
            self.decide(replace(self.request, reserve_usd=Decimal("0.5")))
        self.assertEqual(self.store.status()["accounting"]["reserved_usd"], "0.10")

    def test_invalid_repository_category_risk_and_unknown_commitment_use_unreserved_fallback(self):
        cases = (
            replace(self.request, repository_ref="different-repo"),
            replace(self.request, task=replace(self.request.task, task_type="test_generation")),
            replace(self.request, task=replace(self.request.task, risk_tags=("high",))),
            replace(self.request, reserve_usd=None),
        )
        for request in cases:
            with self.subTest(request=request):
                store = self.store
                self.store = PilotStore(self.directory / f"case-{len(list(self.directory.iterdir()))}")
                self.activate()
                result = self.decide(request)
                self.assertFalse(result["simulation_admitted"])
                self.assertEqual(result["result"]["status"], "fallback")
                self.assertEqual(result["result"]["simulated_model"], "fixture/premium")
                self.assertEqual(self.store.status()["accounting"]["admitted_tasks"], 0)
                self.store = store

    def test_active_task_continuation_keeps_original_model_and_consumes_nothing(self):
        self.activate()
        request = replace(self.request, boundary="continuation", task=replace(self.request.task, selected_model="fixture/standard"))
        result = self.decide(request)
        self.assertEqual(result["result"]["simulated_model"], "fixture/standard")
        self.assertEqual(result["result"]["actual_selected_model"], "fixture/standard")
        self.assertFalse(result["new_reservation"])
        self.assertEqual(self.store.status()["accounting"]["reserved_usd"], "0")

    def test_approved_compatible_developer_override_wins_inside_pilot(self):
        self.activate()
        result = self.decide(replace(self.request, override_model="fixture/standard"))
        self.assertEqual(result["result"]["simulated_model"], "fixture/standard")
        self.assertTrue(result["result"]["override_applied"])
        self.assertEqual(result["result"]["actual_selected_model"], "fixture/premium")

    def test_unknown_override_falls_back_instead_of_approving_model(self):
        self.activate()
        result = self.decide(replace(self.request, override_model="unknown/model"))
        self.assertEqual(result["result"]["status"], "fallback")
        self.assertEqual(result["result"]["simulated_model"], "fixture/premium")
        self.assertFalse(result["simulation_admitted"])

    def test_incompatible_context_blocks_default_without_inventing_compatibility(self):
        self.activate()
        result = self.decide(replace(self.request, task=replace(self.request.task, context_tokens=None)))
        self.assertEqual(result["result"]["status"], "blocked")
        self.assertIsNone(result["result"]["simulated_model"])
        self.assertEqual(self.store.status()["accounting"]["admitted_tasks"], 0)

    def test_task_slot_limit_counts_admissions_not_successful_settlements(self):
        self.activate()
        for index in range(5):
            self.assertTrue(self.decide(self.request_for(index, reserve="0.01"))["simulation_admitted"])
        result = self.decide(self.request_for(6, reserve="0.01"))
        self.assertFalse(result["simulation_admitted"])
        self.assertIn("task limit", result["result"]["reason"])
        self.assertEqual(self.store.status()["accounting"]["admitted_tasks"], 5)

    def test_budget_accounts_for_all_outstanding_reservations(self):
        self.activate()
        self.decide(self.request_for(1, reserve="0.8"))
        result = self.decide(self.request_for(2, reserve="0.3"))
        self.assertFalse(result["simulation_admitted"])
        self.assertEqual(self.store.status()["accounting"]["reserved_usd"], "0.8")
        self.assertEqual(self.store.status()["accounting"]["remaining_usd"], "0.20")

    def test_settlement_releases_unused_reservation_for_later_tasks(self):
        self.activate()
        first = self.request_for(1, reserve="0.8")
        self.decide(first)
        self.settle(first.decision_id, cost="0.1")
        later = self.decide(self.request_for(2, reserve="0.9", timestamp="2026-10-04T15:00:00Z"))
        self.assertTrue(later["simulation_admitted"])
        self.assertEqual(self.store.status()["accounting"]["spent_usd"], "0.1")
        self.assertEqual(self.store.status()["accounting"]["reserved_usd"], "0.9")
        self.assertEqual(Decimal(self.store.status()["accounting"]["remaining_usd"]), Decimal(0))

    def test_settlement_ids_and_invalid_costs_cannot_corrupt_accounting(self):
        self.activate()
        first = self.request_for(1)
        second = self.request_for(2)
        self.decide(first)
        self.decide(second)
        self.settle(first.decision_id)
        original = self.store.path.read_bytes()
        for cost, outcome, identifier in (("0.006", "completed", "settlement-1"),
                                          ("NaN", "completed", "new-settlement"),
                                          ("0.01", "cancelled", "new-settlement")):
            with self.subTest(cost=cost, outcome=outcome):
                with self.assertRaises(ValidationError):
                    self.settle(second.decision_id, cost=cost, outcome=outcome, identifier=identifier)
                self.assertEqual(self.store.path.read_bytes(), original)

    def test_roster_member_outside_reviewed_pilot_scope_gets_no_reservation(self):
        self.ledger = replace(self.ledger, team=replace(self.ledger.team,
                              members=self.ledger.team.members + (("outside-pilot-developer", "developer"),)))
        self.learner = fit_feedback(self.ledger, self.policy,
                                    LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text())))
        self.receipt = review_pilot(build_readiness(self.ledger, self.policy, self.learner), self.scope, self.roster,
                                   "synthetic-senior", "approve", "2026-10-04T12:00:00Z", "Local scope review",
                                   self.ledger, self.policy, self.learner)
        self.activate()
        request = replace(self.request, task=replace(self.request.task, developer_id="outside-pilot-developer"))
        result = self.decide(request)
        self.assertFalse(result["simulation_admitted"])
        self.assertIn("Developer is outside", result["result"]["reason"])
        self.assertEqual(self.store.status()["accounting"]["admitted_tasks"], 0)

    def test_settlement_replaces_reservation_with_exact_actual_cost(self):
        self.activate()
        self.decide()
        status = self.settle(self.request.decision_id)
        self.assertEqual(status["accounting"]["spent_usd"], "0.006")
        self.assertEqual(status["accounting"]["reserved_usd"], "0")
        self.assertEqual(status["accounting"]["remaining_usd"], "0.994")
        self.assertEqual(status["accounting"]["settled_tasks"], 1)
        self.assertEqual(status["status"], "active")

    def test_exact_settlement_retry_never_double_charges(self):
        self.activate()
        self.decide()
        self.settle(self.request.decision_id)
        original = self.store.path.read_bytes()
        self.settle(self.request.decision_id)
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(self.store.status()["accounting"]["spent_usd"], "0.006")

    def test_settlement_cannot_mutate_cost_or_charge_fallback_task(self):
        self.activate()
        self.decide()
        self.settle(self.request.decision_id)
        with self.assertRaises(ValidationError):
            self.settle(self.request.decision_id, cost="0.3")
        request = self.request_for(2, reserve=None, timestamp="2026-10-04T15:00:00Z")
        self.decide(request)
        with self.assertRaises(ValidationError):
            self.settle(request.decision_id, timestamp="2026-10-04T16:00:00Z", identifier="settlement-2")

    def test_cancellation_releases_money_but_never_resets_lifetime_task_limit(self):
        self.activate()
        self.decide()
        status = self.settle(self.request.decision_id, cost="0", outcome="cancelled")
        self.assertEqual(status["accounting"]["remaining_usd"], "1.00")
        self.assertEqual(status["accounting"]["admitted_tasks"], 1)
        self.assertEqual(status["accounting"]["remaining_task_slots"], 4)

    def test_recorded_overrun_is_not_rejected_or_hidden_and_pauses_pilot(self):
        self.activate()
        self.decide()
        status = self.settle(self.request.decision_id, cost="1.2")
        self.assertEqual(status["accounting"]["spent_usd"], "1.2")
        self.assertEqual(status["accounting"]["remaining_usd"], "-0.20")
        self.assertEqual(status["status"], "paused")
        with self.assertRaises(ValidationError):
            self.control("resume", timestamp="2026-10-04T15:00:00Z")

    def test_failure_pauses_even_when_under_budget_and_requires_new_review(self):
        self.activate()
        self.decide()
        status = self.settle(self.request.decision_id, outcome="failed")
        self.assertEqual(status["status"], "paused")
        self.assertEqual(status["accounting"]["spent_usd"], "0.006")
        with self.assertRaisesRegex(ValidationError, "new reviewed pilot"):
            self.control("resume", timestamp="2026-10-04T15:00:00Z")

    def test_pause_resume_require_expected_revision_and_preserve_accounting(self):
        self.activate()
        self.decide()
        self.control("pause")
        self.assertEqual(self.store.status()["status"], "paused")
        with self.assertRaisesRegex(ValidationError, "state changed"):
            self.control("resume", timestamp="2026-10-04T15:00:00Z", revision=2)
        self.control("resume", timestamp="2026-10-04T15:00:00Z")
        self.assertEqual(self.store.status()["status"], "active")
        self.assertEqual(self.store.status()["accounting"]["reserved_usd"], "0.10")

    def test_revoke_and_rollback_disable_future_pilot_selection_without_erasing_costs(self):
        for action, status in (("revoke", "revoked"), ("rollback", "rolled_back")):
            with self.subTest(action=action):
                self.store = PilotStore(self.directory / action)
                self.activate()
                self.decide()
                self.control(action)
                result = self.decide(self.request_for(2, timestamp="2026-10-04T15:00:00Z"))
                self.assertEqual(result["current_pilot_status"], status)
                self.assertEqual(result["result"]["simulated_model"], "fixture/premium")
                self.assertFalse(result["simulation_admitted"])
                settled = self.settle(self.request.decision_id, timestamp="2026-10-04T16:00:00Z")
                self.assertEqual(settled["status"], status)
                self.assertEqual(settled["accounting"]["spent_usd"], "0.006")
                with self.assertRaises(ValidationError):
                    self.control("resume", timestamp="2026-10-04T17:00:00Z")

    def test_replaying_old_decision_after_revocation_never_reauthorizes_it(self):
        self.activate()
        self.decide()
        self.control("revoke")
        result = self.decide()
        self.assertTrue(result["historical_replay"])
        self.assertFalse(result["simulation_admitted"])
        self.assertEqual(result["current_pilot_status"], "revoked")
        self.assertEqual(self.store.status()["accounting"]["admitted_tasks"], 1)

    def test_approval_revocation_or_policy_change_triggers_default_and_pause(self):
        self.activate()
        roster_data = self.roster.to_dict()
        roster_data["approvers"][0]["can_approve_pilots"] = False
        result = self.decide(roster=ApproverRoster.from_dict(roster_data))
        self.assertEqual(result["result"]["simulated_model"], "fixture/premium")
        self.assertFalse(result["simulation_admitted"])
        self.assertEqual(result["current_pilot_status"], "paused")
        self.store = PilotStore(self.directory / "changed-policy")
        self.activate()
        policy = replace(self.policy, policy_version="new-version", rules=())
        result = self.decide(policy=policy)
        self.assertTrue(result["result"]["used_fallback"])
        self.assertEqual(result["current_pilot_status"], "paused")

    def test_new_feedback_failure_cannot_be_ignored_by_runtime(self):
        self.activate()
        old = self.ledger.results[0]
        correction = replace(old, result_id="later-failure", desired_result=False, tests_passed=False, score=None,
                             timestamp="2026-10-04T12:02:00Z", supersedes=old.result_id)
        ledger = replace(self.ledger, results=self.ledger.results + (correction,))
        result = self.decide(ledger=ledger)
        self.assertEqual(result["result"]["status"], "fallback")
        self.assertEqual(result["current_pilot_status"], "paused")
        self.assertEqual(self.store.status()["accounting"]["admitted_tasks"], 0)

    def test_controls_require_designated_reviewer_and_cannot_backdate_events(self):
        self.activate()
        with self.assertRaises(ValidationError):
            self.control("pause", reviewer="synthetic-junior")
        with self.assertRaises(ValidationError):
            self.control("pause", timestamp="2026-10-04T11:00:00Z")
        self.assertEqual(self.store.status()["status"], "active")
        self.assertEqual(self.store.status()["revision"], 1)

    def test_corrupted_decision_cannot_rewrite_simulated_model_or_spend(self):
        self.activate()
        self.decide()
        data = self.store.read().to_dict()
        data["events"][1]["payload"]["result"]["simulated_model"] = "unknown/model"
        event = data["events"][1]
        event["event_sha256"] = _fingerprint({key: value for key, value in event.items() if key != "event_sha256"})
        with self.assertRaisesRegex(ValidationError, "differs from"):
            PilotJournal.from_dict(data)

    def test_missing_or_reordered_history_and_live_mode_are_rejected(self):
        self.activate()
        self.decide()
        for mutation in (
            lambda data: data.update(mode="live_pilot"),
            lambda data: data.update(events=[]),
            lambda data: data["events"].reverse(),
            lambda data: data["events"][0].update(event_sha256="0" * 64),
        ):
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(self.store.read().to_dict())
                mutation(data)
                with self.assertRaises(ValidationError):
                    PilotJournal.from_dict(data)

    def test_interrupted_write_and_malformed_user_state_never_overwrite_good_data(self):
        self.activate()
        original = self.store.path.read_bytes()
        with patch("engine.pilot.os.replace", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                self.decide()
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(list(self.store.directory.glob(".pilot-*")), [])
        self.store.path.write_text('{"unrelated":"user data"}', encoding="utf-8")
        original = self.store.path.read_bytes()
        with self.assertRaises(ValidationError):
            self.activate()
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_private_permissions_and_state_symlinks_are_protected(self):
        self.activate()
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.directory.stat().st_mode & 0o777, 0o700)
        target = self.directory / "user.json"
        target.write_text("user-owned data", encoding="utf-8")
        alias = self.directory / "alias"
        alias.mkdir()
        (alias / "pilot.json").symlink_to(target)
        with self.assertRaises(ValidationError):
            PilotStore(alias).read()
        self.assertEqual(target.read_text(), "user-owned data")

    def test_parallel_admissions_cannot_overreserve_budget_or_lose_decisions(self):
        self.activate()
        requests = [self.request_for(index, reserve="0.4") for index in range(4)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda request: self.decide(request), requests))
        self.assertEqual(sum(item["simulation_admitted"] for item in results), 2)
        status = self.store.status()
        self.assertEqual(status["accounting"]["reserved_usd"], "0.8")
        self.assertEqual(status["decisions_recorded"], 4)
        self.assertEqual(status["accounting"]["admitted_tasks"], 2)

    def test_exact_money_total_does_not_drop_tiny_costs(self):
        self.assertEqual(_money_total([Decimal("1"), Decimal("0.00000000000000000000000000000001")]),
                         Decimal("1.00000000000000000000000000000001"))


class PilotCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tarkado-pilot-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.feedback = self.directory / "feedback"
        self.pilot = self.directory / "pilot"
        policy = load_policy(FIXTURES / "policy.json")
        ledger = import_scenario(parse_json((FIXTURES / "feedback-demo.json").read_text()), policy)
        FeedbackStore(self.feedback).import_ledger(ledger)
        learner = fit_feedback(ledger, policy, LearningPlan.from_dict(parse_json((FIXTURES / "learning-plan.json").read_text())))
        self.learner = self.directory / "learner.json"
        learner.export(self.learner)
        roster = ApproverRoster.from_dict(parse_json((FIXTURES / "pilot-approvers.json").read_text()))
        receipt = review_pilot(build_readiness(ledger, policy, learner), PilotScope.from_dict(parse_json((FIXTURES / "pilot-scope.json").read_text())),
                               roster, "synthetic-senior", "approve", "2026-10-04T12:00:00Z", "Local fixture review", ledger, policy, learner)
        self.receipt = self.directory / "receipt.json"
        receipt.export(self.receipt)

    def run_cli(self, args):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(["pilot"] + args + ["--pilot-store", str(self.pilot)])
        return code, json.loads(output.getvalue()) if output.getvalue() else None, error.getvalue()

    def activate_args(self):
        return ["activate", "--receipt", str(self.receipt), "--learner", str(self.learner),
                "--policy", str(FIXTURES / "policy.json"), "--approvers", str(FIXTURES / "pilot-approvers.json"),
                "--reviewer", "synthetic-senior", "--timestamp", "2026-10-04T12:01:00Z",
                "--reason", "Local fixture activation", "--local-simulation", "--store", str(self.feedback)]

    def test_cli_activation_decision_settlement_and_status_never_execute_models(self):
        with patch("socket.socket", side_effect=AssertionError("No network permitted")), patch("subprocess.run", side_effect=AssertionError("No process dispatch permitted")):
            code, status, _ = self.run_cli(self.activate_args())
            self.assertEqual(code, 0)
            self.assertEqual(status["status"], "active")
            code, result, _ = self.run_cli(["decide", str(FIXTURES / "pilot-request.json"), "--policy", str(FIXTURES / "policy.json"),
                                           "--approvers", str(FIXTURES / "pilot-approvers.json"), "--store", str(self.feedback), "--local-simulation"])
            self.assertEqual(code, 0)
            self.assertTrue(result["simulation_admitted"])
            self.assertFalse(result["result"]["model_request_sent"])
            code, status, _ = self.run_cli(["settle", str(FIXTURES / "pilot-settlement.json"), "--local-simulation"])
            self.assertEqual(code, 0)
            self.assertEqual(status["accounting"]["spent_usd"], "0.006")
            code, status, _ = self.run_cli(["status"])
            self.assertEqual(code, 0)
            self.assertFalse(status["deployment_authorized"])

    def test_cli_control_changes_state_without_erasing_budget(self):
        self.run_cli(self.activate_args())
        code, state, _ = self.run_cli(["rollback", "--expected-revision", "1", "--approvers", str(FIXTURES / "pilot-approvers.json"),
                                      "--reviewer", "synthetic-senior", "--timestamp", "2026-10-04T12:02:00Z",
                                      "--reason", "Local rollback", "--local-simulation"])
        self.assertEqual(code, 0)
        self.assertEqual(state["status"], "rolled_back")
        self.assertFalse(state["routing_enabled"])

    def test_cli_requires_explicit_simulation_acknowledgement(self):
        args = self.activate_args()
        args.remove("--local-simulation")
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(["pilot"] + args)
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.pilot.exists())

    def test_cli_bad_input_has_no_partial_activation(self):
        args = self.activate_args()
        args[args.index("--reviewer") + 1] = "synthetic-junior"
        code, data, _ = self.run_cli(args)
        self.assertEqual(code, 2)
        self.assertIsNone(data)
        self.assertFalse(self.pilot.exists())


if __name__ == "__main__":
    unittest.main()
