---
format: 1920x1080
duration: 125s
message: "Recommend with evidence. Route with permission. Preserve developer control."
arc: how-to-process
audience: professor and engineering reviewers — a visual concept demonstration of intended behaviour
mode: autonomous
music: none
---

## Video direction

**What this film is.** A silent, captioned walkthrough of one intended deployment workflow, told
as a causal chain. It is a concept demonstration, not the product and not a claim of results.
Every surface is invented; the two surfaces are an illustrative OpenCode-style terminal and the
Tarkado dashboard, defined once in `frame.md` § Shared surfaces — build them identically in every
frame, down to the title-bar chip, the rail items and the caption band.

**Palette system (from `frame.md`, never invented).** Cream ground · tile half-step for content ·
ink voice · coral rationed to the kicker ✱ and at most one other moment · warm navy reserved for
the terminal/code surface. The four semantic hues (`--st-info` blue, `--st-ok` green,
`--st-warn` amber, `--st-danger` red) appear only inside status chips / row badges / node states,
always as **glyph + label + colour**. Their meanings are fixed for the whole film:

- **blue / info** — information, neutral state, permitted scope, approved default
- **green / ok** — supported positive signal, confirmed, active
- **amber / warn** — unknown, pending, review-required, paused
- **red / danger** — failure, stopped operation, explicit "not done"

Modes get their own always-visible chips so they can never be confused: `SHADOW` (blue),
`PILOT — approved scope` (green), `PENDING REVIEW` (amber), `PAUSED` (amber), `STOPPED` (red),
`DEFAULT ONLY` (blue). Never a mode shown by colour alone.

**Motion grammar + reveal model.** `power3` long-tail settles (smooth, never bouncy); reveals are
**paced across the whole frame duration**, one piece per beat, with the back ~40% still delivering
new information — never a canvas dumped at t=0. Entrances are `fromTo`. No exits on non-final
frames (the frame transition is the exit). During a hold: still, at most **subtle jitter**
(`sine-wave-loop`, low amplitude). Gentle camera reframing only — `viewport-change` pans locked to
one oversized canvas; no back-half push, no drifting parallax. Cursors move on short eased paths
and rest; typing is restrained (≤ 44 characters, one line). No `repeat`/`yoyo`, no randomness, no
clocks.

**Rhythm / held reads.** Reveal-dense: 1, 2, 3, 4, 5, 6, 9, 10, 11, 12. Deliberate held reads
(still, ≥ 1.2s, for comprehension): frame 7's proposal panel, frame 8's disclaimer footer,
frame 9's approved state, frame 13's final hold. Each frame's most important state must be
readable ≥ 1.5s before the cut.

**Negative list (never appears).** Raw JSON; a table wider than 3 columns or type below 1.4cqw;
neon, glow, bokeh, purple-blue "AI" gradients; a second brand hue beyond coral; colour-only
status; savings percentages or any efficiency claim; consumer pricing or subscriptions; secrets,
tokens or unmasked MFA digits; meaningless shell commands; OS window chrome, browser chrome or
scrollbars (a **designed cursor glyph** is allowed — the subject is the interface); claims of
pixel-perfect OpenCode fidelity (the reconstruction chip must be present); silent retraining,
auto-activation, or an active task changing model. Both failure modes are banned: **slideshow**
(front-load then freeze) and **screensaver** (everything drifting at once).

**Continuity.** Kickers are numbered `01 … 13` with the coral ✱. The caption line sits in the same
band every frame. Terminal frames and dashboard frames alternate but always cut with the same
three seams: `cut` (cold open), `push-slide LEFT` (moving forward through the workflow),
`crossfade` (staying inside the same surface). Fictional names, task ids, model labels and policy
versions are identical everywhere — see `frame.md` § Consistent fiction.

**Layout variety across the film.** 70/30 editorial (1, 7) · asymmetric 60/40 station pan (3, 5) ·
framed window centred (2, 9) · split stage with drawer (4, 10) · full-width strip (5, 11) ·
triptych (8) · stacked evidence ledger (6, 12) · centred lockup (13).

## Frame 1 — Two manual choices

- scene: One oversized hairline canvas holds two labelled OpenCode-style terminal stations; a single camera pans between them while a cursor makes two independent manual model picks
- voiceover: ""
- duration: 9s
- transition_in: cut
- poster: 7s
- status: outline
- src: compositions/frames/01-two-manual-choices.html
- type: hook
- persuasion: Concretization + contrast of two options
- beat: recognition and curiosity
- blueprint: spatial-pan-stations (Adapt)
- focal: the two OpenCode-style terminal stations riding one oversized canvas
- roles: terminals = foreground subject · hairline grid ground = background (dim ~40%) · kicker, caption, connector callout = supporting
- sfx: tick, soft click

Adapt: keep the signature — pre-placed stations traversed by one virtual camera, last station held;
add a third "callout" station (the connector between the two model chips) that the final settle
frames alongside them.

