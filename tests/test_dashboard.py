"""Day-5 dashboard tests — Streamlit app + all six component data paths.

Coverage:
    App       starts headless without exceptions (AppTest), 6 tabs render,
              KPI cards show fixture values, time slider / click / region
              interactions drive the UI.
    Fixtures  fields_snapshot, heat frames, corridor, risk data, alerts,
              KPIs and HI report match the docs/02 data contracts.
    SQLite    AlertAckStore persists acknowledgements.
    Offline   every loader works with no network (FIXTURES mode default).

Run:  .venv/bin/python -m pytest tests/test_dashboard.py -v
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from dashboard import data_source as ds
from dashboard import fixtures_gen

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.usefixtures("fixture_db")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def fixture_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the data source at a fresh copy of the seeded SQLite store."""
    db = tmp_path / "coolchain.db"
    shutil.copy(ROOT / "data" / "coolchain.db", db)
    monkeypatch.setenv("PCS_DB_PATH", str(db))
    yield db


@pytest.fixture(scope="module")
def fields() -> list[dict]:
    return fixtures_gen.generate_fields_snapshot()


@pytest.fixture(scope="module")
def heat_payload() -> dict:
    return fixtures_gen.generate_heat_frames()


@pytest.fixture(scope="module")
def corridor() -> dict:
    return fixtures_gen.generate_corridor()


@pytest.fixture(scope="module")
def risk_data() -> dict:
    return fixtures_gen.generate_risk_data()


@pytest.fixture(scope="module")
def alerts() -> dict:
    return fixtures_gen.generate_alerts()


@pytest.fixture(scope="module")
def kpis() -> dict:
    return fixtures_gen.generate_kpis()


def _run_app(tmp_path: Path):
    from streamlit.testing.v1 import AppTest

    db = tmp_path / "app_coolchain.db"
    shutil.copy(ROOT / "data" / "coolchain.db", db)
    os.environ["PCS_DB_PATH"] = str(db)
    return AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=120)


# ---------------------------------------------------------------------------
# 1. App starts without error (headless)
# ---------------------------------------------------------------------------
def test_app_starts_headless(tmp_path):
    at = _run_app(tmp_path)
    at.run()
    assert len(at.exception) == 0, [e.message for e in at.exception]
    assert [t.label for t in at.tabs] == [
        "Field Map", "Corridor Map", "Risk Charts", "Harvest Alerts",
        "KPI Dashboard", "HI Report",
    ]


# ---------------------------------------------------------------------------
# 2. Each component renders with fixture data
# ---------------------------------------------------------------------------
def test_field_map_tab_renders(tmp_path):
    from dashboard.components.field_map import build_map, legend_html

    h = fixtures_gen.generate_heat_frames()
    f = fixtures_gen.generate_fields_snapshot()
    m = build_map(f, h["frames"], h["field_tiers"], "15:00")
    assert m is not None
    html = m._repr_html_()
    assert "CartoDB Positron" in html or "carto" in html.lower()
    assert legend_html() and "CRITICAL" in legend_html()

    # PNG export is offline matplotlib output.
    png = __import__(
        "dashboard.components.field_map", fromlist=["map_png_bytes"]
    ).map_png_bytes(f, h["field_tiers"], "15:00", "PV-07")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_corridor_tab_renders(tmp_path):
    from dashboard.components.corridor_map import (
        build_corridor_map, recommendation_html, route_summary_df,
        temp_profile_chart,
    )

    c = fixtures_gen.generate_corridor()
    m = build_corridor_map(c)
    assert m is not None
    html = m._repr_html_()
    assert "I75" in html and "I16" in html
    df = route_summary_df(c)
    assert len(df) == 2
    chart = temp_profile_chart(c)
    assert chart is not None
    assert "54%" in recommendation_html(c) and "142" in recommendation_html(c)


