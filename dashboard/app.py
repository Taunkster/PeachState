"""PeachState CoolChain — Streamlit cold-chain command center (Day 5).

Entry point:  streamlit run dashboard/app.py

Six tabs: Field Map | Corridor Map | Risk Charts | Harvest Alerts |
KPI Dashboard | HI Report. FIXTURES mode by default (SQLite/JSON only, no
API calls). All data flows through ``dashboard.data_source`` — the app never
talks to the SDK directly.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from dashboard import data_source as ds
from dashboard.components import (
    cold_chain_kpis,
    corridor_map,
    field_map,
    harvest_alerts,
    hi_report,
    risk_charts,
)
from dashboard.styles.theme import GA_NAVY, GA_RED, app_badge, inject_theme

PAGE_TITLE = "PeachState CoolChain"
REGIONS = [
    ("all", "All Georgia"),
    ("fort_valley", "Fort Valley"),
    ("albany", "Albany"),
    ("bacon_appling", "Bacon/Appling"),
    ("vidalia", "Vidalia"),
]


# ---------------------------------------------------------------------------
# session state helpers
# ---------------------------------------------------------------------------
def _init_state() -> None:
    # Only non-widget keys are pre-seeded; widget values come from their own
    # ``default=`` / ``value=`` args so Streamlit owns the session_state keys.
    defaults = {
        "sms_sent": set(),
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## 🍑 PeachState")
        st.markdown("#### CoolChain Command")

        mode = st.segmented_control(
            "Data source", options=ds.MODES, default=ds.MODE_FIXTURES,
            key="mode",
        )
        st.caption(
            f"Mode: <b>{mode}</b> — "
            + (
                "reading SQLite + JSON fixtures only (no API calls)."
                if mode == ds.MODE_FIXTURES
                else "best-effort live API (8s timeout) with fixture fallback."
            ),
            unsafe_allow_html=True,
        )
        env_source = ds.resolve_source().upper()
        if mode != env_source:
            st.caption(
                f"<span style=\"color:#D96E2B;\">DATA_SOURCE={env_source}</span> "
                "from environment — overrides the toggle.",
                unsafe_allow_html=True,
            )

        st.date_input(
            "Demo date", value=date.fromisoformat(ds.DEFAULT_DATE),
            key="demo_date",
        )
        st.selectbox(
            "Region filter", options=[r[0] for r in REGIONS],
            format_func=lambda r: dict(REGIONS)[r], key="region",
        )
        st.divider()

        st.markdown(
            f'<div style="font-size:12px;color:#5b5f66;">'
            f"agent: monitoring <b>45 fields</b> · 15-min cadence · "
            f"{st.session_state.get('active_hour', '15:00')} EDT"
            f"</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------
def _filter_fields(fields: list[dict], region: str) -> list[dict]:
    if region == "all":
        return fields
    return [f for f in fields if f["region"] == region]


def _tab_field_map(fields: list[dict]) -> None:
    heat = ds.load_heat_frames()
    region_fields = _filter_fields(fields, st.session_state["region"])

    # Time slider 08:00-17:00 EDT.
    hour = st.select_slider(
        "Field heat · time of day (EDT)",
        options=ds.TIME_HOURS,
        value=st.session_state.get("active_hour", "15:00"),
        key="active_hour",
    )
    st.caption(f"Canopy heat frame — {hour} EDT · {len(region_fields)} farms")

    def _on_select(fid: str | None) -> None:
        st.session_state["selected_field_id"] = fid

    field_map.render(
        st,
        fields=region_fields,
        heat_payload=heat,
        active_hour=hour,
        selected_field_id=st.session_state.get("selected_field_id", "PV-07"),
        on_field_select=_on_select,
    )


def _tab_corridor_map() -> None:
    corridor = ds.load_corridor()
    corridor_map.render(st, corridor=corridor)


def _tab_risk_charts(fields: list[dict]) -> None:
    risk_data = ds.load_risk_data()
    risk_charts.render(st, risk_data=risk_data, fields=fields)


def _tab_harvest_alerts() -> None:
    alerts = ds.load_alerts()
    ack_store = ds.AlertAckStore(ds.db_path())
    harvest_alerts.render(st, alerts=alerts, ack_store=ack_store)


def _tab_kpis() -> None:
    kpis = ds.load_kpis()
    cold_chain_kpis.render(
        st, kpis=kpis, drill=st.session_state.get("kpi_drill"),
    )


def _tab_hi_report() -> None:
    report = ds.load_hi_report()
    hi_report.render(st, report=report)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon="🍑",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_theme()
    _init_state()
    ds.wire_caching()

    _render_sidebar()

    # Header + mode badge (st.html — safe raw HTML element)
    mode = st.session_state.get("mode", ds.MODE_FIXTURES)
    demo_date = st.session_state.get("demo_date", date.fromisoformat(ds.DEFAULT_DATE))
    st.html(
        f'<div style="display:flex;justify-content:space-between;align-items:center;">'
        f'<div style="font-size:26px;font-weight:700;color:{GA_NAVY};">'
        f"🍑 PeachState <span style=\"color:{GA_RED};\">CoolChain</span></div>"
        f'<div>{app_badge(mode)} · {demo_date}</div></div>'
    )
    st.caption(
        "Georgia agricultural thermal management — field to Port of Savannah. "
        "Powered by FortyGuard Temperature API."
    )

    fields = ds.load_fields()
    if not fields:
        st.warning(
            "No field data available — the app is running with an empty "
            "fixture set. Check `data/fixtures/dashboard/` or the "
            "`DATA_SOURCE` environment variable."
        )
    tabs = st.tabs(
        ["Field Map", "Corridor Map", "Risk Charts", "Harvest Alerts",
         "KPI Dashboard", "HI Report"]
    )
    with tabs[0]:
        _tab_field_map(fields)
    with tabs[1]:
        _tab_corridor_map()
    with tabs[2]:
        _tab_risk_charts(fields)
    with tabs[3]:
        _tab_harvest_alerts()
    with tabs[4]:
        _tab_kpis()
    with tabs[5]:
        _tab_hi_report()

    st.markdown(
        '<div style="text-align:center;font-size:12px;color:#6b6b71;margin-top:24px;">'
        "PeachState CoolChain · Day 7 final demo · offline-safe FIXTURES mode"
        "</div>",
        unsafe_allow_html=True,
    )

    # Health strip (7.2): source + last live probe + cache age, so a judge can
    # see the fallback state at a glance without asking.
    info = ds.mode_info()
    live_dot = (
        '<span class="pcs-dot pcs-dot-green"></span>'
        if info["last_live_ok"]
        else '<span class="pcs-dot pcs-dot-red"></span>'
    )
    live_txt = (
        f"live probe OK"
        if info["last_live_ok"]
        else f"live probe {'failed' if info['last_live_ok'] is False else 'idle'}"
    )
    st.caption(
        f"source <b>{info['data_source']}</b> · {live_dot}{live_txt} · "
        f"cache age {info['cache_age_s']:.0f}s · GET /health for full state",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()