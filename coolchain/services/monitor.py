"""PeachState CoolChain services - Monitor Orchestrator (Day 4).

15-minute cadence orchestrator that ties the SDK polling, disk cache,
domain engines, and SQLite together:

    1. PollGroup fan-out - for every GA field cluster run heatmap
       (tcm + exceedance + persistence) and env_params *concurrently*,
       capped at ``max_concurrent`` (the SDK rate limiter already caps to 5).
    2. Disk cache - key = sha256(AOI + date_time + analytic_type);
       TTL 15 min for heatmap, 30 min for env_params. An in-memory TTL
       cache is layered on top for single-flight de-duplication.
    3. Graceful degradation - on API failure serve from the disk cache; on
       partial failure continue with the remaining clusters/fields.
    4. Pipeline A integration - :func:`canopy_risk.score_field_from_db`
       for each field -> writes ``risk_scores``.
    5. Pipeline B integration - after risk scores,
       :func:`harvest_timing.evaluate_field_from_db` for pre-harvest
       fields -> writes ``alerts``.
    6. Pipeline C - on-demand corridor comparison (not scheduled here).
    7. State persistence - last successful run, error counts, and cache
       hit rate tracked in a JSON state file.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
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
    ga_threshold_c,
    split_env_requests,
)
from coolchain.domain.canopy_risk import RiskResult, score_field_from_db
from coolchain.domain.harvest_timing import HarvestAlert, evaluate_field_from_db
from coolchain.services.persistence import Persistence
from coolchain.services.pipeline_a import FieldCluster

# TTLs (single source of truth mirrored in fortyguard_sdk.cache).
HEATMAP_DISK_TTL_S = 15 * 60
ENV_DISK_TTL_S = 30 * 60
STATE_FILE = "monitor_state.json"

# Georgia region reference centroids (used to group DB fields into clusters).
GA_REGION_ANCHORS: dict[str, tuple[float, float]] = {
    "fort_valley": (32.5538, -83.8874),
    "albany": (31.5785, -84.1557),
    "bacon": (31.5394, -82.4637),
    "bacon_appling": (31.5394, -82.4637),
    "vidalia": (32.2177, -82.4135),
}
DEFAULT_ANCHOR = (32.8407, -83.6324)  # Macon fallback (still GA)


class DiskCache:
    """JSON-file disk cache with per-entry TTL (survives restarts)."""

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        self.cache_dir = Path(
            cache_dir or (Path(__file__).resolve().parents[2] / "data" / "cache")
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str, max_age_s: float) -> Any | None:
        """Return the cached value if it is younger than ``max_age_s``."""
        p = self._path(key)
        if not p.exists():
            self.misses += 1
            return None
        try:
            meta = json.loads(p.read_text())
            age = time.time() - float(meta["stored_at"])
        except (ValueError, KeyError, TypeError):
            self.misses += 1
            return None
        if age > max_age_s:
            self.misses += 1
            return None
        self.hits += 1
        return meta.get("value")

    def set(self, key: str, value: Any, ttl_s: float) -> None:
        self._path(key).write_text(
            json.dumps(
                {"stored_at": time.time(), "ttl_s": ttl_s, "value": value},
                default=str,
            )
        )

    def cache_key(self, *parts: Any) -> str:
        """key = sha256(AOI + date_time + analytic_type), deterministic."""
        blob = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total else 0.0


@dataclass
class MonitorConfig:
    interval_s: float = 15 * 60
    heatmap_disk_ttl_s: float = HEATMAP_DISK_TTL_S
    env_disk_ttl_s: float = ENV_DISK_TTL_S
    granularity: int = 100
    max_concurrent: int = 5
    plan: Plan = Plan.BASIC
    crop: str = "peach"
    # Pipeline B: evaluate pre-harvest fields only when True, else all.
    preharvest_only: bool = False
    state_file: str = STATE_FILE


@dataclass
class CycleReport:
    """Result of one monitoring pass (tests + /trigger/cycle payload)."""

    started_at: str
    finished_at: str
    clusters_ok: int = 0
    clusters_failed: int = 0
    risk_results: int = 0
    harvest_alerts: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    cache_hit_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "clusters_ok": self.clusters_ok,
            "clusters_failed": self.clusters_failed,
            "risk_results": self.risk_results,
            "harvest_alerts": self.harvest_alerts,
            "errors": self.errors,
            "cache_hit_rate": self.cache_hit_rate,
        }


class MonitorService:
    """15-min cadence orchestrator (PollGroup fan-out + disk cache)."""

    def __init__(
        self,
        client: FortyGuardClient,
        cache: TTLCache,
        persistence: Persistence,
        config: MonitorConfig | None = None,
        *,
        disk_cache: DiskCache | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.persistence = persistence
        self.config = config or MonitorConfig(plan=client.plan)
        self.disk = disk_cache or DiskCache()
        self.state: dict[str, Any] = self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _state_path(self) -> Path:
        return self.disk.cache_dir / self.config.state_file

    def _load_state(self) -> dict[str, Any]:
        p = self._state_path()
        if p.exists():
            try:
                return json.loads(p.read_text())
            except (ValueError, OSError):
                pass
        return {
            "last_run": None,
            "last_successful_run": None,
            "total_cycles": 0,
            "successful_cycles": 0,
            "error_count": 0,
            "errors": [],
            "cache_hits": 0,
            "cache_misses": 0,
            "alerts_fired": 0,
            "risk_scores_written": 0,
        }

    def _save_state(self) -> None:
        self._state_path().write_text(json.dumps(self.state, indent=2))

    def state_summary(self) -> dict[str, Any]:
        total = self.state.get("cache_hits", 0) + self.state.get("cache_misses", 0)
        hit_rate = round(self.state.get("cache_hits", 0) / total, 4) if total else 0.0
        return {
            **self.state,
            "cache_hit_rate": hit_rate,
            "disk_cache": self.disk.stats(),
            "disk_cache_hit_rate": self.disk.hit_rate(),
        }

    # ------------------------------------------------------------------
    # Cluster construction (fields from SQLite -> FieldCluster batches)
    # ------------------------------------------------------------------
    def build_clusters(self, fields: list[Any]) -> list[FieldCluster]:
        """Group DB fields by region -> one FieldCluster per region."""
        by_region: dict[str, list[dict[str, Any]]] = {}
        for f in fields:
            region = (f["region"] or "fort_valley") if "region" in f.keys() else "fort_valley"
            by_region.setdefault(region, []).append(dict(f))

        clusters: list[FieldCluster] = []
        for region, feats in sorted(by_region.items()):
            crop = feats[0].get("crop") or self.config.crop
            anchor = GA_REGION_ANCHORS.get(region, DEFAULT_ANCHOR)
            clusters.append(
                FieldCluster(
                    id=f"{region}-clusters",
                    features=_geo_features(feats),
                    crop=crop,
                    centroid=anchor,
                )
            )
        return clusters

    # ------------------------------------------------------------------
    # PollGroup fan-out for one cluster (concurrent heatmap + env)
    # ------------------------------------------------------------------
    def _window(self) -> DateTimeWindow:
        """F8: use yesterday 14:00 to avoid data-lag zero-cell responses."""
        return DateTimeWindow(
            start_date=date.today() - timedelta(days=1),
            start_time="14:00",
            filter_type=FilterType.SINGLE_HOUR,
        )

    async def _cached_heatmap(
        self, cluster: FieldCluster, dt: DateTimeWindow, analytic: str
    ) -> HeatmapResult:
        """Disk-cache-aware heatmap fetch (TTL 15 min) with in-memory layer."""
        key = self.disk.cache_key(
            cluster.feature_collection, dt.model_dump(mode="json"), analytic
        )
        mem_key = f"hm:{key}"
        cached = await self.cache.get(mem_key)
        if cached is not None:
            return cached

        # 1) try the disk cache first (survives restarts)
        from_disk = self.disk.get(key, self.config.heatmap_disk_ttl_s)
        if from_disk is not None:
            res = HeatmapResult.model_validate(from_disk)
            await self.cache.set(mem_key, res, self.config.heatmap_disk_ttl_s)
            return res

        # 2) fresh API call, then persist to disk + memory
        req = HeatmapRequest(
            polygon_aoi=cluster.feature_collection,
            date_time=dt,
            granularity=self.config.granularity,
            analytic_type=analytic,  # type: ignore[arg-type]
            threshold=ga_threshold_c(cluster.crop) if analytic != "tcm" else None,
        )
        try:
            res = await self.client.heatmap(req)
            self.disk.set(key, res.model_dump(mode="json"), self.config.heatmap_disk_ttl_s)
            await self.cache.set(mem_key, res, self.config.heatmap_disk_ttl_s)
            return res
        except Exception:
            # 3) graceful degradation: API down -> stale disk cache
            stale = self.disk.get(key, self.config.heatmap_disk_ttl_s * 4)
            if stale is not None:
                return HeatmapResult.model_validate(stale)
            raise

    async def _cached_env(
        self, cluster: FieldCluster, dt: DateTimeWindow
    ) -> list[EnvParamsResult]:
        """Disk-cache-aware env_params fetch (TTL 30 min) for a cluster."""
        lat, lon = cluster.centroid
        key = self.disk.cache_key("env", lat, lon, dt.model_dump(mode="json"))
        mem_key = f"env:{key}"
        cached = await self.cache.get(mem_key)
        if cached is not None:
            return cached

        from_disk = self.disk.get(key, self.config.env_disk_ttl_s)
        if from_disk is not None:
            results = [EnvParamsResult.model_validate(r) for r in from_disk]
            await self.cache.set(mem_key, results, self.config.env_disk_ttl_s)
            return results

        batches = split_env_requests(
            ["heat_index_celsius", "wet_bulb_temperature_celsius",
             "relative_humidity_percent", "solar_irradiance"],
            self.config.plan,
        )
        temp_c = cluster.last_temp_c or 30.0

        async def one(batch: list[str]) -> EnvParamsResult:
            return await self.client.env_params(
                EnvParamsRequest(
                    latitude=lat, longitude=lon, temperature=temp_c,
                    date_time=dt, analysis=batch,
                )
            )

        try:
            results = await asyncio.gather(*(one(b) for b in batches))
        except Exception:
            stale = self.disk.get(key, self.config.env_disk_ttl_s * 4)
            if stale is not None:
                return [EnvParamsResult.model_validate(r) for r in stale]
            raise
        self.disk.set(
            key, [r.model_dump(mode="json") for r in results], self.config.env_disk_ttl_s
        )
        await self.cache.set(mem_key, results, self.config.env_disk_ttl_s)
        return results

    async def poll_cluster(self, cluster: FieldCluster) -> list[RiskResult]:
        """One cluster: concurrent tcm/exceedance/persistence heatmaps + env."""
        dt = self._window()
        tcm = await self._cached_heatmap(cluster, dt, "tcm")
        if tcm.n_cells == 0:
            # F8 data-lag: no data yet this window - skip, not an error.
            return []

        cluster.last_temp_c = next(
            (
                t.average_temperature
                for t in tcm.tiles
                if t.average_temperature is not None
            ),
            None,
        )
        exceed, persist, envs = await asyncio.gather(
            self._cached_heatmap(cluster, dt, "exceedance"),
            self._cached_heatmap(cluster, dt, "persistence"),
            self._cached_env(cluster, dt),
        )

        self._persist_cluster(cluster, dt, tcm, exceed, persist, envs)
        return self._risk_results_for_cluster(cluster, tcm, exceed, persist, envs)

    def _persist_cluster(
        self,
        cluster: FieldCluster,
        dt: DateTimeWindow,
        tcm: HeatmapResult,
        exceed: HeatmapResult,
        persist: HeatmapResult,
        envs: list[EnvParamsResult],
    ) -> None:
        """Write heat_samples + env_samples for every field in the cluster."""
        ts = f"{dt.start_date.isoformat()}T{dt.start_time}:00Z"
        stats = tcm.stats_data.temperature_stats
        mean_c = stats.mean if stats else None
        min_c = stats.minimum if stats else None
        max_c = stats.maximum if stats else None

        exceed_val = _analytic_value(exceed)
        persist_val = _analytic_value(persist)

        for feat in cluster.features:
            fid = str(feat.get("id") or feat.get("properties", {}).get("id"))
            if not fid:
                continue
            self.persistence.insert_heat_sample(
                fid, ts, analytic_type="tcm",
                temp_c=mean_c,
                temp_f=_c_to_f(mean_c) if mean_c is not None else None,
                min_c=min_c, max_c=max_c, mean_c=mean_c,
                n_cells=tcm.n_cells,
            )
            if exceed_val is not None:
                self.persistence.insert_heat_sample(
                    fid, ts, analytic_type="exceedance",
                    temp_c=exceed_val, temp_f=exceed_val, n_cells=exceed.n_cells,
                )
            if persist_val is not None:
                self.persistence.insert_heat_sample(
                    fid, ts, analytic_type="persistence",
                    temp_c=persist_val, temp_f=persist_val, n_cells=persist.n_cells,
                )

        loc = envs[0].locations[0] if envs and envs[0].locations else None
        lat, lon = cluster.centroid
        for feat in cluster.features:
            fid = str(feat.get("id") or feat.get("properties", {}).get("id"))
            if not fid:
                continue
            self.persistence.insert_env_sample(
                fid, ts, lat=lat, lon=lon,
                temperature_f=loc.temperature_f if loc else None,
                heat_index_f=loc.heat_index_f if loc else None,
                wet_bulb_f=loc.wet_bulb_f if loc else None,
                relative_humidity_percent=loc.relative_humidity_percent if loc else None,
                ghi_wm2=_ghi(envs),
            )

    def _risk_results_for_cluster(
        self,
        cluster: FieldCluster,
        tcm: HeatmapResult,
        exceed: HeatmapResult,
        persist: HeatmapResult,
        envs: list[EnvParamsResult],
    ) -> list[RiskResult]:
        """Per-field canopy risk from cluster-level data (Day-3 engine)."""
        loc = envs[0].locations[0] if envs and envs[0].locations else None
        from coolchain.domain.canopy_risk import RiskInputs, canopy_risk_score

        results: list[RiskResult] = []
        for feat in cluster.features:
            fid = str(feat.get("id") or feat.get("properties", {}).get("id"))
            if not fid:
                continue
            res = canopy_risk_score(
                fid,
                RiskInputs(
                    tcm_c=_mean_temp_c(tcm),
                    exceedance_h=_analytic_value(exceed),
                    persistence_h=_analytic_value(persist),
                    humidity_pct=loc.relative_humidity_percent if loc else None,
                    heat_index_c=loc.heat_index_c if loc else None,
                    wbgt_c=loc.wet_bulb_c if loc else None,
                    ghi=_ghi(envs),
                ),
                crop=cluster.crop,
            )
            results.append(res)
        return results

    # ------------------------------------------------------------------
    # Full 15-min cycle: Pipeline A (risk) + Pipeline B (harvest)
    # ------------------------------------------------------------------
    async def cycle(self, clusters: list[FieldCluster] | None = None) -> CycleReport:
        """One monitoring pass over all GA field clusters (partial-failure safe)."""
        started = _utc_now()
        report = CycleReport(started_at=started, finished_at=started)
        self.state["last_run"] = started

        fields = self.persistence.load_fields()
        if not fields:
            report.errors.append(("db", "no fields in database (run `fg db init`)"))

        clusters = clusters or self.build_clusters(fields)
        sem = asyncio.Semaphore(self.config.max_concurrent)

        async def one(cluster: FieldCluster) -> list[RiskResult]:
            async with sem:
                try:
                    return await self.poll_cluster(cluster)
                except Exception as exc:  # noqa: BLE001 - partial failure safe
                    report.clusters_failed += 1
                    report.errors.append((cluster.id, str(exc)))
                    return []

        results_by_cluster = await asyncio.gather(*(one(c) for c in clusters))
        report.clusters_ok = len(clusters) - report.clusters_failed
        for rlist in results_by_cluster:
            report.risk_results += len(rlist)

        # Pipeline A: persist risk_scores for every field from the DB samples.
        risk_written = 0
        for f in fields:
            try:
                res = score_field_from_db(
                    self.persistence, f["id"],
                    crop=f["crop"] if "crop" in f.keys() else None,
                    in_preharvest_window=self.config.preharvest_only,
                )
                if res is not None:
                    risk_written += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append((f["id"], f"risk: {exc}"))
        self.state["risk_scores_written"] = (
            self.state.get("risk_scores_written", 0) + risk_written
        )

        # Pipeline B: harvest timing for pre-harvest fields (writes alerts).
        harvest_alerts = 0
        for f in fields:
            try:
                alert = evaluate_field_from_db(self.persistence, f["id"])
                if alert is not None and alert.triggered:
                    harvest_alerts += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append((f["id"], f"harvest: {exc}"))
        report.harvest_alerts = harvest_alerts
        self.state["alerts_fired"] = self.state.get("alerts_fired", 0) + harvest_alerts

        # State bookkeeping.
        finished = _utc_now()
        report.finished_at = finished
        report.cache_hit_rate = self.disk.hit_rate()
        self.state["total_cycles"] = self.state.get("total_cycles", 0) + 1
        self.state["last_successful_run"] = started
        self.state["successful_cycles"] = self.state.get("successful_cycles", 0) + 1
        self.state["cache_hits"] = self.state.get("cache_hits", 0) + self.disk.hits
        self.state["cache_misses"] = self.state.get("cache_misses", 0) + self.disk.misses
        if report.errors:
            self.state["error_count"] = self.state.get("error_count", 0) + len(report.errors)
            self.state["errors"] = (
                [f"{c}: {m}" for c, m in report.errors][-20:]
            )
        self._save_state()
        return report

    async def run_forever(self, interval_s: float | None = None) -> None:
        """Cadence loop: cycle() then sleep the remainder of the interval."""
        interval = interval_s or self.config.interval_s
        while True:
            t0 = asyncio.get_event_loop().time()
            try:
                await self.cycle()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                self._log(f"cycle failed: {exc}")
            sleep = max(0.0, interval - (asyncio.get_event_loop().time() - t0))
            await asyncio.sleep(sleep)

    # ------------------------------------------------------------------
    # Pipeline C: on-demand corridor comparison (not scheduled)
    # ------------------------------------------------------------------
    async def corridor_comparison(self, dt: DateTimeWindow | None = None) -> Any:
        from coolchain.services.pipeline_c import PipelineCService

        pc = PipelineCService(self.client, self.cache)
        return await pc.compare_routes(dt or self._window())

    def _log(self, msg: str) -> None:
        print(f"[Monitor] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _geo_features(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild GeoJSON Features from DB field rows (geometry_json column)."""
    out: list[dict[str, Any]] = []
    for f in fields:
        geom = f.get("geometry_json")
        if isinstance(geom, str):
            try:
                geom = json.loads(geom)
            except ValueError:
                geom = None
        out.append(
            {
                "type": "Feature",
                "id": f.get("id"),
                "properties": {
                    "name": f.get("name"),
                    "crop": f.get("crop"),
                    "region": f.get("region"),
                },
                "geometry": geom or _fallback_geometry(),
            }
        )
    return out


