"""Non-interactive Circuit Framework crypto CLI commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.setup import CRYPTO_DEFAULT_ANALYSTS
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.paper.database import PaperDatabase
from tradingagents.paper.performance import compute_performance
from tradingagents.paper.portfolio import PaperPortfolio
from tradingagents.reporting import write_crypto_report_bundle
from tradingagents.strategies import apply_strategy_to_config, list_strategies

console = Console()

crypto_app = typer.Typer(
    name="crypto",
    help="Circuit Framework crypto research and paper-trading commands",
    add_completion=False,
    no_args_is_help=True,
)


def _build_crypto_config(
    *,
    strategy: str,
    venue: str,
    instrument: str,
    interval: str,
    checkpoint: bool | None,
) -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    config["crypto_venue"] = venue
    config["crypto_instrument_type"] = instrument
    config["crypto_default_interval"] = interval
    if checkpoint is not None:
        config["checkpoint_enabled"] = checkpoint
    config = apply_strategy_to_config(config, strategy)
    return config


def _default_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _paper_db(config: dict[str, Any] | None = None) -> PaperDatabase:
    cfg = config or DEFAULT_CONFIG
    path = cfg.get("paper_database_path") or "~/.tradingagents/circuit/paper.db"
    return PaperDatabase(path)


@crypto_app.command("analyze")
def crypto_analyze(
    symbol: str = typer.Argument(..., help="Crypto symbol, e.g. BTC, ETH-PERP, SOL"),
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        help="Strategy profile name (default: config default_crypto_strategy)",
    ),
    venue: str = typer.Option("hyperliquid", "--venue", help="Crypto venue"),
    instrument: str = typer.Option("perp", "--instrument", help="Instrument type"),
    interval: str = typer.Option("1h", "--interval", help="Primary analysis interval"),
    date: str | None = typer.Option(
        None, "--date", help="Analysis date YYYY-MM-DD (default: today UTC)"
    ),
    paper: bool = typer.Option(
        False, "--paper", help="Execute risk-approved proposal in the paper portfolio"
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Print trade_proposal + risk_decision JSON"
    ),
    checkpoint: bool | None = typer.Option(
        None,
        "--checkpoint/--no-checkpoint",
        help="Enable/disable checkpoint resume for this run",
    ),
):
    """Run crypto research graph for SYMBOL and write the report bundle."""
    trade_date = date or _default_date()
    strategy_name = strategy or DEFAULT_CONFIG.get("default_crypto_strategy", "balanced")
    if strategy_name not in list_strategies():
        console.print(
            f"[red]Unknown strategy {strategy_name!r}. "
            f"Available: {', '.join(list_strategies())}[/red]"
        )
        raise typer.Exit(code=1)

    config = _build_crypto_config(
        strategy=strategy_name,
        venue=venue,
        instrument=instrument,
        interval=interval,
        checkpoint=checkpoint,
    )

    graph = TradingAgentsGraph(
        selected_analysts=list(CRYPTO_DEFAULT_ANALYSTS),
        config=config,
        asset_type="crypto",
        strategy_profile=strategy_name,
    )

    final_state, decision = graph.propagate(
        symbol,
        trade_date,
        asset_type="crypto",
        strategy_profile=strategy_name,
        paper_execution_requested=paper,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    save_path = (
        Path(config["results_dir"])
        / "crypto"
        / f"{symbol}_{strategy_name}_{stamp}"
    )
    write_crypto_report_bundle(
        final_state,
        symbol,
        save_path,
        config=config,
        meta={
            "strategy": strategy_name,
            "venue": venue,
            "paper_execution_requested": paper,
        },
    )

    proposal = final_state.get("trade_proposal")
    risk = final_state.get("risk_decision")
    if hasattr(proposal, "model_dump"):
        proposal = proposal.model_dump(mode="json")
    if hasattr(risk, "model_dump"):
        risk = risk.model_dump(mode="json")

    if as_json:
        console.print(
            json.dumps(
                {"trade_proposal": proposal, "risk_decision": risk},
                indent=2,
                default=str,
            )
        )
    else:
        action = None
        if isinstance(proposal, dict):
            action = proposal.get("action")
        if isinstance(risk, dict) and risk.get("final_action"):
            action = risk.get("final_action")
        approved = risk.get("approved") if isinstance(risk, dict) else None
        console.print(f"[bold]Circuit Framework[/bold] — {symbol} @ {trade_date}")
        console.print(f"  Strategy: {strategy_name}")
        console.print(f"  Final action: {action or decision}")
        console.print(f"  Risk approved: {approved}")
        if paper:
            paper_res = final_state.get("paper_execution_result") or {}
            console.print(f"  Paper execution: {paper_res.get('status', 'n/a')}")
        console.print(f"  Reports: {save_path.resolve()}")


@crypto_app.command("portfolio")
def crypto_portfolio(
    strategy: str | None = typer.Option(
        None, "--strategy", help="Filter to a strategy portfolio"
    ),
    name: str = typer.Option("default", "--name", help="Portfolio name"),
):
    """Show paper portfolio equity, cash, and unrealized PnL."""
    db = _paper_db()
    strategy_name = strategy or DEFAULT_CONFIG.get("default_crypto_strategy", "balanced")
    portfolio = PaperPortfolio(
        db,
        name=name,
        strategy=strategy_name,
        starting_balance=DEFAULT_CONFIG.get("paper_starting_balance", 100_000),
    )
    row = portfolio.refresh()
    equity = portfolio.equity()
    upnl = sum(
        (Decimal(str(p.get("unrealized_pnl") or 0)) for p in portfolio.list_positions()),
        Decimal("0"),
    )
    table = Table(title=f"Paper Portfolio — {name} / {strategy_name}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Equity", f"{equity}")
    table.add_row("Cash", f"{row['cash_balance']}")
    table.add_row("Unrealized PnL", f"{upnl}")
    table.add_row("Starting balance", f"{row['starting_balance']}")
    console.print(table)


@crypto_app.command("positions")
def crypto_positions(
    strategy: str | None = typer.Option(
        None, "--strategy", help="Filter to a strategy"
    ),
    name: str = typer.Option("default", "--name", help="Portfolio name"),
):
    """List open paper positions."""
    db = _paper_db()
    strategy_name = strategy or DEFAULT_CONFIG.get("default_crypto_strategy", "balanced")
    portfolio = PaperPortfolio(
        db,
        name=name,
        strategy=strategy_name,
        starting_balance=DEFAULT_CONFIG.get("paper_starting_balance", 100_000),
    )
    positions = portfolio.list_positions()
    table = Table(title=f"Open Positions — {name} / {strategy_name}")
    table.add_column("Instrument")
    table.add_column("Side")
    table.add_column("Qty", justify="right")
    table.add_column("Entry", justify="right")
    table.add_column("Leverage", justify="right")
    table.add_column("Unrealized", justify="right")
    table.add_column("Mark", justify="right")
    if not positions:
        console.print("[dim]No open positions.[/dim]")
        return
    for p in positions:
        table.add_row(
            str(p.get("instrument")),
            str(p.get("side")),
            str(p.get("qty")),
            str(p.get("entry_price")),
            str(p.get("leverage")),
            str(p.get("unrealized_pnl")),
            str(p.get("mark_price") or "—"),
        )
    console.print(table)


@crypto_app.command("leaderboard")
def crypto_leaderboard(
    name: str = typer.Option("default", "--name", help="Portfolio family name"),
):
    """Rank strategy profiles by paper performance metrics."""
    db = _paper_db()
    portfolios = db.list_portfolios(name=name)
    # Also include known strategies even if empty (create lazily? no — only existing)
    if not portfolios:
        console.print(
            "[dim]No paper portfolios yet. Run "
            "`tradingagents crypto analyze … --paper` first.[/dim]"
        )
        return

    rows: list[dict[str, Any]] = []
    for p in portfolios:
        metrics = compute_performance(db, int(p["id"]))
        insufficient = any(
            getattr(metrics, field) is None
            for field in (
                "total_return",
                "sharpe_ratio",
                "maximum_drawdown",
                "profit_factor",
                "win_rate",
            )
        )
        rows.append(
            {
                "strategy": p["strategy"],
                "total_return": metrics.total_return,
                "sharpe": metrics.sharpe_ratio,
                "max_dd": metrics.maximum_drawdown,
                "profit_factor": metrics.profit_factor,
                "win_rate": metrics.win_rate,
                "fees": metrics.fees_paid,
                "trade_count": metrics.trade_count,
                "insufficient": insufficient,
            }
        )

    def _sort_key(r: dict[str, Any]):
        tr = r["total_return"]
        return (tr is not None, tr if tr is not None else float("-inf"))

    rows.sort(key=_sort_key, reverse=True)

    table = Table(title=f"Strategy Leaderboard — {name}")
    table.add_column("Strategy")
    table.add_column("Total Return", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("Max DD", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Fees", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Status")

    def _fmt(v: Any, pct: bool = False) -> str:
        if v is None:
            return "—"
        if pct:
            return f"{v:.2%}"
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)

    for r in rows:
        status = "insufficient-history" if r["insufficient"] else "ok"
        table.add_row(
            r["strategy"],
            _fmt(r["total_return"], pct=True),
            _fmt(r["sharpe"]),
            _fmt(r["max_dd"], pct=True),
            _fmt(r["profit_factor"]),
            _fmt(r["win_rate"], pct=True),
            _fmt(r["fees"]),
            str(r["trade_count"] if r["trade_count"] is not None else "—"),
            status,
        )
    console.print(table)
