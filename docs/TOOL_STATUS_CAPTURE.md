# Automatic metadata-only local-tool status capture

**Updated:** 2026-10-04. Narrow inactive source for the existing bounded local-function
path. No tool runner, unrestricted shell, MCP/remote tools, subagents or Laya. Actual
OpenCode tool execution, argument validation and permissions remain unchanged.

## Runtime contract actually checked

The official OpenCode V2 plugin guide documents `ctx.tool.hook("execute.before", …)`
and `execute.after`. Its abbreviated examples do not specify every identity field.
Before implementation, the release-pinned **`v2.0.21` source** was inspected:

- [`packages/plugin/src/promise/tool.ts`](https://github.com/anomalyco/opencode/blob/v2.0.21/packages/plugin/src/promise/tool.ts):
  both hooks carry `sessionID`, `messageID`, `id` (tool-call ID), `agent` and `tool`.
  Before carries input; after carries input plus `status: completed | error`.
- [`packages/schema/src/tool.ts`](https://github.com/anomalyco/opencode/blob/v2.0.21/packages/schema/src/tool.ts):
  `Tool.Result` exposes optional arbitrary `metadata`; `Tool.Error` also permits
  optional metadata. There is **no universal tests-passed/permission/cancel field**.
- [`packages/core/src/tool.ts`](https://github.com/anomalyco/opencode/blob/v2.0.21/packages/core/src/tool.ts)
  and [`permission.ts`](https://github.com/anomalyco/opencode/blob/v2.0.21/packages/core/src/permission.ts):
  typed tool errors reach after, but some pre-execution failures, permission-decline
  defects and interruption paths can bypass it. An observed before is an attempted
  invocation, not proof the executor ran or permission was granted.
- [Official plugin guide](https://opencode.ai/v2/docs/build/plugins/),
  [permissions](https://opencode.ai/v2/docs/permissions/) and
  [client live-only/no-replay events](https://opencode.ai/v2/docs/build/client).

Source/tag inspection is not installed-host validation. The shipped source still
requires the pinned V2/private-developer context and separate approved loading.

## What is captured, and what stays unknown

| Signal | Supported source | Meaning |
| --- | --- | --- |
| Invocation start | Native before hook | Exact bound task/message/call/tool attempt, not authorization or completion. |
| Tool execution error | Native after `error` | Generic tool/validation execution-path error. No exception text or detailed cause is read. |
| Completed tool call | Native after `completed` with a result | Runtime completion only. Tests and final engineering outcome remain unknown. |
| Explicit structured test failure | Reviewed test tool metadata contract | Intermediate `test_failed`, not a final failed engineering task. Never inferred from text/exit-code parsing. |
| Explicit permission refusal | Reviewed tool metadata contract | `permission_refused` only when explicitly supplied. No permission rules/feedback/resources are read or altered. |
| Explicit cancellation/interruption | Reviewed tool metadata contract | `interrupted` only when explicitly supplied. Missing after cannot be relabelled cancellation. |
| Unknown/missing result | Missing/malformed after result, or missing after at a subsequent-request/close barrier | Unknown, not completed, free, failed or cancelled. |
| Coverage gap | Queue holes/overflow, orphan after, source unload/restart | Permanent missing coverage, never invented invocation/results. |

Fine-grained metadata projection is opt-in per **independently reviewed tool
contract**. `LocalFunctionTool` has an optional `status_metadata_key`, omitted from
legacy serialization when absent. Its only supported value is `tarkado_status_v1`.
A reviewed existing tool may supply this in `Tool.Result.metadata` or
`Tool.Error.metadata`:

```json
{
  "tarkado_status_v1": {
    "schema_version": 1,
    "status": "test_failed"
  }
}
```

The other allowed negative values are `permission_refused` and `interrupted`.
`test_failed` is permitted only for a task-bound `test` capability. This is **our
explicit tool-integration contract**, not a claim that built-in tools emit it.
The existing `DeliveryVerifier` must review its semantics and implementation; a
supplied key/hash/evidence label alone is not proof. Tools without it supply only
generic native status. Unrecognized/unreviewed metadata is not scanned or promoted.
No output/content, exception message, arguments, source or credentials are copied.

Native permission-decline/cancellation paths without an after hook remain unknown
and gapped. Supporting all native permission/refusal/interruption variants needs
a separately validated attribution surface; it is not implemented here. Test tools
that expose only arbitrary output text do not supply structured test outcomes.

## Exact linkage and permitted data

The existing browser-issued account/repository/directory delegation authenticates
uploads. Only a corresponding owned `DeliveryBinding` with an exact approved local
function contract is accepted; observation is not human feedback or pilot authority.
The source uses its already-bound explicit task session, not inferred task boundaries.

An invocation is an opaque task-keyed fingerprint of **session ID + assistant
message ID + tool-call ID + effective tool name**. Raw message/call IDs and the
task token are not persisted. The observed contract reference binds the full saved
tool name/capability/definition/status contract, not a client-provided untrusted
model/actor label. Current identity/role/MFA/repository/expiry/revocation checks and
the original collection scope apply on each upload. Historical actor snapshots
remain immutable.

Native tool hooks do **not** expose a physical provider-attempt ID. `tool_attempt_ref`
is therefore always null with `physical_attempt_linkage: unavailable`. The tool
invocation is task-linked, but the latest HTTP/request/token counter is not guessed
into exact provider attribution. Adding physical-attempt linkage is separate work.

Only these new explicitly approved metadata fields are accepted, in canonical order:

```text
tool_invocation_ref, tool_contract_ref, tool_phase, tool_status,
tool_observed_at, tool_attempt_ref, tool_status_source
```

The envelope adds the already-approved task/session scope reference, immutable
event ID and ingestion sequence. Server receive time and historical owner snapshot
are service-owned, not submitted roles. Source times must be timezone-aware and
cannot precede the task/start or be future dated; synchronize operator clocks.
Delayed observed times may arrive later than other events: ingestion order is
preserved without rewriting timestamps or old records.

Migration **`0010_tool_observations`** adds an append-only table. No existing tables,
keys, accounts, tasks, policies, journals or private stores are replaced. The new
fields are excluded from bootstrap defaults and existing collection lists/pairings.
No owner database was migrated. No deletion/retention policy is added.

## Explicit activation — not performed

After separately approving plugin loading and collection scope:

1. The authenticated administrator explicitly enables the listed new metadata
   fields in **Policy & collection**. This revision may require a new exact company
   review/approval; do not amend old hashes or thresholds to evade that check.
2. The owner issues a new repository-scoped pairing. Expanding company scope does
   not enlarge a previously issued pairing.
3. Only in the separately approved private-developer delivery package configuration,
   set `toolFailureCapture: true`. Default observer/delivery loading does not enable
   this capture automatically. No plugin configuration was edited in this build.
4. Independently validate host hook ordering, tool/status metadata semantics,
   privacy/logging and identity mapping against controlled tools before real use.

Without both explicit metadata approval/new pairing and enabled source, the feature
is not available. Existing text-only and local-function contracts remain preserved.
No test verifier is installed in product configuration.

## Delivery, missing events and recovery

`ToolCapture` holds only projected metadata, with bounded event/invocation memory.
An append-only capture-open marker allows recovery through permitted company task
metadata. It is **not tool activity** and does not prevent timely acceptance.
Before/after hooks enqueue metadata; they never mutate tool input/results or execute
tools. Collector faults become gaps, not changes to the tool's result.

Retries retain the same event ID, sequence, payload and observed time. Changed
IDs/content, stale sequences and wrong-task/contract linkage are refused. Overflow
records skipped sequences plus a permanent gap. A native after without an observed
before is incomplete coverage, not fabricated before/completion proof.

Before another paid model request or explicit close, the source flushes its queue
and records still-unfinished invocations as unknown. A result arriving later is
appended to the same invocation while retaining the earlier missing/unknown record.
A gap/unknown is not automatically erased by that late completion. Requests while
tool results remain pending are conservatively refused; overlapping paid auxiliary
work during tool execution is not certified by this path.

Transport failure refuses paid continuation rather than losing metadata silently.
Graceful unload records unknown/gaps for open captured tasks. Restart checks only
the company's paired capture records, appends one immutable recovery gap and does
not restore tokens, create sessions, replay private events or infer completion.
If old access is expired/revoked, uploads remain refused; the existing protected
browser interrupted-close/review/reconciliation flow preserves the gap/history.

Late results for an already observed invocation may arrive after explicit close or
withdrawal when the original delegation is still currently permitted. No new start
can attach to a closed task. Outstanding provider costs/unknown obligations remain
settled only through their existing authenticated accounting path.

## Owner-approved intermediate-failure policy

The owner explicitly selected **bound-task repair** on 2026-10-04:

- Generic execution errors and explicit intermediate test failures are retained in
  monitoring and block new automatic tasks in the affected category pending review.
- Only the **exact already-bound task** may attempt repair, with the same model,
  approved scope and remaining authoritative budget. Every model request—including
  repair, retry and auxiliary work—still needs a fresh conservative reservation.
- Refusal, interruption, unknown/missing results, pending invocations and gaps block
  paid continuation. Their observations do not refund or infer provider costs.
- Relevant rejects, final human failures/corrections, provider failures/unknown
  obligations, model/contract mismatches, incompatible models, revoked/expired
  authority and exhausted budgets keep all existing vetoes. There is no blanket
  current-task/event exemption or automatic resume.

Review/publication reads every retained permitted same-source tool record, including
junior failures and records outside the fitting-session subset. Review sidecars and
category blockers are new records, not replacement source hashes or edits to old
learners/evidence/approvals. The count learner receives no fabricated successes or
final task failures. A completed API request can coexist with `test_failed` status.

Human actual-model reports and eventual desired-result reviews remain separate.
An intermediate tool/test failure alone does not declare final failure or veto a
later genuine human success report after repair. Conversely missing/gapped/refused/
interrupted coverage cannot be used to fabricate adopted success. Earlier failures
remain visible alongside any later review/correction. Learned suggestions/readiness
are not inferred from acceptance or a tool/API completion.

## Verification boundary

```sh
.venv/bin/python -m unittest discover -s tests -p test_tool_observations.py -v
node --test integrations/opencode/test/*.test.mjs
```

Tests use temporary synthetic stores, actual company role/MFA/delegated API checks,
the real Node projector through loopback Django HTTP and controlled documented hook
objects. They cover generic and explicitly structured statuses, duplicate/late
events, exact ownership/contracts, clock/order checks, scope consent, gaps/overflow/
restart, raw-data exclusion and the difference between API/tool/test/final outcomes.
Same-task repair still reserves `0.04` USD before the controlled provider; synthetic
usage is `0.002` USD. No real inference or installed-host compatibility follows.

Deferred: actual installed V2 tool hook/runtime loading, real structured test-tool
semantics, native permission/cancellation attribution beyond this contract, physical
provider-attempt attribution, approved real session/identity/logging/deployment and
provider billing/quality validation. No dependencies/plugins installed, private
sessions/stores accessed, real calls, owner-store changes or public push occurred.

Final regression verification: **798 Python / 47 JavaScript tests pass**; all
774 Python / 38 JS baseline checks are retained and `git diff --check` passes.
The Python suite also invokes JS tests; counts are not independent certifications.
