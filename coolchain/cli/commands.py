"""PeachState CoolChain CLI - `fg` commands (Day 4).

Every command works in **live mode** (``FG_API_KEY`` set -> real FortyGuard
API) and in **fixture mode** (offline, canned responses from
``data/fixtures/day1``). JSON output goes to ``--output`` when given, else
pretty-printed to stdout. Exit code 0 = success, 1 = error.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

from coolchain.cli.context import (
    DEMO_DATE,
    DEMO_TIME,
    FIXTURES_DIR,
    CliContext,
    build_context,
    open_persistence,
)
from coolchain.services.persistence import Persistence

app = typer.Typer(
    help="PeachState CoolChain - Georgia thermal management from field to Port of Savannah.",
    no_args_is_help=True,
)
fixtures_app = typer.Typer(help="Record / list offline fixture data.")
db_app = typer.Typer(help="SQLite schema + status.")
app.add_typer(fixtures_app, name="fixtures")
app.add_typer(db_app, name="db")

console = Console()
_DEFAULT_CTX: CliContext | None = None


def _ctx() -> CliContext:
    """Build once per process (client reuse), overridable by tests."""
    global _DEFAULT_CTX
    if _DEFAULT_CTX is None:
        _DEFAULT_CTX = build_context()
    return _DEFAULT_CTX


def _dump(data: Any, output: Optional[str]) -> None:
    text = json.dumps(data, indent=2, default=str)
    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        console.print(f"[green]saved[/green] -> {out}")
    else:
        # soft_wrap: keep the JSON machine-readable when piped/captured
        console.print(text, soft_wrap=True, overflow="ignore")


def _fail(msg: str) -> None:
    console.print(f"[red]error:[/red] {msg}")
    raise typer.Exit(code=1)


def _window(date_str: str, time_str: str = DEMO_TIME):
    from fortyguard_sdk import DateTimeWindow, FilterType

    return DateTimeWindow(
        start_date=date.fromisoformat(date_str),
        start_time=time_str,
        filter_type=FilterType.SINGLE_HOUR,
    )


def _square_aoi(lat: float, lon: float, radius_mi: float) -> dict[str, Any]:
    """~2x2 km AOI around a point (radius_mi is the half-width in miles)."""
    half = radius_mi / 69.0  # 1 deg lat ~ 69 mi
    lon_half = half / max(__import__("math").cos(lat * 3.14159 / 180.0), 0.3)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"cli-{lat:.3f}-{lon:.3f}",
                "properties": {"crop": "peach"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [lon - lon_half, lat - half],
                        [lon + lon_half, lat - half],
                        [lon + lon_half, lat + half],
                        [lon - lon_half, lat + half],
                        [lon - lon_half, lat - half],
                    ]],
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# Live/offline data commands
# ---------------------------------------------------------------------------
@app.command()
def heatmap(
    lat: float = typer.Argument(..., help="Latitude (GA, 30.5..34.5)"),
    lon: float = typer.Argument(..., help="Longitude (GA, -85.5..-80.8)"),
    radius_mi: float = typer.Option(1.0, "--radius-mi", help="AOI half-width in miles"),
    granularity: int = typer.Option(100, "--granularity", min=60, max=100),
    analytic: str = typer.Option("tcm", "--analytic",
                                 help="tcm | exceedance | persistence | time_of_measure"),
    date_str: str = typer.Option(DEMO_DATE, "--date", help="YYYY-MM-DD"),
    output: Optional[str] = typer.Option(None, "--output", help="write JSON to file"),
) -> None:
    """Fetch a heatmap tile for a point AOI."""
    ctx = _ctx()
    from fortyguard_sdk import HeatmapRequest

    try:
        res = asyncio.run(
            ctx.client.heatmap(
                HeatmapRequest(
                    polygon_aoi=_square_aoi(lat, lon, radius_mi),
                    date_time=_window(date_str),
                    granularity=granularity,
                    analytic_type=analytic,  # type: ignore[arg-type]
                )
            )
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    payload = {
        "lat": lat, "lon": lon, "analytic_type": analytic,
        "date": date_str, "granularity": granularity,
        "mode": "live" if ctx.live else "fixtures",
        "n_cells": res.n_cells,
        "stats": res.stats_data.model_dump(mode="json"),
        "map_data": res.map_data,
    }
    _dump(payload, output)


@app.command("env-params")
def env_params(
    lat: float = typer.Argument(..., help="Latitude"),
    lon: float = typer.Argument(..., help="Longitude"),
    temperature: float = typer.Option(32.0, "--temperature", help="Air temp C (F9)"),
    params: str = typer.Option(
        "heat_index_celsius,relative_humidity_percent",
        "--params", help="comma-separated analysis params",
    ),
    date_str: str = typer.Option(DEMO_DATE, "--date", help="YYYY-MM-DD"),
    output: Optional[str] = typer.Option(None, "--output", help="write JSON to file"),
) -> None:
    """Fetch env_params (heat index, WBGT, humidity, solar, AQI) for a point."""
    ctx = _ctx()
    from fortyguard_sdk import EnvParamsRequest

    analysis = [p.strip() for p in params.split(",") if p.strip()]
    try:
        res = asyncio.run(
            ctx.client.env_params(
                EnvParamsRequest(
                    latitude=lat, longitude=lon, temperature=temperature,
                    date_time=_window(date_str), analysis=analysis,
                )
            )
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    payload = {
        "lat": lat, "lon": lon, "date": date_str,
        "mode": "live" if ctx.live else "fixtures",
        "metadata": res.metadata.model_dump(mode="json"),
        "locations": res.fahrenheit(),
    }
    _dump(payload, output)


@app.command()
def corridor(
    origin: str = typer.Argument("Macon", help="Origin anchor (name or lat,lon)"),
    destination: str = typer.Argument("Savannah", help="Destination anchor"),
    route: str = typer.Option("both", "--route", help="i16 | i75 | both"),
    output: Optional[str] = typer.Option(None, "--output", help="write JSON to file"),
) -> None:
    """Compare I-16 (coastal) vs I-75 (inland) heat exposure, Macon->Savannah."""
    from coolchain.domain.routing import compare_corridor_routes, load_corridor_nodes

    nodes = load_corridor_nodes()
    routes = {
        rid: nds for rid, nds in nodes.items()
        if route == "both" or rid.lower() == route.lower()
    }
    if not routes:
        _fail(f"no route matches {route!r} (use i16, i75, or both)")
    result = compare_corridor_routes(routes)
    payload = {
        "origin": origin, "destination": destination, "route_filter": route,
        "recommended": result.recommended,
        "saved_heat_exposure": result.saved_heat_exposure,
        "routes": [r.model_dump(mode="json") for r in result.routes],
    }
    _dump(payload, output)


# ---------------------------------------------------------------------------
# Domain commands (SQLite-backed)
# ---------------------------------------------------------------------------
@app.command()
def risk(
    field_id: str = typer.Argument(..., help="field id, e.g. PV-01"),
    date_str: Optional[str] = typer.Option(None, "--date", help="YYYY-MM-DD (as-of)"),
    output: Optional[str] = typer.Option(None, "--output", help="write JSON to file"),
) -> None:
    """Canopy heat risk score for a field (Pipeline A, from SQLite)."""
    from coolchain.domain.canopy_risk import score_field_from_db

    p = open_persistence(_ctx().db_path)
    try:
        res = score_field_from_db(p, field_id, ts=date_str)
    finally:
        p.close()
    if res is None:
        _dump({"field_id": field_id, "error": "no heat/env samples in DB "
               "(run `fg db init --demo` or wait for a monitor cycle)"}, output)
        return
    _dump(res.to_dict(), output)


@app.command()
def harvest(
    field_id: str = typer.Argument(..., help="field id, e.g. PV-01"),
    output: Optional[str] = typer.Option(None, "--output", help="write JSON to file"),
) -> None:
    """Harvest-timing evaluation (Pipeline B): GDD + urgency + 48h cooldown."""
    from coolchain.domain.harvest_timing import evaluate_field_from_db

    p = open_persistence(_ctx().db_path)
    try:
        alert = evaluate_field_from_db(p, field_id)
    finally:
        p.close()
    if alert is None:
        _dump({"field_id": field_id, "error": "field not found or no samples"}, output)
        return
    _dump(alert.model_dump(mode="json"), output)


@app.command()
def spoilage(
    route: str = typer.Argument(..., help="route (I16/I75) or field id"),
    output: Optional[str] = typer.Option(None, "--output", help="write JSON to file"),
) -> None:
    """Spoilage risk (Q10 degree-hours) for a corridor route or a field."""
    from coolchain.domain.spoilage import evaluate_field_spoilage, evaluate_route_spoilage

    p = open_persistence(_ctx().db_path)
    try:
        if route.upper() in ("I16", "I75"):
            res = evaluate_route_spoilage(p, route.upper())
        else:
            res = evaluate_field_spoilage(p, route)
    finally:
        p.close()
    if res is None:
        _dump({"target": route, "error": "no temperature samples"}, output)
        return
    _dump(res.model_dump(mode="json"), output)


@app.command("hi-report")
def hi_report(
    lat: float = typer.Argument(..., help="Latitude"),
    lon: float = typer.Argument(..., help="Longitude"),
    date_str: str = typer.Option(DEMO_DATE, "--date", help="YYYY-MM-DD"),
    output: Optional[str] = typer.Option(None, "--output", help="PDF output path"),
) -> None:
    """Heat Intelligence report: Premium PDF, or synthetic PDF on Basic."""
    ctx = _ctx()
    from coolchain.services.reporting import ReportService

    p = open_persistence(ctx.db_path)
    try:
        svc = ReportService(p)
        dest = (
            Path(output)
            if output
            else svc._out("pdf", f"hi_{lat:.3f}_{lon:.3f}_{date_str}.pdf")
        )
        path = asyncio.run(
            svc.fetch_hi_pdf(lat, lon, date_str, client=ctx.client, dest=dest)
        )
    finally:
        p.close()
    payload = {
        "mode": "live" if ctx.live else "fixtures",
        "lat": lat, "lon": lon, "date": date_str,
        "pdf": str(path),
        "bytes": path.stat().st_size,
        "note": ("Premium PDF" if ctx.live else
                 "synthetic report card (Basic-plan fallback)"),
    }
    _dump(payload, output if output and str(Path(output)).endswith(".json") else None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@fixtures_app.command()
def record(
    date_str: str = typer.Option(DEMO_DATE, "--date", help="YYYY-MM-DD"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir"),
    sites: str = typer.Option("fort_valley,macon,savannah,albany,vidalia",
                              "--sites", help="[deprecated] live-anchor sites; "
                              "the full 45-field + corridor scope is always "
                              "recorded (live or cached)."),
) -> None:
    """Record the Day-6 demo fixture set (offline-first; live when FG_API_KEY).

    Live API calls are attempted for anchor probes when ``FG_API_KEY`` is
    set; every other envelope falls back to the deterministic cached
    payload (``source: \"cached\"``), so the demo is fully offline-safe by
    default. Writes the full scope to ``data/fixtures/day6/``:
    ``{fields,corridor,env,risk,harvest,spoilage,hi_report}/``.
    """
    from coolchain.services.day6_fixtures import record_day6_fixtures

    ctx = _ctx()
    out = (
        Path(output_dir)
        if output_dir
        else Path(__file__).resolve().parents[2] / "data" / "fixtures" / "day6"
    )
    try:
        manifest = record_day6_fixtures(
            out, date_str=date_str, client=ctx.client, live=ctx.live
        )
    except Exception as exc:  # noqa: BLE001
        _fail(f"capture failed: {exc}")
    _dump(manifest, None)


def _write_fixture(path: Path, endpoint: str, probe: dict, response: dict) -> Path:
    payload = {
        "schema_version": 1,
        "kind": "day1_validation",
        "endpoint": endpoint,
        "generated_ts": datetime.now(timezone.utc).isoformat(),
        "probe": probe,
        "response": response,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


@fixtures_app.command("list")
def fixtures_list() -> None:
    """List recorded offline fixtures."""
    if not FIXTURES_DIR.exists():
        _dump({"fixtures": [], "dir": str(FIXTURES_DIR)}, None)
        return
    files = sorted(str(p.relative_to(FIXTURES_DIR.parent)) for p in FIXTURES_DIR.rglob("*") if p.is_file())
    _dump({"dir": str(FIXTURES_DIR), "count": len(files), "fixtures": files}, None)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def seed_fields(p: Persistence, geojson_path: Path | None = None) -> int:
    """Upsert GA fields from data/ga_fields.geojson (idempotent)."""
    path = geojson_path or Path(__file__).resolve().parents[2] / "data" / "ga_fields.geojson"
    fc = json.loads(path.read_text())
    n = 0
    for feat in fc["features"]:
        p.upsert_field(feat)
        n += 1
    return n


def seed_demo_data(p: Persistence) -> list[str]:
    """Seed synthetic heat/env samples + risk scores for a demo subset."""
    from coolchain.domain.canopy_risk import score_field_from_db
    from coolchain.domain.harvest_timing import evaluate_field_from_db
    from coolchain.domain.spoilage import evaluate_field_spoilage

    seeded: list[str] = []
    demo_fields = ["PV-01", "AL-01", "BB-01", "VD-01"]
    start = date(2026, 5, 1)
    for day in range(60):
        ts_day = (start + timedelta(days=day)).isoformat()
        mean_c = 30.0 + day * 0.10          # warm-up toward high summer
        temp_c = mean_c + 2.0
        for fid in demo_fields:
            p.insert_heat_sample(
                fid, f"{ts_day}T18:00:00Z", analytic_type="tcm",
                temp_c=temp_c, temp_f=_c_to_f(temp_c),
                min_c=temp_c - 1, max_c=temp_c + 3, mean_c=mean_c, n_cells=64,
            )
            p.insert_heat_sample(
                fid, f"{ts_day}T18:00:00Z", analytic_type="exceedance",
                temp_c=7.5, temp_f=7.5, n_cells=64,
            )
            p.insert_heat_sample(
                fid, f"{ts_day}T18:00:00Z", analytic_type="persistence",
                temp_c=5.0, temp_f=5.0, n_cells=64,
            )
        p.insert_env_sample(
            fid, f"{ts_day}T18:00:00Z",
            temperature_f=_c_to_f(temp_c), heat_index_f=_c_to_f(temp_c) + 8,
            wet_bulb_f=80.0, relative_humidity_percent=62.0, ghi_wm2=820.0,
        )
    for fid in demo_fields:
        score_field_from_db(p, fid)
        evaluate_field_from_db(p, fid)
        evaluate_field_spoilage(p, fid)
        seeded.append(fid)
    return seeded


def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


@db_app.command()
def init(
    demo: bool = typer.Option(False, "--demo", help="also seed synthetic demo samples"),
) -> None:
    """Initialize the SQLite schema and seed GA fields."""
    p = open_persistence(_ctx().db_path)
    try:
        p.init_schema()
        n = seed_fields(p)
        extra = []
        if demo:
            extra = seed_demo_data(p)
    finally:
        p.close()
    _dump({
        "db": str(_ctx().db_path),
        "tables": p.table_counts(),
        "fields_seeded": n,
        "demo_fields": extra,
    }, None)


@db_app.command()
def status() -> None:
    """Show table counts and last-sample timestamps."""
    p = open_persistence(_ctx().db_path)
    try:
        counts = p.table_counts()
        last = {}
        for table, col in (
            ("heat_samples", "ts"), ("env_samples", "ts"),
            ("risk_scores", "ts"), ("alerts", "ts"), ("reports", "created_at"),
        ):
            conn = p.reader()
            try:
                row = conn.execute(
                    f"SELECT MAX({col}) AS last_ts FROM {table}"
                ).fetchone()
                last[table] = row["last_ts"] if row else None
            finally:
                conn.close()
    finally:
        p.close()
    _dump({"db": str(_ctx().db_path), "counts": counts, "last_timestamps": last}, None)


# ---------------------------------------------------------------------------
# Serve (separate process from Streamlit)
# ---------------------------------------------------------------------------
@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port", min=1, max=65535),
    monitor_interval_min: int = typer.Option(15, "--interval-min"),
    run_cycle_on_start: bool = typer.Option(True, "--run-cycle-on-start/--no-run-cycle-on-start"),
) -> None:
    """Start the monitor orchestrator + FastAPI + scheduler (no Streamlit)."""
    import uvicorn

    from coolchain.services.api import create_app, create_scheduler
    from coolchain.services.monitor import MonitorConfig, MonitorService
    from coolchain.services.reporting import ReportService

    ctx = _ctx()
    p = open_persistence(ctx.db_path)
    p.init_schema()

    monitor = MonitorService(ctx.client, ctx.cache, p, MonitorConfig(plan=ctx.client.plan))
    reporting = ReportService(p)
    scheduler = create_scheduler(
        monitor, reporting, monitor_interval_min=monitor_interval_min
    )
    console.print(
        f"[green]scheduler ready[/green]: monitor every {monitor_interval_min} min, "
        "report daily 06:00 EDT"
    )

    if run_cycle_on_start:
        report = asyncio.run(monitor.cycle())
        console.print(f"[green]initial monitor cycle[/green]: {report.to_dict()}")

    app_api = create_app(
        monitor=monitor, reporting=reporting, persistence=p, scheduler=scheduler
    )
    console.print(f"[green]PeachState CoolChain monitor API[/green] http://{host}:{port}")
    uvicorn.run(app_api, host=host, port=port, log_level="info")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

__all__ = ["app", "main", "seed_fields", "seed_demo_data"]