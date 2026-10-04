# Product Requirements Document — Tarkado

**Status:** Draft 0.2; company workflow accepted on 2026-10-03
**Project name:** Tarkado
**Audience:** Small engineering teams using multi-model coding tools  
**Last updated:** 2026-10-03

The finalized product journey is in [WORKFLOW.md](WORKFLOW.md). Exact learning
methods, evidence thresholds, and approval authentication remain design work.

## 1. Product statement

Tarkado is a policy/evaluation layer that first observes approved work across
the company and recommends coding models without changing developer choices.
It learns from linked per-task feedback and actual outcomes across sessions,
giving senior feedback greater influence while continuing to monitor everyone.

Once evidence supports specific task categories, Tarkado reports readiness. A
designated senior/admin authorizes the first limited automatic-routing pilot.
Only then can a versioned policy select approved models for junior and senior
developers within that scope through their existing coding tool/gateway.

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
- Self-hosted Tarkado with invitation-only individual accounts and explicit first
  administrator enrollment. Existing company SSO is optional later; the same real
  application must also be demonstrable on a laptop (C-01–C-05 in DECISIONS.md).
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

### Stage A — Observe everyone

The company approves collection scope and installs **observe-only mode** for
all participating developers. It does not change anyone's model selection.

It records only approved metadata:

- task category and risk tags;
- selected model and reasoning tier;
- input/output token counts, cost, and latency;
- outcome signals such as tests passing, developer override, or explicit
  rating;
- policy version, if a policy was suggested;
- a permitted developer reference and role for later role-aware feedback.

### Stage B — Recommend in shadow mode

Tarkado recommends an approved model for a task, but the developer chooses
manually. It never runs an alternative model automatically in shadow mode.
The team can see:

```text
Current choice: premium model
Suggested choice: standard model
Reason: similar low-risk tasks passed tests at lower cost
Confidence: medium
```

The confidence shown above is illustrative, not a guaranteed initial capability.
Missing evidence must be disclosed. Recommendation display does not authorize
a provider/model or alter the active session.

### Stage C — Link senior feedback and actual outcomes

A senior accepts or rejects the recommendation for **one task**. Tarkado links:

```text
Recommendation → per-task response → model actually used → eventual result
```

Acceptance alone records preference. Acceptance, actual use of the suggested
model, and a confirmed desired result provide useful quality evidence. If the
developer used a different model, do not credit the suggested model with that
result. Missing results remain unknown; rejections, failures, and overrides
are retained rather than filtered out.

### Stage D — Learn across tasks/sessions and report readiness

Continue collecting approved usage/outcome metadata from everyone. Prioritize
senior feedback when improving recommendations; do not stop junior monitoring
or treat senior acceptance as infallible.

Begin with a simple learning baseline. Validate the feedback aggregation,
task-category coverage, and cost/quality trade-offs before claiming readiness
for a category. A ready-for-review report includes evidence gaps, failures,
overrides, compatibility, and a proposed limited scope—not automatic activation.

### Stage E — Senior/admin authorization and limited pilot

A designated senior/admin reviews the readiness evidence and explicitly
approves the **first automatic-routing pilot**, its policy version, and limited
repository/team/task-category scope. This is separate from accepting one task's
recommendation. Training, confidence, or an offline report cannot bypass it.

After approval, the existing coding tool/gateway can select models for junior
and senior developers in that scope, only at new-task/run/subagent boundaries.
Developers can override every decision. Unknown/unsupported work keeps the
approved safe default; missing fallback compatibility blocks rather than guesses.

### Stage F — Monitor and review expansion

Continue monitoring everyone and prioritizing senior feedback during the pilot.
Track quality, costs, overrides, and outcome regressions. The policy remains
versioned and reversible; growing confidence does not silently expand scope.

### Separate track — New-model evaluation

When a new coding model launches:

