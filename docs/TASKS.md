# Tarkado Build Roadmap

## Completion goal — First end-to-end Tarkado build

**Requested by the owner:** 2026-10-03.
**Product contract:** [WORKFLOW.md](WORKFLOW.md), decisions W-01 through W-08.
**Status:** Not complete. Company authorization mechanics are implemented,
including conditional live scope approval; the complete task integration,
independently validated readiness, and live routing remain unfinished.

> Finish one usable end-to-end implementation of the accepted company workflow:
> company setup → observe all participating developers → manual shadow
> recommendations → linked senior-prioritized feedback and actual results →
> learning → category review → separate senior/admin pilot authorization →
> scoped model selection for juniors and seniors → monitoring and rollback.

Target the existing first integration choice: OpenCode V2 with documented APIs
and company-managed API/gateway credentials. Do not attempt to support every
coding client or build another general-purpose gateway to call this finished.

### Focused acceptance/freshness correction — 2026-10-04

Baseline before edits: **737 Python / 33 JavaScript tests pass**. Reproduced through
the real delegated API on a synthetic store: acceptance returns HTTP 200, but the
active pilot becomes paused and its guard blocked before a provider attempt.

- [x] Inspect/reproduce the execution behavior, not only the documented limitation.
- [x] Separate the immutable fixed-cutoff reviewed fit from incoming learning
  freshness and current execution safety. Only timely acceptance on new, previously
  unreviewed tasks avoids the freshness veto; negative/changed evidence stays checked.
- [x] Verify accepted tasks reach the controlled provider; add adverse authority,
  budget, failure/unknown/gap/mismatch, response-retry and next-review regressions.
- [x] Finish full verification and update operating/decision docs.
- [ ] Make a separate logical local commit; do not push.

Reviewed policy/learner/evidence/approval and source hashes are not rewritten;
there is no retraining, threshold change, scope expansion, success label or pilot
approval inferred from acceptance. Existing strict future-publication/refitting
freshness remains and is displayed separately from execution status.

**Verification:** **757 Python / 33 JavaScript tests pass** (737 retained Python
baseline + 20 new acceptance regressions); `git diff --check` passes. Coverage
includes acceptance before selection/claim and after binding, controlled-provider
admission, unchanged readiness-request/artifact content, learning-only staleness,
subsequent review retention, current negatives, stopped/expired authority, budget
exhaustion, stale/changed/owned/timed response semantics and result corrections.
Python also invokes JavaScript, so these are not independent certifications.
`DELIVERY_STARTUP.md` and `DECISIONS.md` document the separation. No existing
assertion was weakened; no installation, private session/store access, real
provider call, automatic retraining or public push occurred. Tool-coding support
and installed-host/provider validation remain separate, unfinished work.

### Remaining build packages, in execution order

| ID | Build package | Required result | Dependency / boundary |
| --- | --- | --- | --- |
| B-01 | Scoped pilot runtime | Persistent active/paused/revoked pilot state; exact policy/scope checks; new-task decisions; task/budget accounting; overrides; safe fallback; rollback and decision records. | Build locally first. Local receipts can authorize simulation only, never live requests. |
| B-02 | Company setup and trusted authorization | Manage permitted developers/roles, approved models, collection scope, and designated senior/admin authority; authenticate and revoke pilot approvals tied to exact policy/scope. | Implementation complete for the agreed authorization mechanics. Actual accounts/MFA, recovery, company serving, and conditional live scope approval are tested. The readiness verifier defaults to refusal; real evidence, adapter integration, and deployment validation remain separate gates. |
| B-03 | Developer/admin workflow interface | A usable way to see recommendations, accept/reject per task, record actual models/results, review category evidence, approve a limited pilot, and inspect/reverse its state. | Implementation complete and verified on the existing Django browser/templates (UI-01–UI-03). Guided selectors, separate evidence/scope review, confirmations, readable history/accounting, and owned settlement reuse B-02/B-01 authority without JSON/internal-ID copying. Observation/outcomes remain manual; the connector is separately B-04. |
| B-04 | Task-level OpenCode integration | Documented task/run/subagent admission scope; metadata capture, deduplication, gap/error handling, and visible manual recommendations across participating developers. | Limited explicit-root-task connector/API and inactive OpenCode server/CLI plugin source implemented. Installed-host/terminal loading and approved real-session validation remain unverified; subagent/new-run and exact per-request usage are not claimed. B-04 is not marked fully complete. No Laya or model switching. |
| B-05 | Integrated learning and pilot selection | Feed actual task feedback/results into versioned learning; show category readiness; after separate trusted approval select models only for eligible new tasks and preserve overrides. | Learner publication/future browser-connector suggestions and conditional live-scope selection/accounting are built and regression-tested. Readiness/admission remain default-denying. Missing atomic OpenCode/gateway task-model-provider-cap delivery is unfinished software, not merely deferred validation; B-05 is not fully complete. |
| B-06 | Monitoring, privacy, and operational delivery | Continued company-wide monitoring with senior feedback prioritized; quality/override/failure signals; retention controls; revocation and rollback; install/start instructions and one joined workflow demonstration. | Existing pattern checks are not comprehensive protection. Operational guarantees and supported environments must be stated honestly. |
| B-07 | Stable policy handoff | A stable versioned export contract and a documented first existing-tool/gateway handoff, with unsupported capabilities/combinations made explicit. | Research the selected integration before implementation. Do not replace the existing request transport or infer provider credentials. |

Existing local records, learner, reports, privacy checks, audits, and policy
history are foundations for these packages—not reasons to rebuild them or count
the missing joined workflow as complete. B-01's local simulation and B-02's
company setup/authorization mechanics and B-03 browser workflow are implemented.
B-04 connector code now exists for a limited explicit-task scope; its installed
host/terminal and real-session validation remain pending. Deployment/evidence gates
below remain separate and unsatisfied. No plugin installation or private access occurred.

**Session handoff:** the owner requested implementing B-03 in a fresh session.
Read [HANDOFF_B03.md](HANDOFF_B03.md) for the accepted UI direction, current code/
tests, usability goals, and preserved access/deployment limits. No B-03 UI rebuild
or connector implementation was started by preparing this handoff.

