# B-04 explicit-task OpenCode V2 connector

**Updated:** 2026-10-04. **Status:** code implemented for a limited observe/shadow
connector; installed-host/terminal integration and real-session validation remain
unverified. No plugin/dependency was installed, no private session was accessed,
and no model/provider call was made during implementation. **No Laya.**

The company service remains authoritative. This is not a gateway, automatic model
selection, a task-classification model, or complete B-05 integration. Existing
offline/B-01/B-02/B-03 contracts and owner data remain preserved.

**B-05 update:** future tasks can now use explicitly published, source-bound
company learners. The panel shows historical learner version/publication status;
new feedback/gaps preserve fallback and immutable history. Separate conditional
selection/accounting code exists behind trusted live scope and default-denying
admission, but the observer plugin does not register automatic descriptor binding
or model switching. See [INTEGRATED_LEARNING_SELECTION.md](INTEGRATED_LEARNING_SELECTION.md).

## Implemented components

- `engine/company/connectors.py`, `connector_views.py`: browser-authenticated
  delegated access and a small metadata-only API. Roles/designations come from
  the company store, never a connector payload.
- Additive migration `0006_connector_records`: private scoped credentials,
  linked explicit tasks, and append-only observations. Older scope lists are
  **not expanded** by migration. No existing company database was migrated here.
- `integrations/opencode/src/index.mjs`: OpenCode V2 server plugin using the
  documented request hooks, without reading prompt/message content, provider
  credentials, request/response bodies, or tools/outputs.
- `src/tui.tsx`: documented CLI plugin entrypoint with `/tarkado` task panel,
  prompt footer contribution, and separate start/response/report/end commands.
- `src/core.mjs`, `client.mjs`, `actions.mjs`: dependency-free connector logic,
  scoped HTTPS/loopback transport, bounded in-memory delivery queue, task
  lifecycle, and terminal actions. Node tests exercise these and a controlled
  plugin host. They are **not installed-OpenCode/Solid rendering verification**.
- `engine/connector_config.py`: writes a private credential file using hidden
  interactive input, without JSON copying, network calls, or plugin activation.

The package is deliberately outside `.opencode/plugins/`, has `private: true`,
and is absent from active OpenCode configuration. Merely editing it cannot
activate collection in this conversation or other private sessions.

## Boundary contract

1. The developer explicitly starts a task **while the root session is idle**.
   The terminal supplies category/risk/requirements as declarations, an explicit
   selected model, a task label, and current session/directory hashes.
2. The server plugin checks only that named session's metadata against its exact
   paired directory. Child sessions and forks are refused; no session enumeration.
3. The company server creates the existing shadow recommendation and stores a
   connector link. Manual model choice is unchanged. One open task per account/
   session, including across pairings, prevents parallel boundary confusion.
4. Accepted work continues in OpenCode normally. Request hooks append model
   **attempts**, auxiliary-request kind, permitted HTTP status, and retry metadata.
   They do not decide new engineering tasks, switch models, or submit prompts.
5. Per-task response is immutable and must precede observed model activity.
   No response stays unknown. Actual model use is separately human-reported;
   attempted model metadata is not automatically declared execution proof.
6. The developer explicitly ends observation after work becomes idle, then reports
   the desired result/tests/evidence. Ending or HTTP success is not task success.
   Browser and connector share the existing correction/role/ownership checks.

The host's read-only metadata/idle checks and user declaration do not create an
atomic provider-admission gate. Concurrent prompts, requests already dispatched,
late completions, and unsupported continuations cannot authorize B-05 routing.
An absent task is **not** fabricated as a successful captured task. Work outside
an explicit observed interval is not captured or inferred from session totals.

## Exact capture and limitations

| Observation | Origin | Meaning / limitation |
| --- | --- | --- |
| Original selected model | Explicit terminal selection at task start | Manually selected; no model changes. |
| Primary/compaction/title/generate model attempt | Corresponding documented session request hook | Attempt, not provider execution/completion. Auxiliary models are separate from primary-task attribution. |
| HTTP response status | Documented `http.response` hook | Status only; streamed failures/body/usage not inspected. WebSocket-only traffic lacks this status path. |
| Retry attempt and decision | Documented `retry` hook | Physical retry metadata; request kind is unknown because the documented hook has no kind. No error message, request body, or provider key. |
| Gaps/sequence holes | Delivery overflow, restart/recovery, unsupported observations, interrupted close | Incomplete evidence, never zero usage or success. |
| Reported actual model/result | Explicit owner terminal/browser action | Human report; unknown remains unknown; no independent engineering truth. |

