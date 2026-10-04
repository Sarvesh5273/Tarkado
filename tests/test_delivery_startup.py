"""Inactive terminal/API/startup wiring on synthetic stores; no installed host or provider."""

import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import test_company as support
import test_delivery_review as review_support
from django.conf import settings
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings

from engine.company import delivery
from engine.company.integration import CompanyIntegration, install, load_reviewed
from engine.company.models import Company, ScopedSelectionRuntime
from engine.company.selection import accounting
from engine.gateway_startup import callback_from_config, callback_from_environment
from engine.startup_config import private_json
from engine.schemas import ValidationError


def setUpModule():
    support.setUpModule()


def tearDownModule():
    connections.close_all()


class DeliveryWiringTests(review_support.DeliveryFixture, TestCase):
    def test_guided_scope_choices_are_current_owned_metadata_not_spend_permission(self):
        self.binding()
        before = accounting(ScopedSelectionRuntime.objects.get())
        response = self.api(self.connector_token, "delivery-options", {"location_sha256": self.link.credential.scope["location_sha256"]})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data["collection_supported"])
        self.assertEqual(data["scopes"][0]["scope_ref"], str(self.approval.reference))
        self.assertEqual(data["scopes"][0]["routes"][0]["model"], "fixture/cheap")
        self.assertEqual(data["gateways"][0]["gateway_ref"], str(self.gateway.reference))
        self.assertFalse(data["new_reservation"])
        self.assertFalse(data["execution_sent"])
        self.assertEqual(accounting(ScopedSelectionRuntime.objects.get()), before)
        self.assertNotIn(self.bound["task_token"], response.content.decode())
        self.assertNotIn(self.gateway_token, response.content.decode())

    def test_delivery_task_state_projects_usage_without_task_or_gateway_tokens(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, self.provider.send(request))
        response = self.api(self.connector_token, "delivery-task", {"connector_task_ref": str(self.link.reference),
            "location_sha256": self.link.credential.scope["location_sha256"]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["delivery"]["known_cost_usd"], "0.002")
        self.assertFalse(response.json()["outcome_verified"])
        self.assertNotIn(self.bound["task_token"], response.content.decode())
        self.assertNotIn(self.gateway_token, response.content.decode())

    def test_paused_scope_and_wrong_directory_cannot_be_presented_as_available(self):
        self.binding()
        request = self.physical()
        self.hooks.settle(request, failed=True)
        value = {"location_sha256": self.link.credential.scope["location_sha256"]}
        data = self.api(self.connector_token, "delivery-options", value).json()
        self.assertEqual(data["scopes"][0]["status"], "paused")
        self.assertFalse(data["scopes"][0]["authority_current"])
        self.assertEqual(self.api(self.connector_token, "delivery-options", {"location_sha256": "a" * 64}).status_code, 403)


class PrivateStartupTests(TestCase):
    def private(self, path, value):
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def test_private_startup_json_refuses_symlinks_loose_modes_and_raw_extra_settings(self):
        with tempfile.TemporaryDirectory(dir=support.TEMPORARY.name) as directory:
            path = Path(directory) / "config.json"
            self.private(path, {"synthetic": True})
            self.assertEqual(private_json(path), {"synthetic": True})
            path.chmod(0o644)
            with self.assertRaises(ValidationError): private_json(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            link = Path(directory) / "link.json"; link.symlink_to(path)
            with self.assertRaises(ValidationError): private_json(link)
            self.assertTrue(path.exists())

    def test_gateway_instance_config_loads_only_explicit_machine_credential_and_no_network(self):
        with tempfile.TemporaryDirectory(dir=support.TEMPORARY.name) as directory:
            directory = Path(directory)
            token = "s" * 43
            self.private(directory / "machine.json", {"origin": "https://policy.company.example", "credential": token})
            config = {"schema_version": 1, "company_origin": "https://policy.company.example", "credential_file": str(directory / "machine.json"),
                      "managed_aliases": ["company-cheap"], "managed_deployment_ids": ["deployment-cheap"], "timeout_seconds": 10}
            self.private(directory / "startup.json", config)
            with patch("engine.gateway_startup.make_callback", return_value="controlled-host-instance") as factory, patch("socket.socket", side_effect=AssertionError("No network during startup")):
                self.assertEqual(callback_from_config(directory / "startup.json"), "controlled-host-instance")
            self.assertEqual(factory.call_args.kwargs["managed_aliases"], ("company-cheap",))
            self.assertEqual(factory.call_args.args[0].token, token)
            changed = {**config, "provider_api_key": "unsupported"}
            self.private(directory / "startup.json", changed)
            with self.assertRaises(ValidationError): callback_from_config(directory / "startup.json")

    def test_gateway_origin_mismatch_and_missing_environment_never_guess_credentials(self):
        with tempfile.TemporaryDirectory(dir=support.TEMPORARY.name) as directory:
            directory = Path(directory)
            self.private(directory / "machine.json", {"origin": "https://other.company.example", "credential": "s" * 43})
            self.private(directory / "startup.json", {"schema_version": 1, "company_origin": "https://policy.company.example",
                "credential_file": str(directory / "machine.json"), "managed_aliases": ["alias"], "managed_deployment_ids": ["deploy"], "timeout_seconds": 10})
            with self.assertRaisesMessage(ValidationError, "origin differs"):
                callback_from_config(directory / "startup.json")
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesMessage(ValidationError, "TARKADO_GATEWAY_CONFIG"):
            callback_from_environment()


class CompanyStartupTests(TestCase):
    setUp = support.CompanyControlTests.setUp
    enroll = support.CompanyControlTests.enroll

    def test_operator_code_loading_requires_explicit_approval_before_any_file_access(self):
        with patch("engine.company.integration.private_json", side_effect=AssertionError("No implicit private file read")):
            with self.assertRaisesMessage(ValidationError, "operator approval"):
                load_reviewed("not-read.json", Company.objects.get())

    def test_ready_booleans_and_cross_company_bundle_cannot_replace_refusing_verifiers(self):
        from engine.company.readiness_gate import ReadinessVerifier
        from engine.company.delivery import DeliveryVerifier
        class Readiness(ReadinessVerifier):
            def verify(self, request): raise ValidationError("No controlled evidence")
        class Delivery(DeliveryVerifier):
            def envelope(self, company_id, deployment_id, model_id): raise ValidationError("No controlled billing")
        with override_settings(TARKADO_READINESS_VERIFIER=None, TARKADO_ADMISSION_VERIFIER=None, TARKADO_DELIVERY_VERIFIER=None, TARKADO_BILLING_VERIFIER=None):
            with self.assertRaises(ValidationError): install(Company.objects.get(), {"verified": True})
            different = CompanyIntegration(str(uuid.uuid4()), str(Company.objects.get().deployment_id), "controlled-other-company", Readiness(), Delivery())
            with self.assertRaisesMessage(ValidationError, "different company"):
                install(Company.objects.get(), different)
            self.assertIsNone(settings.TARKADO_READINESS_VERIFIER)
            self.assertIsNone(settings.TARKADO_ADMISSION_VERIFIER)

    def source(self, company, module):
        return f'''from engine.company.integration import CompanyIntegration
from engine.company.readiness_gate import ReadinessVerifier
from engine.company.delivery import DeliveryVerifier
from engine.schemas import ValidationError
class Readiness(ReadinessVerifier):
    def verify(self, request):
        raise ValidationError("Controlled startup has no real evidence")
class Delivery(DeliveryVerifier):
    def envelope(self, company_id, deployment_id, model_id):
        raise ValidationError("Controlled startup has no real billing validation")
def create():
    return CompanyIntegration("{company.company_id}", "{company.deployment_id}", "{module}", Readiness(), Delivery())
'''

    def test_reviewed_startup_executes_exact_source_bytes_but_does_not_approve_or_activate(self):
        company = Company.objects.get()
        module = "synthetic_startup_" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(dir=support.TEMPORARY.name) as directory:
            directory = Path(directory)
            source = self.source(company, module)
            path = directory / (module + ".py"); path.write_text(source); path.chmod(0o600)
            manifest = {"schema_version": 1, "company_id": str(company.company_id), "deployment_id": str(company.deployment_id),
                        "module": module, "factory": "create", "source_sha256": hashlib.sha256(source.encode()).hexdigest()}
            config = directory / "manifest.json"; config.write_text(json.dumps(manifest)); config.chmod(0o600)
            with patch.object(sys, "path", [str(directory), *sys.path]), override_settings(TARKADO_READINESS_VERIFIER=None,
                TARKADO_ADMISSION_VERIFIER=None, TARKADO_DELIVERY_VERIFIER=None, TARKADO_BILLING_VERIFIER=None), patch("socket.socket", side_effect=AssertionError("No network at startup")):
                try:
                    result = load_reviewed(config, company, operator_approved=True)
                    self.assertTrue(result["configured"])
                    self.assertFalse(result["routing_enabled"])
                    self.assertFalse(result["execution_sent"])
                    with self.assertRaisesMessage(ValidationError, "no real evidence"):
                        settings.TARKADO_READINESS_VERIFIER.verify(None)
                    with self.assertRaises(ValidationError): load_reviewed(config, company, operator_approved=True)
                finally:
                    sys.modules.pop(module, None)
            self.assertEqual(support.PilotAuthorization.objects.count(), 0)
            self.assertEqual(ScopedSelectionRuntime.objects.count(), 0)

    def test_changed_reviewed_source_and_wrong_company_refuse_before_execution(self):
        company = Company.objects.get()
        module = "synthetic_unloaded_" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(dir=support.TEMPORARY.name) as directory:
            directory = Path(directory)
            source = self.source(company, module)
            path = directory / (module + ".py"); path.write_text(source + "\nraise AssertionError('Changed bytes must never execute')\n"); path.chmod(0o600)
            manifest = {"schema_version": 1, "company_id": str(company.company_id), "deployment_id": str(company.deployment_id),
                        "module": module, "factory": "create", "source_sha256": hashlib.sha256(source.encode()).hexdigest()}
            config = directory / "manifest.json"; config.write_text(json.dumps(manifest)); config.chmod(0o600)
            with patch.object(sys, "path", [str(directory), *sys.path]):
                with self.assertRaisesMessage(ValidationError, "source changed"):
                    load_reviewed(config, company, operator_approved=True)
                self.assertNotIn(module, sys.modules)
                manifest["company_id"] = str(uuid.uuid4()); config.write_text(json.dumps(manifest))
                with self.assertRaisesMessage(ValidationError, "another company"):
                    load_reviewed(config, company, operator_approved=True)


class JoinedDeliveryHTTPTests(review_support.DeliveryFixture, TransactionTestCase):
    def test_real_node_coordinator_joins_actual_company_http_without_installing_opencode(self):
        import subprocess
        import threading
        from socketserver import ThreadingMixIn
        from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
        from django.core.wsgi import get_wsgi_application
        import test_delivery as delivery_support
        approval = self.active()
        _, token, _ = self.pair(source_kind="team")
        gateway, gateway_token = self.sensitive(delivery.issue_gateway, "controlled-http-gateway", "synthetic-repository",
            {"junior": "employee-junior"}, support.timezone.now() + support.timedelta(hours=1), Company.objects.get().revision)
        class Server(ThreadingMixIn, WSGIServer):
            daemon_threads = True
        class Handler(WSGIRequestHandler):
            def log_message(self, *args): pass
            def finish(self):
                try: super().finish()
                finally: connections.close_all()
        server = make_server("127.0.0.1", 0, get_wsgi_application(), server_class=Server, handler_class=Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        code = '''import { CompanyClient } from "./integrations/opencode/src/client.mjs";
import { DeliveryCoordinator } from "./integrations/opencode/src/delivery-coordinator.mjs";
let text = ""; for await (const part of process.stdin) text += part;
const input = JSON.parse(text);
const coordinator = new DeliveryCoordinator({ company: new CompanyClient({ origin: input.origin, credential: input.token }),
  directory: "/synthetic/work", gatewayRef: input.gatewayRef, providerID: "company", gatewayOrigin: "https://gateway.company.example",
  session: { async create(value) { return value } } });
const config = await coordinator.connect();
if (!config.scopes.some(row => row.scope_ref === input.scopeRef && row.authority_current)) throw new Error("Controlled scope unavailable");
const created = await coordinator.newTask({ scopeRef: input.scopeRef, repositoryRef: "synthetic-repository", taskLabel: "Joined controlled HTTP task",
  taskType: "documentation", riskTags: ["low"], selectedModel: "fixture/premium", overrideModel: null,
  contextTokens: 2000, outputLimit: 1000, taskCapUSD: "0.10" });
const state = await coordinator.state(created.sessionID);
console.log(JSON.stringify({ sessionCreated: created.sessionCreated, executionSent: created.executionSent,
  model: created.model, taskRef: state.task.task_ref, knownCost: state.delivery.known_cost_usd }));'''
        try:
            with override_settings(TARKADO_ADMISSION_VERIFIER=delivery.NarrowDeliveryAdmissionVerifier(), TARKADO_DELIVERY_VERIFIER=delivery_support.ControlledDeliveryVerifier()):
                thread.start()
                result = subprocess.run(["node", "--input-type=module", "-e", code], cwd=support.ROOT,
                    input=json.dumps({"origin": f"http://127.0.0.1:{server.server_port}", "token": token,
                                      "gatewayRef": str(gateway.reference), "scopeRef": str(approval.reference)}),
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                value = json.loads(result.stdout)
                self.assertTrue(value["sessionCreated"])
                self.assertFalse(value["executionSent"])
                self.assertEqual(value["model"], "fixture/cheap")
                self.assertEqual(value["knownCost"], "0")
                self.assertNotIn(token, result.stdout + result.stderr)
                self.assertNotIn(gateway_token, result.stdout + result.stderr)
                self.assertEqual(accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.10")
                self.assertEqual(accounting(ScopedSelectionRuntime.objects.get())["claimed_tasks"], 1)
        finally:
            if thread.is_alive(): server.shutdown()
            server.server_close()
            if thread.ident is not None: thread.join(timeout=5)

    def test_company_help_exposes_explicit_reviewed_loader_without_loading_code(self):
        import subprocess
        result = subprocess.run([sys.executable, "-m", "engine", "company", "service", "--help"], cwd=support.ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--integration-manifest", result.stdout)
        self.assertIn("--load-reviewed-integration", result.stdout)
