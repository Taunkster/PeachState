"""PeachState CoolChain dashboard — design system tokens + CSS injection.

Day 5 (docs/03_design_system.md + Day-5 spec):
    - Georgia flag palette: red #C8102E, blue #003A70, peach #F58B4C.
    - Heat gradient (7-stop): #3B4CC0 -> #EF476F (data scale, cool -> hot).
    - Risk tiers: LOW green / MEDIUM amber / HIGH orange / CRITICAL Georgia red.
    - Typography: Inter (UI) + Roboto Mono (tabular numerals).
    - Motion: 300ms crossfade, 1.2s alert pulse, 4s counter roll.

Injected with ``st.markdown`` (CSS) + ``st.html`` (layout helpers).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
GA_RED = "#C8102E"
GA_BLUE = "#003A70"
GA_NAVY = "#0F1B33"
PEACH = "#F58B4C"
PEACH_DEEP = "#D96E2B"
PEACH_TEXT = "#A0471F"      # WCAG 4.5:1 text/white-on use of the peach brand
CREAM = "#F7F3EC"
WHITE = "#FFFFFF"
CARD_BORDER = "#E4DFD5"

# 7-stop heat gradient cool -> hot (endpoints fixed by the Day-5 spec).
HEAT_GRADIENT_7 = [
    "#3B4CC0", "#594BB3", "#774AA5", "#954998",
    "#B3498A", "#D1487D", "#EF476F",
]

# Risk tier colors (LOW/MEDIUM/HIGH/CRITICAL).
TIER_COLORS = {
    "low": "#2E7D32",
    "medium": "#F9A825",
    "high": "#EF6C00",
    "critical": GA_RED,
}
TIER_LABELS = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "critical": "CRITICAL"}

# Route colors: I-75 = Georgia red (hot inland), I-16 = Georgia blue (cool coastal).
ROUTE_COLORS = {"I75": GA_RED, "I16": GA_BLUE}

# Crop -> accent + emoji (crop chips / legend icons).
# Accent colors are chosen so white chip text meets WCAG 4.5:1.
CROP_META = {
    "peach": {"color": "#B45309", "emoji": "🍑", "label": "Peach"},
    "pecan": {"color": "#8B5A2B", "emoji": "🌰", "label": "Pecan"},
    "blueberry": {"color": "#3347B8", "emoji": "🫐", "label": "Blueberry"},
    "onion": {"color": "#6B8E23", "emoji": "🧅", "label": "Vidalia onion"},
    "watermelon": {"color": "#2E7D32", "emoji": "🍉", "label": "Watermelon"},
}

FONT_UI = "'Inter', 'Roboto', system-ui, sans-serif"
FONT_MONO = "'Roboto Mono', 'SFMono-Regular', Consolas, monospace"

_BASE_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Roboto+Mono:wght@400;500;600&display=swap');

:root {{
  --ga-red: {GA_RED};
  --ga-blue: {GA_BLUE};
  --ga-navy: {GA_NAVY};
  --peach: {PEACH};
  --peach-deep: {PEACH_DEEP};
  --cream: {CREAM};
  --card-border: {CARD_BORDER};
  --font-ui: {FONT_UI};
  --font-mono: {FONT_MONO};
  --heat-0: {HEAT_GRADIENT_7[0]};
  --heat-1: {HEAT_GRADIENT_7[1]};
  --heat-2: {HEAT_GRADIENT_7[2]};
  --heat-3: {HEAT_GRADIENT_7[3]};
  --heat-4: {HEAT_GRADIENT_7[4]};
  --heat-5: {HEAT_GRADIENT_7[5]};
  --heat-6: {HEAT_GRADIENT_7[6]};
}}

html, body, [class*="css"], .stApp {{
  font-family: {FONT_UI};
}}

.stApp {{
  background: {CREAM};
}}

/* ---- KPI metric cards ------------------------------------------------- */
.pcs-kpi {{
  border-radius: 12px;
  background: {WHITE};
  border: 1px solid {CARD_BORDER};
  box-shadow: 0 1px 3px rgba(0,0,0,.08);
  padding: 14px 16px 12px;
  min-height: 118px;
}}
.pcs-kpi .kpi-label {{
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .04em;
  text-transform: uppercase;
  color: #5b5f66;
}}
.pcs-kpi .kpi-value {{
  font-family: {FONT_MONO};
  font-variant-numeric: tabular-nums;
  font-size: 34px;
  font-weight: 600;
  line-height: 1.1;
  color: {GA_NAVY};
}}
.pcs-kpi .kpi-delta {{ font-size: 12px; color: #5b5f66; }}
.pcs-kpi .kpi-tone-green {{ color: #2E7D32; }}
.pcs-kpi .kpi-tone-peach {{ color: {PEACH_TEXT}; }}
.pcs-kpi .kpi-tone-blue  {{ color: {GA_BLUE}; }}
.pcs-kpi .kpi-tone-red   {{ color: {GA_RED}; }}

/* ---- Alert banner ------------------------------------------------------ */
.pcs-alert {{
  border-radius: 12px;
  padding: 14px 16px;
  color: #fff;
  background: linear-gradient(90deg, {GA_RED} 0%, #E14A5F 100%);
  border: 1px solid {GA_RED};
  box-shadow: 0 2px 10px rgba(200,16,46,.35);
  animation: pcs-pulse 1.2s ease-in-out infinite;
}}
@keyframes pcs-pulse {{
  0%, 100% {{ box-shadow: 0 0 0 0 rgba(200,16,46,.45); }}
  50% {{ box-shadow: 0 0 0 10px rgba(200,16,46,0); }}
}}

/* ---- SMS phone mockup -------------------------------------------------- */
.pcs-phone {{
  border-radius: 16px;
  border: 2px solid #d8d3c9;
  background: #fff;
  max-width: 340px;
  font-family: {FONT_MONO};
  font-size: 12.5px;
}}
.pcs-phone .phone-status {{
  background: {GA_NAVY}; color: #cfd6e4;
  padding: 6px 10px; border-radius: 12px 12px 0 0;
  font-size: 11px;
}}
.pcs-phone .phone-bubble {{
  margin: 8px 10px; padding: 8px 10px; border-radius: 10px;
  background: #eef1f6; color: {GA_NAVY}; white-space: pre-wrap;
}}

/* ---- Recommendation banner --------------------------------------------- */
.pcs-reco {{
  border-radius: 12px;
  padding: 12px 16px;
  background: linear-gradient(90deg, {GA_BLUE} 0%, #0d4b8f 100%);
  color: #fff;
  font-weight: 600;
  border: 1px solid {GA_BLUE};
}}

/* ---- Cards / generic ----------------------------------------------------- */
.pcs-card {{
  border-radius: 12px;
  background: #fff;
  border: 1px solid {CARD_BORDER};
  box-shadow: 0 1px 3px rgba(0,0,0,.08);
  padding: 12px;
}}

.pcs-chip {{
  display: inline-block;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  margin-right: 6px;
}}

.pcs-fade {{
  animation: pcs-fade 300ms ease-in-out;
}}
@keyframes pcs-fade {{
  from {{ opacity: 0; }}
  to {{ opacity: 1; }}
}}

/* Counter roll for KPI values (4s ease-out, tabular digits). */
.pcs-roll {{ animation: pcs-roll 4s cubic-bezier(.16,1,.3,1); }}
@keyframes pcs-roll {{
  from {{ opacity: 0; transform: translateY(10px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}

/* Status dots */
.pcs-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
.pcs-dot-green {{ background: #2E7D32; }}
.pcs-dot-red {{ background: {GA_RED}; }}

div[data-testid="stMetric"] {{
  background: #fff;
  border: 1px solid {CARD_BORDER};
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08);
  padding: 10px 12px;
}}
div[data-testid="stMetricValue"] {{ font-family: {FONT_MONO}; font-variant-numeric: tabular-nums; }}
</style>
"""


