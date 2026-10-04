# Technical Requirements Document — Tarkado

**Status:** Draft 0.2; aligned with the accepted company workflow
**Scope:** Architecture and requirements, not implementation commitments

**Last updated:** 2026-10-03
**Product reference:** [WORKFLOW.md](WORKFLOW.md). Technical details below must
not bypass its recommendation-first, senior-feedback, and pilot-approval rules.

## 1. Design principle

Tarkado is a **control plane** [the part that decides rules], not a new
gateway. A gateway or coding client remains the **data plane** [the part that
actually sends each request to a model].

```text
New task / run / subagent + approved metadata
                    ↓
Tarkado: recommendation + policy + evidence
                    ↓
Manual developer choice before pilot approval
Scoped automatic choice only after pilot approval
                    ↓
Existing coding tool / gateway / provider API
                    ↓
Approved model → actual task result + per-task feedback
                    ↓
Local feedback store → learner → readiness report
                                      ↓
                         Senior/admin pilot authorization
```

## 2. Operating modes

| Mode | Behaviour | Safety rule |
| --- | --- | --- |
| Observe | Record approved metadata only. | Never change the selected model. |
| Replay | Evaluate proposed policy on historical tasks. | Offline only. |
| Shadow | Recommend a model; record per-task response and actual result. | Manual developer choice; no extra alternative-model execution. |
| Pilot | Apply a versioned policy within its limited approved scope. | Separate designated senior/admin approval required for the first automatic-routing pilot; overrides/fallback mandatory. |
| Enforce | Apply an approved versioned policy to its approved scope. | Do not expand scope based on confidence alone; monitoring/rollback/audit required. |

Learning runs over collected evidence; it does not implicitly change an
operating mode. Monitor all participating developers within approved collection
scope, with senior feedback given greater influence rather than exclusive data
collection.

## 3. Core components

### 3.1 Trace importer

Reads local JSONL/CSV records initially. Future adapters may import from
OpenCode, LiteLLM, OpenRouter, OpenTelemetry, LangSmith, or Braintrust.

### 3.2 Evaluation store

Stores evaluation cases, candidate outputs, scorers, and outcomes. It must
separate raw content from metadata so a privacy-preserving mode is possible.

### 3.3 Model registry

Stores team-declared model entries with explicit approval state, including:

- provider/model ID;
- compatible client/protocol;
- context/tool capabilities;
- price and latency metadata;
- tier: cheap, standard, premium;
- status: candidate, shadow, approved, disabled.

Registration, a senior's per-task acceptance, and catalog availability are not
model authorization. Only approved/compatible models may be recommended for
ordinary tasks or selected automatically in an approved pilot.

### 3.4 Policy engine

Receives task metadata and returns one of:

```text
recommend approved model X
recommend the approved safe default
ask for user choice
reject because no compatible approved model exists
```

Every decision must include a reason, confidence, policy version, and
fallback.

In early shadow mode, the developer still selects the actual model. An
automatic route is permitted only at a supported new-task boundary inside the
separately approved pilot. Learning must not call `switchModel` on an active
session or turn one accepted recommendation into a routing-policy activation.

### 3.5 Rollout evaluator

Compares a new candidate model with the current policy. It reports quality,
cost, latency, failure rate, and uncertainty across repeated samples.

This is a separate offline evidence tool. It does not execute missing model
outputs, interpret shadow mode as duplicate requests, or authorize deployment.

### 3.6 Export adapters

Start with a human-readable YAML/JSON policy. Later adapters can translate it
to OpenCode configuration/plugins or existing gateway configuration.

### 3.7 Recommendation and feedback store — local baseline available

Link recommendation, response, actual execution/model choice, and eventual
task result using stable IDs. Record permitted actor/role metadata, policy
version, task category/risk, reason/confidence, evidence references, and
known/unknown outcome signals. Keep late outcomes and duplicate feedback
explicit; never attach another model's result to the recommended model.

A senior's accept/reject feedback concerns one task. Keep it separate from the
company's authorized model set and pilot approval. Preserve junior/senior
usage, failures, rejects, and overrides within approved collection scope.

The implemented local baseline is documented in [FEEDBACK.md](FEEDBACK.md).
It uses declared, unverified roles, immutable task responses/executions, and
append-only corrected result history. It does not authenticate outcomes or
activate learned policies. Explicit experimental fitting/application is
documented in [LEARNING.md](LEARNING.md); production validation remains pending.

### 3.8 Feedback learning — experimental baseline available; readiness planned

Use the linked evidence across tasks/sessions to improve task-category
recommendations, prioritizing senior feedback. Start with a simple explainable
baseline; exact weights and training/evidence thresholds remain undecided.

An explicit count-based learning plan fits future manual suggestions from
validation records, with cutoffs and source checks. Experimental settings are
not final production thresholds. Learned suggestions retain low confidence and
manual choice, and can be saved back into the linked feedback store.

