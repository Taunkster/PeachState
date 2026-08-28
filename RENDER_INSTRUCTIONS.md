# RENDER_INSTRUCTIONS.md — PeachState CoolChain Final Demo Render

How to produce the judge-ready demo video package from the **Remotion** stack
(Employee D, final assembly). The master is rendered by Remotion as PNG frames
and encoded by ffmpeg — no PIL overlay, no matplotlib, no `zoompan`.

## Deliverables (all in `data/rehearsal/`)

| File | Spec |
|---|---|
| `peachstate_coolchain_demo_1080p.mp4` | Master — 1920×1080, **60 fps**, H.264 **CRF 18**, **yuv420p tv-range**, silent AAC, **exactly 18000 frames = 300.000 s** |
| `peachstate_coolchain_demo_720p.mp4` | Web — 1280×720, 30 fps, H.264 CRF 18, yuv420p, silent AAC, 9000 frames = 300.000 s |
| `peachstate_coolchain_demo_captions.srt` | SubRip sidecar (from `captions.json`) |
| `peachstate_coolchain_demo_captions.vtt` | WebVTT sidecar (from `captions.json`) |
| `peachstate_coolchain_demo_captions.json` | **Single source of truth** for burned-in + sidecar captions |
| `peachstate_coolchain_demo_clicktrack.wav` | 150 WPM metronome (0.4 s/beat) + double-beep scene cues for the VO session |
| `peachstate_coolchain_demo_timing.json` | Scene boundaries, TC, narration beats, hero numbers |
| `peachstate_coolchain_demo_THUMBNAIL.jpg` | Frame at t=25 s |

## One-command render

```bash
cd /home/taha/peachstate-coolchain
python3 scripts/assemble_demo_video.py --mode remotion   # DEFAULT mode
```

This runs, in order:

1. `npm run render:with-captions` (in `video/`)
   - Remotion renders the `CoolChainWithCaptions` composition → **PNG frames**
     (18000 @ 1920×1080) in a **chunked** pass (default 6000-frame chunks;
     `PSCC_CHUNK_FRAMES` to tune, `PSCC_SINGLE=1` for one-shot, `PSCC_RENDER_DIR`
     to relocate the frame scratch space).
   - ffmpeg encodes each chunk: H.264, CRF 18, yuv420p, tv-range, bt709, 60 fps.
   - Chunks are concatenated (**stream copy** — no re-encode) and a silent AAC
     48 kHz stereo track is muxed in (`+faststart`).
   - Output: `video/out/peachstate_coolchain_demo_with_captions.mp4` → copied to
     `data/rehearsal/peachstate_coolchain_demo_1080p.mp4`.
2. `npm run render:720p` — ffmpeg scales the master to 1280×720 @ 30 fps
   (CRF 18, yuv420p, tv-range, silent AAC) → `_720p.mp4`.
3. `npm run captions:gen` — regenerates `_captions.srt/.vtt` **from the same
   `captions.json`** the burned-in overlay uses (byte-identical to the legacy
   generator).
4. Thumbnail, `timing.json` (Remotion scene table), clicktrack (150 WPM,
   scene-cue double beeps at 30/90/150/210/255 s).

## Quality gates (all checked by the script)

```
✓ duration        300.000 s ± 0.001 s        (ffprobe)
✓ frame count     18000 / 18000, no drops    (ffprobe nb_frames)
✓ resolution      1920×1080 @ 60/1
✓ pixel format    yuv420p, color_range=tv
✓ CRF 18          set at encode time (not exposed by ffprobe)
✓ audio           silent AAC 48 kHz stereo (VO recorded later against clicktrack)
✓ 720p web        1280×720 @ 30 fps, 9000 frames, 300.000 s
✓ captions        21 blocks, in-range, sequential, frame-synced ± 1 frame
                  (overlay switches at round(start_s·60); sidecars round to ms)
```

Manual re-verification:

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,nb_frames,duration,codec_name,pix_fmt,color_range \
  -of default=noprint_wrappers=1 \
  data/rehearsal/peachstate_coolchain_demo_1080p.mp4
# expect: width=1920 height=1080 r_frame_rate=60/1 nb_frames=18000
#         duration=300.000000 codec_name=h264 pix_fmt=yuv420p color_range=tv
```

## Fallbacks / legacy

- The previous matplotlib + PIL overlay pipeline is preserved:
  `python3 scripts/assemble_demo_video.py --mode legacy`
  (crossfades, PIL captions, chart MP4 side-by-sides). Use it only if the
  Remotion stack is unavailable (`video/node_modules` missing).
- If the WebGL/Deck.gl scenes fail on a headless machine, verify
  `video/remotion.config.ts` uses `angle` (SwiftShader fallback) before
  falling back.

## Changing the video

- Edit scenes/timeline: `video/src/` (Root.tsx scene table, theme.ts SCENES,
  scene components). Then re-run `npm run check` (token parity + hero numbers
  + `tsc --noEmit`) before rendering.
- Edit captions: `data/rehearsal/peachstate_coolchain_demo_captions.json`
  (source of truth) → `npm run fixtures:gen` (embeds as typed `CAPTIONS`) →
  re-render. SRT/VTT are regenerated from the same file.
- Edit timing/clicktrack scene boundaries: `REMOTION_SCENES` in
  `scripts/assemble_demo_video.py`.

## CI note

`npm run check` is the CI gate (33 checks + typecheck). The full render needs
~20–30 min on this machine (headless Chromium at concurrency 4) and ~12 GB of
scratch space for the frame chunks (tmpfs `/tmp` by default).