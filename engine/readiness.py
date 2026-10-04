"""Category review and local pilot receipts; neither authorizes live deployment."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

from .exporters import _write_private
from .feedback import FeedbackLedger, _fingerprint, _timestamp, feedback_summary
from .importers import parse_json
from .learning import EVIDENCE_FIELDS, LearnedModel, _source_digest
from .privacy import ensure_safe
from .schemas import Policy, ValidationError, boolean, choice, integer, number, object_fields, strings, text


def _digest(value: Any, name: str) -> str:
    result = text(value, name)
    if not re.fullmatch(r"[a-f0-9]{64}", result):
        raise ValidationError(f"{name} must be a content fingerprint.")
    return result


@dataclass(frozen=True)
class ReadinessReport:
    data: Dict[str, Any]

    @classmethod
    def from_dict(cls, value: Any) -> "ReadinessReport":
        fields = ("schema_version", "record_type", "policy_version", "policy_sha256", "learner_version",
                  "learner_sha256", "feedback_sha256", "fallback_model", "source_kind", "source_status",
                  "observed_through", "counts", "categories", "observations", "result_history", "warnings", "local_only",
                  "deployment_ready", "deployment_authorized", "report_sha256")
        data = object_fields(value, fields, fields)
        ensure_safe(data)
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValidationError("Unsupported readiness report schema.")
        choice(data["record_type"], "record_type", ("category_review_report",))
        for name in ("policy_version", "learner_version", "fallback_model"):
            text(data[name], name)
        for name in ("policy_sha256", "learner_sha256", "feedback_sha256", "report_sha256"):
            _digest(data[name], name)
        choice(data["source_kind"], "source_kind", ("synthetic", "team"))
        choice(data["source_status"], "source_status", ("current", "blocked"))
        _timestamp(data["observed_through"])
        count_fields = ("recommendations", "responses", "executions", "current_results", "result_revisions",
                        "pending_executions", "pending_results", "model_overrides")
        counts = object_fields(data["counts"], count_fields, count_fields)
        for name in count_fields:
            integer(counts[name], name)
        if counts["executions"] + counts["pending_executions"] != counts["recommendations"]:
            raise ValidationError("Readiness execution coverage counts disagree.")
        if counts["current_results"] + counts["pending_results"] != counts["executions"]:
            raise ValidationError("Readiness result coverage counts disagree.")
        if counts["responses"] > counts["recommendations"] or counts["result_revisions"] < counts["current_results"]:
            raise ValidationError("Readiness response/revision counts disagree.")
        if not isinstance(data["categories"], list) or not data["categories"]:
            raise ValidationError("Readiness must declare nonempty task-category reviews.")
        seen = set()
        for category in data["categories"]:
            fields = ("task_type", "suggested_model", "status", "blockers", "evidence", "gaps")
            item = object_fields(category, fields, fields)
            category_id = text(item["task_type"], "task_type")
            if category_id in seen or category_id == "*":
                raise ValidationError("Readiness categories must be explicit and unique.")
            seen.add(category_id)
            choice(item["status"], "status", ("ready_for_local_review", "blocked"))
            strings(item["blockers"], "blockers")
            if item["suggested_model"] is not None:
                text(item["suggested_model"], "suggested_model")
            if item["status"] == "ready_for_local_review" and (
                item["suggested_model"] is None or item["blockers"] or data["source_status"] != "current"
            ):
                raise ValidationError("A blocked or unassigned category cannot be ready for local review.")
            if item["status"] == "blocked" and not item["blockers"]:
                raise ValidationError("Blocked categories require explicit reasons.")
            if not isinstance(item["evidence"], list):
                raise ValidationError("Category evidence must be an array.")
            models = set()
            for value in item["evidence"]:
                evidence = object_fields(value, EVIDENCE_FIELDS, EVIDENCE_FIELDS)
                if evidence["task_type"] != category_id:
                    raise ValidationError("Category evidence names a different task type.")
                model = text(evidence["model"], "model")
                if model in models:
                    raise ValidationError("Category review contains duplicate model evidence.")
                models.add(model)
                for name in EVIDENCE_FIELDS[2:-2]:
                    integer(evidence[name], name)
                choice(evidence["status"], "status", ("candidate_for_manual_review", "collect_more_evidence", "investigate_failures"))
                strings(evidence["reasons"], "reasons")
            if item["status"] == "ready_for_local_review":
                candidate = next((group for group in item["evidence"] if group["model"] == item["suggested_model"]), None)
                if candidate is None or candidate["senior_adopted_successes"] == 0 or any(
                    candidate[name] for name in ("confirmed_failures", "rejects", "unknown_results", "incompatible_executions")
                ):
                    raise ValidationError("A ready-for-local-review candidate requires actual senior-adoption evidence without known negative signals.")
            gaps = object_fields(item["gaps"], ("pending_executions", "unanswered_suggestions", "accepted_but_different_model"),
                                 ("pending_executions", "unanswered_suggestions", "accepted_but_different_model"))
            for name in gaps:
                integer(gaps[name], name)
        strings(data["warnings"], "warnings")
        if not isinstance(data["observations"], list) or len(data["observations"]) != counts["recommendations"]:
            raise ValidationError("Readiness observations must account for every recorded recommendation.")
        if not isinstance(data["result_history"], list) or len(data["result_history"]) != counts["result_revisions"]:
            raise ValidationError("Readiness result history must retain recorded revisions.")
        if not boolean(data["local_only"], "local_only") or boolean(data["deployment_ready"], "deployment_ready") or boolean(data["deployment_authorized"], "deployment_authorized"):
            raise ValidationError("This readiness baseline cannot declare production readiness or authorize deployment.")
        payload = {key: data[key] for key in data if key != "report_sha256"}
        if _fingerprint(payload) != data["report_sha256"]:
            raise ValidationError("Readiness report content fingerprint disagrees.")
        return cls(data)

    def to_dict(self) -> Dict[str, Any]:
        ReadinessReport.from_dict(self.data)
        return self.data

    def export(self, path: Path) -> None:
        _write_private(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", path)

    def verify(self, ledger: FeedbackLedger, policy: Policy, learner: LearnedModel) -> None:
        expected = build_readiness(ledger, policy, learner)
        if self.to_dict() != expected.to_dict():
            raise ValidationError("Readiness report no longer matches current feedback/policy/learner; regenerate before reviewing.")


def build_readiness(ledger: FeedbackLedger, policy: Policy, learner: LearnedModel) -> ReadinessReport:
    ledger = FeedbackLedger.from_dict(ledger.to_dict())
    learner = LearnedModel.from_dict(learner.to_dict())
    summary = feedback_summary(ledger, policy)
    source_error = None
    try:
        learner.verify_source(ledger)
    except ValidationError as error:
        source_error = str(error)
    if policy.fingerprint() != learner.policy.sha256:
        source_error = "Current policy differs from the learner's fitted policy; refit before review."
    categories = []
    for rule in learner.payload()["rules"]:
        category = rule["task_type"]
        current_rows = [row for row in summary["tasks"] if row["task_type"] == category]
        evidence = [item for item in summary["groups"] if item["task_type"] == category]
        blockers = []
        if source_error:
            blockers.append(source_error)
        if rule["recommended_model"] is None:
            blockers.extend(reason for candidate in rule["candidates"] for reason in candidate["reasons"])
            if not blockers:
                blockers.append("No learned candidate has evidence for this category.")
        candidate_evidence = next((item for item in evidence if item["model"] == rule["recommended_model"]), None)
        if candidate_evidence and (candidate_evidence["confirmed_failures"] or candidate_evidence["rejects"] or candidate_evidence["incompatible_executions"] or candidate_evidence["unknown_results"]):
            blockers.append("Current candidate evidence contains failures, rejections, incompatibilities, or unknown executed results.")
        gaps = {
            "pending_executions": sum(row["pending_execution"] for row in current_rows),
            "unanswered_suggestions": sum(row["response"] is None for row in current_rows),
            "accepted_but_different_model": sum(row["response"] == "accept" and row["actual_model"] is not None
                                              and not row["suggestion_used"] for row in current_rows),
        }
        categories.append({"task_type": category, "suggested_model": rule["recommended_model"],
                           "status": "blocked" if blockers else "ready_for_local_review",
                           "blockers": list(dict.fromkeys(blockers)), "evidence": evidence, "gaps": gaps})
    count_fields = ("recommendations", "responses", "executions", "current_results", "result_revisions",
                    "pending_executions", "pending_results", "model_overrides")
    data = {
        "schema_version": 1, "record_type": "category_review_report",
        "policy_version": policy.policy_version, "policy_sha256": policy.fingerprint(),
        "learner_version": learner.plan.learner_version, "learner_sha256": learner.sha256,
        "feedback_sha256": _source_digest(ledger), "fallback_model": policy.default_model,
        "source_kind": learner.plan.source_kind, "source_status": "blocked" if source_error else "current",
        "observed_through": max([learner.plan.cutoff] + [rec.task.timestamp for rec in ledger.recommendations]
                                + [item.timestamp for item in (*ledger.responses, *ledger.executions, *ledger.results)],
                                key=_timestamp),
        "counts": {name: summary[name] for name in count_fields}, "categories": categories,
        "observations": summary["tasks"], "result_history": summary["result_history"],
        "warnings": [
            "Ready for local review is not production readiness, statistical safety, or permission to route live tasks.",
            "Developer/reviewer identities and task confirmations are declared locally, not independently verified.",
            "The learner's caller-declared validation requirements are experimental, not production-approved thresholds.",
            "Pending tasks, unanswered suggestions, model mismatches, and all negative evidence remain visible.",
            "A designated senior/admin must separately review the exact pilot scope; per-task acceptance is insufficient.",
            "Synthetic evidence cannot establish production savings or quality.",
        ],
        "local_only": True, "deployment_ready": False, "deployment_authorized": False,
    }
    data["report_sha256"] = _fingerprint(data)
    return ReadinessReport.from_dict(data)


@dataclass(frozen=True)
class ApproverRoster:
    entries: Tuple[Tuple[str, str, bool], ...]

    @classmethod
    def from_dict(cls, value: Any) -> "ApproverRoster":
        data = object_fields(value, ("approvers",), ("approvers",))
        if not isinstance(data["approvers"], list) or not data["approvers"]:
            raise ValidationError("Declare a separate pilot-approver allowlist.")
        entries = []
        for value in data["approvers"]:
            fields = ("approver_id", "role", "can_approve_pilots")
            item = object_fields(value, fields, fields)
            entries.append((text(item["approver_id"], "approver_id"),
                            choice(item["role"], "role", ("senior", "admin")),
                            boolean(item["can_approve_pilots"], "can_approve_pilots")))
        if len({item[0] for item in entries}) != len(entries):
            raise ValidationError("Pilot approver IDs must be unique.")
        return cls(tuple(entries))

    def designated(self, identifier: str) -> Tuple[str, str, bool]:
        item = next((item for item in self.entries if item[0] == identifier), None)
        if item is None or not item[2]:
            raise ValidationError("Reviewer is not explicitly designated to approve/reject pilot scopes.")
        return item

    def to_dict(self) -> Dict[str, Any]:
        return {"approvers": [{"approver_id": item[0], "role": item[1], "can_approve_pilots": item[2]}
                              for item in self.entries]}


@dataclass(frozen=True)
class PilotScope:
    pilot_id: str
    repository_ref: str
    task_types: Tuple[str, ...]
    developer_ids: Tuple[str, ...]
    max_tasks: int
    max_cost_usd: str

    @classmethod
    def from_dict(cls, value: Any) -> "PilotScope":
        fields = ("pilot_id", "repository_ref", "task_types", "developer_ids", "max_tasks", "max_cost_usd")
        data = object_fields(value, fields, fields)
        categories = strings(data["task_types"], "task_types")
        developers = strings(data["developer_ids"], "developer_ids")
        if not categories or not developers or "*" in categories or "*" in developers:
            raise ValidationError("Pilot task categories and developers must be explicit nonempty lists.")
        tasks = integer(data["max_tasks"], "max_tasks")
        cost = number(data["max_cost_usd"], "max_cost_usd")
        if tasks == 0 or cost == 0:
            raise ValidationError("Pilot scopes must declare positive task and cost limits.")
        return cls(text(data["pilot_id"], "pilot_id"), text(data["repository_ref"], "repository_ref"),
                   categories, developers, tasks, str(cost))

    def to_dict(self) -> Dict[str, Any]:
        return {"pilot_id": self.pilot_id, "repository_ref": self.repository_ref,
                "task_types": list(self.task_types), "developer_ids": list(self.developer_ids),
                "max_tasks": self.max_tasks, "max_cost_usd": self.max_cost_usd}


@dataclass(frozen=True)
class PilotReview:
    data: Dict[str, Any]

    @classmethod
    def from_dict(cls, value: Any) -> "PilotReview":
        fields = ("schema_version", "record_type", "report", "scope", "approver_roster", "reviewer_id",
                  "reviewer_role", "decision", "timestamp", "reason", "routes", "approved_for_local_simulation",
                  "reviewer_identity_source", "limits_enforced", "local_only", "routing_enabled", "deployment_authorized", "review_sha256")
        data = object_fields(value, fields, fields)
        ensure_safe(data)
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValidationError("Unsupported pilot-review schema.")
        choice(data["record_type"], "record_type", ("local_pilot_review",))
        report = ReadinessReport.from_dict(data["report"])
        scope = PilotScope.from_dict(data["scope"])
        roster = ApproverRoster.from_dict(data["approver_roster"])
        reviewer = roster.designated(text(data["reviewer_id"], "reviewer_id"))
        if data["reviewer_role"] != reviewer[1]:
            raise ValidationError("Pilot reviewer role differs from its designated roster entry.")
        decision = choice(data["decision"], "decision", ("approve", "reject"))
        if _timestamp(data["timestamp"]) < _timestamp(report.data["observed_through"]):
            raise ValidationError("Pilot review timestamp cannot precede the evidence it claims to review.")
        text(data["reason"], "reason")
        categories = {item["task_type"]: item for item in report.data["categories"]}
        if set(scope.task_types) - set(categories):
            raise ValidationError("Pilot scope contains task categories absent from the reviewed report.")
        if decision == "approve" and any(categories[name]["status"] != "ready_for_local_review" for name in scope.task_types):
            raise ValidationError("A blocked category cannot be approved, even for local simulation.")
        routes = [{"task_type": category, "model": categories[category]["suggested_model"]}
                  for category in scope.task_types] if decision == "approve" else []
        if data["routes"] != routes:
            raise ValidationError("Pilot routes must match the exact reviewed category/model scope.")
        if boolean(data["approved_for_local_simulation"], "approved_for_local_simulation") != (decision == "approve"):
            raise ValidationError("Local simulation approval contradicts the review decision.")
        choice(data["reviewer_identity_source"], "reviewer_identity_source", ("declared_local_allowlist_unverified",))
        if boolean(data["limits_enforced"], "limits_enforced"):
            raise ValidationError("Review receipts declare future simulation limits; they cannot claim executed limit enforcement.")
        if not boolean(data["local_only"], "local_only") or boolean(data["routing_enabled"], "routing_enabled") or boolean(data["deployment_authorized"], "deployment_authorized"):
            raise ValidationError("Local pilot receipts cannot enable routing or live deployment.")
        payload = {key: data[key] for key in data if key != "review_sha256"}
        if _fingerprint(payload) != _digest(data["review_sha256"], "review_sha256"):
            raise ValidationError("Pilot review content fingerprint disagrees.")
        return cls(data)

    def to_dict(self) -> Dict[str, Any]:
        PilotReview.from_dict(self.data)
        return self.data

    def export(self, path: Path) -> None:
        _write_private(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", path)


def review_pilot(report: ReadinessReport, scope: PilotScope, roster: ApproverRoster,
                 reviewer_id: str, decision: str, timestamp: str, reason: str,
                 ledger: FeedbackLedger, policy: Policy, learner: LearnedModel) -> PilotReview:
    report.verify(ledger, policy, learner)
    scope = PilotScope.from_dict(scope.to_dict())
    roster = ApproverRoster.from_dict(roster.to_dict())
    reviewer = roster.designated(reviewer_id)
    for developer in scope.developer_ids:
        ledger.team.role(developer)
    categories = {item["task_type"]: item for item in report.data["categories"]}
    data = {
        "schema_version": 1, "record_type": "local_pilot_review", "report": report.to_dict(),
        "scope": scope.to_dict(), "approver_roster": roster.to_dict(),
        "reviewer_id": reviewer_id, "reviewer_role": reviewer[1], "decision": decision,
        "timestamp": timestamp, "reason": reason,
        "routes": [{"task_type": category, "model": categories[category]["suggested_model"]}
                   for category in scope.task_types if category in categories] if decision == "approve" else [],
        "approved_for_local_simulation": decision == "approve", "local_only": True,
        "reviewer_identity_source": "declared_local_allowlist_unverified", "limits_enforced": False,
        "routing_enabled": False, "deployment_authorized": False,
    }
    data["review_sha256"] = _fingerprint(data)
    return PilotReview.from_dict(data)


def load_readiness(path: Path) -> ReadinessReport:
    ensure_safe(str(path))
    return ReadinessReport.from_dict(parse_json(path.read_text(encoding="utf-8")))


def load_pilot_review(path: Path) -> PilotReview:
    ensure_safe(str(path))
    return PilotReview.from_dict(parse_json(path.read_text(encoding="utf-8")))
