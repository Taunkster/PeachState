#!/usr/bin/env python3
"""Day 7 — FINAL full rehearsal (task 7.5).

Runs the complete 5-minute demo rehearsal (all six scenes, same timing budgets
as docs/01_demo_script.md) against the FINAL Day-7 code, then writes:

    data/rehearsal/rehearsal_log_day7_final.json   (automated timing evidence)
    data/rehearsal/day7_final_demo.mp4             (Loom-ready video backup)

Exit code is non-zero if any scene exceeds its budget or the total exceeds
300 s (i.e. the demo is NOT judge-ready).

    python scripts/day7_final_rehearsal.py          # final evidence run
    python scripts/day7_final_rehearsal.py --no-video   # skip MP4 build
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FINAL_LOG = ROOT / "data" / "rehearsal" / "rehearsal_log_day7_final.json"
FINAL_VIDEO = ROOT / "data" / "rehearsal" / "day7_final_demo.mp4"
DEMO_BUDGET_S = 300.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-video", action="store_true",
                    help="skip the MP4 video backup build")
    args = ap.parse_args()

    # 1) Full rehearsal (2x) via the Day-6 rehearsal engine.
    from scripts.day6_rehearsal import SCENE_BUDGET, TOTAL_BUDGET, _rehearse

    runs = [_rehearse(core_only=False) for _ in range(2)]
    log = {
        "kind": "day7_final_rehearsal_log",
        "iterations": 2,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "demo_budget_s": DEMO_BUDGET_S,
        "scene_budgets_s": SCENE_BUDGET,
        "runs": runs,
    }
    FINAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    FINAL_LOG.write_text(json.dumps(log, indent=2))
    print(f"rehearsal log -> {FINAL_LOG}")

    # 2) Report + pass/fail.
    worst_total = max(r["total_ms"] / 1000.0 for r in runs)
    worst_scene = max(
        s["elapsed_ms"] / 1000.0
        for r in runs for s in r["segments"]
    )
    all_under = all(
        r["all_scenes_under_budget"] and r["all_transitions_under_2s"]
        for r in runs
    )
    for i, r in enumerate(runs, 1):
        print(
            f"run {i}: total {r['total_ms'] / 1000.0:.3f}s (budget "
            f"{r['total_budget_s']:.0f}s) · worst scene "
            f"{r['worst_scene_s']:.3f}s "
            f"· {'PASS' if r['all_scenes_under_budget'] else 'FAIL'}"
        )
    print(f"FINAL: total {worst_total:.3f}s / {DEMO_BUDGET_S:.0f}s budget · "
          f"worst scene {worst_scene:.3f}s · "
          f"{'PASS — judge-ready' if all_under and worst_total < DEMO_BUDGET_S else 'FAIL'}")

    # 3) Video backup (Loom-ready MP4).
    if not args.no_video:
        from scripts.day6_video_backup import main as video_main

        sys.argv = ["day6_video_backup.py", "--output", str(FINAL_VIDEO)]
        video_main()

    return 0 if (all_under and worst_total < DEMO_BUDGET_S) else 1


if __name__ == "__main__":
    sys.exit(main())
