# 02 — Streamlit Dashboard Component Specs

## Component module map (matches project architecture)

```
dashboard/
├── app.py                      # Tab router: Fields | Alerts | Routes | Ops | Scale
├── components/
│   ├── field_map.py            # Field Map (Scene 1 & 5)
│   ├── corridor_map.py         # Cool Corridor I-75 vs I-16 (Scene 3)
│   ├── risk_charts.py          # Risk time-series + harvest urgency + GDD tracker (Scene 4)
│   ├── harvest_alert_panel.py  # Alert banner + SMS preview + packing house (Scene 2)
│   └── cold_chain_kpis.py      # KPI card row (Scene 4)
├── state.py                    # DemoState dataclass (single source of truth)
├── data_source.py              # LIVE_API / FIXTURES switcher
└── styles/
    └── theme.py                # Color tokens, CSS injection
```

## 2.1 Shared patterns

- **DemoState (`state.py`):** a single `@dataclass` holding `current_time`, `selected_field_id`, `alert_field_id`, `route_selection`, `sms_log: list[SmsEvent]`, `fixture_mode: bool`. All components read from it. The scripted demo becomes a deterministic sequence of state mutations — never network-dependent renders.
- **Data source abstraction (`data_source.py`):** exposes `get_heatmap(spec) -> HeatmapResult`, `get_env_params(spec) -> EnvParamsResult`, etc. With `FIXTURES=1` it reads `data/fixtures/*.json`; with `LIVE=1` it calls the SDK. **The Streamlit app never talks to the SDK directly** — this makes the fallback plan a one-line change.
- **Caching:** `@st.cache_data(ttl=300)` on every data getter. Fixtures cached for the whole session; live mode caches per `activity_id` so a re-render never re-polls.
- **No-spinner rule:** map layers are pre-rendered HTML once, re-injected via `components.html` with a hash key. Slider changes only swap the overlay layer, never rebuild the base map.
- **Units rule:** everything displayed in **°F** (Georgia audience), every data contract stores °F explicitly. No silent C→F conversions.

## 2.2 `FieldMap` — crop polygons + canopy heat overlay + time slider

**Purpose:** Scene 1 (Fort Valley + Albany) and Scene 5 (Athens/Atlanta scale-down). Choropleth of field risk + semi-transparent FortyGuard heatmap overlay with a time slider.

**Props:**
```python
field_map(
    fields: list[Field],
    heat_frames: dict[str, list[HeatFeature]],  # keyed by "HH:00"
    slider_value: str,                           # "15:00"
    selected_field_id: str | None,
    show_alert: bool,
    alert_field_id: str | None,
    center: tuple[float, float],
    zoom: int,
)
```

**Data contract — Field:**
```json
{
  "field_id": "PV-07",
  "name": "Peach Valley Orchard 7",
  "crop": "peach",
  "region": "fort_valley",
  "area_acres": 214.0,
  "center": [32.5512, -83.8971],
  "polygon": {"type": "Polygon", "coordinates": [[[-83.902, 32.554], [-83.894, 32.556], [-83.891, 32.548], [-83.899, 32.547]]]},
  "risk": {
    "score": 87,
    "tier": "CRITICAL",
    "canopy_temp_f": 98.2,
    "threshold_f": 95.0,
    "heat_index_f": 112.0,
    "humidity_pct": 71,
    "exceedance_hours": 3.4,
    "persistence_forecast_hours": 24.0
  },
  "harvest": {"urgency": 88, "window": "NOW", "gdd_since_bloom": 812}
}
```
Enums: `crop ∈ {peach, pecan, blueberry, onion, community, residential}` · `tier ∈ {LOW, MEDIUM, HIGH, CRITICAL}` · `region ∈ {fort_valley, albany, bacon_appling, vidalia, athens, atlanta}`

**Data contract — HeatFeature (one frame):**
```json
{
  "type": "Feature",
  "properties": {"hour": "15:00", "tcm_f": 98.2, "analytic": "tcm"},
  "geometry": {"type": "Polygon", "coordinates": [[[lon, lat], ...]]}
}
```

