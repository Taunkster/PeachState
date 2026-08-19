"""End-to-end pipeline smoke test (mocked FortyGuard client).

Validates the full integration design: Pipeline A (field monitoring),
Pipeline B (harvest timing), Pipeline C (corridor comparison), and
Pipeline D (heat intelligence) all work through the shared client +
cache + limiter without touching the live API.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

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
from coolchain.services.clustering import GAFieldClusterer
from coolchain.services.orchestrator import PipelineRunner
from coolchain.services.pipeline_a import PipelineA
from coolchain.services.pipeline_c import CorridorComparison
from coolchain.services.pipeline_d import PipelineD


def _win():
    return DateTimeWindow(
        start_date=date.today() - timedelta(days=1),
        start_time="14:00",
        filter_type=FilterType.SINGLE_HOUR,
    )


def _fake_heatmap_result(analytic: str, n_tiles: int = 2) -> dict:
    features = []
    for i in range(n_tiles):
        props = {"tile_id": i, "value": 3.5} if analytic != "tcm" else {
            "tile_id": i, "average_temperature": 36.0 + i,
            "min_temperature": 35.0, "max_temperature": 38.0,
        }
        features.append({
            "type": "Feature",
            "id": str(i),
            "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [[
                [-83.90 + i * 0.005, 32.56], [-83.89 + i * 0.005, 32.56],
                [-83.89 + i * 0.005, 32.57], [-83.90 + i * 0.005, 32.57],
                [-83.90 + i * 0.005, 32.56],
            ]]},
        })
    return {
        "map_data": {"type": "FeatureCollection", "features": features},
        "stats_data": {
            "analytic_type": analytic,
            "units": "hour" if analytic != "tcm" else None,
            "n_cells": n_tiles,
            **({"temperature_stats": {"mean": 36.5}} if analytic == "tcm" else {}),
        },
    }


class FakeClient:
    """Duck-typed FortyGuardClient that returns canned responses."""

    def __init__(self, plan: Plan = Plan.BASIC):
        self.plan = plan
        self.heatmap_calls: list[str] = []
        self.env_calls: list[list[str]] = []
        self.hi_calls: list[str] = []

    async def heatmap(self, req: HeatmapRequest) -> HeatmapResult:
        self.heatmap_calls.append(req.analytic_type)
        return HeatmapResult.from_result(_fake_heatmap_result(req.analytic_type))

    async def env_params(self, req: EnvParamsRequest) -> EnvParamsResult:
        self.env_calls.append(req.analysis or ["all"])
        loc = {
            "lat": req.latitude, "lon": req.longitude,
            "temperature": req.temperature, "elevation": 150.0,
            "parameters": {
                "heat_index_celsius": [40.0, 41.0],
                "wet_bulb_temperature_celsius": [27.0, 28.0],
                "relative_humidity_percent": [65.0, 66.0],
            },
            "solar_irradiance": {"clear_sky": {"ghi": 820.0, "dni": 700.0, "dhi": 180.0},
                                 "description": "clear"},
        }
        return EnvParamsResult.from_result(
            {"metadata": {"timezone": "America/New_York", "timestamps": ["t0", "t1"]},
             "locations": [loc]}
        )

    async def heat_intelligence(self, req):
        self.hi_calls.append(str(req.latitude))
        from fortyguard_sdk import HeatIntelligenceResult

        return HeatIntelligenceResult(activity_id="hi-1", download_link="http://x/report.pdf")

    async def download_report(self, link, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 fake")
        return dest

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_pipeline_a_monitoring_cycle():
    client = FakeClient(Plan.BASIC)
    cache = TTLCache()
    pa = PipelineA(client, cache)

    fields = json.loads(Path("data/ga_fields.geojson").read_text())
    clusterer = GAFieldClusterer(fields["features"])
    clusters = clusterer.all_clusters(plan_area_sqmi=10.0)

    results = await pa.cycle(clusters)
    assert results, "expected at least one risk result"
    assert all(0 <= r.score <= 100 for r in results)

    # Basic: tcm + exceedance + persistence per cluster, env in 2 batches
    assert "tcm" in client.heatmap_calls
    assert "exceedance" in client.heatmap_calls
    assert "persistence" in client.heatmap_calls
    assert any(len(b) == 3 for b in client.env_calls)  # Basic split: 3+1


@pytest.mark.asyncio
async def test_pipeline_a_premium_single_env_call():
    client = FakeClient(Plan.PREMIUM)
    cache = TTLCache()
    pa = PipelineA(client, cache)

    fields = json.loads(Path("data/ga_fields.geojson").read_text())
    clusterer = GAFieldClusterer(fields["features"])
    clusters = clusterer.all_clusters(plan_area_sqmi=50.0)

    await pa.cycle(clusters)
    # Premium: single env request with all 4 params
    assert any(len(b) == 4 for b in client.env_calls)


@pytest.mark.asyncio
async def test_pipeline_b_harvest_alert():
    client = FakeClient()
    cache = TTLCache()
    # prime cache with a high-risk score + GDD
    await cache.set("risk:PV-01", 90.0, 60)
    await cache.set("persistence:PV-01", 5.0, 60)
    await cache.set("gdd:PV-01:2026", 2400.0, 60)

    from coolchain.services.pipeline_b import HarvestConfig, PipelineB

    pb = PipelineB(client, cache, HarvestConfig())
    decisions = await pb.cycle([{"id": "PV-01", "crop": "peach", "cluster_id": "fv"}])
    assert decisions, "expected Harvest Now alert for high-risk primed field"


@pytest.mark.asyncio
async def test_pipeline_c_corridor_comparison():
    client = FakeClient(Plan.BASIC)
    cache = TTLCache()
    from coolchain.services.pipeline_c import PipelineCService

    pc = PipelineCService(client, cache)
    cmp = await pc.compare_routes(_win())
    assert isinstance(cmp, CorridorComparison)
    assert cmp.inland["segments_used"] > 0
    assert cmp.coastal["segments_used"] > 0
    assert cmp.cooler_route() in ("I-75 (inland)", "I-16 (coastal)")


@pytest.mark.asyncio
async def test_pipeline_d_reports_premium(tmp_path):
    client = FakeClient(Plan.PREMIUM)
    from coolchain.services.pipeline_d import ReportConfig

    pd = PipelineD(client, TTLCache(), ReportConfig(output_dir=tmp_path))
    paths = await pd.generate_for_locations(
        [{"id": "fort_valley_pack", "latitude": 32.5538, "longitude": -83.8874}],
        "2026-07-15",
    )
    assert len(paths) == 1
    assert paths[0].read_bytes().startswith(b"%PDF")


@pytest.mark.asyncio
async def test_pipeline_d_degrades_on_basic(tmp_path):
    client = FakeClient(Plan.BASIC)
    from coolchain.services.pipeline_d import ReportConfig

    pd = PipelineD(client, TTLCache(), ReportConfig(output_dir=tmp_path))
    paths = await pd.generate_for_locations(
        [{"id": "fort_valley_pack", "latitude": 32.5538, "longitude": -83.8874}],
        "2026-07-15",
    )
    assert len(paths) == 1
    assert "digests" in str(paths[0])  # degraded JSON digest, not PDF


@pytest.mark.asyncio
async def test_orchestrator_concurrent_runner(tmp_path):
    client = FakeClient(Plan.BASIC)
    cache = TTLCache()
    runner = PipelineRunner(client, cache)

    fields = json.loads(Path("data/ga_fields.geojson").read_text())
    clusterer = GAFieldClusterer(fields["features"])
    clusters = clusterer.all_clusters(plan_area_sqmi=10.0)

    # start Pipeline A + run C + D concurrently
    task = runner.start_pipeline_a(clusters)
    cmp = await runner.run_corridor_comparison(_win())
    reports = await runner.run_reports("2026-07-15")
    await runner.stop()

    assert cmp.coastal["segments_used"] >= 1
    assert len(reports) >= 1