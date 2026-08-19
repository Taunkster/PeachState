"""PeachState CoolChain — data-source fallback modes (Day 7).

Env contract (docs/06 §6.2 + Day-7 plan §7.2)::

    DATA_SOURCE=fixtures|live|hybrid     (default: fixtures)

        fixtures  — read local SQLite + JSON fixtures only. Zero network.
                    Demo / judging default (the app never touches the API).
        live      — require a FortyGuard API key; a failed call falls back
                    to the last cached payload and records the miss.
        hybrid    — try live with a hard **8 s timeout**, then auto-fallback
                    to fixtures on any error (no spinner, no error surface).

Runtime state lives in a module singleton (``FallbackState``) so the
``/health`` endpoint can report::

    {"status": "ok", "data_source": "hybrid",
     "last_live_ok": true, "cache_age_s": 42.0, ...}

Demo-mode guard (7.2): when running the Streamlit app for a timed demo the
process should be launched with ``STREAMLIT_SERVER_HEADLESS=true`` and
``STREAMLIT_BROWSER_GATHER_USAGE_STATS=false`` so no browser tab opens and no
telemetry leaves the venue network. ``ensure_demo_mode`` validates this and
returns actionable flags.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

# Data-source modes (must match dashboard.data_source constants).
MODE_FIXTURES = "fixtures"
MODE_LIVE = "live"
MODE_HYBRID = "hybrid"
MODES = (MODE_FIXTURES, MODE_LIVE, MODE_HYBRID)

DEFAULT_SOURCE = MODE_FIXTURES
ENV_VAR = "DATA_SOURCE"
KEY_ENV_VARS = ("FORTYGUARD_API_KEY", "FG_API_KEY", "COOLCHAIN_FORTYGUARD_API_KEY")

# Load .env once so DATA_SOURCE / FORTYGUARD_API_KEY in the repo's .env are
# honored by this env-file-agnostic module (Settings reads .env itself, but
# the dashboard/CLI read plain os.environ).
try:  # python-dotenv is a declared dependency; degrade gracefully if absent.
    from dotenv import load_dotenv

    load_dotenv()  # no-op when .env is missing
except Exception:  # pragma: no cover - optional dependency
    pass

# Hybrid live-attempt hard timeout (task 7.2).
LIVE_TIMEOUT_S = 8.0

# Demo-mode env flags (7.2).
DEMO_ENV_FLAGS = {
    "STREAMLIT_SERVER_HEADLESS": "true",
    "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
}


@dataclass
class FallbackState:
    """Module-level runtime state reported by ``GET /health``."""

    data_source: str = DEFAULT_SOURCE
    last_live_ok: bool | None = None       # None = never attempted
    last_live_at: float | None = None      # epoch seconds of last live attempt
    last_error: str | None = None
    cache_started_at: float = field(default_factory=time.time)
    live_probe_ms: float | None = None     # last successful probe latency

    def cache_age_s(self) -> float:
        return round(time.time() - self.cache_started_at, 1)

    def record_live_ok(self, elapsed_s: float) -> None:
        self.last_live_ok = True
        self.last_live_at = time.time()
        self.last_error = None
        self.live_probe_ms = round(elapsed_s * 1000.0, 1)

    def record_live_fail(self, err: Exception) -> None:
        self.last_live_ok = False
        self.last_live_at = time.time()
        self.last_error = f"{type(err).__name__}: {err}"


STATE = FallbackState()


def resolve_data_source(env: dict[str, str] | None = None) -> str:
    """Resolve the active ``DATA_SOURCE`` from the environment.

    Unknown values fall back to ``fixtures`` (fail-safe: never enable a
    network path by accident). Pass an explicit ``{}`` to test isolation.
    """
    env = os.environ if env is None else env
    raw = (env.get(ENV_VAR) or DEFAULT_SOURCE).strip().lower()
    source = raw if raw in MODES else DEFAULT_SOURCE
    if raw not in MODES:
        print(
            f"[fallback] DATA_SOURCE={raw!r} unknown — using {DEFAULT_SOURCE!r}"
        )
    STATE.data_source = source
    return source


def api_key_from_env(env: dict[str, str] | None = None) -> str:
    """First non-empty FortyGuard key found in the standard env vars."""
    env = os.environ if env is None else env
    for name in KEY_ENV_VARS:
        val = (env.get(name) or "").strip()
        if val:
            return val
    return ""


def is_live_capable(env: dict[str, str] | None = None) -> bool:
    """True when a live path is both configured and has a key."""
    env = os.environ if env is None else env
    return resolve_data_source(env) in (MODE_LIVE, MODE_HYBRID) and bool(
        api_key_from_env(env)
    )


# ---------------------------------------------------------------------------
# Live probe (async SDK wrapped with a hard 8 s timeout)
# ---------------------------------------------------------------------------
def probe_live(api_key: str, timeout_s: float = LIVE_TIMEOUT_S) -> bool:
    """Run the SDK's lightweight Fort Valley probe with a hard timeout.

    Returns True on success. On any failure/timeout records the miss on
    ``STATE`` and returns False. Fully synchronous (``asyncio.run``) so it is
    safe to call from Streamlit's script context or a FastAPI handler.
    """
    if not api_key:
        STATE.record_live_fail(ValueError("no FortyGuard API key configured"))
        return False

    async def _run() -> bool:
        from coolchain.config import Settings, make_client

        client = make_client(Settings(fortyguard_api_key=api_key))
        try:
            return await asyncio.wait_for(
                client.health_check(), timeout=timeout_s
            )
        finally:
            await client.close()

    t0 = time.time()
    try:
        ok = asyncio.run(_run())
    except (TimeoutError, asyncio.TimeoutError):
        STATE.record_live_fail(
            TimeoutError(f"FortyGuard probe exceeded {timeout_s:.0f}s timeout")
        )
        return False
    except Exception as exc:  # noqa: BLE001 — any SDK error => fallback
        STATE.record_live_fail(exc)
        return False

    if ok:
        STATE.record_live_ok(time.time() - t0)
    else:
        STATE.record_live_fail(ConnectionError("FortyGuard probe returned False"))
    return ok


# ---------------------------------------------------------------------------
# Hybrid wrapper: live value with auto-fallback
# ---------------------------------------------------------------------------
def hybrid_fetch(live_fetcher, fixture_fetcher, *, cacheable: bool = True):
    """Try ``live_fetcher`` (8 s budget) then fall back to fixtures.

    ``live_fetcher`` may raise or return a falsy sentinel to trigger the
    fixture path. The result of ``fixture_fetcher`` is always returned so the
    caller never sees a hard failure — the degraded state is visible only on
    ``GET /health``.
    """
    if is_live_capable():
        try:
            value = live_fetcher()
            if value is not None:
                return value
        except Exception as exc:  # noqa: BLE001
            STATE.record_live_fail(exc)
    return fixture_fetcher()


# ---------------------------------------------------------------------------
# Health payload (7.2)
# ---------------------------------------------------------------------------
def health_status() -> dict[str, Any]:
    """Payload for ``GET /health``.

    ``cache_age_s`` is the age of the fallback/fixture cache — i.e. how stale
    the screen would go if the live source vanished mid-demo.
    """
    source = resolve_data_source()
    return {
        "status": "ok",
        "service": "peachstate-coolchain",
        "data_source": source,
        "last_live_ok": STATE.last_live_ok,
        "last_live_at": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(STATE.last_live_at))
            if STATE.last_live_at is not None else None
        ),
        "last_error": STATE.last_error,
        "live_probe_ms": STATE.live_probe_ms,
        "cache_age_s": STATE.cache_age_s(),
        "live_capable": is_live_capable(),
        "fixtures_ok": True,
    }


# ---------------------------------------------------------------------------
# Demo-mode guard (7.2)
# ---------------------------------------------------------------------------
def demo_mode_ok(env: dict[str, str] | None = None) -> bool:
    """True when the demo-mode Streamlit env flags are set correctly."""
    env = os.environ if env is None else env
    return all(
        env.get(k, "").strip().lower() == v.lower()
        for k, v in DEMO_ENV_FLAGS.items()
    )


def ensure_demo_mode(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Validate/repair demo-mode env flags; report what changed."""
    env = os.environ if env is None else env
    missing: dict[str, str] = {}
    for k, v in DEMO_ENV_FLAGS.items():
        if env.get(k, "").strip().lower() != v.lower():
            missing[k] = v
    return {
        "ok": not missing,
        "flags": dict(DEMO_ENV_FLAGS),
        "missing": missing,
    }


__all__ = [
    "MODE_FIXTURES", "MODE_LIVE", "MODE_HYBRID", "MODES",
    "DEFAULT_SOURCE", "ENV_VAR", "KEY_ENV_VARS", "LIVE_TIMEOUT_S",
    "DEMO_ENV_FLAGS", "STATE", "resolve_data_source", "api_key_from_env",
    "is_live_capable", "probe_live", "hybrid_fetch", "health_status",
    "demo_mode_ok", "ensure_demo_mode",
]
