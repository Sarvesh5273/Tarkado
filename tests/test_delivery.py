"""Real adapter path with controlled provider responses. No installed gateway or generation."""

import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import test_company as support
import test_connectors as connector_support
import test_selection as selection_support
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from engine.company import connectors, delivery, delivery_views, selection
from engine.company.models import Company, DeliveryBinding, GatewayCredential, ScopedSelectionRuntime, SecurityEvent
from engine.company.services import current_member
from engine.company.tasks import task_ledger
from engine.company.billing_gate import BillingVerifier, BillingAssessment
from engine.feedback import _fingerprint
from engine.delivery_contract import TextChatEnvelope, chat_usage
from engine.litellm_delivery import AttemptHooks


def setUpModule(): support.setUpModule()
def tearDownModule(): connections.close_all()


class ControlledDeliveryVerifier(delivery.DeliveryVerifier):
    """Deliberately test-only host/billing evidence, not an installable product verifier."""
    def __init__(self):
        self.value = TextChatEnvelope("fixture/cheap", "company-cheap", "fixture-provider-cheap", 2000, 1000,
            "10", "5", "20", "0", "controlled-fake-billing-contract", (timezone.now() + timedelta(hours=1)).isoformat(), timezone.now().isoformat())

    def envelope(self, company_id, deployment_id, model_id): return self.value


class LocalBackend:
    def __init__(self, token): self.token = token
    def call(self, operation, value):
        import threading
        try: return delivery_views.invoke(self.token, operation, value)
        finally:
            if threading.current_thread() is not threading.main_thread(): connections.close_all()


class ControlledBillingVerifier(BillingVerifier):
    def verify(self, request):
        now = timezone.now()
        return BillingAssessment(_fingerprint(request), "controlled-invoice-only", "test-only-billing-checker",
                                 now.isoformat(), (now + timedelta(minutes=5)).isoformat())


