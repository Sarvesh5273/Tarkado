# Tarkado

> **The path of reasoned model choice for engineering teams.**

Tarkado helps engineering teams decide which AI coding model should handle a
task, safely test newly released models, and reduce unnecessary API spend
without silently lowering code quality.

It starts by observing all developers and recommending models without changing
their choices. It learns from actual task results, prioritizing senior feedback.
Automatic routing comes later, only after a designated senior/admin approves a
limited pilot supported by evidence.

The accepted company workflow is recorded in [docs/WORKFLOW.md](docs/WORKFLOW.md).

## Name

**Tarkado** is a coined product name:

- **Tarka** (Sanskrit) — reasoning, inquiry, logical examination.
- **Dō / Dao** (Japanese / Chinese) — way, path, or method.

It is not a formal historical word. It represents:

> **A reasoned path for choosing AI models.**

Pronunciation: **tar-ka-doe**

## The problem

Engineering teams now use several AI coding models through company API
accounts. A team may have a cheap and fast model, a standard coding model, a
premium reasoning model, and a newly released candidate model.

Today, developers often choose manually or always select the strongest model
because it feels safer. That creates a costly and risky cycle:

```text
Simple work goes to expensive models
                ↓
API bills rise
                ↓
New models are enabled without enough evidence
                ↓
Quality may drop on important tasks
                ↓
Teams lose trust and return to premium-by-default
```

Existing gateways can manage API keys, budgets, retries, provider failover, and
logs. Tarkado does not try to replace them. It answers the harder question:

> Based on our own engineering tasks and evidence, which approved model should
> handle this task, and is a new model safe to enable?

## What Tarkado does

```text
Developer starts a coding task
                ↓
Tarkado reads approved task metadata and policy
                ↓
Tarkado recommends a cheap, standard, or premium model
                ↓
Developer accepts or rejects; chooses the model manually
                ↓
Existing coding tool or gateway sends the request
                ↓
Link recommendation, response, actual model, cost, and outcome
                ↓
Improve recommendations using evidence; prioritize senior feedback
```

This is the early recommendation-only workflow. A suggestion or per-task
acceptance does not authorize automatic routing.

Examples:

| Task | Suggested route |
| --- | --- |
| Explain this file | Cheap model |
| Write unit tests for this function | Standard model |
| Review authentication changes | Premium model |
| Database migration affecting customer data | Premium model with a stricter policy |
| A new model just launched | Evaluate first; do not enable by default |

## Target user

Tarkado is for small engineering teams that:

- use a provider-neutral coding tool such as OpenCode;
- use company-managed API keys or an existing API gateway;
- have access to multiple approved AI models;
- want to control AI spend without hurting developer productivity; and
- want a safer way to evaluate newly released coding models.

Tarkado is not for pooling employees' personal ChatGPT or Claude
subscriptions.

## Core workflow

### 1. Observe all developers

Tarkado begins in observe-only mode across all participating developers within
the company's approved collection scope. It does not change anyone's selected
model. It records approved metadata such as task type, selected model,
input/output token counts, API cost, latency, test outcomes, developer
overrides, and policy version.

### 2. Recommend in shadow mode

Tarkado suggests an approved model but does not select it automatically or
execute an alternative model in the background:

```text
Current model:   premium
Suggested model: standard
Reason:          similar low-risk test tasks passed at lower cost
Confidence:      medium
```

Developers choose manually. Shadow mode creates no extra alternative-model
requests. When evidence is missing, Tarkado says so rather than inventing
confidence.

### 3. Learn from senior feedback and actual results

A senior accepts or rejects a recommendation for **one task**. Tarkado links
that response to the model actually used and the eventual task outcome.
Acceptance alone is preference; acceptance followed by a confirmed desired
result is useful quality evidence.

Tarkado learns across tasks and sessions, giving senior feedback greater
influence while continuing approved monitoring for everyone. Rejects, failures,
overrides, and unknown results count too. Learning does not enable routing.

### 4. Review readiness and authorize a limited pilot

When evidence supports specific task categories, Tarkado reports readiness,
quality/cost trade-offs, failures, and evidence gaps. A designated senior/admin
must explicitly approve the **first automatic-routing pilot**, including its
policy version and limited scope. Per-task acceptance is not pilot approval.

The initial scope may be one repository, a volunteer team, or an evidenced
low-risk task category. The developer can always override the decision.

### 5. Route within approved scope and monitor everyone

