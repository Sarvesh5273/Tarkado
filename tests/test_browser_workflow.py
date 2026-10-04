"""Joined B-03 browser checks on isolated synthetic accounts/stores; no models or private sessions."""

from base64 import b32decode
import http.cookiejar
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

import test_company as support

from django.core.management import call_command
from django.db import connections
from django.test import TestCase, override_settings
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.oath import TOTP

from engine.company import authorization
from engine.company.models import AuthorizedPilot, Company, CompanyTask, EvidenceReview, Membership, PilotAuthorization
from engine.company.tasks import recommend_task, record_execution, record_response, record_result, task_ledger
from engine.pilot import PilotJournal


def setUpModule():
    call_command("migrate", interactive=False, verbosity=0)


def tearDownModule():
    connections.close_all()


class BrowserForms(HTMLParser):
    """Read rendered fields/options the way a browser does, without copying internal IDs by hand."""

    def __init__(self, page):
        super().__init__()
        self.forms = []
        self.current = None
        self.select = self.textarea = self.option = None
        self.feed(page.content.decode())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"values": {}, "options": {}}
            self.forms.append(self.current)
        if self.current is None:
            return
        if tag == "input" and attrs.get("name"):
            name, value = attrs["name"], attrs.get("value", "on" if attrs.get("type") in ("checkbox", "radio") else "")
            if attrs.get("type") in ("checkbox", "radio"):
                self.current["options"].setdefault(name, []).append((value, ""))
                if "checked" in attrs:
                    self.current["values"].setdefault(name, []).append(value)
            else:
                previous = self.current["values"].get(name)
                self.current["values"][name] = value if previous is None else (previous + [value] if isinstance(previous, list) else [previous, value])
        elif tag == "select":
            self.select = attrs["name"]
            self.current["options"][self.select] = []
        elif tag == "option" and self.select:
            self.option = attrs.get("value", "")
            self.current["options"][self.select].append((self.option, ""))
            if "selected" in attrs or self.select not in self.current["values"]:
                self.current["values"][self.select] = self.option
        elif tag == "textarea":
            self.textarea = attrs["name"]
            self.current["values"][self.textarea] = ""

    def handle_data(self, data):
        if self.current and self.textarea:
            self.current["values"][self.textarea] += data
        if self.current and self.select and self.option is not None:
            value, label = self.current["options"][self.select][-1]
            self.current["options"][self.select][-1] = (value, label + data)

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None
        elif tag == "select":
            self.select = self.option = None
        elif tag == "option":
            self.option = None
        elif tag == "textarea":
            self.textarea = None

    def containing(self, field):
        return next(form for form in self.forms if field in form["values"] or field in form["options"])


