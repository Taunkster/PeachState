"""Day-2 tests — env_params °F accessors, heat_intelligence digest/result,
corridor tiling math, ga_fields.geojson, crop_thresholds citations, and the
WAL-mode SQLite persistence store.

Offline (mocked) at the SDK boundary; live calls stay in test_integration.py.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from fortyguard_sdk import (
    EnvParamsRequest,
    EnvParamsResult,
    HeatIntelligenceDigest,
    HeatIntelligenceRequest,
    HeatIntelligenceResult,
    Plan,
    c_to_f,
    corridor_segments,
    corridor_tile_summary,
    f_to_c,
    route_nodes,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# env_params models
# ---------------------------------------------------------------------------
def test_c_to_f_roundtrip():
    assert c_to_f(0.0) == 32.0
    assert c_to_f(30.0) == 86.0
    assert f_to_c(c_to_f(30.0)) == pytest.approx(30.0)
    assert f_to_c(86.0) == pytest.approx(30.0)


def test_env_params_result_from_live_shape():
    """Shape copied from the day-1 live fixture (scalar temperature + param arrays)."""
    raw = {
        "metadata": {"timezone": "GMT-6", "timezone_offset_hours": -6},
        "locations": [
            {
                "lat": 32.5517,
                "lon": -83.8871,
                "elevation": 159.0,
                "temperature": 32.0,
                "parameters": {
                    "heat_index_celsius": [35.9],
                    "relative_humidity_percent": [56.2],
                    "wet_bulb_temperature_celsius": [25.0],
                },
            }
        ],
    }
    res = EnvParamsResult.from_result(raw)
    loc = res.locations[0]
    assert loc.temperature == 32.0
    assert loc.temperature_f == pytest.approx(89.6, abs=0.1)
    assert loc.heat_index_c == 35.9
    assert loc.heat_index_f == pytest.approx(96.62, abs=0.1)
    assert loc.relative_humidity_percent == 56.2
    assert loc.elevation == 159.0
    assert res.metadata.timezone == "GMT-6"


def test_env_params_fahrenheit_snapshot():
    from fortyguard_sdk.models.env_params import LocationParams

    loc = LocationParams(
        lat=32.55, lon=-83.88, elevation=159.0, temperature=32.0,
        parameters={
            "heat_index_celsius": [31.7],
            "wet_bulb_temperature_celsius": [25.0],
            "relative_humidity_percent": [37.0],
        },
    )
    f = loc.fahrenheit()
    assert f["temperature_f"] == pytest.approx(89.6, abs=0.1)
    assert f["heat_index_f"] == pytest.approx(89.06, abs=0.1)
    assert f["wet_bulb_f"] == pytest.approx(77.0, abs=0.1)
    # properties stay celsius, fahrenheit via properties
    assert loc.wet_bulb_f == pytest.approx(77.0, abs=0.1)


def test_aqi_param_mapping():
    from fortyguard_sdk import AQI_PARAMS
    from fortyguard_sdk.models.env_params import LocationParams

    # short-name map resolves to canonical full parameter names
    assert AQI_PARAMS["idx"] == "air_quality:idx"
    assert AQI_PARAMS["pm2p5"] == "air_quality_pm2p5:idx"
    for k, v in AQI_PARAMS.items():
        assert isinstance(k, str) and isinstance(v, str)
    # accessor works through the short-name map
    loc = LocationParams(
        lat=32.55, lon=-83.88, temperature=32.0,
        parameters={"air_quality:idx": [62.0], "air_quality_pm2p5:idx": [38.0]},
    )
    assert loc.aqi("idx") == 62.0
    assert loc.aqi_idx == 62.0
    assert loc.pm2p5 == 38.0


# ---------------------------------------------------------------------------
# heat_intelligence models
# ---------------------------------------------------------------------------
def test_hi_digest_build_basic():
    req = HeatIntelligenceRequest(
        latitude=32.5517, longitude=-83.8871,
        temperature=32.8, date="2025-07-15", analysis=["environmental"],
    )
    d = HeatIntelligenceDigest.build("digest-32.552-83.887", req, temperature_c=32.8)
    assert d.is_digest is True
    assert d.activity_id == "digest-32.552-83.887"
    assert d.download_link is None
    # analysis label is human readable
    assert "environmental" in json.dumps(d.sections)


def test_hi_result_from_result():
    r = HeatIntelligenceResult.from_result(
        "act-1",
        {"download_link": "https://example.invalid/report.pdf",
         "metadata": {"pages": 4}},
        status="Completed",
    )
    assert r.activity_id == "act-1"
    assert r.download_link == "https://example.invalid/report.pdf"
    assert r.metadata == {"pages": 4}
    assert r.is_digest is False
    assert r.summary == {}


def test_hi_labels():
    from fortyguard_sdk import HI_ANALYSES, HI_ANALYSIS_LABELS

    assert set(HI_ANALYSES) == {
        "geographic", "environmental", "urban", "events", "anthropogenic",
    }
    assert "environmental" in HI_ANALYSIS_LABELS


# ---------------------------------------------------------------------------
# corridor tiling math
# ---------------------------------------------------------------------------
# Straight Macon->Savannah line in (lon, lat) — ~157 mi as the crow flies.
MACON_SAV = [(-83.6324, 32.8407), (-81.0912, 32.0809)]


def test_corridor_segments_premium_5_tiles():
    tiles = corridor_segments(
        MACON_SAV, buffer_m=805.0, plan=Plan.PREMIUM, route_id="I16"
    )
    # ~157 mi at ~1 mi band / 50 mi² cap -> ~5 tiles
    assert 4 <= len(tiles) <= 6
    for t in tiles:
        assert t["name"].startswith("corridor-I16-tile-")
        props = t["features"][0]["properties"]
        assert props["route_id"] == "I16"


def test_corridor_segments_basic_9_tiles():
    tiles = corridor_segments(
        MACON_SAV, buffer_m=402.0, plan=Plan.BASIC, route_id="I16"
    )
    # ~0.5 mi band / 10 mi² cap -> ~9 tiles
    assert 8 <= len(tiles) <= 11


def test_corridor_tile_summary_shape():
    summary = corridor_tile_summary(
        MACON_SAV, buffer_m=805.0, plan=Plan.PREMIUM, route_id="I16"
    )
    assert summary["route_id"] == "I16"
    assert summary["plan"] == "premium"
    assert summary["tiles"] >= 1
    assert summary["tiles"] == len(summary["tile_area_sqmi"])
    assert summary["within_plan_cap"] is True
    for a in summary["tile_area_sqmi"]:
        assert a <= 50.0 + 1e-6
    assert summary["route_length_mi"] > 100
    assert summary["band_width_mi"] == pytest.approx(1.0, abs=0.01)


def test_route_nodes_spacing():
    nodes = route_nodes(MACON_SAV, "I16", spacing_mi=5.0)
    assert isinstance(nodes, list)
    assert len(nodes) >= 30  # ~157 mi / 5 mi
    assert nodes[0]["route_id"] == "I16"
    assert nodes[0]["distance_mi"] == 0.0
    # spacing roughly 5 mi between consecutive nodes (distance_mi is cumulative)
    for i in range(1, len(nodes)):
        d = abs(nodes[i]["distance_mi"] - nodes[i - 1]["distance_mi"])
        assert 4.0 < d < 6.0
    # node coords fall inside Georgia bounds
    assert all(-85.0 < n["lon"] < -80.0 for n in nodes)
    assert all(31.5 < n["lat"] < 33.5 for n in nodes)


# ---------------------------------------------------------------------------
# ga_fields.geojson (2.3)
# ---------------------------------------------------------------------------
def test_ga_fields_feature_count_and_crops():
    fc = json.loads((ROOT / "data" / "ga_fields.geojson").read_text())
    feats = fc["features"]
    assert len(feats) == 45
    counts: dict[str, int] = {}
    for f in feats:
        crop = f["properties"]["crop"]
        counts[crop] = counts.get(crop, 0) + 1
    assert counts == {"peach": 15, "pecan": 10, "blueberry": 8, "onion": 12}
    # every field polygon is valid GeoJSON
    for f in feats:
        assert f["geometry"]["type"] == "Polygon"
        assert len(f["geometry"]["coordinates"][0]) >= 4


def test_ga_fields_regions():
    fc = json.loads((ROOT / "data" / "ga_fields.geojson").read_text())
    for f in fc["features"]:
        p = f["properties"]
        assert p["region"] in {"fort_valley", "albany", "bacon_appling", "vidalia"}
        assert p["area_acres"] > 0
        assert p["gdd_base_f"] in (40.0, 50.0, 55.0)


# ---------------------------------------------------------------------------
# crop_thresholds.json (2.7)
# ---------------------------------------------------------------------------
def test_crop_thresholds_pecan_gdd_base_55():
    from coolchain.domain.thresholds import crop_thresholds

    t = crop_thresholds("pecan")
    assert t["gdd_base_f"] == 55.0
    assert t["q10"] == 2.2
    assert t["alert_f"] == 95.0


def test_crop_thresholds_vidalia_alias_and_sources():
    from coolchain.domain.thresholds import crop_thresholds

    d = json.loads((ROOT / "data" / "crop_thresholds.json").read_text())
    assert d["crops"]["vidalia_onion"]["gdd_base_f"] == 40.0
    # onion key maps to the same config
    assert crop_thresholds("onion")["gdd_base_f"] == 40.0
    # sources + overall citations present
    assert len(d.get("sources_overall", [])) >= 3
    pecan = d["crops"]["pecan"]
    assert pecan["gdd_base_f"] == 55.0
    assert len(pecan.get("sources", [])) >= 1


# ---------------------------------------------------------------------------
# persistence (2.6)
# ---------------------------------------------------------------------------
def test_persistence_wal_schema_and_roundtrip(tmp_path):
    from coolchain.services.persistence import Persistence

    db = tmp_path / "coolchain.db"
    p = Persistence(db)
    try:
        # WAL mode is on
        conn = p.reader()
        try:
            wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert wal == "wal"
        finally:
            conn.close()

        tables = p.table_counts()
        for t in ("fields", "heat_samples", "corridor_segments", "env_samples",
                  "spoilage_events", "alerts", "reports"):
            assert t in tables

        # upsert a field and round-trip it
        p.upsert_field({
            "id": "PV-01",
            "properties": {
                "name": "Fort Valley Demo Block", "crop": "peach",
                "region": "fort_valley", "area_acres": 42.0,
                "packing_house_id": "PH-01", "gdd_base_f": 50.0,
                "stage_sensitivity_window": "bloom_to_harvest",
            },
            "geometry": {"type": "Polygon", "coordinates": [[
                [-83.90, 32.56], [-83.89, 32.56],
                [-83.89, 32.57], [-83.90, 32.57], [-83.90, 32.56],
            ]]},
        })
        rows = p.load_fields()
        assert len(rows) == 1
        assert rows[0]["crop"] == "peach"
        assert rows[0]["gdd_base_f"] == 50.0
        assert rows[0]["area_acres"] == 42.0

        # upsert again -> still one row (idempotent)
        p.upsert_field({
            "id": "PV-01",
            "properties": {"name": "Renamed", "crop": "peach", "region": "fort_valley"},
            "geometry": None,
        })
        assert len(p.load_fields()) == 1
        assert p.load_fields()[0]["name"] == "Renamed"

        # heat sample insert + query
        p.insert_heat_sample(
            "PV-01", "2025-07-15T18:00:00Z", analytic_type="tcm",
            temp_c=33.6, temp_f=92.5, n_cells=64,
        )
        samples = p.heat_samples("PV-01")
        assert len(samples) == 1
        assert samples[0]["temp_c"] == 33.6
    finally:
        p.close()


def test_persistence_concurrent_reader(tmp_path):
    from coolchain.services.persistence import Persistence

    p = Persistence(tmp_path / "coolchain.db")
    try:
        conn = p.reader()          # read while writer open
        try:
            assert conn.execute("SELECT count(*) FROM fields").fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        p.close()