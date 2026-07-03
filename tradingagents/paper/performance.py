"""Paper performance metrics — None when not yet calculable."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from tradingagents.paper.database import PaperDatabase
from tradingagents.paper.schemas import PerformanceMetrics


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _f(value: Decimal | float | None) -> float | None:
    if value is None:
        return None
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def compute_performance(
    db: PaperDatabase,
    portfolio_id: int,
    *,
    risk_free_rate: float = 0.0,
) -> PerformanceMetrics:
    """Compute portfolio performance. Returns None for undefined metrics."""
    portfolio = db.get_portfolio(portfolio_id)
    if portfolio is None:
        return PerformanceMetrics()

    starting = _d(portfolio["starting_balance"])
    fills = db.list_fills(portfolio_id)
    equity_curve = db.list_equity_snapshots(portfolio_id)
    positions = db.list_positions(portfolio_id)

    fees_paid = sum((_d(f["fee"]) for f in fills), Decimal("0")) if fills else None
    trade_count = len(fills) if fills else None

    realized = (
        sum((_d(f["realized_pnl"]) for f in fills), Decimal("0")) if fills else None
    )
    unrealized = (
        sum((_d(p.get("unrealized_pnl") or 0) for p in positions), Decimal("0"))
        if positions
        else (Decimal("0") if fills else None)
    )

    total_return = None
    if equity_curve and starting > 0:
        last_eq = _d(equity_curve[-1]["equity"])
        total_return = (last_eq - starting) / starting
    elif unrealized is not None and realized is not None and starting > 0:
        total_return = (realized + unrealized - fees_paid) / starting if fees_paid is not None else (realized + unrealized) / starting

    # Win rate / profit factor from fills with non-zero realized (closed legs)
    closed = [f for f in fills if _d(f["realized_pnl"]) != 0] if fills else []
    win_rate = None
    profit_factor = None
    if closed:
        wins = [f for f in closed if _d(f["realized_pnl"]) > 0]
        losses = [f for f in closed if _d(f["realized_pnl"]) < 0]
        win_rate = len(wins) / len(closed)
        gross_profit = sum((_d(f["realized_pnl"]) for f in wins), Decimal("0"))
        gross_loss = abs(sum((_d(f["realized_pnl"]) for f in losses), Decimal("0")))
        if gross_loss > 0:
            profit_factor = float(gross_profit / gross_loss)
        elif gross_profit > 0:
            profit_factor = None  # undefined infinite — report None not fake
        else:
            profit_factor = None

    # Maximum drawdown from equity curve
    maximum_drawdown = None
    if len(equity_curve) >= 2:
        peak = _d(equity_curve[0]["equity"])
        max_dd = Decimal("0")
        for row in equity_curve:
            eq = _d(row["equity"])
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd
        maximum_drawdown = float(max_dd)

    # Sharpe from equity period returns
    sharpe_ratio = None
    if len(equity_curve) >= 3:
        rets: list[float] = []
        for i in range(1, len(equity_curve)):
            prev = float(_d(equity_curve[i - 1]["equity"]))
            cur = float(_d(equity_curve[i]["equity"]))
            if prev > 0:
                rets.append((cur - prev) / prev)
        if len(rets) >= 2:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            std = math.sqrt(var)
            if std > 0:
                sharpe_ratio = (mean - risk_free_rate) / std

    average_leverage = None
    if fills:
        # Use order leverage via joining — fills don't store leverage; approx from positions + orders
        with db.connection() as conn:
            rows = conn.execute(
                "SELECT leverage FROM orders WHERE portfolio_id = ? AND status = 'filled'",
                (portfolio_id,),
            ).fetchall()
        if rows:
            lev = [_d(r["leverage"]) for r in rows]
            average_leverage = float(sum(lev) / len(lev))

    return PerformanceMetrics(
        total_return=_f(total_return),
        realized_pnl=_f(realized),
        unrealized_pnl=_f(unrealized),
        win_rate=_f(win_rate),
        profit_factor=profit_factor,
        maximum_drawdown=maximum_drawdown,
        sharpe_ratio=sharpe_ratio,
        average_leverage=average_leverage,
        fees_paid=_f(fees_paid),
        trade_count=trade_count,
    )