1. Add it as a candidate, not as a default.
2. Compare available approved evaluation evidence to the current baseline.
3. Report quality, cost, latency, failures, compatibility, and evidence gaps.
4. Propose further evidence/review or reject; do not change approval state.
5. Require explicit company model approval and the separate senior/admin pilot
   authorization before automatic routing to the new model.

Offline tools compare recorded outcomes; they do not create missing outputs.
Any future isolated alternative-model experiment needs separate company/data
authorization and API budget. It is not part of recommendation-only shadow
mode or a prerequisite that quietly runs on every developer task.

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

### Required next — The recommendation/feedback learning loop

- Define permitted developer/role references without collecting raw task content.
- Link recommendation IDs, per-task accept/reject responses, actual model use,
  and delayed results without double counting or inventing outcomes.
- Distinguish senior per-task feedback from authorized company pilot approval.
- Keep everyone else's approved observations and negative feedback visible.
- Learn a simple baseline from senior-prioritized feedback plus task results;
  validate before adopting more advanced methods.
- Produce category-specific readiness reports that do not activate routing.

### Required for a coding-tool integration

- Receive a new-task or subagent-boundary event.
- Choose only from the team's approved, compatible model set.
- Route before task/session execution, not unexpectedly in the middle of a
  live agent session.
- Preserve a user override path.
- Preserve manual selection in initial recommendation-only shadow mode; do not
  send duplicate alternative-model requests.
- Enforce the separate senior/admin authorization for the first scoped routing
  pilot; never interpret per-task feedback as that authorization.
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
- A new-model report clearly recommends review, shadow, further evidence, or
  rejection without authorizing model/pilot activation.
- A per-task recommendation can be traced to the developer's response, actual
  model choice, and known/unknown result.
- The senior-prioritized learning loop retains company-wide usage/outcome
  visibility and reports readiness only for evidenced categories.
- No automatic-routing pilot starts without a designated senior/admin's
  separate policy/scope authorization.

### Quality measures

- No enforced policy is enabled without an offline comparison against a
  baseline policy.
- Task acceptance and API/session completion are never counted as verified
  engineering success by themselves.
- Junior failures remain evaluation signals even when senior feedback is positive.
- Cost reductions are reported alongside quality/outcome changes, never alone.
- Routing failures fall back to an approved default model.
- Raw source code/prompt content is opt-in for collection; metadata-only mode
  must be supported.

## 9. MVP boundaries

The existing foundation is an **offline policy simulator plus local CLI**.
It is not the complete company product. The next priority is the locally
testable recommendation → response → actual model → outcome learning loop.
Then integrate observe/recommend behavior before an approved routing pilot.

Local recommendation/response/actual-model/result records and a preliminary
senior-prioritized review ranking are implemented in [FEEDBACK.md](FEEDBACK.md).
This validates links, not identities or outcome truth. Experimental fitting and
future manual application are documented in [LEARNING.md](LEARNING.md), but
real-world improvement/settings are not validated. Local category review and
designated simulation receipts are in [READINESS_PILOT.md](READINESS_PILOT.md).
Verified company readiness, real task/provider admission, and live
task-level collection/routing are still unimplemented. Snapshot observation and
local review labels must not be presented as substitutes for them.

Initial real individual login/company setup is implemented in
[COMPANY_AUTHORIZATION.md](COMPANY_AUTHORIZATION.md), using the existing engine's
policy contracts. The same authenticated interface now links manual suggestions,
responses, reported actual models, and outcomes with historical role snapshots.
It does not verify outcomes or capture live tasks. Category learning/review,
separate authenticated scoped **simulation** approval/runtime controls,
forgotten-password recovery, and a single-host HTTPS-proxy serving contract are
implemented. Conditional live scope approval mechanics now require a trusted
independent readiness assessment and separate designated fresh-MFA human approval.
The checker is unconfigured/default-denying; actual company readiness, task/provider
integration, and deployment validation remain pending. Scope approval, MFA, and
recovery are not themselves execution/deployment permission. B-02 implementation
completion does not complete the end-to-end product.
See [COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md).

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
