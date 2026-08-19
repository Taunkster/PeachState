"""Day-4 CLI tests - every `fg` command parses, runs (fixture mode), and
returns the expected exit code + output.

Offline: no FG_API_KEY -> the CLI uses the FixtureBackend, so all data
commands work end-to-end without network. DB-backed commands run against a
temp SQLite DB pointed to by COOLCHAIN_DB / the injected context.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from coolchain.cli import commands as cli
from coolchain.cli.context import build_context
from coolchain.services.persistence import Persistence

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


@pytest.fixture()
def cli_ctx(tmp_path, monkeypatch):
    """Fixture-mode context with a temp DB injected into the CLI module."""
    ctx = build_context(api_key="")  # force fixture mode
    ctx.db_path = tmp_path / "coolchain.db"
    cli._DEFAULT_CTX = ctx
    monkeypatch.setenv("COOLCHAIN_DB", str(ctx.db_path))
    yield ctx
    cli._DEFAULT_CTX = None


def _invoke(args, **kw):
    return runner.invoke(cli.app, args, **kw)


# ---------------------------------------------------------------------------
# Help / app registration
# ---------------------------------------------------------------------------
def test_cli_app_help():
    result = _invoke(["--help"])
    assert result.exit_code == 0
    for name in ("heatmap", "env-params", "corridor", "risk", "harvest",
                 "spoilage", "hi-report", "fixtures", "serve", "db"):
        assert name in result.output


def test_cli_command_helps():
    for args in (
        ["heatmap", "--help"], ["env-params", "--help"], ["corridor", "--help"],
        ["risk", "--help"], ["harvest", "--help"], ["spoilage", "--help"],
        ["hi-report", "--help"], ["fixtures", "--help"], ["db", "--help"],
        ["db", "init", "--help"], ["db", "status", "--help"],
        ["fixtures", "list", "--help"], ["fixtures", "record", "--help"],
    ):
        result = _invoke(args)
        assert result.exit_code == 0, f"{args} failed: {result.output}"


# ---------------------------------------------------------------------------
# Live/fixture data commands (offline fixture mode)
# ---------------------------------------------------------------------------
def test_cli_heatmap_fixture(cli_ctx):
    result = _invoke(["heatmap", "--date", "2025-07-15",
                      "--output", str(cli_ctx.db_path.parent / "hm.json"),
                      "32.5517", "--", "-83.8871"])
    assert result.exit_code == 0, result.output
    data = json.loads((cli_ctx.db_path.parent / "hm.json").read_text())
    assert data["analytic_type"] == "tcm"
    assert data["n_cells"] > 0
    assert data["mode"] == "fixtures"
    assert "map_data" in data


def test_cli_heatmap_stdout(cli_ctx):
    result = _invoke(["heatmap", "--analytic", "exceedance",
                      "32.0809", "--", "-81.0912"])
    assert result.exit_code == 0
    assert "exceedance" in result.output


def test_cli_env_params_fixture(cli_ctx):
    result = _invoke(["env-params",
                      "--params", "heat_index_celsius,relative_humidity_percent",
                      "--output", str(cli_ctx.db_path.parent / "env.json"),
                      "32.5517", "--", "-83.8871"])
    assert result.exit_code == 0, result.output
    data = json.loads((cli_ctx.db_path.parent / "env.json").read_text())
    assert data["locations"]
    assert data["locations"][0]["temperature_f"] is not None
    assert data["mode"] == "fixtures"


def test_cli_corridor_fixture(cli_ctx):
    result = _invoke(["corridor", "Macon", "Savannah", "--route", "both",
                      "--output", str(cli_ctx.db_path.parent / "corr.json")])
    assert result.exit_code == 0, result.output
    data = json.loads((cli_ctx.db_path.parent / "corr.json").read_text())
    assert data["recommended"] == "I16"
    assert len(data["routes"]) == 2


def test_cli_corridor_single_route(cli_ctx):
    result = _invoke(["corridor", "Macon", "Savannah", "--route", "i75"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["routes"]) == 1
    assert data["routes"][0]["route_id"] == "I75"


# ---------------------------------------------------------------------------
# DB commands
# ---------------------------------------------------------------------------
def test_cli_db_init_and_status(cli_ctx):
    result = _invoke(["db", "init", "--demo"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["fields_seeded"] == 45
    assert data["demo_fields"] == ["PV-01", "AL-01", "BB-01", "VD-01"]
    assert data["tables"]["fields"] == 45

    result2 = _invoke(["db", "status"])
    assert result2.exit_code == 0
    status = json.loads(result2.output)
    assert status["counts"]["risk_scores"] >= 4
    assert status["last_timestamps"]["heat_samples"] is not None


# ---------------------------------------------------------------------------
# Domain commands (SQLite-backed)
# ---------------------------------------------------------------------------
def test_cli_risk_field(cli_ctx):
    _invoke(["db", "init", "--demo"])
    result = _invoke(["risk", "PV-01", "--output", str(cli_ctx.db_path.parent / "risk.json")])
    assert result.exit_code == 0, result.output
    data = json.loads((cli_ctx.db_path.parent / "risk.json").read_text())
    assert data["field_id"] == "PV-01"
    assert 0 <= data["score"] <= 100
    assert data["tier"] in ("low", "medium", "high", "critical")


def test_cli_risk_no_data(cli_ctx):
    _invoke(["db", "init"])
    result = _invoke(["risk", "PV-01"])
    assert result.exit_code == 0
    assert "error" in json.loads(result.output)


def test_cli_harvest_field(cli_ctx):
    _invoke(["db", "init", "--demo"])
    result = _invoke(["harvest", "PV-01"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["field_id"] == "PV-01"
    assert data["crop"] == "peach"
    assert "urgency" in data
    assert "recommended_action" in data


def test_cli_spoilage_route(cli_ctx):
    _invoke(["db", "init", "--demo"])
    result = _invoke(["spoilage", "PV-01"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["field_id"] == "PV-01"
    assert "risk_pct" in data


def test_cli_hi_report_fixture(cli_ctx):
    result = _invoke(["hi-report", "--output", str(cli_ctx.db_path.parent / "hi.pdf"),
                      "32.5517", "--", "-83.8871"])
    assert result.exit_code == 0, result.output
    pdf = cli_ctx.db_path.parent / "hi.pdf"
    assert pdf.exists()
    assert pdf.read_bytes().startswith(b"%PDF")


def test_cli_fixtures_list(cli_ctx):
    result = _invoke(["fixtures", "list"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["count"] >= 5
    assert any("env_params_fort_valley.json" in f for f in data["fixtures"])


def test_cli_fixtures_record_offline_day6(cli_ctx, tmp_path):
    # No FG_API_KEY -> record runs OFFLINE, writing the full Day-6 scope
    # (live calls are only attempted when the key is set; otherwise every
    # envelope is source:"cached"). This is the demo's offline safety net.
    out = tmp_path / "day6"
    result = _invoke(["fixtures", "record", "--output-dir", str(out)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    for sub in ("fields", "corridor", "env", "risk", "harvest", "spoilage",
                "hi_report"):
        assert any(f.startswith(f"{sub}/") for f in data["files"]), sub
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["source_mode"] == "cached"
    assert manifest["counts"]["fields"] >= 12
    assert manifest["counts"]["env"] == 2
    assert manifest["counts"]["hi_report"] == 2
    # Hero numbers frozen exactly (docs/01 demo script).
    risk = json.loads((out / "risk" / "risk_scores.json").read_text())
    pv = next(f for f in risk["response"]["fields"] if f["field_id"] == "PV-07")
    assert pv["score"] == 91.0
    assert pv["tier"] == "critical"


def test_cli_serve_registered(cli_ctx):
    result = _invoke(["serve", "--help"])
    assert result.exit_code == 0
    assert "--interval-min" in result.output
    assert "--port" in result.output


# ---------------------------------------------------------------------------
# Scheduler + app building blocks are covered in test_services.py
# ---------------------------------------------------------------------------
def test_seed_helpers_idempotent(tmp_path):
    p = Persistence(tmp_path / "coolchain.db")
    try:
        n1 = cli.seed_fields(p)
        n2 = cli.seed_fields(p)
        assert n1 == n2 == 45
        assert len(p.load_fields()) == 45
    finally:
        p.close()