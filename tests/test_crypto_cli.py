"""CLI crypto Typer app smoke tests — no LLM / no network."""

from typer.testing import CliRunner

from cli.main import app


runner = CliRunner()


def test_root_help_circuit_branding():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Circuit Framework" in result.stdout


def test_crypto_help():
    result = runner.invoke(app, ["crypto", "--help"])
    assert result.exit_code == 0
    assert "analyze" in result.stdout
    assert "portfolio" in result.stdout
    assert "positions" in result.stdout
    assert "leaderboard" in result.stdout


def test_crypto_portfolio_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    monkeypatch.setenv("TRADINGAGENTS_PAPER_DATABASE_PATH", str(db_path))
    # Re-import config after env — DEFAULT_CONFIG already loaded; patch command helper
    from tradingagents.paper.database import PaperDatabase
    from tradingagents.paper.portfolio import PaperPortfolio
    from decimal import Decimal

    db = PaperDatabase(db_path)
    PaperPortfolio(db, name="default", strategy="balanced", starting_balance=Decimal("100000"))

    from cli import crypto_cmd

    monkeypatch.setattr(crypto_cmd, "_paper_db", lambda config=None: PaperDatabase(db_path))
    result = runner.invoke(app, ["crypto", "portfolio"])
    assert result.exit_code == 0
    assert "Equity" in result.stdout or "100000" in result.stdout


def test_crypto_analyze_help():
    result = runner.invoke(app, ["crypto", "analyze", "--help"])
    assert result.exit_code == 0
    assert "--strategy" in result.stdout
    assert "--paper" in result.stdout
    assert "--json" in result.stdout
