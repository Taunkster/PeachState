#!/usr/bin/env node
/**
 * encode.mjs — ffmpeg encode: Remotion PNG/JPEG frame sequence → H.264 MP4.
 *
 * Matches the current assembly spec: 1920x1080 @ 60fps, H.264, CRF 18, yuv420p.
 * Run after `npm run render:frames` (writes out/frames/frame_*.jpeg).
 */
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const FRAMES = resolve(ROOT, "out", "frames");
const OUT = resolve(ROOT, "out", "peachstate_coolchain_demo.mp4");

if (!existsSync(FRAMES) || readdirSync(FRAMES).length === 0) {
  console.error("No frames found in", FRAMES, "— run `npm run render:frames` first.");
  process.exit(1);
}

const args = [
  "-y",
  "-framerate", "60",
  "-start_number", "0",
  "-i", resolve(FRAMES, "element-%05d.jpeg"),
  "-vf", "format=yuv420p", // force limited-range 4:2:0 (JPEG input is full-range)
  "-c:v", "libx264",
  "-preset", "medium",
  "-crf", "18",
  "-pix_fmt", "yuv420p",
  "-color_range", "tv",
  "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
  "-r", "60",
  "-movflags", "+faststart",
  OUT,
];

console.log("ffmpeg", args.join(" "));
execFileSync("ffmpeg", args, { stdio: "inherit" });
console.log("encoded:", OUT);