"""Metadata-only local-tool status linkage and constrained bound-task repair."""

import copy
import json
import uuid
from dataclasses import replace
from datetime import timedelta

import test_company as support
import test_function_coding as coding
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from engine.company import authorization, company_learning, delivery, selection, tool_observations
from engine.company.models import Company, ToolObservation, ScopedSelectionRuntime
from engine.company.operations import monitor
from engine.company.services import SUPPORTED_COLLECTION_FIELDS, TOOL_CAPTURE_FIELDS, current_member, update_company
from engine.company.tasks import task_ledger
from engine.delivery_contract import delivery_envelope
from engine.feedback import _fingerprint
from engine.schemas import ValidationError


def setUpModule(): support.setUpModule()
def tearDownModule(): connections.close_all()


class ToolObservationTests(TestCase):
    setUp = coding.FunctionCodingTests.setUp
    enroll = coding.FunctionCodingTests.enroll
    request = coding.FunctionCodingTests.request
    sensitive = coding.FunctionCodingTests.sensitive
    source = coding.FunctionCodingTests.source
    evidence = coding.FunctionCodingTests.evidence
    approve = coding.FunctionCodingTests.approve
    scope = coding.FunctionCodingTests.scope
    developer_request = coding.FunctionCodingTests.developer_request
    task = coding.FunctionCodingTests.task
    active = coding.FunctionCodingTests.active
    value = coding.FunctionCodingTests.value
    api = coding.FunctionCodingTests.api
    task_source = coding.FunctionCodingTests.task_source
    body = coding.FunctionCodingTests.body
    physical = coding.FunctionCodingTests.physical
    accept = coding.FunctionCodingTests.accept
    state = coding.FunctionCodingTests.state

    def pair(self, **kwargs):
        if getattr(self, "capture_approved", True):
            company = Company.objects.get()
            # Actual approved change, before the review/pairing; not a migration
            # default or a caller-supplied boolean with collection authority.
            if not set(TOOL_CAPTURE_FIELDS).issubset(company.collection_fields):
                update_company(self.owner, support.PASSWORD, company.name, company.policy, company.repository_refs,
                    list(SUPPORTED_COLLECTION_FIELDS), True, company.revision, reason="Explicit synthetic tool-status collection approval")
        return coding.FunctionCodingTests.pair(self, **kwargs)

    def binding(self, approved=True, accept=True):
        self.capture_approved = approved
        if approved:
            company = Company.objects.get()
            update_company(self.owner, support.PASSWORD, company.name, company.policy, company.repository_refs,
                list(SUPPORTED_COLLECTION_FIELDS), True, company.revision, reason="Approve synthetic metadata-only tool fields")
        verifier = coding.ControlledFunctionVerifier()
        verifier.value = replace(verifier.value, local_tools=tuple(replace(tool, status_metadata_key="tarkado_status_v1") for tool in verifier.value.local_tools))
        result = coding.FunctionCodingTests.binding(self, verifier=verifier)
        if accept: self.accept()
        self.bound_tool = next(tool for tool in delivery_envelope(self.link.delivery.data["envelope"]).local_tools if tool.capability == "test")
        return result

    def event(self, phase="start", status="started", seq=1, invocation=None, source="opencode_v2_hook", **changes):
        self.invocation = invocation or getattr(self, "invocation", _fingerprint({"synthetic_call": str(uuid.uuid4())}))
        value = {"connector_task_ref": str(self.link.reference), "location_sha256": self.link.credential.scope["location_sha256"],
                 "session_ref": self.link.session_ref, "event_id": str(uuid.uuid4()), "sequence": seq,
                 "payload": {"tool_invocation_ref": self.invocation, "tool_contract_ref": _fingerprint(self.bound_tool.to_dict()),
                             "tool_phase": phase, "tool_status": status, "tool_observed_at": (timezone.now() - timedelta(milliseconds=10)).isoformat(),
                             "tool_attempt_ref": None, "tool_status_source": source}}
        value.update(changes)
        return value

    def send(self, value):
        return self.api(self.connector_token, "tool-status", value)

    def started(self):
        result = self.send(self.event())
        self.assertEqual(result.status_code, 200, result.content)

    def status_case(self, status, source="opencode_v2_hook", blocked=True):
        self.binding(); self.started()
        response = self.send(self.event("result", status, 2, source=source))
        self.assertEqual(response.status_code, 200, response.content)
        observed = response.json()
        self.assertEqual(observed["invocations"][self.invocation]["status"], status)
        self.assertEqual(observed["continuation_blocked"], blocked)
        self.assertIsNone(observed["final_task_outcome"])
        self.assertEqual(task_ledger(self.link.task).results, ())
        if blocked:
            with self.assertRaises(ValidationError): self.physical()
        return observed

    def test_execution_error_allows_only_exact_bound_repair_and_not_new_category_selection(self):
        observed = self.status_case("execution_error", blocked=False)
        original = copy.deepcopy(self.approval.data)
        reviewed = copy.deepcopy(self.approval.review.data)
        request = self.physical()
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.hooks.settle(request, self.provider.send(request))
        future = selection.select(current_member(self.junior), self.approval.reference, self.value(2))
        self.assertFalse(future["new_reservation"])
        self.assertEqual(company_learning.guard(self.publication, Company.objects.get())["status"], "blocked")
        self.assertTrue(any(row["signal"] == "tool_execution_error" for row in monitor(self.request())["alerts"]))
        self.approval.refresh_from_db(); self.assertEqual(self.approval.data, original)
        self.approval.review.refresh_from_db(); self.assertEqual(self.approval.review.data, reviewed)
        self.assertEqual(observed["physical_attempt_linkage"], "unavailable")

    def test_intermediate_failure_checks_target_only_the_relevant_category(self):
        self.status_case("test_failed", "reviewed_tool_metadata", blocked=False)
        captured = tool_observations.observations(Company.objects.get(), "team")
        with self.assertRaisesMessage(ValidationError, "new automatic tasks"):
            tool_observations.verify_execution([], captured, task_types=("documentation",))
        # This does not grant another category scope or disable other guards;
        # it establishes that THIS diagnostic is category-specific only.
        tool_observations.verify_execution([], captured, task_types=("test_generation",))
        tool_observations.verify_execution([], captured, binding_ref=str(self.link.delivery.reference), task_types=("documentation",))

    def test_explicit_intermediate_test_failure_is_not_final_failed_task_and_can_repair(self):
        self.status_case("test_failed", "reviewed_tool_metadata", blocked=False)
        request = self.physical(); self.hooks.settle(request, self.provider.send(request))
        self.assertEqual(selection._state(ScopedSelectionRuntime.objects.get())["status"], "active")
        self.assertEqual(task_ledger(self.link.task).results, ())
        plan = dict(self.approval.review.data["learner"]["plan"], learner_version="tool-failure-next-review", cutoff=timezone.now().isoformat())
        review = authorization.prepare_review(self.request(), plan)
        self.assertEqual(review.data["report"]["categories"][0]["status"], "blocked")
        self.assertIn("test_failed", review.data["tool_observations"][0]["state"]["negative_signals"])
        self.assertEqual(review.data["learner"]["training_counts"], self.approval.review.data["learner"]["training_counts"])

    def test_explicit_permission_refusal_blocks_continuation_without_paid_refund(self):
        self.status_case("permission_refused", "reviewed_tool_metadata")
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.20")

    def test_explicit_interruption_blocks_continuation_and_is_not_zero_cost(self):
        self.status_case("interrupted", "reviewed_tool_metadata")
        self.assertEqual(self.state()["attempts"], {})
        self.assertEqual(selection.accounting(ScopedSelectionRuntime.objects.get())["reserved_usd"], "0.20")

    def test_missing_result_is_unknown_not_inferred_permission_or_cancellation(self):
        observed = self.status_case("unknown", "missing_after_hook")
        self.assertEqual(observed["negative_signals"], ["unknown"])
        self.assertFalse(observed["test_outcome_verified"])

    def test_native_completed_status_cannot_be_promoted_to_passing_test(self):
        self.binding(); self.started()
        result = self.send(self.event("result", "completed", 2))
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["negative_signals"], [])
        self.assertFalse(result.json()["test_outcome_verified"])
        self.assertIsNone(result.json()["final_task_outcome"])
        self.assertEqual(task_ledger(self.link.task).results, ())

    def test_missing_before_event_sequence_holes_are_retained_never_false_complete(self):
        self.binding()
        result = self.send(self.event("result", "completed", 3))
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["gap_count"], 2)
        self.assertTrue(result.json()["continuation_blocked"])
        with self.assertRaises(ValidationError): self.physical()

    def test_orphan_result_without_gap_is_refused_instead_of_guessed_linkage(self):
        self.binding()
        result = self.send(self.event("result", "completed"))
        self.assertEqual(result.status_code, 400)
        self.assertEqual(ToolObservation.objects.count(), 0)

    def test_duplicate_retries_are_exact_and_changed_stale_events_refused(self):
        self.binding()
        first = self.event(); self.assertEqual(self.send(first).status_code, 200)
        self.assertEqual(self.send(first).status_code, 200)
        changed = copy.deepcopy(first); changed["payload"]["tool_status"] = "completed"
        self.assertEqual(self.send(changed).status_code, 400)
        self.assertEqual(self.send(self.event()).status_code, 400)
        result = self.event("result", "completed", 2); self.assertEqual(self.send(result).status_code, 200)
        self.assertEqual(self.send(result).status_code, 200)
        self.assertEqual(ToolObservation.objects.count(), 2)

    def test_late_result_after_close_keeps_original_start_role_and_ingestion_order(self):
        self.binding(); self.started()
        original = ToolObservation.objects.get().actor_snapshot
        delivery.close_delivery(self.gateway_token, self.bound["binding_ref"])
        # Explicit company task close (separate from accounting close).
        import test_connectors as connector_support
        close = connector_support.ConnectorTests.event(self, {"connector_task_ref": str(self.link.reference)}, kind="close")
        result = self.api(self.connector_token, "observation", close)
        self.assertEqual(result.status_code, 200, result.content)
        result = self.send(self.event("result", "execution_error", 2))
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(list(ToolObservation.objects.values_list("sequence", flat=True)), [1, 2])
        self.assertEqual(ToolObservation.objects.first().actor_snapshot, original)
        self.assertEqual(original["role"], "junior")
        self.assertEqual(self.send(self.event(seq=3, invocation="a" * 64)).status_code, 400)

    def test_changed_contract_wrong_session_task_owner_and_attempt_guess_are_refused(self):
        self.binding()
        for changes in ({"session_ref": "a" * 64}, {"connector_task_ref": str(uuid.uuid4())}):
            self.assertEqual(self.send(self.event(**changes)).status_code, 403)
        changed = self.event(); changed["payload"]["tool_contract_ref"] = "b" * 64
        self.assertEqual(self.send(changed).status_code, 400)
        changed = self.event(); changed["payload"]["tool_attempt_ref"] = str(uuid.uuid4())
        self.assertEqual(self.send(changed).status_code, 400)
        _, other_token, _ = self.pair(user=self.senior, source_kind="team")
        self.assertEqual(self.api(other_token, "tool-status", self.event()).status_code, 403)
        self.assertEqual(ToolObservation.objects.count(), 0)

    def test_new_fields_require_explicit_approval_no_bootstrap_or_pairing_expansion(self):
        self.assertFalse(set(TOOL_CAPTURE_FIELDS).issubset(Company.objects.get().collection_fields))
        self.binding(approved=False)
        self.assertEqual(self.send(self.event()).status_code, 403)
        self.assertEqual(ToolObservation.objects.count(), 0)
        self.assertFalse(set(TOOL_CAPTURE_FIELDS).issubset(self.link.credential.scope["collection_fields"]))

    def test_browser_offers_new_supported_fields_without_selecting_them_by_default(self):
        from engine.company.configuration_forms import BrowserConfigurationForm
        from engine.company.services import COLLECTION_FIELDS
        company = Company.objects.get()
        form = BrowserConfigurationForm(company=company)
        offered = {value for value, _ in form.fields["collection_fields"].choices}
        self.assertTrue(set(TOOL_CAPTURE_FIELDS).issubset(offered))
        self.assertEqual(form.initial["collection_fields"], list(COLLECTION_FIELDS))
        self.assertFalse(set(TOOL_CAPTURE_FIELDS).intersection(form.initial["collection_fields"]))

    def test_structured_status_without_contract_cannot_be_submitted_as_native_outcome(self):
        self.binding(); self.started()
        self.assertEqual(self.send(self.event("result", "permission_refused", 2)).status_code, 400)
        read = next(tool for tool in delivery_envelope(self.link.delivery.data["envelope"]).local_tools if tool.capability == "read")
        self.bound_tool = read
        result = self.send(self.event("result", "test_failed", 2, source="reviewed_tool_metadata"))
        self.assertEqual(result.status_code, 400)

    def test_raw_arguments_outputs_error_text_and_credentials_are_never_accepted(self):
        self.binding(); self.started()
        for field in ("input", "arguments", "output", "error", "message", "credential"):
            changed = self.event("result", "completed", 2)
            changed["payload"][field] = "Synthetic private data"
            response = self.send(changed)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn("Synthetic private data", response.content.decode())
        result = self.send(self.event("result", "execution_error", 2)); self.assertEqual(result.status_code, 200)
        saved = json.dumps(list(ToolObservation.objects.values("payload", "actor_snapshot")))
        for value in (self.gateway_token, self.connector_token, self.bound["task_token"], "Synthetic private data"):
            self.assertNotIn(value, saved)

    def test_api_success_does_not_hide_tool_failure_and_provider_failure_still_vetoes_repair(self):
        self.binding(); self.started()
        result = self.send(self.event("result", "test_failed", 2, source="reviewed_tool_metadata")); self.assertEqual(result.status_code, 200)
        request = self.physical()
        self.hooks.settle(request, failed=True)
        with self.assertRaises(ValidationError): self.physical()
        self.assertEqual(self.state()["unknown_attempts"], 1)
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.assertIsNone(result.json()["final_task_outcome"])

    def test_unknown_then_late_completed_result_does_not_erase_retained_missing_evidence(self):
        self.binding(); self.started()
        self.assertEqual(self.send(self.event("result", "unknown", 2, source="missing_after_hook")).status_code, 200)
        result = self.send(self.event("result", "completed", 3))
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["invocations"][self.invocation]["status"], "completed")
        self.assertIn("unknown", result.json()["negative_signals"])
        with self.assertRaises(ValidationError): self.physical()

    def test_capture_initialization_is_not_tool_activity_and_does_not_block_acceptance(self):
        self.binding(accept=False)
        value = self.event("open", "capture_open", source="adapter_lifecycle")
        value["payload"]["tool_invocation_ref"] = value["payload"]["tool_contract_ref"] = None
        self.assertEqual(self.send(value).status_code, 200)
        self.accept()
        request = self.physical()
        self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
        self.assertEqual(self.provider.calls, 0)

    def test_revoked_pairing_or_reduced_collection_scope_cannot_upload_tool_events(self):
        self.binding(); self.started()
        company = Company.objects.get()
        company.collection_fields = [field for field in company.collection_fields if field != "tool_status"]
        company.save(update_fields=("collection_fields",))
        self.assertEqual(self.send(self.event("result", "execution_error", 2)).status_code, 403)
        self.assertEqual(ToolObservation.objects.count(), 1)
        self.link.credential.revoked_at = timezone.now(); self.link.credential.save()
        self.assertEqual(self.send(self.event("result", "completed", 2)).status_code, 403)

    def test_clock_and_invocation_order_are_checked_without_reordering_delayed_events(self):
        self.binding(); self.started()
        result = self.event("result", "completed", 2)
        result["payload"]["tool_observed_at"] = (timezone.now() + timedelta(hours=1)).isoformat()
        self.assertEqual(self.send(result).status_code, 400)
        result["payload"]["tool_observed_at"] = (timezone.now() - timedelta(hours=1)).isoformat()
        self.assertEqual(self.send(result).status_code, 400)
        self.assertEqual(ToolObservation.objects.count(), 1)

    def close_task(self):
        import test_connectors as connector_support
        close = connector_support.ConnectorTests.event(self, {"connector_task_ref": str(self.link.reference)}, kind="close")
        response = self.api(self.connector_token, "observation", close)
        self.assertEqual(response.status_code, 200, response.content)

    def test_intermediate_test_failure_does_not_override_later_separate_human_success(self):
        from engine.company.tasks import record_execution, record_result
        self.binding(); self.started()
        response = self.send(self.event("result", "test_failed", 2, source="reviewed_tool_metadata"))
        self.assertEqual(response.status_code, 200, response.content)
        attempt = self.physical(); self.hooks.settle(attempt, self.provider.send(attempt))
        self.close_task()
        self.link.task.refresh_from_db()
        task = record_execution(self.junior, self.link.task.reference, "fixture/cheap", self.link.task.revision)
        self.assertEqual(task_ledger(task).results, ())
        task = record_result(self.junior, task.reference, {"desired_result": True, "tests_passed": None, "score": None,
            "cost_usd": None, "latency_ms": None, "evidence_ref": "separate-controlled-human-review-after-repair", "supersedes": None}, task.revision)
        self.assertTrue(task_ledger(task).results[-1].desired_result)
        self.assertIn("test_failed", tool_observations.state(self.link.delivery)["negative_signals"])
        self.assertEqual(self.state()["known_cost_usd"], "0.002")

    def test_missing_tool_coverage_cannot_be_relabelled_as_adopted_success(self):
        from engine.company.tasks import record_execution, record_result
        self.binding()
        attempt = self.physical(); self.hooks.settle(attempt, self.provider.send(attempt))
        self.started()
        response = self.send(self.event("result", "unknown", 2, source="missing_after_hook"))
        self.assertEqual(response.status_code, 200, response.content)
        self.close_task()
        self.link.task.refresh_from_db()
        task = record_execution(self.junior, self.link.task.reference, "fixture/cheap", self.link.task.revision)
        with self.assertRaisesMessage(ValidationError, "coverage cannot establish"):
            record_result(self.junior, task.reference, {"desired_result": True, "tests_passed": None, "score": None,
                "cost_usd": None, "latency_ms": None, "evidence_ref": "cannot-certify-missing-tool-events", "supersedes": None}, task.revision)
        task = record_result(self.junior, task.reference, {"desired_result": None, "tests_passed": None, "score": None,
            "cost_usd": None, "latency_ms": None, "evidence_ref": None, "supersedes": None}, task.revision)
        self.assertIsNone(task_ledger(task).results[-1].desired_result)


