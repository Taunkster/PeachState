"""PeachState CoolChain services — spatial clustering of GA farm polygons.

Georgia farm polygons are small (orchards ~50-200 acres = 0.08-0.3 mi²),
so a 10 mi² Basic AOI fits ~30-120 fields. STRtree over farm polygons +
greedy batching by region keeps the API call count tiny (F4-proven
multi-polygon batching).

Regions (verified in GA bbox):
    Fort Valley peaches, Albany pecans, Bacon blueberries, Vidalia onions.

Corridor tiling (Day 2) is implemented in the SDK
(:mod:`fortyguard_sdk.clustering`) and re-exported here so both the SDK and
the coolchain services layers expose ``corridor_segments`` / ``route_nodes``.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from coolchain.services.pipeline_a import FieldCluster
from fortyguard_sdk.clustering import (  # noqa: F401  (re-export)
    corridor_segments,
    corridor_tile_summary,
    route_nodes,
)

__all__ = [
    "GAFieldClusterer",
    "GA_REGIONS",
    "corridor_segments",
    "corridor_tile_summary",
    "route_nodes",
]

# GA region reference centroids + default crop.
GA_REGIONS: dict[str, dict[str, Any]] = {
    "fort_valley": {"lat": 32.5538, "lon": -83.8874, "crop": "peach"},
    "albany":      {"lat": 31.5785, "lon": -84.1557, "crop": "pecan"},
    "bacon":       {"lat": 31.5394, "lon": -82.4637, "crop": "blueberry"},
    "vidalia":     {"lat": 32.2177, "lon": -82.4135, "crop": "onion"},
}


class GAFieldClusterer:
    """STRtree over GA farm polygons -> greedy batches under plan area limit."""

    def __init__(self, farms: list[dict[str, Any]]) -> None:
        """farms: GeoJSON Features with .id, .properties.crop, .geometry."""
        self._farms = farms
        self._geoms = [shape(f["geometry"]) for f in farms]
        self._tree = STRtree(self._geoms)

    def cluster_by_area_limit(
        self, limit_sqmi: float, region: str | None = None
    ) -> list[FieldCluster]:
        """Greedy merge of adjacent farms while combined AOI envelope <= limit.

        Returns FieldCluster objects ready for polygon_aoi (F4-proven).
        """
        candidates = list(range(len(self._farms)))
        if region is not None:
            ref = GA_REGIONS[region]
            candidates = [
                i for i in candidates
                if _distance_km((self._geoms[i].centroid.x, self._geoms[i].centroid.y),
                                (ref["lon"], ref["lat"])) < 50.0
            ]

        used: set[int] = set()
        clusters: list[FieldCluster] = []
        for i in candidates:
            if i in used:
                continue
            group = [self._farms[i]]
            group_geom = self._geoms[i]
            for j in candidates[i + 1:]:
                if j in used:
                    continue
                merged = unary_union([group_geom, self._geoms[j]])
                if _geom_area_sqmi(merged) <= limit_sqmi:
                    group.append(self._farms[j])
                    group_geom = merged
                    used.add(j)
            used.add(i)
            crop = group[0].get("properties", {}).get("crop", "peach")
            clusters.append(
                FieldCluster(
                    id=f"{region or 'ga'}-{len(clusters)}",
                    features=group,
                    crop=crop,
                    centroid=_approx_centroid(group),
                )
            )
        return clusters

    def all_clusters(self, plan_area_sqmi: float) -> list[FieldCluster]:
        """Cluster across all GA regions."""
        out: list[FieldCluster] = []
        for region in GA_REGIONS:
            out.extend(self.cluster_by_area_limit(plan_area_sqmi, region))
        return out


def _geom_area_sqmi(geom) -> float:
    """Approx planar area in mi² from bounds (fine for the 10/50 mi² guard)."""
    import math

    b = geom.bounds
    if None in b:
        return 0.0
    w, h = b[2] - b[0], b[3] - b[1]
    km_per_deg_lon = 111.0 * math.cos((b[1] + b[3]) / 2 * math.pi / 180)
    sq_km = (w * km_per_deg_lon) * (h * 111.0)
    return sq_km * 0.386102


def _approx_centroid(features: list[dict[str, Any]]) -> tuple[float, float]:
    pts: list[tuple[float, float]] = []
    for f in features:
        g = f.get("geometry", {})
        c = g.get("coordinates")
        if g.get("type") == "Polygon" and c:
            pts.extend(p for ring in c for p in ring)
    if not pts:
        return (33.0, -83.5)
    return (sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts))


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    import math

    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[1], a[0], b[1], b[0]])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))