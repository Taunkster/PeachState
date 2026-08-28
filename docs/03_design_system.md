# 03 — Visual Design System

## 3.1 Color tokens

Georgia flag palette (red/white/blue) as the brand layer; peach/orange accents for warmth; heat gradient as the data layer.

| Token | Hex | Usage |
|-------|-----|-------|
| `--ga-red` | `#C8102E` | Georgia flag red — critical alerts, danger, I-75 hot route |
| `--ga-blue` | `#003A70` | Georgia flag blue — brand, cool corridor, I-16 cool route |
| `--white` | `#FFFFFF` | Card surfaces, text on dark |
| `--navy` | `#0F1B33` | Hero background, dark text-on-light fallback |
| `--peach` | `#F58B4C` | Peach accent — season savings, selected state, highlights |
| `--peach-deep` | `#D96E2B` | Peach hover, deep accents |
| `--cream` | `#F7F3EC` | App background (soft, reads as white on screen) |

**Heat gradient (data scale, cool → hot):**
`#2E5AFF` (cool) → `#00C2D1` → `#4CD964` → `#FFD400` → `#FF9500` → `#FF3B30` → `#C8102E` (extreme) — the hot end deliberately lands on Georgia red.

**Risk tiers:**
- LOW `#2E7D32` (green) · MEDIUM `#F9A825` (amber) · HIGH `#EF6C00` (orange) · CRITICAL `#C8102E` (Georgia red)

**Routes:** I-75 default = `#C8102E` (Georgia red), I-16 cool corridor = `#003A70` (Georgia blue) — blue deliberately reads "cool" against the red-hot inland route, and both are literally the state flag colors.

## 3.2 Typography

- **Headings / body:** `Inter` (weights 400/600/700), fallback `Roboto`.
- **Numbers / KPIs / counters:** `Roboto Mono` or `Inter` with `font-variant-numeric: tabular-nums` — prevents digit jitter during counter rolls.
- **Scale:** H1 28px · H2 20px · body 14px · caption 12px · KPI values 34px.
- Injection: `styles/theme.py` → `st.markdown("<style>…</style>", unsafe_allow_html=True)`.
- Units always shown: `°F`, `mi`, `lb`, `$` — never bare numbers on a dashboard.

## 3.3 Map tiles & layers

- Base tiles: **CartoDB Positron** (light, clean, minimal noise) — matches the design system; `leafmap` supports it directly.
- Optional custom GA style: dark-on-light with state highways emphasized (`CartoDB Positron` + thin white outline on polygons) — keep the road layer quiet so crop polygons pop.
- Fallback tile: OpenStreetMap standard (denser) if Positron CDN is blocked.
- Offline fallback: pre-rendered static PNG per scene (see `06_fallback_plans.md`).
- Heat overlay: polygons at 45% opacity, no outlines, gradient fill.
- Route overlays: I-75 red / I-16 blue, weight 5, rounded caps; origin/destination markers with emoji glyphs (🚛 Macon, ⚓ Port of Savannah).

## 3.4 Motion & interaction language

| Element | Motion | Spec |
|---------|--------|------|
| Heatmap overlay | Crossfade | 300ms `ease-in-out` on layer swap |
| Alert banner | Slide + pulse | Slide-in 250ms; border pulse 1.2s infinite |
| SMS message | Typewriter | 40ms/char, monospace, phone mockup |
| Counter (e.g., $180K) | Roll | 4s, ease-out, tabular digits |
| Risk score | Step-up | 0.5s per tick, red tint while climbing |
| KPI value | Roll-in | 600ms on first render |
| Truck marker | Ghost trail | 30 markers, 80ms opacity ramp |
| Tab switch | Fade | 200ms crossfade between scenes |

## 3.5 Layout & density

