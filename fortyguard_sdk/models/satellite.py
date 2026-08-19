"""FortyGuard SDK — satellite (Premium) request/response models.

Docs: satellite view segmentation analysis using lat/lon + date_time +
granularity (60, 80, 100). Response: coordinates, original images, segmentation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import DateTimeWindow


class SatelliteRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    date_time: DateTimeWindow
    granularity: int = Field(100, ge=60, le=100)

    def to_payload(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "date_time": self.date_time.to_payload(),
            "granularity": self.granularity,
        }


class SatelliteResult(BaseModel):
    coordinates: dict[str, Any] = {}
    original_images: list[Any] = []
    segmentation: dict[str, Any] = {}