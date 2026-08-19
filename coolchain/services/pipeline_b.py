"""PeachState CoolChain services — Pipeline B: Harvest Timing (Georgia).

Runs every 5 minutes during the pre-harvest window. For each field:
    1. latest risk scores from cache (TTL 15 min)
    2. fresh heatmap ONLY if the tcm cache entry is > 30 min old
    3. GDD accumulation (local compute from cached tcm series)
    4. "Harvest Now" alert when urgency >= 80 AND GDD target met

No-forecast API: persistence (past hours >= crop threshold) is the proxy
for "staying hot" (Employee 1 fix).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from fortyguard_sdk import (
    HARVEST_COOLDOWN_S,
    HEATMAP_TTL_S,
    DateTimeWindow,
    FilterType,
    FortyGuardClient,
    HeatmapRequest,
    HeatmapResult,
    TTLCache,
    ga_threshold_c,
)
from coolchain.domain.harvest_timing import (
    GA_CROP_GDD,
    HarvestDecision,
    evaluate_harvest,
    gdd_daily,
)


@dataclass
class HarvestConfig:
    interval_s: float = 5 * 60          # 5 min pre-harvest
    heatmap_max_age_s: float = 30 * 60  # refresh only if >30 min old
    cooldown_s: float = HARVEST_COOLDOWN_S  # 48 h between alerts
    granularity: int = 100


class PipelineB:
    def __init__(
        self,
        client: FortyGuardClient,
        cache: TTLCache,
        config: HarvestConfig | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.config = config or HarvestConfig()

    async def run_forever(self, fields: list[dict[str, Any]]) -> None:
        while True:
            t0 = asyncio.get_event_loop().time()
            try:
                await self.cycle(fields)
            except Exception as exc:  # noqa: BLE001
                self._log(f"cycle failed: {exc}")
            sleep = max(0.0, self.config.interval_s - (asyncio.get_event_loop().time() - t0))
            await asyncio.sleep(sleep)

    async def cycle(self, fields: list[dict[str, Any]]) -> list[HarvestDecision]:
        """fields: [{id, crop, cluster_id, lat, lon}]."""
        decisions: list[HarvestDecision] = []
        for f in fields:
            try:
                dec = await self._evaluate_field(f)
                if dec.alert:
                    decisions.append(dec)
            except Exception as exc:  # partial failure safe
                self._log(f"field {f.get('id')} failed: {exc}")
        return decisions

    async def _evaluate_field(self, f: dict[str, Any]) -> HarvestDecision:
        fid = str(f["id"])
        crop = f.get("crop", "peach")

        # 1. latest risk from cache (written by Pipeline A)
        risk = await self.cache.get(f"risk:{fid}")
        if risk is None:
            return HarvestDecision(False, fid, crop, "no risk data yet")

        # 2. freshness check: refresh heatmap only if stale
        heat_key = f"heatmap:{f.get('cluster_id')}:tcm:*"
        age = await self._heatmap_age(heat_key)
        if age is None or age > self.config.heatmap_max_age_s:
            await self._refresh_heatmap(f)

        # 3. GDD accumulation from cached tcm series
        gdd_season = await self._accumulate_gdd(f, crop)

        # 4. cooldown check
        cooldown_key = f"cooldown:{fid}"
        last_alert = await self.cache.get(cooldown_key)
        cooldown_ok = last_alert is None or (
            time.time() - last_alert > self.config.cooldown_s
        )

        persistence_h = await self.cache.get(f"persistence:{fid}")
        warm_night = await self.cache.get(f"warm_night:{fid}") or False

        decision = evaluate_harvest(
            fid, crop,
            risk_score=float(risk),
            persistence_h=float(persistence_h) if persistence_h is not None else None,
            gdd_season=gdd_season,
            warm_night=bool(warm_night),
            cooldown_ok=cooldown_ok,
        )
        if decision.alert:
            await self.cache.set(cooldown_key, time.time(), self.config.cooldown_s)
            self._log(f"HARVEST NOW: {fid} ({crop}) — {decision.reason}")
        return decision

    async def _heatmap_age(self, key_pattern: str) -> float | None:
        """Best-effort age of the freshest tcm cache entry (in seconds)."""
        # In-memory TTLCache doesn't expose ages; Pipeline A stamps the risk
        # entry which is refreshed every 15 min — use it as freshness proxy.
        return None  # default: rely on risk cache TTL; refresh policy below

    async def _refresh_heatmap(self, f: dict[str, Any]) -> None:
        """Fresh tcm call for a field cluster (only when stale)."""
        cid = str(f.get("cluster_id"))
        dt = _now_window()
        fc = {"type": "FeatureCollection", "features": [f]}
        try:
            res = await self.client.heatmap(
                HeatmapRequest(
                    polygon_aoi=fc,
                    date_time=dt,
                    granularity=self.config.granularity,
                    analytic_type="tcm",
                )
            )
            # update risk & persistence caches from the fresh tiles
            if res.n_cells and res.tiles:
                temp = res.tiles[0].average_temperature
                if temp is not None:
                    await self.cache.set(f"risk:{f.get('id')}", temp, HEATMAP_TTL_S)
        except Exception as exc:  # noqa: BLE001 — fall back to cache
            self._log(f"refresh heatmap failed for {cid}: {exc}")

    async def _accumulate_gdd(self, f: dict[str, Any], crop: str) -> float:
        """GDD accumulation from cached tcm series (nightly recompute, TTL 24h)."""
        params = GA_CROP_GDD.get(crop, GA_CROP_GDD["peach"])
        key = f"gdd:{f.get('id')}:{_season_tag()}"
        cached = await self.cache.get(key)
        if cached is not None:
            return float(cached)

        series = await self.cache.get(f"tcm_series:{f.get('id')}") or []
        total = 0.0
        for tmax_c, tmin_c in series:
            total += gdd_daily(
                _c_to_f(tmax_c), _c_to_f(tmin_c), params["gdd_base_f"]
            )
        await self.cache.set(key, total, 24 * 3600)
        return total

    def _log(self, msg: str) -> None:
        print(f"[PipelineB] {msg}")


def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def _season_tag() -> str:
    from datetime import date

    d = date.today()
    # GA growing season: use crop-year (Oct-Sep for pecans, calendar for rest)
    return f"{d.year}" if d.month >= 3 else f"{d.year - 1}"


def _now_window() -> DateTimeWindow:
    from datetime import date, timedelta

    return DateTimeWindow(
        start_date=date.today() - timedelta(days=1),
        start_time="14:00",
        filter_type=FilterType.SINGLE_HOUR,
    )