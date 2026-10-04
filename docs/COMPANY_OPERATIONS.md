# Company operations and joined authorization walkthrough

**Updated:** 2026-10-04. **Implementation boundary:** actual accounts/MFA and
recovery, category evidence, scoped simulation controls, conditional live scope
approval/revocation, and a single-host HTTPS-proxy serving path are implemented.
**B-02 authorization code is complete and tested**, not a completed live company
deployment. The readiness verifier defaults to refusal; a real verified evidence
integration, trusted task/provider execution, and operator-approved deployment
remain separate gates. This guide supplies no credentials or actual live approval.
See [TASKS.md](TASKS.md) and [WORKFLOW.md](WORKFLOW.md).

This reuses the existing engine and B-01 journal/accounting. It does not rebuild
the router, import old unsigned demo receipts into trusted company state, replace
model transport, or create alternative-model requests.

## Start a laptop installation

Run from the repository root with the approved Python environment. For a **new**
store, create the first administrator once:

```sh
.venv/bin/python -m engine company bootstrap \
  --store local/company-demo-v1 --name "Tarkado laptop demonstration" \
  --username owner --policy tests/fixtures/policy.json \
  --repositories synthetic-repository --company-api
```

The password is prompted privately, never provided in arguments or shipped with
the code. `--pilot-approver` is an optional **explicit** first-administrator
designation; without it the admin may configure the company but cannot authorize
a pilot. Existing seniority/task acceptance never supplies that designation.

For an **existing** store, stop its server, back it up privately, and apply shipped
migrations instead of bootstrapping again:

```sh
.venv/bin/python -m engine company upgrade --store local/company-demo-v1
```

Then start the local-only interface:

```sh
.venv/bin/python -m engine company serve --store local/company-demo-v1
```

Open `http://127.0.0.1:8000`. Complete actual administrator authenticator setup,
save one-use MFA backup codes privately, invite juniors/seniors, and explicitly
designate an administrator/senior as pilot approver through **Accounts** if needed.
Do not expose/tunnel the development server to other machines.

## Password and account recovery

While logged in with confirmed MFA, open **Save private password-recovery
credential**. Enter the current password and a fresh unused authenticator code.
One random offline credential is displayed once; only its digest is stored.
Keep it offline, outside the server/backup, and never in Git, chat, or screenshots.
A new personal credential revokes earlier personal credentials.

For forgotten-password recovery, open **Forgot password? Use private recovery**:

1. Supply the account name, private recovery credential, and new password twice.
2. Supply a current authenticator or an unused MFA backup code if the account has
   an enrolled factor. Password recovery does not disable that factor.
3. On success, log in normally again. Recovery does **not** automatically log in.
   Old login/MFA sessions and outstanding reset grants are invalidated; roles,
   revoked access, task history, approval content, and accounting are preserved.
4. Reissue a new offline credential after recovery. Recovered approver identity
   invalidates previous pilot admission authority through its MFA generation.

An MFA-verified company administrator may use **Audited administrator-assisted
password recovery** only after separately verifying the intended person's identity.
It requires the admin's fresh password/code, exact target account, reason,
metadata-only identity-confirmation reference, and expiry within one hour. Deliver
the displayed grant privately to that person; it is not sent through email/SMS.
It cannot restore disabled membership, appoint roles, or remove existing MFA.
Revoking the issuing administrator also invalidates outstanding assisted grants.

Identity confirmation is the trusted administrator's responsibility, not proof
created by a text reference. Failed attempts are bounded by the account-attempt
window and do not alter the target's password/membership. No public reset-anyone
endpoint, secret question, default reset password, or role-spoofing bypass exists.
If a sole administrator loses **all** personal recovery/MFA evidence and no other
trusted admin can verify them, fail closed: use the company's approved operator
identity/recovery process, not database resets or edits masquerading as login.
Tarkado does not independently verify human employment/identity documents.

## Joined evidence → separate authorization → runtime

**B-03 usability update:** follow [BROWSER_WORKFLOW.md](BROWSER_WORKFLOW.md) for
the current joined interface. Work sessions/categories/developers and owned
settlement tasks are selected by readable labels; copying projected session IDs,
policy JSON, or decision IDs is no longer part of the normal browser workflow.
Evidence review is independent of approver-only scope decisions. Scope/control
previews require explicit browser confirmation plus the existing fresh-MFA checks.
All manual/source/live-use limits below remain unchanged.

