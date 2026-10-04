"""Persistent scoped pilot simulation. This module never sends model requests."""

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .feedback import FeedbackLedger, TaskRequest, _fingerprint, _policy_input, _timestamp
from .history import PolicySnapshot
from .importers import parse_json
from .learning import LearnedModel
from .policy import incompatibility
from .privacy import ensure_safe
from .readiness import ApproverRoster, PilotReview
from .schemas import Policy, ValidationError, choice, integer, number, object_fields, text

try:
    import fcntl
except ImportError:
    fcntl = None


@dataclass(frozen=True)
class PilotRequest:
    decision_id: str
    task: TaskRequest
    repository_ref: str
    boundary: str
    reserve_usd: Optional[Decimal]
    override_model: Optional[str]

    @classmethod
    def from_dict(cls, value: Any) -> "PilotRequest":
        fields = ("decision_id", "task", "repository_ref", "boundary", "reserve_usd", "override_model")
        data = object_fields(value, fields, fields)
        reserve = None if data["reserve_usd"] is None else number(data["reserve_usd"], "reserve_usd")
        if reserve == 0:
            raise ValidationError("A reservation must be positive or explicitly unknown.")
        return cls(text(data["decision_id"], "decision_id"), TaskRequest.from_dict(data["task"]),
                   text(data["repository_ref"], "repository_ref"),
                   choice(data["boundary"], "boundary", ("new_task", "new_run", "subagent", "continuation")),
                   reserve, None if data["override_model"] is None else text(data["override_model"], "override_model"))

    def to_dict(self) -> Dict[str, Any]:
        return {"decision_id": self.decision_id, "task": self.task.to_dict(), "repository_ref": self.repository_ref,
                "boundary": self.boundary, "reserve_usd": str(self.reserve_usd) if self.reserve_usd is not None else None,
                "override_model": self.override_model}


def _money_total(values: list) -> Decimal:
    # Allocate enough precision to preserve all supplied decimal costs, even small fractional amounts.
    if not values:
        return Decimal(0)
    highest = max(value.adjusted() for value in values)
    lowest = min(value.as_tuple().exponent for value in values)
    with localcontext() as context:
        context.prec = max(28, highest - lowest + len(str(len(values))) + 3)
        return sum(values, Decimal(0))


def _settlement(value: Any) -> Dict[str, Any]:
    fields = ("settlement_id", "decision_id", "timestamp", "actual_cost_usd", "outcome")
    data = object_fields(value, fields, fields)
    _timestamp(data["timestamp"])
    cost = number(data["actual_cost_usd"], "actual_cost_usd")
    outcome = choice(data["outcome"], "outcome", ("completed", "failed", "cancelled"))
    if outcome == "cancelled" and cost != 0:
        raise ValidationError("Cancellation before execution must have zero recorded cost; use failed/completed for incurred cost.")
    return {"settlement_id": text(data["settlement_id"], "settlement_id"),
            "decision_id": text(data["decision_id"], "decision_id"), "timestamp": data["timestamp"],
            "actual_cost_usd": str(cost), "outcome": outcome}


