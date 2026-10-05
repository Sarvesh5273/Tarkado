#!/usr/bin/env node
/**
 * Build player.html from index.html.
 *
 * index.html stays a pure composition (what the harness renders).
 * player.html is that same composition plus a fixed 1920x1080 stage that
 * scales to the window and a control bar: play/pause, replay, seek, and
 * one button per scene.
 *
 *   node build-player.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "index.html"), "utf8");

/* Scene starts, in seconds — mirrors SCENES inside index.html. */
const SCENES = [
  { n: "01", label: "Company setup", start: 0 },
  { n: "02", label: "Task observation", start: 14 },
  { n: "03", label: "Shadow suggestion", start: 28 },
  { n: "04", label: "Linked records", start: 41 },
  { n: "05", label: "Evidence retained", start: 54 },
  { n: "06", label: "Category review", start: 67 },
  { n: "07", label: "PAUSED HERE", start: 81 },
  { n: "08", label: "Final frame", start: 93 },
];

const STYLE = `
      /* ============ player chrome (not part of the composition) ============ */
      html.hf-player,
      body.hf-player {
        height: 100%;
        overflow: hidden;
        background: #05070b;
      }
      body.hf-player {
        position: relative;
      }
      #root {
        position: absolute;
        top: 0;
        left: 0;
        transform-origin: 0 0;
      }
      .hf-bar {
        position: fixed;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 999;
        padding: 10px 18px 12px;
        background: rgba(5, 7, 11, 0.96);
        border-top: 1px solid rgba(232, 237, 244, 0.14);
        font-family: Montserrat, "Helvetica Neue", Arial, sans-serif;
        color: #e8edf4;
        user-select: none;
      }
      .hf-row {
        display: flex;
        align-items: center;
        gap: 14px;
      }
      .hf-btn {
        flex: none;
        font: 700 15px/1 Montserrat, Arial, sans-serif;
        letter-spacing: 0.02em;
        color: #e8edf4;
        background: rgba(232, 237, 244, 0.08);
        border: 1px solid rgba(232, 237, 244, 0.2);
        border-radius: 8px;
        padding: 10px 14px;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 9px;
        transition: background 0.15s ease, border-color 0.15s ease;
      }
      .hf-btn:hover {
        background: rgba(240, 169, 59, 0.16);
        border-color: rgba(240, 169, 59, 0.6);
      }
      .hf-btn:focus-visible,
      .hf-chip:focus-visible,
      .hf-seek:focus-visible {
        outline: 2px solid #f0a93b;
        outline-offset: 2px;
      }
      .hf-btn svg {
        width: 13px;
        height: 13px;
        fill: currentColor;
      }
      .hf-time {
        flex: none;
        font: 400 15px/1 "IBM Plex Mono", monospace;
        color: #98a2b3;
        min-width: 104px;
        text-align: center;
      }
      .hf-seek {
        position: relative;
        flex: 1;
        height: 26px;
        cursor: pointer;
        touch-action: none;
        border-radius: 999px;
      }
      .hf-track,
      .hf-fill,
      .hf-head {
        position: absolute;
        top: 50%;
        transform: translateY(-50%);
        pointer-events: none;
      }
      .hf-track {
        left: 0;
        right: 0;
        height: 8px;
        background: rgba(232, 237, 244, 0.14);
        border-radius: 999px;
      }
      .hf-fill {
        left: 0;
        width: 0;
        height: 8px;
        background: #f0a93b;
        border-radius: 999px;
      }
      .hf-head {
        left: 0;
        width: 3px;
        height: 18px;
        background: #fff;
        border-radius: 2px;
        margin-left: -1.5px;
      }
      .hf-tick {
        position: absolute;
        top: 50%;
        width: 1px;
        height: 16px;
        margin-top: -8px;
        background: rgba(5, 7, 11, 0.85);
        border-left: 1px solid rgba(232, 237, 244, 0.5);
        pointer-events: none;
      }
      .hf-scenes {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        margin-top: 10px;
      }
      .hf-chip {
        font: 700 13px/1 Montserrat, Arial, sans-serif;
        letter-spacing: 0.03em;
        color: #98a2b3;
        background: transparent;
        border: 1px solid rgba(232, 237, 244, 0.18);
        border-radius: 999px;
        padding: 7px 12px;
        cursor: pointer;
        transition: color 0.15s ease, border-color 0.15s ease,
          background 0.15s ease;
      }
      .hf-chip b {
        color: #f0a93b;
        margin-right: 6px;
      }
      .hf-chip:hover {
        color: #e8edf4;
        border-color: rgba(240, 169, 59, 0.6);
      }
      .hf-chip[aria-current="true"] {
        color: #0a0d13;
        background: #f0a93b;
        border-color: #f0a93b;
      }
      .hf-chip[aria-current="true"] b {
        color: #0a0d13;
      }
      .hf-hint {
        margin-left: auto;
        font: 400 13px/1.5 "IBM Plex Mono", monospace;
        color: rgba(152, 162, 179, 0.8);
        white-space: nowrap;
      }
      .hf-error {
        position: fixed;
        inset: 0;
        z-index: 1000;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 40px;
        text-align: center;
        font: 700 20px/1.6 Montserrat, Arial, sans-serif;
        color: #e8edf4;
        background: #05070b;
      }
      @media (max-width: 1100px) {
        .hf-hint {
          display: none;
        }
      }
`;