def test_risk_charts_tab_renders(tmp_path):
    from dashboard.components.risk_charts import (
        crop_radar_chart, harvest_window_df, risk_series_chart, spoilage_chart,
    )

    r = fixtures_gen.generate_risk_data()
    chart = risk_series_chart(r, ["PV-07"])
    assert chart is not None
    df = harvest_window_df(r)
    assert len(df) == 45
    assert set(df["crop"]).issubset({"peach", "pecan", "blueberry", "onion"})
    s = spoilage_chart(r)
    assert s is not None
    radar = crop_radar_chart(r)
    assert radar is not None


def test_harvest_alerts_tab_renders(tmp_path):
    from dashboard.components.harvest_alerts import (
        alert_banner_html, alerts_df, packing_house_html, sms_phone_html,
    )

    a = fixtures_gen.generate_alerts()
    df = alerts_df(a)
    assert len(df) == 5
    assert df.iloc[0]["field_id"] == "PV-07"  # highest urgency hero
    banner = alert_banner_html(a["alerts"][0])
    assert "PV-07" in banner and "CRITICAL" in banner
    sms = sms_phone_html(a["alerts"][0]["sms"])
    assert "HARVEST NOW" in sms and "Foreman" in sms
    ph = packing_house_html(a["alerts"][0])
    assert "Fort Valley Peach Co-op" in ph and "12,400" in ph


def test_hi_report_renders(tmp_path):
    from dashboard.components.hi_report import synthetic_report_card

    report = fixtures_gen.generate_hi_report()
    # PDF fixture exists (Day 2) — bytes must be loaded.
    assert report["pdf_path"] and Path(report["pdf_path"]).exists()
    card = synthetic_report_card(report)
    assert "Heat Intelligence Report" in card


# ---------------------------------------------------------------------------
# 3. Time slider updates map colors
# ---------------------------------------------------------------------------
def test_time_slider_updates_field_colors(fields, heat_payload):
    field_tiers = heat_payload["field_tiers"]
    field_scores = heat_payload.get("field_scores", {})
    assert set(field_tiers.keys()) == set(ds.TIME_HOURS)
    assert set(field_scores.keys()) == set(ds.TIME_HOURS)
    # Hero PV-07 follows the demo-script risk curve: 87 @ 08:00 -> 91 @ 15:00
    # (both CRITICAL tier — docs/01 side panel "87/100 (CRITICAL)").
    assert field_scores["08:00"]["PV-07"] == pytest.approx(87.0)
    assert field_scores["15:00"]["PV-07"] == pytest.approx(91.0)
    assert field_tiers["08:00"]["PV-07"] == "critical"
    assert field_tiers["15:00"]["PV-07"] == "critical"
    # Every field's risk rises into the 15:00 peak (score delta >= 0).
    for fid, s08 in field_scores["08:00"].items():
        assert field_scores["15:00"][fid] >= s08
    # The whole map shifts: far fewer critical farms at 08:00 than 15:00.
    n_crit_morning = sum(1 for t in field_tiers["08:00"].values() if t == "critical")
    n_crit_peak = sum(1 for t in field_tiers["15:00"].values() if t == "critical")
    assert n_crit_morning < n_crit_peak

    from dashboard.styles.theme import heat_color

    assert heat_color(85.0) != heat_color(100.0)
    assert heat_color(120.0) == heat_color(110.0)  # clamps at hot end


def test_time_slider_widget_drives_caption(tmp_path):
    at = _run_app(tmp_path)
    at.run()
    at.select_slider[0].set_value("08:00")
    at.run()
    assert at.select_slider[0].value == "08:00"
    captions = " ".join(c.value for c in at.caption)
    assert "08:00 EDT" in captions


# ---------------------------------------------------------------------------
# 4. Click interaction populates sidebar
# ---------------------------------------------------------------------------
def test_click_parses_folium_output(fields):
    from dashboard.components.field_map import field_click_id

    # st_folium returns the clicked feature via last_object_clicked.
    out = type("Out", (), {"last_object_clicked": {
        "id": "fields", "props": {"field_id": "PV-07"},
    }})()
    assert field_click_id(out) == "PV-07"
    out2 = type("Out", (), {"last_object_clicked": None})()
    assert field_click_id(out2) is None


