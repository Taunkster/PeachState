"""FortyGuard SDK — adaptive-interval status poller.

Implements the async workflow:

    POST /{endpoint}  ->  activity_id
    GET /status/{id}  ->  Processing ... (poll) ... Completed/Failed

Poll strategy (per task):
    - start 2s, exponential x2, cap 10s
    - soft budget 5 min for normal tasks; hard timeout 10 min
      (heat_intelligence: 15 min)
    - cancellation-safe: the rate-limiter slot is always released
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .exceptions import TaskFailedError, TaskTimeoutError

# Terminal / intermediate status strings observed in live probing.
_COMPLETED = frozenset({"completed", "succeeded"})
_FAILED = frozenset({"failed", "error"})


@dataclass
class ActivityResult:
    activity_id: str
    status: str
    result: dict[str, Any] | None = None
    elapsed_s: float = 0.0


class TaskPoller:
    def __init__(
        self,
        get_status: Callable[[str], Awaitable[dict[str, Any]]],
        *,
        min_interval: float = 2.0,
        max_interval: float = 10.0,
        max_duration: float = 600.0,   # 10 min hard cap per task
        soft_budget: float = 300.0,    # 5 min soft budget for normal tasks
        backoff_factor: float = 2.0,
    ) -> None:
        self._get_status = get_status
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.max_duration = max_duration
        self.soft_budget = soft_budget
        self.backoff_factor = backoff_factor

    def _next_delay(self, attempt: int) -> float:
        d = self.min_interval * (self.backoff_factor**attempt)
        return min(d, self.max_interval)

    async def wait_for(self, activity_id: str) -> ActivityResult:
        """Poll until Completed/Failed, max_duration, or cancellation."""
        attempt = 0
        t0 = time.monotonic()
        while True:
            elapsed = time.monotonic() - t0
            if elapsed > self.max_duration:
                raise TaskTimeoutError(activity_id, self.max_duration)
            try:
                body = await self._get_status(activity_id)
            except asyncio.CancelledError:
                raise  # caller decides: retry later or abandon
            data = body.get("data") or {}
            status = str(data.get("status", "")).lower()

            if status in _COMPLETED:
                return ActivityResult(
                    activity_id=activity_id,
                    status="Completed",
                    result=data.get("result"),
                    elapsed_s=time.monotonic() - t0,
                )
            if status in _FAILED:
                raise TaskFailedError(activity_id, details=data)

            attempt += 1
            await asyncio.sleep(self._next_delay(attempt))


class PollGroup:
    """Runs up to `max_concurrent` pollers simultaneously (fan-out).

    Lets Pipeline A launch tcm + exceedance + persistence + env_params
    concurrently and await all with a single timeout.
    """

    def __init__(self, poller: TaskPoller, max_concurrent: int = 5) -> None:
        self._poller = poller
        self._sem = asyncio.Semaphore(max_concurrent)

    async def run(self, activity_ids: list[str]) -> list[ActivityResult]:
        async def one(aid: str) -> ActivityResult:
            async with self._sem:
                return await self._poller.wait_for(aid)

        return list(await asyncio.gather(*(one(a) for a in activity_ids)))