"""PeachState CoolChain services - Alerting (Day 4).

Channels:
    - console   (demo: logs to stdout)
    - webhook   (HTTP POST)
    - sms       (Twilio stub - logged, no real carrier)
    - email     (SMTP stub - logged, no real MTA)

Rules:
    - Hysteresis + cooldown: 48 h per field (mirrors harvest_timing);
      the same field + same alert kind within the cooldown window is
      suppressed UNLESS the risk tier has escalated (LOW->MEDIUM->HIGH->
      CRITICAL).
    - Deduplication: identical (field_id, alert_kind, tier) within the
      cooldown window is suppressed.
    - Alert payload carries the full demo context (field_id, crop,
      risk_score, tier, canopy_temp_f, urgency, recommended_action,
      timestamp) and a rendered template line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from coolchain.domain.harvest_timing import HARVEST_COOLDOWN_H
from coolchain.services.persistence import Persistence

TIER_ORDER = ("low", "medium", "high", "critical")

# Exact demo template from the Day-4 spec (kept ASCII-escaped in source):
#   "🚨 {tier} ALERT: {crop} field {field_id} — {canopy_temp_f}°F canopy,
#    urgency {urgency}/100 → {action}"
ALERT_TEMPLATE = (
    "\U0001F6A8 {tier} ALERT: {crop} field {field_id} "
    "\u2014 {canopy_temp_f}\u00B0F canopy, urgency {urgency}/100 "
    "\u2192 {action}"
)

# The task template uses the emoji; kept as a separate constant so tests can
# assert on the exact demo string.
TEMPLATE_EMOJI = "\U0001F6A8"


@dataclass
class AlertConfig:
    cooldown_h: float = HARVEST_COOLDOWN_H  # 48 h per field
    channels: tuple[str, ...] = ("console", "webhook", "sms", "email")
    dry_run: bool = False  # demo: never hit real carriers/webhooks
    webhook_url: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    twilio_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""
    # injectable senders (tests / stubs)
    webhook_sender: Callable[[dict[str, Any]], Any] | None = None
    sms_sender: Callable[[dict[str, Any]], Any] | None = None
    email_sender: Callable[[dict[str, Any]], Any] | None = None


class AlertPayload(dict):
    """Dict payload with a rendered ``message`` template line."""

    @classmethod
    def build(
        cls,
        *,
        field_id: str,
        crop: str,
        risk_score: float,
        tier: str,
        canopy_temp_f: float | None,
        urgency: float,
        recommended_action: str,
        timestamp: str | None = None,
        alert_kind: str = "canopy_risk",
    ) -> "AlertPayload":
        payload = cls(
            field_id=field_id,
            crop=crop,
            risk_score=round(float(risk_score), 1),
            tier=str(tier).lower(),
            canopy_temp_f=round(canopy_temp_f, 1) if canopy_temp_f is not None else None,
            urgency=round(float(urgency), 1),
            recommended_action=recommended_action,
            alert_kind=alert_kind,
            timestamp=timestamp or _utc_now(),
        )
        payload["message"] = render_template(payload)
        return payload


def render_template(payload: dict[str, Any]) -> str:
    """Render the demo alert template.

    ``payload`` keys: field_id, crop, risk_score, tier, canopy_temp_f,
    urgency, recommended_action.
    """
    return ALERT_TEMPLATE.format(
        tier=str(payload.get("tier", "LOW")).upper(),
        crop=payload.get("crop", "peach"),
        field_id=payload.get("field_id", "?"),
        canopy_temp_f=payload.get("canopy_temp_f") or "n/a",
        urgency=payload.get("urgency", 0),
        action=payload.get("recommended_action", "monitor"),
    )


class AlertManager:
    """Cooldown + escalation + dedup + multi-channel dispatch."""

    def __init__(
        self,
        persistence: Persistence,
        config: AlertConfig | None = None,
    ) -> None:
        self.persistence = persistence
        self.config = config or AlertConfig()

    # ------------------------------------------------------------------
    # Cooldown / dedup / escalation
    # ------------------------------------------------------------------
    def _last_tier(self, field_id: str, alert_kind: str) -> str | None:
        ts = self.persistence.latest_alert_ts(field_id, alert_type=alert_kind)
        if ts is None:
            return None
        for row in self.persistence.alerts(limit=500):
            if row["field_id"] == field_id and row["alert_type"] == alert_kind:
                return row["severity"] or None
        return None

    def should_send(
        self,
        field_id: str,
        alert_kind: str,
        tier: str,
        *,
        now_ts: str | None = None,
    ) -> tuple[bool, str]:
        """Decide whether an alert should fire.

        Returns (send, reason). Suppressed when:
            - the last alert of the same kind is inside the cooldown window
              AND the tier has not escalated above the last tier (dedup).
        """
        from coolchain.domain.harvest_timing import cooldown_active

        last_ts = self.persistence.latest_alert_ts(field_id, alert_type=alert_kind)
        if last_ts is None:
            return True, "no prior alert"

        in_cooldown = cooldown_active(last_ts, now_ts, self.config.cooldown_h)
        last_tier = self._last_tier(field_id, alert_kind)
        escalated = _tier_index(tier) > _tier_index(last_tier)

        if in_cooldown and not escalated:
            return (
                False,
                f"suppressed: {alert_kind} cooldown active (last tier {last_tier})",
            )
        if in_cooldown and escalated:
            return True, f"escalated {last_tier} -> {tier} (sends through cooldown)"
        return True, f"cooldown expired (last {last_ts})"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def record(
        self,
        payload: AlertPayload,
        *,
        now_ts: str | None = None,
    ) -> int:
        """Persist the alert (and stamp the cooldown window)."""
        ts = now_ts or payload.get("timestamp") or _utc_now()
        return self.persistence.insert_alert(
            ts=ts,
            field_id=payload["field_id"],
            alert_type=payload.get("alert_kind", "canopy_risk"),
            severity=str(payload["tier"]).upper(),
            message=payload["message"],
        )

    # ------------------------------------------------------------------
    # Channel dispatch
    # ------------------------------------------------------------------
    def send(
        self,
        payload: AlertPayload,
        *,
        channels: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Dispatch a payload to every configured channel (best effort).

        Returns per-channel results: {channel, ok, detail}.
        """
        channels = channels or self.config.channels
        results: list[dict[str, Any]] = []
        for ch in channels:
            try:
                ok, detail = self._dispatch(ch, payload)
            except Exception as exc:  # noqa: BLE001 - channels never kill alerts
                ok, detail = False, str(exc)
            results.append({"channel": ch, "ok": ok, "detail": detail})
        return results

    def _dispatch(self, channel: str, payload: AlertPayload) -> tuple[bool, Any]:
        ch = channel.lower()
        if ch == "console":
            print(payload["message"])
            return True, "logged to console"
        if ch == "webhook":
            return self._send_webhook(payload)
        if ch == "sms":
            return self._send_sms(payload)
        if ch == "email":
            return self._send_email(payload)
        return False, f"unknown channel {channel!r}"

    def _send_webhook(self, payload: AlertPayload) -> tuple[bool, Any]:
        if self.config.dry_run or not self.config.webhook_url:
            return True, "webhook skipped (dry-run / no URL)"
        if self.config.webhook_sender is not None:
            return True, self.config.webhook_sender(payload)
        r = httpx.post(
            self.config.webhook_url,
            json=dict(payload),
            timeout=10.0,
        )
        r.raise_for_status()
        return True, f"HTTP {r.status_code}"

    def _send_sms(self, payload: AlertPayload) -> tuple[bool, Any]:
        if self.config.dry_run or not self.config.twilio_to:
            return True, "sms skipped (Twilio stub: no credentials configured)"
        if self.config.sms_sender is not None:
            return True, self.config.sms_sender(payload)
        # Twilio stub - real integration would POST to
        # https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json
        return True, (
            f"Twilio stub: SMS {payload.get('field_id')} queued "
            f"(sid={self.config.twilio_account_sid or 'demo'})"
        )

    def _send_email(self, payload: AlertPayload) -> tuple[bool, Any]:
        if self.config.dry_run or not self.config.email_to:
            return True, "email skipped (SMTP stub: no recipients configured)"
        if self.config.email_sender is not None:
            return True, self.config.email_sender(payload)
        # SMTP stub - real integration would use smtplib with the configured
        # host/credentials to send the payload to `email_to`.
        return True, (
            f"SMTP stub: email {payload.get('field_id')} queued "
            f"(host={self.config.smtp_host or 'demo'})"
        )

    # ------------------------------------------------------------------
    # High-level: evaluate a risk result -> optionally fire + record
    # ------------------------------------------------------------------
    def evaluate_and_send(
        self,
        *,
        field_id: str,
        crop: str,
        risk_score: float,
        tier: str,
        canopy_temp_f: float | None,
        urgency: float,
        recommended_action: str,
        alert_kind: str = "canopy_risk",
        now_ts: str | None = None,
    ) -> dict[str, Any]:
        """Full alert pipeline: dedup/cooldown -> payload -> send -> record."""
        send, reason = self.should_send(
            field_id, alert_kind, tier, now_ts=now_ts
        )
        payload = AlertPayload.build(
            field_id=field_id,
            crop=crop,
            risk_score=risk_score,
            tier=tier,
            canopy_temp_f=canopy_temp_f,
            urgency=urgency,
            recommended_action=recommended_action,
            alert_kind=alert_kind,
            timestamp=now_ts,
        )
        if not send:
            return {"sent": False, "reason": reason, "payload": dict(payload)}

        results = self.send(payload)
        self.record(payload, now_ts=now_ts)
        return {
            "sent": True,
            "reason": reason,
            "channels": results,
            "payload": dict(payload),
        }


def _tier_index(tier: str | None) -> int:
    if tier is None:
        return -1
    try:
        return TIER_ORDER.index(str(tier).lower())
    except ValueError:
        return -1


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = [
    "AlertConfig",
    "AlertPayload",
    "AlertManager",
    "render_template",
    "TIER_ORDER",
    "ALERT_TEMPLATE",
    "TEMPLATE_EMOJI",
]