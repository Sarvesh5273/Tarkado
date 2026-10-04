# Local policy history and rollback

## Scope

These commands save versioned policies, record an explicit local review, and
choose or restore a policy for future local use. They do **not** change a live
session, send model requests, edit model approval states, or authorize rollout.
Every CLI result includes `local_only: true` and `deployment_authorized: false`.

Reviewers and reasons are user-supplied metadata. A review label is not an
authenticated identity, a verified evaluation, or permission to deploy a model.

See [WORKFLOW.md](WORKFLOW.md) for the accepted two-stage approval distinction:
a senior accepts/rejects a recommendation for one task; a designated senior/admin
separately authorizes the first limited automatic-routing pilot. Neither is
implemented by the local `policy review` command below. Use the separate
[feedback commands](FEEDBACK.md) for local per-task responses/results.
Recording a policy review or selecting a snapshot does not train a policy or
activate a company pilot.

## Save, review, and select a snapshot

Commands default to the Git-ignored `local/policies/` directory. Add
`--store local/another-history` after any subcommand to use a different local
history.

```sh
.venv/bin/python -m engine policy save tests/fixtures/policy.json

.venv/bin/python -m engine policy review synthetic-static-v1 \
  --reviewer synthetic-reviewer --reason "Reviewed the local fixture only"

.venv/bin/python -m engine policy select synthetic-static-v1 --initial \
  --reviewer synthetic-reviewer --reason "Use this fixture for local work"
```

Saving does not select a policy. Selecting requires a previous content-bound
review. `--initial` requires that nothing is selected; it cannot replace an
existing local selection.

Inspect the selection and complete event history:

```sh
.venv/bin/python -m engine policy current
.venv/bin/python -m engine policy history
```

An empty history reports `current_policy_version: null`, not an invented default.

## Change the local selection

Prepare a new policy file locally with a **new** `policy_version`. Save and
review that exact snapshot before selecting it:

```sh
.venv/bin/python -m engine policy save local/proposed-v2.json

.venv/bin/python -m engine policy review team-policy-v2 \
  --reviewer local-reviewer --reason "Reviewed the exact local proposal"

.venv/bin/python -m engine policy select team-policy-v2 \
  --expected-current synthetic-static-v1 \
  --reviewer local-reviewer --reason "Change the local selection only"
```

`local/proposed-v2.json` is an example path, not a supplied fixture. Its version
must match the version used in subsequent commands. Selection records the
previous version, reviewer label, reason, time, and content fingerprint.

`--expected-current` prevents a stale change [a decision based on an older local
selection]. If someone has selected another version, the operation fails without
changing history. Read `policy current` and review the situation rather than
retrying blindly with a different expected version.

## Roll back

Restore a reviewed snapshot that was previously selected:

```sh
.venv/bin/python -m engine policy rollback synthetic-static-v1 \
  --expected-current team-policy-v2 \
  --reviewer local-reviewer --reason "Restore the previous local policy"
```

Rollback appends an event and restores the exact stored policy. It does not
overwrite snapshots or discard history. A saved/reviewed policy that was never
selected is not a rollback target; use an explicit selection instead.

This is **local rollback**, not live deployment rollback. A future adapter must
recheck current model/provider approval, revocations, and capabilities before
using an old snapshot at a new-task boundary. An old review alone is not enough
to re-enable a revoked model.

## Export a stored policy

```sh
.venv/bin/python -m engine policy export synthetic-static-v1 \
  --output local/restored-v1.json

.venv/bin/python -m engine replay tests/fixtures/synthetic.jsonl \
  --policy local/restored-v1.json
```

Export never overwrites an existing file. Choose a new destination if it already
exists. Replay/evaluate still require an explicit policy file; local selection
does not secretly change either command's supplied policy.

## Storage and validation

The store uses one JSON state file containing snapshots and append-only event
history. Snapshot content is immutable through the API and CLI: saving the
same version/content is a no-op, and reusing a version with different content
is rejected. Policy-version labels are never used as filesystem paths.

- SHA-256 [a content fingerprint] binds saved snapshots and review events to
  the normalized policy content. This detects inconsistent edits; it is **not a
  signature**, authentication, or protection against someone rewriting hashes
  and history together.
- Reads validate policy contracts, content fingerprints, event sequence, prior
  reviews, and selection/rollback links. Corrupt or unknown state is rejected,
  not silently repaired or replaced.
- Writers use a file lock and replace the JSON file only after a complete
  temporary write. Concurrent changes are serialized; an expected-current
  check prevents two stale selections from both succeeding.
- New store directories have mode `0700`; new state and lock files have mode
  `0600` [accessible only to the owning user]. Existing directory permissions
  are not changed. Existing lock files are never truncated.
- Store-root, state-file, and lock-file symlinks [filesystem shortcuts] are
  refused. Keep the history in a trusted local directory and do not edit it
  concurrently outside Tarkado.
- Policy-history locking currently supports macOS/Linux. Unsupported locking
  fails explicitly; offline replay/evaluation remain independently usable.

Atomic replacement prevents partial JSON from becoming the current state. This
is not a backup, a disaster-recovery guarantee, a multi-host store, or a
tamper-proof audit system. Manual deletion can lose history; retention and
backup management remain future work.

Review labels, reasons, and other metadata are now checked for supported secret
patterns before acceptance or persistence. These checks are not comprehensive;
do not put secrets, prompts, code, or customer data into them. Keep real histories and
exports under Git-ignored local-data folders.

See [PRIVACY_AUDIT.md](PRIVACY_AUDIT.md) for diagnostic redaction, private
exports, and separate offline per-task audit files.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Local operation succeeded; deployment remains unauthorized. |
| `2` | Invalid policy/history, missing review, stale selection, invalid rollback, file access error, or an existing export destination. |

Tests cover policy-content preservation, review gates, exact rollback,
concurrent updates, rejected corrupt state, interrupted writes, private file
permissions, and non-overwriting exports. See [TASKS.md](TASKS.md) for remaining
privacy, approval, and live-integration work.
