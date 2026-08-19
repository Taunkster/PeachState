"""PeachState CoolChain services — orchestrator.

Owns the shared FortyGuardClient + limiter and runs Pipelines A-D
concurrently:

    Pipeline A: field monitoring   (15-min cadence during season)
    Pipeline B: harvest timing     (5-min cadence pre-harvest)
    Pipeline C: corridor routing   (on-demand + periodic)
    Pipeline D: heat intelligence  (daily 06:00 + on-demand)
"""

from __future__ import annotations

import asyncio
from typing import Any

from fortyguard_sdk import FortyGuardClient, TTLCache

from .pipeline_a import MonitorConfig, PipelineA
from .pipeline_b import HarvestConfig, PipelineB
from .pipeline_c import PipelineCService
from .pipeline_d import PipelineD


class PipelineRunner:
    def __init__(self, client: FortyGuardClient, cache: TTLCache) -> None:
        self.client = client
        self.cache = cache
        self._tasks: list[asyncio.Task] = []

    def start_pipeline_a(self, clusters, config: MonitorConfig | None = None) -> asyncio.Task:
        pa = PipelineA(self.client, self.cache, config)
        t = asyncio.create_task(pa.run_forever(clusters))
        self._tasks.append(t)
        return t

    def start_pipeline_b(self, fields, config: HarvestConfig | None = None) -> asyncio.Task:
        pb = PipelineB(self.client, self.cache, config)
        t = asyncio.create_task(pb.run_forever(fields))
        self._tasks.append(t)
        return t

    async def run_corridor_comparison(self, dt) -> Any:
        pc = PipelineCService(self.client, self.cache)
        return await pc.compare_routes(dt)

    async def run_reports(self, date: str) -> list[Any]:
        pd = PipelineD(self.client, self.cache)
        return await pd.generate_daily(date)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)