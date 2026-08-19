"""PeachState CoolChain services - Reporting (Day 4).

JSON reports:
    - daily field summary
    - corridor comparison
    - spoilage risk
    - alert log

PDF reports:
    - Heat Intelligence PDF (Premium, from ``download_report``) for packing
      houses / buyers.
    - Synthetic report card (Basic fallback): field risk table, corridor
      recommendation, spoilage estimate, KPI summary - produced by the
      dependency-free PDF writer (:mod:`coolchain.services.pdf`).

Scheduling: daily 06:00 EDT pre-harvest briefing (APScheduler job in
``coolchain.services.api``) and on-demand via the CLI (``fg hi-report``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from coolchain.domain.routing import compare_from_db, load_corridor_nodes
from coolchain.domain.spoilage import evaluate_field_spoilage, evaluate_route_spoilage
from coolchain.services.pdf import write_report_card_pdf
from coolchain.services.persistence import Persistence

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"


@dataclass
class ReportService:
    persistence: Persistence
    output_dir: Path = DEFAULT_OUTPUT_DIR

    # ------------------------------------------------------------------
    # JSON reports
    # ------------------------------------------------------------------
    def _out(self, *parts: str) -> Path:
        p = self.output_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def daily_field_summary_json(self, report_date: str | None = None) -> Path:
        """Per-field latest risk + canopy temp for the pre-harvest briefing."""
        report_date = report_date or date.today().isoformat()
        fields = self.persistence.load_fields()
        summary = []
        for f in fields:
            rows = self.persistence.risk_scores(f["id"], limit=1)
            latest = rows[0] if rows else None
            summary.append(
                {
                    "field_id": f["id"],
                    "crop": f["crop"],
                    "region": f["region"],
                    "risk_score": latest["score"] if latest else None,
                    "tier": latest["tier"] if latest else None,
                    "canopy_temp_f": latest["canopy_temp_f"] if latest else None,
                    "as_of": latest["ts"] if latest else None,
                }
            )
        payload = {
            "report_type": "daily_field_summary",
            "date": report_date,
            "generated_at": _utc_now(),
            "fields": summary,
        }
        dest = self._out("json", f"daily_field_summary_{report_date}.json")
        dest.write_text(json.dumps(payload, indent=2))
        self.persistence.insert_report(
            report_type="daily_field_summary",
            path=str(dest),
            metadata={"date": report_date, "fields": len(summary)},
        )
        return dest

    def corridor_comparison_json(self, report_date: str | None = None) -> Path:
        report_date = report_date or date.today().isoformat()
        result = compare_from_db(self.persistence)
        payload = {
            "report_type": "corridor_comparison",
            "date": report_date,
            "generated_at": _utc_now(),
            "recommended": result.recommended,
            "saved_heat_exposure": result.saved_heat_exposure,
            "routes": [r.model_dump(mode="json") for r in result.routes],
        }
        dest = self._out("json", f"corridor_comparison_{report_date}.json")
        dest.write_text(json.dumps(payload, indent=2))
        self.persistence.insert_report(
            report_type="corridor_comparison",
            path=str(dest),
            metadata={"date": report_date, "routes": len(result.routes)},
        )
        return dest

    def spoilage_risk_json(self, report_date: str | None = None) -> Path:
        report_date = report_date or date.today().isoformat()
        fields = self.persistence.load_fields()
        per_field = []
        for f in fields:
            try:
                res = evaluate_field_spoilage(self.persistence, f["id"])
                if res is not None:
                    per_field.append(res.model_dump(mode="json"))
            except Exception:  # noqa: BLE001 - partial failure safe
                continue
        routes = []
        for rid in ("I16", "I75"):
            try:
                res = evaluate_route_spoilage(self.persistence, rid)
                if res is not None:
                    routes.append(res.model_dump(mode="json"))
            except Exception:  # noqa: BLE001
                continue
        payload = {
            "report_type": "spoilage_risk",
            "date": report_date,
            "generated_at": _utc_now(),
            "fields": per_field,
            "routes": routes,
        }
        dest = self._out("json", f"spoilage_risk_{report_date}.json")
        dest.write_text(json.dumps(payload, indent=2))
        self.persistence.insert_report(
            report_type="spoilage_risk",
            path=str(dest),
            metadata={"date": report_date, "fields": len(per_field)},
        )
        return dest

    def alert_log_json(self, report_date: str | None = None) -> Path:
        report_date = report_date or date.today().isoformat()
        alerts = self.persistence.alerts(limit=500)
        payload = {
            "report_type": "alert_log",
            "date": report_date,
            "generated_at": _utc_now(),
            "count": len(alerts),
            "alerts": [
                {
                    "id": a["id"],
                    "field_id": a["field_id"],
                    "alert_type": a["alert_type"],
                    "severity": a["severity"],
                    "message": a["message"],
                    "ts": a["ts"],
                }
                for a in alerts
            ],
        }
        dest = self._out("json", f"alert_log_{report_date}.json")
        dest.write_text(json.dumps(payload, indent=2))
        self.persistence.insert_report(
            report_type="alert_log",
            path=str(dest),
            metadata={"date": report_date, "alerts": len(alerts)},
        )
        return dest

    # ------------------------------------------------------------------
    # Synthetic report card PDF (Basic fallback)
    # ------------------------------------------------------------------
    def generate_synthetic_pdf(
        self,
        report_date: str | None = None,
        *,
        field_rows: list[dict[str, Any]] | None = None,
        corridor: dict[str, Any] | None = None,
        spoilage: dict[str, Any] | None = None,
    ) -> Path:
        """Synthetic report card: field risk table + corridor recommendation +
        spoilage estimate + KPI summary (dependency-free PDF)."""
        report_date = report_date or date.today().isoformat()
        field_rows = field_rows or self._latest_field_rows()
        corridor = corridor or self._corridor_payload()
        spoilage = spoilage or self._spoilage_payload()

        sections: dict[str, list[str]] = {
            "FIELD RISK TABLE": [
                f"{r['field_id']:<8} {r['crop']:<10} score={r['risk_score']:<5} "
                f"tier={r['tier']:<8} canopy={r['canopy_temp_f']} F"
                for r in field_rows
            ]
            or ["(no field risk data)"],
            "CORRIDOR RECOMMENDATION": [
                f"Recommended route: {corridor.get('recommended')}",
                f"Saved heat exposure: {corridor.get('saved_heat_exposure')} F-mi",
            ]
            + [
                f"{r.get('route_id')}: {r.get('distance_mi')} mi, "
                f"avg {r.get('avg_temp_f')} F, exposure {r.get('heat_exposure')} F-mi"
                for r in corridor.get("routes", [])
            ],
            "SPOILAGE ESTIMATE": [
                f"{s.get('field_id', '?')}: {s.get('risk_pct', 0)}% risk, "
                f"{s.get('dh_accumulated', 0)} deg-h, "
                f"shelf life {s.get('estimated_shelf_life_days', 0)} days"
                for s in spoilage.get("fields", [])
            ]
            or ["(no spoilage data)"],
            "KPI SUMMARY": self._kpi_lines(report_date),
        }
        dest = self._out("pdf", f"report_card_{report_date}.pdf")
        write_report_card_pdf(dest, title=f"PeachState CoolChain Report Card - {report_date}", sections=sections)
        self.persistence.insert_report(
            report_type="report_card",
            path=str(dest),
            metadata={"date": report_date, "sections": list(sections)},
        )
        return dest

    def _latest_field_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for f in self.persistence.load_fields():
            latest = self.persistence.risk_scores(f["id"], limit=1)
            if latest:
                rows.append(
                    {
                        "field_id": f["id"],
                        "crop": f["crop"],
                        "risk_score": latest[0]["score"],
                        "tier": latest[0]["tier"],
                        "canopy_temp_f": latest[0]["canopy_temp_f"],
                    }
                )
        return rows

    def _corridor_payload(self) -> dict[str, Any]:
        result = compare_from_db(self.persistence)
        return {
            "recommended": result.recommended,
            "saved_heat_exposure": result.saved_heat_exposure,
            "routes": [r.model_dump(mode="json") for r in result.routes],
        }

    def _spoilage_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"fields": []}
        for f in self.persistence.load_fields():
            try:
                res = evaluate_field_spoilage(self.persistence, f["id"])
                if res is not None:
                    payload["fields"].append(res.model_dump(mode="json"))
            except Exception:  # noqa: BLE001
                continue
        return payload

    def _kpi_lines(self, report_date: str) -> list[str]:
        alerts = self.persistence.alerts(limit=500)
        high = sum(1 for a in alerts if (a["severity"] or "").upper() in ("HIGH", "CRITICAL"))
        fields = self.persistence.load_fields()
        risk_rows = self._latest_field_rows()
        at_risk = sum(1 for r in risk_rows if r["tier"] in ("high", "critical"))
        counts = self.persistence.table_counts()
        return [
            f"Date: {report_date}",
            f"Fields monitored: {len(fields)}",
            f"Fields at HIGH/CRITICAL risk: {at_risk}",
            f"Alerts in log: {len(alerts)} (HIGH/CRITICAL: {high})",
            f"Heat samples stored: {counts.get('heat_samples', 0)}",
            f"Risk scores stored: {counts.get('risk_scores', 0)}",
        ]

    # ------------------------------------------------------------------
    # Heat Intelligence PDF (Premium) / digest fallback
    # ------------------------------------------------------------------
    async def fetch_hi_pdf(
        self,
        lat: float,
        lon: float,
        report_date: str,
        *,
        client: Any = None,
        dest: Path | None = None,
        temperature: float = 30.0,
        analysis: list[str] | None = None,
    ) -> Path | None:
        """Fetch the Premium Heat Intelligence PDF for a packing house.

        Falls back to a synthetic report card when the client is on the
        Basic plan or the download fails.
        """
        from fortyguard_sdk import HeatIntelligenceRequest, Plan

        if client is None or client.plan != Plan.PREMIUM:
            # Basic fallback: synthetic report card at the packing-house site.
            fallback = dest or self._out("pdf", f"hi_fallback_{report_date}.pdf")
            write_report_card_pdf(
                fallback,
                title=f"Heat Intelligence (synthetic) - {report_date}",
                sections={
                    "SITE": [f"lat={lat}, lon={lon}"],
                    "NOTE": [
                        "Heat Intelligence PDF is a Premium feature; this "
                        "synthetic report card is the Basic-plan fallback."
                    ],
                },
            )
            return fallback

        req = HeatIntelligenceRequest(
            latitude=lat,
            longitude=lon,
            temperature=temperature,
            date=report_date,
            analysis=analysis or ["environmental"],
        )
        res = await client.heat_intelligence(req)
        if not res.download_link:
            raise RuntimeError("heat_intelligence returned no download_link")
        dest = dest or self._out("pdf", f"hi_{lat:.3f}_{lon:.3f}_{report_date}.pdf")
        return await client.download_report(res.download_link, dest)

    # ------------------------------------------------------------------
    # Daily bundle
    # ------------------------------------------------------------------
    def generate_daily(self, report_date: str | None = None) -> dict[str, Path]:
        """JSON + synthetic PDF bundle for the 06:00 pre-harvest briefing."""
        report_date = report_date or date.today().isoformat()
        files = {
            "daily_field_summary": self.daily_field_summary_json(report_date),
            "corridor_comparison": self.corridor_comparison_json(report_date),
            "spoilage_risk": self.spoilage_risk_json(report_date),
            "alert_log": self.alert_log_json(report_date),
            "report_card": self.generate_synthetic_pdf(report_date),
        }
        return files

    def list_reports(self, report_type: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "id": r["id"],
                "report_type": r["report_type"],
                "field_id": r["field_id"],
                "path": r["path"],
                "created_at": r["created_at"],
            }
            for r in self.persistence.reports(report_type, limit=200)
        ]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = ["ReportService", "DEFAULT_OUTPUT_DIR"]