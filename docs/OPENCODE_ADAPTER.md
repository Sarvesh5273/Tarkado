# OpenCode V2 read-only snapshot adapter

**B-04 update:** a separate explicit-task connector/API and inactive server/CLI
plugin source now exists. See [OPENCODE_CONNECTOR.md](OPENCODE_CONNECTOR.md).
This existing snapshot wrapper is preserved unchanged; it still does not infer
tasks or supply per-task quality/usage. No private installed session was accessed.

**Checked:** 2026-10-03. The installed CLI reports `opencode v2.0.21`.
Only its version/help commands were used against the real installation during
this milestone. Session observation was tested using mocks, not private sessions
or provider calls.

The accepted product workflow is in [WORKFLOW.md](WORKFLOW.md): team-wide
observation → manual shadow recommendations → senior-prioritized per-task
feedback plus actual results → category readiness → separate senior/admin
approval for the first limited routing pilot. This snapshot wrapper does not
implement those task/feedback stages and must not be presented as the full loop.

## First integration: an explicit CLI wrapper

Tarkado uses the installed OpenCode CLI's documented `api get` command to read
one explicitly selected session and, when allowlisted, its model catalog entry.
This reuses OpenCode's service discovery/authentication without a new client
package, plugin installation, raw HTTP credentials, or gateway.

The wrapper never asks OpenCode to change a model, prompt a session, execute a
tool, read messages, read credentials, or update configuration. It does not load
a Tarkado plugin into your active environment.

**An observation is a session snapshot, not a task trace or task boundary.**
It cannot establish which individual task used a model or whether that task's
tests passed. It is not paired candidate evaluation evidence.

## Why live hooks were deferred

