"""Local policy snapshots and review history. Nothing here changes live routing."""

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from .exporters import export_policy
from .importers import parse_json
from .privacy import ensure_safe
from .schemas import Policy, ValidationError, boolean, choice, integer, object_fields, text


try:
    import fcntl
except ImportError:
    fcntl = None


def policy_digest(policy: Policy) -> str:
    return policy.fingerprint()


@dataclass(frozen=True)
class PolicySnapshot:
    policy: Policy
    sha256: str

    @classmethod
    def create(cls, policy: Policy) -> "PolicySnapshot":
        validated = Policy.from_dict(policy.to_dict())
        return cls(validated, policy_digest(validated))

    @classmethod
    def from_dict(cls, value: Any) -> "PolicySnapshot":
        fields = ("policy_version", "sha256", "policy")
        data = object_fields(value, fields, fields)
        policy = Policy.from_dict(data["policy"])
        if text(data["policy_version"], "policy_version") != policy.policy_version:
            raise ValidationError("Snapshot version disagrees with its policy.")
        digest = text(data["sha256"], "sha256")
        if digest != policy_digest(policy):
            raise ValidationError("Snapshot content digest does not match; history is not trusted.")
        return cls(policy, digest)

    def to_dict(self) -> Dict[str, Any]:
        return {"policy_version": self.policy.policy_version, "sha256": self.sha256,
                "policy": self.policy.to_dict()}


@dataclass(frozen=True)
class HistoryEvent:
    sequence: int
    timestamp: str
    action: str
    policy_version: str
    policy_sha256: str
    previous_policy_version: Optional[str]
    reviewer: Optional[str]
    reason: Optional[str]

    @classmethod
    def from_dict(cls, value: Any) -> "HistoryEvent":
        fields = ("sequence", "timestamp", "action", "policy_version", "policy_sha256",
                  "previous_policy_version", "reviewer", "reason")
        data = object_fields(value, fields, fields)
        sequence = integer(data["sequence"], "sequence")
        if sequence == 0:
            raise ValidationError("History sequence must be positive.")
        timestamp = text(data["timestamp"], "timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError("History timestamp must be ISO-8601.") from None
        if parsed.tzinfo is None:
            raise ValidationError("History timestamp must include a timezone.")
        action = choice(data["action"], "action", ("save", "review", "select", "rollback"))
        previous = data["previous_policy_version"]
        if previous is not None:
            previous = text(previous, "previous_policy_version")
        reviewer, reason = data["reviewer"], data["reason"]
        if action == "save":
            if reviewer is not None or reason is not None or previous is not None:
                raise ValidationError("Save events cannot assert a review or previous selection.")
        else:
            reviewer = text(reviewer, "reviewer")
            reason = text(reason, "reason")
        if action == "review" and previous is not None:
            raise ValidationError("Review events cannot assert a previous selection.")
        return cls(sequence, timestamp, action, text(data["policy_version"], "policy_version"),
                   text(data["policy_sha256"], "policy_sha256"), previous, reviewer, reason)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence, "timestamp": self.timestamp, "action": self.action,
            "policy_version": self.policy_version, "policy_sha256": self.policy_sha256,
            "previous_policy_version": self.previous_policy_version,
            "reviewer": self.reviewer, "reason": self.reason,
        }


@dataclass(frozen=True)
class PolicyHistory:
    snapshots: Tuple[PolicySnapshot, ...] = ()
    events: Tuple[HistoryEvent, ...] = ()

    @classmethod
    def from_dict(cls, value: Any) -> "PolicyHistory":
        fields = ("schema_version", "snapshots", "events")
        data = object_fields(value, fields, fields)
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValidationError("Unsupported policy-history schema version.")
        if not isinstance(data["snapshots"], list) or not isinstance(data["events"], list):
            raise ValidationError("History snapshots and events must be arrays.")
        snapshots = tuple(PolicySnapshot.from_dict(item) for item in data["snapshots"])
        events = tuple(HistoryEvent.from_dict(item) for item in data["events"])
        by_version = {snapshot.policy.policy_version: snapshot for snapshot in snapshots}
        if len(by_version) != len(snapshots):
            raise ValidationError("History contains duplicate policy versions.")
        saved, reviewed, selected = set(), set(), set()
        current = None
        for sequence, event in enumerate(events, start=1):
            if event.sequence != sequence:
                raise ValidationError("History event sequence is incomplete or out of order.")
            snapshot = by_version.get(event.policy_version)
            if snapshot is None or snapshot.sha256 != event.policy_sha256:
                raise ValidationError("History event does not match a stored snapshot.")
            version = event.policy_version
            if event.action == "save":
                if version in saved:
                    raise ValidationError("History contains multiple saves for one version.")
                saved.add(version)
            else:
                if version not in saved:
                    raise ValidationError("History references a policy before it was saved.")
                if event.action == "review":
                    reviewed.add(version)
                else:
                    if version not in reviewed:
                        raise ValidationError("Selection history has no prior content-bound review.")
                    if event.previous_policy_version != current or version == current:
                        raise ValidationError("Selection history has an invalid previous policy.")
                    if event.action == "rollback" and (current is None or version not in selected):
                        raise ValidationError("Rollback target was not previously selected.")
                    selected.add(version)
                    current = version
        if saved != set(by_version):
            raise ValidationError("History has snapshots without save records.")
        return cls(snapshots, events)

    @property
    def current_version(self) -> Optional[str]:
        return next((event.policy_version for event in reversed(self.events)
                     if event.action in ("select", "rollback")), None)

    def snapshot(self, version: str) -> PolicySnapshot:
        snapshot = next((item for item in self.snapshots if item.policy.policy_version == version), None)
        if snapshot is None:
            raise ValidationError("Requested policy version is not saved in this local history.")
        return snapshot

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": 1, "snapshots": [snapshot.to_dict() for snapshot in self.snapshots],
                "events": [event.to_dict() for event in self.events]}


