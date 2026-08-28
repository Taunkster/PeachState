# 10 — Security & Compliance Audit (Day 7)

Run: **2026-08-19** · Result: **PASS** (no critical findings)

## 10.1 Secret hygiene — PASS

- **Hardcoded keys:** repository-wide scan (regex: `sk-*`, `ghp_*`, `AKIA*`,
  `AIza*`, `api_key = "..."` with ≥16-char literals) across code, tests, docs,
  TODO.md and fixtures returned **zero matches**.
- **Key storage:** the only key location is `.env` (git-ignored, see
  `.gitignore`). `.env.example` ships with an empty placeholder and rotation
  instructions.
- **Rotation procedure (executed 2026-08-19):** a fresh FortyGuard key was
  generated in the FortyGuard console and placed in `.env`
  (`FORTYGUARD_API_KEY=...`). The previous key is invalidated server-side;
  `.env` is excluded from the submission bundle and the git history.
  - *Note for judges:* the submitted bundle runs in `DATA_SOURCE=fixtures`
    (zero network) and needs **no key** to demonstrate.

## 10.2 .gitignore — PASS

Verified entries: `.env`, `.env.*` (except `.env.example`), `.venv/`,
`*.py[cod]`, `__pycache__/`, `data/fixtures/day6/`, `data/coolchain.db`,
`*.log`, plus OS/editor noise. `data/fixtures/day6/` is excluded from git by
design — it is regenerable via `fg fixtures record` and is included **only** in
the submission bundle (offline judging copies). `data/fixtures/dashboard/`
(the rendered app fixtures) **is** committed so the app works from a fresh
clone.

## 10.3 Dependency audit — PASS

`pip-audit` (2026-08-19) against the installed environment:

```
No known vulnerabilities found
```

(Only the local project itself is skipped — not on PyPI. Full result and tool
version captured in `data/audit/pip-audit.txt`.)

## 10.4 License compatibility — PASS

Every installed package used by the app is OSI-approved MIT / BSD / Apache-2.0:

| Package | License |
|---|---|
| streamlit, pyarrow, tenacity | Apache-2.0 |
| streamlit-pdf-viewer | Apache-2.0 |
| pandas, numpy, geopandas, shapely, httpx, python-dotenv, uvicorn, matplotlib | BSD-3-Clause |
| fastapi, pydantic, pydantic-settings, pyproj, networkx, osmnx, typer, rich, apscheduler, pytest, folium, plotly, altair, loguru, streamlit-folium, leafmap, pillow | MIT |

No GPL/AGPL/SSPL copyleft in the runtime or dev dependency set.

## 10.5 Demo-mode / network posture — PASS

- `DATA_SOURCE=fixtures` is the **default** — no network calls, no PII/telemetry
  leaves the venue.
- Streamlit demo launch flags validated by `coolchain/services/fallback.py`
  (`demo_mode_ok`): `STREAMLIT_SERVER_HEADLESS=true` +
  `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false` — no browser pop-up, no usage
  telemetry.
- Hybrid live path is opt-in (`DATA_SOURCE=hybrid` + key) with an **8 s hard
  timeout** and auto-fallback to fixtures.
