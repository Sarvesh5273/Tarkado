# Experimental feedback learner

**B-05 update:** the company browser now publishes/reverses exact reviewed learner
artifacts for future manual browser/connector suggestions. Historical snapshots and
new feedback/gap vetoes remain, with no implicit pilot authorization. Conditional
selection mechanics require additional independent admission and are default-denying;
real OpenCode/provider delivery is not built. See
[INTEGRATED_LEARNING_SELECTION.md](INTEGRATED_LEARNING_SELECTION.md).

## What is implemented

Tarkado can fit a simple count-based recommendation model from linked local
feedback and apply it to future **manual** suggestions. It is a baseline [a
simple approach to compare later methods against], not a trained language
model, production confidence estimator, or automatic-routing policy.

The accepted [company workflow](WORKFLOW.md) is unchanged. A designated
senior/admin must authorize the first limited routing pilot. Nothing here makes
model requests, switches a session, or grants that approval.

## Continue after the feedback demo

If you already imported `feedback-demo.json`, fit from that existing store:

```sh
.venv/bin/python -m engine feedback learn \
  --store local/feedback-demo --policy tests/fixtures/policy.json \
  --plan tests/fixtures/learning-plan.json \
  --output local/feedback-learner-v1.json
```

The file is private and never overwritten. If it exists, inspect it or use a
new destination; do not delete unrelated user data to rerun the command.

The demonstration requirements are two senior adopted successes across two
senior sessions. **These are illustrative, caller-declared validation settings,
not approved production thresholds.** The fixture establishes no safety,
savings, or usefulness on real company tasks.

Apply the learner to a future documentation task:

```sh
.venv/bin/python -m engine feedback recommend tests/fixtures/learning-docs-task.json \
  --store local/feedback-demo --policy tests/fixtures/policy.json \
  --learner local/feedback-learner-v1.json
```

Expected: **suggest `fixture/cheap`, retain `fixture/premium` as the actual
selected model**, with low confidence and source references. The suggestion is
saved with its learner snapshot. Later response/execution/result commands use
the returned recommendation ID just like [ordinary feedback records](FEEDBACK.md).

Try the test-generation category:

```sh
.venv/bin/python -m engine feedback recommend tests/fixtures/learning-tests-task.json \
  --store local/feedback-demo --policy tests/fixtures/policy.json \
  --learner local/feedback-learner-v1.json
```

Expected: **suggest the premium fallback**, not the standard model. The junior
failure and senior rejection prevent learning that standard-model suggestion.
Failed/rejected evidence remains in the output. Unlike the static rule, this
decision uses recorded feedback—but still executes nothing.

Without `--learner`, `feedback recommend` retains static behavior. There is no
silently active learned policy or background retraining.

## Explicit learning plan

Plans require a learner version, declared source kind, validation split, cutoff,
explicit session/category scope, and positive minimum success/session counts.
See `tests/fixtures/learning-plan.json` for the complete format.

- `source_kind` is `synthetic` or `team`; a label is not proof of provenance.
- `dataset_split` must be `validation`. Fitting refuses `test` and does not tune
  settings from held-out test [final checking] data.
- Select scope/requirements on validation data and freeze them before held-out
  evaluation. Changing labels does not make test data validation data.
- `cutoff` is an ISO-8601 timestamp with timezone. Only source records at or
  before it enter fitting. Later results cannot become evidence for an earlier
  suggestion retroactively.
- Session/category lists prevent silent broadening. An absent declared session
  or one with no scoped records before the cutoff is an error.
- Real production weights and readiness thresholds are not finalized. Local
  experimental settings do not decide those product requirements.

The fitting view retains pending, rejected, mismatched-model, failed, and
corrected-result records in its declared scope. Only each execution's current
result as of the cutoff supplies outcome evidence; revisions remain visible.
Acceptance without actual use/success cannot increase success counts.

## Simple learning rule

For each declared task category:

1. Count senior-accepted, actually used, senior-confirmed desired-result
   successes, as defined by the [feedback baseline](FEEDBACK.md).
2. Require the caller's minimum senior successes and supporting sessions.
3. Withhold candidates with failures, rejections, incompatible executions, or
   executed tasks with unknown results.
4. Prioritize eligible candidates by senior successes, then supporting senior
   sessions, then total recorded successes, with model ID as a fixed tie-breaker.
   A candidate never wins merely because it is cheap.
5. Save a category-to-model suggestion or an explicit withheld category.

Accepted-but-unexecuted tasks and actual-model mismatches are visible but not
fabricated successes. Junior failures veto a candidate just as senior failures
do. This is conservative exploratory behavior, not a validated production
threshold or statistical guarantee.

## Source binding and freshness

The immutable file includes the plan, policy snapshot, roster/source
fingerprints, all fitting counts, grouped evidence, selected/withheld rules,
low confidence, and `deployment_authorized: false`.

Application checks actual source records, not only a claimed source hash.
Altered evidence counts cannot pass by reusing a fingerprint. The file is
nevertheless **not signed**: hashes cannot authenticate roles, outcomes,
evidence references, or an operator.

The additive schema-2 ledger projection used by company records retains historical
role attributions through validation-cutoff views and source fingerprints. A later
promotion cannot relabel old junior failures or fabricate senior adoption. Changing
an attribution makes the old source/learner stale. Schema-1 behavior stays unchanged.
This is role-attribution support, not automatic authentication of an imported
ledger or company learner activation. The authenticated manual company interface
still uses static suggestions for new tasks. Its category-review UI now fits the
existing learner from an explicit validation plan and stores evidence for
separate simulation authorization. B-02's live scope approval code additionally
requires a server-owned independent readiness assessment; the default denies it.
Future learned-suggestion application and real company evaluation integration
remain pending. See
[COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md).

The feedback store rechecks:

- the matching learner source/roster;
- new scoped responses/executions/results arriving after fitting;
- known category/model failures or rejections elsewhere in the same store, even
  if an explicit fitting subset excluded them;
- current policy/model approval and tools/context compatibility; and
- a future task in a session not used for fitting.

New evidence makes the old learner stale. **Refit explicitly** with a suitable
new cutoff, version, and declared validation scope rather than ignore it.
Inconsistent/stale sources block creating a new learned record. Historical
recommendations remain immutable; retrying an identical already stored record
does not reinterpret its old decision.

The new-session requirement guards against presenting fitted examples as
independent evaluation. It is not a finalized production-operation restriction.

High/unknown risk, unsupported categories, withheld rules, changed policy
content, or incompatible proposed models use the approved default recommendation.
If that default is incompatible, the recommendation is blocked. Every decision
remains shadow/manual, preserving the developer's actual selection.

## Remaining work

This implements fitting/application mechanics, not proof of better suggestions.
Unit scenarios compare behavior against static rules, not production performance.

Independent real-task validation of the algorithm/settings, outcome verification,
stronger task-context signals, learned manual-suggestion integration, verified
category readiness, and an approved real readiness-verifier integration remain
required before using the completed live-authorization mechanics. Company learner/review preparation and separately authenticated
simulation approval/runtime now work; their manual evidence is not production validation.
The manual company feedback loop now binds submitters and historical roles; that
does not independently verify outcomes or authenticate imported learner artifacts.
Local review
reports and designated simulation receipts are in
[READINESS_PILOT.md](READINESS_PILOT.md), without deployment approval. Live capture,
automatic selection, and monitored live rollback remain unfinished.

Public/synthetic results support no production-savings claim. See
[TASKS.md](TASKS.md) for verified progress.
