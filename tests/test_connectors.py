"""B-04 delegated browser/API records tested with isolated synthetic accounts, no private clients."""

import json
import re
import uuid
import subprocess
import sys
from pathlib import Path
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_company as support
from django.core.management import call_command
from django.db import connections
from django.test import TestCase
from django.utils import timezone

from engine.company import connectors
from engine.company.models import Company, ConnectorCredential, ConnectorTask, ConnectorObservation, CompanyTask, MFAState
from engine.company.tasks import record_response, record_execution, record_result, task_ledger
from engine.company.services import CONNECTOR_FIELDS


def setUpModule():
    call_command("migrate", interactive=False, verbosity=0)


def tearDownModule():
    connections.close_all()


class ConnectorTests(TestCase):
    setUp = support.CompanyControlTests.setUp
    enroll = support.CompanyControlTests.enroll
    request = support.CompanyControlTests.request
    sensitive = support.CompanyControlTests.sensitive
    source = support.CompanyControlTests.source
    evidence = support.CompanyControlTests.evidence

    def pair(self, user=None, source_kind="synthetic"):
        user = user or self.junior
        company = Company.objects.get()
        company.collection_fields = list(dict.fromkeys(company.collection_fields + list(CONNECTOR_FIELDS)))
        company.save(update_fields=("collection_fields",))
        client = support.LocalClient()
        client.force_login(user)
        response = client.post("/connectors/", {"name": "Synthetic OpenCode", "repository_ref": "synthetic-repository",
            "directory": "/synthetic/work", "source_kind": source_kind, "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            "expected_revision": company.revision, "confirm_password": support.PASSWORD, "confirmation": "on"})
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'<pre id="connector-credential">([A-Za-z0-9_-]{43})</pre>', response.content)
        self.assertIsNotNone(match, response.content.decode())
        value = match.group(1).decode()
        return ConnectorCredential.objects.get(digest=connectors.digest(value)), value, client

    def api(self, value, method, payload, **kwargs):
        return support.LocalClient().post(f"/api/connectors/v1/{method}/", json.dumps(payload), content_type="application/json",
                                         HTTP_AUTHORIZATION="Bearer " + value, **kwargs)

    def task_source(self, **updates):
        return {"client_task_id": str(uuid.uuid4()), "session_ref": connectors.digest("ses_synthetic"),
                "location_sha256": connectors.digest("/synthetic/work"), "task_label": "Synthetic documentation",
                "task_type": "documentation", "risk_tags": ["low"], "selected_model": "fixture/premium",
                "required_tools": ["read"], "context_tokens": 2000, "boundary": "new_task", **updates}

    def started(self):
        credential, value, browser = self.pair()
        source = self.task_source()
        response = self.api(value, "start", source)
        self.assertEqual(response.status_code, 200, response.content)
        return credential, value, browser, response.json(), source

    def event(self, state, sequence=1, kind="model_attempt", model="fixture/cheap", **updates):
        return {"connector_task_ref": state["connector_task_ref"], "location_sha256": connectors.digest("/synthetic/work"),
                "event_id": str(uuid.uuid4()), "sequence": sequence,
                "payload": {"observation_kind": kind, "request_kind": "primary" if kind not in ("gap", "close") else "unknown",
                            "model": model if kind not in ("gap", "close") else None, "http_status": None, "attempt": None,
                            "retry": None, "coverage_status": "incomplete" if kind == "gap" else "limited_hook_coverage", **updates}}

    def feedback(self, value, state, action, content):
        return self.api(value, "feedback", {"connector_task_ref": state["connector_task_ref"],
            "location_sha256": connectors.digest("/synthetic/work"), "action": action, "value": content, "expected_revision": state["task_revision"]})

    def result_value(self, **updates):
        return {"desired_result": None, "tests_passed": None, "score": None, "cost_usd": None, "latency_ms": None,
                "evidence_ref": None, "supersedes": None, **updates}

    def test_pairing_is_own_scoped_expiring_password_verified_and_digest_only(self):
        credential, value, _ = self.pair()
        self.assertEqual(credential.user, self.junior)
        self.assertNotEqual(credential.digest, value)
        self.assertNotIn(value, json.dumps(credential.scope))
        self.assertNotIn("/synthetic/work", json.dumps(credential.scope))
        self.assertFalse(credential.scope["member"]["can_approve_pilots"])
        self.assertEqual(credential.scope["location_sha256"], connectors.digest("/synthetic/work"))

    def test_existing_collection_scope_not_silently_expanded(self):
        Company.objects.update(collection_fields=[field for field in support.COLLECTION_FIELDS if field not in CONNECTOR_FIELDS])
        client = support.LocalClient()
        client.force_login(self.junior)
        response = client.post("/connectors/", {"name": "Denied", "repository_ref": "synthetic-repository", "directory": "/synthetic/work",
            "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(), "expected_revision": Company.objects.get().revision,
            "confirm_password": support.PASSWORD, "source_kind": "synthetic", "confirmation": "on"})
        self.assertContains(response, "explicitly approve connector observation fields")
        self.assertEqual(ConnectorCredential.objects.count(), 0)

    def test_bearer_api_has_no_cookie_or_origin_authority_and_no_admin_endpoint(self):
        credential, value, browser = self.pair()
        body = {"location_sha256": credential.scope["location_sha256"]}
        self.assertEqual(self.api(value, "status", body, HTTP_ORIGIN="https://forged.example").status_code, 403)
        self.assertEqual(browser.post("/api/connectors/v1/status/", json.dumps(body), content_type="application/json", HTTP_AUTHORIZATION="Bearer " + value).status_code, 403)
        self.assertEqual(self.api(value, "status", body).status_code, 200)
        self.assertEqual(self.api(value, "authorize", body).status_code, 404)
        self.assertEqual(support.LocalClient().get("/api/connectors/v1/status/").status_code, 405)

    def test_revoked_expired_disabled_recovered_credentials_refused(self):
        credential, value, browser = self.pair()
        body = {"location_sha256": credential.scope["location_sha256"]}
        credential.expires_at = timezone.now() - timedelta(seconds=1)
        credential.save()
        self.assertEqual(self.api(value, "status", body).status_code, 403)
        credential.expires_at = timezone.now() + timedelta(hours=1)
        credential.save()
        self.junior.set_password("synthetic-changed-" + "P9!" * 8)
        self.junior.save()
        self.assertEqual(self.api(value, "status", body).status_code, 403)
        self.assertEqual(ConnectorCredential.objects.count(), 1)

    def test_permission_and_collection_reduction_block_existing_connector(self):
        credential, value, _ = self.pair()
        body = {"location_sha256": credential.scope["location_sha256"]}
        company = Company.objects.get()
        company.collection_fields.remove("http_status")
        company.save()
        self.assertEqual(self.api(value, "status", body).status_code, 403)
        self.assertEqual(ConnectorCredential.objects.count(), 1)

    def test_start_reuses_manual_shadow_engine_and_never_executes(self):
        credential, value, _, state, source = self.started()
        self.assertEqual(state["recommendation"]["recommended_model"], "fixture/cheap")
        self.assertEqual(state["recommendation"]["effective_model"], "fixture/premium")
        self.assertFalse(state["routing_enabled"])
        self.assertFalse(state["outcome_verified"])
        self.assertEqual(CompanyTask.objects.count(), 1)
        self.assertEqual(ConnectorTask.objects.count(), 1)

    def test_task_retry_is_exact_and_conflict_cannot_overwrite(self):
        _, value, _, state, source = self.started()
        self.assertEqual(self.api(value, "start", source).json()["task_ref"], state["task_ref"])
        self.assertEqual(self.api(value, "start", dict(source, selected_model="fixture/standard")).status_code, 400)
        self.assertEqual(CompanyTask.objects.count(), 1)

    def test_wrong_directory_session_and_subagent_cannot_be_admitted(self):
        credential, value, _ = self.pair()
        for update in ({"location_sha256": connectors.digest("/outside")}, {"session_ref": "ses_raw"}, {"boundary": "subagent"}, {"boundary": "continuation"}, {"developer_id": "senior"}):
            self.assertIn(self.api(value, "start", self.task_source(**update)).status_code, (400, 403))
        self.assertEqual(CompanyTask.objects.count(), 0)

    def test_one_open_task_per_account_session_even_across_pairings(self):
        _, value, _, state, _ = self.started()
        self.assertEqual(self.api(value, "start", self.task_source(task_label="Second")).status_code, 400)
        _, other_value, _ = self.pair()
        self.assertEqual(self.api(other_value, "start", self.task_source(task_label="Second")).status_code, 400)

    def test_append_only_events_keep_unknowns_retries_errors_and_sequence_gaps(self):
        _, value, _, state, _ = self.started()
        event = self.event(state, sequence=3, kind="http_status", http_status=500)
        response = self.api(value, "observation", event)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["gap_count"], 2)
        self.assertEqual(self.api(value, "observation", event).status_code, 200)
        self.assertEqual(ConnectorObservation.objects.count(), 1)
        changed = json.loads(json.dumps(event)); changed["payload"]["http_status"] = 200
        self.assertEqual(self.api(value, "observation", changed).status_code, 400)
        self.assertEqual(self.api(value, "observation", self.event(state, sequence=2)).status_code, 400)
        self.assertEqual(ConnectorObservation.objects.get().payload["http_status"], 500)

    def test_cross_owner_pairing_cannot_read_or_append_another_task(self):
        _, value, _, state, _ = self.started()
        _, senior_value, _ = self.pair(self.senior)
        self.assertEqual(self.api(senior_value, "observation", self.event(state)).status_code, 403)
        self.assertEqual(self.api(senior_value, "task", {"connector_task_ref": state["connector_task_ref"], "location_sha256": connectors.digest("/synthetic/work")}).status_code, 403)

    def test_response_precedes_observed_attempt_and_unknown_is_not_retroactively_accepted(self):
        _, value, browser, state, _ = self.started()
        self.assertEqual(self.api(value, "observation", self.event(state)).status_code, 200)
        self.assertEqual(self.feedback(value, state, "response", "accept").status_code, 400)
        response = browser.post(f"/tasks/{state['task_ref']}/response/", {"expected_revision": 1, "response": "accept"})
        self.assertContains(response, "must precede observed model activity")
        self.assertEqual(task_ledger(CompanyTask.objects.get()).responses, ())

    def test_joined_response_reported_actual_unknown_result_and_close(self):
        _, value, _, state, _ = self.started()
        state = self.feedback(value, state, "response", "accept").json()
        state = self.api(value, "observation", self.event(state)).json()
        state = self.api(value, "observation", self.event(state, sequence=2, kind="close")).json()
        state = self.feedback(value, state, "actual_model", "fixture/cheap").json()
        response = self.feedback(value, state, "result", self.result_value())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["current_result"]["desired_result"])
        self.assertEqual(len(task_ledger(CompanyTask.objects.get()).results), 1)

    def test_open_gapped_or_multiple_model_observation_never_invents_adopted_success(self):
        _, value, browser, state, _ = self.started()
        state = self.feedback(value, state, "actual_model", "fixture/cheap").json()
        self.assertEqual(self.feedback(value, state, "result", self.result_value(desired_result=True, evidence_ref="synthetic-report")).status_code, 400)
        state = self.api(value, "observation", self.event(state, model="fixture/cheap")).json()
        state = self.api(value, "observation", self.event(state, sequence=2, model="fixture/standard")).json()
        self.assertTrue(state["multiple_models"])
        self.assertEqual(self.feedback(value, state, "result", self.result_value(desired_result=True, evidence_ref="synthetic-ambiguous")).status_code, 400)
        self.assertEqual(ConnectorObservation.objects.count(), 2)
        self.assertEqual(len(task_ledger(CompanyTask.objects.get()).results), 0)
        response = self.feedback(value, state, "result", self.result_value(desired_result=False, evidence_ref="synthetic-multi-model-failure"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(task_ledger(CompanyTask.objects.get()).results[-1].desired_result)

    def test_gap_preserves_failure_report_and_negative_evidence(self):
        _, value, _, state, _ = self.started()
        state = self.feedback(value, state, "actual_model", "fixture/cheap").json()
        state = self.api(value, "observation", self.event(state, kind="gap")).json()
        self.assertEqual(self.feedback(value, state, "result", self.result_value(desired_result=False, evidence_ref="synthetic-failure")).status_code, 200)
        self.assertEqual(task_ledger(CompanyTask.objects.get()).results[-1].desired_result, False)

    def test_raw_prompt_body_headers_and_secret_metadata_refused_and_not_echoed(self):
        _, value, _, state, _ = self.started()
        secret = "sk-" + "A" * 32
        for field in ("prompt", "body", "headers", "output", "tokens"):
            event = self.event(state); event["payload"][field] = secret
            response = self.api(value, "observation", event)
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, secret, status_code=400)
        self.assertEqual(ConnectorObservation.objects.count(), 0)

    def test_credentials_never_appear_in_status_browser_or_audit(self):
        credential, value, browser = self.pair()
        self.assertNotContains(browser.get("/connectors/"), value)
        response = self.api(value, "status", {"location_sha256": credential.scope["location_sha256"]})
        self.assertNotContains(response, value)
        self.assertNotIn(value, json.dumps(list(support.SecurityEvent.objects.values_list("details", flat=True))))

    def test_browser_pairing_and_revoke_csrf_enforced_and_record_preserved(self):
        credential, value, browser = self.pair()
        client = support.LocalClient(enforce_csrf_checks=True)
        client.force_login(self.junior)
        self.assertEqual(client.post("/connectors/", {}).status_code, 403)
        path = f"/connectors/{credential.reference}/revoke/"
        self.assertEqual(client.post(path, {}).status_code, 403)
        self.assertEqual(browser.post(path, {"confirmation": "on", "confirm_password": support.PASSWORD}).status_code, 302)
        self.assertEqual(self.api(value, "status", {"location_sha256": credential.scope["location_sha256"]}).status_code, 403)
        self.assertEqual(ConnectorCredential.objects.count(), 1)

    def test_connector_views_no_model_or_private_client_access(self):
        credential, value, browser = self.pair()
        with patch("socket.socket", side_effect=AssertionError("No external calls")), patch("subprocess.run", side_effect=AssertionError("No provider/private client calls")):
            response = self.api(value, "status", {"location_sha256": credential.scope["location_sha256"]})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_migration_matches_models_without_replacing_baseline_tables(self):
        call_command("makemigrations", "company", check=True, dry_run=True, verbosity=0)
        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(support.Membership.objects.count(), 3)

    def test_closed_tasks_refuse_fresh_events_but_return_exact_historical_retry(self):
        _, value, _, state, _ = self.started()
        event = self.event(state, kind="close")
        self.assertEqual(self.api(value, "observation", event).status_code, 200)
        self.assertEqual(self.api(value, "observation", event).status_code, 200)
        self.assertEqual(self.api(value, "observation", self.event(state, sequence=2)).status_code, 400)
        self.assertEqual(ConnectorObservation.objects.count(), 1)

    def test_malformed_observation_measurements_and_duplicates_are_refused(self):
        _, value, _, state, _ = self.started()
        for payload in (self.event(state, kind="http_status"), self.event(state, kind="retry"),
                        self.event(state, http_status=999), self.event(state, retry="true"), self.event(state, sequence=0)):
            self.assertEqual(self.api(value, "observation", payload).status_code, 400)
        self.assertEqual(ConnectorObservation.objects.count(), 0)

    def test_primary_and_auxiliary_attempts_are_separate_and_not_cumulative_usage(self):
        _, value, _, state, _ = self.started()
        self.api(value, "observation", self.event(state, model="fixture/cheap"))
        response = self.api(value, "observation", self.event(state, sequence=2, model="fixture/premium", request_kind="title"))
        self.assertEqual(response.json()["observed_attempt_models"], ["fixture/cheap"])
        self.assertFalse(response.json()["multiple_models"])
        self.assertFalse(response.json()["usage_verified"])
        self.assertEqual(ConnectorObservation.objects.count(), 2)

    def test_changed_identity_role_or_mfa_generation_invalidates_token(self):
        credential, value, _ = self.pair()
        support.Membership.objects.filter(user=self.junior).update(role="senior")
        self.assertEqual(self.api(value, "status", {"location_sha256": credential.scope["location_sha256"]}).status_code, 403)
        support.Membership.objects.filter(user=self.junior).update(role="junior")
        MFAState.objects.create(user=self.junior, generation=1)
        self.assertEqual(self.api(value, "status", {"location_sha256": credential.scope["location_sha256"]}).status_code, 403)

    def test_corrupt_observation_history_is_refused_without_reset(self):
        _, value, _, state, _ = self.started()
        self.api(value, "observation", self.event(state))
        ConnectorTask.objects.update(sequence=5)
        response = self.api(value, "task", {"connector_task_ref": state["connector_task_ref"], "location_sha256": connectors.digest("/synthetic/work")})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ConnectorTask.objects.get().sequence, 5)
        self.assertEqual(ConnectorObservation.objects.count(), 1)

    def test_success_report_requires_closed_consistent_single_model_and_stale_corrections_refused(self):
        _, value, browser, state, _ = self.started()
        state = self.feedback(value, state, "response", "accept").json()
        state = self.api(value, "observation", self.event(state)).json()
        state = self.api(value, "observation", self.event(state, sequence=2, kind="close")).json()
        state = self.feedback(value, state, "actual_model", "fixture/cheap").json()
        state = self.feedback(value, state, "result", self.result_value(desired_result=True, evidence_ref="synthetic-reported-result")).json()
        previous = state["current_result"]["result_id"]
        correction = self.result_value(desired_result=False, evidence_ref="synthetic-correction", supersedes=previous)
        self.assertEqual(self.feedback(value, state, "result", correction).status_code, 200)
        self.assertEqual(self.feedback(value, state, "result", self.result_value(supersedes=previous)).status_code, 400)
        page = browser.get(state["browser_path"])
        self.assertContains(page, "Linked OpenCode observations")
        self.assertContains(page, "synthetic-correction")

    def test_expired_connector_can_be_closed_in_browser_only_with_permanent_gap(self):
        credential, value, browser, state, _ = self.started()
        credential.expires_at = timezone.now() - timedelta(seconds=1)
        credential.save()
        path = f"/tasks/{state['task_ref']}/connector/end-interrupted/"
        self.assertEqual(browser.post(path, {"expected_sequence": 0, "confirm_password": support.PASSWORD, "confirmation": "on"}).status_code, 302)
        link = ConnectorTask.objects.get()
        self.assertIsNotNone(link.closed_at)
        self.assertEqual(list(link.observations.values_list("payload__observation_kind", flat=True)), ["gap", "close"])
        self.assertEqual(connectors.task_state(link)["gap_count"], 1)
        self.assertEqual(self.api(value, "task", {"connector_task_ref": state["connector_task_ref"], "location_sha256": connectors.digest("/synthetic/work")}).status_code, 403)

    def test_interrupted_close_rechecks_owner_csrf_and_expected_sequence(self):
        _, value, browser, state, _ = self.started()
        self.api(value, "observation", self.event(state))
        path = f"/tasks/{state['task_ref']}/connector/end-interrupted/"
        self.assertContains(browser.post(path, {"expected_sequence": 0, "confirm_password": support.PASSWORD, "confirmation": "on"}), "changed/ended")
        senior = support.LocalClient(); senior.force_login(self.senior)
        self.assertEqual(senior.get(path).status_code, 403)
        csrf = support.LocalClient(enforce_csrf_checks=True); csrf.force_login(self.junior)
        self.assertEqual(csrf.post(path, {}).status_code, 403)
        self.assertIsNone(ConnectorTask.objects.get().closed_at)

    def test_new_connector_observations_stale_category_review_and_preserve_negative_sidecar(self):
        _, value, _, state, _ = self.started()
        self.api(value, "observation", self.event(state, kind="http_status", http_status=500))
        review = self.evidence()
        bound = review.data["connector_observations"]
        self.assertEqual(bound[0]["observations"][0]["payload"]["http_status"], 500)
        self.assertEqual(bound[0]["observations"][0]["actor_snapshot"]["role"], "junior")
        support.authorization.verify_review(review, Company.objects.get())
        self.api(value, "observation", self.event(state, sequence=2, kind="gap"))
        with self.assertRaisesMessage(support.ValidationError, "changed"):
            support.authorization.verify_review(review, Company.objects.get())
        self.assertContains(self.client.get(f"/pilots/reviews/{review.reference}/"), "Bound OpenCode observation diagnostics")

    def test_empty_closed_interval_cannot_supply_successful_model_evidence(self):
        _, value, _, state, _ = self.started()
        state = self.feedback(value, state, "actual_model", "fixture/cheap").json()
        state = self.api(value, "observation", self.event(state, kind="close")).json()
        response = self.feedback(value, state, "result", self.result_value(desired_result=True, evidence_ref="synthetic-empty"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("empty interval", response.json()["error"])


class ConnectorJavaScriptTests(unittest.TestCase):
    def test_dependency_free_connector_and_mock_host_suite(self):
        root = Path(__file__).resolve().parent.parent
        paths = sorted((root / "integrations/opencode/test").glob("*.test.mjs"))
        result = subprocess.run(["node", "--test", *map(str, paths)], cwd=root, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("fail 0", result.stdout)
