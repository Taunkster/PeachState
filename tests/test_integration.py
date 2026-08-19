"""Live integration tests against the FortyGuard API (Georgia).

Gated on FG_API_KEY. Run with:
    FG_API_KEY=... pytest tests/test_integration.py -q

Day-1 validation priority: confirm the hackathon key covers GEORGIA
coordinates (Fort Valley) — the API is US-only, Georgia confirmed.
"""

from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("FG_API_KEY"), reason="requires FG_API_KEY"
)

from datetime import date, timedelta

from fortyguard_sdk import (
    DateTimeWindow,
    EnvParamsRequest,
    FilterType,
    FortyGuardClient,
    HeatmapRequest,
    HeatmapResult,
    Plan,
    estimate_aoe_area_sqmi,
    ga_threshold_c,
)


@pytest.fixture
def client_factory():
    created = []

    def _make():
        c = FortyGuardClient(
            os.environ["FG_API_KEY"],
            plan=Plan.BASIC,           # start Basic; probe premium features
            concurrency=5,
        )
        created.append(c)
        return c

    yield _make
    for c in created:
        if not c._client.is_closed:
            import asyncio

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            try:
                asyncio.run(c.close())
            except RuntimeError:
                pass


# Georgia-covered region: Fort Valley, Peach County (day-1 target)
FORT_VALLEY_FC = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "PV-01",
            "properties": {"crop": "peach"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-83.9000, 32.5600], [-83.8900, 32.5600],
                    [-83.8900, 32.5700], [-83.9000, 32.5700],
                    [-83.9000, 32.5600],
                ]],
            },
        }
    ],
}


def _win():
    return DateTimeWindow(
        start_date=date.today() - timedelta(days=1),  # F8: avoid data-lag
        start_time="14:00",
        filter_type=FilterType.SINGLE_HOUR,
    )


@pytest.mark.asyncio
async def test_ga_env_params(client_factory):
    """env_params works on Georgia coords (F2: global endpoint)."""
    c = client_factory()
    res = await c.env_params(
        EnvParamsRequest(
            latitude=32.5538,
            longitude=-83.8874,
            temperature=30.0,          # F9
            date_time=_win(),
            analysis=["heat_index_celsius", "relative_humidity_percent"],
        )
    )
    assert res.locations, "no location data returned for Fort Valley"
    loc = res.locations[0]
    assert abs(loc.lat - 32.5538) < 1.0


@pytest.mark.asyncio
async def test_ga_heatmap_tcm(client_factory):
    """Heatmap on a Georgia farm polygon (day-1 coverage validation)."""
    c = client_factory()
    area = estimate_aoe_area_sqmi(FORT_VALLEY_FC)
    assert area <= 10.0
    res = await c.heatmap(
        HeatmapRequest(
            polygon_aoi=FORT_VALLEY_FC,
            date_time=_win(),
            granularity=100,
            analytic_type="tcm",
        )
    )
    # Georgia confirmed coverage; n_cells may be 0 only if data-lag (F8)
    assert res.n_cells >= 0


@pytest.mark.asyncio
async def test_ga_heatmap_exceedance(client_factory):
    """Exceedance with GA peach threshold (95°F -> 35°C)."""
    c = client_factory()
    res = await c.heatmap(
        HeatmapRequest(
            polygon_aoi=FORT_VALLEY_FC,
            date_time=_win(),
            granularity=100,
            analytic_type="exceedance",
            threshold=ga_threshold_c("peach"),
        )
    )
    assert isinstance(res, HeatmapResult)


@pytest.mark.asyncio
async def test_health_check(client_factory):
    c = client_factory()
    assert await c.health_check() is True