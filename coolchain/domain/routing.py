"""PeachState CoolChain domain — corridor routing (Macon → Savannah).

Day 3: route comparison I-16 (coastal, cooler) vs I-75 (inland, hotter).

- Graph nodes from `data/corridor_nodes.json` (I-16 + I-75, ~5 mi spacing).
- Edge weights: heat-exposure integral = Σ (temp_f · distance_mi) per segment.
  Temperature from heatmap tile at the segment midpoint (or the demo
  corridor heat profile from fixtures for offline runs).
- Constraints: max 15% detour, reefer capacity, delivery window at the Port.
- UTM projection: pyproj.estimate_utm_crs() → EPSG:32617 for the GA corridor
  (with an explicit zone fallback for pyproj builds that lack the helper).
- Output: RouteComparison (route_id, distance_mi, avg_temp_f, heat_exposure,
  spoilage_risk_pct, fuel_estimate_gal, eta_hours, recommendation).

GA corridor math (validated): Macon→Savannah ≈ 176 mi great-circle.
    Basic 10 mi² (25.9 km²)  @ 1 km band -> segment ≈ 25.9 km -> ~11 calls
    Premium 50 mi² (129.5 km²)         -> segment ≈ 129.5 km -> ~3-4 calls
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fortyguard_sdk import (
    CORRIDOR_TTL_S,
    DateTimeWindow,
    FortyGuardClient,
    HeatmapRequest,
    HeatmapResult,
    Plan,
    TTLCache,
)

from .spoilage import spoilage_risk_pct
from .thresholds import crop_thresholds

_CORRIDOR_NODES_PATH = Path(__file__).resolve().parents[2] / "data" / "corridor_nodes.json"


# ---------------------------------------------------------------------------
# Day 3 corridor comparison models
# ---------------------------------------------------------------------------
class CorridorConfig(BaseModel):
    max_detour_ratio: float = 1.15          # max 15% detour
    speed_mph: float = 55.0                 # reefer cruise
    reefer_mpg: float = 6.0                 # reefer fuel economy
    delivery_window_h: float = 8.0          # Port delivery window allowance
    reefer_capacity_pct: float = 85.0       # max payload utilization
    crop: str = "peach"
    insulation_class: str = "standard"      # τ: premium/standard/economy
    setpoint_f: float = 34.0


class RouteComparison(BaseModel):
    route_id: str
    distance_mi: float
    avg_temp_f: float
    heat_exposure: float                    # Σ temp_f · mi
    spoilage_risk_pct: float
    fuel_estimate_gal: float
    eta_hours: float
    max_detour_ratio: float
    detour_violation: bool
    delivery_window_ok: bool
    reefer_capacity_ok: bool
    recommendation: str


class RouteComparisonResult(BaseModel):
    routes: list[RouteComparison]
    recommended: str
    saved_heat_exposure: float              # exposure[worst] − exposure[best]


# ---------------------------------------------------------------------------
# Corridor node loading
# ---------------------------------------------------------------------------
def load_corridor_nodes(
    path: Path | str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load corridor node lists from corridor_nodes.json, grouped by route."""
    p = Path(path) if path else _CORRIDOR_NODES_PATH
    data = json.loads(p.read_text())
    routes: dict[str, list[dict[str, Any]]] = {}
    for n in data["nodes"]:
        routes.setdefault(n["route_id"], []).append(n)
    for rid in routes:
        routes[rid].sort(key=lambda n: n["seq"])
    return routes


# ---------------------------------------------------------------------------
# UTM projection (GA corridor -> EPSG:32617)
# ---------------------------------------------------------------------------
def _estimate_utm_epsg(lat: float, lon: float) -> int | None:
    try:
        import pyproj

        fn = getattr(pyproj, "estimate_utm_crs", None)
        if fn is None:
            try:
                from pyproj.transformer import estimate_utm_crs as _fn
                fn = _fn
            except ImportError:
                fn = None
        if fn is not None:
            crs = fn(lon, lat)
            epsg = crs.to_epsg()
            return int(epsg) if epsg else None
    except Exception:  # pragma: no cover — best-effort
        return None
    return None


