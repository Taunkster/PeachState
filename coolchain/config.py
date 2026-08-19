"""PeachState CoolChain — configuration (pydantic-settings).

Basic vs Premium feature flags for the GA use case. Configuration-driven
so the same codebase runs both plans and hot-swaps on key upgrade.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings

from fortyguard_sdk import Plan


class Settings(BaseSettings):
    # --- auth ---
    fortyguard_api_key: str = ""
    fortyguard_plan: Plan = Plan.BASIC

    # --- feature flags (derived from plan unless overridden) ---
    heatmap_enabled: bool = True
    satellite_enabled: bool = False
    streetview_enabled: bool = False
    heat_intelligence_enabled: bool = False
    max_heatmap_area_sqmi: float = 10.0
    max_env_params_per_request: int = 3

    # --- Georgia corridor config (Employee 1 fix: narrow corridor) ---
    corridor_band_width_m: float = 1000.0
    corridor_node_spacing_m: float = 8000.0   # 5 mi
    corridor_premium_enabled: bool = False    # Premium: wide AOIs (50 mi²)

    # --- pipeline cadence ---
    pipeline_a_interval_s: float = 15 * 60
    pipeline_b_interval_s: float = 5 * 60
    pipeline_b_active: bool = False           # enabled only pre-harvest
    pipeline_d_daily_hour: int = 6

    # --- data ---
    data_dir: str = "data"
    reports_dir: str = "data/reports"
    graphs_dir: str = "data/graphs"

    # --- demo override (hackathon key may be premium trial) ---
    override_plan_features: dict[str, Any] = {}

    model_config = {"env_prefix": "COOLCHAIN_", "env_file": ".env",
                    "extra": "ignore"}

    @property
    def effective_caps(self) -> dict[str, Any]:
        """Plan-derived caps, merged with any manual overrides."""
        caps = {
            "heatmap_area_sqmi": (
                50.0 if self.fortyguard_plan == Plan.PREMIUM
                else self.max_heatmap_area_sqmi
            ),
            "env_params_per_request": (
                999 if self.fortyguard_plan == Plan.PREMIUM
                else self.max_env_params_per_request
            ),
            "heat_intelligence": (
                self.heat_intelligence_enabled
                or self.fortyguard_plan == Plan.PREMIUM
            ),
            "satellite": self.satellite_enabled
            or self.fortyguard_plan == Plan.PREMIUM,
            "streetview": self.streetview_enabled
            or self.fortyguard_plan == Plan.PREMIUM,
        }
        caps.update(self.override_plan_features)
        return caps


def make_client(settings: Settings):
    """Build a FortyGuardClient from Settings (shared limiter/concurrency)."""
    from fortyguard_sdk import FortyGuardClient, TTLCache

    return FortyGuardClient(
        api_key=settings.fortyguard_api_key,
        plan=settings.fortyguard_plan,
        concurrency=5,
        cache=TTLCache(),
    )