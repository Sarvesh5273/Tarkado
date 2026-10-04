# New-session handoff — implement B-03

**Saved:** 2026-10-04. The owner requested moving B-03 implementation to a new
session because the conversation had become long. Do not restart Tarkado or
rebuild completed components.

**Resumed/completed:** B-03 browser implementation was subsequently verified on
2026-10-04: **605 tests pass** (573 retained baseline + 32 B-03 checks). See
[BROWSER_WORKFLOW.md](BROWSER_WORKFLOW.md) and the B-03 checklist in
[TASKS.md](TASKS.md) for the current interface. The original recovery context
below is retained as history; B-04/private/live/dependency/commit limits remain.

**Later owner authorization (2026-10-04):** B-04 and conditional B-05 code have
since been built. The owner then authorized logical local commit batches but
selected **Keep code unpublished**, deferring public push until choosing a
licence. Earlier no-commit instructions below are historical; private-session,
provider-call, dependency-installation, and deployment limits remain unchanged.
Current progress and the remaining delivery-contract gap are in [TASKS.md](TASKS.md).

## Start here

Workspace: `/Users/sarvesh/Dev/Tarkado`.
Application code: `engine/`, including the optional Django app `engine/company/`.

First verify the existing baseline:

```sh
.venv/bin/python -m unittest discover -s tests -q
```

**Last verified:** 573 tests passing. This is regression verification, not proof
of production security, model quality, or savings. Subsequent changes may alter
the count; inspect failures instead of weakening assertions.

Recover context before editing:

1. Read `AGENTS.md`, `docs/WORKFLOW.md`, and `docs/TASKS.md`.
2. Read `docs/DECISIONS.md`, especially C-01–C-05 and accepted UI-01–UI-03.
3. Read `README.md`, `docs/PRD.md`, and `docs/TRD.md`.
4. Read `docs/COMPANY_AUTHORIZATION.md` and `docs/COMPANY_OPERATIONS.md`.
5. Read `docs/FEEDBACK.md`, `docs/LEARNING.md`, and `docs/READINESS_PILOT.md`.
6. Read the supporting implementation docs: `DEVELOPMENT.md`, `POLICY_HISTORY.md`,
   `PRIVACY_AUDIT.md`, `ROLLOUT.md`, `UNCERTAINTY.md`, and `OPENCODE_ADAPTER.md`.
   Consult `RESEARCH.md` for background; it is not deployment evidence.
7. Inspect `git status`, diff, the company application/templates, and relevant
   tests. Much of the implementation is untracked/uncommitted **user work**;
   preserve it. Do not assume an untracked file is disposable.

## Accepted B-03 architecture

The owner accepted the browser-first recommendation and wants a real company
product also demonstrable on a laptop, not a skill-only or separate toy build.

- **B-03:** improve the existing Django browser/template interface into a joined,
  understandable developer/admin workflow. No React rewrite, new desktop app,
  replacement backend, or new runtime dependency is needed for the agreed scope.
- Reuse B-02 accounts, permissions, MFA, recovery, records, approval checks, and
  the existing engine. The company service remains the authority.
- **B-04:** a separate narrow OpenCode connector for developer-facing suggestions
  and permitted task observation. A CLI plugin is a candidate for its display;
  the authentication/capture/task-boundary integration is not implemented or
  finalized. Multi-model support alone does not make a client safely routable.
- Optional agent skills may later explain usage. They cannot establish identity,
  result truth, company model approval, or first-pilot authorization.
- Proposed `/tarkado`, footer status, and terminal task panels are illustrative,
  **not working features**. Do not install or build a connector as part of B-03.

The owner asked for careful CTO-level recommendations. Explain tradeoffs honestly;
do not promise a risk-free decision or misrepresent a mock as integration.

## Completed work to retain

- Offline replay, policy/model registry, candidate evaluation, uncertainty,
  privacy/audits, and local policy history/rollback.
- Recommendation → per-task response → reported actual model → outcome linkage,
  delayed/corrected results, and an experimental count-based learner.
- B-01 persistent scoped simulation runtime: reservations/settlement, complete
  costs/failures/overruns, overrides/fallback, pause/resume/revoke/default-only
  rollback, ordered history, stale checks, and idempotent retries.
- B-02 implementation complete for the owner-confirmed **authorization mechanics**:
  invitation-only individual accounts, explicit administrator/approver designations,
  current permissions, MFA and recovery, company configuration/history, private
  backups, and approved Waitress single-host HTTPS-proxy serving contract.
- Authenticated manual task records preserve historical per-action roles through
  an additive schema-2 projection. Schema-1 offline records remain unchanged.
- Company category reviews and separately authenticated simulation approvals are
  joined to the B-01 journal/accounting, not a second routing implementation.
- Conditional live scope approval uses a server-owned `ReadinessVerifier`
  interface and a separate designated human's fresh password/MFA. It binds exact
  company/deployment/revision/evidence/policy/learner/scope/validity and retains
  immutable approval/withdrawal history.

**Important:** a live scope approval is NOT execution/deployment permission.
The shipped readiness verifier is unconfigured/default-denying. The positive
path is tested with a controlled verifier defined only in tests. Do not expose a
"ready/verified" checkbox or configure a test verifier in the product. Actual
company evidence/criteria verification, task/provider admission (B-04/B-05), and
deployment validation remain separate live-use gates, not another B-02 rebuild.

## B-03 required result

Make the existing forms/pages usable **without manually copying JSON or internal
record IDs**. Prioritize the joined workflow, not more standalone reports.

1. **Developer home/tasks:** readable task cards, clear pending states, and a
   guided metadata-only task flow. Display selected/suggested/fallback models,
   reason, confidence limitations, policy version, and current versus historical
   state. Prefer supported selectors over opaque identifiers.
