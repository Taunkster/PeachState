"""FortyGuard SDK (PeachState CoolChain — Georgia edition).

Thin async client wrapping the five POST endpoints + status polling,
rate limiting, retries, plan gating, GA-geography guards, and
response parsing behind type-safe method signatures.

Async workflow (empirically validated 2026-08-18):
    POST /{endpoint} -> activity_id
    GET /status/{activity_id} -> Processing/Completed/Failed

Usage:
    client = FortyGuardClient(api_key=os.environ["FG_API_KEY"],
                              plan=Plan.BASIC, concurrency=5)
    res = await client.heatmap(HeatmapRequest(polygon_aoi=fc, date_time=...))
    await client.close()
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from .cache import TTLCache
from .exceptions import (
    AuthError,
    DownloadError,
    FortyGuardError,
    InvalidApiKeyError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .georgia import assert_in_georgia
from .models.common import PolygonAOI
from .models.env_params import EnvParamsRequest, EnvParamsResult
from .models.heat_intelligence import (
    HeatIntelligenceRequest,
    HeatIntelligenceResult,
)
from .models.heatmap import HeatmapRequest, HeatmapResult
from .models.satellite import SatelliteRequest, SatelliteResult
from .models.streetview import StreetViewRequest, StreetViewResult
from .plans import Plan, require, validate_heatmap_area
from .polling import TaskPoller
from .rate_limit import AsyncRateLimiter

ENDPOINTS = {
    "heatmap": "/heatmap",
    "env_params": "/env_params",
    "heat_intelligence": "/heat_intelligence",
    "satellite": "/satellite",
    "streetview": "/streetview",
}


class FortyGuardClient:
    """Thin async client for the FortyGuard Temperature API (GA edition).

    All five endpoint methods follow the same pipeline:
      1. plan-gate + GA-area validation
      2. rate-limiter acquire (shared concurrency cap = 5)
      3. POST -> activity_id
      4. poll GET /status/{activity_id} (2s -> backoff -> 10s, cap 10 min)
      5. parse + type-check result; cache when cacheable
    """

    def __init__(
        self,
        api_key: str,
        plan: Plan = Plan.BASIC,
        base_url: str = "https://api.fortyguard.com/v1",
        *,
        concurrency: int = 5,
        max_per_window: int = 90,
        poll_min_interval: float = 2.0,
        poll_max_interval: float = 10.0,
        poll_max_duration: float = 600.0,   # 10 min per task
        cache: TTLCache | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")

        self.plan = plan
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = http_client or httpx.AsyncClient(
            headers={"api-key": api_key, "Content-Type": "application/json"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self._limiter = AsyncRateLimiter(
            max_concurrent=concurrency, max_per_window=max_per_window
        )
        self._poller = TaskPoller(
            self._get_status,
            min_interval=poll_min_interval,
            max_interval=poll_max_interval,
            max_duration=poll_max_duration,
        )
        self._cache = cache or TTLCache()
        # Last-known heatmap tile mean temp (°C) — used to chain the REQUIRED
        # `temperature` field of env_params / heat_intelligence requests when
        # the caller did not provide one (F9; heatmap tile temp or last-known).
        self._last_heatmap_temp_c: float | None = None
        # Optional external temperature source: async callable (lat, lon) -> °C|None.
        self._temperature_provider = None

    # ------------------------------------------------------------------
    # Public endpoint methods
    # ------------------------------------------------------------------
    async def heatmap(self, req: HeatmapRequest) -> HeatmapResult:
        require("heatmap", self.plan)
        validate_heatmap_area(_fc_area(req.polygon_aoi), self.plan)
        assert_in_georgia(*_fc_bounds(req.polygon_aoi))
        result = await self._submit_and_wait("heatmap", req.to_payload())
        res = HeatmapResult.from_result(result)
        # Remember the mean tile temp (°C) so downstream env_params /
        # heat_intelligence calls can chain the REQUIRED `temperature` field.
        ts = res.stats_data.temperature_stats
        if ts is not None and ts.mean is not None:
            self._last_heatmap_temp_c = float(ts.mean)
        return res

    @property
    def last_heatmap_temp_c(self) -> float | None:
        """Most recent heatmap mean tile temp (°C) — temp-chaining source."""
        return self._last_heatmap_temp_c

    def set_temperature_provider(
        self, provider: Any | None
    ) -> None:
        """Register an async ``provider(lat, lon) -> temp_c | None`` used to
        chain the REQUIRED temperature field when requests omit it."""
        self._temperature_provider = provider

    async def _resolve_temperature(
        self,
        req_temp_c: float | None,
        lat: float,
        lon: float,
        default_c: float = 30.0,
    ) -> float:
        """Chain a temperature for requests that require one (F9).

        Resolution order:
            1. explicit value (request.temperature / method arg)
            2. registered temperature provider (heatmap tile temp lookup)
            3. last-known heatmap mean temp on this client
            4. ``default_c`` (30 °C — a warm GA summer afternoon)
        """
        if req_temp_c is not None:
            return float(req_temp_c)
        if self._temperature_provider is not None:
            try:
                got = await self._temperature_provider(lat, lon)
            except Exception:
                got = None
            if got is not None:
                return float(got)
        if self._last_heatmap_temp_c is not None:
            return self._last_heatmap_temp_c
        return default_c

    async def env_params(
        self,
        req: EnvParamsRequest,
        temperature_c: float | None = None,
    ) -> EnvParamsResult:
        require("env_params", self.plan)
        assert_in_georgia(req.latitude, req.longitude)
        if req.temperature is None:
            req.temperature = await self._resolve_temperature(
                temperature_c, req.latitude, req.longitude
            )
        result = await self._submit_and_wait("env_params", req.to_payload())
        return EnvParamsResult.from_result(result)

    async def heat_intelligence(
        self,
        req: HeatIntelligenceRequest,
        *,
        download_to: Path | None = None,
        poll_timeout: float = 1500.0,   # >= 15 min budget (generation takes minutes)
        temperature_c: float | None = None,
    ) -> HeatIntelligenceResult:
        """Submit a heat-intelligence report (Premium PDF).

        Behavior:
            - **Basic plan**: graceful degradation — no API call; returns a
              local JSON :class:`HeatIntelligenceDigest` (``is_digest=True``).
            - **Premium plan**: POST + long poll (default 25 min budget), then
              parse ``download_link``. If ``download_to`` is given the PDF is
              fetched immediately.
            - Temporary signed URLs are never logged.
        """
        if self.plan == Plan.BASIC:
            from .models.heat_intelligence import HeatIntelligenceDigest

            digest = HeatIntelligenceDigest.build(
                f"digest-{req.latitude:.3f}-{req.longitude:.3f}",
                req,
                temperature_c=(
                    temperature_c if temperature_c is not None else req.temperature
                ),
            )
            return digest

        require("heat_intelligence", self.plan)
        assert_in_georgia(req.latitude, req.longitude)
        if req.temperature is None:
            req.temperature = await self._resolve_temperature(
                temperature_c, req.latitude, req.longitude
            )
        payload = req.to_payload()
        activity_id = await self._submit("heat_intelligence", payload)
        # Long poll: HI generation can take minutes.
        res = await self.poll_status(activity_id, timeout=poll_timeout)
        out = HeatIntelligenceResult.from_result(
            activity_id, res.result, status=res.status
        )
        if out.download_link and download_to is not None:
            await self.download_report(out.download_link, download_to)
        return out

    async def satellite(self, req: SatelliteRequest) -> SatelliteResult:
        require("satellite", self.plan)
        assert_in_georgia(req.latitude, req.longitude)
        result = await self._submit_and_wait("satellite", req.to_payload())
        return SatelliteResult(
            coordinates=result.get("coordinates", {}),
            original_images=result.get("orignal_image", []),  # sic: API typo
            segmentation=result.get("segmentation", {}),
        )

    async def streetview(self, req: StreetViewRequest) -> StreetViewResult:
        require("streetview", self.plan)
        assert_in_georgia(req.latitude, req.longitude)
        result = await self._submit_and_wait("streetview", req.to_payload())
        return StreetViewResult(
            coordinates=result.get("coordinates", {}), front=result.get("front", {})
        )

    # ------------------------------------------------------------------
    # Supporting
    # ------------------------------------------------------------------
    async def poll_status(
        self,
        activity_id: str,
        timeout: float = 600.0,
        interval: float = 2.0,
        backoff: float = 1.5,
        max_interval: float = 10.0,
    ) -> "ActivityResult":
        """Poll an activity until completion (adaptive exponential backoff).

        Args:
            activity_id: POST response activity id.
            timeout: hard per-task budget in seconds (default 600 = 10 min).
            interval: initial poll interval in seconds (default 2).
            backoff: multiplicative backoff between polls (default 1.5).
            max_interval: cap on poll interval (default 10).

        Returns:
            ActivityResult with status/result on completion.

        Raises:
            TaskFailedError: activity reached a terminal failed state.
            TaskTimeoutError: activity still processing after `timeout`.
        """
        from .polling import TaskPoller

        poller = TaskPoller(
            self._get_status,
            min_interval=interval,
            max_interval=max_interval,
            max_duration=timeout,
            backoff_factor=backoff,
        )
        return await poller.wait_for(activity_id)

    async def submit_and_wait(
        self,
        endpoint: str,
        payload: dict[str, Any],
        **poll_kwargs: Any,
    ) -> dict[str, Any]:
        """Submit an endpoint payload, then poll to completion.

        Combines :meth:`_submit` + :meth:`poll_status`; any ``**poll_kwargs``
        (timeout/interval/backoff/max_interval) are forwarded to the poller.

        Returns:
            The completed activity's ``result`` dict (may be {} for some
            endpoints whose payload lives on ``download_link``).
        """
        activity_id = await self._submit(endpoint, payload)
        res = await self.poll_status(activity_id, **poll_kwargs)
        return res.result or {}

    async def download_report(self, download_link: str, dest: Path) -> Path:
        """Fetch a temporary signed URL (heat intelligence PDF)."""
        try:
            async with self._limiter:
                r = await self._client.get(download_link)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise DownloadError(f"download failed: {exc}") from exc
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return dest

    async def health_check(self) -> bool:
        """Probe the API with the smallest GA request (env_params, Fort Valley)."""
        try:
            await self.env_params(
                EnvParamsRequest(
                    latitude=32.5538,          # Fort Valley, Peach County
                    longitude=-83.8874,
                    temperature=30.0,          # F9: temperature required
                    date_time=_now_window(),
                    analysis=["elevation"],
                )
            )
            return True
        except FortyGuardError:
            return False

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _submit(self, endpoint: str, payload: dict[str, Any]) -> str:
        require(endpoint, self.plan)
        await self._limiter.acquire()
        try:
            r = await self._client.post(
                f"{self.base_url}{ENDPOINTS[endpoint]}", json=payload
            )
        except httpx.HTTPError as exc:
            raise FortyGuardError(f"{endpoint} transport error: {exc}") from exc
        finally:
            self._limiter.release()

        body = r.json()
        if r.status_code == 401:
            raise InvalidApiKeyError(body.get("details", {}).get("message", "401"))
        if r.status_code == 403:
            from .exceptions import FeatureNotAvailableError

            raise FeatureNotAvailableError(
                body.get("details", {}).get("message", "403")
            )
        if r.status_code == 429:
            reset = int(r.headers.get("x-ratelimit-reset", "0") or 0)
            await self._limiter.wait_until_reset(reset)
            raise RateLimitError("rate limited; requeue")
        if r.status_code == 422:
            raise ValidationError(
                body.get("details", {}).get("message", "422"),
                field=body.get("field"),
            )
        if 500 <= r.status_code < 600:
            retry_after = _retry_after(r)
            raise ServerError(
                f"{endpoint} HTTP {r.status_code}: {body.get('message', r.text[:200])}",
                status_code=r.status_code,
                retry_after_s=retry_after,
            )
        if r.status_code != 200:
            raise FortyGuardError(
                f"{endpoint} HTTP {r.status_code}: {body.get('message', r.text)}"
            )

        data = body.get("data") or {}
        activity_id = data.get("activity_id")
        if not activity_id:
            raise FortyGuardError(f"{endpoint} response missing activity_id")
        return activity_id

    async def _get_status(self, activity_id: str) -> dict[str, Any]:
        await self._limiter.acquire()
        try:
            r = await self._client.get(f"{self.base_url}/status/{activity_id}")
        except httpx.HTTPError as exc:
            raise FortyGuardError(f"status transport error: {exc}") from exc
        finally:
            self._limiter.release()
        body = r.json()
        if r.status_code == 401:
            raise InvalidApiKeyError("invalid api key during status poll")
        if r.status_code == 404:
            raise FortyGuardError(f"activity {activity_id} not found")
        if 500 <= r.status_code < 600:
            raise ServerError(
                f"status HTTP {r.status_code}: {body.get('message', r.text[:200])}",
                status_code=r.status_code,
                retry_after_s=_retry_after(r),
            )
        if r.status_code != 200:
            raise FortyGuardError(
                f"status HTTP {r.status_code}: {body.get('message', r.text)}"
            )
        return body

    async def _submit_and_wait(
        self, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        activity_id = await self._submit(endpoint, payload)
        res = await self._poller.wait_for(activity_id)
        return res.result or {}


def _fc_area(fc: Any) -> float:
    from .models.heatmap import estimate_aoe_area_sqmi, estimate_area_mi2

    if isinstance(fc, PolygonAOI):
        return estimate_area_mi2(fc)
    return estimate_aoe_area_sqmi(fc)


def _fc_bounds(fc: Any) -> tuple[float, float]:
    """Return (approx lat, lon) center of a FeatureCollection for GA guard."""
    if isinstance(fc, PolygonAOI):
        return fc.centroid
    coords: list[tuple[float, float]] = []
    for feat in fc.get("features", []):
        geom = feat.get("geometry", {})
        _walk(geom, coords)
    if not coords:
        return (33.0, -83.5)  # GA fallback center
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _walk(geom: dict[str, Any], out: list[tuple[float, float]]) -> None:
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "Point":
        out.append((c[0], c[1]))
    elif t == "Polygon":
        for ring in c:
            for pt in ring:
                out.append((pt[0], pt[1]))
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                for pt in ring:
                    out.append((pt[0], pt[1]))
    elif t == "GeometryCollection":
        for g in c:
            _walk(g, out)


def _retry_after(r: httpx.Response) -> float | None:
    """Parse Retry-After header (seconds or HTTP-date) into seconds."""
    raw = r.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _now_window():
    from datetime import date, timedelta

    from .models.common import DateTimeWindow, FilterType

    return DateTimeWindow(
        start_date=date.today() - timedelta(days=1),   # F8: avoid data-lag 0 cells
        start_time="14:00",
        filter_type=FilterType.SINGLE_HOUR,
    )


__all__ = [
    "FortyGuardClient",
    "Plan",
    "HeatmapRequest",
    "HeatmapResult",
    "EnvParamsRequest",
    "EnvParamsResult",
    "HeatIntelligenceRequest",
    "HeatIntelligenceResult",
    "SatelliteRequest",
    "StreetViewRequest",
    "TTLCache",
]