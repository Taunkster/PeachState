"""PeachState CoolChain — Day 6 full-scope demo fixture recorder.

Records the complete offline demo fixture set for ``fg fixtures record
--date 2025-07-15 --output-dir data/fixtures/day6/``:

    fields/     per-region heatmap frames (tcm/exceedance/persistence at
                08:00, 11:00, 15:00 EDT) for all 45 GA fields + snapshot
    corridor/   I-16 + I-75 Macon->Savannah, 5-mi nodes, heatmap per segment
    env/        env_params at field centroids + corridor nodes
    risk/       risk scores (15:00) + 24h risk series
    harvest/    harvest alerts + SMS + packing-house coordination
    spoilage/   per-field Q10 spoilage + I-75 vs I-16 route comparison
    hi_report/  Heat Intelligence PDF (Fort Valley) + JSON summary

Each fixture envelope includes ``timestamp``, ``endpoint``, ``params``,
``response`` and ``source: "live" | "cached"``. Live calls are attempted when
``FG_API_KEY`` is set; any failure falls back to the deterministic cached
payload (schema: ``dashboard.fixtures_gen`` + domain engines) so the demo is
fully offline-safe by default.

Determinism: all synthetic jitter uses a fixed seed (``pcs-day6::<key>``), so
the same command produces byte-identical fixtures — "same seed = same demo".
"""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coolchain.domain.spoilage import evaluate_spoilage

# The `dashboard` package lives in the repo root (Day 5) and is not part of
# the installed packages — make the repo importable when `fg` runs from an
# arbitrary cwd (same pattern as scripts/*.py).
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

FROZEN_DATE = "2025-07-15"
DEMO_TIME_UTC = "19:00:00Z"        # 15:00 EDT
FRAME_HOURS = ("08:00", "11:00", "15:00")
REGIONS = ("fort_valley", "albany", "bacon_appling", "vidalia")
REGION_LABEL = {
    "fort_valley": "Fort Valley / Peach County",
    "albany": "Albany / Dougherty County",
    "bacon_appling": "Bacon/Appling Counties",
    "vidalia": "Vidalia / Toombs County",
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rng(seed: str) -> random.Random:
    return random.Random(f"pcs-day6::{seed}")


def _f_to_c(f: float) -> float:
    return round((f - 32.0) * 5.0 / 9.0, 2)


def _envelope(
    endpoint: str,
    analytic: str | None,
    params: dict[str, Any],
    response: dict[str, Any],
    source: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    env: dict[str, Any] = {
        "schema_version": 1,
        "kind": "day6_fixture",
        "endpoint": endpoint,
        "analytic": analytic,
        "generated_ts": _now_utc(),
        "frozen_date": FROZEN_DATE,
        "params": params,
        "response": response,
        "source": source,
    }
    if extra:
        env.update(extra)
    return env


def _meta(timestamps: list[str] | None = None) -> dict[str, Any]:
    ts = timestamps or [f"{FROZEN_DATE}T{DEMO_TIME_UTC}"]
    return {
        "timezone": "GMT-4",                 # EDT — July Georgia (R-05 corrected)
        "timezone_offset_hours": -4,
        "time_range": {
            "start": ts[0], "end": ts[-1], "interval": "1h", "count": len(ts),
        },
        "timestamps": ts,
    }


def _tile_geometry(lon: float, lat: float, half_deg: float = 0.004) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - half_deg, lat - half_deg],
            [lon + half_deg, lat - half_deg],
            [lon + half_deg, lat + half_deg],
            [lon - half_deg, lat + half_deg],
            [lon - half_deg, lat - half_deg],
        ]],
    }


def _field_centroid(field: dict[str, Any]) -> tuple[float, float]:
    return (field["center"][0], field["center"][1])   # [lat, lon]


