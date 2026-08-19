"""FortyGuard SDK — TTL cache with async get-or-fetch.

Georgia TTLs (single source of truth — mirrored in design doc §4.1):
    heatmap          15 min   (temperature changes slowly; F8 data lag)
    env params       30 min
    risk scores      15 min
    harvest cooldown 48 h     (min interval between "Harvest Now" alerts)
    GDD accumulation 24 h
    corridor segments 15 min
    coverage registry 24 h
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    """Simple async TTL cache (in-memory).

    get_or_fetch de-duplicates concurrent fetches of the same key so two
    pipelines asking for the same corridor segment only hit the API once.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.monotonic() > expires_at:
            await self._delete(key)
            return None
        return value

    async def set(self, key: str, value: Any, ttl_s: float) -> None:
        async with self._lock:
            self._store[key] = (time.monotonic() + ttl_s, value)

    async def _delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def get_or_fetch(
        self, key: str, ttl_s: float, fetcher: Callable[[], Awaitable[T]]
    ) -> T:
        """Return cached value or fetch+store it. Single-flight per key."""
        hit = await self.get(key)
        if hit is not None:
            return hit

        # single-flight: reuse an in-progress fetch for the same key
        async with self._lock:
            fut = self._inflight.get(key)
            if fut is not None and not fut.done():
                return await asyncio.shield(fut)
            fut = asyncio.get_running_loop().create_future()
            self._inflight[key] = fut

        try:
            value = await fetcher()
            await self.set(key, value, ttl_s)
            fut.set_result(value)
            return value
        except BaseException as exc:
            fut.set_exception(exc)
            raise
        finally:
            async with self._lock:
                self._inflight.pop(key, None)


# TTL constants (single source of truth — mirrored in design doc §4.1)
HEATMAP_TTL_S = 15 * 60
ENV_PARAMS_TTL_S = 30 * 60
RISK_TTL_S = 15 * 60
HARVEST_COOLDOWN_S = 48 * 3600
GDD_TTL_S = 24 * 3600
CORRIDOR_TTL_S = 15 * 60
COVERAGE_TTL_S = 24 * 3600