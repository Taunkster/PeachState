"""PeachState CoolChain CLI - runtime context (live vs fixture mode).

Live mode is used when ``FG_API_KEY`` is set; otherwise an offline
``FixtureBackend`` serves canned SDK responses recorded in
``data/fixtures/day1`` so every ``fg`` command works end-to-end without
network access (success criterion: "live + fixture modes").

The SQLite path is overridable with the ``COOLCHAIN_DB`` environment
variable (tests point this at a temp file).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fortyguard_sdk import (
    DateTimeWindow,
    EnvParamsRequest,
    EnvParamsResult,
    FilterType,
    FortyGuardClient,
    HeatmapRequest,
    HeatmapResult,
    Plan,
    TTLCache,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "data" / "fixtures" / "day1"
HI_PDF_FIXTURE = ROOT / "data" / "fixtures" / "heat_intelligence_fort_valley.pdf"

FIXTURE_SITES: dict[str, tuple[float, float]] = {
    "fort_valley": (32.5517, -83.8871),
    "macon": (32.8407, -83.6324),
    "savannah": (32.0809, -81.0912),
    "albany": (31.5785, -84.1557),
    "vidalia": (32.2177, -82.4134),
}

DEMO_DATE = "2025-07-15"
DEMO_TIME = "18:00"


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    import math

    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[1], a[0], b[1], b[0]])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def nearest_fixture_site(lat: float, lon: float) -> str:
    best, best_d = "fort_valley", float("inf")
    for name, (slat, slon) in FIXTURE_SITES.items():
        d = _haversine_km((lon, lat), (slon, slat))
        if d < best_d:
            best, best_d = name, d
    return best


def _load_fixture(name: str) -> dict[str, Any]:
    p = FIXTURES_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"fixture missing: {p} (run `fg fixtures record`)")
    return json.loads(p.read_text())


class FixtureBackend:
    """Offline duck-typed client serving canned SDK responses."""

    def __init__(self) -> None:
        self.plan = Plan.BASIC
        self.live = False
        self._last_heatmap_temp_c: float | None = None

    @property
    def last_heatmap_temp_c(self) -> float | None:
        return self._last_heatmap_temp_c

    async def heatmap(self, req: HeatmapRequest) -> HeatmapResult:
        site = nearest_fixture_site(*_fc_center(req.polygon_aoi))
        if req.analytic_type == "tcm":
            fixture = _load_fixture(f"heatmap_{site}_tcm.json")
            res = HeatmapResult.from_result(fixture["response"])
        else:
            # synthesize exceedance/persistence from the tcm fixture
            fixture = _load_fixture(f"heatmap_{site}_tcm.json")
            base = HeatmapResult.from_result(fixture["response"])
            res = _synthesize_analytic(base, req.analytic_type, req.threshold)
        ts = res.stats_data.temperature_stats
        if ts is not None and ts.mean is not None:
            self._last_heatmap_temp_c = float(ts.mean)
        return res

    async def env_params(
        self, req: EnvParamsRequest, temperature_c: float | None = None
    ) -> EnvParamsResult:
        site = nearest_fixture_site(req.latitude, req.longitude)
        fixture = _load_fixture(f"env_params_{site}.json")
        return EnvParamsResult.from_result(fixture["response"])

    async def heat_intelligence(self, req, **kwargs: Any):
        from fortyguard_sdk import HeatIntelligenceDigest

        return HeatIntelligenceDigest.build(
            f"digest-{req.latitude:.3f}-{req.longitude:.3f}",
            req,
            temperature_c=req.temperature,
        )

    async def download_report(self, download_link: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if HI_PDF_FIXTURE.exists():
            dest.write_bytes(HI_PDF_FIXTURE.read_bytes())
        else:
            dest.write_bytes(b"%PDF-1.4 fake heat intelligence\n")
        return dest

    async def health_check(self) -> bool:
        return True

    async def close(self) -> None:
        pass


def _fc_center(aoi: Any) -> tuple[float, float]:
    """Approximate (lat, lon) center of a polygon_aoi (dict or model)."""
    coords: list[tuple[float, float]] = []
    if hasattr(aoi, "features"):
        aoi = aoi.to_dict()
    for feat in aoi.get("features", []):
        _walk_coords(feat.get("geometry", {}), coords)
    if not coords:
        return (32.5538, -83.8874)
    return (sum(c[1] for c in coords) / len(coords),
            sum(c[0] for c in coords) / len(coords))


def _walk_coords(geom: dict[str, Any], out: list[tuple[float, float]]) -> None:
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "Polygon":
        for ring in c:
            for pt in ring:
                out.append((pt[0], pt[1]))
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                for pt in ring:
                    out.append((pt[0], pt[1]))


def _synthesize_analytic(
    base: HeatmapResult, analytic: str, threshold_c: float | None
) -> HeatmapResult:
    """exceedance/persistence tiles from the tcm fixture (hours above 95F)."""
    thr_c = threshold_c if threshold_c is not None else 35.0
    features = []
    for tile in base.tiles:
        t = tile.average_temperature
        value = round(max(0.0, (t - thr_c)), 2) if t is not None else 0.0
        if analytic == "persistence":
            value = round(min(6.0, value), 2)
        features.append(
            {
                "type": "Feature",
                "id": str(tile.tile_id),
                "properties": {"tile_id": tile.tile_id, "value": value},
                "geometry": tile.geometry,
            }
        )
    return HeatmapResult.from_result(
        {
            "map_data": {"type": "FeatureCollection", "features": features},
            "stats_data": {
                "analytic_type": analytic,
                "units": "hour",
                "n_cells": len(features),
            },
        }
    )


@dataclass
class CliContext:
    client: Any
    cache: TTLCache
    db_path: Path
    live: bool
    settings: Any = None

    def close(self) -> None:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(self.client.close())
            except Exception:  # noqa: BLE001
                pass


def _default_db_path() -> Path:
    env = os.environ.get("COOLCHAIN_DB")
    if env:
        return Path(env)
    return ROOT / "data" / "coolchain.db"


def build_context(*, api_key: str | None = None) -> CliContext:
    """Live client when ``FG_API_KEY`` is present, else FixtureBackend."""
    from coolchain.config import Settings
    from coolchain.services.persistence import Persistence

    settings = Settings()
    key = api_key if api_key is not None else os.environ.get("FG_API_KEY", "")
    cache = TTLCache()

    if key:
        client = FortyGuardClient(
            key,
            plan=settings.fortyguard_plan,
            concurrency=5,
            cache=cache,
        )
        live = True
    else:
        client = FixtureBackend()
        live = False

    db_path = _default_db_path()
    return CliContext(
        client=client,
        cache=cache,
        db_path=db_path,
        live=live,
        settings=settings,
    )


def open_persistence(db_path: Path | None = None):
    from coolchain.services.persistence import Persistence

    return Persistence(db_path or _default_db_path())


__all__ = [
    "build_context",
    "open_persistence",
    "CliContext",
    "FixtureBackend",
    "FIXTURES_DIR",
    "DEMO_DATE",
    "DEMO_TIME",
    "nearest_fixture_site",
]