Scene 1 (0.0–2.4s): cream ground with a faint hairline grid (background, dim). Editorial 70/30,
content upper-left, right third empty. Kicker `✱ 01 — THE PROBLEM` then the hero line
**"Different tasks need different models."** enters via **per-word staggered reveal**
(`dynamic-content-sequencing`) on a smooth long-tail settle; the sub-line **"Price alone does not
establish quality."** lands on its own beat beneath it in smaller Inter. Nothing else is on
screen.

Scene 2 (2.4–5.0s): **pan / focus-lock** (`viewport-change`) travels right along the canvas and
centres station A — Maya's terminal: title bar with the `OpenCode-style · illustrative
reconstruction` chip, header `SESSION maya · branch feat/idempotency-key · TASK-201`, two short
conversation rows, a `test` tool-activity row, and the composer's **`MODEL · Apex-Premium
(manual)`** chip. Asymmetric 60/40, station fills the left 60%. The cursor glides to the chip and lands a
**cursor click + ripple** (`cursor-click-ripple`) — a tactile, damped press, no overshoot.

Scene 3 (5.0–7.6s): the same **pan** continues to station B — Arjun's terminal, identical chrome,
`SESSION arjun · TASK-202 docs page`, a `read` activity row, model chip **`MODEL · Apex-Standard
(manual)`**; the cursor repeats the click. A connector **draws itself** between the two chips
(**SVG self-draw** → `svg-path-draw`) and a small info-blue label chip lands on it:
`manual choice · no shared evidence`.

Scene 4 (7.6–9.0s): the camera **settles** so both stations and the connector sit side by side
(centered 2-up, grid still dim beneath). The introducing line **"Tarkado — evidence-based model
choice for engineering teams."** enters **per-word staggered reveal** in the lower band of the
stage; the frame then holds STILL — no drift, no breathing. No number, no percentage, anywhere.

narrativeRole: Establishes that model choice is already per-task and per-person, and made without shared evidence — then names the idea that will organise the rest of the film.
keyMessage: Different tasks need different models, price alone proves nothing, and Tarkado exists to make that choice evidence-based for a whole team.

## Frame 2 — Company setup

- scene: The Tarkado dashboard walks its own setup screens — administrator, MFA, two invites, approved models, and an explicit collection scope
- voiceover: ""
- duration: 10s
- transition_in: push-slide LEFT
- poster: 8s
- status: outline
- src: compositions/frames/02-company-setup.html
- type: feature_showcase
- persuasion: Progressive disclosure + numbered enumeration
- beat: orientation and confidence
- blueprint: cursor-ui-demo (Reproduce)
- focal: the Tarkado setup window
- roles: dashboard window = foreground subject · cream ground + faint grid = background · caption, SSO note, rail = supporting
- sfx: tick, soft click

Reproduce: locked static stage, a designed cursor drives the reconstructed dashboard through
clicks, and element swaps do the "camera work" — the signature move is the cursor-driven state
change, kept intact.

Scene 1 (0.0–2.2s): the dashboard slides in on the **push** (`push-slide LEFT` seam) to a centred
framed window, 72% of the stage: rail `Overview ✱ Members · Models · Collection · Evidence ·
Pilot`, header `TARKADO · installation setup · Northwind Labs`. The cursor moves to card
`1 — Administrator` and lands a **cursor click + ripple** (`cursor-click-ripple`). Kicker
`✱ 02 — COMPANY SETUP` upper-left.

Scene 2 (2.2–4.6s): the card **steps in place** through two states via **in-place token cycle**
(`discrete-text-sequence`): `Create administrator → Sam Ortiz` then `Multi-factor authentication`
with a masked field `••••••` filling one dot at a time (**in-place token cycle** →
`discrete-text-sequence`); a green chip **`✓ MFA enabled`** settles beside it. No digits, no
caret, ever shown.

Scene 3 (4.6–7.0s): the `Members` card reveals two invite rows with a staggered reveal, each glyph + label: `Maya — senior developer — invited`, `Arjun —
junior developer — invited`; their chips cycle amber `pending invite` → green `✓ active` one
after the other.

Scene 4 (7.0–8.6s): two supporting panels reveal side by side (40/40, centred gap): **`Approved
models`** — `Apex-Premium ✓ approved premium`, `Apex-Standard ✓ approved standard`, and beneath a
rule `Approved premium fallback → Apex-Premium`; and **`Collection scope — permitted`** — chips
`category`, `model selected`, `usage`, `outcome status`. Info-blue, glyph + label.

Scene 5 (8.6–10.0s): a third narrow panel drops in below with a lock glyph: **`Not collected —
blocked`** and four struck items `raw prompts · source files · secrets · model outputs` — each strike wiping
across on its own beat (a short left-to-right sweep, danger red). The caption line and a small mono note
`Existing company SSO is optional.` sit in the caption band; the window holds STILL.

narrativeRole: Shows the setup as a company-controlled act of scope-setting before any recommendation exists — accounts, models and collection are all declared up front.
keyMessage: Individual accounts, company-controlled models, and an explicitly permitted collection scope — with everything else blocked.

## Frame 3 — Observe everyone

- scene: Two stacked terminals keep working while permitted metadata chips cascade into a Tarkado column, and a locked lane shows what never travels
- voiceover: ""
- duration: 8s
- transition_in: push-slide LEFT
- poster: 6s
- status: outline
- src: compositions/frames/03-observe-everyone.html
- type: feature_showcase
- persuasion: Demonstration (show the mechanism running) + subtractive framing
- beat: comprehension
- blueprint: grid-card-assemble (Adapt)
- focal: the vertical column of permitted metadata chips assembling from both terminals
- roles: terminals = foreground subject · right-hand Tarkado column = foreground subject · blocked lane = supporting · ground = background
- sfx: tick

Adapt: keep the signature — N items self-assemble in a staggered cascade into a vertical list;
here the cascade runs horizontally out of two terminals into one column, then a blocked lane
assembles beneath it.

Scene 1 (0.0–2.0s): push-slide settles on a 60/40 split stage: left, two stacked OpenCode-style
terminals (Maya `TASK-214` above, Arjun `TASK-219` below) whose tool-activity rows advance one
line at a time under a restrained caret; right, an empty column headed `TARKADO · shadow` with a
blue mode chip and the line `permitted metadata only`. Kicker `✱ 03 — OBSERVE`.

Scene 2 (2.0–4.6s): permitted chips **self-assemble in a staggered cascade** (`grid-card-assemble`
signature via `dynamic-content-sequencing`) from each terminal into the column, each with glyph +
label: `category · unit-test`, `model selected · Apex-Premium`, `usage · 1 task / 2
continuations`, `outcome · unknown` (amber) and a second `outcome · known` (green). An arrow from
each terminal draws in behind them (`svg-path-draw`).

Scene 3 (4.6–6.6s): beneath the column a **locked lane** reveals: a danger-red header `NOT
TRANSMITTED` with a lock glyph, then four struck rows `raw prompts`, `source files`, `secrets`,
`model outputs` — each strike drawn on (**SVG self-draw** → `svg-path-draw`). Supporting scale,
never the focal.

Scene 4 (6.6–8.0s): both composer model chips get an info-blue tick **`unchanged — developer
still chooses`**; the caption line `Observe approved work across participating developers.` sits
in the band; the frame holds STILL with the two chips still reading `Apex-Premium (manual)` and
`Apex-Standard (manual)`.

narrativeRole: Separates observation from control — Tarkado sees approved task metadata and nothing else, and seeing changes nothing about who chooses.
keyMessage: Observation is scoped metadata only; the developers' model selections are untouched.

## Frame 4 — Shadow recommendation

- scene: Maya starts a low-risk unit-test task, the Tarkado drawer expands beside the workflow and lays out a shadow recommendation with three explicit choices
- voiceover: ""
- duration: 9s
- transition_in: crossfade
- poster: 7s
- status: outline
- src: compositions/frames/04-shadow-recommendation.html
- type: feature_showcase
- persuasion: Progressive disclosure (one field at a time) + explicit counter-example
- beat: comprehension + cautious confidence
- blueprint: cursor-ui-demo (Reproduce)
- focal: the Tarkado task drawer and its suggestion block
- roles: terminal = foreground subject · drawer = foreground subject · caption + stamp = supporting · cream ground = background
- sfx: soft click, tick

Reproduce: locked static stage; the cursor opens the task and then the drawer; the signature
cursor-click drives each state change.

Scene 1 (0.0–2.6s): crossfade into Maya's terminal filling the stage (title-bar reconstruction
chip visible). The cursor clicks `+ New task` in the session header (**cursor click + ripple** →
`cursor-click-ripple`); the composer types on: `write unit tests for
idempotency_key()` — 44 characters, one line, restrained, behind a steady caret
(**type-on with caret** → `discrete-text-sequence`). A mono chip `LOW RISK · unit tests`
attaches to the header; the composer's model chip reads `Apex-Premium (manual)`. Kicker
`✱ 04 — SHADOW`.

Scene 2 (2.6–5.2s): the cursor clicks the `TARKADO` tab; the drawer **expands** from the right
edge and settles long-tail. Its rows then reveal one at a time on a staggered reveal, each with
glyph + label: `Mode · SHADOW` (blue), `Currently selected · Apex-Premium — approved premium`,
`Suggested · Apex-Standard — approved standard` (green glyph), `Reason · relevant category
evidence supports review`, `Confidence · LIMITED — inspect evidence` (amber),
`Fallback · Apex-Premium — approved premium`. Asymmetric 55/45, drawer right.

Scene 3 (5.2–7.4s): three buttons arrive together on one beat with a restrained spring entrance
(smooth long-tail settle, no bounce): `[Accept suggestion]` `[Reject]` `[View
evidence]`. The cursor moves to `[View evidence]` and clicks; a compact read-only popover opens
above the buttons: `Evidence · 42 linked records · 6 sessions · senior-weighted`, blue header
chip `READ ONLY`, and closes again.

Scene 4 (7.4–9.0s): a danger-red outlined stamp lands directly under the suggestion — a
slashed-arrows glyph plus **"No duplicate alternative-model request."** — revealed by **marker
emphasis** (`css-marker-patterns`, outline draw, no fill). The caption
`Recommend first. The developer still chooses.` sits in the band; the frame holds STILL.

narrativeRole: Makes the shadow contract concrete — a suggestion with its reason, its limits and its fallback, handed to a developer who still owns the decision.
keyMessage: In shadow mode Tarkado only recommends; the developer chooses, and no second model request is ever made.

## Frame 5 — Acceptance is not success

- scene: One stage carries the causal chain — accept, record flips to pending, a separate manual model pick, then the single request path draws itself
- voiceover: ""
- duration: 10s
- transition_in: crossfade
- poster: 8s
- status: outline
- src: compositions/frames/05-acceptance-not-success.html
- type: feature_showcase
- persuasion: Causal chain + subtractive framing (what acceptance is not)
- beat: clarity + resolve
- blueprint: compose
- focal: the three-node request path, with the single travelling task token
- roles: drawer + record = foreground subject · request path strip = foreground subject · terminal = supporting · ground = background
- sfx: tick, soft click

Compose: three beats on one locked stage — record, then the separate manual action, then the
path. Reveals stay spread across the full 10s; the path is not drawn before the manual pick lands.

Scene 1 (0.0–2.8s): crossfade to a 60/40 stage — Maya's terminal left, Tarkado drawer right with
the same recommendation rows held from the previous frame. The cursor clicks **`[Accept
suggestion]`** (**cursor click + ripple** → `cursor-click-ripple`, then **button press** →
`press-release-spring`). The record line **steps in place** via **in-place token cycle**
(`discrete-text-sequence`): `Suggestion pending` → **`Suggestion accepted — outcome pending`**,
with an amber chip glyph `✓ ⏳ ACCEPTED · OUTCOME PENDING`. Kicker `✱ 05 — ACCEPTANCE ≠ SUCCESS`.

Scene 2 (2.8–5.4s): a divider label `Not recorded by acceptance:` and three struck items reveal
on a **staggered reveal** — `task success` · `pilot approval` · `model switch` — each strike
drawn with **SVG self-draw** (`svg-path-draw`), danger red. Then, separately and lower in the
terminal, the cursor travels to the composer's **`MODEL` selector**, opens it, and deliberately
picks **`Apex-Standard`** (**cursor click + ripple**); the chip flips to `Apex-Standard (manual)`
and a mono note attaches: `manual model selection · separate action`.

Scene 3 (5.4–8.0s): the lower third builds the request path as a full-width strip (3 nodes,
centred, generous gaps): **`OpenCode`** → **`Existing LiteLLM Proxy`** → **`Company-managed model
API`**, each node entering on its own beat via **layer-reveal** and each connector drawn with
**SVG self-draw** (`svg-path-draw`). The proxy node carries an info-blue chip
`company-managed routing`.

Scene 4 (8.0–10.0s): a single labelled token **`TASK-214`** travels once along the drawn path from
OpenCode to the model API (deterministic tween along the path, long-tail ease), and beneath it
**"Only the selected model receives the task."** reveals, with a small danger-red note
`no parallel alternative request`. The path then holds STILL — no looping travel.

narrativeRole: Breaks the most dangerous misunderstanding — accepting a suggestion is a recorded preference, and the model only changes through a separate deliberate human action.
keyMessage: Acceptance records preference, not task success and not pilot approval; a single manual selection is what routes the task.

## Frame 6 — Link actual use and result

- scene: A four-link task record cascades into one connected chain, system signal and engineering outcome separate, then two sourced evidence cards and a smaller counter-example arrive
- voiceover: ""
- duration: 10s
- transition_in: crossfade
- poster: 8s
- status: outline
- src: compositions/frames/06-link-use-and-result.html
- type: social_proof
- persuasion: Causal chain + worked example with real (fictional) values
- beat: comprehension + conviction
- blueprint: grid-card-assemble (Reproduce)
- focal: the connected four-link record for TASK-214
- roles: chain = foreground subject · evidence input cards = foreground subject · counter-example card = supporting · ground = background
- sfx: tick

Reproduce: N cards self-assemble in a staggered cascade across a full-width strip and hold; the
signature cascade runs left-to-right along the chain.

Scene 1 (0.0–2.6s): crossfade to a full-width strip: a mono header `TASK-214 · linked record`
and the kicker `✱ 06 — LINK USE AND RESULT`. Four link cards cascade in left→right
(**staggered reveal** → `dynamic-content-sequencing`), connectors drawing between them
(`svg-path-draw`): `1 Recommendation → Apex-Standard` · `2 Maya's response → accepted` ·
`3 Model actually used → Apex-Standard` · `4 Eventual task result → ⏳ pending` (amber chip).

