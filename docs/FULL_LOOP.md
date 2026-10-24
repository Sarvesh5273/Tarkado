# Full-loop demo (DEMO only)

One DEMO company runs every stage of the loop on installed hosts: OpenCode 2.0.21 with
the Tarkado plugin, LiteLLM 1.104.0 with the Tarkado delivery callback, the company app,
and a real provider. Everything here is labelled DEMO: thresholds are reduced (3 senior
successes / 3 sessions), the sample repository is synthetic, and the people are personas
(`owner` = administrator and pilot approver, `senior`, `junior`).

## Pieces

| Piece | Where | Notes |
| --- | --- | --- |
| Stack supervisor | `demo/full_loop/stack.py` | Company app (:8000), gateway (:3000), one OpenCode server per developer. SIGHUP restarts LiteLLM only. |
| Stage runner | `demo/full_loop/run_loop.py <stage>` | Each stage is resumable; state in `local/full-loop/` (gitignored). |
| Fixture tasks | `demo/full_loop/tasks.json`, `demo/full_loop/sample_repo/` | Fixed DEMO instructions; no private prompts. |
| CI | `demo/full_loop/demo_ci.py` | Parses, scope, docstrings, behaviour unchanged, unit tests. Its record id is the result evidence. |
| Transcript | `local/full-loop/run/transcript.log` | Metadata only: no prompts, outputs or keys. |

## Stages

1. `setup`, `people` — bootstrap the company store, the owner with MFA, the developers,
   OpenCode hosts with isolated XDG directories.
2. `shadow` — developers record tasks; Tarkado suggests a model; the developer accepts or
   rejects; OpenCode runs; CI produces the result; the developer reports the actual model
   and result.
3. `review`, `publish` — owner prepares the category evidence review and publishes the learner.
4. `approve` — the pilot approver grants live scope with password + fresh MFA code; activation.
5. `delivery` — gateway credential and developer pairing for routed delivery.
6. `routed R1 R2` — a new task through the plugin: Tarkado selects at the new-task boundary,
   binds a session, the developer accepts, OpenCode → LiteLLM → provider runs, CI, gateway
   close settles the known cost, then actual model and result are reported. The runner
   reports nothing if the provider did not demonstrably complete (unknown attempts, zero
   known cost, or a failed run).
7. `relearn` — the next learning review including the routed outcomes.
8. Failure path — any failed/unknown routed outcome pauses the pilot; the owner rolls it
   back with `rollback "<reason>"` (fresh MFA). Run 1 exercised this for real (see
   DECISIONS.md, 2026-10-24).

Recovery: `recover <task_ref>` (gateway close, then end-interrupted, creates a gap),
`close_refused <id> "<why>"` (gateway refused before any paid attempt), `rescope <label> <pilot_id>`.
Never re-submit a lost start; never reuse a task label.

## Provider

The gateway calls one reviewed OpenAI-transport endpoint (`provider_api_base`, gateway
startup schema v2). Provider keys stay in LiteLLM's configuration and environment, never in
Tarkado files. A different OpenAI-compatible endpoint (for example Azure AI Foundry's
`https://<resource>.services.ai.azure.com/openai/v1/` with deployment names as provider
models) should only need configuration, but is unverified until run against a real resource.
