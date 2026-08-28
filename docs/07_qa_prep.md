# 07 — Judge Q&A Prep (19 Anticipated Questions)

Each question gets a **one-sentence answer** (for the timed Q&A) followed by a
**one-paragraph answer** (for the deeper follow-up). Numbers in bold match the
presenter one-sheet (`docs/08`) so the numbers you say in the demo are the
same numbers you defend here.

---

## 1. How do you estimate canopy temp from 2m air temp?

**1-sentence:** We take FortyGuard's hyperlocal 2m air temperature and load it
with solar irradiance (GHI) while subtracting VPD-driven evaporative cooling,
then cap it at crop-specific ceilings.

**1-paragraph:** The canopy sits at roughly the same height as a 2m
measurement, so air temperature is the right *primary* signal — but it is not
the whole story. Our `canopy_temp_f` applies a physics-informed adjustment:
GHI loading raises effective fruit temperature during full sun (peaks mid-July
afternoon), VPD cooling lowers it when humidity is low and the plant transpires
freely, and the result is capped by crop ceilings so we never overshoot
unrealistically. In GA's humid July the VPD term is small and the GHI term
dominates, which is exactly why a shaded 95°F air reading still produces a
98°F canopy at PV-07. The full formula lives in `coolchain/domain/canopy.py`
and is unit-tested against the demo's hero values (98.2°F at 15:00 EDT).

## 2. Is the risk score calibrated?

**1-sentence:** Yes — thresholds are per-crop values from UGA Extension heat
guides (peach 95°F, pecan 95°F, blueberry 90°F, onion 85°F) and the component
weights live in a versioned config file, not in code.

**1-paragraph:** The 0–100 risk score is a weighted combination of three
standardized signals: current canopy temperature relative to the crop's
threshold, hours of exceedance above that threshold, and forecast persistence.
Each crop's threshold comes from UGA Extension publications and the weights
are declared in `data/crop_thresholds.json` so an agronomist can retune them
without a code change. The tier bands (Low → Critical) are calibrated so that
CRITICAL is a "harvest now" trigger, which is a decision aid rather than an
absolute physical measurement — we'd harden it with in-canopy sensors in a
production pilot. As a ranking and alerting signal it has been validated
against our historical heatmap + USDA loss-report backtest (question 17).

## 3. Why is I-16 cooler than I-75?

**1-sentence:** I-16 runs 142 miles shorter toward the coast where the Atlantic
marine layer moderates the afternoon peak, while I-75 cuts inland through
south Georgia's hottest asphalt.

**1-paragraph:** The corridor router compares two real OSM geometries from
Macon to the Port of Savannah. I-75 is 318 miles through inland south Georgia
— the hottest part of the state in July, with open asphalt and less moisture
moderation — averaging 97.1°F. I-16 is 176 miles running due east, staying
near the Savannah River basin where coastal Atlantic air keeps the afternoon
peak down, averaging 91.3°F. Six degrees and 142 fewer miles is not a rounding
error: at Q10 kinetics that combination drives a −54% spoilage-risk reduction
for this load and −12% fuel.

## 4. Where does the $180K come from?

**1-sentence:** $180K is a season-long modeled saving from a 23% spoilage
reduction applied to the $780M combined GA peach/pecan/blueberry/onion value
that moves through our 45 tracked fields.

**1-paragraph:** The math is deliberately conservative. Georgia's peach,
pecan, blueberry, and Vidalia onion production is worth roughly $780M at
farmgate for the value chains we model; our harvest-timing interventions
(harvest before the heat spike) plus cool-corridor routing cut modeled
spoilage by 23% across the fleet. 23% × $780M × a spoilage-fraction baseline
from USDA post-harvest loss studies gives approximately $180K of annualized
margin saved — and that is *before* the fuel saving (12% per I-16 trip) and
the Port rejection reduction (96% vs 82% on-time baseline). All three buckets
are in `dashboard/fixtures_gen.py` so the number is auditable, not hand-waved.

## 5. What if the API goes down?

**1-sentence:** The demo runs in FIXTURES mode by default — zero network
dependency — and HYBRID mode has an 8-second live timeout with automatic
fallback to the recorded fixtures.

**1-paragraph:** This was a hard design requirement from day one. Every screen
the judge sees reads from `data/fixtures/` (JSON + SQLite), which are the
*actual* FortyGuard API responses recorded on Day 6 — identical bytes,
identical numbers, no network. If we do run live, `DATA_SOURCE=hybrid` gives
the SDK an 8-second hard timeout; on any error the app silently serves the
fixture cache and the `GET /health` endpoint reports
`{status, data_source, last_live_ok, cache_age_s}` so an operator can see the
degradation. The demo simply cannot break because a venue Wi-Fi drops.

## 6. How do you handle the 10 mi² limit?

**1-sentence:** We run a Premium key at 50 mi², tile large corridors into
sub-area requests, and route only the env waypoints that matter.