### B-05 implementation — versioned learning and conditional scoped selection

**Started:** 2026-10-04. **Status:** conditional build milestone implemented;
**B-05 not fully complete** because actual atomic provider/model delivery remains
unfinished. Baseline retained: 637 Python tests and 14 JavaScript tests. User deferred installed-client/real-data/
deployment checks, not regression tests or authority/safety enforcement.

- [x] Publish/reverse reviewed versioned learners explicitly for future manual suggestions.
- [x] Preserve exact learned historical task snapshots and safe current fallback.
- [x] Join connector observations/feedback to learner freshness and evidence review.
- [x] Build conditional selection/reservation/settlement behind separate live approval and server-owned admission verification; default deny unsupported live delivery.
- [x] Retain overrides, current guard, monitoring failures/gaps, stale checks, history, and rollback.
- [x] Extend joined regression/adverse tests and document build versus deferred integration.
- [ ] Implement a supported atomic new-task/model/provider-cap delivery adapter, then wire the descriptor-binding seam; the observer cannot perform this and no live-session switch is substituted.
- [ ] Independently validate company outcomes/evaluation/learning criteria and the real readiness/admission verifier integrations before live use.
- [ ] Complete later installed-client, approved real-session, and actual deployment checks (owner-deferred).

No Laya, numeric production gates, dependencies/plugin installation, provider calls,
private-session access, commits/pushes, or live deployment. OpenCode lacks a verified
atomic delivery/budget boundary in this build; do not replace it with a live-session
switch or claim the full automatic-execution workflow finished.

**Verification:** **671 Python tests pass** (all 637 baseline + 34 new B-05
publication/selection/concurrency checks); **19 dependency-free JavaScript tests
pass**, including five conditional descriptor-binding checks. The Python suite
also runs the JS suite; these are regression checks, not independent production
certifications. `git diff --check` passes. No assertion was weakened or removed.

An initial background run failed with 53 errors because migration 0007 was added
while old models were loaded; subsequent consistent-snapshot verification passed
637 tests before further tests and finished at 671. No reset or user-store migration
was used. Publication/MFA/version/source checks, connected learned suggestions,
unknown/junior-negative retention, conditional linked-task/API selection, separate
human approval, proof/override/cap/claim binding, rollback/incurred cost, corruption,
current revocation, and shared-budget/one-use concurrency are covered.

Migration 0007 and optional refusal metadata are additive; schema-1/offline behavior,
B-01 simulation, B-02 live-scope boundaries, B-03 browser work, B-04 observer,
accounts/MFA/recovery, and all owner uncommitted data remain preserved. The controlled
readiness/admission verifiers exist only in tests. Shipped launchers deny both;
no package, Laya, plugin activation, private access, model call, commit/push, or
deployment occurred. See [INTEGRATED_LEARNING_SELECTION.md](INTEGRATED_LEARNING_SELECTION.md).

### B-04 implementation — explicit-task OpenCode connector

**Started:** 2026-10-04. **Status:** limited connector code implemented/tested;
**B-04 not fully complete** pending installed-host/terminal and approved real-session
validation. Recovery baseline: **605 tests pass**.
The owner accepted no Laya, explicit task starts, permitted automatic observations,
code-enforced storage, and manual recommendations. Preserve B-01–B-03 and all
uncommitted work. No dependencies/plugins installed or private/model access.

- [x] Verify baseline and current official OpenCode V2 hooks/CLI/RPC/API docs.
- [x] Implement revocable account/repository-scoped connector pairing and authority.
- [x] Bind explicit tasks and append-only observations/feedback to existing records.
- [x] Add inactive-in-repository OpenCode server/terminal plugin and task panel source.
- [x] Test retries, gaps, ownership, revocation, stale/multi-model behavior, and privacy.
- [x] Document supported boundaries, inactive installation, and unverified-host limits.
- [ ] Verify installed OpenCode V2 package/TSX/peer-runtime loading and rendered task panel after explicit operator approval; controlled-host tests are not that verification.
- [ ] Validate owner-approved real task/repository/session scope; private access remains deferred.

Actual private-session validation, installed OpenCode host integration, subagent
capture, verified provider usage, B-05 automatic selection, and deployment remain
separate gates. Do not mark B-04 fully verified from mocks alone.

**Verification:** 637 Python tests pass (all 605 baseline + 32 connector/API/HTTP
and embedded JavaScript-runner checks); 14 dependency-free JavaScript tests pass
separately. Real loopback HTTP uses synthetic actual accounts/MFA and completes
browser-issued delegation → task suggestion/response → attempt/close → reported
model/unknown outcome. Tests cover scoped credentials, current permission/MFA/
recovery, immutable event IDs, gaps, raw-content refusal, negative/multiple-model
retention, interrupted close, and source-bound category-review staleness.
`git diff --check` passes. Test counts are not production/evidence certification.

The server plugin refuses loading without an explicit private-single-developer
service attestation; it is not safe for a shared/multi-user OpenCode service's
human identity. The attestation is an operator responsibility, not identity proof.

Code is in `engine/company/` and `integrations/opencode/`; full scope/operation
guide: [OPENCODE_CONNECTOR.md](OPENCODE_CONNECTOR.md). Migration 0006 is additive,
and existing approved collection lists are not expanded automatically. It was
applied only to temporary synthetic test stores, never owner databases/keys.
No packages/Laya/weights, live OpenCode configuration, model calls, private
sessions, commits/pushes, or real deployment were introduced.

### B-03 completed implementation details

**Started/completed code verification:** 2026-10-04.
**Status:** B-03 implementation complete for the accepted browser-first scope;
UI-01–UI-03 unchanged. The end-to-end product/live workflow is not complete.
Recovery completed before editing: all handoff references and existing UI/tests
inspected; **573 tests pass**. Existing uncommitted implementation/data retained.