class PolicyStore:
    """A single JSON store with locked, atomic updates on macOS and Linux."""

    def __init__(self, directory: Path):
        ensure_safe(str(directory))
        self.directory = directory
        self.state_path = directory / "state.json"

    def _read(self) -> PolicyHistory:
        if self.state_path.is_symlink():
            raise ValidationError("Policy-history state must not be a symbolic link.")
        if not self.state_path.exists():
            return PolicyHistory()
        with os.fdopen(os.open(self.state_path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as stream:
            return PolicyHistory.from_dict(parse_json(stream.read()))

    @contextmanager
    def _locked(self, create: bool) -> Iterator[PolicyHistory]:
        if fcntl is None:
            raise ValidationError("Local policy-history locking currently requires macOS or Linux.")
        if self.directory.is_symlink():
            raise ValidationError("Policy-history directory must not be a symbolic link.")
        if not self.directory.exists() and not create:
            yield PolicyHistory()
            return
        if create:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.directory / ".lock"
        with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield self._read()
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write(self, history: PolicyHistory) -> None:
        validated = PolicyHistory.from_dict(history.to_dict())
        ensure_safe(validated.to_dict())
        content = json.dumps(validated.to_dict(), indent=2, ensure_ascii=False) + "\n"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             prefix=".state-", suffix=".json", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def read(self) -> PolicyHistory:
        with self._locked(create=False) as history:
            return history

    def _event(self, history: PolicyHistory, snapshot: PolicySnapshot, action: str,
               reviewer: Optional[str] = None, reason: Optional[str] = None,
               previous: Optional[str] = None) -> HistoryEvent:
        return HistoryEvent.from_dict({
            "sequence": len(history.events) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(), "action": action,
            "policy_version": snapshot.policy.policy_version, "policy_sha256": snapshot.sha256,
            "previous_policy_version": previous, "reviewer": reviewer, "reason": reason,
        })

    def save(self, policy: Policy) -> PolicySnapshot:
        snapshot = PolicySnapshot.create(policy)
        with self._locked(create=True) as history:
            existing = next((item for item in history.snapshots
                             if item.policy.policy_version == policy.policy_version), None)
            if existing is not None:
                if existing.sha256 != snapshot.sha256:
                    raise ValidationError("Policy version already exists with different content; use a new version.")
                return existing
            event = self._event(history, snapshot, "save")
            self._write(PolicyHistory(history.snapshots + (snapshot,), history.events + (event,)))
        return snapshot

    def review(self, version: str, reviewer: str, reason: str) -> HistoryEvent:
        text(version, "policy_version")
        text(reviewer, "reviewer")
        text(reason, "reason")
        with self._locked(create=False) as history:
            snapshot = history.snapshot(version)
            event = self._event(history, snapshot, "review", reviewer, reason)
            self._write(PolicyHistory(history.snapshots, history.events + (event,)))
        return event

    def select(self, version: str, reviewer: str, reason: str,
               expected_current: Optional[str], rollback: bool = False) -> HistoryEvent:
        text(version, "policy_version")
        text(reviewer, "reviewer")
        text(reason, "reason")
        boolean(rollback, "rollback")
        if expected_current is not None:
            text(expected_current, "expected_current")
        with self._locked(create=False) as history:
            snapshot = history.snapshot(version)
            current = history.current_version
            if current != expected_current:
                raise ValidationError("Local selection changed; read current policy and review the change before retrying.")
            if current == version:
                raise ValidationError("Requested policy is already the local selection.")
            if not any(event.action == "review" and event.policy_version == version for event in history.events):
                raise ValidationError("Record an explicit local review of this snapshot before selecting it.")
            if rollback and (current is None or not any(
                event.action in ("select", "rollback") and event.policy_version == version for event in history.events
            )):
                raise ValidationError("Rollback requires a previously selected reviewed snapshot.")
            event = self._event(history, snapshot, "rollback" if rollback else "select", reviewer, reason, current)
            self._write(PolicyHistory(history.snapshots, history.events + (event,)))
        return event

    def current_policy(self) -> Optional[Policy]:
        history = self.read()
        return history.snapshot(history.current_version).policy if history.current_version is not None else None

    def export(self, version: str, destination: Path) -> None:
        export_policy(self.read().snapshot(version).policy, destination)
