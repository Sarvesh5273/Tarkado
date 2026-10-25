# Roadmap: adopting a new model in a company

One page. It sets the owner's lifecycle beside what exists today (the Monday 2026-10-26 demo)
and the changes we recommend. "Today" means built and demonstrated in the DEMO company;
everything else is planned, not built.

## The lifecycle

| Phase | Who | What happens | Moves on when | Today |
| --- | --- | --- | --- | --- |
| 0. Prior | Owner | New model added to the company gateway. A starting policy comes from public evidence (benchmarks, provider docs); only narrow low-risk task types get a suggestion | The owner publishes the starting policy | Hand-written policy file (`demo/full_loop/policy.json`); no public-evidence import |
| 1. Trial | All developers, opt-in | Tarkado *suggests* a model per task; accepting switches the model for that task only; every task can be rated 0–5 at End | Per task type: enough senior-accepted, rated, CI-checked successes | Built: suggestions, accept/reject, actual model, CI result, 0–5 rating |
| 2. Senior pilot | Seniors | The engine drafts a policy; the approver grants a time- and budget-limited pilot that *routes automatically* at the new-task boundary | Pilot evidence passes the next review | Built: review, password + MFA approval, limited pilot (8 tasks, $0.50, 10 h), routing for documentation + test-writing → luna |
| 3. Approval | Manager | The policy is reviewed and approved in the company portal | Approval recorded | Built (portal review + approval pages) |
| 4. Rollout | All developers | Automatic routing for approved task types; ratings continue; the portal watches quality and cost; the policy changes on enough bad feedback | — | Partly: a 0–3 rating, a corrected result, a recovery gap or an unknown cost pauses routing automatically until a new review; rollback / revoke are manual; no failure-rate threshold yet |

## Recommended changes to the plan

1. **Gate phases on evidence per task type, not on a fixed two weeks.** Documentation may be
   ready in days; refactoring may never be. Each task type moves when its own thresholds pass.
2. **Phase 1 is an opt-in trial, not a shadow test.** People accept suggestions on easy tasks,
   so the evidence is biased toward easy work. Add a small blind side-by-side sample (same task,
   both models, a senior picks without knowing which is which).
3. **Rate per task, not per response, and make it skippable.** One tap at End task, each score
   with a fixed meaning (5 used as-is … 0 harmful). Count "redid it on my usual model" as a low rating.
4. **Day-one routing only for narrow, low-risk types** (documentation, test-writing) — not
   "general queries" — and always visible and overridable.
5. **Juniors can't always judge weak output.** After rollout, rely on CI and overrides plus
   ongoing blind senior spot checks, not on junior ratings alone.
6. **Define the monitoring trigger exactly:** a rolling window per model *and* reasoning effort,
   a minimum sample size, and a failure-rate threshold that pauses routing automatically.

## Engine rules found while building the demo (change before real use)

- **Learning counts only senior-accepted suggestions.** A senior who overrides a suggestion
  and succeeds adds no evidence. This is sound (the suggestion was the thing tested), but it
  means phase 0 must suggest the new model for anything to be learned.
- **One rejection or one failure blocks a model for a task type permanently.** The review says
  "investigate", but there is no way to record an investigation. Needed: an owner action
  "investigated, reason …" in the portal, and a failure-rate threshold instead of a single veto.
- **A task with no recorded result blocks the next review.** Correct (missing outcomes bias the
  evidence), but it makes the End-task rating essential, not optional polish.
- **Approval accepts only CI-checked outcomes.** Laptop work never reaches the company CI, so a
  laptop task's outcome, rated or not, blocks the next approval for its task type. Needed: CI on
  the pushed change (the pull request), cited by the task's result, with the rating as its score.
- **The rating is the task's one result** (4–5 = desired, 0–3 = not), recorded right after End.
  The trial also needs the task's cost settled before the next task starts; the demo stack does
  this automatically, and in production the gateway should do it when the task ends.

## Not built yet

Public-evidence import for phase 0 · blind side-by-side sampling · per-reasoning-effort tracking ·
a failure-rate threshold (today one bad rating pauses) · CI on the pushed change for laptop
work · the investigation action · per-prompt (rather than per-task) suggestions.
