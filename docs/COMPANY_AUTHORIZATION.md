# B-02 company setup and trusted authorization

**Prepared:** 2026-10-03.
**Status:** Self-hosted invitation-only onboarding accepted on 2026-10-03.
The account/company-setup and authenticated manual task loop are implemented
using approved Django 5.2.17 and Python 3.13.12. Authenticator MFA and lost-factor
backup recovery use approved `django-otp 1.7.3`. Offline/admin-assisted password
recovery, company evidence and authenticated scoped simulation authorization,
B-01-backed runtime controls, and an approved Waitress HTTPS-proxy serving contract
are implemented. **B-02 authorization implementation is now complete**, including
the positive conditional live scope approval boundary against a default-denying
server-owned readiness interface. The real readiness verifier, B-04/B-05 execution
integration, actual deployment/TLS, and model-use/outcome truth remain unverified
or unconfigured; they are separate live-use gates, not completed by tests. The current
joined operation guide is [COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md).
This is not live-pilot approval.

This proposal follows [WORKFLOW.md](WORKFLOW.md), W-01–W-08. It extends the
existing local records and B-01 simulation runtime; it does not replace them.
Accepted onboarding decisions C-01–C-05 are in [DECISIONS.md](DECISIONS.md).

## Owner clarification — real product and laptop demonstration

The owner clarified that Tarkado must become a real company product while also
being demonstrable on their laptop. These are not mutually exclusive targets:
use the same application and real login/permission checks in both settings,
with deployment-specific security configuration. Do not build a separate toy
implementation or use mock identities as the demonstration's authority.

The owner also raised startups without existing company login. Do not assume
company SSO [employee single sign-on] exists or make it an adoption prerequisite.
Invitation-only individual Tarkado accounts are accepted as the initial login
path. Account/MFA enrollment and approved password-recovery mechanisms are
implemented. A protected single-host serving contract and conditional live
scope approval mechanics are available; real evidence and deployment/TLS
validation remain pending.

A laptop demonstration can use actual individual logins and durable company
state with an isolated synthetic evidence dataset. Synthetic evidence remains
clearly labeled, does not establish production readiness, and cannot authorize
live requests. Real-session collection/provider execution stays deferred. Any
loopback-only development configuration must not be exposed as a company server.

## Recovered implementation boundary

- `engine/feedback.py`: `TeamConfig`, linked records, and a private local store.
  Developer/reviewer IDs and roles are declared, not authenticated. The existing
  roster is immutable, so replacing it would also change historical attribution.
- `engine/learning.py`: experimental suggestions and source/freshness checks.
  These checks cannot establish identity, outcome truth, or readiness.
- `engine/readiness.py`: category review, a separate `ApproverRoster`, exact
  `PilotScope`, and local-only `PilotReview` receipts.
- `engine/pilot.py`: activation, new-boundary decisions, reservations/settlement,
  overrides, pause/resume/revoke, and default-only rollback. It accepts declared
  identities/scope and never dispatches a model.
- `engine/cli.py`: existing offline/local commands, not a protected company
  interface. A user able to edit local rosters can declare an approver.

Regression verification on recovery: **372 tests pass**. Existing uncommitted
implementation and local data must remain intact. Test results do not prove
production security, model quality, or savings.

## Implemented B-02 slice — individual accounts and company setup

Optional application code is in `engine/company/`. Existing offline modules are
not replaced and do not require Django at runtime. Company state uses a separate
private SQLite database [a local database file] and Django login sessions. Legacy
feedback/pilot JSON stores remain unchanged and are not automatically imported
or upgraded into trusted company evidence.

Available now:

- Explicit operator bootstrap into a **new** store, with an interactively entered
  password. No public signup, automatic first-web-user admin, default password,
  shared account, or implicit pilot-approver designation.
- Actual Django password verification and sessions; passwords use the framework's
  PBKDF2 hashing [slow one-way password storage]. Minimum password length is 15,
  with framework common/numeric/similarity checks. No custom password algorithm.
- Administrator-created, named invitations with selected roles/permissions,
  expiry within seven days, single-use consumption, and revocation. Only the
  random invitation's digest is stored. Its usable value appears once to the
  authenticated administrator for **private manual delivery**, not in a URL,
  email service, database, or audit event.
