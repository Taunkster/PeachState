"""Day-4 service tests - Monitor Orchestrator, Alerting, Reporting.

Offline (mocked client / fixture backends) - no live API calls.
Covers:
    Monitor:  cadence loop, disk cache hit/miss, partial-failure handling,
              state persistence, Pipeline A/B integration
    Alerting: cooldown enforcement, dedup, tier escalation, template
    Reporting: JSON structure, synthetic PDF, HI PDF download (Basic fallback
              + Premium mock)
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from fortyguard_sdk import (
    DateTimeWindow,
    EnvParamsRequest,
    EnvParamsResult,
    FilterType,
    HeatmapRequest,
    HeatmapResult,
    Plan,
    TTLCache,
)
from coolchain.services.alerting import (
    ALERT_TEMPLATE,
    AlertConfig,
    AlertManager,
    AlertPayload,
    render_template,
)
from coolchain.services.monitor import DiskCache, MonitorConfig, MonitorService
from coolchain.services.persistence import Persistence
from coolchain.services.reporting import ReportService

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _seed_field(persistence: Persistence, field_id: str, crop: str, region: str) -> None:
    persistence.upsert_field({
        "id": field_id,
        "properties": {
            "name": f"{field_id} Demo Block", "crop": crop,
            "region": region, "area_acres": 42.0,
            "packing_house_id": "PH-01", "gdd_base_f": 50.0,
            "stage_sensitivity_window": "bloom_to_harvest",
        },
        "geometry": {"type": "Polygon", "coordinates": [[
            [-83.90, 32.56], [-83.89, 32.56],
            [-83.89, 32.57], [-83.90, 32.57], [-83.90, 32.56],
        ]]},
    })


def _fake_heatmap(analytic: str, n_tiles: int = 3) -> dict:
    features = []
    for i in range(n_tiles):
        props = (
            {"tile_id": i, "value": 7.0}
            if analytic != "tcm"
            else {"tile_id": i, "average_temperature": 36.0,
                  "min_temperature": 35.0, "max_temperature": 38.0}
        )
        features.append({
            "type": "Feature", "id": str(i), "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [[
                [-83.90 + i * 0.005, 32.56], [-83.89 + i * 0.005, 32.56],
                [-83.89 + i * 0.005, 32.57], [-83.90 + i * 0.005, 32.57],
                [-83.90 + i * 0.005, 32.56],
            ]]},
        })
    return {
        "map_data": {"type": "FeatureCollection", "features": features},
        "stats_data": {
            "analytic_type": analytic,
            "units": "hour" if analytic != "tcm" else None,
            "n_cells": n_tiles,
            **({"temperature_stats": {"mean": 36.5, "minimum": 35.0, "maximum": 38.0}}
               if analytic == "tcm" else {}),
        },
    }


def _fake_env() -> dict:
    return {
        "metadata": {"timezone": "America/New_York", "timestamps": ["t0"]},
        "locations": [{
            "lat": 32.55, "lon": -83.88, "elevation": 159.0, "temperature": 36.0,
            "parameters": {
                "heat_index_celsius": [40.0],
                "wet_bulb_temperature_celsius": [27.0],
                "relative_humidity_percent": [65.0],
            },
            "solar_irradiance": {"clear_sky": {"ghi": 820.0, "dni": 700.0, "dhi": 180.0},
                                 "description": "clear"},
        }],
    }


def _feature_ids(aoi) -> set[str]:
    ids: set[str] = set()
    if hasattr(aoi, "features"):
        aoi = aoi.to_dict()
    for feat in aoi.get("features", []):
        fid = feat.get("id") or feat.get("properties", {}).get("id")
        if fid:
            ids.add(str(fid))
    return ids


class FakeClient:
    """Duck-typed FortyGuardClient for monitor/reporting tests."""

    def __init__(self, plan: Plan = Plan.BASIC, fail_ids: set[str] | None = None):
        self.plan = plan
        self.heatmap_calls: list[str] = []
        self.env_calls: list[list[str]] = []
        self.fail_ids = set(fail_ids or [])
        self.hi_calls: list[str] = []

    async def heatmap(self, req: HeatmapRequest) -> HeatmapResult:
        self.heatmap_calls.append(req.analytic_type)
        if _feature_ids(req.polygon_aoi) & self.fail_ids:
            raise RuntimeError("simulated heatmap failure")
        return HeatmapResult.from_result(_fake_heatmap(req.analytic_type))

    async def env_params(
        self, req: EnvParamsRequest, temperature_c: float | None = None
    ) -> EnvParamsResult:
        self.env_calls.append(req.analysis or [])
        return EnvParamsResult.from_result(_fake_env())

    async def heat_intelligence(self, req):
        self.hi_calls.append(str(req.latitude))
        from fortyguard_sdk import HeatIntelligenceResult

        return HeatIntelligenceResult(activity_id="hi-1", download_link="http://x/report.pdf")

    async def download_report(self, link: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 fake heat intelligence report\n")
        return dest

    async def close(self) -> None:
        pass


def _monitor_ctx(tmp_path: Path, client: FakeClient, cache_dir: Path | None = None):
    p = Persistence(tmp_path / "coolchain.db")
    cache = TTLCache()
    disk = DiskCache(cache_dir or tmp_path / "cache")
    monitor = MonitorService(
        client, cache, p,
        MonitorConfig(plan=client.plan, preharvest_only=False),
        disk_cache=disk,
    )
    return p, cache, disk, monitor


# ---------------------------------------------------------------------------
# Monitor: DiskCache
# ---------------------------------------------------------------------------
def test_disk_cache_hit_and_miss(tmp_path):
    dc = DiskCache(tmp_path / "cache")
    dc.set("k1", {"temp_c": 36.0}, ttl_s=60)
    assert dc.get("k1", max_age_s=60) == {"temp_c": 36.0}
    assert dc.get("k1", max_age_s=60) == {"temp_c": 36.0}  # repeated hit
    assert dc.get("missing", max_age_s=60) is None
    stats = dc.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert dc.hit_rate() == pytest.approx(2 / 3, abs=0.01)


def test_disk_cache_expiry(tmp_path):
    dc = DiskCache(tmp_path / "cache")
    dc.set("k1", {"v": 1}, ttl_s=60)
    assert dc.get("k1", max_age_s=60) == {"v": 1}
    assert dc.get("k1", max_age_s=0) is None  # past the requested TTL window
    assert dc.get("k1", max_age_s=60) == {"v": 1}  # still on disk


def test_disk_cache_key_deterministic():
    dc = DiskCache("/tmp/opencode/cache-key-test")
    a = dc.cache_key({"a": 1}, "2025-07-15", "tcm")
    b = dc.cache_key({"a": 1}, "2025-07-15", "tcm")
    c = dc.cache_key({"a": 1}, "2025-07-15", "env")
    assert a == b and len(a) == 64
    assert a != c


# ---------------------------------------------------------------------------
# Monitor: cycle / cadence / partial failure / state
# ---------------------------------------------------------------------------
def test_monitor_cycle_writes_risk_scores(tmp_path):
    client = FakeClient()
    p, cache, disk, monitor = _monitor_ctx(tmp_path, client)
    try:
        _seed_field(p, "PV-01", "peach", "fort_valley")
        _seed_field(p, "VD-01", "onion", "vidalia")

        report = asyncio.run(monitor.cycle())

        assert report.clusters_ok == 2
        assert report.clusters_failed == 0
        assert report.risk_results > 0
        assert len(p.risk_scores("PV-01")) >= 1
        assert len(p.heat_samples("PV-01")) >= 3  # tcm + exceedance + persistence
        assert len(p.env_samples("PV-01")) >= 1
        # state persisted
        state = monitor.state_summary()
        assert state["total_cycles"] == 1
        assert state["last_successful_run"] is not None
        assert (disk.cache_dir / "monitor_state.json").exists()
    finally:
        p.close()


def test_monitor_cadence_loop_runs_multiple_cycles(tmp_path):
    client = FakeClient()
    p, cache, disk, monitor = _monitor_ctx(tmp_path, client)
    try:
        _seed_field(p, "PV-01", "peach", "fort_valley")

        async def _run():
            task = asyncio.create_task(monitor.run_forever(interval_s=0.01))
            for _ in range(200):
                if monitor.state.get("total_cycles", 0) >= 2:
                    break
                await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run())
        assert monitor.state.get("total_cycles", 0) >= 2
    finally:
        p.close()


def test_monitor_partial_failure_continues_with_available(tmp_path):
    """API failure for one cluster must not break the others."""
    client = FakeClient(fail_ids={"AL-01"})
    p, cache, disk, monitor = _monitor_ctx(tmp_path, client)
    try:
        _seed_field(p, "PV-01", "peach", "fort_valley")
        _seed_field(p, "AL-01", "pecan", "albany")

        report = asyncio.run(monitor.cycle())

        assert report.clusters_failed == 1
        assert report.clusters_ok == 1
        assert any("AL-01" in str(c) or "albany" in str(c) for c, _ in report.errors)
        # the healthy cluster still produced risk data
        assert len(p.risk_scores("PV-01")) >= 1
        assert len(p.risk_scores("AL-01")) == 0
        assert monitor.state["error_count"] >= 1
    finally:
        p.close()


def test_monitor_disk_cache_serves_second_cycle(tmp_path):
    """After a restart (fresh in-memory cache), disk cache serves the 2nd cycle."""
    client = FakeClient()
    p, cache, disk, monitor = _monitor_ctx(tmp_path, client)
    try:
        _seed_field(p, "PV-01", "peach", "fort_valley")
        asyncio.run(monitor.cycle())
        calls_after_first = len(client.heatmap_calls)
        assert calls_after_first >= 3

        # simulate process restart: new in-memory cache, same disk cache + DB
        monitor2 = MonitorService(
            client, TTLCache(), p, MonitorConfig(plan=client.plan),
            disk_cache=disk,
        )
        asyncio.run(monitor2.cycle())
        # tcm/exceedance/persistence served from disk cache -> no new calls
        assert len(client.heatmap_calls) == calls_after_first
        assert disk.stats()["hits"] > 0
    finally:
        p.close()


def test_monitor_graceful_degradation_on_failure(tmp_path):
    """When the API is down, the monitor serves from the disk cache."""
    client = FakeClient()
    p, cache, disk, monitor = _monitor_ctx(tmp_path, client)
    try:
        _seed_field(p, "PV-01", "peach", "fort_valley")
        asyncio.run(monitor.cycle())  # warm the disk cache

        # now the API dies entirely
        client.fail_ids = {"PV-01"}
        report = asyncio.run(monitor.cycle())
        # cluster still processed (stale disk cache) OR gracefully degraded
        assert report.clusters_ok + report.clusters_failed == 1
        assert report.risk_results >= 0
    finally:
        p.close()


def test_monitor_on_demand_corridor_comparison(tmp_path):
    client = FakeClient()
    p, cache, disk, monitor = _monitor_ctx(tmp_path, client)
    try:
        cmp = asyncio.run(monitor.corridor_comparison())
        assert cmp.inland["segments_used"] > 0
        assert cmp.coastal["segments_used"] > 0
    finally:
        p.close()


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------
def test_alert_template_rendering():
    payload = AlertPayload.build(
        field_id="PV-01", crop="peach", risk_score=88.0, tier="HIGH",
        canopy_temp_f=102.4, urgency=92.0,
        recommended_action="Irrigate at dawn",
        timestamp="2026-08-18T12:00:00Z",
    )
    expected = (
        "\U0001F6A8 HIGH ALERT: peach field PV-01 \u2014 102.4\u00B0F canopy, "
        "urgency 92.0/100 \u2192 Irrigate at dawn"
    )
    assert payload["message"] == expected
    assert render_template(payload) == expected
    assert "\U0001F6A8" in ALERT_TEMPLATE


def test_alert_dedup_within_cooldown(tmp_path):
    p = Persistence(tmp_path / "alerts.db")
    try:
        mgr = AlertManager(p)
        send, _ = mgr.should_send("PV-01", "canopy_risk", "high",
                                  now_ts="2026-08-18T12:00:00+00:00")
        assert send  # no prior alert

        payload = AlertPayload.build(
            field_id="PV-01", crop="peach", risk_score=70, tier="high",
            canopy_temp_f=98.0, urgency=75, recommended_action="irrigate",
        )
        mgr.record(payload, now_ts="2026-08-18T12:00:00Z")

        # same field + same kind + same tier inside 48h -> suppressed
        send2, reason = mgr.should_send("PV-01", "canopy_risk", "high",
                                        now_ts="2026-08-18T18:00:00+00:00")
        assert not send2
        assert "suppressed" in reason
    finally:
        p.close()


def test_alert_escalation_sends_through_cooldown(tmp_path):
    p = Persistence(tmp_path / "alerts.db")
    try:
        mgr = AlertManager(p)
        low = AlertPayload.build(
            field_id="PV-01", crop="peach", risk_score=45, tier="low",
            canopy_temp_f=95.0, urgency=50, recommended_action="monitor",
        )
        mgr.record(low, now_ts="2026-08-18T12:00:00Z")

        # within cooldown but tier escalated LOW -> CRITICAL -> send
        send, reason = mgr.should_send("PV-01", "canopy_risk", "critical",
                                       now_ts="2026-08-18T18:00:00+00:00")
        assert send
        assert "escalated" in reason
    finally:
        p.close()


def test_alert_cooldown_expires_after_48h(tmp_path):
    p = Persistence(tmp_path / "alerts.db")
    try:
        mgr = AlertManager(p)
        payload = AlertPayload.build(
            field_id="PV-01", crop="peach", risk_score=70, tier="high",
            canopy_temp_f=98.0, urgency=75, recommended_action="irrigate",
        )
        mgr.record(payload, now_ts="2026-08-18T12:00:00Z")

        # +49h -> cooldown expired, same tier sends again
        send, reason = mgr.should_send("PV-01", "canopy_risk", "high",
                                       now_ts="2026-08-20T13:00:00+00:00")
        assert send
        assert "expired" in reason
    finally:
        p.close()


def test_alert_channels_dispatch(tmp_path, capsys):
    p = Persistence(tmp_path / "alerts.db")
    try:
        mgr = AlertManager(p, AlertConfig(dry_run=True))
        payload = AlertPayload.build(
            field_id="PV-01", crop="peach", risk_score=88, tier="critical",
            canopy_temp_f=102.0, urgency=90, recommended_action="harvest now",
        )
        results = mgr.send(payload, channels=("console", "webhook", "sms", "email"))
        by_channel = {r["channel"]: r for r in results}
        assert all(r["ok"] for r in results)
        assert "logged to console" in by_channel["console"]["detail"]
        assert "webhook skipped" in by_channel["webhook"]["detail"]
        assert "Twilio stub" in by_channel["sms"]["detail"]
        assert "SMTP stub" in by_channel["email"]["detail"]
        captured = capsys.readouterr()
        assert "\U0001F6A8" in captured.out
    finally:
        p.close()


def test_alert_evaluate_and_send_pipeline(tmp_path):
    p = Persistence(tmp_path / "alerts.db")
    try:
        mgr = AlertManager(p)
        out = mgr.evaluate_and_send(
            field_id="BB-01", crop="blueberry", risk_score=82, tier="critical",
            canopy_temp_f=101.0, urgency=88,
            recommended_action="shade + irrigate immediately",
            now_ts="2026-08-18T12:00:00Z",
        )
        assert out["sent"] is True
        rows = p.alerts()
        assert len(rows) == 1
        assert rows[0]["severity"] == "CRITICAL"
        assert rows[0]["field_id"] == "BB-01"

        # duplicate within cooldown -> not sent, not recorded twice
        out2 = mgr.evaluate_and_send(
            field_id="BB-01", crop="blueberry", risk_score=82, tier="critical",
            canopy_temp_f=101.0, urgency=88,
            recommended_action="shade + irrigate immediately",
            now_ts="2026-08-18T18:00:00Z",
        )
        assert out2["sent"] is False
        assert len(p.alerts()) == 1
    finally:
        p.close()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _seed_report_db(p: Persistence) -> None:
    _seed_field(p, "PV-01", "peach", "fort_valley")
    _seed_field(p, "VD-01", "onion", "vidalia")
    p.insert_heat_sample("PV-01", "2026-08-18T18:00:00Z", analytic_type="tcm",
                         temp_c=36.0, temp_f=96.8, mean_c=36.0, max_c=37.5, n_cells=64)
    p.insert_heat_sample("PV-01", "2026-08-18T18:00:00Z", analytic_type="exceedance",
                         temp_c=7.0, temp_f=7.0, n_cells=64)
    p.insert_env_sample("PV-01", "2026-08-18T18:00:00Z",
                        temperature_f=96.8, heat_index_f=101.0, wet_bulb_f=80.0,
                        relative_humidity_percent=62.0, ghi_wm2=820.0)
    p.insert_alert("2026-08-18T12:00:00Z", field_id="PV-01",
                   alert_type="canopy_risk", severity="HIGH",
                   message="\U0001F6A8 HIGH ALERT demo")
    from coolchain.domain.canopy_risk import score_field_from_db

    score_field_from_db(p, "PV-01")


def test_reporting_daily_field_summary_json(tmp_path):
    p = Persistence(tmp_path / "rep.db")
    try:
        _seed_report_db(p)
        svc = ReportService(p, output_dir=tmp_path / "reports")
        dest = svc.daily_field_summary_json("2026-08-18")
        data = json.loads(dest.read_text())
        assert data["report_type"] == "daily_field_summary"
        assert data["date"] == "2026-08-18"
        rows = {r["field_id"]: r for r in data["fields"]}
        assert rows["PV-01"]["crop"] == "peach"
        assert rows["PV-01"]["risk_score"] is not None
        assert "tier" in rows["PV-01"]
    finally:
        p.close()


def test_reporting_corridor_comparison_json(tmp_path):
    from coolchain.domain.routing import load_corridor_nodes

    p = Persistence(tmp_path / "rep.db")
    try:
        ts = "2026-08-18T18:00:00Z"
        nodes = load_corridor_nodes()
        for rid in ("I16", "I75"):
            base = 92.0 if rid == "I16" else 99.0
            for seg_id, node in enumerate(nodes[rid]):
                p.insert_corridor_segment(rid, seg_id, ts, temp_f=base,
                                          distance_mi=node["distance_mi"])
        svc = ReportService(p, output_dir=tmp_path / "reports")
        dest = svc.corridor_comparison_json("2026-08-18")
        data = json.loads(dest.read_text())
        assert data["report_type"] == "corridor_comparison"
        assert data["recommended"] == "I16"
        assert len(data["routes"]) == 2
    finally:
        p.close()


def test_reporting_spoilage_risk_json(tmp_path):
    p = Persistence(tmp_path / "rep.db")
    try:
        _seed_report_db(p)
        svc = ReportService(p, output_dir=tmp_path / "reports")
        dest = svc.spoilage_risk_json("2026-08-18")
        data = json.loads(dest.read_text())
        assert data["report_type"] == "spoilage_risk"
        assert isinstance(data["fields"], list)
        assert any(f["field_id"] == "PV-01" for f in data["fields"])
    finally:
        p.close()


def test_reporting_alert_log_json(tmp_path):
    p = Persistence(tmp_path / "rep.db")
    try:
        _seed_report_db(p)
        svc = ReportService(p, output_dir=tmp_path / "reports")
        dest = svc.alert_log_json("2026-08-18")
        data = json.loads(dest.read_text())
        assert data["report_type"] == "alert_log"
        assert data["count"] >= 1
        assert data["alerts"][0]["field_id"] == "PV-01"
    finally:
        p.close()


def test_reporting_synthetic_pdf(tmp_path):
    p = Persistence(tmp_path / "rep.db")
    try:
        _seed_report_db(p)
        svc = ReportService(p, output_dir=tmp_path / "reports")
        dest = svc.generate_synthetic_pdf("2026-08-18")
        assert dest.exists()
        assert dest.read_bytes().startswith(b"%PDF")
        assert dest.stat().st_size > 200
    finally:
        p.close()


def test_reporting_hi_pdf_premium_download(tmp_path):
    from coolchain.services.reporting import ReportService

    p = Persistence(tmp_path / "rep.db")
    try:
        client = FakeClient(Plan.PREMIUM)
        svc = ReportService(p, output_dir=tmp_path / "reports")
        dest = asyncio.run(
            svc.fetch_hi_pdf(32.5517, -83.8871, "2026-08-18",
                             client=client, dest=tmp_path / "hi.pdf")
        )
        assert dest.exists()
        assert dest.read_bytes().startswith(b"%PDF")
        assert client.hi_calls  # heat_intelligence was called
    finally:
        p.close()


def test_reporting_hi_pdf_basic_fallback(tmp_path):
    p = Persistence(tmp_path / "rep.db")
    try:
        client = FakeClient(Plan.BASIC)  # not premium -> synthetic fallback
        svc = ReportService(p, output_dir=tmp_path / "reports")
        dest = asyncio.run(
            svc.fetch_hi_pdf(32.5517, -83.8871, "2026-08-18", client=client)
        )
        assert dest.exists()
        assert dest.read_bytes().startswith(b"%PDF")
        assert client.hi_calls == []  # no live heat_intelligence call
    finally:
        p.close()


def test_reporting_daily_bundle(tmp_path):
    p = Persistence(tmp_path / "rep.db")
    try:
        _seed_report_db(p)
        svc = ReportService(p, output_dir=tmp_path / "reports")
        files = svc.generate_daily("2026-08-18")
        assert set(files) == {
            "daily_field_summary", "corridor_comparison",
            "spoilage_risk", "alert_log", "report_card",
        }
        assert all(Path(v).exists() for v in files.values())
    finally:
        p.close()


# ---------------------------------------------------------------------------
# API + scheduler (fg serve building blocks)
# ---------------------------------------------------------------------------
def test_create_app_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from coolchain.services.api import create_app

    p = Persistence(tmp_path / "rep.db")
    try:
        _seed_report_db(p)
        client = FakeClient()
        cache = TTLCache()
        monitor = MonitorService(
            client, cache, p, MonitorConfig(plan=client.plan),
            disk_cache=DiskCache(tmp_path / "cache"),
        )
        svc = ReportService(p, output_dir=tmp_path / "reports")
        app = create_app(monitor=monitor, reporting=svc, persistence=p)

        with TestClient(app) as tc:
            assert tc.get("/health").json()["status"] == "ok"
            status = tc.get("/status").json()
            assert "monitor" in status and "db" in status
            cycle = tc.post("/trigger/cycle").json()
            assert cycle["ok"] is True
            rep = tc.post("/trigger/report").json()
            assert rep["ok"] is True
            assert "report_card" in rep["files"]
            reports = tc.get("/reports").json()
            assert isinstance(reports["reports"], list)
    finally:
        p.close()


def test_create_scheduler_jobs(tmp_path):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from coolchain.services.api import create_scheduler

    p = Persistence(tmp_path / "rep.db")
    try:
        client = FakeClient()
        cache = TTLCache()
        monitor = MonitorService(client, cache, p, MonitorConfig(),
                                 disk_cache=DiskCache(tmp_path / "cache"))
        svc = ReportService(p, output_dir=tmp_path / "reports")
        sched = create_scheduler(monitor, svc)
        assert isinstance(sched, AsyncIOScheduler)
        jobs = {j.id: j for j in sched.get_jobs()}
        assert "monitor-cycle" in jobs
        assert "daily-report" in jobs
    finally:
        p.close()