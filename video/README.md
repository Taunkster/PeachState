# PeachState CoolChain — Video Engine (Remotion + Deck.gl + Vega-Lite + Manim)

Programmatic video generation for the 5-minute (300s @ 60fps) judge demo, replacing the
matplotlib + ffmpeg pipeline. Based on Employee A's recommendation
(`docs/11_video_stack_recommendation.md`): **Remotion** is the timeline/assembly engine,
**Deck.gl** renders the maps/heatmaps (GPU kernel-density, not polygon dots), **Vega-Lite**
is the declarative chart layer (P2), **Manim** stays for math/counter scenes, and
`design/design_tokens.json` remains the single source of truth.

```
fixtures JSON ──▶ src/data/fixtures.generated.ts (typed, npm run fixtures:gen)
design_tokens.json ──▶ src/design/design_tokens.generated.json (npm run tokens:sync)
                          │
                          ▼
Deck.gl (maps/heatmap) ─┐
Vega-Lite (charts, P2) ─┼──▶ Remotion (React, 60fps) ──▶ JPEG frames ──▶ ffmpeg ──▶ MP4
SVG (titles/KPI cards) ─┘
```

## Project structure

```
video/
├── package.json               # exact deps (Remotion 4.0.514, Deck.gl 9.3.10, React 19, Vega-Lite 6)
├── remotion.config.ts         # 1920x1080@60, h264 CRF18 yuv420p, WebGL (ANGLE)
├── tsconfig.json
├── public/fonts/              # Space Grotesk / DM Sans / JetBrains Mono (offline)
├── scripts/
│   ├── generate-fixtures.mjs  # JSON → fixtures.generated.ts  (npm run fixtures:gen)
│   ├── sync-tokens.mjs        # design_tokens.json → theme mirror (npm run tokens:sync)
│   ├── verify-fixtures.mjs    # hero-value + parity checks     (npm run verify)
│   ├── vega-render.mjs        # Vega-Lite spec → SVG frames    (npm run vega:render)
│   └── encode.mjs             # frames → H.264 MP4             (npm run build)
└── src/
    ├── index.ts               # registerRoot entry
    ├── Root.tsx               # composition registry (6 scenes + CoolChainMaster 18000f)
    ├── design/
    │   ├── theme.ts           # TS mirror of design_tokens.json (colors/ramp/easing/type)
    │   └── components/        # MeshBackground, LowerThird, MetricCard, ProgressBar,
    │                          # Legend (24-stop heat), CaptionBox, SmsPhone, Fonts
    ├── scenes/                # Hook, FieldMap(Deck.gl), HarvestAlert, Corridor(Deck.gl+Vega-Lite), KPI, Scale
    ├── data/
    │   ├── types.ts           # canonical fixture types
    │   ├── fixtures.generated.ts  # AUTO-GENERATED typed data (do not edit)
    │   ├── fixtures.ts        # typed views + helpers (chart_data.py parity)
    │   ├── colors.ts          # heatColor()/tierColor()/heatColorRange() (chart_theme.py parity)
    │   └── vega/              # Vega-Lite specs (corridor-spoilage.vl.json)
    └── utils/                 # easing.ts (design-token beziers), camera.ts (flyTo), format.ts
```

## Install

```bash
cd /home/taha/peachstate-coolchain/video
npm install
```

## Commands

| Command | What it does |
|---|---|
| `npm run check` | sync tokens → regen fixtures → verify hero values → `tsc --noEmit` |
| `npm run studio` | Remotion Studio (hot-reload preview + scrubbing) |
| `npm run render:hook` | render Scene 0 proof-of-concept → `out/hook.mp4` |
| `npm run render` | render full 300s master → `out/peachstate_coolchain_demo.mp4` |
| `npm run render:with-captions` | **full master pipeline**: render `CoolChainWithCaptions` to PNG frames (chunked) → ffmpeg H.264 CRF18 yuv420p tv-range → silent AAC → `out/peachstate_coolchain_demo_with_captions.mp4` (exactly 18000 frames = 300.000 s) |
| `npm run render:720p` | web version from the master → `out/peachstate_coolchain_demo_720p.mp4` (1280×720 @ 30 fps, CRF18 yuv420p) |
| `npm run render:recording` | master + `ClickTrack` visual metronome → `out/peachstate_coolchain_demo_recording.mp4` (VO session) |
| `npm run render:frames` | render JPEG frame sequence → `out/frames/frame_%d.jpeg` |
| `npm run build` | frames → ffmpeg H.264 CRF18 yuv420p → `out/peachstate_coolchain_demo.mp4` |
| `npm run vega:render` | Vega-Lite specs → `out/vega/*.svg` (P2 chart frames) |
| `npm run fixtures:gen` | regenerate `src/data/fixtures.generated.ts` from fixture JSONs (incl. captions + timing) |
| `npm run captions:gen` | regenerate sidecar `data/rehearsal/*_captions.srt/.vtt` from the same `captions.json` |
| `npm run tokens:sync` | re-copy canonical `design/design_tokens.json` into the theme mirror |

