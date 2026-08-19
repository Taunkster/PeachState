#!/usr/bin/env python3
"""Day-1 Go/No-Go gate for PeachState CoolChain — Georgia API validation.

Usage:
    export FG_API_KEY=your_key
    python scripts/ga_validation.py            # run full gate
    python scripts/ga_validation.py --quick    # env_params + heatmap only

Validated 2026-08-18 on the hackathon key (GA coverage confirmed, Premium tier).
Re-run whenever the API key is refreshed or before the live demo date.
Exit code 0 = GO, 1 = NO-GO (fallback plan in docs/09_technical_risks.md §3).
"""
from __future__ import annotations

import json
import os
import sys
import time

import httpx

KEY = os.environ["FG_API_KEY"]
BASE = "https://api.fortyguard.com/v1"
H = {"api-key": KEY, "Content-Type": "application/json"}

# Five Georgia pilot sites (lat, lon)
SITES = {
    "fort_valley": (32.5517, -83.8871),  # peach capital, Peach Co.
    "macon": (32.8407, -83.6324),        # corridor origin, Bibb Co.
    "savannah": (32.0809, -81.0912),     # Port of Savannah, Chatham Co.
    "albany": (31.5785, -84.1557),       # pecan belt, Dougherty Co.
    "vidalia": (32.2177, -82.4134),      # sweet onions, Toombs Co.
}

# A known hot Georgia summer day (heatmap-verified to return data).
DEMO_DATE = "2025-07-15"


def log(*a) -> None:
    print(*a, flush=True)


def sq_poly(lat: float, lon: float, half_deg: float = 0.02) -> dict:
    """~2x2 km (~1.5 mi²) square AOI — well under any plan cap."""
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[
                [lon - half_deg, lat - half_deg],
                [lon + half_deg, lat - half_deg],
                [lon + half_deg, lat + half_deg],
                [lon - half_deg, lat + half_deg],
                [lon - half_deg, lat - half_deg],
            ]]},
        }],
    }


def poll(c: httpx.Client, aid: str, budget_s: float = 180.0, label: str = "") -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < budget_s:
        time.sleep(2.0)
        s = c.get(f"{BASE}/status/{aid}").json()
        st = str((s.get("data") or {}).get("status", "")).lower()
        if st in ("completed", "succeeded"):
            return (s.get("data") or {}).get("result", {}) or {}
        if st in ("failed", "error"):
            log(f"    [{label}] FAILED: {json.dumps(s)[:300]}")
            return {}
    log(f"    [{label}] TIMEOUT after {budget_s:.0f}s")
    return {}


def _run_env_probe(c: httpx.Client, name: str, lat: float, lon: float,
                   budget_s: float = 45.0) -> bool:
    """POST env_params and poll; returns True when parameters came back.

    The server occasionally queues an activity for >30s (observed 2026-08-18);
    a short budget produces false negatives, so the gate polls up to
    `budget_s` and retries once on a stuck activity.
    """
    t0 = time.monotonic()
    r = c.post(f"{BASE}/env_params", json={
        "latitude": lat, "longitude": lon, "temperature": 32.0,
        "date_time": {"start_date": DEMO_DATE, "start_time": "18:00",
                      "filter_type": 1},
        "analysis": ["heat_index_celsius", "relative_humidity_percent"],
    })
    ok = False
    if r.status_code == 200 and r.json().get("data", {}).get("activity_id"):
        res = poll(c, r.json()["data"]["activity_id"], budget_s, f"env:{name}")
        locs = res.get("locations") or []
        ok = bool(locs and locs[0].get("parameters"))
    log(f"    env {name:12s} HTTP {r.status_code} ok={ok} "
        f"({time.monotonic()-t0:.0f}s)")
    return ok