The official [plugin guide](https://opencode.ai/v2/docs/build/plugins) states:

- Prompt hooks run before model resolution; provider scoping is unavailable.
- Prompt hooks may run more than once for concurrent admission and are not an
  exactly-once side-effect boundary.
- Context hooks run for the agent loop, including tool continuations, not only
  at a new task.
- Public event subscriptions can include all server locations. The
  [client guide](https://opencode.ai/v2/docs/build/client) documents live-only
  subscriptions without replay/automatic reconnection.

The published OpenAPI represents event/log payload schemas as JSON-encoded
strings, rather than specifying a complete typed task-admission/outcome pairing
contract. We will not guess event fields, treat session idle as proof of task
success, or use a model hook to switch an active session.

Future live capture needs explicit task metadata, location filtering,
deduplication, reconnection-gap reporting, and a documented safe boundary before
any recommendations can be enforced. This remains pending in [TASKS.md](TASKS.md).

## Use an approved company-API session

First configure an actual team registry/policy under a Git-ignored local folder.
The repository's `fixture/*` models are fictional. Do not promote a real model
because it appears in an OpenCode catalog.

Use a session you have permission to observe. Supply its exact session ID and
the directory returned by OpenCode for that session:

```sh
.venv/bin/python -m engine opencode observe \
  --session ses_REPLACE_WITH_APPROVED_SESSION_ID \
  --directory "$PWD" --policy local/team-policy.json \
  --company-api --output local/session-snapshot.jsonl
```

The session ID and policy path above are placeholders, not provided fixtures.
Use `--help` to inspect the command without connecting:

```sh
.venv/bin/python -m engine opencode observe --help
```

- `--company-api` is an explicit **attestation** [your confirmation], not a
  credential check. Only company-managed provider/gateway APIs are supported;
  consumer subscriptions remain outside Tarkado's scope.
- `--directory` is required. A different/missing session location is refused.
- `--output` is optional. Without it the snapshot only prints to stdout.
- Exports are private, secret-checked metadata files and never overwrite an
  existing destination. Choose a new filename for another observation.
- `--executable` selects an already installed OpenCode executable. No package
  is installed automatically.
- `--timeout` limits each subprocess read to 1–120 seconds (default 30).
- V1/unrecognized version output is rejected; there is no legacy fallback.

## Exactly what is requested

| Command/API | Purpose |
| --- | --- |
| `opencode --version` | Check that the selected executable reports V2. |
| `opencode api get /api/session/{sessionID}` | Read the explicitly requested session metadata. |
| `opencode api get '/api/model?location[directory]=...'` | Read the selected model at the exact location, only when already present in the team registry. The directory query is URL-encoded by Tarkado. |

No session list, message/context export, event stream, credential/configuration
read, mutation endpoint, or provider-generation endpoint is used.

**Important service behavior:** OpenCode's CLI may discover/start its background
service and activate configured location plugins while handling a GET. Tarkado
does not configure, control, or certify those plugins. Check your OpenCode
environment before observation; GET-only does not mean zero server lifecycle
side effects. A timeout does not forcibly roll back unrelated OpenCode activity.

## Metadata projection and limitations

The response is projected [only chosen fields are copied] into a validated
`opencode_session_snapshot` record:

- hashed session/parent/location references;
- root/child-session classification, without claiming a subagent task boundary;
- source creation/update timestamps;
- explicit selected catalog ID and optional variant;
- whether the selected model is registered and its existing team status/tier;
- selected catalog tool/context metadata with **unverified** provenance;
- cumulative tokens, including reasoning/cache counts, and cumulative API cost;
- runtime session outcome, with task tests/score left unknown;
- exact policy version/fingerprint; and
- `mode: observe`, `task_boundary_observed: false`, `local_only: true`,
  `deployment_authorized: false`.

Titles, prompts, files, permission resources, arbitrary session metadata, model
settings/headers/bodies, provider endpoints, and unrelated catalog entries are
not copied, printed, or persisted. The API responses may contain such fields
transiently in process memory; this wrapper is not a server-side metadata-only
filter or a guarantee of zero sensitive data exposure in memory.

Raw session/project IDs and paths are hashed before export. As with audit
references, deterministic hashes are linkable and are not anonymization.
Accepted model IDs/variants and policy labels remain readable.

Token/cost fields are **cumulative session counters**, not per-task costs.
Repeated snapshots must not be summed as separate requests. Runtime
`succeeded` is not a passing test or reviewed engineering outcome. Missing
cost/tokens remain `null`, not zero.

If the session has no explicit model, its actual request model is unknown.
Tarkado deliberately does not infer the catalog default: auxiliary requests or
prior session activity might have used something else.

The [model guide](https://opencode.ai/v2/docs/models) documents fallback
capability/context assumptions for custom models. Resolved catalog values
therefore have `provenance: resolved_catalog_unverified`. They never update
team model approvals or policy capabilities. The current catalog may also
precede plugin settlement, as noted by the model-list API.

## Validate a saved snapshot

```sh
.venv/bin/python -m engine privacy check local/session-snapshot.jsonl --kind snapshot
```

This checks the snapshot schema and supported secret patterns without printing
values. Snapshot files are not accepted as replay/evaluation inputs.

## Verification and remaining work

The test suite includes a local mock OpenCode executable using documented
response shapes. Tests check only allowlisted GETs, location validation, no
selection/policy mutation, omission of synthetic secrets, unknown counters,
unverified capability handling, private/non-overwriting export, failures,
timeouts, and the module CLI entrypoint.

This is not a live provider integration test. A real-session smoke test remains
pending until an approved company-API session is supplied. Live boundary
capture, tool/test outcome mapping, retention, authenticated approval,
independent evidence, and pilot/live rollback remain unfinished.

The owner has deferred real-session validation. Local recommendation/response/
actual-model/outcome linkage is now available in [FEEDBACK.md](FEEDBACK.md),
without session access. Experimental learning/application is available in
[LEARNING.md](LEARNING.md); production validation/readiness remain pending.
The snapshot wrapper does not collect these records or apply a learner.

## Primary documentation

- [V2 plugin API](https://opencode.ai/v2/docs/build/plugins)
- [V2 client and subscription behavior](https://opencode.ai/v2/docs/build/client)
- [V2 HTTP API](https://opencode.ai/v2/docs/api)
- [V2 OpenAPI specification](https://opencode.ai/v2/openapi.json)
- [V2 model catalog and capability assumptions](https://opencode.ai/v2/docs/models)
- [V2 configuration and location precedence](https://opencode.ai/v2/docs/config)
- [V2 CLI/service behavior](https://opencode.ai/v2/docs/cli)

For V2 contracts, use these versioned documentation pages—not the unversioned
V1 docs or the editor config schema to infer field shapes.
