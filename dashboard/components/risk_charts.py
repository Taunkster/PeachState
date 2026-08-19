"""PeachState CoolChain dashboard — Risk Charts component (Scene 4).

Day 5 (docs/02 §2.4):
    - 24h risk series per field (Altair line chart with tier bands)
    - Harvest window timeline (GDD progress + stress days + urgency)
    - Spoilage curve (degree-hours vs tolerance threshold)
    - Crop comparison radar (temp / exceedance / persistence components)
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from dashboard.styles.theme import (
    GA_NAVY,
    TIER_COLORS,
    TIER_LABELS,
    chip_style,
    heat_color,
    tier_color,
)

TIER_BANDS = [(0, 40, "LOW"), (40, 60, "MEDIUM"), (60, 75, "HIGH"), (75, 100, "CRITICAL")]


# ---------------------------------------------------------------------------
# Pure data-shaping helpers
# ---------------------------------------------------------------------------
def field_risk_series(risk_data: dict[str, Any], field_id: str) -> pd.DataFrame:
    rows = [r for r in risk_data["series"] if r["field_id"] == field_id]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["ts", "risk_score", "tier"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts")
    return df


def risk_series_chart(risk_data: dict[str, Any], field_ids: list[str]) -> Any:
    """Multi-field 24h risk line chart with tier bands."""
    import altair as alt

    all_rows = [r for r in risk_data["series"] if r["field_id"] in field_ids]
    df = pd.DataFrame(all_rows)
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"])

    band_rows = [
        {"y0": lo, "y1": hi, "tier": lbl, "color": TIER_COLORS[lbl.lower()]}
        for lo, hi, lbl in TIER_BANDS
    ]
    bands = alt.Chart(pd.DataFrame(band_rows)).mark_rect(opacity=0.12).encode(
        x=alt.X("ts:O", axis=None),
        y="y0:Q",
        y2="y1:Q",
        color=alt.Color("color:N", scale=None),
    )

    lines = alt.Chart(df).mark_line(strokeWidth=2.2).encode(
        x=alt.X("ts:T", title="Time (EDT)"),
        y=alt.Y("risk_score:Q", title="Canopy risk (0-100)",
                scale=alt.Scale(domain=(0, 100))),
        color=alt.Color("field_id:N", legend=alt.Legend(title="Field")),
        tooltip=["field_id", "ts", "risk_score", "tier"],
    )
    return (bands + lines).properties(height=300, title="24h canopy heat risk")


def harvest_window_df(risk_data: dict[str, Any]) -> pd.DataFrame:
    df = pd.DataFrame(risk_data["harvest_windows"])
    df["tier_color"] = df["tier"].map(tier_color)
    return df


def harvest_window_markdown(row: dict[str, Any]) -> str:
    """GDD progress bar + stress days + urgency for one field."""
    pct = min(100.0, float(row["gdd_progress_pct"]))
    bar_color = heat_color(60 + 40 * pct / 100.0, 60, 100)
    urgency = float(row["urgency"])
    urg_color = tier_color(
        "critical" if urgency >= 75 else "high" if urgency >= 60 else "medium"
    )
    return f"""
    <div class="pcs-card pcs-fade" style="margin-bottom:8px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <b>{row['field_id']}</b>
        <span class="pcs-chip" style="{chip_style(tier_color(row['tier']))}">
          {TIER_LABELS.get(row['tier'], row['tier'])}
        </span>
      </div>
      <div style="font-size:12px;color:#5b5f66;">{row['crop'].title()} · window <b>{row['window']}</b></div>
      <div style="margin:8px 0 2px;font-size:12px;color:#5b5f66;">
        GDD {row['gdd_since_bloom']:.0f}/{row['gdd_target']:.0f} ({row['gdd_progress_pct']:.0f}%)
      </div>
      <div style="height:8px;border-radius:6px;background:#eee;overflow:hidden;">
        <div style="width:{pct:.0f}%;height:100%;background:{bar_color};"></div>
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:12px;">
        <span style="color:#5b5f66;">{row['stress_days']} stress days</span>
        <span style="color:{urg_color};font-weight:700;font-family:monospace;">
          urgency {urgency:.0f}/100
        </span>
      </div>
    </div>
    """


def spoilage_chart(risk_data: dict[str, Any], crop: str | None = None) -> Any:
    """Degree-hours accumulation vs tolerance threshold per crop."""
    import altair as alt

    rows = []
    for s in risk_data["spoilage"]:
        if crop and s["crop"] != crop:
            continue
        for pt in s["curve"]:
            rows.append({
                "crop": s["crop"], "h": pt["h"], "dh": pt["dh"],
                "tolerance": s["tolerance_deg_hours"],
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    tol = alt.Chart(df).mark_rule(strokeDash=[4, 4], color=GA_NAVY).encode(
        y="tolerance:Q",
        color=alt.value("#0F1B33"),
    )
    lines = alt.Chart(df).mark_line(strokeWidth=2).encode(
        x=alt.X("h:Q", title="Transit hours"),
        y=alt.Y("dh:Q", title="Accumulated degree-hours (°F·h)"),
        color=alt.Color("crop:N", legend=alt.Legend(title="Crop")),
        tooltip=["crop", "h", "dh"],
    )
    return (lines + tol).properties(
        height=300, title="Spoilage curve — degree-hours vs crop tolerance"
    )


def crop_radar_chart(risk_data: dict[str, Any]) -> Any:
    """Radar of risk components per crop (plotly)."""
    import plotly.graph_objects as go

    radar_rows = risk_data["crop_radar"]
    if not radar_rows:
        return None
    cats = ["temp", "exceedance", "persistence"]
    labels = {
        "temp": "Temp score", "exceedance": "Exceedance", "persistence": "Persistence",
    }
    fig = go.Figure()
    for r in radar_rows:
        fig.add_trace(go.Scatterpolar(
            r=[r[c] for c in cats],
            theta=[labels[c] for c in cats],
            fill="toself",
            name=r["crop"].title(),
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        height=330,
        title="Risk components by crop",
        margin=dict(l=40, r=40, t=50, b=20),
    )
    return fig


# ---------------------------------------------------------------------------
# Streamlit render
# ---------------------------------------------------------------------------
def render(st, *, risk_data: dict[str, Any], fields: list[dict[str, Any]]) -> None:
    field_options = [f["field_id"] for f in fields]
    default = [fid for fid in ("PV-07", "PV-02", "AL-04") if fid in field_options]
    chosen = st.multiselect(
        "Fields to compare", options=field_options, default=default,
        key="risk_fields",
    )
    if not chosen:
        st.info("Select at least one field to see the 24h risk series.")
        chosen = field_options[:1]

    chart = risk_series_chart(risk_data, chosen)
    if chart is not None:
        st.altair_chart(chart, width="stretch")
    else:
        st.info("No 24h risk series for the selected fields — empty state "
                "shown instead of a blank chart.")

    c1, c2 = st.columns([2, 1], gap="medium")
    with c1:
        st.markdown("#### Harvest window timeline")
        df = harvest_window_df(risk_data)
        if df.empty:
            st.info("No harvest windows for the current region — select a "
                    "different region or demo date.")
        else:
            for _, row in df.iterrows():
                st.markdown(harvest_window_markdown(row.to_dict()), unsafe_allow_html=True)

    with c2:
        st.markdown("#### Spoilage curve")
        spoilage = spoilage_chart(risk_data)
        if spoilage is not None:
            st.altair_chart(spoilage, width="stretch")
        else:
            st.info("No spoilage curve data for the selected fields.")
        st.markdown("#### Crop comparison")
        radar = crop_radar_chart(risk_data)
        if radar is not None:
            st.plotly_chart(radar, width="stretch")
        else:
            st.info("No crop-comparison data available.")


__all__ = [
    "field_risk_series", "risk_series_chart", "harvest_window_df",
    "harvest_window_markdown", "spoilage_chart", "crop_radar_chart", "render",
]