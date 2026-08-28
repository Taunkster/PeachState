# Migration Checklist — matplotlib/ffmpeg → Remotion + Deck.gl + Vega-Lite

Owner: Data Visualization Engineer (Employee B). Mirrors `docs/11_video_stack_recommendation.md` §7
with a P0–P3 phasing tuned to the hackathon deadline. Every phase has an exit gate — do not
start the next phase until the gate passes.

Legend: `[x]` done · `[ ]` open · `[~]` in progress

---

## P0 — Scaffold + Heatmap proof-of-concept (0.5 d) — **DONE in this deliverable**

- [x] `video/` project scaffold: `package.json` (Remotion 4.0.514, Deck.gl 9.3.10, React 19, Vega-Lite 6), `remotion.config.ts`, `tsconfig.json`
- [x] `src/design/theme.ts` — typed mirror of `design/design_tokens.json` (imports synced copy, `npm run tokens:sync` keeps it 1:1)
- [x] `src/data/fixtures.generated.ts` — typed constants generated from the fixture JSONs (`npm run fixtures:gen`); `src/data/fixtures.ts` + `types.ts` + `colors.ts` provide chart_data/chart_theme parity
- [x] Hook scene proof-of-concept renders (title reveal, $74B counter, 3 staggered stat chips, one-shot shimmer, progress bar)
- [x] `npm run check` gate: token parity + hero values (PV-07 98.2°F/91, KPI 23%/$180K/12%/96%, corridor 54%/12%/142 mi) + `tsc --noEmit`
- [ ] **Gate P0**: `npm run render:hook` produces a clean 1920x1080@60 MP4, hero numbers fixture-verified

## P1 — Migrate all 6 scenes (1 d)

- [x] Scene 1 Field Map: Deck.gl `HeatmapLayer` (720 tiles/hour, `ramp_smooth_24` colorRange) + `GeoJsonLayer` fields + 24-stop °F legend + one `flyTo` camera
- [x] Scene 2 Harvest Alert: banner slide-in (snap), one-shot red pulse, SMS phone typewriter, status toasts
- [x] Scene 3 Corridor: `PathLayer` animated draw I-16/I-75, truck marker, route chips, SVG Q10 spoilage + temp profile, `corridor-spoilage.vl.json` spec
- [x] Scene 4 KPI: 4 `MetricCard`s (flip-in, counter roll, sparklines) + secondary metrics + HI report card
- [x] Scene 5 Scale: mosaic grid + closing brand card (QR slot)
- [x] `CoolChainMaster`: 6 `Sequence`s → 18000 frames (300s)
- [x] Wire scene captions from `docs/01_demo_script.md` narration into `CaptionBox` per scene
- [x] **Gate P1**: full master renders deterministically end-to-end; every scene number matches fixtures (spot-check PV-07 panel, corridor counters, KPI cards)

## P2 — Replace matplotlib charts with Vega-Lite / Remotion-native (1 d)

- [ ] Render `src/data/vega/*.vl.json` specs via `npm run vega:render` → ingest SVGs as `<Img>` in scenes (spoilage curves, risk time series)
- [ ] Port remaining matplotlib chart data (risk components, harvest windows, GDD tracker) as typed fixtures + Vega-Lite/Remotion components
- [ ] Replace `chart_b..h` PNGs in `data/video_charts/` with Remotion-native equivalents; keep old MP4s as fallback
- [ ] Figma → SVG title art for Hook (replace code-only lockup)
- [ ] **Gate P2**: zero matplotlib charts in the video pipeline

## P3 — Polish + captions + voiceover merge (0.5 d)

- [ ] 500ms crossfades between scenes via `@remotion/transitions` (master currently hard-cuts)
- [x] Burned-in captions (`data/rehearsal/_captions.srt`) via `CaptionOverlay` per scene
      — Remotion-native: `CoolChainWithCaptions` composition, `npm run render:with-captions`;
      sidecar SRT/VTT regenerated from the same captions.json via `npm run captions:gen` (Employee C)
- [x] Voiceover click-track visual alignment (`ClickTrack` HUD, 150 WPM from `_timing.json` key beats)
      — `CoolChainRecording` composition for the VO session (Employee C)
- [x] Lower thirds + progress bar + scene dots finalized per `design/component_specs.md`
- [x] 1080p + 720p exports (mirror current `assemble_demo_video.py` output spec)
      — `python3 scripts/assemble_demo_video.py --mode remotion` (DEFAULT) delegates the
      burned-in master render to `npm run render:with-captions` (PNG frames → ffmpeg encode,
      CRF18 yuv420p tv-range, exactly 18000 frames) + `render:720p` (web) + `captions:gen`
      (sidecars); validated by `validate_remotion()` (duration ±0.001 s, 18000 frames, yuv420p)
- [ ] QR code for closing brand card
- [ ] Delete matplotlib + `zoompan` paths (`scripts/video_charts/*`, `scripts/assemble_demo_video.py` legacy)
- [ ] GitHub Actions CI render job (headless Chrome, ffmpeg, artifact upload)
- [ ] **Gate P3**: output equals current assembly quality spec with the new Deck.gl look

## Key risks / hedges

- **TS blocker** → fallback: Manim (Python) for all scenes + ffmpeg assembly, keep Deck.gl only via
  `pydeck` frame capture (Employee A hedge, `docs/11_video_stack_recommendation.md` §7).
- **WebGL in headless Chrome** → `remotion.config.ts` sets `angle` OpenGL renderer (SwiftShader fallback);
  verify on the CI runner before P1 gate.
- **Fixture drift** → every scene reads `fixtures.generated.ts`; `npm run verify` fails CI if hero values change.