def check_env_params(c: httpx.Client) -> bool:
    log("== G1 env_params on Georgia sites ==")
    all_ok = True
    for name, (lat, lon) in SITES.items():
        # R-06 (2026-08-18): env_params activities intermittently get stuck in
        # "Processing" server-side (~1 in 5; heatmaps unaffected). A stuck
        # activity never completes, so each site retries with a fresh POST.
        ok = False
        for attempt in range(1, 4):
            ok = _run_env_probe(c, name, lat, lon, budget_s=45.0)
            if ok:
                break
            log(f"    env {name:12s} attempt {attempt + 1}/3 "
                f"(stuck-activity retry, R-06)...")
        all_ok &= ok
    return all_ok


def check_heatmap(c: httpx.Client) -> bool:
    log("== G2 heatmap tcm on Georgia sites ==")
    all_ok = True
    for name in ("fort_valley", "savannah"):
        lat, lon = SITES[name]
        t0 = time.monotonic()
        r = c.post(f"{BASE}/heatmap", json={
            "polygon_aoi": sq_poly(lat, lon),
            "date_time": {"start_date": DEMO_DATE, "start_time": "18:00",
                          "filter_type": 1},
            "granularity": 100, "analytic_type": "tcm",
        })
        ok = False
        if r.status_code == 200 and r.json().get("data", {}).get("activity_id"):
            res = poll(c, r.json()["data"]["activity_id"], 180, f"hm:{name}")
            n = len(((res.get("map_data") or {}).get("features")) or [])
            ok = n > 0
            log(f"    hm  {name:12s} HTTP {r.status_code} features={n} "
                f"({time.monotonic()-t0:.0f}s)")
        else:
            log(f"    hm  {name:12s} HTTP {r.status_code} {r.text[:200]}")
        all_ok &= ok
    return all_ok


def check_corridor_strip(c: httpx.Client) -> bool:
    log("== G3 corridor strip feasibility (I-16, long-thin AOI) ==")
    strip = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[
            [-83.62, 32.70], [-82.90, 32.52], [-82.90, 32.60],
            [-83.62, 32.78], [-83.62, 32.70],
        ]]},
    }]}
    t0 = time.monotonic()
    r = c.post(f"{BASE}/heatmap", json={
        "polygon_aoi": strip,
        "date_time": {"start_date": DEMO_DATE, "start_time": "18:00", "filter_type": 1},
        "granularity": 100, "analytic_type": "tcm",
    })
    ok = False
    if r.status_code == 200 and r.json().get("data", {}).get("activity_id"):
        res = poll(c, r.json()["data"]["activity_id"], 180, "hm:strip")
        n = len(((res.get("map_data") or {}).get("features")) or [])
        ok = n > 0
        log(f"    strip HTTP {r.status_code} features={n} ({time.monotonic()-t0:.0f}s)")
    else:
        log(f"    strip HTTP {r.status_code} {r.text[:300]}")
    return ok


def check_plan_tier(c: httpx.Client) -> bool:
    log("== G5 plan tier (heat_intelligence POST) ==")
    r = c.post(f"{BASE}/heat_intelligence", json={
        "latitude": SITES["fort_valley"][0], "longitude": SITES["fort_valley"][1],
        "temperature": 32.8, "date": DEMO_DATE, "analysis": ["environmental"],
    })
    premium = r.status_code == 200
    log(f"    heat_intelligence HTTP {r.status_code} -> "
        f"{'PREMIUM' if premium else 'BASIC/other'}")
    return premium


