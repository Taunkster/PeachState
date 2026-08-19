"""PeachState CoolChain dashboard — Field Map component (Scene 1).

Day 5 (docs/02 §2.2): GA farm polygons colored by risk tier + a translucent
FortyGuard heat-tile overlay with an 08:00-17:00 EDT time slider. Clicking a
field populates the sidebar detail panel. PNG export via an offline matplotlib
render (no network tiles).

Render path:
    render()  ->  build_map()  ->  st_folium (live click capture)
                                     |-- fallback st.components.v1.html
    +  sidebar detail panel for the selected field (selectbox + map click)
"""

from __future__ import annotations

import io
from typing import Any, Callable

import folium

from dashboard.styles.theme import (
    CROP_META,
    HEAT_GRADIENT_7,
    TIER_COLORS,
    TIER_LABELS,
    chip_style,
    heat_color,
    render_scale_bar,
    tier_color,
)

GA_CENTER = (32.5, -83.5)
GA_ZOOM = 7
POSITRON_TILES = "CartoDB Positron"


def _crop_emoji(crop: str) -> str:
    return CROP_META.get(crop, {}).get("emoji", "🌾")


# ---------------------------------------------------------------------------
# Pure map-building helpers (unit-testable without Streamlit)
# ---------------------------------------------------------------------------
def build_map(
    fields: list[dict[str, Any]],
    frames: dict[str, list[dict[str, Any]]],
    field_tiers: dict[str, dict[str, str]],
    active_hour: str,
    *,
    field_scores: dict[str, dict[str, float]] | None = None,
    center: tuple[float, float] = GA_CENTER,
    zoom: int = GA_ZOOM,
) -> folium.Map:
    """Folium map: GA center, Positron tiles, tier-colored field polygons,
    translucent heat-tile overlay for ``active_hour``."""
    m = folium.Map(location=list(center), zoom_start=zoom, tiles=POSITRON_TILES,
                   control_scale=True, zoom_control=False)

    tiers_now = field_tiers.get(active_hour, {})
    scores_now = (field_scores or {}).get(active_hour, {})
    tier_lookup = {f["field_id"]: f["risk"]["tier"] for f in fields}

    # Field polygons (fill by risk tier at the active hour).
    def _field_style(feature: dict[str, Any]) -> dict[str, Any]:
        fid = feature.get("id") or feature["properties"].get("field_id")
        t = tiers_now.get(fid, tier_lookup.get(fid, "low"))
        return {
            "fillColor": tier_color(t),
            "color": "#FFFFFF",
            "weight": 1.5,
            "fillOpacity": 0.7,
        }

    field_fc: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    for f in fields:
        # Hour-specific risk score when the fixture provides one (the demo
        # script reads PV-07 87 @ 08:00 -> 91 @ 15:00).
        hour_score = scores_now.get(f["field_id"], f["risk"]["score"])
        feature = {
            "type": "Feature",
            "id": f["field_id"],
            "properties": {
                "field_id": f["field_id"],
                "name": f["name"],
                "crop": f["crop"],
                "tier": tiers_now.get(f["field_id"], f["risk"]["tier"]),
                "risk_score": hour_score,
                "canopy_temp_f": f["risk"]["canopy_temp_f"],
                "urgency": f["harvest"]["urgency"],
            },
            "geometry": f["polygon"],
        }
        field_fc["features"].append(feature)

    gj_fields = folium.GeoJson(
        field_fc,
        name="fields",
        style_function=_field_style,
        highlight_function=lambda feat: {"weight": 3.0, "color": "#0F1B33"},
        tooltip=folium.GeoJsonTooltip(
            fields=["field_id", "crop", "tier", "risk_score", "canopy_temp_f"],
            aliases=["Field", "Crop", "Tier", "Risk", "Canopy °F"],
            localize=True,
            sticky=False,
        ),
        popup=folium.GeoJsonPopup(
            fields=["field_id", "name", "crop", "tier", "risk_score",
                    "canopy_temp_f", "urgency"],
            aliases=["Field", "Name", "Crop", "Tier", "Risk", "Canopy °F",
                     "Urgency"],
        ),
    )
    m.add_child(gj_fields)

    # Heat overlay tiles for the active hour (45% opacity, temp gradient).
    heat_features = frames.get(active_hour, [])

    def _heat_style(feature: dict[str, Any]) -> dict[str, Any]:
        t = feature["properties"].get("tcm_f", 90.0)
        return {
            "fillColor": heat_color(t),
            "color": heat_color(t),
            "weight": 0.2,
            "fillOpacity": 0.45,
        }

    if heat_features:
        heat_fc: dict[str, Any] = {
            "type": "FeatureCollection", "features": heat_features,
        }
        m.add_child(folium.GeoJson(
            heat_fc,
            name=f"heat-{active_hour}",
            style_function=_heat_style,
            show=True,
        ))

    # Alert pulse markers for CRITICAL fields at this hour.
    for f in fields:
        if tiers_now.get(f["field_id"], f["risk"]["tier"]) == "critical":
            lat, lon = f["center"]
            folium.CircleMarker(
                location=(lat, lon),
                radius=10,
                color="#C8102E",
                fill=True,
                fill_color="#C8102E",
                fill_opacity=0.35,
                weight=2,
                popup=f"{f['field_id']} — CRITICAL",
            ).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    return m


