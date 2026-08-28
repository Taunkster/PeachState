/**
 * types.ts — canonical TypeScript types for PeachState CoolChain video fixtures.
 *
 * These mirror the JSON schema of `data/fixtures/{dashboard,demo}/*.json` and
 * `data/crop_thresholds.json`. The auto-generated module
 * `src/data/fixtures.generated.ts` (built by `npm run fixtures:gen`) is typed
 * against these interfaces.
 */

export type RiskTier = "low" | "medium" | "high" | "critical";

export type Crop = "peach" | "pecan" | "blueberry" | "onion";

export interface LngLat {
  lon: number;
  lat: number;
}

export interface PolygonGeometry {
  type: "Polygon";
  /** GeoJSON ring(s): [ [ [lon, lat], ... ] ] */
  coordinates: number[][][];
}

// ---------------------------------------------------------------------------
// fields_snapshot.json — one record per field (45 total)
// ---------------------------------------------------------------------------
export interface FieldRisk {
  score: number;
  tier: RiskTier;
  canopy_temp_f: number;
  threshold_f: number;
  critical_f: number;
  heat_index_f: number;
  humidity_pct: number;
  exceedance_hours: number;
  persistence_forecast_hours: number;
  components: { temp_score: number; exceedance_score: number; persistence_score: number };
}

export interface FieldHarvest {
  urgency: number;
  window: string;
  gdd_since_bloom: number;
  gdd_target: number;
  gdd_progress_pct: number;
  stress_days: number;
}

export interface FieldSnapshot {
  field_id: string;
  name: string;
  crop: Crop;
  region: string;
  region_label: string;
  area_acres: number;
  packing_house_id: string;
  /** [lat, lon] (note: lat-first, matches fixture) */
  center: [number, number];
  polygon: PolygonGeometry;
  risk: FieldRisk;
  harvest: FieldHarvest;
}

// ---------------------------------------------------------------------------
// heat_frames.json — 10 time steps 08:00–17:00, 720 tiles/hour
// ---------------------------------------------------------------------------
export interface HeatTileFeature {
  type: "Feature";
  properties: {
    hour: string;
    tcm_f: number;
    analytic: string;
    field_id: string;
    tier: RiskTier;
    risk_score: number;
  };
  geometry: PolygonGeometry;
}

export interface HeatFrames {
  frames: Record<string, HeatTileFeature[]>;
  field_tiers: Record<string, Record<string, RiskTier>>;
  field_scores: Record<string, Record<string, number>>;
}

/** Point feed for Deck.gl HeatmapLayer (centroid of a heat tile). */
export interface HeatPoint {
  fieldId: string;
  hour: string;
  lon: number;
  lat: number;
  tcmF: number;
  riskScore: number;
  tier: RiskTier;
}

// ---------------------------------------------------------------------------
// corridor.json (demo) — I-16 vs I-75
// ---------------------------------------------------------------------------
export interface CorridorPoint {
  d_mi: number;
  temp_f: number;
  lat: number;
  lon: number;
}

export interface CorridorRoute {
  route_id: string;
  label: string;
  distance_mi: number;
  avg_temp_f: number;
  peak_temp_f: number;
  heat_exposure: number;
  spoilage_risk_pct: number;
  fuel_gal: number;
  eta_hours: number;
  points: CorridorPoint[];
}

export interface CorridorFixture {
  origin: { name: string; lat: number; lon: number };
  destination: { name: string; lat: number; lon: number };
  recommended: string;
  recommendation: string;
  routes: CorridorRoute[];
}

// ---------------------------------------------------------------------------
// alerts.json — harvest alerts + packing houses
// ---------------------------------------------------------------------------
export interface SmsMessage {
  from: string;
  to: string;
  body: string;
  status: string;
  sent_ts: string;
}

export interface PackingHouse {
  facility_id: string;
  name: string;
  region: string;
  crop: string;
  cold_storage_lb: number;
  precool_capacity_lb_h: number;
}

/** packing_house as it appears on an Alert (subset of PackingHouse). */
export interface AlertPackingHouse {
  facility_id: string;
  name: string;
  precool_slot: string;
  inbound_quantity: string;
  truck_id: string;
  cold_storage_lb: number;
}

export interface Alert {
  field_id: string;
  crop: Crop;
  tier: RiskTier;
  canopy_temp_f: number;
  urgency: number;
  threshold_f: number;
  exceedance_hours: number;
  recommended_action: string;
  ts: string;
  acknowledged: boolean;
  sms: SmsMessage | null;
  packing_house: AlertPackingHouse;
}