class BrowserWorkflowTests(TestCase):
    # Reuse synthetic setup helpers, not inherited tests or an authorization bypass.
    setUp = support.CompanyControlTests.setUp
    enroll = support.CompanyControlTests.enroll
    request = support.CompanyControlTests.request
    sensitive = support.CompanyControlTests.sensitive
    source = support.CompanyControlTests.source
    evidence = support.CompanyControlTests.evidence
    approve = support.CompanyControlTests.approve
    active = support.CompanyControlTests.active
    developer_request = support.CompanyControlTests.developer_request

    def browser(self, user):
        client = support.LocalClient()
        client.force_login(user)
        return client

    def fresh_post(self, client, path, values):
        device = TOTPDevice.objects.get(user_id=client.session["_auth_user_id"], confirmed=True)
        code, at = support.device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            return client.post(path, dict(values, confirm_password=support.PASSWORD, code=code))

    def scope_values(self, review):
        path = f"/pilots/reviews/{review.reference}/authorize/"
        values = BrowserForms(self.client.get(path)).containing("pilot_id")["values"]
        values.update(pilot_id="browser-scope", repository_ref="synthetic-repository", task_types=["documentation"],
                      developer_ids=["junior", "senior"], max_tasks=3, max_cost_usd="1.00",
                      expires_at=(timezone.now() + timedelta(hours=1)).isoformat(), reason="Reviewed exact synthetic scope")
        return path, values

    def preview(self, review=None):
        review = review or self.evidence()
        path, values = self.scope_values(review)
        page = self.client.post(path, values)
        self.assertContains(page, "Confirm the exact scope below")
        self.assertEqual(PilotAuthorization.objects.count(), 0)
        return path, BrowserForms(page).containing("confirmation_token")["values"]

    def executed(self, user=None, number=1, actual="fixture/cheap"):
        user = user or self.junior
        task = recommend_task(user, self.source(number))
        task = record_response(user, task.reference, "accept", task.revision)
        return record_execution(user, task.reference, actual, task.revision)

    def result(self, **updates):
        return {"desired_result": True, "tests_passed": None, "score": "0.83", "cost_usd": "0.006",
                "latency_ms": 200, "evidence_ref": "synthetic-review", "supersedes": None, **updates}

    def test_home_has_role_navigation_pending_task_cards_and_manual_limits(self):
        recommend_task(self.junior, self.source())
        client = self.browser(self.junior)
        page = client.get("/")
        for text in ("Awaiting per-task response", "fixture/premium", "fixture/cheap", "does not collect live tasks", "Start a manual task", "Skip to main content"):
            self.assertContains(page, text)
        self.assertNotContains(page, 'href="/configuration/"')
        self.assertNotContains(page, "<pre>")

    def test_task_form_lists_permitted_repositories_models_and_category_help(self):
        page = self.browser(self.junior).get("/tasks/new/")
        form = BrowserForms(page).containing("selected_model")
        self.assertEqual(form["options"]["repository_ref"], [("synthetic-repository", "synthetic-repository")])
        self.assertEqual([item[0] for item in form["options"]["selected_model"]], [model.model_id for model in self.policy.models])
        self.assertContains(page, 'id="task-categories"')
        self.assertContains(page, "blank means unknown")

    def test_out_of_scope_repository_selector_cannot_grant_collection(self):
        client = self.browser(self.junior)
        values = self.source(repository_ref="private-outside-scope", risk_tags="low", required_tools="read")
        self.assertContains(client.post("/tasks/new/", values), "Select a valid choice")
        self.assertEqual(CompanyTask.objects.count(), 0)

    def test_unknown_category_and_context_stay_blocked_and_do_not_invent_confidence(self):
        task = recommend_task(self.junior, self.source(task_type=None, context_tokens=None, risk_tags=[]))
        page = self.browser(self.junior).get(f"/tasks/{task.reference}/")
        self.assertContains(page, "Blocked")
        self.assertContains(page, "not a measured probability")
        self.assertContains(page, "Unknown")
        self.assertIsNone(task_ledger(task).recommendations[0].decision["recommended_model"])

    def test_response_and_actual_model_are_separate_and_late_response_link_is_hidden(self):
        task = recommend_task(self.junior, self.source())
        client = self.browser(self.junior)
        path = f"/tasks/{task.reference}/"
        self.assertEqual(client.post(path + "execution/", {"expected_revision": 1, "actual_model": "fixture/cheap"}).status_code, 302)
        page = client.get(path)
        self.assertNotContains(page, 'href="' + path + 'response/"')
        self.assertContains(page, "it stays unknown")
        self.assertContains(client.post(path + "response/", {"expected_revision": 2, "response": "accept"}), "cannot be added after")
        self.assertEqual(task_ledger(CompanyTask.objects.get()).responses, ())

    def test_unapproved_actual_model_and_mismatch_are_retained_readably(self):
        task = self.executed(actual="unapproved/observed")
        record_result(self.junior, task.reference, self.result(desired_result=False), task.revision)
        page = self.browser(self.junior).get(f"/tasks/{task.reference}/")
        for text in ("unapproved/observed", "Different model used", "Reported failure", "not currently compatible/approved"):
            self.assertContains(page, text)
        self.assertNotContains(page, "<pre>")

    def test_unknown_result_is_visible_and_acceptance_is_not_success(self):
        task = self.executed()
        record_result(self.junior, task.reference, self.result(desired_result=None, score=None, cost_usd=None, latency_ms=None, evidence_ref=None), task.revision)
        page = self.browser(self.junior).get(f"/tasks/{task.reference}/")
        self.assertContains(page, "Result unknown")
        self.assertContains(page, "Unknown", count=12)
        self.assertNotContains(page, "Reported desired result</h3>")

    def test_correction_form_prefills_full_result_and_resolves_current_result_internally(self):
        task = self.executed()
        task = record_result(self.junior, task.reference, self.result(), task.revision)
        client = self.browser(self.junior)
        path = f"/tasks/{task.reference}/result/"
        values = BrowserForms(client.get(path)).containing("supersedes")["values"]
        self.assertEqual(values["score"], "0.83")
        self.assertEqual(values["cost_usd"], "0.006")
        self.assertEqual(values["supersedes"], task_ledger(task).results[-1].result_id)
        values.update(desired_result="false", tests_passed="false", evidence_ref="synthetic-correction")
        self.assertEqual(client.post(path, values).status_code, 302)
        page = client.get(f"/tasks/{task.reference}/")
        self.assertContains(page, "synthetic-review")
        self.assertContains(page, "synthetic-correction")
        task.refresh_from_db()
        self.assertEqual(len(task_ledger(task).results), 2)

    def test_stale_browser_correction_cannot_discard_a_newer_result(self):
        task = self.executed()
        task = record_result(self.junior, task.reference, self.result(), task.revision)
        client = self.browser(self.junior)
        path = f"/tasks/{task.reference}/result/"
        values = BrowserForms(client.get(path)).containing("supersedes")["values"]
        old = task_ledger(task).results[-1].result_id
        record_result(self.junior, task.reference, self.result(supersedes=old, desired_result=False), task.revision)
        self.assertContains(client.post(path, values), "Task changed")
        task.refresh_from_db()
        self.assertEqual(len(task_ledger(task).results), 2)

    def test_admin_history_has_no_engineering_actions_and_senior_cannot_replace_another_reviewer(self):
        task = self.executed()
        record_result(self.senior, task.reference, self.result(), task.revision)
        path = f"/tasks/{task.reference}/"
        self.assertNotContains(self.client.get(path), 'href="' + path + 'result/"')
        self.assertNotContains(self.browser(self.junior).get(path), 'href="' + path + 'result/"')
        self.assertContains(self.client.get(path), "role at submission senior")
        self.assertEqual(self.client.get(path + "result/").status_code, 403)

    def test_review_selectors_show_work_labels_not_projected_session_ids(self):
        review = self.evidence()
        page = self.client.get("/pilots/reviews/new/")
        self.assertContains(page, "senior / session-1")
        self.assertContains(page, "senior / session-2")
        self.assertNotContains(page, "Available projected session references")
        form = BrowserForms(page).containing("session_ids")
        self.assertEqual(len(form["options"]["session_ids"]), 2)
        self.assertEqual([item[0] for item in form["options"]["task_types"]], ["documentation"])
        self.assertEqual(len(review.data["learner"]["plan"]["session_ids"]), 2)

    def test_browser_builds_review_from_rendered_session_choices(self):
        self.evidence()
        form = BrowserForms(self.client.get("/pilots/reviews/new/")).containing("session_ids")
        values = form["values"]
        values.update(learner_version="browser-validation-v1", source_kind="synthetic", cutoff=timezone.now().isoformat(),
                      session_ids=[item[0] for item in form["options"]["session_ids"]], task_types=["documentation"],
                      min_senior_successes=2, min_senior_sessions=2)
        page = self.client.post("/pilots/reviews/new/", values)
        self.assertEqual(page.status_code, 302)
        self.assertNotIn("authorize", page["Location"])
        self.assertContains(self.client.get(page["Location"]), "Category evidence review")

    def test_review_rejects_unknown_duplicate_and_wrong_source_selections(self):
        review = self.evidence()
        plan = review.data["learner"]["plan"]
        for updates in ({"session_ids": ["forged-session"]}, {"session_ids": [plan["session_ids"][0]] * 2},
                        {"source_kind": "team"}, {"dataset_split": "test"}):
            values = {key: value for key, value in plan.items() if key != "dataset_split"}
            values.update(updates)
            self.assertEqual(self.client.post("/pilots/reviews/new/", values).status_code, 200)
            self.assertEqual(EvidenceReview.objects.count(), 1)

    def test_nondesignated_admin_can_review_and_inspect_but_cannot_authorize_or_control(self):
        review = self.evidence()
        approval = self.approve(review)
        _, invitation = support.create_invitation(self.owner, support.PASSWORD, "review-admin", "admin", False, True, False,
                                                  timezone.now() + timedelta(hours=1), Company.objects.get().revision, reason="Synthetic evidence administrator")
        admin = support.accept_invitation(invitation, support.PASSWORD)
        client = self.browser(admin)
        page = client.get(f"/pilots/reviews/{review.reference}/")
        self.assertContains(page, "not a designated pilot approver")
        self.assertNotContains(page, 'href="' + f'/pilots/reviews/{review.reference}/authorize/' + '"')
        self.assertEqual(client.get(f"/pilots/{approval.reference}/").status_code, 200)
        self.assertEqual(client.post(f"/pilots/{approval.reference}/", {"action": "activate"}).status_code, 403)
        self.assertEqual(client.get(f"/pilots/reviews/{review.reference}/authorize/").status_code, 403)

    def test_review_displays_junior_failures_rejects_unknowns_and_all_corrections(self):
        self.evidence()
        task = self.executed(number=3)
        task = record_result(self.junior, task.reference, self.result(desired_result=False), task.revision)
        record_result(self.junior, task.reference, self.result(desired_result=None, supersedes=task_ledger(task).results[-1].result_id), task.revision)
        task = recommend_task(self.junior, self.source(4))
        record_response(self.junior, task.reference, "reject", task.revision)
        from engine.company.tasks import company_ledger
        ledger = company_ledger(Company.objects.get(), "synthetic")
        plan = {"learner_version": "negative-browser-v1", "source_kind": "synthetic", "dataset_split": "validation",
                "cutoff": timezone.now().isoformat(), "session_ids": [rec.task.session_id for rec in ledger.recommendations],
                "task_types": ["documentation"], "min_senior_successes": 2, "min_senior_sessions": 2}
        review = authorization.prepare_review(self.request(), plan)
        page = self.client.get(f"/pilots/reviews/{review.reference}/")
        for text in ("blocked", "rejects 1", "unknown results 1", "All result revisions", "junior", "synthetic-review"):
            self.assertContains(page, text)
        self.assertEqual(len(review.data["report"]["observations"]), 4)
        self.assertEqual(len(review.data["report"]["result_history"]), 4)

    def test_scope_preview_is_readable_and_requires_separate_confirmation_and_fresh_mfa(self):
        path, values = self.preview()
        values["confirmation"] = "on"
        response = self.client.post(path, values)
        self.assertContains(response, "This field is required")
        self.assertEqual(PilotAuthorization.objects.count(), 0)
        response = self.fresh_post(self.client, path, values)
        self.assertEqual(response.status_code, 302)
        approval = PilotAuthorization.objects.get()
        self.assertEqual(approval.data["receipt"]["scope"]["developer_ids"], ["junior", "senior"])
        self.assertEqual(AuthorizedPilot.objects.count(), 0)

    def test_confirmation_cannot_change_scope_expiry_reason_or_target(self):
        path, values = self.preview()
        for updates in ({"max_tasks": 100}, {"developer_ids": ["senior"]}, {"reason": "Changed reason"}, {"target": "live"}):
            changed = dict(values, confirmation="on", **updates)
            response = self.fresh_post(self.client, path, changed)
            self.assertContains(response, "changed scope requires a new review")
            self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_refused_confirmation_can_retry_fresh_credentials_without_recopying_scope(self):
        path, values = self.preview()
        page = self.client.post(path, dict(values, confirmation="on"))
        self.assertContains(page, "Confirm the exact scope below")
        self.assertContains(page, 'name="code"')
        retry = BrowserForms(page).containing("confirmation_token")["values"]
        self.assertEqual(retry["confirmation_token"], values["confirmation_token"])
        self.assertEqual(retry["developer_ids"], ["junior", "senior"])
        self.assertEqual(self.fresh_post(self.client, path, retry).status_code, 302)
        self.assertEqual(PilotAuthorization.objects.count(), 1)

    def test_confirmation_rejects_missing_acknowledgment_expired_token_and_cross_account(self):
        path, values = self.preview()
        self.assertContains(self.fresh_post(self.client, path, values), "Confirm the exact displayed content")
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 901):
            self.assertContains(self.fresh_post(self.client, path, dict(values, confirmation="on")), "Confirmation expired")
        self.assertEqual(self.browser(self.senior).post(path, dict(values, confirmation="on")).status_code, 403)
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_stale_evidence_and_revision_refuse_confirmed_scope(self):
        path, values = self.preview()
        recommend_task(self.junior, self.source(3))
        self.assertEqual(self.fresh_post(self.client, path, dict(values, confirmation="on")).status_code, 200)
        self.assertEqual(PilotAuthorization.objects.count(), 0)
        self.assertContains(self.client.get(path), "Stale evidence cannot be authorized")

    def test_secret_in_preview_is_refused_without_redisplay_or_storage(self):
        review = self.evidence()
        path, values = self.scope_values(review)
        secret = "sk-" + "A" * 32
        values["reason"] = secret
        page = self.client.post(path, values)
        self.assertNotContains(page, secret)
        self.assertNotContains(page, "Confirm the exact scope below")
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_control_choices_follow_state_and_confirmation_preserves_accounting(self):
        approval = self.approve()
        path = f"/pilots/{approval.reference}/"
        form = BrowserForms(self.client.get(path)).containing("action")
        self.assertEqual([item[0] for item in form["options"]["action"]], ["activate", "revoke"])
        values = dict(form["values"], action="activate", reason="Explicit browser activation")
        preview = self.client.post(path, values)
        self.assertContains(preview, "Confirm consequential control")
        self.assertEqual(AuthorizedPilot.objects.count(), 0)
        final = BrowserForms(preview).containing("confirmation_token")["values"]
        self.assertEqual(self.fresh_post(self.client, path, dict(final, confirmation="on")).status_code, 302)
        form = BrowserForms(self.client.get(path)).containing("action")
        self.assertEqual([item[0] for item in form["options"]["action"]], ["pause", "revoke", "rollback"])
        self.assertEqual(PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state().accounting()["spent_usd"], "0")

    def test_stale_activation_revision_is_refused_inside_existing_authority(self):
        approval = self.approve()
        self.sensitive(authorization.activate, approval.reference, "Synthetic activation")
        with self.assertRaisesMessage(support.ValidationError, "stale activation"):
            self.sensitive(authorization.activate, approval.reference, "Synthetic activation", expected_revision=0)
        self.assertEqual(PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state().revision, 1)

    def test_owned_settlement_selector_filters_other_developers_and_refuses_forged_id(self):
        approval = self.active()
        own = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.10")
        other = authorization.decide(self.developer_request(self.senior), approval.reference, self.source(4), "0.10")
        client = self.browser(self.junior)
        path = f"/pilots/{approval.reference}/settle/"
        form = BrowserForms(client.get(path)).containing("decision_id")
        self.assertEqual([item[0] for item in form["options"]["decision_id"]], [own["decision_id"]])
        self.assertContains(client.get(path), "docs-3")
        self.assertNotContains(client.get(path), "docs-4")
        self.assertContains(client.post(path, {"decision_id": other["decision_id"], "actual_cost_usd": "0.01", "outcome": "completed"}), "Select a valid choice")
        self.assertEqual(PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state().accounting()["settled_tasks"], 0)

    def test_overrun_failure_negative_budget_and_post_revoke_settlement_stay_visible(self):
        approval = self.active()
        decision = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.10")
        self.sensitive(authorization.control, approval.reference, "revoke", 2, "Preserve settlement")
        client = self.browser(self.junior)
        path = f"/pilots/{approval.reference}/settle/"
        values = BrowserForms(client.get(path)).containing("decision_id")["values"]
        values.update(actual_cost_usd="1.30", outcome="failed")
        self.assertContains(client.post(path, values), "-0.30")
        self.assertContains(self.client.get(f"/pilots/{approval.reference}/"), "Overrun Yes")
        self.assertNotContains(self.client.get(f"/pilots/{approval.reference}/"), 'value="resume"')
        self.assertContains(client.post(path, values), "-0.30")
        self.assertEqual(PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state().accounting()["settled_tasks"], 1)

    def test_unscoped_developer_cannot_inspect_simulation_or_settle_it(self):
        approval = self.active()
        user = self.enroll("outside-dev", "developer")
        client = self.browser(user)
        for suffix in ("decide/", "settle/"):
            self.assertEqual(client.get(f"/pilots/{approval.reference}/{suffix}").status_code, 403)

    def test_live_scope_never_offers_simulation_controls_in_browser(self):
        from test_live_authorization import ControlledReadinessVerifier, LiveApprovalTests
        with patch.object(self, "source", side_effect=lambda number: support.CompanyControlTests.source(self, number, source_kind="team")):
            review = LiveApprovalTests.evidence(self)
        with override_settings(TARKADO_READINESS_VERIFIER=ControlledReadinessVerifier()):
            approval = self.approve(review, target="live")
            page = self.client.get(f"/pilots/{approval.reference}/")
            for item in ("activate", "pause", "resume"):
                self.assertNotContains(page, 'value="' + item + '"')
            self.assertContains(page, "not an execution/reservation ticket")
            client = self.browser(self.junior)
            self.assertEqual(client.get(f"/pilots/{approval.reference}/decide/").status_code, 403)
            self.assertEqual(client.get(f"/pilots/{approval.reference}/settle/").status_code, 403)
        self.assertEqual(AuthorizedPilot.objects.count(), 0)

    def test_guided_configuration_has_no_json_editor_and_preserves_unchanged_policy(self):
        page = self.client.get("/configuration/")
        self.assertNotContains(page, 'name="policy_json"')
        self.assertContains(page, "Existing registered models")
        values = BrowserForms(page).containing("policy_version")["values"]
        values.update(reason="Same policy, browser company rename", confirm_password=support.PASSWORD, name="Renamed synthetic company")
        self.assertEqual(self.client.post("/configuration/", values).status_code, 302)
        self.assertEqual(Company.objects.get().policy, self.policy.to_dict())
        self.assertEqual(Company.objects.get().collection_fields, list(support.COLLECTION_FIELDS))

    def test_guided_policy_changes_require_new_version_and_cannot_disable_fallback(self):
        values = BrowserForms(self.client.get("/configuration/")).containing("policy_version")["values"]
        values.update(reason="Browser capability change", confirm_password=support.PASSWORD, model_0_status="disabled")
        self.assertContains(self.client.post("/configuration/", values), "new policy version")
        self.assertEqual(Company.objects.get().policy, self.policy.to_dict())
        values["policy_version"] = "browser-policy-v2"
        self.assertEqual(self.client.post("/configuration/", values).status_code, 302)
        values = BrowserForms(self.client.get("/configuration/")).containing("policy_version")["values"]
        values.update(reason="Invalid fallback change", confirm_password=support.PASSWORD, policy_version="browser-policy-v3", model_2_status="disabled")
        self.assertContains(self.client.post("/configuration/", values), "approved premium model")
        self.assertEqual(Company.objects.get().policy["policy_version"], "browser-policy-v2")

    def test_guided_configuration_rejects_duplicate_fields_and_secret_metadata(self):
        values = BrowserForms(self.client.get("/configuration/")).containing("policy_version")["values"]
        values.update(reason="Synthetic browser refusal", confirm_password=support.PASSWORD, model_0_tools=["read", "edit"])
        self.assertContains(self.client.post("/configuration/", values), "Duplicate form values")
        values["model_0_tools"] = "sk-" + "A" * 32
        self.assertNotContains(self.client.post("/configuration/", values), values["model_0_tools"])
        self.assertEqual(Company.objects.get().policy, self.policy.to_dict())

    def test_new_browser_pages_preserve_csrf_privacy_and_no_network(self):
        review = self.evidence()
        client = support.LocalClient(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for path in ("/pilots/reviews/new/", f"/pilots/reviews/{review.reference}/authorize/", "/configuration/"):
            self.assertEqual(client.post(path, {}).status_code, 403)
            with patch("socket.socket", side_effect=AssertionError("No external access")), patch("subprocess.run", side_effect=AssertionError("No model/client calls")):
                page = self.client.get(path)
            self.assertEqual(page["Cache-Control"], "no-store")
            self.assertEqual(page["Referrer-Policy"], "no-referrer")
            self.assertEqual(page["X-Frame-Options"], "DENY")


class BrowserHTTPTests(unittest.TestCase):
    def test_real_http_task_review_and_scope_preview_use_rendered_choices_and_refuse_forgery(self):
        with tempfile.TemporaryDirectory(prefix="browser-http-", dir=support.TEMPORARY.name) as temporary:
            root = Path(temporary) / "company"
            result = subprocess.run([sys.executable, "-m", "engine", "company", "bootstrap", "--store", str(root),
                "--name", "Synthetic B-03 HTTP", "--username", "owner", "--policy", str(support.FIXTURES / "policy.json"),
                "--repositories", "synthetic-repository", "--company-api", "--pilot-approver"], cwd=support.ROOT,
                input=support.PASSWORD + "\n" + support.PASSWORD + "\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            process = subprocess.Popen([sys.executable, "-m", "engine", "company", "serve", "--store", str(root), "--port", str(port)],
                                       cwd=support.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            base = f"http://127.0.0.1:{port}"
            owner = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
            senior = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

            def get(client, path):
                with client.open(base + path, timeout=5) as response:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    return SimpleNamespace(content=response.read(), url=response.geturl())

            def post(client, path, values, field):
                rendered = BrowserForms(get(client, path)).containing(field)["values"]
                rendered.update(values)
                with client.open(Request(base + path, data=urlencode(rendered, doseq=True).encode()), timeout=5) as response:
                    return SimpleNamespace(content=response.read(), url=response.geturl())

            try:
                deadline = time.monotonic() + 15
                started = False
                while time.monotonic() < deadline:
                    try:
                        get(owner, "/login/")
                        started = True
                        break
                    except URLError:
                        time.sleep(0.05)
                self.assertTrue(started, "Synthetic HTTP service did not start.")
                page = post(owner, "/login/", {"username": "owner", "password": support.PASSWORD}, "username")
                self.assertIn(b"Signed in as owner", page.content)
                page = post(owner, "/security/mfa/setup/", {"confirm_password": support.PASSWORD}, "confirm_password")
                seed = re.search(rb'<pre id="setup-secret">([A-Z2-7]+)</pre>', page.content)
                self.assertIsNotNone(seed)
                authenticator = TOTP(b32decode(seed.group(1)), 30, 0, 6, 0)
                page = post(owner, "/security/mfa/confirm/", {"code": str(authenticator.token()).zfill(6)}, "code")
                self.assertIn(b"Authenticator confirmed", page.content)
                page = post(owner, "/invitations/", {"username": "senior-http", "role": "senior", "participating": "on",
                    "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(), "reason": "Synthetic browser HTTP", "confirm_password": support.PASSWORD}, "username")
                invitation = re.search(rb'<pre>([A-Za-z0-9_-]{43})</pre>', page.content)
                self.assertIsNotNone(invitation)
                post(senior, "/join/", {"invitation": invitation.group(1).decode(), "password1": support.PASSWORD, "password2": support.PASSWORD}, "invitation")
                post(senior, "/login/", {"username": "senior-http", "password": support.PASSWORD}, "username")
                for number in (1, 2):
                    page = post(senior, "/tasks/new/", {"task_id": f"http-task-{number}", "session_id": f"http-work-{number}",
                        "source_kind": "synthetic", "boundary": "new_task", "task_type": "documentation", "risk_tags": "low",
                        "required_tools": "read", "context_tokens": 2000, "selected_model": "fixture/premium"}, "task_id")
                    path = page.url.removeprefix(base)
                    self.assertIn(b"Suggested: fixture/cheap", page.content)
                    post(senior, path + "response/", {"response": "accept"}, "response")
                    post(senior, path + "execution/", {"actual_model": "fixture/cheap"}, "actual_model")
                    page = post(senior, path + "result/", {"desired_result": "true", "tests_passed": "unknown", "cost_usd": "0.006", "evidence_ref": f"synthetic-http-result-{number}"}, "desired_result")
                    self.assertIn(b"Reported desired result", page.content)
                form = BrowserForms(get(owner, "/pilots/reviews/new/")).containing("session_ids")
                values = form["values"]
                values.update(learner_version="http-validation-v1", session_ids=[item[0] for item in form["options"]["session_ids"]],
                              task_types=["documentation"], min_senior_successes=2, min_senior_sessions=2, cutoff=timezone.now().isoformat())
                self.assertEqual(len(values["session_ids"]), 2)
                page = post(owner, "/pilots/reviews/new/", values, "learner_version")
                self.assertIn(b"Category evidence review", page.content)
                review_path = page.url.removeprefix(base)
                scope_path = review_path + "authorize/"
                page = post(owner, scope_path, {"pilot_id": "http-browser-pilot", "repository_ref": "synthetic-repository",
                    "task_types": ["documentation"], "developer_ids": ["senior-http"], "max_tasks": 3, "max_cost_usd": "1.00",
                    "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(), "reason": "Synthetic scope preview", "preview": "scope"}, "pilot_id")
                self.assertIn(b"Confirm the exact scope below", page.content)
                self.assertIn(b"synthetic-repository", page.content)
                self.assertIn(b"senior-http", page.content)
                confirmed = BrowserForms(page).containing("confirmation_token")["values"]
                confirmed.update(confirmation="on", confirm_password=support.PASSWORD, readiness_verified="true")
                with owner.open(Request(base + scope_path, data=urlencode(confirmed, doseq=True).encode()), timeout=5) as response:
                    refused = response.read()
                self.assertIn(b"Unexpected form fields", refused)
                self.assertNotIn(support.PASSWORD.encode(), refused)
                self.assertNotIn(seed.group(1), refused)
                self.assertNotIn(b"http-browser-pilot</a>", get(owner, "/pilots/").content)
                with self.assertRaises(HTTPError) as error:
                    senior.open(base + scope_path, timeout=5)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            finally:
                process.terminate()
                output, diagnostics = process.communicate(timeout=10)
                self.assertNotIn(support.PASSWORD, output + diagnostics)
