# Conditional delivery reference, operations and policy handoff

**Updated:** 2026-10-04. Accepted path remains **OpenCode V2 → existing LiteLLM
Proxy → company-managed OpenAI API** (AD-01–AD-03). No Laya or replacement gateway.

**Terminal/startup follow-up:** separate guided delivery terminal source/package,
metadata choice/state API and explicit reviewed company/LiteLLM startup loaders
are now implemented. No actual plugin/callback loading or installed-host check was
performed. See [DELIVERY_STARTUP.md](DELIVERY_STARTUP.md), which supersedes the
earlier terminal/startup missing-software notes below. Normal tool-coding support,
continuous pilot-feedback handling and real verification remain incomplete.

**Local-function coding follow-up:** a separate envelope/handoff schema 2 now supports
explicitly reviewed client-owned local function tools and budgeted post-tool model
continuations. Legacy text-only contracts remain unchanged. See
[FUNCTION_CODING.md](FUNCTION_CODING.md), which supersedes text-only-only scope below
without claiming unrestricted shell, hosted tools or installed-host/tool validation.

The narrow adapter is now real application/source code, exercised with controlled
provider responses and a loopback fake-provider HTTP server. **It is not installed
or authorized for real generation.** Company evidence, host compatibility, actual
billing and task quality are not established by these tests. Full B-04/B-05/B-06
completion remains pending for the software and validation items below.

**Known-cost correction follow-up:** independently verified increases/decreases now
append exact task/request/attempt revisions, with signed administrative review/fresh-
MFA confirmation and scoped machine review/apply. Original settlements, failures,
overruns and lifetime claims remain; decreases never auto-resume delivery. See
[COST_CORRECTIONS.md](COST_CORRECTIONS.md), superseding earlier missing-correction notes.
Metadata-only capture/repair rules remain unchanged in [TOOL_STATUS_CAPTURE.md](TOOL_STATUS_CAPTURE.md).
Current regression verification: **838 Python / 47 JavaScript tests pass**, with the
798 Python baseline retained and 40 new correction regressions. Earlier verification
counts below are historical milestones, not installed-host/billing readiness claims.

## Implemented supported path

- `engine/company/delivery.py`: concrete `NarrowDeliveryAdmissionVerifier`, exact
  linked task/model/claim binding, separate gateway identity, logical requests,
  physical-attempt reservations, complete/unknown settlement and permanent close.
- `engine/delivery_contract.py`: versioned text-chat envelope [reviewed billing
  bounds], exact decimal arithmetic and fixed usage projection.
- `engine/litellm_delivery.py`: actual optional LiteLLM `CustomLogger` factory,
  pre-call and per-deployment admission callbacks, and a company HTTP metadata
  client. It sends no inference request itself; LiteLLM remains the transport.
- `integrations/opencode/src/delivery-{adapter,coordinator,index,rpc}.mjs`: separate
  opt-in source/RPC [typed in-tool calls]. The coordinator joins explicit metadata
  start → independent preflight → selection → one-use claim → gateway binding →
  **creation of a new isolated root session with the exact model**. It submits no
  prompt, reads no message history, and never calls `switchModel` or session removal.
  The original observer and terminal panel remain recommendation-only.
- `engine/company/operations*.py`: protected company monitoring, readable linked
  usage/accounting, administrator gateway issue/revoke and non-destructive privacy
  controls, with current roles and fresh password/authenticator verification.
- `engine/company/policy_handoff.py`: strict schema-1 policy/learner/scope/model
  handoff for this reference. Export is not portable approval or credentials.

Migrations `0008` and `0009` are additive. They add private gateway/binding and
operational-control records, not replacements for existing accounts, keys, task
events, learners, approvals, simulation journals or backups. Existing collection
lists and pairings are not enlarged by migration. No owner store was upgraded.

## Authority and exact boundaries

The new-task boundary is an explicit unused company descriptor [fixed task
metadata], not an inferred idle event. The delivery source allocates a future
session ID, links its hash, and creates only that new root with the selected model.
An unexpected/duplicate/child/fork/model response fails closed; the claim is not
refunded or silently reused. The gateway checks the same immutable task/session/
owner/model binding before physical admission. Identical retry payloads keep the
same opaque, task-keyed request ID; intentional identical re-execution is
conservatively unsupported by this first source.

Separate live readiness, designated fresh-MFA human approval and activation remain
required. Per-task acceptance, learner publication, a metadata source label,
export, token, confidence or test count cannot supply them. Existing company
transactions serialize checks and accounting across concurrent attempts.

