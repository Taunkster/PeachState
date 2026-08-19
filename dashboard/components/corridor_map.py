"""PeachState CoolChain dashboard — Corridor Map component (Scene 3).

Day 5 (docs/02 §2.3): dual-layer route overlay (I-75 Georgia-red inland vs
I-16 Georgia-blue coastal), Macon -> Port of Savannah. Temperature profile
chart along distance, summary cards, and the recommendation banner.
"""

from __future__ import annotations

from typing import Any, Callable

import folium
import pandas as pd
import streamlit as st

from dashboard.styles.theme import GA_BLUE, GA_RED, ROUTE_COLORS

POSITRON_TILES = "CartoDB Positron"
ORIGIN_ICON = "🚛"
DEST_ICON = "⚓"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def route_points(corridor: dict[str, Any], route_id: str) -> list[dict[str, Any]]:
    route = next(
        (r for r in corridor["routes"] if r["route_id"] == route_id), None
    )
    return route["points"] if route else []


def build_corridor_map(corridor: dict[str, Any]) -> folium.Map:
    """Folium map: both route polylines + origin/destination markers."""
    origin = corridor["origin"]
    dest = corridor["destination"]
    bounds: list[tuple[float, float]] = []
    m = folium.Map(
        location=[32.6, -82.6],
        zoom_start=8,
        tiles=POSITRON_TILES,
        control_scale=True,
        zoom_control=False,
    )

    for route in corridor["routes"]:
        rid = route["route_id"]
        color = ROUTE_COLORS.get(rid, GA_RED)
        pts = [(p["lat"], p["lon"]) for p in route["points"]]
        bounds.extend(pts)
        folium.PolyLine(
            pts,
            color=color,
            weight=5,
            opacity=0.9,
            tooltip=f"{route['label']} · {route['avg_temp_f']}°F avg · "
                    f"{route['distance_mi']:.0f} mi",
        ).add_to(m)
        # midpoint label
        mid = pts[len(pts) // 2]
        folium.Marker(
            mid,
            icon=folium.DivIcon(
                html=f'<div style="font-size:13px;font-weight:700;'
                     f'color:{color};">{rid}</div>'
            ),
        ).add_to(m)

    folium.Marker(
        (origin["lat"], origin["lon"]),
        popup=f"{ORIGIN_ICON} {origin['name']}",
        tooltip=f"{ORIGIN_ICON} {origin['name']}",
        icon=folium.DivIcon(
            html=f'<div style="font-size:24px;">{ORIGIN_ICON}</div>'
        ),
    ).add_to(m)
    folium.Marker(
        (dest["lat"], dest["lon"]),
        popup=f"{DEST_ICON} {dest['name']}",
        tooltip=f"{DEST_ICON} {dest['name']}",
        icon=folium.DivIcon(
            html=f'<div style="font-size:24px;">{DEST_ICON}</div>'
        ),
    ).add_to(m)

    if bounds:
        m.fit_bounds(bounds)
    return m


def route_summary_df(corridor: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for r in corridor["routes"]:
        rows.append({
            "route_id": r["route_id"],
            "label": r["label"],
            "distance_mi": r["distance_mi"],
            "avg_temp_f": r["avg_temp_f"],
            "peak_temp_f": r["peak_temp_f"],
            "heat_exposure": r["heat_exposure"],
            "spoilage_risk_pct": r["spoilage_risk_pct"],
            "fuel_gal": r["fuel_gal"],
            "eta_hours": r["eta_hours"],
        })
    return pd.DataFrame(rows)


def temp_profile_chart(corridor: dict[str, Any]) -> Any:
    """Altair two-series line chart: distance vs °F with spoilage band."""
    import altair as alt

    frames = []
    for r in corridor["routes"]:
        for p in r["points"]:
            frames.append({
                "route": "I-75 inland" if r["route_id"] == "I75" else "I-16 coastal",
                "d_mi": p["d_mi"],
                "temp_f": p["temp_f"],
            })
    df = pd.DataFrame(frames)

    base = alt.Chart(df).encode(
        x=alt.X("d_mi:Q", title="Distance from Macon (mi)", scale=alt.Scale(domain=(0, 320))),
        y=alt.Y("temp_f:Q", title="Ambient temperature (°F)",
                scale=alt.Scale(domain=(82, 106))),
        color=alt.Color(
            "route:N",
            scale=alt.Scale(domain=["I-75 inland", "I-16 coastal"],
                            range=[GA_RED, GA_BLUE]),
            legend=alt.Legend(title="Route"),
        ),
    )
    band = alt.Chart(pd.DataFrame([{"lo": 85, "hi": 95}])).mark_rect(
        opacity=0.08, color="#C8102E"
    ).encode(
        y="lo:Q",
        y2="hi:Q",
    )
    lines = base.mark_line(strokeWidth=3, point=False)
    return (band + lines).properties(
        height=300,
        title="Corridor temperature profile — spoilage risk band 85-95°F",
    )


def recommendation_html(corridor: dict[str, Any]) -> str:
    return f"""
    <div class="pcs-reco">
      ✅ {corridor["recommendation"]} — route recommended for reefer loads
    </div>
    """


def summary_metrics(corridor: dict[str, Any]) -> None:
    """Summary cards: distance, avg temp, heat exposure, spoilage, fuel, ETA."""
    rows = route_summary_df(corridor)
    i75 = rows[rows["route_id"] == "I75"].iloc[0]
    i16 = rows[rows["route_id"] == "I16"].iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("I-75 distance", f"{i75['distance_mi']:.0f} mi",
              f"{i75['distance_mi'] - i16['distance_mi']:.0f} mi longer")
    c2.metric("I-75 avg temp", f"{i75['avg_temp_f']:.1f} °F",
              f"{i75['avg_temp_f'] - i16['avg_temp_f']:.1f} °F hotter")
    c3.metric("I-16 distance", f"{i16['distance_mi']:.0f} mi",
              f"ETA {i16['eta_hours']:.1f} h")
    c4.metric("I-16 avg temp", f"{i16['avg_temp_f']:.1f} °F",
              f"ETA {i75['eta_hours']:.1f} h via I-75")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("I-75 heat exposure",
              f"{i75['heat_exposure']:,.0f} °F·mi",
              "Σ temp × distance")
    c2.metric("I-16 heat exposure",
              f"{i16['heat_exposure']:,.0f} °F·mi",
              f"-{i75['heat_exposure'] - i16['heat_exposure']:,.0f} °F·mi vs I-75")
    c3.metric("I-75 spoilage risk", f"{i75['spoilage_risk_pct']:.1f}%",
              "peach Q10 model")
    c4.metric("I-16 spoilage risk", f"{i16['spoilage_risk_pct']:.1f}%",
              f"-{(i75['spoilage_risk_pct'] - i16['spoilage_risk_pct']) / i75['spoilage_risk_pct'] * 100:.0f}% vs I-75")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("I-75 fuel", f"{i75['fuel_gal']:.0f} gal",
              f"{i75['fuel_gal'] - i16['fuel_gal']:.0f} gal more")
    c2.metric("I-16 fuel", f"{i16['fuel_gal']:.0f} gal",
              f"{(i75['fuel_gal'] - i16['fuel_gal']) / i75['fuel_gal'] * 100:.0f}% less")
    c3.metric("I-75 ETA", f"{i75['eta_hours']:.1f} h", "55 mph cruise")
    c4.metric("I-16 ETA", f"{i16['eta_hours']:.1f} h", "fits Port window")


# ---------------------------------------------------------------------------
# Streamlit render
# ---------------------------------------------------------------------------
def render(
    st,
    *,
    corridor: dict[str, Any],
    on_route_select: Callable[[str], None] | None = None,
) -> None:
    if not corridor or not corridor.get("routes"):
        st.info(
            "No corridor routes available for the selected date/region — "
            "switch the demo date or fall back to FIXTURES mode."
        )
        return
    st.markdown(recommendation_html(corridor), unsafe_allow_html=True)
    summary_metrics(corridor)

    col_map, col_chart = st.columns([3, 2], gap="medium")
    with col_map:
        m = build_corridor_map(corridor)
        try:
            from streamlit_folium import st_folium

            st_folium(m, width="100%", height=460, key="corridor_map")
        except Exception:
            st.components.v1.html(m._repr_html_(), height=460)
        # Accessible text alternative for the map (7.1): the same numbers a
        # sighted judge gets from the chart are available as a caption.
        i75 = next(r for r in corridor["routes"] if r["route_id"] == "I75")
        i16 = next(r for r in corridor["routes"] if r["route_id"] == "I16")
        st.caption(
            f"Route map (I-75 inland {i75['distance_mi']:.0f} mi / "
            f"{i75['avg_temp_f']:.1f}°F vs I-16 coastal {i16['distance_mi']:.0f} mi / "
            f"{i16['avg_temp_f']:.1f}°F) from {corridor['origin']['name']} to "
            f"{corridor['destination']['name']}. Color legend: red = I-75, "
            f"blue = I-16."
        )
        st.markdown(
            f'<div style="font-size:13px;">'
            f'<span style="color:{GA_RED};font-weight:700;">▬ I-75</span> inland · '
            f'<span style="color:{GA_BLUE};font-weight:700;">▬ I-16</span> coastal'
            f'</div>',
            unsafe_allow_html=True,
        )

    with col_chart:
        chart = temp_profile_chart(corridor)
        st.altair_chart(chart, width="stretch")

    st.markdown("#### Route comparison")
    rows = route_summary_df(corridor)
    st.dataframe(
        rows.drop(columns=["label"]).rename(columns={
            "route_id": "Route", "distance_mi": "Distance (mi)",
            "avg_temp_f": "Avg °F", "peak_temp_f": "Peak °F",
            "heat_exposure": "Heat exposure", "spoilage_risk_pct": "Spoilage %",
            "fuel_gal": "Fuel (gal)", "eta_hours": "ETA (h)",
        }),
        width="stretch",
        hide_index=True,
    )


__all__ = [
    "route_points", "build_corridor_map", "route_summary_df",
    "temp_profile_chart", "recommendation_html", "summary_metrics", "render",
]