Scene 2 (2.6–5.0s): two status lines resolve **in place** (`discrete-text-sequence`): a green
`✓ Provider request completed` appears against link 3 while link 4 stays amber
`⏳ Engineering outcome: pending`. A thin divider labels the two columns `system signal` (blue)
versus `engineering outcome` (amber) so the distinction is textual, not just coloured.

Scene 3 (5.0–7.6s): two evidence-input cards assemble below the chain, each with a provenance
badge on a **staggered reveal**: `Test signal — from repository test run` with a blue
`SEPARATE SOURCE` chip, and `Human result confirmation — confirmed by Maya` with a green
`HUMAN CONFIRMED` chip. An amber caution line reveals beneath them: `Illustrative future evidence
inputs — not proof that the current integration verifies anything automatically.`

Scene 4 (7.6–10.0s): a smaller secondary card slides into the lower-right of the stage
(**comparison** reveal): `TASK-217 · suggested Apex-Standard → actually used Apex-Premium →
result credited to Apex-Premium`, headed by the label **"Credit the result to the model actually
used."** Everything then holds STILL for the read.

narrativeRole: Shows what a linked record actually contains, and where a result is allowed to come from — never from the suggestion.
keyMessage: Credit every outcome to the model that was really used, keep system signals apart from engineering outcomes, and treat both evidence inputs as illustrative.

