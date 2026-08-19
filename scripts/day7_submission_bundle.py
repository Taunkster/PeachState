#!/usr/bin/env python3
"""Day 7 — build the hackathon submission bundle (task 7.5).

Assembles everything a judge needs to run + review PeachState CoolChain into
``data/submission/peachstate-coolchain-submission.zip``:

    README.md                     problem / solution / architecture / team
    pyproject.toml                + requirements-lock.txt
    docs/                         01 demo script, 07 Q&A, 08 one-sheet, 06, 09, 10
    fortyguard_sdk/ coolchain/    source (no .env, no secrets)
    dashboard/                    Streamlit app + theme + components
    data/fixtures/day6/           recorded live API fixtures (judging)
    data/fixtures/heat_intelligence_fort_valley.pdf
    data/rehearsal/day7_final_demo.mp4   final 5-min demo video

Secrets (.env) and the local DB are excluded by construction. A MANIFEST.json
records sha256 hashes so the bundle is verifiable.

    python scripts/day7_submission_bundle.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "submission"
ZIP_OUT = OUT_DIR / "peachstate-coolchain-submission.zip"
MANIFEST = OUT_DIR / "MANIFEST.json"

# Everything that ships in the bundle.
INCLUDE = [
    "README.md",
    "pyproject.toml",
    "requirements-lock.txt",
    ".env.example",
    "docs",
    "fortyguard_sdk",
    "coolchain",
    "dashboard",
    "scripts",
    "tests",
    "data/fixtures/day6",
    "data/fixtures/heat_intelligence_fort_valley.pdf",
    "data/rehearsal/day7_final_demo.mp4",
    "data/fixtures/README.md",
]

# Never ship these, even if they appear under an INCLUDE dir.
EXCLUDE_PARTS = (
    "__pycache__",
    ".pytest_cache",
    "*.egg-info",
    ".env",
    "coolchain.db",
    "*.log",
    ".git",
)


def _excluded(rel: str) -> bool:
    for part in EXCLUDE_PARTS:
        if part.startswith("*"):
            if Path(rel).suffix == part[1:] or Path(rel).name == part[1:]:
                return True
        elif part in rel.split("/"):
            return True
    return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ZIP_OUT.unlink(missing_ok=True)

    git_url = ""
    try:
        git_url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        pass

    manifest_entries: list[dict] = []
    with zipfile.ZipFile(ZIP_OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in INCLUDE:
            src = ROOT / item
            if not src.exists():
                print(f"WARN missing: {item}")
                continue
            if src.is_dir():
                for p in sorted(src.rglob("*")):
                    rel = p.relative_to(ROOT).as_posix()
                    if _excluded(rel) or p.is_dir():
                        continue
                    zf.write(p, rel)
                    manifest_entries.append(
                        {"path": rel, "sha256": _sha256(p), "bytes": p.stat().st_size}
                    )
            else:
                rel = src.relative_to(ROOT).as_posix()
                if _excluded(rel):
                    continue
                zf.write(src, rel)
                manifest_entries.append(
                    {"path": rel, "sha256": _sha256(src), "bytes": src.stat().st_size}
                )

    manifest = {
        "bundle": "peachstate-coolchain-submission.zip",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_repo_url": git_url or "(github repo url to be added at upload)",
        "demo_video": "data/rehearsal/day7_final_demo.mp4 (300s)",
        "files": manifest_entries,
        "count": len(manifest_entries),
        "note": "No .env / secrets included. DATA_SOURCE=fixtures default — "
                "runs fully offline.",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2))

    size_kb = ZIP_OUT.stat().st_size // 1024
    print(f"bundle -> {ZIP_OUT} ({size_kb} KB, {len(manifest_entries)} files)")
    print(f"manifest -> {MANIFEST}")
    if git_url:
        print(f"repo url -> {git_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