def check_freshness(c: httpx.Client) -> bool:
    """G6 current-date freshness probe (F8 data-lag risk).

    Query today's env_params at Fort Valley for the current UTC hour and
    the previous hour; PASS when at least one returns a non-null heat_index.
    Report the observed API timezone so the day-1 timezone calibration is
    re-confirmed against a live/current request.
    """
    from datetime import date, datetime, timedelta, timezone

    log("== G6 current-date freshness probe (Fort Valley) ==")
    lat, lon = SITES["fort_valley"]
    now = datetime.now(timezone.utc)
    # 12h past-current-time is the documented max; probe a bracket of recent hours.
    hours = [now - timedelta(hours=h) for h in (0, 1, 2, 4, 8)]
    ok = False
    for probe in hours:
        t0 = time.monotonic()
        r = c.post(f"{BASE}/env_params", json={
            "latitude": lat, "longitude": lon, "temperature": 30.0,
            "date_time": {"start_date": probe.date().isoformat(),
                          "start_time": f"{probe.hour:02d}:00",
                          "filter_type": 1},
            "analysis": ["heat_index_celsius"],
        })
        aid = (r.json().get("data") or {}).get("activity_id")
        res = poll(c, aid, 30, f"fresh:{probe.strftime('%m-%d %HZ')}") if aid else {}
        locs = res.get("locations") or []
        meta = res.get("metadata") or {}
        if locs:
            p = locs[0].get("parameters") or {}
            v = (p.get("heat_index_celsius") or [None])[0]
            null = v is None
            log(f"    {probe.strftime('%Y-%m-%d %H:%M')}Z HTTP {r.status_code} "
                f"heat_index={v} null={null} api_tz={meta.get('timezone')} "
                f"ts={meta.get('timestamps')} ({time.monotonic()-t0:.0f}s)")
            if not null:
                ok = True
        else:
            log(f"    {probe.strftime('%Y-%m-%d %H:%M')}Z HTTP {r.status_code} "
                f"no locations ({time.monotonic()-t0:.0f}s)")
    log(f"    freshness: {'PASS (live data within 8h)' if ok else 'WARN (data-lag > 8h)'}")
    return ok


def check_timezone(c: httpx.Client) -> None:
    """R-05 calibration probe: sweep 12-23 UTC, print heat_index to eyeball diurnal fit."""
    log("== G7 timezone calibration sweep (12-23 UTC, Fort Valley) ==")
    lat, lon = SITES["fort_valley"]
    for hh in ("12:00", "15:00", "18:00", "21:00", "23:00"):
        t0 = time.monotonic()
        r = c.post(f"{BASE}/env_params", json={
            "latitude": lat, "longitude": lon, "temperature": 30.0,
            "date_time": {"start_date": DEMO_DATE, "start_time": hh, "filter_type": 1},
            "analysis": ["heat_index_celsius", "relative_humidity_percent"],
        })
        aid = r.json().get("data", {}).get("activity_id")
        res = poll(c, aid, 30, f"tz:{hh}")
        locs = res.get("locations") or []
        meta = res.get("metadata") or {}
        if locs:
            p = locs[0].get("parameters") or {}
            log(f"    req {hh}UTC -> api_tz={meta.get('timezone')} "
                f"ts={meta.get('timestamps')} heat_index={p.get('heat_index_celsius')} "
                f"rh={p.get('relative_humidity_percent')} "
                f"ghi={(locs[0].get('solar_irradiance') or {}).get('clear_sky', {}).get('ghi')}")
        log(f"    ({time.monotonic()-t0:.0f}s)")


def main() -> int:
    quick = "--quick" in sys.argv
    results: dict[str, bool] = {}
    with httpx.Client(headers=H, timeout=90.0) as c:
        results["G1_env_params"] = check_env_params(c)
        results["G2_heatmap"] = check_heatmap(c)
        results["G3_corridor"] = check_corridor_strip(c)
        results["G5_premium"] = check_plan_tier(c)
        if not quick:
            results["G6_freshness"] = check_freshness(c)
            check_timezone(c)

    log("\n=== GATE RESULT ===")
    for k, v in results.items():
        log(f"  {k}: {'PASS' if v else 'FAIL'}")
    gate = all(results.values())
    log(f"  DAY-1 GATE: {'GO' if gate else 'NO-GO'}")
    if not gate:
        log("  Fallback: env_params-only pipeline OR fixtures-only demo "
            "(docs/09_technical_risks.md §3).")
    return 0 if gate else 1


if __name__ == "__main__":
    if not os.environ.get("FG_API_KEY"):
        log("Set FG_API_KEY first: export FG_API_KEY=...")
        sys.exit(2)
    sys.exit(main())
