"""DEMO-ONLY runner for the Tarkado full loop (docs/FULL_LOOP.md).

Every stage uses the same paths a company would: browser pages over the public
HTTPS origin (with password + fresh authenticator codes), real OpenCode servers
per developer, LiteLLM, and the real provider. It never writes the database
directly and never weakens a gate; when a gate refuses, the runner stops and
prints the refusal.

Stages (run in order; each is idempotent where the product is):
  setup      private files, company bootstrap, checkouts, gateway keys, host validation
  people     owner MFA, invitations, developer enrolment + MFA
  shadow     S1-S3, J1 (documentation), T1-T3 (test writing): recorded tasks, suggestion, response, real OpenCode run,
             reported model, independent CI, result
  review     category evidence review + learner publication
  approve    scope authorization (fresh MFA, real readiness verifier) + activation
  delivery   gateway identity, LiteLLM callback, developer pairing
  routed     R1/R2 (documentation), R3 (test writing) through OpenCode -> LiteLLM -> provider, settlement, feedback
  relearn    the next learning review including routed outcomes
  drill      F1 failure: provider path lost mid-attempt -> pause -> rollback -> N1
  laptop     pair a laptop and write its private bundle
  settle     manual fallback: close one task's cost record
  status     print a metadata summary

State: local/full-loop/ (gitignored). Usage: run_loop.py <stage> [...]
"""

import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from html import unescape
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(DEMO)]

import demo_ci  # noqa: E402
from browser import Browser, Forms, text_of  # noqa: E402

STATE = ROOT / "local" / "full-loop"
PRIVATE = STATE / "private"
RUN = STATE / "run"
WORK = STATE / "work"
STORE = STATE / "store"
PYTHON = str(ROOT / ".venv" / "bin" / "python")
OPENCODE = str(ROOT / "local" / "opencode-host" / "node_modules" / "@opencode" / "cli" / "bin" / "opencode.exe")
DEV = os.environ.get("REPLIT_DEV_DOMAIN", "")
COMPANY = f"https://{DEV}:8000"
GATEWAY = f"https://{DEV}:3000"
REPOSITORY = "demo/inventory"
COMPANY_NAME = "Tarkado Demo Co (DEMO)"
PERSONAS = {
    "owner": {"role": "admin", "port": None},
    "senior": {"role": "senior", "port": 4101},
    "junior": {"role": "junior", "port": 4102},
}
ALIASES = {"company/luna": "team-luna", "company/sol": "team-sol"}
PROVIDER_MODELS = {"team-luna": "gpt-5.6-luna", "team-sol": "gpt-5.6-sol", "company-cheap": "gpt-5.6-luna"}
# DEMO list prices, USD per 1M tokens: input, cached input, output.
PRICES = {"gpt-5.6-luna": (Decimal("0.20"), Decimal("0.02"), Decimal("1.20")),
          "gpt-5.6-sol": (Decimal("4.00"), Decimal("0.40"), Decimal("20.00"))}
TASKS = json.loads((DEMO / "tasks.json").read_text())
DENIED_TOOLS = ("shell", "execute", "webfetch", "websearch", "subagent", "skill", "question")
ALLOWED_TOOLS = ("read", "glob", "grep", "edit", "write")


# ---------------------------------------------------------------- utilities

def log(message):
    line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {message}"
    print(line, flush=True)
    RUN.mkdir(parents=True, exist_ok=True)
    with open(RUN / "transcript.log", "a") as stream:
        stream.write(line + "\n")


def write_private(path, value, *, raw=False):
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb" if raw else "w") as stream:
        if raw:
            stream.write(value)
        elif isinstance(value, str):
            stream.write(value)
        else:
            json.dump(value, stream, indent=1, sort_keys=True)
    os.replace(temporary, path)


def read_json(path):
    return json.loads(Path(path).read_text())


def load_state():
    path = STATE / "state.json"
    return read_json(path) if path.exists() else {}


def save_state(state):
    path = STATE / "state.json"
    path.write_text(json.dumps(state, indent=1, sort_keys=True))


def personas():
    return read_json(PRIVATE / "personas.json")


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def git(repo, *args):
    # Never let git search above the demo directory: a checkout that lost its .git would
    # otherwise resolve to the enclosing workspace repository, where "checkout -f",
    # "reset --hard" and "clean -fdx" would destroy real files.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(Path(repo).resolve().parent)}
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()


def cost_of(model, usage):
    price_in, price_cached, price_out = PRICES[model]
    cached = usage.get("cache_read", 0)
    fresh = usage["input"] - cached if usage["input"] >= cached else usage["input"]
    total = (Decimal(fresh) * price_in + Decimal(cached) * price_cached + Decimal(usage["output"]) * price_out) / Decimal(1_000_000)
    return total.quantize(Decimal("0.000001"))


def stack_signal(sig):
    """Signal the running stack supervisor; False when the stack is not running."""
    try:
        os.kill(int((RUN / "stack.pid").read_text()), sig)
        return True
    except (FileNotFoundError, ProcessLookupError, ValueError):
        return False