**Not supported:** exact per-request token/cost/latency, provider billing,
WebSocket payload parsing, automatic task boundaries, automatic subagent capture,
counterfactual outcomes, verified execution, or automatic selection. Documented
session counters are cumulative, so the connector deliberately does not turn
their differences into task-level measurements. The model hooks have no complete
typed durable completion/usage contract usable without additional validation.

Primary tasks involving multiple observed models retain **every observation**.
Unknown/failure reports remain allowed conservatively; one model cannot receive a
positive whole-task result under the current single-execution ledger. Missing/
open/gapped/empty intervals and reported-model mismatch cannot establish positive
adopted success. These are data-integrity refusals, not production learning gates.
Per-attempt quality attribution belongs to separately agreed B-05 design.

Company evidence reviews include a source-bound connector-diagnostics sidecar
[linked observation history]. All same-source records, including junior status
errors, retries, gaps, and multiple models, remain visible. New observations stale
an old review/approval guard. Diagnostics do not become fabricated learner outcomes.

## Identity, privacy, and failure handling

- A participating developer issues their own credential through **OpenCode
  connector** in the existing browser after password verification and applicable
  primary MFA. They confirm one repository, exact absolute directory, source label,
  and expiry (within 24 hours). An admin can revoke/inspect but cannot mint a
  participating developer identity through their own administrator-only account.
- The value is shown once for private transfer. Only its digest is stored in
  company state; the connector reads one explicitly configured private local
  credential file. It never resolves OpenCode provider connections/credentials.
  This is an initial private-transfer pairing flow, not a browser/device OAuth flow.
- This first package requires one private, single-developer OpenCode service
  access context per pairing. Do not load it into a shared/multi-user OpenCode
  server: peers able to call its RPC could otherwise use that delegated identity.
  OpenCode server authentication is not independently verified employee identity;
  shared-host per-human RPC authorization is not implemented or approved.
- Every API call checks current active participation/role snapshot, password and
  MFA generation, company/deployment identity, expiry/revocation, repository,
  and the original collection-field scope. Scope reduction denies old access;
  scope expansion does not enlarge an old pairing. Different permissions require
  another browser-issued credential. A pairing is delegation, not machine attestation.
- The bearer-only API refuses browser session cookies and any Origin header.
  Its CSRF exemption applies only to these narrow endpoints; browser issue/revoke/
  interrupted-close pages still enforce CSRF and authentication. No admin/pilot
  endpoint accepts connector credentials.
- API input is strict, bounded JSON. Actor/time come from the company service.
  Fixed projected fields only; raw prompts/code/output/header/body fields are
  refused, with known-pattern diagnostic redaction and no-store responses.
- Network failures leave manual OpenCode choice untouched. A bounded 256-event
  queue retries the same immutable event identity/sequence; no silent disk spool.
  Overflow becomes sequence holes. Restart recovers open company records with a
  gap. Unsupported/wrong-location observations cannot be relabeled into new work.
  Gaps/failures do not activate routing or cause hidden alternative-model execution.
- Expired/revoked access cannot upload pending records. The owner can use the
  browser's **End interrupted observation** action: password, current permissions,
  confirmation, and expected sequence append a permanent gap/close, preserving
  prior records. Renew pairing for later tasks; do not erase/rebootstrap old state.
- Company HTTPS remains required except explicit loopback laptop development.
  Redirects, credential-bearing URLs, and unsafe origins are refused. No provider
  endpoint transport, browser launching shell, or private-session discovery is used.

## Operator preparation — instructions, not performed installation

Do not load this connector into private sessions without approved data/session scope.

1. Stop the existing company server, make a private paired backup, then run shipped
   `company upgrade` against the **same** store. No reset/rebootstrap.
