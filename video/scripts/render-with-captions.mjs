#!/usr/bin/env node
/**
 * render-with-captions.mjs — FULL master render pipeline (Employee D, final assembly).
 *
 * Renders the `CoolChainWithCaptions` composition (burned-in captions) to
 * 18000 PNG frames and encodes them with ffmpeg into the submission master:
 *
 *   out/peachstate_coolchain_demo_with_captions.mp4
 *     1920x1080 @ 60 fps · H.264 · CRF 18 · yuv420p (limited/tv range)
 *     · silent AAC 48 kHz stereo · +faststart
 *     · EXACTLY 18000 frames = 300.000 s
 *
 * Pipeline (per the assembly spec — Remotion frames, ffmpeg encode):
 *
 *   1. Remotion renders the composition as a PNG frame sequence.
 *      The render is CHUNKED so it fits in the available disk space: each
 *      chunk is rendered, encoded and deleted before the next chunk starts.
 *      (A full 18000-frame PNG sequence is ~8–18 GB; chunking keeps peak
 *      usage bounded. Set PSCC_CHUNK_FRAMES to tune, or PSCC_SINGLE=1 to
 *      render everything in one shot on machines with plenty of disk.)
 *   2. Each chunk is encoded to a video-only H.264 MP4 (CRF 18, yuv420p,
 *      tv range) — identical settings per chunk.
 *   3. Chunks are concatenated with a stream copy (no re-encode → no
 *      quality loss, exact frame count preserved).
 *   4. A silent AAC 48 kHz stereo track is muxed in (voiceover is added
 *      later; the clicktrack is provided as a separate WAV sidecar).
 *
 * Run: npm run render:with-captions
 */
import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const OUT_DIR = resolve(ROOT, "out");
const OUT_MP4 = resolve(OUT_DIR, "peachstate_coolchain_demo_with_captions.mp4");

// Composition spec (mirrors src/design/theme.ts + Root.tsx)
const COMP = "CoolChainWithCaptions";
const TOTAL_FRAMES = Number(process.env.PSCC_TOTAL_FRAMES || 18000); // 300.000 s @ 60 fps
const FPS = 60;
const CRF = 18;

// Work directory: use tmpfs (/tmp) by default to keep the big PNG frames off
// the repo disk; override with PSCC_RENDER_DIR for custom placement.
const WORK = resolve(process.env.PSCC_RENDER_DIR || "/tmp/opencode/pscc_render");

// Chunking: default 6000 frames (3 chunks ≈ 100 s each). Auto-shrink when
// free space is tight, or set PSCC_CHUNK_FRAMES explicitly.
const MAX_CHUNK = Number(process.env.PSCC_CHUNK_FRAMES || 6000);
const SINGLE_SHOT = process.env.PSCC_SINGLE === "1";
const EST_BYTES_PER_FRAME = 1_100_000; // measured 0.14–1.08 MB/frame PNG (1920x1080)

function freeBytes(dir) {
  try {
    const df = execFileSync("df", ["-Pk", dir], { encoding: "utf8" });
    const line = df.trim().split("\n").pop();
    const parts = line.split(/\s+/);
    return Number(parts[3]) * 1024; // available KB → bytes
  } catch {
    return 8 * 1024 ** 3; // unknown → assume 8 GB
  }
}

function chunkFrames() {
  if (SINGLE_SHOT) return TOTAL_FRAMES;
  const free = freeBytes(WORK);
  const bySpace = Math.max(500, Math.floor((free * 0.6) / EST_BYTES_PER_FRAME));
  return Math.min(MAX_CHUNK, Math.max(500, bySpace));
}

function run(cmd, desc) {
  console.log(`  · ${desc}`);
  execFileSync(cmd[0], cmd.slice(1), { stdio: "inherit" });
}

function renderChunk(start, end, dir) {
  mkdirSync(dir, { recursive: true });
  run(
    [
      resolve(ROOT, "node_modules", ".bin", "remotion"),
      "render",
      resolve(ROOT, "src", "index.ts"),
      COMP,
      dir,
      "--sequence",
      "--image-format=png",
      `--frames=${start}-${end}`,
      "--concurrency=4",
      "--muted",
      "--log=error",
    ],
    `rendering frames ${start}–${end} (${end - start + 1}) → ${dir}`,
  );
}