## Frame 7 — Learn without hiding negatives

- scene: The evidence ledger travels past a pinned senior-feedback card and four retained negative rows, then a versioned proposal clicks into explicit review
- voiceover: ""
- duration: 9s
- transition_in: push-slide LEFT
- poster: 7s
- status: outline
- src: compositions/frames/07-learn-without-hiding-negatives.html
- type: benefit_highlight
- persuasion: Contrast (what is kept) + explicit counter-example
- beat: unease resolving into trust
- blueprint: transcript-scroll-artifact-reveal (Adapt)
- focal: the evidence ledger with the pinned senior-feedback card
- roles: ledger = foreground subject · pinned card = foreground subject · proposal panel + struck list = supporting · dashboard chrome = background
- sfx: tick, soft click

Adapt: keep the signature — a long surface travelled as evidence, then one focal interaction that
pivots into an artefact. The travel is a vertical pan over a pre-laid ledger (`viewport-change`),
and the pivot is the proposal card clicking into its review panel.

Scene 1 (0.0–2.2s): push-slide into the dashboard's `Evidence` view (70/30: rail left, wide
ledger right). Header `Evidence ledger · 42 linked records · 6 work sessions`. A pinned card
sits at the top of the ledger: `Senior feedback — weighted first` with a green chip and the line
`Maya: review-supported for unit tests`. Kicker `✱ 07 — LEARNING`.

