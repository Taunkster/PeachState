"""FortyGuard SDK — shared request models.

Encodes the date_time window contract (docs bundle, validated live):

    filter_type 1 (Single Hour)        : start_date + start_time
    filter_type 2 (Range of Hours)     : start_date + start_time + end_time
    filter_type 3 (Single Day)         : start_date only
    filter_type 4 (Range of Days)      : start_date + end_date (<= 1 month)

Valid date range: 2019-01-01 .. 12h past current time.
Granularity: 60 / 80 / 100 (meters).
"""

from __future__ import annotations

from datetime import date
from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class FilterType(IntEnum):
    SINGLE_HOUR = 1
    RANGE_OF_HOURS = 2
    SINGLE_DAY = 3
    RANGE_OF_DAYS = 4


GRANULARITIES = (60, 80, 100)


class DateTimeWindow(BaseModel):
    start_date: date
    start_time: str | None = None  # "HH:MM" 24h
    end_time: str | None = None
    end_date: date | None = None
    filter_type: FilterType = FilterType.SINGLE_HOUR

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "DateTimeWindow":
        ft = self.filter_type
        if ft == FilterType.SINGLE_HOUR and self.start_time is None:
            raise ValueError("filter_type=1 requires start_time")
        if ft == FilterType.RANGE_OF_HOURS and (
            self.start_time is None or self.end_time is None
        ):
            raise ValueError("filter_type=2 requires start_time and end_time")
        if ft == FilterType.RANGE_OF_DAYS and self.end_date is None:
            raise ValueError("filter_type=4 requires end_date")
        return self

    def to_payload(self) -> dict:
        p: dict = {
            "start_date": self.start_date.isoformat(),
            "filter_type": int(self.filter_type),
        }
        if self.start_time:
            p["start_time"] = self.start_time
        if self.end_time:
            p["end_time"] = self.end_time
        if self.end_date:
            p["end_date"] = self.end_date.isoformat()
        return p


class Envelope(BaseModel):
    """Bounding box helper used for area checks / corridor segmentation."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @property
    def width_deg(self) -> float:
        return self.max_lon - self.min_lon

    @property
    def height_deg(self) -> float:
        return self.max_lat - self.min_lat

    @property
    def area_sqmi(self) -> float:
        """Rough planar area in mi² (good enough for the 10/50 mi² guard)."""
        km_per_deg_lat = 111.0
        km_per_deg_lon = 111.0 * __import__(
            "math"
        ).cos((self.min_lat + self.max_lat) / 2 * 3.14159 / 180.0)
        sq_km = (self.width_deg * km_per_deg_lon) * (
            self.height_deg * km_per_deg_lat
        )
        return sq_km * 0.386102  # km² -> mi²


# DateTimeFilter is the public name for the date_time window contract
# (filter_type 1/2/3/4). Kept as an alias of DateTimeWindow so code can
# reference either name without duplication.
DateTimeFilter = DateTimeWindow


class PolygonAOI(BaseModel):
    """GeoJSON FeatureCollection whose features carry Polygon geometry.

    Mirrors the API's ``polygon_aoi`` request field. Every feature's
    geometry must be a Polygon (or MultiPolygon) so the AOI is a
    closed area — the client-side 10/50 mi² plan guard can then be
    applied before any request is sent.
    """

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[dict[str, Any]] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_geometries(self) -> "PolygonAOI":
        for f in self.features:
            geom = f.get("geometry") or {}
            if geom.get("type") not in ("Polygon", "MultiPolygon"):
                raise ValueError(
                    "PolygonAOI requires all geometries to be "
                    f"Polygon/MultiPolygon, got {geom.get('type')!r}"
                )
        return self

    @property
    def centroid(self) -> tuple[float, float]:
        """Approximate (lat, lon) center of all vertices (GA guard input)."""
        lats: list[float] = []
        lons: list[float] = []
        for f in self.features:
            _walk_coords(f.get("geometry", {}), lats, lons)
        if not lats:
            return (33.0, -83.5)
        return (sum(lats) / len(lats), sum(lons) / len(lons))

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _walk_coords(
    geom: dict[str, Any], lats: list[float], lons: list[float]
) -> None:
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "Polygon":
        for ring in c:
            for pt in ring:
                lons.append(pt[0])
                lats.append(pt[1])
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                for pt in ring:
                    lons.append(pt[0])
                    lats.append(pt[1])