# Auditable known delivery-cost corrections

**Updated:** 2026-10-04. Conditional software on the existing OpenCode V2 → LiteLLM
Proxy → company-managed OpenAI API path. No gateway, tool runner, plugin installation,
provider request or live activation is added.

## Authority and independent evidence

The original `settle` operation still refuses a changed known settlement. Unknown
costs retain their original independent reconciliation path and cannot use corrections
until they have a complete known settlement.

Correction review/apply reuse two existing authorities:

- A **currently authenticated scoped gateway machine identity**, with the exact
  historical company, gateway identity, repository and developer/user mapping.
  Renewed credentials with the same mapping may reconcile historical attempts;
  expired/revoked credentials cannot mutate or replay correction receipts.
- A **current administrator with `can_manage_company`**, through protected company
  operating controls. Review requires current authenticator proof; confirmation
  additionally requires fresh password and unused authenticator verification.
  Developer access, a senior title or pilot-approval permission alone is insufficient.

No new permission is introduced. Administrative correction is narrowly independently
verified billing, not prohibited manual settlement/refund of bound delivery. The
historical gateway stays the accounting binding; the actual human actor is recorded
separately. Administrators need not reactivate/reissue revoked delivery credentials
to correct incurred costs. Neither authority establishes billing truth by itself.

Both paths invoke the same server-owned `BillingVerifier`, which must consult actual
independent provider/accounting evidence, exact task/request/physical-attempt ownership,
company/account identity and current authoritative invoice revision. Submitted amounts,
reference strings, checkboxes and client hashes cannot establish billing truth. No
positive real-world verifier is supplied or installed.

`BillingAssessment` retains its original fields, in order:

```text
request_sha256, evidence_ref, verifier_id, verified_at, valid_until
```

It optionally adds `evidence_sha256`, the fingerprint of evidence actually checked.
This is **required for corrections**, not retroactively for old unknown-cost records.
Applying a reviewed correction checks the evidence again. Request, evidence reference/
content, verifier and validity must match; changed evidence under the same reference
requires a new review. A fingerprint checks consistency, not invoice truth/authorship.

## Guided workflow

1. In **Monitoring → linked task**, open **Review a known cost correction**.
2. Select the labeled request/physical attempt. Enter its **complete corrected total
   USD cost**, not a difference/additional charge, and a metadata-only evidence
   reference. Never paste invoice bodies, prompts, code, outputs or credentials.
3. Review independent evidence, previous/new cost and revision, all task obligations,
   and current/proposed complete pilot totals. Negative budgets remain visible.
4. Confirm that exact signed review with fresh password/authenticator verification.
   Changed form content, billing evidence, delivery history or pilot revision is
   refused; reload/review rather than overriding stale history.
5. Read **Verified cost correction history** on the task: original settlement/usage/
   outcome and each correction's evidence, actual actor, receive time and revision.

Selectors/signatures are usability/safety controls, not billing truth. The terminal's
existing task view receives the same current validated cost projection; no new in-tool
permission, prompt command or model/tool execution is added.

The machine API provides the same two stages:

```text
POST /api/delivery/v1/review-cost/
POST /api/delivery/v1/correct-cost/
```

Both use the existing scoped bearer credential, refuse browser sessions/Origin headers,
connector credentials and extra/raw fields. Review accepts these canonical fields:

```text
binding_ref, correction_id, attempt_id, request_id, expected_revision,
supersedes_sha256, cost_usd, evidence_ref
```

`expected_revision` is the delivery-journal sequence; `supersedes_sha256` is the exact
attempt's current known settlement/correction fingerprint. Apply additionally requires
the reviewed `expected_assessment`. The verifier checks it again; fabricating it cannot
install/bypass a verifier. Review is read-only; apply returns a receipt, not execution.

## History, totals and non-reactivation