Learning produces a versioned recommendation proposal and readiness report,
not a live activation. Evidence must distinguish preference from confirmed
quality, disclose missing/counterfactual outcomes, and report negative results.
Validate parameters on validation data, not held-out tests.

### 3.9 Pilot review — local receipts and conditional company authorization available

A designated senior/admin authorizes the first limited automatic-routing
pilot after reviewing readiness. Bind authorization to the policy version and
scope. The runtime must refuse unapproved activation/scope changes and retain
safe fallback, override, and rollback paths. Approver authentication and
scope-bound approval/revocation mechanics are implemented; real readiness
criteria/evidence integration and retention controls remain unresolved. Local
`policy review` labels are not authenticated authority.

Local category-review reports and designated senior/admin simulation receipts
are in [READINESS_PILOT.md](READINESS_PILOT.md). They bind the current report and
scope, retain blocked categories, and never enable routing. Identities are
declared. The separate simulation runtime now checks task/budget reservations
and supports state controls; live provider caps remain unimplemented. The company
application has separate authenticated simulation approvals and positive conditional
live scope approval against a default-denying server-owned readiness interface.

### Company identity/setup implementation boundary

Accepted onboarding C-01–C-05 uses invitation-only individual accounts and optional
later SSO. `engine/company/` now provides an approved Django 5.2 LTS account/setup
application on supported Python, with a separate private SQLite store, current
permission checks, explicit policy/collection configuration, and actor/time/reason
history. It reuses existing policy validation and leaves legacy ledgers untouched.
The development launcher stays loopback-only. A separate approved Waitress
private-socket single-host server requires exact HTTPS origin/proxy configuration
and secure cookies; actual TLS/proxy operation is not independently verified.
Manual task feedback uses
authenticated events and per-record role snapshots, projected into the existing
contracts without changing schema-1 data. Category learner/review preparation,
exact-scope authenticated simulation authorization/revocation, B-01-backed
company runtime/accounting, and private offline/admin-assisted password recovery
are implemented. B-02's positive conditional live-authorization boundary and
ordered withdrawal are implemented/tested; a trusted real readiness verifier,
automatic task capture/execution, and actual deployment/readiness validation
remain pending. Scope checks explicitly create no execution/budget ticket.
Authenticator MFA and lost-factor
backup recovery are implemented using approved django-otp; backup tickets cannot
directly grant privileged company access or pilot authorization. Factor keys and
backup codes remain in the private local store without encryption at rest.
See [COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md). Authentication of an
account cannot independently verify engineering outcomes or production readiness.

## 4. Task-boundary routing rule

Tarkado routes at a **new task**, **new run**, or **subagent** boundary.
It must not silently change a model mid-session in v1.

Reasons:

- an active session may contain provider-specific tool calls or context;
- different models may have different tool, reasoning, and context support;
- an unexpected switch is difficult to debug and reduces user trust.

## 5. Minimum data contracts

These are proposed product contracts. The stricter implemented Phase 1
metadata-only format is documented in [DEVELOPMENT.md](DEVELOPMENT.md). It adds
task IDs, explicit baseline rows, and compatibility requirements for paired
replay. Candidate reports and repeated sample pairing are documented in
[ROLLOUT.md](ROLLOUT.md). Raw-content references, statistical enablement, and
live deployment remain unimplemented.

Feedback has a separate local record contract in [FEEDBACK.md](FEEDBACK.md),
not extra fields accepted by the historical trace importer. Authenticated pilot
authorization and verified production readiness below remain requirements.
Local review/receipt contracts are documented in `READINESS_PILOT.md`.

### 5.1 TaskTrace

```json
{
  "trace_id": "string",
  "timestamp": "ISO-8601 timestamp",
  "task_type": "optional string",
  "risk_tags": ["optional strings"],
  "selected_model": "provider/model",
  "model_tier": "cheap|standard|premium",
  "input_tokens": 0,
  "output_tokens": 0,
  "cost_usd": 0.0,
  "latency_ms": 0,
  "outcome": {
    "tests_passed": true,
    "developer_override": false,
    "score": 0.0
  },
  "raw_content_ref": "optional local-only reference"
}
```

`raw_content_ref` must be optional. The core system must work with metadata
plus evaluable cases, although richer content can improve policy quality.

### 5.2 PolicyDecision

```json
{
  "policy_version": "string",
  "recommended_model": "provider/model",
  "recommended_tier": "cheap|standard|premium",
  "confidence": "low|medium|high",
  "reason": "human-readable explanation",
  "fallback_model": "provider/model",
  "enforcement": "observe|shadow|pilot|enforce"
}
```

### 5.3 RolloutReport

Must include:

