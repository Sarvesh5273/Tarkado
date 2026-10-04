# Independent-task uncertainty reporting

## Scope

Candidate reports now include task-weighted estimates and optional conservative
confidence intervals [ranges intended to cover an expected mean under stated
sampling assumptions]. This is independent of OpenCode session access and
requires no API calls, extra packages, or live routing.

Reporting uncertainty does **not** approve a model. It does not relax the
per-sample failure/override checks or change rollout recommendations. Every
report still has `deployment_authorized: false`.

The accepted product workflow is in [WORKFLOW.md](WORKFLOW.md). Local per-task
responses and actual outcomes are implemented in [FEEDBACK.md](FEEDBACK.md);
experimental senior-prioritized fitting/application is described in
[LEARNING.md](LEARNING.md), with independent production validation still pending.
Equal task weighting in this offline statistical report is **not** a chosen
senior-feedback learning weight or an implemented role-aware learner. Exact
feedback weights/evidence gates remain undecided. A narrow interval cannot
replace the designated senior/admin's first-pilot authorization.

## Existing plans continue to work

The existing evaluation command automatically includes an `uncertainty` section:

```sh
.venv/bin/python -m engine evaluate tests/fixtures/rollout.jsonl \
  --policy tests/fixtures/rollout-policy.json \
  --candidate fixture/candidate --plan tests/fixtures/rollout-plan.json
```

Old plans default to unconfirmed sampling assumptions. Task means/ranges and
sample standard deviations are printed, but inferential intervals are withheld.

To inspect the mathematical demonstration:

```sh
.venv/bin/python -m engine evaluate tests/fixtures/rollout.jsonl \
  --policy tests/fixtures/rollout-policy.json \
  --candidate fixture/candidate --plan tests/fixtures/uncertainty-plan.json
```

The demonstration is **synthetic**, still returns **REJECT** (exit `1`), and does
not verify a real sampling design. Its three tasks yield broad quality ranges,
not evidence that a production model is safe.

## Predeclare assumptions and confidence

An evaluation plan may add:

```json
"uncertainty": {
  "confidence_level": "0.95",
  "independent_tasks_attested": true,
  "fixed_sampling_attested": true
}
```