def inject_theme() -> None:
    """Inject the full design-system CSS into the running Streamlit app."""
    import streamlit as st

    st.markdown(_BASE_CSS, unsafe_allow_html=True)


def app_badge(mode: str) -> str:
    """LIVE / FIXTURES / HYBRID badge HTML (white text, WCAG-safe fills)."""
    color = {"LIVE": GA_RED, "FIXTURES": GA_BLUE, "HYBRID": PEACH_TEXT}.get(
        mode.upper(), GA_NAVY
    )
    return (
        f'<span style="background:{color};color:#fff;border-radius:999px;'
        f'padding:3px 12px;font-size:12px;font-weight:700;'
        f'font-family:{FONT_MONO}">{mode.upper()}</span>'
    )


def readable_text_on(bg: str) -> str:
    """White or GA-navy — whichever meets WCAG 4.5:1 on ``bg``.

    White fails on amber/orange/peach fills (medium tier, peach brand);
    GA-navy fails on red/blue/green fills. This picks a readable text color
    so chip/badge labels never drop below 4.5:1 (7.1 accessibility).
    """
    if _contrast_ratio(WHITE, bg) >= 4.5:
        return WHITE
    return GA_NAVY


def chip_style(bg: str) -> str:
    """Inline ``background:...;color:...`` for a pill chip on ``bg``."""
    return f"background:{bg};color:{readable_text_on(bg)};"


