"""Pipeline logic tests (mocked client — no live API).

Covers: canopy risk engine, harvest timing, corridor segmentation math,
spoilage kinetics, and the GA field clusterer.
"""

from __future__ import annotations

from datetime import date

import pytest

from coolchain.domain.canopy_risk import RiskInputs, canopy_risk_score, tier
from coolchain.domain.harvest_timing import (
    GA_CROP_GDD,
    evaluate_harvest,
    gdd_daily,
)
from coolchain.domain.routing import RouteConfig, RoutePoint
from coolchain.domain.spoilage import degree_hours, spoilage_risk
from coolchain.services.clustering import GAFieldClusterer
from coolchain.services.pipeline_a import FieldCluster


# ---------------------------------------------------------------------------
# Canopy risk (Georgia crops)
# ---------------------------------------------------------------------------
def test_canopy_risk_critical_peach():
    # 39.5°C = 103°F, above peach critical 100°F with 8h exceedance
    res = canopy_risk_score(
        "PV-01",
        RiskInputs(tcm_c=39.5, exceedance_h=8, persistence_h=6, humidity_pct=80,
                   heat_index_c=50, wbgt_c=33),
        crop="peach",
    )
    assert res.score >= 75
    assert res.tier.value == "critical"


def test_canopy_risk_low_and_missing_handling():
    res = canopy_risk_score("VD-07", RiskInputs(tcm_c=22.0), crop="onion")
    assert res.score < 40
    assert "humidity" in res.missing  # missing inputs recorded, not zeroed


def test_crop_thresholds_present():
    from fortyguard_sdk import GA_CROP_THRESHOLDS_F

    assert GA_CROP_THRESHOLDS_F["onion"] == 85.0   # Vidalia onions most sensitive
    assert GA_CROP_THRESHOLDS_F["blueberry"] == 90.0


def test_tier_thresholds():
    assert tier(30).value == "low"
    assert tier(50).value == "medium"
    assert tier(70).value == "high"
    assert tier(80).value == "critical"


# ---------------------------------------------------------------------------
# Harvest timing (GDD + alert)
# ---------------------------------------------------------------------------
def test_gdd_daily():
    assert gdd_daily(95.0, 65.0, 50.0) == 30.0   # avg 80 - 50
    assert gdd_daily(85.0, 70.0, 50.0) == 27.5
    assert gdd_daily(45.0, 40.0, 50.0) == 0.0    # below base


def test_harvest_alert_fires_when_gdd_met():
    dec = evaluate_harvest(
        "PV-01", "peach",
        risk_score=88.0, persistence_h=5.0, gdd_season=2400.0,  # > harvest_gdd 2200
        warm_night=True, cooldown_ok=True,
    )
    assert dec.alert
    assert "Harvest" in dec.reason or "urgency" in dec.reason


def test_harvest_alert_blocked_by_gdd():
    dec = evaluate_harvest(
        "PV-01", "peach",
        risk_score=88.0, persistence_h=5.0, gdd_season=800.0,  # target not met
        warm_night=True, cooldown_ok=True,
    )
    assert not dec.alert
    assert "GDD" in dec.reason


def test_harvest_alert_cooldown():
    dec = evaluate_harvest(
        "PV-01", "peach",
        risk_score=88.0, persistence_h=5.0, gdd_season=2400.0,
        cooldown_ok=False,
    )
    assert not dec.alert
    assert "cooldown" in dec.reason


# ---------------------------------------------------------------------------
# Spoilage (Q10 kinetics)
# ---------------------------------------------------------------------------
def test_degree_hours():
    series = [35.0, 38.0, 40.0, 33.0]   # °C
    # peach threshold 95°F = 35°C
    dh = degree_hours(series, 95.0)
    assert 0.0 < dh < 20.0


def test_spoilage_risk_monotonic():
    low = spoilage_risk("blueberry", [33.0, 33.5, 34.0])
    high = spoilage_risk("blueberry", [40.0, 41.0, 42.0])
    assert high.spoilage_risk > low.spoilage_risk
    assert 0.0 <= high.spoilage_risk <= 1.0
    assert high.est_loss_usd > 0


# ---------------------------------------------------------------------------
# Corridor segmentation math
# ---------------------------------------------------------------------------
def test_corridor_segment_count_basic():
    """~176 mi Macon->Savannah @ 1km band -> ~11 segments on Basic."""
    from coolchain.domain.routing import PipelineC

    # stub client so plan is BASIC without network
    class _FakeClient:
        plan = None

    from fortyguard_sdk import Plan as _Plan

    class _Client:
        def __init__(self):
            self.plan = _Plan.BASIC

    # Reuse the solver's segmentation logic directly (no client calls).
    solver = PipelineC.__new__(PipelineC)
    solver.client = _Client()
    solver.config = RouteConfig()

    samples = []
    # build ~282 km corridor at 8 km spacing -> ~36 points
    import math
    n = int(282.0 / 8.0) + 1
    for i in range(n + 1):
        t = i / n
        samples.append(RoutePoint(lon=-83.63 + (-81.09 + 83.63) * t,
                                  lat=32.84 + (32.08 - 32.84) * t,
                                  distance_km=282.0 * t))
    segments = solver._segment_by_area(samples)
    # Basic 10 mi² -> 25.9 km segments -> ~282/25.9 ≈ 11
    assert len(segments) == 11


def test_corridor_segment_count_premium():
    from coolchain.domain.routing import PipelineC

    from fortyguard_sdk import Plan as _Plan

    class _Client:
        def __init__(self):
            self.plan = _Plan.PREMIUM

    solver = PipelineC.__new__(PipelineC)
    solver.client = _Client()
    solver.config = RouteConfig()

    n = int(282.0 / 8.0) + 1
    samples = []
    for i in range(n + 1):
        t = i / n
        samples.append(RoutePoint(lon=-83.63 + (-81.09 + 83.63) * t,
                                  lat=32.84 + (32.08 - 32.84) * t,
                                  distance_km=282.0 * t))
    segments = solver._segment_by_area(samples)
    # Premium 50 mi² -> ~129.5 km segments -> ~282/129.5 ≈ 3
    assert len(segments) == 3


# ---------------------------------------------------------------------------
# GA field clustering
# ---------------------------------------------------------------------------
def test_clustering_ga_fields_fit_basic_limit():
    import json
    from pathlib import Path

    fc = json.loads(
        Path("data/ga_fields.geojson").read_text()
    )
    clusterer = GAFieldClusterer(fc["features"])
    clusters = clusterer.all_clusters(plan_area_sqmi=10.0)
    # 45 GA fields (Day-2 dataset): each field fits under the 10 mi² cap, so
    # clusters <= 45; nearby same-crop fields may merge -> fewer clusters.
    assert 1 <= len(clusters) <= len(fc["features"]) == 45
    assert all(isinstance(c, FieldCluster) for c in clusters)
    # every field must be assigned to exactly one cluster
    assigned = [f["id"] for c in clusters for f in c.features]
    assert len(assigned) == len(set(assigned)) == len(fc["features"])
    # each cluster crop should be consistent
    for c in clusters:
        crops = {f["properties"]["crop"] for f in c.features}
        assert len(crops) == 1


def test_cluster_areas_within_limit():
    import json
    from pathlib import Path

    from fortyguard_sdk import estimate_aoe_area_sqmi

    fc = json.loads(Path("data/ga_fields.geojson").read_text())
    clusterer = GAFieldClusterer(fc["features"])
    clusters = clusterer.all_clusters(plan_area_sqmi=10.0)
    for c in clusters:
        assert estimate_aoe_area_sqmi(c.feature_collection) <= 10.0