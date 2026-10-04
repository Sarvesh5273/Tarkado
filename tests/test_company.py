"""Real Django account/permission tests; all identities and credentials are synthetic."""

import atexit
from base64 import b32decode
import copy
import hashlib
import http.cookiejar
import io
import json
import os
import re
import subprocess
import socket
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from engine.company.runtime import check_private_file, configure, initialize_store, private_directory


TEMPORARY = tempfile.TemporaryDirectory(prefix="tarkado-company-suite-")
atexit.register(TEMPORARY.cleanup)
configure(Path(TEMPORARY.name) / "state", create=True)
initialize_store(Path(TEMPORARY.name) / "state")

from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.core.management import call_command
from django.db import connections
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from engine.company.models import Company, CompanyEvent, Invitation, LoginAttempt, Membership
from engine.company.models import CompanyTask, TaskEvent
from engine.company.models import MFAState, SecurityEvent
from engine.company.models import AuthorizedPilot, EvidenceReview, PilotAuthorization, RecoveryGrant
from engine.company import authorization, recovery
from engine.company.deployment import validate_deployment
from engine.company.mfa import PROOF_KEY, RECOVERY_KEY, recover_factor, verify_mfa
from engine.company.services import (
    COLLECTION_FIELDS, LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW, accept_invitation,
    bootstrap_company, checked_login, collection_team, create_invitation, current_member,
    require_collection, revoke_invitation, update_company, update_member,
)
from engine.feedback import import_scenario
from engine.feedback import FeedbackLedger, feedback_summary
from engine.company.tasks import (
    company_feedback, get_task, recommend_task, record_execution, record_response,
    record_result, task_detail, task_ledger, visible_tasks,
)
from engine.importers import load_policy, parse_json
from engine.schemas import ValidationError
from engine.pilot import PilotJournal
from engine.privacy import PrivacyError


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PASSWORD = "synthetic-account-" + "R9!" * 8


def setUpModule():
    call_command("migrate", interactive=False, verbosity=0)


def tearDownModule():
    connections.close_all()


class LocalClient(Client):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("HTTP_HOST", "localhost")
        super().__init__(*args, **kwargs)

    def force_login(self, user, backend=None):
        super().force_login(user, backend=backend)
        member = Membership.objects.filter(user_id=user.pk).first()
        if member and (member.role == "admin" or member.can_approve_pilots or TOTPDevice.objects.filter(user=user, confirmed=True).exists()):
            complete_mfa(self, user)


def device_code(device):
    at = max(time.time(), device.t0 + (device.last_t + 1) * device.step)
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = at
    return str(totp.token()).zfill(device.digits), at


def security_post(client, path, values):
    page = client.get(path)
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())
    if match is None:
        raise AssertionError("Synthetic security form did not provide a CSRF token.")
    return client.post(path, dict(values, csrfmiddlewaretoken=match.group(1)))


def complete_mfa(client, user):
    """Existing privileged browser fixtures now provide actual MFA proof, never bypass it."""
    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    if device is None:
        response = security_post(client, "/security/mfa/setup/", {"confirm_password": PASSWORD})
        if response.status_code != 200:
            raise AssertionError("Synthetic MFA enrollment did not succeed: " + str(response.status_code))
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        code, at = device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = security_post(client, "/security/mfa/confirm/", {"code": code})
        if response.status_code != 200 or not TOTPDevice.objects.filter(user=user, confirmed=True).exists():
            raise AssertionError("Synthetic MFA confirmation failed.")
    else:
        code, at = device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = security_post(client, "/security/mfa/verify/", {"code": code})
        if response.status_code != 302:
            raise AssertionError("Synthetic MFA verification failed.")


