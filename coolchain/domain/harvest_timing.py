"""PeachState CoolChain domain — harvest timing logic (Georgia crops).

Day 3: GDD tracking + heat stress + urgency -> HarvestAlert.

GDD (Growing Degree Days) daily accumulation from tcm mean:
    gdd_day = max(0, T_mean − base)          base per crop (°F)
    peach/blueberry 50°F, pecan 55°F, Vidalia onion 40°F (config-driven).

Heat stress days: count of days with max temp > crop alert_f.

Urgency score (0-100):
    gdd_progress = min(100, 100 · accumulated_gdd / gdd_target)
    stress_bonus  = min(30, heat_stress_days · 5)
    urgency       = gdd_progress + stress_bonus

Alert rule:
    urgency > 80 AND forecast_exceedance_12h > 6h
    (the FortyGuard API has no forecast — heatmap persistence/exceedance
    is used as the "staying hot" proxy).

Cooldown: 48h minimum between alerts per field (persisted in SQLite).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from .thresholds import crop_thresholds

# GA crop GDD parameters (base °F, harvest-stage target GDD, Q10).
# Source: data/crop_thresholds.json (single source of truth), refreshed below.
GA_CROP_GDD = {
    "peach":      {"gdd_base_f": 50.0, "harvest_gdd": 850.0, "q10": 2.8},
    "pecan":      {"gdd_base_f": 55.0, "harvest_gdd": 2200.0, "q10": 2.2},
    "blueberry":  {"gdd_base_f": 50.0, "harvest_gdd": 650.0, "q10": 3.2},
    "onion":      {"gdd_base_f": 40.0, "harvest_gdd": 950.0, "q10": 1.8},
    "watermelon": {"gdd_base_f": 55.0, "harvest_gdd": 1600.0, "q10": 2.5},
}

# Refresh GA_CROP_GDD from the canonical data file when available.
for _crop, _cfg in GA_CROP_GDD.items():
    _t = crop_thresholds(_crop)
    if "gdd_base_f" in _t:
        _cfg["gdd_base_f"] = float(_t["gdd_base_f"])
    if "gdd_target" in _t:
        _cfg["harvest_gdd"] = float(_t["gdd_target"])
    if "q10" in _t:
        _cfg["q10"] = float(_t["q10"])

# Day 3 rule constants.
HARVEST_URGENCY_THRESHOLD = 80.0
HARVEST_EXCEEDANCE_THRESHOLD_H = 6.0
HARVEST_COOLDOWN_H = 48.0


def gdd_daily(tmax_f: float, tmin_f: float, gdd_base_f: float) -> float:
    """Single-day Growing Degree Days (Baskerville-Emin approx ok for demo)."""
    if tmax_f is None or tmin_f is None:
        return 0.0
    avg = (tmax_f + tmin_f) / 2.0
    return max(0.0, avg - gdd_base_f)


def gdd_from_mean(mean_f: float, gdd_base_f: float) -> float:
    """Single-day GDD from a daily mean temperature (tcm-derived)."""
    if mean_f is None:
        return 0.0
    return max(0.0, mean_f - gdd_base_f)


def accumulate_gdd(
    mean_f_series: list[float | None], gdd_base_f: float
) -> float:
    """Accumulated GDD over a daily-mean temperature series."""
    return round(
        sum(gdd_from_mean(m, gdd_base_f) for m in mean_f_series if m is not None),
        1,
    )


def heat_stress_days(
    max_temp_f_series: list[float | None], alert_f: float
) -> int:
    """Count of days whose max temperature exceeded the crop alert threshold."""
    return sum(1 for t in max_temp_f_series if t is not None and t > alert_f)


def compute_urgency(
    gdd_accumulated: float, gdd_target: float, stress_days: int
) -> tuple[float, float, float]:
    """Return (gdd_progress_pct, stress_bonus, urgency)."""
    progress = min(100.0, 100.0 * gdd_accumulated / max(gdd_target, 1.0))
    bonus = min(30.0, stress_days * 5.0)
    urgency = min(100.0, progress + bonus)
    return round(progress, 1), round(bonus, 1), round(urgency, 1)


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def cooldown_active(
    last_alert_ts: str | None,
    now_ts: str | None = None,
    cooldown_h: float = HARVEST_COOLDOWN_H,
) -> bool:
    """True when a field's last alert is younger than `cooldown_h`."""
    last = _parse_ts(last_alert_ts)
    if last is None:
        return False
    now = _parse_ts(now_ts) if now_ts else datetime.now(timezone.utc)
    if now is None:
        return True
    return (now - last).total_seconds() < cooldown_h * 3600.0


def cooldown_until_ts(
    last_alert_ts: str | None, cooldown_h: float = HARVEST_COOLDOWN_H
) -> str | None:
    last = _parse_ts(last_alert_ts)
    if last is None:
        return None
    return (last + timedelta(hours=cooldown_h)).replace(microsecond=0).isoformat()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Day 3 output model