def field_click_id(folium_output: Any) -> str | None:
    """Extract the clicked field id from a st_folium result.

    st_folium returns ``last_object_clicked`` as ``{"id": ..., "props": {...}}``;
    we map the GeoJson ``id`` back to ``field_id`` via the feature props.
    """
    if folium_output is None:
        return None
    clicked = getattr(folium_output, "last_object_clicked", None)
    if not clicked or not isinstance(clicked, dict):
        return None
    props = clicked.get("props") or {}
    fid = props.get("field_id")
    return str(fid) if fid else None


def field_tooltip(f: dict[str, Any]) -> str:
    r = f["risk"]
    return (
        f"{_crop_emoji(f['crop'])} {f['field_id']} · "
        f"{f['crop'].title()} · {r['score']:.0f}/100 "
        f"{TIER_LABELS.get(r['tier'], r['tier'])} · {r['canopy_temp_f']:.0f}°F"
    )


# ---------------------------------------------------------------------------
# Sidebar detail panel
# ---------------------------------------------------------------------------
def field_detail_markdown(
    f: dict[str, Any] | None,
    *,
    score: float | None = None,
    tier: str | None = None,
) -> str:
    """HTML for the selected-field detail card (sidebar).

    ``score``/``tier`` override the snapshot values so the panel tracks the
    time-slider hour (demo script: PV-07 risk 87 @ 08:00 -> 91 @ 15:00).
    """
    if f is None:
        return (
            '<div class="pcs-card"><b>No field selected</b><br>'
            "Click a farm on the map (or pick one below) to inspect its "
            "canopy heat risk, harvest window and latest alert.</div>"
        )
    r = f["risk"]
    h = f["harvest"]
    if score is None:
        score = r["score"]
    if tier is None:
        tier = r["tier"]
    tier_col = tier_color(tier)
    return f"""
    <div class="pcs-card pcs-fade">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:22px;">{_crop_emoji(f['crop'])}</span>
        <div>
          <b>{f['field_id']}</b> · {f['name']}
          <div style="font-size:12px;color:#5b5f66;">{f['region_label']} · {f['area_acres']:.0f} ac</div>
        </div>
      </div>
      <div style="margin-top:8px;">
        <span class="pcs-chip" style="{chip_style(tier_col)};">
          {TIER_LABELS.get(tier, tier)} {score:.0f}/100
        </span>
        <span class="pcs-chip" style="{chip_style(CROP_META.get(f['crop'],{}).get('color','#666'))};">
          {f['crop'].title()}
        </span>
      </div>
      <table style="width:100%;margin-top:8px;font-size:13px;border-collapse:collapse;">
        <tr><td style="padding:2px 0;color:#5b5f66;">Canopy temp</td>
            <td style="text-align:right;font-family:monospace;"><b>{r['canopy_temp_f']:.1f}°F</b></td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Alert threshold</td>
            <td style="text-align:right;font-family:monospace;">{r['threshold_f']:.0f}°F</td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Heat index</td>
            <td style="text-align:right;font-family:monospace;">{r['heat_index_f']:.0f}°F</td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Exceedance</td>
            <td style="text-align:right;font-family:monospace;">{r['exceedance_hours']:.1f} h</td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Persistence</td>
            <td style="text-align:right;font-family:monospace;">{r['persistence_forecast_hours']:.1f} h</td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">GDD since bloom</td>
            <td style="text-align:right;font-family:monospace;">{h['gdd_since_bloom']:.0f} / {h['gdd_target']:.0f}</td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Stress days</td>
            <td style="text-align:right;font-family:monospace;">{h['stress_days']}</td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Urgency</td>
            <td style="text-align:right;font-family:monospace;"><b>{h['urgency']:.0f}/100</b></td></tr>
        <tr><td style="padding:2px 0;color:#5b5f66;">Harvest window</td>
            <td style="text-align:right;"><span class="pcs-chip" style="background:#0F1B33;">{h['window']}</span></td></tr>
      </table>
      <div style="margin-top:8px;font-size:12px;color:#5b5f66;">
        <span class="pcs-dot pcs-dot-red"></span>Last alert: field CRITICAL — harvest crews notified
      </div>
    </div>
    """


