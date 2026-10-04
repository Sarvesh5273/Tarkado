import unittest
from pathlib import Path

from engine.importers import load_policy, load_traces, parse_json
from engine.policy import decide
from engine.schemas import Policy, TaskTrace, ValidationError


FIXTURES = Path(__file__).parent / "fixtures"


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        self.trace_data = parse_json((FIXTURES / "synthetic.jsonl").read_text().splitlines()[0])

    def trace(self, **updates):
        return TaskTrace.from_dict(dict(self.trace_data, **updates))

    def modified_policy(self, change):
        data = parse_json((FIXTURES / "policy.json").read_text())
        change(data)
        return Policy.from_dict(data)

    def test_low_risk_rule_chooses_approved_cheap_model(self):
        decision = decide(self.policy, self.trace())
        self.assertEqual(decision.recommended_model, "fixture/cheap")
        self.assertEqual(decision.effective_model, "fixture/cheap")
        self.assertEqual(decision.policy_version, "synthetic-static-v1")
        self.assertEqual(decision.confidence, "medium")
        self.assertTrue(decision.evidence_refs)
        self.assertFalse(decision.used_fallback)

    def test_high_unknown_or_missing_risk_falls_back(self):
        for tags in (["high"], ["security"], ["low", "security"], [], ["unexpected"]):
            with self.subTest(tags=tags):
                decision = decide(self.policy, self.trace(risk_tags=tags))
                self.assertTrue(decision.used_fallback)
                self.assertEqual(decision.recommended_model, "fixture/premium")

    def test_unknown_task_and_unmatched_rule_fall_back(self):
        for task_type in (None, "new_task_type"):
            with self.subTest(task_type=task_type):
                self.assertEqual(decide(self.policy, self.trace(task_type=task_type)).effective_model, "fixture/premium")

    def test_rule_without_evidence_falls_back(self):
        policy = self.modified_policy(lambda data: data["rules"][0].update(evidence_refs=[]))
        self.assertTrue(decide(policy, self.trace()).used_fallback)

    def test_unknown_or_unapproved_rule_model_falls_back(self):
        policies = (
            self.modified_policy(lambda data: data["rules"][0].update(model="missing/model")),
            self.modified_policy(lambda data: data["models"][0].update(approved=False)),
        )
        for policy in policies:
            with self.subTest(policy=policy.rules[0].model):
                self.assertEqual(decide(policy, self.trace()).recommended_model, "fixture/premium")

    def test_tool_and_context_limits_fall_back(self):
        for updates in ({"required_tools": ["edit"]}, {"context_tokens": 9000}):
            with self.subTest(updates=updates):
                self.assertEqual(decide(self.policy, self.trace(**updates)).effective_model, "fixture/premium")

    def test_incompatible_default_blocks_instead_of_guessing(self):
        for updates in ({"required_tools": ["unknown_tool"]}, {"context_tokens": 64001}, {"context_tokens": None}):
            with self.subTest(updates=updates):
                decision = decide(self.policy, self.trace(**updates))
                self.assertTrue(decision.used_fallback)
                self.assertIsNone(decision.recommended_model)
                self.assertIsNone(decision.effective_model)
                self.assertIn("no route is authorized", decision.reason)

    def test_model_task_type_approval_is_required(self):
        policy = self.modified_policy(lambda data: data["models"][0].update(task_types=["other_task"]))
        self.assertEqual(decide(policy, self.trace()).recommended_model, "fixture/premium")

    def test_observe_and_shadow_never_change_original_selection(self):
        for trace in load_traces(FIXTURES / "synthetic.jsonl"):
            for mode in ("observe", "shadow"):
                with self.subTest(trace=trace.trace_id, mode=mode):
                    self.assertEqual(decide(self.policy, trace, mode).effective_model, trace.selected_model)
        shadow = decide(self.policy, self.trace(), "shadow")
        self.assertEqual(shadow.recommended_model, "fixture/cheap")
        self.assertEqual(shadow.effective_model, "fixture/premium")

    def test_approved_developer_override_is_retained(self):
        outcome = dict(self.trace_data["outcome"], developer_override=True)
        decision = decide(self.policy, self.trace(outcome=outcome))
        self.assertEqual(decision.effective_model, "fixture/premium")
        self.assertIn("override retained", decision.reason)

    def test_invalid_override_is_not_authorized_but_shadow_preserves_observation(self):
        outcome = dict(self.trace_data["outcome"], developer_override=True)
        trace = self.trace(outcome=outcome, selected_model="unapproved/model")
        self.assertEqual(decide(self.policy, trace).effective_model, "fixture/premium")
        self.assertEqual(decide(self.policy, trace, "shadow").effective_model, "unapproved/model")

    def test_live_modes_are_not_implemented(self):
        for mode in ("pilot", "enforce", "unknown"):
            with self.subTest(mode=mode):
                with self.assertRaises(ValidationError):
                    decide(self.policy, self.trace(), mode)


if __name__ == "__main__":
    unittest.main()
