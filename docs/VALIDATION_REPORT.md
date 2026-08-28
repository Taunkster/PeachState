# Validation Report — PeachState CoolChain Video Charts

**Date:** 2026-08-20
**Scope:** All eight animated charts (A–H) in `scripts/video_charts/`.
**Tool:** `scripts/video_charts/validate_charts.py` — reads every number
back from the fixture JSONs at validation time. Where expectations exist
they were derived from the fixtures themselves (not invented).
**Result:** **65 / 65 checks PASSED** (exit code 0).

---

## 1. Render integrity

| Chart | Frames | MP4 size (px) | FPS | Duration | Blank frames |
|-------|-------:|---------------|-----|---------:|:------------:|
| A field heatmap | 840 | 1920x1080 | 60 | 14.00 s | none |
| B risk components | 300 | 1920x1080 | 60 | 5.00 s | none |
| C temp timeline | 330 | 1920x1080 | 60 | 5.50 s | none |
| D corridor | 420 | 1920x1080 | 60 | 7.00 s | none |
| E spoilage kinetics | 390 | 1920x1080 | 60 | 6.50 s | none |
| F KPI dashboard | 480 | 1920x1080 | 60 | 8.00 s | none |
| G alert timeline | 540 | 1920x1080 | 60 | 9.00 s | none |
| H scale mosaic | 360 | 1920x1080 | 60 | 6.00 s | none |

- Frame content check: sampled frames across each timeline show non-trivial
  luminance variance and 61–64 quantized colors — no blank/corrupt frames.
- MP4 files verified with `ffprobe` (resolution, frame rate, duration correct).

## 2. Data accuracy — by chart

### A — Field heat map (14 checks)
- PV-07 tooltip risk score **91.0** == `fields_snapshot.json` risk.score (91.0)
- PV-07 canopy **98.2 °F** == `fields_snapshot.json` canopy_temp_f
- PV-07 threshold **95 °F**, exceedance **3.4 h** == `alerts.json`
- PV-07 tier **critical** == `fields_snapshot.json` risk.tier
- Alert timestamp 19:04Z == **15:04 EDT**; SMS status `SENT`
- All 45 fields with polygon + tier data from `dashboard/heat_frames.json`
  (10 hourly steps)

### B — Risk components (15 checks)
- Component split (`temp`/`exceedance`/`persistence`) per crop matches
  `dashboard/risk_data.json` `crop_radar[]` **exactly** (all 5 crops:
  peach, pecan, blueberry, vidalia onion, community)
- Components sum > 0 for every crop

### C — Canopy temperature timeline (9 checks)
- 10 hourly canopy values per field (PV-07, AL-01, VD-01)
- Tile-mean canopy @ 15:00 matches snapshot canopy within 0.5 °F:
  - PV-07: 98.3 vs 98.2
  - AL-01: 94.5 vs 94.4
  - VD-01: 93.1 vs 93.1
- PV-07 diurnal trend: 08:00 < 15:00 (heat of day)

### D — Corridor comparison (8 checks)
Demo corridor fixture (`demo/corridor.json`) — matches annotation copy exactly:
- I-16: avg **91.3 °F**, spoilage **3.1 %**, fuel **116 gal**, distance **176 mi**
- I-75: avg **97.1 °F**, spoilage **6.8 %**, fuel **132 gal**, distance **318 mi**
- Both routes have >= 2 geometry points

### E — Spoilage kinetics (4 checks)
- Peach Q10 **2.8**, Blueberry Q10 **3.2** == `crop_thresholds.json`
- Peach & blueberry degree-hour spoilage curves present in
  `dashboard/risk_data.json` `spoilage[]`

### F — KPI dashboard (6 checks)
- 4 cards exactly as `kpis.json`: down 23 % / $180K / 12 % / 96 %
- Sparkline terminal values match: spoilage 23, savings 180
- Card deltas/tones read from fixture

### G — Alert timeline (8 checks)
- PV-07 hourly risk **87.0, 87.5, 88.0, 88.5, 89.0, 89.5, 90.5, 91.0**
  for 08:00–15:00 == `dashboard/heat_frames.json` `field_scores`
- Final value 91.0 reconciles with `alerts.json` urgency (91.0) and
  `fields_snapshot.json` risk (91.0) — full-chain consistency
- SMS body line 1 == "FIELD PV-07 — HARVEST NOW"; contains `98°F`,
  `3.4h`, `I-16`, `Reefer #212` — all exact from `alerts.json`

### H — Scale vision (3 checks)
- Community crop threshold == `crop_thresholds.json`: alert **90 °F**,
  critical **95 °F**, Q10 **2.5**
- Scene-5 canonical numbers (ATH-CG-02 · 1.8 ac · risk 58/100; Atlanta
  34 °F cooler) traced to `docs/01_demo_script.md` (no fixture exists for
  Scene 5 — documented in `CHART_SPEC.md`)

## 3. Notes & known limitations

1. **Scene 5 has no fixture.** Chart H's garden/delivery metrics come from
   the demo script (`docs/01_demo_script.md`), the project's canonical
   Scene-5 spec, plus the `community` crop model. If fixture files are
   later added for Athens/Atlanta/backyard, Chart H should be rewired.
2. **Field ID mapping.** Task references "ALB-01"/"VID-01"; fixture IDs are
   `AL-01` (Albany pecan) and `VD-01` (Vidalia onion) — documented in
   `CHART_SPEC.md` and consistent with `docs/04_demo_data_strategy.md`.
3. **Fonts.** Only Regular weights were downloaded; matplotlib logs benign
   "Failed to find font weight 600" warnings (falls back to Regular).
4. **Chart H mini heat maps** are illustrative (design-token heat ramp at
   documented anchor coordinates) — they visualize the community-crop
   temperature band, not per-polygon fixture data (none exists for Scene 5).

## 4. Reproduce

```bash
cd scripts/video_charts
.venv/bin/python validate_charts.py      # 65/65 PASS, exit 0
.venv/bin/python render_all.py           # frames + MP4s (~5.7 min)
```
