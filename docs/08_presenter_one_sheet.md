# PEACHSTATE COOLCHAIN — DEMO DAY ONE-SHEET (presenter cheat sheet)

**Tagline:** "From Georgia field to Port of Savannah — heat never wins."

**Stack:** Streamlit dashboard · FortyGuard Temperature API · FIXTURES mode
default (`DATA_SOURCE=fixtures`) — network-off safe · fallback live 8s timeout
· GET /health for source state.

## Flow (300s)

| # | Time | Scene | 1-line beat | Endpoint shout-out |
|---|------|-------|-------------|--------------------|
| 0 | 0:00–0:30 | Hook | "Georgia grows **$780M** of peach/pecan/blueberry/onion; humid July heat rots it. FortyGuard sees it first." | — |
| 1 | 0:30–1:30 | Field map | Slider 08→11→15. Click PV-07. "Color = canopy risk from 2m heat + GHI loading + humidity." | `heatmap` tcm |
| 2 | 1:30–2:30 | Harvest alert | "PV-07 at 98°F, 3.4h above threshold, +6h forecast. Agent says HARVEST NOW → SMS to foreman." | `exceedance` + `env_params` |
| 3 | 2:30–3:30 | Cool corridor | "I-75 = 318 mi @ 97°F. I-16 = 176 mi @ 91°F — 142 mi shorter. Q10 spoilage −54%, fuel −12%." | corridor `heatmap` + `env_params` |
| 4 | 3:30–4:15 | Dashboard KPIs | "23% spoilage ↓ · **$180K saved** · 12% fuel ↓ · 96% Port on-time." | `heat_intelligence` |
| 5 | 4:15–5:00 | Scale vision | "Same API, ten square miles — Athens community garden, Atlanta last mile. Scan the QR." | same API, smaller polygons |

**HARD STOP 4:50.**

## Key numbers (memorize in this order)
$780M GA crop value (peach/pecan/blueberry/onion) · thresholds: peach 95 / pecan 95 / blueberry 90 / onion 85 °F · PV-07: 98°F, 3.4h exceedance, risk 91 @ 15:00 (87 @ 08:00) · I-75 **318 mi @ 97.1°F** vs I-16 **176 mi @ 91.3°F** (142 mi shorter) · spoilage **−54%** load / **−23%** season · **$180K** saved · 12% fuel · 96% Port on-time · 45 fields · 5 regions · frozen date **2025-07-15 15:00 EDT**.

## Interaction points (mouse only)
1. Scene 1: slider 08→11→15 (slow), click **PV-07**.
2. Scene 2: click **SEND SMS** exactly on "harvest now".
3. Scene 3: let truck animation finish (~8s), point red then blue.
4. Scene 4: click PDF report once (thumbnail, don't wait).
5. Scene 5: click **ATH-CG-02** community garden.

## Safety net (Day 7 hardened)
- Everything runs in **FIXTURES mode** (`DATA_SOURCE=fixtures`, default) — zero network dependency. All fixture JSON = byte-identical recorded live API output (Day 6).
- `Ctrl+D` = next scene (any click miss).
- If app freezes: switch to pre-recorded **`data/rehearsal/day7_final_demo.mp4`** (Loom-ready), no apology, "let's jump to the corridor scene."
- If a judge asks about live: "Every number you see is real API output, cached locally — the demo doesn't depend on the network." Health endpoint `GET /health` shows `{data_source, last_live_ok, cache_age_s}`.
- Demo-mode launch: `STREAMLIT_SERVER_HEADLESS=true STREAMLIT_BROWSER_GATHER_USAGE_STATS=false streamlit run dashboard/app.py` (no tab pop, no telemetry).
- If time is short: skip Scene 5, land after KPIs + one-line scale vision.

## Q&A one-liners (see docs/07 for the full paragraph)
- Canopy from 2m air: "2m air + GHI loading + VPD cooling, capped per crop — fruit lives at 2m."
- Calibrated? "Per-crop thresholds from UGA Extension; weights in `data/crop_thresholds.json`."
- Why I-16 cooler: "142 mi shorter toward the coast — Atlantic marine layer; I-75 cuts inland through the hottest part of the state."
- $180K: "23% spoilage reduction × $780M of GA crop value — before fuel and Port-rejection savings."
- API down? "FIXTURES mode by default; HYBRID has an 8s live timeout with auto-fallback to recorded fixtures."
- vs Google Maps: "They minimize minutes; we minimize heat exposure under the same delivery window."
- Q10 spoilage: "Decay scales exponentially with temperature; six degrees + shorter trip = −54% this load."
- 10 mi² limit: "Premium 50 mi² key; corridors tiled into sub-AOIs; env waypoints only."
- Who pays: "Packers (Lane, Pearson), shippers (Lineage), insurers (USDA RMA)."
- Real-time? "15-min cadence, heatmap 12h lag, env_params live."
- Pecans? "Tree is heat tolerant; kernel-fill stage is moisture + temp sensitive."
- Soil moisture? "FAO-56 Hargreaves bucket — decision support, not telemetry."
- Creative API use: "Heatmap analytic + env_params + GDD fused into one harvest command."

## Demo-day kit checklist
- [ ] Charged laptop + HDMI/dongle tested at 1080p
- [ ] App pre-warmed: all 6 tabs visited once (cache hot)
- [ ] `DATA_SOURCE=fixtures` confirmed in the shell (`echo $DATA_SOURCE`)
- [ ] Launch flags set: `STREAMLIT_SERVER_HEADLESS=true`, `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false`
- [ ] Backup video `data/rehearsal/day7_final_demo.mp4` on the demo machine **and** a phone
- [ ] Hotspot + backup laptop + Loom queued
- [ ] Fonts installed (Inter + Roboto Mono)
- [ ] OS notifications + sleep disabled
- [ ] QR code to GitHub repo on the last slide
- [ ] `.env` present locally with rotated key (never committed); `requirements-lock.txt` in the bundle
- [ ] GA coverage check done (Fort Valley, Albany, Macon, Savannah)