## Render pipeline

```
npm run check          # gates: token parity + hero numbers + types
npm run render:with-captions  # PNG frames (chunked) → ffmpeg CRF18 yuv420p → master MP4
npm run render:720p    # 1280x720@30 web version from the master
npm run captions:gen   # SRT/VTT sidecars from the same captions.json
```

One-shot: `python3 ../scripts/assemble_demo_video.py --mode remotion` (the
default) runs all four plus thumbnail/timing/clicktrack and drops the full
deliverable set in `data/rehearsal/`. Full render instructions + quality gates
live in `RENDER_INSTRUCTIONS.md` (repo root).

CI (GitHub Actions) runs `npm run check`; headless Chrome is bundled by Remotion.

## Key visual fixes implemented

1. **Heatmap → Deck.gl `HeatmapLayer`** (`scenes/FieldMap.tsx`): real GPU kernel-density
   fed by 720 tile centroids/hour from `dashboard/heat_frames.json`, `colorRange` bound to
   `heat.ramp_smooth_24`, plus a `GeoJsonLayer` for the 45 field polygons and a 24-stop
   legend with °F ticks. No more discrete polygon dots.
2. **Corridor → `PathLayer` animated draw** (`scenes/Corridor.tsx`): I-16 (blue) / I-75
   (red) slice forward once; a `ScatterplotLayer` reefer rides I-16. Q10 spoilage curves +
   temp profile rendered as SVG mirrors of `src/data/vega/corridor-spoilage.vl.json`.
3. **No loops**: every animation is one-shot (`spring`/`interpolate` with explicit
   durations, `Sequence`-driven timeline; no wrapped time, no infinite pulses).
4. **Purposeful cameras**: `utils/camera.ts` `flyTo()` uses the design-token
   `cubic-bezier(0.22, 1, 0.36, 1)` — replaces ffmpeg `zoompan`.
5. **Color from tokens**: `src/data/colors.ts` is a line-for-line port of
   `chart_theme.py` (`heat_color`, `tier_color`); verified identical by `npm run verify`.
6. **Remotion-native captions** (`CaptionOverlay`/`ClickTrack`, Employee C):
   burned-in captions render inside the composition from the same `captions.json`
   that produces the SRT/VTT sidecars — no PIL/ffmpeg overlay pass.

## Caption & voiceover system (Employee C)

Single source of truth: `data/rehearsal/peachstate_coolchain_demo_captions.json`
(21 blocks, seconds on the 300 s master) + `..._timing.json` (scenes, 150 WPM
clicktrack spec, key beats). `npm run fixtures:gen` embeds both as typed
`CAPTIONS` / `TIMING` in `src/data/fixtures.generated.ts`.

| Artifact | File | Used for |
|---|---|---|
| Burned-in | `src/design/components/CaptionOverlay.tsx` (composition `CoolChainWithCaptions`) | submission MP4 |
| Karaoke | `CaptionOverlay karaoke` (composition `CoolChainKaraoke`) | word-level peach highlight |
| Recording aid | `src/design/components/ClickTrack.tsx` (composition `CoolChainRecording`) | visual metronome for VO session |
| Parser/helpers | `src/utils/captions.ts` | frame sync, karaoke timing, SRT/VTT builders, beat helpers |
| Sidecar SRT/VTT | `npm run captions:gen` → `data/rehearsal/*_captions.srt/.vtt` | YouTube / Vimeo |

Rendering: `python scripts/assemble_demo_video.py --mode remotion` runs
`npm run render:with-captions` (burned-in) then `npm run captions:gen`
(sidecars) and assembles the full `data/rehearsal/` deliverable set.

## Licensing note

Remotion is free for teams ≤ 3 people (hackathon fits). If the org grows past that,
budget for the company license (~$100/mo) — see `docs/11_video_stack_recommendation.md`.