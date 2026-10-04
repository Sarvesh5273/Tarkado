# Category review and separate local pilot receipts

## Scope

**Company application update (2026-10-04):** the authenticated company interface
now stores category reviews and separate MFA-verified scoped simulation approvals,
then reuses the B-01 runtime for admission/accounting/control. Those authoritative
company records differ from the unsigned local receipts described below and
cannot enable live routing. B-02 now also implements positive conditional live
scope approval using a separate server-owned readiness assessment and designated
fresh-MFA human decision. The checker defaults to refusal; manual evidence alone
is not verified readiness and a scope record is not an execution ticket. See
[COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md).

Tarkado builds a category-specific evidence report and records a separate
designated senior/admin decision for a limited **local simulation** pilot.
This implements review-record mechanics from [WORKFLOW.md](WORKFLOW.md), not
authenticated company authorization or live routing.

- `ready_for_local_review` is not production readiness or verified safety.
- Per-task acceptance cannot produce a pilot receipt.
- A separately designated senior/admin must review the scope.
- Even approval keeps `routing_enabled: false` and `deployment_authorized: false`.
- Review receipts only declare limits: `limits_enforced: false`. The separate
  local runtime below checks task/budget reservations; no live provider cap is enforced.

## Continue from the learned feedback demo

Use the store and learner file you already created:

```sh
.venv/bin/python -m engine feedback readiness \
  --store local/feedback-demo --policy tests/fixtures/policy.json \
  --learner local/feedback-learner-v1.json --output local/category-review-v1.json
```

Expected: documentation is `ready_for_local_review` with `fixture/cheap`;
test generation is `blocked` with the junior failure and senior rejection.
Pending tasks, unanswered suggestions, and accepted-but-different-model cases
remain visible, including future recommendations you recorded. Observed scores,
costs, latency, and correction history are retained. No counterfactual [unused
model] results or savings are invented.

The example's learner requirements are not production thresholds. Passing local
review checks does not mean two successful tasks suffice to route company work.

Source/freshness/policy errors become explicit blockers. Reports bind the policy,
learner, and full current feedback fingerprints. A change to any input requires
a new report before a pilot decision is recorded.

## Separate designated approvers and limited scope

`tests/fixtures/pilot-approvers.json` declares senior/admin reviewer labels and
an explicit `can_approve_pilots` permission. It is separate from the developer
feedback roster. Seniority or task acceptance alone grants no pilot authority.
A designated admin need not be a task's developer.

This local allowlist **does not authenticate identity or authority**. Anyone with
permission to edit it can declare an approver. Receipts use
`reviewer_identity_source: declared_local_allowlist_unverified`. A future
company integration needs trusted identity/role checks before live activation.

The demo scope is:

```json
{
  "pilot_id": "synthetic-documentation-pilot-v1",
  "repository_ref": "synthetic-repository",
  "task_types": ["documentation"],
  "developer_ids": ["synthetic-senior", "synthetic-junior"],
  "max_tasks": 5,
  "max_cost_usd": "1.00"
}
```

Categories/developers must be explicit, without wildcards. Developers must be in
the collection roster, categories must appear in the exact report, and approval
cannot include a blocked category. Limits must be positive. These numbers and
repository reference are fictional examples, not real-company approval or
validated production defaults.

## Record a local approval or rejection

```sh
.venv/bin/python -m engine pilot review \
  --store local/feedback-demo --report local/category-review-v1.json \
  --policy tests/fixtures/policy.json --learner local/feedback-learner-v1.json \
  --scope tests/fixtures/pilot-scope.json \
  --approvers tests/fixtures/pilot-approvers.json --reviewer synthetic-senior \
  --decision approve --timestamp 2026-10-04T12:00:00Z \
  --reason "Review the synthetic documentation pilot only" \
  --local-simulation --output local/pilot-review-v1.json
```

The synthetic timestamp follows the example observation times. Review time
cannot precede the evidence it claims to review; real input needs an appropriate
explicit time. Local timestamps are caller-declared, not trusted clock proof.

