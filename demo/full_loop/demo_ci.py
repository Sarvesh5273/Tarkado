"""DEMO-ONLY independent CI checks with an HMAC-signed, metadata-only ledger.

This is the full-loop demonstration's stand-in for a company's existing CI. It
runs fixed, versioned checks against a developer checkout AFTER a task finishes
and signs a metadata-only record (no code, prompts or outputs). Developers only
cite the record ID as their result evidence; the company-side demo readiness
verifier re-validates every cited record with the CI key, which the developer
personas never use.

On a single demo machine this independence is procedural, not cryptographic
separation of duties. A real company would use its existing CI and key custody.
"""

import ast
import hashlib
import hmac
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "tarkado-demo-ci-v1"
CHECKS_VERSION = "demo-ci-checks-v1"
CATEGORIES = ("documentation", "test_generation")


def criteria_sha256():
    """Fingerprint of these exact check definitions (this file)."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def _public_definitions(tree):
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            found.append(node)
            if isinstance(node, ast.ClassDef):
                found.extend(child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and (not child.name.startswith("_") or child.name == "__init__"))
    return found


def _unit_tests(repo):
    try:
        completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=repo,
                                   capture_output=True, text=True, timeout=180, env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired:
        return {"passed": False, "ran": None}
    ran = None
    for line in completed.stderr.splitlines():
        if line.startswith("Ran ") and " test" in line:
            try:
                ran = int(line.split()[1])
            except ValueError:
                ran = None
    return {"passed": completed.returncode == 0, "ran": ran}


def _test_methods(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    return {f"{node.name}.{child.name}" for node in tree.body if isinstance(node, ast.ClassDef)
            for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test")}


def evaluate(repo, base_commit, category, target):
    """Run the fixed checks for one category against the working tree. Returns metadata only."""
    if category not in CATEGORIES:
        raise ValueError("Unknown demo CI category.")
    repo = Path(repo)
    changed = sorted({line[3:].strip() for line in _git(repo, "status", "--porcelain", "--untracked-files=all").splitlines() if line.strip()}
                     | {line.strip() for line in _git(repo, "diff", "--name-only", base_commit).splitlines() if line.strip()})
    changed = [path for path in changed if "__pycache__" not in path]
    checks = {}
    if category == "documentation":
        before = _git(repo, "show", f"{base_commit}:{target}")
        after_path = repo / target
        after = after_path.read_text() if after_path.exists() else ""
        try:
            after_tree = ast.parse(after)
            checks["parses"] = True
        except SyntaxError:
            after_tree, checks["parses"] = None, False
        checks["only_target_changed"] = changed == [target]
        if after_tree is not None:
            definitions = _public_definitions(after_tree)
            checks["module_docstring"] = bool(ast.get_docstring(after_tree))
            checks["every_public_definition_documented"] = bool(definitions) and all(ast.get_docstring(node) for node in definitions)
            checks["behaviour_unchanged"] = _strip_docstrings(ast.parse(before)) == _strip_docstrings(after_tree)
        else:
            checks["module_docstring"] = checks["every_public_definition_documented"] = checks["behaviour_unchanged"] = False
    else:
        source_changes = [path for path in changed if not path.startswith("tests/")]
        checks["source_unchanged"] = not source_changes
        added = set()
        for path in changed:
            if path.startswith("tests/") and path.endswith(".py") and (repo / path).exists():
                try:
                    previous = _git(repo, "show", f"{base_commit}:{path}")
                except subprocess.CalledProcessError:
                    previous = ""
                current = (repo / path).read_text()
                if target.replace("/", ".").removesuffix(".py") in current:
                    added |= _test_methods(current) - _test_methods(previous)
        checks["at_least_three_new_tests_for_target"] = len(added) >= 3
    tests = _unit_tests(repo)
    checks["unit_tests_pass"] = tests["passed"]
    return {"category": category, "target": target, "changed_files": len(changed), "checks": checks,
            "tests_ran": tests["ran"], "tests_passed": tests["passed"], "passed": all(checks.values())}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sign(record, key):
    return hmac.new(key, _canonical(record), hashlib.sha256).hexdigest()


def record(ledger_dir, key, *, task_id, session_id, developer, repo, base_commit, category, target):
    """Evaluate and append one signed record. Returns the record (metadata only)."""
    result = evaluate(repo, base_commit, category, target)
    # Stage to fingerprint the exact evaluated working tree (metadata only).
    _git(repo, "add", "-A")
    tree = _git(repo, "write-tree").strip()
    value = {"schema": SCHEMA, "checks_version": CHECKS_VERSION, "criteria_sha256": criteria_sha256(),
             "record_id": str(uuid.uuid4()), "task_id": task_id, "session_id": session_id, "developer": developer,
             "base_commit": base_commit, "result_tree": tree, "ran_at": datetime.now(timezone.utc).isoformat(), **result}
    signed = {"record": value, "hmac_sha256": sign(value, key)}
    ledger_dir = Path(ledger_dir)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_dir / (value["record_id"] + ".json")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(signed, stream, indent=1, sort_keys=True)
    return value


def load_verified(ledger_dir, key, record_id):
    """Return the record only when its signature verifies; otherwise None."""
    try:
        uuid.UUID(record_id)
    except (ValueError, TypeError):
        return None
    path = Path(ledger_dir) / (record_id + ".json")
    if not path.is_file() or path.is_symlink():
        return None
    try:
        signed = json.loads(path.read_text())
        value = signed["record"]
        if not hmac.compare_digest(signed["hmac_sha256"], sign(value, key)) or value.get("record_id") != record_id:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    return value