class CompanyAccountTests(TestCase):
    client_class = LocalClient

    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        self.company = bootstrap_company("owner", PASSWORD, "Synthetic company", self.policy.to_dict(), ["synthetic-repository"])
        self.owner = get_user_model().objects.get(username="owner")

    def revision(self):
        return Company.objects.get(pk=1).revision

    def invite(self, username="junior", role="junior", participating=True, manage=False, approve=False,
               user=None, password=PASSWORD, expires=None, revision=None):
        return create_invitation(user or self.owner, password, username, role, participating, manage, approve,
                                 expires or timezone.now() + timedelta(hours=1), revision or self.revision(),
                                 reason="Synthetic invitation test")

    def enroll(self, username="junior", role="junior", participating=True, manage=False, approve=False):
        invitation, value = self.invite(username, role, participating, manage, approve)
        user = accept_invitation(value, PASSWORD)
        return user, invitation, value

    def change(self, user, role=None, active=True, participating=None, manage=None, approve=None):
        member = current_member(user)
        return update_member(self.owner, PASSWORD, user.pk, role or member.role, active,
                             member.participating if participating is None else participating,
                             member.can_manage_company if manage is None else manage,
                             member.can_approve_pilots if approve is None else approve, self.revision(), reason="Synthetic permission test")

    def test_bootstrap_is_explicit_and_never_grants_pilot_authority_by_default(self):
        member = current_member(self.owner)
        self.assertEqual(member.role, "admin")
        self.assertTrue(member.can_manage_company)
        self.assertFalse(member.can_approve_pilots)
        self.assertFalse(self.owner.is_staff)
        self.assertFalse(self.owner.is_superuser)
        with self.assertRaises(PermissionDenied):
            current_member(self.owner, "approve")
        self.assertEqual(CompanyEvent.objects.get().revision, 1)

    def test_password_is_actually_hashed_and_checked_by_django(self):
        self.assertNotEqual(self.owner.password, PASSWORD)
        self.assertTrue(self.owner.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(self.owner.check_password(PASSWORD))
        self.assertFalse(self.owner.check_password("wrong-synthetic-value"))
        self.assertEqual(checked_login(None, "owner", PASSWORD).pk, self.owner.pk)

    def test_bootstrap_cannot_replace_existing_accounts_company_or_history(self):
        before = list(CompanyEvent.objects.values())
        with self.assertRaises(ValidationError):
            bootstrap_company("replacement", PASSWORD, "Other company", self.policy.to_dict(), ["other-repo"])
        self.assertEqual(list(CompanyEvent.objects.values()), before)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Company.objects.get().name, "Synthetic company")

    def test_invitation_is_named_expiring_and_only_its_digest_is_stored(self):
        invitation, value = self.invite()
        self.assertEqual(len(value), 43)
        self.assertEqual(invitation.digest, hashlib.sha256(value.encode("ascii")).hexdigest())
        self.assertEqual(invitation.username, "junior")
        self.assertGreater(invitation.expires_at, timezone.now())
        self.assertNotIn(value, json.dumps(list(CompanyEvent.objects.values("details"))))
        self.assertNotIn(PASSWORD, json.dumps(list(CompanyEvent.objects.values("details"))))

    def test_no_company_email_domain_or_external_identity_provider_is_required(self):
        user, _, _ = self.enroll()
        self.assertEqual(user.email, "")
        self.assertEqual(current_member(user).role, "junior")
        self.assertEqual(checked_login(None, "junior", PASSWORD).pk, user.pk)

    def test_invitation_cannot_be_used_twice_or_reset_a_password(self):
        user, invitation, value = self.enroll()
        before = user.password
        with self.assertRaises(ValidationError):
            accept_invitation(value, "different-synthetic-password-" + "T7!" * 8)
        invitation.refresh_from_db()
        user.refresh_from_db()
        self.assertIsNotNone(invitation.consumed_at)
        self.assertEqual(user.password, before)
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_expired_revoked_and_unknown_invitations_never_enroll_accounts(self):
        invitation, value = self.invite()
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=("expires_at",))
        with self.assertRaises(ValidationError):
            accept_invitation(value, PASSWORD)
        invitation, value = self.invite("another-junior")
        revoke_invitation(self.owner, PASSWORD, invitation.invitation_id, self.revision(), reason="Synthetic revocation test")
        for supplied in (value, "invalid", "A" * 43):
            with self.subTest(supplied_kind=len(supplied)):
                with self.assertRaises(ValidationError):
                    accept_invitation(supplied, PASSWORD)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_weak_password_cannot_consume_invitation_or_create_account(self):
        invitation, value = self.invite()
        with self.assertRaises(DjangoValidationError):
            accept_invitation(value, "short")
        invitation.refresh_from_db()
        self.assertIsNone(invitation.consumed_at)
        self.assertFalse(get_user_model().objects.filter(username="junior").exists())

    def test_duplicate_pending_and_existing_account_names_are_refused(self):
        self.invite()
        for name in ("junior", "owner"):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    self.invite(name)
        self.assertEqual(Invitation.objects.count(), 1)

    def test_seniority_alone_grants_neither_administration_nor_pilot_approval(self):
        senior, _, _ = self.enroll("senior", "senior")
        for permission in ("manage", "approve"):
            with self.subTest(permission=permission):
                with self.assertRaises(PermissionDenied):
                    current_member(senior, permission)
        with self.assertRaises(PermissionDenied):
            self.invite("other-user", user=senior)

    def test_designation_is_separate_and_revocation_is_checked_on_current_state(self):
        senior, _, _ = self.enroll("senior", "senior", approve=True)
        self.assertEqual(current_member(senior, "approve").user_id, senior.pk)
        self.change(senior, approve=False)
        with self.assertRaises(PermissionDenied):
            current_member(senior, "approve")
        self.assertEqual(CompanyEvent.objects.last().details["before"]["can_approve_pilots"], True)
        self.assertEqual(CompanyEvent.objects.last().details["after"]["can_approve_pilots"], False)

    def test_junior_cannot_be_assigned_admin_or_pilot_approval_flags(self):
        for manage, approve in ((True, False), (False, True)):
            with self.subTest(manage=manage, approve=approve):
                with self.assertRaises(ValidationError):
                    self.invite(manage=manage, approve=approve)
        self.assertEqual(Invitation.objects.count(), 0)

    def test_existing_browser_session_loses_access_when_member_is_disabled(self):
        junior, _, _ = self.enroll()
        client = LocalClient()
        client.force_login(junior)
        self.assertEqual(client.get("/").status_code, 200)
        self.change(junior, active=False)
        self.assertEqual(client.get("/").status_code, 403)
        self.assertIsNone(checked_login(None, "junior", PASSWORD))
        self.assertTrue(get_user_model().objects.filter(pk=junior.pk).exists())

    def test_stale_user_object_cannot_bypass_current_user_disabling(self):
        self.owner.is_active = False
        self.owner.save(update_fields=("is_active",))
        stale = get_user_model()(pk=self.owner.pk, username="owner", is_active=True)
        with self.assertRaises(PermissionDenied):
            current_member(stale, "manage")

    def test_uninvited_user_and_framework_superuser_have_no_company_authority(self):
        outsider = get_user_model().objects.create_user(username="outsider", password=PASSWORD, is_staff=True, is_superuser=True)
        for user in (AnonymousUser(), outsider, None):
            with self.subTest(kind=type(user).__name__):
                with self.assertRaises(PermissionDenied):
                    current_member(user, "manage")

    def test_sensitive_changes_require_fresh_password_and_failures_are_retained(self):
        with self.assertRaises(PermissionDenied):
            self.invite(password="wrong-synthetic-value")
        self.assertEqual(Invitation.objects.count(), 0)
        self.assertEqual(LoginAttempt.objects.filter(result="failed").count(), 1)
        self.assertEqual(self.revision(), 1)

    def test_login_attempt_limit_blocks_correct_password_until_window_passes(self):
        for _ in range(LOGIN_FAILURE_LIMIT):
            self.assertIsNone(checked_login(None, "owner", "wrong-synthetic-value"))
        with patch("engine.company.services.authenticate", side_effect=AssertionError("Blocked attempts must not verify more passwords")):
            self.assertIsNone(checked_login(None, "owner", PASSWORD))
        self.assertEqual(LoginAttempt.objects.filter(result="failed").count(), LOGIN_FAILURE_LIMIT)
        later = timezone.now() + LOGIN_FAILURE_WINDOW + timedelta(seconds=1)
        with patch("engine.company.services.timezone.now", return_value=later):
            self.assertEqual(checked_login(None, "owner", PASSWORD).pk, self.owner.pk)

    def test_failed_admin_reauthentication_cannot_evade_limit_by_transaction_rollback(self):
        for _ in range(LOGIN_FAILURE_LIMIT):
            with self.assertRaises(PermissionDenied):
                self.invite(password="wrong-synthetic-value")
        with self.assertRaises(PermissionDenied):
            self.invite(password=PASSWORD)
        self.assertEqual(LoginAttempt.objects.filter(result="failed").count(), LOGIN_FAILURE_LIMIT)
        self.assertEqual(Invitation.objects.count(), 0)

    def test_unknown_and_disabled_users_receive_the_same_generic_login_response(self):
        user, _, _ = self.enroll()
        self.change(user, active=False)
        responses = [self.client.post("/login/", {"username": username, "password": PASSWORD}) for username in ("missing", "junior")]
        for response in responses:
            self.assertContains(response, "Login failed.")
            self.assertNotContains(response, PASSWORD)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_pending_privileged_invitation_dies_when_its_issuing_admin_is_revoked(self):
        admin, _, _ = self.enroll("other-admin", "admin", participating=False, manage=True)
        invitation, value = self.invite("pending-senior", "senior", approve=True)
        update_member(admin, PASSWORD, self.owner.pk, "admin", False, False, False, False, self.revision(), reason="Synthetic admin revocation")
        with self.assertRaises(PermissionDenied):
            accept_invitation(value, PASSWORD)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.consumed_at)
        self.assertFalse(get_user_model().objects.filter(username="pending-senior").exists())

    def test_stale_revision_cannot_overwrite_newer_configuration_or_members(self):
        previous = self.revision()
        self.invite()
        with self.assertRaises(ValidationError):
            self.invite("another-user", revision=previous)
        with self.assertRaises(ValidationError):
            update_company(self.owner, PASSWORD, "Changed", self.policy.to_dict(), ["other-repo"], list(COLLECTION_FIELDS), True, previous,
                           reason="Synthetic stale change")
        self.assertEqual(Invitation.objects.count(), 1)
        self.assertEqual(Company.objects.get().name, "Synthetic company")

    def test_last_active_administrator_cannot_remove_their_only_access_path(self):
        with self.assertRaises(ValidationError):
            self.change(self.owner, active=False, manage=False)
        self.assertTrue(current_member(self.owner, "manage").active)

    def test_configuration_reuses_existing_policy_and_canonical_metadata_order(self):
        fields = list(reversed(COLLECTION_FIELDS))
        update_company(self.owner, PASSWORD, "Updated company", self.policy.to_dict(), ["another-repository"], fields, True, self.revision(),
                       reason="Synthetic scope change")
        company = Company.objects.get()
        self.assertEqual(company.policy, self.policy.to_dict())
        self.assertEqual(company.collection_fields, list(COLLECTION_FIELDS))
        self.assertEqual(company.repository_refs, ["another-repository"])
        self.assertEqual(CompanyEvent.objects.last().details["before"]["repository_refs"], ["synthetic-repository"])

    def test_unapproved_default_raw_collection_and_wildcard_scope_are_rejected(self):
        policy = self.policy.to_dict()
        policy["models"][-1]["approved"] = False
        changes = (
            (policy, ["synthetic-repository"], list(COLLECTION_FIELDS), True),
            (self.policy.to_dict(), ["*"], list(COLLECTION_FIELDS), True),
            (self.policy.to_dict(), ["synthetic-repository"], list(COLLECTION_FIELDS) + ["prompt"], True),
            (self.policy.to_dict(), ["synthetic-repository"], list(COLLECTION_FIELDS), False),
        )
        for values in changes:
            with self.subTest(scope_kind=values[1]):
                with self.assertRaises(ValidationError):
                    update_company(self.owner, PASSWORD, "Bad configuration", *values, self.revision(), reason="Synthetic invalid change")
        self.assertEqual(self.revision(), 1)

    def test_authenticated_collection_scope_covers_all_participants_not_only_seniors(self):
        junior, _, _ = self.enroll()
        senior, _, _ = self.enroll("senior", "senior")
        team = collection_team(Company.objects.get())
        self.assertEqual(team.members, (("junior", "junior"), ("senior", "senior")))
        for user in (junior, senior):
            self.assertEqual(require_collection(user, "synthetic-repository", user.username).user_id, user.pk)
        with self.assertRaises(PermissionDenied):
            require_collection(junior, "synthetic-repository", "senior")
        with self.assertRaises(PermissionDenied):
            require_collection(senior, "another-repository", "senior")

    def test_role_changes_do_not_rewrite_existing_feedback_or_grant_it_authenticated_provenance(self):
        ledger = import_scenario(parse_json((FIXTURES / "feedback-demo.json").read_text()), self.policy)
        before = ledger.to_dict()
        junior, _, _ = self.enroll()
        self.change(junior, role="senior")
        self.assertEqual(ledger.to_dict(), before)
        self.assertEqual(ledger.team.role("synthetic-junior"), "junior")
        event = CompanyEvent.objects.last()
        self.assertEqual(event.details["before"]["role"], "junior")
        self.assertEqual(event.details["after"]["role"], "senior")

    def test_unknown_permissions_fail_closed(self):
        with self.assertRaises(PermissionDenied):
            current_member(self.owner, "grant_live_routing")

    def test_actual_login_invitation_enrollment_and_second_account_flow(self):
        with patch("socket.socket", side_effect=AssertionError("No external network allowed")), patch("subprocess.run", side_effect=AssertionError("No model/client execution allowed")):
            response = self.client.post("/login/", {"username": "owner", "password": PASSWORD})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.session["_auth_user_id"], str(self.owner.pk))
            complete_mfa(self.client, self.owner)
            response = self.client.post("/invitations/", {
                "expected_revision": self.revision(), "confirm_password": PASSWORD, "username": "junior",
                "reason": "Invite a synthetic junior account",
                "role": "junior", "participating": "on", "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            })
            self.assertContains(response, "Private invitation for junior")
            match = re.search(r"<pre>([A-Za-z0-9_-]{43})</pre>", response.content.decode())
            self.assertIsNotNone(match)
            invitation_value = match.group(1)
            other = LocalClient()
            response = other.post("/join/", {"invitation": invitation_value, "password1": PASSWORD, "password2": PASSWORD})
            self.assertEqual(response.status_code, 302)
            self.assertNotIn("_auth_user_id", other.session)
            response = other.post("/login/", {"username": "junior", "password": PASSWORD})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(other.get("/").status_code, 200)
            self.assertEqual(other.get("/configuration/").status_code, 403)
            self.assertEqual(other.get("/invitations/").status_code, 403)
            self.assertEqual(other.get("/history/").status_code, 403)
            self.assertEqual(self.client.get("/history/").status_code, 200)

    def test_unauthenticated_users_cannot_inspect_company_configuration_or_accounts(self):
        for path in ("/", "/members/", "/configuration/", "/history/", "/invitations/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], "/login/")

    def test_guest_cannot_choose_role_username_or_permissions_while_joining(self):
        invitation, value = self.invite()
        response = self.client.post("/join/", {"invitation": value, "password1": PASSWORD, "password2": PASSWORD,
                                              "role": "admin", "username": "owner", "can_approve_pilots": "on"})
        self.assertContains(response, "Unexpected form fields")
        invitation.refresh_from_db()
        self.assertIsNone(invitation.consumed_at)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_spoofed_reviewer_header_and_role_body_cannot_grant_admin_access(self):
        junior, _, _ = self.enroll()
        self.client.force_login(junior)
        response = self.client.post("/configuration/", {"reviewer_id": "owner", "role": "admin"}, HTTP_X_USER="owner")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(current_member(junior).role, "junior")

    def test_csrf_protection_applies_to_login_join_and_sensitive_admin_changes(self):
        client = LocalClient(enforce_csrf_checks=True)
        for path in ("/login/", "/join/"):
            response = client.post(path, {"username": "owner", "password": PASSWORD})
            self.assertEqual(response.status_code, 403)
        client.force_login(self.owner)
        self.assertEqual(client.post("/configuration/", {"confirm_password": PASSWORD}).status_code, 403)
        page = client.get("/configuration/")
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
        response = client.post("/configuration/", {
            "csrfmiddlewaretoken": csrf, "expected_revision": self.revision(), "confirm_password": PASSWORD,
            "reason": "Synthetic CSRF-protected configuration change",
            "name": "Real protected form", "policy_json": json.dumps(self.policy.to_dict()),
            "repositories": "synthetic-repository", "collection_fields": list(COLLECTION_FIELDS), "company_api_attested": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Company.objects.get().name, "Real protected form")

    def test_sensitive_values_are_not_echoed_after_failed_forms(self):
        _, value = self.invite()
        response = self.client.post("/join/", {"invitation": value, "password1": PASSWORD, "password2": "mismatch"})
        self.assertNotContains(response, value)
        self.assertNotContains(response, PASSWORD)
        self.client.force_login(self.owner)
        suspect = "sk-" + "A" * 32
        policy = self.policy.to_dict()
        policy["rules"][0]["evidence_refs"] = [suspect]
        response = self.client.post("/configuration/", {
            "expected_revision": self.revision(), "confirm_password": PASSWORD, "name": "Unsafe",
            "reason": "Synthetic rejected unsafe metadata",
            "policy_json": json.dumps(policy), "repositories": "synthetic-repository",
            "collection_fields": list(COLLECTION_FIELDS), "company_api_attested": "on",
        })
        self.assertNotContains(response, suspect)
        self.assertNotContains(response, PASSWORD)
        self.assertEqual(Company.objects.get().name, "Synthetic company")

    def test_browser_responses_prevent_caching_framing_and_referrer_leaks(self):
        response = self.client.get("/login/")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIn("form-action 'self'", response["Content-Security-Policy"])

    def test_no_public_registration_model_endpoint_or_live_pilot_bypass_exists(self):
        self.client.force_login(self.owner)
        for path in ("/register/", "/admin/", "/pilot/approve/", "/model/request/"):
            self.assertEqual(self.client.post(path, {"approved": True}).status_code, 404)
        self.assertContains(self.client.get("/"), "does not collect live tasks")

    def test_logout_requires_post_and_invalidates_the_login_session(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/logout/").status_code, 405)
        self.assertEqual(self.client.post("/logout/").status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_migration_state_matches_the_actual_models(self):
        with redirect_stdout(io.StringIO()) as output:
            call_command("makemigrations", "company", check=True, dry_run=True, verbosity=1)
        self.assertIn("No changes detected", output.getvalue())

    def test_permission_is_rechecked_after_password_verification_before_state_change(self):
        original = checked_login

        def revoke_after_login(*args, **kwargs):
            user = original(*args, **kwargs)
            Membership.objects.filter(user=self.owner).update(can_manage_company=False)
            return user

        with patch("engine.company.services.checked_login", side_effect=revoke_after_login):
            with self.assertRaises(PermissionDenied):
                self.invite()
        self.assertEqual(Invitation.objects.count(), 0)
        self.assertEqual(self.revision(), 1)

    def test_suspected_secrets_in_incomplete_or_invalid_forms_are_not_redisplayed(self):
        self.client.force_login(self.owner)
        suspect = "sk-" + "a" * 32
        response = self.client.post("/invitations/", {
            "expected_revision": self.revision(), "confirm_password": PASSWORD, "reason": "Synthetic unsafe input",
            "username": suspect, "role": "junior", "participating": "on",
            "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
        })
        self.assertNotContains(response, suspect)
        policy = self.policy.to_dict()
        policy["rules"][0]["evidence_refs"] = [suspect]
        response = self.client.post("/configuration/", {"policy_json": json.dumps(policy)})
        self.assertNotContains(response, suspect)
        self.assertEqual(self.revision(), 1)


class CompanyTaskTests(TestCase):
    client_class = LocalClient

    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        bootstrap_company("owner", PASSWORD, "Synthetic company", self.policy.to_dict(), ["synthetic-repository"])
        self.owner = get_user_model().objects.get(username="owner")
        self.junior = self.enroll("junior", "junior")
        self.senior = self.enroll("senior", "senior")

    def enroll(self, name, role):
        _, value = create_invitation(self.owner, PASSWORD, name, role, True, False, False,
                                     timezone.now() + timedelta(hours=1), Company.objects.get().revision, reason="Synthetic workflow participant")
        return accept_invitation(value, PASSWORD)

    def source(self, **updates):
        return {"repository_ref": "synthetic-repository", "source_kind": "synthetic", "boundary": "new_task",
                "task_id": "documentation-task", "session_id": "manual-session", "task_type": "documentation",
                "risk_tags": ["low"], "selected_model": "fixture/premium", "required_tools": ["read"], "context_tokens": 2000, **updates}

    def result(self, **updates):
        return {"desired_result": True, "tests_passed": None, "score": None, "cost_usd": "0.006",
                "latency_ms": 200, "evidence_ref": "synthetic-confirmation", "supersedes": None, **updates}

    def change(self, user, **updates):
        member = current_member(user)
        values = {"role": member.role, "active": member.active, "participating": member.participating,
                  "manage": member.can_manage_company, "approve": member.can_approve_pilots, **updates}
        update_member(self.owner, PASSWORD, user.pk, values["role"], values["active"], values["participating"],
                      values["manage"], values["approve"], Company.objects.get().revision, reason="Synthetic workflow role change")

    def executed(self, user=None, actual="fixture/cheap", **source):
        user = user or self.junior
        task = recommend_task(user, self.source(**source))
        record_response(user, task.reference, "accept", task.revision)
        task.refresh_from_db()
        return record_execution(user, task.reference, actual, task.revision)

    def test_manual_recommendation_uses_existing_engine_and_preserves_selected_model(self):
        with patch("socket.socket", side_effect=AssertionError("No network allowed")), patch("subprocess.run", side_effect=AssertionError("No model/client execution allowed")):
            task = recommend_task(self.junior, self.source())
            rec = task_ledger(task).recommendations[0]
        self.assertEqual(rec.decision["recommended_model"], "fixture/cheap")
        self.assertEqual(rec.decision["effective_model"], "fixture/premium")
        self.assertEqual(rec.decision["enforcement"], "shadow")
        self.assertEqual(rec.task.developer_id, "junior")
        self.assertEqual(task.events.get().actor_id, self.junior.pk)

    def test_complete_authenticated_response_actual_model_and_delayed_result_are_linked(self):
        task = self.executed()
        record_result(self.senior, task.reference, self.result(), task.revision)
        detail = task_detail(self.owner, task.reference)
        ledger = detail["ledger"]
        self.assertEqual(ledger.responses[0].recommendation_id, ledger.recommendations[0].recommendation_id)
        self.assertEqual(ledger.executions[0].recommendation_id, ledger.recommendations[0].recommendation_id)
        self.assertEqual(ledger.results[0].execution_id, ledger.executions[0].execution_id)
        self.assertEqual(ledger.results[0].reviewer_id, "senior")
        self.assertEqual(detail["summary"]["tasks"][0]["result_status"], "success")
        self.assertEqual([event.actor_snapshot["role"] for event in detail["events"]], ["junior", "junior", "junior", "senior"])
        self.assertFalse(detail["summary"]["deployment_authorized"])

    def test_acceptance_without_actual_use_and_outcome_is_not_success(self):
        task = recommend_task(self.senior, self.source())
        record_response(self.senior, task.reference, "accept", task.revision)
        report = company_feedback(self.owner)["summary"]
        self.assertEqual(report["groups"][0]["accepted_without_execution"], 1)
        self.assertEqual(report["groups"][0]["confirmed_successes"], 0)
        self.assertEqual(report["pending_executions"], 1)

    def test_actual_model_mismatch_receives_its_result_not_the_suggested_model(self):
        task = self.executed(self.senior, actual="fixture/premium")
        record_result(self.senior, task.reference, self.result(), task.revision)
        groups = {row["model"]: row for row in company_feedback(self.owner)["summary"]["groups"]}
        self.assertEqual(groups["fixture/cheap"]["confirmed_successes"], 0)
        self.assertEqual(groups["fixture/cheap"]["accepted_but_different_model"], 1)
        self.assertEqual(groups["fixture/premium"]["confirmed_successes"], 1)

    def test_unknown_results_and_measurements_remain_unknown(self):
        task = self.executed()
        unknown = self.result(desired_result=None, tests_passed=None, score=None, cost_usd=None, latency_ms=None, evidence_ref=None)
        record_result(self.junior, task.reference, unknown, task.revision)
        row = task_detail(self.junior, task.reference)["summary"]["tasks"][0]
        self.assertEqual(row["result_status"], "unknown")
        self.assertIsNone(row["cost_usd"])
        self.assertIsNone(row["tests_passed"])

    def test_senior_success_never_hides_junior_failure_or_rejection(self):
        senior_task = self.executed(self.senior, task_id="senior-task")
        record_result(self.senior, senior_task.reference, self.result(), senior_task.revision)
        junior_task = self.executed()
        record_result(self.junior, junior_task.reference, self.result(desired_result=False, tests_passed=False), junior_task.revision)
        rejected = recommend_task(self.senior, self.source(task_id="rejected-task"))
        record_response(self.senior, rejected.reference, "reject", rejected.revision)
        group = company_feedback(self.owner)["summary"]["groups"][0]
        self.assertEqual(group["senior_adopted_successes"], 1)
        self.assertEqual(group["non_senior_failures"], 1)
        self.assertEqual(group["rejects"], 1)
        self.assertEqual(group["status"], "investigate_failures")

    def test_developer_cannot_read_or_modify_another_developers_task(self):
        task = recommend_task(self.senior, self.source())
        for operation in (
            lambda: get_task(self.junior, task.reference),
            lambda: record_response(self.junior, task.reference, "accept", 1),
            lambda: record_execution(self.junior, task.reference, "fixture/cheap", 1),
            lambda: record_result(self.junior, task.reference, self.result(), 1),
        ):
            with self.assertRaises(PermissionDenied):
                operation()
        self.assertEqual(task.events.count(), 1)
        self.assertEqual(list(visible_tasks(self.junior)), [])

    def test_senior_can_review_but_cannot_accept_or_claim_actual_model_for_a_junior(self):
        task = self.executed()
        self.assertEqual(get_task(self.senior, task.reference).pk, task.pk)
        with self.assertRaises(PermissionDenied):
            record_response(self.senior, task.reference, "accept", task.revision)
        with self.assertRaises(PermissionDenied):
            record_execution(self.senior, task.reference, "fixture/premium", task.revision)
        record_result(self.senior, task.reference, self.result(), task.revision)
        self.assertEqual(task_detail(self.owner, task.reference)["current_result"].reviewer_id, "senior")

    def test_admin_permission_does_not_invent_an_engineering_reviewer_role(self):
        task = self.executed()
        self.assertEqual(get_task(self.owner, task.reference).pk, task.pk)
        with self.assertRaises(PermissionDenied):
            record_result(self.owner, task.reference, self.result(), task.revision)
        with self.assertRaises(PermissionDenied):
            recommend_task(self.owner, self.source())

    def test_disabled_or_nonparticipating_actor_cannot_keep_writing_with_old_session(self):
        task = recommend_task(self.junior, self.source())
        self.client.force_login(self.junior)
        self.change(self.junior, active=False)
        with self.assertRaises(PermissionDenied):
            record_response(self.junior, task.reference, "accept", 1)
        self.assertEqual(self.client.get("/tasks/").status_code, 403)
        self.assertEqual(task.events.count(), 1)
        self.assertEqual(company_feedback(self.owner)["summary"]["recommendations"], 1)

    def test_removed_owner_collection_scope_blocks_new_reviews_without_deleting_history(self):
        task = self.executed()
        self.change(self.junior, participating=False)
        with self.assertRaises(PermissionDenied):
            record_result(self.senior, task.reference, self.result(), task.revision)
        self.assertEqual(company_feedback(self.owner)["summary"]["pending_results"], 1)

    def test_repository_and_field_scope_are_checked_on_every_write(self):
        with self.assertRaises(PermissionDenied):
            recommend_task(self.junior, self.source(repository_ref="outside-scope"))
        task = recommend_task(self.junior, self.source())
        fields = [field for field in COLLECTION_FIELDS if field != "response"]
        update_company(self.owner, PASSWORD, "Synthetic company", self.policy.to_dict(), ["synthetic-repository"], fields, True,
                       Company.objects.get().revision, reason="Narrow synthetic metadata collection")
        with self.assertRaises(PermissionDenied):
            record_response(self.junior, task.reference, "accept", 1)
        self.assertEqual(task.events.count(), 1)

    def test_removed_repository_stops_collection_and_personal_reads_but_admin_history_remains(self):
        task = recommend_task(self.junior, self.source())
        update_company(self.owner, PASSWORD, "Synthetic company", self.policy.to_dict(), ["other-repository"], list(COLLECTION_FIELDS), True,
                       Company.objects.get().revision, reason="End collection scope")
        with self.assertRaises(PermissionDenied):
            get_task(self.junior, task.reference)
        with self.assertRaises(PermissionDenied):
            record_response(self.junior, task.reference, "accept", 1)
        self.assertEqual(get_task(self.owner, task.reference).pk, task.pk)

    def test_unknown_high_risk_or_incompatible_tasks_use_existing_safe_behavior(self):
        for number, update in enumerate(({"risk_tags": []}, {"risk_tags": ["high"]}, {"task_type": None}, {"context_tokens": None})):
            task = recommend_task(self.junior, self.source(task_id="unsafe-" + str(number), **update))
            decision = task_ledger(task).recommendations[0].decision
            self.assertTrue(decision["used_fallback"])
            self.assertEqual(decision["effective_model"], "fixture/premium")
            if update.get("context_tokens", 1) is None:
                self.assertIsNone(decision["recommended_model"])

    def test_continuation_and_unexpected_identity_time_or_raw_content_fields_are_refused(self):
        for field, value in (("boundary", "continuation"), ("developer_id", "senior"), ("timestamp", "2026-10-03T00:00:00Z"),
                             ("role", "senior"), ("prompt", "not permitted"), ("policy", self.policy.to_dict())):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    recommend_task(self.junior, self.source(**{field: value}))
        self.assertEqual(CompanyTask.objects.count(), 0)

    def test_exact_retries_do_not_add_recommendations_or_feedback_events(self):
        task = recommend_task(self.junior, self.source())
        self.assertEqual(recommend_task(self.junior, self.source()).reference, task.reference)
        record_response(self.junior, task.reference, "accept", 1)
        record_response(self.junior, task.reference, "accept", 1)
        task.refresh_from_db()
        record_execution(self.junior, task.reference, "fixture/cheap", task.revision)
        record_execution(self.junior, task.reference, "fixture/cheap", task.revision)
        task.refresh_from_db()
        record_result(self.junior, task.reference, self.result(), task.revision)
        record_result(self.junior, task.reference, self.result(), task.revision)
        task.refresh_from_db()
        self.assertEqual(task.revision, 4)
        self.assertEqual(task.events.count(), 4)

    def test_task_metadata_response_and_actual_model_cannot_be_overwritten(self):
        task = self.executed()
        for operation in (
            lambda: recommend_task(self.junior, self.source(task_type="test_generation")),
            lambda: record_response(self.junior, task.reference, "reject", task.revision),
            lambda: record_execution(self.junior, task.reference, "fixture/premium", task.revision),
        ):
            with self.assertRaises(ValidationError):
                operation()
        self.assertEqual(task.events.count(), 3)

    def test_same_task_and_session_labels_from_two_developers_are_namespaced(self):
        junior = recommend_task(self.junior, self.source())
        senior = recommend_task(self.senior, self.source())
        self.assertNotEqual(task_ledger(junior).recommendations[0].task.session_id, task_ledger(senior).recommendations[0].task.session_id)
        self.assertEqual(company_feedback(self.owner)["summary"]["recommendations"], 2)

    def test_post_execution_acceptance_is_refused_and_missing_response_stays_unknown(self):
        task = recommend_task(self.junior, self.source())
        task = record_execution(self.junior, task.reference, "fixture/cheap", 1)
        with self.assertRaises(ValidationError):
            record_response(self.junior, task.reference, "accept", task.revision)
        row = task_detail(self.owner, task.reference)["summary"]["tasks"][0]
        self.assertIsNone(row["response"])

    def test_result_requires_actual_model_consistent_quality_and_evidence(self):
        task = recommend_task(self.junior, self.source())
        with self.assertRaises(ValidationError):
            record_result(self.junior, task.reference, self.result(), task.revision)
        task = record_execution(self.junior, task.reference, "fixture/cheap", task.revision)
        for update in ({"evidence_ref": None}, {"tests_passed": False}, {"score": "1.1"}, {"cost_usd": "-1"}, {"latency_ms": -1}):
            with self.subTest(update=update):
                with self.assertRaises(ValidationError):
                    record_result(self.junior, task.reference, self.result(**update), task.revision)
        self.assertEqual(task.events.count(), 2)

    def test_stale_or_branched_corrections_are_rejected_and_all_revisions_are_retained(self):
        task = self.executed()
        task = record_result(self.junior, task.reference, self.result(), task.revision)
        previous = task_ledger(task).results[-1]
        correction = self.result(desired_result=False, tests_passed=False, supersedes=previous.result_id)
        task = record_result(self.junior, task.reference, correction, task.revision)
        record_result(self.junior, task.reference, correction, task.revision - 1)
        with self.assertRaises(ValidationError):
            record_result(self.junior, task.reference, self.result(score="0.4", supersedes=previous.result_id), task.revision)
        ledger = task_ledger(task)
        self.assertEqual(len(ledger.results), 2)
        self.assertTrue(ledger.results[0].desired_result)
        self.assertFalse(ledger.results[1].desired_result)
        self.assertEqual(task_detail(self.owner, task.reference)["summary"]["tasks"][0]["result_status"], "failure")

    def test_another_reviewers_result_cannot_be_replaced_without_agreed_disagreement_rules(self):
        task = self.executed()
        task = record_result(self.senior, task.reference, self.result(desired_result=False), task.revision)
        previous = task_ledger(task).results[-1]
        with self.assertRaises(PermissionDenied):
            record_result(self.junior, task.reference, self.result(supersedes=previous.result_id), task.revision)
        self.assertEqual(len(task_ledger(task).results), 1)

    def test_promotion_does_not_relabel_old_task_or_response_as_senior_evidence(self):
        old = self.executed()
        record_result(self.junior, old.reference, self.result(), old.revision)
        self.change(self.junior, role="senior")
        new = self.executed(self.junior, task_id="after-promotion")
        record_result(self.junior, new.reference, self.result(), new.revision)
        report = company_feedback(self.owner)["summary"]
        self.assertEqual(report["groups"][0]["senior_adopted_successes"], 1)
        self.assertEqual(report["groups"][0]["confirmed_successes"], 2)
        old.refresh_from_db()
        self.assertEqual(task_ledger(old).record_role("recommendation", task_ledger(old).recommendations[0].recommendation_id, "junior"), "junior")

    def test_old_policy_snapshots_survive_updates_and_same_version_changes_are_refused(self):
        task = recommend_task(self.junior, self.source())
        old = copy.deepcopy(task.policy_snapshot)
        policy = self.policy.to_dict()
        policy["rules"] = []
        with self.assertRaises(ValidationError):
            update_company(self.owner, PASSWORD, "Synthetic company", policy, ["synthetic-repository"], list(COLLECTION_FIELDS), True,
                           Company.objects.get().revision, reason="Changed rule without version")
        policy["policy_version"] = "new-synthetic-version"
        update_company(self.owner, PASSWORD, "Synthetic company", policy, ["synthetic-repository"], list(COLLECTION_FIELDS), True,
                       Company.objects.get().revision, reason="New versioned rules")
        task.refresh_from_db()
        self.assertEqual(task.policy_snapshot, old)
        self.assertEqual(recommend_task(self.junior, self.source()).reference, task.reference)

    def test_unapproved_reported_actual_model_is_retained_but_never_authorized(self):
        task = self.executed(actual="unapproved/observed-model")
        record_result(self.junior, task.reference, self.result(desired_result=False), task.revision)
        group = next(row for row in company_feedback(self.owner)["summary"]["groups"] if row["model"] == "unapproved/observed-model")
        self.assertEqual(group["incompatible_executions"], 1)
        self.assertEqual(group["confirmed_failures"], 1)
        self.assertFalse(self.policy.model("fixture/cheap") is None)

    def test_known_secret_values_are_refused_before_any_task_or_result_is_saved(self):
        suspect = "sk-" + "A" * 32
        with self.assertRaises(PrivacyError):
            recommend_task(self.junior, self.source(task_id=suspect))
        self.assertEqual(CompanyTask.objects.count(), 0)
        task = self.executed()
        with self.assertRaises(PrivacyError):
            record_result(self.junior, task.reference, self.result(evidence_ref=suspect), task.revision)
        self.assertEqual(task.events.count(), 3)

    def test_source_counts_and_authenticated_actor_provenance_do_not_certify_outcomes(self):
        recommend_task(self.junior, self.source())
        recommend_task(self.senior, self.source(source_kind="team"))
        report = company_feedback(self.owner)["summary"]
        self.assertEqual(report["source_counts"], {"synthetic": 1, "team": 1})
        self.assertEqual(report["roles_source"], "authenticated_company_event_snapshots")
        self.assertEqual(report["outcome_source"], "authenticated_submitter_manual_outcome_unverified")
        self.assertFalse(report["deployment_authorized"])

    def test_corrupt_or_missing_history_is_refused_without_repair_or_overwrite(self):
        task = self.executed()
        event = task.events.get(kind="execution")
        payload = dict(event.payload, actual_model="modified/observed-model", developer_id="senior")
        event.payload = payload
        event.save(update_fields=("payload",))
        with self.assertRaises(ValidationError):
            record_result(self.junior, task.reference, self.result(), task.revision)
        event.refresh_from_db()
        self.assertEqual(event.payload, payload)
        task.revision += 1
        task.save(update_fields=("revision",))
        with self.assertRaises(ValidationError):
            task_ledger(task)

    def test_interrupted_write_rolls_back_the_event_and_task_revision(self):
        task = recommend_task(self.junior, self.source())
        with patch("engine.company.tasks._append", side_effect=RuntimeError("Synthetic interruption")):
            with self.assertRaises(RuntimeError):
                record_response(self.junior, task.reference, "accept", 1)
        task.refresh_from_db()
        self.assertEqual(task.revision, 1)
        self.assertEqual(task.events.count(), 1)

    def test_real_login_and_browser_forms_complete_the_joined_manual_workflow(self):
        self.client.post("/login/", {"username": "junior", "password": PASSWORD})
        source = self.source()
        source["risk_tags"], source["required_tools"] = "low", "read"
        response = self.client.post("/tasks/new/", source)
        self.assertEqual(response.status_code, 302)
        path = response["Location"]
        task = CompanyTask.objects.get()
        self.assertContains(self.client.get(path), "fixture/cheap")
        self.assertEqual(self.client.post(path + "response/", {"expected_revision": 1, "response": "accept"}).status_code, 302)
        self.assertEqual(self.client.post(path + "execution/", {"expected_revision": 2, "actual_model": "fixture/cheap"}).status_code, 302)
        result = {"expected_revision": 3, "desired_result": "true", "tests_passed": "unknown", "evidence_ref": "synthetic-browser-review"}
        self.assertEqual(self.client.post(path + "result/", result).status_code, 302)
        self.assertContains(self.client.get(path), "synthetic-browser-review")
        self.assertContains(self.client.get("/tasks/"), "current results 1")
        self.assertEqual(task_detail(self.junior, task.reference)["summary"]["current_results"], 1)

    def test_task_forms_reject_role_identity_injection_and_do_not_echo_secrets(self):
        self.client.force_login(self.junior)
        source = self.source()
        source.update(risk_tags="low", required_tools="read", reviewer_id="senior")
        self.assertContains(self.client.post("/tasks/new/", source), "Unexpected form fields")
        self.assertEqual(CompanyTask.objects.count(), 0)
        suspect = "sk-" + "A" * 32
        self.assertNotContains(self.client.post("/tasks/new/", {"task_id": suspect}), suspect)

    def test_csrf_and_record_access_checks_cover_each_task_endpoint(self):
        task = recommend_task(self.senior, self.source())
        client = LocalClient(enforce_csrf_checks=True)
        client.force_login(self.junior)
        self.assertEqual(client.post("/tasks/new/", self.source()).status_code, 403)
        self.assertEqual(self.client.get("/tasks/").status_code, 302)
        self.client.force_login(self.junior)
        path = "/tasks/" + str(task.reference) + "/"
        for suffix in ("", "response/", "execution/", "result/"):
            self.assertEqual(self.client.get(path + suffix).status_code, 403)


class CompanyMFATests(TestCase):
    def setUp(self):
        policy = load_policy(FIXTURES / "policy.json")
        bootstrap_company("owner", PASSWORD, "Synthetic MFA company", policy.to_dict(), ["synthetic-repository"])
        self.owner = get_user_model().objects.get(username="owner")
        self.client = self.plain_client(self.owner)

    def plain_client(self, user):
        client = Client(HTTP_HOST="localhost")
        client.force_login(user)
        return client

    def enroll(self, client=None, user=None):
        client, user = client or self.client, user or self.owner
        response = security_post(client, "/security/mfa/setup/", {"confirm_password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="setup-secret"', response.content.decode())
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        code, at = device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = security_post(client, "/security/mfa/confirm/", {"code": code})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Authenticator confirmed", response.content.decode())
        codes = re.findall(r'<pre class="backup-code">([A-Z2-7]{16})</pre>', response.content.decode())
        self.assertEqual(len(codes), 8)
        device.refresh_from_db()
        return device, codes, code, at

    def verify(self, client, device):
        device.refresh_from_db()
        code, at = device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = security_post(client, "/security/mfa/verify/", {"code": code})
        return response, code, at

    def test_password_only_admin_is_restricted_to_enrollment_not_company_controls(self):
        for path in ("/", "/configuration/", "/members/", "/invitations/", "/history/", "/tasks/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], "/security/mfa/setup/")
        self.assertEqual(self.client.get("/security/mfa/setup/").status_code, 200)
        self.assertEqual(TOTPDevice.objects.count(), 0)

    def test_enrollment_requires_fresh_password_and_keeps_failed_attempts(self):
        response = security_post(self.client, "/security/mfa/setup/", {"confirm_password": "wrong-synthetic-password"})
        self.assertContains(response, "Fresh account verification failed")
        self.assertEqual(TOTPDevice.objects.count(), 0)
        self.assertEqual(LoginAttempt.objects.filter(result="failed").count(), 1)

    def test_pending_factor_does_not_grant_mfa_access_or_redisplay_seed(self):
        response = security_post(self.client, "/security/mfa/setup/", {"confirm_password": PASSWORD})
        secret = re.search(r'<pre id="setup-secret">([A-Z2-7]+)</pre>', response.content.decode()).group(1)
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertNotContains(self.client.get("/security/mfa/setup/"), secret)
        self.assertEqual(TOTPDevice.objects.get().confirmed, False)
        response = security_post(self.client, "/security/mfa/setup/", {"confirm_password": PASSWORD})
        self.assertContains(response, "already pending")
        self.assertNotContains(response, secret)

    def test_actual_totp_confirmation_enables_required_privileged_access(self):
        device, codes, _, _ = self.enroll()
        self.assertTrue(device.confirmed)
        self.assertEqual(MFAState.objects.get().generation, 1)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/configuration/").status_code, 200)
        self.assertEqual(StaticToken.objects.count(), len(codes))
        self.assertEqual(len(set(codes)), len(codes))

    def test_totp_code_replay_in_another_login_is_rejected(self):
        device, _, code, at = self.enroll()
        client = self.plain_client(self.owner)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = security_post(client, "/security/mfa/verify/", {"code": code})
        self.assertContains(response, "Code verification failed")
        self.assertNotIn(PROOF_KEY, client.session)
        device.refresh_from_db()
        self.assertEqual(device.throttling_failure_count, 1)

    def test_mfa_failure_counter_and_audit_survive_failed_verification(self):
        device, _, _, _ = self.enroll()
        client = self.plain_client(self.owner)
        response = security_post(client, "/security/mfa/verify/", {"code": "invalid-synthetic-code"})
        self.assertContains(response, "Code verification failed")
        device.refresh_from_db()
        self.assertEqual(device.throttling_failure_count, 1)
        self.assertEqual(SecurityEvent.objects.filter(action="mfa_verify_failed").count(), 1)
        self.assertNotContains(response, "invalid-synthetic-code")

    def test_fresh_unused_totp_code_authenticates_another_browser(self):
        device, _, _, _ = self.enroll()
        other = self.plain_client(self.owner)
        self.assertEqual(other.get("/configuration/")["Location"], "/security/mfa/verify/")
        response, _, _ = self.verify(other, device)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(other.get("/configuration/").status_code, 200)

    def test_expired_future_or_malformed_proofs_do_not_keep_access(self):
        self.enroll()
        original = dict(self.client.session[PROOF_KEY])
        bad = (
            dict(original, at=(timezone.now() - timedelta(minutes=16)).isoformat()),
            dict(original, at=(timezone.now() + timedelta(minutes=1)).isoformat()),
            dict(original, at="not-a-time"),
            dict(original, generation=True),
        )
        for proof in bad:
            with self.subTest(proof_kind=type(proof["at"]).__name__):
                session = self.client.session
                session[PROOF_KEY] = proof
                session.save()
                self.assertEqual(self.client.get("/configuration/")["Location"], "/security/mfa/verify/")

    def test_unconfirmed_or_cross_account_device_cannot_be_used_as_a_proof(self):
        pending = TOTPDevice.objects.create(user=self.owner, confirmed=False)
        state = MFAState.objects.create(user=self.owner)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = pending.persistent_id
        session[PROOF_KEY] = {"account_id": self.owner.pk, "generation": state.generation, "at": timezone.now().isoformat()}
        session.save()
        self.assertEqual(self.client.get("/configuration/").status_code, 302)
        other = get_user_model().objects.create_user(username="uninvited-factor-owner", password=PASSWORD)
        pending.confirmed = True
        pending.user = other
        pending.save(update_fields=("confirmed", "user"))
        self.assertEqual(self.client.get("/configuration/").status_code, 302)

    def test_posted_verified_flags_or_another_device_id_cannot_bypass_challenge(self):
        device, _, _, _ = self.enroll()
        other = self.plain_client(self.owner)
        response = security_post(other, "/security/mfa/verify/", {"code": "000000", "verified": "true", "device_id": device.persistent_id})
        self.assertContains(response, "Unexpected form fields")
        self.assertNotIn(PROOF_KEY, other.session)

    def test_expired_enrollment_cannot_be_confirmed_with_a_valid_code(self):
        security_post(self.client, "/security/mfa/setup/", {"confirm_password": PASSWORD})
        device = TOTPDevice.objects.get(confirmed=False)
        MFAState.objects.filter(user=self.owner).update(pending_since=timezone.now() - timedelta(minutes=16))
        code, at = device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = security_post(self.client, "/security/mfa/confirm/", {"code": code})
        self.assertContains(response, "missing or expired")
        device.refresh_from_db()
        self.assertFalse(device.confirmed)

    def test_pending_enrollment_can_be_cancelled_explicitly_without_changing_business_state(self):
        security_post(self.client, "/security/mfa/setup/", {"confirm_password": PASSWORD})
        before = list(CompanyEvent.objects.values())
        response = security_post(self.client, "/security/mfa/cancel/", {"confirm_password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TOTPDevice.objects.count(), 0)
        self.assertEqual(list(CompanyEvent.objects.values()), before)
        self.assertEqual(SecurityEvent.objects.filter(action="mfa_enrollment_cancel").count(), 1)

    def test_backup_recovery_requires_password_and_never_consumes_code_on_password_failure(self):
        _, codes, _, _ = self.enroll()
        other = self.plain_client(self.owner)
        response = security_post(other, "/security/mfa/recover/", {"confirm_password": "wrong-synthetic-password", "code": codes[0]})
        self.assertContains(response, "Fresh account verification failed")
        self.assertTrue(StaticToken.objects.filter(token=codes[0]).exists())
        self.assertNotIn(RECOVERY_KEY, other.session)

    def test_backup_code_is_single_use_and_grants_only_a_replacement_ticket(self):
        _, codes, _, _ = self.enroll()
        other = self.plain_client(self.owner)
        response = security_post(other, "/security/mfa/recover/", {"confirm_password": PASSWORD, "code": codes[0]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/security/mfa/setup/")
        self.assertFalse(StaticToken.objects.filter(token=codes[0]).exists())
        self.assertIn(RECOVERY_KEY, other.session)
        self.assertNotIn(PROOF_KEY, other.session)
        self.assertEqual(other.get("/configuration/")["Location"], "/security/mfa/verify/")
        response = security_post(other, "/security/mfa/recover/", {"confirm_password": PASSWORD, "code": codes[0]})
        self.assertContains(response, "Backup-code verification failed")
        self.assertNotContains(response, codes[0])

    def test_expired_recovery_ticket_cannot_begin_replacement(self):
        _, codes, _, _ = self.enroll()
        other = self.plain_client(self.owner)
        security_post(other, "/security/mfa/recover/", {"confirm_password": PASSWORD, "code": codes[0]})
        session = other.session
        session[RECOVERY_KEY] = dict(session[RECOVERY_KEY], at=(timezone.now() - timedelta(minutes=6)).isoformat())
        session.save()
        response = security_post(other, "/security/mfa/setup/", {"confirm_password": PASSWORD})
        self.assertContains(response, "requires current MFA")
        self.assertEqual(TOTPDevice.objects.filter(confirmed=False).count(), 0)

    def test_password_only_session_cannot_replace_an_existing_factor(self):
        device, _, _, _ = self.enroll()
        other = self.plain_client(self.owner)
        response = security_post(other, "/security/mfa/setup/", {"confirm_password": PASSWORD})
        self.assertContains(response, "requires current MFA")
        self.assertEqual(TOTPDevice.objects.get().pk, device.pk)

    def test_recovered_replacement_revokes_old_factor_sessions_and_old_backup_codes(self):
        device, codes, _, _ = self.enroll()
        other = self.plain_client(self.owner)
        security_post(other, "/security/mfa/recover/", {"confirm_password": PASSWORD, "code": codes[0]})
        new_device, new_codes, _, _ = self.enroll(other)
        self.assertNotEqual(new_device.pk, device.pk)
        self.assertFalse(TOTPDevice.objects.filter(pk=device.pk).exists())
        self.assertEqual(MFAState.objects.get().generation, 2)
        self.assertEqual(other.get("/configuration/").status_code, 200)
        self.assertEqual(self.client.get("/configuration/")["Location"], "/security/mfa/verify/")
        self.assertNotIn(RECOVERY_KEY, other.session)
        self.assertEqual(set(StaticToken.objects.values_list("token", flat=True)), set(new_codes))
        self.assertEqual(len(new_codes), len(codes))

    def test_generation_revocation_blocks_a_previously_verified_session(self):
        self.enroll()
        MFAState.objects.filter(user=self.owner).update(generation=2)
        self.assertEqual(self.client.get("/configuration/")["Location"], "/security/mfa/verify/")

    def test_factor_verification_does_not_override_disabled_membership(self):
        self.enroll()
        Membership.objects.filter(user=self.owner).update(active=False)
        self.assertEqual(self.client.get("/configuration/").status_code, 403)
        self.assertEqual(self.client.get("/security/mfa/setup/").status_code, 403)

    def test_pilot_approver_must_use_mfa_even_without_admin_permission(self):
        _, value = create_invitation(self.owner, PASSWORD, "designated-senior", "senior", True, False, True,
                                     timezone.now() + timedelta(hours=1), Company.objects.get().revision, reason="Synthetic approver MFA")
        senior = accept_invitation(value, PASSWORD)
        client = self.plain_client(senior)
        self.assertEqual(client.get("/")["Location"], "/security/mfa/setup/")
        self.enroll(client, senior)
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/configuration/").status_code, 403)
        self.assertEqual(client.post("/pilot/approve/", {"approved": True}).status_code, 404)

    def test_nonprivileged_users_can_work_without_mfa_until_they_enroll(self):
        _, value = create_invitation(self.owner, PASSWORD, "junior", "junior", True, False, False,
                                     timezone.now() + timedelta(hours=1), Company.objects.get().revision, reason="Synthetic optional MFA")
        junior = accept_invitation(value, PASSWORD)
        client = self.plain_client(junior)
        self.assertEqual(client.get("/").status_code, 200)
        device, _, _, _ = self.enroll(client, junior)
        other = self.plain_client(junior)
        self.assertEqual(other.get("/tasks/")["Location"], "/security/mfa/verify/")
        self.verify(other, device)
        self.assertEqual(other.get("/tasks/").status_code, 200)

    def test_secrets_and_codes_are_absent_from_business_and_security_audits(self):
        device, codes, _, _ = self.enroll()
        body = json.dumps(list(SecurityEvent.objects.values("details"))) + json.dumps(list(CompanyEvent.objects.values("details")))
        self.assertNotIn(device.key, body)
        self.assertNotIn(PASSWORD, body)
        for code in codes:
            self.assertNotIn(code, body)
        self.assertNotContains(self.client.get("/history/"), device.key)

    def test_mfa_forms_are_csrf_protected_and_codes_are_never_echoed(self):
        client = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
        client.force_login(self.owner)
        for path in ("setup", "confirm", "recover", "cancel"):
            response = client.post("/security/mfa/" + path + "/", {"confirm_password": PASSWORD, "code": "123456"})
            self.assertEqual(response.status_code, 403)
            self.assertNotContains(response, PASSWORD, status_code=403)

    def test_verification_and_recovery_make_no_provider_or_external_authentication_requests(self):
        with patch("socket.socket", side_effect=AssertionError("No external calls allowed")), patch("subprocess.run", side_effect=AssertionError("No model/client process allowed")):
            _, codes, _, _ = self.enroll()
            other = self.plain_client(self.owner)
            response = security_post(other, "/security/mfa/recover/", {"confirm_password": PASSWORD, "code": codes[0]})
        self.assertEqual(response.status_code, 302)

    def test_logout_removes_mfa_and_recovery_session_proofs(self):
        self.enroll()
        self.assertIn(PROOF_KEY, self.client.session)
        self.client.post("/logout/")
        self.assertNotIn(PROOF_KEY, self.client.session)
        self.assertNotIn(RECOVERY_KEY, self.client.session)
        self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)

    def test_browser_business_operations_recheck_mfa_generation_inside_the_transaction(self):
        self.enroll()
        page = self.client.get("/configuration/")
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
        revision = Company.objects.get().revision
        from engine.company.mfa import require_request_mfa
        original = require_request_mfa

        def revoke_then_check(*args, **kwargs):
            MFAState.objects.filter(user=self.owner).update(generation=2)
            return original(*args, **kwargs)

        with patch("engine.company.mfa.require_request_mfa", side_effect=revoke_then_check):
            response = self.client.post("/configuration/", {
                "csrfmiddlewaretoken": csrf, "expected_revision": revision, "confirm_password": PASSWORD,
                "reason": "Synthetic generation revocation", "name": "Should not replace company",
                "policy_json": json.dumps(load_policy(FIXTURES / "policy.json").to_dict()),
                "repositories": "synthetic-repository", "collection_fields": list(COLLECTION_FIELDS), "company_api_attested": "on",
            })
        self.assertContains(response, "Complete current authenticator verification")
        self.assertEqual(Company.objects.get().name, "Synthetic MFA company")
        self.assertEqual(Company.objects.get().revision, revision)

    def test_cross_account_verified_browser_cannot_authorize_another_account_operation(self):
        self.enroll()
        other = get_user_model().objects.create_user(username="another-account", password=PASSWORD)
        request = RequestFactory().post("/configuration/")
        request.user = other
        request.session = self.client.session
        with self.assertRaises(PermissionDenied):
            create_invitation(self.owner, PASSWORD, "must-not-enroll", "junior", True, False, False,
                              timezone.now() + timedelta(hours=1), Company.objects.get().revision,
                              reason="Synthetic cross-account refusal", request=request)
        self.assertEqual(Invitation.objects.count(), 0)

    def test_unverified_request_cannot_access_company_feedback_even_via_service(self):
        request = RequestFactory().get("/tasks/")
        request.user = self.owner
        SessionMiddleware(lambda _: None).process_request(request)
        with self.assertRaises(PermissionDenied):
            company_feedback(self.owner, request=request)


class CompanyControlTests(TestCase):
    def setUp(self):
        self.policy = load_policy(FIXTURES / "policy.json")
        bootstrap_company("owner", PASSWORD, "Synthetic control company", self.policy.to_dict(), ["synthetic-repository"], pilot_approver=True)
        self.owner = get_user_model().objects.get(username="owner")
        self.client = LocalClient()
        self.client.force_login(self.owner)
        self.senior = self.enroll("senior", "senior")
        self.junior = self.enroll("junior", "junior")
        self.owner.refresh_from_db()

    def enroll(self, name, role):
        _, value = create_invitation(self.owner, PASSWORD, name, role, True, False, False,
                                     timezone.now() + timedelta(hours=1), Company.objects.get().revision, reason="Synthetic control test")
        return accept_invitation(value, PASSWORD)

    def request(self):
        request = RequestFactory().post("/company-sensitive-action/")
        request.user = get_user_model().objects.get(pk=self.owner.pk)
        request.user.otp_device = TOTPDevice.objects.get(user=self.owner, confirmed=True)
        request.session = self.client.session
        return request

    def sensitive(self, operation, *args, **kwargs):
        request = self.request()
        code, at = device_code(request.user.otp_device)
        try:
            with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
                return operation(request, PASSWORD, code, *args, **kwargs)
        finally:
            request.session.save()
            self.client.cookies[settings.SESSION_COOKIE_NAME] = request.session.session_key

    def source(self, number=1, **updates):
        return {"repository_ref": "synthetic-repository", "source_kind": "synthetic", "boundary": "new_task",
                "task_id": "docs-" + str(number), "session_id": "session-" + str(number), "task_type": "documentation",
                "risk_tags": ["low"], "selected_model": "fixture/premium", "required_tools": ["read"], "context_tokens": 2000, **updates}

    def evidence(self):
        for number in (1, 2):
            task = recommend_task(self.senior, self.source(number))
            task = record_response(self.senior, task.reference, "accept", task.revision)
            task = record_execution(self.senior, task.reference, "fixture/cheap", task.revision)
            record_result(self.senior, task.reference, {"desired_result": True, "tests_passed": None, "score": None,
                          "cost_usd": "0.006", "latency_ms": 200, "evidence_ref": "synthetic-evidence-" + str(number), "supersedes": None}, task.revision)
        from engine.company.tasks import company_ledger
        ledger = company_ledger(Company.objects.get(), "synthetic")
        plan = {"learner_version": "synthetic-control-v1", "source_kind": "synthetic", "dataset_split": "validation",
                "cutoff": timezone.now().isoformat(), "session_ids": sorted({item.task.session_id for item in ledger.recommendations}),
                "task_types": ["documentation"], "min_senior_successes": 2, "min_senior_sessions": 2}
        return authorization.prepare_review(self.request(), plan)

    def approve(self, review=None, target="simulation", scope=None):
        review = review or self.evidence()
        scope = scope or {"pilot_id": "synthetic-pilot-v1", "repository_ref": "synthetic-repository", "task_types": ["documentation"],
                          "developer_ids": ["junior", "senior"], "max_tasks": 3, "max_cost_usd": "1.00"}
        return self.sensitive(authorization.authorize, review.reference, scope, timezone.now() + timedelta(hours=1),
                              "Explicit synthetic pilot only", Company.objects.get().revision, target)

    def active(self):
        approval = self.approve()
        self.sensitive(authorization.activate, approval.reference, "Activate reviewed simulation")
        return approval

    def developer_request(self, user=None):
        request = RequestFactory().post("/pilots/decide/")
        request.user = user or self.junior
        SessionMiddleware(lambda _: None).process_request(request)
        return request

    def test_personal_password_recovery_is_one_use_and_keeps_mfa_roles_and_history(self):
        value = self.sensitive(recovery.issue_personal)
        grant = RecoveryGrant.objects.get()
        self.assertNotEqual(grant.digest, value)
        before = list(Membership.objects.values())
        events = list(CompanyEvent.objects.values())
        device = TOTPDevice.objects.get(user=self.owner, confirmed=True)
        code, at = device_code(device)
        new_password = "new-synthetic-password-" + "F8!" * 8
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            self.assertTrue(recovery.reset_password("owner", value, new_password, code, "authenticator"))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(new_password))
        self.assertEqual(list(Membership.objects.values()), before)
        self.assertEqual(list(CompanyEvent.objects.values()), events)
        self.assertEqual(TOTPDevice.objects.filter(user=self.owner, confirmed=True).count(), 1)
        self.assertFalse(recovery.reset_password("owner", value, PASSWORD, code, "authenticator"))
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_password_recovery_invalidates_other_outstanding_grants(self):
        personal = self.sensitive(recovery.issue_personal)
        assisted = self.sensitive(recovery.issue_assisted, self.owner.pk, timezone.now() + timedelta(minutes=20),
                                  "Synthetic identity checked", "synthetic-in-person-check")
        device = TOTPDevice.objects.get(user=self.owner, confirmed=True)
        code, at = device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            self.assertTrue(recovery.reset_password("owner", personal, "new-password-" + "S5!" * 8, code, "authenticator"))
        self.assertFalse(recovery.reset_password("owner", assisted, PASSWORD, code, "authenticator"))
        self.assertEqual(RecoveryGrant.objects.filter(consumed_at__isnull=True, revoked_at__isnull=True).count(), 0)

    def test_assisted_recovery_has_expiry_identity_reason_and_no_membership_restoration(self):
        value = self.sensitive(recovery.issue_assisted, self.junior.pk, timezone.now() + timedelta(minutes=20),
                              "Synthetic person confirmed", "synthetic-owner-confirmation")
        self.assertTrue(recovery.reset_password("junior", value, "new-junior-password-" + "S6!" * 8, "", "authenticator"))
        self.assertEqual(current_member(self.junior).role, "junior")
        self.assertFalse(current_member(self.junior).can_approve_pilots)
        audit = SecurityEvent.objects.get(action="password_recovery_grant")
        self.assertEqual(audit.details["identity_confirmation_ref"], "synthetic-owner-confirmation")
        self.assertNotIn(value, json.dumps(audit.details))

    def test_expired_wrong_account_revoked_issuer_and_disabled_target_recovery_are_refused(self):
        value = self.sensitive(recovery.issue_assisted, self.junior.pk, timezone.now() + timedelta(minutes=20), "Synthetic check", "synthetic-check")
        self.assertFalse(recovery.reset_password("senior", value, PASSWORD, "", "authenticator"))
        grant = RecoveryGrant.objects.get()
        grant.expires_at = timezone.now() - timedelta(seconds=1)
        grant.save(update_fields=("expires_at",))
        self.assertFalse(recovery.reset_password("junior", value, PASSWORD, "", "authenticator"))
        grant.expires_at = timezone.now() + timedelta(minutes=20)
        grant.save(update_fields=("expires_at",))
        Membership.objects.filter(user=self.owner).update(can_manage_company=False)
        self.assertFalse(recovery.reset_password("junior", value, PASSWORD, "", "authenticator"))
        Membership.objects.filter(user=self.owner).update(can_manage_company=True)
        Membership.objects.filter(user=self.junior).update(active=False)
        self.assertFalse(recovery.reset_password("junior", value, PASSWORD, "", "authenticator"))

    def test_missing_second_factor_does_not_reset_privileged_account(self):
        value = self.sensitive(recovery.issue_personal)
        before = get_user_model().objects.get(pk=self.owner.pk).password
        self.assertFalse(recovery.reset_password("owner", value, "new-password-" + "T5!" * 8, "bad-code", "authenticator"))
        self.assertEqual(get_user_model().objects.get(pk=self.owner.pk).password, before)
        self.assertEqual(RecoveryGrant.objects.filter(consumed_at__isnull=True).count(), 1)

    def test_removed_authenticator_does_not_downgrade_an_existing_recovery_grant(self):
        value = self.sensitive(recovery.issue_personal)
        before = get_user_model().objects.get(pk=self.owner.pk).password
        TOTPDevice.objects.filter(user=self.owner).delete()
        self.assertFalse(recovery.reset_password("owner", value, "must-not-reset-password-" + "F8!" * 8, "", "authenticator"))
        self.assertEqual(get_user_model().objects.get(pk=self.owner.pk).password, before)
        self.assertTrue(RecoveryGrant.objects.filter(consumed_at__isnull=True, revoked_at__isnull=True).exists())

    def test_recovery_unknown_account_diagnostics_are_generic_and_do_not_create_grants(self):
        response = self.client.post("/security/password/reset/", {"username": "missing", "recovery_credential": "unknown",
                                    "password1": PASSWORD, "password2": PASSWORD, "factor_kind": "authenticator", "code": "000000"})
        self.assertContains(response, "Recovery verification failed")
        self.assertNotContains(response, PASSWORD)
        self.assertEqual(RecoveryGrant.objects.count(), 0)

    def test_company_review_uses_authenticated_all_source_records_and_existing_learner(self):
        review = self.evidence()
        self.assertEqual(review.data["report"]["counts"]["recommendations"], 2)
        self.assertEqual(review.data["report"]["categories"][0]["status"], "ready_for_local_review")
        self.assertFalse(review.data["outcome_truth_verified"])
        self.assertFalse(review.data["report"]["deployment_ready"])
        self.assertEqual(PilotAuthorization.objects.count(), 0)
        self.assertEqual(AuthorizedPilot.objects.count(), 0)

    def test_separate_approval_binds_exact_company_report_policy_scope_and_identity(self):
        approval = self.approve()
        self.assertEqual(approval.data["approver"]["account_id"], self.owner.pk)
        self.assertEqual(approval.data["receipt"]["scope"]["developer_ids"], ["junior", "senior"])
        self.assertEqual(approval.data["receipt"]["report"]["policy_sha256"], self.policy.fingerprint())
        self.assertEqual(approval.data["review_ref"], str(approval.review.reference))
        self.assertFalse(approval.data["deployment_authorized"])
        self.assertEqual(AuthorizedPilot.objects.count(), 0)

    def test_live_approval_is_blocked_even_with_designated_mfa_approver(self):
        with self.assertRaisesRegex(ValidationError, "verified company readiness"):
            self.approve(target="live")
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_senior_task_acceptance_cannot_create_or_activate_company_approval(self):
        self.evidence()
        request = self.developer_request(self.senior)
        with self.assertRaises(PermissionDenied):
            authorization.prepare_review(request, {})
        with self.assertRaises(PermissionDenied):
            authorization.authorize(request, PASSWORD, "123456", "missing-review", {}, timezone.now(), "Invalid", 1)
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_stale_evidence_and_company_revision_cannot_be_approved(self):
        review = self.evidence()
        task = CompanyTask.objects.filter(owner=self.senior).first()
        ledger = task_ledger(task)
        record_result(self.senior, task.reference, {"desired_result": False, "tests_passed": False, "score": None,
                      "cost_usd": "0.006", "latency_ms": 200, "evidence_ref": "synthetic-new-failure",
                      "supersedes": ledger.results[-1].result_id}, task.revision)
        with self.assertRaises(ValidationError):
            self.approve(review=review)
        self.assertEqual(PilotAuthorization.objects.count(), 0)

    def test_activation_reuses_b01_state_and_preserves_scoped_budget_accounting(self):
        approval = self.active()
        state = authorization.status(self.request(), approval.reference)
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["accounting"]["remaining_usd"], "1.00")
        result = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.10")
        self.assertTrue(result["simulation_admitted"])
        self.assertEqual(result["result"]["simulated_model"], "fixture/cheap")
        self.assertEqual(result["result"]["actual_selected_model"], "fixture/premium")
        self.assertFalse(result["result"]["model_request_sent"])
        accounting = authorization.settle(self.developer_request(), approval.reference, result["decision_id"], "0.006", "completed")
        self.assertEqual(accounting["spent_usd"], "0.006")
        self.assertEqual(accounting["remaining_usd"], "0.994")

    def test_revocation_stops_new_admissions_and_preserves_outstanding_settlement(self):
        approval = self.active()
        first = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.1")
        self.sensitive(authorization.control, approval.reference, "revoke", 2, "End synthetic pilot")
        later = authorization.decide(self.developer_request(), approval.reference, self.source(4), "0.1")
        self.assertFalse(later["simulation_admitted"])
        self.assertEqual(later["result"]["simulated_model"], "fixture/premium")
        accounting = authorization.settle(self.developer_request(), approval.reference, first["decision_id"], "0.02", "completed")
        self.assertEqual(accounting["spent_usd"], "0.02")
        state = authorization.status(self.request(), approval.reference)
        self.assertEqual(state["status"], "revoked")
        with self.assertRaises(ValidationError):
            self.sensitive(authorization.control, approval.reference, "resume", state["revision"], "Cannot revive")

    def test_default_only_rollback_and_cost_overruns_are_not_hidden(self):
        approval = self.active()
        first = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.1")
        accounting = authorization.settle(self.developer_request(), approval.reference, first["decision_id"], "1.2", "failed")
        self.assertEqual(accounting["remaining_usd"], "-0.20")
        state = authorization.status(self.request(), approval.reference)
        self.assertEqual(state["status"], "paused")
        self.sensitive(authorization.control, approval.reference, "rollback", state["revision"], "Default only")
        self.assertEqual(authorization.status(self.request(), approval.reference)["status"], "rolled_back")

    def test_approval_identity_recovery_generation_changes_block_pilot_admission(self):
        approval = self.active()
        MFAState.objects.filter(user=self.owner).update(generation=2)
        result = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.1")
        self.assertFalse(result["simulation_admitted"])
        self.assertIn("authority changed", result["result"]["reason"])
        self.assertEqual(PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state().status, "paused")

    def test_scope_override_and_unknown_out_of_scope_paths_reuse_safe_runtime(self):
        approval = self.active()
        result = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.1", "fixture/standard")
        self.assertEqual(result["result"]["simulated_model"], "fixture/standard")
        later = authorization.decide(self.developer_request(), approval.reference, self.source(4, task_type="test_generation"), "0.1")
        self.assertFalse(later["simulation_admitted"])
        self.assertEqual(later["result"]["status"], "fallback")

    def test_exact_decision_and_settlement_retries_never_reserve_or_charge_twice(self):
        approval = self.active()
        first = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.10")
        retry = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.10")
        self.assertTrue(retry["historical_replay"])
        self.assertFalse(retry["simulation_admitted"])
        authorization.settle(self.developer_request(), approval.reference, first["decision_id"], "0.02", "completed")
        again = authorization.settle(self.developer_request(), approval.reference, first["decision_id"], "0.02", "completed")
        self.assertEqual(again["spent_usd"], "0.02")
        self.assertEqual(again["admitted_tasks"], 1)

    def test_approval_from_an_unstored_receipt_or_forged_company_source_cannot_be_used(self):
        review = self.evidence()
        with self.assertRaises(ValidationError):
            self.sensitive(authorization.authorize, "00000000-0000-0000-0000-000000000000", {},
                           timezone.now() + timedelta(hours=1), "Invalid caller receipt", Company.objects.get().revision)
        review.data["company_id"] = "other-company"
        review.save(update_fields=("data",))
        with self.assertRaises(ValidationError):
            self.approve(review=review)

    def test_browser_review_form_and_recovery_form_are_actual_protected_workflow_pages(self):
        review = self.evidence()
        self.assertContains(self.client.get("/pilots/"), str(review.reference))
        self.assertContains(self.client.get("/pilots/reviews/new/"), "validation plan")
        self.assertContains(self.client.get("/pilots/reviews/" + str(review.reference) + "/authorize/"), "Separate".lower(), html=False)
        self.assertEqual(self.client.get("/security/password/recovery/").status_code, 200)

    def test_rejected_company_pilot_scope_never_activates(self):
        review = self.evidence()
        scope = {"pilot_id": "rejected-simulation", "repository_ref": "synthetic-repository", "task_types": ["documentation"],
                 "developer_ids": ["junior"], "max_tasks": 2, "max_cost_usd": "1"}
        approval = self.sensitive(authorization.authorize, review.reference, scope, timezone.now() + timedelta(hours=1),
                                  "Reject this scope", Company.objects.get().revision, "simulation", "reject")
        self.assertEqual(approval.data["receipt"]["routes"], [])
        with self.assertRaises(ValidationError):
            self.sensitive(authorization.activate, approval.reference, "Cannot activate rejection")
        self.assertEqual(AuthorizedPilot.objects.count(), 0)

    def test_unenrolled_junior_membership_is_scope_not_fabricated_outcome_evidence(self):
        review = self.evidence()
        from engine.company.tasks import company_ledger
        ledger = company_ledger(Company.objects.get(), "synthetic")
        self.assertEqual(ledger.team.role("junior"), "junior")
        self.assertEqual(review.data["report"]["counts"]["recommendations"], 2)
        self.assertEqual(review.data["report"]["categories"][0]["evidence"][0]["confirmed_successes"], 2)
        self.assertFalse(any(record.task.developer_id == "junior" for record in ledger.recommendations))

    def test_authorization_expiry_blocks_future_admission_but_does_not_hide_accounting(self):
        approval = self.active()
        later = timezone.now() + timedelta(hours=2)
        with patch("engine.company.authorization.timezone.now", return_value=later):
            result = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.1")
        self.assertFalse(result["simulation_admitted"])
        self.assertIn("expired", result["result"]["reason"])
        self.assertEqual(PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state().accounting()["admitted_tasks"], 0)

    def test_company_permission_change_invalidates_exact_approval_before_new_admission(self):
        approval = self.active()
        update_member(self.owner, PASSWORD, self.junior.pk, "senior", True, True, False, False,
                      Company.objects.get().revision, reason="Synthetic role promotion changes company revision")
        result = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.1")
        self.assertFalse(result["simulation_admitted"])
        self.assertIn("configuration changed", result["result"]["reason"])

    def test_a_new_result_cannot_be_ignored_by_an_active_company_pilot(self):
        approval = self.active()
        task = CompanyTask.objects.filter(owner=self.senior).first()
        record_result(self.senior, task.reference, {"desired_result": False, "tests_passed": False, "score": None,
                      "cost_usd": "0.006", "latency_ms": 200, "evidence_ref": "synthetic-post-approval-failure",
                      "supersedes": task_ledger(task).results[-1].result_id}, task.revision)
        result = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.1")
        self.assertFalse(result["simulation_admitted"])
        self.assertEqual(PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state().status, "paused")

    def test_sensitive_actions_require_fresh_code_not_just_existing_mfa_session(self):
        review = self.evidence()
        device = TOTPDevice.objects.get(user=self.owner, confirmed=True)
        totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
        at = device.t0 + device.last_t * device.step
        totp.time = at
        used_code = str(totp.token()).zfill(device.digits)
        scope = {"pilot_id": "must-not-approve", "repository_ref": "synthetic-repository", "task_types": ["documentation"],
                 "developer_ids": ["junior"], "max_tasks": 1, "max_cost_usd": "1"}
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            with self.assertRaises(PermissionDenied):
                authorization.authorize(self.request(), PASSWORD, used_code, review.reference, scope,
                                        timezone.now() + timedelta(hours=1), "Refuse replay", Company.objects.get().revision)
        self.assertEqual(PilotAuthorization.objects.count(), 0)
        device.refresh_from_db()
        self.assertEqual(device.throttling_failure_count, 1)

    def test_account_recovery_keeps_a_correctly_entered_mfa_required_for_next_login(self):
        value = self.sensitive(recovery.issue_personal)
        device = TOTPDevice.objects.get(user=self.owner, confirmed=True)
        code, at = device_code(device)
        password = "recovered-private-password-" + "B9!" * 8
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            self.assertTrue(recovery.reset_password("owner", value, password, code, "authenticator"))
        other = Client(HTTP_HOST="localhost")
        self.assertEqual(other.post("/login/", {"username": "owner", "password": password}).status_code, 302)
        self.assertEqual(other.get("/")["Location"], "/security/mfa/verify/")

    def test_private_credential_issue_and_password_reset_browser_flow(self):
        device = TOTPDevice.objects.get(user=self.owner, confirmed=True)
        code, at = device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = security_post(self.client, "/security/password/recovery/", {"confirm_password": PASSWORD, "code": code})
        self.assertEqual(response.status_code, 200)
        match = re.search(r'<pre id="recovery-value">([A-Za-z0-9_-]+)</pre>', response.content.decode())
        self.assertIsNotNone(match)
        value = match.group(1)
        device.refresh_from_db()
        code, at = device_code(device)
        other = Client(HTTP_HOST="localhost")
        password = "browser-recovery-password-" + "G4!" * 8
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = other.post("/security/password/reset/", {"username": "owner", "recovery_credential": value,
                                  "password1": password, "password2": password, "factor_kind": "authenticator", "code": code})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", other.session)
        self.assertNotIn(value, json.dumps(list(SecurityEvent.objects.values("details"))))

    def test_csrf_applies_to_password_reset_and_pilot_authorization(self):
        client = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
        self.assertEqual(client.post("/security/password/reset/", {"username": "owner"}).status_code, 403)
        review = self.evidence()
        client.force_login(self.owner)
        self.assertEqual(client.post("/pilots/reviews/" + str(review.reference) + "/authorize/", {"target": "live"}).status_code, 403)

    def test_browser_forms_authorize_activate_admit_and_settle_the_same_company_workflow(self):
        review = self.evidence()
        plan = review.data["learner"]["plan"]
        response = self.client.post("/pilots/reviews/new/", {
            "learner_version": plan["learner_version"], "source_kind": "synthetic", "cutoff": plan["cutoff"],
            "session_ids": ",".join(plan["session_ids"]), "task_types": "documentation",
            "min_senior_successes": 2, "min_senior_sessions": 2,
        })
        self.assertEqual(response.status_code, 302)
        path = response["Location"]
        device = TOTPDevice.objects.get(user=self.owner, confirmed=True)
        code, at = device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = self.client.post(path, {
                "confirm_password": PASSWORD, "code": code, "pilot_id": "browser-authorized-pilot",
                "repository_ref": "synthetic-repository", "task_types": "documentation", "developer_ids": "junior,senior",
                "max_tasks": 3, "max_cost_usd": "1.00", "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
                "reason": "Explicit browser scope review", "expected_revision": Company.objects.get().revision,
                "target": "simulation", "decision": "approve",
            })
        self.assertEqual(response.status_code, 302)
        pilot_path = response["Location"]
        device.refresh_from_db()
        code, at = device_code(device)
        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            response = self.client.post(pilot_path, {"confirm_password": PASSWORD, "code": code, "action": "activate",
                                                    "expected_revision": 0, "reason": "Activate exact reviewed scope"})
        self.assertEqual(response.status_code, 302)
        junior = Client(HTTP_HOST="localhost")
        self.assertEqual(junior.post("/login/", {"username": "junior", "password": PASSWORD}).status_code, 302)
        source = self.source(3)
        source.update(risk_tags="low", required_tools="read", reserve_usd="0.10")
        response = junior.post(pilot_path + "decide/", source)
        self.assertContains(response, "company_decision_")
        state = PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state()
        decision_id = next(iter(state.decisions))
        response = junior.post(pilot_path + "settle/", {"decision_id": decision_id, "actual_cost_usd": "0.006", "outcome": "completed"})
        self.assertContains(response, "0.994")
        self.assertEqual(PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state().accounting()["spent_usd"], "0.006")


class CompanyDeploymentTests(unittest.TestCase):
    def config(self):
        return {"public_origin": "https://tarkado.company.example", "https_proxy_configured": True,
                "private_single_host": True, "backup_policy": "Private reviewed operator backup", "operator_contact": "company-operator"}

    def test_server_config_requires_explicit_https_origin_and_operator_prerequisites(self):
        value = validate_deployment(self.config())
        self.assertEqual(value["host"], "tarkado.company.example")
        for updates in ({"public_origin": "http://company.example"}, {"public_origin": "https://*.company.example"},
                        {"public_origin": "https://company.example/path"}, {"https_proxy_configured": False},
                        {"private_single_host": False}, {"public_origin": "https://localhost"},
                        {"public_origin": "https://company.example:bad"}):
            with self.subTest(updates=updates):
                with self.assertRaises(ValidationError):
                    validate_deployment(dict(self.config(), **updates))

    def test_company_wsgi_config_is_secure_and_refuses_raw_forwarded_scheme(self):
        script = """import sys, tempfile
from pathlib import Path
from engine.company.runtime import configure, initialize_store
from engine.company.deployment import validate_deployment
from django.conf import settings
from django.test import Client
from django.core.management import call_command
root = Path(sys.argv[1])
config = {'public_origin':'https://tarkado.company.example','https_proxy_configured':True,'private_single_host':True,'backup_policy':'private','operator_contact':'operator'}
configure(root, create=True, deployment=validate_deployment(config))
initialize_store(root)
call_command('migrate', interactive=False, verbosity=0)
assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE and not settings.DEBUG
client = Client(HTTP_HOST='tarkado.company.example')
assert client.get('/login/', secure=True).status_code == 200
assert client.get('/login/').status_code == 400
assert client.get('/login/', HTTP_X_FORWARDED_PROTO='https').status_code == 400
assert client.get('/login/', secure=True, HTTP_HOST='other.company.example').status_code == 400
print('HTTPS boundary and secure-cookie settings verified')
"""
        with tempfile.TemporaryDirectory(prefix="tarkado-company-service-settings-") as directory:
            result = subprocess.run([sys.executable, "-c", script, str(Path(directory) / "company")],
                                    cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verified", result.stdout)

    def test_waitress_wrapper_uses_private_socket_explicit_proxy_trust_and_bounded_requests(self):
        from engine.company.deployment import serve
        with tempfile.TemporaryDirectory(prefix="tarkado-waitress-contract-") as directory:
            with override_settings(TARKADO_SERVICE_MODE="company_https_proxy", TARKADO_PUBLIC_ORIGIN="https://tarkado.company.example"), patch("waitress.serve") as start:
                serve(Path(directory), validate_deployment(self.config()))
            kwargs = start.call_args.kwargs
            self.assertEqual(kwargs["unix_socket_perms"], "600")
            self.assertEqual(kwargs["trusted_proxy"], "localhost")
            self.assertEqual(kwargs["trusted_proxy_headers"], {"x-forwarded-proto"})
            self.assertTrue(kwargs["clear_untrusted_proxy_headers"])
            self.assertFalse(kwargs["expose_tracebacks"])
            self.assertEqual(kwargs["max_request_body_size"], 131072)
            self.assertNotIn("listen", kwargs)

    def test_company_server_refuses_development_or_mismatched_origin_configuration(self):
        from engine.company.deployment import serve
        with tempfile.TemporaryDirectory(prefix="tarkado-refused-company-service-") as directory:
            with patch("waitress.serve") as start:
                with self.assertRaises(ValidationError):
                    serve(Path(directory), validate_deployment(self.config()))
                with override_settings(TARKADO_SERVICE_MODE="company_https_proxy", TARKADO_PUBLIC_ORIGIN="https://other.company.example"):
                    with self.assertRaises(ValidationError):
                        serve(Path(directory), validate_deployment(self.config()))
            start.assert_not_called()

    def test_real_waitress_private_socket_enforces_https_proxy_scheme_and_host(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-waitress-socket-") as temporary:
            root = Path(temporary) / "company"
            result = subprocess.run([sys.executable, "-m", "engine", "company", "bootstrap", "--store", str(root),
                                     "--name", "Synthetic service", "--username", "owner", "--policy", str(FIXTURES / "policy.json"),
                                     "--repositories", "synthetic-repository", "--company-api"],
                                    cwd=ROOT, input=PASSWORD + "\n" + PASSWORD + "\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            config = Path(temporary) / "deployment.json"
            with os.fdopen(os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
                json.dump(self.config(), stream)
            process = subprocess.Popen([sys.executable, "-m", "engine", "company", "service", "--store", str(root),
                                        "--deployment", str(config)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            path = root / "company.sock"
            try:
                deadline = time.monotonic() + 15
                while not path.exists() and time.monotonic() < deadline and process.poll() is None:
                    time.sleep(0.05)
                self.assertTrue(path.exists(), "The private company-serving socket was not created.")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

                def request(headers):
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                        client.settimeout(5)
                        client.connect(str(path))
                        message = "GET /login/ HTTP/1.1\r\nHost: tarkado.company.example\r\nConnection: close\r\n" + headers + "\r\n"
                        client.sendall(message.encode())
                        pieces = []
                        while True:
                            chunk = client.recv(65536)
                            if not chunk:
                                break
                            pieces.append(chunk)
                        return b"".join(pieces).decode()

                secure = request("X-Forwarded-Proto: https\r\n")
                self.assertTrue(secure.startswith("HTTP/1.1 200"), secure[:300])
                self.assertIn("secure", secure.lower())
                insecure = request("")
                self.assertTrue(insecure.startswith("HTTP/1.1 400"), insecure[:300])
                self.assertNotIn(PASSWORD, secure + insecure)
            finally:
                process.terminate()
                process.communicate(timeout=10)

    def test_operator_backup_preserves_pair_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-operator-backup-") as temporary:
            root = Path(temporary) / "company"
            result = subprocess.run([sys.executable, "-m", "engine", "company", "bootstrap", "--store", str(root),
                                     "--name", "Synthetic backup", "--username", "owner", "--policy", str(FIXTURES / "policy.json"),
                                     "--repositories", "synthetic-repository", "--company-api"],
                                    cwd=ROOT, input=PASSWORD + "\n" + PASSWORD + "\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            destination = Path(temporary) / "private-backup"
            arguments = [sys.executable, "-m", "engine", "company", "backup", "--store", str(root), "--output", str(destination)]
            result = subprocess.run(arguments, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["includes_private_credentials"])
            self.assertEqual((destination / ".secret-key").read_bytes(), (root / ".secret-key").read_bytes())
            for name in ("company.sqlite3", ".secret-key"):
                self.assertEqual((destination / name).stat().st_mode & 0o777, 0o600)
            result = subprocess.run(arguments, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            status_result = subprocess.run([sys.executable, "-m", "engine", "company", "status", "--store", str(destination)],
                                           cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            self.assertEqual(json.loads(status_result.stdout)["accounts"], 1)


class CompanyPilotConcurrencyTests(TransactionTestCase):
    setUp = CompanyControlTests.setUp
    enroll = CompanyControlTests.enroll
    request = CompanyControlTests.request
    sensitive = CompanyControlTests.sensitive
    source = CompanyControlTests.source
    evidence = CompanyControlTests.evidence
    approve = CompanyControlTests.approve
    active = CompanyControlTests.active
    developer_request = CompanyControlTests.developer_request

    def test_parallel_authorized_admissions_serialize_budget_and_preserve_all_history(self):
        approval = self.active()

        def admit(number):
            try:
                return authorization.decide(self.developer_request(), approval.reference, self.source(number), "0.75")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(admit, (3, 4)))
        self.assertEqual(sum(item["simulation_admitted"] for item in results), 1)
        state = PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state()
        self.assertEqual(len(state.decisions), 2)
        self.assertEqual(state.accounting()["reserved_usd"], "0.75")

    def test_authorization_revocation_completed_in_another_connection_blocks_admission(self):
        approval = self.active()

        def revoke():
            try:
                self.sensitive(authorization.control, approval.reference, "revoke", 1, "Concurrent operator revocation")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(revoke).result()
        result = authorization.decide(self.developer_request(), approval.reference, self.source(3), "0.1")
        self.assertFalse(result["simulation_admitted"])
        state = PilotJournal.from_dict(AuthorizedPilot.objects.get().journal).state()
        self.assertEqual(state.status, "revoked")
        self.assertEqual(state.accounting()["admitted_tasks"], 0)

    def test_concurrent_password_recovery_cannot_consume_one_grant_twice(self):
        value = self.sensitive(recovery.issue_assisted, self.junior.pk, timezone.now() + timedelta(minutes=30),
                                "Synthetic concurrent reset", "synthetic-person-check")

        def reset(_):
            try:
                return recovery.reset_password("junior", value, "new-concurrent-password-" + "Y3!" * 8, "", "authenticator")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reset, range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(SecurityEvent.objects.filter(action="password_recovered").count(), 1)


class CompanyConcurrencyTests(TransactionTestCase):
    def setUp(self):
        policy = load_policy(FIXTURES / "policy.json")
        bootstrap_company("owner", PASSWORD, "Synthetic company", policy.to_dict(), ["synthetic-repository"])

    def test_concurrent_stale_admin_changes_cannot_both_succeed(self):
        def invite(number):
            try:
                user = get_user_model().objects.get(username="owner")
                create_invitation(user, PASSWORD, "junior-" + str(number), "junior", True, False, False,
                                  timezone.now() + timedelta(hours=1), 1, reason="Synthetic concurrent invitation")
                return "created"
            except ValidationError:
                return "stale"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(invite, range(2)))
        self.assertEqual(sorted(results), ["created", "stale"])
        self.assertEqual(Invitation.objects.count(), 1)
        self.assertEqual(list(CompanyEvent.objects.values_list("revision", flat=True)), [1, 2])

    def test_concurrent_invitation_consumption_enrolls_only_one_account(self):
        user = get_user_model().objects.get(username="owner")
        _, value = create_invitation(user, PASSWORD, "junior", "junior", True, False, False,
                                     timezone.now() + timedelta(hours=1), 1, reason="Synthetic one-use test")

        def accept(_):
            try:
                accept_invitation(value, PASSWORD)
                return "enrolled"
            except ValidationError:
                return "refused"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(accept, range(2)))
        self.assertEqual(sorted(results), ["enrolled", "refused"])
        self.assertEqual(get_user_model().objects.filter(username="junior").count(), 1)
        self.assertEqual(CompanyEvent.objects.filter(action="invite_accept").count(), 1)

    def test_parallel_login_failures_cannot_overrun_the_checked_attempt_limit(self):
        def fail(_):
            try:
                return checked_login(None, "owner", "wrong-synthetic-value")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(fail, range(LOGIN_FAILURE_LIMIT + 3)))
        self.assertEqual(results, [None] * (LOGIN_FAILURE_LIMIT + 3))
        self.assertEqual(LoginAttempt.objects.filter(result="failed").count(), LOGIN_FAILURE_LIMIT)

    def task_user(self):
        owner = get_user_model().objects.get(username="owner")
        _, value = create_invitation(owner, PASSWORD, "junior", "junior", True, False, False,
                                     timezone.now() + timedelta(hours=1), Company.objects.get().revision, reason="Synthetic task concurrency")
        return accept_invitation(value, PASSWORD)

    def task_source(self):
        return {"repository_ref": "synthetic-repository", "source_kind": "synthetic", "boundary": "new_task",
                "task_id": "concurrent-task", "session_id": "concurrent-session", "task_type": "documentation",
                "risk_tags": ["low"], "selected_model": "fixture/premium", "required_tools": ["read"], "context_tokens": 2000}

    def test_concurrent_recommendation_retries_create_one_record_and_one_event(self):
        user = self.task_user()

        def recommend(_):
            try:
                return recommend_task(user, self.task_source()).reference
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(recommend, range(3)))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(CompanyTask.objects.count(), 1)
        self.assertEqual(TaskEvent.objects.count(), 1)

    def test_concurrent_conflicting_responses_cannot_both_be_recorded(self):
        user = self.task_user()
        task = recommend_task(user, self.task_source())

        def respond(value):
            try:
                record_response(user, task.reference, value, 1)
                return "recorded"
            except ValidationError:
                return "refused"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(respond, ("accept", "reject")))
        self.assertEqual(sorted(results), ["recorded", "refused"])
        self.assertEqual(TaskEvent.objects.filter(kind="response").count(), 1)
        self.assertEqual(CompanyTask.objects.get().revision, 2)

    def test_concurrent_result_corrections_cannot_branch_or_discard_history(self):
        user = self.task_user()
        task = recommend_task(user, self.task_source())
        task = record_execution(user, task.reference, "fixture/cheap", 1)
        source = {"desired_result": None, "tests_passed": None, "score": None, "cost_usd": None,
                  "latency_ms": None, "evidence_ref": None, "supersedes": None}
        task = record_result(user, task.reference, source, task.revision)
        source["supersedes"] = task_ledger(task).results[-1].result_id

        def correct(score):
            try:
                record_result(user, task.reference, dict(source, score=score, evidence_ref="synthetic-correction"), task.revision)
                return "recorded"
            except ValidationError:
                return "refused"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(correct, ("0.5", "0.6")))
        self.assertEqual(sorted(results), ["recorded", "refused"])
        task.refresh_from_db()
        self.assertEqual(len(task_ledger(task).results), 2)
        self.assertEqual(TaskEvent.objects.filter(kind="result").count(), 2)

    def test_account_revocation_completed_before_a_task_write_is_not_bypassed(self):
        user = self.task_user()
        task = recommend_task(user, self.task_source())
        owner = get_user_model().objects.get(username="owner")

        def revoke():
            try:
                update_member(owner, PASSWORD, user.pk, "junior", False, True, False, False,
                              Company.objects.get().revision, reason="Synthetic revocation before task write")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(revoke).result()
        with self.assertRaises(PermissionDenied):
            record_response(user, task.reference, "accept", 1)
        self.assertEqual(TaskEvent.objects.count(), 1)

    def mfa_request(self, user):
        request = RequestFactory().post("/security/mfa/verify/")
        request.user = user
        SessionMiddleware(lambda _: None).process_request(request)
        return request

    def test_concurrent_totp_verifications_cannot_accept_one_code_twice(self):
        user = get_user_model().objects.get(username="owner")
        device = TOTPDevice.objects.create(user=user, confirmed=True, tolerance=0)
        MFAState.objects.create(user=user, generation=1)
        code, at = device_code(device)

        def verify(_):
            try:
                return verify_mfa(self.mfa_request(user), code)
            finally:
                connections.close_all()

        with patch("django_otp.plugins.otp_totp.models.time.time", return_value=at):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(verify, range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(SecurityEvent.objects.filter(action="mfa_verify").count(), 1)

    def test_concurrent_backup_recovery_consumes_code_only_once(self):
        user = get_user_model().objects.get(username="owner")
        TOTPDevice.objects.create(user=user, confirmed=True)
        MFAState.objects.create(user=user, generation=1)
        device = StaticDevice.objects.create(user=user, confirmed=True)
        code = "A" * 16
        StaticToken.objects.create(device=device, token=code)

        def recover(_):
            try:
                return recover_factor(self.mfa_request(user), PASSWORD, code)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(recover, range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(StaticToken.objects.filter(token=code).count(), 0)
        self.assertEqual(SecurityEvent.objects.filter(action="mfa_backup_used").count(), 1)


class CompanyFilesystemTests(unittest.TestCase):
    def test_empty_store_explains_bootstrap_before_upgrade_or_serve(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-empty-company-") as temporary:
            root = Path(temporary) / "company"
            for action in ("upgrade", "serve"):
                with self.subTest(action=action):
                    result = subprocess.run([sys.executable, "-m", "engine", "company", action, "--store", str(root)],
                                            cwd=ROOT, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("not initialized", result.stderr)
                    self.assertIn("company bootstrap", result.stderr)
                    self.assertIn("first administrator", result.stderr)
                    self.assertEqual(list(root.iterdir()), [])

    def test_incomplete_existing_store_does_not_recommend_bootstrapping_over_user_data(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-incomplete-company-") as temporary:
            root = private_directory(Path(temporary) / "company")
            database = root / "company.sqlite3"
            with os.fdopen(os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                stream.write(b"synthetic user-owned state; preserve it")
            original = database.read_bytes()
            result = subprocess.run([sys.executable, "-m", "engine", "company", "upgrade", "--store", str(root)],
                                    cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("store is incomplete", result.stderr)
            self.assertIn("Do not bootstrap", result.stderr)
            self.assertEqual(database.read_bytes(), original)
            self.assertFalse((root / ".secret-key").exists())

    def test_private_directory_and_files_never_change_existing_loose_permissions(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-company-permissions-") as temporary:
            root = private_directory(Path(temporary) / "company")
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            loose = Path(temporary) / "loose"
            loose.mkdir(mode=0o755)
            os.chmod(loose, 0o755)
            with self.assertRaises(ValueError):
                private_directory(loose)
            self.assertEqual(loose.stat().st_mode & 0o777, 0o755)

    def test_symlink_state_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-company-symlink-") as temporary:
            target = Path(temporary) / "user-owned"
            target.write_text("preserve user work")
            alias = Path(temporary) / "alias"
            alias.symlink_to(target)
            with self.assertRaises(ValueError):
                check_private_file(alias)
            self.assertEqual(target.read_text(), "preserve user work")

    def test_optional_cli_help_does_not_load_django_or_create_company_state(self):
        result = subprocess.run([sys.executable, "-c", "from engine.cli import main; import sys; main(['company', '--help'])"],
                                 cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bootstrap", result.stdout)
        script = "from engine.cli import main; import sys; main(['--version']); assert 'django' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_bootstrap_and_status_use_private_state_and_refuse_rebootstrap(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-company-cli-") as temporary:
            root = Path(temporary) / "company"
            arguments = [sys.executable, "-m", "engine", "company", "bootstrap", "--store", str(root),
                         "--name", "Synthetic company", "--username", "owner", "--policy", str(FIXTURES / "policy.json"),
                         "--repositories", "synthetic-repository", "--company-api"]
            result = subprocess.run(arguments, cwd=ROOT, input=PASSWORD + "\n" + PASSWORD + "\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(PASSWORD, result.stdout + result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["accounts"], 1)
            self.assertFalse(output["deployment_authorized"])
            for filename in (".secret-key", "company.sqlite3"):
                self.assertEqual((root / filename).stat().st_mode & 0o777, 0o600)
            before = (root / "company.sqlite3").read_bytes()
            result = subprocess.run(arguments, cwd=ROOT, input=PASSWORD + "\n" + PASSWORD + "\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual((root / "company.sqlite3").read_bytes(), before)
            result = subprocess.run([sys.executable, "-m", "engine", "company", "status", "--store", str(root)],
                                     cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["revision"], 1)

    def test_invalid_policy_is_refused_before_creating_a_store_or_prompting_for_password(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-company-invalid-") as temporary:
            root = Path(temporary) / "company"
            result = subprocess.run([sys.executable, "-m", "engine", "company", "bootstrap", "--store", str(root),
                                     "--name", "Synthetic", "--username", "owner", "--policy", str(Path(temporary) / "missing.json"),
                                     "--repositories", "synthetic-repository", "--company-api"],
                                    cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(root.exists())

    def test_weak_bootstrap_password_never_publishes_account_or_secret_files(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-company-weak-bootstrap-") as temporary:
            root = Path(temporary) / "company"
            result = subprocess.run([sys.executable, "-m", "engine", "company", "bootstrap", "--store", str(root),
                                     "--name", "Synthetic", "--username", "owner", "--policy", str(FIXTURES / "policy.json"),
                                     "--repositories", "synthetic-repository", "--company-api"],
                                    cwd=ROOT, input="short\nshort\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((root / "company.sqlite3").exists())
            self.assertFalse((root / ".secret-key").exists())

    def test_additive_upgrade_preserves_existing_accounts_company_history_and_secret(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-company-upgrade-") as temporary:
            root = Path(temporary) / "company"
            setup = """import sys
from pathlib import Path
from django.core.management import call_command
from engine.company.runtime import configure, initialize_store
configure(Path(sys.argv[1]), create=True)
initialize_store(Path(sys.argv[1]))
call_command('migrate', 'auth', interactive=False, verbosity=0)
call_command('migrate', 'company', '0001_initial', interactive=False, verbosity=0)
from engine.company.services import bootstrap_company
from engine.importers import load_policy
bootstrap_company('owner', sys.stdin.readline().strip(), 'Preserved company', load_policy(Path(sys.argv[2])).to_dict(), ['synthetic-repository'])
"""
            snapshot = """import sys, json, hashlib
from pathlib import Path
from engine.company.runtime import configure
configure(Path(sys.argv[1]))
from django.contrib.auth import get_user_model
from engine.company.models import Company, CompanyEvent, Membership
state = [list(get_user_model().objects.values()), list(Company.objects.values()), list(CompanyEvent.objects.values()), list(Membership.objects.values())]
print(hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest())
"""
            result = subprocess.run([sys.executable, "-c", setup, str(root), str(FIXTURES / "policy.json")],
                                    input=PASSWORD + "\n", cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            before = subprocess.run([sys.executable, "-c", snapshot, str(root)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(before.returncode, 0, before.stderr)
            key_before = (root / ".secret-key").read_bytes()
            upgraded = subprocess.run([sys.executable, "-m", "engine", "company", "upgrade", "--store", str(root)],
                                      cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
            self.assertEqual(json.loads(upgraded.stdout)["revision"], 1)
            after = subprocess.run([sys.executable, "-c", snapshot, str(root)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(after.returncode, 0, after.stderr)
            self.assertEqual(after.stdout, before.stdout)
            self.assertEqual((root / ".secret-key").read_bytes(), key_before)

    def test_actual_loopback_server_login_and_company_page(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-company-http-") as temporary:
            root = Path(temporary) / "company"
            result = subprocess.run([sys.executable, "-m", "engine", "company", "bootstrap", "--store", str(root),
                                     "--name", "Synthetic HTTP company", "--username", "owner", "--policy", str(FIXTURES / "policy.json"),
                                     "--repositories", "synthetic-repository", "--company-api"],
                                    cwd=ROOT, input=PASSWORD + "\n" + PASSWORD + "\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            process = subprocess.Popen([sys.executable, "-m", "engine", "company", "serve", "--store", str(root), "--port", str(port)],
                                       cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
            base = "http://127.0.0.1:" + str(port)
            try:
                page = None
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        with opener.open(base + "/login/", timeout=1) as response:
                            page = response.read().decode()
                        break
                    except URLError:
                        time.sleep(0.05)
                self.assertIsNotNone(page, "The loopback-only company server did not start.")
                csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
                data = urlencode({"csrfmiddlewaretoken": csrf, "username": "owner", "password": PASSWORD}).encode()
                with opener.open(Request(base + "/login/", data=data), timeout=5) as response:
                    body = response.read().decode()
                    self.assertIn("Synthetic HTTP company", body)
                    self.assertIn("Signed in as owner", body)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertNotIn(PASSWORD, body)

                def submit(client, path, values):
                    with client.open(base + path, timeout=5) as response:
                        form_page = response.read().decode()
                    csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', form_page).group(1)
                    supplied = dict(values, csrfmiddlewaretoken=csrf)
                    with client.open(Request(base + path, data=urlencode(supplied).encode()), timeout=5) as response:
                        return response.geturl(), response.read().decode()

                _, enrollment_page = submit(opener, "/security/mfa/setup/", {"confirm_password": PASSWORD})
                secret_match = re.search(r'<pre id="setup-secret">([A-Z2-7]+)</pre>', enrollment_page)
                self.assertIsNotNone(secret_match)
                authenticator = TOTP(b32decode(secret_match.group(1)), 30, 0, 6, 0)
                _, backup_page = submit(opener, "/security/mfa/confirm/", {"code": str(authenticator.token()).zfill(6)})
                self.assertIn("Authenticator confirmed", backup_page)

                _, invitation_page = submit(opener, "/invitations/", {
                    "expected_revision": 1, "confirm_password": PASSWORD, "reason": "Synthetic HTTP workflow",
                    "username": "senior-http", "role": "senior", "participating": "on",
                    "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
                })
                invitation_match = re.search(r"<pre>([A-Za-z0-9_-]{43})</pre>", invitation_page)
                self.assertIsNotNone(invitation_match)
                reviewer = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
                submit(reviewer, "/join/", {"invitation": invitation_match.group(1), "password1": PASSWORD, "password2": PASSWORD})
                _, reviewer_home = submit(reviewer, "/login/", {"username": "senior-http", "password": PASSWORD})
                self.assertIn("Signed in as senior-http", reviewer_home)
                task_url, task_page = submit(reviewer, "/tasks/new/", {
                    "repository_ref": "synthetic-repository", "source_kind": "synthetic", "boundary": "new_task",
                    "task_id": "http-documentation", "session_id": "manual-http-session", "task_type": "documentation",
                    "risk_tags": "low", "selected_model": "fixture/premium", "required_tools": "read", "context_tokens": 2000,
                })
                self.assertIn("Suggested: fixture/cheap", task_page)
                self.assertIn("Originally selected: fixture/premium", task_page)
                task_path = task_url.removeprefix(base)
                submit(reviewer, task_path + "response/", {"expected_revision": 1, "response": "accept"})
                submit(reviewer, task_path + "execution/", {"expected_revision": 2, "actual_model": "fixture/cheap"})
                _, result_page = submit(reviewer, task_path + "result/", {
                    "expected_revision": 3, "desired_result": "true", "tests_passed": "unknown",
                    "cost_usd": "0.012", "evidence_ref": "synthetic-http-confirmation",
                })
                self.assertIn("synthetic-http-confirmation", result_page)
                self.assertIn("role at submission senior", result_page)
                self.assertNotIn(PASSWORD, result_page)
                with opener.open(base + "/tasks/", timeout=5) as response:
                    summary_page = response.read().decode()
                self.assertIn("current results 1", summary_page)
                self.assertIn("senior_adopted_successes", summary_page)
                request = Request(base + "/configuration/", headers={"Host": "untrusted.invalid"})
                with self.assertRaises(HTTPError) as error:
                    opener.open(request, timeout=5)
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
            finally:
                process.terminate()
                output, diagnostics = process.communicate(timeout=10)
                self.assertNotIn(PASSWORD, output + diagnostics)