class ControlledProvider:
    def __init__(self): self.calls = 0
    def send(self, request, fail=False, missing_usage=False, model="fixture-provider-cheap"):
        self.calls += 1
        if fail:
            raise TimeoutError("Synthetic private provider error content; never retain this")
        return {"model": model, "service_tier": "default", "choices": [{"message": {"content": "Synthetic private output; never retain this"}}],
                "usage": None if missing_usage else {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
                "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 10}}}


class DeliveryTests(TestCase):
    setUp = selection_support.SelectionTests.setUp
    enroll = selection_support.SelectionTests.enroll
    request = selection_support.SelectionTests.request
    sensitive = selection_support.SelectionTests.sensitive
    source = selection_support.SelectionTests.source
    evidence = selection_support.SelectionTests.evidence
    approve = selection_support.SelectionTests.approve
    scope = selection_support.SelectionTests.scope
    developer_request = selection_support.SelectionTests.developer_request
    task = selection_support.SelectionTests.task
    active = selection_support.SelectionTests.active
    value = selection_support.SelectionTests.value
    pair = connector_support.ConnectorTests.pair
    api = connector_support.ConnectorTests.api
    task_source = connector_support.ConnectorTests.task_source

    def binding(self, reserve="0.10"):
        approval = self.active()
        verifier = ControlledDeliveryVerifier()
        settings = override_settings(TARKADO_ADMISSION_VERIFIER=delivery.NarrowDeliveryAdmissionVerifier(), TARKADO_DELIVERY_VERIFIER=verifier)
        settings.enable(); self.addCleanup(settings.disable)
        credential, connector_token, _ = self.pair(source_kind="team")
        source = self.task_source(required_tools=[])
        started = self.api(connector_token, "start", source).json()
        link = connectors.ConnectorTask.objects.get(reference=started["connector_task_ref"])
        proposal = self.value(task=task_ledger(link.task).recommendations[0].task.to_dict(), reserve_usd=reserve)
        member = current_member(self.junior)
        selected = selection.select(member, approval.reference, proposal, connector_link=link)
        selection.claim(member, approval.reference, selected["selection"]["selection_id"])
        gateway, gateway_token = self.sensitive(delivery.issue_gateway, "controlled-gateway", "synthetic-repository",
            {"junior": "employee-junior"}, timezone.now() + timedelta(hours=1), Company.objects.get().revision)
        result = delivery.bind(credential, member, link, str(approval.reference), proposal["selection_id"], str(gateway.reference))
        self.approval, self.bound, self.gateway_token, self.gateway = approval, result, gateway_token, gateway
        self.connector_token, self.link, self.verifier = connector_token, link, verifier
        self.hooks, self.provider = AttemptHooks(LocalBackend(gateway_token)), ControlledProvider()
        return result

    def body(self, kind="primary", **updates):
        bound = self.bound
        return {"model": "company-cheap", "messages": [{"role": "user", "content": "Synthetic private prompt; never retain this"}],
            "max_completion_tokens": 1000, "store": False, "metadata": {"tarkado_binding": bound["binding_ref"],
            "tarkado_task": bound["task_token"], "tarkado_session": bound["session_ref"],
            "tarkado_request": str(uuid.uuid4()), "tarkado_kind": kind}, **updates}

    def physical(self, **updates):
        request = self.hooks.pre_call(self.body(**updates), SimpleNamespace(user_id="employee-junior"))
        request["model"] = "openai/fixture-provider-cheap"
        return self.hooks.pre_attempt(request)

    def state(self): return delivery.state(DeliveryBinding.objects.get())

    def test_real_adapter_reserves_before_fake_provider_and_joins_complete_settlement(self):
        self.binding()
        request = self.physical()
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.assertEqual(self.provider.calls, 0)
        response = self.provider.send(request)
        self.hooks.settle(request, response)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")
        self.assertEqual(self.state()["unknown_attempts"], 0)
        self.assertEqual(task_ledger(self.link.task).executions, ())
        final = delivery.close_delivery(self.gateway_token, self.bound["binding_ref"])
        self.assertTrue(final["closed"])
        money = selection.accounting(ScopedSelectionRuntime.objects.get())
        self.assertEqual(money["spent_usd"], "0.002")
        self.assertEqual(money["reserved_usd"], "0")
        self.assertEqual(money["remaining_usd"], "0.998")
        self.assertEqual(ScopedSelectionRuntime.objects.get().journal["events"][-1]["actor"],
                         {"gateway_ref": str(self.gateway.reference), "gateway_id": "controlled-gateway"})

    def test_unknown_billing_verifier_refuses_binding_not_only_provider_calls(self):
        self.binding()
        with override_settings(TARKADO_DELIVERY_VERIFIER=None):
            with self.assertRaisesMessage(support.ValidationError, "unconfigured"):
                self.physical()
        self.assertEqual(self.provider.calls, 0)

    def test_logical_duplicate_and_physical_duplicate_never_send_twice(self):
        self.binding()
        body = self.body()
        opened = self.hooks.pre_call(body, SimpleNamespace(user_id="employee-junior"))
        with self.assertRaisesMessage(support.ValidationError, "duplicate"):
            self.hooks.pre_call(body, SimpleNamespace(user_id="employee-junior"))
        opened["model"] = "fixture-provider-cheap"
        request = self.hooks.pre_attempt(opened)
        with self.assertRaisesMessage(support.ValidationError, "unresolved"):
            self.hooks.pre_attempt(opened)
        self.hooks.settle(request, self.provider.send(request))
        with self.assertRaises(support.ValidationError): self.hooks.pre_attempt(opened)
        self.assertEqual(self.provider.calls, 1)

    def test_wrong_models_and_unsupported_tool_billing_refused_before_provider(self):
        self.binding()
        for updates in ({"model": "wrong"}, {"tools": []}, {"n": 2}, {"service_tier": "priority"}, {"max_tokens": 1000},
                        {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": "synthetic"}]}]}):
            with self.subTest(updates=updates), self.assertRaises(support.ValidationError):
                self.hooks.pre_call(self.body(**updates), SimpleNamespace(user_id="employee-junior"))
        opened = self.hooks.pre_call(self.body(), SimpleNamespace(user_id="employee-junior"))
        opened["model"] = "wrong-provider-model"
        with self.assertRaisesMessage(support.ValidationError, "model differs"): self.hooks.pre_attempt(opened)
        self.assertEqual(self.provider.calls, 0)

    def test_title_compaction_and_generate_share_the_same_task_budget(self):
        self.binding()
        first = self.physical(kind="title")
        second = self.physical(kind="compaction")
        with self.assertRaises(support.ValidationError): self.physical(kind="generate")
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.08")
        self.hooks.settle(first, self.provider.send(first))
        third = self.physical(kind="generate")
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.08")
        self.assertEqual(len(self.state()["attempts"]), 3)

    def test_provider_timeout_does_not_become_zero_or_authorize_a_retry(self):
        self.binding()
        request = self.physical()
        with self.assertRaises(TimeoutError): self.provider.send(request, fail=True)
        self.hooks.settle(request, failed=True)
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.assertEqual(selection.status(self.request(), self.approval.reference)["selection_status"], "paused")
        with self.assertRaises(support.ValidationError): self.physical()
        delivery.close_delivery(self.gateway_token, self.bound["binding_ref"])
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")

    def test_missing_usage_stays_unknown(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, self.provider.send(request, missing_usage=True))
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertIsNone(next(iter(self.state()["attempts"].values()))["cost_usd"])

    def test_missing_cache_or_reasoning_counters_are_not_measured_zeros(self):
        self.binding()
        request = self.physical()
        complete = self.provider.send(request)
        response = copy.deepcopy(complete)
        response["usage"]["prompt_tokens_details"].pop("cached_tokens")
        self.hooks.settle(request, response)
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertIsNone(next(iter(self.state()["attempts"].values()))["cost_usd"])
        response = copy.deepcopy(complete)
        response["usage"]["completion_tokens_details"].pop("reasoning_tokens")
        self.assertIsNone(chat_usage(response))
        self.assertEqual(self.provider.calls, 1)

    def test_wrong_actual_model_preserves_unknown_cost_and_pauses(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, self.provider.send(request, model="different-provider-model"))
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(selection.status(self.request(), self.approval.reference)["selection_status"], "paused")

    def test_late_unknown_resolution_survives_revocation_and_keeps_full_negative_cost(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, failed=True)
        delivery.close_delivery(self.gateway_token, self.bound["binding_ref"])
        runtime = ScopedSelectionRuntime.objects.get()
        self.sensitive(selection.control, self.approval.reference, "rollback", selection._state(runtime)["revision"], "Stop controlled delivery")
        attempt_id = next(iter(self.state()["attempts"]))
        with override_settings(TARKADO_BILLING_VERIFIER=ControlledBillingVerifier()):
            delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], attempt_id, "1.30", None, "failed", None, "controlled-invoice")
        money = selection.accounting(ScopedSelectionRuntime.objects.get())
        self.assertEqual(money["spent_usd"], "1.30")
        self.assertEqual(money["remaining_usd"], "-0.30")
        self.assertEqual(selection.status(self.request(), self.approval.reference)["selection_status"], "rolled_back")

    def test_manual_settlement_cannot_refund_bound_provider_obligations(self):
        self.binding()
        self.physical()
        with self.assertRaisesMessage(support.ValidationError, "physical attempts"):
            selection.settle(current_member(self.junior), self.approval.reference, "synthetic-selection-1", "0", "cancelled")
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")

    def test_gateway_identity_does_not_claim_human_feedback_or_other_owner(self):
        self.binding()
        with self.assertRaises(support.PermissionDenied): delivery_views.invoke(self.gateway_token, "response", {})
        with self.assertRaises(support.PermissionDenied): self.hooks.pre_call(self.body(), SimpleNamespace(user_id="another-user"))
        response = self.api(self.gateway_token, "status", {"location_sha256": self.link.credential.scope["location_sha256"]})
        self.assertEqual(response.status_code, 403)

    def test_private_content_credentials_and_outputs_never_reach_company_records(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, self.provider.send(request))
        saved = json.dumps({"bindings": list(DeliveryBinding.objects.values("data", "journal")),
                            "security": list(SecurityEvent.objects.values("details"))})
        for secret in (self.gateway_token, self.connector_token, self.bound["task_token"], "Synthetic private prompt", "Synthetic private output", "Synthetic private provider error"):
            self.assertNotIn(secret, saved)
        self.assertNotIn("metadata", {k: v for k, v in request.items() if k != "litellm_params"})

    def test_known_settlement_exact_retry_and_changed_cost_refusal(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, self.provider.send(request))
        binding = DeliveryBinding.objects.get()
        payload = {k: v for k, v in binding.journal[-1]["payload"].items() if k != "billing_assessment"}
        result = delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], **payload)
        self.assertEqual(result["known_cost_usd"], "0.002")
        with override_settings(TARKADO_BILLING_VERIFIER=ControlledBillingVerifier()), self.assertRaisesMessage(support.ValidationError, "immutable"):
            delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], **{**payload, "cost_usd": "0"})

    def test_machine_api_rejects_raw_content_cookies_origin_and_connector_credentials(self):
        self.binding()
        client = support.LocalClient()
        path = "/api/delivery/v1/close/"
        valid = {"binding_ref": self.bound["binding_ref"]}
        def post(body, **headers): return client.post(path, json.dumps(body), content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.gateway_token, **headers)
        self.assertEqual(post({**valid, "messages": "private"}).status_code, 400)
        self.assertEqual(post(valid, HTTP_ORIGIN="https://bad.example").status_code, 403)
        self.assertEqual(support.LocalClient().post(path, json.dumps(valid), content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.connector_token).status_code, 403)
        client.force_login(self.owner)
        self.assertEqual(post(valid).status_code, 403)

    def test_changed_host_envelope_and_revoked_delegation_stop_delivery_without_switch(self):
        self.binding()
        self.link.credential.revoked_at = timezone.now()
        self.link.credential.save()
        with self.assertRaises(support.PermissionDenied): self.physical()
        self.assertEqual(self.provider.calls, 0)

    def test_known_retryable_attempt_requires_a_fresh_physical_reservation(self):
        self.binding()
        opened = self.hooks.pre_call(self.body(), SimpleNamespace(user_id="employee-junior"))
        opened["model"] = "fixture-provider-cheap"
        first = self.hooks.pre_attempt(opened)
        attempt = next(iter(self.state()["attempts"]))
        zero_usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "reasoning_tokens": 0}
        delivery.settle_attempt(self.gateway_token, self.bound["binding_ref"], attempt, "0", zero_usage, "retryable_failure", 0,
                                "controlled-provider-retry-receipt", "fixture-provider-cheap")
        second = self.hooks.pre_attempt(opened)
        self.assertNotEqual(first["litellm_params"]["metadata"], second["litellm_params"]["metadata"])
        self.assertEqual(len(self.state()["attempts"]), 2)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.assertEqual(self.provider.calls, 0)

    def test_buffered_client_stream_uses_one_bounded_nonstreaming_provider_attempt(self):
        self.binding()
        self.hooks.buffer_streams = True
        request = self.physical(stream=True, stream_options={"include_usage": True})
        self.assertFalse(request["stream"])
        self.assertNotIn("stream_options", request)
        self.assertEqual(request["max_retries"], 0)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.hooks.settle(request, self.provider.send(request))
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")

    def test_real_loopback_fake_provider_receives_only_after_adapter_reservation(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        from urllib.request import Request, urlopen
        self.binding()
        provider = self.provider
        class Handler(BaseHTTPRequestHandler):
            def do_POST(handler):
                payload = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
                result = provider.send(payload)
                body = json.dumps(result).encode()
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            physical = self.physical()
            self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
            self.assertEqual(provider.calls, 0)
            # This test fixture stands in ONLY for the existing gateway's HTTP
            # transport. Product code sends no provider request of its own.
            wire = {key: value for key, value in physical.items() if key not in ("litellm_params", "max_retries")}
            self.assertNotIn("metadata", wire)
            with urlopen(Request(f"http://127.0.0.1:{server.server_port}/v1/chat/completions", json.dumps(wire).encode(),
                                 {"Content-Type": "application/json"}), timeout=5) as response:
                received = json.loads(response.read())
            self.hooks.settle(physical, received)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(self.state()["known_cost_usd"], "0.002")
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_provider_internal_retry_client_and_wrong_endpoint_are_refused(self):
        self.binding()
        opened = self.hooks.pre_call(self.body(), SimpleNamespace(user_id="employee-junior"))
        opened["model"] = "fixture-provider-cheap"
        with self.assertRaisesMessage(support.ValidationError, "internal retries"):
            self.hooks.pre_attempt({**opened, "client": SimpleNamespace(max_retries=2)})
        with self.assertRaisesMessage(support.ValidationError, "endpoint"):
            self.hooks.pre_attempt({**opened, "api_base": "https://unapproved.example/v1"})
        self.assertEqual(self.state()["attempts"], {})


class DeliveryConcurrencyTests(TransactionTestCase):
    setUp = DeliveryTests.setUp
    enroll = DeliveryTests.enroll
    request = DeliveryTests.request
    sensitive = DeliveryTests.sensitive
    source = DeliveryTests.source
    evidence = DeliveryTests.evidence
    approve = DeliveryTests.approve
    scope = DeliveryTests.scope
    developer_request = DeliveryTests.developer_request
    task = DeliveryTests.task
    active = DeliveryTests.active
    value = DeliveryTests.value
    pair = DeliveryTests.pair
    api = DeliveryTests.api
    task_source = DeliveryTests.task_source
    binding = DeliveryTests.binding
    body = DeliveryTests.body
    physical = DeliveryTests.physical
    state = DeliveryTests.state

    def test_parallel_real_pre_attempt_hooks_share_authoritative_task_cap(self):
        self.binding(reserve="0.05")
        opened = []
        for _ in range(2):
            value = self.hooks.pre_call(self.body(), SimpleNamespace(user_id="employee-junior"))
            value["model"] = "fixture-provider-cheap"
            opened.append(value)
        def admit(value):
            try:
                try: return self.hooks.pre_attempt(value)
                except support.ValidationError: return None
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(admit, opened))
        self.assertEqual(sum(value is not None for value in result), 1)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")

    def test_stream_interruption_uses_real_wrapper_and_preserves_unknown_reservation(self):
        import asyncio
        self.binding()
        request = self.physical(stream=True, stream_options={"include_usage": True})
        async def chunks():
            yield {"model": "fixture-provider-cheap", "usage": None, "choices": ["Synthetic private output"]}
            raise TimeoutError("Synthetic private interrupted stream")
        async def run():
            with self.assertRaises(TimeoutError):
                async for chunk in self.hooks.stream(request, chunks()): pass
        asyncio.run(run())
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")

    def test_stream_cancellation_cannot_refund_a_pending_obligation(self):
        import asyncio
        self.binding()
        request = self.physical(stream=True, stream_options={"include_usage": True})
        async def chunks():
            yield {"model": "fixture-provider-cheap", "usage": None}
            raise AssertionError("Controlled cancellation must stop consumption")
        async def run():
            stream = self.hooks.stream(request, chunks())
            await anext(stream)
            await stream.aclose()
        asyncio.run(run())
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")

    def test_optional_callback_factory_with_controlled_host_preserves_unrelated_requests(self):
        import asyncio
        import sys
        from types import ModuleType
        from engine.litellm_delivery import make_callback
        self.binding()
        class Logger:
            def __init__(self, turn_off_message_logging=False): self.logging_disabled = turn_off_message_logging
            async def async_pre_call_deployment_hook(self, kwargs, call_type): pass
            async def async_post_call_success_deployment_hook(self, request_data, response, call_type): pass
            async def async_post_call_failure_deployment_hook(self, request_data, exception, call_type, fallback_depth=None): pass
        class ResponseIterator:
            def __init__(self, response): self.response = response
        class StreamWrapper:
            def __init__(self, **kwargs): self.data = kwargs
        modules = {name: ModuleType(name) for name in ("litellm", "litellm.integrations", "litellm.integrations.custom_logger",
            "litellm.litellm_core_utils", "litellm.litellm_core_utils.streaming_handler", "litellm.llms", "litellm.llms.base_llm", "litellm.llms.base_llm.base_model_iterator")}
        modules["litellm.integrations.custom_logger"].CustomLogger = Logger
        modules["litellm.litellm_core_utils.streaming_handler"].CustomStreamWrapper = StreamWrapper
        modules["litellm.llms.base_llm.base_model_iterator"].MockResponseIterator = ResponseIterator
        async def run(callback):
            unrelated = {"model": "unrelated-company-alias"}
            self.assertIs(await callback.async_pre_call_hook(None, None, unrelated, "completion"), unrelated)
            unrelated_physical = {"model_info": {"id": "unrelated-deployment"}}
            self.assertIs(await callback.async_pre_call_deployment_hook(unrelated_physical, SimpleNamespace(value="acompletion")), unrelated_physical)
            with self.assertRaises(support.ValidationError):
                await callback.async_pre_call_deployment_hook({"model_info": {"id": "controlled-deployment"}}, SimpleNamespace(value="acompletion"))
            logical = await callback.async_pre_call_hook(SimpleNamespace(user_id="employee-junior"), None,
                self.body(stream=True, stream_options={"include_usage": True}), "completion")
            logical["model"] = "fixture-provider-cheap"
            logical["litellm_logging_obj"] = SimpleNamespace(stream=False)
            physical = await callback.async_pre_call_deployment_hook(logical, SimpleNamespace(value="acompletion"))
            self.assertFalse(physical["stream"])
            self.assertEqual(physical["max_retries"], 0)
            response = SimpleNamespace(**self.provider.send(physical))
            returned = await callback.async_post_call_success_deployment_hook(physical, response, SimpleNamespace(value="acompletion"))
            self.assertIsInstance(returned, StreamWrapper)
            self.assertIs(returned.data["completion_stream"].response, response)
        # Stub only the optional HOST classes, never the product policy/accounting
        # implementation. This is not installed-LiteLLM compatibility verification.
        with patch.dict(sys.modules, modules), patch("engine.litellm_delivery.version", return_value="1.104.0"):
            callback = make_callback(LocalBackend(self.gateway_token), managed_aliases=["company-cheap"], managed_deployment_ids=["controlled-deployment"])
            self.assertTrue(callback.logging_disabled)
            asyncio.run(run(callback))
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.state()["known_cost_usd"], "0.002")
