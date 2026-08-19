#!/usr/bin/env python3
"""Day 6 — offline video backup of the demo (Loom-style fallback).

Renders one title/visual card per scene (docs/01_demo_script.md) using only
offline assets (fixture JSON + matplotlib PNGs — zero network), then stitches
them with ffmpeg into an MP4 where each scene plays for its allocated budget
duration. Produces `data/rehearsal/day6_demo_backup.mp4`.

    python scripts/day6_video_backup.py          # build MP4 (needs ffmpeg)
    python scripts/day6_video_backup.py --frames-only   # just the PNG cards

The MP4 is the ultimate fallback for the "audio/video failure" risk row in
docs/06 (§6.1): identical demo numbers, pre-rendered, no live app required.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import data_source as ds  # noqa: E402
from dashboard.components.field_map import map_png_bytes  # noqa: E402

OUT_DIR = ROOT / "data" / "rehearsal" / "frames"
VIDEO_OUT = ROOT / "data" / "rehearsal" / "day6_demo_backup.mp4"
# (scene, duration_s, headline, sub)
SCENES = [
    ("scene_0_hook", 30, "PeachState CoolChain",
     "Georgia Agricultural Thermal Intelligence · $74B · 95°F+ · 98°F canopy"),
    ("scene_1_field_map", 60, "Live Field Map — 15:00 EDT",
     "PV-07 Peach Valley Orchard 7 · 91/100 CRITICAL · 98°F · 3.4h exceedance"),
    ("scene_2_harvest_alert", 60, "Harvest Alert → Auto-SMS",
     "FIELD PV-07 — HARVEST NOW · SMS SENT · Fort Valley Co-op pre-cool 4:30 PM"),
    ("scene_3_corridor", 60, "Cool Corridor Routing",
     "I-16: 176 mi · 91°F · spoilage −54% · fuel −12%"),
    ("scene_4_kpis", 45, "Cold Chain Dashboard",
     "Spoilage ↓23% · $180K saved · Fuel ↓12% · Port on-time 96%"),
    ("scene_5_scale", 45, "Scale Vision",
     "Athens community garden + Atlanta last-mile · one temperature signal"),
]


def _make_card(text: str, sub: str, *, map_png: bytes | None = None) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(16, 9), dpi=110)
    fig.patch.set_facecolor("#0F1B33")
    ax.set_facecolor("#0F1B33")
    ax.axis("off")
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    if map_png is not None:
        import io

        from matplotlib.image import imread

        img = imread(io.BytesIO(map_png))
        ax.imshow(img, extent=[0.4, 9.6, 0.5, 8.5], aspect="equal")
    ax.text(0.6, 8.2, "PeachState CoolChain", fontsize=13, color="#F7B32B",
            ha="left")
    ax.text(0.6, 5.2 if map_png is None else 4.4, text, fontsize=30,
            color="white", fontweight="bold", ha="left", va="center")
    ax.text(0.6, 3.6 if map_png is None else 2.9, sub, fontsize=15,
            color="#B8C4D4", ha="left", va="center", wrap=True)
    ax.text(15.4, 0.4, "api.fortyguard.com/v1", fontsize=11, color="#5b6b84",
            ha="right")
    path = OUT_DIR / f"card_{text.splitlines()[0].replace(' ', '_')}.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames-only", action="store_true",
                    help="only render the PNG cards, skip ffmpeg")
    ap.add_argument(
        "--output", default=str(VIDEO_OUT),
        help=f"MP4 output path (default {VIDEO_OUT})",
    )
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    fields = ds.load_fields()
    heat = ds.load_heat_frames()
    field_map = map_png_bytes(fields, heat["field_tiers"], "15:00",
                              selected_field_id="PV-07")

    cards: list[tuple[Path, int]] = []
    for name, dur, headline, sub in SCENES:
        png = _make_card(
            headline, sub,
            map_png=field_map if name == "scene_1_field_map" else None,
        )
        cards.append((png, dur))

    if args.frames_only:
        print(f"frames -> {OUT_DIR}")
        return 0

    ffmpeg = "/usr/bin/ffmpeg"
    if not Path(ffmpeg).exists():
        print("ffmpeg not found; frames written only", file=sys.stderr)
        return 0

    video_out = Path(args.output)
    video_out.parent.mkdir(parents=True, exist_ok=True)
    # Build the concat filter: each card shown for its budget duration,
    # with a 0.3s crossfade between scenes.
    n = len(cards)
    fade = 0.3
    inputs = []
    for png, dur in cards:
        inputs += ["-loop", "1", "-t", f"{dur + fade}", "-i", str(png)]
    filters = []
    for i in range(n):
        filters.append(
            f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
            f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=24[v{i}]"
        )
    prev = "v0"
    for i in range(1, n):
        # xfade offset = end of the already-merged stream minus the fade, which
        # simplifies to the sum of the base durations of the prior cards.
        offset = sum(cards[j][1] for j in range(i))
        cur = f"vx{i}"
        filters.append(
            f"[{prev}][v{i}]xfade=transition=fade:duration={fade}:"
            f"offset={offset:.2f}[{cur}]"
        )
        prev = cur

    cmd = [ffmpeg, "-y", *inputs, "-filter_complex",
           ";".join(filters), "-map", f"[{prev}]", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", "-r", "24", str(video_out)]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"video -> {video_out} ({video_out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