- [x] Recover context and verify the 573-test baseline before editing.
- [x] Add readable developer task cards, pending states, and guided metadata selectors.
- [x] Join per-task response, actual-model use, results, and correction/history display.
- [x] Add independent evidence review and guided experimental validation-plan selection.
- [x] Show exact pilot scope for separate fresh-MFA human confirmation.
- [x] Add readable pilot guards/accounting/history, valid controls, and owned settlement choices.
- [x] Improve role navigation, accessibility, errors, and consequential confirmations.
- [x] Extend browser/HTTP adverse-flow tests and document the same-app laptop walkthrough.

B-04, dependency installation, private sessions, model calls, commits/pushes, and
real readiness/deployment validation remain outside this implementation.

**Completion verification:** **605 tests pass**, including all 573 baseline tests
and 32 new B-03 browser/HTTP checks. Exact-content confirmations, fresh credentials,
current authority, stale/changed inputs, scoped selectors, unknowns, corrections,
junior negatives, unapproved actual-model reports, live/simulation separation,
owned settlements, complete overruns, and guided policy editing are covered.
The real loopback HTTP flow uses actual synthetic accounts/MFA, linked tasks,
rendered session/category choices, scope preview, and refused forgery. No earlier
test assertion was weakened or removed. `git diff --check` passes.

The joined walkthrough and limitations are in
[BROWSER_WORKFLOW.md](BROWSER_WORKFLOW.md). B-03 introduces no dependency or database
migration. Existing uncommitted work and owner stores remain preserved; tests use
temporary synthetic stores. No connector, private-session access, model/provider
calls, commits, pushes, real verifier, or deployment was performed. Counts are
regression verification, not security certification, quality validation, or savings.

### Definition of building complete

- [ ] One supported installation can run the joined workflow without manually
  copying fixture JSON between otherwise disconnected demonstrations.
- [ ] Company configuration and developer/admin controls exist; required roles
  and live approval authority are verified, not just claimed in local metadata.
- [ ] Approved task-level observations cover participating developers, with
  collection scope, missing events, and unknown outcomes handled explicitly.
- [ ] Recommendations appear before new tasks; accept/reject is linked to the
  exact recommendation, actual model use, and eventual result.
- [ ] The learner consumes linked results, prioritizes senior feedback, retains
  everyone's failures, and produces explainable versioned recommendations.
- [ ] Category evidence and approval are separate. Only a designated senior/admin
  can authorize the first limited live pilot; readiness cannot activate it alone.
- [ ] Pilot scope, current approval/model status, task/budget limits, fallback,
  and overrides are enforced at the supported task boundary.
- [ ] Monitoring, pause/revocation, policy rollback, and audit records work through
  that same workflow, not only in an unrelated local history command.
- [ ] Installation, operation, privacy/retention, policy handoff, and unsupported
  behavior are documented together. No live capability is claimed from mocks.

These are implementation completion criteria, not a demand to collect real
company data now. A runnable local simulation milestone comes first; incomplete
live integration/authentication must stay labeled pending rather than being
removed from the goal.

### Deployment gates — tracked separately from code completion

**2026-10-04 owner update:** logical local commit batches are now authorized.
The owner selected **Keep code unpublished** after review identified the existing
public GitHub repository and unresolved licence. Do not push implementation until
the owner chooses a licence; the earlier push request is superseded by that choice.
The current live-delivery blocker requires a chosen supported company gateway/
provider task-model-hard-cap admission path as well as integration verification,
not merely another run of the existing tests. No such path is assumed/installed.

**Local commit batches:** product/guardrail docs (`e388d13`), offline engine and
synthetic regression fixtures (`717a939`), joined company authority/browser
services (`7bd955e`), inactive OpenCode connector and HTTP/core tests (`aff0241`),
and publication/conditional-selection regression coverage (`0d2bcc6`). The final
batch records operating guides, build limitations, and this roadmap. Shared company
modules already join B-02–B-05, so these are dependency/topic batches of the current
implementation, not invented historical milestone snapshots. Private owner stores,
credentials, environment files, generated caches, and node dependencies are excluded.
Verification remains 671 Python tests plus 19 JavaScript tests; all 34 publication/
selection tests, 32 connector tests, and 383 offline tests also pass in focused runs.
These commits remain local; the remote was not pushed or changed.

Real-session/data access remains deferred until the owner supplies approved
scope. Company-managed credentials, trusted approver identity, a reviewed
evaluation design, validated learning/readiness thresholds, and a reviewed
pilot scope are required before company deployment. Code can implement these
interfaces and checks, but cannot invent those approvals or evidence.

No package/skill installation, provider spend, private-session collection,
public release, or push is authorized by this completion goal alone. Local commits
are separately authorized by the dated owner update above; public release is not.
Ask before any new dependency installation; request missing deployment inputs
only when they block the corresponding package. No finish date, production
savings, or bug-free guarantee is claimed.

### Scope control

Complete the required company workflow before optional Laya, embeddings,
advanced retrieval/active learning, additional adapters, or a new hosted
platform. Those existing roadmap tracks remain visible below; optional research
is not a prerequisite for the first end-to-end build. Raw-content opt-in is also
a separate unresolved privacy track, not permission to collect code/prompts now.
Choose a licence before public code release. Changes to accepted workflow or
release scope require owner agreement and a dated decision entry.

Use the existing implementation log and phase checklists below for progress.
Mark a package complete only when its required behavior is implemented and
verified. Test counts show regression checks, not percentage of product built.

## Completed implementation iteration — B-02 company setup and trusted authorization

**Started:** 2026-10-03
**Completed code verification:** 2026-10-04.
**Status:** B-02 implementation complete for the owner-confirmed authorization
scope: actual company accounts/roles/MFA/recovery, approved model/collection setup,
company serving/backup, authenticated simulation approval/runtime, and the positive
conditional live-approval boundary are implemented and tested. The live boundary
requires a trusted server-owned readiness assessment, with default refusal.
Actual company evidence verification, live task/provider integration, and real
deployment/TLS validation are still required before live use; they are not claimed
from controlled tests and do not reopen completed B-02 coding work. B-01 is retained.

The company workflow is finalized in [WORKFLOW.md](WORKFLOW.md): observe all
participating developers → recommend/manual choice → senior per-task feedback
plus actual results → learn across sessions while monitoring everyone →
category readiness → separate senior/admin approval for the first limited
automatic-routing pilot → scoped routing for juniors and seniors → monitoring.