An administrator issues an expiring repository-scoped **machine credential** and
an explicit one-to-one developer → authenticated LiteLLM-user mapping. The caller's
`user` field or header is not identity. Gateway credentials cannot post human
feedback or control a pilot. Owner connector delegation, current permissions,
recovery/MFA generations, model/scope status and exact envelope are rechecked.

`make_callback` requires explicit managed gateway aliases and deployment IDs.
Unrelated identified gateway deployments pass through unchanged. Managed requests
without valid context are refused; fallback/context loss cannot become unbudgeted
delivery. A real deployment must verify these mappings, protected router metadata,
callback ordering, disabled bypasses and credential isolation. Source configuration
alone is not that verification.

Both company launchers still set readiness/admission/delivery/billing verifiers to
`None`. `NarrowDeliveryAdmissionVerifier` is concrete code; it still needs the
independent `DeliveryVerifier` host/billing integration. Controlled positive
readiness, delivery and billing implementations live **only in tests**. No form,
JSON flag or export installs a verifier.

## Cost and request limits

The first envelope supports only default-tier, single-completion, unstored text
chat, with explicit output limits and exact model aliases. Tools, non-text inputs,
prediction/cache-write/extra billing, WebSockets, arbitrary provider settings,
unknown models/prices and unreviewed endpoints are refused.

The reservation uses the **full reviewed billable-input ceiling**, not a guessed
token count, plus the requested output/reasoning ceiling and every reviewed fixed
charge. This is deliberately conservative and can be expensive. No tokenizer is
installed. A real verifier must independently establish provider rejection above
the input ceiling, output/reasoning enforcement, prices, rounding/minimum/extra
charges, account/endpoint identity and validity. Unknown bounds remain unavailable.
Neither sample ranges nor ordinary gateway/provider budgets supply those facts.

Selection reserves the lifetime task allowance in the shared pilot budget. Each
physical attempt additionally reserves from that same authoritative task allowance
**before** execution. Continuations, retries and title/compaction/generate requests
share it. Retries cannot reuse an attempt permission; different-model fallbacks
are refused. SDK-internal retries must be disabled, including prebuilt clients;
the callback sets `max_retries=0`, and host validation must prove lowering honors it.

### Streaming finding and supported adaptation

The inspected LiteLLM `v1.104.0` async wrapper returns actual provider streams
before the ordinary deployment-success callback. Merely wrapping a response in
that callback would therefore miss streaming settlement. The factory instead
requests **one bounded non-streaming provider response**, records its actual usage,
then uses LiteLLM's existing response-to-stream conversion for the client. It does
not generate another response or invent usage. The first client chunk is delayed
until the provider completes. Actual conversion/loading compatibility is unverified.

The framework-neutral stream helper is also tested for interruption/cancellation;
it is not claimed as an installed per-physical-stream integration. Direct provider
streaming and its recovery mapping remain unsupported software scope.

## Usage, unknown obligations and eventual results

Tarkado receives only fixed model/request/attempt, token, cost, latency and error
status metadata. Reasoning and cached-input counts are subsets, not additional
token charges. Latency is per provider attempt, not whole engineering-task time.
Calculated usage cost is visibly distinct from independent provider-invoice truth.

Missing/malformed usage, wrong actual model, timeout or interrupted work creates
an **unknown obligation**, not zero. Its reservation remains; monitoring pauses
future delivery, and unchanged resume cannot bypass it. Lost settlement callbacks
leave the original pending reservation. Closed tasks do not release unknown money.
Missing optional cache/reasoning counters are not inserted as measured zeros;
incomplete supported usage requires later independent billing reconciliation.

Known usage calculations must match the exact envelope/model. Usage-free invoices,
zero-cost cancellation claims and different costs require a separate typed
`BillingVerifier` assessment bound to that exact obligation. An evidence-reference
string cannot refund it. The verifier defaults to refusal. Known settlement remains
immutable; separate append-only correction now requires independently checked evidence
content and repeat verification. Current totals use validated history, not old-event
edits. Late decreases cannot reactivate tasks, restore claims/slots or erase failures
and earlier individual/cumulative overruns.

Explicit owner close and complete known attempt settlement join back to the
original conditional selection exactly once. Failures and full overruns remain,
including negative remaining budget. Pause, revocation, privacy pause and
default-only rollback do not remove incurred obligations. A renewed current
credential with the same scoped gateway identity/owner mapping may reconcile
old costs; it cannot revive the old task or claim.

Human actual-model reports and eventual desired-result reviews remain separate.
Paid activity prevents retroactive acceptance. Positive attribution requires
closed, complete, consistent single-model primary delivery and matching reported
use; unknowns, failures, mismatches and observation gaps are retained. Gateway
completion is never automatically written as engineering success.