function normalizeFrames(dir, n) {
  // Remotion names files by the composition frame number with per-render
  // padding (e.g. element-4500.png). Rename to a uniform element-%05d.png
  // 0-based sequence so ffmpeg's image2 demuxer is happy.
  const files = readdirSync(dir)
    .filter((f) => f.endsWith(".png"))
    .sort((a, b) => Number(a.match(/\d+/)) - Number(b.match(/\d+/)));
  if (files.length !== n) {
    throw new Error(`chunk expected ${n} frames, got ${files.length} in ${dir}`);
  }
  files.forEach((f, i) => {
    renameSync(resolve(dir, f), resolve(dir, `element-${String(i).padStart(5, "0")}.png`));
  });
}

function encodeChunk(dir, n, outMp4) {
  const dur = (n / FPS).toFixed(6);
  run(
    [
      "ffmpeg", "-y",
      "-framerate", String(FPS),
      "-start_number", "0",
      "-i", resolve(dir, "element-%05d.png"),
      "-frames:v", String(n),
      "-vf", "format=yuv420p",
      "-c:v", "libx264", "-preset", "medium", "-crf", String(CRF),
      "-pix_fmt", "yuv420p",
      "-color_range", "tv",
      "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
      "-r", String(FPS),
      outMp4,
    ],
    `encoding chunk (${n} frames, ${dur}s, CRF ${CRF}) → ${outMp4}`,
  );
}

function concatChunks(chunks, outMp4) {
  const list = resolve(WORK, "concat.txt");
  writeFileSync(list, chunks.map((c) => `file '${c.replace(/'/g, "'\\''")}'`).join("\n") + "\n", "utf8");
  run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy", outMp4], `concatenating ${chunks.length} chunks (stream copy) → ${outMp4}`);
}

function muxSilentAudio(videoOnly, outMp4) {
  const dur = (TOTAL_FRAMES / FPS).toFixed(6);
  run(
    [
      "ffmpeg", "-y",
      "-i", videoOnly,
      "-f", "lavfi", "-t", dur, "-i", "anullsrc=r=48000:cl=stereo",
      "-c:v", "copy",
      "-c:a", "aac", "-b:a", "128k",
      "-shortest",
      "-movflags", "+faststart",
      outMp4,
    ],
    `muxing silent AAC track (${dur}s) → ${outMp4}`,
  );
}

// ---------------------------------------------------------------------------
function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  mkdirSync(WORK, { recursive: true });

  const CF = chunkFrames();
  const nChunks = Math.ceil(TOTAL_FRAMES / CF);
  console.log(`== render:with-captions ==`);
  console.log(`  composition : ${COMP} (${TOTAL_FRAMES} frames = ${(TOTAL_FRAMES / FPS).toFixed(3)}s @ ${FPS}fps)`);
  console.log(`  work dir    : ${WORK} (${(freeBytes(WORK) / 1e9).toFixed(1)} GB free)`);
  console.log(`  chunk size  : ${CF} frames × ${nChunks} chunks`);

  const chunkMp4s = [];
  for (let i = 0; i < nChunks; i++) {
    const start = i * CF;
    const end = Math.min(start + CF - 1, TOTAL_FRAMES - 1);
    const n = end - start + 1;
    const dir = resolve(WORK, `chunk_${i}`);
    const mp4 = resolve(WORK, `chunk_${i}.mp4`);
    rmSync(dir, { recursive: true, force: true });
    renderChunk(start, end, dir);
    normalizeFrames(dir, n);
    encodeChunk(dir, n, mp4);
    rmSync(dir, { recursive: true, force: true }); // free disk for next chunk
    chunkMp4s.push(mp4);
  }

  const videoOnly = resolve(WORK, "video_only.mp4");
  concatChunks(chunkMp4s, videoOnly);
  chunkMp4s.forEach((c) => rmSync(c, { force: true }));
  muxSilentAudio(videoOnly, OUT_MP4);
  rmSync(videoOnly, { force: true });

  console.log(`\nDONE → ${OUT_MP4} (${(statSync(OUT_MP4).size / 1e6).toFixed(1)} MB)`);
}

main();