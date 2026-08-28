/**
 * captions.ts — caption parser + timing helpers for the Remotion-native
 * caption system (Employee C).
 *
 * Everything here is derived from the canonical `captions.json` / `timing.json`
 * (typed as `CaptionBlock[]` / `TimingDoc` in `src/data/fixtures.generated.ts`),
 * so burned-in captions, karaoke word timing, the ClickTrack voiceover
 * metronome and the SRT/VTT sidecars all share one source of truth.
 *
 * Time model: caption timestamps are in SECONDS on the 300 s master timeline.
 * Remotion frames = seconds × fps (fps from design tokens, 60).
 */

import type { CaptionBlock, CaptionWord, KeyBeat, TimingDoc } from "../data/types";

// ---------------------------------------------------------------------------
// Frame ⇄ seconds
// ---------------------------------------------------------------------------
export const secondsToFrames = (seconds: number, fps: number): number =>
  Math.round(seconds * fps);

export const framesToSeconds = (frame: number, fps: number): number =>
  frame / fps;

// ---------------------------------------------------------------------------
// Lookup — active caption at a master-timeline frame
// ---------------------------------------------------------------------------
/** Binary-search the caption block active at `seconds` (blocks are sorted,
 *  non-overlapping). Returns null during visual-only gaps. */
export function findCaptionAt(
  captions: CaptionBlock[],
  seconds: number,
): CaptionBlock | null {
  let lo = 0;
  let hi = captions.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const c = captions[mid];
    if (seconds < c.start_s) hi = mid - 1;
    else if (seconds >= c.end_s) lo = mid + 1;
    else return c;
  }
  return null;
}

/** Convenience wrapper for Remotion components: frame → active block. */
export function activeCaption(
  captions: CaptionBlock[],
  frame: number,
  fps: number,
): CaptionBlock | null {
  return findCaptionAt(captions, framesToSeconds(frame, fps));
}

/** Progress through a block (0 before start, 1 after end, eased 0..1 inside). */
export function captionProgress(
  block: CaptionBlock,
  frame: number,
  fps: number,
): number {
  const t = framesToSeconds(frame, fps);
  const dur = block.end_s - block.start_s;
  if (dur <= 0) return t >= block.start_s ? 1 : 0;
  return Math.max(0, Math.min(1, (t - block.start_s) / dur));
}

// ---------------------------------------------------------------------------
// Karaoke — word-level timing
// ---------------------------------------------------------------------------
/**
 * Word timings for a block. Uses explicit `block.words` when the caption JSON
 * carries word-level timestamps; otherwise derives them by distributing the
 * block's duration evenly across whitespace-separated words (deterministic,
 * stable across renders).
 */
export function wordTimings(block: CaptionBlock): CaptionWord[] {
  if (block.words && block.words.length > 0) {
    return block.words;
  }
  const words = block.text.split(/\s+/).filter(Boolean);
  const dur = block.end_s - block.start_s;
  if (words.length === 0) return [];
  const step = dur / words.length;
  return words.map((text, i) => ({
    text,
    start_s: block.start_s + i * step,
    end_s: block.start_s + (i + 1) * step,
  }));
}

/** Index of the word being spoken at `seconds`, or -1 before/after the block. */
export function activeWordIndex(words: CaptionWord[], seconds: number): number {
  if (words.length === 0) return -1;
  let lo = 0;
  let hi = words.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const w = words[mid];
    if (seconds < w.start_s) hi = mid - 1;
    else if (seconds >= w.end_s) lo = mid + 1;
    else return mid;
  }
  return -1;
}

// ---------------------------------------------------------------------------
// Wrapping / ellipsis (max 2 lines, caption-safe)
// ---------------------------------------------------------------------------
/**
 * Greedy word-wrap into at most `maxLines` lines of ≤ `maxChars` characters.
 * Falls back to the pre-wrapped `block.lines` when present (the caption JSON
 * ships 2-line blocks); used when a block has no `lines` field.
 */
export function wrapLines(
  text: string,
  maxLines = 2,
  maxChars = 56,
): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > maxChars && cur) {
      lines.push(cur);
      cur = w;
      if (lines.length === maxLines) break;
    } else {
      cur = (cur ? cur + " " : "") + w;
    }
  }
  if (cur) lines.push(cur);
  return lines.slice(0, maxLines);
}

