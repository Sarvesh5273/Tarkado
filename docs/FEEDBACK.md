# Local recommendation, response, actual-model, and result loop

## What is implemented

The first part of the accepted [company workflow](WORKFLOW.md) is now runnable
locally: record a recommendation, its developer's response, the model actually
used, and a later result. Declared roles let the summary prioritize senior
adoption evidence without dropping junior failures or rejections.

This is **not live task collection, authenticated identity, readiness
certification, or pilot authorization**. No command here executes a model or
changes a session. Recommendations use the static policy unless an experimental
learner is explicitly supplied; summaries never replace it automatically. See
[LEARNING.md](LEARNING.md) for fitting from these records.

## Run the complete local demonstration

```sh
.venv/bin/python -m engine feedback import tests/fixtures/feedback-demo.json \
  --policy tests/fixtures/policy.json --store local/feedback-demo
```

This imports explicitly hand-written observations into an empty store. The
fictional example has:

- seven recommendations and seven responses;
- five recorded actual-model executions/results;
- two accepted/used/successful senior documentation examples across sessions;
- one acceptance with no execution, which supplies no successful-model evidence;
- one acceptance followed by use of a different model, credited to that actual
  model rather than the suggested model; and
- a senior test-generation success alongside a junior failure and a senior
  rejection. The group says `investigate_failures`, not "safe to route."

The two recommendations without execution records remain explicitly visible.
No API use or real company outcome is implied by importing the fixture. These
are supplied observations, not model-generated answers.

Inspect the ledger's current evidence:

```sh
.venv/bin/python -m engine feedback summary \
  --policy tests/fixtures/policy.json --store local/feedback-demo
```

Reimporting the exact same ledger is idempotent [does not add duplicate records].
Bulk import refuses a different existing ledger; it never replaces user work.
Use a new store for a different batch, or append individual records below.

## Build records incrementally

Create an approved local collection roster, for example `local/team.json`:

```json
{
  "company_api_attested": true,
  "members": [
    {"developer_id": "local-senior", "role": "senior"},
    {"developer_id": "local-junior", "role": "junior"}
  ]
}
```

Only declared participating developers are accepted. Supported local role
labels are `junior`, `developer`, and `senior`; none grants pilot authority.
The caller's company-API attestation [explicit confirmation] is not a credential
check. This roster is immutable in the initial baseline and is not an
authenticated company directory.

```sh
.venv/bin/python -m engine feedback init --team local/team.json
```

### 1. Request and save a recommendation

Create `local/task.json` using this canonical field order:

```json
{
  "task_id": "local-task-1",
  "session_id": "local-session-1",
  "developer_id": "local-senior",
  "timestamp": "2026-10-03T10:00:00Z",
  "task_type": "documentation",
  "risk_tags": ["low"],
  "selected_model": "fixture/premium",
  "required_tools": ["read"],
  "context_tokens": 2000
}
```

```sh
.venv/bin/python -m engine feedback recommend local/task.json \
  --policy tests/fixtures/policy.json
```

This example uses fictional models. Use an explicitly approved real team policy
for real observations, not the fixture. Session/task IDs are caller-supplied
references, not permission to read a real coding-tool session.

Output includes a deterministic `rec_...` recommendation ID. Copy that actual
ID into response/execution records; the examples below contain placeholders.
The policy snapshot and recommendation are saved with their exact content
fingerprint. The decision stays in shadow mode and retains the original model
selection. Unknown/unsafe metadata uses the existing policy fallback or a
blocked recommendation; no alternate request is sent.

### 2. Record a per-task response

Create `local/response.json`:

```json
{
  "recommendation_id": "REPLACE_WITH_RETURNED_REC_ID",
  "developer_id": "local-senior",
  "timestamp": "2026-10-03T10:01:00Z",
  "response": "accept"
}
```

```sh
.venv/bin/python -m engine feedback record local/response.json --kind response
```

Only `accept`/`reject` are supported in this baseline. Missing responses stay
unknown, not silently rejected. The response must belong to the recommendation's
developer, and must describe a choice made before the recorded execution.
Late arrival is permitted when the source timestamps preserve that order.

Acceptance is **preference only**. It is never task success, model approval, or
an automatic-routing pilot authorization.

### 3. Record the model actually used

Create `local/execution.json`:

```json
{
  "execution_id": "local-execution-1",
  "recommendation_id": "REPLACE_WITH_RETURNED_REC_ID",
  "developer_id": "local-senior",
  "timestamp": "2026-10-03T10:02:00Z",
  "actual_model": "fixture/cheap"
}
```

```sh
.venv/bin/python -m engine feedback record local/execution.json --kind execution
```

This records supplied execution metadata; it **does not execute** the model.
The actual model may differ from the suggestion. Historical unapproved model
use is retained as an observation but marked incompatible/unapproved during
current-policy summary; it never authorizes that model.

### 4. Record a delayed result or unknown outcome

Create `local/result.json`:

```json
{
  "result_id": "local-result-1",
  "execution_id": "local-execution-1",
  "reviewer_id": "local-senior",
  "timestamp": "2026-10-03T10:03:00Z",
  "desired_result": true,
  "tests_passed": null,
  "score": null,
  "cost_usd": "0.005",
  "latency_ms": 200,
  "evidence_ref": "local-confirmation:task-1",
  "supersedes": null
}
```

