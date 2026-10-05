# Fresh-session handoff — delivery adapter, then remaining build

> **Historical handoff.** Newer `TASKS.md`, `DECISIONS.md` and operating guides take
> precedence over the implementation counts and next-build instructions below.
> On 2026-10-05 the owner authorized reviewed public GitHub publication without
> choosing a Tarkado licence; older no-push instructions here are superseded.

**Saved:** 2026-10-04. The owner requested continuing in a new session because the
conversation is long. Resume the existing Tarkado product; do not rebuild or reset
completed components. This handoff itself changes documentation only.

## 1. Immediate goal and accepted reference

Build the missing concrete delivery adapter for:

```text
OpenCode V2 → existing LiteLLM Proxy → company-managed OpenAI API
                     ↑
          Tarkado policy/approval/accounting
```

The owner accepted this reference after asking for a short, plain-language
explanation. Tarkado decides policy; OpenCode does coding; LiteLLM performs existing
gateway transport. Build a **narrow integration**, not another generic gateway,
replacement backend, new coding client, or fake-only demonstration.

The owner also agreed to a **controlled fake provider for initial tests**. Build
real adapter code and exercise its request/admission/settlement path with test
responses. That avoids paid generation/credentials/private code while testing
failures, retries, limits, and wrong/duplicate requests. It does not establish
installed LiteLLM/OpenCode compatibility, real provider billing, task quality, or
production readiness. Do not switch to actual providers automatically.

Accepted decisions AD-01–AD-03 are in [DECISIONS.md](DECISIONS.md). No Laya. Do not
ask the owner to reselect browser/plugin/reference architecture. Ask only for a
genuinely new blocking choice, dependency, data permission, or operational policy.

## 2. Context recovery — before editing

Workspace: `/Users/sarvesh/Dev/Tarkado`. Existing application: `engine/` and
`engine/company/`. Inactive client plugin source: `integrations/opencode/`.

1. Inspect `git status --short --branch`, `git log`, and the current diff. Before
   handoff preparation the tree was clean, `main` six commits ahead of
   `origin/main`; this handoff/roadmap/decision update is now **uncommitted work**.
   Preserve it. Do not reset/discard user files or assume current status is unchanged.
2. Read `AGENTS.md`, `docs/WORKFLOW.md`, `docs/TASKS.md`, `docs/DECISIONS.md`, and
   `README.md`. Recover W-01–W-08, C-01–C-05, UI-01–UI-03, no-Laya B-04, build-phase
   deferrals, AD-01–AD-03, and **Keep code unpublished**.
3. Read `docs/INTEGRATED_LEARNING_SELECTION.md`, `docs/OPENCODE_CONNECTOR.md`,
   `docs/BROWSER_WORKFLOW.md`, `docs/COMPANY_AUTHORIZATION.md`, and
   `docs/COMPANY_OPERATIONS.md`. These distinguish built authority from absent
   execution integration and real-world validation.
4. Read `docs/FEEDBACK.md`, `docs/LEARNING.md`, `docs/READINESS_PILOT.md`,
   `docs/PRD.md`, and `docs/TRD.md`. Supporting docs: `DEVELOPMENT.md`,
   `POLICY_HISTORY.md`, `PRIVACY_AUDIT.md`, `ROLLOUT.md`, `UNCERTAINTY.md`, and
   `OPENCODE_ADAPTER.md`. Research is background, not company deployment evidence.
5. Rerun the baseline **in the foreground and before edits**, especially migrations:

   ```sh
   .venv/bin/python -m unittest discover -s tests -q
   node --test integrations/opencode/test/*.test.mjs
   git diff --check
   ```

   **Last verified:** 671 Python tests and 19 JavaScript tests pass. The Python
   suite also invokes the JavaScript suite; do not count them as independent
   certifications. Inspect failures; never weaken/remove assertions to make it pass.
   A previous run failed because a migration was added while old models were loaded;
   consistent-snapshot reruns passed. Do not repeat that edit/test collision.
6. Load the **OpenCode skill** for integration changes. Consult official **V2**
   docs and primary LiteLLM/provider docs before selecting field shapes/versions.
   Do not use V1 docs or guessed event/request schemas. Inspect existing services,
   migrations, plugin core, and tests listed below before choosing exact edits.

## 3. Existing implementation — keep it

- Offline replay, registry/rules, candidate evaluation, uncertainty, privacy/audit,
  policy history/rollback, linked feedback, and the experimental learner.