2. In **Policy & collection**, explicitly approve `observation kind`, `request kind`,
   `coverage status`, and actual-model metadata. Optionally approve HTTP status,
   attempt, and retry. Existing configured fields stay unchanged until the admin acts.
3. As a participating developer, open **OpenCode connector**, enter the exact
   absolute directory of the OpenCode server location, repository, name/source/expiry,
   confirmation, and password. Complete applicable MFA normally.
4. Save its one-time value outside Git using hidden input:

   ```sh
   .venv/bin/python -m engine.connector_config \
     --origin http://127.0.0.1:8000 \
     --output local/connector-private/pairing-v1.json
   ```

   Use the actual company HTTPS origin for company operation. The helper never
   contacts OpenCode or a provider and refuses existing destination files.
5. After separately approving plugin loading/toolchain, add the local package to
   the explicitly permitted OpenCode V2 configuration, preserving unrelated settings:

   ```jsonc
   {
     "plugins": [{
       "package": "/absolute/path/Tarkado/integrations/opencode",
       "options": {
         "credentialFile": "/absolute/private/path/pairing-v1.json",
         "privateDeveloperService": true
       }
     }]
   }
   ```

   This example is **not installed**. No package/runtime dependency is added by our
   tests. The host must supply compatible `@opencode/plugin`, TUI runtime, and
   `solid-js` resolution; actual local-package/TSX loading must be verified on the
   approved installed V2 version before claiming working terminal integration.
6. In that approved idle root session use `/tarkado`, `/tarkado-start`, then
   `/tarkado-accept` or `/tarkado-reject`, manual model choice and normal work,
   `/tarkado-end`, `/tarkado-report-model`, and `/tarkado-result`. `/tarkado-browser`
   shows the existing browser record path; no credential is in the URL. Commands
   exist **in plugin source**, not in this unmodified live OpenCode installation.

For older closed tasks use the existing browser list; the terminal recovers only
its recent paired task records. Further measurements/corrections use browser forms.
No production thresholds or authorized live scope are supplied by this walkthrough.

## Verification and remaining B-04 gates

`tests/test_connectors.py` and `test_connector_http.py` cover browser-issued actual
synthetic account delegation, real loopback API linkage, immutable events, retained
negative/unknown results, interrupted close, ownership, credential scope/revocation,
stale reviews, malformed/raw-content inputs, and additive schema consistency.
`integrations/opencode/test/*.test.mjs` exercise the JavaScript core, controlled
server-plugin registration, late boundaries, terminal action context, private file
handling, outages, overflow/reload, and no provider/session mutation.

Run without installing dependencies:

Latest verification: **637 Python tests pass**, retaining the 605-test baseline,
and **14 JavaScript tests pass**. The Python suite includes one runner for the
JavaScript suite; these are not two independent certifications. `git diff --check`
passes. No assertion was weakened or removed.

```sh
.venv/bin/python -m unittest discover -s tests -q
node --test integrations/opencode/test/*.test.mjs
```

Still required before marking **B-04 fully verified**:

- Approved installed OpenCode V2 local-package/TSX/peer-runtime verification and
  real task-panel behavior (not a substituted host).
- Owner-approved real-session/repository/account observation validation without
  collecting raw content or making additional provider calls.
- A supported verified per-request usage/completion mapping if added later;
  subagent/new-run scopes remain refused until supported and separately tested.

B-05 learning/live selection, B-06 retention/live operations, and B-07 stable
handoff remain separate. Test counts are regression checks, not security,
production savings, model quality, or live execution/deployment permission.

## Primary V2 references checked before implementation

- [Server plugins and request hooks](https://opencode.ai/v2/docs/build/plugins/)
- [CLI commands, slots, selected model, and session panels](https://opencode.ai/v2/docs/build/plugins/cli/)
- [Plugin RPC](https://opencode.ai/v2/docs/build/plugins/rpc/)
- [Client and live-only/no-replay subscriptions](https://opencode.ai/v2/docs/build/client)
- [Published V2 OpenAPI](https://opencode.ai/v2/openapi.json): `Model.Ref`,
  `Session.Info`, `Session.Message.Assistant`, cumulative `TokenUsage.Info`,
  and encoded event/log payload limits. No V1 contract is used.
