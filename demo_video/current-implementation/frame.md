# frame.md — design spec for `current-implementation`

Design source: none supplied by the user (confirmed "None — everything reconstructed").
This file is the project's brand truth. Everything below is invented for this
demonstration; it is not a reproduction of any real product's design system.

## Concept angle

A progressive-disclosure audit walkthrough: each scene adds exactly one more link to an
evidence chain, and the chain visibly, deliberately stops at an amber gate.

## Palette (one background, one foreground, one accent)

| Token         | Value     | Use                                                        |
| ------------- | --------- | ---------------------------------------------------------- |
| Stage bg      | `#0A0D13` | The desktop stage behind every window (same in all scenes) |
| Stage fg      | `#E8EDF4` | Text on the stage                                          |
| Accent        | `#F0A93B` | Amber — the gate, active state, focus, the word PAUSED      |
| App surface   | `#F6F7F9` | Tarkado browser window background                           |
| App card      | `#FFFFFF` | Cards inside the Tarkado window                             |
| App ink       | `#141922` | Text inside the Tarkado window                              |
| App line      | `#DCE1E9` | Borders, dividers inside the Tarkado window                 |
| Term surface  | `#0D1117` | OpenCode terminal window background                         |
| Term ink      | `#C9D1D9` | Text inside the terminal                                    |

Semantic badge colors (used **only** on status badges and counts — never decoratively):

| Meaning        | Value     |
| -------------- | --------- |
| implemented    | `#2F9E6E` |
| failed/reject  | `#D2564B` |
| pending/unknown| `#8A93A2` |
| paused/gate    | `#F0A93B` |

Amber is the single accent. Green/red/grey appear only where a status genuinely is
positive/negative/unknown — a status color is data, not decoration.

## Type

- **Montserrat** (400 / 700 / 900) — statements: scene titles, captions, UI body.
- **IBM Plex Mono** (400 / 700) — the machine's voice: model identifiers, metadata
  chips, counts, terminal content, record ids.

Why these disagree: the video is about the gap between *what a machine records* and
*what a human verifies*. Montserrat states; Plex Mono records. Sans + mono crosses the
pairing boundary as required; neither is on the banned list and both are bundled (no
network fetch at render).

Tracking: `-0.03em` on display sizes. On the dark stage, body weight drops to 400 with
`line-height +0.06`. Counts use `font-variant-numeric: tabular-nums`.

## Frame construction

- **Focal element** — one application window per scene (Tarkado browser or OpenCode
  terminal), 1560px wide, anchored left-of-centre with a stage gutter.
- **Edge anchors** — top-left: scene marker `01 · Company setup`; top-right: `Reconstructed
  interface — not a screenshot`; bottom-left: the persistent honesty label; bottom-right:
  the scene progress rail.
- **Supporting detail** — monospace metadata chips, 2px hairline rules, status badges,
  SVG linked-record connectors that draw themselves.
- **Background treatment** — stage `#0A0D13`, a faint 48px grid at 4% opacity, and ONE
  localized radial glow behind the window (max 0.22 opacity). No full-screen linear
  gradient — it bands under H.264.

## Scale (video, not web)

Headlines 64–84px · scene captions 34–40px · body 26–30px · data labels 20–22px ·
decorative opacity 12–25% · borders 2–3px · padding 48–96px. Nothing below 20px.

## Motion doctrine for this piece

`power3` long-tail settles, never bounce. Sequential reveal across each scene's back 50%
— nothing is dumped in the first quarter. Scene seams use **cut-the-curve** (leftward,
mirrored `power4.in` / `power4.out`, partial travel + fade, no full off-screen exits) so
the whole piece reads as one continuous move. No breathing loops, no back-half camera
pushes, no `repeat`/`yoyo`. Scene 7 settles and then holds **perfectly still** — the
stillness is the point of the gate.
