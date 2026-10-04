# Bounded local-function coding path

**Updated:** 2026-10-04. Accepted architecture unchanged: **OpenCode V2 → existing
LiteLLM Proxy → company-managed OpenAI API**. No Laya or replacement coding client,
gateway, tool runner, provider SDK or tokenizer.

This is implemented **conditional software support** for a constrained subset of
tool-using coding requests. It is not installed-host/provider validation, a live
pilot authorization or a claim of general unrestricted coding support.

## Supported extension

The original text-only envelope and serialization remain unchanged and still
refuse tool-required work. A separately reviewed `LocalFunctionChatEnvelope`
[fixed request/billing contract] adds:

```text
schema_version: 2
record_type: bounded_local_function_chat
local_tools: [{name, capability, function_sha256}]
local_execution_evidence_ref
```

The original exact model aliases, input/output ceilings, decimal prices, fixed
charges and verification interval remain. Each tool maps to an explicit local
`read`, `edit` or `test` capability and an exact definition fingerprint. Built-in
read/glob/grep and edit/write/patch names cannot be relabelled as another capability.
Bindings include only the tools needed by this task's explicitly declared
capabilities, not every tool from the company deployment. Company model approval,
compatibility, evidenced category scope and separate human approval still apply.

The delivery terminal source now allows explicit local-capability declaration only
when the trusted company metadata service reports a matching reviewed envelope.
Its outgoing session hooks remove unapproved tool definitions **only from this
task's request**, not the global registry or another active session. The final
gateway callback checks each exact function definition again after transport
lowering [conversion to provider fields]. Late overlays cannot pass on a name alone.
Model choice stays fixed across tools, retries and auxiliary requests.

## What independent verification must establish

The existing server-owned `DeliveryVerifier` must independently verify both the
provider's function-chat contract and the client tool-execution boundary. Returning
a reference string, supplying a hash, enabling a catalog flag or publishing a
learner is not this verification. Shipped launchers still default to refusal.

For every enabled local function, verify the actual implementation, schema,
permissions, repository/data scope and applicable formatter/test side effects:

- no hidden model/subagent calls, consumer subscriptions, remote paid tools,
  hosted provider tools, external API charges or extra unbounded billing;
- no unrestricted process/network authority disguised as a `test` function;
- current independent evidence ties the implementation to its exact definition
  and capability, rather than merely trusting the tool's name/description;
- OpenCode's own tool permissions and argument validation remain enforced;
- provider input ceilings include full tool definitions, conversation, tool-call
  arguments and prior tool outputs, not only the original prompt;
- actual model/endpoint supports **Chat Completions function calling**, exact
  output/reasoning ceilings and reviewed input/output/fixed charges;
- all physical inference retries/continuations reach the existing blocking callback.

Ordinary `shell`/`bash`, `subagent`, `execute`/batch, remote search/fetch, MCP and
skill-loading paths remain refused by this extension. A generic shell command can
start network or model work; labelling it `test` does not bound it. A separately
reviewed already-existing client-owned test function may be mapped to `test`.
The repository does **not** install or supply a general company test runner.

Test fixtures use a controlled `run_tests` implementation against new temporary
synthetic files. That name is not claimed to be a built-in installed OpenCode tool.
An actual deployment without a reviewed safe local test tool cannot use that
capability. Broader shell/custom/remote tool safety adapters are missing software,
not merely deferred provider validation.

## Request and accounting behavior

The new gateway path supports text messages/parts, standard function definitions,
assistant function calls and linked text tool-result messages. It accepts bounded
ordinary temperature/top-p/stop, named tool choice and explicit parallel-function
settings, subject to the reviewed model contract. It refuses:

- wrong-model requests, unknown/changed/duplicate functions and hosted tools;
- orphaned, duplicate or incomplete tool-result linkage;
- image/audio/file inputs, prediction, cache-write or unknown extra billing;
- unsupported options/transports and automatic different-model fallbacks.

Tool schemas, arguments, source and outputs pass only transiently through the
authorized coding client/gateway. Tarkado stores the approved capability/definition
references and existing fixed usage/accounting metadata, not inference content.
This does not disable unrelated existing client/gateway logs; logging/credentials
and approved data scope still need operator validation before real use.

Each model request before or after a tool result reserves the conservative maximum
**before** its physical attempt. The maximum still uses the full independently
reviewed billable-input ceiling, not guessed tokenizer counts, plus output/reasoning
and reviewed fixed charges. Every continuation, retry, title, compaction and generate
request shares the same authoritative task/pilot budget. A local read/edit/test
function is not treated as a free model call: its independent boundary must prove
there is no separate paid operation at all. Unknown billing refuses that path.