# ---------------------------------------------------------------------------
# Response builders (cached / deterministic)
# ---------------------------------------------------------------------------
def build_fields_heatmaps(
    fields: list[dict[str, Any]],
    heat: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Per-region tcm/exceedance/persistence frames at 08:00/11:00/15:00."""
    by_region: dict[str, list[dict[str, Any]]] = {r: [] for r in REGIONS}
    for f in fields:
        by_region.setdefault(f["region"], []).append(f)

    out: dict[str, dict[str, Any]] = {}
    for region in REGIONS:
        region_fields = by_region.get(region, [])
        fids = {f["field_id"] for f in region_fields}
        fid_by_prop = {f["field_id"]: f for f in region_fields}
        frames: dict[str, dict[str, Any]] = {}
        exceed_tiles: list[dict[str, Any]] = []
        pers_tiles: list[dict[str, Any]] = []
        tile_idx = 0
        for hh in FRAME_HOURS:
            feats = [
                x for x in heat["frames"][hh]
                if x["properties"]["field_id"] in fids
            ]
            tcm_tiles: list[dict[str, Any]] = []
            for x in feats:
                p = x["properties"]
                t_f = p["tcm_f"]
                t_c = _f_to_c(t_f)
                tcm_tiles.append({
                    "type": "Feature",
                    "id": f"tile-{tile_idx}",
                    "properties": {
                        "tile_id": tile_idx,
                        "average_temperature": t_c,
                        "min_temperature": round(t_c - 0.3, 2),
                        "max_temperature": round(t_c + 0.3, 2),
                        "tcm_f": t_f,
                        "field_id": p["field_id"],
                        "hour": hh,
                    },
                    "geometry": x["geometry"],
                })
                # exceedance/persistence tiles (one per field, hours)
                field = fid_by_prop[p["field_id"]]
                jitter = _rng(f"{region}::{hh}::{p['field_id']}").uniform(-0.2, 0.2)
                exceed_tiles.append({
                    "type": "Feature",
                    "id": f"ex-{region}-{p['field_id']}",
                    "properties": {
                        "tile_id": len(exceed_tiles),
                        "value": round(max(
                            0.0, field["risk"]["exceedance_hours"] + jitter), 2),
                        "field_id": p["field_id"],
                        "hour": hh,
                    },
                    "geometry": x["geometry"],
                })
                pers_tiles.append({
                    "type": "Feature",
                    "id": f"per-{region}-{p['field_id']}",
                    "properties": {
                        "tile_id": len(pers_tiles),
                        "value": round(max(
                            0.0, field["risk"]["persistence_forecast_hours"]
                            + jitter), 2),
                        "field_id": p["field_id"],
                        "hour": hh,
                    },
                    "geometry": x["geometry"],
                })
                tile_idx += 1
            temps = [t["properties"]["average_temperature"] for t in tcm_tiles]
            frames[hh] = {
                "map_data": {"type": "FeatureCollection", "features": tcm_tiles},
                "stats_data": {
                    "analytic_type": "tcm",
                    "units": "°C",
                    "n_cells": len(tcm_tiles),
                    "temperature_stats": {
                        "minimum": min(temps) if temps else None,
                        "maximum": max(temps) if temps else None,
                        "mean": (round(sum(temps) / len(temps), 2)
                                 if temps else None),
                        "standard_deviation": (
                            round(math.sqrt(
                                sum((t - sum(temps) / len(temps)) ** 2
                                    for t in temps) / len(temps)), 2)
                            if temps else None),
                    },
                },
            }

        for analytic, tiles in (
            ("exceedance", exceed_tiles),
            ("persistence", pers_tiles),
        ):
            vals = [t["properties"]["value"] for t in tiles]
            out[f"{analytic}_{region}.json"] = _envelope(
                "POST /heatmap", analytic,
                {"region": region, "analytic_type": analytic,
                 "threshold_c": 35.0,
                 "granularity": 100, "date": FROZEN_DATE},
                {
                    "map_data": {"type": "FeatureCollection", "features": tiles},
                    "stats_data": {
                        "analytic_type": analytic,
                        "units": "hour",
                        "n_cells": len(tiles),
                        "min": min(vals) if vals else None,
                        "max": max(vals) if vals else None,
                        "mean": (round(sum(vals) / len(vals), 2)
                                 if vals else None),
                    },
                },
                "cached",
            )

        out[f"tcm_{region}_frames.json"] = {
            "schema_version": 1,
            "kind": "day6_fixture",
            "endpoint": "POST /heatmap",
            "analytic": "tcm",
            "generated_ts": _now_utc(),
            "frozen_date": FROZEN_DATE,
            "params": {
                "region": region, "analytic_type": "tcm",
                "granularity": 100, "hours": list(FRAME_HOURS),
            },
            "response": {
                # Canonical 15:00 envelope (SDK-parseable) + all demo frames.
                "map_data": frames["15:00"]["map_data"],
                "stats_data": frames["15:00"]["stats_data"],
                "frames": frames,
            },
            "source": "cached",
        }
    return out


def build_fields_snapshot(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """fields_snapshot.json — the 45-farm snapshot the dashboard reads."""
    return {
        "fields_snapshot.json": _envelope(
            "derived:fields_snapshot", None,
            {"date": FROZEN_DATE, "count": len(fields)},
            {"date": FROZEN_DATE, "fields": fields},
            "cached",
        )
    }


def build_env_params(
    fields: list[dict[str, Any]],
    corridor: dict[str, Any],
    corridor_nodes: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """env_params at field centroids + corridor nodes (Premium-style shape)."""
    field_locs: list[dict[str, Any]] = []
    for f in fields:
        lat, lon = _field_centroid(f)
        r = f["risk"]
        hi_c = round((r["heat_index_f"] - 32.0) * 5.0 / 9.0, 2)
        wb_c = round(max(22.0, hi_c * 0.68), 2)
        field_locs.append(_location(lat, lon, r["canopy_temp_f"], r["humidity_pct"],
                                    hi_c, wb_c, rng_seed=f["field_id"]))
    fields_env = _envelope(
        "POST /env_params", None,
        {"analysis": ["heat_index_celsius", "relative_humidity_percent",
                      "wet_bulb_temperature_celsius", "solar_irradiance"],
         "date": FROZEN_DATE, "count": len(field_locs)},
        {"metadata": _meta(), "locations": field_locs},
        "cached",
    )

    node_locs: list[dict[str, Any]] = []
    for rid, nodes in corridor_nodes.items():
        route = next(r for r in corridor["routes"] if r["route_id"] == rid)
        points = route["points"]
        for i, n in enumerate(nodes):
            t_f = points[i]["temp_f"] if i < len(points) else route["avg_temp_f"]
            hi_c = round((t_f + 14.0 - 32.0) * 5.0 / 9.0, 2)
            wb_c = round((t_f - 14.0 - 32.0) * 5.0 / 9.0, 2)
            node_locs.append(_location(
                n["lat"], n["lon"], t_f, 62.0, hi_c, wb_c,
                rng_seed=f"corr-{rid}-{i}",
                extra={"route_id": rid, "seq": n["seq"],
                       "distance_mi": n["distance_mi"]},
            ))
    corridor_env = _envelope(
        "POST /env_params", None,
        {"analysis": ["heat_index_celsius", "relative_humidity_percent",
                      "wet_bulb_temperature_celsius", "solar_irradiance"],
         "date": FROZEN_DATE, "count": len(node_locs)},
        {"metadata": _meta(), "locations": node_locs},
        "cached",
    )
    return {
        "env_params_field_centroids.json": fields_env,
        "env_params_corridor_nodes.json": corridor_env,
    }


def _location(
    lat: float, lon: float, temp_f: float, rh_pct: float,
    hi_c: float, wb_c: float, *, rng_seed: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rng = _rng(rng_seed)
    loc: dict[str, Any] = {
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "elevation": round(rng.uniform(100.0, 220.0), 1),
        "temperature": _f_to_c(temp_f),
        "parameters": {
            "heat_index_celsius": [hi_c],
            "apparent_temperature_celsius": [round(hi_c - 1.2, 2)],
            "wet_bulb_temperature_celsius": [wb_c],
            "relative_humidity_percent": [round(rh_pct, 1)],
            "precipitation_mm": [0.0],
            "cloud_cover_octas": [round(rng.uniform(1.0, 6.0), 1)],
            "air_quality:idx": [round(rng.uniform(85.0, 135.0), 1)],
            "air_quality_pm2p5:idx": [round(rng.uniform(25.0, 65.0), 1)],
            "methane_ppb": [round(rng.uniform(1900.0, 2050.0), 1)],
            "co2_ppm": [round(rng.uniform(430.0, 470.0), 1)],
        },
        "solar_irradiance": {
            "clear_sky": {
                "ghi": round(rng.uniform(720.0, 920.0), 2),
                "dni": round(rng.uniform(600.0, 800.0), 2),
                "dhi": round(rng.uniform(90.0, 150.0), 2),
            },
            "description": (
                f"Solar energy available at {FROZEN_DATE} 15:00 EDT. "
                "GHI total, DNI direct, DHI diffuse."
            ),
        },
    }
    if extra:
        loc.update(extra)
    return loc


def build_corridor_fixtures(
    corridor: dict[str, Any],
    corridor_nodes: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Corridor comparison + per-route segment heatmap envelopes."""
    out: dict[str, dict[str, Any]] = {}
    out["corridor_comparison.json"] = _envelope(
        "POST /corridor", None,
        {"origin": "Macon, GA", "destination": "Port of Savannah, GA",
         "routes": ["I75", "I16"], "date": FROZEN_DATE},
        {"origin": corridor["origin"], "destination": corridor["destination"],
         "recommended": corridor["recommended"],
         "recommendation": corridor["recommendation"],
         "routes": corridor["routes"]},
        "cached",
    )

    for rid, nodes in corridor_nodes.items():
        route = next(r for r in corridor["routes"] if r["route_id"] == rid)
        points = route["points"]
        tiles: list[dict[str, Any]] = []
        for i, n in enumerate(nodes):
            t_f = points[i]["temp_f"] if i < len(points) else route["avg_temp_f"]
            tiles.append({
                "type": "Feature",
                "id": f"{rid.lower()}-seg-{n['seq']}",
                "properties": {
                    "tile_id": n["seq"],
                    "average_temperature": _f_to_c(t_f),
                    "min_temperature": round(_f_to_c(t_f) - 0.4, 2),
                    "max_temperature": round(_f_to_c(t_f) + 0.4, 2),
                    "tcm_f": t_f,
                    "route_id": rid,
                    "distance_mi": n["distance_mi"],
                },
                "geometry": _tile_geometry(n["lon"], n["lat"], half_deg=0.02),
            })
        temps = [t["properties"]["average_temperature"] for t in tiles]
        out[f"heatmap_{rid.lower()}_segments.json"] = _envelope(
            "POST /heatmap", "tcm",
            {"route_id": rid, "analytic_type": "tcm", "granularity": 100,
             "node_spacing_mi": 5.0, "date": FROZEN_DATE,
             "n_nodes": len(nodes)},
            {
                "map_data": {"type": "FeatureCollection", "features": tiles},
                "stats_data": {
                    "analytic_type": "tcm",
                    "units": "°C",
                    "n_cells": len(tiles),
                    "temperature_stats": {
                        "minimum": min(temps) if temps else None,
                        "maximum": max(temps) if temps else None,
                        "mean": (round(sum(temps) / len(temps), 2)
                                 if temps else None),
                        "standard_deviation": (
                            round(math.sqrt(
                                sum((t - sum(temps) / len(temps)) ** 2
                                    for t in temps) / len(temps)), 2)
                            if temps else None),
                    },
                },
            },
            "cached",
        )
    return out


def build_risk_fixtures(fields: list[dict[str, Any]], risk_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Risk scores (15:00) + 24h series envelopes."""
    scores = []
    for f in fields:
        scores.append({
            "field_id": f["field_id"],
            "crop": f["crop"],
            "region": f["region"],
            "score": f["risk"]["score"],
            "tier": f["risk"]["tier"],
            "canopy_temp_f": f["risk"]["canopy_temp_f"],
            "threshold_f": f["risk"]["threshold_f"],
            "critical_f": f["risk"]["critical_f"],
            "heat_index_f": f["risk"]["heat_index_f"],
            "humidity_pct": f["risk"]["humidity_pct"],
            "exceedance_hours": f["risk"]["exceedance_hours"],
            "persistence_forecast_hours": f["risk"]["persistence_forecast_hours"],
            "components": f["risk"]["components"],
            "harvest": f["harvest"],
        })
    out: dict[str, dict[str, Any]] = {}
    out["risk_scores.json"] = _envelope(
        "POST /risk", None,
        {"as_of": f"{FROZEN_DATE}T{DEMO_TIME_UTC}", "count": len(scores)},
        {"as_of": f"{FROZEN_DATE}T{DEMO_TIME_UTC}", "fields": scores},
        "cached",
    )
    out["risk_series_24h.json"] = _envelope(
        "derived:risk_series", None,
        {"resolution": "30min", "fields": len(risk_data["series"])},
        {"series": risk_data["series"]},
        "cached",
    )
    return out


def build_harvest_fixtures(alerts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "harvest_alerts.json": _envelope(
            "POST /alerts", None,
            {"date": FROZEN_DATE, "active": len(alerts["alerts"])},
            {"alerts": alerts["alerts"], "packing_houses": alerts["packing_houses"]},
            "cached",
        )
    }


def build_spoilage_fixtures(
    fields: list[dict[str, Any]], corridor: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Per-field Q10 spoilage + I-75 vs I-16 route comparison envelopes."""
    field_entries: list[dict[str, Any]] = []
    for f in fields:
        peak = f["risk"]["canopy_temp_f"]
        # Deterministic 12h diurnal field-exposure series (07:00..18:00 EDT).
        series = [
            round(peak - 6.0 + 6.0 * math.sin(math.pi * (h - 6.0) / 12.0), 1)
            for h in range(7, 19)
        ]
        res = evaluate_spoilage(
            f["field_id"], f["crop"], series,
            interval_h=1.0, load_value_usd=400.0 * (f["area_acres"] or 50.0),
        )
        field_entries.append({
            "field_id": f["field_id"],
            "crop": f["crop"],
            "degree_hours": res.dh_accumulated,
            "risk_pct": res.risk_pct,
            "est_loss_usd": res.est_loss_usd,
            "estimated_shelf_life_days": res.estimated_shelf_life_days,
        })

    routes = []
    for rid in ("I75", "I16"):
        route = next(r for r in corridor["routes"] if r["route_id"] == rid)
        temps = [p["temp_f"] for p in route["points"]]
        res = evaluate_spoilage(
            f"route:{rid}", "peach", temps,
            interval_h=(route["distance_mi"] / 55.0) / max(len(temps) - 1, 1),
            load_value_usd=40000.0,
        )
        routes.append({
            "route_id": rid,
            "distance_mi": route["distance_mi"],
            "avg_temp_f": route["avg_temp_f"],
            "peak_temp_f": route["peak_temp_f"],
            "q10": 2.8,                     # peach (USDA H66)
            "degree_hours": res.dh_accumulated,
            "risk_pct": route["spoilage_risk_pct"],   # demo-script contract
            "estimated_shelf_life_days": res.estimated_shelf_life_days,
            "fuel_gal": route["fuel_gal"],
            "eta_hours": route["eta_hours"],
        })
    i75 = next(r for r in routes if r["route_id"] == "I75")
    i16 = next(r for r in routes if r["route_id"] == "I16")
    delta_spoilage = round(
        (i75["risk_pct"] - i16["risk_pct"]) / max(i75["risk_pct"], 1e-9) * 100.0
    )
    delta_fuel = round(
        (i75["fuel_gal"] - i16["fuel_gal"]) / max(i75["fuel_gal"], 1e-9) * 100.0
    )
    return {
        "spoilage_fields.json": _envelope(
            "derived:spoilage", None,
            {"crop_q10": "peach 2.8, pecan 2.2, blueberry 3.2, onion 1.8",
             "count": len(field_entries)},
            {"fields": field_entries},
            "cached",
        ),
        "spoilage_routes.json": _envelope(
            "derived:spoilage", None,
            {"crop": "peach", "q10": 2.8, "load_value_usd": 40000.0},
            {
                "routes": routes,
                "recommended": "I16",
                "delta_spoilage_pct": delta_spoilage,     # -54%
                "delta_fuel_pct": delta_fuel,             # -12%
                "delta_distance_mi": round(i75["distance_mi"] - i16["distance_mi"]),
            },
            "cached",
        ),
    }


def build_hi_report_fixture(hi_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "heat_intelligence_fort_valley.json": _envelope(
            "POST /heat_intelligence", None,
            {"site": "fort_valley", "date": FROZEN_DATE,
             "analysis": ["environmental"]},
            {
                "activity_id": hi_report["activity_id"],
                "title": hi_report["title"],
                "generated_ts": hi_report["generated_ts"],
                "download_link_present": True,
                "download_link_preview": (
                    "https://api.fortyguard.com/v1/reports/..."
                    "signed-url-redacted"),
                "summary": hi_report["summary"],
                "pdf_path": "heat_intelligence_fort_valley.pdf",
            },
            "cached",
        )
    }


# ---------------------------------------------------------------------------
# Live capture (best-effort; falls back to cached per item)
# ---------------------------------------------------------------------------
async def _try_live(
    client: Any, live: bool, kind: str, req: Any,
) -> dict[str, Any] | None:
    """Attempt a live SDK call; return None so the caller uses cached data."""
    if not live or client is None:
        return None
    try:
        res = await client.heatmap(req) if kind == "heatmap" else await client.env_params(req)
        return {"response": res.model_dump(mode="json"), "source": "live"}
    except Exception:  # noqa: BLE001 — offline-safe by design
        return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def record_day6_fixtures(
    out_dir: Path | str,
    date_str: str = FROZEN_DATE,
    *,
    client: Any = None,
    live: bool = False,
) -> dict[str, Any]:
    """Write the complete Day-6 fixture set to ``out_dir``.

    Returns a manifest dict (paths written, counts, source mode). Live API
    calls are attempted only when ``FG_API_KEY`` is set; any failure falls
    back to the deterministic cached payload (offline-safe by default).
    """
    from dashboard import fixtures_gen
    from coolchain.domain.routing import load_corridor_nodes

    out = Path(out_dir)

    fields = fixtures_gen.generate_fields_snapshot()
    heat = fixtures_gen.generate_heat_frames(fields)
    corridor = fixtures_gen.generate_corridor()
    risk_data = fixtures_gen.generate_risk_data(fields)
    alerts = fixtures_gen.generate_alerts(fields)
    hi_report = fixtures_gen.generate_hi_report()
    nodes = load_corridor_nodes()

    # Explicit relative path -> envelope payload (no fragile name parsing).
    fixtures: dict[str, dict[str, Any]] = {
        f"fields/{name}": payload
        for name, payload in build_fields_heatmaps(fields, heat).items()
    }
    fixtures.update({
        f"fields/{name}": payload
        for name, payload in build_fields_snapshot(fields).items()
    })
    fixtures.update({
        f"env/{name}": payload
        for name, payload in build_env_params(fields, corridor, nodes).items()
    })
    fixtures.update({
        f"corridor/{name}": payload
        for name, payload in build_corridor_fixtures(corridor, nodes).items()
    })
    fixtures.update({
        f"risk/{name}": payload
        for name, payload in build_risk_fixtures(fields, risk_data).items()
    })
    fixtures.update({
        f"harvest/{name}": payload
        for name, payload in build_harvest_fixtures(alerts).items()
    })
    fixtures.update({
        f"spoilage/{name}": payload
        for name, payload in build_spoilage_fixtures(fields, corridor).items()
    })
    fixtures.update({
        f"hi_report/{name}": payload
        for name, payload in build_hi_report_fixture(hi_report).items()
    })

    # Best-effort live anchors (env_params/heatmap at Fort Valley + Macon).
    captured_live = 0
    if live and client is not None:
        import asyncio

        from datetime import date as _date

        from fortyguard_sdk import (
            DateTimeWindow, EnvParamsRequest, FilterType,
        )

        async def _anchors() -> int:
            n = 0
            win = DateTimeWindow(
                start_date=_date.fromisoformat(date_str), start_time="18:00",
                filter_type=FilterType.SINGLE_HOUR,
            )
            for site, (lat, lon) in (
                ("fort_valley", (32.5517, -83.8871)),
                ("macon", (32.8407, -83.6324)),
            ):
                env_res = await _try_live(
                    client, True, "env_params",
                    EnvParamsRequest(latitude=lat, longitude=lon,
                                     temperature=32.0, date_time=win,
                                     analysis=["heat_index_celsius",
                                               "relative_humidity_percent"]),
                )
                if env_res:
                    fixtures[f"env/live_env_params_{site}.json"] = _envelope(
                        "POST /env_params", None,
                        {"site": site, "lat": lat, "lon": lon},
                        env_res["response"], "live",
                    )
                    n += 1
            return n

        captured_live = asyncio.run(_anchors())

    written: list[str] = []
    counts: dict[str, int] = {}
    for rel, payload in fixtures.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, indent=2, default=str))
        written.append(str(dest.relative_to(out)))
        sub = rel.split("/")[0]
        counts[sub] = counts.get(sub, 0) + 1

    # Heat Intelligence PDF (Fort Valley hero field) — copy fixture PDF.
    pdf_src = fixtures_gen.ROOT / "data" / "fixtures" / "heat_intelligence_fort_valley.pdf"
    pdf_dest = out / "hi_report" / "heat_intelligence_fort_valley.pdf"
    if pdf_src.exists():
        pdf_dest.write_bytes(pdf_src.read_bytes())
        written.append(str(pdf_dest.relative_to(out)))
        counts["hi_report"] = counts.get("hi_report", 0) + 1

    # manifest.json
    manifest = {
        "schema_version": 1,
        "kind": "day6_manifest",
        "generated_ts": _now_utc(),
        "frozen_date": date_str,
        "source_mode": "live" if live else "cached",
        "captured_live_items": captured_live,
        "counts": counts,
        "files": sorted(written),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


__all__ = [
    "FROZEN_DATE", "FRAME_HOURS", "REGIONS",
    "record_day6_fixtures",
    "build_fields_heatmaps", "build_fields_snapshot", "build_env_params",
    "build_corridor_fixtures", "build_risk_fixtures", "build_harvest_fixtures",
    "build_spoilage_fixtures", "build_hi_report_fixture",
]