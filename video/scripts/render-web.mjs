#!/usr/bin/env node
/**
 * render-web.mjs — web version (1280x720 @ 30 fps) of the demo master.
 *
 * Reads the master `out/peachstate_coolchain_demo_with_captions.mp4` (1920x1080
 * @ 60 fps) and produces the web deliverable:
 *
 *   out/peachstate_coolchain_demo_720p.mp4
 *     1280x720 @ 30 fps · H.264 · CRF 18 · yuv420p (tv range)
 *     · silent AAC 48 kHz stereo · +faststart
 *
 * The frame rate is halved 60 → 30 (every other frame kept) so the duration
 * stays exactly 300.000 s with 9000 frames — no dropped/repeated frames.
 *
 * Run: npm run render:720p
 */
import { execFileSync } from "node:child_process";
import { existsSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const OUT_DIR = resolve(ROOT, "out");
const SRC = resolve(OUT_DIR, "peachstate_coolchain_demo_with_captions.mp4");
const OUT = resolve(OUT_DIR, "peachstate_coolchain_demo_720p.mp4");

if (!existsSync(SRC)) {
  console.error(`render:720p — master not found: ${SRC}\n  Run \`npm run render:with-captions\` first.`);
  process.exit(1);
}

console.log(`== render:720p ==`);
console.log(`  input  : ${SRC}`);
console.log(`  output : ${OUT} (1280x720 @ 30fps, CRF 18, yuv420p tv-range)`);

execFileSync(
  "ffmpeg",
  [
    "-y",
    "-i", SRC,
    "-vf",
    "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
    "-c:v", "libx264", "-preset", "slow", "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-color_range", "tv",
    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
    "-r", "30",
    "-c:a", "aac", "-b:a", "128k",
    "-movflags", "+faststart",
    OUT,
  ],
  { stdio: "inherit" },
);

console.log(`\nDONE → ${OUT} (${(statSync(OUT).size / 1e6).toFixed(1)} MB)`);