After pilot approval, Tarkado can automatically select models for **junior and
senior developers** within that scope, only before a new task/run/subagent
begins. An illustrative approved policy might be:

```text
Simple task            → cheap model
Normal coding task     → standard model
Security or migration  → premium model
Unknown or high-risk   → approved premium fallback
```

Every policy is reversible.

Monitoring continues across everyone, with senior feedback still prioritized.
Unknown or unsupported work uses the safe default; confidence cannot silently
expand the pilot into other task categories.

## New-model rollout

A new coding model should never become the default just because it is cheaper
or newly released. Tarkado uses this rollout path:

```text
Candidate model added
                ↓
Select representative engineering tasks
                ↓
Run offline evaluation
                ↓
Compare quality, cost, latency, test outcomes, and failures
                ↓
Review recorded outcomes and senior per-task feedback
                ↓
Recommendation: READY FOR REVIEW / KEEP SUGGESTING / MORE EVIDENCE / REJECT
                ↓
Senior/admin authorizes model/policy use and the initial routing pilot
```

Offline tools compare already recorded outcomes; they do not call models.
Shadow recommendations never execute alternatives. Any separate candidate-model
experiment needs explicit company authorization, approved data, and API budget.
A new model's release, low price, or one accepted suggestion never enables it.

This is the main reason Tarkado exists.

## What Tarkado is not

Tarkado is not:

- another generic LLM gateway;
- a replacement for OpenCode, LiteLLM, or OpenRouter;
- a tool that silently switches models halfway through an active coding session;
- a browser automation layer for ChatGPT or Claude subscriptions;
- a guarantee that cheaper models are always safe; or
- a system that claims production savings from public benchmark results alone.

## Architecture

```text
┌────────────────────────────────┐
│ Coding tool                    │
│ OpenCode or compatible CLI     │
└───────────────┬────────────────┘
                │ New task or subagent boundary
                ▼
┌────────────────────────────────┐
│ Tarkado                        │
│ Policy and evaluation engine   │
│ • Model recommendation         │
│ • Confidence and fallback      │
│ • Rollout report               │
└───────────────┬────────────────┘
                │ Developer's choice initially;
                │ scoped automatic choice only after pilot approval
                ▼
┌────────────────────────────────┐
│ Existing gateway or APIs       │
│ LiteLLM / OpenRouter / direct  │
│ provider APIs                  │
└───────────────┬────────────────┘
                ▼
┌────────────────────────────────┐
│ Approved model                 │
│ Cheap / standard / premium     │
└────────────────────────────────┘
```

Tarkado is the **control plane** [the part that decides policy]. The coding
tool or gateway is the **data plane** [the part that sends requests to models].

## Safety principles

1. **Default to fallback.** If Tarkado is uncertain, it uses the team's
   approved default model.
2. **No mid-session surprise switching.** Routing happens before a task, run,
   or subagent begins.
3. **Human override always wins.** Developers can choose another approved
   model.
4. **No raw code by default.** Tarkado supports metadata-only collection and
   local-first storage.
5. **No unknown capability assumptions.** A model must be explicitly approved
   for required tools, context length, and task type.
6. **Evidence before enforcement.** Observe first, shadow next, pilot later,
   and require senior/admin approval for the first automatic-routing pilot.
7. **Every decision is explainable.** Tarkado records the chosen model, reason,
   confidence, fallback, and policy version.
8. **Feedback is linked to results.** Per-task acceptance is not success or
   policy approval. Prioritize senior feedback without hiding anyone's failures.

## Initial roadmap

### Phase 1 — Offline simulator

- Import local task traces.
- Define cheap, standard, and premium model tiers.
- Replay historical tasks against different policies.
- Generate readable cost and quality reports.
- Generate a versioned routing policy.

### Phase 2 — New-model evaluator

- Register a candidate model.
- Compare it against the current policy.
- Measure cost, latency, outcomes, failures, and uncertainty.
- Report readiness for review, shadow advice, evidence gaps, or rejection;
  model/pilot authorization is a separate decision.

### Next priority — Recommendation and feedback loop

- Link each suggestion, per-task response, actual model choice, and result.
- Continue monitoring everyone while prioritizing senior feedback.
- Learn simple task-category recommendations from approved evidence.
- Produce readiness reports without automatically enabling routing.
- Require separate senior/admin approval for the first limited routing pilot.

### Phase 3 — OpenCode integration

- Observe OpenCode tasks without changing model selection.
- Show routing recommendations and support shadow mode.
- Support controlled pilots.
- Export policies to existing gateways later.