### Owner-review corrections — 2026-10-04

Company evidence reviews now bind the validated gateway attempt journal alongside
the connector sidecar. Timeouts, missing usage, failures/retries, wrong models and
cost/usage-bound overruns block affected category review and future published
suggestions even when the failed developer/session was not selected for fitting.
Retained failures survive later billing reconciliation. The count-based learner
is not given fabricated task outcomes or extra positive examples. Pending/healthy
delivery alone does not stale a future-task suggestion. Known same-request retries
keep their original model and require a fresh reservation; unknown costs do not
get a retry exemption. Both live evidence checks and publication consume the same
validated diagnostics; old reports/publications are not rewritten.

## Privacy, retention and monitoring

The existing gateway necessarily processes authorized inference content. Tarkado
does not receive prompts, code, outputs, provider keys or exception text. Its
callback disables its own message logging, but this **does not disable all existing
gateway logs**. Validate proxy body snapshots, spend/debug logs, metadata/token
logging and other callbacks before approving real collection. Pattern checks are
not a secret-free guarantee; private stores/history are not encrypted/tamper-proof.

Monitoring uses the permitted company view, prioritizes historical senior signals,
and keeps junior failures, rejects, overrides, gaps, HTTP errors and unknown
obligations visible. It links the same task, human results, gateway accounting and
separate pilot controls. Dashboard alerts are derived from retained evidence;
there is no fabricated readiness threshold or automatic expansion.

Administrators may pause new task metadata collection/delivery and set a **manual
retention-review reminder**. Resuming collection cannot activate a pilot. Security
history and late authorized settlement are preserved. No reminder schedules
deletion, expiry, backup rotation or removal of failures. Retention duration and
destructive deletion policy remain owner decisions; no private store/backups are
read, cleaned or reset by this build.

## Versioned handoff

The protected pilot handoff serializes these canonical top-level fields:

```text
schema_version, kind, reference_path, company_id, deployment_id, company_revision,
scope_ref, scope, policy, policy_sha256, learner, learner_content_sha256,
model_bindings, compatibility, unsupported, execution_credential,
portable_live_approval, routing_enabled, sha256
```

Model bindings retain policy-registry order and map each policy ID to its exact
gateway/provider envelope or an explicit unsupported/unknown entry. Conflicting
aliases, changed content/contracts and execution-authority flags are refused.
Compatibility declares the source versions and narrow capabilities, not an
installed-host certification. Stale/inactive scopes and unavailable envelopes
are disclosed. The full exact policy/learner/scope is included without provider
secrets or inference content. A hash detects inconsistent copies, not authorship.
The live company service must still recheck authority at every supported boundary.

The checker also validates the nested learner, scope, positive limits, identifiers,
model capabilities, aggregate counts and unsupported-envelope diagnostics. Rehashing
malformed content does not make it valid. This is structural/semantic validation,
not authentication of detached scope/source claims. Simulation-pilot exports read
their local receipt format explicitly, remain labelled simulation-only and include
no live provider envelopes. Corrupt stored exports return a controlled HTTP 400
refusal; current permissions/MFA still protect the export and no history is reset.

## Joined controlled walkthrough — runnable now