# ---------------------------------------------------------------------------
# Legend + PNG export (offline matplotlib)
# ---------------------------------------------------------------------------
def legend_html() -> str:
    tiers = [
        ("low", "LOW", "Normal — monitor"),
        ("medium", "MEDIUM", "Pre-cool window"),
        ("high", "HIGH", "Harvest soon"),
        ("critical", "CRITICAL", "Harvest NOW"),
    ]
    chips = "".join(
        f'<span style="{chip_style(TIER_COLORS[t])}border-radius:999px;'
        f'padding:2px 10px;font-size:12px;font-weight:600;margin-right:6px;">{lbl}</span>'
        for t, lbl, _ in tiers
    )
    crops = "".join(
        f'<span style="margin-right:10px;font-size:13px;">{meta["emoji"]} {meta["label"]}</span>'
        for meta in CROP_META.values()
    )
    heat_stops = "".join(
        f'<span style="display:inline-block;width:26px;height:10px;'
        f'background:{c};border-radius:3px;margin-right:2px;"></span>'
        for c in HEAT_GRADIENT_7
    )
    return (
        f'<div class="pcs-card" style="font-size:13px;">'
        f"<div style=\"font-weight:600;margin-bottom:6px;\">Risk tiers</div>{chips}"
        f"<div style=\"font-weight:600;margin:10px 0 6px;\">Crops</div>{crops}"
        f'<div style="font-weight:600;margin:10px 0 6px;">Canopy heat</div>'
        f'<div>{heat_stops}</div>'
        f'<div style="font-size:12px;color:#5b5f66;margin-top:4px;">80°F → 105°F</div>'
        f"</div>"
    )


