# 01 — Five-Minute Demo Script (Scene by Scene)

Total: **300 seconds**. ~15s of buffer built into transitions. Hard cut to closing at 4:50.

| # | Time | Scene | Core Visual | Endpoints shown |
|---|------|-------|-------------|-----------------|
| 0 | 0:00–0:30 | Hook | Hero + $74B + heat threat chips | — |
| 1 | 0:30–1:30 | Live Field Map | Fort Valley + Albany, time-slider heatmap | `heatmap` (tcm) |
| 2 | 1:30–2:30 | Harvest Alert → SMS | Pulse alert + SMS phone mockup | `heatmap` (exceedance) + `env_params` |
| 3 | 2:30–3:30 | Cool Corridor Routing | I-75 vs I-16 dual-layer map + temp profile | `heatmap` (corridor) + `env_params` |
| 4 | 3:30–4:15 | Cold Chain Dashboard | KPI cards + risk charts + GDD tracker | `heat_intelligence` (report) |
| 5 | 4:15–5:00 | Scale Vision | Athens community garden + Atlanta last-mile | Same API, 10 mi² Basic |

---

## Scene 0 — HOOK (0:00–0:30)

**Visual:** Full-screen title card. Dark navy background, PeachState CoolChain logo (peach slice + thermometer + state outline), subtitle "Georgia Agricultural Thermal Intelligence". Slow heat-shimmer gradient (peach-orange) behind. Three stat chips fade in one by one.

**Narration (~25s):**
> "Georgia grows $74 billion of food a year — peaches, pecans, Vidalia onions, blueberries — a crop goes from field to Port of Savannah in hours, and every one of those hours is a race against heat.
>
> July here is brutal: 95-plus degrees, humidity you can pour. Heat ripens fruit too fast, rots it in transit, and sends the refrigerated load to the dumpster instead of the dock.
>
> PeachState CoolChain takes FortyGuard's hyperlocal temperature API and turns it into an **action signal** — for the orchard, for the truck, and for the last mile."

**On-screen stat chips (staggered):**
- `$74B` Georgia agricultural economy → *the 4th-largest in the US*
- `95°F+` humid July peaks → *accelerates spoilage from field to port*
- `98°F` canopy at Fort Valley right now → *FortyGuard sees it first*

**Presenter cues:** Stand confidently, brief eye contact on "$74 billion". On "action signal", gesture toward the screen; the app transitions to Scene 1.

**Transition (5s):** App window opens with a fast zoom to Fort Valley, GA (32.55°N, 83.89°W). Map tiles load from cache (no spinner).

---

## Scene 1 — LIVE FIELD MAP: FORT VALLEY + ALBANY (0:30–1:30)

**Visual:** Field Map component. CartoDB Positron light tiles. Fort Valley peach orchard polygons (PV-01…PV-15) around 32.55°N, 83.89°W, and Albany pecan groves (ALB-01…ALB-10) ~60 mi west along the Flint River. Polygons filled by risk tier (green/amber/orange/red). Semi-transparent canopy heatmap overlay (FortyGuard `tcm` analytic) drifts in. Time slider at bottom; clock reads **08:00 EDT**.

**Narration (~45s):**
> "This is Peach County, Georgia — the peach capital of America. These polygons are real orchard blocks; the color is **canopy heat risk** — computed from FortyGuard's 2-meter temperature snapshots plus humidity, heat index, and solar irradiance.
>
> Let's ride the day. 8 a.m., the orchards are calm. [drag slider to 11:00] By 11, the western blocks are already amber. [drag to 15:00] Three p.m. — and the whole valley is in the danger zone. This heatmap is the actual `heatmap` endpoint — the temperature signal underneath every decision you're about to see."

**Interactions (exact):**
1. Drag slider 08:00 → 11:00 → 15:00 (heat overlay morphs, 300ms ease).
2. **Click Orchard PV-07** → side panel slides in:
   - Name "Peach Valley Orchard 7" · Crop **Peach** · Area 214 ac
   - Canopy risk **87 / 100 (CRITICAL)** · Current **98°F** · Threshold **95°F**
   - Exceedance **3.4h** · Humidity **71%** · Heat index **112°F**
   - Mini sparkline: risk 08:00→15:00.

