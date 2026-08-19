"""Day-7 tests — polish + fallback modes + security + EDT labels.

Coverage (docs/task 7.1-7.4):
    Fallback  DATA_SOURCE resolution (fixtures default, unknown -> fixtures,
              live/hybrid gating on an API key), 8 s hybrid timeout,
              auto-fallback to fixtures, health payload shape, demo-mode guard.
    EDT       utc_to_edt / utc_to_edt_iso convert UTC store -> America/New_York
              wall clock (July 2025 = UTC-4).
    API       GET /health returns {status, data_source, last_live_ok,
              cache_age_s, ...}.
    A11y      readable_text_on() / chip_style() meet WCAG 4.5:1 on every
              tier + crop fill.
    Empty     alerts_df / KPI cards handle no-data without crashing.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from dashboard import data_source as ds
from dashboard.styles import theme
from coolchain.services import fallback as fb

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. DATA_SOURCE resolution (7.2)
# ---------------------------------------------------------------------------
def test_data_source_defaults_to_fixtures(monkeypatch):
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    assert fb.resolve_data_source({}) == fb.MODE_FIXTURES
    assert fb.health_status()["data_source"] == "fixtures"


def test_data_source_unknown_falls_back_to_fixtures(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "bogus-mode")
    assert fb.resolve_data_source() == fb.MODE_FIXTURES


def test_data_source_env_roundtrip(monkeypatch):
    for mode in ("fixtures", "live", "hybrid"):
        monkeypatch.setenv("DATA_SOURCE", mode)
        assert fb.resolve_data_source() == mode
        assert fb.health_status()["data_source"] == mode


def test_live_requires_api_key(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "hybrid")
    for key_var in ("FORTYGUARD_API_KEY", "FG_API_KEY", "COOLCHAIN_FORTYGUARD_API_KEY"):
        monkeypatch.delenv(key_var, raising=False)
    assert fb.api_key_from_env() == ""
    assert fb.is_live_capable() is False

    monkeypatch.setenv("FORTYGUARD_API_KEY", "test-key-not-real")
    assert fb.api_key_from_env() == "test-key-not-real"
    assert fb.is_live_capable() is True


# ---------------------------------------------------------------------------
# 2. Hybrid: live ok -> live value; live fail -> fixtures (8 s timeout)
# ---------------------------------------------------------------------------
def test_hybrid_uses_live_value_when_ok(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "hybrid")
    monkeypatch.setenv("FORTYGUARD_API_KEY", "x")

    live = lambda: {"source": "live"}  # noqa: E731
    fixtures = lambda: {"source": "fixtures"}  # noqa: E731
    assert fb.hybrid_fetch(live, fixtures)["source"] == "live"
    assert fb.STATE.last_live_ok is None  # value returned, no probe recorded


def test_hybrid_falls_back_when_live_raises(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "hybrid")
    monkeypatch.setenv("FORTYGUARD_API_KEY", "x")

    def boom():
        raise ConnectionError("API down")

    fixtures = lambda: {"source": "fixtures"}  # noqa: E731
    assert fb.hybrid_fetch(boom, fixtures)["source"] == "fixtures"
    assert fb.STATE.last_live_ok is False
    assert "ConnectionError" in (fb.STATE.last_error or "")


def test_hybrid_fixtures_mode_never_calls_live(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "fixtures")

    def should_not_run():
        raise AssertionError("live fetcher must not run in fixtures mode")

    fixtures = lambda: {"source": "fixtures"}  # noqa: E731
    assert fb.hybrid_fetch(should_not_run, fixtures)["source"] == "fixtures"


def test_probe_live_no_key_fails_fast(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "hybrid")
    t0 = time.time()
    assert fb.probe_live("") is False
    assert time.time() - t0 < 1.0  # no network wait without a key


def test_health_payload_shape():
    h = fb.health_status()
    for key in ("status", "data_source", "last_live_ok", "cache_age_s"):
        assert key in h
    assert h["status"] == "ok"
    assert isinstance(h["cache_age_s"], float)


# ---------------------------------------------------------------------------
# 3. Demo-mode guard (7.2)
# ---------------------------------------------------------------------------
def test_demo_mode_guard():
    env = {
        "STREAMLIT_SERVER_HEADLESS": "true",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    }
    assert fb.demo_mode_ok(env) is True
    assert fb.ensure_demo_mode(env)["ok"] is True

    bad = dict(env)
    bad["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "true"
    assert fb.demo_mode_ok(bad) is False
    assert fb.ensure_demo_mode(bad)["ok"] is False


# ---------------------------------------------------------------------------
# 4. EDT labels (7.1)
# ---------------------------------------------------------------------------
def test_utc_to_edt_conversion():
    # 19:04 UTC on July 15 (EDT, UTC-4) == 15:04 EDT.
    assert ds.utc_to_edt("2025-07-15T19:04:00Z") == "2025-07-15 15:04"
    assert ds.utc_to_edt("2025-07-15T19:04:00Z", "%H:%M EDT") == "15:04 EDT"
    assert ds.utc_to_edt_iso("2025-07-15T19:04:00Z") == "2025-07-15T15:04:00"


def test_utc_to_edt_passthrough_on_garbage():
    assert ds.utc_to_edt("not-a-date") == "not-a-date"
    assert ds.utc_to_edt_iso("not-a-date") == "not-a-date"


def test_loaders_emit_edt_labels():
    r = ds.load_risk_data()
    first = r["series"][0]["ts"]  # UTC 00:00Z -> previous day 20:00 EDT
    assert first.endswith("T20:00:00")

    a = ds.load_alerts()
    assert a["alerts"][0]["ts_edt"].endswith("EDT")
    assert a["alerts"][0]["ts_edt"] == ds.utc_to_edt(
        a["alerts"][0]["ts"], "%Y-%m-%d %H:%M EDT"
    )


# ---------------------------------------------------------------------------
# 5. /health endpoint (7.2)
# ---------------------------------------------------------------------------
def test_health_endpoint_full_payload(tmp_path, monkeypatch):
    from coolchain.services.api import create_app
    from coolchain.services.monitor import DiskCache, MonitorConfig, MonitorService
    from coolchain.services.persistence import Persistence
    from coolchain.services.reporting import ReportService

    monkeypatch.setenv("DATA_SOURCE", "fixtures")
    db = tmp_path / "db.sqlite"
    p = Persistence(str(db))
    try:
        from fortyguard_sdk import Plan

        monitor = MonitorService(
            client=None,  # never used in this test
            cache=None,
            persistence=p,
            config=MonitorConfig(plan=Plan.BASIC),
            disk_cache=DiskCache(tmp_path / "cache"),
        )
        # Skip actual SDK construction: monitor.cycle is never called here.
        app = create_app(monitor=monitor, reporting=ReportService(
            p, output_dir=tmp_path / "reports"), persistence=p)

        from fastapi.testclient import TestClient

        with TestClient(app) as tc:
            h = tc.get("/health").json()
            assert h["status"] == "ok"
            assert h["data_source"] == "fixtures"
            assert "cache_age_s" in h and "last_live_ok" in h
    finally:
        p.close()


# ---------------------------------------------------------------------------
# 6. Accessibility: readable text meets 4.5:1 on every fill (7.1)
# ---------------------------------------------------------------------------
def test_chip_text_contrast_wcag_45():
    fills = list(theme.TIER_COLORS.values()) + [
        m["color"] for m in theme.CROP_META.values()
    ]
    for bg in fills:
        txt = theme.readable_text_on(bg)
        assert theme._contrast_ratio(txt, bg) >= 4.5, (
            f"text {txt} on {bg} below 4.5:1"
        )
    assert "color:" in theme.chip_style("#F9A825")  # inline style helper


def test_peach_text_token_compliant():
    assert theme._contrast_ratio(theme.PEACH_TEXT, "#FFFFFF") >= 4.5


# ---------------------------------------------------------------------------
# 7. Empty states (7.1)
# ---------------------------------------------------------------------------
def test_alerts_df_empty_state():
    from dashboard.components.harvest_alerts import alerts_df

    df = alerts_df({"alerts": []})
    assert df.empty  # empty state instead of a crash / blank dataframe


def test_kpi_empty_state_returns_no_ids(monkeypatch):
    import streamlit

    info_calls: list[str] = []
    monkeypatch.setattr(streamlit, "info", info_calls.append)

    from dashboard.components.cold_chain_kpis import render_kpi_cards

    ids = render_kpi_cards({"kpis": []})
    assert ids == []
    assert len(info_calls) == 1  # helpful message shown


def test_theme_tokens_day7():
    assert theme.GA_RED == "#C8102E"
    assert theme.GA_BLUE == "#003A70"
    assert theme.PEACH == "#F58B4C"