def test_field_detail_markdown(fields):
    from dashboard.components.field_map import field_detail_markdown

    f = next(x for x in fields if x["field_id"] == "PV-07")
    md = field_detail_markdown(f)
    assert "PV-07" in md and "Peach" in md
    assert f"{f['risk']['canopy_temp_f']:.1f}°F" in md
    assert f"{f['harvest']['urgency']:.0f}/100" in md
    assert field_detail_markdown(None).startswith('<div class="pcs-card"')


def test_field_selection_populates_sidebar(tmp_path):
    at = _run_app(tmp_path)
    at.run()
    field_sel = [s for s in at.selectbox if s.label.startswith("Selected field")][0]
    field_sel.set_value("AL-04")
    at.run()
    md = " ".join(m.value for m in at.markdown)
    assert "AL-04" in md and "Pecan" in md and "Pecan" in md


# ---------------------------------------------------------------------------
# 5. KPI cards show correct fixture values
# ---------------------------------------------------------------------------
def test_kpi_fixture_values(kpis):
    by_id = {k["id"]: k for k in kpis["kpis"]}
    assert by_id["spoilage"]["value"] == "↓ 23%"
    assert by_id["savings"]["value"] == "$180K"
    assert by_id["fuel"]["value"] == "12%"
    assert by_id["port"]["value"] == "96%"
    assert "Carbon ↓41 t CO₂e" in kpis["secondary"]


def test_kpi_cards_render_in_app(tmp_path):
    at = _run_app(tmp_path)
    at.run()
    html = " ".join(m.value for m in at.markdown)
    assert "23%" in html and "$180K" in html and "96%" in html
    # st.metric elements from corridor + HI report tabs
    values = {m.value for m in at.metric}
    assert "318 mi" in values and "176 mi" in values


def test_corridor_metrics_match_fixture(corridor):
    i75 = next(r for r in corridor["routes"] if r["route_id"] == "I75")
    i16 = next(r for r in corridor["routes"] if r["route_id"] == "I16")
    assert i75["distance_mi"] == 318.0 and i16["distance_mi"] == 176.0
    assert i75["avg_temp_f"] == 97.1 and i16["avg_temp_f"] == 91.3
    assert i75["spoilage_risk_pct"] == 6.8 and i16["spoilage_risk_pct"] == 3.1
    assert i75["fuel_gal"] == 132.0 and i16["fuel_gal"] == 116.0
    assert corridor["recommendation"] == (
        "I-16 saves 54% spoilage risk, 12% fuel, 142 mi shorter"
    )


