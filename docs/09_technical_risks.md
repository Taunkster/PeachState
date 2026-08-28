# 09 — Technical Risks & Day-1 Empirical Findings (Georgia Edition)

> Status: LIVE-VERIFIED 2026-08-18 with the hackathon key
> (`33a55ce2...`, **Premium** confirmed). Empirically validated by
> `scripts/ga_validation.py` (exit 0 = GO) and `scripts/day1_fixtures.py`.

Risk rank = likelihood × impact (1-5). Mitigations are concrete and Day-scoped.

## Day-1 verified gate (2026-08-18)

| Gate | Probe | Result |
|------|-------|--------|
| G1 env_params | 5 GA sites (Fort Valley, Macon, Savannah, Albany, Vidalia) | PASS |
| G2 heatmap tcm | Fort Valley (1652 tiles) + Savannah (1320 tiles) | PASS |
| G3 corridor strip | I-16 long-thin AOI (59 962 tiles, ~47 s) | PASS |
| G5 plan tier | heat_intelligence POST accepted → **Premium** | PASS |
| G6 freshness | current-date env_params within 8 h, non-null | PASS |
| G7 timezone | 12–23 UTC diurnal sweep (GMT-6 label confirmed) | recorded |

`DAY-1 GATE: GO` (exit code 0).

## Risk register

### R-06 (NEW 2026-08-18) — env_params activities intermittently get STUCK server-side
- **What**: ~1-in-5 env_params POSTs return `activity_id` that stays
  `Processing` forever (confirmed: an activity still `Processing` 20+ min
  later). Retrying the *same* activity never helps; a **fresh POST** succeeds
  within 3–7 s. Heatmap activities were **never** observed stuck (all 10+
  runs completed in 20–75 s).
- **Impact**: 4/5. If unhandled, a monitoring pipeline shows spurious
  "no data" gaps and the demo can stall on an env_params panel.
- **Mitigation** (already in place):
  1. SDK `submit_and_wait`/`poll_status` raise `TaskTimeoutError` → caller
     resubmits (pattern in `scripts/day1_fixtures.py::_with_retry`, 3 attempts).
  2. Gate G1 retries each site up to 3× with fresh POSTs (verified: GO).
  3. Pipeline A should treat `TaskTimeoutError` as "resubmit once, then skip
     this cycle" (Day 3/4 hardening).
- **Action**: bake resubmit-on-timeout into `coolchain/services/` when
  building the monitoring loop.

### R-05 — Timezone reporting is WRONG for GA summer (GMT-6, should be EDT/GMT-4)
- API labels all GA timestamps `GMT-6` (winter UTC-6) even in July when
  Georgia is on EDT (UTC-4). Requested 12:00 UTC is returned as
  `2025-07-15T12:00:00-06:00`, i.e. the server treats the requested hour as
  *local wall-clock* and labels it -06:00. Diurnal fit is therefore offset
  ~2 h.
- **Impact**: 5/5 for any hour-sensitive feature (harvest windows, corridor
  departure-time comparison).
- **Mitigation**: never trust `timezone_offset_hours`. Calibrate empirically
  (G7 sweep) and define ONE display convention (e.g. "all hours are EDT").
  Day-1 sweep recorded heat_index 30.0→37.4 across 12→23 UTC with
  humidity 43→79% — use as the calibration reference.

### R-04 — env_params GHI / solar irradiance is anomalous (qualitative only)
- GHI = 925 W/m² at 12 UTC (≈07:00 EDT) and ≈0 at 23 UTC (≈18:00 EDT) on
  2025-07-15 — misaligned with a real July diurnal curve. Treat GHI as a
  qualitative proxy, not an absolute irradiance value.
- **Impact**: 3/5 (canopy heat models that weight GHI heavily).
- **Mitigation**: weight GHI ≤10% in canopy risk; lean on tcm + heat_index.

### R-03 — Plan caps are contractual, NOT server-enforced
- Server accepted a ~180×220 km AOI (>10 000 mi²), 15/60 mi² AOIs, and
  returned the full env_params set (16 params) when only 2 were requested.
- **Impact**: 2/5. Abuse risks quota burn and 60 s+ jobs.
- **Mitigation**: keep client-side guards (`validate_heatmap_area`,
  `cap_env_analysis`) — already in SDK; these are the enforcement point.

### R-02 — Heatmap latency 20–75 s; big AOIs slower
- Fort Valley/Savannah squares ~20–26 s; corridor strip ~47 s @ 60 k tiles.
- **Impact**: 3/5 for live demo pacing.
- **Mitigation**: pre-generate fixtures (Day 6); run corridor strips
  offline; use HYBRID mode (live env_params + fixture heatmaps).

### R-01 — Single-hour exceedance/persistence returns zeros
- `exceedance`/`persistence` with a single-hour window return `min/max/mean =
  0` (need a multi-hour `filter_type=2/4` window to see hours-above-threshold).
- **Impact**: 3/5 (harvest alert "6 h exceedance" story needs a window).
- **Mitigation**: request range-of-hours windows for these analytics
  (Pipeline A: tcm single-hour + exceedance/persistence over a 6–24 h range).

### R-07 — Heat Intelligence generation takes minutes
- POST accepted (Premium) and `download_link` arrives after several minutes.
- **Impact**: 2/5 demo pacing.
- **Mitigation**: pre-generate the PDF fixture (Day 6); never block the
  live dashboard on HI.

### R-08 — Data lag: current-date freshness verified OK within 8 h
- Live probe (2026-08-18): heat_index non-null at t-0,1,2,4,8 h. But very
  early hours can lag — always probe recent hours for the demo date.

### R-09 — Security: API key in plaintext
- The hackathon key is embedded in docs/TODO. **Rotate before any public
  repo.** Use `FG_API_KEY` env var + `.env` (python-dotenv) everywhere.

## §3 Fallback plans (if a live gate ever fails)
1. **env_params-only pipeline**: env_params works on all 5 sites (with
   R-06 retry); demo still shows heat_index/WBGT/humidity/GHI story.
2. **Fixtures-only demo**: `data/fixtures/day1/` + Employee 3's demo
   fixtures power the full dashboard without any live call
   (`DATA_SOURCE=fixtures`, `docs/06_fallback_plans.md`).
3. **HYBRID** (recommended default): live env_params where fresh, fixtures
   for heatmap layers and the HI PDF.