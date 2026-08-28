/**
 * colors.ts — color helpers shared by every scene (mirror of chart_theme.py).
 *
 * All colors come from `design/design_tokens.json` via theme.ts. Never hard-code
 * a hex in a scene — import from here.
 */
import {
  COLORS,
  HEAT_STOPS,
  HEAT_LO_F,
  HEAT_HI_F,
  HEAT_RAMP_24,
  TIER_COLORS,
  hexToRgb,
  lerpColor,
  rgbToHex,
  type RampStop,
} from "../design/theme";
import type { RiskTier } from "./types";

/**
 * heatColor(f) — canopy temp °F → hex via the design-token heat ramp (80–105°F).
 * Exact port of `chart_theme.heat_color`. Falls back to ramp_smooth_24 for
 * banded rendering (colors.ts exposes both).
 */
export function heatColor(f: number): string {
  if (f <= HEAT_LO_F) return HEAT_STOPS[0].hex;
  if (f >= HEAT_HI_F) return HEAT_STOPS[HEAT_STOPS.length - 1].hex;
  for (let i = 0; i < HEAT_STOPS.length - 1; i++) {
    const f0 = HEAT_STOPS[i].f;
    const f1 = HEAT_STOPS[i + 1].f;
    if (f >= f0 && f <= f1) {
      const t = (f - f0) / (f1 - f0);
      return lerpColor(HEAT_STOPS[i].hex, HEAT_STOPS[i + 1].hex, t);
    }
  }
  return HEAT_STOPS[HEAT_STOPS.length - 1].hex;
}

/** Index into the 24-stop smooth ramp for a °F value (Deck.gl colorRange). */
export function heatRampIndex(f: number): number {
  const t = Math.min(1, Math.max(0, (f - HEAT_LO_F) / (HEAT_HI_F - HEAT_LO_F)));
  return Math.min(HEAT_RAMP_24.length - 1, Math.max(0, Math.round(t * (HEAT_RAMP_24.length - 1))));
}

export function heatRampColor(f: number): string {
  return HEAT_RAMP_24[heatRampIndex(f)];
}

/** Deck.gl aggregation colorRange: 24 stops → [r,g,b] tuples. */
export function heatColorRange(): [number, number, number][] {
  return HEAT_RAMP_24.map((hex) => hexToRgb(hex));
}

export function tierColor(tier: RiskTier | string): string {
  return TIER_COLORS[tier] ?? COLORS.slate;
}

export function tierOpacity(tier: RiskTier): number {
  return { low: 0.16, medium: 0.28, high: 0.42, critical: 0.55 }[tier] ?? 0.16;
}

/** Route color (I16 / I75) via tokens.color.routes. */
export function routeColor(routeId: string): string {
  return routeId.toUpperCase() === "I16" ? COLORS.blue : COLORS.red;
}

export { COLORS, HEAT_STOPS, HEAT_RAMP_24, hexToRgb, lerpColor, rgbToHex };
export type { RampStop };