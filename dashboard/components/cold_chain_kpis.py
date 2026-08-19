"""PeachState CoolChain dashboard — Cold Chain KPI cards (Scene 4 top row).

Day 5 (docs/02 §2.6): four large-number metric cards (spoilage ↓23%,
season savings $180K, fuel 12%, Port on-time 96%) with inline SVG
sparklines and a 4s counter-roll animation. Clicking a card drills into a
detail chart below.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

# tone -> CSS accent color
TONE_COLORS = {
    "green": "#2E7D32",
    "peach": "#D96E2B",
    "blue": "#003A70",
    "red": "#C8102E",
}


def sparkline_svg(values: list[float], color: str = "#003A70") -> str:
    """Inline 200x40 SVG sparkline (no external assets, offline-safe)."""
    if not values:
        return ""
    w, h, pad = 200, 40, 4
    vmin, vmax = min(values), max(values)
    span = max(vmax - vmin, 1e-9)
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad + (w - 2 * pad) * i / (n - 1)
        y = h - pad - (h - 2 * pad) * (v - vmin) / span
        pts.append(f"{x:.1f},{y:.1f}")
    last = pts[-1].split(",")
    poly = " ".join(pts)
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'style="display:block;margin-top:6px;">'
        f'<polyline points="{poly}" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last[0]}" cy="{last[1]}" r="3" fill="{color}"/>'
        f"</svg>"
    )


def kpi_card_html(kpi: dict[str, Any]) -> str:
    """One CSS metric card (Inter/ Roboto Mono, tabular numerals)."""
    color = TONE_COLORS.get(kpi["tone"], "#003A70")
    spark_color = {"green": "#2E7D32", "peach": "#D96E2B",
                   "blue": "#003A70", "red": "#C8102E"}.get(kpi["tone"], color)
    return f"""
    <div class="pcs-kpi pcs-roll" data-kpi="{kpi['id']}">
      <div class="kpi-label">{kpi['label']}</div>
      <div class="kpi-value">{kpi['value']}</div>
      <div class="kpi-delta">
        <span class="kpi-tone-{kpi['tone']}" style="font-weight:600;">{kpi['delta']}</span>
      </div>
      {sparkline_svg(kpi.get('spark', []), spark_color)}
    </div>
    """


def render_kpi_cards(kpis: dict[str, Any]) -> list[str]:
    """Render the 4-card row; returns the kpi ids so the drill-down can key on them."""
    cards = kpis.get("kpis", [])
    if not cards:
        st.info("No KPI data for the selected date/region — showing empty "
                "state instead of blank cards.")
        return []
    cols = st.columns(4, gap="medium")
    ids: list[str] = []
    for col, kpi in zip(cols, cards):
        with col:
            st.markdown(kpi_card_html(kpi), unsafe_allow_html=True)
            ids.append(kpi["id"])
    return ids


def render_secondary_strip(kpis: dict[str, Any]) -> None:
    items = " · ".join(kpis.get("secondary", []))
    st.markdown(
        f'<div style="font-size:13px;color:#5b5f66;margin-top:8px;">'
        f'<span class="pcs-dot pcs-dot-green"></span>{items}</div>',
        unsafe_allow_html=True,
    )


def render_drill_down(kpis: dict[str, Any], selected: str) -> None:
    """Detail chart for the clicked KPI card."""
    detail = kpis.get("detail", {})
    d = detail.get(selected, "")
    kpi = next((k for k in kpis["kpis"] if k["id"] == selected), None)
    if kpi is None:
        return
    st.markdown(
        f'<div class="pcs-card pcs-fade"><b>{kpi["label"]}</b> — '
        f'<span class="kpi-value" style="font-size:22px;">{kpi["value"]}</span><br>'
        f'<span style="font-size:13px;color:#5b5f66;">{d}</span></div>',
        unsafe_allow_html=True,
    )

    # Small trend chart of the spark values.
    import altair as alt
    import pandas as pd

    vals = kpi.get("spark", [])
    df = pd.DataFrame({
        "step": list(range(1, len(vals) + 1)), "value": vals,
    })
    chart = alt.Chart(df).mark_area(opacity=0.25).encode(
        x=alt.X("step:Q", title="Season week"),
        y=alt.Y("value:Q", title=kpi["label"]),
    ) + alt.Chart(df).mark_line(strokeWidth=2.5).encode(
        x="step:Q", y="value:Q",
    )
    chart = chart.properties(height=180)
    st.altair_chart(chart, width="stretch")


def render(
    st,
    *,
    kpis: dict[str, Any],
    drill: str | None = None,
    on_drill: Any = None,
) -> None:
    ids = render_kpi_cards(kpis)
    if not ids:
        return
    render_secondary_strip(kpis)

    with st.expander("KPI drill-down (click a card to select)", expanded=True):
        clicked = st.radio(
            "Detail", options=ids, index=ids.index(drill) if drill in ids else 0,
            horizontal=True, key="kpi_drill",
        )
        render_drill_down(kpis, clicked)
        if on_drill:
            # Only allowed before the radio widget is created; the radio itself
            # already persists the selection in session_state["kpi_drill"].
            try:
                on_drill(clicked)
            except Exception:
                pass


__all__ = ["sparkline_svg", "kpi_card_html", "render_kpi_cards",
           "render_secondary_strip", "render_drill_down", "render"]