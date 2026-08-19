"""PeachState CoolChain services - FastAPI app + APScheduler (Day 4).

The monitoring + reporting background jobs run in a **separate process**
from Streamlit (`fg serve`): Streamlit only reads SQLite.

Endpoints:
    GET  /health           liveness probe
    GET  /status           monitor state summary + DB counts
    POST /trigger/cycle    manual monitor cycle
    POST /trigger/report   on-demand daily report bundle
    GET  /reports          report index
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException

# ---------------------------------------------------------------------------
# Scheduler (APScheduler 3.x AsyncIOScheduler)
# ---------------------------------------------------------------------------
def create_scheduler(
    monitor: Any,
    reporting: Any,
    *,
    monitor_interval_min: int = 15,
    report_hour: int = 6,
    report_minute: int = 0,
    timezone: str = "America/New_York",
):
    """AsyncIOScheduler with the 15-min monitor + daily 06:00 EDT report."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        monitor.cycle,
        IntervalTrigger(minutes=monitor_interval_min),
        id="monitor-cycle",
        name="Monitor 15-min cadence",
        replace_existing=True,
    )
    scheduler.add_job(
        reporting.generate_daily,
        CronTrigger(hour=report_hour, minute=report_minute, timezone=timezone),
        args=[date.today().isoformat()],
        id="daily-report",
        name="Daily 06:00 EDT pre-harvest briefing",
        replace_existing=True,
    )
    return scheduler


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
def create_app(
    monitor: Any = None,
    reporting: Any = None,
    persistence: Any = None,
    scheduler: Any = None,
) -> FastAPI:
    """Build the control-plane FastAPI app (no Streamlit dependency).

    ``scheduler`` (an unstarted APScheduler) is started/stopped inside the
    ASGI lifespan so it runs on the uvicorn event loop.
    """
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if scheduler is not None:
            scheduler.start()
        yield
        if scheduler is not None and getattr(scheduler, "running", False):
            scheduler.shutdown(wait=False)

    app = FastAPI(
        title="PeachState CoolChain - Monitor API",
        description="Control plane for the 15-min monitoring orchestrator, "
        "alerting, and daily reporting. Streamlit reads SQLite directly.",
        version="0.4.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness + data-source state (Day 7 §7.2).

        Returns ``{status, data_source, last_live_ok, cache_age_s, ...}`` so
        an ops dashboard (or a judge) can see at a glance whether the live
        FortyGuard source is healthy or the app is running on fixtures.
        """
        from coolchain.services.fallback import health_status

        return health_status()

    @app.get("/status")
    async def status() -> dict[str, Any]:
        state = monitor.state_summary() if monitor else {}
        counts = persistence.table_counts() if persistence else {}
        return {"monitor": state, "db": counts}

    @app.post("/trigger/cycle")
    async def trigger_cycle() -> dict[str, Any]:
        if monitor is None:
            raise HTTPException(status_code=503, detail="monitor not configured")
        report = await monitor.cycle()
        return {"ok": True, "cycle": report.to_dict()}

    @app.post("/trigger/report")
    async def trigger_report() -> dict[str, Any]:
        if reporting is None:
            raise HTTPException(status_code=503, detail="reporting not configured")
        files = reporting.generate_daily(date.today().isoformat())
        return {
            "ok": True,
            "files": {k: str(v) for k, v in files.items()},
        }

    @app.get("/reports")
    async def reports() -> dict[str, Any]:
        if reporting is None:
            raise HTTPException(status_code=503, detail="reporting not configured")
        return {"reports": reporting.list_reports()}

    return app


__all__ = ["create_app", "create_scheduler"]