def _fallback_geometry() -> dict[str, Any]:
    """Small ~1.5 mi² square around the GA default anchor."""
    lat, lon = DEFAULT_ANCHOR
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - 0.01, lat - 0.01], [lon + 0.01, lat - 0.01],
            [lon + 0.01, lat + 0.01], [lon - 0.01, lat + 0.01],
            [lon - 0.01, lat - 0.01],
        ]],
    }


def _mean_temp_c(tcm: HeatmapResult) -> float | None:
    if tcm.stats_data.temperature_stats:
        return tcm.stats_data.temperature_stats.mean
    temps = [t.average_temperature for t in tcm.tiles if t.average_temperature is not None]
    return (sum(temps) / len(temps)) if temps else None


def _analytic_value(res: HeatmapResult) -> float | None:
    vals = [t.value for t in res.tiles if t.value is not None]
    if vals:
        return round(sum(vals) / len(vals), 2)
    return res.stats_data.analytic_stats.mean if res.stats_data.analytic_stats else None


def _ghi(envs: list[EnvParamsResult]) -> float | None:
    for r in envs:
        if r.locations and r.locations[0].solar_irradiance:
            g = r.locations[0].solar_irradiance.ghi()
            if g is not None:
                return g
    return None


def _c_to_f(c: float | None) -> float | None:
    return c * 9.0 / 5.0 + 32.0 if c is not None else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = [
    "DiskCache",
    "MonitorConfig",
    "CycleReport",
    "MonitorService",
    "HEATMAP_DISK_TTL_S",
    "ENV_DISK_TTL_S",
]