- Invited users choose their own passwords, then sign in. Enrollment does not
  automatically sign in the browser or let the recipient select a different
  username/role. An invitation proves possession of the private enrollment value,
  not independently verified employment; the administrator must deliver it to
  the intended person. Expired/revoked/used invitations are refused.
- Protected setup/account/history pages; current active membership/permission is
  checked server-side. Existing sessions lose access after membership is disabled.
  Junior/senior roles never imply admin or pilot-approval permission. Even a Django
  superuser without company membership cannot bypass this application's checks.
- Fresh administrator password verification before setup, permission, invitation,
  or revocation changes. Failed verification is retained even when the proposed
  change is refused. Eight failures in a rolling 15-minute account window block
  further verification until the window clears. This is an initial explicit
  authentication safeguard, not a production-validated abuse policy or protection
  against every distributed attack. Counters are not silently deleted.
- Existing `Policy` validation for model states/default/capabilities, explicit
  collection repositories and metadata-field scope, participating developer
  permissions, and company-managed API attestation. This does not start collection
  or authenticate provider credentials/capability provenance.
- Numbered company changes with server time, authenticated actor, reason, and
  before/after snapshots. Stale changes are refused, and SQLite IMMEDIATE
  transactions [reserve the writer before checking and changing state] serialize
  concurrent enrollment/configuration changes. The last active administrator's
  access cannot be removed through the ordinary control.
- CSRF protection [reject forged browser actions], restricted session cookies,
  POST-only logout, no-store/referrer/frame protections, and safe refused-form
  display. Supported suspected-secret values are not redisplayed as routing data.

**What this does not implement:** machine collector identity, automatic task
collection, independent outcome truth, an approved real readiness verifier, live
dispatch, automatic email delivery, actual public TLS/proxy validation,
multi-host coordination,
encrypted storage, tamper-proof history, or automatic retention. Approver
designation records future permission but cannot enable any live pilot endpoint.

## Authenticator MFA and lost-factor recovery — implemented

**Owner approved:** `django-otp` and authenticator-app MFA with single-use backup
codes on 2026-10-03. Installed/pinned version: `1.7.3`, with no other new package
required. No SMS/email provider, company SSO, QR-rendering package, or provider
requests are used. Time-based codes use the library's standard implementation,
not a Tarkado cryptographic algorithm.

- Administrators and designated pilot approvers must confirm an authenticator
  and verify it before protected company pages/operations. Password login still
  creates the initial session, but that session is restricted to enrollment,
  verification/recovery, and logout until required MFA is satisfied. An ordinary
  developer may opt into MFA; once enrolled, that account requires it too.
- Enrollment begins only after fresh password verification. A private manual
  setup key is displayed once, and a code must be verified before confirmation.
  Merely creating a device or submitting `verified: true` grants no access.
  Pending enrollment lasts 15 minutes; restart requires explicit cancellation,
  never silently deleting a confirmed factor.
- The authenticator configuration is time-based, six digits, 30-second period,
  issuer `Tarkado`; use the account name displayed in the application. No clock
  tolerance/drift sync is enabled: a current code and synchronized clocks are
  needed. A code used for enrollment/verification cannot be reused. Wait for the
  next unused code when necessary. Library throttling [delaying repeated failed
  verification] is enabled; failure counters commit rather than disappear on a
  refused operation. Concurrent verification of one code succeeds at most once.
- A verified session holds an account-bound generation and 15-minute verification
  proof. Expired, future-dated, malformed, cross-account, unconfirmed, revoked,
  or prior-generation proof does not grant access. Company administration and
  browser task operations recheck applicable MFA inside their transaction, not
  only when displaying the page. The local operator's internal Python access
  still controls the database; it is not a protected public API or a company
  identity-verification shortcut for future deployment.
- Confirmation generates eight random 16-character backup codes, displayed once.
  Each backup requires the current password and is consumed once. Successful use
  grants a five-minute **factor-replacement-only ticket**, not direct company
  admin access or pilot approval. Confirming the new factor revokes the old
  factor, remaining old backup codes, and older MFA session generations; it
  preserves company/task/budget history.
- Authentication security history records enrollment, verification failure,
  recovery use, and factor replacement without passwords, seeds, or codes. CSRF,
  no-store/referrer controls, and non-redisplaying password/code fields apply.

