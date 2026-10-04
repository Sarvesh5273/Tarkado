"""Real loopback browser-issued delegation -> metadata-only API; synthetic hosts/accounts only."""

import http.cookiejar
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from datetime import timedelta
from base64 import b32decode
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

import test_company as support
from django.utils import timezone
from django_otp.oath import TOTP
from engine.company.connectors import digest


class ConnectorHTTPTests(unittest.TestCase):
    def test_real_http_pair_start_response_attempt_close_actual_result(self):
        with tempfile.TemporaryDirectory(prefix="tarkado-connector-http-", dir=support.TEMPORARY.name) as directory:
            store = Path(directory) / "company"
            bootstrap = subprocess.run([sys.executable, "-m", "engine", "company", "bootstrap", "--store", str(store),
                "--name", "Synthetic connector HTTP", "--username", "owner", "--policy", str(support.FIXTURES / "policy.json"),
                "--repositories", "synthetic-repository", "--company-api"], cwd=support.ROOT,
                input=support.PASSWORD + "\n" + support.PASSWORD + "\n", text=True, capture_output=True)
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0)); port = reservation.getsockname()[1]
            process = subprocess.Popen([sys.executable, "-m", "engine", "company", "serve", "--store", str(store), "--port", str(port)], cwd=support.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            base = f"http://127.0.0.1:{port}"
            owner = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
            developer = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
            plain = build_opener()

            def submit(client, path, values):
                with client.open(base + path, timeout=5) as response:
                    page = response.read().decode()
                values = dict(values, csrfmiddlewaretoken=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1))
                with client.open(Request(base + path, data=urlencode(values).encode()), timeout=5) as response:
                    return response.read().decode()

            def api(token, method, data):
                with plain.open(Request(base + f"/api/connectors/v1/{method}/", data=json.dumps(data).encode(),
                    headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}), timeout=5) as response:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    return json.loads(response.read())

            try:
                started = False
                until = time.monotonic() + 15
                while time.monotonic() < until:
                    try:
                        with owner.open(base + "/login/", timeout=1): started = True
                        break
                    except URLError: time.sleep(.05)
                self.assertTrue(started)
                submit(owner, "/login/", {"username": "owner", "password": support.PASSWORD})
                page = submit(owner, "/security/mfa/setup/", {"confirm_password": support.PASSWORD})
                seed = re.search(r'<pre id="setup-secret">([A-Z2-7]+)</pre>', page).group(1)
                authenticator = TOTP(b32decode(seed), 30, 0, 6, 0)
                submit(owner, "/security/mfa/confirm/", {"code": str(authenticator.token()).zfill(6)})
                page = submit(owner, "/invitations/", {"username": "connector-dev", "role": "developer", "participating": "on",
                    "reason": "Synthetic connector HTTP account", "expected_revision": 1, "confirm_password": support.PASSWORD,
                    "expires_at": (timezone.now() + timedelta(hours=1)).isoformat()})
                invitation = re.search(r'<pre>([A-Za-z0-9_-]{43})</pre>', page).group(1)
                submit(developer, "/join/", {"invitation": invitation, "password1": support.PASSWORD, "password2": support.PASSWORD})
                submit(developer, "/login/", {"username": "connector-dev", "password": support.PASSWORD})
                page = submit(developer, "/connectors/", {"name": "Synthetic HTTP connector", "repository_ref": "synthetic-repository",
                    "directory": "/synthetic/work", "source_kind": "synthetic", "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
                    "expected_revision": 3, "confirm_password": support.PASSWORD, "confirmation": "on"})
                match = re.search(r'<pre id="connector-credential">([A-Za-z0-9_-]{43})</pre>', page)
                self.assertIsNotNone(match, page)
                token = match.group(1)
                status = api(token, "status", {"location_sha256": digest("/synthetic/work")})
                self.assertFalse(status["routing_enabled"])
                state = api(token, "start", {"client_task_id": str(uuid.uuid4()), "session_ref": digest("ses_synthetic"),
                    "location_sha256": digest("/synthetic/work"), "task_label": "Synthetic HTTP documentation", "boundary": "new_task",
                    "task_type": "documentation", "risk_tags": ["low"], "required_tools": ["read"], "context_tokens": 2000, "selected_model": "fixture/premium"})
                self.assertEqual(state["recommendation"]["effective_model"], "fixture/premium")
                self.assertEqual(state["recommendation"]["recommended_model"], "fixture/cheap")
                def feedback(action, value):
                    return api(token, "feedback", {"connector_task_ref": state["connector_task_ref"], "location_sha256": digest("/synthetic/work"),
                        "action": action, "expected_revision": state["task_revision"], "value": value})
                state = feedback("response", "accept")
                for sequence, kind in ((1, "model_attempt"), (2, "close")):
                    state = api(token, "observation", {"connector_task_ref": state["connector_task_ref"], "location_sha256": digest("/synthetic/work"),
                        "event_id": str(uuid.uuid4()), "sequence": sequence, "payload": {"observation_kind": kind,
                            "request_kind": "primary" if kind == "model_attempt" else "unknown", "model": "fixture/cheap" if kind == "model_attempt" else None,
                            "http_status": None, "attempt": None, "retry": None, "coverage_status": "limited_hook_coverage"}})
                state = feedback("actual_model", "fixture/cheap")
                state = feedback("result", {"desired_result": None, "tests_passed": None, "score": None, "cost_usd": None, "latency_ms": None, "evidence_ref": None, "supersedes": None})
                self.assertIsNone(state["current_result"]["desired_result"])
                with developer.open(base + state["browser_path"], timeout=5) as response:
                    page = response.read().decode()
                self.assertIn("Linked OpenCode observations", page)
                self.assertIn("Result unknown", page)
                self.assertNotIn(token, page)
            finally:
                process.terminate()
                stdout, stderr = process.communicate(timeout=10)
                self.assertNotIn(support.PASSWORD, stdout + stderr)
