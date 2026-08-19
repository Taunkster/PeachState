"""Generate Day-5 dashboard fixtures + seed the SQLite store.

Usage:
    .venv/bin/python scripts/gen_dashboard_fixtures.py [--db data/coolchain.db]

Writes:
    data/fixtures/dashboard/*.json     (fields, heat frames, corridor, risk,
                                        alerts, kpis, packing houses, HI report)
Seeds (SQLite WAL, offline):
    fields      45 GA farms from data/ga_fields.geojson
    risk_scores snapshot at 15:00 EDT
    alerts      harvest alerts (acknowledged=0)
    heat_samples/env_samples  a few rows per field for the DB-read paths
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard import fixtures_gen  # noqa: E402
from coolchain.services.persistence import Persistence  # noqa: E402

NOW_TS = "2025-07-15T19:00:00Z"


def seed_db(db_path: Path, fields: list[dict]) -> None:
    pers = Persistence(db_path)
    # Idempotent: clear data tables first (fields use upsert).
    for table in (
        "corridor_segments", "risk_scores", "env_samples", "heat_samples",
        "alerts", "spoilage_events", "reports",
    ):
        with pers._writer_lock:
            pers._writer.execute(f"DELETE FROM {table}")
            pers._writer.commit()

    # fields
    fc = json.loads((ROOT / "data" / "ga_fields.geojson").read_text())
    for feature in fc["features"]:
        pers.upsert_field(feature)

    # risk_scores + heat/env samples
    for f in fields:
        pers.insert_risk_score(
            f["field_id"], NOW_TS, crop=f["crop"], score=f["risk"]["score"],
            tier=f["risk"]["tier"], canopy_temp_f=f["risk"]["canopy_temp_f"],
            components_json=json.dumps(f["risk"]["components"]),
        )
        pers.insert_heat_sample(
            f["field_id"], NOW_TS, analytic_type="tcm",
            temp_c=round((f["risk"]["canopy_temp_f"] - 32.0) * 5.0 / 9.0, 2),
            temp_f=f["risk"]["canopy_temp_f"],
            mean_c=round((f["risk"]["canopy_temp_f"] - 32.0) * 5.0 / 9.0, 2),
            n_cells=16,
        )
        pers.insert_env_sample(
            f["field_id"], NOW_TS,
            lat=f["center"][0], lon=f["center"][1],
            temperature_f=f["risk"]["canopy_temp_f"],
            heat_index_f=f["risk"]["heat_index_f"],
            relative_humidity_percent=f["risk"]["humidity_pct"],
            ghi_wm2=840.0,
        )

    # alerts (harvest) — acknowledged defaults to 0 via the migration
    alerts = fixtures_gen.generate_alerts(fields)["alerts"]
    for a in alerts:
        pers.insert_alert(
            ts=a["ts"], field_id=a["field_id"], alert_type="harvest",
            severity=a["tier"].upper(), message=a["recommended_action"],
        )

    # corridor segments snapshot (one row per route node)
    corridor = fixtures_gen.generate_corridor()
    for route in corridor["routes"]:
        for i, p in enumerate(route["points"]):
            pers.insert_corridor_segment(
                route["route_id"], i, NOW_TS, temp_f=p["temp_f"],
                distance_mi=p["d_mi"],
                exposure_index=route["heat_exposure"],
            )

    print("seeded:", pers.table_counts())
    pers.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Day-5 dashboard fixtures")
    ap.add_argument("--db", default=str(ROOT / "data" / "coolchain.db"))
    args = ap.parse_args()

    written = fixtures_gen.write_all_fixtures()
    for p in written:
        print(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size} bytes)")

    seed_db(Path(args.db), fixtures_gen.generate_fields_snapshot())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())