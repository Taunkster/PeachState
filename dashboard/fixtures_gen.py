"""PeachState CoolChain dashboard — deterministic demo fixture generation.

Day 5: pure, offline, seeded generation of every fixture the dashboard reads.
Used by ``scripts/gen_dashboard_fixtures.py`` to write ``data/fixtures/dashboard/*.json``
and as the runtime fallback in ``dashboard/data_source.py`` when a fixture file
is missing (so the app never renders garbage on a fresh checkout).

All temperatures are °F (Georgia audience — no silent C conversions).
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from shapely.geometry import shape as shapely_shape

from coolchain.domain.canopy_risk import RiskInputs, canopy_heat_risk
from coolchain.domain.harvest_timing import compute_urgency
from coolchain.domain.routing import (
    demo_route_temps,
    heat_exposure_integral,
    load_corridor_nodes,
)

ROOT = Path(__file__).resolve().parents[1]
FIELDS_GEOJSON = ROOT / "data" / "ga_fields.geojson"
CORRIDOR_NODES = ROOT / "data" / "corridor_nodes.json"

FROZEN_DATE = "2025-07-15"
DEFAULT_HOURS = [f"{h:02d}:00" for h in range(8, 18)]  # 08:00 .. 17:00 EDT

# Demo-script hero calibration for PV-07 (docs/01 + Day 6 contract):
#   "click PV-07 (risk 87 -> 91)" — side panel reads 87/100 CRITICAL at
#   08:00 EDT and 91/100 at the 15:00 EDT peak. The rest of the fields are
#   engine-computed; the hero is pinned so every scene matches the script
#   numbers exactly (risk 87 @ 08:00, 91 @ 15:00; 98°F; 3.4h; 71% RH;
#   112°F heat index; +6h persistence).
HERO_ID = "PV-07"
HERO_PEAK_SCORE = 91.0          # 15:00 EDT (Scene 2 alert banner)
HERO_MORNING_SCORE = 87.0       # 08:00 EDT (Scene 1 side panel)
HERO_HUMIDITY_PCT = 71.0        # demo script: "Humidity 71%"
HERO_HEAT_INDEX_F = 112.0       # demo script: "Heat index 112°F"
HERO_RISK_BY_HOUR: dict[int, float] = {
    0: 45.0, 1: 42.0, 2: 40.0, 3: 39.0, 4: 40.0, 5: 44.0,
    6: 52.0, 7: 68.0,
    8: 87.0, 9: 87.5, 10: 88.0, 11: 88.5, 12: 89.0, 13: 89.5,
    14: 90.5, 15: 91.0, 16: 90.0, 17: 88.5,
    18: 84.0, 19: 78.0, 20: 70.0, 21: 62.0, 22: 55.0, 23: 49.0,
}

# Region-level peak AIR temperature at 15:00 EDT (°F). The canopy engine
# adds solar heating (k·GHI ≈ +6°F) minus transpirational cooling, so these
# air values yield canopy temps in the 94-99°F band needed for a
# LOW/MEDIUM/HIGH/CRITICAL spread across the 45 farms.
REGION_BASE_F = {
    "fort_valley": 92.5,
    "albany": 91.2,
    "vidalia": 90.0,
    "bacon_appling": 88.8,
}
CROP_ADJ_F = {"peach": 0.3, "pecan": 0.0, "onion": -0.6, "blueberry": -1.2}

# Design-contract corridor totals (docs/02): I-75 318 mi / I-16 176 mi.
CORRIDOR_DIST_MI = {"I75": 318.0, "I16": 176.0}
CORRIDOR_STATS = {
    "I75": {"avg_temp_f": 97.1, "peak_temp_f": 102.4, "spoilage_risk_pct": 6.8,
            "fuel_gal": 132.0},
    "I16": {"avg_temp_f": 91.3, "peak_temp_f": 96.1, "spoilage_risk_pct": 3.1,
            "fuel_gal": 116.0},
}


def _rng(seed: str) -> random.Random:
    return random.Random(f"pcs-demo::{seed}")


# ---------------------------------------------------------------------------
# Heat index (NOAA Rothfusz approximation, °F)
# ---------------------------------------------------------------------------
def heat_index_f(t_f: float, rh_pct: float) -> float:
    if t_f < 80.0:
        return t_f
    hi = (
        0.5 * (t_f + 61.0 + (t_f - 68.0) * 1.2 + rh_pct * 0.094)
        + 0.0
    )
    if hi >= 80.0:
        hi = (
            -42.379 + 2.04901523 * t_f + 10.14333127 * rh_pct
            - 0.22475541 * t_f * rh_pct - 6.83783e-3 * t_f * t_f
            - 5.481717e-2 * rh_pct * rh_pct
            + 1.22874e-3 * t_f * t_f * rh_pct
            + 8.5282e-4 * t_f * rh_pct * rh_pct
            - 1.99e-6 * t_f * t_f * rh_pct * rh_pct
        )
    return round(max(hi, t_f), 1)


def _f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def _diurnal_rel(hour: int) -> float:
    """°F offset from the 15:00 peak for a given hour (parabolic curve).

    08:00 -> -6.0, 15:00 -> 0.0, 17:00 -> -0.5.
    """
    return -6.0 / 49.0 * (hour - 15.0) ** 2


def peak_temp_for(field: dict[str, Any], *, hero: bool = False) -> float:
    """Field peak AIR temperature at 15:00 EDT (the canopy engine adds solar)."""
    props = field["properties"]
    crop = props["crop"]
    region = props["region"]
    if hero:
        # PV-07 hero: air 92.2°F + 0.008*840 GHI - VPD cooling ~= canopy 98.2°F.
        return 92.2
    jitter = _rng(props["id"]).uniform(-1.0, 1.0)
    return REGION_BASE_F.get(region, 91.0) + CROP_ADJ_F.get(crop, 0.0) + jitter


def _exceedance_for(field_id: str, peak_f: float, alert_f: float,
                    hero: bool = False) -> float:
    """Hours-above-threshold, proportional to how far the field is past alert."""
    if hero:
        return 3.4
    rng = _rng(field_id + "::ex")
    above = max(0.0, peak_f - alert_f)
    return round(max(0.3, above * 0.5 + rng.uniform(0.4, 1.8)), 2)


def _persistence_for(field_id: str, exceed_h: float, hero: bool = False) -> float:
    if hero:
        return 6.0
    rng = _rng(field_id + "::pers")
    return round(max(0.8, exceed_h * 0.7 + rng.uniform(0.5, 2.0)), 2)


def _risk_for(field_id: str, crop: str, peak_f: float, exceed_h: float,
              pers_h: float, *, preharvest: bool = False) -> dict[str, Any]:
    thr = _crop_threshold(crop)
    hero = field_id == HERO_ID
    if hero:
        # Demo-script hero values (docs/01): 71% RH, 112°F heat index,
        # 91/100 risk at the 15:00 peak — pinned for exact script match.
        humidity, ghi = HERO_HUMIDITY_PCT, 840.0
    else:
        humidity = _rng(field_id + "::rh").uniform(52.0, 74.0)
        ghi = _rng(field_id + "::ghi").uniform(700.0, 900.0)
    inputs = RiskInputs(
        tcm_c=_f_to_c(peak_f),
        exceedance_h=exceed_h,
        persistence_h=pers_h,
        humidity_pct=humidity,
        ghi=ghi,
    )
    res = canopy_heat_risk(
        field_id, inputs, crop=crop, in_preharvest_window=preharvest,
        timestamp=f"{FROZEN_DATE}T19:00:00Z",
    )
    hi = heat_index_f(peak_f, humidity)
    if hero:
        # Pin the displayed hero values so Scene 1/2 match the script exactly.
        score, tier = HERO_PEAK_SCORE, "critical"
        hi = HERO_HEAT_INDEX_F
        canopy = res.canopy_temp_f if res.canopy_temp_f else peak_f
    else:
        score, tier, hi, canopy = (
            round(res.score, 1), res.tier.value, hi,
            round(res.canopy_temp_f or peak_f, 1),
        )
    return {
        "score": score,
        "tier": tier,
        "canopy_temp_f": round(canopy, 1),
        "threshold_f": thr["alert_f"],
        "critical_f": thr["critical_f"],
        "heat_index_f": hi,
        "humidity_pct": round(humidity, 1),
        "exceedance_hours": exceed_h,
        "persistence_forecast_hours": pers_h,
        "components": {
            "temp_score": res.components.get("temp_score", 0.0),
            "exceedance_score": res.components.get("exceedance_score", 0.0),
            "persistence_score": res.components.get("persistence_score", 0.0),
        },
    }


def _crop_threshold(crop: str) -> dict[str, Any]:
    data = json.loads((ROOT / "data" / "crop_thresholds.json").read_text())
    crops = data.get("crops", {})
    key = crop if crop in crops else {"peach": "peach"}.get(crop, "peach")
    return crops.get(key, {"alert_f": 95.0, "critical_f": 100.0})


# ---------------------------------------------------------------------------
# Fields snapshot
# ---------------------------------------------------------------------------
def generate_fields_snapshot(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Field + risk + harvest snapshot for every GA farm (45 fields)."""
    p = Path(path) if path else FIELDS_GEOJSON
    fc = json.loads(p.read_text())
    out: list[dict[str, Any]] = []
    for feature in fc["features"]:
        props = feature["properties"]
        fid = feature["id"]
        hero = fid == "PV-07"
        crop = props["crop"]
        thr = _crop_threshold(crop)

        peak = peak_temp_for(feature, hero=hero)
        exceed = _exceedance_for(fid, peak, thr["alert_f"], hero=hero)
        pers = _persistence_for(fid, exceed, hero=hero)
        preharvest = bool(props.get("stage_sensitivity_window"))
        risk = _risk_for(fid, crop, peak, exceed, pers, preharvest=preharvest)

        # Harvest window / urgency (deterministic per field).
        rng = _rng(fid + "::harvest")
        target = float(thr.get("gdd_target", 850.0))
        gdd = round(target * rng.uniform(0.55, 0.97), 1)
        stress_days = int(rng.uniform(2.0, 9.0))
        progress, bonus, urgency = compute_urgency(gdd, target, stress_days)
        window = (
            "NOW"
            if risk["tier"] == "critical" or urgency > 88
            else "07-14"
            if rng.random() < 0.5
            else "07-16"
        )

        geom = shapely_shape(feature["geometry"])
        cx, cy = geom.centroid.x, geom.centroid.y
        out.append({
            "field_id": fid,
            "name": props["name"],
            "crop": crop,
            "region": props["region"],
            "region_label": props.get("region_label", props["region"]),
            "area_acres": props.get("area_acres"),
            "packing_house_id": props.get("packing_house_id"),
            "center": [cy, cx],                       # [lat, lon]
            "polygon": feature["geometry"],
            "risk": risk,
            "harvest": {
                "urgency": round(urgency, 1),
                "window": window,
                "gdd_since_bloom": round(gdd, 1),
                "gdd_target": round(target, 1),
                "gdd_progress_pct": progress,
                "stress_days": stress_days,
            },
        })
    out.sort(key=lambda f: f["field_id"])
    return out


