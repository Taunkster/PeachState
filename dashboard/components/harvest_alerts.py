"""PeachState CoolChain dashboard — Harvest Alert Panel (Scene 2).

Day 5 (docs/02 §2.5): active alert table, SMS preview phone mockup, packing
house coordination, and an acknowledge button that persists to SQLite.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd
from dashboard.styles.theme import TIER_LABELS, tier_color
from dashboard.data_source import utc_to_edt_iso


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def alerts_df(alerts: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for a in alerts["alerts"]:
        rows.append({
            "field_id": a["field_id"],
            "crop": a["crop"].title(),
            "tier": TIER_LABELS.get(a["tier"], a["tier"]),
            "canopy_temp_f": a["canopy_temp_f"],
            "urgency": a["urgency"],
            "recommended_action": a["recommended_action"],
            "ts": utc_to_edt_iso(a["ts"]),  # naive EDT wall clock for display
            "acknowledged": bool(a.get("acknowledged", False)),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("urgency", ascending=False)
    return df


def alert_banner_html(alert: dict[str, Any]) -> str:
    """Pulsing red banner with the four decision readouts."""
    tier_col = tier_color(alert["tier"])
    return f"""
    <div class="pcs-alert" style="border-left:5px solid {tier_col};">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div style="font-weight:700;font-size:16px;">
          ⚠ FIELD {alert['field_id']} {TIER_LABELS.get(alert['tier'], alert['tier'])}
        </div>
        <div style="font-family:monospace;font-size:12px;opacity:.9;">
          {alert.get('ts_edt', alert.get('ts', ''))}
        </div>
      </div>
      <div style="margin-top:6px;font-size:13px;">
        risk {alert['urgency']:.0f}/100 · {alert['canopy_temp_f']:.1f}°F ·
        {alert['exceedance_hours']:.1f}h above threshold · action:
        <b>{alert['recommended_action']}</b>
      </div>
    </div>
    """


def sms_phone_html(sms: dict[str, Any] | None) -> str:
    """CSS phone mockup with the exact SMS text that goes to the foreman."""
    if sms is None:
        return (
            '<div class="pcs-card" style="font-size:13px;">'
            "No SMS dispatched for this alert.</div>"
        )
    body = sms.get("body", "").replace("\n", "<br>")
    sent = sms.get("sent_ts_edt") or sms.get("sent_ts", "")
    return f"""
    <div class="pcs-phone pcs-fade">
      <div class="phone-status">▸ {sms.get('from', 'PeachState Agent')}</div>
      <div style="padding:6px 10px;font-size:11px;color:#5b5f66;">
        TO: {sms.get('to', '')} · {sms.get('status', '')} {sent}
      </div>
      <div class="phone-bubble">{body}</div>
    </div>
    """


def packing_house_html(alert: dict[str, Any]) -> str:
    ph = alert.get("packing_house") or {}
    if not ph:
        return '<div class="pcs-card">No packing house assigned.</div>'
    return f"""
    <div class="pcs-card" style="font-size:13px;">
      <div style="font-weight:600;">🏭 {ph.get('name', 'Packing house')}</div>
      <table style="width:100%;margin-top:6px;border-collapse:collapse;">
        <tr><td style="padding:2px 0;color:#5b5f66;">Pre-cool slot</td>
            <td style="text-align:right;font-family:monospace;">{ph.get('precool_slot', '—')}</td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Inbound</td>
            <td style="text-align:right;font-family:monospace;">{ph.get('inbound_quantity', '—')}</td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Truck</td>
            <td style="text-align:right;font-family:monospace;">{ph.get('truck_id', '—')}</td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Cold storage</td>
            <td style="text-align:right;font-family:monospace;">{ph.get('cold_storage_lb', '—'):,} lb</td></tr>
      </table>
    </div>
    """


# ---------------------------------------------------------------------------
# Streamlit render
# ---------------------------------------------------------------------------
def render(
    st,
    *,
    alerts: dict[str, Any],
    ack_store: Any,
    on_acknowledge: Callable[[str], None] | None = None,
) -> None:
    df = alerts_df(alerts)
    if df.empty:
        st.info("No active harvest alerts.")
        return

    # Hero alert = highest urgency (PV-07 by construction).
    hero_id = df.iloc[0]["field_id"]
    hero = next(a for a in alerts["alerts"] if a["field_id"] == hero_id)
    st.markdown(alert_banner_html(hero), unsafe_allow_html=True)

    # Alert selector drives the SMS + packing house detail below the table.
    selected = st.selectbox(
        "Inspect alert", options=df["field_id"].tolist(), index=0,
        key="alert_select",
    )
    active = next(a for a in alerts["alerts"] if a["field_id"] == selected)

    c1, c2, c3 = st.columns([2, 1, 1], gap="medium")
    with c1:
        st.markdown("#### SMS preview — foreman")
        st.markdown(sms_phone_html(active.get("sms")), unsafe_allow_html=True)
    with c2:
        st.markdown("#### Packing house coordination")
        st.markdown(packing_house_html(active), unsafe_allow_html=True)
    with c3:
        st.markdown("#### Acknowledge")
        acked = ack_store.acknowledged() if ack_store is not None else set()
        is_acked = selected in acked or bool(active.get("acknowledged", False))
        if is_acked:
            st.success("✓ Read by foreman")
        else:
            if st.button("Mark as read", key=f"ack_{selected}", type="primary"):
                if ack_store is not None:
                    ack_store.mark_acknowledged(selected)
                if on_acknowledge:
                    on_acknowledge(selected)
                st.rerun()

    st.markdown("#### Active alerts")
    display = df.copy()
    display["ts"] = pd.to_datetime(display["ts"])
    st.dataframe(
        display.rename(columns={
            "field_id": "Field", "crop": "Crop", "tier": "Tier",
            "canopy_temp_f": "Canopy °F", "urgency": "Urgency",
            "recommended_action": "Recommended action", "ts": "Time (EDT)",
            "acknowledged": "Read",
        }),
        width="stretch",
        hide_index=True,
    )


__all__ = ["alerts_df", "alert_banner_html", "sms_phone_html",
           "packing_house_html", "render"]