Scene 2 (2.2–5.2s): the ledger **travels vertically** (**pan / focus-lock** → `viewport-change`)
revealing four retained rows one at a time, each glyph + label + colour, never colour alone:
`TASK-219 · Arjun — ✗ FAILED` (red) · `TASK-205 · suggestion REJECTED` (amber) · `TASK-211 ·
OVERRIDE — developer chose differently` (blue) · `TASK-208 · result UNKNOWN` (amber). Beneath the
pinned card a rule reads `Retained: failures · rejects · overrides · unknowns`.

Scene 3 (5.2–7.2s): one focal interaction — the cursor clicks the card `Recommendation policy
proposal v1.4` (**cursor click + ripple**); it glides to centre and opens a review panel
(**anchored layout expand** → `anchored-layout-expand`) with rows revealing on a staggered beat:
`Status · PENDING EXPLICIT REVIEW` (amber), `Reviewer · designated senior / admin`, `Activation ·
manual only` and a danger-red lock line `Learning or readiness alone cannot activate policy`.

Scene 4 (7.2–9.0s): a held read. Three struck lines wipe on beneath the panel (a short
left-to-right strike per line, danger red): `silent retraining` · `outcomes invented for unused
models` · `automatic policy activation`. The frame then sits STILL — this is a deliberate held
frame, no drift. Caption: `Prioritize senior feedback. Retain everyone's failures and unknowns.`

narrativeRole: Turns "learning" from a black box into a reviewable, versioned artefact that keeps the negatives in view.
keyMessage: Senior feedback leads, but failures, rejects, overrides and unknowns stay on the record, and a new policy version only ever reaches the system through explicit review.

## Frame 8 — Category-specific readiness

- scene: Three category cards assemble and resolve their status chips, each with coverage, failures, compatibility and gaps — then the no-threshold disclaimer
- voiceover: ""
- duration: 8s
- transition_in: crossfade
- poster: 6s
- status: outline
- src: compositions/frames/08-category-readiness.html
- type: feature_showcase
- persuasion: Comparison of three options + rule of three
- beat: clarity
- blueprint: grid-card-assemble (Reproduce)
- focal: the three category cards and their status chips
- roles: category cards = foreground subject · evidence strips = supporting · disclaimer footer = supporting · ground = background
- sfx: tick

Reproduce: three tiles self-assemble in a staggered cascade and hold; the signature cascade is the
reveal, with each card then cycling its own chip in place.

Scene 1 (0.0–2.0s): crossfade to `Evidence review · by category` (triptych, three equal cards
across the stage): `Unit-test writing`, `Authentication changes`, `Migration work`. They
**self-assemble** with a staggered cascade; each opens with an amber `… assessing` chip. Kicker
`✱ 08 — READINESS`.

Scene 2 (2.0–4.8s): each chip **steps in place** in sequence (**in-place token cycle** →
`discrete-text-sequence`), glyph + label + colour: unit-test → `✓ EVIDENCE-SUPPORTED · eligible
for limited review` (green); authentication → `! INSUFFICIENT EVIDENCE · not eligible` (amber);
migration → `i DEFAULT ONLY · approved fallback` (blue). Under each card a four-row evidence
strip reveals on a staggered beat: `coverage · linked records`, `failures`, `compatibility
notes`, `gaps` — shown as **counts and small bars** (`stat-bars-and-fills`), never as a score.

