"""FortyGuard SDK — corridor tiling math (Georgia cool-corridor routing).

Day 2 (PeachState CoolChain): split a route corridor into heatmap AOI tiles
that each fit under the plan's area cap, so a shipper can query the API once
per tile and merge the thermal profile locally.

Tile budget for the Macon->Savannah I-16 corridor (~165 mi):
    Premium (50 mi², ~1 mi total band => buffer_m=805) -> ~4-5 tiles/route
    Basic   (10 mi², ~0.5 mi total band => buffer_m=402) -> ~11 tiles/route
The exact count depends on band width and corner losses; the client-side
area guard (:func:`~fortyguard_sdk.plans.validate_heatmap_area`) is applied
to every emitted tile, so a segment can never exceed the plan cap.

``buffer_m`` is the **half-width** (shapely ``LineString.buffer`` grows both
sides), so the full corridor band is ``2 * buffer_m``. 1 mi total band =>
``buffer_m=805``; 0.5 mi total band => ``buffer_m=402``.

The same module also emits static route nodes for the offline demo
(``data/corridor_nodes.json``): {route_id, seq, lat, lon, distance_mi}.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import pyproj
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform

from .plans import PLAN_CAPABILITIES, Plan, validate_heatmap_area

M2_PER_SQMI = 2589988.110336
M_PER_MI = 1609.344

# Safety factor for corner/end losses when computing max tile length: the
# actual buffered capsule has area 2*L*w + pi*w^2 (w = half-width), and a
# bending corridor loses a little at each corner.
_CORNER_SAFETY = 1.25


def _as_line(route_geometry: Any) -> LineString:
    """Normalize route input to a shapely LineString.

    Accepts: shapely LineString, GeoJSON LineString/MultiLineString dict, or
    a sequence of (lon, lat) pairs.
    """
    if isinstance(route_geometry, LineString):
        return route_geometry
    if isinstance(route_geometry, dict):
        line = shape(route_geometry)
        if not isinstance(line, LineString):
            raise ValueError("route GeoJSON must be a LineString geometry")
        return line
    if isinstance(route_geometry, (list, tuple)):
        pts = [tuple(p) for p in route_geometry]
        if len(pts) < 2:
            raise ValueError("route needs at least 2 points")
        return LineString(pts)
    raise TypeError(
        "route_geometry must be a LineString, GeoJSON dict, or [(lon, lat), ...]"
    )


def _local_crs(line: LineString):
    """Return (to_local, to_wgs) transforms centered on the route centroid.

    Uses an azimuthal-equidistant projection so meter measurements along the
    route are accurate for a ~200 mi corridor.
    """
    lat0, lon0 = line.centroid.y, line.centroid.x
    aeqd = pyproj.Proj(proj="aeqd", lat_0=lat0, lon_0=lon0, ellps="WGS84")
    wgs = pyproj.Proj(proj="latlong", datum="WGS84")
    to_local = pyproj.Transformer.from_proj(wgs, aeqd, always_xy=True).transform
    to_wgs = pyproj.Transformer.from_proj(aeqd, wgs, always_xy=True).transform
    return to_local, to_wgs


def _subline(line: LineString, start_m: float, end_m: float) -> LineString:
    """Slice a line between two distances (meters along the line)."""
    pts: list[Point] = []
    step = max(1.0, (end_m - start_m) / max(2, int((end_m - start_m) // 10)))
    d = start_m
    while d <= end_m:
        pts.append(line.interpolate(d))
        d += step
    if (pts[-1].distance(line.interpolate(end_m)) > 1e-6):
        pts.append(line.interpolate(end_m))
    return LineString(pts)


def _tile_fc(
    wgs_polygon, route_id: str, seq: int, length_m: float, buffer_m: float
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": f"corridor-{route_id}-tile-{seq}",
        "features": [
            {
                "type": "Feature",
                "id": f"{route_id}-t{seq:02d}",
                "properties": {
                    "route_id": route_id,
                    "segment_id": seq,
                    "buffer_m": buffer_m,
                    "length_m": round(length_m, 1),
                },
                "geometry": mapping(wgs_polygon),
            }
        ],
    }


def corridor_segments(
    route_geometry: Any,
    buffer_m: float = 1609.344,          # 1 mi band by default
    plan: Plan = Plan.PREMIUM,
    route_id: str = "route",
) -> list[dict[str, Any]]:
    """Split a route corridor into plan-sized heatmap AOI tiles.

    Args:
        route_geometry: LineString / GeoJSON LineString / [(lon, lat), ...].
        buffer_m: corridor half-width in meters (0.5-1 mi => 805-1609 m).
        plan: Plan.BASIC (10 mi² tiles) or Plan.PREMIUM (50 mi² tiles).
        route_id: label stamped on each tile's properties.

    Returns:
        List of GeoJSON FeatureCollections; every tile passes
        :func:`validate_heatmap_area` for the given plan.

    Raises:
        ValueError: invalid route / buffer, or a tile exceeds the plan cap
            (e.g., buffer_m so wide that even a sliver is over the cap).
    """
    line = _as_line(route_geometry)
    if buffer_m <= 0:
        raise ValueError("buffer_m must be positive")
    cap_sqmi = PLAN_CAPABILITIES[plan].max_heatmap_area_sqmi
    cap_m2 = cap_sqmi * M2_PER_SQMI

    to_local, to_wgs = _local_crs(line)
    proj_line = transform(to_local, line)
    total_len_m = proj_line.length
    if total_len_m <= 0:
        raise ValueError("route has zero length")

    # A buffered corridor capsule has area ~ 2*L*w + pi*w^2. Solve for the
    # maximum segment length that fits the plan cap (with a corner safety).
    w = float(buffer_m)
    max_len_m = max(1.0, (cap_m2 - math.pi * w * w) / (2.0 * w) / _CORNER_SAFETY)
    # Guard against an absurdly wide buffer that even a sliver can't fit.
    if max_len_m < 1.0:
        raise ValueError(
            f"buffer_m={w:.0f}m too wide for {plan.value} cap "
            f"({cap_sqmi:.0f} mi²); reduce buffer width"
        )

    # Greedy tiling: extend each tile until its true area would exceed the cap.
    tiles: list[dict[str, Any]] = []
    pos, seq = 0.0, 0
    while pos < total_len_m - 1e-6:
        lo, hi = pos, min(pos + max_len_m * 2.0, total_len_m)
        best = pos + max_len_m * 0.05            # guaranteed minimal progress
        for _ in range(32):                      # bisect the farthest fit
            mid = (lo + hi) / 2.0
            sub = _subline(proj_line, pos, mid)
            buf = sub.buffer(w)
            fc = _tile_fc(transform(to_wgs, buf), route_id, seq, mid - pos, w)
            try:
                validate_heatmap_area(fc, plan)
                ok = True
            except ValueError:
                ok = False
            if ok:
                lo = mid
            else:
                hi = mid
            best = lo
        end = max(best, pos + 1.0)
        sub = _subline(proj_line, pos, end)
        buf = sub.buffer(w)
        fc = _tile_fc(transform(to_wgs, buf), route_id, seq, end - pos, w)
        validate_heatmap_area(fc, plan)          # final guard (fail-fast)
        tiles.append(fc)
        pos = end
        seq += 1
    return tiles


def corridor_tile_summary(
    route_geometry: Any,
    buffer_m: float = 1609.344,
    plan: Plan = Plan.PREMIUM,
    route_id: str = "route",
) -> dict[str, Any]:
    """Return the tile count + per-tile stats for a corridor (no API call)."""
    tiles = corridor_segments(route_geometry, buffer_m=buffer_m, plan=plan, route_id=route_id)
    from .models.heatmap import estimate_area_mi2

    line = _as_line(route_geometry)
    to_local, _ = _local_crs(line)
    total_m = transform(to_local, line).length
    areas = [estimate_area_mi2(t) for t in tiles]
    return {
        "route_id": route_id,
        "plan": plan.value,
        "tiles": len(tiles),
        "buffer_m": buffer_m,
        "band_width_mi": round(2.0 * buffer_m / M_PER_MI, 2),
        "route_length_mi": round(total_m / M_PER_MI, 1),
        "tile_area_sqmi": [round(a, 2) for a in areas],
        "min_area_sqmi": round(min(areas), 2),
        "max_area_sqmi": round(max(areas), 2),
        "within_plan_cap": all(a <= PLAN_CAPABILITIES[plan].max_heatmap_area_sqmi for a in areas),
    }


def route_nodes(
    route_geometry: Any,
    route_id: str,
    spacing_mi: float = 5.0,
) -> list[dict[str, Any]]:
    """Emit static route nodes for the offline demo.

    Returns [{route_id, seq, lat, lon, distance_mi}, ...] spaced ~spacing_mi
    apart along the route. No graph library required by the consumer.
    """
    line = _as_line(route_geometry)
    to_local, to_wgs = _local_crs(line)
    proj_line = transform(to_local, line)
    total_m = proj_line.length
    spacing_m = spacing_mi * M_PER_MI
    n = max(1, math.ceil(total_m / spacing_m))
    nodes: list[dict[str, Any]] = []
    for i in range(n + 1):
        d = total_m * i / n
        pt_wgs = transform(to_wgs, proj_line.interpolate(d))
        nodes.append({
            "route_id": route_id,
            "seq": i,
            "lat": round(pt_wgs.y, 6),
            "lon": round(pt_wgs.x, 6),
            "distance_mi": round(d / M_PER_MI, 2),
        })
    return nodes


__all__ = [
    "corridor_segments",
    "corridor_tile_summary",
    "route_nodes",
    "M2_PER_SQMI",
    "M_PER_MI",
]
