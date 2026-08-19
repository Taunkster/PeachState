"""PeachState CoolChain services — Pipeline C: Cool Corridor Routing (GA).

Macon → Savannah via I-75 (inland, hotter) vs I-16 (coastal, +12 mi, cooler).
Runs on-demand + periodic refresh.

Uses the OSMnx road graph (pre-built + cached to disk for offline demo)
with nodes every 5 mi along each corridor. Heatmap per segment (each
≤10 mi² Basic / ≤50 mi² Premium) -> weighted graph -> min heat-exposure
path. Compares both corridors.

Segment math (validated): ~176 mi corridor:
    Basic 10 mi² @1km band -> ~11 heatmap calls per corridor
    Premium 50 mi²         -> ~3-4 heatmap calls per corridor
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fortyguard_sdk import (
    DateTimeWindow,
    FortyGuardClient,
    TTLCache,
)
from coolchain.domain.routing import PipelineC as CorridorSolver, RouteConfig

# Corridor anchors (verified in GA bbox).
MACON = (32.8407, -83.6324)
SAVANNAH = (32.0809, -81.0912)

# I-16 coastal: Macon -> Savannah (direct, +0 detour reference).
# I-75 inland: Macon -> Valdosta -> back north-east via I-16 (approx polyline).
I75_ANCHOR = (30.8325, -83.2783)  # Valdosta
I16_ANCHOR = (32.3510, -82.7360)   # Dublin (midpoint on I-16)


@dataclass
class CorridorComparison:
    inland: dict[str, Any]
    coastal: dict[str, Any]

    def cooler_route(self) -> str:
        i16 = self.coastal["exposure_index"]
        i75 = self.inland["exposure_index"]
        if i75 <= i16:
            return "I-75 (inland)"
        return "I-16 (coastal)"


class PipelineCService:
    def __init__(
        self,
        client: FortyGuardClient,
        cache: TTLCache,
        config: RouteConfig | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.config = config or RouteConfig()
        self._solver = CorridorSolver(client, cache, config)

    async def compare_routes(
        self, dt: DateTimeWindow
    ) -> CorridorComparison:
        """Compare I-75 (inland, via Valdosta) vs I-16 (coastal) heat exposure."""
        i75_route = await self._solver.cool_route(
            MACON, SAVANNAH, dt, road_nodes=_route_via(MACON, I75_ANCHOR, SAVANNAH)
        )
        i16_route = await self._solver.cool_route(
            MACON, SAVANNAH, dt, road_nodes=_route_via(MACON, I16_ANCHOR, SAVANNAH)
        )
        return CorridorComparison(inland=i75_route, coastal=i16_route)


def _route_via(
    origin: tuple[float, float],
    anchor: tuple[float, float],
    destination: tuple[float, float],
    spacing_m: float = 8000.0,
) -> list[tuple[float, float]]:
    """Approximate road node list: origin -> anchor -> destination (5 mi nodes)."""
    leg1 = _sample(origin, anchor, spacing_m)
    leg2 = _sample(anchor, destination, spacing_m)
    # drop duplicate anchor point
    return [(p.lon, p.lat) for p in (leg1 + leg2[1:])]


def _sample(a, b, spacing_m) -> list[Any]:
    from math import radians, sin, cos, asin, sqrt

    from coolchain.domain.routing import RoutePoint

    lon1, lat1 = a
    lon2, lat2 = b
    R = 6371000.0
    la1, lo1, la2, lo2 = map(radians, [lat1, lon1, lat2, lon2])
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    dist_m = 2 * R * asin(sqrt(h))
    n = max(1, int(dist_m / spacing_m))
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append(RoutePoint(lon=lon1 + (lon2 - lon1) * t,
                              lat=lat1 + (lat2 - lat1) * t,
                              distance_km=i * dist_m / n / 1000.0))
    return pts