Scene 3 (4.8–6.6s): the middle card expands a detail line (**layer-reveal**): `no linked
authentication outcomes in scope · compatibility notes missing`; the right card gains
`stays on approved fallback until evidence exists`. Both hold ≥ 1.5s.

Scene 4 (6.6–8.0s): a footer rule and mono disclaimer reveal in the caption band:
**"No universal confidence score. No minimum-success threshold defined."** (amber glyph, textual).
Deliberate held read — the frame sits STILL. Caption: `Readiness applies to evidenced categories—not
every task.`

narrativeRole: Narrows readiness from "the system works" to "this category, with this evidence".
keyMessage: Readiness is per category and evidence-bound; nothing here is a universal score or an approved threshold.

## Frame 9 — Separate human pilot approval

- scene: The pilot approval window holds as hero while nine review rows fill in, then a checkbox, a fresh MFA prompt and an approved state land
- voiceover: ""
- duration: 11s
- transition_in: push-slide LEFT
- poster: 9s
- status: outline
- src: compositions/frames/09-pilot-approval.html
- type: feature_showcase
- persuasion: Numbered enumeration + demonstration of a human gate
- beat: resolve + reassurance
- blueprint: device-surface-showcase (Adapt)
- focal: the pilot approval window
- roles: approval window = foreground subject · cursor + MFA prompt = foreground subject · caption + amber note = supporting · ground = background
- sfx: tick, soft click

Adapt: keep the signature — one window held as hero while its content cycles through a real flow,
cursorless stepwise steps filling in; no camera push, the window simply holds.

Scene 1 (0.0–2.0s): push-slide to the `Pilot approval` window, centred, 72% of the stage. Header
`PILOT APPROVAL · draft A1 · repository northwind/payments-api`, with a left column of nine labels
already set: `Policy version`, `Repository`, `Eligible developers`, `Task categories`, `Model
mappings`, `Task / budget limits`, `Expiry`, `Evidence references`, `Fallback & rollback`. Kicker
`✱ 09 — HUMAN APPROVAL`. Caption: `Approve a limited pilot—not every future task.`

Scene 2 (2.0–6.2s): the nine values fill in sequence on the **staggered reveal**
(`dynamic-content-sequencing`), ~0.45s apart, each landing with a small check glyph:
`RTM policy v1.3` · `northwind/payments-api` · `Maya (senior) · Arjun (junior)` ·
`unit-test writing only` · `Apex-Standard → approved standard` ·
`$4.00 / task · $250 / month · 40 tasks / day` · `2026-11-30` · `42 linked records` ·
`Fallback Apex-Premium · Rollback default-only`. Beside the limits row an amber outlined badge
appears: **`ILLUSTRATIVE PILOT LIMITS`** (labelled, textual).

Scene 3 (6.2–8.6s): the footer becomes a human gate. The cursor ticks a checkbox
`I approve pilot A1 within the scope above` (**cursor click + ripple** + **button press**), then a
fresh-MFA prompt replaces it: masked dots `••••••` **type on** behind a caret
(`discrete-text-sequence` + `context-sensitive-cursor`), and a green chip `✓ MFA verified` settles.
No digits, no token, ever.

Scene 4 (8.6–11.0s): a green status bar lands across the footer: `PILOT A1 — APPROVED · limited
scope · expires 2026-11-30`, and beside it an amber note with a lock glyph:
**"Readiness alone cannot authorize routing."** The approval control greys to
`Approved — recorded by Sam Ortiz`. Deliberate held read: the frame sits STILL.

narrativeRole: Separates readiness from authorisation — a named human, an exact scope, and a fresh second factor are what turn readiness into a pilot.
keyMessage: Only an explicit, scoped, MFA-confirmed human approval can start routing, and it never generalises to every future task.

## Frame 10 — Scoped automatic selection

- scene: Arjun's new task runs a five-row pre-flight that checks off, a pilot selection card lands with override controls, then Maya's identical flow and an auth task on fallback
- voiceover: ""
- duration: 10s
- transition_in: crossfade
- poster: 8s
- status: outline
- src: compositions/frames/10-scoped-selection.html
- type: feature_showcase
- persuasion: Signposting (identity → approval → scope → compatibility → budget) + demonstration
- beat: momentum + control
- blueprint: agent-progress-theater (Reproduce)
- focal: the pre-flight checklist and the pilot selection card
- roles: terminal = foreground subject · pre-flight card = foreground subject · second + third panes = supporting · ground = background
- sfx: tick, soft click

Reproduce: one trigger beat hands the frame to working-state theatre — rows arrive and check off,
then the receipt lands. The signature is the checking-off cascade, kept intact.

Scene 1 (0.0–2.4s): crossfade to Arjun's terminal. The cursor clicks `+ New task`
(**cursor click + ripple**); the composer types on (**type-on with caret** →
`discrete-text-sequence`): `fix flaky retry test`; a mono chip `eligible category · unit tests`
attaches. Kicker `✱ 10 — SCOPED SELECTION`. Caption: `After approval, selection can serve juniors
and seniors within scope.`

