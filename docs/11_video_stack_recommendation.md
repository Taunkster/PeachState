# Video Generation Stack — Research & Recommendation

**Author:** Employee A — Senior Motion Designer
**Date:** 2026-08-20
**Status:** For manager review
**Scope:** Complete rethink of the PeachState CoolChain video generation pipeline (matplotlib + ffmpeg → modern motion-design stack)

---

## 1. Executive Summary

Our current pipeline renders each chart as a sequence of matplotlib PNGs at 100 DPI and stitches them with raw ffmpeg. That is why the demo looks like a PowerPoint deck:

- **matplotlib is a plotting library, not a motion-design engine.** It has no camera, no easing curves that feel designed (we had to hand-roll bezier solvers), no per-object staggering, no morphing, no compositing, no text layout worth using, and no GPU.
- **The "heatmap" is a scatter of polygon fills**, not a continuous WebGL density surface — so it reads as random dots.
- **Animation is time-indexed redraws** (a `draw_frame(fig, i)` loop) — every frame re-runs the whole scene, which is why loops feel disorienting and zooms feel random; there is no authored timeline, only frame math.

**Recommendation (TL;DR):** Adopt a **layered stack**:

1. **Remotion (React/TypeScript)** as the primary video authoring/rendering engine — the industry-standard for programmatic, data-driven video (2024–2026). Handles the full 300 s master: title page, scenes, transitions, lower thirds, captions, progress bar, exact timing.
2. **Deck.gl (WebGL)** for all map/geo work — real GPU heatmaps with proper color ramps, camera animation, and large GeoJSON polygon layers (our 45 field polygons and 102 corridor nodes are trivial for it).
3. **Vega-Lite / Observable Plot (headless)** for data charts where the design is "default-perfect" and we want declarative, reviewable chart specs — rendered to frames via headless Chrome.
4. **Manim (Community, Python)** retained as a **specialist tool** for math/abstract animations and the animated title/hero sequences (our `manim_theme.json` is already written for it), rendered to PNG sequences that Remotion ingests.
5. **Figma → SVG** for title-page art direction; animate the SVG inside Remotion (or Manim) rather than drawing titles in code.

`design/design_tokens.json` stays the single source of truth — every tool consumes the same tokens (colors, heat ramp, type scale, easing, durations) either via our existing `chart_theme.py` (Python) or a new `theme.ts` (TypeScript).

Why not a single tool: no one tool wins all four jobs (maps, charts, titles, timeline). The winning pattern in 2025–2026 professional pipelines is **"compose per-scene best tools → render deterministic PNG/ProRes frames → assemble in a timeline engine."** Remotion is that timeline engine.

---

## 2. Current Pipeline Autopsy (what is actually wrong)