Known usage settles each physical attempt. Missing/malformed usage or failed
delivery keeps an unknown obligation and its reservation; unsafe continuation is
paused/refused. Delayed settlement, revocation/default-only withdrawal and full
overruns retain the original accounting. Duplicate logical requests cannot rerun
a paid attempt or repeat tool work by obtaining another permission. The existing
buffered-client-stream strategy remains; direct provider streaming is unsupported.

## Results and learning are not fabricated

The acceptance/freshness correction remains: timely acceptance is preference and
does not pause otherwise eligible work or rewrite reviewed policy/learner/approval.
Tool completion, unit-test output or API completion does **not** automatically
become engineering success, approved billing truth or an extra learning example.
The existing human actual-model/result/correction flow remains separate.

A text tool-error result can be passed back to the model without being mislabelled
as an API failure or zero-cost task. Its semantics are not inferred from raw output.
Automatic independently attributed local-tool failure/quality capture is still
unsupported software; report known failures through the existing owned outcome
flow. Recorded negatives/unknown costs/gaps/mismatches keep their existing vetoes.
No failed provider obligation is erased because a local tool later succeeded.

## Versioned handoff and preservation

Policy handoff schema 2 declares `reviewed_client_owned_functions`, exact tool
contracts and clear hosted-tool/unrestricted-shell refusal. The checker validates
that capabilities are present in the saved model policy. Schema 1 remains accepted
with its original text-only compatibility; it cannot hide a function envelope.
Simulation exports remain non-executable policy copies with no live mappings.
Neither schema is an execution credential or portable approval.

No migration is needed: existing accounts/tasks/role snapshots/journals, source
hashes, policy versions and private stores remain unchanged. A changed model/tool/
local-execution evidence envelope cannot be silently rebound mid-task; another
explicit review/supported boundary is required. Do not upgrade an owner's store,
install tools, load plugins, access private sessions or call a real provider without
separate approval. All code remains local/unpublished pending licence choice.

## Controlled verification

```sh
.venv/bin/python -m unittest discover -s tests -p test_function_coding.py -v
node --test integrations/opencode/test/*.test.mjs
```

The actual adapter request/admission/settlement code is exercised with controlled
provider tool-call responses. Test-side client tools read/edit a new synthetic file
and run an isolated unittest via `.venv/bin/python`; no real model/provider or owner
code is used. Four model attempts each reserve `0.04` USD before the controlled
response, settle supplied `0.002` USD usage, and retain `0.008` USD total. The pilot
then shows `0.992` USD remaining. These complete values are **synthetic accounting
checks**, not real prices, savings, quality or readiness evidence.

Adverse tests cover exact-schema/capability restriction, legacy refusal, lost/unknown
provider costs, result linkage, extra billing/hosted-tool refusal, duplicate delivery,
revocation, fixed-model/budget guards, auxiliary budgets and privacy. JS tests cover
guided declarations, per-task outgoing-tool filtering, wire data and retry identity.

Actual OpenCode/LiteLLM runtime/peer/response lowering/permissions, real model function
support, local test-tool boundary, pricing/invoices/criteria and operator deployment
remain **separately unverified**. This does not mark B-04/B-05/B-06 fully complete.

Regression verification: **774 Python / 38 JavaScript tests pass**, with all
earlier assertions retained and `git diff --check` passing. Python also invokes
JavaScript. Test counts do not establish actual tool safety or production readiness.

## Primary sources consulted

- OpenAI [function calling](https://developers.openai.com/api/docs/guides/function-calling):
  functions execute in the client; callable definitions are billed as input tokens;
  tool results require another model request. Hosted tools are a different path.
- OpenAI [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create):
  function/tool-result shapes, options, usage, output/reasoning bounds. Not every
  current model supports function calling on this protocol; some require Responses.
- LiteLLM [function calling](https://docs.litellm.ai/docs/completion/function_call):
  existing gateway transport and per-model function support, not tool safety proof.
- OpenCode V2 [request hooks](https://opencode.ai/v2/docs/build/plugins/) and
  [tools](https://opencode.ai/v2/docs/tools/): context hooks also cover tool-driven
  continuation; local tools have different permissions and shell has host/network
  authority. No guessed V1 or untyped tool-event attribution is substituted.
