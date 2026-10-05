# Tarkado — planned deployment workflow

A silent, captioned 16:9 (1920×1080) motion-graphics presentation, ~119 s / 13 frames,
that explains **how Tarkado is intended to work in a company deployment**.
It is a visual concept demonstration: not the real app, not a real deployment,
and not evidence of savings.

## Open and play

The composition and the player both need an HTTP origin (browsers block script
loading from `file://`). From this folder:

```bash
python3 -m http.server 8080
# or: npx serve .
```

then open **http://localhost:8080/presentation.html**

Controls in `presentation.html`:

| Control | What it does |
| --- | --- |
| **Play / Pause** | toggles playback |
| **Replay** | jumps to 0:00 and plays |
| **Seek bar** | click or drag to scrub anywhere in the 119 s timeline |
| **Frame 01–13 buttons** | jump to that frame and start playing |
| **Space** | play / pause |
| **← / →** | seek ∓ 5 s |
| **Home** | back to the start |
| **1–9** | jump to frame 1–9 |

`index.html` on its own is the raw HyperFrames composition (root `data-duration="119"`,
one paused GSAP timeline registered at `window.__timelines["main"]`).

## Files

| Path | Purpose |
| --- | --- |
| `index.html` | the composition: 13 timed scenes + the single seek-safe timeline |
| `presentation.html` | browser wrapper: player, transport, scene navigation |
| `STORYBOARD.md` | the 13-frame plan this was built from |
| `frame.md` | design tokens, shared surfaces, status-colour rules |
| `BRIEF.md` | locked brief |
| `vendor/` | locally vendored GSAP 3.14.2, HyperFrames runtime and player — **no CDN calls** |
| `assets/fonts/` | Inter, EB Garamond, JetBrains Mono (OFL) + licences |
| `snapshots/` | PNG contact sheets from `hyperframes snapshot` |

**Fully offline.** No font, script, or media request leaves the machine. There is no
narration, no music and no network/backend of any kind: the piece is silent and the
on-screen captions carry the message.

## What is illustrative (fiction, by design)

Everything on screen is invented:

- **Company, people, repo** — Northwind Labs; `northwind/payments-api`;
  branch `feat/idempotency-key`; Maya (senior), Arjun (junior), Sam Ortiz
  (owner/admin/reviewer).
- **Models** — Apex-Premium and Apex-Standard are placeholders for company-approved
  models. No real vendor is named or implied.
- **Numbers** — TASK-2xx IDs, 42 linked records · 6 sessions, $4.00/task,
  $250/month, 40 tasks/day, approval A1 expiring 2026-11-30, policy v1.3 → v1.4.
  All fictional.
- **Interface** — the terminal is an *illustrative OpenCode-style reconstruction*,
  labelled as such in its own window chrome. It is not a screenshot of OpenCode and
  not the real Tarkado product.
- **Transport** — OpenCode → existing LiteLLM proxy → company-managed model API is a
  diagram of the intended shape, not a running system.

## Safety claims the film makes (and deliberately does not make)

It **does** state: shadow mode first; no duplicate alternative-model request;
acceptance ≠ success ≠ pilot approval; credit follows the model actually used;
negatives, overrides and stops are retained; no silent retraining; readiness ≠
authorization; fresh MFA approval; no switching of active tasks; corrections append;
rollback retains history.

It **never** claims: a savings percentage, consumer subscriptions, blanket
compatibility, a universal confidence score, a minimum-success threshold, or any
production result. Public benchmark data is never used as evidence.

Status colours are always paired with an icon and a label — colour alone never
carries meaning.

## Rebuild / validate

```bash
npx hyperframes check          # lint + runtime + layout + motion + contrast
npx hyperframes snapshot --at 5,13.5,22,30,39,48.5,57.5,65.5,74.5,84.5,93.5,103,113.5 --no-end
```