- **B-01 complete for simulation:** persistent reservations/settlement, costs,
  overrides/fallback, state controls, ordered journal, stale checks, exact retries.
- **B-02 accepted authority scope complete:** individual invitation accounts,
  current roles/designations, MFA/recovery, company setup/history, private backups,
  supported single-host Waitress/private-socket HTTPS-proxy contract, conditional
  live-scope approval and withdrawal.
- **B-03 complete:** joined Django browser workflow, task cards/pending states,
  one-task response/actual-model/result/correction flow, readable evidence, guided
  scope/model/developer selection, confirmations, accounting and settlement selectors.
- **B-04 limited connector built:** browser-issued scoped credentials, strict
  metadata API, explicit root-task starts/ends, append-only model-attempt/status/
  retry/gap records, role history, interrupted close, inactive V2 server/CLI source
  and task panel. No installed-host rendering/private-session validation.
  Exact per-request usage/completion, automatic subagent/new-run attribution, and
  automatic task-boundary inference remain unsupported.
- **B-05 conditional layer built:** reviewed learner publication/default-only
  reversal, immutable future learned browser/connector suggestions, stale-feedback/
  observation vetoes; conditional live-scope selection/reservation/one-use claim/
  settlement, negative monitoring, controls, rollback, and concurrency checks.

**B-05 is not finished:** the trusted new-task/model/provider-cap delivery adapter
is real missing software, not merely a delayed test. The JS descriptor-binding
seam defaults to refusal and is not registered by the observer plugin.

The `ReadinessVerifier` and `AdmissionVerifier` are server-owned interfaces,
unconfigured/default-denying in both shipped launchers. Their controlled positive
implementations are **test-only**. Never expose a verified/ready checkbox, install a
test verifier in product configuration, or infer live permission from a task accept,
model confidence, learner publication, synthetic report, scope record, or test count.
Admission and claims currently send no model request; preserve that distinction
until a genuine supported execution path is implemented and separately authorized.

## 4. Six local commits — no public push

The owner first requested commit/push, then selected **Keep code unpublished** when
the public remote and unresolved licence were explained. The latter supersedes
the push request. The remote is `origin`, `Sarvesh5273/Tarkado` on GitHub, public.

| Commit | Batch |
| --- | --- |
| `e388d13` | Company workflow and engineering guardrails |
| `717a939` | Offline engine, simulation, packaging and synthetic tests |
| `7bd955e` | Joined company authority/browser services and additive migrations |
| `aff0241` | Inactive OpenCode connector and controlled HTTP/core tests |
| `0d2bcc6` | Learner publication/conditional-selection verification |
| `fbd2a46` | Operating guides and remaining build/deployment gates |

These are coherent dependency/topic batches of the current joined code, not
invented historical B-02/B-03/B-04 snapshots. Logical **local** commits remain
authorized; preserve existing history and stage only reviewed project files.
**Do not push/publicly release or choose a licence without owner agreement.**
No environment, local database/key/credential, generated cache, node dependency,
or real prompt/source/output dataset was committed. Do not read these private
stores to investigate setup. Ordinary tracked `engine/` code is project code,
not captured customer/task content.

## 5. Adapter build requirements — first priority

1. Define one supported **explicit new-task boundary** and immutable task/model
   binding that cannot alter unrelated active work. Native per-run selection may
   help; do not assume read-only idle checks plus `switchModel` are atomic admission.
2. Reuse current account/repository/credential authority, live-scope approval,
   readiness, and conditional selection/claim accounting. Narrowly authenticate
   any gateway machine identity; it cannot claim human feedback or pilot authority.
3. Implement a LiteLLM integration that can refuse **before** provider execution.
   Its documented pre-call/per-deployment hooks are candidate integration points;
   pin/validate their exact runtime contract before claiming host compatibility.
   Do not use parallel moderation or post-response checks to prevent paid work
   that has already been sent.
4. Reserve a justified conservative maximum cost before **every physical paid
   attempt**: first request, retry, provider/model fallback, continuation, and
   auxiliary title/compaction/generate where applicable. Concurrent attempts must
   share one authoritative task/pilot budget. Do not silently switch task models
   through gateway auto-routing/fallbacks outside approved override/scope.
5. Keep request model, actual provider model/alias, owner, task, policy/learner,
   selection/claim, attempt, and settlement linkage exact. A header or supplied
   hash alone is not authenticated authority. Refuse duplicate delivery and
   wrong-model/boundary reuse; retries cannot consume the same permission twice.
