# Metadata privacy checks and offline audit records

## Scope

Tarkado supports local metadata-only inputs. Raw prompts, code, model outputs,
credentials, and raw-content references are unsupported fields. Secret checks
and audit export do not collect live tasks, authorize models, or send API calls.

The accepted [company workflow](WORKFLOW.md) keeps monitoring everyone while
prioritizing senior per-task feedback linked to actual outcomes. Today's audit
records do not include that role-aware response/result loop or authenticate
pilot approvers. Separate local feedback records are now documented in
[FEEDBACK.md](FEEDBACK.md); they are not extra audit/trace input fields. The
working feedback ledger retains readable approved IDs rather than hashed audit
references, so it must remain private and outside Git.

**Pattern checks cannot prove that data is secret-free.** Custom, encoded, or
unfamiliar secrets may be missed. Personal/customer information is not
automatically classified. Only import metadata that your team has approved.

## Check an input without printing its values

```sh
.venv/bin/python -m engine privacy check tests/fixtures/synthetic.jsonl --kind traces
.venv/bin/python -m engine privacy check tests/fixtures/rollout.jsonl --kind traces --repeated
.venv/bin/python -m engine privacy check tests/fixtures/policy.json --kind policy
```

`--kind` may be `traces`, `policy`, `plan`, `audit`, or `snapshot`. The corresponding schema
is validated, not just scanned as arbitrary JSON. Output includes the checked
record count and supported pattern categories, not input values.

Checks also run during imports, report generation, history writes, and exports.
There is no bypass flag. Raw-content opt-in is not implemented.

## What the checks do

- Detect declared patterns for private-key headers, common key/token prefixes,
  bearer tokens, JWT-like strings, credential assignments/fields, command-line
  credential flags, URL passwords, and credential query parameters.
- Reject multiline/control-character metadata and strings over 1024 characters.
- Reject non-finite numeric metadata at export boundaries.
- Reject suspected secrets before accepting/persisting supported metadata.
- Avoid echoing invalid command-line values. Known secret patterns in file/error
  diagnostics are replaced with `[REDACTED]`.

These are simple rules in `engine/privacy.py`, not a comprehensive credential
scanner. False positives are possible. Redaction is for **diagnostics only**:
Tarkado never rewrites a model ID, risk label, evidence reference, or policy to
make a routing decision pass. Correct the source metadata and rerun.

No API calls are made to test whether a suspected key is valid.

## Export replay and candidate audits

```sh
.venv/bin/python -m engine replay tests/fixtures/synthetic.jsonl \
  --policy tests/fixtures/policy.json --audit local/replay-audit.jsonl

.venv/bin/python -m engine evaluate tests/fixtures/rollout.jsonl \
  --policy tests/fixtures/rollout-policy.json \
  --candidate fixture/candidate --plan tests/fixtures/rollout-plan.json \
  --audit local/candidate-audit.jsonl
```

Replay exports seven decision events and one additional override event for the
fixture. Unpaired/blocked replay results can still be audited, with missing
outcomes and unknown measurements recorded explicitly. Observe/shadow audit
records preserve the original selected model.

The candidate fixture returns **REJECT**, exit code `1`, and six candidate
records. Test/score regressions remain in the report and audit. Candidate
records have no effective route: they describe recorded comparisons, not live
model requests. Recorded candidate overrides get an additional override event.

Audit export is explicit and optional: without `--audit`, no audit file is
written. Normal reports still go to the local terminal.

## File format and policy binding

Audit JSONL starts with a **manifest** [a summary of the file], followed by
validated events in their declared canonical field order. The manifest records
schema/mode, policy version/fingerprint, event counts by type, hashed identifier
handling, manual retention, `local_only: true`, and
`deployment_authorized: false`.

Each event records:

- hashed task/sample/trace references and the source timestamp;
- event type, mode, and exact policy version/SHA-256 [content fingerprint];
- recorded, baseline, suggested, effective, evaluated, and fallback models;
- fallback, blocked, override, and missing-outcome flags;
- reason, confidence, and approved evidence references;
- baseline and evaluated tokens, cost, latency, and outcome metadata; and
- a fingerprint of its own content.

Reports bind their policy fingerprint at generation. Audit creation refuses a
different policy even if its version label is reused. Loading validates record
contracts, fingerprints, counts, and policy/mode references. This detects
inconsistent edits; hashes are **not signatures** and do not authenticate an
author or protect against coordinated rewriting of data and fingerprints.

Override events reference the same measurement as the associated decision or
evaluation. Do **not** sum all events as separate tasks/API requests. Use event
types and manifest counts to avoid double counting.

```sh
.venv/bin/python -m engine privacy check local/replay-audit.jsonl --kind audit
```

## Identifier and storage limits

Raw task/sample/trace IDs become deterministic fingerprints in audit reference
fields. This is **not anonymization**: guessed IDs can be matched, and stable
references permit linking records. Model IDs, policy labels, reasons, and
approved evidence references remain readable metadata. Human-readable reports
still display accepted task IDs.

Exports are checked before writing, use private `0600` file permissions on
macOS/Linux, and publish only a completely written file. Existing files and
destination symlinks are never overwritten. Publication/flush failures clean
up Tarkado's temporary export, not user files. Use trusted local directories;
network filesystems, encryption, and backup/disaster recovery are not covered.

Keep real policies, reports, audits, and review histories in `local/` or another
Git-ignored data folder. JSONL/CSV files are ignored by default; only explicitly
synthetic fixtures are exempted.

## Retention and exit codes

Manifests declare `retention_policy: manual`. **Nothing deletes records
automatically.** Manage retention yourself until a reviewed feature exists.
Audit creation does not clean older files or Git history retroactively.

| Code | Meaning |
| --- | --- |
| `0` | Supported privacy rules passed, or the underlying command succeeded. Not proof of secret-free data or rollout approval. |
| `1` | Replay/evaluation is incomplete or a candidate is rejected; a requested audit may still be written. |
| `2` | Unsafe/invalid metadata, corrupt audit, file error, or an existing audit destination. |

An export failure after report generation preserves stdout and returns `2`.
Failed exports do not silently report success.

Authenticated approval, independently validated evidence/sampling design,
live integration tests, live rollback, retention management, encryption, and
broader secret/customer-data handling remain pending. No raw-content opt-in or
automatic enablement is supplied. See [TASKS.md](TASKS.md) for progress.

The conditional task-level uncertainty baseline is documented in
[UNCERTAINTY.md](UNCERTAINTY.md); it does not verify evidence or authorize rollout.

The OpenCode snapshot wrapper projects only chosen metadata fields from API
responses, but those responses may contain sensitive fields transiently in
memory. It does not read message history. See
[OPENCODE_ADAPTER.md](OPENCODE_ADAPTER.md) for scope and limitations.
