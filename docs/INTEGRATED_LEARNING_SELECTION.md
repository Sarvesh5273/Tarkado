# B-05 integrated learning and conditional scoped selection

**Updated:** 2026-10-04. **Build status:** versioned learner publication, historical
learned suggestions, connector feedback/freshness, conditional scoped selection/
reservation/claim/settlement, human controls, and adverse/concurrency tests are
implemented. **The complete live automatic-selection delivery loop is not built**:
OpenCode's observer has no verified atomic new-task/model/provider-cap admission
adapter. No live `switchModel` shortcut is installed to pretend otherwise.

The owner deferred installed-client, real-session/company evidence, and deployment
checks while building. They did **not** remove regression tests, privacy, trusted
human approval, source validation, safe fallback, or provider-cap enforcement.
No Laya, dependencies, model/provider calls, private sessions, commits, or pushes.

## Joined company learning

1. Record approved tasks, one-task responses, reported actual-model use, and
   known/unknown eventual results using the existing browser/connector. Existing
   historical actor roles, corrections, failures, rejects, and overrides remain.
2. Prepare an explicit validation-plan category review. This reuses the existing
   count baseline; numeric thresholds/weights are experimental, not inferred from
   production or selected on held-out tests.
3. Open **Review learner publication for future manual suggestions**. A permitted
   administrator or designated senior/admin reviewer separately confirms the exact
   artifact/source/repository scope with current primary MFA and fresh password/code.
   Publication is **not** pilot approval, model approval, or automatic execution.
4. New matching browser and explicit connector tasks use that exact published
   artifact, with low explanatory confidence, preserving the original selected model.
   Future pending recommendations alone do not invalidate the frozen fitting view.
5. New category feedback/results, source/publisher/MFA/policy changes, and connector
   gaps/errors/multiple-model evidence block future learned suggestions. A task is
   still recordable using a saved approved fallback refusal; unknown compatibility
   blocks the recommendation. No hidden retraining or fabricated outcomes.
6. **Default-only** publication reversal appends history and restores the static/
   default baseline for future tasks. Old learned recommendations, exact snapshots,
   publication bindings, record IDs, and retries remain immutable.

`LearningPublication` records immutable ordered artifact/repository/source/actor/
MFA/reason/company bindings. `CompanyTask.learning_snapshot` and
`suggestion_context` store the exact historical basis. The engine adds an optional
`suggestion_refusal` field only when a saved unavailable-learner fallback needs
reconstruction; unchanged schema-1/schema-2 records serialize exactly as before.

Conflicting learner version labels cannot be published as the same artifact.
Synthetic and team sources stay separate. Declaring team does not verify outcome
truth, readiness, cost savings, or the learner's accuracy.

## Separate live scope remains required

Category readiness and learner publication cannot authorize selection. Existing
B-02 live-scope decisions still require an independently checked `ReadinessVerifier`
assessment and a designated human's fresh password/MFA. Default shipped readiness
is unconfigured/refusing. Synthetic evidence and local simulation receipts remain
unable to grant live scope.

After such a conditional live-scope decision exists, the **Conditional selection/
accounting controls** page separately activates a scoped selection runtime. Its
controls preview exact scope/revision/reason and require fresh password/MFA.
One active/paused selection runtime per company; activation cannot reset history.
Pause, eligible resume, revoke, and default-only withdrawal preserve accounting.

This runtime is **not** the B-01 simulation journal. B-01/B-02 simulations are
unchanged and cannot be converted into live execution evidence. The conditional
runtime must handle live-scope records, which B-01 deliberately refuses; it
reuses existing compatibility, exact decimal accounting, company transactions,
historical roles, and approval checks rather than introducing model transport.

## Admission interface — default deny, not an installable test shortcut

`engine/company/admission_gate.py` provides a server-owned `AdmissionVerifier`.
The server constructs an `AdmissionRequest` containing exact company/deployment/
live-scope fingerprint, task metadata, selection-request digest, selected model,
and cost commitment. A real adapter must independently check:

- A genuine **new task**, not an active continuation or inferred idle event.
- Current employee/owner/repository/task scope.
- Atomic model binding [bind exactly this selection to this new task, not a
  mutable shared live-session setting].
- Provider-cap enforcement and approved deployment.
- Current, short-lived, immutable boundary assessment tied to the exact request.

Typed `AdmissionAssessment` must confirm all five requirements and current
validity. Unknown/untyped/outage/wrong-bound/expired/changed results are refused.
`TARKADO_ADMISSION_VERIFIER` is installed only by trusted application code; both
shipped launchers configure it as `None`. No browser/JSON/CLI checkbox installs
one. The controlled positive verifier is defined **only in tests**.

The existing observation credential and terminal plugin **do not satisfy this
gate**. Per-request token counts, session-cost differences, model hooks, and a
generic `switchModel` call do not establish atomic bounded delivery. B-05 retains
that missing implementation explicitly; it is not merely a postponed test.

## Conditional selection/accounting contract

`engine/company/selection.py` implements:

1. **Select/reserve:** recheck live readiness/authority/current policy, explicit
   category/developer/repository/risk/compatibility, optional approved override,
   known positive commitment, and lifetime task/budget capacity. Serialize evidence
   checks and reservation in the existing SQLite writer transaction. For connector
   API input, the exact owned linked task must have no previous model activity/close.
2. **Default/block:** invalid scope/state/evidence or exhausted limits returns an
   approved compatible fallback diagnostic, without reservation or permission to
   send a fallback request. Incompatible default returns blocked, not a guess.
