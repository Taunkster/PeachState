"""SDK smoke tests — models, plan gating, GA guard, limiter, poller.

Mocked at the SDK boundary: no live API calls (integration tests live in
tests/test_integration.py, gated on FG_API_KEY).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from pydantic import ValidationError

from fortyguard_sdk import (
    DateTimeWindow,
    FilterType,
    FortyGuardClient,
    GeorgiaBoundaryError,
    HeatmapRequest,
    HeatmapResult,
    Plan,
    TaskFailedError,
    TaskPoller,
    TTLCache,
    estimate_aoe_area_sqmi,
    FeatureNotAvailableError,
    assert_in_georgia,
    split_env_requests,
    ga_threshold_c,
)
from fortyguard_sdk.rate_limit import AsyncRateLimiter


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def test_datetime_window_validation():
    with pytest.raises(ValidationError):
        DateTimeWindow(start_date=date(2026, 7, 15), filter_type=FilterType.SINGLE_HOUR)
    w = DateTimeWindow(
        start_date=date(2026, 7, 15),
        start_time="14:00",
        filter_type=FilterType.SINGLE_HOUR,
    )
    assert w.to_payload()["filter_type"] == 1


def test_heatmap_request_payload():
    fc = {"type": "FeatureCollection", "features": []}
    req = HeatmapRequest(
        polygon_aoi=fc,
        date_time=DateTimeWindow(
            start_date=date(2026, 7, 15), start_time="14:00",
            filter_type=FilterType.SINGLE_HOUR,
        ),
        analytic_type="exceedance",
        threshold=ga_threshold_c("peach"),  # 95°F -> 35.0°C
    )
    p = req.to_payload()
    assert p["analytic_type"] == "exceedance"
    assert abs(p["threshold"] - 35.0) < 0.1
    assert "direction" not in p


def test_heatmap_result_from_live_shape():
    """Shape copied from live probe (tcm response)."""
    result = {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "0",
                    "type": "Feature",
                    "properties": {
                        "tile_id": 0,
                        "average_temperature": 33.4,
                        "min_temperature": 33.4,
                        "max_temperature": 33.4,
                    },
                    "geometry": {"type": "Polygon", "coordinates": [[]]},
                }
            ],
        },
        "stats_data": {
            "temperature_stats": {
                "minimum": 33.1, "maximum": 34.2,
                "mean": 33.6, "standard_deviation": 0.3,
            }
        },
    }
    hr = HeatmapResult.from_result(result)
    assert hr.n_cells == 1
    assert hr.tiles[0].average_temperature == 33.4
    assert hr.stats_data.temperature_stats["mean"] == 33.6


def test_area_estimate():
    # ~1 km x 1 km at 32.5N (Fort Valley)
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-83.90, 32.56], [-83.89, 32.56],
                    [-83.89, 32.57], [-83.90, 32.57],
                    [-83.90, 32.56],
                ]],
            },
        }],
    }
    area = estimate_aoe_area_sqmi(fc)
    assert 0.3 < area < 2.0  # under Basic 10 mi²


# ---------------------------------------------------------------------------
# Plan gating & env param splitting
# ---------------------------------------------------------------------------
def test_plan_gating_basic():
    with pytest.raises(FeatureNotAvailableError):
        from fortyguard_sdk.plans import require

        require("satellite", Plan.BASIC)
    require("heatmap", Plan.BASIC)  # no error


def test_env_param_split_basic_vs_premium():
    wanted = ["heat_index_celsius", "wet_bulb_temperature_celsius",
              "relative_humidity_percent", "solar_irradiance"]
    basic = split_env_requests(wanted, Plan.BASIC)
    assert len(basic) == 2          # 3 + 1
    assert len(basic[0]) == 3
    premium = split_env_requests(wanted, Plan.PREMIUM)
    assert len(premium) == 1        # all in one
    assert len(premium[0]) == 4


# ---------------------------------------------------------------------------
# Georgia guard
# ---------------------------------------------------------------------------
def test_georgia_guard():
    assert_in_georgia(32.5538, -83.8874)  # Fort Valley OK
    with pytest.raises(GeorgiaBoundaryError):
        assert_in_georgia(24.4539, 54.3773)  # Abu Dhabi -> rejected
    with pytest.raises(GeorgiaBoundaryError):
        assert_in_georgia(33.7, -118.2)      # LA -> rejected (US but not GA)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
async def test_rate_limiter_concurrency():
    lim = AsyncRateLimiter(max_concurrent=2, max_per_window=10)
    active = 0
    peak = 0

    async def work():
        nonlocal active, peak
        await lim.acquire()
        try:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
        finally:
            lim.release()

    await asyncio.gather(*(work() for _ in range(8)))
    assert peak <= 2


# ---------------------------------------------------------------------------
# Poller
# ---------------------------------------------------------------------------
async def test_poller_completed():
    async def get_status(aid: str) -> dict:
        return {"data": {"status": "Completed", "result": {"ok": 1}}}

    p = TaskPoller(get_status, min_interval=0.01, max_interval=0.05)
    res = await p.wait_for("abc")
    assert res.status == "Completed"
    assert res.result == {"ok": 1}


async def test_poller_failed():
    async def get_status(aid: str) -> dict:
        return {"data": {"status": "Failed"}}

    p = TaskPoller(get_status, min_interval=0.01, max_interval=0.05)
    with pytest.raises(TaskFailedError):
        await p.wait_for("abc")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
async def test_cache_ttl_and_single_flight():
    cache = TTLCache()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "value"

    a = await cache.get_or_fetch("k", 60, fetch)
    b = await cache.get_or_fetch("k", 60, fetch)
    assert a == b == "value"
    assert calls == 1  # single-flight


# ---------------------------------------------------------------------------
# Day-1 additions: DateTimeFilter alias, PolygonAOI, typed stats, guards
# ---------------------------------------------------------------------------
def test_datetime_filter_alias():
    from fortyguard_sdk import DateTimeFilter

    w = DateTimeFilter(
        start_date=date(2025, 7, 15), start_time="18:00",
        filter_type=FilterType.SINGLE_HOUR,
    )
    assert w.to_payload()["filter_type"] == 1
    with pytest.raises(ValidationError):
        DateTimeFilter(start_date=date(2025, 7, 15), filter_type=FilterType.SINGLE_HOUR)


def test_polygon_aoi_validation():
    from pydantic import ValidationError

    from fortyguard_sdk import PolygonAOI

    ok = PolygonAOI(
        type="FeatureCollection",
        features=[{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-83.90, 32.56], [-83.89, 32.56], [-83.89, 32.57],
                [-83.90, 32.57], [-83.90, 32.56],
            ]]},
        }],
    )
    assert ok.centroid[0] == pytest.approx(32.564, abs=0.001)
    assert ok.centroid[1] == pytest.approx(-83.896, abs=0.001)
    assert estimate_aoe_area_sqmi(ok.to_dict()) > 0.3

    with pytest.raises(ValidationError):
        PolygonAOI(
            type="FeatureCollection",
            features=[{"type": "Feature", "geometry": {"type": "Point",
                                                        "coordinates": [0, 0]}}],
        )
    with pytest.raises(ValidationError):
        PolygonAOI(type="FeatureCollection", features=[])


def test_area_guard_plan_limits_with_polygon():
    from fortyguard_sdk import PolygonAOI, validate_heatmap_area

    # ~140 x 200 km polygon at GA latitude -> ~10,800 mi² (well over Premium)
    big = PolygonAOI(
        type="FeatureCollection",
        features=[{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-84.5, 31.5], [-82.0, 31.5], [-82.0, 33.5],
                [-84.5, 33.5], [-84.5, 31.5],
            ]]},
        }],
    )
    with pytest.raises(ValueError):
        validate_heatmap_area(big, Plan.PREMIUM)   # >50 mi²
    with pytest.raises(ValueError):
        validate_heatmap_area(big, Plan.BASIC)     # >10 mi²
    small = PolygonAOI(type="FeatureCollection", features=[{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[
            [-83.90, 32.56], [-83.89, 32.56], [-83.89, 32.57],
            [-83.90, 32.57], [-83.90, 32.56],
        ]]},
    }])
    validate_heatmap_area(small, Plan.BASIC)       # no raise
    validate_heatmap_area(small, Plan.PREMIUM)     # no raise


def test_estimate_area_mi2_accepts_dict_and_model():
    from fortyguard_sdk import estimate_area_mi2

    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-83.90, 32.56], [-83.89, 32.56], [-83.89, 32.57],
                [-83.90, 32.57], [-83.90, 32.56],
            ]]},
        }],
    }
    assert estimate_area_mi2(fc) == pytest.approx(estimate_aoe_area_sqmi(fc))


def test_typed_stats_tcm_and_analytic():
    from fortyguard_sdk import AnalyticStats, HeatmapResult, TemperatureStats

    tcm = HeatmapResult.from_result({
        "map_data": {"type": "FeatureCollection", "features": []},
        "stats_data": {"temperature_stats": {
            "minimum": 33.1, "maximum": 34.2, "mean": 33.6,
            "standard_deviation": 0.3,
            "overall_temperature_distribution": [33.1, 33.6, 34.2],
        }},
    })
    ts = tcm.stats_data.temperature_stats
    assert isinstance(ts, TemperatureStats)
    assert ts.mean == 33.6 and ts["mean"] == 33.6      # dict-style access
    assert ts.overall_temperature_distribution == [33.1, 33.6, 34.2]

    exc = HeatmapResult.from_result({
        "activity_id": "act-9",
        "map_data": {"type": "FeatureCollection", "features": []},
        "stats_data": {"analytic_type": "exceedance", "units": "hour",
                       "n_cells": 4, "min": 1.0, "max": 6.0, "mean": 3.5},
    })
    a = exc.stats_data.analytic_stats
    assert isinstance(a, AnalyticStats)
    assert a.analytic_type == "exceedance" and a.units == "hour"
    assert a.activity_id == "act-9" and a.mean == 3.5


# ---------------------------------------------------------------------------
# Day-1 additions: error mapping + client submit/poll surface
# ---------------------------------------------------------------------------
def _mock_client(handler, plan=Plan.BASIC):
    import httpx

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        transport=transport,
        headers={"api-key": "k", "Content-Type": "application/json"},
    )
    return FortyGuardClient("k", plan=plan, http_client=http, cache=TTLCache())


def _status_handler(body: dict, status_code: int = 200):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if "/status/" in request.url.path:
            return httpx.Response(200, json={"data": {"status": "Completed",
                                                      "result": body}})
        return httpx.Response(200, json={"data": {"activity_id": "aid-1"}})

    return handler


async def test_client_submit_and_wait():
    from fortyguard_sdk import AuthError, InvalidApiKeyError, RateLimitError, ServerError

    c = _mock_client(_status_handler({"locations": []}))
    try:
        res = await c.submit_and_wait("env_params", {
            "latitude": 32.55, "longitude": -83.88, "temperature": 30.0,
            "date_time": {"start_date": "2025-07-15", "start_time": "18:00",
                          "filter_type": 1},
            "analysis": ["heat_index_celsius"],
        })
        assert res == {"locations": []}
    finally:
        await c.close()


async def test_client_poll_status():
    from fortyguard_sdk import ActivityResult

    c = _mock_client(_status_handler({"ok": True}))
    try:
        aid = await c._submit("env_params", {"latitude": 32.55, "longitude": -83.88})
        res = await c.poll_status(aid, timeout=10, interval=0.01, max_interval=0.05)
        assert isinstance(res, ActivityResult)
        assert res.status == "Completed"
        assert res.result == {"ok": True}
    finally:
        await c.close()


async def test_client_heatmap_end_to_end_mocked():
    """Full client.heatmap() path with a PolygonAOI object (typed payload)."""
    import httpx

    from fortyguard_sdk import PolygonAOI

    def handler(request: httpx.Request) -> httpx.Response:
        if "/status/" in request.url.path:
            return httpx.Response(200, json={"data": {"status": "Completed", "result": {
                "map_data": {"type": "FeatureCollection", "features": [
                    {"type": "Feature", "id": "0",
                     "properties": {"tile_id": 0, "average_temperature": 33.4},
                     "geometry": {"type": "Polygon", "coordinates": [[]]}}]},
                "stats_data": {"temperature_stats": {
                    "minimum": 33.1, "maximum": 34.2, "mean": 33.6,
                    "standard_deviation": 0.3}}}}})
        # verify the payload carried a serialized PolygonAOI
        payload = json.loads(request.content)
        assert payload["polygon_aoi"]["type"] == "FeatureCollection"
        return httpx.Response(200, json={"data": {"activity_id": "aid-1"}})

    c = _mock_client(handler)
    try:
        aoi = PolygonAOI(type="FeatureCollection", features=[{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-83.90, 32.56], [-83.89, 32.56], [-83.89, 32.57],
                [-83.90, 32.57], [-83.90, 32.56],
            ]]},
        }])
        res = await c.heatmap(
            HeatmapRequest(
                polygon_aoi=aoi,
                date_time=DateTimeWindow(
                    start_date=date(2025, 7, 15), start_time="18:00",
                    filter_type=FilterType.SINGLE_HOUR,
                ),
                analytic_type="tcm",
            )
        )
        assert res.tiles[0].average_temperature == 33.4
        assert res.stats_data.temperature_stats.mean == 33.6
    finally:
        await c.close()


async def test_error_mapping_5xx_401_422_429():
    import httpx

    from fortyguard_sdk import (
        AuthError,
        InvalidApiKeyError,
        RateLimitError,
        ServerError,
        ValidationError,
    )

    async def _expect(handler, exc_type, **kwargs):
        c = _mock_client(handler)
        try:
            with pytest.raises(exc_type):
                await c._submit("env_params", {"latitude": 32.55, "longitude": -83.88})
        finally:
            await c.close()

    # 500 -> ServerError
    await _expect(lambda r: httpx.Response(500, json={"message": "boom"}),
                  ServerError)
    # 503 -> ServerError
    await _expect(lambda r: httpx.Response(503, json={"message": "down"},
                                           headers={"retry-after": "30"}),
                  ServerError)
    # 401 -> InvalidApiKeyError (an AuthError)
    await _expect(lambda r: httpx.Response(401, json={"details": {"message": "bad key"}}),
                  InvalidApiKeyError)
    assert issubclass(InvalidApiKeyError, AuthError)
    # 422 -> ValidationError
    await _expect(lambda r: httpx.Response(422, json={"details": {"message": "nope"}}),
                  ValidationError)
    # 429 -> RateLimitError (honors x-ratelimit-reset)
    await _expect(
        lambda r: httpx.Response(429, json={"message": "slow down"},
                                 headers={"x-ratelimit-reset": "0"}),
        RateLimitError,
    )