Shadow recommendations make no extra alternative-model calls. A senior's
per-task acceptance is neither task success nor pilot/model approval. Exact
learning weights, evidence thresholds, and production pilot limits remain
unresolved. Account authentication, historical roles, and live-scope approval
mechanics are implemented. Outcome truth and a real company readiness verifier
are not established; the default installation grants no live approval/execution.

**Phase 1 verification:** 52 unit/local CLI tests pass. The synthetic replay is
deterministic and makes no API calls. The code is in `engine/`; it is not a
second Tarkado project. No additional skills or runtime packages were installed.

**Previous iteration (B-01):** persistent simulation state and event history,
new-task scope/compatibility checks, budget reservations and settlement,
developer overrides, pause/resume/revoke, and rollback to default-only behavior.
Explicit local receipts authorize simulation only. Full costs, overruns, and
failures remain visible.

**This iteration (B-02):** build one company-controlled authority, verified
identity separate from role/permission, exact-scope revocable approvals, and
joined checks on existing feedback/review/runtime operations. See
[COMPANY_AUTHORIZATION.md](COMPANY_AUTHORIZATION.md). Self-hosted invitation-only
accounts, explicit administrator enrollment, and optional later SSO are accepted
as C-01–C-05 in [DECISIONS.md](DECISIONS.md). Framework/dependencies and supported
Python transition are now approved: Django 5.2.17 on Python 3.13.12. Actual login,
private manual invitations, permission changes, policy/collection setup, and
company history are implemented. The same browser interface now joins actual
accounts to manual shadow recommendations, responses, reported model use, and
outcomes with historical roles. Authenticator MFA and restricted backup recovery
are implemented with approved django-otp 1.7.3. On 2026-10-04 the owner approved
offline/admin-assisted password recovery and Waitress single-host HTTPS-proxy
serving; those paths and joined evidence → authenticated simulation authorization
→ B-01 runtime controls are implemented. Conditional live scope approval now
requires an independently checked assessment in addition to the designated human
decision. Actual deployment review, real readiness verification, and the live
adapter remain unfinished. A recorded scope approval alone cannot run a model.

**Owner clarification:** build a real company product that is also demonstrable
on the laptop, not a separate toy implementation. Do not assume startups have
existing company SSO [employee single sign-on]. Standalone invitation-only accounts
with the same permission checks are accepted; the framework and initial enrollment
are implemented. Authenticator MFA and lost-factor recovery are approved and
implemented. Password recovery and the company server contract were subsequently
approved and implemented; actual deployment prerequisites and live validation
remain separate.
Synthetic demonstration evidence and deferred real-session/provider access
remain separate from real account authentication.

**Previous verification:** 98 unit/local CLI tests pass, including all 52 Phase 1 tests.
The candidate example returns reject with `deployment_authorized: false`.
Reviewed enablement and independent evaluation-design verification remain
pending; Phase 2 as a whole is not yet complete.

**Previous history verification:** 137 unit/local CLI tests pass. Local snapshot history,
content-bound review labels, stale-change protection, and rollback are tested.
Policy/model content and live sessions remain unchanged by history operations.

**Previous privacy verification:** 180 unit/local CLI tests pass. Suspected secrets are
blocked, known-pattern diagnostics are redacted, and audit exports bind exact
policy content and retain failures/overrides. Files are private and are never
overwritten. Pattern checks are not a secret-free guarantee.

**Previous adapter verification:** 210 unit/local CLI tests pass. The wrapper issues only
version checks and scoped GETs to a mock OpenCode executable, preserves model
selection, and projects approved metadata. Installed OpenCode is V2.0.21;
only its version/help were checked, not private sessions or real providers.

**Previous uncertainty verification:** 236 unit/local CLI tests pass. Bounded-quality
intervals use distinct tasks, complete paired coverage, and predeclared caller
attestations. Repeated identical runs cannot shrink them. Existing conservative
regression checks and disabled enablement remain unchanged.

**Previous linkage verification:** 276 unit/local CLI tests pass. Local records preserve
recommendation/response/actual-model/result linkage, role labels, delayed
outcomes, and correction history. Senior-prioritized review ranking retains
junior failures; it does not train future recommendations or authorize routing.

**Previous learning verification:** 306 unit/local CLI tests pass. The explicit
validation-plan learner fits category rules and saves future manual suggestions
back into the feedback loop. Tests retain failures/rejects, enforce cutoffs,
refuse stale/forged source evidence, preserve selection, and never authorize
deployment. Synthetic mechanics are not real-task algorithm validation.

**Previous review verification:** 331 unit/local CLI tests pass. Category reports retain
gaps/failures, and designated local senior/admin receipts bind the exact report
and scope. Blocked/stale reports cannot be approved. Identity is unverified,
limits are declared rather than enforced, and live routing remains disabled.

**Previous B-01 verification:** 372 unit/local CLI tests pass. Scoped simulation
admission enforces reviewed task/budget reservations; settlement preserves
actual costs, failures, and overruns. Persistent controls and default-only
rollback retain history. Source/policy/approval changes block admission; retries
cannot double reserve/charge. No provider requests or live authorization.

**Previous verification:** 421 tests pass, including 49 new company-account/setup
tests and all 372 prior tests. Checks include actual individual login, single-use
expiring/revocable invitations, fresh administrator verification, current-role
gates, login-attempt limits, CSRF/session safeguards, policy/collection setup,
revisioned actor/time/reason history, concurrent changes, and actual loopback HTTP
login. Existing offline/simulation components and local demo data remain intact.
These tests do not certify production security or complete B-02.

**Previous joined-loop verification:** 469 tests pass, including 48 new authenticated-task,
historical-role, concurrency, and additive-upgrade checks. The actual loopback
HTTP test now completes invitation → login → suggestion → response → reported
model use → result without copying fixture JSON. Legacy ledger format/counts stay
unchanged; promotion cannot relabel old junior evidence, and failures/rejections/
unknowns remain visible. Authentication binds submitters, not engineering truth.
No provider requests or live task capture/authorization; B-02 remains incomplete.