- Left rail: tabs `Fields · Alerts · Routes · Ops · Scale` + live clock + `LIVE / FIXTURES` badge.
- Main area: scene component fills viewport height; fixed header 56px; no scrollbars mid-scene (sized to `vh`).
- Cards: `border-radius: 12px`, `box-shadow: 0 1px 3px rgba(0,0,0,.08)`, 12px padding, 1px `#E4DFD5` border.
- Status dots: 8px circles with `--green`/`--red` — used on field rows and the SMS log.
- Field ID convention shown as chips: `PV-07` (peach), `ALB-04` (pecan), `BB-03` (blueberry), `VD-08` (onion) — color-coded by crop.

## 3.6 Visual mockups (text descriptions)

**Field Map card (Scene 1):**
```
┌──────────────────────────────────────────────────────────┐
│ [Fields] [Alerts] [Routes] [Ops] [Scale]     LIVE · 15:00│
├──────────────────────────────────────────────────────────┤
│   ┌────────────────────────────────────────┐  ┌────────┐ │
│  │  (Fort Valley light map, peach poly-   │  │PV-07   │ │
│  │   gons green/amber/orange/red, trans-  │  │Peach   │ │
│  │   lucent heat overlay drifting under)  │  │87 CRIT │ │
│  │                                        │  │98°F    │ │
│  │  ● PV-07 · Peach · 87 CRITICAL · 98°F │  │spark.. │ │
│   └────────────────────────────────────────┘  └────────┘ │
│   ──┬──────────┬──────────┬──────────┬── 08:00 ── 15:00 │
│   Fort Valley  Albany  Bacon/Appling  Vidalia   [chips]  │
└──────────────────────────────────────────────────────────┘
```

**Corridor map card (Scene 3):**
```
┌──────────────────────────────────────────────────────────┐
│ [Fields] [Alerts] [Routes] [Ops] [Scale]     LIVE · 15:12│
├──────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────┐  Legend        │
│  │  🚛Macon ●───────────                 │  ▬▬ I-75      │
│  │         ╲             ╲               │   97°F avg    │
│  │          ╲             ╲ ▬▬▬▬▬▬▬▬▬   │  ▬▬ I-16      │
│  │   red (I-75) ──────────  ● ⚓Savannah │   91°F avg    │
│  └──────────────────────────────────────┘               │
│  ┌──────────────────────────────────────┐               │
│  │ 102°F ┐        ▄▄▄▄▄                  │  I-75 318mi  │
│  │  91°F ┘ ▂▂▂▂▂▂▂▂▂▂▂                │  I-16 176mi  │
│  │        0mi ────────────── 318mi     │  Spoil −54%   │
│  └──────────────────────────────────────┘  Fuel −12%    │
└──────────────────────────────────────────────────────────┘
```

**Alert banner + SMS panel (Scene 2):**
```
┌──────────────────────────────────────────────────────────┐
│  ⚠ FIELD PV-07 CRITICAL — risk 91 · 98°F · 6h above 95°F │
├──────────────────────────────────────────────────────────┤
│  Decision inputs:  risk 91 │ exceed 6.0h │ persist +24h │ │
│                    action: HARVEST NOW                   │
│  [SEND SMS]                ┌─────────────────────────┐   │
│  ┌──────────────────┐      │ ▸ PeachState Agent      │   │
│  │ Fort Valley Co-op │      │ FIELD PV-07 — HARVEST  │   │
│  │ pre-cool 4:30 PM  │      │ NOW  98°F · 6h above…  │   │
│  │ 12,400 lb · #212  │      │ Packing house: FV Co-op│   │
│  └──────────────────┘      │ Truck: Reefer #212      │   │
│  urgency 88 · window NOW   └─────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

**KPI row (Scene 4):**
```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│↓ 23%     │ │$180K     │ │12%       │ │96%       │
│Spoilage  │ │Season    │ │Fuel      │ │Port      │
│ risk     │ │savings   │ │savings   │ │on-time   │
│ ↘ spark  │ │ ↗ spark  │ │ ↘ spark  │ │ ↗ spark  │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
Carbon ↓41 tCO₂e · 45 fields protected · 1,240 loads routed
```
