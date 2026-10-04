"""Tarkado's local CLI: print every metric without hiding regressions."""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .audit import load_audit, replay_audit, rollout_audit
from .exporters import export_policy
from .feedback import FeedbackStore, TaskRequest, TeamConfig, feedback_summary, import_scenario
from .history import PolicyStore
from .learning import LearningPlan, fit_feedback, load_learner
from .importers import load_policy, load_traces, parse_json
from .replay import METRIC_FIELDS, ReplayReport, replay
from .rollout import EvaluationPlan, RolloutReport, evaluate
from .privacy import PrivacyError, SECRET_PATTERNS, ensure_safe, redact_text
from .opencode import AdapterError, OpenCodeReader, load_snapshot
from .readiness import ApproverRoster, PilotScope, build_readiness, load_readiness, review_pilot
from .readiness import load_pilot_review
from .pilot import PilotRequest, PilotStore
from .schemas import MODES, ValidationError


def render_text(report: ReplayReport) -> str:
    data = report.to_dict()
    ensure_safe(data)
    lines = [
        "Tarkado — offline policy comparison",
        f"Policy: {report.policy_version} | Mode: {report.mode}",
        f"Policy content fingerprint: {report.policy_sha256}",
        f"Tasks: {data['total_tasks']} | Evaluated: {data['evaluated_tasks']} | Unevaluated: {data['unevaluated_tasks']}",
        f"Rule matches: {data['rule_matches']} | Fallbacks: {data['fallbacks']} | Missing suggested outcomes: {data['missing_suggested_outcomes']}",
        "",
        "metric | recorded baseline (all tasks) | baseline (paired) | policy (paired)",
        "--- | --- | --- | ---",
    ]
    for name in METRIC_FIELDS:
        values = [str(data[group][name]) if data[group][name] is not None else "unknown"
                  for group in ("recorded_baseline", "comparison_baseline", "comparison_policy")]
        lines.append(" | ".join([name] + values))
    for name in ("cost_reduction_usd", "total_latency_change_ms", "score_pairs", "mean_score_change"):
        lines.append(f"{name}: {data[name] if data[name] is not None else 'unknown'}")
    lines.extend(["", "Decisions:"])
    for row in report.rows:
        evaluated = row.evaluated.selected_model if row.evaluated else "UNEVALUATED"
        lines.extend([
            f"- {row.task_id}: baseline={row.baseline.selected_model}, suggested={row.suggested_model}, effective={row.decision.effective_model}, evaluated={evaluated}",
            f"  confidence={row.decision.confidence}, fallback={row.decision.used_fallback}, missing_suggested_outcome={row.missing_suggested_outcome}, policy_version={row.decision.policy_version}",
            f"  fallback_model={row.decision.fallback_model}, evidence_refs={json.dumps(list(row.decision.evidence_refs))}",
            f"  reason={row.decision.reason}",
        ])
    lines.extend(["", "Notes:"] + [f"- {note}" for note in data["notes"]])
    return "\n".join(lines)


