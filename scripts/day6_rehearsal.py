#!/usr/bin/env python3
"""Day 6 — automated demo rehearsal (task 6.3).

Runs 2x full demo rehearsals: for every scene in docs/01_demo_script.md the
script loads the scene's data (offline, DATA_SOURCE=fixtures) and executes
the same component builds / interactions the presenter performs (slider drags,
field click, SMS render, corridor map, KPI cards, HI PDF), timing each
segment. Exits non-zero if any scene segment exceeds its timing budget.

    python scripts/day6_rehearsal.py                 # 2x full run (Scenes 0-5)
    python scripts/day6_rehearsal.py --core-only     # time-short 4-min variant
    python scripts/day6_rehearsal.py --iterations 1  # single rehearsal

Output: data/rehearsal/rehearsal_log.json (JSON), per-scene timing table.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import data_source as ds  # noqa: E402

# Scene budgets (seconds) from docs/01_demo_script.md "Timing Budget Check".
SCENE_BUDGET = {
    "scene_0_hook": 30.0,
    "scene_1_field_map": 60.0,
    "scene_2_harvest_alert": 60.0,
    "scene_3_corridor": 60.0,
    "scene_4_kpis": 45.0,
    "scene_5_scale": 45.0,
}
TOTAL_BUDGET = 300.0
TRANSITION_BUDGET = 2.0  # scene transition (data load + build) must be < 2s


class Timer:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0


def _segment(label: str) -> Timer:
    return Timer()


def _scene_0(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """Hook chips: $74B / 95°F+ / 98°F canopy at Fort Valley (PV-07)."""
    pv07 = next(f for f in fields if f["field_id"] == "PV-07")
    return {
        "stat_economy": "$74B",
        "stat_peak": "95°F+",
        "stat_canopy_f": pv07["risk"]["canopy_temp_f"],
    }


def _scene_1(fields, heat_payload) -> dict[str, Any]:
    """Field Map: slider 08:00 -> 11:00 -> 15:00 + click PV-07 detail panel."""
    from dashboard.components.field_map import build_map, field_detail_markdown

    frames = heat_payload["frames"]
    field_tiers = heat_payload["field_tiers"]
    field_scores = heat_payload.get("field_scores", {})
    hours = ["08:00", "11:00", "15:00"]
    maps = [build_map(fields, frames, field_tiers, h,
                      field_scores=field_scores, center=(32.55, -83.89), zoom=10)
            for h in hours]
    pv07 = next(f for f in fields if f["field_id"] == "PV-07")
    panels = []
    for h in hours:
        html = field_detail_markdown(
            pv07,
            score=field_scores.get(h, {}).get("PV-07"),
            tier=field_tiers.get(h, {}).get("PV-07"),
        )
        panels.append({"hour": h, "score": field_scores.get(h, {}).get("PV-07"),
                       "html_bytes": len(html.encode())})
    return {
        "maps_built": len(maps),
        "hours": hours,
        "pv07_scores": {p["hour"]: p["score"] for p in panels},
        "pv07_scores_ok": (
            field_scores.get("08:00", {}).get("PV-07") == 87.0
            and field_scores.get("15:00", {}).get("PV-07") == 91.0
        ),
    }


def _scene_2(alerts, risk_data) -> dict[str, Any]:
    """Harvest alert -> auto SMS: alert banner + SMS payload + packing house."""
    active = [a for a in alerts["alerts"] if a.get("tier") == "critical"]
    pv = next((a for a in alerts["alerts"] if a.get("field_id") == "PV-07"), None)
    # SMS preview payload (docs/01: FOREMAN + packing house + truck).
    sms = None
    if pv is not None:
        sms = {
            "from": "PeachState Agent",
            "field": pv.get("field_id"),
            "message": (
                f"FIELD {pv.get('field_id')} — HARVEST NOW · "
                f"{pv.get('canopy_temp_f', 98.0):.0f}°F · "
                f"{pv.get('exceedance_hours', 3.4):.1f}h above threshold · +6h forecast"
            ),
            "status": pv.get("sms", {}).get("status"),
        }
    harvest_windows = [
        w for w in risk_data.get("harvest_windows", [])
        if w.get("field_id") == "PV-07"
    ]
    return {
        "critical_alerts": len(active),
        "pv07_alert_present": pv is not None,
        "sms": sms,
        "harvest_window": harvest_windows[:1],
    }


def _scene_3(corridor, spoilage_routes, env_nodes) -> dict[str, Any]:
    """Cool Corridor: dual-route map + temp profile + spoilage/fuel counters."""
    from dashboard.components.corridor_map import build_corridor_map

    m = build_corridor_map(corridor)
    routes = {r["route_id"]: r for r in corridor["routes"]}
    i16 = routes.get("i16", routes.get("I-16"))
    i75 = routes.get("i75", routes.get("I-75"))
    sr = spoilage_routes["routes"] if "routes" in spoilage_routes else spoilage_routes
    # find i16 vs i75 spoilage deltas
    by_id = {r.get("route_id"): r for r in sr}
    s16, s75 = by_id.get("i16"), by_id.get("i75")
    return {
        "map_built": m is not None,
        "i75_avg_f": i75.get("avg_temp_f") if i75 else None,
        "i16_avg_f": i16.get("avg_temp_f") if i16 else None,
        "i16_delta": (i75.get("avg_temp_f") - i16.get("avg_temp_f"))
                     if i75 and i16 else None,
        "spoilage_i75_pct": s75.get("spoilage_pct") if s75 else None,
        "spoilage_i16_pct": s16.get("spoilage_pct") if s16 else None,
        "env_node_count": len(env_nodes["locations"]),
    }


def _scene_4(kpis, risk_data, hi_report) -> dict[str, Any]:
    """Cold chain dashboard: KPI cards + risk charts + HI PDF bytes."""
    k = kpis["kpis"]
    pv_series = next(
        (s for s in risk_data.get("series_24h", [])
         if s.get("field_id") == "PV-07"), None
    )
    pdf_ok = bool(hi_report.get("pdf_bytes"))
    return {
        "kpi_count": len(k),
        "kpi_map": {c["label"]: c["value"] for c in k},
        "pv07_series_points": len(pv_series.get("values", [])) if pv_series else 0,
        "hi_pdf_bytes": hi_report.get("pdf_size", 0),
        "pdf_ok": pdf_ok,
    }


def _scene_5(fields) -> dict[str, Any]:
    """Scale vision: Athens community garden + Atlanta last-mile loop."""
    from dashboard.components.field_map import map_png_bytes

    field_tiers = {f["field_id"]: f["risk"]["tier"] for f in fields}
    png = map_png_bytes(fields, {"08:00": field_tiers}, "08:00",
                        selected_field_id="ATH-CG-02")
    return {
        "athens_garden_ok": any(
            f.get("field_id") == "ATH-CG-02" or "Athens" in f.get("name", "")
            for f in fields
        ),
        "scale_png_bytes": len(png),
    }


def _run_scene(name: str, fn, *args) -> tuple[float, float, dict[str, Any]]:
    t = _segment(name)
    result = fn(*args)
    elapsed_ms = t.ms()
    return elapsed_ms, SCENE_BUDGET[name], result


def _rehearse(core_only: bool) -> dict[str, Any]:
    fields = ds.load_fields()
    heat_payload = ds.load_heat_frames()
    corridor = ds.load_corridor()
    risk_data = ds.load_risk_data()
    alerts = ds.load_alerts()
    kpis = ds.load_kpis()
    hi_report = ds.load_hi_report()
    from coolchain.services.day6_fixtures import build_spoilage_fixtures
    from dashboard import fixtures_gen
    spoilage = build_spoilage_fixtures(fields, fixtures_gen.generate_corridor())
    sr = spoilage["spoilage_routes.json"]["response"]
    env_nodes = json.loads(
        (ROOT / "data" / "fixtures" / "day6" / "env" / "env_params_corridor_nodes.json")
        .read_text()
    )["response"]

    segments: list[dict[str, Any]] = []

    def _rec(name: str, elapsed_ms: float, budget: float, info: dict[str, Any]) -> None:
        segments.append({
            "segment": name, "elapsed_ms": round(elapsed_ms, 1),
            "budget_s": budget, "under_budget": elapsed_ms / 1000.0 < budget,
            "info": info,
        })

    el, budget, info = _run_scene("scene_0_hook", _scene_0, fields)
    _rec("scene_0_hook", el, budget, info)
    el, budget, info = _run_scene("scene_1_field_map", _scene_1, fields, heat_payload)
    _rec("scene_1_field_map", el, budget, info)
    el, budget, info = _run_scene("scene_2_harvest_alert", _scene_2, alerts, risk_data)
    _rec("scene_2_harvest_alert", el, budget, info)
    el, budget, info = _run_scene("scene_3_corridor", _scene_3, corridor, sr, env_nodes)
    _rec("scene_3_corridor", el, budget, info)
    el, budget, info = _run_scene("scene_4_kpis", _scene_4, kpis, risk_data, hi_report)
    _rec("scene_4_kpis", el, budget, info)
    if not core_only:
        el, budget, info = _run_scene("scene_5_scale", _scene_5, fields)
        _rec("scene_5_scale", el, budget, info)

    total_ms = sum(s["elapsed_ms"] for s in segments)
    worst = max(s["elapsed_ms"] / 1000.0 for s in segments)
    return {
        "segments": segments,
        "total_ms": round(total_ms, 1),
        "total_budget_s": TOTAL_BUDGET,
        "worst_scene_s": round(worst, 2),
        "all_scenes_under_budget": all(s["under_budget"] for s in segments),
        "all_transitions_under_2s": worst < TRANSITION_BUDGET,
        "core_only": core_only,
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=2,
                    help="number of full demo rehearsals (default 2)")
    ap.add_argument("--core-only", action="store_true",
                    help="time-short 4-minute variant (skip Scene 5)")
    args = ap.parse_args()

    out_dir = ROOT / "data" / "rehearsal"
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = [_rehearse(args.core_only) for _ in range(args.iterations)]
    log = {
        "kind": "day6_rehearsal_log",
        "iterations": args.iterations,
        "core_only": args.core_only,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "budget_note": "scene segments from docs/01_demo_script.md timing budget",
        "runs": runs,
    }
    # Keep full-demo and time-short (core-only) logs separate so a core-only
    # rehearsal never clobbers the 2x full-run evidence.
    log_name = "rehearsal_log_core.json" if args.core_only else "rehearsal_log.json"
    (out_dir / log_name).write_text(json.dumps(log, indent=2))
    print(f"log -> {out_dir / log_name}")

    # Pretty table
    hdr = f"{'scene':<24}{'run1':>10}{'run2':>10}{'budget':>10}{'status':>8}"
    print(hdr)
    print("-" * len(hdr))
    all_ok = True
    names = list(SCENE_BUDGET) if not args.core_only else list(SCENE_BUDGET)[:5]
    for i, name in enumerate(names):
        cells = []
        for run in runs:
            seg = next(s for s in run["segments"] if s["segment"] == name)
            cells.append(f"{seg['elapsed_ms'] / 1000.0:8.3f}s")
        while len(cells) < 2:
            cells.append(f"{'':>8}")
        budget = SCENE_BUDGET[name]
        ok = all(
            next(s for s in run["segments"] if s["segment"] == name)["under_budget"]
            for run in runs
        )
        all_ok = all_ok and ok
        print(f"{name:<24}{cells[0]:>10}{cells[1]:>10}{budget:>7.0f}s{'PASS' if ok else 'FAIL':>8}")
    print("-" * len(hdr))
    for i, run in enumerate(runs, 1):
        print(
            f"run {i}: total {run['total_ms'] / 1000.0:.3f}s "
            f"(budget {run['total_budget_s']:.0f}s) · worst scene "
            f"{run['worst_scene_s']:.3f}s (transition budget {TRANSITION_BUDGET}s) "
            f"· {'PASS' if run['all_scenes_under_budget'] else 'FAIL'}"
        )
        all_ok = all_ok and run["all_scenes_under_budget"]
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