const SCRIPT = `
      (function () {
        var tl = window.__timelines && window.__timelines["main"];
        if (!tl) {
          var err = document.createElement("div");
          err.className = "hf-error";
          err.textContent =
            "The composition timeline did not load. Keep player.html beside index.html and assets/.";
          document.body.appendChild(err);
          return;
        }

        var SCENES = ${JSON.stringify(SCENES)};
        var DURATION = tl.duration();
        var bar = document.getElementById("hf-bar");
        var playBtn = document.getElementById("hf-play");
        var playLabel = playBtn.querySelector("[data-label]");
        var playIcon = playBtn.querySelector("[data-icon]");
        var replayBtn = document.getElementById("hf-replay");
        var timeEl = document.getElementById("hf-time");
        var seek = document.getElementById("hf-seek");
        var fill = document.getElementById("hf-fill");
        var head = document.getElementById("hf-head");
        var scenesEl = document.getElementById("hf-scenes");

        /* ---------- keep the 1920x1080 stage fitted above the control bar ---------- */
        function fit() {
          var w = window.innerWidth;
          var h = window.innerHeight - bar.offsetHeight;
          var k = Math.min(w / 1920, h / 1080);
          var dx = (w - 1920 * k) / 2;
          var dy = (h - 1080 * k) / 2;
          document.getElementById("root").style.transform =
            "translate(" + dx + "px," + dy + "px) scale(" + k + ")";
        }

        /* ---------- readout ---------- */
        function clock(sec) {
          var s = Math.max(0, Math.floor(sec));
          return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
        }

        function activeScene(t) {
          var idx = 0;
          for (var i = 0; i < SCENES.length; i++) {
            if (t >= SCENES[i].start - 0.001) idx = i;
          }
          return idx;
        }

        var chips = SCENES.map(function (sc) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "hf-chip";
          b.innerHTML = "<b>" + sc.n + "</b>" + sc.label;
          b.title = "Jump to " + sc.label + " (" + sc.start + "s)";
          b.addEventListener("click", function () {
            goto(sc.start);
          });
          scenesEl.insertBefore(b, scenesEl.querySelector(".hf-hint"));
          return b;
        });

        /* scene-boundary ticks on the seek bar */
        SCENES.forEach(function (sc) {
          if (!sc.start) return;
          var t = document.createElement("i");
          t.className = "hf-tick";
          t.style.left = ((sc.start / DURATION) * 100).toFixed(3) + "%";
          seek.appendChild(t);
        });

        function goto(sec) {
          var wasPlaying = !tl.paused();
          tl.time(sec);
          if (wasPlaying) tl.play();
          sync();
        }

        function sync() {
          var t = tl.time();
          var p = DURATION ? t / DURATION : 0;
          fill.style.width = (p * 100).toFixed(3) + "%";
          head.style.left = (p * 100).toFixed(3) + "%";
          timeEl.textContent = clock(t) + " / " + clock(DURATION);
          seek.setAttribute("aria-valuenow", String(Math.round(p * 100)));
          seek.setAttribute("aria-valuetext", clock(t));
          var playing = !tl.paused() && t < DURATION;
          playLabel.textContent = playing ? "Pause" : "Play";
          playIcon.innerHTML = playing
            ? '<path d="M3 2h4v12H3zM9 2h4v12H9z"/>'
            : '<path d="M4 2l10 6-10 6z"/>';
          playBtn.setAttribute("aria-pressed", playing ? "true" : "false");
          var active = activeScene(t);
          chips.forEach(function (c, i) {
            c.setAttribute("aria-current", i === active ? "true" : "false");
          });
        }

        /* ---------- play / pause / replay ---------- */
        function toggle() {
          if (tl.progress() >= 1) tl.time(0);
          if (tl.paused()) tl.play();
          else tl.pause();
          sync();
        }
        playBtn.addEventListener("click", toggle);
        replayBtn.addEventListener("click", function () {
          tl.time(0);
          tl.play();
          sync();
        });

        /* ---------- seek: click + drag ---------- */
        function seekTo(clientX) {
          var r = seek.getBoundingClientRect();
          var p = r.width ? (clientX - r.left) / r.width : 0;
          p = Math.min(1, Math.max(0, p));
          tl.time(p * DURATION);
          sync();
        }
        var dragging = false;
        seek.addEventListener("pointerdown", function (e) {
          dragging = true;
          seek.setPointerCapture(e.pointerId);
          seekTo(e.clientX);
        });
        seek.addEventListener("pointermove", function (e) {
          if (dragging) seekTo(e.clientX);
        });
        seek.addEventListener("pointerup", function (e) {
          dragging = false;
          try {
            seek.releasePointerCapture(e.pointerId);
          } catch (err) {}
        });
        seek.addEventListener("pointercancel", function () {
          dragging = false;
        });
        seek.addEventListener("keydown", function (e) {
          if (e.key === "ArrowRight") {
            e.preventDefault();
            goto(Math.min(DURATION, tl.time() + 5));
          } else if (e.key === "ArrowLeft") {
            e.preventDefault();
            goto(Math.max(0, tl.time() - 5));
          }
        });

        /* ---------- keyboard ---------- */
        document.addEventListener("keydown", function (e) {
          if (e.metaKey || e.ctrlKey || e.altKey) return;
          if (e.key === " " || e.key === "k") {
            e.preventDefault();
            toggle();
          } else if (e.key === "ArrowRight") {
            e.preventDefault();
            goto(Math.min(DURATION, tl.time() + 5));
          } else if (e.key === "ArrowLeft") {
            e.preventDefault();
            goto(Math.max(0, tl.time() - 5));
          } else if (e.key === "r" || e.key === "R") {
            e.preventDefault();
            tl.time(0);
            tl.play();
            sync();
          } else if (/^[1-8]$/.test(e.key)) {
            e.preventDefault();
            goto(SCENES[Number(e.key) - 1].start);
          }
        });

        /* ---------- timeline callbacks + layout ---------- */
        tl.eventCallback("onUpdate", sync);
        tl.eventCallback("onPlay", sync);
        tl.eventCallback("onPause", sync);
        tl.eventCallback("onComplete", sync);

        window.addEventListener("resize", fit);
        if (window.ResizeObserver) new ResizeObserver(fit).observe(bar);

        fit();
        sync();

        /* Deep links for review:
             player.html#t=63      starts paused at 63s
             player.html#play=1    starts playing immediately          */
        var m = /t=([0-9.]+)/.exec(window.location.hash || "");
        if (m) {
          tl.time(Math.min(DURATION, parseFloat(m[1])));
          sync();
        }
        if (/play=1/.test(window.location.hash || "")) tl.play();
      })();
`;

