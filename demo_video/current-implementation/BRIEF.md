---
workflow: general-video
flow: companion
storyboard: no
message: "Implemented and controlled — and deliberately paused before real readiness"
destination: website
aspect: 1920x1080
language: en
length: 100s
audience: professor (progress demonstration)
angle: how-to
narration: no
---

## Intent

A progress demonstration for a professor: a ~90–110 second landscape walkthrough of
Tarkado's **implemented** workflow mechanics, using fictional users and controlled
evidence only. Tone is restrained, technical, and scrupulously honest — it must read as
"here is what is built and where it stops," never as a product launch or a production
claim. The user explicitly asked for startup-launch-grade *production polish*, not a
promotional register.

## Customizations

- **Persistent honesty label** on every frame: `Implemented mechanics · controlled demonstration`
- **Second label on OpenCode scenes (2 and 3):** `Connector source implemented · installed-host validation pending`
- **Playback shell:** Play/Pause, Replay, scene navigation (7 scenes), seekable timeline.
- **Deterministic, seek-safe** timing; browser-playable HTML/CSS/SVG + JavaScript animation.
- Scene 7 must **stop visibly at the amber `PAUSED HERE` gate**. Nothing after it may show
  approval granted, live activation, provider execution, notifications, streaming,
  automatic subagents, or external alerts.
- Final frame highlights only the stages actually reached, plus the test-count footer and
  the conditional-components note.

## Assets

- None. All interface visuals are reconstructed in HTML/CSS/SVG; no screenshots supplied
  and no pixel-perfect reproduction is claimed.

## Notes

- **Fictional users:** Owner (company administrator), Maya (senior developer), Arjun
  (junior developer).
- **Fictional models:** `fixture/premium`, `fixture/standard`, `fixture/cheap` —
  demonstration identifiers only, not real production recommendations.
- Seven scenes: 1 Company setup · 2 Explicit task observation · 3 Manual shadow
  suggestion · 4 Linked actual-model and result records · 5 Retain everyone's evidence ·
  6 Experimental learning and category review · 7 Pause at independent readiness.
- Do not display passwords, MFA seeds, backup codes, or tokens anywhere.
- Do not transmit or depict prompt bodies, source files, outputs, or credentials.
- Never claim: automatic task/subagent discovery, duplicate alternative-model requests,
  automatic success from acceptance, automatic retraining, savings, or production
  readiness. Keep unknowns, failures, rejections, overrides, and manual-choice behaviour
  visible.
- Illustrative thresholds in Scene 6 must carry
  `Demonstration parameters—not production-approved thresholds.`
- Footer: `Recorded verification: 880 Python / 47 JavaScript tests passing.` and
  `Regression tests—not proof of production readiness, quality, or savings.`
- Silent piece. Work only inside this project directory; do not modify Tarkado application
  code or private stores.