**1-paragraph:** The plan contract is enforced client-side in the SDK. With a
Basic key we split the Fort Valley 20 mi² cluster into two 10 mi² requests and
limit env_params to 3 per call; with a Premium key we get 50 mi² and all env
params in one call. For the I-16/I-75 corridor we tile the band into smaller
AOIs and sample env_params at the packing houses and waypoint nodes rather
than every mile. The capability matrix lives in `fortyguard_sdk/plans.py`, so
the same code degrades gracefully between plans and hot-swaps on key upgrade.

## 7. Is this real-time?

**1-sentence:** The agent cadence is 15 minutes, the heatmap carries up to a
12-hour lag by design, and env_params (heat index, humidity, GHI) are polled
live.

**1-paragraph:** Honest answer: the *decisions* run on a 15-minute cadence
(the monitor orchestrator in `coolchain/services/monitor.py`), which is the
right frequency for a harvest window measured in hours. The thermal heatmap is
an analytic product with up to a 12-hour measurement lag — that is fine because
we use it for *spatial* pattern (which corridor is cooler) rather than the
minute-level forecast. Live `env_params` are polled on the 15-minute loop, so
the heat-index and humidity readouts the judge sees are effectively current.
We deliberately never claim sub-minute real-time.

## 8. What about soil moisture?

**1-sentence:** We model soil-moisture stress with a FAO-56 Hargreaves
reference-evapotranspiration bucket — decision support, not telemetry.

**1-paragraph:** We do not pretend to be a soil sensor company. The domain
layer (`coolchain/domain/canopy.py`) carries a simple one-bucket soil water
balance using FAO-56 Hargreaves ET₀ from the temperature data we already have,
so a multi-day drought stress can push the canopy risk score up even when air
temperature is moderate. It is explicitly a decision-support input, not a
telemetry claim: in production we would ingest grower irrigation records or
optional soil probes rather than invent data we don't have.

## 9. Can this scale to all of Georgia?

**1-sentence:** Yes — the architecture is cluster-batched (45 fields today,
1,000+ with the same code path) because we make one API call per farm cluster,
not per field.

**1-paragraph:** Georgia has ~42,000 farms but the thermal signal is regional.
We geo-cluster nearby fields (`coolchain/services/clustering.py`) so one
heatmap request covers a whole cluster, and the local spatial join assigns
each field its risk. The demo tracks 45 fields across 5 regions in 4 clusters;
statewide coverage is a few hundred cluster calls on the same code path. The
hard costs (API credits, storage) grow sub-linearly with field count — the
architecture scales, not just the demo.

## 10. Why not just use the NWS forecast?

**1-sentence:** The NWS gives county-level grid forecasts; FortyGuard gives
hyperlocal 2m temperature at field and truck level — which is the scale a
harvest decision actually needs.

**1-paragraph:** A harvest or routing decision made on a county-average
forecast is made on someone else's weather. FortyGuard's temperature API
resolves the 2m air temperature at our field polygon and route-segment scale,
which is where the 6°F I-16-vs-I-75 difference and the 98°F canopy at PV-07
actually live. NWS is a great free sanity check and we can fuse it as a second
source, but it cannot drive a per-farm harvest command the way a field-level
temperature API can. That is precisely why the FortyGuard data is the core of
the pipeline rather than an enhancement.

## 11. How does the spoilage model work?

**1-sentence:** Q10 degree-hour kinetics (decay scales exponentially with
temperature) plus a lethal heat term, parameterized from USDA H66 cold-chain
kinetics.

**1-paragraph:** Spoilage is modeled as accumulated degree-hours above each
crop's transit threshold, where the rate constant doubles every 10°C
(a Q10 of ~2), capped by a lethal-temperature term for extreme excursions.
The parameters come from USDA Agriculture Handbook 66 cold-storage kinetics
for stone fruit, pecans, blueberries, and onions, and live in
`coolchain/domain/spoilage.py` with unit tests. The router sums degree-hours
along each route, which is how six degrees cooler + 142 fewer miles becomes a
−54% spoilage-risk reduction — the number is a kinetic calculation, not a
marketing estimate.

## 12. What's the business model?

**1-sentence:** SaaS for packers, shippers, and insurers — a seat-based
dashboard plus API credit consumption for the FortyGuard data.

**1-paragraph:** We sell the decision, not the raw feed: packers and grower
co-ops pay per season per field for harvest-timing alerts, shippers (reefer
fleets) pay per route for the cool-corridor recommendation and spoilage
forecast, and insurers pay for the heat-intelligence PDF as underwriting
evidence of loss mitigation. Underneath, each customer consumes FortyGuard API
credits through our billing — so revenue has a direct COGS in API usage, and
the same platform sells to three segments with the same code. Georgia's
packing-house concentration (Fort Valley, Albany, Vidalia) gives us a dense
initial beachhead.

## 13. How do you handle grower adoption?

**1-sentence:** We meet growers where they are — SMS alerts on their existing
phone, no app install, integrated with the packing-house workflow they already
run.

