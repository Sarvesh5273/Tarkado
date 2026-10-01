# Product Requirements Document — Lanesmith

**Status:** Draft 0.1  
**Project name:** Lanesmith
**Audience:** Small engineering teams using multi-model coding tools  
**Last updated:** 2026-10-01

## 1. Product statement

Lanesmith is an open-source policy engine that helps engineering teams choose
an approved coding model for a new task, safely evaluate newly released
models, and export evidence-based routing policies to an existing coding tool
or gateway.

## 2. User problem

An engineering team may have access to several API-billed models. Today,
developers often select a model manually or always use the strongest model.

This creates four problems:

1. **Uncontrolled spend:** simple tasks may consume premium-model tokens.
2. **Unclear quality trade-off:** cheaper models may work for some tasks but
   fail on others.
3. **Model-release churn:** teams repeatedly ask whether a new model is worth
   adopting.
4. **Unsafe change:** a cost policy that silently degrades code quality loses
   developer trust immediately.

## 3. Product goal

Give a team a transparent answer before and during model routing:

> “For this task class, which approved model tier is justified by our own
> evidence, and what happens if we enable a new model?”

## 4. Target user and environment

### Primary user

Platform engineer, developer-experience engineer, or technical founder at a
small software company.

### Assumed environment

- A provider-neutral coding client such as OpenCode.
- Company-managed provider credentials, OpenRouter credentials, or an existing
  company gateway.
- More than one approved coding model/tier.
- Permission to collect limited task metadata and outcome signals.

### Not the target environment

- Employees' personal ChatGPT/Claude subscriptions.
- A company with no tasks, traces, feedback, or way to evaluate output.
- A team that needs a fully managed enterprise gateway before it needs a policy
  engine.

## 5. Core user journey

### Stage A — Observe

The team installs an integration in **observe-only mode**. It does not change
model selection.

It records only approved metadata:

- task category and risk tags;
- selected model and reasoning tier;
- input/output token counts, cost, and latency;
- outcome signals such as tests passing, developer override, or explicit
  rating;
- policy version, if a policy was suggested.

### Stage B — Evaluate

The team imports a small evaluation set from curated tasks, production traces,
or selected historical tasks. It evaluates candidate models against the current
approved policy.

### Stage C — Shadow mode

Lanesmith recommends a route but does not enforce it. The team can see:

```text
Current choice: premium model
Suggested choice: standard model
Reason: similar low-risk tasks passed tests at lower cost
Confidence: medium
```

### Stage D — Pilot

The team enables routing only for a limited repository, volunteer group, or
low-risk task class. Developers can override every decision.

### Stage E — Enforce and monitor

After evidence supports the policy, Lanesmith exports a versioned policy to an
existing integration/gateway. It continuously monitors costs, overrides, and
outcome regressions. A bad policy can be rolled back.

### Stage F — New-model rollout

When a new coding model launches:

1. Add it as a candidate, not as a default.
2. Select representative and informative evaluation tasks.
3. Compare it to the current policy on quality, cost, latency, and risk.
4. Recommend **enable**, **shadow-test**, **collect more evidence**, or
   **reject**.
5. Update the policy only after the approved rollout rule passes.

## 6. Product capabilities

### Required for the first useful version

- Import task traces/evaluation cases from a local file.
- Define approved model tiers: cheap, standard, premium.
- Replay historical tasks through candidate policies offline.
- Calculate cost, latency, task outcome, model overrides, and policy coverage.
- Generate a readable routing-policy recommendation.
- Keep every recommendation explainable: rule, evidence, confidence, and
  fallback.
- Version, export, and roll back policies.

### Required for a coding-tool integration

- Receive a new-task or subagent-boundary event.
- Choose only from the team's approved, compatible model set.
- Route before task/session execution, not unexpectedly in the middle of a
  live agent session.
- Preserve a user override path.
- Fail safely to the team default model when the policy is uncertain or the
  integration fails.

### Future capabilities

- Active task selection [choose the most informative tasks to evaluate a new
  model on].
- Repository/risk-aware policies: security, migrations, payments, tests,
  documentation, and read-only questions.
- Laya or another decision model as an optional fast task/difficulty signal.
- Gateway adapters for LiteLLM/OpenRouter-compatible deployments.
- Local-first dashboard and GitHub Action.

## 7. Explicit non-goals

- Build a generic API gateway from scratch.
- Replace a coding agent's tool-use or permission system.
- Route blindly based only on short prompt length; “Hi” can begin a difficult
  repository task.
- Claim automatic model switching between incompatible coding-agent products.
- Use a vendor's consumer subscription as a shared company API service.
- Claim that a public benchmark proves production savings.

## 8. Success measures

### Product measures

- A team can install observe-only mode without changing workflows.
- A policy decision includes a model, reason, confidence, fallback, and policy
  version.
- A user can override a decision and the override is recorded.
- A new-model report produces a clear enable/shadow/reject recommendation.

### Quality measures

- No enforced policy is enabled without an offline comparison against a
  baseline policy.
- Cost reductions are reported alongside quality/outcome changes, never alone.
- Routing failures fall back to an approved default model.
- Raw source code/prompt content is opt-in for collection; metadata-only mode
  must be supported.

## 9. MVP boundaries

The MVP is an **offline policy simulator plus local CLI**. It should prove the
policy/evaluation loop before building a real gateway or production plugin.

The first live integration target is a provider-neutral tool such as OpenCode,
where one tool can select among multiple configured models. Standalone Claude
Code/Codex integrations are later adapters and may have provider-specific
constraints.

## 10. Risks

| Risk | Product response |
| --- | --- |
| No labelled cases | Report insufficient evidence; help create an evaluation set rather than invent confidence. |
| Cheap model harms code | Start in observe/shadow mode; use a premium fallback and developer override. |
| Sensitive prompts/code | Default to local metadata collection and redact/avoid raw content. |
| Gateway already solves the problem | Integrate with gateways; focus on private evaluation and policy generation. |
| Developers distrust the router | Make decisions explainable, reversible, and optional at first. |
| New model is incompatible | Mark it unsupported for that task/integration instead of forcing it into the policy. |
