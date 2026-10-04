# Continuous pilot feedback — narrow routine progress

**Owner-approved direction:** 2026-10-04. **Build status:** narrow conditional routine-
progress software implemented and regression-tested; no installed/live-use claim. Existing
OpenCode V2 → LiteLLM Proxy → company-managed OpenAI API path; no new gateway,
tool runner, model call or automatic learning.

## Three separate states

1. **Reviewed basis:** exact policy, learner/fixed-cutoff evidence, independent
   readiness assessment and designated human approval. These remain immutable.
2. **Incoming feedback:** authenticated per-task response, actual-model report,
   initial result and correction, preserving each actor's historical role. Human
   reports are not independently verified engineering outcomes. The next learning
   review needs an explicit new validation plan/cutoff/version and separate review.
3. **Execution safety:** current scope/model/budget/authority, paid obligations and
   retained negative/unknown/gap/mismatch/override/corrected evidence. Pending learning
   freshness alone is not execution authority or an automatic stop/resume command.

The prior acceptance-only path made a healthy closed task's matching model report
block the pilot guard, then a first positive human result pause it. The owner chose
**Routine progress** over an explicit-review-only path preserving those stops.
Controlled reproduction showed `active/current` before reports, `active/blocked`
after matching model use and `paused/blocked` after the first positive result, while
spent remained `0.002` USD and pilot remaining `0.998` USD. No real provider was called.

## Narrow conditional exception

Timely acceptance on a new recommendation retains the existing behavior. The new
routine path additionally checks matching model reports and first positive human
results against the exact current pilot's already-bound delivery, never a submitted
task ID or model label alone:

- New recommendation after the reviewed observation boundary, not a fitting or
  previously reviewed task; same approved company/repository/category/developer scope.
- Exact owned task/selection/one-use claim/binding from this approval; no developer
  override or changed model. A manual recommendation is not the actual bound model.
- Explicit owner close, complete known matching primary and auxiliary attempts,
  no provider failures/retries, unknown obligations, invoice corrections or overruns.
  Evidence must already exist before the report, not be fabricated retroactively.
- No connector gaps/errors/multiple-model inconsistency or pending/negative tool
  signals. Tool completion still cannot become tests-passed or final task success.
- Exact bound actual-model report. A first positive human result has known desired
  result and no test failure; optional unknown test measurements stay visibly unknown.
  A conflicting human cost report cannot override authoritative delivery accounting.

A missing per-task response remains unknown, rather than being invented as acceptance.
Actual-model reporting matches the **approved bound model**, not a potentially stale
manual-suggestion publication. Explicit developer overrides still require review. The
manual feedback ledger retains any difference from its suggested model and does not
count that as adoption of the suggestion. An unchanged approved pilot choice differing
from a stale manual-suggestion fallback is not permission to override the bound model;
only the exact approved binding may qualify for routine progress.
The model report itself does not require a human result yet: the pilot view shows that
result as pending. A subsequently submitted explicit unknown/negative result blocks;
no missing result is counted as success or assigned an invented expiry threshold.

Qualifying feedback is retained for explicit future learning without changing the
current approved basis. It is **not verified success**, new readiness evidence,
another claim, expanded scope or a new model binding. Unknown/negative results,
overrides, missing evidence, result revisions and altered reviewed observations still
block. Another developer's negatives cannot be hidden by routine progress. A stopped
pilot never resumes automatically. Closed work stays closed and lifetime costs/slots/
claims remain consumed. Known-cost corrections retain their separate verified workflow.

Intermediate-tool repair rules are unchanged: exact-bound repair alone may continue
after a retained intermediate error/test failure; refusal/interruption/missing results
and gaps still forbid paid continuation. A repaired human-success report does not
erase intermediate failures or exempt new automatic tasks from their existing veto.

## Review and operating boundaries

The existing authenticated task/browser/connector paths retain incoming feedback.
Model reports now trigger the same immediate monitoring as responses/results, instead
of leaving a blocked guard behind an apparently active runtime. The pilot view shows
linked senior-prioritized incoming records and separate
routine-progress, review-required and missing-model/result states. These are readable
projections of existing event history, not a new permission or mutable outcome label.
All participating developers' relevant approved records remain visible; senior priority
does not discard junior failures, missing outcomes or overrides.

Open **Pilots → Conditional selection/accounting → Incoming pilot feedback** to inspect
record kind, exact ID/fingerprint, receive time, historical role, classification/reason
and linked task history. **Still awaiting human linkage** distinguishes missing model
reports from pending eventual results. **Prepare a new explicit validation/learning
review** reuses the existing reviewed plan/version/source/authority forms. Classification
is computed from validated history, not a mutable success flag or editable queue.
No database migration or owner-store change is required.
These are **current** safety/learning-review projections. Later corrections may make
earlier feedback require review now; neither an old feedback event nor an earlier
selection decision is overwritten or relabeled as having known the future evidence.

The original approval's evidence, learner, scope, prices, thresholds and source hashes
are never replaced to make new reports fit. Its readiness verifier still rechecks the
exact original request. A bare evidence review, another pilot's binding, API reference
or caller-declared role cannot establish this exception. Billing corrections retain
current totals but never silently become routine feedback or erase their old evidence.

Learning/publication freshness remains strict. Fitting, publication and any different
pilot scope require the existing explicit review/authority gates. No background refit,
automatic threshold change, replacement hash, self-approved pilot or external provider
experiment is introduced. First human approval and default-denying verifiers remain.

## Verification boundary

Recovered baseline: **838 Python / 47 JavaScript tests pass** on unchanged source.
**Final verification: 880 Python / 47 JavaScript tests pass**, retaining the 838 Python
baseline with 42 new focused feedback regressions. The 42 new tests, 20 acceptance
regressions and 24 tool-status regressions also pass separately. Existing assertions
are unchanged and `git diff --check` passes. Source stayed fixed during full tests.
Python also invokes JS, so counts are not independent certifications. History and
remaining work are tracked in `docs/TASKS.md`.
Use controlled evidence/provider responses and new temporary stores only. No new
dependencies/plugins, private-session/store access, owner-store changes, real calls,
activation or public push. Counts do not prove production readiness or useful learning.

External notifications/supervision, direct provider-stream/lost-delivery recovery,
automatic subagent/new-run attribution, finer native tool/provider attribution, broader
shell/remote/non-text/extra-charge support and positive company-specific real verifier
implementations remain separate software. Actual installed-host/approved real evidence/
private data/deployment validation remains separately deferred. Code stays local and
unpublished pending licence selection.

Strict learner publication remains manual/reviewed; broader feedback adaptation,
cross-reviewer disagreements and revised-result resolution are not implemented by this
exception. The controlled next-task flow records `0.002` USD for the first task, retains
`0.998` USD pilot remaining and reserves a separate `0.04` USD before the next model
attempt. Two separately completed controlled tasks total `0.004` USD, with `0.996` USD
remaining. These are complete synthetic accounting values, not real costs/savings or
quality evidence. A pending next task holds its original `0.10` USD allowance: spent
`0.002`, reserved `0.10`, committed `0.102`, remaining `0.898` USD, one remaining
lifetime task slot. Reporting success does not refund that reservation or restore slots.
