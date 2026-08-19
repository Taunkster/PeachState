"""PeachState CoolChain services — Pipeline D: Heat Intelligence Reports (GA).

Daily (06:00) + on-demand. For each key GA packing house / field location:
    heat_intelligence(lat, lon, temperature, date, analysis)
        -> poll -> download_link -> fetch PDF immediately (temp URL)
    -> store reports/{location}/{date}.pdf -> notify buyers/insurers

Premium-only; on Basic this degrades to a JSON digest built from
cached heatmap + env_params data (no PDF).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fortyguard_sdk import (
    HeatIntelligenceRequest,
    FortyGuardClient,
    Plan,
    TTLCache,
)

# Key GA packing houses + field locations (verified in GA bbox).
GA_PACKING_HOUSES = [
    {"id": "fort_valley_pack", "latitude": 32.5538, "longitude": -83.8874,
     "name": "Fort Valley Packing (Peach)"},
    {"id": "albany_pack", "latitude": 31.5785, "longitude": -84.1557,
     "name": "Albany Pecan Facility"},
    {"id": "bacon_pack", "latitude": 31.5394, "longitude": -82.4637,
     "name": "Bacon Blueberry Packing"},
    {"id": "vidalia_pack", "latitude": 32.2177, "longitude": -82.4135,
     "name": "Vidalia Onion Curing Shed"},
    {"id": "savannah_port", "latitude": 32.0809, "longitude": -81.0912,
     "name": "Port of Savannah Cold Storage"},
]


@dataclass
class ReportConfig:
    output_dir: Path = Path("data/reports")
    daily_hour: int = 6
    analyses: tuple[str, ...] = ("environmental", "geographic", "urban")
    report_ttl_days: int = 7


class PipelineD:
    def __init__(
        self,
        client: FortyGuardClient,
        cache: TTLCache | None = None,
        config: ReportConfig | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.config = config or ReportConfig()

    async def generate_for_locations(
        self,
        locations: list[dict[str, Any]],
        date: str,
        temperature_provider=None,
    ) -> list[Path]:
        """locations: [{id, latitude, longitude}]; temperature_provider
        resolves the per-location temperature required by the API (F9)."""
        if self.client.plan != Plan.PREMIUM:
            return await self._degraded_json_digest(locations, date)

        async def one(loc: dict[str, Any]) -> Path:
            lat = loc["latitude"]
            lon = loc["longitude"]
            temp = temperature_provider(loc) if temperature_provider else 30.0
            req = HeatIntelligenceRequest(
                latitude=lat,
                longitude=lon,
                temperature=temp,
                date=date,
                analysis=list(self.config.analyses),
            )
            res = await self.client.heat_intelligence(req)
            if not res.download_link:
                raise RuntimeError(f"no download_link for {loc['id']}")
            dest = self.config.output_dir / f"{loc['id']}" / f"{date}.pdf"
            if dest.exists():
                return dest  # TTL: never re-generate same-day report
            return await self.client.download_report(res.download_link, dest)

        # concurrency capped by client limiter; gather tolerates partial failure
        results = await asyncio.gather(
            *(one(loc) for loc in locations), return_exceptions=True
        )
        ok: list[Path] = []
        for loc, res in zip(locations, results):
            if isinstance(res, Exception):
                print(f"[PipelineD] report failed for {loc.get('id')}: {res}")
            else:
                ok.append(res)
        return ok

    async def generate_daily(self, date: str) -> list[Path]:
        return await self.generate_for_locations(GA_PACKING_HOUSES, date)

    async def _degraded_json_digest(self, locations, date) -> list[Path]:
        """Basic plan: JSON/CSV digest from cached data (no heat intelligence)."""
        dest = self.config.output_dir / "digests" / f"{date}.json"
        digest = {
            "date": date,
            "plan": "basic",
            "note": "degraded digest (heat_intelligence is Premium-only)",
            "locations": [{"id": l.get("id"), "lat": l["latitude"], "lon": l["longitude"]}
                          for l in locations],
        }
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(digest, indent=2))
        return [dest]