# 04 — Demo Data Strategy (Georgia)

## 4.1 Principle

> **Demo data is a first-class citizen, not an afterthought.** Every screen must render identically with the network off. Live mode is an enhancement, not a dependency.

## 4.2 Fixture store (`data/fixtures/`)

Pre-recorded API responses saved as JSON, mirroring real SDK return shapes:

```
data/
├── crop_thresholds.json
└── fixtures/
    ├── fortvalley_heatmap_08_11_15.json   # tcm frames for 08/11/15:00 EDT (Scene 1)
    ├── albany_heatmap_08_11_15.json       # pecan groves tcm frames (Scene 1)
    ├── fortvalley_exceedance_1500.json    # exceedance analytic PV-07 (Scene 2)
    ├── farm_env_params_1500.json          # humidity/heat_index/GHI at Fort Valley (Scene 2)
    ├── corridor_heatmap_i75_i16.json      # heat along both corridors (Scene 3)
    ├── corridor_env_params.json           # ambient temp along routes (RoutePoint)
    ├── heat_intelligence_report.json      # PDF download_link (Scene 4)
    ├── risk_series_24h.json               # pre-computed risk time series (Scene 4)
    ├── harvest_events.json                # 24h harvest urgency log (Scene 4)
    ├── gdd_tracker.json                   # season-long GDD per crop (Scene 4)
    ├── athens_heatmap_10mi.json           # community gardens frame (Scene 5)
    └── atlanta_lastmile_heatmap.json      # last-mile corridor frame (Scene 5)
```

Each fixture follows the **exact data contracts in `02_dashboard_components.md`**, so `data_source.py` needs zero transformation — swapping `LIVE ↔ FIXTURES` is one env var.

**Fixture generation script** (`scripts/gen_fixtures.py` — handoff to Employee 1/2): calls the real API once per fixture with the project API key, saves responses, adds synthetic jitter so frames look organic. Run ahead of the demo; commit to repo.

## 4.3 Synthetic-but-realistic Georgia geography

All coordinates are real Georgia towns/corridors, confirmed inside FortyGuard's US coverage (Georgia state coverage confirmed).

- **Fort Valley / Peach County (Scene 1):** ~15 peach orchard polygons (PV-01…PV-15) in a **20 mi² cluster** centered on 32.55°N, 83.89°W. Real orchard-block shapes via `shapely` buffering/union of random-walk boundaries; areas 80–400 ac. 2 clusters: NW block (older trees, hotter baseline) and SE block.
- **Albany / Dougherty County (Scene 1):** ~10 pecan groves (ALB-01…ALB-10) **spread along the Flint River** ~31.5–31.7°N, 84.1–84.2°W. Longer thin polygons tracing river meanders; 150–700 ac each.
- **Bacon/Appling Counties (dashboard list + optional map):** ~8 blueberry farms (BB-01…BB-08) along the **US-1/US-23 corridor** near Alma, GA ~31.5°N, 82.4°W. Packing house at Alma.
- **Vidalia / Toombs County (dashboard list + optional map):** ~12 onion fields (VD-01…VD-12) ~32.2°N, 82.4°W. **Curing sheds marked** as separate point markers (curing = heat-sensitive stage).
- **Community scale-down (Scene 5):** Athens — UGA trial garden + 4 community gardens (ATH-CG-01…05) near 33.95°N, 83.37°W; Atlanta — last-mile delivery zone with 12 street-corridor segments near 33.75°N, 84.39°W.
- **Corridors (Scene 3):** origin **Macon** (32.84°N, 83.63°W), destination **Port of Savannah** (32.08°N, 81.10°W).
  - **I-75 route** (inland): Macon → I-75 S → Valdosta → US-84/US-341 → Savannah. **318 mi, avg 97°F, peak 102°F** (hot inland asphalt).
  - **I-16 route** (direct coastal): Macon → I-16 E → Savannah. **176 mi, avg 91°F, peak 96°F** (cooler coastal influence).
  - Geometry pulled from OpenStreetMap via `osmnx` once, cached in `data/ga_corridors.geojson`. Temperatures: add +3–5°F to I-75 inland segments vs I-16 — grounded in July GA coastal-vs-inland gradients.

