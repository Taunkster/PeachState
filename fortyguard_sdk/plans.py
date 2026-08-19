"""FortyGuard SDK — plan capabilities and feature gating (Georgia edition).

Encodes the documented Basic vs Premium differences:

    Basic:   heatmap <= 10 mi², env_params <= 3 params per request
    Premium: heatmap <= 50 mi², all env params, + satellite, streetview,
             heat_intelligence

All limits are enforced client-side so a misconfigured request fails fast
with a clear error instead of burning API quota or hanging on an oversized
AOI (the API accepted a ~180x220 km polygon and ran 60s+).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .exceptions import FeatureNotAvailableError


class Plan(str, Enum):
    BASIC = "basic"
    PREMIUM = "premium"


@dataclass(frozen=True)
class PlanCapabilities:
    heatmap: bool = True
    env_params: bool = True
    satellite: bool = False
    streetview: bool = False
    heat_intelligence: bool = False
    max_heatmap_area_sqmi: float = 10.0
    max_env_params_per_request: int = 3  # 999 ~= "unlimited" (Premium)
    env_params_all: bool = False
    max_heatmap_granularity: int = 100


PLAN_CAPABILITIES: dict[Plan, PlanCapabilities] = {
    Plan.BASIC: PlanCapabilities(
        heatmap=True,
        env_params=True,
        satellite=False,
        streetview=False,
        heat_intelligence=False,
        max_heatmap_area_sqmi=10.0,
        max_env_params_per_request=3,
        env_params_all=False,
    ),
    Plan.PREMIUM: PlanCapabilities(
        heatmap=True,
        env_params=True,
        satellite=True,
        streetview=True,
        heat_intelligence=True,
        max_heatmap_area_sqmi=50.0,
        max_env_params_per_request=999,
        env_params_all=True,
    ),
}


def require(endpoint: str, plan: Plan) -> None:
    """Raise FeatureNotAvailableError if `endpoint` is not in `plan`."""
    caps = PLAN_CAPABILITIES[plan]
    enabled = {
        "heatmap": caps.heatmap,
        "env_params": caps.env_params,
        "satellite": caps.satellite,
        "streetview": caps.streetview,
        "heat_intelligence": caps.heat_intelligence,
    }[endpoint]
    if not enabled:
        raise FeatureNotAvailableError(
            f"endpoint '{endpoint}' requires Premium plan (current: {plan.value})"
        )


def cap_env_analysis(wanted: list[str] | None, plan: Plan) -> list[str] | None:
    """Cap the env_params analysis list to the plan limit.

    Premium returns None (= "request all"), Basic slices to 3.
    """
    caps = PLAN_CAPABILITIES[plan]
    if caps.env_params_all:
        return None
    if wanted is None:
        return None
    return wanted[: caps.max_env_params_per_request]


def validate_heatmap_area(polygon_or_area: Any, plan: Plan) -> None:
    """Client-side guard against oversized AOIs (prevents runaway jobs).

    Accepts either a numeric area in mi² or a GeoJSON FeatureCollection /
    :class:`~fortyguard_sdk.models.common.PolygonAOI` polygon (the area is
    computed from the polygon's bounding box). Raises ValueError when the
    area exceeds the plan cap (10 mi² Basic / 50 mi² Premium).
    """
    caps = PLAN_CAPABILITIES[plan]
    if isinstance(polygon_or_area, (int, float)):
        sq_mi = float(polygon_or_area)
    else:
        from .models.heatmap import estimate_area_mi2

        sq_mi = estimate_area_mi2(polygon_or_area)
    if sq_mi > caps.max_heatmap_area_sqmi:
        raise ValueError(
            f"AOI {sq_mi:.1f} mi² exceeds plan limit "
            f"({caps.max_heatmap_area_sqmi:.0f} mi² for {plan.value})"
        )


def split_env_requests(
    wanted: list[str], plan: Plan
) -> list[list[str]]:
    """Split a wanted param list into plan-sized request batches.

    GA Pipeline A needs 4 params (heat_index, WBGT, humidity, GHI):
        Basic  -> [[p1,p2,p3], [p4]]   (2 requests)
        Premium-> [[p1,p2,p3,p4]]      (1 request, or None = all)
    """
    caps = PLAN_CAPABILITIES[plan]
    if caps.env_params_all:
        return [wanted]
    n = caps.max_env_params_per_request
    return [wanted[i : i + n] for i in range(0, len(wanted), n)]