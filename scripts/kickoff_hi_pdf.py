"""Day 2, subtask 2.8 — kick off Fort Valley heat-intelligence PDF generation.

Submits the Premium `heat_intelligence` request and long-polls (up to 25 min)
until the signed PDF URL is ready, then downloads it to
`data/fixtures/heat_intelligence_fort_valley.pdf`.

Run:  FG_API_KEY=... python scripts/kickoff_hi_pdf.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fortyguard_sdk.client import FortyGuardClient
from fortyguard_sdk.models.heat_intelligence import HeatIntelligenceRequest
from fortyguard_sdk.plans import Plan

OUT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "heat_intelligence_fort_valley.pdf"


async def main() -> None:
    key = os.environ.get("FG_API_KEY") or "REDACTED_API_KEY"
    client = FortyGuardClient(key, plan=Plan.PREMIUM)
    try:
        req = HeatIntelligenceRequest(
            latitude=32.5517,
            longitude=-83.8871,
            temperature=32.8,
            date="2025-07-15",
            analysis=["environmental"],
        )
        print(f"[hi] submitting {req.latitude},{req.longitude} ...", flush=True)
        res = await client.heat_intelligence(
            req, download_to=OUT, poll_timeout=1500.0
        )
        print(f"[hi] is_digest={res.is_digest} status={res.status}", flush=True)
        print(f"[hi] activity_id={res.activity_id}", flush=True)
        print(f"[hi] download_link_present={bool(res.download_link)}", flush=True)
        print(f"[hi] summary={res.summary}", flush=True)
        if OUT.exists():
            print(f"[hi] PDF saved: {OUT} ({OUT.stat().st_size} bytes)", flush=True)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())