**1-paragraph:** The harvest command goes out as an SMS to the foreman in
plain language ("FIELD PV-07 — HARVEST NOW · 98°F · 3.4h above threshold"), and
the acknowledgement flows back to the packing house so pre-cool slots and
trucks are coordinated on the phone they already carry. No new hardware, no
app onboarding, no dashboard requirement for the field crew — the dashboard is
for the manager and the buyer. The demo's Scene 2 is exactly that flow:
alert → SMS → packing-house pre-cool slot → reefer dispatch.

## 14. What about pecans — aren't they heat tolerant?

**1-sentence:** Pecan trees tolerate heat, but kernel-fill stage is moisture-
and temperature-sensitive, so pecan risk is driven by moisture co-stress plus
canopy temperature during the July–August fill window.

**1-paragraph:** Heat tolerance applies to the mature tree, not to the crop in
the kernel-fill stage — that is the window when heat plus drought stress
shrinks nut quality and yield. Our pecan risk score therefore couples canopy
temperature with the FAO-56 soil-moisture bucket (question 8): a 95°F canopy
in a dry field is HIGH, while the same canopy after rain is MEDIUM. Albany
pecan orchards in the demo (AL-04 etc.) show exactly this co-driver behavior,
and the spoilage curve for pecans uses their own H66 kinetics parameters.

## 15. Can this work for other states?

**1-sentence:** The FortyGuard API covers the US, so the same architecture
works anywhere — we just swap crop thresholds and packing-house coordinates.

**1-paragraph:** Everything Georgia-specific is data, not code: crop
thresholds, Q10 parameters, packing houses, and corridor geometry are all in
config and fixtures. The pipeline (heatmap → risk → harvest → route → report)
is state-agnostic. Florida citrus, California stone fruit, Washington apples
would each be a new thresholds file plus a packing-house list and the same
demo. The GA-specific value — humid-heat July logistics — is our strongest
story, so other states are a product roadmap, not a rewrite.

## 16. What's the Premium vs Basic difference?

**1-sentence:** Basic is 10 mi² heatmaps with 3 env params per call; Premium is
50 mi², all env params, plus satellite, streetview, and heat-intelligence
reports.

**1-paragraph:** The plan matrix is encoded in `fortyguard_sdk/plans.py` and
enforced client-side so a misconfigured request fails fast instead of burning
quota. For the demo, Premium is the differentiator: the 20 mi² Fort Valley
cluster fits in one Premium call (two Basic calls otherwise), the corridor
comparison uses all env params, and the buyer-facing heat-intelligence PDF
(Scene 4) is a Premium feature. The design degrades gracefully to Basic —
which is itself a selling point: a customer can start Basic on one farm and
upgrade without a code change.

## 17. How do you validate the model?

**1-sentence:** We backtest the risk and spoilage pipeline against historical
heatmaps and USDA crop-loss reports, and the hero numbers are pinned by tests.

**1-paragraph:** Three layers: (1) unit tests pin the physics — canopy formula,
Q10 spoilage, corridor router all have exact-value tests (PV-07 87@08:00 →
91@15:00, 54% spoilage delta, 3.4h exceedance); (2) our Day-6 fixture set is
byte-identical live API output, so what the judge sees is what the API
returned; (3) season-level backtesting against historical heatmaps and USDA
RMA loss data calibrates the 23% spoilage-reduction claim to published ranges
for pre-cooling plus rapid harvest. We are honest that in-canopy sensor
validation is the production pilot's job — that is step one of "what's next".

## 18. What's next?

**1-sentence:** IoT soil sensors for ground truth, ML yield forecasting on top
of the heat history, and carbon-credit integration for growers who cool-chain
correctly.

**1-paragraph:** The roadmap is sequenced to add ground truth first: a pilot
with Fort Valley co-op deploying a handful of in-canopy sensors to calibrate
the canopy model against reality. Then the accumulated per-field heat history
becomes training data for an ML yield-and-quality forecast (the current risk
score is the feature vector). Finally, because reduced spoilage is reduced
food-miles and waste, we can issue verifiable carbon/sustainability credits —
a revenue line that also strengthens the insurer story. All three reuse the
existing pipeline; none requires a new architecture.

## 19. Who's the customer?

**1-sentence:** Packers and grower co-ops first (Lane Southern Orchards,
Pearson Farm), shippers (Lineage Logistics), and insurers (USDA RMA-backed
programs).

**1-paragraph:** Three buying segments, one platform. Packers — Lane Southern
Orchards in Fort Valley and Pearson Farm — pay for the harvest-timing alerts
because spoilage is direct margin. Shippers such as Lineage (who operate
temperature-controlled warehousing and reefer logistics through the Port of
Savannah) pay for the corridor recommendation and in-transit spoilage
forecast. Insurers and USDA Risk Management Agency-backed programs pay for the
heat-intelligence PDF as loss-mitigation documentation. Each segment sees the
same FortyGuard data through the lens that matters to them: field, truck, or
premium report.

---

## Delivery notes

- **If you only have time for one number in an answer, use the bolded one.**
- Every answer is backed by a fixture, a test, or a config file — point to the
  artifact when challenged ("the thresholds are in `data/crop_thresholds.json`").
- Do not invent numbers. If a judge asks something outside these 19, defer with
  "we can verify that off the recorded fixture set" rather than estimating.