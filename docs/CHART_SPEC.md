# Video Chart Specification — PeachState CoolChain

Eight animated charts (A–H) for the demo video. Every chart renders a
1920×1080 PNG sequence at 60 fps and encodes a silent MP4 via
`render_all.py`. **Every displayed number is read at render time from the
real fixture JSONs** — see the "Source" column; nothing is hard-coded
except Scene-5 canonical numbers (Chart H, see note).

| Chart | File | Duration | Frames | MP4 |
|-------|------|----------|--------|-----|
| A | `chart_a_field_heatmap.py` | 14.0 s | 840 | `data/video_charts/chart_a_field_heatmap.mp4` |
| B | `chart_b_risk_components.py` | 5.0 s | 300 | `data/video_charts/chart_b_risk_components.mp4` |
| C | `chart_c_temp_timeline.py` | 5.5 s | 330 | `data/video_charts/chart_c_temp_timeline.mp4` |
| D | `chart_d_corridor.py` | 7.0 s | 420 | `data/video_charts/chart_d_corridor.mp4` |
| E | `chart_e_spoilage_kinetics.py` | 6.5 s | 390 | `data/video_charts/chart_e_spoilage_kinetics.mp4` |
| F | `chart_f_kpi_dashboard.py` | 8.0 s | 480 | `data/video_charts/chart_f_kpi_dashboard.mp4` |
| G | `chart_g_alert_timeline.py` | 9.0 s | 540 | `data/video_charts/chart_g_alert_timeline.mp4` |
| H | `chart_h_scale_mosaic.py` | 6.0 s | 360 | `data/video_charts/chart_h_scale_mosaic.mp4` |

Total footage: **61 s** (≈1 min). Output root: `data/video_charts/`.

---

## Chart A — Field Heat Map (State of Georgia)

**Scene 1.** Heat map of all 45 monitored fields on a real GA boundary
(`scripts/video_charts/ga_boundary.geojson`). Hour slider animates
08:00→17:00 EDT; clicking PV-07 opens a tooltip.

| Element | Source fixture | Field |
|---------|---------------|-------|
| Fields + polygons | `data/fixtures/dashboard/heat_frames.json` | `frames[t].features[].geometry` |
| Field tier colors | `design/design_tokens.json` | `risk_tiers` (LOW `#10B981`, MEDIUM `#F59E0B`, HIGH `#F97316`, CRITICAL `#EF4444`) |
| Hourly tile temps | `data/fixtures/dashboard/heat_frames.json` | `frames[t].features[].properties.tcm_f[]` (16 tiles/field/hr) |
| Field tier per hour | `data/fixtures/dashboard/heat_frames.json` | `field_tiers[t]` |
| PV-07 tooltip risk 91 | `data/fixtures/demo/fields_snapshot.json` | `fields["PV-07"].risk.score` (91.0) |
| PV-07 tooltip canopy 98.2 °F | `data/fixtures/demo/fields_snapshot.json` | `fields["PV-07"].risk.canopy_temp_f` (98.2) |
| PV-07 tooltip threshold 95 °F | `data/fixtures/demo/alerts.json` | `alerts[0].threshold_f` (95.0) |
| PV-07 tooltip exceedance 3.4 h | `data/fixtures/demo/alerts.json` | `alerts[0].exceedance_hours` (3.4) |
| Alert pop-up copy | `data/fixtures/demo/alerts.json` | `alerts[0].recommended_action` |

**Data model note:** the canonical heat data is the dashboard fixture
(10 steps, all 45 fields). The `demo/heat_frames.json` file only contains
3 fields × 3 steps and is **not** used for this chart.

---

## Chart B — Risk Components (Crop Radar)

**Scene 2.** Stacked component bars per crop — temperature, exceedance,
persistence — revealing why each crop's risk score is what it is.

| Element | Source fixture | Field |
|---------|---------------|-------|
| Component split per crop | `data/fixtures/dashboard/risk_data.json` | `crop_radar[]` (`temp`, `exceedance`, `persistence`) |
| Crop list | `data/fixtures/dashboard/risk_data.json` | `crop_radar[].crop` |
| Component colors | `design/design_tokens.json` | temp `#EF4444`, exceedance `#F59E0B`, persistence `#3B82F6` |

