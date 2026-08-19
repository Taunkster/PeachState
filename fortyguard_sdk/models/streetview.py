"""FortyGuard SDK — streetview (Premium) request/response models.

Docs: street view imagery segmentation (urban features, facades,
vegetation, roads, thermal). Response: coordinates + per-category maps.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import DateTimeWindow


class StreetViewRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    date_time: DateTimeWindow

    def to_payload(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "date_time": self.date_time.to_payload(),
        }


class StreetViewResult(BaseModel):
    coordinates: dict[str, Any] = {}
    front: dict[str, Any] = {}