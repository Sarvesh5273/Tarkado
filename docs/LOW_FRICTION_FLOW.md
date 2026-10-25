# Low-friction developer flow (design; first step built)

**Status:** owner direction 2026-10-25, after the first real laptop run. First step built
and verified in real OpenCode 2.0.21 on 2026-10-25: `/tarkado-delivery-quick` (one
"Use suggestion / Keep mine" confirmation that also records the acceptance) and an end step
that reports the gateway-observed model only for a clean, known-cost run. Gaps against the
design below: the defaults come from the private laptop bundle (`quickStart`), not from
approver-set per-category defaults in the approved scope; the original model is the bundle
default, not the model selected in OpenCode; "Keep mine" records nothing (no task exists to
attach a rejection to); the developer still types start and end commands.

## Problem

One routed task currently takes four commands (`start`, `accept`, `end`,
`report-model`) and ten start dialogs (scope, category, local capabilities, label,
original model, override, low-risk confirmation, context tokens, output limit, task cost
cap). A real team will not do that per task. Most of those inputs exist for safety and
auditability, not because only the developer can know them.

## Principle

Do not interrupt the developer's work. Ask a developer only for what nothing else can
supply. Everything else comes from company policy (set once by a human), the gateway, or
the repository. Safety gates are unchanged: MFA-approved scopes, caps, expiry, provider
policy and gateway checks still apply. Only where each input comes from changes.

## Where each input comes from

| Input today (per task, developer) | Source in the low-friction flow |
| --- | --- |
| Approved scope | Automatic when exactly one active scope matches repository + developer; ask only if several do |
| Task label | Generated (`<developer>-<date>-<n>`) |
| Local capabilities, context tokens, output limit, task cost cap | Per-category defaults in the approved scope, set once by the approver |
| Original manual model choice | The model already selected in OpenCode |
| Override | The popup's "Keep mine" answer |
| Low-risk confirmation | Policy: the category is either inside the approved scope or not |
| Actual model used | Gateway binding record (policy model → gateway model → provider model) |
| Result | Passive signals: CI on the change, change kept or reverted; occasional sampled senior feedback (one keypress) |
| End task | Automatic at the next task boundary or after a sustained idle period |

## What the developer sees

One non-blocking prompt when a new task starts:

> Tarkado suggests **company/luna** for this **documentation** task (approved trial,
> about N× cheaper). **[Use it]** / **[Keep mine]**

Ignoring it means "keep mine". Nothing else is asked. Observe-only companies (no approved
scope) see the same prompt as a suggestion only.

## Decision needed: task category

1. **Developer picks** from a short list inside the same prompt. Private and explicit;
   one extra keypress. **Recommended first.**
2. **Inferred locally** on the laptop from the typed request; only the label leaves the
   machine. No extra keypress, but Tarkado then reads prompts locally, which changes the
   privacy statement and needs the classifier's errors measured.

## Changes this implies (and what each one risks)

- **Per-task explicit bounds become approved per-category defaults.** Today the plugin
  insists on explicit per-task values ("no default budget"). Moving them into the
  MFA-approved scope keeps them human-set and bounded, but they are no longer re-stated
  per task. Record this as a decision change when built.
- **Actual model from the gateway, not a developer report.** Stronger evidence than a
  manual report; the learner must label it as gateway-observed.
- **Results from passive signals.** CI pass and "change kept" are proxies, not
  engineering success. Keep them labelled as such, keep unknowns unknown, and keep senior
  feedback weighted higher.
- **Automatic end.** Needs a reliable task-boundary signal from OpenCode. The current
  plugin only ends on an explicit idle status; an idle timeout can cut a long task, so
  measure on real sessions first.
- **Restart survival** (already a follow-up in TASKS.md) becomes required, because
  developers will not run recovery steps.

## Not changing

Manager-side approval (evidence review, password + authenticator code), expiring scopes,
lifetime task and cost caps, provider deny-by-default in OpenCode, gateway refusal of
unknown tool definitions, and metadata-only collection.