The operation verifies the report against current feedback/policy/learner while
holding the feedback-store lock. Stale reports or blocked categories cannot be
approved. `--decision reject` may record a blocked category's rejection with no
granted routes. `--local-simulation` acknowledges that this cannot authorize
live deployment.

The receipt preserves the exact report, fingerprints, scope, designated reviewer
roster, decision/time/reason, and reviewed category/model mappings. Approval sets
`approved_for_local_simulation: true`; rejection has no route mappings or
simulation approval. Both keep live routing/deployment disabled and make no
claim that task/budget limits have been enforced.

Recording approval does not request a model, switch a session, approve an
unapproved provider, install a policy, or expand a scope.

## Storage and limitations

Reports/receipts are private, secret-checked JSON and never overwrite existing
files. Keep real metadata under Git-ignored `local/`. Readable task/reviewer
references are not anonymized/encrypted; retention remains manual.

Fingerprints detect inconsistent edits, not malicious rewriting or authenticated
authorship. A receipt alone has no active state or accounting. The local runtime
below adds state and reservations without live scope enforcement. Automatic
expiration, multi-host coordination, and real company authority remain pending.
A saved receipt is not proof that a pilot is authorized or running live.

Exit `0` means the report/receipt was validly created, not that every category is
ready or a model is safe. Invalid scope, unauthorized local reviewer, stale
evidence, corrupt content, or file errors return `2` without intentionally
replacing valid data.

## Local pilot runtime — implemented

The runtime uses one explicitly reviewed pilot per private store. It persists
activation, controls, decisions, reservations, and settlements in ordered event
history. It does not change the feedback ledger, send model requests, or
attribute simulated results to a real developer's task.

First create the local receipt using `pilot review` above. Then activate that
exact reviewed simulation:

```sh
.venv/bin/python -m engine pilot activate \
  --store local/feedback-demo --pilot-store local/pilot-runtime-demo \
  --receipt local/pilot-review-v1.json --learner local/feedback-learner-v1.json \
  --policy tests/fixtures/policy.json --approvers tests/fixtures/pilot-approvers.json \
  --reviewer synthetic-senior --timestamp 2026-10-04T12:01:00Z \
  --reason "Activate the reviewed local simulation only" --local-simulation
```

Activation rechecks the exact current report, feedback, learner, scope, and
declared approver roster. It cannot use a rejected receipt or silently replace
an existing pilot/restart its budget. An exact activation retry is idempotent
[does not repeat the operation], even after the pilot is revoked.

Reserve a simulated new task using the supplied fixture:

```sh
.venv/bin/python -m engine pilot decide tests/fixtures/pilot-request.json \
  --store local/feedback-demo --pilot-store local/pilot-runtime-demo \
  --policy tests/fixtures/policy.json --approvers tests/fixtures/pilot-approvers.json \
  --local-simulation
```

Expected: `simulation_admitted: true`, simulated model `fixture/cheap`, a
`0.10` budget reservation, and unchanged actual selection `fixture/premium`.
No model executes. Record the fictional cost separately:

```sh
.venv/bin/python -m engine pilot settle tests/fixtures/pilot-settlement.json \
  --pilot-store local/pilot-runtime-demo --local-simulation

.venv/bin/python -m engine pilot status --pilot-store local/pilot-runtime-demo
```

Expected after settlement: one admitted/settled task, `0.006` recorded cost,
zero outstanding reservation, `0.994` budget remaining, four task slots left,
and revision `3`. These are synthetic accounting records, not provider billing
or proof that task quality passed. The settlement's `completed` status is not a
verified engineering success or training label.

### Request contract

`pilot-request.json` supplies a decision ID, metadata-only task, repository
reference, boundary, maximum cost commitment, and optional override model.
Accepted boundaries are `new_task`, `new_run`, and `subagent`; a `continuation`
keeps the original compatible model and consumes no pilot reservation.

Admission requires active state, unchanged policy and current source/approval,
approved repository/category/developer scope, explicitly low risk, supported
tools/context, a known positive reservation, and available task/budget capacity.
The boundary and repository are caller-declared, not detected from OpenCode;
real boundary/repository authority belongs to the future adapter.

