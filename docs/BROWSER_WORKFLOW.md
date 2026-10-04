# B-03 browser workflow and laptop demonstration

**Updated:** 2026-10-04. Uses the existing Django company application and engine,
not a replacement app, skill, plugin, gateway, or coding-client connector.
Actual accounts/MFA and B-02 permissions remain the authority. No new dependency
or database migration is introduced by B-03.

## Start without replacing existing state

For an already initialized, current B-02 store, restart the same local application:

```sh
.venv/bin/python -m engine company serve --store local/company-demo-v1
```

Use your actual store path. Do not bootstrap again, overwrite a database/key,
or reset data to run this walkthrough. If an older installation needs shipped
migrations, stop its server, make a private matching backup, and follow
[COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md#backup-upgrade-and-rollback-responsibilities).
For a genuinely new store only, follow its interactive first-administrator setup.
The owner supplies passwords privately; no default password is provided here.

Open `http://127.0.0.1:8000`. This is laptop-only development, not a company HTTPS
deployment. Do not expose or tunnel it. Company serving still requires the
approved private-socket/HTTPS-proxy contract and actual operator validation.

## Role-appropriate entry points

- **Participating developers:** Home → Tasks → manual suggestion, one-task response,
  reported actual model, eventual result. Home also links simulations whose stored
  scope includes them. Ordinary developers cannot inspect other developers' tasks.
- **Participating seniors:** the same personal actions plus permitted repository
  task inspection/initial outcome review. They cannot accept another developer's
  suggestion or claim that developer's actual model use.
- **Company administrators:** accounts/invitations, guided policy/model/collection
  editing, retained task history, and category evidence/pilot inspection. An
  administrator without explicit approver designation cannot authorize/control pilots.
- **Designated senior/admin approvers:** separate scope decisions and pilot controls,
  with current applicable MFA plus fresh password/unused authenticator code at the
  sensitive action. Seniority and per-task acceptance never provide designation.

## One joined synthetic demonstration

Use only fictional `fixture/*` models with the fixture policy in an isolated demo
installation. These are supplied demonstration observations, not model executions
or evidence that the models succeeded. Never label real company work synthetic to
evade collection restrictions, or invent a result for an actual task.

1. Sign in as an invited participating senior. Start a manual task from Home.
   Choose the approved synthetic repository and **Synthetic demonstration**.
   Supply a short task label and a manual work-session label; neither reads a
   coding-tool session. Choose `documentation`, justified `low` risk, original
   model `fixture/premium`, required tool `read`, and context requirement `2000`.
   The saved suggestion is `fixture/cheap`; the original choice stays unchanged.
2. Open its **Accept/reject this suggestion** action. Acceptance applies to this
   task only and supplies no success/model/pilot approval. Report fictional actual
   use separately, then the eventual fictional result with a metadata-only evidence
   reference. Unknown tests/scores/costs/latency stay `Unknown` or blank, not zero.
3. Repeat a second documentation example in a different manual work session.
   Optionally include a junior `test_generation` failure/rejection and a task with
   unknown results. The cards, evidence, and result history retain those signals.
   Corrections prefill the full current result and append rather than overwrite;
   the current result reference and task revision are supplied internally.
4. As a permitted admin/approver, open **Evidence & pilots → Prepare category
   evidence**. Choose the source first. Select labeled developer/work-session
   checkboxes and categories; there is no projected-session-ID copying. Supply a
   new learner version, explicit validation cutoff, and your experimental minimum
   success/session inputs. The illustrative two-success/two-session demo inputs
   are **not production-approved thresholds**. Never tune on held-out test data.
5. Read the independent **Category evidence review** page: all model evidence,
   negative/unknown counts, gaps, source limitations, complete result revisions,
   exact policy, and whether the current source still matches the stored review.
   A non-designated admin can stop here and share its protected link with a
   designated approver, rather than being sent to an approval-only page.
6. As that approver, select a **separate pilot scope**: explicit repository,
   permitted junior/senior developers, evidenced category/model mappings, unique
   human-readable pilot label, positive task/budget limits, expiry, and reason.
   Choose **Authenticated simulation only** for this demo. Review the exact
   company/deployment/revision/policy/evidence/scope preview, then acknowledge it
   and supply fresh password/MFA. The signed preview [server-bound reviewed
   metadata] expires after 15 minutes and binds the selected content, not credentials.
7. Approval does not activate anything. On the pilot page, select **Activate reviewed
   simulation only**, preview the consequential action, and confirm with another
   unused authenticator code. The existing B-01 runtime is reused. Its current
   guard [authority checks], scope, complete accounting, and ordered history are readable.
8. A scoped developer opens the simulation link on Home. Supply new-task metadata
   and an explicit simulated reservation, with an optional model override. No model
   runs and no synthetic accounting result enters task-learning evidence.
9. Open **Settle your simulated task** and choose the labeled owned task from the
   selector. No decision-ID copying is needed. Record complete simulated cost and
   completed/failed/cancelled accounting status. Failure/overrun pauses continuation;
   negative remaining budget is displayed. Settled records remain immutable retries,
   not new charges. Pending settlement remains available after pause/revocation/rollback.
10. Inspect the pilot as an admin/approver. Only currently valid controls appear;
    the server still checks designation, fresh MFA, expected revision, authority,
    transitions, and limits. Preview/confirm pause, eligible resume, revoke, or
    default-only rollback. Failure/overrun cannot resume unchanged approval.
    Revoked/default-only records cannot restart their budget or discard history.

## Important limitations

- Task boundaries, labels, selected/actual models, outcome truth, cost, latency,
  and source provenance remain manually reported, not captured/verified by OpenCode.
  No private sessions, model/provider calls, extra shadow requests, or active-session
  switching are part of B-03. The B-04 connector is not implemented here.
- Company learning preparation uses the existing experimental baseline. No new
  production gates, weights, trained-model requests, or automatic learned-suggestion
  application are introduced. Everyone's approved records/negatives remain retained.
- A positive local review is not independent company readiness. Live approval
  still needs the server-owned `ReadinessVerifier`, whose shipped configuration
  defaults to refusal. There is no ready/verified checkbox or test-verifier shortcut.
  Even a valid live scope approval is not execution/deployment permission and has
  no simulation admission/settlement/activation links.
- Normal browser forms use labeled choices and confirmations. Older direct form
  submissions remain compatible with the existing protected B-02 contracts; they
  do not bypass authentication, freshness, authority, source, or live-readiness checks.
  Confirmation previews are a browser safety aid, not a replacement authority.
- Privacy/no-store/CSRF checks remain. History is not tamper-proof, storage is not
  encrypted at rest, and retention remains manual. Tests do not certify production
  security, engineering quality, or savings.

Verification lives in `tests/test_browser_workflow.py` alongside the unchanged
company/live-authorization suites. It includes actual loopback HTTP enrollment →
task linkage → labeled review selection → exact scope preview and refused forgery,
plus browser authorization/control/settlement and adverse cases on temporary stores.