Scene 2 (2.4–5.4s): a `PRE-FLIGHT` card opens over the composer's right and its five rows arrive
and **check off** in order (`agent-progress-theater` cascade), each glyph + label:
`Identity — Arjun ✓`, `Current approval — Pilot A1 ✓`, `Scope — unit-test category ✓`,
`Compatibility — supported ✓`, `Budget reservation — $0.40 reserved ✓`. Blue header chip
`5 / 5 COMPLETE`.

Scene 3 (5.4–7.6s): the receipt lands below the checklist on a **spring-pop entrance**
(`spring-pop-entrance`, smooth settle): `PILOT SELECTION — new task only` (green chip `APPROVED
PILOT`), `Proposed · Apex-Standard — approved standard`, and two controls `[Override]`
`[View reason]`. The cursor clicks `[View reason]` and a popover reveals the reason text:
`category evidence · within Pilot A1 scope · fallback Apex-Premium`. A blue note under the
buttons: `Override always available to the developer.`

Scene 4 (7.6–10.0s): two smaller panes assemble to the right (3-up, equal weight): Maya's
terminal running the **same five checks** and the same `PILOT SELECTION — new task only` card;
and an `authentication changes` task whose chip reads `FALLBACK · Apex-Premium — default only`
(blue, lock glyph). A mono rule reveals beneath: `Active tasks are never re-selected.` The frame
holds STILL.

narrativeRole: Shows approved automatic selection as a gated, bounded, overridable act on a brand-new task — identical for a senior and a junior.
keyMessage: After approval, selection can serve juniors and seniors inside scope — never an active task, never outside it.

## Frame 11 — Budgets, tools, routine feedback

- scene: A read/edit/test run streams through reviewed local tools, per-request reservations settle against the task allowance, and two status cards land
- voiceover: ""
- duration: 9s
- transition_in: crossfade
- poster: 7s
- status: outline
- src: compositions/frames/11-budgets-tools-feedback.html
- type: benefit_highlight
- persuasion: Worked example with real (fictional) values + contrast of two states
- beat: comprehension + confidence
- blueprint: prompt-type-submit-generate (Adapt)
- focal: the budget strip and its per-request reservations
- roles: terminal tool stream = foreground subject · budget strip = foreground subject · status cards = supporting · ground = background
- sfx: tick

Adapt: keep the signature — a typed trigger hands over to a machine that answers with visible
working state and a receipt; here the "answer" is the tool log plus the settlement card.

Scene 1 (0.0–2.4s): crossfade to Arjun's terminal (`TASK-231`). The tool-activity area streams
three reviewed-tool rows one at a time (**staggered reveal** → `dynamic-content-sequencing`),
each glyph + mono verb + target: `read · local · test/retry.spec.ts`, `edit · local · 1 file +14
−3`, `test · local · 12 passed` (green tick). Kicker `✱ 11 — BUDGET & FEEDBACK`.

Scene 2 (2.4–5.0s): above the composer a **budget strip** reveals: `Task allowance · $4.00`
(1px rule, labelled bar) and three reservations arrive as separate pills on their own beats, each
with a green settle tick: `request 1 · $0.18 → settled`, `continuation 2 · $0.14 → settled`,
`continuation 3 · $0.10 → reserved`. A rule label **"Retries and continuations share the task
budget."** reveals beneath the strip. **bars / progress fill**
(`stat-bars-and-fills`) fills the consumed portion, blue, labelled `consumed $0.42 of $4.00`.

Scene 3 (5.0–7.0s): the settlement card lands centre-stage: `TASK-231 — settled $0.42 of $4.00`,
`3 reservations · 1 task`, plus a mono line `fictional accounting · illustrative only`. Beside it
two status cards arrive (**comparison** reveal, equal weight): `Pilot · ACTIVE` (green, glyph) and
`Incoming learning · PENDING EXPLICIT REVIEW` (amber, glyph).

Scene 4 (7.0–9.0s): two final chips resolve in place (**in-place token cycle** →
`discrete-text-sequence`): `Actual-model report · Apex-Standard — matches suggestion` (blue) and
`Human result · tests pass — confirmed by Maya` (green). An amber footnote reveals: `A human
report is not independently verified success.` Caption: `Routine feedback updates the evidence—not
the approved policy.` The frame holds STILL.

narrativeRole: Grounds the economics and the feedback loop in one concrete, fictional task so the accounting and the limits are legible.
keyMessage: Money is reserved per request inside one task allowance, and routine feedback updates evidence — never the approved policy.

## Frame 12 — Failures, corrections, and rollback

- scene: A failed overrun opens the frame, the monitor stops new admission, a correction appends rather than overwrites, and the reviewer chooses default-only rollback
- voiceover: ""
- duration: 11s
- transition_in: crossfade
- poster: 9s
- status: outline
- src: compositions/frames/12-failures-and-rollback.html
- type: pain_point
- persuasion: Counterexample (here is when it breaks) + contrast before/after
- beat: tension resolving into control
- blueprint: compose

