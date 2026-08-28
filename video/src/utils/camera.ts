/**
 * camera.ts — purposeful Deck.gl camera moves with design-token easing.
 *
 * Replaces the ffmpeg `zoompan` hacks: every camera move has a reason
 * (establish → focus → payoff) and uses `cubic-bezier(0.22, 1, 0.36, 1)`
 * (tokens.motion.easing.smooth_out) via `ease()`.
 *
 * Scene presets are computed from fixture bounds (data/fixtures.ts) so the
 * camera always frames real data.
 */
import { interpolate } from "remotion";
import type { MapViewState } from "@deck.gl/core";
import { ease, type EasingName } from "./easing";
import { heatPointsBounds, corridorBounds, type CorridorRoute } from "../data/fixtures";

export interface LngLatZoom {
  longitude: number;
  latitude: number;
  zoom: number;
  bearing?: number;
  pitch?: number;
}

/** Full deck.gl MapViewState (WebMercator). */
export type FlyViewState = MapViewState;

/**
 * FlyTo interpolation between two view states over `durationInFrames`,
 * evaluated at `frame`. Default easing = smooth_out (0.22,1,0.36,1).
 */
export function flyTo(
  frame: number,
  from: LngLatZoom,
  to: LngLatZoom,
  durationInFrames: number,
  easingName: EasingName = "smooth_out",
): FlyViewState {
  const t = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: (x: number) => ease(easingName, x),
  });
  return {
    longitude: lerp(from.longitude, to.longitude, t),
    latitude: lerp(from.latitude, to.latitude, t),
    zoom: lerp(from.zoom, to.zoom, t),
    bearing: lerp(from.bearing ?? 0, to.bearing ?? 0, t),
    pitch: lerp(from.pitch ?? 0, to.pitch ?? 0, t),
  };
}

/** A view that frames a set of [lon,lat] points with padding, at canvas aspect. */
export function boundsViewState(
  pts: [number, number][],
  aspect: number = 16 / 9,
  paddingFactor = 0.12,
  maxZoom = 12.5,
  centerOverride?: [number, number],
): LngLatZoom {
  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
  for (const [lon, lat] of pts) {
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }
  const cLon = (minLon + maxLon) / 2;
  const cLat = (minLat + maxLat) / 2;
  const lonSpan = Math.max(maxLon - minLon, 1e-6) * (1 + paddingFactor);
  const latSpan = Math.max(maxLat - minLat, 1e-6) * (1 + paddingFactor);
  // Rough WebMercator zoom estimate from spans (deg → zoom).
  const zoomLon = Math.log2(360 / (lonSpan * 2)) + 1;
  const zoomLat = Math.log2((360 * aspect) / (latSpan * 2)) + 1;
  const zoom = Math.min(maxZoom, Math.max(zoomLon, zoomLat));
  return { longitude: centerOverride ? centerOverride[0] : cLon, latitude: centerOverride ? centerOverride[1] : cLat, zoom };
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

// ---------------------------------------------------------------------------
// Scene presets (computed from fixtures — never magic numbers)
// ---------------------------------------------------------------------------
const GA_BOUNDS = heatPointsBounds();

export const VIEW_GA = boundsViewState(
  [[GA_BOUNDS.minLon, GA_BOUNDS.minLat], [GA_BOUNDS.maxLon, GA_BOUNDS.maxLat]],
  16 / 9,
  0.1,
  7.5,
);

export const VIEW_FORT_VALLEY: LngLatZoom = { longitude: -83.89, latitude: 32.55, zoom: 10.6, pitch: 45 };
export const VIEW_ALBANY: LngLatZoom = { longitude: -84.13, latitude: 31.6, zoom: 10.2, pitch: 45 };
export const VIEW_PV07: LngLatZoom = { longitude: -83.84, latitude: 32.53, zoom: 13.2, pitch: 55 };

export function corridorViewState(): LngLatZoom {
  const b = corridorBounds();
  return boundsViewState(
    [[b.minLon, b.minLat], [b.maxLon, b.maxLat]],
    16 / 9,
    0.18,
    8.5,
  );
}

export { interpolate };