def heat_color(temp_f: float, lo: float | None = None, hi: float | None = None) -> str:
    """Map a temperature (°F) to a hex color in the 7-stop heat gradient.

    ``lo``/``hi`` default to 80/105 °F (a GA summer field range); values
    outside the band clamp to the nearest gradient stop.
    """
    lo = 80.0 if lo is None else float(lo)
    hi = 105.0 if hi is None else float(hi)
    t = max(0.0, min(1.0, (float(temp_f) - lo) / (hi - lo)))
    idx = t * (len(HEAT_GRADIENT_7) - 1)
    i = int(idx)
    if i >= len(HEAT_GRADIENT_7) - 1:
        return HEAT_GRADIENT_7[-1]
    f = idx - i
    return _lerp_hex(HEAT_GRADIENT_7[i], HEAT_GRADIENT_7[i + 1], f)


def tier_color(tier_name: str) -> str:
    return TIER_COLORS.get(str(tier_name).lower(), "#9E9E9E")


def _lerp_hex(a: str, b: str, f: float) -> str:
    ac = _hex_rgb(a)
    bc = _hex_rgb(b)
    rgb = tuple(round(ac[i] + (bc[i] - ac[i]) * f) for i in range(3))
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.x relative-luminance contrast ratio (>=4.5 for normal text)."""
    l_fg = _luminance(_hex_rgb(fg))
    l_bg = _luminance(_hex_rgb(bg))
    hi, lo = max(l_fg, l_bg), min(l_fg, l_bg)
    return (hi + 0.05) / (lo + 0.05)


def _luminance(rgb: tuple[int, int, int]) -> float:
    def _chan(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def gradient_css() -> str:
    """CSS for the heat-gradient scale bar."""
    stops = ", ".join(f"{c} {i/6*100:.0f}%" for i, c in enumerate(HEAT_GRADIENT_7))
    return f"linear-gradient(90deg, {stops})"


def render_scale_bar() -> Any:
    """Inline HTML heat scale bar (80°F -> 105°F)."""
    import streamlit as st

    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:8px;font-size:12px;
                    font-family:{FONT_MONO};color:#5b5f66;">
          <span>80°F</span>
          <div style="flex:1;height:10px;border-radius:6px;background:{gradient_css()};"></div>
          <span>105°F</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


__all__ = [
    "GA_RED", "GA_BLUE", "GA_NAVY", "PEACH", "PEACH_DEEP", "PEACH_TEXT",
    "CREAM", "WHITE", "CARD_BORDER", "HEAT_GRADIENT_7", "TIER_COLORS",
    "TIER_LABELS", "ROUTE_COLORS", "CROP_META", "FONT_UI", "FONT_MONO",
    "inject_theme", "app_badge", "heat_color", "tier_color",
    "readable_text_on", "chip_style", "gradient_css", "render_scale_bar",
]