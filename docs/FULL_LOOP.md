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
2. `shadow` — developers record tasks (S1–S3, J1 documentation; T1–T3 test writing);
   Tarkado suggests a model; the developer accepts or rejects; OpenCode runs; CI produces the
   result; the developer reports the actual model and result. Only senior-accepted suggestions
   that succeed count as evidence, and one rejection or failure blocks that model for that
   task type permanently (see ROADMAP.md), so the shadow seniors accept luna.
3. `review`, `publish` — owner prepares the category evidence review and publishes the learner.
4. `approve <review> <pilot id> documentation,test_generation` — the pilot approver grants
   live scope with password + fresh MFA code (8 tasks, USD 0.50, 10 h); activation.
5. `delivery` — gateway credential and developer pairing for routed delivery.
6. `routed R1 R2 R3` — a new task through the plugin (R3 is test writing): Tarkado selects at the new-task boundary,
   binds a session, the developer accepts, OpenCode → LiteLLM → provider runs, CI, gateway
   close settles the known cost, then actual model and result are reported. The runner
   reports nothing if the provider did not demonstrably complete (unknown attempts, zero
   known cost, or a failed run).
7. `relearn` — the next learning review including the routed outcomes.
8. Failure path — any failed/unknown routed outcome pauses the pilot; the owner rolls it
   back with `rollback "<reason>"` (fresh MFA). Run 1 exercised this for real (see
   DECISIONS.md, 2026-10-24).

Recovery: `recover <task_ref>` (gateway close, then end-interrupted, creates a gap),
`close_refused <id> "<why>"` (gateway refused before any paid attempt),
`rescope <label> <pilot_id> documentation,test_generation`.
Never re-submit a lost start; never reuse a task label.

## Laptop demo

The stack stays on the host; a Mac or Windows laptop runs only a pinned, isolated OpenCode
2.0.21 with the Tarkado delivery plugin (its own OpenCode config, providers and MCP servers
are not used). Needs Node.js 20+ and git, and the host's company/gateway URLs must be
reachable from the laptop.

On the host (the pilot, gateway and connectors expire within 24 h, so do this the same day):

1. `renew` issues a new gateway identity (they last 20 h) and restarts LiteLLM with it.
2. `rescope <new label> <new pilot id> documentation,test_generation` reviews the evidence
   again and approves a new trial (10 h). Labels and pilot ids are never reused.
3. `laptop <persona> <exact absolute repo path on the laptop> <bundle>` writes the private
   bundle `local/full-loop/laptop/<bundle>.json` (it embeds the gateway reference, so make it
   after `renew`). Send it privately; never commit it.

On the laptop, from a checkout of this branch:

1. `node demo/laptop/start-demo.mjs check <bundle.json>` installs OpenCode once, creates the
   DEMO repository at the bundle path, checks both URLs, and checks that this OpenCode's tool
   definitions match the reviewed host (otherwise the gateway would refuse every request).
2. `node demo/laptop/start-demo.mjs start <bundle.json>`, then in OpenCode:
   `/tarkado-delivery-quick` → **Use suggestion** (one confirmation; records the acceptance)
   → pick the task type (documentation or test-writing) → type the task → wait until it is
   idle → `/tarkado-delivery-end` → **End task** → rate it 0–5 (or Skip).
   **Keep OpenCode open until end.** "Keep mine" (or Esc) starts nothing. Normal prompts
   outside a Tarkado task go to team-sol unrouted; the footer shows `<task> → <model>` inside one.
   Quick start takes every bound from the bundle's reviewed `quickStart` defaults
   (original choice company/sol, read+edit tools, 20k context, 4096 output, USD 0.10 cap,
   label `<persona>-<UTC timestamp>`); it only asks which trial/category when more than one
   applies. At end it reports the model only if the gateway shows every attempt completed on
   the bound model at a known cost with nothing unknown or reserved; otherwise it reports
   nothing. `/tarkado-delivery-start` remains the fully explicit path (and the only path for
   bundles without `quickStart`, which need regenerating to use quick start).
3. Nothing to do on the host: the company settles the task's cost itself when it is ended,
   or when its last cost arrives (the trial lets the next task start only once that has
   happened). `settle <task_ref>` is the manual fallback.

Ratings: 5 used as-is · 4 small fixes only · 3 usable after real edits · 2 mostly redone ·
1 wrong or unusable · 0 harmful (broke something or misleading). The rating is recorded right
after End as the task's one result: 4–5 = desired result, 0–3 = not (score = rating / 5).
Keep OpenCode open until the "Rating … recorded" message. Expect select to take about 10 s.

What happens to the trial (automatic):

- Rated 4–5, or skipped: the trial continues.
- Rated 0–3: the trial pauses until a new review, and that review blocks luna for that task
  type (today one failure vetoes a model).
- OpenCode closed before End: the task needs browser recovery, which records a gap; the trial
  pauses until a new review.
- A task is rated once. A second result is a correction, which also pauses the trial.

Re-approval: the pilot approval accepts only outcomes checked by the company CI, which runs
on the host. Laptop work is not CI-checked, so after any laptop task (rated or not) the next
approval for that task type is refused. Rescope before the first laptop task of the day, then
run the rehearsal and the demo within that one trial (8 tasks, USD 0.50, 10 h).

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
