"""PeachState CoolChain services — Pipeline A: Field Monitoring (Georgia).

Runs every 15 minutes during the season. For each GA field cluster
(Fort Valley peaches, Albany pecans, Bacon blueberries, Vidalia onions):
    1. cached tcm heatmap (TTL 15 min) or fresh call
    2. parallel: exceedance + persistence heatmaps (threshold = crop °F→°C)
    3. env_params: heat_index + WBGT + humidity (call 1) and
       solar_irradiance/GHI (call 2) on Basic; single call on Premium
    4. canopy risk score per field polygon tile

Georgia is CONFIRMED heatmap coverage (US-focused API) — no env_params
grid fallback needed; n_cells==0 is treated as data-lag "no data yet".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fortyguard_sdk import (
    ENV_PARAMS_TTL_S,
    GA_PIPELINE_A_PARAMS,
    HEATMAP_TTL_S,
    RISK_TTL_S,
    DateTimeWindow,
    EnvParamsRequest,
    EnvParamsResult,
    FilterType,
    FortyGuardClient,
    HeatmapRequest,
    HeatmapResult,
    Plan,
    TTLCache,
    ga_threshold_c,
    split_env_requests,
)
from coolchain.domain.canopy_risk import RiskResult, canopy_risk_score


@dataclass
class MonitorConfig:
    plan: Plan = Plan.BASIC
    interval_s: float = 15 * 60
    heatmap_ttl_s: float = HEATMAP_TTL_S
    env_ttl_s: float = ENV_PARAMS_TTL_S
    granularity: int = 100
    # GA crop -> °F threshold (used for exceedance/persistence)
    crop: str = "peach"


@dataclass
class FieldCluster:
    """One ≤10/50 mi² batch of farm polygons + metadata."""
    id: str
    features: list[dict[str, Any]]       # GeoJSON features
    crop: str
    centroid: tuple[float, float] = (0.0, 0.0)
    last_temp_c: float | None = None     # F9: chained temperature for env_params

    @property
    def feature_collection(self) -> dict[str, Any]:
        return {"type": "FeatureCollection", "features": self.features}


class PipelineA:
    def __init__(
        self,
        client: FortyGuardClient,
        cache: TTLCache,
        config: MonitorConfig | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.config = config or MonitorConfig(plan=client.plan)

    async def run_forever(self, clusters: list[FieldCluster]) -> None:
        while True:
            t0 = asyncio.get_event_loop().time()
            try:
                await self.cycle(clusters)
            except Exception as exc:  # noqa: BLE001 — keep loop alive
                self._log(f"cycle failed: {exc}")
            sleep = max(0.0, self.config.interval_s - (asyncio.get_event_loop().time() - t0))
            await asyncio.sleep(sleep)

    async def cycle(self, clusters: list[FieldCluster]) -> list[RiskResult]:
        """One monitoring pass over all GA field clusters (partial-failure safe)."""
        results: list[RiskResult] = []
        for cluster in clusters:
            try:
                results.extend(await self._process_cluster(cluster))
            except Exception as exc:  # partial failure -> continue with others
                self._log(f"cluster {cluster.id} failed: {exc}")
        return results

    async def _process_cluster(self, cluster: FieldCluster) -> list[RiskResult]:
        dt = _now_window()
        key = f"heatmap:{cluster.id}:tcm:{dt.start_date}:{dt.start_time}"

        async def fetch_tcm() -> HeatmapResult:
            return await self.client.heatmap(
                HeatmapRequest(
                    polygon_aoi=cluster.feature_collection,
                    date_time=dt,
                    granularity=self.config.granularity,
                    analytic_type="tcm",
                )
            )

        tcm = await self.cache.get_or_fetch(key, self.config.heatmap_ttl_s, fetch_tcm)
        if tcm.n_cells == 0:
            # F8 data-lag: not an error, just no data yet this window.
            self._log(f"cluster {cluster.id}: tcm n_cells=0 (data lag) — skip cycle")
            return []

        # persist freshest temp for env_params chaining (F9)
        cluster.last_temp_c = next(
            (t.average_temperature for t in tcm.tiles if t.average_temperature is not None),
            None,
        )

        threshold_c = ga_threshold_c(cluster.crop)
        # parallel analytic fan-out (F3: no multi-analytic param) + env params
        exceed, persist, env_results = await asyncio.gather(
            self._fetch_analytic(cluster, dt, "exceedance", threshold_c),
            self._fetch_analytic(cluster, dt, "persistence", threshold_c),
            self._fetch_env(cluster, dt),
        )
        return self._score_tiles(cluster, tcm, exceed, persist, env_results)

    async def _fetch_analytic(
        self, cluster: FieldCluster, dt: DateTimeWindow,
        analytic: str, threshold_c: float,
    ) -> HeatmapResult:
        key = f"heatmap:{cluster.id}:{analytic}:{dt.start_date}:{dt.start_time}"

        async def fetch() -> HeatmapResult:
            return await self.client.heatmap(
                HeatmapRequest(
                    polygon_aoi=cluster.feature_collection,
                    date_time=dt,
                    granularity=self.config.granularity,
                    analytic_type=analytic,  # type: ignore[arg-type]
                    threshold=threshold_c,
                )
            )

        return await self.cache.get_or_fetch(key, self.config.heatmap_ttl_s, fetch)

    async def _fetch_env(self, cluster: FieldCluster, dt: DateTimeWindow
                         ) -> list[EnvParamsResult]:
        lat, lon = cluster.centroid
        key = f"env:{lat:.4f}:{lon:.4f}:{dt.start_date}:{dt.start_time}"
        cached = await self.cache.get(key)
        if cached is not None:
            return cached

        # Basic: 4 params -> 2 requests (heat_index+WBGT+humidity, solar_irradiance)
        batches = split_env_requests(list(GA_PIPELINE_A_PARAMS), self.config.plan)
        temp = cluster.last_temp_c or 30.0  # F9

        async def one(batch: list[str]) -> EnvParamsResult:
            return await self.client.env_params(
                EnvParamsRequest(
                    latitude=lat, longitude=lon, temperature=temp,
                    date_time=dt, analysis=batch,
                )
            )

        results = await asyncio.gather(*(one(b) for b in batches))
        await self.cache.set(key, results, self.config.env_ttl_s)
        return results

    def _score_tiles(
        self, cluster: FieldCluster, tcm: HeatmapResult,
        exceed: HeatmapResult, persist: HeatmapResult,
        env_results: list[EnvParamsResult],
    ) -> list[RiskResult]:
        """Merge tile-level heatmap data + env params into canopy risk scores."""
        env = env_results[0] if env_results and env_results[0].locations else None
        env_loc = env.locations[0] if env else None
        ghi = None
        for r in env_results:
            if r.locations and r.locations[0].solar_irradiance:
                ghi = r.locations[0].solar_irradiance.clear_sky.get("ghi")
                break

        tcm_by_id = {t.tile_id: t for t in tcm.tiles}
        exc_by_id = {t.tile_id: t for t in exceed.tiles}
        per_by_id = {t.tile_id: t for t in persist.tiles}

        results = []
        for tile_id in sorted(tcm_by_id):
            t = tcm_by_id[tile_id]
            from coolchain.domain.canopy_risk import RiskInputs

            results.append(
                canopy_risk_score(
                    f"{cluster.id}:{tile_id}",
                    RiskInputs(
                        tcm_c=t.average_temperature,
                        exceedance_h=exc_by_id.get(tile_id).value
                        if tile_id in exc_by_id else None,
                        persistence_h=per_by_id.get(tile_id).value
                        if tile_id in per_by_id else None,
                        humidity_pct=_latest(env_loc, "relative_humidity_percent"),
                        heat_index_c=_latest(env_loc, "heat_index_celsius"),
                        wbgt_c=_latest(env_loc, "wet_bulb_temperature_celsius"),
                        ghi=ghi,
                    ),
                    crop=cluster.crop,
                )
            )
        return results

    def _log(self, msg: str) -> None:
        print(f"[PipelineA] {msg}")  # swap with loguru in production


def _latest(loc, name: str) -> float | None:
    if loc is None:
        return None
    s = loc.series(name)
    return s[-1] if s else None


def _now_window() -> DateTimeWindow:
    from datetime import date, timedelta

    return DateTimeWindow(
        start_date=date.today() - timedelta(days=1),  # F8: avoid data-lag 0 cells
        start_time="14:00",
        filter_type=FilterType.SINGLE_HOUR,
    )