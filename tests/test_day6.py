"""Day 6 — degraded-mode runbook tests (task 6.4) + fixture validation (task 6.5).

Covers:
  6.4  network kill  -> DATA_SOURCE=fixtures getters still return data
       API 500       -> corrupt fixture falls back to deterministic generator
       tile failure  -> heat frames fall back + offline PNG export works
       time-short    -> --core-only rehearsal (4-min variant) under budget
  6.5  SDK typed models parse every day6 envelope
       offline (fixtures) rendering end-to-end
       scene transitions < 2s, total pipeline < 300s (rehearsal log)
       PV-07 risk 87 @ 08:00, 91 @ 15:00 (exact, frozen demo numbers)
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DAY6 = ROOT / "data" / "fixtures" / "day6"
REHEARSAL_LOG = ROOT / "data" / "rehearsal" / "rehearsal_log.json"


# ---------------------------------------------------------------------------
# 6.5 — SDK typed models parse every day6 envelope
# ---------------------------------------------------------------------------
def _parse_sdk(envelope: dict) -> object:
    from fortyguard_sdk import (
        EnvParamsResult, HeatIntelligenceResult, HeatmapResult,
    )

    endpoint = envelope["endpoint"]
    resp = envelope["response"]
    if endpoint == "POST /heatmap":
        return HeatmapResult.from_result(resp)
    if endpoint == "POST /env_params":
        return EnvParamsResult.from_result(resp)
    if endpoint == "POST /heat_intelligence":
        return HeatIntelligenceResult.from_result(
            "day6::hi_fort_valley", resp
        )
    return None  # derived / non-SDK endpoints checked for envelope shape


@pytest.fixture(scope="session")
def day6_envelopes() -> list[dict]:
    assert DAY6.exists(), "run `fg fixtures record --date 2025-07-15 --output-dir data/fixtures/day6/` first"
    envs = []
    for p in sorted(DAY6.rglob("*.json")):
        if p.name in ("manifest.json", "README.md"):
            continue
        envs.append(json.loads(p.read_text()))
    assert len(envs) == 24
    return envs


def test_day6_fixtures_parse_through_sdk_models(day6_envelopes):
    parsed = 0
    for env in day6_envelopes:
        # envelope shape (task 6.1: timestamp, endpoint, params, response, source)
        for key in ("schema_version", "kind", "generated_ts", "endpoint",
                    "params", "response", "source", "frozen_date"):
            assert key in env, (env["endpoint"], key)
        assert env["schema_version"] == 1
        assert env["source"] in {"live", "cached"}
        assert env["frozen_date"] == "2025-07-15"
        model = _parse_sdk(env)
        if model is not None:
            parsed += 1
            if env["endpoint"] == "POST /heatmap":
                assert model.map_data is not None or model.n_cells > 0
            elif env["endpoint"] == "POST /env_params":
                assert model.locations
            else:
                assert model.status == "Completed"
    # Every SDK-backed envelope parsed: 14 heatmap + 2 env_params + 1 HI json.
    assert parsed == 17


def test_day6_manifest_and_scope(day6_envelopes):
    manifest = json.loads((DAY6 / "manifest.json").read_text())
    assert manifest["kind"] == "day6_manifest"
    assert manifest["source_mode"] == "cached"
    # All 45 GA fields + both corridor routes are represented.
    assert manifest["counts"]["fields"] == 13
    assert manifest["counts"]["corridor"] == 3
    assert manifest["counts"]["env"] == 2
    assert manifest["counts"]["hi_report"] == 2
    snap = next(e for e in day6_envelopes
                if e["endpoint"] == "derived:fields_snapshot")
    assert len(snap["response"]["fields"]) == 45
    corridor = next(e for e in day6_envelopes
                    if e["endpoint"] == "POST /corridor")
    assert {r["route_id"] for r in corridor["response"]["routes"]} == {"I16", "I75"}
    # HI PDF is present.
    assert (DAY6 / "hi_report" / "heat_intelligence_fort_valley.pdf").exists()


# ---------------------------------------------------------------------------
# 6.5 — PV-07 hero numbers frozen exactly (docs/01 demo script)
# ---------------------------------------------------------------------------
def test_day6_hero_values_exact(day6_envelopes):
    snap = next(e for e in day6_envelopes
                if e["endpoint"] == "derived:fields_snapshot")
    pv = next(f for f in snap["response"]["fields"] if f["field_id"] == "PV-07")
    assert pv["risk"]["score"] == 91.0
    assert pv["risk"]["tier"] == "critical"
    assert pv["risk"]["canopy_temp_f"] == pytest.approx(98.2)
    assert pv["risk"]["threshold_f"] == 95.0
    assert pv["risk"]["humidity_pct"] == pytest.approx(71.0)
    assert pv["risk"]["heat_index_f"] == pytest.approx(112.0)

    risk_scores = next(e for e in day6_envelopes if e["endpoint"] == "POST /risk")
    pv_r = next(f for f in risk_scores["response"]["fields"]
                if f["field_id"] == "PV-07")
    assert pv_r["score"] == 91.0
    assert pv_r["tier"] == "critical"
    assert pv_r["exceedance_hours"] == pytest.approx(3.4)
    assert pv_r["persistence_forecast_hours"] == pytest.approx(6.0)

    # 08:00 -> 87, 15:00 -> 91 (exact contract from the demo script).
    series = next(e for e in day6_envelopes if e["endpoint"] == "derived:risk_series")
    by_hour: dict[str, float] = {}
    for row in series["response"]["series"]:
        if row["field_id"] == "PV-07":
            by_hour[row["ts"][11:16]] = row["risk_score"]
    assert by_hour["08:00"] == 87.0
    assert by_hour["15:00"] == 91.0

    # Alert envelope drives Scene 2: PV-07 harvest now + SMS.
    alerts = next(e for e in day6_envelopes if e["endpoint"] == "POST /alerts")
    pv_a = next(a for a in alerts["response"]["alerts"]
                if a.get("field_id") == "PV-07")
    assert pv_a["recommended_action"] == "HARVEST_NOW"
    assert pv_a["sms"]["status"] == "SENT"
    assert "PV-07" in pv_a["sms"]["body"]
    assert "98" in pv_a["sms"]["body"]

    # Corridor spoilage: I-16 vs I-75 is -54% (docs/01 Scene 3).
    spoilage = next(
        e for e in day6_envelopes
        if e["endpoint"] == "derived:spoilage" and "routes" in e["response"]
    )
    routes = {r["route_id"]: r for r in spoilage["response"]["routes"]}
    i75 = routes["I75"]["risk_pct"]
    i16 = routes["I16"]["risk_pct"]
    assert i16 <= i75 * 0.5  # -54% -> more than half


# ---------------------------------------------------------------------------
# 6.4 — degraded modes
# ---------------------------------------------------------------------------
def test_offline_network_kill(monkeypatch):
    """DATA_SOURCE=fixtures + blocked sockets -> every getter still works."""
    from dashboard import data_source as ds

    def _block(*_a, **_k):
        raise OSError("network blocked (test)")

    monkeypatch.setattr(socket, "socket", _block)
    monkeypatch.setenv("DATA_SOURCE", "fixtures")

    fields = ds.load_fields()
    assert len(fields) == 45
    heat = ds.load_heat_frames()
    assert set(heat.keys()) == {"frames", "field_tiers", "field_scores"}
    assert ds.load_corridor()["routes"]
    assert ds.load_risk_data()["series"]
    assert ds.load_alerts()["alerts"]
    assert ds.load_kpis()["kpis"]
    assert ds.load_packing_houses()
    hi = ds.load_hi_report()
    assert hi["pdf_bytes"] is not None  # PDF bundled offline


def test_api_500_falls_back_to_deterministic(monkeypatch, tmp_path):
    """API failure (corrupt/missing fixture) -> in-memory generator fallback.

    ``_read_fixture`` returns None for corrupt files and the getters call the
    deterministic in-memory generator (zero network), so an API 500 or a
    deleted fixture never blanks the demo.
    """
    from dashboard import data_source as ds

    corrupt = tmp_path / "fixtures"
    corrupt.mkdir()
    for name in ("fields_snapshot.json", "heat_frames.json", "corridor.json",
                 "risk_data.json", "alerts.json", "kpis.json",
                 "packing_houses.json", "hi_report.json"):
        (corrupt / name).write_text("{ this is not json !!!")

    monkeypatch.setattr(ds, "FIXTURES_DIR", corrupt)
    monkeypatch.setenv("DATA_SOURCE", "fixtures")

    fields = ds.load_fields()
    assert len(fields) == 45
    heat = ds.load_heat_frames()
    # Generated payload is complete: frames for every hour + tiers + scores.
    assert set(heat.keys()) == {"frames", "field_tiers", "field_scores"}
    assert heat["field_scores"]["08:00"]["PV-07"] == pytest.approx(87.0)
    assert heat["field_scores"]["15:00"]["PV-07"] == pytest.approx(91.0)
    assert ds.load_corridor()["routes"]
    assert len(ds.load_alerts()["alerts"]) >= 1
    assert len(ds.load_kpis()["kpis"]) == 4
    assert ds.load_hi_report()["pdf_bytes"] is not None


def test_tile_failure_png_fallback(monkeypatch, tmp_path):
    """Heat tile layer missing -> generated frames still render + PNG export.

    The component exports an offline matplotlib PNG when interactive tiles are
    unavailable — the demo never depends on the network tile CDN.
    """
    from dashboard import data_source as ds
    from dashboard.components.field_map import map_png_bytes

    monkeypatch.setattr(ds, "FIXTURES_DIR", tmp_path)  # no fixtures at all
    heat = ds.load_heat_frames()
    fields = ds.load_fields()
    tiers = heat["field_tiers"]
    png = map_png_bytes(fields, tiers, "15:00", selected_field_id="PV-07")
    assert png.startswith(b"\x89PNG")  # real PNG bytes, offline
    assert len(png) > 20_000
    # Critical fields still flagged in the PNG scene (PV-07 at 15:00).
    assert tiers["15:00"]["PV-07"] == "critical"


# ---------------------------------------------------------------------------
# 6.4 time-short + 6.5 timing budgets
# ---------------------------------------------------------------------------
def _load_rehearsal() -> dict:
    if not REHEARSAL_LOG.exists():
        pytest.fail("run `python scripts/day6_rehearsal.py` first (task 6.3)")
    return json.loads(REHEARSAL_LOG.read_text())


def test_rehearsal_full_runs_completed():
    log = _load_rehearsal()
    assert log["kind"] == "day6_rehearsal_log"
    assert log["iterations"] >= 2  # 2x full demo rehearsals (task 6.3)
    assert log["core_only"] is False
    assert len(log["runs"]) == log["iterations"]
    for run in log["runs"]:
        assert run["all_scenes_under_budget"] is True
        assert run["all_transitions_under_2s"] is True


def test_scene_transitions_under_2s():
    log = _load_rehearsal()
    for run in log["runs"]:
        for seg in run["segments"]:
            assert seg["elapsed_ms"] / 1000.0 < 2.0, seg  # 6.5: <2s per scene


def test_total_pipeline_under_300s():
    log = _load_rehearsal()
    for run in log["runs"]:
        assert run["total_ms"] / 1000.0 < 300.0, run  # 6.5: full demo < 300s
        # Scene 1 (the heaviest: 3 folium maps) alone stays under 60s budget.
        s1 = next(s for s in run["segments"] if s["segment"] == "scene_1_field_map")
        assert s1["elapsed_ms"] / 1000.0 < 60.0


def test_time_short_core_only_variant(tmp_path):
    """4-minute fallback (skip Scene 5) — the 'time runs short' contingency."""
    import subprocess
    import sys

    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "day6_rehearsal.py"),
         "--core-only", "--iterations", "1"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, res.stderr
    log = json.loads((ROOT / "data" / "rehearsal" / "rehearsal_log_core.json").read_text())
    run = log["runs"][-1]
    assert run["core_only"] is True
    names = {s["segment"] for s in run["segments"]}
    assert "scene_5_scale" not in names
    assert run["all_scenes_under_budget"] is True