**Previous startup verification:** 471 tests pass. Startup diagnostics now distinguish a
new, uninitialized store (bootstrap once before upgrade/serve) from incomplete
existing state (preserve files and inspect/restore, never reset). Two additional
tests check that neither error creates credentials or overwrites existing data.

**Previous MFA verification:** 501 tests pass (30 new MFA/security/recovery checks).
Administrators/designated approvers require confirmed authenticator proof;
verification failures/replays are retained/refused. Backup codes grant limited
factor replacement only, not direct company/pilot access. Factor replacement
revokes old devices, codes, and MFA-session generations. Concurrent code use,
CSRF, current permission checks, and actual loopback HTTP enrollment are tested.
Forgotten-password recovery, trusted pilots, and production deployment remain
pending; these tests do not certify production security or complete B-02.

**Previous joined-control verification:** 540 tests pass (39 new recovery/authorization/deployment
checks). Password recovery preserves roles/MFA and invalidates old sessions;
stored company reviews and designated fresh-MFA approvals bind exact policy/source/
scope/expiry. B-01 state/accounting is reused in serialized company transactions;
reject/revoke/expiry/current authority changes block admission, settlement keeps
incurred cost, and rollback retains history. Actual private-socket Waitress serving,
secure-origin checks, paired private backup, and existing-state upgrades are tested.
The joined browser review/approve/activate/admit/settle path is also tested;
missing MFA cannot downgrade recovery, and company serving refuses development
or mismatched-origin settings. No private-session/provider access or real public
HTTPS deployment was performed.
Manual evidence still cannot authorize live routing; full B-02 is not complete.

**B-02 completion verification:** 573 tests pass (33 new live-approval/interface
checks). A designated human with fresh password/MFA can approve exact live scope
only after a trusted verifier returns a current assessment bound to the same
company/deployment/revision/evidence/report/policy/learner/scope. Synthetic data,
browser booleans, unconfigured/outage/stale verification, and invalid authority
are refused. Revoke/default-only withdrawal preserves ordered immutable history;
old scopes are rechecked rather than reused as execution permission. The positive
browser path is tested with a controlled verifier defined only in the test suite.
No numerical production criteria, real verifier, live execution, private sessions,
or actual company deployment are supplied by these tests.

**Deferred by user:** approved real-session validation. Other offline work
continues; no private session reads or company credential assumptions are made.

**Next building work:** B-03 browser implementation is now complete (checklist
above), reusing completed company/authorization mechanics rather than rebuilding
them. B-04 remains separately scoped and was not implemented in this session. Later
B-04/B-05 connect real task/provider admission and approved company evaluation to
the trusted readiness interface; production criteria are not guessed. Actual
deployment remains an operator-approved validation gate. Real-session access stays
deferred. The joined local controls and live-boundary contract are in
[COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md).

### B-02 implementation checklist

- [x] Recover all product/implementation documentation, inspect existing changes and relevant code/tests, and rerun the 372-test baseline.
- [x] Propose a minimal secure design without treating local labels/hashes as identity or changing W-01–W-08.
- [x] Record accepted self-hosted invitation-only onboarding, the same real laptop/company application, explicit administrator/approver assignment, and optional later SSO (C-01–C-05).
- [x] Obtain approval for Django 5.2 LTS and transition to installed Python 3.13 with the old environment preserved privately.
- [x] Implement initial company setup/current permissions and history while preserving existing feedback roles/records and demo data.
- [x] Implement actual invitation-only login/session checks and protected company administration; payload role/identity labels cannot authenticate it.
- [x] Join current company permission checks to manual recommendation/response/actual-model/result records and preserve per-action historical roles.
- [x] Test ownership/reviewer scope, revoked collection, immutable retries/corrections, concurrent writes, unchanged legacy ledgers, and additive account-preserving upgrades.
- [x] Obtain explicit django-otp approval and implement authenticator enrollment/verification, required admin/approver MFA, restricted one-use lost-factor recovery, and generation revocation.
- [x] Obtain approval and implement private offline/admin-assisted password recovery with existing-MFA checks, audited identity-confirmation responsibility, and session/grant revocation; all-lost credentials remain fail-closed.
- [x] Implement an approved single-host Waitress/HTTPS-proxy serving contract with exact origin, private socket, secure cookies, explicit proxy trust, bounded requests, and private paired backups.
- [x] Bind authenticated **simulation** approvals/rejections to exact company/policy/evidence/scope/limits/expiry and implement revocation.
- [x] Join current company authorization checks to evidence review and B-01 simulation runtime in serialized transactions, preserving concurrency/accounting/settlement/rollback.
- [x] Verify local adversarial identity/permission/scope/replay cases and document the supported company-serving contract and remaining live gates.
- [x] Implement/test positive **live scope approval** with a default-denying trusted readiness interface, exact bindings, designated fresh-MFA human authority, expiry/revocation, and scope rechecks; manual/local evidence alone is blocked.
- [x] Keep live approvals distinct from simulation receipts, activation, task/budget reservations, and deployment/execution permission; test that no endpoint turns a live approval into a model call.

### Separate live-use/deployment gates — not unfinished B-02 authorization code

- [ ] Wire an explicitly approved real readiness verifier to independently verified company evidence and reviewed criteria. The controlled test verifier is not shipped or configurable through forms/JSON/CLI.
- [ ] Complete trusted task/run/subagent/provider admission and atomic runtime enforcement (B-04/B-05); authority checks alone create no execution reservation.
- [ ] Validate an owner-approved real company's TLS/proxy/storage/recovery/operational prerequisites. No real deployment is authorized by the serving code or passing tests.

B-02 authorization implementation is **complete**, as clarified by the owner:
finish the software boundary and its tests now, retain real evidence/deployment
validation separately, and do not require B-04/B-05 to be built inside B-02. This
does not claim the entire product or a live deployment is complete. Accepted
onboarding does not authorize private data access or provider requests.

### B-01 implementation checklist