def map_png_bytes(
    fields: list[dict[str, Any]],
    field_tiers: dict[str, dict[str, str]],
    active_hour: str,
    selected_field_id: str | None = None,
) -> bytes:
    """Offline PNG snapshot (matplotlib) — no network tiles required."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPolygon

    tiers_now = field_tiers.get(active_hour, {})
    fig, ax = plt.subplots(figsize=(9, 6), dpi=110)
    ax.set_facecolor("#EAF0F5")
    fig.patch.set_facecolor("#F7F3EC")
    for f in fields:
        tier = tiers_now.get(f["field_id"], f["risk"]["tier"])
        coords = f["polygon"]["coordinates"][0]
        poly = MplPolygon(
            [(lon, lat) for lon, lat in coords],
            closed=True,
            facecolor=tier_color(tier),
            edgecolor="white",
            linewidth=0.8,
            alpha=0.85,
            zorder=3,
        )
        ax.add_patch(poly)
        if f["field_id"] == selected_field_id:
            cx = f["center"][1]
            cy = f["center"][0]
            ax.scatter([cx], [cy], s=90, c="#0F1B33", marker="*", zorder=5)
    ax.set_xlim(-84.6, -81.0)
    ax.set_ylim(30.9, 34.8)
    ax.set_title(
        f"PeachState CoolChain — field risk · {active_hour} EDT · "
        f"{len(fields)} farms",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_xlabel("Longitude °W")
    ax.set_ylabel("Latitude °N")
    ax.grid(alpha=0.3, zorder=0)
    ax.tick_params(labelsize=9)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Streamlit render
# ---------------------------------------------------------------------------
def render(
    st,
    *,
    fields: list[dict[str, Any]],
    heat_payload: dict[str, Any],
    active_hour: str,
    selected_field_id: str | None,
    on_field_select: Callable[[str | None], None],
) -> None:
    """Render the field map + legend + export controls.

    ``on_field_select`` mutates session state (single source of truth). The
    sidebar selectbox is keyed to the same session_state value, so a map click
    and a dropdown pick converge on the same detail panel.
    """
    frames = heat_payload["frames"]
    field_tiers = heat_payload["field_tiers"]
    field_scores = heat_payload.get("field_scores", {})

    col_map, col_side = st.columns([3, 1], gap="medium")
    with col_map:
        m = build_map(fields, frames, field_tiers, active_hour,
                      field_scores=field_scores)
        clicked = None
        try:
            from streamlit_folium import st_folium

            out = st_folium(
                m, width="100%", height=560, returned_objects=["last_object_clicked"],
                key=f"field_map_{active_hour}",
            )
            clicked = field_click_id(out)
        except Exception:
            st.components.v1.html(m._repr_html_(), height=560)
        if clicked and clicked in {f["field_id"] for f in fields}:
            on_field_select(clicked)

        # Accessible text alternative for the interactive map (7.1): the
        # layered heat + tier colors are summarized so the map is not the only
        # channel carrying the risk signal.
        n_crit = sum(
            1 for f in fields
            if field_tiers.get(active_hour, {}).get(f["field_id"], f["risk"]["tier"])
            == "critical"
        )
        st.caption(
            f"Field risk map at {active_hour} EDT — {len(fields)} farms, "
            f"{n_crit} CRITICAL (harvest now). Color legend below: LOW green, "
            f"MEDIUM amber, HIGH orange, CRITICAL Georgia red; heat overlay "
            f"shows canopy temperature 80-105°F."
        )

        render_scale_bar()

    with col_side:
        st.markdown(legend_html(), unsafe_allow_html=True)
        st.markdown("### Field details")

        options = [f["field_id"] for f in fields]
        if not options:
            st.info("No fields in the selected region.")
            return
        index = options.index(selected_field_id) if selected_field_id in options else 0
        picked = st.selectbox(
            "Selected field (click map or pick)",
            options=options,
            index=index,
            key="selected_field_id",
        )
        lookup = field_by_id_lookup(fields)
        sel = lookup.get(picked)
        # Detail panel tracks the time slider: hour-specific score when the
        # fixture provides one (PV-07 87 @ 08:00 -> 91 @ 15:00).
        hour_scores = field_scores.get(active_hour, {})
        st.markdown(
            field_detail_markdown(
                sel,
                score=hour_scores.get(picked),
                tier=field_tiers.get(active_hour, {}).get(picked),
            ),
            unsafe_allow_html=True,
        )

        st.markdown("#### Export")
        png = map_png_bytes(fields, field_tiers, active_hour, picked)
        st.download_button(
            "📸 Export PNG",
            data=png,
            file_name=f"peachstate_fieldmap_{active_hour.replace(':','')}.png",
            mime="image/png",
            key="export_png",
        )


def field_by_id_lookup(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {f["field_id"]: f for f in fields}


__all__ = [
    "GA_CENTER", "GA_ZOOM", "build_map", "field_click_id", "field_tooltip",
    "field_detail_markdown", "legend_html", "map_png_bytes", "render",
]