# PeachState CoolChain — Demo & UX Design Document (Georgia Edition)

**Author:** Employee 3 (UX/Demo Engineer) · **Date:** 2026-08-18
**Event:** FortyGuard Hackathon'26 — "Building the World's Temperature AI"
**Format:** 5-minute live demo · Judges: NVIDIA, Autodesk Forma, climate/AI experts
**Tracks covered:** Predictive Models, AI Agents, Dashboards, Interactive Maps
**Project:** PeachState CoolChain 🍑🚛 — thermal management from field to Port of Savannah

## Tagline

> **"From Georgia field to Port of Savannah — heat never wins."**

## Design Philosophy

The demo tells a single emotional + technical arc in 5 minutes:

1. **Make it personal** — Georgia's $74B agricultural economy feeds the world (peaches, pecans, Vidalia onions, blueberries). Humid heat is the enemy of every load. Everyone in the room has eaten something that started on a Georgia farm.
2. **Make it visible** — every claim is backed by a live-looking map, route, alert, or counter on screen. No abstract bullets.
3. **Make it credible** — the FortyGuard API calls are real (async polling visible once), numbers are pre-computed and internally consistent, the Q10 spoilage model and canopy risk model are each explained in one sentence.
4. **Make it impossible to miss the API** — each scene names the endpoint(s) used, so judges score API creativity without digging.

**Golden rules for the live demo:**

- Zero loading spinners. Everything pre-cached; the *only* "live" API call is scripted and fast.
- Every scene has a **visual moment** (map shift, alert pulse, counter roll, route swap) within 10 seconds of its start.
- No terminal output on screen. If code is shown, it is a decorative code frame, not a live shell.
- The presenter's words fill ≤ 80% of each scene; the screen carries the rest.

## Document Map

| File | Contents |
|------|----------|
| `01_demo_script.md` | 5-minute scene-by-scene script with narration, visuals, exact interactions, timings |
| `02_dashboard_components.md` | Streamlit component specs + JSON data contracts (Field Map, Corridor Map, Risk Charts, KPIs, Alert Panel) |
| `03_design_system.md` | Colors (GA flag + peach + heat gradient), typography, maps, motion, ASCII mockups |
| `04_demo_data_strategy.md` | Fixture store, synthetic GA geography (Fort Valley/Albany/Bacon/Vidalia), OSM corridors, determinism |
| `05_judging_alignment.md` | Criterion-by-criterion proof map + endpoint cheat sheet |
| `06_fallback_plans.md` | Risk matrix, degraded modes, contingency lines, runbook |
| `07_qa_prep.md` | Anticipated judge questions + prepared answers |
| `08_presenter_one_sheet.md` | 1-page cheat sheet for demo day |

## Supporting Data Artifacts (in `/home/taha/peachstate-coolchain/data/`)

- `data/crop_thresholds.json` — crop-specific canopy heat thresholds (°F) + risk weights + Q10 spoilage params for GA crops
- `data/fixtures/` — directory layout + schema for pre-recorded API responses (see `04_demo_data_strategy.md`)
