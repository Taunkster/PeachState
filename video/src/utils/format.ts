/**
 * format.ts — number formatting per design-token rules:
 *   "Numbers are always mono + tabular; units always rendered: °F, mi, %, $, lb, t CO₂e."
 */

/** Format a number with a unit, e.g. fmt(98.2, "°F") → "98.2°F". */
export function withUnit(value: number, unit: string, decimals = 0): string {
  const n = decimals > 0 ? value.toFixed(decimals) : Math.round(value).toString();
  return `${n}${unit}`;
}

/** Counter roll value for a target number, e.g. roll(74, frame, 0, 60) → "74". */
export function rollValue(frame: number, target: number, durationFrames = 60, decimals = 0): string {
  const p = Math.min(1, frame / durationFrames);
  // smooth gentle easing on the counter (design-token counter_roll uses "gentle")
  const eased = 1 - (1 - p) ** 3;
  const v = target * eased;
  return decimals > 0 ? v.toFixed(decimals) : Math.round(v).toString();
}

/** Typewriter: first `n` characters of text (40ms/char token default). */
export function typewriter(text: string, frame: number, charsPerSecond = 25): string {
  const n = Math.floor((frame / 60) * charsPerSecond);
  return text.slice(0, Math.max(0, Math.min(text.length, n)));
}

/** HH:MM 12h clock label from an "HH:MM" 24h fixture label, e.g. "15:00" → "3:00 PM EDT". */
export function clockLabel(hour24: string, suffix = " EDT"): string {
  const [h, m] = hour24.split(":").map(Number);
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${ampm}${suffix}`;
}