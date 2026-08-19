"""Day-3 domain-logic tests.

Covers the four Day-3 modules plus their SQLite integration (3.6):
    3.1 canopy risk engine (canopy temp + crop weights + growth stage +
        worker WBGT sub-score)
    3.2 harvest timing (GDD progress + stress bonus + 48h cooldown)
    3.3 spoilage Q10 kinetics (degree-hours + lethal term + cold-chain breaks
        + transit thermal box)
    3.4 corridor routing (I-16 vs I-75 heat exposure + UTM distance)

Offline — no live API calls.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from coolchain.domain.canopy_risk import (
    RiskInputs,
    canopy_heat_risk,
    estimate_canopy_temp,
    normalized_temp_score,
    worker_wbgt_subscore,
)
from coolchain.domain.harvest_timing import (
    accumulate_gdd,
    compute_urgency,
    cooldown_active,
    evaluate_harvest_alert,
    gdd_daily,
    gdd_from_mean,
    heat_stress_days,
)
from coolchain.domain.routing import (
    compare_corridor_routes,
    demo_route_temps,
    geodesic_distance_mi,
    heat_exposure_integral,
    load_corridor_nodes,
    utm_crs_for,
    utm_distance_mi,
)
from coolchain.domain.spoilage import (
    degree_hours_f,
    detect_cold_chain_breaks,
    evaluate_spoilage,
    spoilage_risk_pct,
    transit_thermal,
)
from coolchain.domain.thresholds import crop_thresholds


# ---------------------------------------------------------------------------
# 3.1 Canopy heat risk engine
# ---------------------------------------------------------------------------
def test_canopy_peach_critical_at_100f():
    """Canopy temp at peach critical (100°F) + high exceedance -> critical."""
    res = canopy_heat_risk(
        "PV-01",
        RiskInputs(tcm_c=37.78, exceedance_h=8.0, persistence_h=6.0,
                   humidity_pct=100.0, ghi=0.0),
        crop="peach",
    )
    assert res.canopy_temp_f == pytest.approx(100.0, abs=0.1)
    assert res.score >= 75
    assert res.tier.value == "critical"


def test_canopy_peach_low_at_85f():
    """85°F canopy is below peach alert (95°F) -> low risk."""
    res = canopy_heat_risk(
        "PV-01",
        RiskInputs(tcm_c=29.44, humidity_pct=100.0, ghi=0.0),
        crop="peach",
    )
    assert res.canopy_temp_f == pytest.approx(85.0, abs=0.1)
    assert res.score < 40
    assert res.tier.value == "low"


def test_canopy_weights_from_crop_config():
    """Per-crop risk weights come from crop_thresholds.json."""
    assert crop_thresholds("peach")["risk_weights"] == {
        "temp": 0.45, "exceedance": 0.35, "persistence": 0.20,
    }
    assert crop_thresholds("blueberry")["risk_weights"] == {
        "temp": 0.50, "exceedance": 0.30, "persistence": 0.20,
    }


def test_canopy_temp_estimate_and_cap():
    """T_canopy = T_air + k·GHI − c·VPD, capped at T_air + 10°F."""
    # high humidity -> low VPD -> less transpirational cooling -> hotter canopy
    dry = estimate_canopy_temp(95.0, ghi=500.0, humidity_pct=30.0)
    humid = estimate_canopy_temp(95.0, ghi=500.0, humidity_pct=90.0)
    assert humid > dry
    # cap at T_air + 10°F (physical bound)
    hot = estimate_canopy_temp(95.0, ghi=3000.0, humidity_pct=10.0)
    assert hot <= 105.0 + 1e-9
    assert hot >= 95.0


def test_canopy_growth_stage_multiplier():
    """Pre-harvest 2-week window scales risk by 1.2×."""
    base = RiskInputs(tcm_c=36.39, humidity_pct=100.0)  # canopy 97.5°F
    normal = canopy_heat_risk("PV-01", base, crop="peach")
    preharvest = canopy_heat_risk(
        "PV-01", base, crop="peach", in_preharvest_window=True)
    assert preharvest.score == pytest.approx(normal.score * 1.2, abs=0.5)
    assert preharvest.stage_multiplier == 1.2
    assert normal.stage_multiplier == 1.0


def test_worker_wbgt_subscore_separate_from_crop():
    """WBGT worker score is independent of (cool) crop risk."""
    res = canopy_heat_risk(
        "PV-01",
        RiskInputs(tcm_c=29.44, wbgt_c=32.2, humidity_pct=100.0),  # 85°F / 90°F
        crop="peach",
    )
    assert res.score < 40                     # cool canopy -> low crop risk
    assert res.worker_wbgt_f == pytest.approx(90.0, abs=0.2)
    assert res.worker_score is not None and res.worker_score >= 70
    assert res.worker_category == "VERY HIGH"
    # direct function call
    w = worker_wbgt_subscore(80.0)
    assert w is not None and w.score <= 40


def test_normalized_temp_score_ramp():
    assert normalized_temp_score(90.0, 95.0, 100.0) == 0.0
    assert normalized_temp_score(95.0, 95.0, 100.0) == 0.0
    assert normalized_temp_score(97.5, 95.0, 100.0) == 0.5
    assert normalized_temp_score(100.0, 95.0, 100.0) == 1.0
    assert normalized_temp_score(103.0, 95.0, 100.0) == 1.0


# ---------------------------------------------------------------------------
# 3.2 Harvest timing
# ---------------------------------------------------------------------------
def test_gdd_math():
    assert gdd_daily(95.0, 65.0, 50.0) == 30.0
    assert gdd_from_mean(85.0, 50.0) == 35.0
    assert accumulate_gdd([85.0, 90.0, 95.0], 50.0) == 120.0
    assert heat_stress_days([90.0, 96.0, 100.0], 95.0) == 2


def test_urgency_gdd_progress_plus_stress_bonus():
    progress, bonus, urgency = compute_urgency(850.0, 850.0, 6)
    assert progress == 100.0
    assert bonus == 30.0                      # min(30, 6*5)
    assert urgency == 100.0
    progress2, bonus2, urgency2 = compute_urgency(425.0, 850.0, 2)
    assert progress2 == 50.0
    assert bonus2 == 10.0
    assert urgency2 == 60.0


def test_harvest_alert_fires_on_gdd_and_exceedance():
    alert = evaluate_harvest_alert(
        "PV-01", "peach",
        gdd_accumulated=765.0, stress_days=5, forecast_exceedance_h=7.0,
        last_alert_ts=None, now_ts="2026-08-18T12:00:00+00:00",
    )
    assert alert.triggered
    assert alert.urgency > 80
    assert "HARVEST NOW" in alert.recommended_action
    assert alert.cooldown_until is not None


def test_harvest_alert_blocked_when_exceedance_low():
    alert = evaluate_harvest_alert(
        "PV-01", "peach",
        gdd_accumulated=765.0, stress_days=5, forecast_exceedance_h=3.0,
        last_alert_ts=None, now_ts="2026-08-18T12:00:00+00:00",
    )
    assert not alert.triggered
    assert "Continue monitoring" in alert.recommended_action


def test_harvest_cooldown_blocks_repeat_alerts():
    first = evaluate_harvest_alert(
        "PV-01", "peach",
        gdd_accumulated=765.0, stress_days=5, forecast_exceedance_h=7.0,
        last_alert_ts=None, now_ts="2026-08-18T12:00:00+00:00",
    )
    assert first.triggered
    assert cooldown_active(first.cooldown_until, "2026-08-18T18:00:00+00:00")

    repeat = evaluate_harvest_alert(
        "PV-01", "peach",
        gdd_accumulated=765.0, stress_days=5, forecast_exceedance_h=7.0,
        last_alert_ts="2026-08-18T12:00:00+00:00",
        now_ts="2026-08-19T00:00:00+00:00",   # +12h, inside 48h window
    )
    assert not repeat.triggered
    assert "Cooldown active" in repeat.recommended_action
    assert repeat.cooldown_until is not None


def test_harvest_cooldown_expires_after_48h():
    later = evaluate_harvest_alert(
        "PV-01", "peach",
        gdd_accumulated=765.0, stress_days=5, forecast_exceedance_h=7.0,
        last_alert_ts="2026-08-18T12:00:00+00:00",
        now_ts="2026-08-20T13:00:00+00:00",   # +49h -> cooldown expired
    )
    assert later.triggered


# ---------------------------------------------------------------------------
# 3.3 Spoilage Q10 kinetics
# ---------------------------------------------------------------------------
def test_degree_hours_monotonic_with_temp():
    low = degree_hours_f([85.0, 86.0, 87.0], 85.0)
    high = degree_hours_f([95.0, 96.0, 97.0], 85.0)
    assert low == 3.0
    assert high == 33.0
    assert high > low
    assert degree_hours_f([80.0, 84.0], 85.0) == 0.0   # below threshold


def test_lethal_term_accelerates():
    """Above lethal_temp_f, DH accumulates at 10× the excess."""
    plain = degree_hours_f([101.0, 102.0], 95.0)            # 13.0
    lethal = degree_hours_f([101.0, 102.0], 95.0, lethal_temp_f=100.0)
    assert plain == 13.0
    assert lethal == pytest.approx(13.0 + (1 + 2) * 10.0, abs=0.1)
    assert lethal > plain


def test_spoilage_risk_pct():
    assert spoilage_risk_pct(240.0, 480.0) == 50.0
    assert spoilage_risk_pct(960.0, 480.0) == 100.0
    assert spoilage_risk_pct(0.0, 480.0) == 0.0


def test_cold_chain_break_detection():
    # 2h run at 38-39°F vs 34°F setpoint (+3°F limit) -> flagged
    long_break = detect_cold_chain_breaks(
        [34.0, 35.0, 38.0, 39.0, 34.0],
        setpoint_f=34.0, delta_f=3.0, min_break_min=30.0, interval_h=1.0,
    )
    assert len(long_break) == 1
    assert long_break[0]["duration_min"] == 120.0
    # 15-minute blip at interval 0.25h -> not flagged
    short = detect_cold_chain_breaks(
        [34.0, 38.0, 34.0, 34.0],
        setpoint_f=34.0, delta_f=3.0, min_break_min=30.0, interval_h=0.25,
    )
    assert short == []


def test_transit_thermal_box():
    """Product temp approaches ambient with the box model."""
    amb = [90.0, 95.0, 98.0, 100.0]
    prod = transit_thermal(amb, t_initial_f=34.0, tau_h=6.0, interval_h=1.0)
    assert prod[0] > 34.0
    assert prod[-1] < amb[-1]               # hasn't fully equilibrated
    assert prod[-1] > prod[0]               # monotonic warm-up


def test_evaluate_spoilage_result():
    res = evaluate_spoilage(
        "PV-01", "peach",
        temp_series_f=[96.0, 98.0, 100.0], interval_h=1.0,
        trailer_temp_series_f=[34.0, 39.0, 39.0, 34.0],
    )
    assert res.dh_accumulated > 0
    assert res.risk_pct > 0
    assert res.cold_chain_breaks == 1
    assert 0 < res.estimated_shelf_life_days <= 14.0
    assert isinstance(res, BaseModel)       # typed (pydantic) output


# ---------------------------------------------------------------------------
# 3.4 Corridor routing
# ---------------------------------------------------------------------------
def test_i16_less_heat_exposure_than_i75():
    nodes = load_corridor_nodes()
    res = compare_corridor_routes(nodes)
    by_id = {r.route_id: r for r in res.routes}
    assert by_id["I16"].heat_exposure < by_id["I75"].heat_exposure
    assert by_id["I16"].avg_temp_f < by_id["I75"].avg_temp_f
    assert res.recommended == "I16"
    assert res.saved_heat_exposure > 0
    # I-75 is a >15% detour vs the I-16 baseline
    assert not by_id["I16"].detour_violation
    assert by_id["I75"].detour_violation


def test_utm_distance_matches_geodesic_within_1percent():
    nodes = load_corridor_nodes()
    for rid in ("I16", "I75"):
        utm = utm_distance_mi(nodes[rid])
        geo = geodesic_distance_mi(nodes[rid])
        assert utm > 100
        assert geo > 100
        assert abs(utm - geo) / geo < 0.01, f"{rid}: {utm} vs {geo}"


def test_utm_crs_for_georgia_corridor():
    # Macon -> EPSG:32617 (UTM 17N)
    assert utm_crs_for(32.8407, -83.6324) == 32617
    assert utm_crs_for(32.0809, -81.0912) == 32617


def test_heat_exposure_integral_uses_temp_times_distance():
    nodes = load_corridor_nodes()["I16"]
    temps = demo_route_temps(nodes)
    exposure = heat_exposure_integral(nodes, temps)
    # exposure is a weighted sum of temp × distance, bounded by total
    assert exposure > 0
    assert exposure < 200.0 * 100.0          # avg temp well under 100°F... sanity


# ---------------------------------------------------------------------------
# 3.6 SQLite integration
# ---------------------------------------------------------------------------
def _seed_field(persistence, field_id="PV-01", crop="peach"):
    persistence.upsert_field({
        "id": field_id,
        "properties": {
            "name": "Fort Valley Demo Block", "crop": crop,
            "region": "fort_valley", "area_acres": 42.0,
            "packing_house_id": "PH-01", "gdd_base_f": 50.0,
            "stage_sensitivity_window": "bloom_to_harvest",
        },
        "geometry": {"type": "Polygon", "coordinates": [[
            [-83.90, 32.56], [-83.89, 32.56],
            [-83.89, 32.57], [-83.90, 32.57], [-83.90, 32.56],
        ]]},
    })


def test_integration_canopy_risk_writes_risk_scores(tmp_path):
    from coolchain.domain.canopy_risk import score_field_from_db
    from coolchain.services.persistence import Persistence

    p = Persistence(tmp_path / "coolchain.db")
    try:
        _seed_field(p)
        p.insert_heat_sample(
            "PV-01", "2026-08-18T18:00:00Z", analytic_type="tcm",
            temp_c=36.0, temp_f=96.8, mean_c=36.0, max_c=37.5, n_cells=64,
        )
        p.insert_env_sample(
            "PV-01", "2026-08-18T18:00:00Z",
            temperature_f=96.8, heat_index_f=101.0, wet_bulb_f=80.0,
            relative_humidity_percent=62.0, ghi_wm2=820.0,
        )
        res = score_field_from_db(p, "PV-01")
        assert res is not None
        assert 0 <= res.score <= 100
        assert res.canopy_temp_f is not None
        assert res.canopy_temp_f > res.inputs.tcm_c * 9 / 5 + 32   # GHI warmed
        rows = p.risk_scores("PV-01")
        assert len(rows) == 1
        assert rows[0]["score"] == res.score
        assert rows[0]["tier"] == res.tier.value
    finally:
        p.close()


def test_integration_harvest_alert_and_cooldown(tmp_path):
    from coolchain.domain.harvest_timing import evaluate_field_from_db
    from coolchain.services.persistence import Persistence

    p = Persistence(tmp_path / "coolchain.db")
    try:
        _seed_field(p)
        # 4 days of mean temps above base -> GDD accumulates; day 4 max
        # crosses peach alert (95°F) -> 1 heat-stress day
        days = [
            ("2026-08-10", 27.0), ("2026-08-11", 28.0),
            ("2026-08-12", 29.0), ("2026-08-13", 30.0),
        ]
        for i, (day, mean_c) in enumerate(days):
            max_c = 36.0 if i == 3 else mean_c + 4   # day4: 96.8°F > 95°F
            p.insert_heat_sample(
                "PV-01", f"{day}T18:00:00Z", analytic_type="tcm",
                temp_c=mean_c + 2, temp_f=(mean_c + 2) * 9 / 5 + 32,
                mean_c=mean_c, max_c=max_c, n_cells=64,
            )
        # seed a risk score carrying exceedance_h proxy
        from coolchain.domain.canopy_risk import canopy_heat_risk, RiskInputs
        r = canopy_heat_risk(
            "PV-01", RiskInputs(tcm_c=31.0, exceedance_h=8.0), crop="peach",
            timestamp=f"{days[-1][0]}T18:00:00Z",
        )
        import json as _json
        p.insert_risk_score(
            "PV-01", f"{days[-1][0]}T18:00:00Z", crop="peach",
            score=r.score, tier=r.tier.value, canopy_temp_f=r.canopy_temp_f,
            worker_wbgt_f=r.worker_wbgt_f,
            components_json=_json.dumps(r.components),
        )
        alert = evaluate_field_from_db(
            p, "PV-01", now_ts="2026-08-14T12:00:00+00:00")
        assert alert is not None
        assert alert.gdd_accumulated > 0
        assert alert.stress_days >= 1
        # cooldown persists via alerts table after a trigger
        hot = evaluate_field_from_db(
            p, "PV-01", now_ts="2026-08-14T12:00:00+00:00")
        assert hot is not None
        p.insert_alert(
            "2026-08-14T12:00:00Z", field_id="PV-01",
            alert_type="harvest", severity="HIGH", message="HARVEST NOW",
        )
        last = p.latest_alert_ts("PV-01", alert_type="harvest")
        assert last is not None
        from coolchain.domain.harvest_timing import cooldown_active
        assert cooldown_active(last, "2026-08-15T00:00:00+00:00")
        assert not cooldown_active(last, "2026-08-18T12:00:00+00:00")
    finally:
        p.close()


def test_integration_spoilage_writes_events(tmp_path):
    from coolchain.domain.spoilage import evaluate_field_spoilage
    from coolchain.services.persistence import Persistence

    p = Persistence(tmp_path / "coolchain.db")
    try:
        _seed_field(p)
        p.insert_heat_sample(
            "PV-01", "2026-08-18T18:00:00Z", analytic_type="tcm",
            temp_c=37.0, temp_f=98.6, mean_c=37.0, max_c=38.0, n_cells=64,
        )
        res = evaluate_field_spoilage(p, "PV-01")
        assert res is not None
        assert res.dh_accumulated >= 0
        events = p.spoilage_events("PV-01")
        assert len(events) == 1
        assert events[0]["degree_hours_f"] == res.dh_accumulated
        assert events[0]["crop"] == "peach"
    finally:
        p.close()


def test_integration_routing_compares_from_db(tmp_path):
    from coolchain.domain.routing import compare_from_db
    from coolchain.services.persistence import Persistence

    p = Persistence(tmp_path / "coolchain.db")
    try:
        ts = "2026-08-18T18:00:00Z"
        nodes = load_corridor_nodes()
        for rid in ("I16", "I75"):
            base = 92.0 if rid == "I16" else 99.0
            for seg_id, node in enumerate(nodes[rid]):
                p.insert_corridor_segment(
                    rid, seg_id, ts, temp_f=base,
                    distance_mi=node["distance_mi"],
                )
        res = compare_from_db(p, ts=ts)
        by_id = {r.route_id: r for r in res.routes}
        assert by_id["I16"].heat_exposure < by_id["I75"].heat_exposure
        assert res.recommended == "I16"
        assert by_id["I16"].avg_temp_f == 92.0
        assert by_id["I75"].avg_temp_f == 99.0
    finally:
        p.close()