# ---------------------------------------------------------------------------
# Heat frames (time slider 08:00-17:00 EDT)
# ---------------------------------------------------------------------------
def generate_heat_frames(
    fields: list[dict[str, Any]] | None = None,
    hours: list[str] | None = None,
) -> dict[str, Any]:
    """Per-hour heat tile frames + per-hour field tiers.

    Returns ``{"frames": {"HH:00": [HeatFeature, ...]}, "field_tiers": {"HH:00": {fid: tier}}}``.
    Each field is tiled with a 4x4 grid over its bbox; tile temp = the
    field's diurnal temp at that hour + small seeded jitter. The per-hour
    field tier (drives polygon fill) is recomputed with the canopy engine so
    the slider visibly shifts green/yellow -> orange/red across the morning
    into the 15:00 peak.
    """
    fields = fields or generate_fields_snapshot()
    hours = hours or DEFAULT_HOURS
    frames: dict[str, list[dict[str, Any]]] = {}
    field_tiers: dict[str, dict[str, str]] = {}
    field_scores: dict[str, dict[str, float]] = {}

    meta: dict[str, dict[str, Any]] = {}
    for f in fields:
        thr = _crop_threshold(f["crop"])
        peak15 = f["risk"]["canopy_temp_f"]
        meta[f["field_id"]] = {
            "peak15": peak15, "alert_f": thr["alert_f"], "crop": f["crop"],
        }

    for hh in hours:
        hour = int(hh.split(":")[0])
        features: list[dict[str, Any]] = []
        tiers: dict[str, str] = {}
        scores: dict[str, float] = {}
        for f in fields:
            m = meta[f["field_id"]]
            base = m["peak15"] + _diurnal_rel(hour)      # diurnal canopy temp
            # Per-hour tier + score (consistent with the 15:00 snapshot when
            # hour == 15; the hero PV-07 follows the demo-script risk curve
            # 87 @ 08:00 -> 91 @ 15:00).
            if f["field_id"] == HERO_ID:
                hero_score = HERO_RISK_BY_HOUR[hour]
                res = canopy_heat_risk(
                    f["field_id"],
                    RiskInputs(
                        tcm_c=_f_to_c(base),
                        exceedance_h=f["risk"]["exceedance_hours"],
                        persistence_h=f["risk"]["persistence_forecast_hours"],
                        humidity_pct=HERO_HUMIDITY_PCT,
                        ghi=840.0 if 10 <= hour <= 18 else 60.0,
                    ),
                    crop=m["crop"],
                    in_preharvest_window=True,
                    timestamp=f"{FROZEN_DATE}T{hh}:00Z",
                )
                tier_now = "critical" if hero_score >= 75 else res.tier.value
                scores[f["field_id"]] = hero_score
            elif hour == 15:
                tier_now = f["risk"]["tier"]
                scores[f["field_id"]] = f["risk"]["score"]
            else:
                exceed = max(0.0, f["risk"]["exceedance_hours"] * (base / max(m["peak15"], 1e-9)))
                res = canopy_heat_risk(
                    f["field_id"],
                    RiskInputs(
                        tcm_c=_f_to_c(base),
                        exceedance_h=exceed,
                        persistence_h=f["risk"]["persistence_forecast_hours"],
                        humidity_pct=f["risk"]["humidity_pct"],
                        ghi=840.0 if 10 <= hour <= 18 else 60.0,
                    ),
                    crop=m["crop"],
                    in_preharvest_window=True,
                    timestamp=f"{FROZEN_DATE}T{hh}:00Z",
                )
                tier_now = res.tier.value
                scores[f["field_id"]] = round(res.score, 1)
            tiers[f["field_id"]] = tier_now

            geom = shapely_shape(f["polygon"])
            minx, miny, maxx, maxy = geom.bounds
            rng = _rng(f["field_id"] + f"::frame::{hh}")
            step = 4
            for i in range(step):
                for j in range(step):
                    x0 = minx + (maxx - minx) * i / step
                    y0 = miny + (maxy - miny) * j / step
                    x1 = minx + (maxx - minx) * (i + 1) / step
                    y1 = miny + (maxy - miny) * (j + 1) / step
                    t = round(base + rng.uniform(-0.6, 0.6), 1)
                    features.append({
                        "type": "Feature",
                        "properties": {
                            "hour": hh,
                            "tcm_f": t,
                            "analytic": "tcm",
                            "field_id": f["field_id"],
                            "tier": tier_now,
                            "risk_score": scores[f["field_id"]],
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0],
                            ]],
                        },
                    })
        frames[hh] = features
        field_tiers[hh] = tiers
        field_scores[hh] = scores
    return {"frames": frames, "field_tiers": field_tiers,
            "field_scores": field_scores}