# ---------------------------------------------------------------------------
class HarvestAlert(BaseModel):
    field_id: str
    crop: str
    urgency: float
    gdd_progress_pct: float
    gdd_accumulated: float
    gdd_target: float
    stress_days: int
    stress_bonus: float
    forecast_exceedance_h: float
    triggered: bool
    recommended_action: str
    cooldown_until: str | None = None
    ts: str | None = None


def evaluate_harvest_alert(
    field_id: str,
    crop: str,
    *,
    gdd_accumulated: float,
    stress_days: int,
    forecast_exceedance_h: float,
    last_alert_ts: str | None = None,
    now_ts: str | None = None,
    urgency_threshold: float = HARVEST_URGENCY_THRESHOLD,
    exceedance_threshold_h: float = HARVEST_EXCEEDANCE_THRESHOLD_H,
    cooldown_h: float = HARVEST_COOLDOWN_H,
) -> HarvestAlert:
    """Day-3 harvest alert with GDD progress + stress bonus + 48h cooldown.

    Alert fires when urgency > threshold AND next-12h exceedance > threshold
    AND the 48h per-field cooldown is not active.
    """
    thr = crop_thresholds(crop)
    target = float(thr.get("gdd_target", GA_CROP_GDD.get(crop, GA_CROP_GDD["peach"])["harvest_gdd"]))
    progress, bonus, urgency = compute_urgency(gdd_accumulated, target, stress_days)

    now = _parse_ts(now_ts) if now_ts else datetime.now(timezone.utc)
    in_cooldown = cooldown_active(last_alert_ts, now_ts, cooldown_h)

    cooldown_until: str | None = None
    if last_alert_ts and in_cooldown:
        cooldown_until = cooldown_until_ts(last_alert_ts, cooldown_h)

    exceed_ok = forecast_exceedance_h > exceedance_threshold_h
    triggered = (
        urgency > urgency_threshold
        and exceed_ok
        and not in_cooldown
    )
    if triggered:
        cooldown_until = (
            (now + timedelta(hours=cooldown_h))
            .replace(microsecond=0)
            .isoformat()
            if now else None
        )

    if triggered:
        action = (
            f"HARVEST NOW — urgency {urgency:.0f}/100, GDD {progress:.0f}%, "
            f"{stress_days} heat-stress days, {forecast_exceedance_h:.1f}h "
            f"above threshold in next 12h"
        )
    elif in_cooldown and urgency > urgency_threshold and exceed_ok:
        action = (
            f"Cooldown active until {cooldown_until} — urgency "
            f"{urgency:.0f}/100 (GDD {progress:.0f}%, {stress_days} stress days)"
        )
    else:
        action = (
            f"Continue monitoring — urgency {urgency:.0f}/100 (need "
            f">{urgency_threshold:.0f} and >{exceedance_threshold_h:.0f}h "
            f"exceedance)"
        )

    return HarvestAlert(
        field_id=field_id,
        crop=crop,
        urgency=urgency,
        gdd_progress_pct=progress,
        gdd_accumulated=round(gdd_accumulated, 1),
        gdd_target=target,
        stress_days=int(stress_days),
        stress_bonus=bonus,
        forecast_exceedance_h=round(forecast_exceedance_h, 1),
        triggered=triggered,
        recommended_action=action,
        cooldown_until=cooldown_until,
        ts=now_ts or _utc_now(),
    )


# ---------------------------------------------------------------------------
# Legacy decision model (Pipeline B) — unchanged Day-2 behavior
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HarvestDecision:
    alert: bool
    field_id: str
    crop: str
    reason: str
    urgency: float = 0.0
    gdd_season: float = 0.0


def evaluate_harvest(
    field_id: str,
    crop: str,
    *,
    risk_score: float,
    persistence_h: float | None,
    gdd_season: float,
    warm_night: bool = False,
    urgency_threshold: float = 80.0,
    cooldown_ok: bool = True,
) -> HarvestDecision:
    """Rule: urgency >= 80 AND GDD_season >= crop.harvest_gdd AND cooldown ok.

    Urgency is a blend of current risk + persistence (past heat) + warm-night
    flag (GA nights stay >75°F — accelerates ripening).
    """
    params = GA_CROP_GDD.get(crop, GA_CROP_GDD["peach"])

    urgency = risk_score
    if persistence_h is not None:
        urgency += min(10.0, persistence_h * 2.0)
    if warm_night:
        urgency += 5.0
    urgency = min(urgency, 100.0)

    gdd_ok = gdd_season >= params["harvest_gdd"]
    if urgency < urgency_threshold:
        return HarvestDecision(False, field_id, crop, "urgency below threshold",
                               urgency, gdd_season)
    if not gdd_ok:
        return HarvestDecision(False, field_id, crop, "GDD season target not met",
                               urgency, gdd_season)
    if not cooldown_ok:
        return HarvestDecision(False, field_id, crop, "48h cooldown active",
                               urgency, gdd_season)
    return HarvestDecision(True, field_id, crop,
                           f"urgency={urgency:.0f} & GDD={gdd_season:.0f}",
                           urgency, gdd_season)


