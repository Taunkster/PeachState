"""PeachState CoolChain domain — canopy heat risk engine (Georgia crops).

Day 3: GA-normalized, crop-aware canopy risk (0-100 score -> tier).

Canopy temperature estimate (physical model):
    T_canopy = T_air + k·GHI − c·VPD          [°F]
      k   ≈ 0.005–0.01 °F per W/m² (per crop, from crop_thresholds.json)
      c   ≈ 0.5  transpirational cooling coefficient
      VPD computed from humidity + T_air (kPa)
      capped at T_air + 10 °F (physical bound)

Risk formula (weights per crop from crop_thresholds.json `risk_weights`):
    temp_score        = normalized canopy temp vs alert_f / critical_f
    exceedance_score  = normalized hours above threshold
    persistence_score = normalized longest continuous run
    risk = 100 · clamp(w_temp·temp_score + w_ex·exceedance + w_pers·persistence, 0, 1)

Growth-stage sensitivity: pre-harvest 2 weeks = 1.2×; otherwise 1.0×.
Worker safety sub-score: WBGT-based (OSHA/NIOSH), kept separate from crop risk.

Georgia crop thresholds are CANOPY/2m-AIR temperatures (°F) valid in GA's
humid subtropical climate:
    peach 95/100, pecan 95/100, blueberry 90/95, onion 85/90, watermelon 95/100
(alert / critical).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from fortyguard_sdk import GA_CROP_THRESHOLDS_F

from .thresholds import crop_thresholds

# Normalization ceilings for the heatmap analytic proxies (hours).
EXCEEDANCE_FULL_H = 8.0      # 8h above threshold -> exceedance_score 1.0
PERSISTENCE_FULL_H = 6.0     # 6h longest run -> persistence_score 1.0
CANOPY_CAP_F = 10.0          # T_canopy <= T_air + 10°F (physical bound)
VPD_COOLING_C = 0.5          # transpirational cooling coefficient

# Worker safety (OSHA/NIOSH heat-stress) WBGT bands, °F.
WBGT_BANDS = [
    (80.0, "LOW",       "No restriction — NIOSH recommended alert limit not reached."),
    (85.0, "MODERATE",  "Hydrate and take breaks — approaching NIOSH RAL."),
    (88.0, "HIGH",      "Reduced work/rest cycles — OSHA high-heat triggers apply."),
    (90.0, "VERY HIGH", "Limit strenuous work; shade + cool-down rotations."),
    (1e9,  "EXTREME",   "Stop strenuous outdoor work — NIOSH REL exceeded."),
]


class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def tier(score: float) -> RiskTier:
    if score >= 75:
        return RiskTier.CRITICAL
    if score >= 60:
        return RiskTier.HIGH
    if score >= 40:
        return RiskTier.MEDIUM
    return RiskTier.LOW


class RiskInputs(BaseModel):
    """Typed per-tile inputs. Temperatures in °C (API convention); the
    engine converts to °F for the GA-normalized formulas."""

    tcm_c: float | None = Field(
        default=None, description="heatmap tcm — 2m air temperature (°C)")
    exceedance_h: float | None = Field(
        default=None, description="hours above crop threshold")
    persistence_h: float | None = Field(
        default=None, description="longest continuous run above threshold (h)")
    humidity_pct: float | None = Field(default=None, description="relative humidity %")
    heat_index_c: float | None = Field(default=None, description="heat index (°C)")
    wbgt_c: float | None = Field(
        default=None, description="wet-bulb globe temperature (°C)")
    ghi: float | None = Field(
        default=None, description="global horizontal irradiance (W/m²)")
    timestamp: str | None = Field(default=None, description="observation time (ISO)")


class RiskResult(BaseModel):
    """Canopy heat risk output for one tile/field.

    `score` is the 0-100 crop risk; `worker_*` fields carry the separate
    OSHA/NIOSH worker-safety sub-score so the two never mix.
    """

    field_id: str
    score: float
    tier: RiskTier
    inputs: RiskInputs
    crop: str
    missing: tuple[str, ...] = ()
    canopy_temp_f: float | None = None
    components: dict[str, float] = Field(default_factory=dict)
    worker_wbgt_f: float | None = None
    worker_score: float | None = None
    worker_category: str | None = None
    worker_guidance: str | None = None
    stage_multiplier: float = 1.0
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "score": self.score,
            "tier": self.tier.value,
            "crop": self.crop,
            "missing": list(self.missing),
            "canopy_temp_f": self.canopy_temp_f,
            "components": self.components,
            "worker_wbgt_f": self.worker_wbgt_f,
            "worker_score": self.worker_score,
            "worker_category": self.worker_category,
            "timestamp": self.timestamp,
            "inputs": {k: v for k, v in self.inputs.model_dump().items()
                       if v is not None},
        }


@dataclass(frozen=True)
class WorkerSafetyResult:
    score: float
    category: str
    guidance: str


# ---------------------------------------------------------------------------
# Temperature / humidity physics
# ---------------------------------------------------------------------------
def _f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def _norm(value: float, lo: float, hi: float) -> float:
    """Normalize value into [0,1] clamped at [lo,hi]."""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _sat_vapor_pressure_kpa(temp_f: float) -> float:
    """Saturation vapor pressure (kPa) via Tetens (temp °F -> °C internally)."""
    tc = _f_to_c(temp_f)
    return 0.6108 * math.exp(17.27 * tc / (tc + 237.3))


def vpd_kpa(temp_f: float, humidity_pct: float) -> float:
    """Vapor pressure deficit (kPa) from air temp + relative humidity."""
    if humidity_pct is None:
        return 0.0
    es = _sat_vapor_pressure_kpa(temp_f)
    ea = es * max(0.0, min(100.0, humidity_pct)) / 100.0
    return max(0.0, es - ea)


def estimate_canopy_temp(
    t_air_f: float,
    ghi: float | None = None,
    humidity_pct: float | None = None,
    *,
    k: float = 0.008,
    c: float = VPD_COOLING_C,
    cap_f: float = CANOPY_CAP_F,
) -> float:
    """T_canopy = T_air + k·GHI − c·VPD, capped at T_air + cap_f.

    k: solar heating coefficient (0.005–0.01 °F per W/m², per crop).
    c: transpirational cooling coefficient (0.5).
    """
    solar = float(ghi) if ghi is not None else 0.0
    vpd = vpd_kpa(t_air_f, humidity_pct)
    canopy = t_air_f + k * solar - c * vpd
    return min(canopy, t_air_f + cap_f)


def normalized_temp_score(
    t_canopy_f: float, alert_f: float, critical_f: float
) -> float:
    """0 below alert; ramps to 1.0 at critical (and above)."""
    if t_canopy_f <= alert_f:
        return 0.0
    span = max(critical_f - alert_f, 1.0)
    return max(0.0, min(1.0, (t_canopy_f - alert_f) / span))


# ---------------------------------------------------------------------------
# Worker safety (separate from crop risk)
# ---------------------------------------------------------------------------
def worker_wbgt_subscore(wbgt_f: float | None) -> WorkerSafetyResult | None:
    """OSHA/NIOSH worker heat-stress sub-score (0-100) from WBGT °F."""
    if wbgt_f is None:
        return None
    score = _norm(wbgt_f, 78.0, 94.0) * 100.0
    for limit, cat, guide in WBGT_BANDS:
        if wbgt_f < limit:
            return WorkerSafetyResult(
                score=round(score, 1), category=cat, guidance=guide
            )
    return WorkerSafetyResult(score=100.0, category="EXTREME",
                              guidance=WBGT_BANDS[-1][2])


# ---------------------------------------------------------------------------
# Crop thresholds / weights
# ---------------------------------------------------------------------------
def _crop_alert_f(crop: str) -> float:
    t = crop_thresholds(crop)
    return float(t.get("alert_f", GA_CROP_THRESHOLDS_F.get(crop, 95.0)))


def _resolve_weights(
    crop: str, weights: dict[str, float] | None
) -> dict[str, float]:
    """Day-3 weights from crop config; accepts legacy/override dicts."""
    cfg = crop_thresholds(crop)
    rw = cfg.get("risk_weights") or {
        "temp": 0.45, "exceedance": 0.35, "persistence": 0.20,
    }
    if not weights:
        return rw
    if "temp" in weights:
        return {
            "temp": float(weights.get("temp", rw["temp"])),
            "exceedance": float(weights.get("exceedance", rw["exceedance"])),
            "persistence": float(weights.get("persistence", rw["persistence"])),
        }
    # legacy style: tcm/exceedance/persistence keys
    return {
        "temp": float(weights.get("tcm", rw["temp"])),
        "exceedance": float(weights.get("exceedance", rw["exceedance"])),
        "persistence": float(weights.get("persistence", rw["persistence"])),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Day 3 canopy heat risk engine
# ---------------------------------------------------------------------------
def canopy_heat_risk(
    field_id: str,
    inputs: RiskInputs,
    crop: str = "peach",
    *,
    weights: dict[str, float] | None = None,
    in_preharvest_window: bool = False,
    timestamp: str | None = None,
) -> RiskResult:
    """GA-normalized, crop-aware canopy risk (0-100 → tier).

    `in_preharvest_window`: pre-harvest 2 weeks -> 1.2× sensitivity multiplier.
    """
    thr = crop_thresholds(crop)
    alert_f = float(thr.get("alert_f", GA_CROP_THRESHOLDS_F.get(crop, 95.0)))
    critical_f = float(thr.get("critical_f", alert_f + 5.0))
    k = float(thr.get("canopy_k", 0.008))
    w = _resolve_weights(crop, weights)

    present = {name: v for name, v in {
        "tcm": inputs.tcm_c,
        "exceedance": inputs.exceedance_h,
        "persistence": inputs.persistence_h,
        "humidity": inputs.humidity_pct,
        "heat_index": inputs.heat_index_c,
        "wbgt": inputs.wbgt_c,
        "ghi": inputs.ghi,
    }.items() if v is not None}

    all_names = ("tcm", "exceedance", "persistence", "humidity",
                 "heat_index", "wbgt", "ghi")
    ts = timestamp or inputs.timestamp or _utc_now()

    if not present:
        return RiskResult(
            field_id=field_id, score=0.0, tier=RiskTier.LOW,
            inputs=inputs, crop=crop, missing=all_names, timestamp=ts,
        )

    missing = tuple(n for n in all_names if n not in present)

    # --- canopy temperature estimate ---------------------------------
    t_air_f = _c_to_f(inputs.tcm_c)  # type: ignore[arg-type]
    canopy_temp_f = estimate_canopy_temp(
        t_air_f, inputs.ghi, inputs.humidity_pct, k=k
    )

    # --- component scores --------------------------------------------
    temp_score = normalized_temp_score(canopy_temp_f, alert_f, critical_f)
    exceedance_score = _norm(inputs.exceedance_h or 0.0, 0.0, EXCEEDANCE_FULL_H)
    persistence_score = _norm(inputs.persistence_h or 0.0, 0.0, PERSISTENCE_FULL_H)

    risk = 100.0 * max(0.0, min(1.0, (
        w["temp"] * temp_score
        + w["exceedance"] * exceedance_score
        + w["persistence"] * persistence_score
    )))
    stage_mult = 1.2 if in_preharvest_window else 1.0
    risk = min(100.0, risk * stage_mult)
    risk = round(risk, 1)

    # --- worker safety (separate) ------------------------------------
    worker = worker_wbgt_subscore(
        _c_to_f(inputs.wbgt_c) if inputs.wbgt_c is not None else None
    )

    components = {
        "temp_score": round(temp_score, 3),
        "exceedance_score": round(exceedance_score, 3),
        "persistence_score": round(persistence_score, 3),
        "exceedance_h": round(inputs.exceedance_h or 0.0, 2),
        "persistence_h": round(inputs.persistence_h or 0.0, 2),
        "canopy_temp_f": round(canopy_temp_f, 2),
        "growth_stage_multiplier": stage_mult,
    }

    return RiskResult(
        field_id=field_id,
        score=risk,
        tier=tier(risk),
        inputs=inputs,
        crop=crop,
        missing=missing,
        canopy_temp_f=round(canopy_temp_f, 2),
        components=components,
        worker_wbgt_f=round(_c_to_f(inputs.wbgt_c), 1)
        if inputs.wbgt_c is not None else None,
        worker_score=worker.score if worker else None,
        worker_category=worker.category if worker else None,
        worker_guidance=worker.guidance if worker else None,
        stage_multiplier=stage_mult,
        timestamp=ts,
    )


def canopy_risk_score(
    field_id: str,
    inputs: RiskInputs,
    crop: str = "peach",
    weights: dict[str, float] | None = None,
) -> RiskResult:
    """Backward-compatible entry point (Pipeline A) → Day-3 engine."""
    return canopy_heat_risk(
        field_id, inputs, crop=crop, weights=weights,
        timestamp=inputs.timestamp,
    )


# ---------------------------------------------------------------------------
# SQLite integration (3.6): reads heat_samples + env_samples, writes risk_scores
# ---------------------------------------------------------------------------
def score_field_from_db(
    persistence,
    field_id: str,
    *,
    crop: str | None = None,
    ts: str | None = None,
    in_preharvest_window: bool = False,
) -> RiskResult | None:
    """Compute canopy risk for a field from persisted samples."""
    import json

    fields = {r["id"]: r for r in persistence.load_fields()}
    f = fields.get(field_id)
    crop = crop or (f["crop"] if f else None) or "peach"

    samples = persistence.heat_samples(field_id, limit=1000)
    envs = persistence.env_samples(field_id, limit=100)
    if not samples and not envs:
        return None

    ts = ts or (samples[0]["ts"] if samples else None) or _utc_now()
    tcm_c = next(
        (r["temp_c"] for r in samples
         if r["analytic_type"] in (None, "tcm") and r["temp_c"] is not None),
        None,
    )
    exceed = next(
        (r["temp_c"] for r in samples
         if r["analytic_type"] == "exceedance" and r["temp_c"] is not None),
        None,
    )
    persist = next(
        (r["temp_c"] for r in samples
         if r["analytic_type"] == "persistence" and r["temp_c"] is not None),
        None,
    )
    env = envs[0] if envs else None
    inputs = RiskInputs(
        tcm_c=tcm_c,
        exceedance_h=exceed,
        persistence_h=persist,
        humidity_pct=env["relative_humidity_percent"] if env else None,
        heat_index_c=_f_to_c(env["heat_index_f"])
        if env and env["heat_index_f"] is not None else None,
        wbgt_c=_f_to_c(env["wet_bulb_f"])
        if env and env["wet_bulb_f"] is not None else None,
        ghi=env["ghi_wm2"] if env else None,
        timestamp=ts,
    )
    result = canopy_heat_risk(
        field_id, inputs, crop=crop,
        in_preharvest_window=in_preharvest_window, timestamp=ts,
    )
    persistence.insert_risk_score(
        field_id, ts, crop=crop, score=result.score, tier=result.tier.value,
        canopy_temp_f=result.canopy_temp_f, worker_wbgt_f=result.worker_wbgt_f,
        components_json=json.dumps(result.components),
    )
    return result


__all__ = [
    "EXCEEDANCE_FULL_H", "PERSISTENCE_FULL_H", "CANOPY_CAP_F", "VPD_COOLING_C",
    "WBGT_BANDS",
    "RiskTier", "tier", "RiskInputs", "RiskResult", "WorkerSafetyResult",
    "vpd_kpa", "estimate_canopy_temp", "normalized_temp_score",
    "worker_wbgt_subscore", "canopy_heat_risk", "canopy_risk_score",
    "score_field_from_db", "GA_CROP_THRESHOLDS_F",
]