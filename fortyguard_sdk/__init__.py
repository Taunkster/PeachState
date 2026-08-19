"""FortyGuard SDK — public exports (PeachState CoolChain Georgia edition)."""

from .cache import (
    CORRIDOR_TTL_S,
    COVERAGE_TTL_S,
    ENV_PARAMS_TTL_S,
    GDD_TTL_S,
    HARVEST_COOLDOWN_S,
    HEATMAP_TTL_S,
    RISK_TTL_S,
    TTLCache,
)
from .clustering import (
    M2_PER_SQMI,
    M_PER_MI,
    corridor_segments,
    corridor_tile_summary,
    route_nodes,
)
from .client import FortyGuardClient
from .exceptions import (
    AuthError,
    DownloadError,
    FeatureNotAvailableError,
    FortyGuardError,
    GeorgiaBoundaryError,
    InvalidApiKeyError,
    RateLimitError,
    ServerError,
    TaskFailedError,
    TaskTimeoutError,
    ValidationError,
)
from .georgia import GA_BBOX, GA_PILOT_LOCATIONS, assert_in_georgia, is_in_georgia
from .models.common import (
    DateTimeFilter,
    DateTimeWindow,
    Envelope,
    FilterType,
    GRANULARITIES,
    PolygonAOI,
)
from .models.env_params import (
    AQI_PARAMS,
    ENV_PARAM_NAMES,
    GA_PIPELINE_A_PARAMS,
    EnvParamsRequest,
    EnvParamsResult,
    LocationParams,
    SolarIrradiance,
    c_to_f,
    f_to_c,
)
from .models.heat_intelligence import (
    HI_ANALYSES,
    HI_ANALYSIS_LABELS,
    HeatIntelligenceDigest,
    HeatIntelligenceRequest,
    HeatIntelligenceResult,
)
from .models.heatmap import (
    AnalyticStats,
    GA_CROP_THRESHOLDS_F,
    HeatmapRequest,
    HeatmapResult,
    TemperatureStats,
    Tile,
    estimate_aoe_area_sqmi,
    estimate_area_mi2,
    ga_threshold_c,
)
from .models.satellite import SatelliteRequest, SatelliteResult
from .models.streetview import StreetViewRequest, StreetViewResult
from .plans import (
    PLAN_CAPABILITIES,
    Plan,
    PlanCapabilities,
    cap_env_analysis,
    require,
    split_env_requests,
    validate_heatmap_area,
)
from .polling import ActivityResult, PollGroup, TaskPoller
from .rate_limit import AsyncRateLimiter

__all__ = [
    # client
    "FortyGuardClient",
    # plans
    "Plan",
    "PlanCapabilities",
    "PLAN_CAPABILITIES",
    "require",
    "cap_env_analysis",
    "split_env_requests",
    "validate_heatmap_area",
    # polling / rate limit / cache
    "TaskPoller",
    "PollGroup",
    "ActivityResult",
    "AsyncRateLimiter",
    "TTLCache",
    # TTL constants
    "HEATMAP_TTL_S",
    "ENV_PARAMS_TTL_S",
    "RISK_TTL_S",
    "HARVEST_COOLDOWN_S",
    "GDD_TTL_S",
    "CORRIDOR_TTL_S",
    "COVERAGE_TTL_S",
    # exceptions
    "FortyGuardError",
    "AuthError",
    "InvalidApiKeyError",
    "FeatureNotAvailableError",
    "ValidationError",
    "RateLimitError",
    "ServerError",
    "TaskFailedError",
    "TaskTimeoutError",
    "GeorgiaBoundaryError",
    "DownloadError",
    # georgia guard
    "GA_BBOX",
    "GA_PILOT_LOCATIONS",
    "assert_in_georgia",
    "is_in_georgia",
    # common models
    "DateTimeWindow",
    "DateTimeFilter",
    "FilterType",
    "Envelope",
    "PolygonAOI",
    "GRANULARITIES",
    # heatmap models
    "HeatmapRequest",
    "HeatmapResult",
    "Tile",
    "TemperatureStats",
    "AnalyticStats",
    "estimate_aoe_area_sqmi",
    "estimate_area_mi2",
    "GA_CROP_THRESHOLDS_F",
    "ga_threshold_c",
    # env params models
    "EnvParamsRequest",
    "EnvParamsResult",
    "LocationParams",
    "SolarIrradiance",
    "ENV_PARAM_NAMES",
    "GA_PIPELINE_A_PARAMS",
    "AQI_PARAMS",
    "c_to_f",
    "f_to_c",
    # heat intelligence
    "HeatIntelligenceRequest",
    "HeatIntelligenceResult",
    "HeatIntelligenceDigest",
    "HI_ANALYSES",
    "HI_ANALYSIS_LABELS",
    # corridor tiling
    "corridor_segments",
    "corridor_tile_summary",
    "route_nodes",
    "M2_PER_SQMI",
    "M_PER_MI",
    # premium endpoints
    "SatelliteRequest",
    "SatelliteResult",
    "StreetViewRequest",
    "StreetViewResult",
]