export interface AlertsFixture {
  alerts: Alert[];
  packing_houses: PackingHouse[];
}

// ---------------------------------------------------------------------------
// kpis.json — 4 KPI cards
// ---------------------------------------------------------------------------
export interface KpiCard {
  id: string;
  label: string;
  value: string;
  delta: string;
  direction: "up" | "down";
  spark: number[];
  tone: "green" | "peach" | "blue";
}

export interface KpisFixture {
  kpis: KpiCard[];
  secondary: string[];
  detail: Record<string, string>;
}

// ---------------------------------------------------------------------------
// risk_data.json — time series + spoilage Q10 curves + crop radar
// ---------------------------------------------------------------------------
export interface RiskRow {
  field_id: string;
  crop: Crop;
  ts: string;
  risk_score: number;
  tier: RiskTier;
}

export interface SpoilageCurvePoint {
  h: number;
  dh: number;
}

export interface SpoilageCurve {
  crop: Crop;
  alert_f: number;
  tolerance_deg_hours: number;
  curve: SpoilageCurvePoint[];
}

export interface CropRadar {
  crop: Crop;
  temp: number;
  exceedance: number;
  persistence: number;
}

export interface RiskDataFixture {
  series: RiskRow[];
  harvest_windows: {
    field_id: string;
    crop: Crop;
    urgency: number;
    tier: RiskTier;
    window: string;
    gdd_progress_pct: number;
    gdd_since_bloom: number;
    gdd_target: number;
    stress_days: number;
  }[];
  spoilage: SpoilageCurve[];
  crop_radar: CropRadar[];
}

// ---------------------------------------------------------------------------
// crop_thresholds.json — per-crop Q10 / GDD / thresholds
// ---------------------------------------------------------------------------
export interface CropThreshold {
  name: string;
  region: string;
  alert_f: number;
  critical_f: number;
  risk_weights: { temp: number; exceedance: number; persistence: number };
  q10_spoilage: number;
  lethal_temp_f: number;
  tolerance_deg_hours: number;
  canopy_k: number;
  gdd_base_f: number;
  gdd_target_bloom_to_harvest: number;
  notes?: string;
  sources?: string[];
}

export interface CropThresholdsFixture {
  schema_version: number;
  frozen_date: string;
  units: string;
  /** crop key → threshold (canonical keys: peach, pecan, blueberry, vidalia_onion, community). */
  crops: Record<string, CropThreshold>;
}

// ---------------------------------------------------------------------------
// captions.json — narration caption blocks (data/rehearsal/*_captions.json)
// ---------------------------------------------------------------------------
/** Optional word-level timestamp. If absent, word timing is derived by
 *  distributing the block's duration evenly across words (karaoke fallback). */
export interface CaptionWord {
  text: string;
  start_s: number;
  end_s: number;
}

export interface CaptionBlock {
  id: number;
  start_s: number;
  end_s: number;
  text: string;
  /** Pre-wrapped 1–2 display lines (narration aid). Auto-wrapped if missing. */
  lines: string[];
  /** Optional word-level timestamps for karaoke mode. */
  words?: CaptionWord[];
}

// ---------------------------------------------------------------------------
// timing.json — master timing markers (data/rehearsal/*_timing.json)
// ---------------------------------------------------------------------------
export interface SceneTiming {
  id: number;
  name: string;
  start_s: number;
  end_s: number;
  duration_s: number;
  tc: string;
  content?: string | null;
  lower_third?: { title: string; sub: string; tc: string } | null;
  narration_lead_in_s: number;
}

export interface KeyBeat {
  time_s: number;
  label: string;
}

export interface ClicktrackSpec {
  file: string;
  bpm: number;
  beat_s: number;
}

export interface TimingDoc {
  project: string;
  master: {
    duration_s: number;
    fps: number;
    resolution: string;
    transitions: string;
    audio: string;
    clicktrack: ClicktrackSpec;
  };
  scenes: SceneTiming[];
  captions: { id: number; start_s: number; end_s: number; text: string }[];
  /** Derived from `recording_notes` ("land key beats at: 3.0s ($780M), …"). */
  key_beats: KeyBeat[];
  hero_numbers_verified: Record<string, string>;
  recording_notes: string[];
}