# ---------------------------------------------------------------------------
# Corridor fixture (I-75 vs I-16, design-contract stats)
# ---------------------------------------------------------------------------
def generate_corridor() -> dict[str, Any]:
    """Dual-route corridor data: geometry + temp profile + summary cards."""
    nodes_by_route = load_corridor_nodes(CORRIDOR_NODES)
    demo = {rid: demo_route_temps(nds) for rid, nds in nodes_by_route.items()}

    routes: list[dict[str, Any]] = []
    for rid, nodes in nodes_by_route.items():
        total = CORRIDOR_DIST_MI[rid]
        stats = CORRIDOR_STATS[rid]
        last_d = nodes[-1]["distance_mi"] or 1.0

        # Affine-rescale the demo profile so its average matches the contract avg.
        raw = demo[rid]
        raw_avg = sum(raw) / len(raw)
        pts = []
        for n, t in zip(nodes, raw):
            d = n["distance_mi"] / last_d * total
            scaled = t - raw_avg + stats["avg_temp_f"]
            pts.append({
                "d_mi": round(d, 1),
                "temp_f": round(scaled, 1),
                "lat": n["lat"],
                "lon": n["lon"],
            })

        exposure = heat_exposure_integral(
            [{"distance_mi": p["d_mi"]} for p in pts],
            [p["temp_f"] for p in pts],
        )
        routes.append({
            "route_id": rid,
            "label": "I-75 · inland (hot)" if rid == "I75" else "I-16 · coastal (cool)",
            "distance_mi": total,
            "avg_temp_f": stats["avg_temp_f"],
            "peak_temp_f": stats["peak_temp_f"],
            "heat_exposure": round(exposure, 1),
            "spoilage_risk_pct": stats["spoilage_risk_pct"],
            "fuel_gal": stats["fuel_gal"],
            "eta_hours": round(total / 55.0, 2),
            "points": pts,
        })

    i75 = next(r for r in routes if r["route_id"] == "I75")
    i16 = next(r for r in routes if r["route_id"] == "I16")
    spoil_delta = round(
        (i75["spoilage_risk_pct"] - i16["spoilage_risk_pct"])
        / max(i75["spoilage_risk_pct"], 1e-9) * 100.0
    )
    fuel_delta = round(
        (i75["fuel_gal"] - i16["fuel_gal"]) / max(i75["fuel_gal"], 1e-9) * 100.0
    )
    dist_delta = round(i75["distance_mi"] - i16["distance_mi"])

    return {
        "origin": {"name": "Macon", "lat": 32.8407, "lon": -83.6324},
        "destination": {"name": "Port of Savannah", "lat": 32.0835, "lon": -81.0998},
        "routes": routes,
        "recommended": "I16",
        "recommendation": (
            f"I-16 saves {spoil_delta}% spoilage risk, {fuel_delta}% fuel, "
            f"{dist_delta} mi shorter"
        ),
        "spoilage_band_f": [85.0, 95.0],
    }


