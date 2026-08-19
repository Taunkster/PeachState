#!/usr/bin/env python3
"""Build `data/ga_fields.geojson` — 45 synthetic GA farm parcels (Day 2).

Regions (all in the confirmed Georgia/US API coverage bbox):
    fort_valley  Peach County  -> 15 peach orchards (20-200 ac), ~20 mi² cluster
    albany       Dougherty Co. -> 10 pecan groves (50-500 ac), along Flint River
    bacon_appling Bacon/Appling->  8 blueberry farms (10-100 ac), US-1/US-23
    vidalia      Toombs County -> 12 onion fields (5-80 ac), curing sheds marked

Geometry is generated with shapely (rotated + jittered rectangles so parcels
look like real field boundaries), CRS EPSG:4326. Placement uses a perturbed
grid so parcels never overlap. Seeded RNG => deterministic output.

Usage:
    python scripts/build_ga_fields.py [--out data/ga_fields.geojson] [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

from shapely.geometry import Polygon
from shapely.geometry import mapping

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ---------------------------------------------------------------------------
# Region definitions
# ---------------------------------------------------------------------------
REGIONS = {
    "fort_valley": {
        "label": "Fort Valley / Peach County",
        "crop": "peach",
        "center": (-83.8874, 32.5538),
        "n": 15,
        "acres": (20, 200),
        "spacing_m": 2100,
        "grid": (5, 3),
        "gdd_base_f": 50.0,
        "stage_sensitivity_window": "pre-harvest_14d",
        "packing_houses": ["PH-FV-01", "PH-FV-02", "PH-FV-03"],
        "name_prefix": "Peach Orchard",
    },
    "albany": {
        "label": "Albany / Dougherty County",
        "crop": "pecan",
        "center": (-84.1557, 31.5785),
        "n": 10,
        "acres": (50, 500),
        "spacing_m": 3200,
        "grid": (5, 2),
        "gdd_base_f": 55.0,
        "stage_sensitivity_window": "nut_fill_6wk",
        "packing_houses": ["PH-AL-01", "PH-AL-02", "PH-AL-03"],
        "name_prefix": "Pecan Grove",
    },
    "bacon_appling": {
        "label": "Bacon / Appling Counties",
        "crop": "blueberry",
        "center": (-82.4637, 31.5394),
        "n": 8,
        "acres": (10, 100),
        "spacing_m": 1500,
        "grid": (4, 2),
        "gdd_base_f": 50.0,
        "stage_sensitivity_window": "fruit_set_4wk",
        "packing_houses": ["PH-BA-01", "PH-BA-02"],
        "name_prefix": "Blueberry Farm",
    },
    "vidalia": {
        "label": "Vidalia / Toombs County",
        "crop": "onion",
        "center": (-82.4135, 32.2177),
        "n": 12,
        "acres": (5, 80),
        "spacing_m": 1300,
        "grid": (4, 3),
        "gdd_base_f": 40.0,
        "stage_sensitivity_window": "curing_3wk",
        "packing_houses": ["PH-VD-01", "PH-VD-02", "PH-VD-03"],
        "name_prefix": "Onion Field",
    },
}

# id prefixes per region (stable, demo-recognizable)
PREFIX = {
    "fort_valley": "PV",
    "albany": "AL",
    "bacon_appling": "BA",
    "vidalia": "VD",
}

ACRE_M2 = 4046.8564224


def _deg_per_m(lat: float) -> tuple[float, float]:
    """(deg per meter lon, deg per meter lat) at latitude."""
    dlat = 1.0 / 110574.0
    dlon = 1.0 / (111320.0 * math.cos(math.radians(lat)))
    return (dlon, dlat)


def make_parcel(
    center_lon: float,
    center_lat: float,
    acres: float,
    rng: random.Random,
    *,
    aspect_range: tuple[float, float] = (1.8, 3.2),
) -> Polygon:
    """Rotated, jittered rectangle approximating a real farm parcel."""
    area_m2 = acres * ACRE_M2
    aspect = rng.uniform(*aspect_range)
    w_m = math.sqrt(area_m2 * aspect)
    h_m = area_m2 / w_m
    dlon, dlat = _deg_per_m(center_lat)
    w, h = w_m * dlon, h_m * dlat
    theta = rng.uniform(0.0, math.pi)          # field-row heading
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    jitter_m = max(5.0, min(w_m, h_m) * 0.04)  # ~4% edge wobble
    corners = []
    for dx, dy in [(-w / 2, -h / 2), (w / 2, -h / 2),
                   (w / 2, h / 2), (-w / 2, h / 2)]:
        rx = dx * cos_t - dy * sin_t
        ry = dx * sin_t + dy * cos_t
        jx = rng.uniform(-jitter_m, jitter_m) * dlon
        jy = rng.uniform(-jitter_m, jitter_m) * dlat
        corners.append((center_lon + rx + jx, center_lat + ry + jy))
    corners.append(corners[0])
    return Polygon(corners)


def geodesic_area_acres(poly: Polygon) -> float:
    """Accurate polygon area in acres (local equal-area projection)."""
    from fortyguard_sdk.models.heatmap import _polygon_area_sqkm

    km2 = _polygon_area_sqkm(mapping(poly))
    return km2 * 100.0 / 0.40468564224  # km2 -> acres (1 ac = 0.0040468 km2)


def build_fields(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    features: list[dict] = []

    for region_key, cfg in REGIONS.items():
        center_lon, center_lat = cfg["center"]
        dlon, dlat = _deg_per_m(center_lat)
        spacing = cfg["spacing_m"]
        cols, rows = cfg["grid"]
        prefix = PREFIX[region_key]
        for i in range(cfg["n"]):
            r, c = divmod(i, cols)
            # perturbed-grid placement -> guaranteed non-overlap
            base_lon = center_lon + (c - (cols - 1) / 2) * spacing * dlon
            base_lat = center_lat + (r - (rows - 1) / 2) * spacing * dlat
            jitter = spacing * 0.22
            clon = base_lon + rng.uniform(-jitter, jitter) * dlon
            clat = base_lat + rng.uniform(-jitter, jitter) * dlat
            # shift a bit further for the Flint River alignment (albany)
            if region_key == "albany":
                clon += rng.uniform(-0.01, 0.01)

            lo_ac, hi_ac = cfg["acres"]
            target_acres = round(rng.uniform(lo_ac, hi_ac), 1)
            poly = make_parcel(clon, clat, target_acres, rng)
            actual_acres = round(geodesic_area_acres(poly), 1)

            fid = f"{prefix}-{i + 1:02d}"
            ph = cfg["packing_houses"][i % len(cfg["packing_houses"])]
            props = {
                "id": fid,
                "name": f"{cfg['name_prefix']} {fid}",
                "crop": cfg["crop"],
                "region": region_key,
                "region_label": cfg["label"],
                "area_acres": actual_acres,
                "target_area_acres": target_acres,
                "packing_house_id": ph,
                "gdd_base_f": cfg["gdd_base_f"],
                "stage_sensitivity_window": cfg["stage_sensitivity_window"],
            }
            if region_key == "vidalia" and i % 3 == 0:
                props["has_curing_shed"] = True
            features.append(
                {
                    "type": "Feature",
                    "id": fid,
                    "properties": props,
                    "geometry": mapping(poly),
                }
            )
    return features


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO / "data" / "ga_fields.geojson")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    features = build_fields(args.seed)
    fc = {
        "type": "FeatureCollection",
        "name": "Georgia crop field polygons (45 synthetic parcels, EPSG:4326)",
        "schema_version": 2,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "generated_by": "scripts/build_ga_fields.py",
        "features": features,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fc, indent=2))
    print(f"wrote {len(features)} features -> {args.out}")

    # quick validation
    from shapely.geometry import shape

    for f in features:
        p = shape(f["geometry"])
        assert p.is_valid, f"invalid geometry: {f['id']}"
        assert p.area > 0
    by_crop: dict[str, int] = {}
    for f in features:
        by_crop[f["properties"]["crop"]] = by_crop.get(f["properties"]["crop"], 0) + 1
    print("crop counts:", by_crop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