**Recovery distinction:** MFA backup codes recover a lost authenticator only.
Forgotten-password recovery now uses a **separate** private offline credential
or expiring MFA-admin-issued grant, plus existing enrolled MFA. See
[password recovery](COMPANY_OPERATIONS.md#password-and-account-recovery).
If all recovery evidence is lost, trusted administrator/operator identity
confirmation is required; database/role edits are not authenticated recovery.

**Storage/threat limitation:** the library stores TOTP seeds and usable backup
codes in the private SQLite store, readable to its trusted operator; they are
not encrypted at rest. Keep the whole store and backups private. Time-based codes
are not phishing-resistant. Operational key protection, backup handling,
HTTPS/proxy/operational validation and independent security review remain
requirements before company deployment. Implemented recovery/server controls do
not prove those deployment protections or make the complete company workflow live.

### Try MFA on the laptop

For the currently empty `local/company-demo-v1`, run **bootstrap once** using the
first-time command below, then `serve`; `upgrade` cannot create your first admin.
If you already bootstrapped a store, stop its server, preserve a private backup,
run `company upgrade` on that same store, then restart. Migration adds security
state and library device tables without resetting your account/task records.

1. Log in as your actual administrator. The application directs you to
   **Authenticator setup** rather than allowing password-only administration.
2. Confirm your password, then manually enter the displayed private setup key
   into your authenticator application with the configuration above. Do not send
   the key/code/password in chat or expose it in screenshots.
3. Open **Confirm authenticator**, enter its current code, and save the one-time
   backup codes outside the company/laptop database backup. Return to the company
   workflow and invite junior/senior accounts as before.
4. A later password login requires a current unused authenticator code. A
   designated approver must enroll too; seniority alone still grants neither
   approver designation nor routing permission.
5. For lost-factor recovery, select **Recover a lost authenticator**, supply the
   password and one backup code, and pair/confirm a replacement within the ticket's
   validity. This does not activate any pilot or modify your task history.

## Joined authenticated manual task loop — implemented

The company interface now calls the existing `Recommendation`, `Response`,
`Execution`, `TaskResult`, policy matching, and feedback-summary machinery. This
is no longer a setup-only interface, and it does not require copying fixture JSON
between commands. It is still **manual task metadata**, not live OpenCode capture.

### What is bound and enforced

- Actors and event timestamps come from the authenticated account and server,
  not a submitted developer/reviewer name, role, timestamp, or caller ledger.
- Task identity includes company, owner, and supplied task/session references.
  Session references are namespaced [kept distinct for each developer] before
  projection into the existing ledger. Supplying a reference does not read a
  real coding-tool session. Task boundary/source-kind labels are still declared.
- Every new task and record checks current participating membership, approved
  repository scope, and the metadata field allowlist. Out-of-scope non-null values
  are refused, never silently rewritten. Null/empty contract placeholders mean
  uncollected or unknown information; they are not invented measurements.
- Owners see and record their own tasks. Active participating seniors may see
  tasks in current approved repositories and supply the initial outcome review,
  but cannot accept another developer's suggestion or claim that developer's
  actual-model use. Company administrators can inspect retained history, but
  administrator-only accounts do not invent an engineering reviewer role.
- Removing participating access prevents further task writes, including reviews
  for a removed task owner. Removing repository scope blocks non-admin task reads
  and further collection; admin history remains available. Records are retained,
  and missing results remain visible rather than silently filled in.
- One shadow suggestion, immutable response, and actual-model record per task;
  append-only outcome corrections. Exact retries do not create more evidence.
  A response cannot be newly added after reported execution. Stale/branched
  corrections cannot replace a newer result. Initially only the prior outcome
  reviewer may correct it; another reviewer's replacement is blocked until
  disagreement handling is agreed, not treated as proof the first report is true.
- Old recommendations retain exact policy snapshots. Changed policy content
  requires a new version, rather than reusing a label and confusing old evidence.
  Reported use of another or unapproved model is retained as an observation and
  marked accordingly; recording it never approves or executes that model.
- Writes serialize current checks and event storage in the same SQLite
  transaction. A failed/interrupted operation cannot leave an extra task revision
  without its event. Reads validate event order, links, payload/time/actor binding,
  and the saved recommendation. This detects inconsistent state, not coordinated
  rewriting by an operator who controls the database.

### Historical role attribution and evidence limitations

Company task events preserve role snapshots [the role held when each action was
recorded]. Promoting a junior does not make their old task, acceptance, or review
senior evidence. Current roles control access; historical roles control attribution.

The engine's unchanged schema-1 ledger still uses declared local roster roles.
An additive schema-2 projection includes a `role_attributions` entry for every
recommendation, response, execution, and result. The company application creates
these entries from its authenticated events. **A schema-2 JSON file alone is not
authentication**; ordinary imported labels/hashes remain unverified. Legacy
writers cannot discard these entries or silently downgrade the ledger. No old
demo ledger is imported or retroactively certified.

Existing summary/experimental-learning methods retain those role snapshots and
negative signals; they are not replaced with a new scoring system. The browser's
summary shows all evidence in its permitted view, including unknowns, failures,
rejects, overrides, and correction history. A personal/current-repository view
is not whole-company readiness. Synthetic/team source counts are separate visible
labels, not provenance proof; mixed diagnostic counts are not deployment evidence.

Authentication proves who submitted a record under the installation's trust
model. It does not verify which model actually executed, whether tests ran, what
they cost, or whether the desired engineering result was achieved. Acceptance,
login, a source label, or API completion cannot establish success or pilot approval.
Company category review now fits the existing experimental learner from explicit
validation plans. Stored, authenticated **simulation** approvals and B-01 controls
are joined to those records. Future learned manual-suggestion application, actual
task capture, actual verified readiness, and live execution remain pending.
The positive live scope approval code now exists behind a default-denying trusted
readiness-verifier interface; see
[the live boundary contract](COMPANY_OPERATIONS.md#b-02-live-authorization-boundary--implementation-complete).

### Continue from your existing laptop installation

If you already bootstrapped the company database, **do not bootstrap again**.
Stop its development server, preserve a private operator-controlled backup of
the stopped store, and apply the shipped additive migration:

```sh
.venv/bin/python -m engine company upgrade --store local/company-demo-v1
.venv/bin/python -m engine company serve --store local/company-demo-v1
```

Use your actual store path, not a fresh store to evade existing history. Upgrade
creates task/event tables; it does not replace accounts, company configuration,
secret keys, or legacy feedback/pilot stores. No reset, reverse, or fake migration
flag is provided. Existing-state migration preservation is tested on synthetic
accounts; it is not a backup/disaster-recovery guarantee.

After signing in as an invited junior or senior:

1. Open **Linked manual task workflow → Request a manual shadow suggestion**.
   Choose `synthetic` for the demonstration, an approved repository reference,
   a new-task/run/subagent boundary, and metadata-only task/session labels.
2. For the fictional documentation example, enter category `documentation`,
   justified risk `low`, selected model `fixture/premium`, tool requirement
   `read`, and context requirement `2000`. The existing policy suggests
   `fixture/cheap`; the original selected model remains unchanged and no request
   runs. These values demonstrate mechanics, not production thresholds.
3. Record that task's accept/reject response. Record the model actually used
   separately, or use fictional reported use for this synthetic demonstration.
4. Record a known/unknown outcome with a metadata-only evidence reference when
   required. Leave unknown tests/costs/results blank or `Unknown`; do not guess.
   An authorized senior may supply the first review for a junior task.
5. Inspect the exact linkage and authenticated action/role history. Correct your
   own result through its current result reference rather than overwriting it.
6. Compare the owner/senior/junior views. The administrator sees retained company
   history; a junior cannot see another developer's task. Failures and pending
   results stay in the permitted summary.

The same authenticated HTTP flow is tested from bootstrap/invitation through
login, recommendation, response, actual-model record, and result on the actual
loopback server. No model/provider or private-session access is part of this demo.

The loopback [this laptop only] development launcher remains available. A separate
approved Waitress/private-socket company-serving path is now implemented in
[COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md#single-host-company-serving-path).
It binds `127.0.0.1`, refuses unrelated hosts, and uses `DEBUG=False`. Its HTTP
development server is **not a production deployment**; do not expose/tunnel it to
other machines. Network deployment still needs reviewed HTTPS, secure-cookie and
proxy/key/operational validation and independent review. The serving code does
not set up a real TLS proxy or certify production operations.

### Run the actual-account laptop demonstration

The approved environment already has the company dependencies. For another
supported environment, install the pinned `requirements-company.txt` only with
the operator's approval. Use `.venv/bin/python` for every Python command.

Choose a **new**, private, Git-ignored store. The following example configures
fictional models and does not authorize company work:

```sh
.venv/bin/python -m engine company bootstrap \
  --store local/company-demo-v1 --name "Tarkado laptop demonstration" \
  --username owner --policy tests/fixtures/policy.json \
  --repositories synthetic-repository --company-api

.venv/bin/python -m engine company serve --store local/company-demo-v1
```

Bootstrap asks you to set the first administrator's password privately; none is
shipped in the repository. Open `http://127.0.0.1:8000`, sign in, and:

Complete mandatory administrator authenticator enrollment first, following
[Try MFA on the laptop](#try-mfa-on-the-laptop). Save the private backup codes;
they are not shown again and do not recover a forgotten password.

1. Open **Invitations**, create junior and senior accounts with explicit expiry,
   enter a reason, and confirm the administrator password.
2. Deliver each displayed private invitation value to its intended test user.
   Use a separate browser/private window to open `/join/`, paste that value, and
   choose the invited account's password. It then signs in through `/login/`.
3. Verify junior/senior access to the company page but refusal of admin pages.
   A senior is not automatically a pilot approver.
4. Use the admin **Accounts** page to disable an account or change permissions.
   The existing browser session must lose denied access. Inspect **Change history**.
5. Inspect or change the existing engine policy/collection scope through
   **Policy and collection**. Changes require the current revision, reason, and
   fresh password. This does not replace old demo data or turn on collection.

Stop the development server with Ctrl-C. Inspect the same installation without
starting a server:

```sh
.venv/bin/python -m engine company status --store local/company-demo-v1
```

**If you see "Company installation is not initialized":** the selected store
has no company database/key yet. Run the bootstrap command above once, then
serve it. `upgrade` updates an existing installation; it does not create your
first account. An empty directory from an unsuccessful serve/upgrade attempt
does not mean setup completed. Do not share your password in chat or command
arguments. If the error says the store is **incomplete**, preserve existing files
and inspect/restore a matching backup; do not bootstrap/reset damaged state.

Bootstrap refuses existing key/database paths and existing account/company state.
Restart with `serve`, not bootstrap. A failed/partial migration is not automatically
reset; inspect it rather than discard files. Private files are owner-only
(`0700` directory, `0600` database/key); existing loose permissions are refused,
not changed. Use a trusted local path; hostile parent directories/filesystem races
are not comprehensively protected. The operator who owns the store remains trusted.

### Environment approval and preservation

The owner explicitly approved Django 5.2 LTS and transition to the already
installed Python 3.13, preserving the previous environment. Installed versions:
Python `3.13.12`, Django `5.2.17`, `asgiref 3.12.1`, `sqlparse 0.6.0`, and
approved `django-otp 1.7.3` and `waitress 3.0.2`.
The original Python 3.9 environment is retained at:

```text
local/environment-backups/python39-20261003-6f67cfa7502045038c6077fc893132ed
```

This is preserved environment content, not a guarantee that all moved console
scripts work without restoration/recreation. No existing research packages were
deleted; the new `.venv` intentionally installs only the approved company
dependencies. The offline engine still supports its existing Python contract;
the company CLI requires Python 3.12 or later. Do not deploy unsupported Python 3.9.

Run the full suite (requires the approved company dependencies):

```sh
.venv/bin/python -m unittest discover -s tests -q
```

Verification includes real Django accounts, browser form flows, concurrency,
and an actual loopback HTTP login/server check using temporary synthetic stores.
It does not use a live company, OpenCode session, existing credentials, or providers.

## Accepted deployment direction and remaining technical design

Use one company-controlled installation with an authoritative store [the current
source of company permissions and approvals]. Only its service account may write
that store. Developers interact through a protected interface, not shared,
developer-editable approval JSON. This is a policy service, not a model gateway;
OpenCode/the existing company gateway still sends model requests.

Two possible login paths must enforce the same company permissions:

- **Standalone individual accounts:** accepted initial path for startups without
  an identity system. An explicitly appointed administrator invites/provisions
  participants; no corporate email domain or external login provider is required.
  Use a maintained authentication framework for password storage and login
  sessions, not hand-written credential or cryptographic code. The framework and
  any dependencies need owner approval before adoption.
- **Existing company login:** optional later integration using OpenID Connect [a standard
  for verifying a login] or an already deployed identity-verifying proxy [a
  protected entry point that checks login]. Which integrations belong in the
  first release is resolved: SSO is not required for the initial release. No
  specific SSO provider or adapter is selected or authorized for implementation.

Standalone accounts do not automatically prove employment or seniority. The
trusted administrator assigns membership and authority to the intended person;
login then proves control of that person's enrolled credentials. Invitation
delivery, account recovery, initial administrator enrollment, and stronger
verification for pilot approval must be designed explicitly. There must be no
public first-user-admin rule, shared team login, or shipped default password.

Actual login security needs password/session safeguards, protection from repeated
guessing, request-forgery defenses, and reviewed recovery/revocation. Approved
authenticator MFA is now mandatory for administrators/pilot approvers. Backup
codes provide limited lost-factor recovery; separate offline/admin grants now
provide password recovery without dropping MFA. Pilot authorization and recovery
issuance require fresh password plus unused authenticator verification.
Network deployments also need
protected transport, hardened server configuration, and operational review.

Mock verifiers are useful for isolated tests but cannot be the only implementation
behind a claimed real laptop login or company deployment. A foundation with only
mock identities would remain **B-02 partial work**, not trusted authentication.

### Identity and permission boundary

1. Establish identity at the selected protected entry point. Reject missing,
   forged, expired, wrong-company, or unsupported identity proof. A submitted
   `reviewer_id`, role, or `authenticated: true` flag is not proof.
2. Resolve company membership, current role, and explicit permissions from the
   authoritative company configuration, never the task/feedback payload.
3. For standalone accounts, resolve the enrolled account from a verified login
   session and recheck current membership/permissions. Account creation or
   possession of an email address alone never grants senior/admin authority.
4. For an OpenID Connect choice, bind accounts to the verified issuer and subject
   [login authority and stable account identifier], not a matching email/domain
   or display name. Use reviewed verification for signatures, issuer, audience
   [the intended application], expiry, and login replay protection.
5. For a proxy choice, prevent direct access around the proxy and strip/replace
   user-supplied identity headers. Merely reading a header from any caller would
   still be unauthenticated. Its protected transport must be reviewed and tested.
6. Deny unsupported operations by default. Check permission and record ownership
   on reads as well as writes. Seniority affects feedback interpretation but
   never automatically grants permission to administer or approve pilots.
7. Distinguish human reviewers from machine collectors. A collector may submit
   approved observations only through its own explicitly scoped identity; it
   cannot claim a human's per-task acceptance or pilot approval.

### Company setup

Propose an explicitly bootstrapped company administrator [an initially designated
operator], not public first-user signup or automatic admin access for an email
domain. That administrator manages:

- permitted participants, developer-role assignments, disable/revocation state,
  and separate pilot-approver designations;
- approved model/capability configuration and an approved compatible default,
  reusing the current registry/policy contracts;
- explicit repository/developer collection scope and a metadata field allowlist
  [the fields collection may retain], without silently collecting other work;
- revisioned configuration [numbered changes], recorded actor/time/reason, and
  retention settings whose actual implementation status is disclosed.

Role/membership changes must not rewrite past records, discard failures, or
retroactively certify existing locally declared identities. Preserve historical
role/configuration attribution separately from current access permissions.
Unknown task categories/results remain representable; collection scope must not
filter out inconvenient failures or imply every observed category can be routed.

### Separate pilot authorization

The protected approval operation must show and bind all significant reviewed data:

- company and deployment identity;
- unique pilot/approval IDs;
- exact policy version and content, learner, and evidence-report references;
- repository, developers, task categories, and category/model mappings;
- task/budget caps and explicit authorization validity;
- verified approver identity, current explicit designation, decision, time,
  reason, and configuration revision.

Use server-controlled time and replay protection [rejecting reuse as a new
authorization]. Exact retries may return existing history but cannot restart a
pilot, reset accounting, or revive a revoked approval. Changed reviewed content
requires another explicit review, not a client-supplied replacement fingerprint.
Login, per-task acceptance, and readiness remain separate from this operation.

For a single authoritative installation, prefer storing approvals there and
checking their current state, instead of trusting detached JSON receipts. A
content hash is not authentication. An export may be a reference/copy but must
not become independently usable execution permission. Offline portable signed
approvals would be a separate, more complex design, not a default requirement.

Before activation, resume, and each new-task/run/subagent admission, recheck
current authorization, membership, model approval, exact scope/content, validity,
and revocation. Serialize those checks with admission/accounting so a concurrent
revocation or configuration change cannot pass between checking and reserving.
A different local store must not duplicate the same company's pilot allowance.

Revocation prevents subsequent admissions. Preserve outstanding settlements,
costs, failures, history, and default-only rollback; do not switch an in-flight
task. Identity failure denies protected collection/administration/admission.
Missing routing evidence/approval keeps existing manual selection or an approved
compatible fallback; it does not authorize an extra provider request.

## Proposed implementation and verification scope after agreement

1. Add company configuration/history and a fail-closed authorization boundary
   [refuse access when identity or permission cannot be established].
2. Join those checks to existing feedback/review/runtime operations rather than
   create another unrelated report. Preserve old local demonstration commands as
   explicitly untrusted simulation paths, never company authorization fallbacks.
3. Add the selected identity verifier and protected deployment entry point only
   after the environment and any needed dependencies are approved. Real-session
   access and provider requests remain deferred.
4. Test impersonation, non-designated seniors, cross-company/record access,
   revoked participants/approvers/models, changed scope/policy, expired proof,
   retry/replay, concurrent revocation/admission, and preserved settlement/history.
5. Test that simulation receipts, imported local labels, learner artifacts, and
   per-task acceptance can never enter the trusted company-approval path.
6. Keep `docs/TASKS.md` and the limitation statements aligned with the implemented
   scope. No authentication or production-readiness claim from mocks alone.

Only the explicitly approved Django, django-otp, Waitress, and required dependencies were
installed. No private OpenCode sessions, existing credentials, or real model
provider endpoints were accessed. Test accounts/keys are created in temporary
synthetic stores, never in existing user demonstration stores.

## Technical choices still needed before the corresponding implementation

1. Integrate an approved real company readiness verifier and reviewed criteria
   into the completed live-approval contract. Current manual/local reports alone
   and the unconfigured default checker are still refused even with approver MFA.
2. Validate the real deployment's TLS/proxy/key/backup/operational setup. Recovery,
   fresh sensitive-action verification, exact-scope simulation authority/runtime,
   and single-host serving code are implemented, not a claim of deployment review.
3. Continue B-04/B-05 task/provider admission, real task/outcome validation, and
   learning/manual-application integration under approved scope. Never relabel old
   local records, treat an authority check as an execution ticket, or invent evidence.
4. Identify the first operator when enrollment is configured. Synthetic names
   suffice for isolated tests, but fake role labels cannot authenticate the real
   demonstration or company controls.

Authorization lifetimes, actual collection scope, production evidence thresholds,
and deployment credentials remain separate explicit configuration/approval
inputs. No numerical production defaults are chosen here.

## Primary guidance checked for this proposal

- [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html):
  separate authentication from authorization, deny by default, check permissions
  on every request, enforce server-side, and test access-control failures.
- [OWASP Transaction Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html):
  acknowledge significant transaction data, protect state transitions and reviewed
  content, and recheck authorization before execution.
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html):
  primary protocol reference if the owner selects company OpenID Connect login.
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html):
  password/session protections, login-attempt limits, account recovery, and
  additional verification for sensitive operations.
- [Django 5.2 authentication](https://docs.djangoproject.com/en/5.2/topics/auth/default/),
  [password validation](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/),
  [transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/), and
  [deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/):
  checked for the approved framework implementation. Core login does not supply
  every needed deployment/abuse/permission control; this application adds explicit
   company permission checks and an initial account-attempt limit; MFA uses
   separately approved django-otp rather than the core Django login alone.
- [Django 5.2 Python compatibility](https://docs.djangoproject.com/en/5.2/releases/5.2/)
  and [Python 3.9 final support period](https://www.python.org/downloads/release/python-3925/):
  the supported-runtime transition was discussed and separately approved.
- [Django 5.2 migrations](https://docs.djangoproject.com/en/5.2/topics/migrations/):
  checked before adding task tables and an explicit upgrade command. SQLite
  migration and operational limitations do not establish production readiness.
- [django-otp official overview](https://django-otp-official.readthedocs.io/en/stable/overview.html):
  checked for confirmed-device verification, replay tracking, throttling, and
  single-use backup devices. The installed library source was inspected before
  integration; legacy migration advice is not applied to this fresh integration.

These are security guidance, not certification that Tarkado satisfies every
recommendation. The unsupported production/live gates above remain in force.
