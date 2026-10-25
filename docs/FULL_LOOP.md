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

## Laptop demo

The stack stays on the host; a Mac or Windows laptop runs only a pinned, isolated OpenCode
2.0.21 with the Tarkado delivery plugin (its own OpenCode config, providers and MCP servers
are not used). Needs Node.js 20+ and git, and the host's company/gateway URLs must be
reachable from the laptop.

On the host (the pilot, gateway and connectors expire within 24 h, so do this the same day):

1. `rescope <label> <new pilot id>` if the pilot is stale or expired, and renew the gateway.
2. `laptop <persona> <exact absolute repo path on the laptop> <bundle>` writes the private
   bundle `local/full-loop/laptop/<bundle>.json`. Send it privately; never commit it.

On the laptop, from a checkout of this branch:

1. `node demo/laptop/start-demo.mjs check <bundle.json>` installs OpenCode once, creates the
   DEMO repository at the bundle path, checks both URLs, and checks that this OpenCode's tool
   definitions match the reviewed host (otherwise the gateway would refuse every request).
2. `node demo/laptop/start-demo.mjs start <bundle.json>`, then in OpenCode:
   `/tarkado-delivery-quick` → **Use suggestion** (one confirmation; records the acceptance)
   → type the task → wait until it is idle → `/tarkado-delivery-end` → **End task**.
   **Keep OpenCode open until end.** "Keep mine" (or Esc) starts nothing. Normal prompts
   outside a Tarkado task go to team-sol unrouted; the footer shows `<task> → <model>` inside one.
   Quick start takes every bound from the bundle's reviewed `quickStart` defaults
   (original choice company/sol, read+edit tools, 20k context, 4096 output, USD 0.10 cap,
   label `<persona>-<UTC timestamp>`); it only asks which trial/category when more than one
   applies. At end it reports the model only if the gateway shows every attempt completed on
   the bound model at a known cost with nothing unknown or reserved; otherwise it reports
   nothing. `/tarkado-delivery-start` remains the fully explicit path (and the only path for
   bundles without `quickStart`, which need regenerating to use quick start).
3. On the host: `settle <task_ref>` (gateway close, known cost).

The model is reported from the laptop; the result stays unknown there (the CI key stays on
the host). Expect select to take about 10 s.

## Provider

The gateway calls one reviewed OpenAI-transport endpoint (`provider_api_base`, gateway
startup schema v2). Provider keys stay in LiteLLM's configuration and environment, never in
Tarkado files. A different OpenAI-compatible endpoint (for example Azure AI Foundry's
`https://<resource>.services.ai.azure.com/openai/v1/` with deployment names as provider
models) should only need configuration, but is unverified until run against a real resource.

## Recorded runs (2026-10-24)

- **Run 1** (retained, `local/full-loop-run1/`): a gateway defect made the provider reject
  routed task R1b; the pilot paused, the owner rolled it back, and the next review correctly
  refused live re-approval of luna for documentation. See DECISIONS.md.
- **Run 2** (fresh DEMO company, fixed code, about 8 minutes end to end): 5 shadow tasks →
  review → publish → MFA approval and activation → pairing → routed R1 (junior) and R2
  (senior) on luna through OpenCode → LiteLLM → provider, both CI-passing, settled at
  $0.0019612 and $0.0021550 with zero unknown attempts → relearn review published.
