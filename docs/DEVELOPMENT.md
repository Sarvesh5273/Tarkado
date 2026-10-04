# Developing Tarkado

## Current scope

The accepted company journey is in [WORKFLOW.md](WORKFLOW.md). The tools below
are supporting machinery, not the complete senior-feedback learning product.
Local linked recommendation/response/actual-model/results now exist with declared
roles and a preliminary review ranking; see [FEEDBACK.md](FEEDBACK.md).
Experimental fitting/application are in [LEARNING.md](LEARNING.md).
Local review and designated simulation receipts are in
[READINESS_PILOT.md](READINESS_PILOT.md). Team-wide task capture, production-
validated learning/readiness, authenticated first-pilot authorization, and live
routing are not implemented. See [TASKS.md](TASKS.md).

The B-01 local pilot simulation runtime is documented in
[READINESS_PILOT.md](READINESS_PILOT.md#local-pilot-runtime--implemented). It uses
receipts for local reservations/state/accounting only and never dispatches models.

The optional `engine/company/` application now provides actual individual login,
private invitations, current company permissions, and policy/collection setup.
It now also links manual recommendations, responses, reported actual models, and
outcomes to authenticated actors with historical role snapshots. No legacy
feedback/pilot data is imported or upgraded into verified company evidence.
It uses approved Django 5.2.17 on supported Python (current `.venv`: 3.13.12).
See [COMPANY_AUTHORIZATION.md](COMPANY_AUTHORIZATION.md#run-the-actual-account-laptop-demonstration)
for bootstrap/serve and additive `company upgrade` commands. Approved django-otp
now requires admin/approver authenticator MFA and provides one-use lost-factor
backup recovery. The same application now offers private offline/admin-assisted
password recovery, category learning/review, separately authenticated simulation
approvals, and B-01 runtime controls. The development launcher is loopback-only;
an approved Waitress private-socket company-serving contract is separate and
requires an operator-configured HTTPS proxy. See
[COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md) for serving/recovery/backup details.
B-02 authorization implementation is complete: positive live scope approval uses
a default-denying server-owned verifier interface, with a separately authenticated
human decision and ordered withdrawal. Controlled tests verify the positive path;
they do not configure a real readiness verifier. Automatic capture/execution,
independent real evidence, and deployment validation remain pending.
The full test suite now also needs `requirements-company.txt`; ordinary offline
commands still have no runtime dependencies. The previous environment is preserved
under `local/environment-backups/`, not discarded.

The implementation includes offline replay and candidate evaluation, not a
gateway or a live router. It uses Python's standard library, supports Python 3.9 or later, and
does not need runtime dependency installation. Packaging declares a pinned
build backend in `pyproject.toml`; running the commands below does not install
or use that backend.

Run commands from the repository root with the project's `.venv` environment.

```text
Tarkado/
├── engine/              Application code: validation, rules, replay, CLI
├── tests/               Unit and local CLI tests
│   └── fixtures/        Hand-written, metadata-only synthetic examples
├── docs/                Requirements, decisions, and task tracking
├── pyproject.toml       Project metadata and optional packaging configuration
└── README.md            Product overview and quickstart
```

## Run and test

Replay a policy against recorded outcomes:

```sh
.venv/bin/python -m engine replay tests/fixtures/synthetic.jsonl \
  --policy tests/fixtures/policy.json
```

Get a machine-readable report:

```sh
.venv/bin/python -m engine replay tests/fixtures/synthetic.jsonl \
  --policy tests/fixtures/policy.json --format json
```

Run in shadow mode [recommend without applying the recommendation]:

```sh
.venv/bin/python -m engine replay tests/fixtures/synthetic.jsonl \
  --policy tests/fixtures/policy.json --mode shadow
```

Use `--mode observe` to retain the original model without applying routing
rules. Neither observe nor shadow changes the recorded selection. Their
comparison totals describe the original selection, not hypothetical savings
from recommendations. Pilot and enforce modes are intentionally unsupported.

In the company workflow, shadow means suggestions with manual model choice and
no extra alternative-model execution. A senior accepts/rejects one task's
recommendation; actual model use/results must be linked separately. Today's
shadow CLI demonstrates no enforcement, but does not collect that feedback.
Use the separate `feedback` commands for linked records and explicit experimental
fitting. Applying a learner remains manual/recommendation-only.

Run all tests:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

## Input contract

Inputs must be local `.jsonl` or `.csv` files containing approved metadata.
Each row represents an existing outcome for one task and one model. The
simulator never calls a provider to generate a missing outcome.

- `task_id` groups evaluations of the same task.
- `trace_id` identifies a row and must be unique.
- Each task has exactly one `is_baseline: true` row for the original selection.
- A task/model pair may appear only once for replay. The `evaluate` command
  supports repeated JSONL samples with an optional `sample_id`; see
  [ROLLOUT.md](ROLLOUT.md).
- All rows for a task must agree on task type, risk tags, required tools, and
  context requirement.
- A registered model's recorded tier must match the policy registry.
- Timestamps must include a timezone.
- Tokens and latency must be nonnegative integers; costs must be finite and
  nonnegative. Optional scores must be between zero and one.
- Unknown tests and scores are `null`, not an assumed pass or zero score.

The JSONL field order used by the fixtures is:

```text
trace_id, task_id, timestamp, task_type, risk_tags, selected_model, model_tier,
input_tokens, output_tokens, cost_usd, latency_ms, outcome, is_baseline,
required_tools, context_tokens
```

`outcome` contains `tests_passed`, `developer_override`, and `score`. Unknown
`task_type` and `context_tokens` may be `null`. All declared fields are required;
undeclared fields, duplicate JSON keys, and non-finite numbers are rejected.
`sample_id` is the only optional extra field; it defaults to `single`.
JSON object key order is not required on import.

### CSV

CSV columns must use this exact canonical order [the declared column order]:

```text
trace_id,task_id,timestamp,task_type,risk_tags,selected_model,model_tier,input_tokens,output_tokens,cost_usd,latency_ms,tests_passed,developer_override,score,is_baseline,required_tools,context_tokens
```

- `risk_tags` and `required_tools` are JSON arrays inside quoted CSV cells.
- Booleans are lowercase `true` or `false`.
- An empty cell represents an unknown task type, context requirement, test
  outcome, or score. Other required values cannot be empty.
- Outcome fields are separate columns rather than a nested object.

CSV and JSONL import the same validated internal contracts. Tests verify that
equivalent files produce identical records.

## Policies and safe fallback

`tests/fixtures/policy.json` shows the initial policy format. It declares a
version, an approved premium default, model capabilities, and task-type rules.
Each rule names a model and team-supplied evidence references.

Automatic non-default recommendations require explicitly low risk
(`risk_tags: ["low"]`), an evidence reference, model approval, and compatible
task type, tools, and context capacity. Missing rules, missing references,
unknown models, or high/unknown risk use the approved default. If that default
is also incompatible or the context requirement is unknown, the replay blocks
the route instead of guessing.

Recorded developer overrides retain the original approved, compatible model.
Observe/shadow always preserve the recorded selection, even when a proposed
route is blocked. Invalid configuration stops the offline run: a malformed
configuration cannot establish a trusted fallback.

Evidence references are not verified, and confidence is an explanatory rule
label, not a statistical estimate. These rules are a simple baseline [a fixed
approach to compare future methods against], not proof that a real model is
safe for rollout.

## Reading reports

Reports show all-task baseline totals and paired comparisons [the same tasks
with outcomes available for both routes]. If a suggested task/model outcome is
missing, the simulator tries the measured default outcome and records the
fallback. If that is also missing, the task is explicitly unevaluated and does
not enter paired totals. No result is invented or assigned zero cost.

Fallback coverage is not evidence for the original cheaper suggestion. Check
`missing_suggested_outcomes` alongside evaluated task counts.

- Positive `cost_reduction_usd` means a lower sampled cost; negative means a
  higher cost.
- Negative `total_latency_change_ms` means a lower sampled total latency.
- Test passes, failures, unknown outcomes, scored-task counts, and overrides
  are all printed.
- `mean_score_change` compares only tasks with known scores on both routes.
- Decimal values are printed without display rounding; JSON encodes decimal
  values as strings. Repeating averages use decimal arithmetic's default
  28-digit precision.

The synthetic fixture intentionally lowers cost while worsening task quality.
Neither a successful command nor a lower cost constitutes rollout approval.

## Export a local policy proposal

```sh
.venv/bin/python -m engine replay tests/fixtures/synthetic.jsonl \
  --policy tests/fixtures/policy.json \
  --export-policy local/synthetic-static-v1.json
```

Export serializes the supplied versioned policy in canonical field order. It
does not learn new rules, certify evidence, approve deployment, or configure a
gateway. It refuses incomplete comparisons and never overwrites an existing
destination. `local/` is ignored by Git.

For stored version history, explicit local review records, and reversible
selection, see [POLICY_HISTORY.md](POLICY_HISTORY.md). History operations do not
approve a model or silently change the policy supplied to replay/evaluation.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | The selected offline comparison is fully evaluated; this does not mean quality passed. |
| `1` | Some routes are blocked or lack outcomes; the report and requested audit are still produced, but policy export is refused. |
| `2` | Invalid input, configuration, file access, or export destination. |

## Privacy and remaining work

Raw prompts, source code, outputs, keys, and `raw_content_ref` are not supported
input fields. Supported secret patterns are rejected in metadata, and known
patterns are redacted from diagnostics. These rules do not prove that data is
secret-free; do not put sensitive content into metadata strings. Real
JSONL/CSV files are ignored by default; only the explicitly synthetic fixtures
are exempted. Keep local policies and reports under ignored local-data folders.

Candidate reports, registry states, and repeated JSONL samples are implemented
as described in [ROLLOUT.md](ROLLOUT.md). A conditional bounded-quality
uncertainty baseline is described in [UNCERTAINTY.md](UNCERTAINTY.md). Verified
evaluation design/evidence, reviewed enablement, automatic retention, raw-content opt-in, broader
data protection, live integrations, and live rollback are still pending. Local policy
snapshot/rollback history is available as described above. See
[TASKS.md](TASKS.md) for verified progress.

Use `--audit local/replay-audit.jsonl` or `--audit local/candidate-audit.jsonl`
for explicit metadata-only audit exports. See [PRIVACY_AUDIT.md](PRIVACY_AUDIT.md)
for hashed references, policy binding, manual retention, and limitations.

The read-only OpenCode V2 session snapshot wrapper uses an already installed
OpenCode CLI; no plugin/client package is installed. It does not send provider
requests or capture new-task events. See [OPENCODE_ADAPTER.md](OPENCODE_ADAPTER.md)
for its read-only GET contract, mock tests, and pending live validation.