### Phase 4 — Advanced routing

- Similar-task retrieval.
- Active task selection [choosing the most useful tasks for testing a new
  model].
- Optional fast decision models such as Laya.
- Gateway policy exports.

Advanced methods stay only if they beat simple baselines.

## Run the offline simulator

From the repository root, using the project's Python environment:

```sh
.venv/bin/python -m engine replay tests/fixtures/synthetic.jsonl \
  --policy tests/fixtures/policy.json
```

The application code lives in `engine/`; Tarkado remains the product name.
The simulator has no runtime dependencies and makes no API calls. The example
uses fictional models and deliberately includes a cheaper route with worse
test outcomes. Its results are not evidence of production savings.

Run the local recommendation/response/result demonstration:

```sh
.venv/bin/python -m engine feedback import tests/fixtures/feedback-demo.json \
  --policy tests/fixtures/policy.json --store local/feedback-demo
```

This records synthetic senior/junior feedback and actual-model results without
executing models. Acceptance without use is not counted as success, and junior
failures remain visible. The review ranking does not train or activate a policy.
See [FEEDBACK.md](docs/FEEDBACK.md) for incremental record commands and limits.

Fit an experimental learner from that demo:

```sh
.venv/bin/python -m engine feedback learn \
  --store local/feedback-demo --policy tests/fixtures/policy.json \
  --plan tests/fixtures/learning-plan.json --output local/feedback-learner-v1.json
```

Supply it explicitly for future manual suggestions; it never activates routing.
See [LEARNING.md](docs/LEARNING.md) for application commands, source checks,
illustrative settings, and pending real-task validation.

Build a category review report from the existing demo:

```sh
.venv/bin/python -m engine feedback readiness \
  --store local/feedback-demo --policy tests/fixtures/policy.json \
  --learner local/feedback-learner-v1.json --output local/category-review-v1.json
```

Documentation can be reviewed locally; failed test-generation evidence remains
blocked. Designated senior/admin pilot receipts are available for **local
simulation only**, not live authorization. See
[READINESS_PILOT.md](docs/READINESS_PILOT.md) for commands and limitations.