Compose: three beats on one locked stage — failure and stop, then the correction ledger, then the
human rollback decision. Reveals spread across the full 11s; the retained-state ledger is the
final hold.

- focal: the failure band and the correction ledger
- roles: failure band = foreground subject · correction ledger = foreground subject · reviewer panel + retained ledger = supporting · terminal = background
- sfx: low impact, tick

Scene 1 (0.0–3.2s): crossfade to a danger-red band across the top of the stage:
**`TASK-234 — FAILED · budget overrun`** with a `✗` glyph; beneath it the terminal's failing tool
row `test · local · 1 failed — connection refused` (red) and a mono line `allowance $4.00 ·
consumed $4.12 · OVERRUN`. A monitoring card slides in on the right (**layer-reveal**): `Monitor ·
signal retained ✓` (blue), `Unsafe new admission · STOPPED` (red, lock glyph), `Operator notified
· external on-call` (blue chip `PLANNED`). Kicker `✱ 12 — FAILURE & ROLLBACK`.

Scene 2 (3.2–6.4s): a correction ledger opens centre-stage; its rows reveal in order, each glyph +
label: `Original settlement · $0.61` with a blue `RETAINED` tag · `Correction appended · −$0.14`
with an amber `APPENDED` tag · `Current totals updated · $0.47` · `Pilot · PAUSED` (amber) ·
`Failure history · retained` (blue). A rule label draws in beside them (`svg-path-draw`):
`corrections append — nothing is overwritten`.

Scene 3 (6.4–8.8s): a reviewer panel enters on the right (40%): `Rollback scope · new tasks
only`, `Reviewer · Sam Ortiz — designated senior / admin`, and two controls `[Rollback to
default-only]` `[Keep pilot]`. The cursor clicks **`[Rollback to default-only]`** (**cursor click
+ ripple** + **button press**), and the panel confirms in place: `✓ Confirmed — default-only
rollback for new tasks`, green chip.

Scene 4 (8.8–11.0s): a retained-state ledger reveals as four rows with check glyphs:
`History retained`, `Costs retained`, `Outstanding obligations retained`, `Consumed task slots
retained`. Above them an info-blue lock line: **`Running TASK-232 is NOT switched.`** The pilot
chip stays amber `PAUSED`. Caption: `A lower bill does not erase a failure or restart a pilot.`
Deliberate held read — the frame sits STILL.

narrativeRole: Shows the safety machinery doing its job — a failure is kept, contained and rolled back by a human, without rewriting history.
keyMessage: A cheaper bill changes neither the failure nor the paused pilot; corrections append, and only a person chooses rollback.

## Frame 13 — The whole journey

- scene: Nine numbered nodes cascade into one connected chain, dim to let the three-clause headline land, then the closing note
- voiceover: ""
- duration: 11s
- transition_in: crossfade
- poster: 9s
- status: outline
- src: compositions/frames/13-joined-up-chain.html
- type: branding
- persuasion: Distillation (compress to one line) + callback to every prior frame
- beat: clarity and resolve
- blueprint: grid-card-assemble (Adapt)
- focal: the nine-node workflow chain
- roles: chain = foreground subject · headline = foreground subject · closing note + kicker = supporting · ground = background
- sfx: tick

Adapt: keep the signature cascade, run it as three rows of three, then let the chain recede so the
headline takes the frame — the cascade is the spine, the dim is the payoff.

Scene 1 (0.0–3.4s): crossfade to the clean cream ground with its faint hairline grid. Kicker
`✱ 13 — THE WORKFLOW`. Row one of the chain **cascades** in left→right with connectors drawing
between them (`svg-path-draw`): `1 Company setup` · `2 Observe` · `3 Manual recommendations` ·
`4 Linked feedback & outcomes`. Numbered mono index + Inter label + a small status glyph on each
node.

Scene 2 (3.4–6.6s): rows two and three assemble on the same cascade: `5 Reviewed learning` ·
`6 Category evidence` · `7 Separate pilot approval` (amber tag `human gate`), then `8 Scoped
selection` · `9 Monitoring & rollback` (amber tag `rollback`). The full chain is complete and
readable by 6.6s; every connector is drawn; the frame then holds for a full beat.

Scene 3 (6.6–9.2s): the chain dims and softens (**depth-of-field / selective-blur** →
`depth-of-field-blur`, chain to ~40%), and the headline enters **per-word staggered reveal**
(`dynamic-content-sequencing`) centred beneath it, three clauses each landing on its own beat:
**"Recommend with evidence."** → **"Route with permission."** → **"Preserve developer control."**
EB Garamond display, sentence case, negative tracking, ≤ 78cqw measure.

Scene 4 (9.2–11.0s): the closing note reveals in two short Inter lines beneath the headline:
`Concept simulation of the intended workflow. Real use requires approved evidence, supported
integrations, company credentials, and deployment validation.` Everything then holds STILL to the
last frame — no exit, no drift.

narrativeRole: Compresses the whole causal chain into one legible object and lands the three-clause thesis over it.
keyMessage: Evidence, permission and developer control are one continuous workflow, and this remains a concept simulation until real deployment validates it.