```sh
.venv/bin/python -m engine feedback record local/result.json --kind result
```

`desired_result`, tests, score, cost, and latency may be unknown (`null`). They
are never inferred from acceptance or API/session completion. Known quality
labels require a metadata-only evidence reference. A desired-result success
cannot contradict a recorded failed test.

Evidence references and reviewer roles are supplied locally, not independently
verified. The implementation verifies **links and consistency**, not the truth
of a confirmation or review. Tests failing or `desired_result: false` remains
a negative signal, regardless of developer seniority.

### 5. Correct an outcome without overwriting history

Use a new `result_id`, set `supersedes` to the current result's ID, and provide
the corrected full result and evidence reference. The timestamp must not precede
the prior result. Append it with the same result command.

The latest result supplies current evidence, but all revisions remain in the
ledger and summary history. A stale/branched correction is refused. Retrying
identical records does not increase counts; changing an existing ID's content
is refused. This does not authenticate corrections or permit hiding history.

## Senior-prioritized evidence baseline

Summaries group supplied observations by task category and actual/suggested
model, and print all counts, gaps, task results, overrides, and revision history.

For this **initial review-ranking baseline**, senior adopted success requires:

1. The task's developer has the locally declared senior role.
2. That developer accepted the exact recommendation.
3. The suggested model was actually used.
4. A locally declared senior reviewer recorded a desired-result success, with
   no contradictory failed test.
5. The task is explicitly low risk and the model remains compatible/approved
   in the supplied current policy.

Candidates are ordered within each category by senior adopted successes, then
distinct supporting senior sessions, then total recorded successes, with model
ID as a deterministic tie-breaker. This is an inspectable simple baseline, not
a validated training weight or production confidence calculation.

Everyone's rejects, unknowns, and failures remain visible. Any current recorded
failure yields `investigate_failures`, even when senior successes exist. Other
missing/incompatible evidence yields `collect_more_evidence`. Positive evidence
may yield `candidate_for_manual_review`, **never routing readiness or approval**.

The supplied policy is unchanged. `feedback recommend` uses static rules by
default; the summary ranking does not train/install/activate rules. The separate
experimental `feedback learn` command can fit a suggestion model, supplied
explicitly with `--learner`. Manual selection remains; real-world improvement
has not been validated.

No counterfactual [how an unused model would have performed] is invented, and
no production savings are calculated from single-model observations. This
baseline has no final numeric evidence threshold and grants no pilot authority.

## Storage and remaining work

### Authenticated company interface and historical roles

The optional company application now uses these same record contracts through
authenticated browser forms. Actors/time/role snapshots come from server-side
login and current company permissions; tasks, model use, and engineering outcomes
are still manually reported. See the
[joined laptop walkthrough](COMPANY_AUTHORIZATION.md#joined-authenticated-manual-task-loop--implemented).
Legacy JSON stores and their unverified identity labels remain unchanged.

Schema 1 retains its exact existing canonical format. An additive schema 2 appends
`role_attributions`, an array in canonical entry order:

```text
record_kind, record_id, developer_id, role
```

Kinds are recommendation/response/execution/result; their record IDs refer to the
corresponding recommendation, execution, or result. Every recorded action needs
exactly one matching actor/role entry. Task developer role, response role, and
outcome-reviewer role are looked up at their respective actions, not inferred from
a later directory role. Senior adoption in the experimental baseline also needs
a senior response; this adds no approved production weighting/threshold.

**Role-attribution JSON is not identity proof.** Ordinary schema-2 imports remain
unverified; only the company interface binds entries to authenticated events.
Existing local writers cannot silently drop role entries or downgrade history.
Historical role changes are supported for company records, not retroactive
authentication of old local observations. Company outcomes retain original
reviewer corrections; another reviewer's replacement is blocked pending an
agreed disagreement policy. Learning/summary can consume role snapshots but
cannot authenticate a caller merely from their presence.

Records live in a private, Git-ignored `local/feedback/feedback.json` by default.
The local macOS/Linux writer locks, validates, and atomically replaces the
complete state. Invalid/corrupt history is refused, not reset. Store/state
symlinks are refused; new directory/file permissions are `0700`/`0600`.

These permitted metadata files contain readable local developer/task/session
IDs; unlike separate audit exports, the working ledger is not pseudonymized or
encrypted. Secret-pattern checks still apply. Do not include raw prompts, code,
outputs, credentials, or customer information. Retention remains manual.

The first baseline supports one recommendation per task/session, one immutable
response and one execution per recommendation, and append-only result
corrections. More complex multi-attempt tasks, response revisions, authenticated
conflict handling, and multi-host company sync need explicit future design.

CLI success (`0`) means local validation/storage/summary succeeded, not that a
model met a quality target. Invalid input, stale/conflicting history, or storage
failure returns `2` without intentionally overwriting valid records.

Still pending: independent validation of the experimental learner/settings and
verified readiness rules, real task
capture, future learned-manual-application integration, positive trusted live-pilot
approval, and automatic routing. Company category review and separately
authenticated simulation approval/runtime now reuse these records, with
unverified outcomes. The owner-approved
workflow decisions remain unchanged; see [TASKS.md](TASKS.md). Local category
review and simulation receipts are in [READINESS_PILOT.md](READINESS_PILOT.md),
separate from per-task feedback.
