# 🍑 PeachState CoolChain

**FortyGuard Hackathon'26 — "Building the World's Temperature AI"**
**Georgia agricultural thermal management: field → truck → Port of Savannah.**
**Demo day: 2026-08-19 (Day 7 — submission complete).**

---

## The Problem

Georgia grows **$780M** of peaches, pecans, blueberries, and Vidalia onions.
In July, humid heat (heat index 112°F at Fort Valley on the demo date) rots
that crop in three places no one was watching at field scale:

1. **In the field** — harvests run too late; fruit sits through the heat spike.
2. **In transit** — the obvious route (I-75 inland) is also the hot route.
3. **At the Port** — loads arrive degraded and get rejected or reworked.

## The Solution

PeachState CoolChain fuses the **FortyGuard Temperature API** (hyperlocal 2m
air temp + humidity + heat index + heat-intelligence PDFs) into a decision
pipeline that turns temperature into actions:

- **Canopy heat risk (0–100)** per crop, per field — GHI-loaded, VPD-capped,
  calibrated to UGA Extension thresholds (peach/pecan 95°F, blueberry 90°F,
  onion 85°F).
- **Harvest timing** — "HARVEST NOW" SMS to the foreman when a field crosses
  its threshold with persist-forecast, with packing-house pre-cool coordination.
- **Cool corridor routing** — I-16 (176 mi, 91.3°F) vs I-75 (318 mi, 97.1°F):
  Q10 kinetics turn six degrees + 142 fewer miles into **−54% spoilage risk**.
- **Cold-chain KPIs** — **23% spoilage ↓ · $180K season savings · 12% fuel ↓ ·
  96% Port on-time**, plus a buyer-grade heat-intelligence PDF.

## Architecture

```
FortyGuard API ──► fortyguard_sdk (async client, plan gates, polling)
                        │
                        ▼
              coolchain/ (services + domain)
   heatmap ──► canopy_risk ──► harvest_timing ──► SMS alert
   corridor heatmap ──► routing (Q10 spoilage)  ──► reefer recommendation
   env_params ──► heat index / humidity / GHI     ──► KPI dashboard
   heat_intelligence ──► PDF report (Premium)
                        │
                        ▼
       SQLite + JSON fixtures (recorded live API output, Day 6)
                        │
                        ▼
          Streamlit dashboard (6 tabs)  ·  FastAPI control plane (`fg serve`)
```

**Fallback by design:** `DATA_SOURCE=fixtures|live|hybrid` (default
`fixtures`). The demo runs offline on byte-identical recorded API payloads;
hybrid mode tries live with an **8 s timeout** and auto-falls back. `GET /health`
reports `{status, data_source, last_live_ok, cache_age_s}`.

**Domain modules:** `canopy_risk.py` (0–100 risk), `harvest_timing.py`
(GDD + persist), `routing.py` (min-heat path), `spoilage.py` (Q10 degree-hours,
USDA H66 kinetics). All unit-tested with exact-value pins.

## Demo Video

- **Final rehearsal (300 s, Loom-ready):** `data/rehearsal/day7_final_demo.mp4`
  — full 5-minute demo, offline-safe, judge-ready.
- Scene-by-scene backup cards: `data/rehearsal/frames/`.
- Automated rehearsal log with per-scene timings: `data/rehearsal/rehearsal_log.json`.

## Team

- **Employee 1** — Domain logic: canopy risk, harvest timing, Q10 spoilage,
  corridor routing (Days 1–3)
- **Employee 2** — API integration, services, CLI, monitor orchestrator,
  alerting, reporting (Days 1–4)
- **Employee 3** — Streamlit dashboard, fixtures, rehearsals (Days 5–6)
- **Employee 4** — Day 7: polish, fallback modes, Q&A prep, security sweep,
  submission bundle

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install streamlit-folium streamlit-pdf-viewer   # dashboard extras

# Offline demo (recommended — no key needed):
DATA_SOURCE=fixtures \
STREAMLIT_SERVER_HEADLESS=true \
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
streamlit run dashboard/app.py

# Control plane (monitor + reports):
fg serve

# CLI (heatmap, env-params, corridor, risk, harvest, spoilage, hi-report,
# fixtures record, db, serve):
fg --help
```

Live mode requires a key in `.env` (`FORTYGUARD_API_KEY=...`) and
`DATA_SOURCE=live|hybrid`. Tests:

```bash
python -m pytest tests/ -v      # 179 passed, 4 skipped (live-API gated)
```

## Key Numbers (memorized by the presenter)

$780M GA crop value · thresholds peach/pecan 95 · blueberry 90 · onion 85 °F ·
PV-07 98°F · 3.4h exceedance · risk 91@15:00 · I-75 318 mi @97.1°F vs
I-16 176 mi @91.3°F · spoilage −54% load / −23% season · $180K saved ·
12% fuel · 96% Port on-time · 45 fields · 5 regions.

## Docs

- `docs/01_demo_script.md` — 5-minute script with timing budgets
- `docs/03_design_system.md` — Georgia flag palette + motion + typography
- `docs/06_fallback_plans.md` — degraded-mode matrix + rehearsal evidence
- `docs/07_qa_prep.md` — 19 anticipated judge questions with answers
- `docs/08_presenter_one_sheet.md` — printable presenter cheat sheet
- `docs/09_technical_risks.md` — honest risk register
- `docs/10_security_audit.md` — Day-7 security/compliance audit
- `API_INTEGRATION_DESIGN.md` — full SDK/API integration design