2. **Per-task feedback:** clear accept/reject actions labeled for one task only;
   separate actual-model use and eventual result. Unknown must remain unknown.
   Preserve ownership, timing, immutable retries, role history, failures,
   mismatches, overrides, and append-only corrections.
3. **Senior/admin review:** readable category evidence/gaps/negative results,
   visible source limitations, and guided validation-plan selection. Resolve
   session/record references internally; never tune thresholds to held-out test
   results or quietly discard junior failures. Numeric production gates remain
   unfinalized; experimental inputs must stay explicitly labeled.
4. **Separate pilot scope/review:** select permitted developers/categories/models
   and explicit repository/limits/expiry; show the exact content being approved.
   Preserve fresh-MFA designation checks and distinction from per-task acceptance.
   Live approval still requires the independent verifier; no UI bypass.
5. **Pilot controls:** readable scope/status/current guard, complete budget and
   reservation accounting, history, pause/resume/revoke/default-only rollback,
   and settlement without copying decision IDs. Do not offer simulation execution
   controls for live scope records or enable invalid/stale transitions.
6. **Navigation/accessibility/errors:** role-appropriate menus, useful empty states,
   field help, readable error messages, and confirmations for consequential actions.
   Preserve server-side authorization, CSRF, no-store/privacy, safe refused-form
   display, and expected-revision checks. A disabled button is not enforcement.
7. **Verification/documentation:** extend existing browser/HTTP tests for the joined
   flow and adverse cases. Keep `docs/TASKS.md` updated. Mark B-03 complete only
   after its required usable workflow is implemented/tested—not because forms
   already exist. Document the laptop demo and still-manual observation limits.

Some initial usability problems are already apparent: raw dictionaries in task
and review pages, manually pasted projected session IDs, policy JSON editing,
raw developer/category lists, and settlement decision-ID copying. Inspect them
before choosing precise edits. An admin may review evidence without being a
designated pilot approver; the UI should not misleadingly funnel that user into
an approval-only page. Keep these permissions separate rather than weaken them.

## Relevant implementation/tests

- `engine/company/urls.py`, `views.py`, `forms.py`, `task_views.py`, `task_forms.py`,
  `control_views.py`, `templates/company/`, and `style.css`: existing UI foundation.
- `services.py`, `tasks.py`, `models.py`: current company identity/configuration,
  task ownership/scope, historical roles, and records.
- `authorization.py`, `live_authorization.py`, `readiness_gate.py`, `security.py`,
  `mfa.py`, `recovery.py`: completed authority/security checks to reuse.
- `engine/feedback.py`, `learning.py`, `readiness.py`, `pilot.py`: existing record,
  evaluation, and state/accounting contracts; avoid duplicating them in templates.
- `tests/test_company.py`: actual accounts/MFA/recovery, manual task workflow,
  category review/simulation controls, concurrency, additive upgrades, real
  loopback HTTP, private-socket Waitress, and backups.
- `tests/test_live_authorization.py`: positive/negative conditional live authority
  and browser/concurrency checks using test-only readiness verification.
- `tests/test_feedback_roles.py` and the existing feedback/learning/pilot suites:
  preserve legacy behavior, role-attribution integrity, and negative evidence.

## Environment and non-negotiable constraints

- Use `.venv/bin/python` for **every Python command**.
- Approved environment: Python 3.13.12; Django 5.2.17, django-otp 1.7.3,
  Waitress 3.0.2, asgiref 3.12.1, sqlparse 0.6.0. Pinned company requirements are
  in `requirements-company.txt`; normal offline engine commands remain
  dependency-free. No additional framework/package is approved for B-03.
- The old Python 3.9 environment is preserved privately at
  `local/environment-backups/python39-20261003-6f67cfa7502045038c6077fc893132ed`.
  Do not delete or inspect it for credentials.
- All implementation remains uncommitted. Do not commit/push or discard changes.
- Do not overwrite/reset local demo databases, keys, feedback, journals, or backups.
  Use temporary synthetic stores for tests; no automatic rebootstrap/repair.
- The owner previously ran upgrade/serve against an empty `local/company-demo-v1`.
  It was empty **when checked**, not proof of its current state. A new store needs
  interactive bootstrap once; existing stores need stopped-server backup/upgrade.
  Do not create the owner's password or read key/database contents to inspect setup.
- Real OpenCode session access remains explicitly deferred. Do not read private
  sessions/credentials or make provider/model calls. Use company-managed APIs only
  when eventually authorized, never consumer subscriptions.
- No extra alternative-model requests in shadow mode. Manual choice is retained.
- Acceptance is not success or policy approval. Preserve everyone's approved
  negative/unknown/override signals; senior feedback is prioritized, not exclusive.
- Do not weaken/remove assertions, invent outcomes, choose production thresholds,
  or claim validated quality/savings from synthetic/public data or test counts.
- No new packages/skills/plugins without explaining the need and obtaining approval.
  Do not spawn subagents unless explicitly authorized.
- If later work actually changes OpenCode integration, load the OpenCode skill
  and consult official **V2** documentation first. Relevant checked UI pages:
  `https://opencode.ai/v2/docs/skills/`,
  `https://opencode.ai/v2/docs/build/plugins`, and
  `https://opencode.ai/v2/docs/build/plugins/cli/`.

## New-session instruction

Resume from this repository/handoff, verify the baseline, inspect the existing UI,
then implement B-03 within UI-01–UI-03. Do not ask the owner to reselect the
accepted browser/skill/plugin architecture. Ask only for a genuinely new product
choice or dependency that blocks the agreed implementation. Keep the scope and
limitations explicit and finish one usable workflow before optional additions.