let html = src;

if (!html.includes('<html lang="en">')) {
  throw new Error("unexpected <html> tag in index.html");
}
// Drop the harness composition id so the project still has exactly one
// root composition (index.html) when both files sit in the same folder.
html = html.replace(/\s+data-composition-[\w-]+="[^"]*"/g, "");
html = html.replace(
  '<html lang="en">',
  '<html lang="en" class="hf-player">',
);
html = html.replace(
  "<title>Tarkado — Implemented workflow (controlled demonstration)</title>",
  "<title>Tarkado — Implemented workflow · player</title>",
);

const styleAnchor = "    </style>";
if (html.split(styleAnchor).length !== 2) {
  throw new Error("expected exactly one </style> in index.html");
}
html = html.replace(styleAnchor, STYLE + styleAnchor);

const bar = `
    <!-- ===================== player chrome (not part of the composition) ===================== -->
    <div class="hf-bar" id="hf-bar">
      <div class="hf-row">
        <button class="hf-btn" id="hf-play" type="button" aria-label="Play or pause">
          <svg viewBox="0 0 16 16" aria-hidden="true" data-icon><path d="M4 2l10 6-10 6z"/></svg>
          <span data-label>Play</span>
        </button>
        <button class="hf-btn" id="hf-replay" type="button" aria-label="Replay from the start">
          Replay
        </button>
        <span class="hf-time" id="hf-time">0:00 / 1:40</span>
        <div class="hf-seek" id="hf-seek" role="slider" tabindex="0"
             aria-label="Seek through the walkthrough"
             aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
          <div class="hf-track"></div>
          <div class="hf-fill" id="hf-fill"></div>
          <div class="hf-head" id="hf-head"></div>
        </div>
      </div>
      <div class="hf-scenes" id="hf-scenes">
        <span class="hf-hint">Space play/pause &middot; &larr;/&rarr; 5s &middot; R replay &middot; 1&ndash;8 scenes</span>
      </div>
    </div>
    <script>
${SCRIPT}
    </script>
`;
if (!html.includes("  </body>")) throw new Error("no </body> in index.html");
html = html.replace("  </body>", bar + "  </body>");

writeFileSync(join(here, "player.html"), html);
console.log("player.html written (" + html.split("\n").length + " lines)");