class PilotState:
    """Derived from validated history, not from an editable active flag or budget counter."""

    def __init__(self, receipt: PilotReview, learner: LearnedModel):
        self.receipt = receipt
        self.learner = learner
        self.status = "uninitialized"
        self.revision = 0
        self.timestamp = receipt.data["timestamp"]
        self.decisions: Dict[str, Dict[str, Any]] = {}
        self.settlements: Dict[str, Dict[str, Any]] = {}

    @property
    def limits(self) -> Dict[str, Any]:
        return self.receipt.data["scope"]

    def accounting(self) -> Dict[str, Any]:
        reserved = [record for record in self.decisions.values() if record["result"]["status"] == "reserved"]
        pending = [record for record in reserved if record["request"]["decision_id"] not in self.settlements]
        spent = _money_total([Decimal(item["actual_cost_usd"]) for item in self.settlements.values()])
        held = _money_total([Decimal(item["request"]["reserve_usd"]) for item in pending])
        committed = _money_total([spent, held])
        remaining = _money_total([Decimal(self.limits["max_cost_usd"]), committed.copy_negate()])
        return {"admitted_tasks": len(reserved), "pending_tasks": len(pending), "settled_tasks": len(self.settlements),
                "spent_usd": str(spent), "reserved_usd": str(held), "committed_usd": str(committed),
                "remaining_usd": str(remaining), "remaining_task_slots": self.limits["max_tasks"] - len(reserved)}

    def decision(self, request: PilotRequest, policy: Policy, guard: Dict[str, Any]) -> Dict[str, Any]:
        context = _policy_input(request.task, policy)
        state = self.accounting()
        reason = None
        if request.boundary == "continuation":
            reason = "Active-task continuations are not a routing boundary; keep the original model."
        elif self.status != "active":
            reason = "Pilot is not active; use default-only behavior for future tasks."
        elif guard["status"] != "current":
            reason = "Current feedback/approval is not valid for this pilot. " + guard["reason"]
        elif policy.fingerprint() != self.receipt.data["report"]["policy_sha256"]:
            reason = "Current policy content differs from the exact approved pilot; new approval is required."
        elif request.repository_ref != self.limits["repository_ref"]:
            reason = "Repository is outside the approved pilot scope."
        elif request.task.developer_id not in self.limits["developer_ids"]:
            reason = "Developer is outside the approved pilot scope."
        elif request.task.task_type not in self.limits["task_types"]:
            reason = "Task category is outside the approved pilot scope."
        elif set(request.task.risk_tags) != {"low"}:
            reason = "Task risk is high or unknown; use the approved default."
        elif request.reserve_usd is None:
            reason = "Task cost commitment is unknown; no pilot budget can be reserved."
        elif state["remaining_task_slots"] <= 0:
            reason = "The approved pilot task limit has been reached."
        elif request.reserve_usd > Decimal(state["remaining_usd"]):
            reason = "The task reservation exceeds the remaining approved pilot budget."
        chosen = None
        override = request.override_model is not None
        if reason is None:
            selected = next(route["model"] for route in self.receipt.data["routes"]
                            if route["task_type"] == request.task.task_type)
            chosen = request.override_model or selected
            reason = incompatibility(policy.model(chosen), context)
        if reason is None:
            return {"status": "reserved", "simulated_model": chosen,
                    "reason": "Explicit approved local simulation scope; developer override retained." if override
                              else "Explicit approved local simulation scope and compatible new-task model.",
                    "pilot_applied": True, "override_applied": override, "used_fallback": False,
                    "reserved_usd": str(request.reserve_usd), "actual_selected_model": request.task.selected_model,
                    "local_only": True, "model_request_sent": False, "deployment_authorized": False}
        if request.boundary == "continuation":
            candidate = request.task.selected_model
        else:
            candidate = policy.default_model
        issue = incompatibility(policy.model(candidate), context)
        return {"status": "blocked" if issue else "fallback", "simulated_model": None if issue else candidate,
                "reason": reason + (" Default/original model is also incompatible. " + issue if issue else ""),
                "pilot_applied": False, "override_applied": False, "used_fallback": True,
                "reserved_usd": "0", "actual_selected_model": request.task.selected_model,
                "local_only": True, "model_request_sent": False, "deployment_authorized": False}

    def apply(self, event: Any) -> None:
        fields = ("sequence", "timestamp", "action", "payload", "event_sha256")
        data = object_fields(event, fields, fields)
        ensure_safe(data)
        if integer(data["sequence"], "sequence") != self.revision + 1:
            raise ValidationError("Pilot history is missing or reorders an event.")
        timestamp = _timestamp(data["timestamp"])
        if timestamp < _timestamp(self.timestamp):
            raise ValidationError("Pilot event timestamp precedes the current state.")
        action = choice(data["action"], "action", ("activate", "pause", "resume", "revoke", "rollback", "decision", "settle"))
        if _fingerprint({key: data[key] for key in fields if key != "event_sha256"}) != data["event_sha256"]:
            raise ValidationError("Pilot event content fingerprint disagrees.")
        if action in ("activate", "pause", "resume", "revoke", "rollback"):
            payload = object_fields(data["payload"], ("reviewer_id", "approver_roster", "reason"),
                                    ("reviewer_id", "approver_roster", "reason"))
            roster = ApproverRoster.from_dict(payload["approver_roster"])
            roster.designated(text(payload["reviewer_id"], "reviewer_id"))
            text(payload["reason"], "reason")
            if action == "activate":
                if self.revision != 0:
                    raise ValidationError("Activation cannot restart an existing pilot or reset its budget.")
                if roster.to_dict() != self.receipt.data["approver_roster"]:
                    raise ValidationError("Activation roster differs from the recorded pilot review.")
                self.status = "active"
            elif action == "resume":
                if self.status != "paused":
                    raise ValidationError("Only a paused pilot can resume; revoked/rolled-back pilots need a new approval/store.")
                if roster.to_dict() != self.receipt.data["approver_roster"]:
                    raise ValidationError("Resume needs the exact approval roster; changed authority requires a new review.")
                if any(item["outcome"] == "failed" or Decimal(item["actual_cost_usd"]) > Decimal(
                    self.decisions[identifier]["request"]["reserve_usd"]
                ) for identifier, item in self.settlements.items()):
                    raise ValidationError("Recorded failures/overruns require a new reviewed pilot, not resuming unchanged approval.")
                self.status = "active"
            elif action == "pause":
                if self.status != "active":
                    raise ValidationError("Only an active pilot can be paused.")
                self.status = "paused"
            else:
                if self.status not in ("active", "paused"):
                    raise ValidationError("A revoked/default-only pilot cannot be revived by control commands.")
                self.status = "revoked" if action == "revoke" else "rolled_back"
        elif action == "decision":
            if self.status == "uninitialized":
                raise ValidationError("A decision cannot precede explicit pilot activation.")
            payload = object_fields(data["payload"], ("request", "policy", "guard", "result"),
                                    ("request", "policy", "guard", "result"))
            request = PilotRequest.from_dict(payload["request"])
            policy = PolicySnapshot.from_dict(payload["policy"]).policy
            guard = object_fields(payload["guard"], ("status", "reason"), ("status", "reason"))
            choice(guard["status"], "status", ("current", "blocked"))
            text(guard["reason"], "reason")
            if request.task.timestamp != data["timestamp"]:
                raise ValidationError("Pilot task timestamp differs from its decision event.")
            identity = (request.task.session_id, request.task.task_id)
            if request.decision_id in self.decisions or any(
                (item["request"]["task"]["session_id"], item["request"]["task"]["task_id"]) == identity
                for item in self.decisions.values()
            ):
                raise ValidationError("A task/decision is already recorded; duplicate admission cannot consume another slot.")
            result = self.decision(request, policy, guard)
            if result != payload["result"]:
                raise ValidationError("Recorded pilot decision differs from its scope/state/budget checks.")
            self.decisions[request.decision_id] = payload
            if self.status == "active" and (guard["status"] == "blocked" or policy.fingerprint() != self.receipt.data["report"]["policy_sha256"]):
                self.status = "paused"
        else:
            payload = _settlement(data["payload"])
            if payload != data["payload"] or payload["timestamp"] != data["timestamp"]:
                raise ValidationError("Pilot settlement data is not canonical or has a different event timestamp.")
            decision = self.decisions.get(payload["decision_id"])
            if decision is None or decision["result"]["status"] != "reserved":
                raise ValidationError("Settlement requires a recorded reserved task, not a fallback or blocked decision.")
            if payload["decision_id"] in self.settlements or any(
                item["settlement_id"] == payload["settlement_id"] for item in self.settlements.values()
            ):
                raise ValidationError("Duplicate settlement cannot charge or release the same reservation twice.")
            self.settlements[payload["decision_id"]] = payload
            violation = Decimal(payload["actual_cost_usd"]) > Decimal(decision["request"]["reserve_usd"])
            if self.status == "active" and (violation or payload["outcome"] == "failed"):
                self.status = "paused"
        self.revision = data["sequence"]
        self.timestamp = data["timestamp"]