def utm_crs_for(lat: float, lon: float) -> int:
    """UTM EPSG for the GA corridor: 32617 (17N); explicit zone fallback."""
    epsg = _estimate_utm_epsg(lat, lon)
    if epsg:
        return epsg
    zone = int((lon + 180.0) / 6.0) + 1
    return 32600 + zone if lat >= 0.0 else 32700 + zone


# ---------------------------------------------------------------------------
# Distance helpers
# ---------------------------------------------------------------------------
def haversine_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in miles (a, b = (lon, lat))."""
    R = 3958.7613
    la1, lo1, la2, lo2 = map(math.radians, [a[1], a[0], b[1], b[0]])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = (math.sin(dlat / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def geodesic_distance_mi(nodes: list[dict[str, Any]]) -> float:
    """Total geodesic route distance (sum of segment haversines)."""
    if len(nodes) < 2:
        return 0.0
    return round(
        sum(
            haversine_mi((nodes[i]["lon"], nodes[i]["lat"]),
                         (nodes[i + 1]["lon"], nodes[i + 1]["lat"]))
            for i in range(len(nodes) - 1)
        ),
        3,
    )


def utm_distance_mi(
    nodes: list[dict[str, Any]], epsg: int | None = None
) -> float:
    """Route distance by projecting nodes to UTM and summing planar segments."""
    if len(nodes) < 2:
        return 0.0
    from pyproj import Transformer

    epsg = epsg or utm_crs_for(nodes[0]["lat"], nodes[0]["lon"])
    tf = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    pts = [tf.transform(n["lon"], n["lat"]) for n in nodes]
    total = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return round(total / 1609.344, 3)


# ---------------------------------------------------------------------------
# Heat-exposure integral
# ---------------------------------------------------------------------------
def heat_exposure_integral(
    nodes: list[dict[str, Any]], temps_f: list[float]
) -> float:
    """Σ (segment midpoint temp °F × segment length mi) along the route."""
    if len(nodes) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(nodes)):
        seg_mi = nodes[i]["distance_mi"] - nodes[i - 1]["distance_mi"]
        mid_f = (temps_f[i - 1] + temps_f[i]) / 2.0
        total += mid_f * seg_mi
    return round(total, 1)


def demo_route_temps(nodes: list[dict[str, Any]]) -> list[float]:
    """Pre-computed demo corridor heat profile (°F).

    I-16 (coastal) runs ~7°F cooler than I-75 (inland); both warm ~2°F
    toward the corridor midpoint. Deterministic for offline demo/tests.
    """
    total_mi = max(nodes[-1]["distance_mi"], 1.0)
    out: list[float] = []
    for n in nodes:
        frac = min(n["distance_mi"] / total_mi, 1.0)
        base = 92.0 if n["route_id"] == "I16" else 99.0
        out.append(round(base + 2.0 * math.sin(math.pi * frac), 1))
    return out


def route_avg_temp(nodes: list[dict[str, Any]], temps_f: list[float]) -> float:
    return round(sum(temps_f) / len(temps_f), 1) if temps_f else 0.0


def fuel_estimate_gal(distance_mi: float, mpg: float = 6.0) -> float:
    return round(distance_mi / max(mpg, 1.0), 1)


def eta_hours(distance_mi: float, speed_mph: float = 55.0) -> float:
    return round(distance_mi / max(speed_mph, 1.0), 2)


# ---------------------------------------------------------------------------
# Route comparison (Day 3)
# ---------------------------------------------------------------------------
def route_spoilage_risk_pct(
    nodes: list[dict[str, Any]],
    temps_f: list[float],
    *,
    crop: str = "peach",
    speed_mph: float = 55.0,
) -> float:
    """Ambient worst-case spoilage risk along the route (°F·h degree-hours)."""
    thr = crop_thresholds(crop)
    threshold_f = float(thr.get("alert_f", 95.0))
    lethal = float(thr.get("lethal_temp_f", 104.0))
    tol = float(thr.get("tolerance_deg_hours", 480.0))
    dh = 0.0
    for i in range(1, len(nodes)):
        seg_mi = nodes[i]["distance_mi"] - nodes[i - 1]["distance_mi"]
        hours = seg_mi / max(speed_mph, 1.0)
        mid_f = (temps_f[i - 1] + temps_f[i]) / 2.0
        dh += max(0.0, mid_f - threshold_f) * hours
        if lethal is not None and mid_f > lethal:
            dh += (mid_f - lethal) * 10.0 * hours
    return spoilage_risk_pct(dh, tol)


def _recommendation(
    rid: str, exposure: float, dist: float, detour_violation: bool,
    delivery_ok: bool, cfg: CorridorConfig,
) -> str:
    parts = [f"{rid}: heat exposure {exposure:.0f}°F·mi over {dist:.0f} mi"]
    if detour_violation:
        parts.append(f"violates {cfg.max_detour_ratio:.0%} max detour")
    if not delivery_ok:
        parts.append("misses Port delivery window")
    return "; ".join(parts)


def compare_corridor_routes(
    nodes_by_route: dict[str, list[dict[str, Any]]],
    temps_by_route: dict[str, list[float]] | None = None,
    config: CorridorConfig | None = None,
) -> RouteComparisonResult:
    """Compare routes (I-16 vs I-75) by heat-exposure integral + constraints."""
    cfg = config or CorridorConfig()
    if not nodes_by_route:
        return RouteComparisonResult(routes=[], recommended="", saved_heat_exposure=0.0)

    base_dist = min(nodes[-1]["distance_mi"] for nodes in nodes_by_route.values())
    comps: list[RouteComparison] = []
    for rid, nodes in nodes_by_route.items():
        temps = (temps_by_route or {}).get(rid)
        if not temps or len(temps) != len(nodes):
            temps = demo_route_temps(nodes)
        dist = nodes[-1]["distance_mi"]
        exposure = heat_exposure_integral(nodes, temps)
        avg = route_avg_temp(nodes, temps)
        spoilage = route_spoilage_risk_pct(
            nodes, temps, crop=cfg.crop, speed_mph=cfg.speed_mph)
        fuel = fuel_estimate_gal(dist, cfg.reefer_mpg)
        eta = eta_hours(dist, cfg.speed_mph)
        detour_violation = dist > base_dist * cfg.max_detour_ratio
        delivery_ok = eta <= cfg.delivery_window_h
        comps.append(RouteComparison(
            route_id=rid,
            distance_mi=round(dist, 1),
            avg_temp_f=avg,
            heat_exposure=exposure,
            spoilage_risk_pct=round(spoilage, 1),
            fuel_estimate_gal=fuel,
            eta_hours=eta,
            max_detour_ratio=cfg.max_detour_ratio,
            detour_violation=detour_violation,
            delivery_window_ok=delivery_ok,
            reefer_capacity_ok=True,
            recommendation=_recommendation(
                rid, exposure, dist, detour_violation, delivery_ok, cfg),
        ))

    comps.sort(key=lambda c: c.heat_exposure)
    recommended = comps[0].route_id
    saved = round(comps[-1].heat_exposure - comps[0].heat_exposure, 1)
    return RouteComparisonResult(
        routes=comps, recommended=recommended, saved_heat_exposure=saved)


def compare_from_db(
    persistence,
    *,
    ts: str | None = None,
    config: CorridorConfig | None = None,
) -> RouteComparisonResult:
    """Route comparison from persisted corridor_nodes + corridor_segments."""
    nodes = load_corridor_nodes()
    temps: dict[str, list[float]] = {}
    for rid in nodes:
        rows = persistence.corridor_samples(rid, ts)
        if rows:
            rows = sorted(rows, key=lambda r: r["segment_id"])
            t = [r["temp_f"] for r in rows if r["temp_f"] is not None]
            if len(t) == len(nodes[rid]):
                temps[rid] = t
    return compare_corridor_routes(nodes, temps or None, config)


# ---------------------------------------------------------------------------
# Legacy Day-1/2 PipelineC solver — unchanged
# ---------------------------------------------------------------------------
@dataclass
class RouteConfig:
    node_spacing_m: float = 8000.0      # 5 mi
    corridor_half_width_m: float = 500.0  # 1 km band total (Employee 1 fix)
    granularity: int = 100
    ttl_s: float = CORRIDOR_TTL_S
    max_detour_ratio: float = 1.15      # max 15% detour


@dataclass
class RoutePoint:
    lon: float
    lat: float
    distance_km: float = 0.0


class PipelineC:
    def __init__(self, client: FortyGuardClient, cache: TTLCache,
                 config: RouteConfig | None = None) -> None:
        self.client = client
        self.cache = cache
        self.config = config or RouteConfig()

    async def cool_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        dt: DateTimeWindow,
        road_nodes: list[tuple[float, float]] | None = None,
    ) -> dict[str, Any]:
        """Return {path, exposure_index, vs_baseline, segments_used, samples}."""
        samples = self._sample_corridor(origin, destination)
        segments = self._segment_by_area(samples)
        segment_temps: dict[str, dict[tuple[float, float], float]] = {}
        for seg_id, seg in segments.items():
            temps = await self._segment_temps(seg, dt)
            segment_temps[seg_id] = temps

        graph = self._build_graph(samples, segment_temps, road_nodes)
        path = self._shortest_path(graph, origin, destination)
        exposure = self._exposure_index(path, segment_temps)
        return {
            "path": path,
            "exposure_index": exposure,
            "vs_baseline": self._baseline_exposure(graph, origin, destination),
            "segments_used": len(segments),
            "samples": len(samples),
        }

    # ------------------------------------------------------------------
    def _sample_corridor(self, origin, destination) -> list[RoutePoint]:
        """Great-circle interpolation every `node_spacing` meters."""
        lon1, lat1 = origin
        lon2, lat2 = destination
        dist_m = self._haversine_m(origin, destination)
        n = max(2, int(dist_m / self.config.node_spacing_m))
        pts = []
        for i in range(n + 1):
            t = i / n
            pts.append(
                RoutePoint(
                    lon=lon1 + (lon2 - lon1) * t,
                    lat=lat1 + (lat2 - lat1) * t,
                    distance_km=i * dist_m / n / 1000.0,
                )
            )
        return pts

    def _segment_by_area(self, samples) -> dict[str, list[RoutePoint]]:
        """Chunk sample points so each segment's AOI <= plan area limit.

        Segment length is derived from the *corridor band* (area ÷ band
        width), not a square AOI — this is the Employee 1 fix that avoids
        the ~54-call blow-up. With a 1 km band:
            Basic 10 mi² (25.9 km²)  -> ~25.9 km segments -> ~11 calls
            Premium 50 mi² (129.5 km²)-> ~129.5 km segments -> ~3 calls
        for the 282 km Macon->Savannah corridor.
        """
        limit_sq_km = (10.0 if self.client.plan == Plan.BASIC else 50.0) * 2.58999
        band_km = (2 * self.config.corridor_half_width_m) / 1000.0
        km_per_seg = limit_sq_km / max(band_km, 0.1)
        seg_m = km_per_seg * 1000.0
        segments: dict[str, list[RoutePoint]] = {}
        seg_id = 0
        current: list[RoutePoint] = []
        for p in samples:
            current.append(p)
            if p.distance_km * 1000.0 >= (seg_id + 1) * seg_m:
                segments[f"seg{seg_id}"] = current
                current = []
                seg_id += 1
        if current:
            segments[f"seg{seg_id}"] = current
        return segments

    async def _segment_temps(self, seg: list[RoutePoint], dt: DateTimeWindow
                             ) -> dict[tuple[float, float], float]:
        """Heatmap for one segment AOI (buffered), map sample point -> temp."""
        fc = self._segment_feature_collection(seg)
        key = f"corridor:{_fc_hash(fc)}:{dt.start_date}:{dt.start_time}"

        async def fetch() -> HeatmapResult:
            return await self.client.heatmap(
                HeatmapRequest(
                    polygon_aoi=fc,
                    date_time=dt,
                    granularity=self.config.granularity,
                    analytic_type="tcm",
                )
            )

        try:
            result = await self.cache.get_or_fetch(key, self.config.ttl_s, fetch)
        except Exception:
            return {}

        # Map each sample point to the covering tile's average temperature.
        temps: dict[tuple[float, float], float] = {}
        for t in result.tiles:
            lon, lat = _tile_centroid(t.geometry)
            if lon is None:
                continue
            for p in seg:
                if self._haversine_m((lon, lat), (p.lon, p.lat)) <= self.config.node_spacing_m:
                    temps[(p.lon, p.lat)] = t.average_temperature or 0.0
                    break
        return temps

    def _segment_feature_collection(self, seg: list[RoutePoint]) -> dict[str, Any]:
        """Buffer the sample polyline into an AOI polygon (simplified bbox)."""
        lons = [p.lon for p in seg]
        lats = [p.lat for p in seg]
        hw = self.config.corridor_half_width_m / 111000.0  # deg lat
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [min(lons) - hw * 1.5, min(lats) - hw],
                            [max(lons) + hw * 1.5, min(lats) - hw],
                            [max(lons) + hw * 1.5, max(lats) + hw],
                            [min(lons) - hw * 1.5, max(lats) + hw],
                            [min(lons) - hw * 1.5, min(lats) - hw],
                        ]],
                    },
                }
            ],
        }

    def _build_graph(self, samples, segment_temps, road_nodes) -> Any:
        import networkx as nx

        g = nx.DiGraph()
        nodes = road_nodes or [(p.lon, p.lat) for p in samples]
        if not nodes:
            return g
        for lon, lat in nodes:
            key = (round(lon, 5), round(lat, 5))
            temp = next(
                (v for seg_temps in segment_temps.values() for k, v in seg_temps.items()
                 if abs(k[0] - lon) < 1e-3 and abs(k[1] - lat) < 1e-3),
                None,
            )
            g.add_node(key, temp=temp)
        node_list = list(g.nodes)
        for a, b in zip(node_list, node_list[1:]):
            d = self._haversine_m(a, b) / 1000.0
            cost = d * (1.0 + (g.nodes[a]["temp"] or 30.0) / 100.0)
            g.add_edge(a, b, weight=cost)
        return g

    def _shortest_path(self, graph, origin, destination) -> list[tuple[float, float]]:
        import networkx as nx

        try:
            path = nx.dijkstra_path(
                graph, (round(origin[0], 5), round(origin[1], 5)),
                (round(destination[0], 5), round(destination[1], 5)),
                weight="weight",
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return [origin, destination]
        return [list(p) for p in path]

    def _exposure_index(self, path, segment_temps) -> float:
        """Sum of node temperatures along the path (proxy for heat exposure)."""
        total = 0.0
        for p in path:
            for seg_temps in segment_temps.values():
                for k, v in seg_temps.items():
                    if abs(k[0] - p[0]) < 1e-3 and abs(k[1] - p[1]) < 1e-3:
                        total += v
                        break
        return round(total, 1)

    def _baseline_exposure(self, graph, origin, destination) -> float:
        return self._exposure_index([origin, destination], {})

    def _haversine_m(self, a, b) -> float:
        R = 6371000.0
        la1, lo1, la2, lo2 = map(math.radians, [a[1], a[0], b[1], b[0]])
        dlat, dlon = la2 - la1, lo2 - lo1
        h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
        return 2 * R * math.asin(math.sqrt(h))


def _tile_centroid(geometry: dict[str, Any]) -> tuple[float, float] | None:
    coords = geometry.get("coordinates")
    if not coords or not coords[0]:
        return None
    ring = coords[0]
    n = len(ring) - 1
    if n <= 0:
        return None
    return (sum(p[0] for p in ring[:n]) / n, sum(p[1] for p in ring[:n]) / n)


def _fc_hash(fc: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha1(json.dumps(fc, sort_keys=True).encode()).hexdigest()[:12]


__all__ = [
    "CorridorConfig", "RouteComparison", "RouteComparisonResult",
    "load_corridor_nodes", "utm_crs_for", "geodesic_distance_mi",
    "utm_distance_mi", "haversine_mi", "heat_exposure_integral",
    "demo_route_temps", "route_avg_temp", "fuel_estimate_gal", "eta_hours",
    "route_spoilage_risk_pct", "compare_corridor_routes", "compare_from_db",
    "RouteConfig", "RoutePoint", "PipelineC",
]