# ---------------------------------------------------------------------------
# 6. Alert acknowledge persists to SQLite
# ---------------------------------------------------------------------------
def test_alert_ack_store(tmp_path):
    store = ds.AlertAckStore(tmp_path / "coolchain.db")
    assert "PV-07" not in store.acknowledged()
    store.mark_acknowledged("PV-07")
    assert "PV-07" in store.acknowledged()

    conn = sqlite3.connect(tmp_path / "coolchain.db")
    row = conn.execute(
        "SELECT acknowledged FROM alerts WHERE field_id='PV-07' "
        "ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == 1


def test_ack_button_flow(tmp_path):
    at = _run_app(tmp_path)
    at.run()
    at.button[0].click()
    at.run()
    assert len(at.exception) == 0
    conn = sqlite3.connect(tmp_path / "app_coolchain.db")
    rows = conn.execute(
        "SELECT acknowledged FROM alerts WHERE field_id='PV-07'"
    ).fetchall()
    conn.close()
    assert any(r[0] == 1 for r in rows)


# ---------------------------------------------------------------------------
# 7. Fixture data contracts (offline, deterministic)
# ---------------------------------------------------------------------------
def test_fields_snapshot_contract(fields):
    assert len(fields) == 45
    tiers = {f["risk"]["tier"] for f in fields}
    assert tiers == {"low", "medium", "high", "critical"}  # all four colors
    pv = next(f for f in fields if f["field_id"] == "PV-07")
    assert pv["risk"]["tier"] == "critical"
    assert pv["risk"]["canopy_temp_f"] == pytest.approx(98.2, abs=0.4)
    assert pv["harvest"]["window"] == "NOW"
    for f in fields:
        assert set(["score", "tier", "canopy_temp_f", "threshold_f",
                    "heat_index_f", "humidity_pct", "exceedance_hours",
                    "persistence_forecast_hours", "components"]).issubset(
            f["risk"].keys())
        assert "polygon" in f and "center" in f


def test_heat_frames_contract(heat_payload):
    frames = heat_payload["frames"]
    assert list(frames.keys()) == ds.TIME_HOURS
    for hh, feats in frames.items():
        for feat in feats:
            p = feat["properties"]
            assert p["hour"] == hh and p["analytic"] == "tcm"
            assert "tcm_f" in p and "field_id" in p


def test_risk_data_contract(risk_data):
    series = risk_data["series"]
    # 45 fields x 48 half-hour points
    assert len(series) == 45 * 48
    for pt in series[:10]:
        assert {"field_id", "crop", "ts", "risk_score", "tier"}.issubset(pt)
    assert len(risk_data["harvest_windows"]) == 45
    assert len(risk_data["spoilage"]) == 4  # peach, pecan, blueberry, onion
    assert len(risk_data["crop_radar"]) == 4


def test_alerts_contract(alerts):
    ids = {a["field_id"] for a in alerts["alerts"]}
    # All alert field ids must exist in the fields fixture.
    fields = fixtures_gen.generate_fields_snapshot()
    field_ids = {f["field_id"] for f in fields}
    assert ids.issubset(field_ids)
    hero = alerts["alerts"][0]
    assert hero["field_id"] == "PV-07"
    assert hero["sms"]["body"] == (
        "FIELD PV-07 — HARVEST NOW\n"
        "98°F · 3.4h above threshold · +6h forecast\n"
        "Packing house: Fort Valley Peach Co-op (pre-cool slot 4:30 PM)\n"
        "Truck: Reefer #212 dispatched · I-16 corridor"
    )
    assert hero["packing_house"]["name"] == "Fort Valley Peach Co-op"


def test_theme_tokens():
    from dashboard.styles.theme import (
        GA_BLUE, GA_RED, HEAT_GRADIENT_7, TIER_COLORS, heat_color,
    )

    assert GA_RED == "#C8102E" and GA_BLUE == "#003A70"
    assert HEAT_GRADIENT_7[0] == "#3B4CC0" and HEAT_GRADIENT_7[-1] == "#EF476F"
    assert len(HEAT_GRADIENT_7) == 7
    assert TIER_COLORS["critical"] == GA_RED
    assert heat_color(80.0) == "#3B4CC0"
    assert heat_color(105.0) == "#EF476F"


# ---------------------------------------------------------------------------
# 8. Data source mode: FIXTURES default, offline-safe
# ---------------------------------------------------------------------------
def test_fixtures_mode_offline(tmp_path):
    assert ds.MODE_FIXTURES == "FIXTURES"
    # All loaders resolve without network.
    assert len(ds.load_fields()) == 45
    assert set(ds.load_heat_frames()["frames"].keys()) == set(ds.TIME_HOURS)
    assert len(ds.load_corridor()["routes"]) == 2
    assert len(ds.load_alerts()["alerts"]) == 5
    assert len(ds.load_kpis()["kpis"]) == 4
    report = ds.load_hi_report()
    assert report["pdf_bytes"] and len(report["pdf_bytes"]) > 100_000
    assert len(ds.load_packing_houses()) == 5


def test_missing_fixture_falls_back_deterministically(tmp_path, monkeypatch):
    """If a fixture JSON is deleted the in-memory generator still serves it."""
    monkeypatch.setattr(ds, "FIXTURES_DIR", tmp_path / "empty_fixtures")
    fields = ds.load_fields()
    assert len(fields) == 45
    fields2 = ds.load_fields()
    assert fields == fields2  # deterministic