- [x] Persist reviewed simulation state and validate ordered event history.
- [x] Validate current policy/approver/source and explicit new-task/repository/developer/category scope.
- [x] Reserve task/budget capacity before simulated admission; serialize concurrent updates.
- [x] Preserve exact settlement costs; disclose overruns/failures and pause unsafe continuation.
- [x] Preserve compatible developer overrides, safe fallback, and blocked unknown capability paths.
- [x] Implement pause/resume/revoke and default-only rollback with stale-revision protection.
- [x] Make exact retries idempotent and distinguish historical decisions from fresh admission.
- [x] Document a runnable local activation/admission/settlement/control flow without claiming live deployment.

B-01 is complete for **local simulation only**. Real boundary detection, company
identity, provider cap enforcement, and joined live feedback remain dependencies
of later packages; the end-to-end completion goal above is not complete.

**Build sequence:** existing offline foundation → local feedback/result linkage
and learning → category readiness → approved task observation/manual shadow
integration → senior/admin-authorized limited routing pilot → gateway export
and monitored rollback. Propose extra skills/packages before installation.

## Recommendation/feedback/outcome loop

- [x] Record owner-approved workflow decisions W-01 through W-08 in `WORKFLOW.md`.
- [x] Separate per-task senior acceptance from first-pilot authorization in product docs.
- [x] Define validated recommendation, local developer-role, per-task response,
  actual-model execution, and outcome records.
- [x] Link each response/result to the exact recommendation, task, and model used.
- [x] Test acceptance without actual use, wrong-model attribution, unknown/late
  results, duplicate feedback, rejects, failures, and overrides.
- [x] Implement an experimental count-based learner and explicit future manual
  application; prioritize senior feedback
  while retaining everyone else's permitted observations and negative results.
- [x] Add a preliminary senior-prioritized evidence ranking for manual review;
  do not present it as a trained recommendation policy.
- [ ] Validate senior-feedback weighting and evidence gates on validation data;
  never tune them to held-out test results.
- [x] Generate category-specific local-review reports without production-readiness claims or routing activation.
- [x] Test that per-task records and review ranking cannot authorize a pilot or modify policy/model selection.
- [x] Test that fitting/application preserve manual choice and cannot authorize activation.
- [x] Add separate designated senior/admin local approve/reject receipts bound to report/policy/scope.
- [x] Test category blockers, stale reports, approver designation, limited scope, and no routing activation.
- [ ] Implement and validate authenticated company pilot-approver gates.
- [x] Document the locally runnable feedback/result linkage demo before claiming integration.

**Done when:** the local workflow links suggestion/response/actual model/result,
uses role-aware feedback transparently, and preserves manual model choice. It
must not invent alternative outcomes or hide failures. Automatic routing and
company-wide collection remain later, separately approved integration work.

### Implementation log