---

## Chart C — Canopy Temperature Timeline

**Scene 2.** Hourly canopy-temperature lines for three hero fields:
PV-07 (peach), AL-01 (Albany pecan), VD-01 (Vidalia onion), with the
crop alert thresholds as horizontal bands.

| Element | Source fixture | Field |
|---------|---------------|-------|
| Hourly canopy temp (per field) | `data/fixtures/dashboard/heat_frames.json` | tile mean of `frames[t].features[].properties.tcm_f[]` over that field's 16 tiles |
| Alert thresholds | `data/crop_thresholds.json` | `crops[peach|pecan|vidalia_onion].alert_f` |
| Field→crop mapping | `data/fixtures/dashboard/heat_frames.json` | `features[].properties.crop` |

**Field ID mapping (task → fixture):** the task named "ALB-01" and
"VID-01"; the real fixture IDs are **AL-01** (Albany pecan) and **VD-01**
(Vidalia onion) — see `docs/04_demo_data_strategy.md`. These are the IDs
rendered on chart.

---

## Chart D — Corridor Comparison (I-16 vs I-75)

**Scene 3.** Side-by-side route cards. The I-16 corridor (cooler, shorter,
recommended) is compared with I-75 (hotter, longer) using the exact route
stats from the demo corridor fixture.

| Element | Source fixture | Field |
|---------|---------------|-------|
| Route geometry (5 pts each) | `data/fixtures/demo/corridor.json` | `routes[]` |
| I-16 avg 91.3 °F | `data/fixtures/demo/corridor.json` | `routes[0].avg_temp_f` |
| I-75 avg 97.1 °F | `data/fixtures/demo/corridor.json` | `routes[1].avg_temp_f` |
| I-16 spoilage 3.1 % | `data/fixtures/demo/corridor.json` | `routes[0].spoilage_risk_pct` |
| I-75 spoilage 6.8 % | `data/fixtures/demo/corridor.json` | `routes[1].spoilage_risk_pct` |
| I-16 fuel 116 gal | `data/fixtures/demo/corridor.json` | `routes[0].fuel_gal` |
| I-75 fuel 132 gal | `data/fixtures/demo/corridor.json` | `routes[1].fuel_gal` |
| Distance / exposure | `data/fixtures/demo/corridor.json` | `routes[]` `distance_mi`, `exposure` |
| Corridor colors | task spec | I-16 `#3B82F6`, I-75 `#EF4444` |

---

## Chart E — Spoilage Kinetics (Q10 Model)

**Scene 4.** Left: spoilage-risk bars (I-16 3.1 % vs I-75 6.8 %). Middle:
reefer fuel bars (116 vs 132 gal). Right: Q10 decay-rate curves for peach
(Q10 = 2.8) and blueberry (Q10 = 3.2) with the fixture's degree-hour
curves overlaid as dashed lines.

| Element | Source fixture | Field |
|---------|---------------|-------|
| Spoilage bars | `data/fixtures/demo/corridor.json` | `routes[]` `spoilage_risk_pct` |
| Fuel bars | `data/fixtures/demo/corridor.json` | `routes[]` `fuel_gal` |
| Peach Q10 = 2.8 | `data/crop_thresholds.json` | `crops.peach.q10_spoilage` |
| Blueberry Q10 = 3.2 | `data/crop_thresholds.json` | `crops.blueberry.q10_spoilage` |
| Degree-hour curves | `data/fixtures/dashboard/risk_data.json` | `spoilage[]` (`crop`, `curve[]` `h`/`dh`) |
| Curve math | — | `rate(T) = Q10^((T − 50 °F)/18 °F)` (18 °F = 10 °C), normalized to 1.0 at 50 °F |

---

## Chart F — KPI Dashboard

**Scene 4.** Four metric cards with animated counters (0 → target over
1.2 s) and sparklines drawn from the fixture's own history arrays.

