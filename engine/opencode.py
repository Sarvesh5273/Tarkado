"""Explicit read-only OpenCode V2 snapshots, never inferred task boundaries."""

import re
import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlencode, urlsplit

from .exporters import export_jsonl
from .importers import parse_json
from .privacy import ensure_safe
from .schemas import MODEL_STATES, TIERS, Policy, ValidationError, boolean, choice, integer, number, object_fields, strings, text


class AdapterError(ValueError):
    """OpenCode failed or changed contracts. Never include raw process output."""


SNAPSHOT_FIELDS = (
    "schema_version", "record_type", "mode", "opencode_version", "session_ref", "parent_session_ref",
    "location_ref", "scope", "created_ms", "updated_ms", "selected_model", "variant",
    "model_in_team_registry", "team_model_status", "team_model_tier", "catalog", "tokens", "cost_usd",
    "session_outcome", "tests_passed", "score", "task_boundary_observed", "policy_version", "policy_sha256",
    "company_api_attested", "local_only", "deployment_authorized", "notes",
)


def _ref(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _counter(value: Any, name: str) -> int:
    result = number(value, name)
    if result != result.to_integral_value():
        raise ValidationError(f"{name} must be a nonnegative whole token count.")
    return int(result)


def _model_ref(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AdapterError("OpenCode session model must be an object or absent.")
    provider = text(value.get("providerID"), "providerID")
    model = text(value.get("id"), "model.id")
    variant = None if value.get("variant") is None else text(value["variant"], "variant")
    if "/" in provider or "#" in provider or "#" in model:
        raise AdapterError("OpenCode model reference is not a supported provider/model identifier.")
    return {"provider_id": provider, "model_id": model, "variant": variant,
            "selected_model": provider + "/" + model}


@dataclass(frozen=True)
class SessionSnapshot:
    data: Dict[str, Any]

    @classmethod
    def from_dict(cls, value: Any) -> "SessionSnapshot":
        data = object_fields(value, SNAPSHOT_FIELDS, SNAPSHOT_FIELDS)
        ensure_safe(data)
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValidationError("Unsupported OpenCode snapshot version.")
        choice(data["record_type"], "record_type", ("opencode_session_snapshot",))
        choice(data["mode"], "mode", ("observe",))
        text(data["opencode_version"], "opencode_version")
        choice(data["scope"], "scope", ("root_session", "child_session"))
        for field in ("session_ref", "parent_session_ref", "location_ref", "policy_sha256"):
            if field == "parent_session_ref" and data[field] is None:
                continue
            if not isinstance(data[field], str) or not re.fullmatch(r"[a-f0-9]{64}", data[field]):
                raise ValidationError("Snapshot references must be SHA-256 fingerprints.")
        if (data["parent_session_ref"] is None) != (data["scope"] == "root_session"):
            raise ValidationError("Snapshot parent/scope metadata disagrees.")
        created = number(data["created_ms"], "created_ms")
        updated = number(data["updated_ms"], "updated_ms")
        if updated < created:
            raise ValidationError("Snapshot timestamps are inconsistent.")
        for field in ("selected_model", "variant"):
            if data[field] is not None:
                text(data[field], field)
        text(data["policy_version"], "policy_version")
        known = boolean(data["model_in_team_registry"], "model_in_team_registry")
        if known:
            text(data["selected_model"], "selected_model")
            choice(data["team_model_status"], "team_model_status", MODEL_STATES)
            choice(data["team_model_tier"], "team_model_tier", TIERS)
        elif data["team_model_status"] is not None or data["team_model_tier"] is not None:
            raise ValidationError("Unregistered snapshot model cannot assert team approval/tier.")
        if data["catalog"] is not None:
            if not known:
                raise ValidationError("Snapshot catalog is restricted to a team-registered selected model.")
            fields = ("enabled", "supports_tools", "context_tokens", "provenance")
            catalog = object_fields(data["catalog"], fields, fields)
            for field in ("enabled", "supports_tools"):
                if catalog[field] is not None:
                    boolean(catalog[field], field)
            if catalog["context_tokens"] is not None:
                integer(catalog["context_tokens"], "context_tokens")
            choice(catalog["provenance"], "provenance", ("resolved_catalog_unverified",))
        if data["tokens"] is not None:
            fields = ("input", "output", "reasoning", "cache_read", "cache_write")
            tokens = object_fields(data["tokens"], fields, fields)
            for field in fields:
                integer(tokens[field], field)
        if data["cost_usd"] is not None:
            number(data["cost_usd"], "cost_usd")
        if data["session_outcome"] is not None:
            choice(data["session_outcome"], "session_outcome", ("succeeded", "failed", "interrupted"))
        if data["tests_passed"] is not None or data["score"] is not None:
            raise ValidationError("Session snapshots cannot invent task-quality labels.")
        for field, expected in (("task_boundary_observed", False), ("company_api_attested", True),
                                ("local_only", True), ("deployment_authorized", False)):
            if boolean(data[field], field) != expected:
                raise ValidationError("Snapshot must remain attested, local, observe-only, and unauthorized for routing.")
        strings(data["notes"], "notes")
        return cls(data)

    def to_dict(self) -> Dict[str, Any]:
        SessionSnapshot.from_dict(self.data)
        return self.data

    def export(self, path: Path) -> None:
        export_jsonl([self.to_dict()], path)


class OpenCodeReader:
    """Use OpenCode's normal discovery/authentication; never pass provider keys."""

    def __init__(self, executable: str = "opencode", timeout_seconds: int = 30):
        text(executable, "opencode executable")
        integer(timeout_seconds, "timeout_seconds")
        if timeout_seconds == 0 or timeout_seconds > 120:
            raise ValidationError("OpenCode timeout must be between 1 and 120 seconds.")
        resolved = shutil.which(executable)
        if resolved is None:
            raise AdapterError("OpenCode executable was not found; install/configure it explicitly before observing.")
        self.executable = resolved
        self.timeout_seconds = timeout_seconds

    def _run(self, arguments: list) -> str:
        try:
            result = subprocess.run([self.executable] + arguments, capture_output=True, text=True,
                                    encoding="utf-8", timeout=self.timeout_seconds, check=False, shell=False)
        except subprocess.TimeoutExpired:
            raise AdapterError("OpenCode read timed out; no retry or model request was sent by Tarkado.") from None
        except (OSError, UnicodeError):
            raise AdapterError("OpenCode process could not be read; raw diagnostics are withheld.") from None
        if result.returncode != 0:
            raise AdapterError("OpenCode read failed; inspect OpenCode locally. Raw diagnostics are withheld.")
        return result.stdout

    def version(self) -> str:
        value = self._run(["--version"]).strip()
        match = re.fullmatch(r"(?:opencode v?)?(2\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?)", value)
        if match is None:
            raise AdapterError("Only a verified OpenCode V2 executable is supported; no V1 fallback.")
        return match.group(1)

    def get(self, path: str) -> Any:
        # These are the only HTTP operations this adapter may ask OpenCode to perform.
        try:
            ensure_safe(path)
            parsed = urlsplit(path)
            query = parse_qs(parsed.query, strict_parsing=True) if parsed.query else {}
        except ValueError:
            raise AdapterError("Invalid observer endpoint query; request refused.") from None
        session_path = bool(re.fullmatch(r"/api/session/ses[A-Za-z0-9_-]+", path))
        catalog_path = (parsed.path == "/api/model" and set(query) == {"location[directory]"}
                        and len(query["location[directory]"]) == 1
                        and Path(query["location[directory]"][0]).is_absolute()
                        and not parsed.scheme and not parsed.netloc and not parsed.fragment)
        allowed = session_path or catalog_path
        if not allowed:
            raise AdapterError("Read-only adapter request is outside its endpoint allowlist.")
        output = self._run(["api", "get", path])
        try:
            return parse_json(output)
        except ValueError:
            raise AdapterError("OpenCode returned an unsupported response; raw data is withheld.") from None

    def observe(self, session_id: str, directory: Path, policy: Policy,
                company_api_confirmed: bool) -> SessionSnapshot:
        text(session_id, "session_id")
        if not re.fullmatch(r"ses[A-Za-z0-9_-]+", session_id):
            raise ValidationError("Provide an explicit OpenCode session ID, not a path or query.")
        if not boolean(company_api_confirmed, "company_api_confirmed"):
            raise ValidationError("Observation requires confirmation of company-managed API/gateway credentials.")
        ensure_safe(str(directory))
        location = directory.resolve(strict=True)
        if not location.is_dir():
            raise ValidationError("Observation scope must be an existing project directory.")
        fingerprint = policy.fingerprint()
        version = self.version()
        session_response = self.get("/api/session/" + session_id)
        if not isinstance(session_response, dict) or not isinstance(session_response.get("data"), dict):
            raise AdapterError("Unsupported OpenCode session response envelope.")
        session = session_response["data"]
        if session.get("id") != session_id:
            raise AdapterError("OpenCode returned a different session than requested.")
        session_location = session.get("location")
        if not isinstance(session_location, dict) or not isinstance(session_location.get("directory"), str):
            raise AdapterError("Session location is missing; refusing cross-project observation.")
        reported_directory = session_location["directory"]
        ensure_safe(reported_directory)
        if Path(reported_directory).resolve() != location:
            raise AdapterError("Session belongs to a different location; observation refused.")
        parent = None if session.get("parentID") is None else text(session["parentID"], "parentID")
        model = _model_ref(session.get("model"))
        selected = model["selected_model"] if model else None
        team_model = policy.model(selected) if selected else None
        usage = None
        if session.get("tokens") is not None:
            tokens = session["tokens"]
            if not isinstance(tokens, dict) or not isinstance(tokens.get("cache"), dict):
                raise AdapterError("Unsupported OpenCode cumulative token usage.")
            usage = {"input": _counter(tokens.get("input"), "tokens.input"),
                     "output": _counter(tokens.get("output"), "tokens.output"),
                     "reasoning": _counter(tokens.get("reasoning"), "tokens.reasoning"),
                     "cache_read": _counter(tokens["cache"].get("read"), "tokens.cache.read"),
                     "cache_write": _counter(tokens["cache"].get("write"), "tokens.cache.write")}
        times = session.get("time")
        if not isinstance(times, dict):
            raise AdapterError("OpenCode session timestamps are missing.")
        created = str(number(times.get("created"), "time.created"))
        updated = str(number(times.get("updated"), "time.updated"))
        if Decimal(updated) < Decimal(created):
            raise AdapterError("OpenCode session timestamps are inconsistent.")
        outcome = session.get("outcome")
        if outcome is not None and outcome not in ("succeeded", "failed", "interrupted"):
            raise AdapterError("Unsupported OpenCode session outcome.")
        catalog = None
        notes = [
            "Explicit read-only session snapshot, not a new-task/subagent boundary or TaskTrace.",
            "Tokens and cost are cumulative session metadata; do not sum repeated snapshots as requests.",
            "Session outcome is runtime status, not tests passing or a quality score.",
            "Company API use is caller-attested, not verified by reading credentials.",
            "OpenCode API discovery may start its service or activate location plugins; Tarkado only requests GETs.",
        ]
        if model and team_model:
            path = "/api/model?" + urlencode({"location[directory]": str(location)})
            response = self.get(path)
            if not isinstance(response, dict) or not isinstance(response.get("data"), list):
                raise AdapterError("Unsupported OpenCode model response envelope.")
            catalog_location = response.get("location")
            if not isinstance(catalog_location, dict) or catalog_location.get("directory") != str(location):
                raise AdapterError("Model catalog location does not match the requested observation scope.")
            matches = [entry for entry in response["data"] if isinstance(entry, dict)
                       and entry.get("providerID") == model["provider_id"] and entry.get("id") == model["model_id"]]
            if len(matches) > 1:
                raise AdapterError("Model catalog has duplicate selected-model entries.")
            if matches:
                entry = matches[0]
                capabilities, limits = entry.get("capabilities"), entry.get("limit")
                catalog = {
                    "enabled": boolean(entry["enabled"], "enabled") if "enabled" in entry else None,
                    "supports_tools": (boolean(capabilities["tools"], "capabilities.tools")
                                       if isinstance(capabilities, dict) and "tools" in capabilities else None),
                    "context_tokens": (_counter(limits["context"], "limit.context")
                                       if isinstance(limits, dict) and "context" in limits else None),
                    "provenance": "resolved_catalog_unverified",
                }
            notes.append("Resolved catalog capabilities can be fallback assumptions; they do not update team policy.")
        elif model:
            notes.append("Selected model is outside the team registry; no catalog lookup or routing approval.")
        else:
            notes.append("Session has no explicit model; the actual request model is unknown and no default is inferred.")
        data = {
            "schema_version": 1, "record_type": "opencode_session_snapshot", "mode": "observe",
            "opencode_version": version, "session_ref": _ref(session_id), "parent_session_ref": _ref(parent),
            "location_ref": _ref(str(location)), "scope": "child_session" if parent else "root_session",
            "created_ms": created, "updated_ms": updated, "selected_model": selected,
            "variant": model["variant"] if model else None,
            "model_in_team_registry": team_model is not None,
            "team_model_status": team_model.status if team_model else None,
            "team_model_tier": team_model.tier if team_model else None,
            "catalog": catalog, "tokens": usage,
            "cost_usd": str(number(session["cost"], "cost")) if session.get("cost") is not None else None,
            "session_outcome": outcome, "tests_passed": None, "score": None,
            "task_boundary_observed": False, "policy_version": policy.policy_version,
            "policy_sha256": fingerprint, "company_api_attested": True,
            "local_only": True, "deployment_authorized": False, "notes": notes,
        }
        ensure_safe(data)
        return SessionSnapshot.from_dict(data)


def load_snapshot(path: Path) -> SessionSnapshot:
    ensure_safe(str(path))
    records = [parse_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(records) != 1:
        raise ValidationError("A session snapshot file must contain exactly one metadata record.")
    return SessionSnapshot.from_dict(records[0])