The local pilot runtime now supports activation, scoped decisions, budget
reservations, settlement, pause/revocation, and default-only rollback. It never
calls models or changes sessions. Follow the
[runtime walkthrough](docs/READINESS_PILOT.md#local-pilot-runtime--implemented)
after creating a separate local review receipt.

**Actual company accounts and manual task workflow:** the optional application
supports real login, private invitations, company permissions, policy/collection
setup, and linked suggestions/responses/reported models/outcomes around the
existing engine. Historical roles are retained; old demo ledgers remain unchanged.
No company SSO is required. Follow the
[laptop walkthrough](docs/COMPANY_AUTHORIZATION.md#run-the-actual-account-laptop-demonstration)
to bootstrap a new private store and run the loopback interface. The approved
company dependencies are installed in `.venv` (Python 3.13); the old environment
is preserved. For an existing installation, stop the server and use `company
upgrade` on the same store before restarting. Admins and designated approvers now
must enroll/verify authenticator MFA; one-use backup codes recover a lost factor
only. Follow the [MFA walkthrough](docs/COMPANY_AUTHORIZATION.md#try-mfa-on-the-laptop).
Private offline/admin-assisted password recovery, stored category review,
separate authenticated simulation approval/rejection, and B-01-backed pilot
controls now work through the same application. A Waitress single-host
HTTPS-proxy serving contract and private paired backup command are available.
Follow [COMPANY_OPERATIONS.md](docs/COMPANY_OPERATIONS.md) for the joined
walkthrough, upgrades, recovery, and serving prerequisites. **B-02 authorization
implementation is complete**, including positive conditional live scope approval
and ordered withdrawal. It requires a server-owned independent readiness checker,
which defaults to refusal. Positive-path tests use controlled test evidence—not
a real company verifier. Actual readiness verification, task/provider integration,
and deployment validation remain separate gates; no model execution is enabled.

**Browser-first B-03:** the same company application now provides task cards and
pending states, guided metadata/policy forms, labeled validation-session and
pilot-scope selection, separate exact-content confirmations, readable evidence/
accounting/history, and owned settlement choices without copying JSON/internal IDs.
Follow [BROWSER_WORKFLOW.md](docs/BROWSER_WORKFLOW.md) for the joined laptop
walkthrough. Observation and outcomes are still manual/unverified; no B-04 connector,
model calls, automatic routing, or real readiness verifier is added.

**B-04 connector foundation:** scoped browser-issued credentials, a metadata-only
API, explicit linked tasks, append-only observations, and OpenCode V2 server/CLI
plugin source are now available. Plugin loading/terminal-host and real-session
validation are **not performed**; no Laya, dependencies, model calls, automatic
selection, or private access are introduced. See
[OPENCODE_CONNECTOR.md](docs/OPENCODE_CONNECTOR.md) for supported scope and remaining gates.

**B-05 joined build:** reviewed learners can now be explicitly published for future
browser/connector manual suggestions, with exact history and safe fallback after
new feedback/gaps. Conditional live-scope selection/reservation/claim/settlement
mechanics require an additional server-owned admission verifier, default-denying.
No OpenCode automatic switching/provider delivery is installed or claimed. See
[INTEGRATED_LEARNING_SELECTION.md](docs/INTEGRATED_LEARNING_SELECTION.md).

Run the tests:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

See [DEVELOPMENT.md](docs/DEVELOPMENT.md) for input formats, observe/shadow
reports, local policy export, and implementation limitations.

Evaluate the synthetic new-model candidate:

```sh
.venv/bin/python -m engine evaluate tests/fixtures/rollout.jsonl \
  --policy tests/fixtures/rollout-policy.json \
  --candidate fixture/candidate --plan tests/fixtures/rollout-plan.json
```

Expected: **REJECT** (exit code `1`) because the cheaper candidate has quality
regressions. This is a successful negative evaluation, not a command error.
See [ROLLOUT.md](docs/ROLLOUT.md) for model states, repeated samples, evidence
gates, and why the evaluator cannot authorize live deployment.

Candidate reports also include uncertainty across distinct tasks, with repeated
runs grouped inside each task. Confidence bounds require explicitly stated
sampling assumptions and never approve a rollout. See
[UNCERTAINTY.md](docs/UNCERTAINTY.md) for the conservative baseline and its limits.

Inspect local policy history:

```sh
.venv/bin/python -m engine policy history
```

Policy snapshots, local review records, and reversible local selection are
available. See [POLICY_HISTORY.md](docs/POLICY_HISTORY.md) for save/review/select
and rollback commands. These do not change live routing or approve models.

Check metadata and export a local audit:

```sh
.venv/bin/python -m engine privacy check tests/fixtures/synthetic.jsonl --kind traces
.venv/bin/python -m engine replay tests/fixtures/synthetic.jsonl \
  --policy tests/fixtures/policy.json --audit local/replay-audit.jsonl
```

Supported secret patterns are blocked; audit task identifiers are hashed and
files are never overwritten. These checks cannot prove data is secret-free.
See [PRIVACY_AUDIT.md](docs/PRIVACY_AUDIT.md) for the format and limitations.

Inspect the OpenCode observe-only wrapper without connecting:

```sh
.venv/bin/python -m engine opencode observe --help
```

The first adapter reads explicitly scoped session snapshots without changing
model selection. It is **not live task-boundary capture**. See
[OPENCODE_ADAPTER.md](docs/OPENCODE_ADAPTER.md) for required company-API
confirmation, usage, metadata limitations, and mock-test coverage.

## Documentation

| File | Purpose |
| --- | --- |
| [WORKFLOW.md](docs/WORKFLOW.md) | Owner-approved company workflow and unresolved details. |
| [FEEDBACK.md](docs/FEEDBACK.md) | Local recommendation/response/actual-model/result linkage and review ranking. |
| [LEARNING.md](docs/LEARNING.md) | Experimental feedback fitting and future manual suggestions; no activation. |
| [READINESS_PILOT.md](docs/READINESS_PILOT.md) | Category evidence review and separate local pilot receipts; no live routing. |
| [COMPANY_AUTHORIZATION.md](docs/COMPANY_AUTHORIZATION.md) | Accepted self-hosted invitation-only onboarding and B-02 technical design; implementation in progress. |
| [COMPANY_OPERATIONS.md](docs/COMPANY_OPERATIONS.md) | Joined recovery/review/simulation-pilot workflow, HTTPS-proxy serving contract, backup, and remaining live gates. |
| [BROWSER_WORKFLOW.md](docs/BROWSER_WORKFLOW.md) | Browser-first B-03 task/evidence/scope/control walkthrough and still-manual limits. |
| [COMPANY_OPERATIONS.md — live boundary](docs/COMPANY_OPERATIONS.md#b-02-live-authorization-boundary--implementation-complete) | Completed B-02 conditional live-approval mechanics, default-denying readiness interface, and deployment/execution separation. |
| [PRD.md](docs/PRD.md) | Product requirements and user workflow. |
| [TRD.md](docs/TRD.md) | Technical requirements and proposed architecture. |
| [TASKS.md](docs/TASKS.md) | Ordered build roadmap and acceptance checks. |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Run the simulator, tests, and local policy export. |
| [ROLLOUT.md](docs/ROLLOUT.md) | Offline candidate evaluation and rollout safety limits. |
| [UNCERTAINTY.md](docs/UNCERTAINTY.md) | Task-weighted estimates, confidence bounds, and sampling assumptions. |
| [POLICY_HISTORY.md](docs/POLICY_HISTORY.md) | Local snapshots, review records, selection, and rollback. |
| [PRIVACY_AUDIT.md](docs/PRIVACY_AUDIT.md) | Secret checks and metadata-only per-task audit exports. |
| [OPENCODE_ADAPTER.md](docs/OPENCODE_ADAPTER.md) | V2 read-only session snapshots and pending live-capture work. |
| [OPENCODE_CONNECTOR.md](docs/OPENCODE_CONNECTOR.md) | B-04 explicit-task connector/API/plugin source, pairing, capture limits, and unverified-host gates. |
| [INTEGRATED_LEARNING_SELECTION.md](docs/INTEGRATED_LEARNING_SELECTION.md) | B-05 learner publication/future manual guidance, conditional selection accounting, default-denying admission, and missing live-delivery adapter. |
| [DECISIONS.md](docs/DECISIONS.md) | Decisions, assumptions, and unresolved choices. |
| [RESEARCH.md](docs/RESEARCH.md) | Market and research evidence. |
| [AGENTS.md](AGENTS.md) | Engineering rules for implementation work. |

## Project status

**Early implementation: supporting offline tools are available, not the full
company workflow.** Tarkado imports local metadata, compares simple rules
against recorded task/model outcomes,
reports cost and quality together, and exports supplied versioned policies as
local proposals. The candidate evaluator compares repeated recorded outcomes
and gives conservative reject, shadow, or collect-more-evidence advice. Neither
command approves a rollout or changes live model selection.

Local policy history preserves snapshots, binds review labels to their
content, and supports reversible local selection without modifying model
approval states.

Supported secret-pattern checks and explicit private audit exports are also
available. Raw task content and live task/provider integration remain unsupported.
Company approval mechanics are implemented separately from the unsigned offline
tools; they do not enable live execution or verify imported data automatically.

A documented OpenCode V2 read-only snapshot wrapper is available and tested
against a mock executable. Live task-boundary capture and real-provider
integration validation remain pending.

Local recommendation → response → actual model → result linkage is available,
including declared roles, delayed outcomes, and correction history. A simple
senior-prioritized evidence ranking supports manual review. An experimental
count-based learner can fit and change future manual suggestions when explicitly
supplied. Its benefit/settings are **not production-validated**; neither these
records nor learner artifacts authorize a company pilot.

Category-review reports and designated senior/admin local pilot receipts are
available. They preserve blockers and scope, but do not verify company
identities or enable live routing. The separate persistent simulation runtime
enforces local task/budget reservations and preserves settlement/rollback
history; it does not enforce a real provider's cost cap.

B-02 company setup/authorization code is complete, including actual accounts,
MFA/recovery, scoped simulation controls, and conditional live scope approval.
The latter needs an independent server-owned readiness check in addition to the
designated human decision. That check defaults to refusal, and no real company
verifier or live execution is configured. Passing the test-only positive path is
not production readiness, model-quality validation, or savings evidence.

Reviewed enablement, independently verified evaluation design, live task
integrations, and gateway exports remain planned. Verified progress is tracked in
[docs/TASKS.md](docs/TASKS.md).

**Completion target:** finish the accepted company workflow as one usable
end-to-end build, not a collection of fixture demos. Remaining build packages
and the definition of complete are recorded in
[docs/TASKS.md](docs/TASKS.md#completion-goal--first-end-to-end-tarkado-build).
Live deployment still requires approved access, evidence, and trusted pilot
authorization; these are not replaced by passing synthetic tests.

## Guiding principle

> Do not route because a model is cheap.
>
> Route because evidence says the task can safely use it.
