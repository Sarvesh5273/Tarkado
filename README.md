# Tarkado

> **The path of reasoned model choice for engineering teams.**

Tarkado helps engineering teams decide which AI coding model should handle a
task, safely test newly released models, and reduce unnecessary API spend
without silently lowering code quality.

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
Existing coding tool or gateway sends the request
                ↓
Cost, latency, outcome, and developer override are recorded
                ↓
The policy improves using evidence
```

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

### 1. Observe

Tarkado begins in observe-only mode. It does not change a developer's selected
model. It records approved metadata such as task type, selected model,
input/output token counts, API cost, latency, test outcomes, developer
overrides, and policy version.

### 2. Evaluate

The team imports a small set of real engineering tasks from curated test cases,
historical coding-agent traces, pull-request reviews, test-generation tasks,
bug fixes, or selected production incidents. Tarkado compares candidate models
against the team's current policy.

### 3. Shadow mode

Tarkado recommends a route but does not enforce it:

```text
Current model:   premium
Suggested model: standard
Reason:          similar low-risk test tasks passed at lower cost
Confidence:      medium
```

The developer and team remain in control.

### 4. Limited pilot

The team enables routing only for a small scope: one repository, a volunteer
team, read-only questions, documentation tasks, test generation, or low-risk
bug fixes. The developer can always override the decision.

### 5. Enforce and monitor

Once a policy has enough evidence, it can be versioned and enforced:

```text
Simple task            → cheap model
Normal coding task     → standard model
Security or migration  → premium model
Unknown or high-risk   → approved premium fallback
```

Every policy is reversible.

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
Recommendation: ENABLE / SHADOW TEST / COLLECT MORE EVIDENCE / REJECT
                ↓
Update routing policy only after approval
```

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
                │ Approved route
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
   and enforce only after review.
7. **Every decision is explainable.** Tarkado records the chosen model, reason,
   confidence, fallback, and policy version.

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
- Recommend enable, shadow-test, collect-more-evidence, or reject.

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

## Documentation

| File | Purpose |
| --- | --- |
| [PRD.md](docs/PRD.md) | Product requirements and user workflow. |
| [TRD.md](docs/TRD.md) | Technical requirements and proposed architecture. |
| [TASKS.md](docs/TASKS.md) | Ordered build roadmap and acceptance checks. |
| [DECISIONS.md](docs/DECISIONS.md) | Decisions, assumptions, and unresolved choices. |
| [RESEARCH.md](docs/RESEARCH.md) | Market and research evidence. |
| [AGENTS.md](AGENTS.md) | Engineering rules for implementation work. |

## Project status

Tarkado is currently in the planning stage. The first build target is not a
production gateway. It is a local offline policy simulator that proves whether
Tarkado can make transparent, safe, evidence-based model-routing
recommendations.

## Guiding principle

> Do not route because a model is cheap.
>
> Route because evidence says the task can safely use it.
