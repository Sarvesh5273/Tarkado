# Offline new-model evaluation

**Product reference:** [WORKFLOW.md](WORKFLOW.md). The company starts with
recommendations and manual model choice, prioritizes senior per-task feedback
plus actual results, and requires separate senior/admin approval of the first
automatic-routing pilot. Shadow mode never executes an alternative model.

This document describes the existing offline candidate tool, not an implemented
company feedback-learning or pilot-authorization system. Any future isolated
model experiment needs separate company/data permission and API budget.

## Run the candidate example

```sh
.venv/bin/python -m engine evaluate tests/fixtures/rollout.jsonl \
  --policy tests/fixtures/rollout-policy.json \
  --candidate fixture/candidate \
  --plan tests/fixtures/rollout-plan.json
```

Expected: **REJECT**, exit code `1`. This is an intentional negative evaluation,
not a command error. The synthetic candidate costs `0.19` versus `0.60` for the
baseline, but it has one test regression and two score regressions across six
paired samples. Lower cost does not justify those failures.

Add `--format json` for a machine-readable report. The command makes no API
calls and does not edit model approval states or routing policies.

Add `--audit local/candidate-audit.jsonl` for explicit private audit records,
including rejected or missing-outcome evaluations. Reports and audits bind the
exact policy content fingerprint. See [PRIVACY_AUDIT.md](PRIVACY_AUDIT.md) for
secret checks, the format, manual retention, and limitations.

## Model states

Registry entries may declare `status`:

| State | Offline evaluation | Automatic policy routing |
| --- | --- | --- |
| `candidate` | May evaluate recorded outcomes. | Not allowed. |
| `shadow` | May evaluate recorded outcomes. | Not allowed. |
| `approved` | May compare against a different baseline, but no new approval is granted. | Allowed only when policy, risk, and capabilities permit it. |
| `disabled` | Produces a reject recommendation. | Not allowed. |

Phase 1's `approved` boolean remains supported: `true` maps to `approved`, and
`false` maps conservatively to `disabled`, not to `candidate`. If both fields
are provided, they must agree. The configured premium fallback must still be
approved. Evaluation never promotes a model to another state.

## Declare the evaluation plan before examining results

`tests/fixtures/rollout-plan.json` shows the plan format:

```json
{
  "source": "hand-written synthetic repeated outcomes",
  "source_kind": "synthetic",
  "dataset_split": "validation",
  "task_types": ["documentation", "test_generation"],
  "min_tasks": 3,
  "min_samples_per_task": 2
}
```

- `source_kind` is `synthetic`, `public_benchmark`, or `team`.
- `dataset_split` is `validation` or `test`.
- `task_types` is an explicit scope, with no wildcard. Excluded task counts and
  per-type coverage are printed. Every requested type must have complete
  evidence; a scoped conclusion must not be applied to other task types.
- Minimum counts must be positive. These are predeclared evidence gates
  [requirements for sufficient recorded coverage], not statistical guarantees.

The example's count gates are illustrative, not validated production
thresholds. Choose or tune real gates on validation data, freeze them before a
held-out test [data reserved for final checking], and never narrow the task
scope after seeing test failures just to obtain a favorable recommendation.

The evaluator does not tune these values or verify source/split provenance.
Declaring `team` does not authenticate a dataset, and public/synthetic evidence
cannot establish production savings.

## Repeated samples and pairing

Use the same metadata-only JSONL format as replay, with an optional additional
`sample_id` string. Rows from repeated evaluations are grouped by
`(task_id, sample_id)`. Each group needs exactly one original-selection
baseline row and at most one outcome per model. A missing `sample_id` defaults
to `single`, preserving Phase 1 inputs.

All samples of a task must share task type, risk tags, tool requirements, and
context requirement. Trace IDs remain globally unique. Current CSV imports
support single samples only; use JSONL for explicit repeated samples.

The current versioned policy is replayed separately for each sample. Its
compatible recorded result becomes the comparison baseline. The original
no-change selection is shown separately, so a candidate cannot claim a gain
only because the original selection ignored an existing cheaper policy.
Baseline policy fallbacks remain visible in sample explanations.

Missing candidate outcomes are never replaced by premium outcomes. A sample
without a compatible baseline/candidate pair stays unpaired and cannot enter
comparison totals. A candidate already used as the scoped baseline is rejected
as an invalid self-comparison.

## Conservative recommendations

| Recommendation | Meaning |
| --- | --- |
| `reject` | Disabled/incompatible model, non-low-risk scope, failed tests, a paired quality regression, or a new paired developer override. |
| `collect_more_evidence` | Too few distinct tasks/repeated samples, missing or unknown outcomes, an unusable baseline, or a model already approved elsewhere that needs separate policy-expansion review. |
| `shadow` | Predeclared coverage gates pass with known tests/scores and no observed regression; propose a human-reviewed shadow test only. |

Every observed scoped candidate test failure is reported, even when its
baseline cannot be paired. Missing evidence never proves success.

**`enable` is intentionally unsupported.** Every report has
`deployment_authorized: false`. A shadow recommendation does not execute a
model, change a live session, or prove statistical safety. There is no automatic
state transition or policy change.

A senior's acceptance of one task recommendation is not model approval or
pilot authorization. Future readiness must use linked actual outcomes and
remain category-specific; the designated senior/admin authorizes the first
pilot's policy/scope separately. The accepted eventual automatic-routing goal
does not change this tool's current limitations.

## Metrics and variation

The report compares the same paired samples for recorded no-change, current
policy, and candidate routes. It prints costs, tokens, latency, tests, scores,
and developer overrides without display rounding. Metric `task_count` counts
sampled outcomes; `scope_tasks` counts distinct engineering tasks.

- Known-test failure rates exclude unknown test outcomes from their denominator.
- Test regressions count a baseline pass becoming a candidate failure.
- Score regressions count negative paired score differences.
- Mean score change uses only pairs with known scores on both routes.
- Per-task sample counts, mean, minimum, and maximum score changes describe
  observed variation. They are **not confidence intervals** [statistical ranges
  intended to quantify uncertainty].
- The separate `uncertainty` section averages repeated runs within each task,
  then reports equal-task-weighted metrics and optional conservative quality
  intervals. Sampling assumptions default to unconfirmed; see
  [UNCERTAINTY.md](UNCERTAINTY.md).
- Every sample includes missing/compatibility flags and recorded quality data.

Repeated runs of one task are not additional distinct tasks. A simple
bounded-quality uncertainty baseline is implemented, but independence and
sampling design are caller-attested, not verified. Reviewed rollout thresholds,
independent design review, and benchmark validation remain pending.
Local policy snapshot and rollback metadata are
available in [POLICY_HISTORY.md](POLICY_HISTORY.md); they do not authorize live
deployment.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | A shadow-test proposal was produced; deployment is still unauthorized. |
| `1` | Reject or collect-more-evidence; the report is printed. |
| `2` | Invalid input, configuration, unregistered candidate, or file error. |

## Before live use

Remaining gates include real team evaluations, verified evidence and frozen
thresholds, broader privacy/secret handling, live audit capture, a reviewed approval process,
live policy rollback, and observe-only integration tests. Open-source
licensing is also unresolved before public code release. See
[TASKS.md](TASKS.md) for progress and [DEVELOPMENT.md](DEVELOPMENT.md) for the
replay input contract.
