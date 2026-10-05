---
workflow: general-video
flow: companion
storyboard: no
mode: collaborative
message: "Implemented and controlled — and deliberately paused before real readiness"
duration: 100
canvas: 1920x1080
---

# STORYBOARD — current-implementation

Architecture: **monolithic** `index.html` (one paused timeline, one shared stage, one
persistent honesty layer). Chosen over sub-compositions because the honesty labels and
the two surface skins must be identical in every frame, and a single file removes the
cross-file mount risks entirely. Each scene is a `<section class="clip">` sibling.

Registry searched (`catalog --query` for the terminal look and the dashboard look).
Closest hits — `code-snippet-dark-*`, `terminal-simulator`, `browser-device-stage`,
`ui-focus-zoom` — ship their own chrome and copy that would fight the mandated honesty
labels, so both surfaces are hand-authored.

## Frame 1 — Company setup: implemented

- `status: outline`
- `src: index.html#scene-1`
- Timing: `0 → 14s`
- Motion: `spring-pop-entrance` (window settle, smooth register) · `waterfall-entry`
  (setup checklist cascade) · `cursor-click-ripple` (invite action) · `svg-path-draw`
  (registry check marks)
- Beat: Light Tarkado browser window settles onto the stage. First-administrator setup →
  individual login → confirmed authenticator MFA → invite Maya → invite Arjun → developer
  roles + separately designated pilot-approver permission → approved model registry with
  `fixture/premium` fallback → explicit repository/metadata scope. Caption:
  "Company-controlled identities, models, and collection scope." Secondary:
  "No existing company SSO required." No passwords, seeds, backup codes, or tokens shown.

## Frame 2 — Explicit task observation: limited implementation

- `status: outline`
- `src: index.html#scene-2`
- Timing: `14 → 28s`
- Motion: cut-the-curve seam (leftward) · `discrete-text-sequence` + `context-sensitive-cursor`
  (task fields type in) · `waterfall-entry` (panel rows) · `svg-path-draw` (metadata-only
  connector)
- Beat: Dark OpenCode-style terminal with Tarkado's reconstructed task panel. Maya starts
  an eligible root task while idle: category `documentation`, declared risk `low`, original
  model `fixture/premium`, approved repository + tool/context requirements. A small
  metadata-only connection to the company service draws in. Explains: "Explicit task starts
  and scoped observation code are implemented." / "Automatic task/subagent discovery is not
  shown or claimed." Second honesty label appears here.

## Frame 3 — Manual shadow suggestion: implemented

- `status: outline`
- `src: index.html#scene-3`
- Timing: `28 → 41s`
- Motion: `spring-pop-entrance` (suggestion card) · `stat-bars-and-fills` (confidence
  fill) · `cursor-click-ripple` + `press-release-spring` (Accept) · `control-target-sync`
  (the separate manual model pick mirrors its readout on the same beat)
- Beat: Current `fixture/premium` → Suggestion `fixture/cheap` → Reason: supported
  policy/category evidence → Confidence: limited, explanatory → Fallback `fixture/premium`.
  Buttons `[Accept for this task] [Reject] [View details]`. Maya accepts →
  "Preference recorded · model choice remains manual." Then a *separate* deliberate manual
  selection action. Caption: "Acceptance is not success, model approval, or pilot
  authorization." Note: "No duplicate alternative-model requests."

## Frame 4 — Linked actual-model and result records: implemented

- `status: outline`
- `src: index.html#scene-4`
- Timing: `41 → 54s`
- Motion: cut-the-curve seam · `svg-path-draw` (the four-node chain links) ·
  `waterfall-entry` (nodes arrive in sequence) · `css-marker-patterns` (the two labels
  get a drawn highlight)
- Beat: Recommendation → Response → Reported actual model → Reported result. A controlled
  fictional task completes. "Request completion" is visually separated from
  "Human-reported engineering outcome." Maya reports `fixture/cheap` with a synthetic
  confirmation reference → "Outcome reported—not independently verified." A second task on
  a different model: "The actual model receives its result—not the unused suggestion."

## Frame 5 — Retain everyone's evidence: implemented

- `status: outline`
- `src: index.html#scene-5`
- Timing: `54 → 67s`
- Motion: `waterfall-entry` (record rows cascade) · `counting-dynamic-scale` (positive /
  negative / pending counts) · `css-marker-patterns` (historical-role note)
- Beat: Maya's documentation examples across separate sessions; Arjun's failed
  test-generation task; a rejection; an override; a task with unknown outcome. Complete
  positive, negative and pending counts shown. Caption: "Senior feedback is prioritized.
  Junior failures and unknowns remain visible." Historical roles stay attached to their
  original actions. No invented results for models never used.

## Frame 6 — Experimental learning and category review: implemented

- `status: outline`
- `src: index.html#scene-6`
- Timing: `67 → 81s`
- Motion: `anchored-layout-expand` (validation plan panel) · `control-target-sync`
  (session/category selectors) · `waterfall-entry` (freeze + version chips) ·
  `stat-bars-and-fills` (three category status rows) · `css-marker-patterns`
  (demonstration-parameters highlight)
- Beat: Guided evidence interface — explicit validation plan, labelled session/category
  selectors, frozen cutoff and version, experimental success/session parameters, review
  before publication of future manual suggestions. Illustrative values only under
  "Demonstration parameters—not production-approved thresholds." Documentation → ready for
  local review; Test generation → blocked, failure/rejection retained; Unsupported work →
  approved fallback. Caption: "Versioned proposals. Explicit review. No silent retraining."
  / "Local category review is not production readiness."

## Frame 7 — Pause at independent readiness

- `status: outline`
- `src: index.html#scene-7`
- Timing: `81 → 93s`
- Motion: cut-the-curve seam · `svg-path-draw` (amber gate bracket draws) ·
  `waterfall-entry` (gate copy, then the greyed next stage) · then **hold completely still**
- Beat: The documentation review carries toward separate live-pilot approval and STOPS.
  Amber gate: "PAUSED HERE" — "Live-authorization mechanics are implemented." /
  "Positive approval requires an independent company readiness assessment." / "Shipped
  verifiers refuse by default." / "Positive tests use controlled evidence—not a real company
  verifier." Next stage greyed: "Separate live pilot approval → actual bounded execution".
  Explain: "Real company evidence, validated criteria, installed-host behaviour, and
  deployment approval are still required." No approval, activation, provider execution, or
  external alert is animated.

## Frame 8 — Final frame

- `status: outline`
- `src: index.html#scene-8`
- Timing: `93 → 100s`
- Motion: `waterfall-entry` (stage chain reveals node by node) · `svg-path-draw` (ticks on
  reached stages only) · `spring-pop-entrance` (the amber PAUSED node, smooth register) ·
  `waterfall-entry` (footer lines)
- Beat: Highlights only stages reached — Company setup → Explicit task observation →
  Manual recommendation → Linked feedback/results → Experimental learning → Category
  review → **PAUSED: independent real readiness**. Footer: "Recorded verification: 880
  Python / 47 JavaScript tests passing." / "Regression tests—not proof of production
  readiness, quality, or savings." Plus: "Other conditional pilot/accounting components
  exist, but are intentionally not presented as a completed real-deployment continuation."
