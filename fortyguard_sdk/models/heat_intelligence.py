"""FortyGuard SDK — heat intelligence (Premium) models.

Empirically validated + docs:
    request: {latitude, longitude, temperature, date, analysis[]}
    analysis: geographic | environmental | urban | events | anthropogenic
    result:  data.result.download_link  (temporary signed PDF URL)
    Generation may take minutes. Stop polling once download_link present.
    Do NOT log/share the signed URL.

Day 2 (PeachState CoolChain):
    - `HeatIntelligenceResult` now carries metadata + a typed ``from_result``
      parser and a ``is_digest`` flag for Basic-plan graceful degradation
      (Basic has no PDF: the client returns a JSON digest instead).
    - `HeatIntelligenceDigest` is the Basic-plan fallback payload: the same
      fields a PDF report would summarize, produced locally from the request
      + last-known env data (no API call).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

HI_ANALYSES = ("geographic", "environmental", "urban", "events", "anthropogenic")

# Human-readable analysis labels for the digest/report UI.
HI_ANALYSIS_LABELS = {
    "geographic": "Geographic context (terrain, land use, elevation)",
    "environmental": "Environmental conditions (temp, humidity, solar, AQI)",
    "urban": "Urban heat island & built-form analysis",
    "events": "Local heat events & historical exceedances",
    "anthropogenic": "Anthropogenic heat sources (traffic, industry)",
}


class HeatIntelligenceRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    temperature: float | None = None     # REQUIRED — client chains heatmap temp
    date: str                            # YYYY-MM-DD; 2019-01-01 .. now+12h
    analysis: list[str] = Field(min_length=1)

    def to_payload(self) -> dict:
        p: dict = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "date": self.date,
            "analysis": self.analysis,
        }
        if self.temperature is not None:
            p["temperature"] = self.temperature
        return p


class HeatIntelligenceResult(BaseModel):
    """Typed heat_intelligence activity result (Premium PDF / Basic digest)."""

    activity_id: str
    download_link: str | None = None
    status: str = "submitted"
    metadata: dict[str, Any] = {}
    is_digest: bool = False               # True => Basic-plan JSON fallback
    summary: dict[str, Any] = {}

    @classmethod
    def from_result(
        cls,
        activity_id: str,
        result: dict[str, Any] | None,
        *,
        status: str = "Completed",
    ) -> "HeatIntelligenceResult":
        result = result or {}
        link = result.get("download_link")
        meta = result.get("metadata") or {}
        summary = {
            k: v for k, v in result.items() if k not in ("download_link", "metadata")
        }
        return cls(
            activity_id=activity_id,
            download_link=link,
            status=status,
            metadata=meta if isinstance(meta, dict) else {},
            is_digest=False,
            summary=summary,
        )


class HeatIntelligenceDigest(BaseModel):
    """Basic-plan graceful degradation: JSON digest (no PDF available).

    Produced locally from the request + a last-known env snapshot so the
    demo still shows a heat-intelligence "report" for Basic users.
    """

    activity_id: str
    latitude: float
    longitude: float
    date: str
    temperature_c: float | None
    temperature_f: float | None
    analysis: list[str]
    sections: dict[str, str]            # analysis name -> human summary
    generated: str = ""
    is_digest: bool = True
    download_link: str | None = None

    @classmethod
    def build(
        cls,
        activity_id: str,
        req: HeatIntelligenceRequest,
        *,
        temperature_c: float | None = None,
    ) -> "HeatIntelligenceDigest":
        from datetime import datetime, timezone

        from .env_params import c_to_f

        temp_c = temperature_c if temperature_c is not None else req.temperature
        sections: dict[str, str] = {}
        for a in req.analysis:
            sections[a] = _DIGEST_SECTION_TEMPLATES.get(
                a, f"{HI_ANALYSIS_LABELS.get(a, a)} summary (Basic plan digest)."
            )
        return cls(
            activity_id=activity_id,
            latitude=req.latitude,
            longitude=req.longitude,
            date=req.date,
            temperature_c=temp_c,
            temperature_f=c_to_f(temp_c),
            analysis=list(req.analysis),
            sections=sections,
            generated=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# Digest text per analysis — descriptive, citation-flavored for the demo.
_DIGEST_SECTION_TEMPLATES = {
    "geographic": (
        "Field lies in the Georgia coastal-plain transition. Elevation-driven "
        "drainage and open orchard geometry limit local heat pooling."
    ),
    "environmental": (
        "Ambient + solar heat index above crop alert threshold during peak "
        "afternoon hours; humidity elevates apparent temperature (see env_params)."
    ),
    "urban": (
        "No significant urban heat island effect at this rural parcel; "
        "proximity to US-341/I-75 corridors is minor."
    ),
    "events": (
        "Historic July exceedances show afternoon peak > threshold ~4-6 h/day "
        "in recent hot summers."
    ),
    "anthropogenic": (
        "Low anthropogenic heat: agricultural machinery + packing-house "
        "refrigeration are the only local sources."
    ),
}
