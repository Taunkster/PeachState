/**
 * easing.ts — design-token easing for Remotion.
 *
 * Mirrors `chart_theme.py`'s bezier solver so TS and Python produce identical
 * curves, and exposes ready-to-use Remotion `Easing` functions for
 * `interpolate(..., { easing })`.
 */
import { Easing } from "remotion";
import { EASING_POINTS } from "../design/theme";

export type EasingName = keyof typeof EASING_POINTS; // smooth_out | smooth_in_out | gentle | snap

/** Cubic bezier evaluation (chart_theme._sample_bezier parity). */
export function sampleBezier(p0: number, p1: number, p2: number, p3: number, t: number): number {
  const mt = 1 - t;
  return mt ** 3 * p0 + 3 * mt ** 2 * t * p1 + 3 * mt * t ** 2 * p2 + t ** 3 * p3;
}

/** Solve y at x on a cubic-bezier(x1,y1,x2,y2) (chart_theme._solve_bezier_y parity). */
export function solveBezierY(x1: number, y1: number, x2: number, y2: number, x: number): number {
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 32; i++) {
    const t = (lo + hi) / 2;
    if (sampleBezier(0, x1, x2, 1, t) < x) lo = t;
    else hi = t;
  }
  const t = (lo + hi) / 2;
  return sampleBezier(0, y1, y2, 1, t);
}

/** Evaluate a design-token easing by name at progress t ∈ [0,1]. */
export function ease(name: EasingName, t: number): number {
  const clamped = Math.max(0, Math.min(1, t));
  const [x1, y1, x2, y2] = EASING_POINTS[name];
  return solveBezierY(x1, y1, x2, y2, clamped);
}

/** Remotion Easing function for a design-token name. */
export function easingFromToken(name: EasingName): (t: number) => number {
  const [x1, y1, x2, y2] = EASING_POINTS[name];
  return Easing.bezier(x1, y1, x2, y2);
}

// Convenience aliases — most-used token curves.
export const smoothOut = easingFromToken("smooth_out"); // cubic-bezier(0.22, 1, 0.36, 1) — camera flyTo default
export const smoothInOut = easingFromToken("smooth_in_out"); // cubic-bezier(0.65, 0, 0.35, 1)
export const gentle = easingFromToken("gentle"); // cubic-bezier(0.16, 1, 0.3, 1) — counters
export const snapEase = easingFromToken("snap"); // cubic-bezier(0.7, 0, 0.84, 0) — alert-in

export { Easing };