**Rendering behavior:**
- Base: `leafmap` / `folium.Map`, `tiles="CartoDB Positron"`, `zoom_control=False`.
- Field polygons: `GeoJson`, `style_function` maps `risk.tier → fill color` (see design system), weight 1.5, white edge.
- Click: `tooltip = "PV-07 · Peach · 91/100 CRITICAL · 98°F"`, popup = risk detail; click sets `DemoState.selected_field_id`, re-renders the side panel.
- Heat overlay: separate `GeoJson`, `opacity=0.45`, gradient fill by `tcm_f`. **One layer per hour pre-rendered; slider swaps visibility** — no re-fetch, no flicker.
- Alert mode: alert field polygon gets a CSS pulse (`@keyframes pulse` radius circle marker).
- Region switcher chip row: `Fort Valley · Albany · Bacon/Appling · Vidalia` (Scene 1) / `Athens · Atlanta` (Scene 5).

**Time budget:** base map ~80ms (cached HTML), overlay swap ~30ms.

## 2.3 `CorridorMap` — dual-layer route comparison + temp profile

**Purpose:** Scene 3. I-75 (hot/red) vs I-16 (cool/blue), animated truck, temperature profile chart.

**Props:**
```python
corridor_map(
    origin: [lon, lat],
    destination: [lon, lat],
    default_route: LineString,
    cool_route: LineString,
    temp_profile_default: list[RoutePoint],
    temp_profile_cool: list[RoutePoint],
    animate_truck: bool,
)
```

**Data contract — RoutePoint:**
```json
{
  "route_id": "i75",
  "distance_mi": 318.0,
  "duration_h": 5.2,
  "points": [
    {"d_mi": 0.0, "temp_f": 98.5, "lat": 32.84, "lon": -83.63},
    {"d_mi": 20.0, "temp_f": 97.8, "lat": 32.62, "lon": -83.58}
  ],
  "stats": {
    "avg_temp_f": 97.1,
    "peak_temp_f": 102.4,
    "spoilage_prob_pct": 6.8,
    "fuel_gal": 132.0
  }
}
```
(second route object has `"route_id": "i16"`, `avg_temp_f: 91.3`, `peak_temp_f: 96.1`, `spoilage_prob_pct: 3.1`, `fuel_gal: 116.0`)

**Rendering behavior:**
- Two `PolyLine` layers: I-75 = red (weight 5), I-16 = blue (weight 5). Legend top-right: "I-75 inland (97°F avg)" / "I-16 coastal (91°F avg)".
- Truck animation, simplest robust approach: **30 ghost truck markers** along the I-16 route, opacity ramps in sequence (80ms steps) = illusion of movement, zero JS.
- Temp profile chart: `altair`/`plotly` two-series line chart, x = `distance_mi`, y = `temp_f`; red vs blue curves; shaded 85–95°F band labeled "spoilage risk band"; annotated min/max.
- Stats strip: three `st.metric` — avg temp delta, spoilage delta, fuel savings.

## 2.4 `RiskCharts` — risk time-series + harvest urgency + GDD tracker

**Purpose:** Scene 4 middle row.

**Props:**
```python
risk_charts(
    risk_series: list[RiskPoint],          # per field, 24h, 30-min resolution
    harvest_events: list[HarvestEvent],
    gdd_tracker: list[GddPoint],           # season-long GDD accumulation
)
```

**Data contract:**
```json
{
  "risk_series": [
    {"field_id": "PV-07", "ts": "2024-07-15T19:00:00Z", "risk_score": 87, "tier": "CRITICAL"}
  ],
  "harvest_events": [
    {"field_id": "PV-07", "ts": "2024-07-15T19:04:00Z",
     "crop": "peach", "urgency": 88, "trigger": "auto",
     "action": "HARVEST_NOW", "window": "2024-07-15T19:00Z/2024-07-16T11:00Z"}
  ],
  "gdd_tracker": [
    {"crop": "peach", "date": "2024-03-15", "gdd_base50": 0, "target": 850}
  ]
}
```

**Rendering behavior:**
- Left: multi-line chart (one line per field, muted gray), PV-07 highlighted red + annotation at harvest event ("harvest NOW 19:04 → spoilage −23%").
- Middle: harvest urgency timeline (`altair`) — x = time, one row per field, dots = harvest windows, colored by tier, size ∝ urgency.
- Right: GDD tracker — one small gauge/area per crop showing current GDD vs target (peach: 812/850 for harvest maturity), with a "days early/late" readout.
## 2.5 `HarvestAlertPanel` — alert banner + SMS preview + packing house coordination

