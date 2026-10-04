"""Local per-task feedback and actual results; no model execution or pilot approval."""

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from .history import PolicySnapshot
from .importers import parse_json
from .policy import decide, incompatibility
from .privacy import ensure_safe
from .schemas import Outcome, Policy, ValidationError, boolean, choice, integer, number, object_fields, strings, text

try:
    import fcntl
except ImportError:
    fcntl = None


def _timestamp(value: Any) -> datetime:
    timestamp = text(value, "timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError("Feedback timestamp must be ISO-8601.") from None
    if parsed.tzinfo is None:
        raise ValidationError("Feedback timestamp must include a timezone.")
    return parsed


def _fingerprint(value: Any) -> str:
    ensure_safe(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class TeamConfig:
    company_api_attested: bool
    members: Tuple[Tuple[str, str], ...]

    @classmethod
    def from_dict(cls, value: Any) -> "TeamConfig":
        data = object_fields(value, ("company_api_attested", "members"), ("company_api_attested", "members"))
        if not boolean(data["company_api_attested"], "company_api_attested"):
            raise ValidationError("Feedback collection requires company-managed API/gateway attestation.")
        if not isinstance(data["members"], list) or not data["members"]:
            raise ValidationError("Declare at least one participating developer.")
        members = []
        for item in data["members"]:
            fields = ("developer_id", "role")
            member = object_fields(item, fields, fields)
            members.append((text(member["developer_id"], "developer_id"),
                            choice(member["role"], "role", ("junior", "developer", "senior"))))
        if len({member[0] for member in members}) != len(members):
            raise ValidationError("Developer IDs must be unique in the collection roster.")
        return cls(True, tuple(members))

    def role(self, developer_id: str) -> str:
        member = next((member for member in self.members if member[0] == developer_id), None)
        if member is None:
            raise ValidationError("Developer is outside the approved local collection roster.")
        return member[1]

    def to_dict(self) -> Dict[str, Any]:
        return {"company_api_attested": self.company_api_attested,
                "members": [{"developer_id": identifier, "role": role} for identifier, role in self.members]}


@dataclass(frozen=True)
class TaskRequest:
    task_id: str
    session_id: str
    developer_id: str
    timestamp: str
    task_type: Optional[str]
    risk_tags: Tuple[str, ...]
    selected_model: str
    required_tools: Tuple[str, ...]
    context_tokens: Optional[int]

    @classmethod
    def from_dict(cls, value: Any) -> "TaskRequest":
        fields = ("task_id", "session_id", "developer_id", "timestamp", "task_type", "risk_tags",
                  "selected_model", "required_tools", "context_tokens")
        data = object_fields(value, fields, fields)
        _timestamp(data["timestamp"])
        return cls(
            text(data["task_id"], "task_id"), text(data["session_id"], "session_id"),
            text(data["developer_id"], "developer_id"), data["timestamp"],
            None if data["task_type"] is None else text(data["task_type"], "task_type"),
            strings(data["risk_tags"], "risk_tags"), text(data["selected_model"], "selected_model"),
            strings(data["required_tools"], "required_tools"),
            None if data["context_tokens"] is None else integer(data["context_tokens"], "context_tokens"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id, "session_id": self.session_id, "developer_id": self.developer_id,
            "timestamp": self.timestamp, "task_type": self.task_type, "risk_tags": list(self.risk_tags),
            "selected_model": self.selected_model, "required_tools": list(self.required_tools),
            "context_tokens": self.context_tokens,
        }


@dataclass(frozen=True)
class _PolicyInput:
    """Only task metadata is supplied to the existing policy, never invented measurements."""

    task_type: Optional[str]
    risk_tags: Tuple[str, ...]
    selected_model: str
    model_tier: str
    required_tools: Tuple[str, ...]
    context_tokens: Optional[int]
    outcome: Outcome = Outcome(None, False, None)


def _policy_input(task: TaskRequest, policy: Policy) -> _PolicyInput:
    model = policy.model(task.selected_model)
    if model is None or not model.approved:
        raise ValidationError("The initial selected model must be registered and approved for company use.")
    return _PolicyInput(task.task_type, task.risk_tags, task.selected_model, model.tier,
                        task.required_tools, task.context_tokens)


@dataclass(frozen=True)
class Response:
    recommendation_id: str
    developer_id: str
    timestamp: str
    response: str

    @classmethod
    def from_dict(cls, value: Any) -> "Response":
        fields = ("recommendation_id", "developer_id", "timestamp", "response")
        data = object_fields(value, fields, fields)
        _timestamp(data["timestamp"])
        return cls(text(data["recommendation_id"], "recommendation_id"),
                   text(data["developer_id"], "developer_id"), data["timestamp"],
                   choice(data["response"], "response", ("accept", "reject")))

    def to_dict(self) -> Dict[str, Any]:
        return {"recommendation_id": self.recommendation_id, "developer_id": self.developer_id,
                "timestamp": self.timestamp, "response": self.response}


@dataclass(frozen=True)
class Execution:
    execution_id: str
    recommendation_id: str
    developer_id: str
    timestamp: str
    actual_model: str

    @classmethod
    def from_dict(cls, value: Any) -> "Execution":
        fields = ("execution_id", "recommendation_id", "developer_id", "timestamp", "actual_model")
        data = object_fields(value, fields, fields)
        _timestamp(data["timestamp"])
        return cls(*(text(data[field], field) for field in fields))

    def to_dict(self) -> Dict[str, Any]:
        return {"execution_id": self.execution_id, "recommendation_id": self.recommendation_id,
                "developer_id": self.developer_id, "timestamp": self.timestamp, "actual_model": self.actual_model}


@dataclass(frozen=True)
class TaskResult:
    result_id: str
    execution_id: str
    reviewer_id: str
    timestamp: str
    desired_result: Optional[bool]
    tests_passed: Optional[bool]
    score: Optional[Decimal]
    cost_usd: Optional[Decimal]
    latency_ms: Optional[int]
    evidence_ref: Optional[str]
    supersedes: Optional[str]

    @classmethod
    def from_dict(cls, value: Any) -> "TaskResult":
        fields = ("result_id", "execution_id", "reviewer_id", "timestamp", "desired_result", "tests_passed",
                  "score", "cost_usd", "latency_ms", "evidence_ref", "supersedes")
        data = object_fields(value, fields, fields)
        _timestamp(data["timestamp"])
        outcome = Outcome.from_dict({"tests_passed": data["tests_passed"], "score": data["score"], "developer_override": False})
        desired = None if data["desired_result"] is None else boolean(data["desired_result"], "desired_result")
        evidence = None if data["evidence_ref"] is None else text(data["evidence_ref"], "evidence_ref")
        if (desired is not None or outcome.tests_passed is not None or outcome.score is not None) and evidence is None:
            raise ValidationError("Known quality results require a metadata-only evidence reference.")
        if desired is True and outcome.tests_passed is False:
            raise ValidationError("A desired-result success cannot contradict a failed test; record a failure or unknown result.")
        return cls(
            text(data["result_id"], "result_id"), text(data["execution_id"], "execution_id"),
            text(data["reviewer_id"], "reviewer_id"), data["timestamp"], desired, outcome.tests_passed, outcome.score,
            None if data["cost_usd"] is None else number(data["cost_usd"], "cost_usd"),
            None if data["latency_ms"] is None else integer(data["latency_ms"], "latency_ms"), evidence,
            None if data["supersedes"] is None else text(data["supersedes"], "supersedes"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id, "execution_id": self.execution_id, "reviewer_id": self.reviewer_id,
            "timestamp": self.timestamp, "desired_result": self.desired_result, "tests_passed": self.tests_passed,
            "score": str(self.score) if self.score is not None else None,
            "cost_usd": str(self.cost_usd) if self.cost_usd is not None else None,
            "latency_ms": self.latency_ms, "evidence_ref": self.evidence_ref, "supersedes": self.supersedes,
        }


@dataclass(frozen=True)
class Recommendation:
    recommendation_id: str
    task: TaskRequest
    policy_sha256: str
    decision: Dict[str, Any]
    learning: Optional[Dict[str, Any]] = None
    suggestion_refusal: Optional[str] = None

    @classmethod
    def create(cls, task: TaskRequest, policy: Policy, learning: Optional[Dict[str, Any]] = None,
               suggestion_refusal: Optional[str] = None) -> "Recommendation":
        if suggestion_refusal is not None:
            if learning is not None:
                raise ValidationError("A refused learner cannot be recorded as applied learning.")
            from .policy import fallback
            decision = fallback(policy, _policy_input(task, policy), "shadow", text(suggestion_refusal, "suggestion_refusal")).to_dict()
        elif learning is None:
            decision = decide(policy, _policy_input(task, policy), "shadow").to_dict()
        else:
            from .learning import LearnedModel, learned_decision
            model = LearnedModel.from_dict(learning)
            learning = model.to_dict()
            decision = learned_decision(task, policy, model).to_dict()
        digest = policy.fingerprint()
        identity = {"task": task.to_dict(), "policy_sha256": digest}
        if learning is not None:
            identity["learner_sha256"] = learning["learner_sha256"]
        if suggestion_refusal is not None:
            identity["suggestion_refusal"] = suggestion_refusal
        identifier = "rec_" + _fingerprint(identity)
        return cls(identifier, task, digest, decision, learning, suggestion_refusal)

    def to_dict(self) -> Dict[str, Any]:
        data = {"recommendation_id": self.recommendation_id, "task": self.task.to_dict(),
                "policy_sha256": self.policy_sha256, "decision": self.decision}
        if self.learning is not None:
            data["learning"] = self.learning
        if self.suggestion_refusal is not None:
            data["suggestion_refusal"] = self.suggestion_refusal
        return data


@dataclass(frozen=True)
class RoleAttribution:
    """A historical role label, not identity proof; authenticated callers bind it separately."""

    record_kind: str
    record_id: str
    developer_id: str
    role: str

    @classmethod
    def from_dict(cls, value: Any) -> "RoleAttribution":
        fields = ("record_kind", "record_id", "developer_id", "role")
        data = object_fields(value, fields, fields)
        return cls(choice(data["record_kind"], "record_kind", ("recommendation", "response", "execution", "result")),
                   text(data["record_id"], "record_id"), text(data["developer_id"], "developer_id"),
                   choice(data["role"], "role", ("junior", "developer", "senior")))

    def to_dict(self) -> Dict[str, Any]:
        return {"record_kind": self.record_kind, "record_id": self.record_id,
                "developer_id": self.developer_id, "role": self.role}


@dataclass(frozen=True)
class FeedbackLedger:
    team: TeamConfig
    policies: Tuple[PolicySnapshot, ...] = ()
    recommendations: Tuple[Recommendation, ...] = ()
    responses: Tuple[Response, ...] = ()
    executions: Tuple[Execution, ...] = ()
    results: Tuple[TaskResult, ...] = ()
    role_attributions: Optional[Tuple[RoleAttribution, ...]] = None

    @classmethod
    def from_dict(cls, value: Any) -> "FeedbackLedger":
        fields = ("schema_version", "team", "policies", "recommendations", "responses", "executions", "results")
        data = object_fields(value, fields + ("role_attributions",), fields)
        ensure_safe(data)
        if type(data["schema_version"]) is not int or data["schema_version"] not in (1, 2):
            raise ValidationError("Unsupported feedback-ledger schema version.")
        if (data["schema_version"] == 2) != ("role_attributions" in data):
            raise ValidationError("Per-record role attributions require ledger schema 2; schema 1 remains unchanged.")
        for field in fields[2:]:
            if not isinstance(data[field], list):
                raise ValidationError("Feedback ledger collections must be arrays.")
        team = TeamConfig.from_dict(data["team"])
        policies = tuple(PolicySnapshot.from_dict(item) for item in data["policies"])
        by_digest = {snapshot.sha256: snapshot.policy for snapshot in policies}
        if len(by_digest) != len(policies) or len({item.policy.policy_version for item in policies}) != len(policies):
            raise ValidationError("Feedback policy versions and fingerprints must be unique.")
        recommendations = []
        task_ids = set()
        for item in data["recommendations"]:
            fields = ("recommendation_id", "task", "policy_sha256", "decision")
            rec = object_fields(item, fields + ("learning", "suggestion_refusal"), fields)
            task = TaskRequest.from_dict(rec["task"])
            team.role(task.developer_id)
            policy = by_digest.get(text(rec["policy_sha256"], "policy_sha256"))
            if policy is None:
                raise ValidationError("Recommendation has no matching saved policy.")
            expected = Recommendation.create(task, policy, rec.get("learning"), rec.get("suggestion_refusal"))
            if expected.to_dict() != rec:
                raise ValidationError("Stored recommendation differs from its task/policy; feedback history is not trusted.")
            identity = (task.session_id, task.task_id)
            if identity in task_ids:
                raise ValidationError("Only one recommendation per task/session is supported; do not duplicate learning evidence.")
            task_ids.add(identity)
            recommendations.append(expected)
        by_rec = {rec.recommendation_id: rec for rec in recommendations}
        responses = tuple(Response.from_dict(item) for item in data["responses"])
        if len({item.recommendation_id for item in responses}) != len(responses):
            raise ValidationError("Only one immutable response is supported per recommendation.")
        for response in responses:
            rec = by_rec.get(response.recommendation_id)
            if rec is None or response.developer_id != rec.task.developer_id:
                raise ValidationError("Per-task response must refer to its own developer and recommendation.")
            if _timestamp(response.timestamp) < _timestamp(rec.task.timestamp):
                raise ValidationError("Response precedes its recommendation.")
        by_response = {item.recommendation_id: item for item in responses}
        executions = tuple(Execution.from_dict(item) for item in data["executions"])
        if len({item.execution_id for item in executions}) != len(executions) or len({item.recommendation_id for item in executions}) != len(executions):
            raise ValidationError("Only one execution per recommendation is supported in the local baseline.")
        for execution in executions:
            rec = by_rec.get(execution.recommendation_id)
            if rec is None or execution.developer_id != rec.task.developer_id:
                raise ValidationError("Execution must refer to its own developer and recommendation.")
            if _timestamp(execution.timestamp) < _timestamp(rec.task.timestamp):
                raise ValidationError("Execution precedes its recommendation.")
            response = by_response.get(rec.recommendation_id)
            if response is not None and _timestamp(response.timestamp) > _timestamp(execution.timestamp):
                raise ValidationError("Acceptance/rejection must describe a response before execution, not post-hoc approval.")
            text(execution.actual_model, "actual_model")
        by_execution = {item.execution_id: item for item in executions}
        results = tuple(TaskResult.from_dict(item) for item in data["results"])
        if len({item.result_id for item in results}) != len(results):
            raise ValidationError("Result IDs must be unique, including corrections.")
        latest = {}
        for result in results:
            execution = by_execution.get(result.execution_id)
            if execution is None:
                raise ValidationError("Result has no recorded actual-model execution.")
            team.role(result.reviewer_id)
            previous = latest.get(result.execution_id)
            if result.supersedes != (previous.result_id if previous else None):
                raise ValidationError("Result correction must supersede the current result for this execution.")
            start = previous.timestamp if previous else execution.timestamp
            if _timestamp(result.timestamp) < _timestamp(start):
                raise ValidationError("Result precedes execution or its previous correction.")
            latest[result.execution_id] = result
        attributions = None
        if data["schema_version"] == 2:
            if not isinstance(data["role_attributions"], list):
                raise ValidationError("Historical role attributions must be an array.")
            attributions = tuple(RoleAttribution.from_dict(item) for item in data["role_attributions"])
            actors = {("recommendation", item.recommendation_id): item.task.developer_id for item in recommendations}
            actors.update({("response", item.recommendation_id): item.developer_id for item in responses})
            actors.update({("execution", item.execution_id): item.developer_id for item in executions})
            actors.update({("result", item.result_id): item.reviewer_id for item in results})
            seen = set()
            for attribution in attributions:
                identity = (attribution.record_kind, attribution.record_id)
                if identity in seen or actors.get(identity) != attribution.developer_id:
                    raise ValidationError("Role attribution is duplicated or does not match its recorded actor.")
                seen.add(identity)
            if seen != set(actors):
                raise ValidationError("Historical role attributions must cover every recorded action exactly once.")
        return cls(team, policies, tuple(recommendations), responses, executions, results, attributions)

    def record_role(self, kind: str, record_id: str, developer_id: str) -> str:
        if self.role_attributions is None:
            return self.team.role(developer_id)
        entry = next((item for item in self.role_attributions
                      if (item.record_kind, item.record_id, item.developer_id) == (kind, record_id, developer_id)), None)
        if entry is None:
            raise ValidationError("Recorded action has no matching historical role attribution.")
        return entry.role

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "schema_version": 1 if self.role_attributions is None else 2, "team": self.team.to_dict(),
            "policies": [item.to_dict() for item in self.policies],
            "recommendations": [item.to_dict() for item in self.recommendations],
            "responses": [item.to_dict() for item in self.responses],
            "executions": [item.to_dict() for item in self.executions],
            "results": [item.to_dict() for item in self.results],
        }
        if self.role_attributions is not None:
            data["role_attributions"] = [item.to_dict() for item in self.role_attributions]
        return data


class FeedbackStore:
    """Private local JSON ledger with serialized, validated updates."""

    def __init__(self, directory: Path):
        ensure_safe(str(directory))
        self.directory = directory
        self.path = directory / "feedback.json"

    @contextmanager
    def _locked(self, create: bool = False) -> Iterator[Optional[FeedbackLedger]]:
        if fcntl is None:
            raise ValidationError("Local feedback-store locking currently requires macOS or Linux.")
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValidationError("Feedback-store directory/state cannot be a symbolic link.")
        if not self.directory.exists() and not create:
            raise ValidationError("Initialize the local feedback store with an approved roster first.")
        if create:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(self.directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                ledger = None
                if self.path.exists():
                    with os.fdopen(os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as stream:
                        ledger = FeedbackLedger.from_dict(parse_json(stream.read()))
                yield ledger
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write(self, ledger: FeedbackLedger) -> None:
        validated = FeedbackLedger.from_dict(ledger.to_dict())
        content = json.dumps(validated.to_dict(), indent=2, ensure_ascii=False) + "\n"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, prefix=".feedback-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def initialize(self, team: TeamConfig) -> FeedbackLedger:
        team = TeamConfig.from_dict(team.to_dict())
        with self._locked(create=True) as ledger:
            if ledger is not None:
                if ledger.team != team:
                    raise ValidationError("The collection roster is immutable in this baseline; use a separate reviewed store.")
                return ledger
            ledger = FeedbackLedger(team)
            self._write(ledger)
            return ledger

    def read(self) -> FeedbackLedger:
        with self._locked() as ledger:
            if ledger is None:
                raise ValidationError("Feedback store is not initialized.")
            return ledger

    def import_ledger(self, ledger: FeedbackLedger) -> None:
        ledger = FeedbackLedger.from_dict(ledger.to_dict())
        with self._locked(create=True) as existing:
            if existing is not None:
                if existing != ledger:
                    raise ValidationError("Bulk import needs an empty store; existing feedback is never replaced.")
                return
            self._write(ledger)

    def recommend(self, task: TaskRequest, policy: Policy, learning: Optional[Dict[str, Any]] = None) -> Recommendation:
        task = TaskRequest.from_dict(task.to_dict())
        snapshot = PolicySnapshot.create(policy)
        rec = Recommendation.create(task, snapshot.policy, learning)
        with self._locked() as ledger:
            if ledger is None:
                raise ValidationError("Feedback store is not initialized.")
            ledger.team.role(task.developer_id)
            existing = next((item for item in ledger.recommendations
                             if (item.task.session_id, item.task.task_id) == (task.session_id, task.task_id)), None)
            if existing is not None:
                if existing != rec:
                    raise ValidationError("Task/session already has a different recommendation; no evidence is overwritten.")
                return existing
            if ledger.role_attributions is not None:
                raise ValidationError("Per-record role ledgers require explicit new attributions; the legacy writer cannot discard them.")
            if learning is not None:
                from .learning import LearnedModel
                LearnedModel.from_dict(learning).verify_source(ledger)
            saved = next((item for item in ledger.policies if item.policy.policy_version == policy.policy_version), None)
            if saved is not None and saved.sha256 != snapshot.sha256:
                raise ValidationError("Policy version has changed content; supply a new version.")
            policies = ledger.policies if saved else ledger.policies + (snapshot,)
            updated = FeedbackLedger(ledger.team, policies, ledger.recommendations + (rec,),
                                     ledger.responses, ledger.executions, ledger.results)
            self._write(updated)
        return rec

    def record(self, kind: str, value: Any) -> None:
        parsers = {"response": Response, "execution": Execution, "result": TaskResult}
        if kind not in parsers:
            raise ValidationError("Only response, execution, and result records can be appended.")
        item = parsers[kind].from_dict(value)
        collection = {"response": "responses", "execution": "executions", "result": "results"}[kind]
        key = {"response": "recommendation_id", "execution": "execution_id", "result": "result_id"}[kind]
        with self._locked() as ledger:
            if ledger is None:
                raise ValidationError("Feedback store is not initialized.")
            existing = next((entry for entry in getattr(ledger, collection) if getattr(entry, key) == getattr(item, key)), None)
            if existing is not None:
                if existing != item:
                    raise ValidationError("Record ID already has different content; immutable history cannot be overwritten.")
                return
            data = ledger.to_dict()
            data[collection].append(item.to_dict())
            self._write(FeedbackLedger.from_dict(data))


def feedback_summary(ledger: FeedbackLedger, policy: Policy) -> Dict[str, Any]:
    """Rank observed evidence for manual review, not validated learning thresholds."""
    ledger = FeedbackLedger.from_dict(ledger.to_dict())
    policy = Policy.from_dict(policy.to_dict())
    responses = {item.recommendation_id: item for item in ledger.responses}
    executions = {item.recommendation_id: item for item in ledger.executions}
    latest = {item.execution_id: item for item in ledger.results}
    groups = {}
    rows = []

    def group(task_type: Optional[str], model: str) -> Dict[str, Any]:
        key = (task_type, model)
        if key not in groups:
            groups[key] = {
                "task_type": task_type, "model": model, "suggestions": 0, "accepts": 0, "rejects": 0,
                "senior_accepts": 0, "senior_rejects": 0, "unanswered_suggestions": 0,
                "accepted_without_execution": 0, "accepted_but_different_model": 0,
                "executions": 0, "confirmed_successes": 0, "confirmed_failures": 0,
                "unknown_results": 0, "senior_adopted_successes": 0, "senior_success_sessions": set(),
                "non_senior_failures": 0, "incompatible_executions": 0,
            }
        return groups[key]

    for rec in sorted(ledger.recommendations, key=lambda item: (item.task.session_id, item.task.task_id)):
        role = ledger.record_role("recommendation", rec.recommendation_id, rec.task.developer_id)
        response = responses.get(rec.recommendation_id)
        response_role = ledger.record_role("response", response.recommendation_id, response.developer_id) if response else None
        execution = executions.get(rec.recommendation_id)
        result = latest.get(execution.execution_id) if execution else None
        suggested = rec.decision["recommended_model"]
        if suggested is not None:
            target = group(rec.task.task_type, suggested)
            target["suggestions"] += 1
            if response:
                target["accepts" if response.response == "accept" else "rejects"] += 1
                if response_role == "senior":
                    target["senior_accepts" if response.response == "accept" else "senior_rejects"] += 1
                if response.response == "accept":
                    target["accepted_without_execution"] += execution is None
                    target["accepted_but_different_model"] += execution is not None and execution.actual_model != suggested
            else:
                target["unanswered_suggestions"] += 1
        actual = execution.actual_model if execution else None
        matched = execution is not None and actual == suggested
        success = result is not None and result.desired_result is True and result.tests_passed is not False
        failure = result is not None and (result.desired_result is False or result.tests_passed is False)
        senior_confirmed = result is not None and ledger.record_role("result", result.result_id, result.reviewer_id) == "senior"
        issue = None
        if execution:
            task_input = _policy_input(rec.task, next(item.policy for item in ledger.policies if item.sha256 == rec.policy_sha256))
            issue = incompatibility(policy.model(actual), task_input)
            actual_group = group(rec.task.task_type, actual)
            actual_group["executions"] += 1
            actual_group["confirmed_successes"] += bool(success)
            actual_group["confirmed_failures"] += bool(failure)
            actual_group["unknown_results"] += not (success or failure)
            actual_group["non_senior_failures"] += failure and role != "senior"
            actual_group["incompatible_executions"] += issue is not None
            adopted = (role == "senior" and response is not None and response_role == "senior" and response.response == "accept"
                       and matched and success and senior_confirmed and issue is None and set(rec.task.risk_tags) == {"low"})
            if adopted:
                actual_group["senior_adopted_successes"] += 1
                actual_group["senior_success_sessions"].add(rec.task.session_id)
        rows.append({
            "recommendation_id": rec.recommendation_id, "task_id": rec.task.task_id,
            "session_id": rec.task.session_id, "developer_role": role,
            "task_type": rec.task.task_type,
            "response": response.response if response else None, "suggested_model": suggested,
            "actual_model": actual, "suggestion_used": matched, "result_id": result.result_id if result else None,
            "desired_result": result.desired_result if result else None,
            "result_status": "success" if success else "failure" if failure else "unknown",
            "senior_confirmed": senior_confirmed, "compatibility_issue": issue,
            "model_override": execution is not None and actual != suggested,
            "tests_passed": result.tests_passed if result else None,
            "score": str(result.score) if result and result.score is not None else None,
            "cost_usd": str(result.cost_usd) if result and result.cost_usd is not None else None,
            "latency_ms": result.latency_ms if result else None,
            "pending_execution": execution is None, "pending_result": execution is not None and result is None,
        })

    ranked = []
    for (task_type, model), stats in sorted(groups.items(), key=lambda item: (item[0][0] or "", item[0][1])):
        stats["senior_success_sessions"] = len(stats["senior_success_sessions"])
        current = policy.model(model)
        reasons = []
        if current is None or not current.approved:
            reasons.append("Model is not currently approved in the supplied policy.")
        if task_type is None:
            reasons.append("Task category is unknown.")
        if stats["confirmed_failures"]:
            reasons.append("Recorded failures exist, including non-senior outcomes; investigate rather than discard them.")
        if stats["incompatible_executions"]:
            reasons.append("Observed task/model compatibility is missing or invalid.")
        if not stats["senior_adopted_successes"]:
            reasons.append("No senior-accepted, actually-used, senior-confirmed success supports this model/category.")
        if stats["unknown_results"]:
            reasons.append("Some executed tasks have unknown results.")
        stats["status"] = "investigate_failures" if stats["confirmed_failures"] else (
            "candidate_for_manual_review" if not reasons else "collect_more_evidence"
        )
        stats["reasons"] = reasons or ["Observed senior adoption successes support review, not a safety or routing-approval claim."]
        ranked.append(stats)
    ranked.sort(key=lambda item: (item["task_type"] or "", -item["senior_adopted_successes"],
                                 -item["senior_success_sessions"], -item["confirmed_successes"], item["model"]))
    report = {
        "schema_version": 1, "mode": "feedback_summary", "policy_version": policy.policy_version,
        "policy_sha256": policy.fingerprint(), "roles_source": "declared_local_roster_unverified" if ledger.role_attributions is None
        else "declared_event_role_attributions_unverified",
        "outcome_source": "declared_local_confirmation_unverified",
        "recommendations": len(rows), "responses": len(ledger.responses), "executions": len(ledger.executions),
        "result_revisions": len(ledger.results), "current_results": len(latest),
        "pending_executions": sum(row["pending_execution"] for row in rows),
        "pending_results": sum(row["pending_result"] for row in rows),
        "model_overrides": sum(row["model_override"] for row in rows),
        "result_history": [
            {"result_id": item.result_id, "execution_id": item.execution_id,
              "reviewer_role": ledger.record_role("result", item.result_id, item.reviewer_id), "timestamp": item.timestamp,
             "desired_result": item.desired_result, "tests_passed": item.tests_passed,
             "score": str(item.score) if item.score is not None else None,
             "supersedes": item.supersedes,
             "is_current": latest[item.execution_id].result_id == item.result_id}
            for item in sorted(ledger.results, key=lambda entry: (entry.execution_id, _timestamp(entry.timestamp), entry.result_id))
        ],
        "groups": ranked, "tasks": rows, "changes_policy": False, "deployment_authorized": False,
        "notes": [
            "Local records do not execute models, verify identities, collect live sessions, or authorize a pilot.",
            "Link consistency is validated; supplied outcome confirmations and evidence labels are not independently verified.",
            "Acceptance is preference; only the model actually used receives its recorded outcome.",
            "Senior adopted successes lead the review ranking; everyone's failures, rejects, and unknowns remain visible.",
            "Latest result corrections replace earlier evidence in summaries without deleting history or double counting.",
            "Ranking is a simple baseline, not validated training weights, statistical confidence, or automatic pilot readiness.",
            "No counterfactual quality or production savings are inferred from these observations.",
        ],
    }
    ensure_safe(report)
    return report


def import_scenario(value: Any, policy: Policy) -> FeedbackLedger:
    """Import explicitly supplied local observations, not generated model outcomes."""
    root = object_fields(value, ("team", "tasks"), ("team", "tasks"))
    ensure_safe(root)
    team = TeamConfig.from_dict(root["team"])
    if not isinstance(root["tasks"], list):
        raise ValidationError("Scenario tasks must be an array.")
    recommendations, responses, executions, results = [], [], [], []
    for item in root["tasks"]:
        fields = ("task", "response", "execution", "result")
        data = object_fields(item, fields, fields)
        rec = Recommendation.create(TaskRequest.from_dict(data["task"]), policy)
        recommendations.append(rec)
        if data["response"] is not None:
            fields = ("developer_id", "timestamp", "response")
            response = object_fields(data["response"], fields, fields)
            responses.append(Response.from_dict(dict(response, recommendation_id=rec.recommendation_id)))
        execution = None
        if data["execution"] is not None:
            fields = ("execution_id", "developer_id", "timestamp", "actual_model")
            execution_data = object_fields(data["execution"], fields, fields)
            execution = Execution.from_dict(dict(execution_data, recommendation_id=rec.recommendation_id))
            executions.append(execution)
        if data["result"] is not None:
            result = TaskResult.from_dict(data["result"])
            if execution is None or result.execution_id != execution.execution_id:
                raise ValidationError("Scenario result must belong to its own task's execution.")
            results.append(result)
    ledger = FeedbackLedger(team, (PolicySnapshot.create(policy),), tuple(recommendations),
                            tuple(responses), tuple(executions), tuple(results))
    return FeedbackLedger.from_dict(ledger.to_dict())
