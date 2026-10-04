"""Readable projections of existing records; these never grant authority or invent evidence."""

from decimal import Decimal

from django.core.exceptions import PermissionDenied
from engine.history import PolicySnapshot
from engine.readiness import ReadinessReport
from engine.schemas import Policy, ValidationError

from . import authorization
from .models import AuthorizedPilot
from .tasks import get_task, task_ledger


def task_card(task, row):
    ledger = task_ledger(task)
    rec = ledger.recommendations[0]
    if row["pending_execution"]:
        state = "Awaiting actual-model report" if row["response"] else "Awaiting per-task response or actual-model report"
    elif row["pending_result"]:
        state = "Awaiting eventual result"
    else:
        state = {"success": "Reported desired result", "failure": "Reported failure", "unknown": "Result unknown"}[row["result_status"]]
    current = Policy.from_dict(task.company.policy)
    model = current.model(row["suggested_model"])
    return {"task": task, "row": row, "recommendation": rec, "state": state,
            "policy_changed": current.fingerprint() != rec.policy_sha256,
            "suggestion_currently_approved": bool(model and model.approved)}


def task_page(request, detail):
    task = detail["task"]
    row = detail["summary"]["tasks"][0]
    result = detail["current_result"]
    try:
        get_task(request.user, task.reference, write=True)
        writable = True
    except PermissionDenied:
        writable = False
    own = task.owner_id == request.user.pk
    events = []
    for event in detail["events"]:
        payload = event.payload
        if event.kind == "recommendation":
            values = [("Selected model", payload["task"]["selected_model"]),
                      ("Suggested model", payload["decision"]["recommended_model"]),
                      ("Reason", payload["decision"]["reason"])]
        elif event.kind == "response":
            values = [("One-task response", payload["response"])]
        elif event.kind == "execution":
            values = [("Reported actual model", payload["actual_model"])]
        else:
            values = [("Desired result", payload["desired_result"]), ("Tests passed", payload["tests_passed"]),
                      ("Score", payload["score"]), ("Cost USD", payload["cost_usd"]),
                      ("Latency ms", payload["latency_ms"]), ("Evidence reference", payload["evidence_ref"]),
                      ("Correction of prior result", bool(payload["supersedes"]))]
        events.append({"event": event, "values": values})
    return {**detail, **task_card(task, row), "history": events,
            "can_respond": writable and own and not detail["ledger"].responses and not detail["ledger"].executions,
            "can_execute": writable and own and not detail["ledger"].executions,
            "can_result": writable and bool(detail["ledger"].executions) and (not result or result.reviewer_id == request.company_member.developer_id)}


def review_page(review, company):
    report = ReadinessReport.from_dict(review.data["report"]).to_dict()
    try:
        authorization.verify_review(review, company)
        guard = {"status": "current", "reason": "Stored evidence and policy still match. Manual outcome truth remains unverified."}
    except ValidationError as error:
        guard = {"status": "blocked", "reason": str(error)}
    from .models import CompanyTask
    refs, sessions = {}, {}
    for task in CompanyTask.objects.filter(company=company, source_kind=report["source_kind"]).select_related("company", "owner"):
        rec = task_ledger(task).recommendations[0]
        refs[rec.recommendation_id] = task
        sessions[rec.task.session_id] = f"{task.owner.username} / {task.session_id}"
    observations = [{"task": refs.get(row["recommendation_id"]), "row": row} for row in report["observations"]]
    result_records = {}
    for task in refs.values():
        for event in task.events.filter(kind="result"):
            result_records[event.payload["result_id"]] = {"task_label": task.task_id, "reviewer": event.actor_snapshot["developer_id"],
                                                         **event.payload}
    history = []
    for row in report["result_history"]:
        record = result_records.get(row["result_id"], {})
        history.append({"task": record.get("task_label", "Retained record unavailable"), "reviewer": record.get("reviewer"),
                        "historical_reviewer_role": row["reviewer_role"], "timestamp": row["timestamp"],
                        **{key: record.get(key, row.get(key)) for key in ("desired_result", "tests_passed", "score", "cost_usd", "latency_ms", "evidence_ref")},
                        "correction_of_prior_result": bool(row["supersedes"]), "is_current": row["is_current"]})
    plan = review.data["learner"]["plan"]
    display_plan = {**plan, "session_ids": [sessions.get(item, "Retained session unavailable") for item in plan["session_ids"]]}
    return {"review": review, "report": report, "plan": review.data["learner"]["plan"], "review_guard": guard,
            "review_policy": PolicySnapshot.from_dict(review.data["learner"]["policy"]).policy,
            "observations": observations, "review_history": history, "display_plan": display_plan,
            "review_connector_observations": review.data.get("connector_observations", [])}