1. Use the existing **Linked manual task workflow** as invited developers. Record
   a manual shadow suggestion, accept/reject before reported execution, actual
   model used, and known/unknown result. Use `synthetic` for demonstration data.
   Authentication binds submitters and historical roles, not outcome truth.
2. Open **Category review and separate pilot controls → Prepare category evidence**
   as an explicitly permitted admin/approver with MFA. The form lists labeled
   developer/work sessions with internal reference resolution. Supply an explicit **validation** plan: version, source,
   sessions, categories, cutoff, and minimum success/session parameters. They are
   experimental inputs, not production-approved thresholds. Do not use held-out
   tests to tune them or discard junior failures.
3. Review all category evidence and gaps. Existing `fit_feedback` and
   `build_readiness` produce stored source/policy-bound artifacts. The company
   projection retains every record of the selected source, including historical
   removed actors/failures; source labels do not prove provenance. Enrolled
   participants without records are roster members, not fabricated successes.
4. A **designated** senior/admin separately approves or rejects the exact scope:
   pilot ID, policy/report, repository, developers, categories, caps, expiry,
   reason, current company revision, password, and a fresh unused MFA code.
   Task acceptance/readiness cannot create authorization. Changed evidence or
   policy must be reviewed again. Existing unsigned receipt JSON is not imported.
5. For the ordinary laptop demonstration select **Authenticated simulation only**.
   The default installation has no real trusted readiness verifier: positive
   **Live scope approval** is refused even for a genuine MFA approver. The software
   now supports that conditional approval when a server-owned checker supplies
   independently verified company readiness; it still cannot enable execution.
   See the live boundary below. A rejected scope grants no routes. A content hash
   binds consistency, not standalone identity; the company store is the authority.
6. Explicitly activate that stored approval using another fresh password/code.
   One company can have one active/paused pilot at a time; a new pilot requires a
   separately reviewed unique ID. Activation cannot reset old accounting.
7. Share the pilot's **Scoped simulated new-task admission** link privately with
   scoped developers. Supply metadata, a new-task/run/subagent boundary, positive
   reservation, and optional override. No model executes; actual selection stays
   unchanged. Do not claim these simulation records are training outcomes.
8. The developer selects their recorded task and supplies actual simulated cost and
   completed/failed/cancelled accounting outcome through **Settle your simulated
   task**. Unused reservation is released; admitted task slots remain consumed.
   Failures/overruns pause; complete costs and negative remaining budget are kept.
9. Inspect revision, scope, guard [current authorization checks], journal, and
   accounting. Pause/resume/revoke/default-only rollback require designated
   authority, fresh verification, reason, and expected revision. Resume refuses
   stale evidence, invalid authority, or failures/overruns under unchanged approval.
   Revocation/rollback preserve pending settlement/history and prevent fresh
   admission; exact decision retries are historical records, not new permission.

Admission checks company/deployment identity, current revision, approver
membership/designation/MFA generation, exact source/report/policy, expiry,
revocation, scoped developers/repository/categories, compatibility, and limits.
Those checks and accounting share one SQLite IMMEDIATE transaction [reserve the
writer before checking/changing state], rather than unlocked JSON-to-database
dual writes. Concurrent admission/revocation/settlement is tested. The underlying
B-01 state machine, fallback, overrides, overrun preservation, and rollback are
reused, not replaced. No API provider cap or real boundary detection is claimed.

## B-02 live-authorization boundary — implementation complete

This is the remaining B-02 software boundary completed at the owner's request.
It does **not** require implementing the B-04 adapter or collecting real company
evidence now. Those are later integration/deployment gates, not authentication
work to rebuild. Existing simulation reports/receipts remain local-only and are
not relabeled or converted into verified live evidence.

### Independent evidence check, then separate human approval

`engine/company/readiness_gate.py` defines `ReadinessVerifier` and immutable
request/assessment contracts. The server constructs a request bound to the exact:

```text
company_id, deployment_id, company_revision, review_ref, review_sha256,
report_sha256, policy_sha256, feedback_sha256, learner_sha256, scope_sha256
```