def render_rollout(report: RolloutReport) -> str:
    data = report.to_dict()
    ensure_safe(data)
    lines = [
        "Tarkado — offline new-model evaluation",
        f"Policy: {report.policy_version} | Candidate: {report.candidate_model} | State: {report.candidate_status}",
        f"Policy content fingerprint: {report.policy_sha256}",
        f"Recommendation: {report.recommendation.upper()} | Deployment authorized: NO",
        f"Source: {report.plan.source} | Kind: {report.plan.source_kind} | Split: {report.plan.dataset_split}",
        f"Task scope: {json.dumps(list(report.plan.task_types))}",
        f"Evidence gates: min_tasks={report.plan.min_tasks}, min_samples_per_task={report.plan.min_samples_per_task}",
    ]
    for name in (
        "total_tasks", "excluded_tasks", "scope_tasks", "evaluation_samples", "paired_samples",
        "unpaired_samples", "missing_candidate_outcomes", "compatibility_failures", "baseline_failures",
        "observed_candidate_test_failures",
    ):
        lines.append(f"{name}: {data[name]}")
    lines.extend(["", "metric | recorded no-change (paired) | current policy (paired) | candidate (paired)",
                  "--- | --- | --- | ---"])
    for name in METRIC_FIELDS:
        values = [str(data[group][name]) if data[group][name] is not None else "unknown"
                  for group in ("recorded_no_change", "baseline", "candidate")]
        lines.append(" | ".join([name] + values))
    lines.append(f"baseline_models: {json.dumps(data['baseline_models'])}")
    for name in ("cost_reduction_usd", "total_latency_change_ms", "known_test_pairs", "test_regressions",
                 "baseline_test_failure_rate", "candidate_test_failure_rate", "developer_override_change", "override_regressions",
                 "score_pairs", "score_regressions", "mean_score_change"):
        lines.append(f"{name}: {data[name] if data[name] is not None else 'unknown'}")
    lines.extend(["", "Task-type coverage:"])
    for coverage in data["task_type_coverage"]:
        lines.append(json.dumps(coverage, ensure_ascii=False))
    lines.extend(["", "Task variation:"])
    for stats in data["task_variation"]:
        lines.append(json.dumps(stats, ensure_ascii=False))
    uncertainty = data["uncertainty"]
    lines.extend(["", "Independent-task uncertainty:",
                  "Settings: " + json.dumps(uncertainty["settings"]),
                  "Weighting: " + uncertainty["weighting"]])
    for metric, statistics in uncertainty["metrics"].items():
        lines.append(metric + ": " + json.dumps(statistics, ensure_ascii=False))
    lines.extend(["Uncertainty notes:"] + ["- " + note for note in uncertainty["notes"]])
    lines.extend(["", "Samples:"])
    for sample in data["samples"]:
        lines.append(json.dumps(sample, ensure_ascii=False))
    lines.extend(["", "Reasons:"] + [f"- {reason}" for reason in data["reasons"]])
    lines.extend(["", "Notes:"] + [f"- {note}" for note in data["notes"]])
    return "\n".join(lines)


