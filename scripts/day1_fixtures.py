#!/usr/bin/env python3
"""Day-1 fixture capture — PeachState CoolChain validation probes.

Saves the Day-1 validation probe responses (task 1.4) to
``data/fixtures/day1/`` using the live FortyGuard API through the SDK.

Generated fixtures:
    env_params_{site}.json            (fort_valley, macon, savannah, albany, vidalia)
    heatmap_{site}_tcm.json           (fort_valley, savannah)
    heatmap_corridor_strip.json       (I-16 gate strip — raw httpx, server accepts;
                                       SDK guard intentionally bypassed: >50 mi²)
    heat_intelligence_fort_valley.json (Premium PDF report)

Usage:
    export FG_API_KEY=...
    python scripts/day1_fixtures.py            # full capture (HI takes minutes)
    python scripts/day1_fixtures.py --no-hi    # skip heat_intelligence (fast)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fortyguard_sdk import (  # noqa: E402
    DateTimeWindow,
    EnvParamsRequest,
    FilterType,
    FortyGuardClient,
    HeatmapRequest,
    Plan,
    ga_threshold_c,
)

KEY = os.environ["FG_API_KEY"]
BASE = "https://api.fortyguard.com/v1"
OUT = REPO / "data" / "fixtures" / "day1"

# Five Georgia pilot sites (mirrors scripts/ga_validation.py)
SITES = {
    "fort_valley": (32.5517, -83.8871),
    "macon": (32.8407, -83.6324),
    "savannah": (32.0809, -81.0912),
    "albany": (31.5785, -84.1557),
    "vidalia": (32.2177, -82.4134),
}

DEMO_DATE = "2025-07-15"   # validated hot GA summer day (data present)
DEMO_TIME = "18:00"


def sq_poly(lat: float, lon: float, half_deg: float = 0.02) -> dict:
    """~2x2 km (~1.5 mi²) square AOI — under any plan cap."""
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


CORRIDOR_STRIP = {"type": "FeatureCollection", "features": [{
    "type": "Feature", "properties": {},
    "geometry": {"type": "Polygon", "coordinates": [[
        [-83.62, 32.70], [-82.90, 32.52], [-82.90, 32.60],
        [-83.62, 32.78], [-83.62, 32.70],
    ]]},
}]}


def _win() -> DateTimeWindow:
    return DateTimeWindow(
        start_date=date.fromisoformat(DEMO_DATE),
        start_time=DEMO_TIME,
        filter_type=FilterType.SINGLE_HOUR,
    )


def _envelope(endpoint: str, probe: dict, response: dict, **extra) -> dict:
    return {
        "schema_version": 1,
        "kind": "day1_validation",
        "endpoint": endpoint,
        "generated_ts": datetime.now(timezone.utc).isoformat(),
        "probe": probe,
        "response": response,
        **extra,
    }


async def _with_retry(coro_factory, attempts: int = 3, label: str = ""):
    """Retry a live SDK call; guards against stuck server-side activities."""
    from fortyguard_sdk import TaskTimeoutError

    last: Exception | None = None
    for i in range(attempts):
        try:
            return await coro_factory()
        except TaskTimeoutError as exc:
            last = exc
            print(f"    [{label}] attempt {i + 1} timed out ({exc}); retrying...")
    raise RuntimeError(f"{label}: all {attempts} attempts timed out") from last


def _save(name: str, payload: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"  saved {path.relative_to(REPO)} ({path.stat().st_size / 1e6:.2f} MB)")
    return path


async def capture_env_params(client: FortyGuardClient) -> None:
    print("== env_params x5 sites ==")
    for site, (lat, lon) in SITES.items():
        req = EnvParamsRequest(
            latitude=lat, longitude=lon, temperature=32.0,
            date_time=_win(),
            analysis=["heat_index_celsius", "relative_humidity_percent"],
        )
        res = await _with_retry(lambda: client.env_params(req),
                                label=f"env:{site}")
        locs = [l.model_dump() for l in res.locations]
        _save(
            f"env_params_{site}.json",
            _envelope(
                "POST /env_params",
                {"site": site, "lat": lat, "lon": lon,
                 "params": req.to_payload()},
                {"metadata": res.metadata.model_dump(), "locations": locs},
            ),
        )


async def capture_heatmaps(client: FortyGuardClient) -> None:
    print("== heatmap tcm x2 sites (typed parse proof) ==")
    for site, (lat, lon) in SITES.items():
        if site not in ("fort_valley", "savannah"):
            continue
        fc = sq_poly(lat, lon)
        res = await _with_retry(
            lambda: client.heatmap(
                HeatmapRequest(polygon_aoi=fc, date_time=_win(),
                               granularity=100, analytic_type="tcm")
            ),
            label=f"hm:{site}",
        )
        _save(
            f"heatmap_{site}_tcm.json",
            _envelope(
                "POST /heatmap",
                {"site": site, "analytic_type": "tcm", "granularity": 100,
                 "polygon_aoi": fc, "params": {
                     "date_time": _win().to_payload(), "granularity": 100,
                     "analytic_type": "tcm"}},
                {"map_data": res.map_data, "stats_data": res.stats_data.model_dump()},
            ),
        )


async def prove_exceedance_persistence(client: FortyGuardClient) -> None:
    """Live typed-parse proof for exceedance + persistence (success criterion)."""
    print("== live exceedance + persistence typed parse (Fort Valley) ==")
    lat, lon = SITES["fort_valley"]
    fc = sq_poly(lat, lon)
    for analytic in ("exceedance", "persistence"):
        res = await _with_retry(
            lambda: client.heatmap(
                HeatmapRequest(
                    polygon_aoi=fc, date_time=_win(), granularity=100,
                    analytic_type=analytic, threshold=ga_threshold_c("peach"),
                )
            ),
            label=f"hm:{analytic}",
        )
        ts = res.stats_data.temperature_stats
        a_s = res.stats_data.analytic_stats
        print(f"    {analytic}: n_cells={res.n_cells} analytic_type="
              f"{res.stats_data.analytic_type} units={res.stats_data.units} "
              f"min={res.stats_data.min} max={res.stats_data.max} "
              f"mean={res.stats_data.mean} analytic_stats={a_s.model_dump() if a_s else None}")
        assert a_s is not None and a_s.analytic_type == analytic


def capture_corridor_strip() -> None:
    """Raw gate probe — same strip as scripts/ga_validation.py (G3).

    The SDK client-side guard rejects this AOI (>50 mi² Premium cap); the
    server accepted it during gate validation, so the raw probe is recorded
    as the G3 evidence fixture.
    """
    print("== corridor strip (raw gate probe, I-16) ==")
    with httpx.Client(headers={"api-key": KEY, "Content-Type": "application/json"},
                      timeout=90.0) as c:
        r = c.post(f"{BASE}/heatmap", json={
            "polygon_aoi": CORRIDOR_STRIP,
            "date_time": {"start_date": DEMO_DATE, "start_time": DEMO_TIME,
                          "filter_type": 1},
            "granularity": 100, "analytic_type": "tcm",
        })
        r.raise_for_status()
        aid = r.json()["data"]["activity_id"]
        t0 = __import__("time").monotonic()
        while True:
            import time
            time.sleep(2.0)
            s = c.get(f"{BASE}/status/{aid}").json()
            st = str((s.get("data") or {}).get("status", "")).lower()
            if st in ("completed", "succeeded"):
                break
            if st in ("failed", "error"):
                raise RuntimeError(f"corridor strip failed: {json.dumps(s)[:300]}")
            if time.monotonic() - t0 > 240:
                raise TimeoutError("corridor strip timeout")
        result = (s.get("data") or {}).get("result", {}) or {}
        _save(
            "heatmap_corridor_strip.json",
            _envelope(
                "POST /heatmap",
                {"route": "I-16", "analytic_type": "tcm", "granularity": 100,
                 "note": "gate G3 probe; >50 mi² AOI accepted by server, "
                         "SDK client guard would reject", "polygon_aoi": CORRIDOR_STRIP},
                {"map_data": result.get("map_data", {}),
                 "stats_data": result.get("stats_data", {})},
            ),
        )


async def capture_heat_intelligence(client: FortyGuardClient) -> None:
    print("== heat_intelligence fort_valley (Premium, minutes) ==")
    from fortyguard_sdk import HeatIntelligenceRequest, FortyGuardClient as FG

    # HI generation takes minutes — dedicated client with a 25-min poll budget.
    hi_client = FG(KEY, plan=Plan.PREMIUM, poll_max_duration=1500.0)
    try:
        req = HeatIntelligenceRequest(
            latitude=SITES["fort_valley"][0], longitude=SITES["fort_valley"][1],
            temperature=32.8, date=DEMO_DATE, analysis=["environmental"],
        )
        res = await hi_client.heat_intelligence(req)
        link = res.download_link or ""
    finally:
        await hi_client.close()
    _save(
        "heat_intelligence_fort_valley.json",
        _envelope(
            "POST /heat_intelligence",
            {"site": "fort_valley", "params": req.to_payload()},
            {"activity_id": res.activity_id,
             "download_link_present": bool(link),
             "download_link_preview": (link[:60] + "...[redacted]") if link else None},
        ),
    )


async def main() -> int:
    no_hi = "--no-hi" in sys.argv
    client = FortyGuardClient(KEY, plan=Plan.PREMIUM, concurrency=5)
    try:
        await capture_env_params(client)
        await capture_heatmaps(client)
        await prove_exceedance_persistence(client)
        capture_corridor_strip()          # raw httpx (guard bypass documented)
        if not no_hi:
            await capture_heat_intelligence(client)
    finally:
        await client.close()

    print(f"\nFixtures written to {OUT.relative_to(REPO)}/")
    return 0


if __name__ == "__main__":
    if not os.environ.get("FG_API_KEY"):
        print("Set FG_API_KEY first: export FG_API_KEY=...")
        sys.exit(2)
    sys.exit(asyncio.run(main()))
