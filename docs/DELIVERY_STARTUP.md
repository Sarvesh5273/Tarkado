# Delivery terminal and explicit startup wiring

**Updated:** 2026-10-04. Source implemented; **not installed/loaded** on the owner's
OpenCode or LiteLLM. The accepted reference remains OpenCode V2 → existing LiteLLM
Proxy → company-managed OpenAI API. No Laya, replacement gateway or coding client.

This follows [DELIVERY_REFERENCE.md](DELIVERY_REFERENCE.md). It completes the
narrow terminal/startup **software wiring**, not normal tool-coding support,
independent company readiness or real host/provider validation. No existing private
installation or credential/configuration was inspected, upgraded or reset.

**Tool-path update:** explicit local-function read/edit/test capabilities can now be
selected when an independently reviewed function envelope exists. The constrained
contract and safe existing test-tool requirements are in
[FUNCTION_CODING.md](FUNCTION_CODING.md). No unrestricted shell, remote/paid tools,
automatic tool-outcome capture or actual host validation is added.

## What the new terminal source does

The separate private package at `integrations/opencode/delivery/` exports a server
plugin, `./tui` and its typed RPC [in-tool method contract]. It does not change the
default observer package or auto-discover itself through `.opencode/plugins/`.

After **separate plugin-loading/data-scope approval**, its source exposes:

- `/tarkado-delivery-connect`: inspect paired metadata setup—not approval to execute.
- `/tarkado-delivery-start`: choose a current separately approved pilot/category,
  explicit original manual policy-model ID, optional override, justified low-risk
  text scope, context/output requirements and exact task budget. Confirm the full
  metadata. This creates **only a new isolated root session**; it submits no prompt.
- `/tarkado-delivery`: inspect the bound model, known cost, unknown obligations,
  reservations, complete remaining budget and separate human feedback.
- `/tarkado-delivery-end`: explicitly close this task without claiming success or
  refunding unresolved costs. Running/unknown cached session state is refused.
- `/tarkado-delivery-accept`, `-reject`, `-report-model`, `-result`, `-browser`:
  reuse the existing owned feedback/correction/browser flow. An original-model
  selection is a human declaration, not a catalog-to-policy alias guess or actual
  execution proof. Per-task acceptance remains separate from pilot approval.

Dialogs cancelled or followed by a changed route/location make no task-start call.
Navigation targets only the newly created root, never a shared session switch.
Every primary/title/compaction/generate call retains its exact bound model and
explicit output cap; the gateway independently checks the final physical request
and reserves its worst-case cost before attempting it. Unknown/bigger output caps
and unapproved auxiliary models are refused, not silently switched.

The source refuses repeated task-start IDs after a lost result. A failed/incomplete
start can leave a retained company task or reservation: inspect the browser and use
the existing interrupted-close/reconciliation controls, not a new claim/token to
retry historical delivery. Close-event retries keep the same event ID. Plugin
restart does not resurrect in-memory delivery credentials. Historical task recovery
remains in the protected company browser; no private-session enumeration/messages
or raw-content spool is introduced.

### Acceptance, learning freshness and execution safety

The acceptance/freshness conflict was reproduced in the delegated API and corrected
on 2026-10-04. An eligible new-task recommendation can be accepted before paid
activity and continue through the otherwise valid approved pilot. Acceptance alone
does not pause the task or pilot and is neither engineering success nor pilot approval.

Three records/checks stay separate:

1. **Reviewed basis:** the exact policy, fixed-cutoff learner/evidence report,
   designated human approval and independent readiness assessment remain immutable.
   Source hashes, thresholds, scope and model bindings are not replaced.
2. **Incoming learning feedback:** acceptance remains in the owned append-only
   task history, with its original role/time and recommendation link. Strict
   learning/publication freshness may say `needs_review`/blocked for subsequent
   fitting or new published suggestions. The pilot page shows that separately;
   it is not an execution veto by itself. Refitting/review is explicit, never silent.