| Element | Source fixture | Field |
|---------|---------------|-------|
| Spoilage risk ↓ 23 % | `data/fixtures/demo/kpis.json` | `kpis[]` where `id=="spoilage"`, `value="↓ 23%"` |
| Season savings $180K | `data/fixtures/demo/kpis.json` | `kpis[]` `id=="savings"`, `value="$180K"` |
| Fuel savings 12 % | `data/fixtures/demo/kpis.json` | `kpis[]` `id=="fuel"`, `value="12%"` |
| Port on-time 96 % | `data/fixtures/demo/kpis.json` | `kpis[]` `id=="port"`, `value="96%"` |
| Sparkline series | `data/fixtures/demo/kpis.json` | `kpis[].spark[]` |
| Deltas / tones | `data/fixtures/demo/kpis.json` | `kpis[].delta`, `kpis[].tone` |
| Secondary metrics | `data/fixtures/demo/kpis.json` | `secondary[]` |

---

## Chart G — Harvest Alert Timeline

**Scene 2.** PV-07 risk progression 08:00→15:00 EDT as a Gantt of hourly
risk scores, with the CRITICAL alert firing at 15:00 and an SMS phone
mockup that types the exact fixture alert message.

| Element | Source fixture | Field |
|---------|---------------|-------|
| Hourly PV-07 risk 87.0→91.0 | `data/fixtures/dashboard/heat_frames.json` | `field_scores[t]["PV-07"]` for 08:00–15:00 |
| Tier bands (LOW/MED/HIGH/CRIT) | `design/design_tokens.json` + `data/crop_thresholds.json` | `risk_tiers` boundaries |
| Alert trigger time | `data/fixtures/demo/alerts.json` | `alerts[0].ts` = `2025-07-15T19:04:00Z` → 15:04 EDT |
| Alert urgency 91.0 | `data/fixtures/demo/alerts.json` | `alerts[0].urgency` |
| Alert canopy 98 °F, exceed 3.4 h | `data/fixtures/demo/alerts.json` | `canopy_temp_f`, `exceedance_hours` |
| Recommended action | `data/fixtures/demo/alerts.json` | `alerts[0].recommended_action` |
| SMS body (all 4 lines) | `data/fixtures/demo/alerts.json` | `alerts[0].sms.body` |
| Packing house / truck | `data/fixtures/demo/alerts.json` | `alerts[0].packing_house`, `sms.body` (Reefer #212, I-16) |

---

## Chart H — Scale Vision Mosaic

**Scene 5.** Three cards — Athens community garden, Atlanta last-mile
delivery, backyard grower — each with a mini heat map (design-token heat
ramp) and one key metric.

> **Data note:** Scene 5 has **no dedicated fixture**. The three cards use
> the canonical Scene-5 numbers from the demo script
> (`docs/01_demo_script.md`) plus the community crop threshold model from
> `data/crop_thresholds.json`. This is the project's authoritative spec
> for the vision scene (community gardens + last-mile delivery were
> designed there, not in fixture data).

| Element | Source | Field |
|---------|--------|-------|
| Athens garden · ATH-CG-02 · 1.8 ac | `docs/01_demo_script.md` | Scene 5 canonical: risk 58/100, harvest window tonight 8 PM |
| Atlanta last-mile · 34 °F cooler | `docs/01_demo_script.md` | "34 °F cooler in shade corridors" |
| Community alert 90 °F / critical 95 °F / Q10 2.5 | `data/crop_thresholds.json` | `crops.community` (`alert_f`, `critical_f`, `q10_spoilage`) |
| Mini heat-map colors | `design/design_tokens.json` | heat ramp (`heat_color`) |
| Location anchors | — | Athens (33.95, −83.37), Atlanta (33.75, −84.39) |

---

## Runtime & Quality

- **Render all:** `cd scripts/video_charts && python render_all.py`
  (or `.venv/bin/python`). Flags: `--chart a..h`, `--no-mp4`.
- **Full render time:** ≈ 5.7 min (3660 frames + 8 MP4 encodes) on dev box.
- **Fonts:** Space Grotesk (display), DM Sans (UI), JetBrains Mono
  (numerics) — downloaded to `scripts/video_charts/fonts/` (Regular
  weights only; matplotlib "weight 600" fallback warnings are benign).
- **Palette:** all colors from `design/design_tokens.json` (navy
  `#0B1120` background, cream, slate, peach, success, warning, danger).
- **Validation:** `python validate_charts.py` — 65 cross-checks against
  fixture JSONs (see `VALIDATION_REPORT.md`).