- candidate and baseline models;
- evaluation-case count and source;
- quality/outcome comparison;
- cost and latency comparison;
- uncertainty / variation across runs;
- compatibility failures;
- recommendation: ready for authorized review, shadow, collect more evidence,
  or reject. Existing CLI states and limitations are documented in `ROLLOUT.md`.

An eventual ready/enable recommendation means **ready for authorized review**,
not permission to execute. Today's evaluator cannot enable models or pilots.

### 5.4 Recommendation-response-outcome linkage — local baseline implemented

- A recommendation ID references the task, approved candidate model, policy
  version, metadata scope, reason, and evidence/confidence.
- Per-task feedback references that exact recommendation and a permitted actor
  with a role; record accept/reject separately from the actual model choice.
- Execution/outcome records identify the model actually used and the known or
  unknown desired-result evidence, cost, latency, failure, and override signals.
- Preliminary review ranking prioritizes senior feedback without dropping other
  actors or turning acceptance into a quality label; a validated learner remains pending.
- Corrections, delayed results, and duplicates cannot silently double-count
  evidence. Initial field names/limits are documented in `FEEDBACK.md`;
  authenticated roles and richer multi-attempt/conflict handling remain design work.

### 5.5 Separate pilot authorization — local simulation contract only

Keep approver identity/authority, exact policy version/content, approved task
categories/scope, and authorization/reversal history separate from per-task
feedback. Training/readiness alone cannot produce this approval. The first
pilot requires a designated senior/admin decision; later self-activating pilot
rules have not been approved.

Local receipts do not activate live routing or prove approver identity. Local
simulation state/revocation/task-budget accounting is implemented. Trusted live
scope, provider cost enforcement, and company authorization remain pending.

## 6. Routing signals

Initial signals should be simple and explainable:

- explicit task type supplied by the user/tool;
- repository or command scope;
- risk tags;
- expected tool use;
- prior outcome/cost statistics for similar tasks;
- linked per-task senior feedback plus actual desired-result evidence;
- company-wide failures, rejects, and overrides, including junior outcomes;
- user-selected policy constraints.

Later signals may include embeddings [numeric task representations] or a fast
decision model such as Laya. Laya is optional and must improve a measured
metric before it is retained.

## 7. Compatibility requirements

- A model may be selected only when it supports the needed input/output and
  tool capabilities.
- Models with unknown capability metadata are treated as incompatible in
  enforcement mode unless explicitly approved.
- Provider-specific request settings must remain with their compatible runtime.
- The system must preserve a default model for all failure paths.
- The first OpenCode adapter must use documented OpenCode V2 APIs/configuration
  only.

## 8. Security and privacy requirements

- Do not commit API keys, task traces, source code, outputs, or customer data.
- Support local-only data storage in the MVP.
- Make raw-content collection opt-in.
- Record data retention settings in every deployment configuration.
- Redact secrets before a trace is exported.
- Do not route through consumer subscriptions or browser automation.
- Never silently send a task to an unapproved provider.

## 9. Reliability requirements

- Policy evaluation error → use configured default model.
- Unknown task/model capability → default/prompt user; do not guess.
- Exported policy must be versioned and reversible.
- Every enforced decision must be auditable.
- Recommendation-only shadow mode must make no extra alternative-model calls.
- Per-task feedback must never authorize pilot activation or scope expansion.
- Observe/recommend mode retains developer selection even when learning changes
  the proposed recommendation.
- Offline replay must be deterministic for a fixed input dataset and policy.

## 10. Testing requirements

- Unit tests for policy matching, fallback selection, model compatibility, and
  policy versioning.
- Fixtures with cheap/standard/premium models and expected decisions.
- Tests proving observe/shadow modes never change model selection.
- Tests proving no raw task content is emitted when metadata-only mode is on.
- Integration test against a documented local OpenCode-compatible setup only
  after the offline engine is complete.
- Tests for recommendation/response/actual-model/result linkage, including
  acceptance without execution, wrong-model attribution, unknown results,
  duplicates, late outcomes, and senior/junior feedback separation.
- Tests that readiness/training and per-task senior acceptance cannot activate
  routing; only separate authorized pilot scope may affect future tasks.

## 11. Implementation order

1. Keep the existing offline schema, rules, replay, evaluation, history, and
   privacy/audit foundation.
2. Validate the experimental learner/settings against approved real-task
   evidence; the local fitting/application mechanics are implemented.
3. Local review/receipts and scoped simulation runtime/state/accounting are
   implemented; build company setup/trusted authority and the usable interface next.
4. Connect approved task observation and manual shadow recommendations to the
   coding tool; real-session validation remains deferred until approved.
5. Implement separate authenticated senior/admin pilot authorization, then
   scoped new-task routing with override/monitoring/rollback.
6. Add gateway exports only after the reviewed local workflow works.