All three fields are required if this object is provided. Confidence must be
between `0.5` and `0.999`. Omission defaults to `0.95` with both attestations
false. An **attestation** [the evaluator's explicit statement] is not verified
by Tarkado.

- Independence means the task-level measurements are independent units of the
  evaluation design. Rephrased copies of one bug, overlapping incidents, or
  task outcomes influenced by shared adaptive state may not qualify.
- Fixed sampling means task selection, per-task run counts, model/policy,
  metric definitions, scope, and stopping rule were fixed independently of the
  observed outcomes. Retrying until a model passes is not fixed sampling.
- Distinct IDs alone cannot establish either assumption.
- Choose scope/confidence/gates on validation data and freeze the plan before
  a held-out test [data reserved for final checking]. Do not change them after
  inspecting test outcomes to obtain a favorable report.

Tarkado does not tune the settings or authenticate the dataset split. There is
no repeated-testing or data-dependent-stopping guarantee.

## Repeated runs are grouped inside tasks

For each metric, the report first averages paired changes within each task,
then gives every included task equal weight. Tasks with many recorded runs do
not outweigh tasks with fewer runs or increase the independent-task count.

This differs from the main report's pooled totals, which count each paired
sample. Both views are printed with their units; neither is silently substituted
for the other.

Every recorded sample of a task must be paired and known for the relevant
metric. Otherwise the **entire task** is excluded from that metric's descriptive
summary and its task/sample exclusion counts are shown. The report does not
keep only easy or successful runs.

Intervals are withheld if any scoped task is excluded for the metric. Unknown
scores need not hide known tests/costs: coverage is checked separately for each
metric. Entirely absent tasks/runs cannot be discovered from the file; collecting
the complete predeclared evaluation is the team's responsibility.

## Canonical metric order and signs

| Metric | Change and interpretation |
| --- | --- |
| `score_change` | Candidate score minus baseline; positive is better. |
| `test_pass_change` | Candidate pass indicator minus baseline; positive is better. |
| `developer_override_change` | Candidate override indicator minus baseline; positive means more overrides. |
| `cost_reduction_usd` | Baseline cost minus candidate cost; positive is cheaper. |
| `latency_change_ms` | Candidate latency minus baseline latency; negative is faster. |

Each metric prints complete/excluded distinct tasks, included/excluded samples,
task-weighted mean, min/max task means, sample standard deviation across task
means, interval status, and the interval when available. No output display
rounding is applied. This module uses fixed 50-digit decimal precision; ordinary
replay totals continue to use their documented decimal precision.

Observed min/max and standard deviation are **descriptive**. Zero observed
spread is not certainty: the bounded-quality confidence radius remains nonzero.

## Simple bounded-quality baseline

Scores are constrained to `[0, 1]`, and tests/overrides are boolean indicators.
Their paired differences, including within-task averages, lie in `[-1, 1]`.
This lets us use the simple two-sided Hoeffding bound:

```text
alpha  = 1 - confidence_level
n      = number of complete distinct tasks
radius = 2 × sqrt(ln(2 / alpha) / (2 × n))
interval = [max(-1, task_mean - radius), min(1, task_mean + radius)]
```

The factor `2` is the width of `[-1, 1]`. The two tails use a union bound [sum
their probability bounds]. At least two complete distinct tasks are required by
this implementation; that minimum is not a statistical sufficiency claim.

This formula follows Hoeffding's 1963 **Theorem 2**, equation (2.6), combined
with the two-sided relation (1.4):

- [Original paper, university-hosted PDF](https://www.csee.umbc.edu/~lomonaco/f08/643/hwk643/Hoeffding.pdf)
- Wassily Hoeffding, *Probability Inequalities for Sums of Bounded Random
  Variables*, Journal of the American Statistical Association 58(301), 13–30.
  [DOI](https://doi.org/10.1080/01621459.1963.10500830)

The original paper was checked for this baseline. This is an existing method,
not a novelty claim. It avoids assuming normally distributed errors or treating
individual repeated runs as independent tasks. Tighter methods remain future
work and must be compared against this baseline on the same evaluation design.

The interval concerns the expected equal-task-weighted mean under the attested
independent, fixed design. It is **not** a prediction interval for each future
task. Population generalization additionally needs a justified representative
sampling design; neither synthetic fixtures nor caller labels establish that.

Intervals are **pointwise** [for one stated metric/evaluation]. They do not
provide a simultaneous guarantee across metrics, candidate models, multiple
task scopes, or repeated looks at results. No automatic decision threshold or
multi-comparison correction is inferred.

## When intervals are unavailable

| Status | Meaning |
| --- | --- |
| `no_complete_tasks` | No whole tasks have complete paired values for this metric. |
| `incomplete_task_coverage` | At least one scoped task lacks complete values. Descriptive included-task results are not a whole-scope inference. |
| `too_few_distinct_tasks` | Only one complete distinct task; repeated runs do not repair this. |
| `sampling_assumptions_unconfirmed` | Independence or fixed sampling has not been attested. |
| `no_declared_hard_bounds` | Cost/latency changes lack justified finite bounds, so only descriptive statistics are supplied. |
| `available_under_attested_assumptions` | A pointwise bounded-mean interval is calculated; assumptions and provenance are still not verified. |

The observed cost/latency range is **not a hard bound** on future evaluations.
We do not turn that range into a confidence interval or claim savings certainty.

## Tests and remaining work

Tests check the independent two-tail formula, logical endpoints, wider intervals
at higher confidence, reduced radius with more distinct tasks, no artificial
shrinkage from duplicated runs, equal task weighting with uneven repeats,
missing/unknown data, canonical order, and unchanged reject/approval behavior.

The normality-free bound is intentionally conservative, especially for small
datasets. It cannot fix mislabeled scores, duplicate tasks with different IDs,
unrepresentative sampling, missing runs, or correlated tasks. Independent
evaluation design review, benchmark validation, authenticated approval, and real
team outcomes remain required before deployment.