def wait_for(check, what, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {what}.")


def company_ids():
    with sqlite3.connect(STORE / "company.sqlite3") as db:
        row = db.execute("SELECT company_id, deployment_id FROM company_company").fetchone()
    return tuple(str(uuid.UUID(value)) for value in row)  # SQLite stores UUIDs as bare hex


# ---------------------------------------------------------------- browser sessions

_browsers = {}


def code(name):
    """A fresh authenticator code; the last used window survives runner restarts."""
    people = personas()
    client = browser(name)
    client.last_window = people[name].get("last_window")
    value = client.code()
    people[name]["last_window"] = client.last_window
    write_private(PRIVATE / "personas.json", people)
    return value


def browser(name):
    if name in _browsers:
        return _browsers[name]
    person = personas()[name]
    client = Browser(COMPANY, name)
    page = client.submit("/login/", {"username": name, "password": person["password"]}, "username")
    _browsers[name] = client
    if person.get("seed"):
        client.enroll(person["seed"])
        if "/security/mfa/verify/" in page.path or 'name="code"' in page.html:
            page = client.submit("/security/mfa/verify/", {"code": code(name)}, "code")
    if f"Signed in as {name}" not in page.html:
        del _browsers[name]
        raise RuntimeError(f"{name} sign-in did not complete: {text_of(page.html)[:300]}")
    return client


def checkbox_labels(html, name):
    found = re.findall(r'<input[^>]*name="%s"[^>]*value="([^"]+)"[^>]*>\s*([^<]*)</label>' % re.escape(name), html)
    found += re.findall(r'<input[^>]*value="([^"]+)"[^>]*name="%s"[^>]*>\s*([^<]*)</label>' % re.escape(name), html)
    return {key: unescape(text).strip() for key, text in found}


def form_errors(html):
    found = [text_of(item) for item in re.findall(r'<ul class="errorlist[^"]*"[^>]*>(.*?)</ul>', html, re.S)]
    return " | ".join(found) or text_of(html)[-600:]


def secure_submit(name, path, values, field, *, page=None, expect=(200,)):
    """Submit a form, adding the password and a fresh code only where the page asks."""
    client = browser(name)
    page = page or client.get(path)
    form = Forms(page.html).containing(field)
    extra = {}
    if "confirm_password" in form["values"]:
        extra["confirm_password"] = personas()[name]["password"]
    if "code" in form["values"]:
        extra["code"] = code(name)
    return client.submit(path, {**values, **extra}, field, page=page, expect=expect)


# ---------------------------------------------------------------- OpenCode

def oc_paths(name):
    base = WORK / name / "oc"
    return {"home": base / "home", "config": base / "xdg" / "config", "data": base / "xdg" / "data",
            "cache": base / "xdg" / "cache", "state": base / "xdg" / "state"}


def oc_config(base_url, plugin=None):
    models = {alias: {"modelID": alias, "limit": {"context": 400000 if alias == "team-sol" else 128000,
                                                   "output": 16384 if alias == "team-sol" else 4096}}
              for alias in ("team-luna", "team-sol", "company-cheap")}
    config = {"$schema": "https://opencode.ai/config.json", "update": "disable", "share": "disabled",
              # Normal (unrouted) work starts on the developer's usual model. company-cheap is
              # reserved for bound Tarkado tasks and the gateway refuses it anywhere else.
              "model": "company/team-sol",
              "providers": {"company": {"name": "Company gateway (DEMO)", "env": ["COMPANY_GATEWAY_KEY"],
                                        "package": "@opencode/ai/providers/openai-compatible",
                                        "settings": {"baseURL": base_url}, "models": models}},
              "permissions": [{"action": tool, "resource": "*", "effect": "allow"} for tool in ALLOWED_TOOLS]
              + [{"action": tool, "resource": "*", "effect": "deny"} for tool in DENIED_TOOLS],
              # Only the company gateway. Without this OpenCode 2.0.21 also loads its built-in
              # free hosted models and defaults to one, so a prompt typed outside a bound task
              # silently leaves the company (seen on the laptop TUI run). Last match wins.
              "experimental": {"policies": [{"action": "provider.use", "resource": "*", "effect": "deny"},
                                            {"action": "provider.use", "resource": "company", "effect": "allow"}]}}
    if plugin:
        config["plugins"] = [{"package": str(ROOT / "integrations" / "opencode" / "delivery"), "options": plugin}]
    return config


def write_oc_config(name, plugin=None):
    path = oc_paths(name)["config"] / "opencode" / "opencode.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(oc_config(GATEWAY + "/v1", plugin), indent=1))


def start_opencode(name, restart=False):
    """The stack supervisor runs the server; the runner only flips its flags."""
    port = PERSONAS[name]["port"]
    (RUN / f"opencode-{name}.enabled").touch()
    if restart:
        (RUN / f"opencode-{name}.restart").touch()
        time.sleep(4)

    def listening():
        if (RUN / f"opencode-{name}.restart").exists():
            return False
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    wait_for(listening, f"OpenCode server for {name} (is the stack workflow running?)", 90)
    log(f"OpenCode server for {name} is listening on 127.0.0.1:{port}")


def driver(name, command, timeout=1200):
    person = personas()[name]
    command = {"url": f"http://127.0.0.1:{PERSONAS[name]['port']}", "directory": str(WORK / name / "repo"), **command}
    env = {"PATH": os.environ["PATH"], "OC_PASSWORD": person["opencode_password"], "HOME": str(oc_paths(name)["home"])}
    completed = subprocess.run(["node", str(DEMO / "opencode_driver.mjs"), json.dumps(command)], cwd=DEMO, env=env,
                               capture_output=True, text=True, timeout=timeout)
    line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    if not line:
        raise RuntimeError(f"OpenCode driver produced no result: {completed.stderr[-800:]}")
    result = json.loads(line)
    if not result["ok"]:
        raise RuntimeError(f"OpenCode driver ({command['op']}) failed: {result['error']}")
    return result["value"]


def instruction(task):
    module = task["target"].removesuffix(".py").replace("/", ".")
    test_file = "tests/test_" + module.rsplit(".", 1)[1] + "_generated.py"
    return TASKS["instructions"][task["category"]].format(target=task["target"], module=module, test_file=test_file)


def clone_checkout(name):
    """Per-developer clone whose git directory sits beside the checkout (not a nested .git
    folder, which this workspace has lost before)."""
    repo = WORK / name / "repo"
    git(WORK, "clone", "-q", f"--separate-git-dir={WORK / name / 'repo-git'}", str(WORK / "origin.git"), str(repo))


def fresh_checkout(name, task_id):
    repo = WORK / name / "repo"
    if not (repo / ".git").exists():
        raise RuntimeError(f"{repo} is not a git checkout (its .git is missing); re-clone it before running tasks.")
    base = load_state()["base_commit"]
    git(repo, "checkout", "-q", "-f", "main")
    git(repo, "reset", "-q", "--hard", base)
    git(repo, "clean", "-q", "-fdx")
    git(repo, "checkout", "-q", "-B", f"task/{task_id}", base)
    return repo, base


def run_ci(name, task, task_id, session_id):
    repo = WORK / name / "repo"
    key = (PRIVATE / "ci.key").read_bytes()
    record = demo_ci.record(STATE / "ci-ledger", key, task_id=task_id, session_id=session_id, developer=name, repo=repo,
                            base_commit=load_state()["base_commit"], category=task["category"], target=task["target"])
    git(repo, "-c", "user.name=" + name, "-c", f"user.email={name}@demo.invalid", "commit", "-q", "--allow-empty", "-m", f"{task_id} (demo)")
    log(f"  CI {record['record_id'][:8]}: passed={record['passed']} checks={record['checks']} tests_ran={record['tests_ran']}")
    return record


# ---------------------------------------------------------------- stage: setup

def capture_tool_definitions():
    """Host validation: capture the exact local tool definitions the installed
    OpenCode sends with this demo's permissions, against a loopback stub."""
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            for tool in body.get("tools") or []:
                captured[tool["function"]["name"]] = tool["function"]
            usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                     "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}}
            model = body.get("model", "stub")
            chunks = [{"id": "s", "object": "chat.completion.chunk", "created": 0, "model": model,
                       "choices": [{"index": 0, "delta": {"role": "assistant", "content": "OK"}, "finish_reason": None}]},
                      {"id": "s", "object": "chat.completion.chunk", "created": 0, "model": model,
                       "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                      {"id": "s", "object": "chat.completion.chunk", "created": 0, "model": model, "choices": [], "usage": usage}]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.close_connection = True

        def do_GET(self):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    scratch = WORK / "host-validation"
    shutil.rmtree(scratch, ignore_errors=True)
    project = scratch / "project"
    project.mkdir(parents=True)
    git(project, "init", "-q")
    env = {"PATH": os.environ["PATH"], "HOME": str(scratch / "home"), "XDG_CONFIG_HOME": str(scratch / "config"),
           "XDG_DATA_HOME": str(scratch / "data"), "XDG_CACHE_HOME": str(scratch / "cache"), "XDG_STATE_HOME": str(scratch / "state"),
           "COMPANY_GATEWAY_KEY": "host-validation-stub", "LANG": "C.UTF-8"}
    config = oc_config(f"http://127.0.0.1:{server.server_address[1]}/v1")
    (scratch / "config" / "opencode").mkdir(parents=True)
    (scratch / "config" / "opencode" / "opencode.json").write_text(json.dumps(config, indent=1))
    try:
        subprocess.run([OPENCODE, "run", "--standalone", "--format", "json", "-m", "company/company-cheap", "Reply OK."],
                       cwd=project, env=env, capture_output=True, text=True, timeout=180)
    finally:
        server.shutdown()
    version = subprocess.run([OPENCODE, "--version"], env=env, capture_output=True, text=True, timeout=60).stdout.strip()
    shutil.rmtree(scratch, ignore_errors=True)
    from engine.delivery_contract import function_fingerprint
    missing = [name for name in ALLOWED_TOOLS if name not in captured]
    if missing:
        raise RuntimeError(f"Host validation did not observe tools {missing}; captured {sorted(captured)}.")
    permissions = config["permissions"]
    verified = now()
    return {"record": "demo-host-validation-v1", "opencode_version": version, "gateway_model": "company-cheap",
            "tools": {name: function_fingerprint(captured[name]) for name in ALLOWED_TOOLS},
            "offered_tools": sorted(captured), "permissions_sha256": hashlib.sha256(json.dumps(permissions, sort_keys=True).encode()).hexdigest(),
            "verified_at": verified.isoformat(), "valid_until": (verified + timedelta(days=3)).isoformat()}


def litellm_config(with_callback):
    lines = ["# DEMO LiteLLM config (generated by run_loop.py; private).", "model_list:"]
    for alias in ("team-luna", "team-sol"):
        lines += [f"  - model_name: {alias}", "    litellm_params:", f"      model: openai/{PROVIDER_MODELS[alias]}",
                  "      api_base: os.environ/AI_INTEGRATIONS_OPENAI_BASE_URL", "      api_key: os.environ/AI_INTEGRATIONS_OPENAI_API_KEY",
                  "      reasoning_effort: none", "      extra_body:", "        prompt_cache_options:", "          mode: explicit"]
    # The managed alias carries no provider settings: the Tarkado hook adds the
    # reviewed ones after validating the client's own request.
    lines += ["  - model_name: company-cheap", "    litellm_params:", "      model: openai/gpt-5.6-luna",
              "      api_base: os.environ/AI_INTEGRATIONS_OPENAI_BASE_URL", "      api_key: os.environ/AI_INTEGRATIONS_OPENAI_API_KEY",
              "    model_info:", "      id: demo-company-cheap-luna",
              "litellm_settings:", "  num_retries: 0", "  request_timeout: 600", "  drop_params: false"]
    if with_callback:
        lines += ["  callbacks: integrations.litellm.tarkado_callbacks.callback"]
    # custom_auth handles every request; the random master key is never handed out.
    lines += ["router_settings:", "  num_retries: 0", "general_settings:", "  custom_auth: demo_gateway_auth.user_api_key_auth",
              "  master_key: os.environ/LITELLM_MASTER_KEY"]
    return "\n".join(lines) + "\n"


def stage_setup():
    if not DEV:
        raise SystemExit("REPLIT_DEV_DOMAIN is required.")
    for path in (STATE, RUN, WORK):
        path.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(PRIVATE, 0o700)
    if not (PRIVATE / "personas.json").exists():
        write_private(PRIVATE / "personas.json", {name: {"password": secrets.token_urlsafe(24), "gateway_key": secrets.token_urlsafe(32),
                                                         "opencode_password": secrets.token_urlsafe(24), "seed": None}
                                                  for name in PERSONAS})
        log("Generated persona passwords, gateway keys and OpenCode server passwords (private).")
    people = personas()
    write_private(PRIVATE / "gateway-keys.json", {hashlib.sha256(people[name]["gateway_key"].encode()).hexdigest(): f"employee-{name}"
                                                  for name in PERSONAS if name != "owner"})
    if not (PRIVATE / "litellm-master.key").exists():
        write_private(PRIVATE / "litellm-master.key", "sk-" + secrets.token_hex(32))
    if not (PRIVATE / "ci.key").exists():
        write_private(PRIVATE / "ci.key", secrets.token_bytes(32), raw=True)
    if not (STORE / "company.sqlite3").exists():
        completed = subprocess.run([PYTHON, "-m", "engine", "company", "bootstrap", "--store", str(STORE), "--name", COMPANY_NAME,
                                    "--username", "owner", "--policy", str(DEMO / "policy.json"), "--repositories", REPOSITORY,
                                    "--company-api", "--pilot-approver"], cwd=ROOT,
                                   input=people["owner"]["password"] + "\n" + people["owner"]["password"] + "\n",
                                   text=True, capture_output=True, start_new_session=True, timeout=120)
        if completed.returncode:
            raise SystemExit("Bootstrap failed: " + completed.stderr[-800:])
        log("Bootstrapped the company store with owner as administrator + designated pilot approver.")
    company_id, deployment_id = company_ids()
    write_private(PRIVATE / "deployment.json", {"public_origin": COMPANY, "https_proxy_configured": True, "private_single_host": True,
                                               "backup_policy": "DEMO: local single-host store; back up before changes with `engine company backup`.",
                                               "operator_contact": "demo-operator"})
    if not (PRIVATE / "host-validation.json").exists():
        write_private(PRIVATE / "host-validation.json", capture_tool_definitions())
        log("Host validation captured the installed OpenCode local tool definitions.")
    write_private(PRIVATE / "integration-config.json", {
        "company_id": company_id, "deployment_id": deployment_id, "ci_ledger_dir": str(STATE / "ci-ledger"),
        "ci_key_file": str(PRIVATE / "ci.key"), "criteria_sha256": demo_ci.criteria_sha256(),
        "assessment_dir": str(STATE / "assessments"), "host_validation_file": str(PRIVATE / "host-validation.json"),
        "min_senior_successes": 3, "min_senior_sessions": 3})
    source = (DEMO / "tarkado_demo_integration.py").read_bytes()
    write_private(PRIVATE / "integration-manifest.json", {"schema_version": 1, "company_id": company_id, "deployment_id": deployment_id,
                                                         "module": "tarkado_demo_integration", "factory": "create",
                                                         "source_sha256": hashlib.sha256(source).hexdigest()})
    write_private(PRIVATE / "litellm.yaml", litellm_config((PRIVATE / "gateway-config.json").exists()))
    # Shared origin repository and one checkout per developer.
    state = load_state()
    origin = WORK / "origin.git"
    if not origin.exists():
        seed = WORK / "seed"
        shutil.rmtree(seed, ignore_errors=True)
        shutil.copytree(DEMO / "sample_repo", seed, ignore=shutil.ignore_patterns("__pycache__"))
        git(seed, "init", "-q", "-b", "main")
        (seed / ".gitignore").write_text("__pycache__/\n")
        git(seed, "add", "-A")
        git(seed, "-c", "user.name=demo", "-c", "user.email=demo@demo.invalid", "commit", "-q", "-m", "Inventory demo repository")
        git(WORK, "clone", "-q", "--bare", str(seed), str(origin))
        shutil.rmtree(seed)
        state["base_commit"] = git(origin, "rev-parse", "HEAD")
        save_state(state)
    for name in ("senior", "junior"):
        repo = WORK / name / "repo"
        if not repo.exists():
            clone_checkout(name)
        write_oc_config(name)
    link = DEMO / "node_modules"
    if not link.exists():
        link.symlink_to(ROOT / "local" / "opencode-host" / "node_modules")
    (RUN / "litellm.enabled").touch()
    stack_signal(signal.SIGHUP)
    log(f"Setup complete. Company {company_id[:8]}..., base commit {state['base_commit'][:10]}.")


# ---------------------------------------------------------------- stage: people

def enroll_mfa(name):
    people = personas()
    if people[name].get("seed"):
        return
    client = Browser(COMPANY, name)
    client.submit("/login/", {"username": name, "password": people[name]["password"]}, "username")
    page = client.submit("/security/mfa/setup/", {"confirm_password": people[name]["password"]}, "confirm_password")
    seed = re.search(r'<pre id="setup-secret">([A-Z2-7]+)</pre>', page.html)
    if not seed:
        raise RuntimeError(f"MFA setup for {name} did not show a seed: {text_of(page.html)[:300]}")
    client.enroll(seed.group(1))
    client.last_window = people[name].get("last_window")
    page = client.submit("/security/mfa/confirm/", {"code": client.code()}, "code")
    if "Authenticator confirmed" not in page.html and "backup" not in page.html.lower():
        raise RuntimeError(f"MFA confirm for {name} failed: {text_of(page.html)[:300]}")
    people[name]["seed"] = seed.group(1)
    people[name]["last_window"] = client.last_window
    write_private(PRIVATE / "personas.json", people)
    log(f"{name} enrolled an authenticator (TOTP).")


def stage_people():
    enroll_mfa("owner")
    people = personas()
    for name in ("senior", "junior"):
        if people[name].get("joined"):
            continue
        page = secure_submit("owner", "/invitations/", {"username": name, "role": PERSONAS[name]["role"], "participating": "on",
                                                        "expires_at": (now() + timedelta(hours=2)).isoformat(),
                                                        "reason": "DEMO full loop: participating developer"}, "username")
        token = re.search(r"<pre>([A-Za-z0-9_-]{43})</pre>", page.html)
        if not token:
            raise RuntimeError(f"Invitation for {name} failed: {text_of(page.html)[:400]}")
        joiner = Browser(COMPANY, name)
        joiner.submit("/join/", {"invitation": token.group(1), "password1": people[name]["password"],
                                 "password2": people[name]["password"]}, "invitation")
        people[name]["joined"] = True
        write_private(PRIVATE / "personas.json", people)
        log(f"owner invited {name} ({PERSONAS[name]['role']}, participating); {name} joined.")
        enroll_mfa(name)
        people = personas()


# ---------------------------------------------------------------- stage: shadow

def record_task(name, task, task_id, session_id):
    client = browser(name)
    page = client.submit("/tasks/new/", {"task_id": task_id, "session_id": session_id, "source_kind": "team",
                                          "boundary": "new_task", "task_type": task["category"], "risk_tags": "low",
                                          "required_tools": "read,edit", "context_tokens": 20000,
                                          "selected_model": task["selected_model"], "repository_ref": REPOSITORY}, "task_id")
    suggestion = re.search(r"Suggested: ([A-Za-z0-9_./-]+)", text_of(page.html))
    return page.path, (suggestion.group(1).rstrip(".") if suggestion else None), page


def task_action(name, path, action, values, field):
    client = browser(name)
    page = client.submit(path + action + "/", values, field)
    return page


def stage_shadow(only=None):
    state = load_state()
    state.setdefault("shadow", {})
    for name in ("senior", "junior"):
        start_opencode(name)
    for task in TASKS["shadow"]:
        if only and task["id"] not in only:
            continue
        done = state["shadow"].get(task["id"], {})
        if done.get("result"):
            continue
        name = task["persona"]
        task_id = f"demo-{task['id'].lower()}"
        session_id = f"demo-session-{task['id'].lower()}"
        log(f"[{task['id']}] {name} records a {task['category']} task on {task['target']} (selected {task['selected_model']}).")
        if not done.get("path"):
            path, suggestion, _ = record_task(name, task, task_id, session_id)
            done.update(path=path, suggestion=suggestion)
            state["shadow"][task["id"]] = done
            save_state(state)
        log(f"[{task['id']}] Tarkado shadow suggestion: {done['suggestion']}")
        if not done.get("response"):
            task_action(name, done["path"], "response", {"response": task["response"]}, "response")
            done["response"] = task["response"]
            save_state(state)
        log(f"[{task['id']}] {name} {task['response']}s the suggestion.")
        model = done["suggestion"] if task["response"] == "accept" and done["suggestion"] else task["selected_model"]
        alias = ALIASES[model]
        if not done.get("run"):
            repo, base = fresh_checkout(name, task_id)
            log(f"[{task['id']}] {name} runs OpenCode with {model} (gateway alias {alias}).")
            run = driver(name, {"op": "shadow", "model": alias, "text": instruction(task)})
            run["cost_usd"] = str(cost_of(PROVIDER_MODELS[alias], run["session_usage"] or run["usage"]))
            done["run"] = {key: run[key] for key in ("sessionID", "latency_ms", "failure", "outcome", "usage", "session_usage",
                                                     "steps", "models", "finishes", "errors", "cost_usd")}
            save_state(state)
            log(f"[{task['id']}] OpenCode finished ({run['outcome']}): steps={run['steps']} usage={run['usage']} "
                f"session_total={run['session_usage']} latency={run['latency_ms']}ms cost=${run['cost_usd']} failure={run['failure']}")
        if not done.get("execution"):
            task_action(name, done["path"], "execution", {"actual_model": model}, "actual_model")
            done["execution"] = model
            save_state(state)
            log(f"[{task['id']}] {name} reports the model actually used: {model}.")
        if not done.get("ci"):
            record = run_ci(name, task, task_id, session_id)
            done["ci"] = {"record_id": record["record_id"], "passed": record["passed"], "tests_passed": record["tests_passed"]}
            save_state(state)
        ci = done["ci"]
        values = {"desired_result": "true" if ci["passed"] else "false", "tests_passed": "true" if ci["tests_passed"] else "false",
                  "cost_usd": done["run"]["cost_usd"], "latency_ms": done["run"]["latency_ms"], "evidence_ref": "ci:" + ci["record_id"]}
        page = task_action(name, done["path"], "result", values, "desired_result")
        done["result"] = {key: values[key] for key in ("desired_result", "tests_passed", "cost_usd", "evidence_ref")}
        save_state(state)
        log(f"[{task['id']}] {name} records the result: desired={values['desired_result']} tests={values['tests_passed']} "
            f"cost=${values['cost_usd']} evidence={values['evidence_ref'][:11]}...")


# ---------------------------------------------------------------- stage: review

def review_summary(html):
    text = text_of(html)
    start = text.find("Category evidence review")
    return text[start:start + 1600] if start >= 0 else text[:1600]


def stage_review(label="initial"):
    state = load_state()
    expected = {f"demo-session-{task['id'].lower()}" for task in TASKS["shadow"]}
    path = "/pilots/reviews/new/?source=team"
    page = browser("owner").get(path)
    # Sessions are offered as opaque keys with a "<owner> / <session> — n task(s)" label.
    # The review declares every recorded team session, including routed ones.
    labels = checkbox_labels(page.html, "session_ids")
    offered = {text.split(" / ", 1)[-1].split(" —")[0].strip() for text in labels.values()}
    if expected - offered:
        raise RuntimeError(f"Review page does not offer sessions {sorted(expected - offered)}.")
    chosen = sorted(labels)
    sessions = sorted(labels.values())
    values = {"learner_version": f"demo-{label}-v1", "source_kind": "team", "cutoff": now().isoformat(), "session_ids": chosen,
              "task_types": ["documentation", "test_generation"], "min_senior_successes": 3, "min_senior_sessions": 3}
    page = secure_submit("owner", path, values, "learner_version", page=page)
    if "/pilots/reviews/" not in page.path or "/new/" in page.path:
        raise RuntimeError("Review was refused: " + form_errors(page.html))
    state.setdefault("reviews", {})[label] = {"path": page.path}
    save_state(state)
    log(f"owner created the {label} category evidence review ({len(sessions)} sessions, DEMO thresholds 3 senior successes / 3 sessions).")
    log("  " + review_summary(page.html))
    return page


def review_ref(label):
    return load_state()["reviews"][label]["path"].rstrip("/").rsplit("/", 1)[1]


def stage_publish(label="initial"):
    """Publish the reviewed learner for manual suggestions (owner, password + fresh code)."""
    path = f"/learning/reviews/{review_ref(label)}/publish/"
    page = secure_submit("owner", path, {"action": "publish", "repositories": [REPOSITORY], "confirmation": "on",
                                         "reason": f"DEMO full loop: publish the {label} reviewed learner for manual suggestions"}, "expected_sequence")
    if page.path.startswith(path):
        raise RuntimeError("Publication was refused: " + form_errors(page.html))
    state = load_state()
    state["reviews"][label]["published"] = True
    save_state(state)
    log(f"owner published the {label} learner for manual suggestions on {REPOSITORY}.")


# ---------------------------------------------------------------- stage: approve

def preview_then_confirm(name, path, values, field, *, page=None):
    """Two-step browser confirmation: an exact scope preview, then password + fresh code."""
    page = secure_submit(name, path, {**values, "preview": "scope"}, field, page=page)
    form = Forms(page.html).containing(field)
    if not form["values"].get("confirmation_token"):
        raise RuntimeError(f"Preview at {path} was refused: " + form_errors(page.html))
    return secure_submit(name, path, {"confirmation": "on"}, "confirmation_token", page=page)


def selection_summary(html):
    text = text_of(html)
    start = text.find("Conditional scoped selection")
    return text[start:start + 700]


def stage_approve(label="initial", pilot_id="demo-documentation-luna", task_types="documentation"):
    state = load_state()
    if not state.get("pilot"):
        path = state["reviews"][label]["path"] + "authorize/"
        page = browser("owner").get(path)
        developers = [key for key, _ in Forms(page.html).containing("pilot_id")["options"]["developer_ids"]]
        types = [value for value in task_types.split(",") if value]
        values = {"pilot_id": pilot_id, "repository_ref": REPOSITORY, "task_types": types,
                  "developer_ids": developers, "max_tasks": 8, "max_cost_usd": "0.50",
                  "expires_at": (now() + timedelta(hours=10)).isoformat(), "target": "live", "decision": "approve",
                  "reason": f"DEMO full loop: limited automatic-routing pilot, {' + '.join(types)} -> company/luna"}
        page = preview_then_confirm("owner", path, values, "pilot_id", page=page)
        if "/pilots/reviews/" in page.path:
            raise RuntimeError("Live scope authorization was refused: " + form_errors(page.html))
        state["pilot"] = {"path": page.path, "pilot_id": pilot_id, "review": label}
        save_state(state)
        log(f"owner (designated approver) authorized live scope: {', '.join(types)} -> company/luna for {developers}, "
            f"max 8 tasks / $0.50, readiness verified by the server. Pilot page {page.path}")
    pilot = state["pilot"]
    if not pilot.get("active"):
        # Live scope approval never permits a model call; conditional selection is
        # its own separately confirmed control.
        path = pilot["path"] + "selection/"
        page = preview_then_confirm("owner", path, {"action": "activate", "reason": "DEMO full loop: activate conditional selection for the approved pilot"}, "reason")
        if "errorlist" in page.html:
            raise RuntimeError("Activation was refused: " + form_errors(page.html))
        pilot["active"] = True
        save_state(state)
        log("owner activated conditional selection for the pilot (fresh password + authenticator code).")
        log("  " + selection_summary(page.html))


# ---------------------------------------------------------------- stage: delivery

def gateway_up():
    """LiteLLM answers through the bridge (a bad key gets 401, never a model call)."""
    import urllib.error
    import urllib.request
    request = urllib.request.Request(GATEWAY + "/v1/chat/completions", data=b"{}", method="POST",
                                     headers={"Authorization": "Bearer invalid-demo-probe", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        return error.code == 401
    except OSError:
        return False
    return False


def restart_litellm():
    write_private(PRIVATE / "litellm.yaml", litellm_config((PRIVATE / "gateway-config.json").exists()))
    if not stack_signal(signal.SIGHUP):
        raise RuntimeError("The stack workflow is not running.")
    time.sleep(5)
    wait_for(gateway_up, "LiteLLM to come back up behind the gateway", 180)


def issue_gateway(state):
    page = browser("owner").get("/gateways/")
    labels = dict(re.findall(r'<label for="id_(user_\d+)">LiteLLM authenticated user ID for ([^<]+)</label>', page.html))
    mapping = {field: f"employee-{developer.strip().rstrip(':')}" for field, developer in labels.items()
               if developer.strip().rstrip(':') in ("senior", "junior")}
    if len(mapping) != 2:
        raise RuntimeError(f"Gateway form did not offer both developers: {sorted(labels.values())}")
    page = secure_submit("owner", "/gateways/", {"gateway_id": "demo-litellm-gateway", "repository_ref": REPOSITORY, "confirmation": "on",
                                                 "expires_at": (now() + timedelta(hours=20)).isoformat(), **mapping}, "gateway_id", page=page)
    value = re.search(r'<pre id="gateway-credential">([A-Za-z0-9_-]{43})</pre>', page.html)
    reference = re.search(r"Gateway reference ([0-9a-f-]{36})", text_of(page.html))
    if not value or not reference:
        raise RuntimeError("Gateway identity was refused: " + form_errors(page.html))
    write_private(PRIVATE / "gateway-credential.json", {"origin": COMPANY, "credential": value.group(1)})
    # Version 2: the single reviewed provider endpoint (the same value LiteLLM's
    # deployment resolves from its environment) and gateway-owned settings.
    write_private(PRIVATE / "gateway-config.json", {
        "schema_version": 2, "company_origin": COMPANY, "credential_file": str(PRIVATE / "gateway-credential.json"),
        "managed_aliases": ["company-cheap"], "managed_deployment_ids": ["demo-company-cheap-luna"], "timeout_seconds": 20,
        "provider_api_base": os.environ["AI_INTEGRATIONS_OPENAI_BASE_URL"],
        "provider_request_overrides": {"reasoning_effort": "none", "extra_body": {"prompt_cache_options": {"mode": "explicit"}}}})
    state["gateway"] = {"reference": reference.group(1)}
    save_state(state)
    log(f"owner issued the gateway identity {reference.group(1)[:8]}... (employee-senior/junior mapped; credential stored privately).")


def pair(name, state):
    repo = WORK / name / "repo"
    page = secure_submit(name, "/connectors/", {"name": f"{name}-opencode", "repository_ref": REPOSITORY, "directory": str(repo),
                                                "expires_at": (now() + timedelta(hours=20)).isoformat(), "source_kind": "team",
                                                "confirmation": "on"}, "directory")
    value = re.search(r'<pre id="connector-credential">([A-Za-z0-9_-]{43})</pre>', page.html)
    if not value:
        raise RuntimeError(f"Pairing for {name} was refused: " + form_errors(page.html))
    write_private(PRIVATE / f"connector-{name}.json", {"origin": COMPANY, "credential": value.group(1)})
    state.setdefault("paired", {})[name] = True
    save_state(state)
    log(f"{name} paired an OpenCode connector for {REPOSITORY} (credential stored privately, 0600).")


def stage_laptop(name, directory, bundle):
    """Kit for a developer laptop running only OpenCode + the Tarkado plugin against this
    stack: pair one more connector for `name` scoped to the laptop's exact repository
    directory, and write a private bundle (credentials included, DEMO only) that
    demo/laptop/start-demo.mjs consumes. Never committed; download it, keep it private."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", bundle):
        raise SystemExit("Bundle name: letters, digits, '-' or '_' only.")
    state = load_state()
    page = secure_submit(name, "/connectors/", {"name": f"{name}-laptop-{bundle}", "repository_ref": REPOSITORY, "directory": directory,
                                                "expires_at": (now() + timedelta(hours=23)).isoformat(), "source_kind": "team",
                                                "confirmation": "on"}, "directory")
    value = re.search(r'<pre id="connector-credential">([A-Za-z0-9_-]{43})</pre>', page.html)
    if not value:
        raise RuntimeError(f"Laptop pairing for {name} was refused: " + form_errors(page.html))
    person = read_json(PRIVATE / "personas.json")[name]
    config = oc_config(GATEWAY + "/v1")
    (STATE / "laptop").mkdir(mode=0o700, exist_ok=True)
    write_private(STATE / "laptop" / f"{bundle}.json", {
        "schema": "tarkado-demo-laptop-v1", "persona": name, "directory": directory, "opencode_version": "2.0.21",
        "company_origin": COMPANY, "gateway_key": person["gateway_key"],
        "connector": {"origin": COMPANY, "credential": value.group(1)},
        "plugin_options": {"privateDeveloperService": True, "gatewayRef": state["gateway"]["reference"], "providerID": "company",
                           "gatewayOrigin": GATEWAY + "/",
                           # One-confirmation start: the same bounds the reviewed routed runs use.
                           "quickStart": {"selectedModel": "company/sol", "requiredTools": ["read", "edit"], "contextTokens": 20000,
                                          "outputLimit": 4096, "taskCapUSD": "0.10", "labelPrefix": name}},
        "opencode_config": config, "tool_fingerprints": read_json(PRIVATE / "host-validation.json")["tools"]})
    log(f"{name} paired a laptop connector for {directory} (bundle local/full-loop/laptop/{bundle}.json, private, connector expires in 23h).")


def close_binding(binding, why):
    closed = gateway_call("close", {"binding_ref": binding})
    log(f"gateway operator closed cost record {binding[:8]}... ({why}): " + json.dumps(
        {key: closed.get(key) for key in ("closed", "known_cost_usd", "unknown_attempts")}, sort_keys=True))
    return closed


def stage_settle(task_ref):
    """Manual fallback: close one task's cost record now. Normally nothing is needed: the
    company settles a task itself when the developer ends it, or when its last cost arrives."""
    if not re.fullmatch(r"[0-9a-f-]{36}", task_ref):
        raise SystemExit("Give the task reference from /tarkado-delivery-browser (/tasks/<ref>/).")
    task_path = f"/tasks/{task_ref}/"
    binding = binding_ref_of(task_path)
    if not binding:
        raise SystemExit("That task has no gateway binding.")
    close_binding(binding, f"manual settle of task {task_ref[:8]}...")
    log("  " + delivery_line(browser("owner").get(task_path).html))


def plugin_options(name):
    return {"privateDeveloperService": True, "credentialFile": str(PRIVATE / f"connector-{name}.json"),
            "gatewayRef": load_state()["gateway"]["reference"], "providerID": "company", "gatewayOrigin": GATEWAY + "/"}


def stage_delivery():
    state = load_state()
    if not state.get("gateway"):
        issue_gateway(state)
    restart_litellm()
    log("LiteLLM restarted with the Tarkado delivery callback (gateway config v2).")
    for name in ("senior", "junior"):
        if not state.get("paired", {}).get(name):
            pair(name, state)
        write_oc_config(name, plugin_options(name))
        start_opencode(name, restart=True)
        connected = driver(name, {"op": "connect"})
        log(f"{name}'s OpenCode delivery plugin connected: " + json.dumps(connected, sort_keys=True)[:600])


# ---------------------------------------------------------------- gateway operator + recovery

def gateway_call(operation, payload):
    """The gateway operator's metadata-only machine API (no browser session, no Origin)."""
    import urllib.error
    import urllib.request
    credential = read_json(PRIVATE / "gateway-credential.json")["credential"]
    request = urllib.request.Request(f"{COMPANY}/api/delivery/v1/{operation}/", data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + credential, "Content-Type": "application/json",
                                              "User-Agent": "tarkado-demo-gateway-operator/1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Gateway {operation} refused ({error.code}): {error.read().decode(errors='replace')[:400]}")


def binding_ref_of(task_path):
    page = browser("owner").get(task_path)
    found = re.search(r"/delivery/([0-9a-f-]{36})/correct-cost/", page.html)
    return found.group(1) if found else None


def delivery_line(html):
    text = text_of(html)
    start = text.find("Supported gateway request/usage accounting")
    return text[start:start + 420] if start >= 0 else "(no delivery accounting on this task)"


def recover_task(name, task_path, why):
    """Documented recovery for a start whose bound session was lost: the gateway
    closes the binding (no attempts -> cancelled, $0, reserve released; the slot
    stays consumed) and the developer ends the observation with a permanent gap."""
    binding = binding_ref_of(task_path)
    if binding:
        closed = gateway_call("close", {"binding_ref": binding})
        log(f"  gateway operator closed binding {binding[:8]}...: closed={closed.get('closed')} known_cost={closed.get('known_cost_usd')} "
            f"unknown_attempts={closed.get('unknown_attempts')}")
    reference = task_path.strip("/").rsplit("/", 1)[1]
    page = secure_submit(name, f"/tasks/{reference}/connector/end-interrupted/", {"confirmation": "on"}, "expected_sequence")
    if "errorlist" in page.html:
        raise RuntimeError("End interrupted observation was refused: " + form_errors(page.html))
    log(f"  {name} ended the interrupted observation with a permanent gap ({why}).")
    log("  " + delivery_line(browser("owner").get(task_path).html))


def pilot_control(action, reason):
    """Owner's selection control on the current pilot (exact preview, then password + fresh code)."""
    path = load_state()["pilot"]["path"] + "selection/"
    page = preview_then_confirm("owner", path, {"action": action, "reason": reason}, "reason")
    if "errorlist" in page.html:
        raise RuntimeError(f"Selection control {action} was refused: " + form_errors(page.html))
    log(f"owner applied selection control '{action}': {reason}")
    log("  " + selection_summary(page.html))
    return page


def stage_rollback(reason):
    """Owner's failure response: roll the paused pilot back (no further routed selection on it).
    Recorded costs, unknown obligations and failures stay retained for the next review."""
    state = load_state()
    if not state["pilot"].get("rolled_back"):
        pilot_control("rollback", reason)
        state = load_state()
        state["pilot"]["rolled_back"] = True
        save_state(state)


def stage_rescope(label="rescope", pilot_id="demo-documentation-luna-2", task_types="documentation"):
    """Stale live authority is never repaired in place: revoke it, review the
    complete evidence (including the gap tasks) again, and approve a new pilot."""
    state = load_state()
    # No current pilot when the previous rescope's approval was refused (it was already retired).
    if "pilot" in state and state["pilot"].get("pilot_id", "demo-documentation-luna") != pilot_id:
        if not state["pilot"].get("rolled_back"):
            pilot_control("revoke", "DEMO full loop: live authority went stale after interrupted-start gaps; revoke before a new review")
        state = load_state()
        state.setdefault("retired_pilots", []).append(state.pop("pilot"))
        save_state(state)
    if label not in state.get("reviews", {}):
        stage_review(label)
    if not load_state()["reviews"][label].get("published"):
        stage_publish(label)
    stage_approve(label, pilot_id, task_types)


# ---------------------------------------------------------------- stage: routed

def scope_ref():
    return load_state()["pilot"]["path"].strip("/").rsplit("/", 1)[1]


def routed_start(task, done):
    """Explicit new task through the delivery plugin. A start whose response was
    lost is never repeated (that would mint another claim); recover it instead."""
    name, task_id = task["persona"], f"demo-{task['id'].lower()}"
    if done.get("start") and not done.get("started"):
        raise RuntimeError(f"{task['id']} start was submitted but its result was lost; recover it in the browser, never re-submit.")
    if not done.get("start"):
        fresh_checkout(name, task_id)
        done["start"] = {"scopeRef": scope_ref(), "repositoryRef": REPOSITORY, "taskLabel": task_id, "taskType": task["category"],
                         "riskTags": ["low"], "selectedModel": task["selected_model"], "contextTokens": 20000, "taskCapUSD": "0.10",
                         "outputLimit": 4096, "clientTaskID": str(uuid.uuid4()), "overrideModel": None, "requiredTools": ["read", "edit"]}
        save_state(STATE_CACHE)
        log(f"[{task['id']}] {name} starts a new {task['category']} task on {task['target']} through the Tarkado delivery plugin "
            f"(selected {task['selected_model']}, task cap $0.10, output limit 4096).")
        started = driver(name, {"op": "start", "start": done["start"]})
        done["started"] = {"sessionID": started.get("sessionID"), "model": started.get("model"), "sessionCreated": started.get("sessionCreated"),
                           "status": started.get("status"), "task_ref": started["task"]["task_ref"],
                           "revision": started["task"]["task_revision"]}
        save_state(STATE_CACHE)
    started = done["started"]
    if not started["sessionCreated"]:
        raise RuntimeError(f"{task['id']}: no model was applied (status {started['status']}); the task stays manual.")
    log(f"[{task['id']}] Tarkado selected {started['model']} at the new-task boundary and bound a fresh session (no prompt sent yet).")
    return started


def routed_feedback(name, done, action, value):
    result = driver(name, {"op": "feedback", "feedback": {"sessionID": done["started"]["sessionID"], "action": action,
                                                           "expectedRevision": done["started"]["revision"], "value": value}})
    done["started"]["revision"] = result["task_revision"]
    save_state(STATE_CACHE)
    return result


def routed_task(task, *, close=True):
    global STATE_CACHE
    STATE_CACHE = load_state()
    done = STATE_CACHE.setdefault("routed", {}).setdefault(task["id"], {})
    if done.get("result"):
        return done
    name, task_id = task["persona"], f"demo-{task['id'].lower()}"
    started = routed_start(task, done)
    session = started["sessionID"]
    task_path = f"/tasks/{started['task_ref']}/"
    if not done.get("response"):
        routed_feedback(name, done, "response", "accept")
        done["response"] = "accept"
        save_state(STATE_CACHE)
        log(f"[{task['id']}] {name} accepts the routed suggestion before any paid attempt.")
    if not done.get("run"):
        log(f"[{task['id']}] {name} submits the task prompt in the bound session (OpenCode -> LiteLLM -> provider).")
        run = driver(name, {"op": "prompt", "sessionID": session, "text": instruction(task)})
        done["run"] = {key: run[key] for key in ("latency_ms", "failure", "outcome", "usage", "session_usage", "steps", "models", "finishes", "errors")}
        save_state(STATE_CACHE)
        log(f"[{task['id']}] OpenCode finished ({run['outcome']}): steps={run['steps']} models={run['models']} usage={run['usage']} "
            f"session_total={run['session_usage']} latency={run['latency_ms']}ms failure={run['failure']} errors={run['errors']}")
    if not close:
        return done
    if not done.get("ci"):
        record = run_ci(name, task, task_id, "oc_" + hashlib.sha256(session.encode()).hexdigest())
        done["ci"] = {"record_id": record["record_id"], "passed": record["passed"], "tests_passed": record["tests_passed"]}
        save_state(STATE_CACHE)
    if not done.get("ended"):
        driver(name, {"op": "end", "sessionID": session})
        done["ended"] = True
        save_state(STATE_CACHE)
        log(f"[{task['id']}] {name} ends the task in OpenCode (connector observation closed).")
    if not done.get("settled"):
        binding = binding_ref_of(task_path)
        closed = gateway_call("close", {"binding_ref": binding})
        done["settled"] = {"binding_ref": binding, "known_cost_usd": closed.get("known_cost_usd"), "unknown_attempts": closed.get("unknown_attempts"),
                           "closed": closed.get("closed")}
        save_state(STATE_CACHE)
        log(f"[{task['id']}] gateway operator closed binding {binding[:8]}...: " + json.dumps(done["settled"], sort_keys=True))
    log("  " + delivery_line(browser("owner").get(task_path).html))
    if not done.get("execution"):
        # Report the policy model only when the provider demonstrably did the work: a settled,
        # positive known cost with zero unknown attempts, and OpenCode's own messages show only the bound alias.
        settled = done["settled"]
        if settled["unknown_attempts"] or not float(settled["known_cost_usd"] or 0) > 0 or done["run"]["outcome"] == "failed":
            raise RuntimeError(f"{task['id']}: no demonstrated provider completion ({json.dumps(settled)}, outcome {done['run']['outcome']}); "
                               "not reporting a model or result. Investigate before any further feedback.")
        if done["run"]["models"] != ["company/company-cheap"]:
            raise RuntimeError(f"{task['id']}: OpenCode reported models {done['run']['models']}; not reporting {task['routed_model']}.")
        routed_feedback(name, done, "actual_model", task["routed_model"])
        done["execution"] = task["routed_model"]
        save_state(STATE_CACHE)
        log(f"[{task['id']}] {name} reports the model actually used: {task['routed_model']}.")
    ci = done["ci"]
    value = {"desired_result": bool(ci["passed"]), "tests_passed": bool(ci["tests_passed"]), "score": None,
             "cost_usd": done["settled"]["known_cost_usd"], "latency_ms": done["run"]["latency_ms"],
             "evidence_ref": "ci:" + ci["record_id"], "supersedes": None}
    routed_feedback(name, done, "result", value)
    done["result"] = {key: value[key] for key in ("desired_result", "tests_passed", "cost_usd", "evidence_ref")}
    save_state(STATE_CACHE)
    log(f"[{task['id']}] {name} records the result: desired={value['desired_result']} tests={value['tests_passed']} "
        f"cost=${value['cost_usd']} (settled gateway cost) evidence={value['evidence_ref'][:11]}...")
    return done


STATE_CACHE = None


def stage_routed(*only):
    # A retry of a refused task needs a new task label (labels are never reused): "R1b" reruns R1's brief.
    for wanted in only or [task["id"] for task in TASKS["routed"]]:
        base = next(task for task in TASKS["routed"] if task["id"] == re.match(r"R\d+", wanted).group(0))
        routed_task({**base, "id": wanted, "routed_model": "company/luna"})


def stage_close_refused(task_id, why):
    """A routed task whose model request the gateway refused before any paid attempt.
    The gateway closes first (zero attempts -> cancelled, $0; the slot stays consumed),
    then the developer ends it through the plugin. No model ran, so neither an actual
    model nor a result is reported; the task stays visibly unanswered, never a model failure."""
    state = load_state()
    done = state["routed"][task_id]
    if done.get("execution") or done.get("result"):
        raise RuntimeError(f"{task_id} already has reported feedback; it is not a refused task.")
    task = next(task for task in TASKS["routed"] if task["id"] == re.match(r"R\d+", task_id).group(0))
    task_path = f"/tasks/{done['started']['task_ref']}/"
    log(f"[{task_id}] The gateway refused the model request before any paid attempt ({why}).")
    if not done.get("settled"):
        binding = binding_ref_of(task_path)
        closed = gateway_call("close", {"binding_ref": binding})
        done["settled"] = {"binding_ref": binding, "known_cost_usd": closed.get("known_cost_usd"), "unknown_attempts": closed.get("unknown_attempts"),
                           "closed": closed.get("closed")}
        save_state(state)
        log(f"[{task_id}] gateway operator closed binding {binding[:8]}...: " + json.dumps(done["settled"], sort_keys=True))
    if not done.get("ended"):
        driver(task["persona"], {"op": "end", "sessionID": done["started"]["sessionID"]})
        done["ended"] = True
        save_state(state)
        log(f"[{task_id}] {task['persona']} ends the task through the plugin (connector observation closed, no gap).")
    log("  " + delivery_line(browser("owner").get(task_path).html))
    state.setdefault("refused_routed", {})[task_id] = {**state["routed"].pop(task_id), "why": why}
    save_state(state)
    log(f"[{task_id}] No model ran: no actual model or result is reported. The retry uses a new task label.")


def stage_recover(*references):
    for reference in references:
        task_path = f"/tasks/{reference}/"
        owner = browser("owner").get(task_path)
        found = re.search(r"Owner: (\w+)\.", text_of(owner.html))
        name = found.group(1)
        log(f"Recovering lost delivery start {reference[:8]}... ({name}).")
        recover_task(name, task_path, "host session creation was refused by the strict model-ref check before any prompt")


# ---------------------------------------------------------------- main

def stage_relearn(label="relearn"):
    """The next learning review: the routed outcomes (settled cost, CI results) enter the evidence."""
    if label not in load_state().get("reviews", {}):
        stage_review(label)
    if not load_state()["reviews"][label].get("published"):
        stage_publish(label)


STAGES = {"laptop": stage_laptop, "settle": stage_settle, "relearn": stage_relearn, "setup": stage_setup, "people": stage_people, "shadow": stage_shadow, "review": stage_review, "publish": stage_publish, "approve": stage_approve, "delivery": stage_delivery, "recover": stage_recover, "rescope": stage_rescope, "routed": stage_routed, "close_refused": stage_close_refused, "rollback": stage_rollback}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        raise SystemExit(__doc__)
    STAGES[sys.argv[1]](*sys.argv[2:]) if len(sys.argv) > 2 else STAGES[sys.argv[1]]()