6. Do not equate token/output settings or ordinary virtual-key budgets with a
   guaranteed dollar cap. Validate supported model/tokenization/pricing/output
   bounds and extra charges. Refuse unknown/non-text/tool/plugin/billing paths
   when no justified worst-case bound exists. Never invent a production threshold.
7. Reconcile supported actual usage/cost/latency and errors without retaining
   prompts/code/outputs/API keys. The existing gateway necessarily processes its
   authorized inference payload; Tarkado should receive only approved metadata.
   This is not permission to read/export real private sessions or add raw logging.
8. Streaming failures/timeouts/cancellation do not imply zero cost. Keep unknown
   obligations/reservations and pause/refuse unsafe continuation; settle incurred
   costs fully, including overruns and negative budget. Delayed/retried events,
   crash recovery, revocation, and default-only rollback must preserve evidence.
9. Add controlled fake-provider tests that exercise the real adapter path, including
   parallel admission, cap exhaustion, failed/retried attempts, model mismatch,
   streaming interruption, late settlement, unknown cost, replay, and privacy.
   Framework-neutral tests are fine until a separately approved dependency/host
   test is necessary; state what has and has not been exercised.
10. Finish one usable joined flow before optional expansion. If the reference cannot
    meet a guarantee, print/document that limitation and stop that path; do not
    downgrade assertions or claim the accepted controls work from mock booleans.

## 6. Primary research already checked — recheck when implementing

