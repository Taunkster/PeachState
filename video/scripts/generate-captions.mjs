#!/usr/bin/env node
/**
 * generate-captions.mjs — sidecar caption files (SRT / VTT) from the SAME
 * `captions.json` the burned-in Remotion render uses.
 *
 *   data/rehearsal/peachstate_coolchain_demo_captions.json  (source of truth)
 *     ├── ▶ src/data/fixtures.generated.ts  (CAPTIONS — burned-in, CaptionOverlay)
 *     └── ▶ *.srt / *.vtt                   (sidecar — YouTube / Vimeo)
 *
 * Mirrors the legacy `scripts/assemble_demo_video.py:write_caption_files()`
 * output byte-for-byte so the two pipelines stay interchangeable.
 * Run: npm run captions:gen   (also invoked by the updated assemble script)
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const VIDEO = resolve(HERE, "..");
const REPO = resolve(VIDEO, "..");
const SRC = resolve(REPO, "data", "rehearsal", "peachstate_coolchain_demo_captions.json");
const OUT = resolve(REPO, "data", "rehearsal");

const captions = JSON.parse(readFileSync(SRC, "utf8"));

/** `mm:ss.mmm` (VTT) / `hh:mm:ss,mmm` (SRT) from seconds. */
function ts(seconds, srt = false) {
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

const lines = (c) => (c.lines?.length ? c.lines.slice(0, 2) : [c.text].slice(0, 2));

// SRT
const srt = [];
captions.forEach((c, i) => {
  srt.push(String(i + 1));
  srt.push(`${ts(c.start_s, true)} --> ${ts(c.end_s, true)}`);
  srt.push(...lines(c));
  srt.push("");
});
writeFileSync(resolve(OUT, "peachstate_coolchain_demo_captions.srt"), srt.join("\n"), "utf8");

// VTT
const vtt = ["WEBVTT", ""];
for (const c of captions) {
  vtt.push(`${ts(c.start_s)} --> ${ts(c.end_s)}`);
  vtt.push(...lines(c));
  vtt.push("");
}
writeFileSync(resolve(OUT, "peachstate_coolchain_demo_captions.vtt"), vtt.join("\n"), "utf8");

console.log(`captions:gen — ${captions.length} blocks → peachstate_coolchain_demo_captions.srt/.vtt`);
console.log(`  first:  ${ts(captions[0].start_s)} → ${ts(captions[0].end_s)}  ${captions[0].text.slice(0, 48)}…`);
console.log(`  last:   ${ts(captions[captions.length - 1].start_s)} → ${ts(captions[captions.length - 1].end_s)}  ${captions[captions.length - 1].text.slice(0, 48)}…`);