| Date | Change | Result |
| --- | --- | --- |
| 2026-10-03 | Added validated imports, static rules, fallback, replay, and local reports. | First runnable offline implementation. |
| 2026-10-03 | Corrected two miscalculated test expectations after user approval; fixture data and exact assertions were retained. | Baseline cost is `0.46`; simulated cost is `0.345`. |
| 2026-10-03 | Renamed the application folder from `tarkado/` to `engine/`. | Imports, packaging entrypoint, and module execution updated. |
| 2026-10-03 | Added non-overwriting local policy export and development instructions. | 52 tests pass; rollout evaluation remains pending. |
| 2026-10-03 | Added model states, repeated task/sample pairing, conservative candidate evaluation, and rollout documentation. | 98 tests pass; no approval-state changes or live routing. |
| 2026-10-03 | Added local immutable snapshots, content-bound review records, expected-current checks, and rollback history. | 137 tests pass; no live selection or model-state changes. |
| 2026-10-03 | Added conservative secret checks, safe CLI diagnostics, private audit exports, and exact report-to-policy binding. | 180 tests pass; raw content and live routing remain unsupported. |
| 2026-10-03 | Reviewed official OpenCode V2 docs; added a scoped read-only session snapshot wrapper. | 210 tests pass including a local mock executable; live task-boundary capture remains pending. |
| 2026-10-03 | Added equal-task-weighted uncertainty and a conservative Hoeffding baseline after checking the primary paper. | 236 tests pass; incomplete/unattested intervals are withheld; live validation stays deferred. |
| 2026-10-03 | Owner finalized company workflow and separate first-pilot authorization; aligned documentation and engineering rules. | Documentation-only update. Feedback/result learning loop is explicitly unimplemented and the next priority. |
| 2026-10-03 | Implemented local roster, recommendations, per-task responses, actual-model records, result revisions, and senior-prioritized review ranking. | 276 tests pass; no model calls, trained policy updates, real identity verification, or routing approval. |
| 2026-10-03 | Added experimental validation-plan feedback learning, immutable source-bound artifacts, and linked future manual suggestions. | 306 tests pass; settings/results are not production-validated, and no routing is enabled. |
| 2026-10-03 | Added category-review reports and designated senior/admin receipts for local pilot simulation. | 331 tests pass; identity is unverified, limits are not enforced yet, and live routing stays disabled. |
| 2026-10-03 | Owner requested a goal to finish the remaining build; recorded packages B-01–B-07 and the joined workflow's completion criteria. | Planning/documentation only. B-01 is next; live data access, approval, and deployment gates remain separate. |
| 2026-10-03 | Implemented B-01 scoped local pilot runtime, reservations/settlement, state controls, and default-only rollback. | 372 tests pass; no model dispatch or live authorization. B-02 trusted setup/identity is next. |
| 2026-10-03 | Recovered all repository documentation and relevant implementation/tests; proposed B-02 company setup/trusted authorization and requested explicit deployment/identity choices. | Recovery baseline: 372 tests pass. Proposal/documentation only; no identity mechanism chosen, completed code rebuilt, dependencies installed, or local demo data overwritten. |
| 2026-10-03 | Owner accepted C-01–C-05 and separately approved Django 5.2 LTS/Python 3.13 with the original environment preserved; implemented the initial real account/company-setup slice in engine/company/. | 421 tests pass (49 new). Real local login/private invitations/current permissions and company configuration/history work; MFA/recovery, joined authenticated feedback/pilot authorization, and production deployment remain pending. No private-session access, provider calls, or demo-data replacement. |
| 2026-10-03 | Joined authenticated company accounts to existing manual shadow/response/reported-model/outcome contracts; added per-action role snapshots and additive task-table upgrade. | 469 tests pass (48 new). Actual loopback HTTP joined flow, role-history preservation, scoped access, retries/corrections, concurrency, and account-preserving migration are checked. No legacy data replacement, new dependencies, model calls, verified outcome/readiness claim, or live pilot authorization. |
| 2026-10-03 | Owner tried upgrade/serve against an empty company-demo-v1 store. Clarified first-time bootstrap and improved diagnostics to distinguish uninitialized versus incomplete state. | 471 tests pass (2 new). No administrator/password was created for the owner, and no existing state was reset or replaced. Remaining B-02 MFA/recovery and trusted pilot controls are still pending. |
| 2026-10-03 | Owner explicitly approved django-otp; implemented mandatory administrator/approver authenticator MFA and single-use lost-factor backup recovery. | 501 tests pass (30 new). Required proof, enrollment/replay/throttling, restricted replacement tickets, generation revocation, audit privacy, and actual loopback MFA flow are checked. Password recovery, trusted pilot authorization/runtime, and production deployment remain pending. No user credentials read, demo state reset, or provider calls. |
| 2026-10-04 | Owner requested full B-02 and approved offline/admin-assisted password recovery plus Waitress single-host HTTPS-proxy serving. Added joined company evidence, exact-scope fresh-MFA simulation approvals/rejections, B-01-backed activation/admission/accounting/reversal, and paired private backup. | 540 tests pass (39 new). Includes joined browser controls, recovery downgrade refusal, and serving configuration checks. Existing code/data retained. Full B-02 remains blocked for positive live authorization: current manual evidence is not verified readiness and no trusted live task/provider admission exists. No private sessions, provider calls, real proxy/certificate configuration, commits, or pushes. |
| 2026-10-04 | Owner clarified that B-02's remaining item is authorization code, not B-04/B-05 or actual deployment, and requested completion. Implemented the server-owned readiness-verifier contract, positive conditional live scope approval, independent live authorization history/withdrawal, and scoped authority rechecks. | 573 tests pass (33 new). B-02 authorization implementation complete; default verifier denies live approval, test-only positive evidence does not certify quality, and live adapter/deployment/evidence gates remain separate. No new dependencies, rebuilt components, user-data replacement, provider calls, commits, or pushes. |
| 2026-10-04 | Owner accepted browser-first B-03 on the existing Django app and a separate narrow B-04 developer connector; recorded UI-01–UI-03. | Planning/documentation only. OpenCode footer/panel/command examples are proposed UI, not an installed integration. Other platforms need separate capability checks/adapters; no skill/plugin/package installation, private access, or model calls. |
| 2026-10-04 | Owner requested B-03 implementation in a new session; saved HANDOFF_B03.md with recovery steps, accepted decisions, current implementation/tests, usability gaps, and constraints. | Handoff/documentation only. Last verified baseline remains 573 tests; no application/data/dependency changes, commits, or live access. |
| 2026-10-04 | Recovered the handoff and passing 573-test baseline, then completed B-03 on the existing Django application: task cards/guided linkage, independent evidence review, labeled validation and exact category/model/developer scope selection, signed browser confirmations, guided policy editing, readable guards/history/accounting, and owned settlement choices. | 605 tests pass (32 new browser/HTTP checks); B-03 complete for the accepted interface scope. All baseline tests retained; same-app laptop walkthrough documented. B-01/B-02, historical roles/corrections/negatives, and uncommitted user work preserved. No dependencies/migrations, B-04 connector, private sessions, model calls, demo-data reset, commits, pushes, real readiness verifier, or live deployment. |
| 2026-10-04 | Owner accepted explicit-task B-04 implementation with no Laya. Added scoped browser-issued delegated credentials, strict metadata-only API, additive connector records, inactive OpenCode V2 server/terminal plugin source, immutable retries/gaps, reported feedback linkage, interrupted-close recovery, and source-bound review diagnostics. | 637 Python tests pass (605 baseline + 32 connector/API/HTTP/runner checks); 14 JavaScript tests pass. Actual synthetic loopback browser/API flow and controlled plugin/core are tested, not installed OpenCode/TUI rendering or private task capture. B-04 remains limited/unverified at those gates; root-task only, no exact per-request usage or subagent inference. No dependencies/plugins installed, owner data migration/reset, Laya, model/provider calls, private sessions, commits, pushes, or live routing. |
| 2026-10-04 | Owner deferred installed-client/real-company checks while building and requested B-05. Added explicit learner publication/default-only reversal, future learned browser/connector tasks, immutable refusal/version history, frozen validation/current-negative checks, and conditional live-scope selection/accounting/one-use claim behind a default-denying admission interface. | 671 Python and 19 JavaScript tests pass; no assertions weakened. Includes connected feedback/learner flow, negative/gap monitoring, exact scope/override/budget/proof/claim binding, paused/revoked settlement/rollback, and concurrent shared limits. B-05 conditional build milestone, not full live delivery: atomic OpenCode/gateway task-model-provider-cap adapter is unfinished software. Real evidence/verifier/deployment and installed-client checks remain deferred; no Laya/dependencies/private access/provider calls/activation/user-store reset/commits/pushes. |

## Phase 0 — Product foundation

- [x] Create product, technical, research, decisions, and task documents.
- [x] Choose final repository name: Tarkado.
- [x] Finalize recommendation-first company journey, senior-prioritized per-task
  learning signals, and designated senior/admin approval for the first pilot.
- [ ] Choose an open-source licence.
- [x] Create Git repository and initial documentation commit.
- [ ] Interview or simulate the workflow of at least three engineering teams:
  how they select models, track spend, and test new models.

**Done when:** the first user/problem statement is sharper than “reduce LLM
costs.”

## Phase 1 — Offline policy simulator

