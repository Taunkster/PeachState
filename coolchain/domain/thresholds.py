"""PeachState CoolChain domain — crop threshold loader.

Single source of truth: `data/crop_thresholds.json` (created by the
demo/data owner). This loader merges that file over SDK defaults so the
domain logic and the dashboard always agree on thresholds, GDD targets,
and Q10 spoilage params.

Crop key mapping: the canonical file uses `vidalia_onion`; the SDK/code
uses short keys (`onion`). The loader normalizes both.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Defaults mirror SDK GA_CROP_THRESHOLDS_F and domain constants.
# Day 3 additions: risk_weights (temp/exceedance/persistence), lethal_temp_f
# (degree-hour lethal limit), tolerance_deg_hours (100% spoilage), canopy_k
# (solar heating coefficient °F per W/m²).
DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "peach":      {"alert_f": 95.0, "critical_f": 100.0, "q10": 2.8,
                   "gdd_base_f": 50.0, "gdd_target": 850.0,
                   "risk_weights": {"temp": 0.45, "exceedance": 0.35,
                                    "persistence": 0.20},
                   "lethal_temp_f": 104.0, "tolerance_deg_hours": 480.0,
                   "canopy_k": 0.008},
    "pecan":      {"alert_f": 95.0, "critical_f": 100.0, "q10": 2.2,
                   "gdd_base_f": 55.0, "gdd_target": 2200.0,
                   "risk_weights": {"temp": 0.40, "exceedance": 0.35,
                                    "persistence": 0.25},
                   "lethal_temp_f": 104.0, "tolerance_deg_hours": 600.0,
                   "canopy_k": 0.006},
    "blueberry":  {"alert_f": 90.0, "critical_f": 95.0, "q10": 3.2,
                   "gdd_base_f": 50.0, "gdd_target": 650.0,
                   "risk_weights": {"temp": 0.50, "exceedance": 0.30,
                                    "persistence": 0.20},
                   "lethal_temp_f": 100.0, "tolerance_deg_hours": 350.0,
                   "canopy_k": 0.010},
    "onion":      {"alert_f": 85.0, "critical_f": 90.0, "q10": 1.8,
                   "gdd_base_f": 40.0, "gdd_target": 950.0,
                   "risk_weights": {"temp": 0.55, "exceedance": 0.30,
                                    "persistence": 0.15},
                   "lethal_temp_f": 95.0, "tolerance_deg_hours": 720.0,
                   "canopy_k": 0.006},
    "watermelon": {"alert_f": 95.0, "critical_f": 100.0, "q10": 2.5,
                   "gdd_base_f": 55.0, "gdd_target": 1600.0,
                   "risk_weights": {"temp": 0.45, "exceedance": 0.35,
                                    "persistence": 0.20},
                   "lethal_temp_f": 100.0, "tolerance_deg_hours": 520.0,
                   "canopy_k": 0.008},
    "community":  {"alert_f": 90.0, "critical_f": 95.0, "q10": 2.5,
                   "gdd_base_f": 50.0, "gdd_target": 700.0,
                   "risk_weights": {"temp": 0.45, "exceedance": 0.35,
                                    "persistence": 0.20},
                   "lethal_temp_f": 100.0, "tolerance_deg_hours": 400.0,
                   "canopy_k": 0.008},
}

# canonical file aliases -> short keys
_CROP_ALIASES = {
    "vidalia_onion": "onion",
}

_default_path = Path(__file__).resolve().parents[2] / "data" / "crop_thresholds.json"


def load_thresholds(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return merged thresholds: canonical file (if present) over defaults."""
    merged = {k: dict(v) for k, v in DEFAULT_THRESHOLDS.items()}
    p = path or _default_path
    if not p.exists():
        return merged
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return merged
    for key, crop in (raw.get("crops") or {}).items():
        short = _CROP_ALIASES.get(key, key)
        if short not in merged:
            merged[short] = {}
        merged[short].update({
            "alert_f": crop.get("alert_f"),
            "critical_f": crop.get("critical_f"),
            "q10": crop.get("q10_spoilage"),
            "gdd_base_f": crop.get("gdd_base_f"),
            "gdd_target": (
                crop.get("gdd_target_bloom_to_harvest")
                or crop.get("gdd_target_plant_to_cure")
                or crop.get("gdd_target")
            ),
            "risk_weights": crop.get("risk_weights"),
            "lethal_temp_f": crop.get("lethal_temp_f"),
            "tolerance_deg_hours": crop.get("tolerance_deg_hours"),
            "canopy_k": crop.get("canopy_k"),
        })
        merged[short] = {k: v for k, v in merged[short].items() if v is not None}
    return merged


THRESHOLDS = load_thresholds()


def crop_thresholds(crop: str) -> dict[str, Any]:
    """Get merged threshold config for a crop (falls back to peach)."""
    return THRESHOLDS.get(crop, THRESHOLDS["peach"])