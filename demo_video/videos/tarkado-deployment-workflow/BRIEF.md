---
workflow: faceless-explainer
flow: automation
storyboard: no
message: "Recommend with evidence. Route with permission. Preserve developer control."
destination: browser-embed
aspect: 1920x1080
language: en
audience: professor / engineering reviewers — a visual concept demonstration of the intended Tarkado deployment workflow
length: 125s
angle: how-to-process
---

## Intent

A browser-playable motion-graphics presentation (~110–130s, 16:9, designed at 1920×1080) that
explains how Tarkado is **intended** to work in a real company deployment. It is a visual concept
demonstration for a professor — not the actual Tarkado application, not a production deployment,
and not evidence of achieved savings. It must feel like a carefully designed engineering-product
walkthrough, not a marketing slideshow: a believable illustrative OpenCode-style terminal
reconstruction contrasted against a clean Tarkado browser dashboard, with smooth cursor movement,
restrained typing, panel expansion, highlighted connections and gentle camera reframing.

Voice: precise, calm, engineering-credible. Every claim carries its qualifier on screen.

## Customizations

- Player controls are part of the deliverable: Play/Pause, Replay, a seekable timeline, and scene
  navigation, presented in a wrapper page around the HyperFrames composition.
- A small persistent label must stay on screen for the whole runtime:
  "Planned deployment workflow · illustrative simulation".
- Fully silent piece: `music: none`, no `SCRIPT.md`, no narration, no TTS, no BGM, no SFX.
  On-screen captions carry the message. No paid generation, no external services.
- Illustrative OpenCode-style reconstruction must be labelled as such on the interface itself
  (no claim of pixel-perfect accuracy).
- Status must never rely on colour alone — every state carries an icon and a text label.

## Notes

- Fictional only: all interactions, users, code snippets, evidence, accounting values, model
  names, task ids and policy versions are invented for this demonstration. No backend, no real
  model calls, no secrets on screen (MFA shown as masked input + confirmation state).
- Do not show invented savings percentages, consumer subscriptions, hidden model experiments,
  fabricated production savings, blanket compatibility claims, raw JSON walls, giant tables,
  tiny text, or excessive neon.
- Recommendation-only shadow mode first; acceptance ≠ success; acceptance ≠ pilot approval;
  readiness alone cannot authorize routing; the first limited automatic-routing pilot requires
  explicit designated senior/admin approval with fresh MFA; failures, rejects, overrides and
  unknowns are retained; corrections append rather than overwrite; active tasks are never
  re-selected.
- Work only inside this presentation directory. Tarkado's repository, application, private
  stores and credentials are untouched.
- No Laya and no advanced learning model.