3. **Trusted proof:** require the independent admission assessment, recheck current
   scope after verification, and append the exact selected model/request/assessment/
   policy/override/reservation/link bindings. A task/boundary cannot be reserved
   again, including under another pilot. Exact retries are historical and cannot
   reserve, bind, claim, or send anything again.
4. **One-use claim:** recheck current scope, boundary assessment, active runtime,
   task owner, and no prior observed task activity. Exactly one new claim may consume
   that selection. The return is the exact model/cap for a **trusted** adapter, not
   proof a provider request was sent. Historical claims give no new claim.
5. **Descriptor binding seam:** `integrations/opencode/src/boundary-selection.mjs`
   requires a separately trusted adapter to inspect/bind a fixed task descriptor.
   It validates the whole returned request and matching one-use claim. Its default
   adapter throws; the observer entrypoint does not register this path. `bind` must
   not prompt a model or mutate an already-running session.
6. **Settle:** record the complete incurred cost plus completed/failed/cancelled
   accounting status, preserving overruns/negative remaining budgets and lifetime
   slots. Completion requires a claim; cancellation before delivery requires zero
   cost. Failed/incurred costs are never erased by a refund. Exact retries do not
   charge twice. Settlement is not an engineering quality/result label.
7. **Monitor/control:** linked HTTP errors, gaps, multiple primary models, and later
   stale category feedback pause future selection and retain immutable history.
   In-flight models are never switched. Failures/overruns cannot resume unchanged
   approval. Revoke/rollback withdraws live scope and preserves pending settlement.

The bearer-only API adds `conditional-select`, `conditional-claim`, and
`conditional-settle`. They retain B-04 ownership/repository/permission/privacy
checks; team scope and server-owned admission are required. The observer's public
status reports `conditional_selection_available: false`. No live route or provider
request is enabled by selecting a model, activation, claim, learned publication,
or passing synthetic tests. A real trusted adapter/provider integration must own
actual capped delivery and current claim consumption before this becomes live use.

## Frozen source versus current feedback

Ordinary B-02 scope/readiness checks remain exact/full-source by default. Only
the conditional runtime uses the opt-in frozen-validation view: existing reviewed
task observations must remain identical; future pending recommendations may be
added; new feedback/results and new connector negatives/gaps still veto through
the existing learner/source checks. The exact original review hash is retained,
not replaced with a freshly favorable report. A new source requires refit/review,
never silent threshold tuning or first-pilot self-approval.

The current learner conservatively stales on any new category feedback after its
cutoff. Continuous adaptation and independently validated production criteria are
not claimed; explicit refit/new review is required. This is a simple baseline,
not proof of superior model choice or production savings.

## Installation/state preservation

Migration `0007_learning_selection` only adds task snapshot fields, publication
history, and the conditional runtime table. It does not replace accounts, task
events, policy/model registry, MFA/recovery, connector observations, old feedback
JSON, simulation journals, or private keys. It is applied only to temporary test
stores during this build; no owner installation is upgraded automatically.

For an existing installation later: stop the server, preserve a matching private
backup, run the existing `.venv/bin/python -m engine company upgrade --store ...`
on the same store, then restart. Do not rebootstrap, reset, or configure the
controlled verifier to make the demo appear live.

## Verification and remaining work

Tests cover publication → browser/connector future learned suggestions → negative
feedback → explicit refit/reversal, immutable historical snapshots, source/version
and permissions/MFA integrity; conditional live scope → activation → proof-bound
selection → one-use claim → complete settlement → monitoring/withdrawal; malformed
proofs/routes, costs/limits, stale state, exact retries, and concurrent reservations/
claims. JavaScript tests cover unsupported-adapter refusal and controlled task-
descriptor binding without calling a model or live OpenCode.

Latest verification: **671 Python tests pass** (637 retained baseline + 34 B-05
checks) and **19 JavaScript tests pass**. The Python suite also runs the JavaScript
suite; counts are regression checks, not independent evidence/security certificates.
`git diff --check` passes.

No existing assertion is weakened/removed. An initial background test run collided
with a newly added migration while old models were loaded; it was stopped at failure,
investigated, and rerun against consistent code/schema without any store reset or
assertion change. Subsequent full verification passes; see [TASKS.md](TASKS.md).

**Remaining software, not merely deferred validation:** a supported real OpenCode/
gateway new-task descriptor/model/cap binding adapter and exact provider delivery/
settlement integration. Rich per-attempt/multi-model positive-quality attribution
also remains unsupported; negative/unknown observation/history is retained.
Installed-client, approved real-session/evidence/criteria/deployment checks are
separately deferred. B-06 retention/operational delivery and B-07 stable external
policy handoff are still separate packages. B-05 is a conditional build milestone,
not the completed live automatic-routing product.

**2026-10-04 feasibility/commit review:** testing is required before live automatic
use, but existing tests cannot supply the missing delivery contract. The checked
official V2 [plugin hooks](https://opencode.ai/v2/docs/build/plugins/) and
[model selection guide](https://opencode.ai/v2/docs/models/) document request hooks,
explicit per-run model choice, and session switching—not an independently enforced
company per-task dollar budget. A concrete company-managed gateway/provider
admission and cap-enforcement design must be selected and tested before completing
the delivery adapter. No undocumented path, shared live-session switch, or
optimistic `provider_cap_enforced` assertion is substituted.

The owner authorized logical local commit batches, then selected **Keep code
unpublished** because the remote is public and the licence is unresolved. No
implementation push is authorized until the licence choice is made. This changes
the earlier no-commit constraint only; all data/access/execution limits remain.
