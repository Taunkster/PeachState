"""PeachState CoolChain services — SQLite persistence (WAL mode).

Day 2: single-writer / concurrent-reader SQLite store for the demo and the
monitoring pipelines.

Design:
    - ``journal_mode=WAL`` — one writer connection (serialized by a lock)
      while the dashboard/readers open their own read-only connections.
    - ``PRAGMA busy_timeout`` so writers never trip on a locked reader.
    - raw GeoJSON for heat tiles / field polygons is cached on disk (either
      inline ``TEXT`` columns or on-disk files referenced by path).

Tables (see :data:`SCHEMA_SQL`):
    fields, heat_samples, corridor_segments, env_samples, risk_scores,
    spoilage_events, alerts, reports

Indexes:
    (field_id, ts) on heat_samples / env_samples / risk_scores /
    spoilage_events / alerts,
    (route_id, segment_id, ts) on corridor_segments.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fields (
    id                      TEXT PRIMARY KEY,
    name                    TEXT,
    crop                    TEXT,
    region                  TEXT,
    geometry_json           TEXT,          -- GeoJSON Polygon (EPSG:4326)
    area_acres              REAL,
    packing_house_id        TEXT,
    gdd_base_f              REAL,
    stage_sensitivity_window TEXT,
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT
);

CREATE TABLE IF NOT EXISTS heat_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id        TEXT NOT NULL,
    ts              TEXT NOT NULL,
    analytic_type   TEXT,
    temp_c          REAL,
    temp_f          REAL,
    min_c           REAL,
    max_c           REAL,
    mean_c          REAL,
    n_cells         INTEGER,
    raw_geojson     TEXT,                  -- raw tile GeoJSON cached on disk
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_heat_samples_field_ts
    ON heat_samples(field_id, ts);

CREATE TABLE IF NOT EXISTS corridor_segments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id        TEXT NOT NULL,
    segment_id      INTEGER NOT NULL,
    ts              TEXT NOT NULL,
    temp_f          REAL,
    exposure_index  REAL,
    distance_mi     REAL,
    geometry_json   TEXT,                  -- tile GeoJSON
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_corridor_segments_route_ts
    ON corridor_segments(route_id, segment_id, ts);

CREATE TABLE IF NOT EXISTS env_samples (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id                TEXT NOT NULL,
    lat                     REAL,
    lon                     REAL,
    ts                      TEXT NOT NULL,
    temperature_f           REAL,
    heat_index_f            REAL,
    wet_bulb_f              REAL,
    relative_humidity_percent REAL,
    ghi_wm2                 REAL,
    aqi_idx                 REAL,
    precip_mm               REAL,
    raw_json                TEXT,
    created_at              TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_env_samples_field_ts
    ON env_samples(field_id, ts);

CREATE TABLE IF NOT EXISTS risk_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id        TEXT NOT NULL,
    ts              TEXT NOT NULL,
    crop            TEXT,
    score           REAL,                  -- 0..100 canopy risk
    tier            TEXT,                  -- LOW/MEDIUM/HIGH/CRITICAL
    canopy_temp_f   REAL,
    worker_wbgt_f   REAL,
    components_json TEXT,                  -- temp/exceedance/persistence breakdown
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_risk_scores_field_ts
    ON risk_scores(field_id, ts);

CREATE TABLE IF NOT EXISTS spoilage_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id        TEXT NOT NULL,
    crop            TEXT,
    ts              TEXT NOT NULL,
    degree_hours_f  REAL,
    spoilage_risk   REAL,                  -- 0..1 probability
    q10             REAL,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_spoilage_field_ts
    ON spoilage_events(field_id, ts);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id    TEXT,
    alert_type  TEXT,
    severity    TEXT,                      -- LOW/MEDIUM/HIGH/CRITICAL
    message     TEXT,
    ts          TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_alerts_field_ts
    ON alerts(field_id, ts);

CREATE TABLE IF NOT EXISTS reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type     TEXT,                  -- heat_intelligence / digest / spoilage
    field_id        TEXT,
    path            TEXT,                  -- local PDF/JSON path
    download_link   TEXT,
    metadata_json   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "coolchain.db"


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class Persistence:
    """WAL-mode SQLite store: one writer, many concurrent readers."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or _DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._writer_lock = threading.RLock()
        self._writer: sqlite3.Connection | None = None
        # SQLite connections cannot be shared across threads by default; the
        # dashboard reads through fresh read-only connections (check_same_thread=False
        # so a connection may be used from the reader thread that created it).
        self._init_writer()
        self.init_schema()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    def _init_writer(self) -> None:
        # check_same_thread=False: the monitor API (`fg serve`) may call the
        # writer from the ASGI event-loop thread; all writes are serialized
        # by self._writer_lock so the connection stays safe.
        conn = sqlite3.connect(str(self.db_path), timeout=30.0,
                               check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        self._writer = conn

    def init_schema(self) -> None:
        with self._writer_lock:
            self._writer.executescript(_SCHEMA_SQL)
            self._writer.commit()

    def close(self) -> None:
        with self._writer_lock:
            if self._writer is not None:
                self._writer.close()
                self._writer = None

    def reader(self) -> sqlite3.Connection:
        """A fresh read-only connection for concurrent dashboard readers."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Writer helpers
    # ------------------------------------------------------------------
    def _execute(self, sql: str, params: tuple | dict) -> int:
        with self._writer_lock:
            cur = self._writer.execute(sql, params)
            self._writer.commit()
            return cur.lastrowid

    def _executemany(self, sql: str, rows: Iterable[tuple]) -> None:
        with self._writer_lock:
            self._writer.executemany(sql, rows)
            self._writer.commit()

    # ------------------------------------------------------------------
    # fields
    # ------------------------------------------------------------------
    def upsert_field(self, feature: dict[str, Any]) -> None:
        props = feature.get("properties", {}) or {}
        fid = feature.get("id") or props.get("id")
        if not fid:
            raise ValueError("field feature requires an id")
        geom = feature.get("geometry")
        with self._writer_lock:
            self._writer.execute(
                """
                INSERT INTO fields (id, name, crop, region, geometry_json,
                                    area_acres, packing_house_id, gdd_base_f,
                                    stage_sensitivity_window, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, crop=excluded.crop, region=excluded.region,
                    geometry_json=excluded.geometry_json, area_acres=excluded.area_acres,
                    packing_house_id=excluded.packing_house_id,
                    gdd_base_f=excluded.gdd_base_f,
                    stage_sensitivity_window=excluded.stage_sensitivity_window,
                    updated_at=excluded.updated_at
                """,
                (
                    fid,
                    props.get("name"),
                    props.get("crop"),
                    props.get("region"),
                    json.dumps(geom) if geom else None,
                    props.get("area_acres"),
                    props.get("packing_house_id"),
                    props.get("gdd_base_f"),
                    props.get("stage_sensitivity_window"),
                    _now(),
                ),
            )
            self._writer.commit()

    def load_fields(self) -> list[sqlite3.Row]:
        conn = self.reader()
        try:
            return conn.execute(
                "SELECT * FROM fields ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # heat_samples
    # ------------------------------------------------------------------
    def insert_heat_sample(
        self,
        field_id: str,
        ts: str,
        *,
        analytic_type: str | None = None,
        temp_c: float | None = None,
        temp_f: float | None = None,
        min_c: float | None = None,
        max_c: float | None = None,
        mean_c: float | None = None,
        n_cells: int | None = None,
        raw_geojson: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO heat_samples (field_id, ts, analytic_type, temp_c,
                                      temp_f, min_c, max_c, mean_c, n_cells,
                                      raw_geojson)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (field_id, ts, analytic_type, temp_c, temp_f, min_c, max_c,
             mean_c, n_cells, raw_geojson),
        )

    def heat_samples(self, field_id: str, limit: int = 200) -> list[sqlite3.Row]:
        conn = self.reader()
        try:
            return conn.execute(
                "SELECT * FROM heat_samples WHERE field_id=? "
                "ORDER BY ts DESC LIMIT ?",
                (field_id, limit),
            ).fetchall()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # corridor_segments
    # ------------------------------------------------------------------
    def insert_corridor_segment(
        self,
        route_id: str,
        segment_id: int,
        ts: str,
        *,
        temp_f: float | None = None,
        exposure_index: float | None = None,
        distance_mi: float | None = None,
        geometry_json: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO corridor_segments (route_id, segment_id, ts, temp_f,
                                           exposure_index, distance_mi, geometry_json)
            VALUES (?,?,?,?,?,?,?)
            """,
            (route_id, segment_id, ts, temp_f, exposure_index, distance_mi,
             geometry_json),
        )

    def corridor_samples(
        self, route_id: str, ts: str | None = None
    ) -> list[sqlite3.Row]:
        conn = self.reader()
        try:
            if ts:
                rows = conn.execute(
                    "SELECT * FROM corridor_segments WHERE route_id=? AND ts=? "
                    "ORDER BY segment_id",
                    (route_id, ts),
                ).fetchall()
            else:
                # most recent ts for the route
                row = conn.execute(
                    "SELECT MAX(ts) AS ts FROM corridor_segments WHERE route_id=?",
                    (route_id,),
                ).fetchone()
                rows = (
                    conn.execute(
                        "SELECT * FROM corridor_segments WHERE route_id=? AND ts=? "
                        "ORDER BY segment_id",
                        (route_id, row["ts"]),
                    ).fetchall()
                    if row and row["ts"]
                    else []
                )
            return rows
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # env_samples
    # ------------------------------------------------------------------
    def insert_env_sample(
        self,
        field_id: str,
        ts: str,
        *,
        lat: float | None = None,
        lon: float | None = None,
        temperature_f: float | None = None,
        heat_index_f: float | None = None,
        wet_bulb_f: float | None = None,
        relative_humidity_percent: float | None = None,
        ghi_wm2: float | None = None,
        aqi_idx: float | None = None,
        precip_mm: float | None = None,
        raw_json: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO env_samples (field_id, lat, lon, ts, temperature_f,
                                     heat_index_f, wet_bulb_f,
                                     relative_humidity_percent, ghi_wm2,
                                     aqi_idx, precip_mm, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (field_id, lat, lon, ts, temperature_f, heat_index_f, wet_bulb_f,
             relative_humidity_percent, ghi_wm2, aqi_idx, precip_mm, raw_json),
        )

    def env_samples(self, field_id: str, limit: int = 200) -> list[sqlite3.Row]:
        conn = self.reader()
        try:
            return conn.execute(
                "SELECT * FROM env_samples WHERE field_id=? "
                "ORDER BY ts DESC LIMIT ?",
                (field_id, limit),
            ).fetchall()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # risk_scores (Day 3: canopy risk engine output)
    # ------------------------------------------------------------------
    def insert_risk_score(
        self,
        field_id: str,
        ts: str,
        *,
        crop: str | None = None,
        score: float | None = None,
        tier: str | None = None,
        canopy_temp_f: float | None = None,
        worker_wbgt_f: float | None = None,
        components_json: str | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO risk_scores (field_id, ts, crop, score, tier,
                                     canopy_temp_f, worker_wbgt_f,
                                     components_json)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (field_id, ts, crop, score, tier, canopy_temp_f, worker_wbgt_f,
             components_json),
        )

    def risk_scores(self, field_id: str, limit: int = 100) -> list[sqlite3.Row]:
        conn = self.reader()
        try:
            return conn.execute(
                "SELECT * FROM risk_scores WHERE field_id=? "
                "ORDER BY ts DESC LIMIT ?",
                (field_id, limit),
            ).fetchall()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # alerts (Day 3: harvest cooldown lookup)
    # ------------------------------------------------------------------
    def latest_alert_ts(
        self, field_id: str, alert_type: str | None = None
    ) -> str | None:
        """Most recent alert timestamp for a field (harvest cooldown)."""
        conn = self.reader()
        try:
            if alert_type:
                row = conn.execute(
                    "SELECT MAX(ts) AS ts FROM alerts "
                    "WHERE field_id=? AND alert_type=?",
                    (field_id, alert_type),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT MAX(ts) AS ts FROM alerts WHERE field_id=?",
                    (field_id,),
                ).fetchone()
            return row["ts"] if row and row["ts"] else None
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # spoilage_events
    # ------------------------------------------------------------------
    def insert_spoilage_event(
        self,
        field_id: str,
        ts: str,
        *,
        crop: str | None = None,
        degree_hours_f: float | None = None,
        spoilage_risk: float | None = None,
        q10: float | None = None,
    ) -> int:
        return self._execute(
            """
            INSERT INTO spoilage_events (field_id, crop, ts, degree_hours_f,
                                         spoilage_risk, q10)
            VALUES (?,?,?,?,?,?)
            """,
            (field_id, crop, ts, degree_hours_f, spoilage_risk, q10),
        )

    def spoilage_events(self, field_id: str | None = None,
                        limit: int = 200) -> list[sqlite3.Row]:
        conn = self.reader()
        try:
            if field_id:
                return conn.execute(
                    "SELECT * FROM spoilage_events WHERE field_id=? "
                    "ORDER BY ts DESC LIMIT ?",
                    (field_id, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM spoilage_events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # alerts
    # ------------------------------------------------------------------
    def insert_alert(
        self,
        ts: str,
        *,
        field_id: str | None = None,
        alert_type: str | None = None,
        severity: str | None = None,
        message: str | None = None,
    ) -> int:
        return self._execute(
            "INSERT INTO alerts (field_id, alert_type, severity, message, ts) "
            "VALUES (?,?,?,?,?)",
            (field_id, alert_type, severity, message, ts),
        )

    def alerts(self, severity: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
        conn = self.reader()
        try:
            if severity:
                return conn.execute(
                    "SELECT * FROM alerts WHERE severity=? ORDER BY ts DESC LIMIT ?",
                    (severity, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # reports
    # ------------------------------------------------------------------
    def insert_report(
        self,
        *,
        report_type: str,
        field_id: str | None = None,
        path: str | None = None,
        download_link: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        return self._execute(
            "INSERT INTO reports (report_type, field_id, path, download_link, "
            "metadata_json) VALUES (?,?,?,?,?)",
            (report_type, field_id, path, download_link,
             json.dumps(metadata) if metadata else None),
        )

    def reports(self, report_type: str | None = None,
                limit: int = 100) -> list[sqlite3.Row]:
        conn = self.reader()
        try:
            if report_type:
                return conn.execute(
                    "SELECT * FROM reports WHERE report_type=? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (report_type, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM reports ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def table_counts(self) -> dict[str, int]:
        conn = self.reader()
        try:
            names = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND "
                    "name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            return {
                name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in names
            }
        finally:
            conn.close()

    def verify_schema(self) -> list[str]:
        """Return the list of expected tables; raises if any is missing."""
        conn = self.reader()
        try:
            have = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        expected = [
            "fields", "heat_samples", "corridor_segments", "env_samples",
            "risk_scores", "spoilage_events", "alerts", "reports",
        ]
        missing = [t for t in expected if t not in have]
        if missing:
            raise RuntimeError(f"missing tables: {missing}")
        return expected


__all__ = ["Persistence", "SCHEMA_SQL", "_DEFAULT_DB"]

# Public alias (docstring / __all__ reference SCHEMA_SQL).
SCHEMA_SQL = _SCHEMA_SQL