These commands create isolated synthetic accounts/MFA/stores and use the actual
company services, metadata API, adapter core and a controlled HTTP provider. They
do not start an owner service, load an installed plugin or call a real model:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_delivery*.py' -v
node --test integrations/opencode/test/*.test.mjs
```

The joined cases cover approval/activation → exact task selection/claim → gateway
binding → pre-attempt reservation → controlled response/unknown failure → owner
close/late settlement → readable monitoring → privacy pause/default-only rollback
→ versioned handoff. Supplied success/zero/invoice values are synthetic records,
not real-company evidence. No fixture JSON is manually copied into disconnected
replacement products.

One controlled calculation reserves `0.04` USD before the fake attempt and records
`0.002` USD from supplied usage. A separate late synthetic invoice records `1.30`
USD and exposes `-0.30` USD remaining after withdrawal. These complete numbers are
fixture accounting checks, not real prices, savings or quality evidence.

## Later operator walkthrough — not performed installation

1. Obtain explicit package/plugin/data/host-validation permissions. Preserve the
   same private installation; stop its server, make a matching private backup,
   apply shipped additive `company upgrade`, then restart. Never rebootstrap it.
2. Explicitly approve usage fields in **Policy & collection**. Issue each owner's
   connector through the existing browser. In **Monitoring → Scoped gateway
   identities**, the MFA administrator maps actual authenticated gateway users
   and privately transfers the one-time machine credential. No OpenAI key enters
   Tarkado or chat.
3. Independently validate the exact source/runtime/billing contract and install
   approved real verifier implementations through trusted application code.
   Neither default launchers nor the supplied tests configure those integrations.
4. After callback-loading approval, the existing gateway's private startup module
   constructs `CompanyBackend` and `make_callback(..., managed_aliases=...,
   managed_deployment_ids=...)`. Register the resulting **instance**, not its class,
   through the documented LiteLLM callbacks configuration. Keep credentials in
   operator-controlled private environment/configuration, outside Git. Verify
   request rejection before provider traffic, every retry, callback ordering,
   zero SDK-internal retries, and buffered streaming against a controlled provider
   on that installed host before any separately approved real call.
5. Load only the separately approved private-developer OpenCode delivery source.
   Its typed `tarkado.delivery.v1` RPC starts an explicit text-only descriptor and
   creates the new bound root. The existing current session remains unchanged.
   The existing observer's commands cannot activate this path. A terminal delivery
   command/panel and standardized deployment-loader wiring remain software work;
   do not claim that source RPC tests verify their usability or installation.
6. Submit work normally only after all separate live-use approvals. End the
   explicit interval and review gateway usage alongside human actual-model/result
   records. For a lost source, use the existing browser interrupted-close action,
   retain its permanent gap, and reconcile outstanding costs with current machine
   authority. Do not mint another token/claim to replay historical work.
7. Use **Monitoring**, privacy pause and the existing separate pilot controls to
   inspect gaps/unknowns and withdraw to default-only behavior. Do not change an
   in-flight model or restore an old database over newer settlements/revocations.

## Remaining software versus deferred validation

**Software still missing for the full build:** continuous pilot-feedback handling;
direct physical provider-stream/lost-delivery recovery mapping; automatic subagent/
new-run attribution; external notifications/supervision; finer universal native tool/
test/permission/interruption and physical-provider-attempt attribution; broader shell/
remote/non-text/extra-charge envelopes. Positive company-specific real verifier
integrations/evidence remain unsupplied. These are not validation checkboxes. Terminal/
startup, bounded local functions, opt-in metadata capture and known-cost corrections
are implemented in newer operating guides, not installed or real billing/tool-safety
proof. Unsupported delivery still refuses.

**Separately deferred real-world validation/configuration:** installed OpenCode
plugin/peer/terminal and LiteLLM/provider lowering/conversion/ordering/retries;
real authenticated user/deployment/credential mappings; approved model/pricing/
ceiling/extra-charge evidence; actual invoice reconciliation; independent company
readiness/evaluation criteria and task quality; real private-session scope, TLS,
backup/recovery/capacity/security and operational walkthrough. Ask before
installation, loading, private access, destructive retention or real provider calls.

## Primary evidence checked

- OpenCode V2 [model selection](https://opencode.ai/v2/docs/models/),
  [plugin session creation/request hooks](https://opencode.ai/v2/docs/build/plugins/)
  and [OpenAPI](https://opencode.ai/v2/openapi.json): `Session.create` accepts an
  explicit ID/model; HTTP hooks carry request kind. No V1 schema is substituted.
- LiteLLM [pre-call rejection](https://docs.litellm.ai/docs/proxy/call_hooks),
  [physical-attempt callbacks](https://docs.litellm.ai/docs/observability/custom_callback)
  and released [`v1.104.0` source](https://github.com/BerriAI/litellm/tree/v1.104.0):
  `CustomLogger` signatures, async wrapper pre-call ordering, streaming bypass,
  metadata handling, failure-hook exception handling and response conversion were
  inspected. Source inspection is not installed-host verification.
- OpenAI [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create):
  `max_completion_tokens` includes reasoning; usage and extra billing modalities
  must be handled explicitly. [Spend limits](https://developers.openai.com/api/docs/guides/spend-limits)
  are not instantaneous strict per-task caps.
- LiteLLM [shared coordination](https://docs.litellm.ai/docs/proxy/redis_requirements):
  worker-local ordinary budgets/revocations are insufficient for a shared guarantee.
  Tarkado's authoritative company transaction is reused; no Redis is installed.

Local logical commits are authorized. **No public push or release** until the
owner selects a licence. All six earlier local commits and private stores remain.

Historical regression verification after the owner-review fixes: **725 Python /
26 JavaScript tests pass** (705 retained Python baseline + 20 new regressions),
`git diff --check` passes, and existing assertions are retained. The Python suite
also invokes JavaScript tests. Counts demonstrate regression coverage, not
installed-host compatibility, real provider billing, model quality or readiness.