class AutomaticToolHTTPTests(TransactionTestCase):
    setUp = ToolObservationTests.setUp
    enroll = ToolObservationTests.enroll
    request = ToolObservationTests.request
    sensitive = ToolObservationTests.sensitive
    source = ToolObservationTests.source
    evidence = ToolObservationTests.evidence
    approve = ToolObservationTests.approve
    scope = ToolObservationTests.scope
    developer_request = ToolObservationTests.developer_request
    task = ToolObservationTests.task
    active = ToolObservationTests.active
    value = ToolObservationTests.value
    api = ToolObservationTests.api
    task_source = ToolObservationTests.task_source
    body = ToolObservationTests.body
    physical = ToolObservationTests.physical
    accept = ToolObservationTests.accept
    state = ToolObservationTests.state
    pair = ToolObservationTests.pair
    binding = ToolObservationTests.binding

    def test_actual_node_hook_projector_uploads_metadata_then_exact_task_can_repair(self):
        import subprocess
        import threading
        from socketserver import ThreadingMixIn
        from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
        from django.core.wsgi import get_wsgi_application
        self.binding()
        class Server(ThreadingMixIn, WSGIServer): daemon_threads = True
        class Handler(WSGIRequestHandler):
            def log_message(self, *args): pass
            def finish(self):
                try: super().finish()
                finally: connections.close_all()
        server = make_server("127.0.0.1", 0, get_wsgi_application(), server_class=Server, handler_class=Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        code = '''import { CompanyClient } from "./integrations/opencode/src/client.mjs";
import { ToolCapture } from "./integrations/opencode/src/tool-capture.mjs";
let text = ""; for await (const chunk of process.stdin) text += chunk;
const input = JSON.parse(text);
const adapter = { sessionID: "ses_synthetic", sessionHash: input.sessionRef, descriptor: { connectorTaskRef: input.taskRef }, binding: input.binding };
const capture = new ToolCapture({ company: new CompanyClient({ origin: input.origin, credential: input.token }), adapter, location: input.location });
await capture.open();
const event = { sessionID: "ses_synthetic", messageID: "msg_synthetic_exact", id: "call_synthetic_exact", tool: "run_tests" };
Object.defineProperty(event, "input", { get() { throw new Error("No private arguments may be read") } });
capture.before(event);
capture.after({ ...event, status: "completed", result: { content: "Synthetic private test output", metadata: { tarkado_status_v1: { schema_version: 1, status: "test_failed" } } } });
await capture.barrier(); console.log(JSON.stringify({ pendingUploads: capture.queue.length }));'''
        try:
            thread.start()
            result = subprocess.run(["node", "--input-type=module", "-e", code], cwd=support.ROOT, text=True, capture_output=True, timeout=20,
                input=json.dumps({"origin": f"http://127.0.0.1:{server.server_port}", "token": self.connector_token, "sessionRef": self.link.session_ref,
                    "taskRef": str(self.link.reference), "binding": self.bound, "location": self.link.credential.scope["location_sha256"]}))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["pendingUploads"], 0)
            captured = tool_observations.state(self.link.delivery)
            self.assertEqual(captured["negative_signals"], ["test_failed"])
            self.assertEqual(ToolObservation.objects.count(), 3)
            request = self.physical()
            self.assertEqual(self.state()["attempt_reserved_usd"], "0.04")
            self.hooks.settle(request, self.provider.send(request))
            self.assertEqual(self.provider.calls, 1)
            saved = json.dumps(list(ToolObservation.objects.values("payload")))
            self.assertNotIn("Synthetic private test output", saved)
            for secret in (self.connector_token, self.bound["task_token"], "msg_synthetic_exact", "call_synthetic_exact"):
                self.assertNotIn(secret, result.stdout + result.stderr + saved)
        finally:
            if thread.is_alive(): server.shutdown()
            server.server_close()
            if thread.ident is not None: thread.join(timeout=5)