**Presenter cues:** Mouse only, no keyboard. Slider drags slow enough to see interpolation; pause 1s after each drag.

**Transition (3s):** Click "Alerts" tab → Dashboard swaps to scene-2 state. Thin "agent watch" footer bar: `agent: monitoring 45 fields · 3:52 pm`.

---

## Scene 2 — HARVEST ALERT → AUTO-SMS (1:30–2:30)

**Visual:** Same map; Orchard **PV-07** flashes. Red alert banner slides in from the right with pulsing edge:
`⚠ FIELD PV-07 CRITICAL — canopy risk 91/100 · 98°F · +6h exceedance forecast → HARVEST NOW`

The **Harvest Alert Panel** opens: active alerts list, **SMS preview phone mockup**, packing house coordination card.

**Narration (~50s):**
> "Now watch the agent work. Orchard seven — peaches — is at 98 degrees, already three and a half hours above its crop threshold, and the forecast says six more hours of heat ahead today. That's the `exceedance` analytic talking.
>
> The harvest-timing agent runs the numbers — fruit is at full color, heat stress days are peaking — and it makes a call a human crew would take hours to reach: **harvest now**.
>
> [click SEND SMS] The foreman's phone gets the alert, the packing house in Fort Valley is notified that a load is coming hot, and the reefer truck is pre-cooled and dispatched. No spreadsheets. No guesswork. One API call."

**Visual action (the payoff):**
- SMS phone mockup animates in, text types itself:
  ```
  From: PeachState Agent
  FIELD PV-07 — HARVEST NOW
  98°F · 3.4h above threshold · +6h forecast
  Packing house: Fort Valley Co-op (pre-cool slot 4:30 PM)
  Truck: Reefer #212 dispatched · I-16 corridor
  ```
- `STATUS: SMS SENT · FOREMAN CONFIRMED · PACKING HOUSE NOTIFIED` toasts stack.
- Risk score PV-07 label: "harvest window: NOW · cooldown 48h".
- Toast: `Harvest command committed · agent next check in 15 min`.

**Presenter cues:** Hit "SEND SMS" as "harvest now" lands. Let the SMS type itself out (2s). Smile at "no spreadsheets" — the AI Agent track.

**Transition (3s):** Click "Routes" tab → map zooms to Macon→Savannah corridor (I-75 and I-16).

---

## Scene 3 — COOL CORRIDOR ROUTING (2:30–3:30)

**Visual:** Corridor Map component. Origin: Macon, GA (reefer truck icon, "Packing house pickup"). Destination: Port of Savannah (anchor icon). Two routes render simultaneously:
- **I-75 route** (inland, via Macon→Valdosta→Savannah): thick **red** line.
- **I-16 route** (direct Macon→Savannah): thick **blue** line.

Below the map, a **temperature profile chart** along distance: red curve (97°F avg, peak 102°F) vs blue curve (91°F avg, peak 96°F). Truck marker animates along the blue route.

**Narration (~50s):**
> "The same heat signal drives our logistics. A loaded reefer leaves Macon for the Port of Savannah. The typical routing — down I-75 through inland south Georgia — averages 97 degrees for over three hundred miles.
>
> Our router doesn't optimize for *miles*; it optimizes for **heat exposure**. I-16 runs due east toward the coast — cooler air, shorter run — averaging 91 degrees. Same truck, same cargo, six degrees cooler.
>
> With Q10 spoilage kinetics, that six degrees plus a shorter trip cuts **spoilage risk by more than half** on this load. [counter rolls] And because I-16 is shorter, the reefer burns less fuel: **twelve percent savings per trip**."

**On-screen counters (staggered):**
- `I-75: 318 mi · 5.2h · 97°F avg` (red chip)
- `I-16: 176 mi · 2.8h · 91°F avg` (blue chip)
- `Spoilage risk: −54% this load` (counter rolls)
- `Fuel saved: 12% per trip` (counter rolls)

**Presenter cues:** Point at the red line on "typical routing", then the blue line on "I-16". Let the truck animation run its full ~8s once.

**Transition (3s):** Click "Ops" tab.

---

## Scene 4 — COLD CHAIN DASHBOARD: KPIs (3:30–4:15)