`correct_cost` links the exact binding/task/selection, request and physical attempt.
It retains correction ID, prior delivery/pilot revisions, previous/new total cost,
prior cost-head fingerprint, next cost revision, historical actor and independent
assessment. Its verification request also binds original settlement, previous corrections,
owner, envelope and logical request. Only the derived current cost changes; original
usage, latency, model, outcome and evidence are never overwritten.

Delivery and selection append in one existing serialized company transaction. Failed
appends roll back both. Concurrent corrections cannot lose a revision or double-charge.
Exact correction-ID retries return their historical receipt and current totals, even
after later corrections, without fresh verification or another charge. Changed retry
content/actor and stale/branched heads are refused. A separately verified same-amount
revision can record new evidence without adding its amount again.

Amounts are nonnegative exact decimal strings, including zero/tiny values, never binary
floats or currency rounding. Current totals include other tasks and unknown obligations.
Selection replay checks the original delivery-journal prefix, not today's revised total;
legacy settlements remain readable. New accounting binds exact delivery revision/hash.
Historical proof validity is checked at ingestion, not against today's verifier/expiry.
Old journal events are never edited. Private journals are not encrypted/tamper-proof.
No database migration is needed: existing binding/selection journal fields retain their
original events and append the new correction records. No owner store was upgraded.

Individual-attempt **and cumulative task** overruns remain visible after decreases.
Failure, unknown-cost, mismatch and tool-gap evidence stays in review. Unchanged resume
cannot erase retained failures/overruns. Authorized late corrections after owner close,
pilot pause/revocation/default-only withdrawal or collection pause never reopen execution,
auto-resume pilots, restore consumed slots, reset lifetime limits, refund claims, switch
models or fabricate human outcomes/learner success. Intermediate-tool repair rules and
feedback exemptions are unchanged; changed reviewed evidence retains existing vetoes.

## Verification and separate gaps

```sh
.venv/bin/python -m unittest discover -s tests -p test_billing_corrections.py -v
node --test integrations/opencode/test/*.test.mjs
```

Tests use new temporary synthetic stores and independently supplied controlled receipts,
not owner stores, invoices or paid provider calls. They cover increases/decreases/zero/
tiny decimals; duplicate/changed/stale/branched/concurrent updates; ownership; unverified/
changed/expired evidence; append rollback; late closed/revoked accounting; complete
multi-task/unknown totals; individual/cumulative overruns; legacy/equal-clock replay;
signed review, current authority/fresh MFA and privacy. **838 Python / 47 JavaScript
tests pass**, retaining the recovered 798 Python / 47 JS baseline with 40 focused
correction regressions. All earlier assertions remain unchanged; `git diff --check`
passes. Python also invokes JS, so counts are not independent certifications or
production-readiness evidence. Verification history is tracked in [TASKS.md](TASKS.md).

One controlled receipt revises `0.002` USD to `1.30` USD: task remaining is `-1.20`
USD and pilot remaining is `-0.30` USD. A verified decrease to `0.001` USD leaves
`0.999` USD pilot remaining but retains paused state and historical overrun evidence.
Another retains `1E-36` USD with `0.999999999999999999999999999999999999` USD pilot
remaining. These are complete synthetic accounting values, not real prices/savings.

**Remaining software, separate batches:** continuous pilot-feedback handling; external
notifications/escalation/operational supervision; direct physical provider-stream and
lost-delivery recovery mapping; automatic subagent/new-run attribution; finer native
permission/interruption/test and physical-provider-attempt tool attribution beyond the
reviewed metadata contract; broader shell/remote/non-text/extra-charge support. Positive
company-specific verifier implementations/evidence remain unsupplied and default-denying.

**Separately deferred installed-host/real-world gates:** approved OpenCode/LiteLLM
loading/peers/runtime/permissions/callback/bypass/retry checks; real identity/pricing/
invoice/readiness/outcome evidence; approved private sessions/data and deployment/TLS/
logging/storage/backup/security/capacity/operator validation. No installation, private
access, owner-store migration/change, real call, activation or public push is performed.
Code remains unpublished until the owner selects a licence.