# ---------------------------------------------------------------------------
# SQLite integration (3.6): reads fields + heat_samples + risk_scores,
# writes alerts (cooldown persisted via the alerts table)
# ---------------------------------------------------------------------------
def _group_by_day(samples: list[Any]) -> dict[str, list[Any]]:
    days: dict[str, list[Any]] = {}
    for r in samples:
        ts = r["ts"] or ""
        days.setdefault(ts[:10], []).append(r)
    return days


def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def gdd_accumulate_from_samples(
    samples: list[Any], gdd_base_f: float
) -> float:
    """Accumulated GDD from persisted heat_sample daily means."""
    days = _group_by_day(samples)
    total = 0.0
    for day_rows in days.values():
        means = [r["mean_c"] for r in day_rows if r["mean_c"] is not None]
        if not means:
            means = [r["temp_c"] for r in day_rows if r["temp_c"] is not None]
        if means:
            mean_f = _c_to_f(sum(means) / len(means))
            total += gdd_from_mean(mean_f, gdd_base_f)
    return round(total, 1)


def stress_days_from_samples(samples: list[Any], alert_f: float) -> int:
    """Heat-stress days from persisted heat_sample daily max temps."""
    days = _group_by_day(samples)
    count = 0
    for day_rows in days.values():
        maxes = [r["max_c"] for r in day_rows if r["max_c"] is not None]
        if not maxes:
            maxes = [r["temp_c"] for r in day_rows if r["temp_c"] is not None]
        if maxes and _c_to_f(max(maxes)) > alert_f:
            count += 1
    return count


def evaluate_field_from_db(
    persistence,
    field_id: str,
    *,
    now_ts: str | None = None,
    cooldown_h: float = HARVEST_COOLDOWN_H,
    urgency_threshold: float = HARVEST_URGENCY_THRESHOLD,
    exceedance_threshold_h: float = HARVEST_EXCEEDANCE_THRESHOLD_H,
) -> HarvestAlert | None:
    """Evaluate a persisted field → HarvestAlert (writes alerts on trigger)."""
    fields = {r["id"]: r for r in persistence.load_fields()}
    f = fields.get(field_id)
    if f is None:
        return None
    crop = f["crop"] or "peach"
    thr = crop_thresholds(crop)
    base = (
        float(f["gdd_base_f"])
        if f["gdd_base_f"] is not None
        else float(thr.get("gdd_base_f", 50.0))
    )
    alert_f = float(thr.get("alert_f", 95.0))

    samples = persistence.heat_samples(field_id, limit=2000)
    gdd = gdd_accumulate_from_samples(samples, base)
    stress = stress_days_from_samples(samples, alert_f)

    # forecast proxy: latest persisted risk components' exceedance hours
    exceed_h = 0.0
    risks = persistence.risk_scores(field_id, limit=1)
    if risks:
        comps = json.loads(risks[0]["components_json"] or "{}")
        exceed_h = float(comps.get("exceedance_h", 0.0) or 0.0)

    last_alert = persistence.latest_alert_ts(field_id, alert_type="harvest")
    alert = evaluate_harvest_alert(
        field_id, crop,
        gdd_accumulated=gdd,
        stress_days=stress,
        forecast_exceedance_h=exceed_h,
        last_alert_ts=last_alert,
        now_ts=now_ts,
        urgency_threshold=urgency_threshold,
        exceedance_threshold_h=exceedance_threshold_h,
        cooldown_h=cooldown_h,
    )
    if alert.triggered:
        persistence.insert_alert(
            ts=alert.ts or now_ts or _utc_now(),
            field_id=field_id,
            alert_type="harvest",
            severity="HIGH",
            message=alert.recommended_action,
        )
    return alert


__all__ = [
    "HARVEST_URGENCY_THRESHOLD", "HARVEST_EXCEEDANCE_THRESHOLD_H",
    "HARVEST_COOLDOWN_H", "GA_CROP_GDD",
    "gdd_daily", "gdd_from_mean", "accumulate_gdd", "heat_stress_days",
    "compute_urgency", "cooldown_active", "cooldown_until_ts",
    "HarvestAlert", "evaluate_harvest_alert",
    "HarvestDecision", "evaluate_harvest",
    "gdd_accumulate_from_samples", "stress_days_from_samples",
    "evaluate_field_from_db",
]