3. **Execution safety:** the fixed reviewed fit and prior reviewed observations are
   still checked, together with current authority, compatibility, budget and negative
   evidence. Only timely acceptance on a new, previously unreviewed recommendation
   is benign. Reviewed-task changes, relevant rejects, executions/result revisions,
   failures, unknown costs, gaps and model mismatches retain their conservative
   checks. There is no blanket exemption for current-task events or future feedback.

Duplicate responses remain idempotent; changed/stale/new late/wrong-owner responses
are refused as before. Acceptance cannot resume a paused/revoked/expired pilot,
refund an obligation, approve a model, expand scope or switch an active-task model.
Positive or other later feedback can still require a new explicit category review;
general continuous adaptation is not implemented by this focused acceptance fix.

## Company verifier startup — explicitly reviewed code

Default `company serve` and `company service` still leave all verifiers unconfigured
and refusing. The company service now accepts a private **integration manifest**
[exact startup code references], only when paired with explicit code-loading approval.
It does not create accounts, migrate/reset state or activate/approve a pilot.

A separately reviewed operator module supplies a `create()` factory returning
`engine.company.integration.CompanyIntegration`:

```text
company_id, deployment_id, integration_id,
readiness: ReadinessVerifier,
delivery: DeliveryVerifier,
billing: BillingVerifier or None
```

These are real interface implementations, not `ready: true` or fixture criteria.
Readiness must consult approved independent company evidence/criteria; delivery
must validate the installed host and billing contract; billing reconciliation must
verify the exact outstanding obligation. The shipped repository supplies **no
positive real-world verifier** or production threshold. If billing is unset,
unknown obligations cannot be refunded by a reference string.

The manifest format is:

```json
{
  "schema_version": 1,
  "company_id": "REPLACE_WITH_EXISTING_COMPANY_UUID",
  "deployment_id": "REPLACE_WITH_EXISTING_DEPLOYMENT_UUID",
  "module": "company_tarkado_integration",
  "factory": "create",
  "source_sha256": "REPLACE_WITH_EXACT_REVIEWED_SOURCE_FINGERPRINT"
}
```

Place it outside Git in an owner-only regular file. The referenced simple Python
module must already be available to the service interpreter, operator-owned,
non-group/world-writable and explicitly reviewed. Source bytes must match the
manifest before the factory executes. Arbitrary package/native-loader discovery,
already-loaded-module replacement and different company/deployment bindings are
refused. No package installation occurs. The loader checks interfaces and installs
the concrete narrow admission adapter; it never turns a hash into evidence or
human live-scope authority.

Only after the operator separately approves loading that code:

```sh
.venv/bin/python -m engine company service \
  --store /absolute/private/existing-store \
  --deployment /absolute/private/deployment.json \
  --integration-manifest /absolute/private/integration.json \
  --load-reviewed-integration
```

This is an **instruction, not a performed deployment**. First stop the existing
service, preserve a matching private backup and apply shipped additive migrations
if needed; never rebootstrap. The normal private-socket/HTTPS-proxy restrictions
remain. Omitting either loader argument cannot silently enable integration.

Source fingerprints check consistency, not authorship or the safety of trusted
code/imports. That code runs as the service operator and can access its privileges;
independent review of it and its dependencies is mandatory. No trusted startup
module was loaded from owner data in these tests.

## Existing LiteLLM callback instance startup

The new dotted **instance** entrypoint is:

```text
integrations.litellm.tarkado_callbacks.callback
```

It is imported only by an explicitly configured existing LiteLLM Proxy. Neither
the company launcher nor ordinary engine import loads it automatically. It reuses
the existing adapter's candidate `1.104.0` version/signature checks; no LiteLLM,
Redis, SDK, tokenizer or peer package is installed by this build.

Its private config, selected explicitly by `TARKADO_GATEWAY_CONFIG`, contains:

```json
{
  "schema_version": 1,
  "company_origin": "https://tarkado.company.example",
  "credential_file": "/absolute/private/gateway-machine.json",
  "managed_aliases": ["company-approved-model-alias"],
  "managed_deployment_ids": ["exact-existing-deployment-id"],
  "timeout_seconds": 10
}
```

The separately stored private machine credential file contains only:

```text
origin: the same exact company HTTPS origin
credential: the browser-issued scoped Tarkado machine credential
```

This is **not an OpenAI API key**, consumer subscription or developer feedback
credential. Issue it through the MFA-protected company gateway-identity page and
transfer privately to the intended gateway operator. Both files must be small,
owner-only regular files. Symlinks, loose modes, extra provider/billing settings,
wrong origins and unspecified paths are refused without rewriting permissions.
No provider/OpenCode credential store is searched. Do not paste usable values into
chat, shell arguments, screenshots or Git.

After separate callback-loading approval, the operator's existing proxy config
registers the instance using the documented LiteLLM `litellm_settings.callbacks`
field, preserving unrelated gateway settings/callbacks. Exact managed aliases and
deployment IDs must come from the reviewed gateway configuration; do not invent
IDs or rely on a supplied header/hash as authority. Validate instance registration,
ordering, logging/redaction, disabled internal retries and every physical-attempt
path on the actual installed host before any separately approved real call.

## OpenCode package loading — not performed

After approving installation/loading/collection for a private single-developer
OpenCode service, its operator uses the separate local package path, not the
observer's historical `./delivery` subpath:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": [{
    "package": "/absolute/path/Tarkado/integrations/opencode/delivery",
    "options": {
      "privateDeveloperService": true,
      "credentialFile": "/absolute/private/owner-pairing.json",
      "gatewayRef": "REPLACE_WITH_SCOPED_GATEWAY_UUID",
      "providerID": "REPLACE_WITH_REVIEWED_OPENCODE_PROVIDER_ID",
      "gatewayOrigin": "https://existing-gateway.company.example"
    }
  }]
}
```

The config is illustrative and **not installed**. Preserve other settings.
OpenCode's reviewed provider catalog must map the selected policy model to the
exact LiteLLM alias, protocol and company-managed authentication. The same-origin
HTTP path remains `/v1/chat/completions`; WebSockets and unknown transport/billing
paths are refused. The host supplies compatible plugin/TSX/Solid peers. The source
checks `2.0.21`, but tests do not prove actual local-package/TSX/runtime behavior.

## What has and has not been exercised

Tests exercise real company services/roles/MFA, typed startup loaders/private
files, the concrete JS coordinator through real loopback HTTP, request-kind/output
binding, CLI action cancellation/context changes and controlled host registration.
No prompt/provider execution occurs in the startup/UI HTTP test. Existing controlled
fake-provider delivery/settlement tests remain intact.

Not exercised: installed OpenCode rendering/peers, actual LiteLLM instance loading/
lowering/logging/retries/response conversion, real verifier evidence/pricing/
invoices, company TLS/private-session/provider operations. Tool-using coding,
direct provider-stream recovery, known-cost corrections and external notifications
remain separate software work. No production-readiness or savings claim follows.

Primary references checked: official OpenCode V2
[CLI plugins](https://opencode.ai/v2/docs/build/plugins/cli/),
[RPC](https://opencode.ai/v2/docs/build/plugins/rpc/),
[server request hooks](https://opencode.ai/v2/docs/build/plugins/) and
[configuration](https://opencode.ai/v2/docs/config/), plus LiteLLM's
[callback-instance/pre-call documentation](https://docs.litellm.ai/docs/proxy/call_hooks).

Regression verification after the acceptance fix: **757 Python / 33 JavaScript tests pass**; the original
assertions are retained and `git diff --check` passes. Python also runs JavaScript
tests. These numbers are regression checks, not host/billing/production evidence.