@dataclass(frozen=True)
class PilotJournal:
    receipt: PilotReview
    learner: LearnedModel
    events: tuple

    @classmethod
    def from_dict(cls, value: Any) -> "PilotJournal":
        fields = ("schema_version", "mode", "receipt", "learner", "events")
        data = object_fields(value, fields, fields)
        ensure_safe(data)
        if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["mode"] != "local_pilot_simulation":
            raise ValidationError("Only the local pilot-simulation journal is supported; no live mode.")
        receipt = PilotReview.from_dict(data["receipt"])
        learner = LearnedModel.from_dict(data["learner"])
        if not receipt.data["approved_for_local_simulation"]:
            raise ValidationError("A rejected review cannot initialize a simulation pilot.")
        report = receipt.data["report"]
        if report["learner_sha256"] != learner.sha256 or report["policy_sha256"] != learner.policy.sha256:
            raise ValidationError("Pilot receipt and learner/policy fingerprints disagree.")
        if not isinstance(data["events"], list) or not data["events"]:
            raise ValidationError("Pilot journal requires explicit activation history.")
        journal = cls(receipt, learner, tuple(data["events"]))
        journal.state()
        return journal

    def state(self) -> PilotState:
        state = PilotState(self.receipt, self.learner)
        for event in self.events:
            state.apply(event)
        return state

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": 1, "mode": "local_pilot_simulation", "receipt": self.receipt.to_dict(),
                "learner": self.learner.to_dict(), "events": list(self.events)}