## 4.4 Packing houses (`data/packing_houses.json`)

| Facility | Location | Crop | Role in demo |
|----------|----------|------|--------------|
| Fort Valley Peach Co-op (FVC-01) | Fort Valley | Peach | Scene 2 pre-cool slot + inbound load card |
| Albany Pecan Growers (APG-01) | Albany | Pecan | Alert coordination (Scene 2 side-list) |
| Alma Blueberry Exchange (ABX-01) | Alma | Blueberry | Dashboard packing list (Scene 4) |
| Vidalia Sweet Onion Packing (VOP-01) | Vidalia | Onion | Curing shed status (Scene 4) |
| Garden City Terminal | Savannah | Port | Scene 3 destination + on-time KPI |

## 4.5 Crop thresholds (`data/crop_thresholds.json`)

Canopy (2m air) heat thresholds in °F, from UGA Extension / USDA literature:

| Crop | Alert °F | Critical °F | Risk weight (heat) | Q10 spoilage | Notes |
|------|----------|-------------|--------------------|--------------|-------|
| Peach | 95 | 100 | 0.45 | 2.8 | brown rot / softening |
| Pecan | 95 | 100 | 0.40 | 2.2 | kernel quality |
| Blueberry | 90 | 95 | 0.50 | 3.2 | decay, anthocyanin loss |
| Vidalia onion | 85 | 90 | 0.55 | 1.8 | sprouting in curing/transit |
| Community/residential | 90 | 95 | 0.45 | 2.5 | wilt / leaf stress |

The actual machine-readable file lives at `data/crop_thresholds.json` (created alongside this document).

## 4.6 Risk model inputs (what fixtures encode)

Canopy heat risk score (0–100) per field, pre-computed:
`risk = 100 · clamp( Σ wᵢ · zᵢ )`, where `z` are standardized proxies:

- `z_temp` — current 2m air temp (`heatmap` tcm) relative to crop alert/critical thresholds.
- `z_exceed` — hours above alert threshold (`heatmap` exceedance).
- `z_persist` — forecast persistence (`heatmap` persistence) + `env_params` heat_index/humidity modifier.

Weights per crop live in `crop_thresholds.json`. Presenters never show the formula live — one sentence in Scene 2 ("risk = heat + hours above threshold + forecast, weighted by crop") is enough.

## 4.7 Q10 spoilage kinetics (Scene 3 numbers)

Per-crop Q10 from USDA literature; demo load = **fresh peaches** (Q10 ≈ 2.8):

- Baseline: load spends T hours at ambient T°F on each route; respiration/decay rate `r = r₀ · Q10^((T − 32)/10)` above refrigeration baseline.
- I-75: 318 mi @ avg 97°F → spoilage probability **6.8%**.
- I-16: 176 mi @ avg 91°F → spoilage probability **3.1%**.
- Delta: **−54% spoilage risk this load** (temp effect × shorter exposure time).
- Season-aggregated KPI (Scene 4): **−23% spoilage risk** across all 45 fields after harvest-timing + routing + pre-cooling interventions (field intervention contributes the majority).

## 4.8 Determinism & replay

- Every scene is a fixed sequence of `DemoState` mutations (defined in `scripts/demo_sequence.py`).
- Hidden hotkey `Ctrl+D` steps to the next scene regardless of mouse — presenter safety net.
- **Timestamps frozen to 2024-07-15 14:00 EDT** (peak GA summer heat event; internally consistent: risks rise through the morning, peak ~15:00, PV-07 alert fires 15:04 EDT). All fixture `generated_ts` values are UTC equivalents (`2024-07-15T18:00:00Z` etc.).
- Every fixture file includes `"frozen_date": "2024-07-15"` and `"schema_version": 1`.

## 4.9 Demo data contract versioning

- Add a `"schema_version": 1` field to every fixture file so `data_source.py` can fail loudly on mismatch instead of rendering garbage.
- Keep a `README.md` in `data/fixtures/` listing each file, its source endpoint, and the script that generated it.