- [x] Create a Python project with no runtime dependencies and a pinned build backend.
- [x] Define and validate `TaskTrace` and `PolicyDecision` schemas.
- [x] Add synthetic metadata-only fixtures with cheap, standard, and premium outcomes.
- [x] Validate JSONL/CSV imports, pairing, and canonical CSV column order.
- [x] Implement deterministic historical replay against a recorded baseline.
- [x] Implement explainable static policies based on task/risk tags.
- [x] Fall back for invalid/unknown recommendations; block if the default is incompatible.
- [x] Add unit tests proving observe/shadow modes do not enforce routing.
- [x] Add readable text and JSON local reports with unknown/negative results visible.
- [x] Export supplied versioned policies as local proposals without overwriting files.
- [x] Document the quickstart, input contract, safety limits, and development workflow.

`RolloutReport` is implemented in Phase 2. Replay and candidate reports are not
rollout approvals.

**Done when:** a local CSV/JSONL file produces a reproducible policy comparison
report without calling a real API.

## Phase 2 — New-model rollout evaluator

- [x] Define and validate the `RolloutReport` contract.
- [x] Add candidate-model registry state: candidate/shadow/approved/disabled.
- [x] Add baseline-versus-candidate report: cost, latency, outcome, failures,
  descriptive variation, and compatibility.
- [x] Add conservative shadow / collect-more-evidence / reject recommendations.
- [ ] Add category-readiness recommendations using linked senior feedback and
  independently validated task/result evidence; readiness alone never enables routing.
- [x] Add local policy snapshots, version/content validation, review records, and rollback metadata.
- [x] Add a constant/no-change baseline so the evaluator cannot claim a gain
  without comparison.
- [x] Import repeated JSONL samples and print per-task counts and score ranges.
- [x] Add conditional pointwise bounded-quality intervals across distinct tasks; repeated samples stay inside task means.
- [ ] Verify independent/representative evaluation design and any deployment threshold on real approved evidence.
- [ ] Test an old benchmark dataset only as an offline research fixture; do not
  claim production results from it.

**Done when:** a new candidate model can be evaluated and produce a transparent
go/no-go recommendation.

## Phase 3 — Privacy and safety

- [x] Implement a metadata-only offline input contract; raw-content fields are rejected.
- [ ] Implement raw-content opt-in configuration.
- [x] Add conservative secret-pattern rejection before metadata/audit/policy export and redact known-pattern diagnostics.
- [x] Add offline policy allowlist: automatic replay routes use only registered, approved models.
- [x] Add risk-tag fallback for high-risk/unknown tasks; block incompatible defaults.
- [x] Add offline audit records for every replay decision and recorded override, plus candidate-evaluation records.
- [x] Export private audit snapshots with hashed task references and exact policy-content fingerprints.
- [ ] Add live decision/override audit capture when the adapter exists.
- [ ] Add reviewed retention management and broader secret/customer-data handling.

Local history and offline per-task audits are implemented. Live capture,
authenticated approval, automatic retention, and raw-content opt-in remain
pending. Secret-pattern detection is a baseline, not comprehensive data-loss
prevention.

**Done when:** a team can explain what data is stored and why every routing
decision occurred.

## Phase 4 — OpenCode adapter (observe-only first)

- [x] Read current official OpenCode V2 plugin/client/API/model documentation before coding.
- [x] Decide whether the first adapter is a plugin, command wrapper, or local
  proxy; document the choice.
- [x] Add explicit session snapshot wrapper using documented GETs and company-API attestation.
- [x] Project only allowlisted selected-model catalog fields; no provider credentials/config reads.
- [ ] Verify capability provenance from explicitly approved configuration; resolved catalog defaults remain unverified.
- [ ] Capture permitted new-task/subagent-boundary events in observe mode.
- [ ] Map compatible model capabilities into Tarkado's registry.
- [x] Verify the snapshot wrapper never issues model/session mutation calls in mock tests.
- [x] Add mock OpenCode API/CLI integration tests with preserved session selection and omitted secrets.
- [ ] Validate an approved real-session snapshot without provider calls.
- [ ] Add live adapter integration tests using a local/mock provider after the boundary contract is defined.

Snapshot observation is session-level, not a task/subagent event. The wrapper
does not silently turn snapshots into replay traces or task-quality evidence.

**Done when:** Tarkado can observe an OpenCode workflow without exposing API
keys or changing a developer's selected model.

## Phase 5 — Shadow and pilot routing

- [ ] Return a Tarkado recommendation at a new task/subagent boundary.
- [ ] Show the suggested model, reason, confidence, fallback, and override
  option to the developer.
- [ ] Integrate manual shadow recommendations and per-task responses without
  additional alternative-model requests or automatic model changes.
- [ ] Continue approved usage/outcome monitoring for all participating developers;
  give senior feedback greater influence, not exclusive visibility.
- [x] Surface local category review and require designated local senior/admin receipts for simulation scope.
- [ ] Surface verified company readiness and require authenticated senior/admin approval for live pilot scope.
- [ ] Test role authority and pilot authorization independently of per-task feedback.
- [x] Add explicit repository/developer/category limits for local simulation.
- [ ] Connect trusted live repository/team scope to the coding-tool adapter.
- [ ] Apply automatic selection for juniors and seniors only within the approved
  scope, before task/run/subagent execution, with developer overrides.
- [x] Add persistent default-only rollback for local simulation without erasing accounting/history.
- [ ] Connect approved live-policy rollback to the task-level adapter.
- [ ] Measure developer overrides as a first-class quality signal.

**Done when:** a team can recommend manually, learn from linked actual results,
and enter a separately authorized limited routing pilot without losing control
of its coding workflow. Confidence cannot silently broaden scope.

## Phase 6 — Existing-gateway exports

- [ ] Design a stable policy YAML/JSON format.
- [ ] Research LiteLLM export/integration constraints.
- [ ] Add one gateway-policy exporter only after the local format stabilises.
- [ ] Document unsupported cross-agent/provider combinations clearly.

**Done when:** Tarkado can hand a versioned, explainable policy to an
existing gateway rather than becoming another gateway.

## Phase 7 — Optional intelligence improvements

- [ ] Establish simple-rule and random-selection baselines first.
- [ ] Evaluate embeddings or retrieval for similar-task matching.
- [ ] Evaluate active task selection for new-model testing.
- [ ] Evaluate Laya only against the same data, policy, and latency budget.
- [ ] Keep an advanced method only if it improves a measured result.

**Done when:** every “smart” feature beats a simple baseline or is removed.
