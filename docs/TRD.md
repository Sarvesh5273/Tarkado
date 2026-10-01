# Technical Requirements Document — Lanesmith

**Status:** Draft 0.1  
**Scope:** Architecture and requirements, not implementation commitments

## 1. Design principle

Lanesmith is a **control plane** [the part that decides rules], not a new
gateway. A gateway or coding client remains the **data plane** [the part that
actually sends each request to a model].

```text
              ┌──────────────────────────┐
              │  Lanesmith control plane │
              │ policy + evaluation      │
              └────────────┬─────────────┘
                           │ policy decision
                           ▼
┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ OpenCode or   │ → │ Existing       │ → │ Provider/model  │
│ another client│   │ gateway/API    │   │ chosen by policy│
└───────────────┘   └───────────────┘   └─────────────────┘
        │                     │
        └──── approved traces ┴────→ local event store
```

## 2. Operating modes

| Mode | Behaviour | Safety rule |
| --- | --- | --- |
| Observe | Record approved metadata only. | Never change the selected model. |
| Replay | Evaluate proposed policy on historical tasks. | Offline only. |
| Shadow | Recommend a model without enforcing it. | User/default route remains active. |
| Pilot | Enforce policy for a limited scope. | User override and default fallback required. |
| Enforce | Enforce approved versioned policy. | Rollback and audit trail required. |

## 3. Core components

### 3.1 Trace importer

Reads local JSONL/CSV records initially. Future adapters may import from
OpenCode, LiteLLM, OpenRouter, OpenTelemetry, LangSmith, or Braintrust.

### 3.2 Evaluation store

Stores evaluation cases, candidate outputs, scorers, and outcomes. It must
separate raw content from metadata so a privacy-preserving mode is possible.

### 3.3 Model registry

Stores only models approved by the team, including:

- provider/model ID;
- compatible client/protocol;
- context/tool capabilities;
- price and latency metadata;
- tier: cheap, standard, premium;
- status: candidate, shadow, approved, disabled.

### 3.4 Policy engine

Receives task metadata and returns one of:

```text
route to model X
route to default premium model
ask for user choice
reject because no compatible approved model exists
```

Every decision must include a reason, confidence, policy version, and
fallback.

### 3.5 Rollout evaluator

Compares a new candidate model with the current policy. It reports quality,
cost, latency, failure rate, and uncertainty across repeated samples.

### 3.6 Export adapters

Start with a human-readable YAML/JSON policy. Later adapters can translate it
to OpenCode configuration/plugins or existing gateway configuration.

## 4. Task-boundary routing rule

Lanesmith routes at a **new task**, **new run**, or **subagent** boundary.
It must not silently change a model mid-session in v1.

Reasons:

- an active session may contain provider-specific tool calls or context;
- different models may have different tool, reasoning, and context support;
- an unexpected switch is difficult to debug and reduces user trust.

## 5. Minimum data contracts

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
- recommendation: enable, shadow, collect more evidence, or reject.

## 6. Routing signals

Initial signals should be simple and explainable:

- explicit task type supplied by the user/tool;
- repository or command scope;
- risk tags;
- expected tool use;
- prior outcome/cost statistics for similar tasks;
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
- Offline replay must be deterministic for a fixed input dataset and policy.

## 10. Testing requirements

- Unit tests for policy matching, fallback selection, model compatibility, and
  policy versioning.
- Fixtures with cheap/standard/premium models and expected decisions.
- Tests proving observe/shadow modes never change model selection.
- Tests proving no raw task content is emitted when metadata-only mode is on.
- Integration test against a documented local OpenCode-compatible setup only
  after the offline engine is complete.

## 11. Implementation order

1. Local data schema and replay simulator.
2. Explainable static policy engine.
3. New-model evaluation/report generator.
4. Local CLI and policy export.
5. OpenCode adapter in observe-only mode.
6. Shadow/pilot routing, then gateway exports.