A real approved verifier must consult independent company outcome/evaluation
evidence, reviewed criteria, source freshness, and revocation. A passing local
category report, caller's `team` label, confidence, or per-task acceptance does
not satisfy it. A valid assessment returns canonical fields:

```text
verifier_id, evidence_ref, criteria_version, request_sha256, verified_at,
valid_until, outcomes_verified, evaluation_design_verified, criteria_validated
```

The assessment must bind this exact request, have current bounded validity, and
confirm all three independent verification requirements. No numerical production
criterion is chosen by B-02. Invalid/untyped results, outages, future/expired
evidence, changed criteria, or source mismatches block authority.

Only trusted application code may install the verifier instance in
`TARKADO_READINESS_VERIFIER`. There is **no** form field, CLI switch, JSON import
path, or browser/header flag to do so. Both shipped launchers configure it as
`None`, which uses the default-denying implementation. The controlled verifier
in `tests/test_live_authorization.py` is **test-only**, not a product evidence
verifier or installable demonstration shortcut. A real implementation and its
company criteria must be explicitly approved and validated when B-05 evaluation
is connected. Do not paste a fabricated positive assessment or disable this gate.

After that independent check, a separately designated senior/admin must still
provide fresh password/MFA and approve the exact policy/report/repository/
developers/categories/caps/expiry. Readiness alone cannot create that decision.
Approval cannot outlive its assessment. Synthetic/blocked evidence cannot approve
live scope even if a misconfigured checker returns a positive result. A live
rejection may be recorded without granting any assessment, routes, or authority.

### Stored authority is not execution permission

Live scope decisions are separate versioned `company_live_pilot_authorization`
records, not unsigned `local_pilot_review` receipts. They retain exact bindings,
verified-assessment references, designated actor/MFA-generation snapshots, and
ordered approval/withdrawal events. Revision `1` is the immutable decision;
`revoke` or default-only withdrawal adds revision `2`. No resume, reapproval under
the same pilot ID, duplicate authorization, or budget restart revives it.
Withdrawal does not need a still-working evidence checker, and old data/history
is preserved. Simulation journals are unaffected.

`live_guard` rechecks current company/model/evidence/criteria/role/MFA validity,
assessment identity, expiry, and revocation. `check_live_scope` additionally
checks the logged-in developer, exact repository/category/model, low-risk
metadata, compatibility, and a new-task/run/subagent boundary. It returns only
`authority_current`/`scope_current` plus diagnostics. It explicitly returns:

```text
new_reservation: false
execution_authorized: false
routing_enabled: false
deployment_authorized: false
```

This is a B-02 authority check, not a spend/run ticket. B-04/B-05 must establish
the real task boundary/scope and atomically join authority, accounting,
overrides/fallback, and provider admission before execution. Calling the check
with declared metadata cannot establish that boundary. Simulation activation,
decision, and settlement endpoints explicitly refuse live approvals; the live
status page hides simulation links and cannot activate models.

### Update an existing installation

With the server stopped and a private backup made, run `company upgrade` on the
same store. The additive `0005_live_authority_history` migration adds independent
live-authorization revision/history fields without replacing old accounts,
feedback, or simulation journals. `company status` reports that live scope approval
mechanics are supported and whether a real trusted checker is configured; that
flag is not a quality or deployment-readiness claim. A new store still needs the
first-time bootstrap above, not upgrade.

## Single-host company-serving path

The owner approved Waitress `3.0.2`. Approved/pinned dependencies are in
`requirements-company.txt`; the offline engine still needs none of them at runtime.
This path supports **one macOS/Linux host, one private company database, and a
private Unix socket**. It is not multi-host, hosted SaaS, a generic gateway, or a
claim that SQLite meets arbitrary production scale/availability needs.

Before actually deploying, the operator must provide:

- an explicit company HTTPS origin and working, reviewed TLS proxy/certificate;
- a dedicated trusted service/proxy account with private state/socket access;
- company-approved collection/model credentials/evidence and scope (no consumer
  subscriptions), permission/recovery administrators, retention, and monitoring;
- protected backups and reviewed storage/key safeguards; MFA seeds and private
  credential material are currently **not encrypted at rest**;