Inside scope, an explicit compatible approved `override_model` wins. Unknown or
incompatible overrides, unsafe/out-of-scope tasks, unknown costs, exhausted
limits, and inactive pilots fall back without consuming a reservation. They do
not authorize a fallback API call outside the pilot. If the safe model is also
incompatible, the decision is blocked. Real manual selection is unchanged in
every case.

An exact decision retry returns `historical_replay: true`,
`simulation_admitted: false`, and `new_reservation: false`. The archived result
is not fresh permission to execute or reserve again—even after revocation.
Reusing a task/session or decision ID with changed content is refused.

### Budget and settlement

Admission checks `spent + outstanding reservations + requested commitment`
against the reviewed cap. It checks all pending tasks under the same local
lock, so concurrent admissions cannot each claim the same remaining money.
Unknown commitments do not become zero-cost tasks.

Settlement replaces the pending reservation with its recorded actual cost.
Unused money becomes available, but admitted tasks consume their lifetime task
slot even if cancelled. Cancellation before execution requires zero cost.
Failed tasks or costs incurred before cancellation must be recorded as such,
not hidden by refunding the reservation.

If cost exceeds the commitment, **record it fully and pause the pilot**. Negative
remaining budget is printed, not clipped or hidden. A recorded failure also
pauses the pilot. Those failures/overruns require a new reviewed pilot rather
than resuming unchanged approval. No commitment checks guarantee that a real
provider honors a cost cap; the runtime has no provider transport.

Settlements may arrive after pause/revoke/rollback to preserve outstanding
costs; they never reactivate a stopped pilot. Exact retries do not double charge.
Changed costs under an existing settlement are refused in this baseline;
audited cost corrections remain future work.

### State controls and default-only rollback

Controls require a designated local reviewer, reason/time, and expected current
revision [the state version you reviewed]. Read `pilot status` first; stale
controls are refused instead of overwriting newer decisions.

After the demonstration above, roll back to default-only behavior:

```sh
.venv/bin/python -m engine pilot rollback \
  --pilot-store local/pilot-runtime-demo --expected-revision 3 \
  --approvers tests/fixtures/pilot-approvers.json --reviewer synthetic-senior \
  --timestamp 2026-10-04T14:00:00Z --reason "End the local pilot; default only" \
  --local-simulation
```

The example revision assumes exactly the three successful operations above.
Additional decisions/controls change it. Rollback marks the pilot `rolled_back`,
preserves all history/reservations/costs, and prevents future pilot selection.
This is **default-only rollback**, not restoration of a previous live deployment.

`pause`, `resume`, and `revoke` use the same reviewer/time/revision arguments.
Resume additionally requires current `--store` feedback and `--policy` checks.
Only paused pilots can resume; revoked/rolled-back pilots cannot be revived.
New source feedback, changed policy/approver scope, or recorded failure/overrun
requires explicit refitting/review rather than continuing stale approval.

The baseline requires nondecreasing source event timestamps. Out-of-order
settlement ingestion and richer time/clock reconciliation remain future work;
do not fake timestamps to bypass event ordering.

### Persistence and boundaries

The private local JSON journal is replay-validated: current state and accounting
are derived from its events, not editable counters. Interrupted writes preserve
the previous file; malformed state is rejected, never reset automatically.
New stores/files use `0700`/`0600` permissions. Root/state/lock symlinks are
refused. Retention is manual; this is not a backup or a tamper-proof ledger.

There is one pilot per store. A fresh store does not constitute fresh company
approval; multi-store/multi-host duplicate-ID coordination is not implemented.
Unknown failures, source/approval mismatch, or policy changes use safe fallback,
and source/approval/policy changes pause an active simulation on the next check.

B-01's local runtime is implemented. Company setup/identity, category review,
authenticated simulation approval and joined local controls are now implemented.
B-02 authorization mechanics, including the positive conditional live scope
boundary, are complete. The remaining B-03 interface, approved real readiness
verifier, task-level adapter, joined learning/live selection, retention, and real operational
validation remain unfinished. Real routing still
requires approved data/evidence and authenticated senior/admin authorization.