/** Ellipsize a single line so it fits `maxChars` (used for auto-wrap fallback). */
export function ellipsize(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
}

/**
 * Resolve the display lines for a block: `lines` → wrap → ellipsize → max 2.
 * Curated `block.lines` (from captions.json, already ≤2 lines) are trusted and
 * never ellipsized; only auto-wrapped lines get the ellipsis treatment.
 */
export function captionLines(
  block: CaptionBlock,
  maxLines = 2,
  maxChars = 56,
): string[] {
  if (block.lines?.length) {
    return block.lines.slice(0, maxLines);
  }
  return wrapLines(block.text, maxLines, maxChars).map((l) => ellipsize(l, maxChars));
}

// ---------------------------------------------------------------------------
// Responsive type — design-token "28px (responsive: clamp 24–32px)"
// ---------------------------------------------------------------------------
/** Scale a base px size by canvas width (1920 design width), clamped [min,max]. */
export function responsiveFontSize(
  width: number,
  base = 28,
  min = 24,
  max = 32,
): number {
  const scaled = (width / 1920) * base;
  return Math.max(min, Math.min(max, scaled));
}

// ---------------------------------------------------------------------------
// Sidecar generators — SRT / VTT from the SAME captions.json
// ---------------------------------------------------------------------------
/** `mm:ss.mmm` (VTT) or `hh:mm:ss,mmm` (SRT) timestamp from seconds. */
export function formatTimestamp(seconds: number, srt = false): string {
  const ms = Math.round(seconds * 1000);
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  const r = ms % 1000;
  const frac = srt ? `,${String(r).padStart(3, "0")}` : `.${String(r).padStart(3, "0")}`;
  if (srt) {
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}${frac}`;
  }
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}${frac}`;
}

/** SubRip sidecar from the same caption blocks (YouTube/Vimeo friendly). */
export function buildSrt(captions: CaptionBlock[]): string {
  const out: string[] = [];
  captions.forEach((c, i) => {
    out.push(String(i + 1));
    out.push(`${formatTimestamp(c.start_s, true)} --> ${formatTimestamp(c.end_s, true)}`);
    out.push(...captionLines(c));
    out.push("");
  });
  return out.join("\n");
}

/** WebVTT sidecar from the same caption blocks. */
export function buildVtt(captions: CaptionBlock[]): string {
  const out: string[] = ["WEBVTT", ""];
  for (const c of captions) {
    out.push(`${formatTimestamp(c.start_s)} --> ${formatTimestamp(c.end_s)}`);
    out.push(...captionLines(c));
    out.push("");
  }
  return out.join("\n");
}

// ---------------------------------------------------------------------------
// ClickTrack — visual metronome helpers (150 WPM = 0.4 s/beat)
// ---------------------------------------------------------------------------
export interface BeatState {
  /** Absolute beat index since master start (0-based). */
  beatIndex: number;
  /** Beat number within its bar (1..4). */
  barBeat: number;
  /** True on the downbeat (bar start). */
  isDownbeat: boolean;
  /** 0..1 progress of the current beat (0 = just ticked). */
  phase: number;
}

/** Metronome state at `seconds`, from a 150 WPM clicktrack spec. */
export function beatState(seconds: number, beatS = 0.4): BeatState {
  const beatIndex = Math.floor(seconds / beatS);
  const phase = (seconds - beatIndex * beatS) / beatS;
  return {
    beatIndex,
    barBeat: (beatIndex % 4) + 1,
    isDownbeat: beatIndex % 4 === 0,
    phase: Math.max(0, Math.min(1, phase)),
  };
}

/** True within the 100 ms double-beep window at a scene boundary. */
export function inSceneCue(seconds: number, boundaries: number[]): boolean {
  return boundaries.some(
    (b) => seconds >= b - 0.05 && seconds <= b + 0.25,
  );
}

/** Key beats from the timing doc, filtered to `seconds` ± `window`. */
export function keyBeatNear(
  beats: KeyBeat[],
  seconds: number,
  window = 0.6,
): KeyBeat | null {
  return beats.find((b) => Math.abs(b.time_s - seconds) <= window) ?? null;
}

/** Scene name active at `seconds` (from the timing doc scene table). */
export function sceneAt(
  scenes: TimingDoc["scenes"],
  seconds: number,
): TimingDoc["scenes"][number] | null {
  return (
    scenes.find((s) => seconds >= s.start_s && seconds < s.end_s) ?? null
  );
}