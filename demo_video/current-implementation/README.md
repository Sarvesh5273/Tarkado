# Tarkado — current implementation walkthrough

A 100-second, 1920×1080, silent motion-graphics walkthrough of the workflow that is
**actually implemented** in Tarkado today. It is built for a progress demonstration to a
professor and stops, on screen, at the first gate the evidence cannot satisfy.

Two things to read before anything else:

- **`player.html` is what you open.** It is the composition plus the playback controls.
- **The video is not a claim that production is live.** The honesty label and the
  Scene 7 stop are part of the deliverable, not decoration.

---

## 1. Opening it

Double-click `player.html`, or serve the folder:

```bash
npx serve .          # or: python3 -m http.server
```

Everything is local — fonts (`assets/fonts/`) and GSAP (`assets/gsap.min.js`) are
vendored, so no network request is made and nothing is loaded from a CDN.

### Controls

| Control | How |
| --- | --- |
| Play / Pause | Button, or `Space` / `K` |
| Replay from the top | Button, or `R` |
| Seek | Drag / click the timeline, or `←` `→` (5s steps) |
| Scene navigation | Eight numbered chips, or keys `1`–`8` |
| Time readout | `0:00 / 1:40` |

The timeline marks each scene boundary with a tick, and the active scene chip stays
highlighted while playing. Review deep-links: `player.html#t=63` starts paused at 63s,
`player.html#play=1` starts playing.

`index.html` is the raw composition (no controls). It plays in a browser too, but it is
the file the render toolchain targets.

---

## 2. The three distinctions

This is the whole point of the piece, so the wording is deliberate.

### Implemented

Machinery that exists in the repository and is covered by the shipped test suites.

- Company setup and owners; members and roles (owner / senior / junior).
- An explicit, bounded task-observation scope (manual task reference — no automatic
  scanning of anyone's sessions).
- A manual "shadow suggestion": a model *recommendation* attached to a task, with the
  person's explicit choice left manual and recorded.
- Linked records: recommendation → response → reported model → reported result, kept as
  separate fields so nothing is inferred downstream.
- Evidence retention for every participant (accepts, rejects, overrides, failures,
  reported outcomes).
- Local experimental learning and a category review pass.
- Verifiers that refuse by default; no silent retraining; no default routing.

**"Implemented" means the code and its regression tests exist. It does not mean the
behaviour has been observed on a real company's evidence.**

### Controlled demonstration

Everything on screen is a **reconstructed** interface built from fictional fixtures:

- Fictional people: Owner (administrator), Maya (senior), Arjun (junior).
- Fictional models: `fixture/premium`, `fixture/standard`, `fixture/cheap`.
- Fictional companies, tasks and dates.

No screenshot of the real product is used, no pixel-perfect claim is made, no backend is
touched, and no credential, token, password or MFA seed appears anywhere. The persistent
label reads:

> **Implemented mechanics · controlled demonstration**

### Pending — deliberately not shown

- **Installed-host validation.** Scenes 2–3 carry the additional label
  *“Connector source implemented · installed-host validation pending”*.
- **Real company evidence** and **validated thresholds.** Every parameter on screen is a
  demonstration value, labelled as such.
- **Any approval or live activation.** The walkthrough stops before pilot execution,
  notifications, streaming, automatic subagents, provider execution and external alerts.
  Nothing after the pause is portrayed as working.

The required gates still outstanding are on screen in Scene 7: real company evidence,
validated criteria, installed-host behaviour, deployment approval.

---

## 3. Scene map

| # | Scene | Start | What it establishes |
| --- | --- | --- | --- |
| 01 | Company setup | 0s | Company record, owners, roles — implemented, no SSO required |
| 02 | Explicit task observation (limited) | 14s | Manual task reference only; connector caveat appears |
| 03 | Manual shadow suggestion | 28s | Model choice stays manual; acceptance ≠ success/approval/pilot |
| 04 | Linked actual-model / result records | 41s | Four linked records, kept distinct; outcome *reported*, not verified |
| 05 | Retain everyone's evidence | 54s | Owners, seniors and juniors all recorded; rejects and failures kept |
| 06 | Experimental learning & category review | 67s | Frozen snapshot, demonstration parameters, no silent retraining |
| 07 | Independent readiness — **PAUSED HERE** | 81s | Shipped verifiers refuse by default; the gate is not satisfied |
| 08 | Final frame | 93s | What is implemented / controlled / pending, in writing |

Scene 7 is intentionally still. There is no motion after the gate is reached.

---

## 4. Verification status

> **Recorded verification: 880 Python / 47 JavaScript tests passing.**
> *Regression tests — not proof of production readiness, quality, or savings.*

Those are the project's own test suites run against the implemented code. They say the
implemented machinery behaves as its tests describe. They say nothing about production
readiness, output quality, or cost savings — and no saving is claimed anywhere in this
video.

This walkthrough itself was validated with the composition checker:

- lint: 0 errors
- runtime: 0 errors
- layout: 0 issues
- motion: 0 errors
- contrast: 157/157 checks pass WCAG AA

---

## 5. Quality rules the piece obeys

- No stage is worded as a validated deployment; the words *implemented*, *controlled*
  and *pending* are kept apart on purpose.
- Acceptance never turns into success, model approval or pilot authorization — stated in
  the caption, not implied by an animation.
- No savings claim, no hidden experiment, no automatic retraining.
- Unknowns and failures stay visible: outcomes are *reported*, verifiers *refuse by
  default*, rejected suggestions are retained rather than discarded.
- Captions and overlay labels are ≥ 28px in the 1920×1080 frame; task cards, selectors,
  badges and linked records are shown as cards, never as raw JSON.
- Silent: no music, no voiceover, no `<audio>` or `<video>` element.

---

## 6. Files

| File | Role |
| --- | --- |
| `player.html` | **Open this.** Composition + playback controls |
| `index.html` | The composition itself — single source of truth (timeline inlined) |
| `build-player.mjs` | Regenerates `player.html` from `index.html` (`node build-player.mjs`) |
| `BRIEF.md` | The approved brief this was built against |
| `frame.md` | Design truth: palette, type, motion doctrine |
| `STORYBOARD.md` | Scene-by-scene breakdown and timing |
| `assets/` | Vendored GSAP + self-hosted woff2 fonts (no network at runtime) |
| `snapshots/` | Verification frames used during review |

After editing `index.html`, re-run:

```bash
npx hyperframes check   # lint + runtime + layout + motion + contrast
node build-player.mjs   # rebuild player.html
```

An MP4 can be produced with `npm run render` (local mode: bundled Chromium + the FFmpeg
at `/opt/homebrew/bin/ffmpeg`). It is optional — the deliverable is the browser player.

---

## 7. Scope note

This work lives entirely outside Tarkado's application directory. No project source, test
harness, private store or credential was touched; nothing here is a screenshot of the
running product; and no pixel-perfect equivalence is claimed.