# ---------------------------------------------------------------------------
# Risk charts data (24h series + harvest windows + spoilage curve + radar)
# ---------------------------------------------------------------------------
def _ts(hour: int, minute: int = 0) -> str:
    dt = datetime(2025, 7, 15) + timedelta(hours=hour, minutes=minute)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def generate_risk_data(fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fields = fields or generate_fields_snapshot()
    series: list[dict[str, Any]] = []
    for f in fields:
        peak = f["risk"]["canopy_temp_f"]
        thr = _crop_threshold(f["crop"])
        for h in range(0, 24):
            for m in (0, 30):
                frac = (h + m / 60.0) / 24.0
                # diurnal wave: cool night -> hot afternoon
                t_f = peak - 6.0 + 6.0 * (0.5 - 0.5 * math.cos(2 * math.pi * (frac - 0.6)))
                exceed = f["risk"]["exceedance_hours"] * (0.2 + 0.8 * (t_f - (peak - 9)) / 9.0)
                exceed = max(0.0, min(8.0, exceed))
                res = canopy_heat_risk(
                    f["field_id"],
                    RiskInputs(
                        tcm_c=_f_to_c(t_f),
                        exceedance_h=exceed,
                        persistence_h=f["risk"]["persistence_forecast_hours"]
                        * max(0.0, (t_f - (peak - 9)) / 9.0),
                        humidity_pct=f["risk"]["humidity_pct"],
                        ghi=900.0 if 10 <= h <= 18 else 50.0,
                    ),
                    crop=f["crop"],
                    in_preharvest_window=True,
                    timestamp=_ts(h, m),
                )
                if f["field_id"] == HERO_ID:
                    # Hero curve: exact demo numbers (87 @ 08:00, 91 @ 15:00).
                    risk_score = HERO_RISK_BY_HOUR[h]
                    tier_name = "critical" if risk_score >= 75 else res.tier.value
                else:
                    risk_score = round(res.score, 1)
                    tier_name = res.tier.value
                series.append({
                    "field_id": f["field_id"],
                    "crop": f["crop"],
                    "ts": _ts(h, m),
                    "risk_score": risk_score,
                    "tier": tier_name,
                })

    # Harvest window timeline rows (one per field).
    windows = []
    for f in fields:
        windows.append({
            "field_id": f["field_id"],
            "crop": f["crop"],
            "urgency": f["harvest"]["urgency"],
            "tier": f["risk"]["tier"],
            "window": f["harvest"]["window"],
            "gdd_progress_pct": f["harvest"]["gdd_progress_pct"],
            "gdd_since_bloom": f["harvest"]["gdd_since_bloom"],
            "gdd_target": f["harvest"]["gdd_target"],
            "stress_days": f["harvest"]["stress_days"],
        })

    # Spoilage curve: degree-hours accumulation vs tolerance per crop.
    spoilage = []
    crops = sorted({f["crop"] for f in fields})
    for crop in crops:
        thr = _crop_threshold(crop)
        alert = thr["alert_f"]
        tol = float(thr.get("tolerance_deg_hours", 480.0))
        points = []
        acc = 0.0
        for h in range(0, 25):
            # transit ambient diurnal, warmest midday
            t_f = 96.0 + 3.0 * math.sin(math.pi * (h - 8.0) / 10.0)
            acc += max(0.0, t_f - alert) * 1.0
            points.append({"h": h, "dh": round(acc, 1)})
        spoilage.append({
            "crop": crop,
            "alert_f": alert,
            "tolerance_deg_hours": tol,
            "curve": points,
        })

    # Crop radar: average risk components per crop.
    radar = []
    for crop in crops:
        fs = [f for f in fields if f["crop"] == crop]
        n = max(len(fs), 1)
        radar.append({
            "crop": crop,
            "temp": round(sum(f["risk"]["components"]["temp_score"] for f in fs) / n, 3),
            "exceedance": round(
                sum(f["risk"]["components"]["exceedance_score"] for f in fs) / n, 3),
            "persistence": round(
                sum(f["risk"]["components"]["persistence_score"] for f in fs) / n, 3),
        })

    return {
        "series": series,
        "harvest_windows": windows,
        "spoilage": spoilage,
        "crop_radar": radar,
    }


# ---------------------------------------------------------------------------
# Harvest alerts + SMS + packing house coordination
# ---------------------------------------------------------------------------
def generate_packing_houses() -> list[dict[str, Any]]:
    return [
        {"facility_id": "PH-FV-01", "name": "Fort Valley Peach Co-op",
         "region": "fort_valley", "crop": "peach", "cold_storage_lb": 480000,
         "precool_capacity_lb_h": 42000},
        {"facility_id": "PH-AL-01", "name": "Albany Pecan Growers",
         "region": "albany", "crop": "pecan", "cold_storage_lb": 620000,
         "precool_capacity_lb_h": 38000},
        {"facility_id": "PH-VD-01", "name": "Vidalia Sweet Onion Co-op",
         "region": "vidalia", "crop": "onion", "cold_storage_lb": 900000,
         "precool_capacity_lb_h": 51000},
        {"facility_id": "PH-BA-01", "name": "Bacon/Appling Blueberry Packing",
         "region": "bacon_appling", "crop": "blueberry", "cold_storage_lb": 300000,
         "precool_capacity_lb_h": 26000},
        {"facility_id": "PH-SAV-01", "name": "Port of Savannah Cold Storage",
         "region": "savannah", "crop": "mixed", "cold_storage_lb": 2400000,
         "precool_capacity_lb_h": 120000},
    ]


def generate_alerts(fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fields = fields or generate_fields_snapshot()
    by_id = {f["field_id"]: f for f in fields}
    phs = {p["facility_id"]: p for p in generate_packing_houses()}

    hero = by_id["PV-07"]
    hero_sms = (
        "FIELD PV-07 — HARVEST NOW\n"
        f"{hero['risk']['canopy_temp_f']:.0f}°F · "
        f"{hero['risk']['exceedance_hours']:.1f}h above threshold · +6h forecast\n"
        "Packing house: Fort Valley Peach Co-op (pre-cool slot 4:30 PM)\n"
        "Truck: Reefer #212 dispatched · I-16 corridor"
    )
    alerts = [
        {
            "field_id": "PV-07", "crop": "peach", "tier": "critical",
            "canopy_temp_f": hero["risk"]["canopy_temp_f"],
            "urgency": 91.0, "threshold_f": 95.0,
            "exceedance_hours": hero["risk"]["exceedance_hours"],
            "recommended_action": "HARVEST_NOW",
            "ts": "2025-07-15T19:04:00Z",
            "acknowledged": False,
            "sms": {
                "from": "PeachState Agent",
                "to": "+1 (478) 555-0142 · Foreman M. Reed",
                "body": hero_sms,
                "status": "SENT",
                "sent_ts": "2025-07-15T19:04:00Z",
            },
            "packing_house": {
                "facility_id": "PH-FV-01",
                "name": "Fort Valley Peach Co-op",
                "precool_slot": "2025-07-15T20:30:00Z",
                "inbound_quantity": "12,400 lb",
                "truck_id": "Reefer #212",
                "cold_storage_lb": phs["PH-FV-01"]["cold_storage_lb"],
            },
        },
        {
            "field_id": "AL-04", "crop": "pecan", "tier": "high",
            "canopy_temp_f": 97.4, "urgency": 84.0, "threshold_f": 95.0,
            "exceedance_hours": 4.2,
            "recommended_action": "PREPARE_HARVEST",
            "ts": "2025-07-15T18:22:00Z",
            "acknowledged": False,
            "sms": None,
            "packing_house": {
                "facility_id": "PH-AL-01",
                "name": "Albany Pecan Growers",
                "precool_slot": "2025-07-15T21:00:00Z",
                "inbound_quantity": "8,600 lb",
                "truck_id": "Reefer #117",
                "cold_storage_lb": phs["PH-AL-01"]["cold_storage_lb"],
            },
        },
        {
            "field_id": "BA-03", "crop": "blueberry", "tier": "high",
            "canopy_temp_f": 94.1, "urgency": 82.0, "threshold_f": 90.0,
            "exceedance_hours": 5.1,
            "recommended_action": "HARVEST_NOW",
            "ts": "2025-07-15T17:58:00Z",
            "acknowledged": False,
            "sms": None,
            "packing_house": {
                "facility_id": "PH-BA-01",
                "name": "Bacon/Appling Blueberry Packing",
                "precool_slot": "2025-07-15T19:45:00Z",
                "inbound_quantity": "9,900 lb",
                "truck_id": "Reefer #088",
                "cold_storage_lb": phs["PH-BA-01"]["cold_storage_lb"],
            },
        },
        {
            "field_id": "VD-08", "crop": "onion", "tier": "medium",
            "canopy_temp_f": 88.9, "urgency": 71.0, "threshold_f": 85.0,
            "exceedance_hours": 3.0,
            "recommended_action": "MONITOR_CURING",
            "ts": "2025-07-15T16:40:00Z",
            "acknowledged": False,
            "sms": None,
            "packing_house": {
                "facility_id": "PH-VD-01",
                "name": "Vidalia Sweet Onion Co-op",
                "precool_slot": "2025-07-15T18:30:00Z",
                "inbound_quantity": "15,200 lb",
                "truck_id": "Reefer #305",
                "cold_storage_lb": phs["PH-VD-01"]["cold_storage_lb"],
            },
        },
        {
            "field_id": "PV-02", "crop": "peach", "tier": "high",
            "canopy_temp_f": 97.8, "urgency": 86.0, "threshold_f": 95.0,
            "exceedance_hours": 3.8,
            "recommended_action": "PREPARE_HARVEST",
            "ts": "2025-07-15T18:10:00Z",
            "acknowledged": False,
            "sms": None,
            "packing_house": {
                "facility_id": "PH-FV-01",
                "name": "Fort Valley Peach Co-op",
                "precool_slot": "2025-07-15T22:00:00Z",
                "inbound_quantity": "7,300 lb",
                "truck_id": "Reefer #206",
                "cold_storage_lb": phs["PH-FV-01"]["cold_storage_lb"],
            },
        },
    ]
    return {"alerts": alerts, "packing_houses": generate_packing_houses()}


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------
def generate_kpis() -> dict[str, Any]:
    return {
        "kpis": [
            {"id": "spoilage", "label": "Spoilage risk", "value": "↓ 23%",
             "delta": "-23 pp vs I-75 baseline", "direction": "down",
             "spark": [46, 43, 40, 36, 32, 27, 23], "tone": "green"},
            {"id": "savings", "label": "Season savings", "value": "$180K",
             "delta": "+$180K vs baseline", "direction": "up",
             "spark": [20, 60, 95, 125, 150, 168, 180], "tone": "peach"},
            {"id": "fuel", "label": "Fuel savings", "value": "12%",
             "delta": "-12% fuel / season", "direction": "down",
             "spark": [3, 5, 7, 9, 10, 11, 12], "tone": "blue"},
            {"id": "port", "label": "Port on-time", "value": "96%",
             "delta": "+14 pp vs baseline", "direction": "up",
             "spark": [82, 85, 89, 92, 94, 95, 96], "tone": "green"},
        ],
        "secondary": [
            "Carbon ↓41 t CO₂e",
            "45 fields protected",
            "1,240 loads routed",
            "5 packing houses synced",
        ],
        "detail": {
            "spoilage": "Seasonal spoilage risk reduction from cooler-corridor "
                        "routing (I-16 vs I-75) across 45 GA fields.",
            "savings": "Modeled $180K seasonal value: reduced spoilage losses, "
                       "fuel, and pre-cooling energy.",
            "fuel": "Reefer fuel reduction from 142 mi shorter average route "
                    "plus 7°F cooler coastal corridor.",
            "port": "Port of Savannah on-time deliveries rose from 82% baseline "
                    "to 96% with corridor routing + packing-house sync.",
        },
    }


# ---------------------------------------------------------------------------
# HI report
# ---------------------------------------------------------------------------
def generate_hi_report() -> dict[str, Any]:
    pdf = ROOT / "data" / "fixtures" / "heat_intelligence_fort_valley.pdf"
    return {
        "title": "Heat Intelligence Report — Fort Valley / Peach County",
        "activity_id": "a4f65006-9322-491a-adb2-a5b30a21ecad",
        "generated_ts": "2025-07-15T19:00:00Z",
        "pdf_path": str(pdf) if pdf.exists() else None,
        "pdf_bytes": None,
        "summary": {
            "region": "Fort Valley / Peach County, GA",
            "pages": 268,
            "sections": ["Geographic", "Environmental", "Urban", "Events",
                         "Anthropogenic"],
            "headline": "Extreme-heat window 13:00-18:00 EDT; canopy risk peaks "
                        "15:00; brown-rot acceleration risk on peach surfaces.",
        },
    }


def write_all_fixtures(out_dir: Path | str | None = None) -> list[Path]:
    """Generate + write every dashboard fixture to ``out_dir`` (default
    ``data/fixtures/dashboard``). Returns the written file paths."""
    out = Path(out_dir) if out_dir else ROOT / "data" / "fixtures" / "dashboard"
    out.mkdir(parents=True, exist_ok=True)

    fields = generate_fields_snapshot()
    payloads = {
        "fields_snapshot.json": fields,
        "heat_frames.json": generate_heat_frames(fields),
        "corridor.json": generate_corridor(),
        "risk_data.json": generate_risk_data(fields),
        "alerts.json": generate_alerts(fields),
        "kpis.json": generate_kpis(),
        "packing_houses.json": generate_packing_houses(),
        "hi_report.json": generate_hi_report(),
    }
    written: list[Path] = []
    for name, data in payloads.items():
        p = out / name
        p.write_text(json.dumps(data, indent=1))
        written.append(p)
    return written


__all__ = [
    "FROZEN_DATE", "DEFAULT_HOURS",
    "HERO_ID", "HERO_PEAK_SCORE", "HERO_MORNING_SCORE",
    "HERO_HUMIDITY_PCT", "HERO_HEAT_INDEX_F", "HERO_RISK_BY_HOUR",
    "generate_fields_snapshot", "generate_heat_frames", "generate_corridor",
    "generate_risk_data", "generate_alerts", "generate_kpis",
    "generate_packing_houses", "generate_hi_report", "write_all_fixtures",
]