/**
 * fixtures.ts — typed views over the auto-generated fixture constants.
 *
 * Mirrors `scripts/video_charts/chart_data.py` (single source of truth: JSON).
 * Re-exports the generated constants plus derived helpers the scenes consume.
 */
import {
  HEAT_POINTS_BY_HOUR,
  FIELDS,
  CORRIDOR,
  ALERTS,
  KPIS,
  RISK_DATA,
  CROP_THRESHOLDS,
  CAPTIONS,
  TIMING,
} from "./fixtures.generated";
import type {
  Alert,
  CaptionBlock,
  CorridorRoute,
  FieldSnapshot,
  HeatPoint,
  RiskTier,
  TimingDoc,
} from "./types";

export * from "./types";
export {
  HEAT_POINTS_BY_HOUR,
  FIELDS,
  CORRIDOR,
  ALERTS,
  KPIS,
  RISK_DATA,
  CROP_THRESHOLDS,
  CAPTIONS,
  TIMING,
};
export type { CaptionBlock, TimingDoc };

// ---------------------------------------------------------------------------
// Hours (clock labels)
// ---------------------------------------------------------------------------
export const HOURS: string[] = Object.keys(HEAT_POINTS_BY_HOUR).sort(); // 08:00..17:00
export const HOUR_INDEX: Record<string, number> = Object.fromEntries(HOURS.map((h, i) => [h, i]));

// ---------------------------------------------------------------------------
// Field lookups
// ---------------------------------------------------------------------------
export const FIELDS_BY_ID: Record<string, FieldSnapshot> = Object.fromEntries(
  FIELDS.map((f) => [f.field_id, f]),
);

export function fieldName(fieldId: string): string {
  return FIELDS_BY_ID[fieldId]?.name ?? fieldId;
}

/** GeoJSON FeatureCollection of field polygons for Deck.gl GeoJsonLayer. */
export function fieldGeoJson(
  tierByField?: Record<string, RiskTier>,
): { type: "FeatureCollection"; features: GeoJSON.Feature[] } {
  return {
    type: "FeatureCollection",
    features: FIELDS.map((f) => ({
      type: "Feature",
      properties: {
        id: f.field_id,
        name: f.name,
        crop: f.crop,
        tier: tierByField?.[f.field_id] ?? f.risk.tier,
        risk: tierByField ? undefined : f.risk.score,
      },
      geometry: f.polygon,
    })),
  };
}

// ---------------------------------------------------------------------------
// Heat helpers
// ---------------------------------------------------------------------------
/** Mean canopy °F per field per hour (chart_data.canopy_temp_hourly parity). */
export function fieldHourlyTemps(fieldId: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const hour of HOURS) {
    const acc = HEAT_POINTS_BY_HOUR[hour]
      .filter((p) => p.fieldId === fieldId)
      .map((p) => p.tcmF);
    if (acc.length) {
      out[hour] = Math.round((acc.reduce((a, b) => a + b, 0) / acc.length) * 10) / 10;
    }
  }
  return out;
}

/** Hourly mean canopy temp across all fields (for scene-1 heat curve). */
export function systemHourlyTemps(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const hour of HOURS) {
    const pts = HEAT_POINTS_BY_HOUR[hour];
    out[hour] = Math.round((pts.reduce((a, p) => a + p.tcmF, 0) / pts.length) * 10) / 10;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Corridor
// ---------------------------------------------------------------------------
export const CORRIDOR_ROUTES: CorridorRoute[] = CORRIDOR.routes;
export const CORRIDOR_I16: CorridorRoute = CORRIDOR_ROUTES.find((r) => r.route_id === "I16")!;
export const CORRIDOR_I75: CorridorRoute = CORRIDOR_ROUTES.find((r) => r.route_id === "I75")!;
/** Fixture-verified headline: "I-16 saves 54% spoilage risk, 12% fuel, 142 mi shorter". */
export const CORRIDOR_HEADLINE = CORRIDOR.recommendation;

export function routeLine(route: CorridorRoute): [number, number][] {
  return route.points.map((p) => [p.lon, p.lat]);
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------
export const PV07_ALERT: Alert =
  ALERTS.alerts.find((a) => a.field_id === "PV-07" && a.tier === "critical") ?? ALERTS.alerts[0];
export const ACTIVE_ALERTS: Alert[] = ALERTS.alerts.filter((a) => !a.acknowledged);

// ---------------------------------------------------------------------------
// KPIs
// ---------------------------------------------------------------------------
export const KPI_CARDS = KPIS.kpis;
export const KPI_SECONDARY = KPIS.secondary;

// ---------------------------------------------------------------------------
// Risk / spoilage
// ---------------------------------------------------------------------------
export function fieldSeries(fieldId: string) {
  return RISK_DATA.series.filter((s) => s.field_id === fieldId);
}

/** Q10 spoilage curve for a crop (degree-hours vs hour). */
export function spoilageCurve(crop: string) {
  return RISK_DATA.spoilage.find((s) => s.crop === crop) ?? RISK_DATA.spoilage[0];
}

/** Critical alert fields (tier=critical or urgency ≥ 80) for scene 2. */
export function criticalFields(): { field_id: string; urgency: number; tier: RiskTier }[] {
  return RISK_DATA.harvest_windows
    .filter((w) => w.tier === "critical" || w.urgency >= 80)
    .map((w) => ({ field_id: w.field_id, urgency: w.urgency, tier: w.tier }))
    .sort((a, b) => b.urgency - a.urgency);
}

// ---------------------------------------------------------------------------
// Geospatial bounds (used by utils/camera.ts initial views)
// ---------------------------------------------------------------------------
export function heatPointsBounds(): { minLon: number; minLat: number; maxLon: number; maxLat: number } {
  const all: HeatPoint[] = Object.values(HEAT_POINTS_BY_HOUR).flat();
  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
  for (const p of all) {
    if (p.lon < minLon) minLon = p.lon;
    if (p.lon > maxLon) maxLon = p.lon;
    if (p.lat < minLat) minLat = p.lat;
    if (p.lat > maxLat) maxLat = p.lat;
  }
  return { minLon, minLat, maxLon, maxLat };
}

export function corridorBounds() {
  const pts = CORRIDOR_ROUTES.flatMap((r) => r.points);
  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
  for (const p of pts) {
    if (p.lon < minLon) minLon = p.lon;
    if (p.lon > maxLon) maxLon = p.lon;
    if (p.lat < minLat) minLat = p.lat;
    if (p.lat > maxLat) maxLat = p.lat;
  }
  return { minLon, minLat, maxLon, maxLat };
}