- OpenCode V2 [models](https://opencode.ai/v2/docs/models/),
  [CLI](https://opencode.ai/v2/docs/cli/),
  [server plugins](https://opencode.ai/v2/docs/build/plugins/),
  [CLI plugins](https://opencode.ai/v2/docs/build/plugins/cli/),
  [RPC](https://opencode.ai/v2/docs/build/plugins/rpc/),
  [client](https://opencode.ai/v2/docs/build/client), and
  [OpenAPI](https://opencode.ai/v2/openapi.json).
  Explicit model choice is documented; full atomic task/dollar-cap delivery is
  not established by those UI/model APIs. Public event payloads/retry/gap limits
  and cumulative session usage must not be guessed into per-task outcomes.
- LiteLLM [pre-call rejection hooks](https://docs.litellm.ai/docs/proxy/call_hooks)
  and [per-deployment callbacks](https://docs.litellm.ai/docs/observability/custom_callback).
  Pre-call hooks can modify/refuse before execution; documented deployment hooks
  cover physical attempts/retries/fallbacks, unlike logical-request logging hooks.
  Correct instance registration/version behavior needs verification.
- LiteLLM [budgets](https://docs.litellm.ai/docs/proxy/users) and
  [coordination/Redis requirements](https://docs.litellm.ai/docs/proxy/redis_requirements).
  Uncoordinated worker-local reservations can overshoot and delay revocation.
  Redis/shared deployment is a separate dependency/operational choice; it is not
  installed or approved merely by selecting LiteLLM as the reference.
- OpenAI [current spend limits](https://developers.openai.com/api/docs/guides/spend-limits):
  hard monthly organization/project controls are documented but enforcement is
  not instantaneous and recorded spend can exceed the amount. Older help content
  describes soft thresholds; use current primary docs, not a blanket claim that
  all project limits are either hard or soft. Neither establishes a strict task cap.
- OpenRouter was investigated but **not selected**. Its
  [limits](https://openrouter.ai/docs/api_reference/limits) and
  [workspace-budget caveat](https://openrouter.ai/docs/guides/features/workspaces/workspace-budgets)
  distinguish account-level estimated in-flight protections from all per-task/key
  controls; ordinary budgets can allow already-dispatched work to finish. Do not
  switch the chosen reference solely because another product advertises a cap.

Documentation is evidence of available integration surfaces, not proof of our
deployment, provider-cost bounds, or adapter correctness.

## 7. Relevant existing files/tests

- `engine/company/connectors.py`, `connector_views.py`, `tasks.py`, `models.py`,
  `services.py`: current identity/scope, explicit-task/event linkage, historical
  roles, strict metadata payloads, ownership/corrections, and immutable retry rules.
- `engine/company/company_learning.py`, `learning_views.py`: exact reviewed
  artifact publication, current vetoes, future manual application and reversals.
- `engine/company/authorization.py`, `live_authorization.py`, `readiness_gate.py`,
  `security.py`, `mfa.py`: separate human/live readiness and revocation authority.
- `engine/company/admission_gate.py`, `selection.py`, `selection_views.py`:
  immutable proof requests, conditional reservations/claims/settlement and controls.
- `engine/pilot.py`, `feedback.py`, `learning.py`, `readiness.py`, `privacy.py`:
  preserve simulation, canonical record/decimal contracts and simple learner baseline.
- `integrations/opencode/src/{index.mjs,tui.tsx,core.mjs,actions.mjs,client.mjs,rpc.mjs,boundary-selection.mjs}`:
  observer/plugin/transport source and default-refusing binding seam. Keep it
  outside automatic `.opencode/plugins/` discovery until explicit load approval.
- `tests/test_company.py`, `test_live_authorization.py`, `test_browser_workflow.py`,
  `test_connectors.py`, `test_connector_http.py`, `test_company_learning.py`,
  `test_selection.py`, `test_feedback_roles.py`, existing engine suites, and
  `integrations/opencode/test/*.test.mjs`.
- Migrations `0001`–`0007` are additive and tested on isolated synthetic stores.
  New changes must preserve historical records/keys/accounts; no owner DB upgrade
  or reset is part of ordinary implementation.

## 8. Other remaining build — after the adapter

### B-04 / B-05 supported flow completion

Complete exact supported request/usage/error capture and actual bounded delivery/
settlement through the chosen path. Automatic subagent/new-run inference and
multi-model positive-result attribution are not implemented. Add only a supported,
documented boundary/attribution design; keep failures/unknowns from everyone even
when positive attribution is refused. Do not use a source label or API success
as engineering truth.

### B-06 monitoring, privacy, and operations

Build continued company-wide permitted monitoring/alerts, explicit retention/
privacy controls, actual delivery revocation/default-only rollback integration,
supported install/start/update/recovery instructions, and one joined workflow demo.
Reuse existing pause/monitor, accounts/MFA, backup/recovery, and Waitress contract.
Retention duration/deletion policy is **not chosen**: ask for a genuinely required
owner decision before destructive automatic deletion; never remove failures or
silently delete owner backups/journals. No real deployment configuration is supplied.

### B-07 stable policy handoff

Define a versioned export/integration contract for the chosen existing LiteLLM/
OpenCode path: exact policy/learner/content, model aliases/capabilities/scope,
compatibility/version validation, no provider secrets/raw content, and clear
unsupported cases. Exported policy is not portable live approval or an execution
credential; company authority must still be rechecked at the boundary.

Keep `docs/TASKS.md` updated as work proceeds. Complete only implemented/tested
behavior; list missing software separately from deferred validation.

## 9. Non-negotiable working limits

- Use `.venv/bin/python` for **every** Python command. Approved Python 3.13.12;
  company packages in `requirements-company.txt`. Do not install new dependencies,
  SDKs, gateways, Redis, node/Solid peers, tokenizers, Laya, or model weights without
  separately explaining the need and obtaining approval.
- Preserve `local/`, old environment backups, databases/keys, feedback, journals,
  and backups. Do not inspect credentials or create the owner's password. Tests
  use new temporary synthetic stores. No implicit upgrade/repair/bootstrap.
- Do not access private OpenCode sessions/messages/config credentials or perform
  paid/free generation/model/provider calls. Do not auto-start private services or
  load the connector into this conversation. A fake-provider test is controlled
  software output, not an actual local model inference request.
- Recommendation-only shadow makes no extra alternative-model requests and leaves
  model choice manual. First automatic pilot needs explicit designated fresh-MFA
  approval plus independent readiness/admission. Learning cannot authorize it.
- No Laya in the current build. Give evidence-backed recommendations; do not change
  advice simply to agree with the owner. Explain genuine new evidence/tradeoffs.
- Explain technical terms with a brief bracketed definition and use plain language.
  No production quality/savings/security claims from public/synthetic data/test counts.
- Never weaken/remove assertions. Preserve canonical columns, complete decimal
  output, negative results, role history, failed requests and stale/replay refusal.
  Tune on validation data, not held-out tests; no production numeric gates guessed.
- Local reviewed commit batches authorized; **no public push** until licence choice.
  This handoff update is uncommitted and must be preserved. No subagents unless the
  owner/applicable instructions explicitly authorize delegation.

## 10. Next-session instruction

Recover the context and baseline, then implement the real narrow adapter for the
accepted LiteLLM/company OpenAI reference with controlled fake-provider tests.
Preserve the existing service/authority and finish the supported joined flow first,
then remaining B-06/B-07. Ask only for genuinely blocking new dependencies/choices,
not for real credentials/access that local construction does not require. Keep
software completion, host/provider validation, and live-use authorization separate.
