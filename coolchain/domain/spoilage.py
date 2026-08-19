"""PeachState CoolChain domain — spoilage kinetics (Q10 model, GA crops).

Day 3: degree-hours + lethal-limit acceleration + cold-chain break detection
+ transit thermal box.

Degree-hours accumulation from a tcm time series (filter_type=2 range-of-hours):
    DH = Σ max(0, T_tile − threshold_f) · Δt_hours        per tile
    then area-weighted mean per field.

Lethal-limit term (accelerated decay):
    if T_tile > lethal_temp_f:  DH += (T_tile − lethal) · 10 · Δt

Spoilage risk:
    risk = min(100, 100 · DH / tolerance_deg_hours)
    tolerance_deg_hours per crop from crop_thresholds.json (Q10-derived).

Cold-chain break: trailer temp > setpoint + 3°F for > 30 min → flag.

Transit model (thermal box):
    T_p(t+Δt) = T_p + (T_amb − T_p) · (1 − exp(−Δt/τ)),  τ from insulation class.

Q10 params (USDA H66 / Kader): peach 2.5-3.0, blueberry ~3.0, onion ~2.0,
watermelon 2.0-2.5, pecan 1.5-2.0.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from .thresholds import crop_thresholds

# Crop transit thresholds (°F), Q10, lethal limit (°F), 100%-spoilage
# degree-hour tolerance, and reference respiration rate (relative).
GA_CROP_SPOILAGE = {
    "peach":      {"threshold_f": 95.0, "q10": 2.8,
                   "lethal_temp_f": 104.0, "tolerance_deg_hours": 480.0,
                   "ref_rate": 1.0},
    "pecan":      {"threshold_f": 95.0, "q10": 2.2,
                   "lethal_temp_f": 104.0, "tolerance_deg_hours": 600.0,
                   "ref_rate": 0.6},
    "blueberry":  {"threshold_f": 90.0, "q10": 3.2,
                   "lethal_temp_f": 100.0, "tolerance_deg_hours": 350.0,
                   "ref_rate": 1.4},
    "onion":      {"threshold_f": 85.0, "q10": 1.8,
                   "lethal_temp_f": 95.0, "tolerance_deg_hours": 720.0,
                   "ref_rate": 0.5},
    "watermelon": {"threshold_f": 95.0, "q10": 2.5,
                   "lethal_temp_f": 100.0, "tolerance_deg_hours": 520.0,
                   "ref_rate": 1.1},
}

# Refresh Q10 / thresholds / lethal / tolerance from the canonical file.
for _crop, _cfg in GA_CROP_SPOILAGE.items():
    _t = crop_thresholds(_crop)
    if "q10" in _t:
        _cfg["q10"] = float(_t["q10"])
    if "alert_f" in _t:
        _cfg["threshold_f"] = float(_t["alert_f"])
    if "lethal_temp_f" in _t:
        _cfg["lethal_temp_f"] = float(_t["lethal_temp_f"])
    if "tolerance_deg_hours" in _t:
        _cfg["tolerance_deg_hours"] = float(_t["tolerance_deg_hours"])

# Cold-chain break rules.
COLD_CHAIN_DELTA_F = 3.0       # setpoint + 3°F
COLD_CHAIN_MIN_BREAK_MIN = 30.0

# Insulation class -> thermal time constant τ (hours).
INSULATION_TAU_H = {"premium": 4.0, "standard": 6.0, "economy": 12.0}


def degree_hours(
    temp_series_c: list[float | None],
    threshold_f: float,
    interval_h: float = 1.0,
) -> float:
    """Accumulated degree-hours above threshold (°C series, legacy API)."""
    thr_c = (threshold_f - 32.0) * 5.0 / 9.0
    total = 0.0
    for t in temp_series_c:
        if t is None:
            continue
        total += max(0.0, t - thr_c) * interval_h
    return total


def degree_hours_f(
    temp_series_f: list[float | None],
    threshold_f: float,
    interval_h: float = 1.0,
    lethal_temp_f: float | None = None,
) -> float:
    """Day-3 degree-hours in °F with optional lethal-limit acceleration.

    DH = Σ max(0, T − threshold) · Δt  +  lethal term.
    """
    total = 0.0
    for t in temp_series_f:
        if t is None:
            continue
        total += max(0.0, t - threshold_f) * interval_h
        if lethal_temp_f is not None and t > lethal_temp_f:
            total += (t - lethal_temp_f) * 10.0 * interval_h
    return total


def area_weighted_degree_hours(
    tile_series_f: dict[str, list[float | None]],
    threshold_f: float,
    *,
    interval_h: float = 1.0,
    lethal_temp_f: float | None = None,
    weights: dict[str, float] | None = None,
) -> float:
    """Per-tile degree-hours → area-weighted mean per field."""
    weights = weights or {}
    total = 0.0
    wsum = 0.0
    for tile_id, series in tile_series_f.items():
        w = float(weights.get(tile_id, 1.0))
        total += degree_hours_f(series, threshold_f, interval_h,
                                lethal_temp_f) * w
        wsum += w
    return (total / wsum) if wsum else 0.0


def spoilage_risk_pct(dh: float, tolerance_deg_hours: float) -> float:
    """risk = min(100, 100 · DH / tolerance)."""
    return min(100.0, 100.0 * dh / max(tolerance_deg_hours, 1.0))


def detect_cold_chain_breaks(
    trailer_temp_f_series: list[float | None],
    setpoint_f: float = 34.0,
    delta_f: float = COLD_CHAIN_DELTA_F,
    min_break_min: float = COLD_CHAIN_MIN_BREAK_MIN,
    interval_h: float = 1.0,
) -> list[dict[str, Any]]:
    """Flag contiguous runs where trailer temp exceeds setpoint + delta
    for longer than `min_break_min`."""
    limit = setpoint_f + delta_f
    breaks: list[dict[str, Any]] = []
    start: int | None = None

    def _flush(end_idx: int) -> None:
        nonlocal start
        if start is None:
            return
        dur_min = (end_idx - start) * interval_h * 60.0
        if dur_min > min_break_min:
            run = [x for x in trailer_temp_f_series[start:end_idx]
                   if x is not None]
            breaks.append({
                "start_idx": start,
                "end_idx": end_idx - 1,
                "duration_min": round(dur_min, 1),
                "max_temp_f": round(max(run), 1) if run else None,
            })
        start = None

    for i, t in enumerate(trailer_temp_f_series):
        if t is not None and t > limit:
            if start is None:
                start = i
        else:
            _flush(i)
    _flush(len(trailer_temp_f_series))
    return breaks


def transit_thermal(
    t_amb_series_f: list[float | None],
    t_initial_f: float,
    tau_h: float = 6.0,
    interval_h: float = 1.0,
) -> list[float]:
    """Thermal box: T_p(t+Δt) = T_p + (T_amb − T_p)·(1 − exp(−Δt/τ))."""
    temps: list[float] = []
    t = t_initial_f
    for amb in t_amb_series_f:
        if amb is None:
            amb = t
        t = t + (amb - t) * (1.0 - math.exp(-interval_h / max(tau_h, 1e-6)))
        temps.append(round(t, 2))
    return temps


def estimate_shelf_life_days(
    dh: float,
    tolerance_deg_hours: float,
    base_shelf_life_days: float = 14.0,
) -> float:
    """Linear remaining-shelf-life: 100% at DH=0, 0 days at tolerance."""
    frac = min(1.0, dh / max(tolerance_deg_hours, 1.0))
    return round(max(0.0, base_shelf_life_days * (1.0 - frac)), 1)


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------
class SpoilageResult(BaseModel):
    field_id: str = ""
    crop: str = "peach"
    degree_hours: float = 0.0            # legacy name (also = dh_accumulated)
    dh_accumulated: float = 0.0          # Day-3 degree-hours (°F·h)
    spoilage_risk: float = 0.0           # 0..1 probability (legacy)
    risk_pct: float = 0.0                # 0..100 (Day 3)
    est_loss_usd: float = 0.0
    cold_chain_breaks: int = 0
    cold_chain_break_details: list[dict[str, Any]] = Field(default_factory=list)
    estimated_shelf_life_days: float = 0.0


def spoilage_risk(
    crop: str,
    temp_series_c: list[float | None],
    interval_h: float = 1.0,
    load_value_usd: float = 10000.0,
) -> SpoilageResult:
    """Legacy Q10 spoilage risk from °C series (dashboard KPI layer)."""
    params = GA_CROP_SPOILAGE.get(crop, GA_CROP_SPOILAGE["peach"])
    dh = degree_hours(temp_series_c, params["threshold_f"], interval_h)
    thr_c = (params["threshold_f"] - 32.0) * 5.0 / 9.0
    excess = [max(0.0, t - thr_c) for t in temp_series_c if t is not None]
    avg_excess = (sum(excess) / len(excess)) if excess else 0.0
    rate = params["ref_rate"] * (params["q10"] ** (avg_excess / 10.0))
    risk = 1.0 - math.exp(-0.02 * rate * dh)
    risk = min(1.0, max(0.0, risk))
    return SpoilageResult(
        crop=crop,
        degree_hours=round(dh, 1),
        dh_accumulated=round(dh, 1),
        spoilage_risk=round(risk, 3),
        risk_pct=round(risk * 100.0, 1),
        est_loss_usd=round(load_value_usd * risk, 2),
        estimated_shelf_life_days=estimate_shelf_life_days(
            dh, params["tolerance_deg_hours"]),
    )


def evaluate_spoilage(
    field_id: str,
    crop: str,
    temp_series_f: list[float | None],
    *,
    interval_h: float = 1.0,
    tile_series_f: dict[str, list[float | None]] | None = None,
    weights: dict[str, float] | None = None,
    trailer_temp_series_f: list[float | None] | None = None,
    setpoint_f: float = 34.0,
    load_value_usd: float = 10000.0,
    base_shelf_life_days: float = 14.0,
) -> SpoilageResult:
    """Day-3 spoilage evaluation (°F series, lethal term, cold-chain breaks)."""
    params = GA_CROP_SPOILAGE.get(crop, GA_CROP_SPOILAGE["peach"])
    threshold_f = params["threshold_f"]
    lethal = params["lethal_temp_f"]
    tol = params["tolerance_deg_hours"]

    if tile_series_f:
        dh = area_weighted_degree_hours(
            tile_series_f, threshold_f, interval_h=interval_h,
            lethal_temp_f=lethal, weights=weights,
        )
    else:
        dh = degree_hours_f(temp_series_f, threshold_f, interval_h, lethal)

    risk_pct = spoilage_risk_pct(dh, tol)
    breaks = (
        detect_cold_chain_breaks(
            trailer_temp_series_f, setpoint_f=setpoint_f, interval_h=interval_h)
        if trailer_temp_series_f else []
    )
    return SpoilageResult(
        field_id=field_id,
        crop=crop,
        degree_hours=round(dh, 1),
        dh_accumulated=round(dh, 1),
        spoilage_risk=round(risk_pct / 100.0, 3),
        risk_pct=round(risk_pct, 1),
        est_loss_usd=round(load_value_usd * risk_pct / 100.0, 2),
        cold_chain_breaks=len(breaks),
        cold_chain_break_details=breaks,
        estimated_shelf_life_days=estimate_shelf_life_days(
            dh, tol, base_shelf_life_days),
    )


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# SQLite integration (3.6): reads heat_samples / corridor_segments,
# writes spoilage_events
# ---------------------------------------------------------------------------
def evaluate_field_spoilage(
    persistence,
    field_id: str,
    *,
    ts: str | None = None,
    interval_h: float = 1.0,
) -> SpoilageResult | None:
    """Spoilage for a field from persisted heat_sample temps."""
    fields = {r["id"]: r for r in persistence.load_fields()}
    f = fields.get(field_id)
    crop = (f["crop"] if f else None) or "peach"
    samples = persistence.heat_samples(field_id, limit=2000)
    temps = [
        r["temp_f"] for r in sorted(samples, key=lambda r: r["ts"])
        if r["temp_f"] is not None
    ]
    if not temps:
        return None
    res = evaluate_spoilage(field_id, crop, temps, interval_h=interval_h)
    persistence.insert_spoilage_event(
        field_id, ts or _utc_now(), crop=crop,
        degree_hours_f=res.dh_accumulated, spoilage_risk=res.spoilage_risk,
        q10=GA_CROP_SPOILAGE.get(crop, GA_CROP_SPOILAGE["peach"])["q10"],
    )
    return res


def evaluate_route_spoilage(
    persistence,
    route_id: str,
    *,
    ts: str | None = None,
    interval_h: float = 1.0,
    crop: str = "peach",
    field_id: str | None = None,
) -> SpoilageResult | None:
    """Spoilage along a corridor route from persisted corridor_segments."""
    rows = persistence.corridor_samples(route_id, ts)
    temps = [
        r["temp_f"] for r in sorted(rows, key=lambda r: r["segment_id"])
        if r["temp_f"] is not None
    ]
    if not temps:
        return None
    res = evaluate_spoilage(
        field_id or f"route:{route_id}", crop, temps, interval_h=interval_h)
    persistence.insert_spoilage_event(
        field_id or f"route:{route_id}", ts or _utc_now(), crop=crop,
        degree_hours_f=res.dh_accumulated, spoilage_risk=res.spoilage_risk,
        q10=GA_CROP_SPOILAGE.get(crop, GA_CROP_SPOILAGE["peach"])["q10"],
    )
    return res


__all__ = [
    "GA_CROP_SPOILAGE", "COLD_CHAIN_DELTA_F", "COLD_CHAIN_MIN_BREAK_MIN",
    "INSULATION_TAU_H",
    "degree_hours", "degree_hours_f", "area_weighted_degree_hours",
    "spoilage_risk_pct", "detect_cold_chain_breaks", "transit_thermal",
    "estimate_shelf_life_days",
    "SpoilageResult", "spoilage_risk", "evaluate_spoilage",
    "evaluate_field_spoilage", "evaluate_route_spoilage",
]