import copy
import unittest
from decimal import Decimal
from pathlib import Path

from engine.importers import parse_json
from engine.schemas import Outcome, Policy, PolicyDecision, TaskTrace, ValidationError


FIXTURES = Path(__file__).parent / "fixtures"


def trace_data():
    return parse_json((FIXTURES / "synthetic.jsonl").read_text().splitlines()[0])


def policy_data():
    return parse_json((FIXTURES / "policy.json").read_text())


class SchemaTests(unittest.TestCase):
    def test_trace_accepts_synthetic_metadata(self):
        trace = TaskTrace.from_dict(trace_data())
        self.assertEqual(trace.cost_usd, Decimal("0.06"))
        self.assertEqual(trace.outcome.score, Decimal("1"))
        self.assertEqual(trace.context_tokens, 2000)

    def test_trace_rejects_bad_values(self):
        cases = (
            ("trace_id", ""), ("task_id", None), ("timestamp", "2026-10-03"),
            ("timestamp", "not-a-date"), ("task_type", ""), ("risk_tags", "low"),
            ("risk_tags", ["low", "low"]), ("input_tokens", True),
            ("input_tokens", -1), ("output_tokens", 0.5), ("cost_usd", "NaN"),
            ("cost_usd", "Infinity"), ("cost_usd", "-0.01"), ("cost_usd", True),
            ("latency_ms", -1), ("model_tier", "candidate"),
            ("is_baseline", "true"), ("required_tools", None), ("context_tokens", -1),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                data = trace_data()
                data[field] = value
                with self.assertRaises(ValidationError):
                    TaskTrace.from_dict(data)

    def test_raw_content_and_extra_fields_are_rejected(self):
        for field in ("prompt", "source_code", "output", "api_key", "raw_content_ref"):
            with self.subTest(field=field):
                data = trace_data()
                data[field] = "never accepted"
                with self.assertRaises(ValidationError):
                    TaskTrace.from_dict(data)

    def test_missing_required_field_is_rejected(self):
        data = trace_data()
        del data["risk_tags"]
        with self.assertRaises(ValidationError):
            TaskTrace.from_dict(data)

    def test_outcomes_can_be_unknown(self):
        outcome = Outcome.from_dict({"tests_passed": None, "developer_override": False, "score": None})
        self.assertIsNone(outcome.tests_passed)
        self.assertIsNone(outcome.score)

    def test_invalid_outcomes_are_rejected(self):
        for field, value in (("tests_passed", 1), ("developer_override", "false"), ("score", "1.01")):
            with self.subTest(field=field):
                data = {"tests_passed": True, "developer_override": False, "score": "1"}
                data[field] = value
                with self.assertRaises(ValidationError):
                    Outcome.from_dict(data)

    def test_policy_requires_a_trusted_premium_default(self):
        for update in ({"approved": False}, {"tier": "cheap"}, {"max_context_tokens": 0}):
            with self.subTest(update=update):
                data = policy_data()
                data["models"][2].update(update)
                with self.assertRaises(ValidationError):
                    Policy.from_dict(data)
        data = policy_data()
        data["default_model"] = "missing/model"
        with self.assertRaises(ValidationError):
            Policy.from_dict(data)

    def test_duplicate_models_and_rules_are_rejected(self):
        for field in ("models", "rules"):
            with self.subTest(field=field):
                data = policy_data()
                data[field].append(copy.deepcopy(data[field][0]))
                with self.assertRaises(ValidationError):
                    Policy.from_dict(data)

    def test_unknown_rule_model_is_retained_for_safe_fallback(self):
        data = policy_data()
        data["rules"][0]["model"] = "missing/model"
        self.assertEqual(Policy.from_dict(data).rules[0].model, "missing/model")

    def test_decision_validates_mode_and_recommendation(self):
        values = dict(
            policy_version="v1", recommended_model="fixture/cheap", recommended_tier="cheap",
            confidence="medium", reason="A test decision", fallback_model="fixture/premium",
            enforcement="replay", effective_model="fixture/cheap", used_fallback=False,
        )
        self.assertEqual(PolicyDecision(**values).enforcement, "replay")
        for update in ({"enforcement": "enforce"}, {"confidence": "certain"}, {"recommended_tier": None}):
            with self.subTest(update=update):
                with self.assertRaises(ValidationError):
                    PolicyDecision(**dict(values, **update))


if __name__ == "__main__":
    unittest.main()
