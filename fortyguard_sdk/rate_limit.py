"""FortyGuard SDK — sliding-window rate limiter + concurrency cap.

Empirically validated (probe 6, 2026-08-18):
    - server headers: x-ratelimit-limit: 100, x-ratelimit-remaining,
      x-ratelimit-reset (unix seconds)
    - burst of 8 concurrent POSTs succeeded

Design: keep max_concurrent = 5 in-flight (both POSTs and status polls
share the slot), and a sliding window well under the documented 100
per window. On 429 honor the server's reset epoch instead of blind
sleeping.
"""

from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    def __init__(
        self,
        max_concurrent: int = 5,
        max_per_window: int = 90,
        window_seconds: float = 60.0,
    ) -> None:
        self._sem = asyncio.Semaphore(max_concurrent)
        self._window_s = window_seconds
        self._max_window = max_per_window
        self._slots: list[float] = []
        self._lock = asyncio.Lock()

    @property
    def max_concurrent(self) -> int:
        return self._sem._value if hasattr(self._sem, "_value") else 5

    async def acquire(self) -> None:
        """Wait for a concurrency slot AND a window slot (graceful queue)."""
        await self._sem.acquire()
        try:
            async with self._lock:
                now = time.monotonic()
                self._slots = [t for t in self._slots if now - t < self._window_s]
                if len(self._slots) >= self._max_window:
                    # Sleep until the oldest slot expires — avoids a 429.
                    wait = self._slots[0] + self._window_s - now
                    if wait > 0:
                        await asyncio.sleep(wait)
                self._slots.append(time.monotonic())
        except BaseException:
            self.release()
            raise

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.release()

    def release(self) -> None:
        self._sem.release()

    async def wait_until_reset(self, reset_epoch: int) -> None:
        """Called on 429 when x-ratelimit-reset is present (unix seconds).

        Never sleeps more than 60s in one shot; caller re-loops if needed.
        """
        delay = max(0.0, reset_epoch - time.time())
        if delay > 0:
            await asyncio.sleep(min(delay, 60.0))