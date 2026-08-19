"""FortyGuard SDK — Georgia geographic guard.

The FortyGuard Temperature API covers the United States only (Georgia
confirmed 2026-08-18). This module fails fast on non-GA coordinates so
pipelines never waste API quota on uncovered regions.
"""

from __future__ import annotations

from .exceptions import GeorgiaBoundaryError

# Georgia state bounding box (approx, generous).
GA_BBOX = {
    "min_lat": 30.36,
    "max_lat": 35.00,
    "min_lon": -85.61,
    "max_lon": -80.75,
}

# Confirmed GA pilot locations (demo day-1 validation targets).
GA_PILOT_LOCATIONS = {
    "fort_valley":      {"lat": 32.5538, "lon": -83.8874, "crop": "peach"},
    "albany":           {"lat": 31.5785, "lon": -84.1557, "crop": "pecan"},
    "bacon_county":     {"lat": 31.5394, "lon": -82.4637, "crop": "blueberry"},
    "vidalia":          {"lat": 32.2177, "lon": -82.4135, "crop": "onion"},
    "macon":            {"lat": 32.8407, "lon": -83.6324, "crop": "hub"},
    "savannah":         {"lat": 32.0809, "lon": -81.0912, "crop": "port"},
    "athens":           {"lat": 33.9519, "lon": -83.3576, "crop": "trial_garden"},
    "atlanta":          {"lat": 33.7490, "lon": -84.3880, "crop": "urban"},
}


def assert_in_georgia(lat: float, lon: float) -> None:
    """Raise GeorgiaBoundaryError when lat/lon fall outside the GA bbox."""
    b = GA_BBOX
    if not (b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]):
        raise GeorgiaBoundaryError(lat, lon)


def is_in_georgia(lat: float, lon: float) -> bool:
    try:
        assert_in_georgia(lat, lon)
        return True
    except GeorgiaBoundaryError:
        return False