| Problem (user feedback) | Root cause in current code | Where |
|---|---|---|
| "Looks like PowerPoint" | matplotlib Agg at 100 DPI; flat figure axes; no depth, glow, blur, mesh gradients (tokens define them but charts can't render them) | `scripts/video_charts/chart_theme.py`, `render.py` |
| "Looping is disorienting" | Time-slider charts re-draw per frame with no authored keyframes; `glow_pulse`/`shimmer` are `loop: true` patterns; pulse math `0.5+0.5*sin(2π t·2)` runs for the entire 5 s click hold | `chart_a_field_heatmap.py:197`, `design_tokens.json` motion.patterns |
| "Random zooms" | ffmpeg `zoompan` in the assembly script applies linear zoom regardless of scene intent | `scripts/assemble_demo_video.py` |
| "Heatmap = random dots" | `HeatmapLayer` does not exist; fields are drawn as flat `Polygon` fills colored by 4 discrete tiers — no continuous heat ramp, no density, no readable axis | `chart_a_field_heatmap.py:_draw_fields` |
| "XY axis barely readable" | Axis styling is matplotlib default-ish even after rcParams; tick labels at 10 px mono on a 1920 canvas | `chart_a_field_heatmap.py` |
| "Title page horrible" | Title drawn with PIL (`final_demo_video.py` / `assemble_demo_video.py` Hook scene) — no typography, no kerning, no easing, no art direction | assembly scripts |
| "Wrong tools" | matplotlib + ffmpeg are neither motion-design tools nor video editors | whole pipeline |

The design system (`design/design_tokens.json`, `component_specs.md`, `scene_storyboards.md`) is already excellent and tool-agnostic — the failure is the **rendering tool**, not the design. We keep the tokens, we replace the renderer.

---

## 3. Tool Landscape Research (2024–2026)

### Category 1: Code-first motion design (Python)

**Manim Community (v0.20.1, Feb 2026; v0.21.0 Aug 2026 — MIT, Python ≥3.9)**
- The 3Blue1Brown engine. Precise mathematical animation, `Transform`, `Create`, `ValueTracker`-driven counters, `MovingCamera`, rate functions (`ease_out_quint`, `ease_in_out_quint`, …).
- Cairo (default) renderer is deterministic and headless-friendly; **OpenGL renderer** is GPU-accelerated, ~10× faster, and becoming primary — needs `xvfb` on headless Linux (we already run headless).
- 4K 60 fps is supported (community tooling reports 4K@60 needs ~8 GB RAM for long scenes).
- **Gaps:** charts are work (no grammar of graphics); geo/maps are manual; typography is good but not Figma-grade; heavy math API is overkill for KPI cards.
- **Verdict:** keep for hero math/counter/abstract sequences and the SVG-animated title. Already have `manim_theme.json`.

**Motion Canvas (TypeScript, MIT, ~18k stars)**
- Generator-based (`yield*`) animation with precise timing control, real-time browser editor, 60 fps export.
- **Gaps vs our needs:** rendering is UI-driven (`npx motion-canvas render` exists but batch/server-side automation is weak); canvas-only (no HTML/DOM so no easy Vega-Lite/D3 interop); audio pipeline basic; **Revideo** (a fork) adds server rendering + variables + templates but is younger.
- **Verdict:** excellent for explainer videos; our pipeline is data-dashboard-driven → lower priority than Remotion.

**Coldtype (Python, Apache-2.0, alpha)**
- Programmatic display typography + animation; real-time window, font-aware layout, exports via ffmpeg/skia.
- **Gaps:** alpha quality ("API subject to change"), small community (342 stars), charts/maps out of scope.
- **Verdict:** niche — could power title typography experiments but Remotion+Figma covers it better.

**MoviePy**
- Higher-level than ffmpeg for editing/assembling clips but is **not** a motion-design engine — no scene graph, no keyframes with easing, no morphing. Fine for glue code; wrong for the look we need.
- **Verdict:** keep only as an assembly utility, not the primary stack.

### Category 2: Data visualization → video

**Observable Plot + headless Chrome**
- Declarative grammar of graphics (Mark Renders at Observable). Concise, defaults are beautiful, designed for dark/data-dense contexts. Vega-Lite alternative with cleaner API.
- Render path: `Plot` → SVG in headless Chrome → screenshot per frame (Puppeteer/CDP) → ffmpeg. Deterministic and CI-safe.
- **Gaps:** animation must be driven externally (re-render per frame with changing data/params); no built-in timeline; maps limited.

**Vega-Lite + headless Chrome**
- Declarative spec (JSON), includes `rect` marks for proper heatmaps, scale ranges can bind to our Viridis ramp, Vega transforms offload to DuckDB via VegaFusion/Mosaic for big data.
- `Animated Vega-Lite` research adds time as an encoding channel — promising but research-grade.
- **Gaps:** no timeline; frame-by-frame re-render; WebGL only via vega-embed canvas.

**Plotly + Kaleido**
- Static export only (Kaleido v3 supports WebGL, 4K). Sequence frames manually. Fine but animation is clunky.
- **Verdict:** weakest of the three for our use.

**Deck.gl (WebGL2/WebGPU, MIT, vis.gl/Uber ecosystem, ~13k stars)**
- GPU rendering of millions of points at 60 fps; `HeatmapLayer` implements **Gaussian kernel density estimation on the GPU** — the correct answer to "random dots".
- Layer catalog: `GeoJsonLayer` (our 45 fields), `ScatterplotLayer`, `ArcLayer`, `LineLayer` (corridors), `ScreenGridLayer`, `HeatmapLayer`; `CameraController`/transition system gives **purposeful camera moves with easing** (flyTo, linear/smooth interpolation).
- Headless: render to an offscreen canvas with `@deck.gl/core` Deck instance, capture WebGL canvas per frame → ffmpeg. Python binding exists (`pydeck`) for dev/static but video path is JS.
- **Verdict:** the map/geo engine. This is the single biggest upgrade for the field-map and corridor scenes.

### Category 3: Professional motion design apps

**After Effects + Bodymovin/Lottie**
- The industry-standard editor. Bodymovin exports AE compositions to Lottie JSON; `lottie-web`/`lottie-player` plays them in a browser; headless capture → video. Designers get AE freedom; engineers get a renderable format.
- **Costs:** AE is paid (~$22.99/mo standalone), Lottie format has feature limits (expressions partially supported), and the Figma→AE→Lottie→video chain is heavier than Figma→SVG→Remotion.
- **Verdict:** valid if we hire a dedicated motion designer; not needed for a hackathon demo team.

**Rive (free; $9–32/mo)**
- State machines + data binding + scripting; ideal for interactive UI animation and product surfaces. Not a broadcast video/compositing tool; `.riv` runtime required.
- **Verdict:** wrong layer for a rendered MP4 demo pipeline.

**Cavalry (free for individuals since Apr 2026)**
- Node-based procedural, **data-driven** 2D animation: import Google Sheets/JSON, duplicate systems, animate 500 data points. Used for election-night / sports / finance graphics. Exports MP4, Lottie.
- **Verdict:** genuinely interesting for automated data-graphics; but it's a GUI tool (not code), and our team is a code-first repo. Keep as a watch item.

### Category 4: Web-based (modern) — the frontier

**Remotion (React, source-available; free for ≤3-person teams, company license from ~$100/mo; ~25k stars)**
- Videos as React components evaluated per frame. Frame-accurate; `interpolate()` with easing presets; `Sequence`/`Series` for scenes; `<Video>/<Audio>/<Img>`; built-in transitions (`@remotion/transitions`); `@remotion/renderer` for programmatic server-side rendering to MP4/WebM/ProRes/image sequences; Lambda rendering; input props = JSON (perfect for our fixtures).
- Anything the web can render it can render: SVG, Canvas, D3, Deck.gl, Lottie, CSS. This is the key advantage — **Deck.gl and Vega-Lite run *inside* Remotion**.
- Deterministic, CI-friendly, hot-reload Studio for iteration.
- **Costs:** license for >3-person for-profits; headless Chrome required (fine — we already run headless); React/TS learning curve for a Python team.
- **Verdict:** the timeline/assembly/compositing engine and the primary authoring surface.

**Motion One, GSAP, Anime.js, Hyperframes/HTML-rec**
- Web animation primitives / HTML-to-video bridges. GSAP is best-in-class for DOM tweening (easing, stagger, scrub); Hyperframes (Apache-2.0) renders plain HTML+CSS+GSAP to MP4 deterministically, is agent-friendly, and free — a credible Remotion alternative if the team wants to avoid React.

---

## 4. Decision Matrix (7 dimensions × 8 candidates)

Scoring: 1 (weak) → 5 (excellent). Scores are for **our** workload (data-driven, map-heavy, 300 s narrated demo, headless Linux CI, Python + small TS tolerance).

| Tool | Learning curve (5 = easy) | Data-driven (JSON fixtures) | Map/geo quality | Animation precision (easing/stagger/morph) | Output quality (4K/60fps/color) | Team skill fit (Python/TS) | Maintenance & iteration speed | **Weighted score** |
|---|---|---|---|---|---|---|---|---|
| **Remotion** (React) | 3 | 5 | 4 (via Deck.gl/D3) | 5 | 5 | 3 | 5 | **4.4** |
| **Deck.gl** (TS) | 3 | 5 | 5 | 4 | 5 | 3 | 4 | **4.1** |
| **Manim CE** (Python) | 3 | 3 | 1 | 4 | 4 | 5 | 3 | **3.3** |
| **Motion Canvas** (TS) | 3 | 3 | 1 | 5 | 4 | 3 | 3 | **3.1** |
| **Observable Plot / Vega-Lite** (JS) | 4 | 4 | 1 | 2 | 4 | 3 | 4 | **3.2** |
| **MoviePy** (Python) | 4 | 3 | 1 | 2 | 3 | 5 | 3 | **3.0** |
| **Rive** (GUI) | 2 | 4 | 0 | 4 | 3 | 1 | 3 | **2.4** |
| **Cavalry** (GUI) | 2 | 4 | 0 | 4 | 4 | 1 | 3 | **2.5** |
| **AE + Lottie** (GUI) | 2 | 3 | 0 | 5 | 5 | 1 | 2 | **2.5** |

*Weighting: data-driven 20%, map/geo 20%, animation precision 20%, output 15%, iteration 15%, skill fit 5%, learning 5%. Rationale: this is a data-dashboard demo; maps + data + polish dominate.*

### Ranking by scenario
- **Fastest to a professional result with a code team:** Remotion (4.4) — everything else slots into it.
- **Best single map fix:** Deck.gl (4.1) — the HeatmapLayer alone fixes "random dots".
- **Best Python-only path:** Manim + MoviePy + matplotlib-with-plotnine (≈3.3) — still leaves the map problem unsolved.
- **Best zero-code designer path:** Cavalry/AE-Lottie — different team profile.

---

## 5. Recommendation (specific + why)

### Primary stack
```
Figma (title art) ──▶ SVG ──┐
fixtures JSON ──────────────┤
Deck.gl (maps) ─────────────┼──▶ Remotion (React, 60 fps) ──▶ MP4/ProRes
Vega-Lite/Observable (charts)┤        ▲
Manim (math/counters, Python)┘        │
                              design_tokens.json (single source of truth)
```

**Why Remotion (not Manim/Motion Canvas/ffmpeg):**
1. **JSON-first:** fixtures are already JSON; Remotion takes `inputProps` = our exact `heat_frames.json`, `corridor.json`, `alerts.json`, `kpis.json`. Every number flows in unmodified — no per-chart copy/paste.
2. **The only engine where Deck.gl and Vega-Lite can live inside the same scene.** Maps and charts share one camera/timeline.
3. **Frame-accurate + deterministic:** `useCurrentFrame()` + `interpolate(frame, [0,30],[0,1], {easing: Easing.out(Easing.cubic)})` gives authored easing; `Sequence` gives authored scene timing; no loops unless we say so.
4. **Pro output:** ProRes/MP4 at 60 fps, exact color via CSS colors + linear color config; Remotion Studio gives hot-reload iteration (the "maintenance speed" win).
5. **License fits:** our team is ≤3 people for the hackathon → free tier. Document the upgrade path if the org grows.

**Why Deck.gl for maps (not matplotlib/Leaflet):**
- `HeatmapLayer` = GPU kernel-density heat with `colorRange` bound to our Viridis-style ramp from `design_tokens.json` (`heat.ramp_smooth_24`), `radiusPixels` for smoothing, `intensity` for punch.
- `GeoJsonLayer` renders our 45 field polygons + `LineLayer`/`PathLayer` for I-75/I-16 corridors.
- Camera transitions (`flyTo`, easing) replace `zoompan`.
- 60 fps at 1080p/4K confirmed at millions of points.

**Why Manim stays (as scene-specialist):**
- `manim_theme.json` already matches tokens 1:1; `DecimalNumber` counters, `Create` route-draw, `MovingCamera` are exactly our hero/alert/corridor beats. Render Manim scenes to PNG sequences; Remotion composites them (a common pattern: engines emit frames, Remotion assembles).

**Why not MoviePy/ffmpeg-only:** keep ffmpeg for final encode (Remotion does this internally), drop manual zoompan and hand-rolled bezier solvers.

---

## 6. Specific Fixes for Our Current Video Problems

### Fix 1 — Heatmap: Deck.gl real WebGL heat with proper ramps
- Replace `chart_a_field_heatmap.py` polygon-fill map with a **Deck.gl `HeatmapLayer`** fed by `dashboard/heat_frames.json` `frames.<hour>` features (each has `tcm_f`; use `getWeight: f => f.properties.tcm_f` or risk_score).
- `colorRange = tokens.heat.ramp_smooth_24` (80–105 °F); `getColorValue` → map `tcm_f` through the ramp via a small `tokens.ts` helper (same math as `chart_theme.heat_color`).
- Overlay `GeoJsonLayer` for field boundaries at low opacity + selected field highlight.
- Add a **real legend**: horizontal gradient bar (24-stop ramp) with °F ticks at 80/85/90/95/100/103/105, using the token `mono` font, inside a `map_container` component — not a 4-tier box.
- Readable axes: since Deck.gl maps the world, add a scale bar + compass + North arrow (Carto/Positron-style) and put time/coords in a header chip, not microscopic axis ticks.

### Fix 2 — Title page: Figma → SVG → animate in Remotion
- Design the title in **Figma** (peach mesh hero, `$74B`/`PeachState CoolChain` lockup, Space Grotesk, per design tokens).
- Export as **SVG**; import into Remotion (`@remotion/svg` or plain `<img>`/inline SVG).
- Animate: mask-reveal title (staggered lines, `Easing.out(Easing.cubic)`), counter roll for `$74B` (tabular JetBrains Mono), subtle mesh shimmer (background only, 1.6 s, **not** infinite).
- This kills the PIL title instantly and matches `component_specs.md#7-stat-chip` + `scene_storyboards.md` Scene 0.

### Fix 3 — Kill looping animations
- Audit `design_tokens.json` motion.patterns: `glow_pulse` (1.6 s loop) and `shimmer` (2.4 s loop) become **one-shot** or `playOnce` in Remotion (or Manim `.set_run_time` with no repeat).
- Rule from the design system: "motion encodes state, never decoration" — encode the CRITICAL state with a **single** pulse at alert-instant, then hold, not perpetual pulsing.
- In Remotion, use `Sequence` + explicit durations; in Manim, remove `loop=True` equivalents and use `wait()`.
- Replace time-slider redraw loops with a **scrubbed `ValueTracker`** (Remotion: `useCurrentFrame()`), so time moves forward once per video, never wraps.

### Fix 4 — Purposeful camera moves with easing
- Remove ffmpeg `zoompan`. In Deck.gl use camera **transitions**: e.g., 2.4 s `flyTo` from GA overview → Fort Valley cluster with `Easing.inOut(Easing.cubic)`; push-in to PV-07 only once, holding for the tooltip (5 s), then pull back.
- In Manim use `self.play(camera.frame.animate.scale(0.75).set_ease_in_out_quint())` for match-cuts (per storyboards).
- Every camera move gets a reason (establish → focus → payoff) and a design-token duration (`hero` 0.8 s, `emphasis` 0.5 s) — never "random".

### Fix 5 — Color-coded heat from design_tokens Viridis ramp + proper legend
- Centralize ramp access: new `design/theme.ts` exporting `heatColor(f)`, `HEAT_RAMP`, `EASING`, `DUR` from `design_tokens.json` (mirror of `chart_theme.py`) so Python charts and TS scenes share identical colors.
- All heat surfaces (map, corridor temp profile, spoilage curves) use `ramp_smooth_24` interpolation on `tcm_f`, not discrete tier fills.
- Add the 24-stop legend bar (above) to every heat surface, with `lo_f: 80, hi_f: 105, unit: °F` from tokens.
- Keep Okabe-Ito categorical colors **only** for non-heat categorical data (crops, routes) — never for temperature.

---

## 7. Migration Roadmap (phased, low-risk)

| Phase | Scope | Exit criteria |
|---|---|---|
| **P0 (0.5 d)** | `design/theme.ts` from `design_tokens.json` (colors/ramp/easing/durations) + Jest snapshot; port `heat_color` | token parity: TS vs Python render identical color for sampled values |
| **P1 (1 d)** | Deck.gl scene for Field Map (HeatmapLayer + GeoJsonLayer + flyTo + legend) rendered to frames | field map video no longer "random dots"; 60 fps 1080p |
| **P2 (1 d)** | Remotion scaffold: `Composition` 1920×1080@60, 300 s; ingest fixtures via `inputProps`; scenes Hook + Field Map + KPIs | MP4 renders deterministically; numbers match fixtures |
| **P3 (1 d)** | Port remaining scenes (Alert, Corridor, Scale) incl. Manim-produced counter/corridor PNG sequences + Vega-Lite chart frames; Figma→SVG title | full 300 s master at 60 fps, all 6 scenes |
| **P4 (0.5 d)** | Captions (SRT/VTT), lower thirds, progress bar, click track sync, 1080p + 720p exports, CRF 18 yuv420p | output equals current assembly quality spec, plus new look |
| **P5 (0.5 d)** | Delete matplotlib charts + zoompan paths; docs; cleanup | no matplotlib in video pipeline |

**Team-skill hedge:** if TS is a blocker, fallback path = **Manim (Python) for all scenes + ffmpeg assembly** (current, improved) while keeping Deck.gl only for the map via `pydeck`-style frame capture; but the primary recommendation is Remotion because it is the only option that fixes all five complaints in one coherent timeline.

---

## 8. Sources / evidence (2024–2026)

- Manim Community v0.20.1/v0.21.0 releases (PyPI), OpenGL renderer guidance, headless `xvfb` notes (Manim docs, 2025–2026).
- Remotion docs: license & pricing (free ≤3 people; company license ~$100/mo), Remotion vs Motion Canvas comparisons, rendering to MP4/ProRes (remotion.dev, 2026).
- Motion Canvas / Revideo comparisons (programmatic render limits vs Remotion's CLI/Lambda) (2026).
- Deck.gl docs: HeatmapLayer GPU KDE, GeoJsonLayer, performance at millions of points, camera transitions (deck.gl 9.x docs, 2025–2026).
- Observable Plot + Vega-Lite (Observable Framework lib, Vega-Lite JSON spec) and VegaFusion/Mosaic for large-data transforms (2025–2026).
- Coldtype GitHub (alpha status, Apache-2.0); Cavalry free-for-individuals (Apr 2026) and data-driven positioning; Rive vs Lottie (state machines/data binding, 2025–2026); LottieFiles motion-design tools ranking (2026).
- Existing repo: `design/design_tokens.json`, `design/manim_theme.json`, `scripts/video_charts/*` (matplotlib pipeline), `scripts/assemble_demo_video.py` (ffmpeg zoompan), fixture JSONs under `data/fixtures/`.