def _event(state: PilotState, action: str, timestamp: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = {"sequence": state.revision + 1, "timestamp": timestamp, "action": action, "payload": payload}
    data["event_sha256"] = _fingerprint(data)
    return data


class PilotStore:
    """One immutable reviewed pilot per local store, with locked accounting/history."""

    def __init__(self, directory: Path):
        ensure_safe(str(directory))
        self.directory = directory
        self.path = directory / "pilot.json"

    @contextmanager
    def _locked(self, create: bool = False) -> Iterator[Optional[PilotJournal]]:
        if fcntl is None:
            raise ValidationError("Local pilot-store locking requires macOS or Linux.")
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValidationError("Pilot store/state cannot be a symbolic link.")
        if not self.directory.exists() and not create:
            raise ValidationError("Activate an explicitly reviewed local simulation before using this pilot store.")
        if create:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(self.directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                journal = None
                if self.path.exists():
                    with os.fdopen(os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as stream:
                        journal = PilotJournal.from_dict(parse_json(stream.read()))
                yield journal
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write(self, journal: PilotJournal) -> None:
        validated = PilotJournal.from_dict(journal.to_dict())
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, prefix=".pilot-", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(validated.to_dict(), stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def read(self) -> PilotJournal:
        with self._locked() as journal:
            if journal is None:
                raise ValidationError("Pilot store has no activation record.")
            return journal

    def activate(self, receipt: PilotReview, learner: LearnedModel, ledger: FeedbackLedger, policy: Policy,
                 roster: ApproverRoster, reviewer_id: str, timestamp: str, reason: str) -> None:
        receipt = PilotReview.from_dict(receipt.to_dict())
        learner = LearnedModel.from_dict(learner.to_dict())
        receipt_report = receipt.data["report"]
        from .readiness import ReadinessReport
        ReadinessReport.from_dict(receipt_report).verify(ledger, policy, learner)
        if not receipt.data["approved_for_local_simulation"]:
            raise ValidationError("Activation requires a separate approved local pilot receipt.")
        for developer in receipt.data["scope"]["developer_ids"]:
            ledger.team.role(developer)
        initial = PilotState(receipt, learner)
        event = _event(initial, "activate", timestamp, {"reviewer_id": reviewer_id,
                       "approver_roster": roster.to_dict(), "reason": reason})
        journal = PilotJournal.from_dict(PilotJournal(receipt, learner, (event,)).to_dict())
        with self._locked(create=True) as existing:
            if existing is not None:
                if existing.receipt != receipt or existing.learner != learner or existing.events[0] != event:
                    raise ValidationError("Pilot store already has different activation content; history/budget cannot be reset.")
                return
            self._write(journal)

    def control(self, action: str, expected_revision: int, roster: ApproverRoster, reviewer_id: str,
                timestamp: str, reason: str, ledger: Optional[FeedbackLedger] = None, policy: Optional[Policy] = None) -> None:
        choice(action, "action", ("pause", "resume", "revoke", "rollback"))
        integer(expected_revision, "expected_revision")
        with self._locked() as journal:
            if journal is None:
                raise ValidationError("Pilot store has no activation record.")
            state = journal.state()
            if state.revision != expected_revision:
                raise ValidationError("Pilot state changed; inspect status before retrying a stale control decision.")
            if action == "resume":
                if ledger is None or policy is None:
                    raise ValidationError("Resume requires current feedback and approved policy checks.")
                journal.learner.verify_source(ledger)
                if policy.fingerprint() != journal.receipt.data["report"]["policy_sha256"]:
                    raise ValidationError("Changed policy requires new pilot review; old approval cannot resume it.")
                if Decimal(state.accounting()["committed_usd"]) > Decimal(state.limits["max_cost_usd"]):
                    raise ValidationError("Pilot is over its budget and cannot resume.")
            event = _event(state, action, timestamp, {"reviewer_id": reviewer_id, "approver_roster": roster.to_dict(), "reason": reason})
            self._write(PilotJournal(journal.receipt, journal.learner, journal.events + (event,)))

    def decide(self, request: PilotRequest, policy: Policy, ledger: FeedbackLedger, roster: ApproverRoster) -> Dict[str, Any]:
        request = PilotRequest.from_dict(request.to_dict())
        ledger = FeedbackLedger.from_dict(ledger.to_dict())
        policy = PolicySnapshot.create(policy).policy
        with self._locked() as journal:
            if journal is None:
                raise ValidationError("Pilot store has no activation record.")
            state = journal.state()
            existing = state.decisions.get(request.decision_id)
            if existing is not None:
                if existing["request"] != request.to_dict() or existing["policy"]["sha256"] != policy.fingerprint():
                    raise ValidationError("Decision ID already has different task/policy content; history cannot be changed.")
                return {"historical_replay": True, "result": existing["result"], "current_pilot_status": state.status,
                        "new_reservation": False, "simulation_admitted": False, "deployment_authorized": False}
            ledger.team.role(request.task.developer_id)
            guard = {"status": "current", "reason": "Current local source and declared approver roster match."}
            try:
                journal.learner.verify_source(ledger)
                designated = roster.designated(journal.receipt.data["reviewer_id"])
                if designated[1] != journal.receipt.data["reviewer_role"]:
                    raise ValidationError("Pilot approver role changed; new review is required.")
                if roster.to_dict() != journal.receipt.data["approver_roster"]:
                    raise ValidationError("Pilot approver roster changed; no current local authorization.")
            except ValidationError as error:
                guard = {"status": "blocked", "reason": str(error)}
            payload = {"request": request.to_dict(), "policy": PolicySnapshot.create(policy).to_dict(), "guard": guard,
                       "result": state.decision(request, policy, guard)}
            event = _event(state, "decision", request.task.timestamp, payload)
            updated = PilotJournal(journal.receipt, journal.learner, journal.events + (event,))
            self._write(updated)
            return {"historical_replay": False, "result": payload["result"], "current_pilot_status": updated.state().status,
                    "new_reservation": payload["result"]["status"] == "reserved",
                    "simulation_admitted": payload["result"]["status"] == "reserved", "deployment_authorized": False}

    def settle(self, value: Any) -> Dict[str, Any]:
        settlement = _settlement(value)
        with self._locked() as journal:
            if journal is None:
                raise ValidationError("Pilot store has no activation record.")
            state = journal.state()
            existing = state.settlements.get(settlement["decision_id"])
            if existing is not None:
                if existing != settlement:
                    raise ValidationError("Settlement already has different content; costs are immutable in this baseline.")
                return self._status(journal)
            event = _event(state, "settle", settlement["timestamp"], settlement)
            updated = PilotJournal(journal.receipt, journal.learner, journal.events + (event,))
            self._write(updated)
            return self._status(updated)

    def _status(self, journal: PilotJournal) -> Dict[str, Any]:
        state = journal.state()
        return {"mode": "local_pilot_simulation", "pilot_id": state.limits["pilot_id"], "status": state.status,
                "revision": state.revision, "last_event_timestamp": state.timestamp, "scope": state.limits,
                "review_sha256": journal.receipt.data["review_sha256"], "accounting": state.accounting(),
                "decisions_recorded": len(state.decisions), "event_count": len(journal.events),
                "local_only": True, "routing_enabled": False, "deployment_authorized": False,
                "note": "Simulation reservations are not actual API dispatch or verified provider cost caps."}

    def status(self) -> Dict[str, Any]:
        return self._status(self.read())