def pilot_details(state):
    approval = state["authorization"]
    data = approval.data
    live = data["target"] == "live"
    receipt = data if live else data["receipt"]
    result = {**state, "scope": receipt["scope"], "routes": receipt["routes"],
              "approved_policy": PolicySnapshot.from_dict(data["policy"] if live else approval.review.data["learner"]["policy"]).policy,
              "is_live": live, "history": [], "decisions": [], "control_choices": []}
    if not live and not state.get("pilot") and approval.revoked_at is not None:
        result["status"] = "revoked"
    if live:
        result["history"] = [{"sequence": event.sequence, "timestamp": event.timestamp,
                              "action": event.action, "actor": event.payload["actor"]["developer_id"],
                              "reason": event.payload["reason"]} for event in approval.authority_events.all()]
        if approval.revoked_at is None:
            result["control_choices"] = [("revoke", "Revoke live scope"), ("rollback", "Withdraw to default-only scope")]
    elif state.get("pilot") is not None:
        journal = authorization._journal(state["pilot"])
        runtime = journal.state()
        for item in runtime.decisions.values():
            request, decision = item["request"], item["result"]
            settlement = runtime.settlements.get(request["decision_id"])
            result["decisions"].append({"id": request["decision_id"], "task": request["task"], "request": request,
                                         "result": decision, "settlement": settlement,
                                         "overrun": bool(settlement and Decimal(settlement["actual_cost_usd"]) > Decimal(request["reserve_usd"]))})
        for event in journal.events:
            payload = event["payload"]
            result["history"].append({"sequence": event["sequence"], "timestamp": event["timestamp"], "action": event["action"],
                                      "actor": payload.get("reviewer_id", payload.get("request", {}).get("task", {}).get("developer_id", "Original task developer")),
                                      "reason": payload.get("reason", payload.get("result", {}).get("reason", payload.get("outcome", "")))})
        if state["status"] in ("active", "paused"):
            result["control_choices"] = [("revoke", "Revoke simulation"), ("rollback", "Roll back to default-only")]
            if state["status"] == "active":
                result["control_choices"].insert(0, ("pause", "Pause new simulated admissions"))
            elif state["guard"]["status"] == "current" and not any(row["overrun"] or row["settlement"] and row["settlement"]["outcome"] == "failed" for row in result["decisions"]):
                result["control_choices"].insert(0, ("resume", "Resume reviewed simulation"))
    elif approval.revoked_at is None:
        result["control_choices"] = [("revoke", "Revoke unactivated simulation")]
        if state["guard"]["status"] == "current":
            result["control_choices"].insert(0, ("activate", "Activate reviewed simulation only"))
    accounting = state.get("accounting")
    result["can_admit"] = (not live and state.get("pilot") is not None and state["status"] == "active"
                           and state["guard"]["status"] == "current" and accounting["remaining_task_slots"] > 0
                           and Decimal(accounting["remaining_usd"]) > 0)
    return result


def developer_pilot(request, reference):
    member = request.company_member
    approval = authorization._pilot(member, reference)
    authorization._validate_authorization(approval)
    if approval.data["target"] != "simulation":
        raise PermissionDenied("Live scope records have no simulation execution or settlement controls.")
    if member.developer_id not in approval.data["receipt"]["scope"]["developer_ids"]:
        raise PermissionDenied("This simulation scope does not include your developer account.")
    pilot = AuthorizedPilot.objects.filter(authorization=approval).first()
    runtime = authorization._journal(pilot).state() if pilot else None
    guard = authorization.authorization_guard(approval, member.company)
    details = pilot_details({"authorization": approval, "pilot": pilot, "status": runtime.status if runtime else "unactivated",
                          "revision": runtime.revision if runtime else 0, "guard": guard,
                          "accounting": runtime.accounting() if runtime else None})
    details["decisions"] = [row for row in details["decisions"] if row["task"]["developer_id"] == member.developer_id]
    details["history"] = []
    details["control_choices"] = []
    return details
