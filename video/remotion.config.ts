import { Config } from "@remotion/cli/config";

// PeachState CoolChain — Remotion render config (design_tokens canvas + output spec).
//
// Master target: 1920x1080 @ 60fps, H.264, CRF 18, yuv420p (see scripts/encode.mjs).
// Frames render as JPEG sequence (fast, deterministic) then ffmpeg encodes to MP4.

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setConcurrency(4);
Config.setChromiumOpenGlRenderer("angle"); // WebGL for Deck.gl scenes (SwiftShader fallback on headless)
Config.setPixelFormat("yuv420p");
Config.setCodec("h264");
Config.setCrf(18);