**Purpose:** Scene 2. Alert banner, SMS phone mockup, packing house coordination.

**Props:**
```python
harvest_alert_panel(
    alert: Alert | None,
    sms_preview: SmsMessage | None,
    packing_house: PackingHouseTask | None,
    on_send: callable,          # mutates DemoState
)
```

**Data contract:**
```json
{
  "alert": {
    "field_id": "PV-07", "severity": "CRITICAL",
    "risk_score": 91, "crop": "peach", "threshold_f": 95.0,
    "canopy_temp_f": 98.2, "exceedance_hours": 3.4,
    "forecast_exceedance_24h_hours": 6.0,
    "persistence_forecast_hours": 24.0,
    "recommended_action": "HARVEST_NOW"
  },
  "sms": {
    "from": "PeachState Agent",
    "to": "+1 (478) 555-0142 · Foreman M. Reed",
    "body": "FIELD PV-07 — HARVEST NOW\n98°F · 3.4h above threshold · +6h forecast\nPacking house: Fort Valley Co-op (pre-cool slot 4:30 PM)\nTruck: Reefer #212 dispatched · I-16 corridor",
    "status": "SENT", "sent_ts": "2024-07-15T19:04:00Z"
  },
  "packing_house": {
    "facility_id": "FVC-01", "name": "Fort Valley Peach Co-op",
    "crop": "peach", "precool_slot": "2024-07-15T20:30:00Z",
    "inbound_quantity": "12,400 lb", "truck_id": "Reefer #212"
  }
}
```

**Rendering behavior:**
- Alert banner: red gradient card, pulsing border, icon, field name, and the **four decision readouts** (`risk`, `exceedance`, `persistence`, `recommended action`) — this visualizes the agent's reasoning for the AI Agents judges.
- SMS preview: CSS phone mockup (rounded rect, status bar, message bubbles) — text types itself with a 40ms/char animation on trigger.
- "SEND SMS" primary button → phone mockup animates in, then toasts `STATUS: SENT · FOREMAN CONFIRMED · PACKING HOUSE NOTIFIED`.
- Packing house card: facility name, pre-cool slot, inbound quantity, assigned truck.
- Harvest urgency meter: `urgency 88/100 · window NOW · cooldown 48h`.

## 2.6 `ColdChainKpis` — KPI card row

**Purpose:** Scene 4 top row.

**Props:** `cold_chain_kpis(kpis: list[Kpi])`

**Data contract:**
```json
{"kpis": [
  {"id": "spoilage", "label": "Spoilage risk", "value": "↓ 23%",
   "delta": "-23 pp", "direction": "down", "spark": [46,43,40,36,32,27,23], "tone": "green"},
  {"id": "savings", "label": "Season savings", "value": "$180K",
   "delta": "+$180K vs baseline", "spark": [20,60,95,125,150,168,180], "tone": "peach"},
  {"id": "fuel", "label": "Fuel savings", "value": "12%",
   "delta": "-12% fuel/season", "spark": [3,5,7,9,10,11,12], "tone": "blue"},
  {"id": "port", "label": "Port on-time", "value": "96%",
   "delta": "+14 pp vs baseline", "spark": [82,85,89,92,94,95,96], "tone": "green"}
]}
```

**Rendering behavior:** four CSS cards in `st.columns(4)`, each with icon, big value (Inter SemiBold, tabular numerals), delta chip, 200×40 inline SVG sparkline. Values roll in on first render (JS animation, 4s counter roll for `$180K`). Secondary metrics strip: `Carbon ↓41 t CO₂e · 45 fields protected · 1,240 loads routed`.

## 2.7 App-level behaviors

- **Tab router (`app.py`):** five tabs `Fields · Alerts · Routes · Ops · Scale`; scene state read from `DemoState`, not from widget defaults — so hotkeys and mouse clicks converge on the same render.
- **Hidden hotkey `Ctrl+D`:** steps to the next scene regardless of mouse — presenter safety net.
- **Badge:** header shows `LIVE` or `FIXTURES`; the presenter mentions the badge only when actually live.
- **Regional footer:** thin agent-watch bar: `agent: monitoring 45 fields · 3:52 pm` — shows async polling cadence (15-min) without a spinner.