- reviewed platform capacity, process supervision, dependency updates, and
  independent security/evaluation checks. Local tests do not certify these.

Create a private Git-ignored config such as `local/company-deployment.json`
with owner-only file permissions. Example (placeholders, not a deployed company):

```json
{
  "public_origin": "https://tarkado.company.example",
  "https_proxy_configured": true,
  "private_single_host": true,
  "backup_policy": "Private operator backup and tested recovery procedure",
  "operator_contact": "designated-company-operator"
}
```

Confirmations are operator attestations, not an automatic TLS audit. The code
requires an exact HTTPS origin, denies wildcard/development hosts, refuses missing
migrations or existing sockets, and does not modify real proxy/certificate files.

Start only after the operator has satisfied those prerequisites:

```sh
.venv/bin/python -m engine company service \
  --store local/company-demo-v1 --deployment local/company-deployment.json
```

Waitress listens only at the private store's `company.sock` (`0600`), not on a
public TCP port. The HTTPS proxy must run with explicitly authorized socket access,
validate the company host, **overwrite** client forwarding headers, and send the
exact company `Host` and `X-Forwarded-Proto: https`. Only that scheme header is
trusted from the private local proxy; other forwarding headers are cleared and
caller identity/role headers never authenticate anyone. Do not relax the socket
to world-writable or trust arbitrary Internet proxy peers. For an existing nginx
proxy, the operator-reviewed location has the equivalent of:

```nginx
location / {
    proxy_set_header Host tarkado.company.example;
    proxy_set_header X-Forwarded-Proto https;
    proxy_pass http://unix:/absolute/private/company/store/company.sock;
}
```

That fragment does not configure TLS, DNS, permissions, or a full nginx service.
Do not deploy it blindly. No nginx/system package was installed or configured.
Django requires the resolved secure scheme and exact public origin, `DEBUG=False`,
secure session/CSRF cookies, bounded body size, CSRF/origin protections, and HSTS
[ask browsers to keep using HTTPS]. Setting an untrusted forwarded header at
Django does not bypass the gate. Waitress bounds request headers/bodies/connections
and does not expose tracebacks. Actual private-socket serving plus resolved scheme
and host rejection are tested; a real public TLS proxy has not been validated.

## Backup, upgrade, and rollback responsibilities

Stop the service for maintenance; preserve the matching database/key pair. Create
a trusted private backup parent, then request a new destination:

```sh
.venv/bin/python -m engine company backup \
  --store local/company-demo-v1 --output local/backups/company-before-upgrade
.venv/bin/python -m engine company upgrade --store local/company-demo-v1
```

Backup explicitly includes credential material; it is not a metadata-only export
and must stay private/offline and outside Git. It uses SQLite's snapshot backup
and an integrity check, paired with the matching application key. Destination
files are not overwritten. Interrupted/partial backup state is kept for inspection,
not silently treated as valid restoration. Encryption, backup rotation/retention,
and automated disaster recovery are not supplied.

Upgrade applies shipped migrations, not reset/reverse/fake operations. After
graceful service termination, a stale socket may remain: inspect that no server
owns it before removing **only that operator-confirmed socket**. The launcher
will not silently unlink it. Never restore an old database/key pair over newer
records without a reviewed maintenance/reconciliation process; doing so can
revive revoked credentials/approvals or lose settlements. Default-only pilot
rollback does not roll back the account database or restore a live deployment.

## Verified result versus remaining gates

The suite covers real passwords/MFA, offline/admin recovery, current role scope,
category-source binding, separate simulation approvals, concurrency, expiry,
revocation/accounting/rollback, additive migrations, and real local/Waitress server
checks. None authorizes private sessions, live model execution, or production
savings. **B-02 authorization implementation is complete:** the positive and
negative live-authority boundary is tested using controlled evidence, alongside
the existing real-account/simulation/server paths. Real evidence verification,
criteria, B-04/B-05 execution integration, and company TLS/deployment validation
remain unsatisfied live-use gates, not omitted product requirements. No mock or
passing test supplies those company approvals or proves model quality/savings.

Primary references checked: [OWASP password recovery](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html),
[Waitress reverse proxy](https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html),
and [Waitress server arguments](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html).
