"""Real adapter path with controlled local-function responses/tools, never real provider inference."""

import copy
import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import test_company as support
import test_delivery as delivery_support
import test_delivery_review as review_support
from django.db import connections
from django.test import TestCase, override_settings

from engine.company import company_learning, delivery, policy_handoff, selection
from engine.company.models import Company, ConnectorTask, DeliveryBinding, ScopedSelectionRuntime
from engine.company.services import current_member
from engine.company.tasks import task_ledger
from engine.delivery_contract import (LocalFunctionChatEnvelope, LocalFunctionTool, bind_tools,
                                      chat_request, delivery_envelope, function_fingerprint)
from engine.litellm_delivery import AttemptHooks
from engine.schemas import Policy, ValidationError


FUNCTIONS = [
    {"name": "read", "description": "Read the isolated synthetic text file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "edit", "description": "Apply the isolated synthetic edit", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "run_tests", "description": "Run only the isolated synthetic unit tests without network", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
]
TOOLS = [{"type": "function", "function": item} for item in FUNCTIONS]


def setUpModule(): support.setUpModule()
def tearDownModule(): connections.close_all()


class ControlledFunctionVerifier(delivery.DeliveryVerifier):
    """Test-only runtime/tool evidence. Not a product-ready verifier or a real model price."""
    def __init__(self):
        legacy = delivery_support.ControlledDeliveryVerifier().value
        self.value = LocalFunctionChatEnvelope(**legacy.to_dict(), local_tools=tuple(
            LocalFunctionTool(function["name"], capability, function_fingerprint(function))
            for function, capability in zip(FUNCTIONS, ("read", "edit", "test"))),
            local_execution_evidence_ref="controlled-isolated-local-tools-no-provider-or-network")

    def envelope(self, company_id, deployment_id, model_id): return self.value


class ControlledFunctionProvider:
    def __init__(self, tools=("read", "edit", "run_tests")):
        self.calls, self.tools = 0, tools

    def send(self, request, fail=False):
        self.calls += 1
        if fail:
            raise TimeoutError("Controlled tool-capable provider timeout")
        result = delivery_support.ControlledProvider().send(request)
        if self.calls <= len(self.tools):
            name = self.tools[self.calls - 1]
            result["choices"] = [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_synthetic_" + str(self.calls), "type": "function", "function": {"name": name,
                 "arguments": json.dumps({"path": "calc.py"} if name != "run_tests" else {})}}]}}]
        else:
            result["choices"] = [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Synthetic final response, not engineering truth"}}]
        return result


class ControlledLocalTools:
    """Test-side replacement only for the EXISTING client's tool execution, not product code."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "calc.py"
        self.path.write_text("def add(a, b):\n    return a - b\n")
        (self.directory / "test_calc.py").write_text("import unittest\nfrom calc import add\nclass AddTests(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n")
        self.executed = []

    def execute(self, call):
        name = call["function"]["name"]
        self.executed.append(name)
        if name == "read":
            return self.path.read_text()
        if name == "edit":
            self.path.write_text("def add(a, b):\n    return a + b\n")
            return "Synthetic edit completed"
        if name == "run_tests":
            result = subprocess.run([str(support.ROOT / ".venv/bin/python"), "-m", "unittest", "discover", "-s", str(self.directory), "-q"],
                cwd=self.directory, text=True, capture_output=True, timeout=10)
            if result.returncode != 0:
                raise AssertionError(result.stdout + result.stderr)
            return "Synthetic unit test passed; no automatic task-quality label"
        raise AssertionError("No unapproved local tool may run")


class FunctionCodingTests(review_support.DeliveryFixture, TestCase):
    def setUp(self):
        review_support.DeliveryFixture.setUp(self)
        policy = copy.deepcopy(self.policy.to_dict())
        policy["models"][0]["tools"] = ["read", "edit", "test"]
        # Explicit fictional fixture capabilities, never inferred company approval.
        self.policy = Policy.from_dict(policy)
        Company.objects.update(policy=self.policy.to_dict())

    def binding(self, reserve="0.20", required=("read", "edit", "test"), verifier=None):
        approval = self.active()
        self.publication = self.sensitive(company_learning.change, "team", 0, "Publish controlled tool-task suggestions only",
            review_ref=approval.review.reference, repositories=["synthetic-repository"])
        self.verifier = verifier or ControlledFunctionVerifier()
        setting = override_settings(TARKADO_ADMISSION_VERIFIER=delivery.NarrowDeliveryAdmissionVerifier(), TARKADO_DELIVERY_VERIFIER=self.verifier)
        setting.enable(); self.addCleanup(setting.disable)
        credential, token, _ = self.pair(source_kind="team")
        started = self.api(token, "start", self.task_source(required_tools=list(required))).json()
        link = ConnectorTask.objects.get(reference=started["connector_task_ref"])
        proposal = self.value(task=task_ledger(link.task).recommendations[0].task.to_dict(), reserve_usd=reserve)
        selected = selection.select(current_member(self.junior), approval.reference, proposal, connector_link=link)
        self.assertTrue(selected["new_reservation"])
        selection.claim(current_member(self.junior), approval.reference, proposal["selection_id"])
        gateway, gateway_token = self.sensitive(delivery.issue_gateway, "controlled-functions-gateway", "synthetic-repository",
            {"junior": "employee-junior"}, support.timezone.now() + support.timedelta(hours=1), Company.objects.get().revision)
        bound = delivery.bind(credential, current_member(self.junior), link, str(approval.reference), proposal["selection_id"], str(gateway.reference))
        self.approval, self.bound, self.gateway, self.gateway_token = approval, bound, gateway, gateway_token
        self.connector_token, self.link = token, link
        self.hooks, self.provider = AttemptHooks(delivery_support.LocalBackend(gateway_token)), ControlledFunctionProvider()
        return bound

    def body(self, kind="primary", messages=None, tools=None, **updates):
        body = delivery_support.DeliveryTests.body(self, kind=kind)
        return {**body, "messages": messages or [{"role": "user", "content": [{"type": "text", "text": "Fix the isolated synthetic addition example"}]}],
                "tools": TOOLS if tools is None else tools, "tool_choice": "auto", "parallel_tool_calls": False, **updates}

    def physical(self, **updates):
        logical = self.hooks.pre_call(self.body(**updates), SimpleNamespace(user_id="employee-junior"))
        logical["model"] = "openai/fixture-provider-cheap"
        return self.hooks.pre_attempt(logical)

    def accept(self):
        self.link.task.refresh_from_db()
        result = self.api(self.connector_token, "feedback", {"connector_task_ref": str(self.link.reference),
            "location_sha256": self.link.credential.scope["location_sha256"], "action": "response", "expected_revision": self.link.task.revision, "value": "accept"})
        self.assertEqual(result.status_code, 200, result.content)
        self.link.task.refresh_from_db()

    def test_accepted_read_edit_test_loop_reserves_each_paid_continuation_on_same_model(self):
        self.binding()
        reviewed, approved = copy.deepcopy(self.approval.review.data), copy.deepcopy(self.approval.data)
        self.accept()
        messages = self.body()["messages"]
        with tempfile.TemporaryDirectory(dir=support.TEMPORARY.name) as directory:
            local = ControlledLocalTools(directory)
            for number in range(4):
                request = self.physical(messages=messages)
                self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
                self.assertEqual(self.provider.calls, number)
                self.assertEqual(request["model"], "openai/fixture-provider-cheap")
                response = self.provider.send(request)
                self.hooks.settle(request, response)
                self.assertEqual(self.state()["attempt_reserved_usd"], "0")
                message = response["choices"][0]["message"]
                messages.append(message)
                for call in message.get("tool_calls", []):
                    output = local.execute(call)
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
            self.assertEqual(local.executed, ["read", "edit", "run_tests"])
            self.assertEqual(local.path.read_text(), "def add(a, b):\n    return a + b\n")
        self.assertEqual(self.provider.calls, 4)
        self.assertEqual(self.state()["known_cost_usd"], "0.008")
        self.assertEqual(len(self.state()["attempts"]), 4)
        delivery.close_delivery(self.gateway_token, self.bound["binding_ref"])
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["spent_usd"], "0.008")
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["remaining_usd"], "0.992")
        self.assertEqual(task_ledger(self.link.task).results, ())
        self.approval.refresh_from_db(); self.approval.review.refresh_from_db()
        self.assertEqual(self.approval.data, approved)
        self.assertEqual(self.approval.review.data, reviewed)

    def test_legacy_text_contract_keeps_identical_shape_and_refuses_tools(self):
        envelope = delivery_support.ControlledDeliveryVerifier().value
        self.assertEqual(delivery_envelope(envelope.to_dict()).to_dict(), envelope.to_dict())
        self.assertNotIn("schema_version", envelope.to_dict())
        with self.assertRaises(ValidationError): bind_tools(envelope, ["read"])
        with self.assertRaises(ValidationError): chat_request({"model": envelope.gateway_model, "messages": [{"role": "user", "content": "synthetic"}],
            "tools": TOOLS, "max_completion_tokens": 1000}, envelope)

    def test_new_tool_required_scope_refuses_without_independent_function_envelope(self):
        with self.assertRaisesMessage(ValidationError, "Legacy text-only"):
            self.binding(verifier=delivery_support.ControlledDeliveryVerifier())
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["selected_tasks"], 0)

    def test_schema_name_hosted_extra_billing_and_malformed_tools_refused_before_paid_attempt(self):
        self.binding()
        changed = copy.deepcopy(TOOLS); changed[0]["function"]["parameters"]["extra"] = True
        cases = ({"tools": changed}, {"tools": [{"type": "web_search"}]}, {"tools": [TOOLS[0], TOOLS[0]]},
                 {"tools": [{"type": "function", "function": {"name": "shell", "parameters": {}}}]},
                 {"tool_choice": {"type": "function", "function": {"name": "unknown"}}}, {"prediction": {}},
                 {"modalities": ["audio"]}, {"parallel_tool_calls": "unknown"}, {"temperature": True}, {"service_tier": "priority"})
        for updates in cases:
            with self.subTest(updates=updates), self.assertRaises(ValidationError): self.physical(**updates)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.state()["attempts"], {})

    def test_bound_capability_subset_cannot_inherit_edit_or_test_tools(self):
        self.binding(required=("read",))
        self.assertEqual([tool["name"] for tool in self.bound["local_tools"]], ["read"])
        with self.assertRaises(ValidationError): self.physical()
        self.physical(tools=[TOOLS[0]])
        self.assertEqual(len(self.state()["attempts"]), 1)

    def test_changed_physical_function_definition_cannot_consume_paid_permission(self):
        self.binding()
        logical = self.hooks.pre_call(self.body(), SimpleNamespace(user_id="employee-junior")); logical["model"] = "fixture-provider-cheap"
        logical["tools"] = copy.deepcopy(TOOLS); logical["tools"][0]["function"]["description"] = "changed-late-overlay"
        with self.assertRaisesMessage(ValidationError, "definition changed"): self.hooks.pre_attempt(logical)
        self.assertEqual(self.state()["attempts"], {})

    def test_orphan_duplicate_incomplete_nontext_and_wrong_tool_results_refused(self):
        self.binding()
        user = {"role": "user", "content": "Synthetic tool task"}
        call = {"id": "synthetic_call", "type": "function", "function": {"name": "read", "arguments": "{}"}}
        assistant = {"role": "assistant", "content": None, "tool_calls": [call]}
        result = {"role": "tool", "tool_call_id": call["id"], "content": "synthetic output"}
        for messages in ([user, result], [user, assistant], [user, assistant, result, result],
                         [user, {**assistant, "tool_calls": [call, call]}, result],
                         [user, {"role": "assistant", "content": "synthetic", "tool_calls": {}}],
                         [user, {"role": "assistant", "content": None}],
                         [user, assistant, {**result, "content": [{"type": "image_url", "image_url": "synthetic"}]}],
                         [user, {**assistant, "tool_calls": [{**call, "function": {"name": "subagent", "arguments": "{}"}}]}, result]):
            with self.subTest(messages=messages), self.assertRaises(ValidationError): self.physical(messages=messages)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.state()["attempts"], {})

    def test_unknown_provider_cost_after_tools_blocks_next_continuation_without_refund(self):
        self.binding(); self.accept()
        messages = self.body()["messages"]
        request = self.physical(messages=messages)
        response = self.provider.send(request); self.hooks.settle(request, response)
        call = response["choices"][0]["message"]["tool_calls"][0]
        messages += [response["choices"][0]["message"], {"role": "tool", "tool_call_id": call["id"], "content": "synthetic file data"}]
        next_request = self.physical(messages=messages)
        with self.assertRaises(TimeoutError): self.provider.send(next_request, fail=True)
        self.hooks.settle(next_request, failed=True)
        with self.assertRaises(ValidationError): self.physical(messages=messages)
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.assertEqual(self.state()["known_cost_usd"], "0.002")

    def test_post_tool_continuation_cannot_bypass_exhausted_task_allowance(self):
        self.binding(reserve="0.04"); self.accept()
        messages = self.body()["messages"]
        request = self.physical(messages=messages)
        response = self.provider.send(request); self.hooks.settle(request, response)
        call = response["choices"][0]["message"]["tool_calls"][0]
        messages += [response["choices"][0]["message"], {"role": "tool", "tool_call_id": call["id"], "content": "synthetic data"}]
        with self.assertRaises(ValidationError): self.physical(messages=messages)
        self.assertEqual(self.state()["remaining_task_usd"], "0.038")
        self.assertEqual(self.provider.calls, 1)

    def test_local_tool_error_is_returned_as_text_not_fabricated_zero_cost_or_task_success(self):
        self.binding(); self.accept()
        messages = self.body()["messages"]
        request = self.physical(messages=messages)
        response = self.provider.send(request); self.hooks.settle(request, response)
        call = response["choices"][0]["message"]["tool_calls"][0]
        messages += [response["choices"][0]["message"], {"role": "tool", "tool_call_id": call["id"], "content": "Controlled read error: file missing"}]
        request = self.physical(messages=messages)
        self.hooks.settle(request, self.provider.send(request))
        self.assertEqual(self.state()["known_cost_usd"], "0.004")
        self.assertEqual(task_ledger(self.link.task).results, ())
        self.assertEqual(self.provider.calls, 2)

    def test_function_content_arguments_results_and_credentials_never_reach_company_journals(self):
        self.binding(); self.accept()
        request = self.physical(messages=[{"role": "user", "content": "Synthetic private function prompt\nwith code"}])
        response = self.provider.send(request); self.hooks.settle(request, response)
        call = response["choices"][0]["message"]["tool_calls"][0]
        continuation = [{"role": "user", "content": "Synthetic private function prompt\nwith code"}, response["choices"][0]["message"],
                        {"role": "tool", "tool_call_id": call["id"], "content": "Synthetic private tool source/output"}]
        request = self.physical(messages=continuation)
        self.hooks.settle(request, self.provider.send(request))
        saved = json.dumps(list(DeliveryBinding.objects.values("data", "journal")))
        for secret in ("Synthetic private function prompt", "Synthetic private tool source/output", "calc.py", FUNCTIONS[0]["description"],
                       self.bound["task_token"], self.gateway_token):
            self.assertNotIn(secret, saved)

    def test_function_envelope_requires_local_execution_evidence_and_disallows_shell(self):
        envelope = ControlledFunctionVerifier().value
        for change in ({"local_execution_evidence_ref": ""}, {"schema_version": 3},
                       {"local_tools": [{"name": "shell", "capability": "test", "function_sha256": "a" * 64}]}):
            with self.subTest(change=change), self.assertRaises(ValidationError): delivery_envelope({**envelope.to_dict(), **change})
        self.assertEqual(delivery_envelope(envelope.to_dict()).to_dict(), envelope.to_dict())
        with self.assertRaisesMessage(ValidationError, "relabelled"):
            LocalFunctionTool("edit", "read", "a" * 64).to_dict()

    def test_handoff_versions_local_tools_without_expanding_schema_one(self):
        self.binding()
        value = policy_handoff.build(self.request(), self.approval.reference)
        self.assertEqual(value["schema_version"], 2)
        self.assertEqual(value["compatibility"]["tools"], "reviewed_client_owned_functions")
        self.assertFalse(value["portable_live_approval"])
        self.assertEqual(policy_handoff.validate(value), value)
        changed = copy.deepcopy(value); changed["schema_version"] = 1
        changed["sha256"] = support.hashlib.sha256(json.dumps({key: val for key, val in changed.items() if key != "sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.assertRaises(ValidationError): policy_handoff.validate(changed)

    def test_auxiliary_calls_share_function_task_allowance_without_tool_execution(self):
        self.binding(reserve="0.05")
        self.physical(kind="title", tools=[])
        with self.assertRaises(ValidationError): self.physical(kind="compaction", tools=[])
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.assertEqual(self.state()["remaining_task_usd"], "0.01")
        self.assertEqual(self.provider.calls, 0)

    def test_completed_request_replay_cannot_repeat_paid_tools_or_switch_models(self):
        self.binding()
        body = self.body()
        logical = self.hooks.pre_call(body, SimpleNamespace(user_id="employee-junior")); logical["model"] = "fixture-provider-cheap"
        attempt = self.hooks.pre_attempt(logical)
        self.hooks.settle(attempt, self.provider.send(attempt))
        with self.assertRaises(ValidationError): self.hooks.pre_call(body, SimpleNamespace(user_id="employee-junior"))
        with self.assertRaises(ValidationError): self.hooks.pre_attempt(logical)
        with self.assertRaises(ValidationError): self.physical(model="another-model")
        self.assertEqual(len(self.state()["attempts"]), 1)
        self.assertEqual(self.provider.calls, 1)

    def test_revocation_after_tool_response_refuses_paid_continuation_but_keeps_usage(self):
        self.binding(); self.accept()
        messages = self.body()["messages"]
        attempt = self.physical(messages=messages)
        response = self.provider.send(attempt); self.hooks.settle(attempt, response)
        revision = selection._state(ScopedSelectionRuntime.objects.get())["revision"]
        self.sensitive(selection.control, self.approval.reference, "revoke", revision, "Stop future bounded function work")
        call = response["choices"][0]["message"]["tool_calls"][0]
        messages += [response["choices"][0]["message"], {"role": "tool", "tool_call_id": call["id"], "content": "Controlled existing tool result"}]
        with self.assertRaises(ValidationError): self.physical(messages=messages)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")
        self.assertEqual(self.provider.calls, 1)

    def test_tool_billing_evidence_changes_cannot_rebind_active_task(self):
        self.binding()
        from dataclasses import replace
        self.verifier.value = replace(self.verifier.value, local_execution_evidence_ref="different-operator-boundary-review")
        with self.assertRaisesMessage(ValidationError, "envelope changed"):
            self.physical()
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.state()["attempts"], {})