**Visual:** Full dashboard. Top row: **four KPI cards** (delta arrows + sparklines). Middle row: **risk time-series chart** (all fields, 24h) + **harvest urgency timeline** (dots colored by tier) + **GDD tracker** gauge. Right column: `heat_intelligence` report card with `Download PDF report`.

**Narration (~40s):**
> "Here's the operations view — every field, every truck, one screen. Over a single July season with PeachState CoolChain:
>
> **Spoilage risk down 23%** — because we harvest *before* the heat, not after.
> **One hundred eighty thousand dollars saved per season** — less lost product, less wasted fuel.
> **Twelve percent fuel savings** across the fleet — from the cool corridors you just saw.
> **96% of loads on-time at the Port** — pre-cooling slots matched to heat forecasts.
>
> And when a buyer asks 'prove it', one click generates a FortyGuard heat-intelligence report — the same API, now telling a boardroom story."

**On-screen KPI cards:**

| KPI | Value | Delta | Sparkline |
|-----|-------|-------|-----------|
| Spoilage risk | ↓ 23% | −23 pp | descending |
| Season savings | $180K | +$180K vs baseline | steps up |
| Fuel savings | 12% | −12% fuel/season | steps down |
| Port on-time | 96% | +14 pp vs baseline | steps up |

**Secondary metrics row (small):** Carbon reduced **41 t CO₂e** · Fields protected **45** · Loads routed **1,240**.

**Presenter cues:** Read cards top-to-bottom with a finger point. On "prove it", click the PDF button once (opens pre-generated report thumbnail; do NOT wait for a download).

**Transition (3s):** Click "Scale" tab → map zooms out to Athens + Atlanta metro.

---

## Scene 5 — SCALE VISION: COMMUNITY + LAST-MILE (4:15–5:00)

**Visual:** Athens (UGA trial garden + community gardens) and Atlanta (last-mile delivery zone). Small polygons on the same risk scale. Zoom-in reveals a community garden: "ATH-CG-02 · community garden · 1.8 ac · risk 58/100 · harvest window tonight 8 PM". A delivery van icon moves along Atlanta streets with a route strip: "Last-mile loop · 34°F cooler in shade corridors".

**Narration (~35s):**
> "Now shrink the polygons. Same FortyGuard API, ten square miles, Basic plan — that's enough for the whole neighborhood.
>
> The same heat signal that saved a peach orchard in Fort Valley tells an Athens community garden when to pick, and routes an Atlanta delivery van through the coolest last-mile blocks — keeping greens crisp and fresh at the farmers market.
>
> PeachState CoolChain: one temperature signal, from Georgia field to port to front porch. [pause] The API key and demo are on the QR code behind me — go protect your own corner of Georgia tonight."

**Closing visual:** Brand card fades in over the scale map: logo + tagline + QR code + `api.fortyguard.com/v1`.

**Presenter cues:** Slow down. The last 15 seconds are the memory judges keep. End on eye contact, not the screen.

**Hard stop at 4:50.** Do not run over.

---

## Timing Budget Check

| Scene | Allocated | Narrated | Visual actions | Slack |
|-------|-----------|----------|----------------|-------|
| 0 | 30s | 25s | 3 chips | 5s |
| 1 | 60s | 45s | 2 drags + click | 15s |
| 2 | 60s | 50s | SMS type + toasts | 10s |
| 3 | 60s | 50s | truck anim + counters | 10s |
| 4 | 45s | 40s | PDF click | 5s |
| 5 | 45s | 35s | zoom-in + brand card | 10s |
| **Total** | **300s** | **245s** | — | **55s buffer** |

## Rehearsal Checklist

- [ ] Full run-through with all transitions timed (stopwatch)
- [ ] Dry run with **no network** (fixture mode) — entire demo must work offline
- [ ] Dry run with **map tiles blocked** — fallback tiles/static images ready
- [ ] Presenter cues memorized: stat chips order, click points, tab names
- [ ] Ctrl+D next-scene hotkey tested
- [ ] QR code + live-API key slide ready for the closing
- [ ] Backup laptop / pre-recorded Loom of the same demo
- [ ] Verify Fort Valley/Albany/I-75/I-16 coordinates are US/Georgia (API coverage confirmed)
