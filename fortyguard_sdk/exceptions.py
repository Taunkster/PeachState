"""FortyGuard SDK — typed exception hierarchy.

All SDK errors derive from FortyGuardError so callers can catch one
base type. Sub-classes map 1:1 to the API's documented failure modes
plus Georgia-specific geographic guards.
"""

from __future__ import annotations


class FortyGuardError(Exception):
    """Base class for all FortyGuard SDK errors."""


class AuthError(FortyGuardError):
    """HTTP 401/403 — authentication or authorization failure.

    Base for InvalidApiKeyError (401) and FeatureNotAvailableError (403)
    so callers can catch one type for all credential/plan issues.
    """


class InvalidApiKeyError(AuthError):
    """HTTP 401 — missing or invalid api-key header."""


class FeatureNotAvailableError(AuthError):
    """HTTP 403 — endpoint gated by current plan (Basic vs Premium)."""


class ServerError(FortyGuardError):
    """HTTP 5xx — upstream server failure.

    Attributes:
        status_code: the HTTP status observed (500/502/503/504).
        retry_after_s: seconds to wait before retrying when the server
            provides Retry-After; otherwise None.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_s = retry_after_s


class ValidationError(FortyGuardError):
    """HTTP 400/422 — request failed server-side validation.

    Attributes:
        field: offending request field when the API reports one.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class RateLimitError(FortyGuardError):
    """HTTP 429 — rate limit exceeded; requeue after reset."""


class TaskFailedError(FortyGuardError):
    """Activity reached terminal 'Failed' status.

    Attributes:
        activity_id: failed activity for diagnostics/re-submission.
        details: raw failure payload when available.
    """

    def __init__(self, activity_id: str, details: dict | None = None) -> None:
        super().__init__(f"activity {activity_id} failed: {details}")
        self.activity_id = activity_id
        self.details = details or {}


class TaskTimeoutError(FortyGuardError):
    """Polling exceeded max_duration for an activity.

    Attributes:
        activity_id: activity still Processing when we gave up.
        timeout_s: configured per-task timeout in seconds.
    """

    def __init__(self, activity_id: str, timeout_s: float) -> None:
        super().__init__(
            f"activity {activity_id} did not complete within {timeout_s:.0f}s"
        )
        self.activity_id = activity_id
        self.timeout_s = timeout_s


class GeorgiaBoundaryError(FortyGuardError):
    """Coordinates outside the confirmed Georgia/US coverage area.

    The FortyGuard Temperature API is US-only (Georgia confirmed);
    this guard fails fast before wasting an API call.
    """

    def __init__(self, lat: float, lon: float) -> None:
        super().__init__(
            f"coordinates ({lat:.4f}, {lon:.4f}) outside Georgia/US coverage "
            "— FortyGuard API is US-only"
        )
        self.lat = lat
        self.lon = lon


class DownloadError(FortyGuardError):
    """Failed to fetch a temporary download_link (e.g. heat intelligence PDF)."""