def run_policy_command(args: argparse.Namespace) -> int:
    store = PolicyStore(args.store)
    action = args.policy_action
    result = {"local_only": True, "deployment_authorized": False}
    if action == "save":
        snapshot = store.save(load_policy(args.source))
        result.update(action="save", policy_version=snapshot.policy.policy_version, sha256=snapshot.sha256)
    elif action == "review":
        result.update(store.review(args.policy_version, args.reviewer, args.reason).to_dict())
    elif action in ("select", "rollback"):
        event = store.select(args.policy_version, args.reviewer, args.reason,
                             expected_current=args.expected_current, rollback=action == "rollback")
        result.update(event.to_dict())
    elif action == "export":
        store.export(args.policy_version, args.output)
        result.update(action="export", policy_version=args.policy_version, output=str(args.output))
    else:
        history = store.read()
        result.update(current_policy_version=history.current_version)
        if action == "current":
            selection = next((event for event in reversed(history.events)
                              if event.action in ("select", "rollback")), None)
            result["last_selection"] = selection.to_dict() if selection else None
        else:
            result.update(snapshot_count=len(history.snapshots), event_count=len(history.events),
                          snapshots=[{"policy_version": item.policy.policy_version, "sha256": item.sha256}
                                     for item in history.snapshots],
                          events=[event.to_dict() for event in history.events])
    ensure_safe(result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Invalid arguments may contain secrets. Show supported syntax, not their values.
        super().error("Invalid command-line arguments; use --help for supported commands.")


def main(argv: Optional[List[str]] = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        ensure_safe(arguments)
    except PrivacyError as error:
        print(f"Tarkado: {error}", file=sys.stderr)
        return 2
    parser = SafeArgumentParser(prog="tarkado", description="Offline coding-model policy evaluation; no API calls.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    from .company.cli import add_commands
    add_commands(commands)
    command = commands.add_parser("replay", help="Compare a policy with recorded task/model outcomes")
    command.add_argument("traces", type=Path, help="Local metadata-only JSONL or CSV file")
    command.add_argument("--policy", type=Path, required=True, help="Versioned policy JSON file")
    command.add_argument("--mode", choices=MODES, default="replay")
    command.add_argument("--format", choices=("text", "json"), default="text")
    command.add_argument("--export-policy", type=Path,
                         help="Write the supplied policy as a versioned local proposal; never overwrite")
    command.add_argument("--audit", type=Path, help="Export a private metadata-only audit snapshot; never overwrite")
    evaluation = commands.add_parser("evaluate", help="Evaluate a registered candidate using local recorded samples")
    evaluation.add_argument("traces", type=Path, help="Metadata-only JSONL/CSV with paired task/model outcomes")
    evaluation.add_argument("--policy", type=Path, required=True)
    evaluation.add_argument("--candidate", required=True, help="Registered model ID; approval state is never changed")
    evaluation.add_argument("--plan", type=Path, required=True, help="Source, scope, split, and predeclared evidence gates")
    evaluation.add_argument("--format", choices=("text", "json"), default="text")
    evaluation.add_argument("--audit", type=Path, help="Export candidate/override audit records even for rejected evaluations")
    policies = commands.add_parser("policy", help="Local policy snapshots, review records, and rollback; no live routing")
    policy_commands = policies.add_subparsers(dest="policy_action", required=True)
    storage = argparse.ArgumentParser(add_help=False)
    storage.add_argument("--store", type=Path, default=Path("local/policies"), help="Local JSON history directory")
    save = policy_commands.add_parser("save", parents=[storage], help="Save an immutable versioned snapshot")
    save.add_argument("source", type=Path)
    for action in ("review", "select", "rollback"):
        operation = policy_commands.add_parser(action, parents=[storage])
        operation.add_argument("policy_version")
        operation.add_argument("--reviewer", required=True, help="User-supplied local review label, not authenticated identity")
        operation.add_argument("--reason", required=True)
        if action == "select":
            expected = operation.add_mutually_exclusive_group(required=True)
            expected.add_argument("--initial", action="store_true", help="Require that no local policy is selected yet")
            expected.add_argument("--expected-current", help="Refuse the change if current selection differs")
        elif action == "rollback":
            operation.add_argument("--expected-current", required=True)
    for action in ("current", "history"):
        policy_commands.add_parser(action, parents=[storage])
    export = policy_commands.add_parser("export", parents=[storage], help="Export a saved snapshot without overwriting")
    export.add_argument("policy_version")
    export.add_argument("--output", required=True, type=Path)
    privacy = commands.add_parser("privacy", help="Check supported input contracts without printing metadata values")
    privacy_commands = privacy.add_subparsers(dest="privacy_action", required=True)
    check = privacy_commands.add_parser("check")
    check.add_argument("source", type=Path)
    check.add_argument("--kind", required=True, choices=("traces", "policy", "plan", "audit", "snapshot"))
    check.add_argument("--repeated", action="store_true", help="Allow repeated trace samples with explicit sample IDs")
    integration = commands.add_parser("opencode", help="Explicit read-only OpenCode V2 session snapshots")
    integrations = integration.add_subparsers(dest="opencode_action", required=True)
    observe = integrations.add_parser("observe")
    observe.add_argument("--session", required=True, help="Explicit session ID; no session-list or message reads")
    observe.add_argument("--directory", type=Path, required=True, help="Require the session to belong to this location")
    observe.add_argument("--policy", type=Path, required=True, help="Team registry allowlist; no automatic approval")
    observe.add_argument("--company-api", action="store_true", required=True,
                         help="Attest company-managed API/gateway use, not consumer subscriptions")
    observe.add_argument("--output", type=Path, help="Optional private JSONL snapshot; never overwrite")
    observe.add_argument("--executable", default="opencode", help="Explicit installed OpenCode executable")
    observe.add_argument("--timeout", type=int, default=30, help="Per-read timeout, 1-120 seconds")
    feedback = commands.add_parser("feedback", help="Local per-task recommendations, responses, actual results, and evidence ranking")
    feedback_commands = feedback.add_subparsers(dest="feedback_action", required=True)
    feedback_storage = argparse.ArgumentParser(add_help=False)
    feedback_storage.add_argument("--store", type=Path, default=Path("local/feedback"))
    initialize = feedback_commands.add_parser("init", parents=[feedback_storage], help="Declare participating developers; roles are local labels")
    initialize.add_argument("--team", type=Path, required=True)
    recommend = feedback_commands.add_parser("recommend", parents=[feedback_storage], help="Save a recommendation without executing a model")
    recommend.add_argument("task", type=Path)
    recommend.add_argument("--policy", type=Path, required=True)
    recommend.add_argument("--learner", type=Path, help="Explicit experimental learner; manual choice only, never activation")
    record = feedback_commands.add_parser("record", parents=[feedback_storage], help="Append response/execution/result metadata")
    record.add_argument("source", type=Path)
    record.add_argument("--kind", choices=("response", "execution", "result"), required=True)
    summary = feedback_commands.add_parser("summary", parents=[feedback_storage], help="Rank linked evidence for manual review; no routing changes")
    summary.add_argument("--policy", type=Path, required=True)
    ingest = feedback_commands.add_parser("import", parents=[feedback_storage], help="Import explicit local task observations into an empty store")
    ingest.add_argument("scenario", type=Path)
    ingest.add_argument("--policy", type=Path, required=True)
    learn = feedback_commands.add_parser("learn", parents=[feedback_storage], help="Fit an experimental count-based suggestion model from explicit validation evidence")
    learn.add_argument("--policy", type=Path, required=True)
    learn.add_argument("--plan", type=Path, required=True)
    learn.add_argument("--output", type=Path, required=True, help="Private immutable learner file; never overwrite")
    readiness = feedback_commands.add_parser("readiness", parents=[feedback_storage], help="Build category review report; never declare production readiness")
    readiness.add_argument("--policy", type=Path, required=True)
    readiness.add_argument("--learner", type=Path, required=True)
    readiness.add_argument("--output", type=Path, required=True)
    pilots = commands.add_parser("pilot", help="Separate designated-reviewer receipts for local pilot simulation; no live activation")
    pilot_commands = pilots.add_subparsers(dest="pilot_action", required=True)
    review = pilot_commands.add_parser("review", parents=[feedback_storage])
    review.add_argument("--report", type=Path, required=True)
    review.add_argument("--policy", type=Path, required=True)
    review.add_argument("--learner", type=Path, required=True)
    review.add_argument("--scope", type=Path, required=True)
    review.add_argument("--approvers", type=Path, required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--decision", choices=("approve", "reject"), required=True)
    review.add_argument("--timestamp", required=True, help="Explicit review timestamp; identity/time remain caller-declared")
    review.add_argument("--reason", required=True)
    review.add_argument("--local-simulation", action="store_true", required=True, help="Acknowledge that this cannot authorize live routing")
    review.add_argument("--output", type=Path, required=True)
    runtime_storage = argparse.ArgumentParser(add_help=False)
    runtime_storage.add_argument("--pilot-store", type=Path, default=Path("local/pilot-runtime"))
    activate = pilot_commands.add_parser("activate", parents=[runtime_storage, feedback_storage], help="Activate one reviewed local simulation; never start live routing")
    activate.add_argument("--receipt", type=Path, required=True)
    activate.add_argument("--learner", type=Path, required=True)
    activate.add_argument("--policy", type=Path, required=True)
    activate.add_argument("--approvers", type=Path, required=True)
    activate.add_argument("--reviewer", required=True)
    activate.add_argument("--timestamp", required=True)
    activate.add_argument("--reason", required=True)
    activate.add_argument("--local-simulation", action="store_true", required=True)
    pilot_commands.add_parser("status", parents=[runtime_storage], help="Print complete local state and accounting")
    decision = pilot_commands.add_parser("decide", parents=[runtime_storage, feedback_storage], help="Reserve a scoped simulated task; no model request")
    decision.add_argument("request", type=Path)
    decision.add_argument("--policy", type=Path, required=True)
    decision.add_argument("--approvers", type=Path, required=True)
    decision.add_argument("--local-simulation", action="store_true", required=True)
    settle = pilot_commands.add_parser("settle", parents=[runtime_storage], help="Record simulated cost/failure and release the reservation")
    settle.add_argument("source", type=Path)
    settle.add_argument("--local-simulation", action="store_true", required=True)
    for action in ("pause", "resume", "revoke", "rollback"):
        control = pilot_commands.add_parser(action, parents=[runtime_storage, feedback_storage])
        control.add_argument("--expected-revision", type=int, required=True)
        control.add_argument("--approvers", type=Path, required=True)
        control.add_argument("--reviewer", required=True)
        control.add_argument("--timestamp", required=True)
        control.add_argument("--reason", required=True)
        control.add_argument("--local-simulation", action="store_true", required=True)
        if action == "resume":
            control.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        if args.command == "company":
            from .company.cli import run_command
            return run_command(args)
        if args.command == "pilot":
            if args.pilot_action != "review":
                runtime = PilotStore(args.pilot_store)
                if args.pilot_action == "status":
                    result = runtime.status()
                elif args.pilot_action == "settle":
                    result = runtime.settle(parse_json(args.source.read_text(encoding="utf-8")))
                else:
                    roster = ApproverRoster.from_dict(parse_json(args.approvers.read_text(encoding="utf-8")))
                    if args.pilot_action in ("activate", "decide", "resume"):
                        policy = load_policy(args.policy)
                        with FeedbackStore(args.store)._locked() as ledger:
                            if ledger is None:
                                raise ValidationError("Initialize feedback before activating or admitting pilot tasks.")
                            if args.pilot_action == "activate":
                                runtime.activate(load_pilot_review(args.receipt), load_learner(args.learner), ledger,
                                                 policy, roster, args.reviewer, args.timestamp, args.reason)
                                result = runtime.status()
                            elif args.pilot_action == "decide":
                                request = PilotRequest.from_dict(parse_json(args.request.read_text(encoding="utf-8")))
                                result = runtime.decide(request, policy, ledger, roster)
                            else:
                                runtime.control("resume", args.expected_revision, roster, args.reviewer, args.timestamp,
                                                args.reason, ledger, policy)
                                result = runtime.status()
                    else:
                        runtime.control(args.pilot_action, args.expected_revision, roster, args.reviewer, args.timestamp, args.reason)
                        result = runtime.status()
                ensure_safe(result)
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0
            store = FeedbackStore(args.store)
            report = load_readiness(args.report)
            policy = load_policy(args.policy)
            learner = load_learner(args.learner)
            scope = PilotScope.from_dict(parse_json(args.scope.read_text(encoding="utf-8")))
            roster = ApproverRoster.from_dict(parse_json(args.approvers.read_text(encoding="utf-8")))
            with store._locked() as ledger:
                if ledger is None:
                    raise ValidationError("Initialize the feedback store before pilot review.")
                receipt = review_pilot(report, scope, roster, args.reviewer, args.decision, args.timestamp,
                                       args.reason, ledger, policy, learner)
                receipt.export(args.output)
            print(json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False))
            return 0
        if args.command == "feedback":
            store = FeedbackStore(args.store)
            if args.feedback_action == "init":
                team = TeamConfig.from_dict(parse_json(args.team.read_text(encoding="utf-8")))
                ledger = store.initialize(team)
                result = {"members": len(ledger.team.members), "roles_source": "declared_local_roster_unverified"}
            elif args.feedback_action == "recommend":
                task = TaskRequest.from_dict(parse_json(args.task.read_text(encoding="utf-8")))
                learned = load_learner(args.learner).to_dict() if args.learner is not None else None
                rec = store.recommend(task, load_policy(args.policy), learned)
                result = rec.to_dict()
                if rec.learning is not None:
                    artifact = rec.learning
                    result["learning"] = {"learner_version": artifact["plan"]["learner_version"],
                                          "learner_sha256": artifact["learner_sha256"],
                                          "source_sha256": artifact["source_sha256"],
                                          "evidence": [item for item in artifact["evidence"] if item["task_type"] == task.task_type]}
            elif args.feedback_action == "record":
                store.record(args.kind, parse_json(args.source.read_text(encoding="utf-8")))
                result = {"recorded": args.kind}
            elif args.feedback_action == "import":
                policy = load_policy(args.policy)
                ledger = import_scenario(parse_json(args.scenario.read_text(encoding="utf-8")), policy)
                store.import_ledger(ledger)
                result = feedback_summary(ledger, policy)
            elif args.feedback_action == "learn":
                plan = LearningPlan.from_dict(parse_json(args.plan.read_text(encoding="utf-8")))
                model = fit_feedback(store.read(), load_policy(args.policy), plan)
                model.export(args.output)
                result = model.to_dict()
            elif args.feedback_action == "readiness":
                report = build_readiness(store.read(), load_policy(args.policy), load_learner(args.learner))
                report.export(args.output)
                result = report.to_dict()
            else:
                result = feedback_summary(store.read(), load_policy(args.policy))
            result.update(local_only=True, deployment_authorized=False)
            ensure_safe(result)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if args.command == "opencode":
            policy = load_policy(args.policy)
            snapshot = OpenCodeReader(args.executable, args.timeout).observe(
                args.session, args.directory, policy, args.company_api)
            print(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False))
            if args.output is not None:
                snapshot.export(args.output)
            return 0
        if args.command == "privacy":
            if args.kind == "traces":
                records = len(load_traces(args.source, repeated=args.repeated))
            elif args.kind == "policy":
                load_policy(args.source)
                records = 1
            elif args.kind == "audit":
                records = len(load_audit(args.source).events)
            elif args.kind == "snapshot":
                load_snapshot(args.source)
                records = 1
            else:
                ensure_safe(str(args.source))
                EvaluationPlan.from_dict(parse_json(args.source.read_text(encoding="utf-8")))
                records = 1
            print(json.dumps({"metadata_only": True, "records_checked": records,
                              "supported_secret_patterns_detected": False,
                              "patterns_checked": [name for name, _ in SECRET_PATTERNS],
                              "note": "Pattern checks are conservative and cannot prove data is secret-free."}, indent=2))
            return 0
        if args.command == "policy":
            return run_policy_command(args)
        policy = load_policy(args.policy)
        if args.command == "evaluate":
            plan = EvaluationPlan.from_dict(parse_json(args.plan.read_text(encoding="utf-8")))
            report = evaluate(load_traces(args.traces, repeated=True), policy, args.candidate, plan)
            ensure_safe(report.to_dict())
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
                  if args.format == "json" else render_rollout(report))
            if args.audit is not None:
                rollout_audit(report, policy).export(args.audit)
            return 0 if report.recommendation == "shadow" else 1
        report = replay(load_traces(args.traces), policy, args.mode)
        ensure_safe(report.to_dict())
    except (OSError, UnicodeError, ValueError, ValidationError, PrivacyError, AdapterError) as error:
        print(f"Tarkado: {redact_text(str(error))}", file=sys.stderr)
        return 2
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
          if args.format == "json" else render_text(report))
    if args.audit is not None:
        try:
            replay_audit(report, policy).export(args.audit)
        except (OSError, UnicodeError, ValidationError, PrivacyError) as error:
            print(f"Tarkado: audit export failed: {redact_text(str(error))}", file=sys.stderr)
            return 2
    if args.export_policy is not None:
        if report.unevaluated_tasks:
            print("Tarkado: policy export refused because the comparison is incomplete.", file=sys.stderr)
            return 1
        try:
            export_policy(policy, args.export_policy)
        except (OSError, UnicodeError, ValidationError, PrivacyError) as error:
            print(f"Tarkado: policy export failed: {redact_text(str(error))}", file=sys.stderr)
            return 2
    return 1 if report.unevaluated_tasks else 0
