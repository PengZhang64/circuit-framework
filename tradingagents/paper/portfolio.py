"""Paper portfolio helpers — balances, mark-to-market, equity."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from tradingagents.paper.database import PaperDatabase


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


class PaperPortfolio:
    def __init__(
        self,
        db: PaperDatabase,
        *,
        name: str = "default",
        strategy: str = "balanced",
        starting_balance: Decimal | float | int = 100_000,
    ) -> None:
        self.db = db
        self.name = name
        self.strategy = strategy
        self.starting_balance = _d(starting_balance)
        record = self.db.get_or_create_portfolio(
            name=name,
            strategy=strategy,
            starting_balance=self.starting_balance,
        )
        self.portfolio_id = int(record["id"])

    def refresh(self) -> dict[str, Any]:
        row = self.db.get_portfolio(self.portfolio_id)
        if row is None:
            raise RuntimeError(f"portfolio {self.portfolio_id} missing")
        return row

    @property
    def cash_balance(self) -> Decimal:
        return _d(self.refresh()["cash_balance"])

    def list_positions(self) -> list[dict[str, Any]]:
        return self.db.list_positions(self.portfolio_id, strategy=self.strategy)

    def mark_to_market(
        self,
        marks: dict[str, Decimal | float],
        *,
        conn=None,
    ) -> Decimal:
        """Update unrealized PnL using current mark prices. Returns total unrealized."""
        total_upnl = Decimal("0")
        positions = (
            self.db.list_positions(self.portfolio_id, strategy=self.strategy)
            if conn is None
            else []
        )
        if conn is not None:
            # read inside caller transaction
            rows = conn.execute(
                "SELECT * FROM positions WHERE portfolio_id = ? AND strategy = ?",
                (self.portfolio_id, self.strategy),
            ).fetchall()
            positions = [dict(r) for r in rows]

        for pos in positions:
            instrument = pos["instrument"]
            mark = marks.get(instrument)
            if mark is None:
                total_upnl += _d(pos.get("unrealized_pnl") or 0)
                continue
            mark_d = _d(mark)
            qty = _d(pos["qty"])
            entry = _d(pos["entry_price"])
            side = pos["side"]
            if side == "LONG":
                upnl = (mark_d - entry) * qty
            elif side == "SHORT":
                upnl = (entry - mark_d) * qty
            else:
                upnl = Decimal("0")
            total_upnl += upnl
            fields = {
                "portfolio_id": self.portfolio_id,
                "strategy": self.strategy,
                "instrument": instrument,
                "side": side,
                "qty": qty,
                "entry_price": entry,
                "leverage": _d(pos["leverage"]),
                "stop_loss": _d(pos["stop_loss"]) if pos.get("stop_loss") else None,
                "take_profits": json.loads(pos.get("take_profits") or "[]"),
                "unrealized_pnl": upnl,
                "realized_pnl": _d(pos.get("realized_pnl") or 0),
                "mark_price": mark_d,
            }
            if conn is not None:
                self.db.upsert_position(fields, conn=conn)
            else:
                with self.db.transaction() as c:
                    self.db.upsert_position(fields, conn=c)
        return total_upnl

    def equity(self, marks: dict[str, Decimal | float] | None = None) -> Decimal:
        cash = self.cash_balance
        if marks:
            upnl = self.mark_to_market(marks)
        else:
            upnl = sum(
                (_d(p.get("unrealized_pnl") or 0) for p in self.list_positions()),
                Decimal("0"),
            )
        return cash + upnl

    def record_equity_snapshot(
        self,
        *,
        marks: dict[str, Decimal | float] | None = None,
        conn=None,
    ) -> dict[str, Decimal]:
        upnl = Decimal("0")
        if marks:
            upnl = self.mark_to_market(marks, conn=conn)
        else:
            upnl = sum(
                (_d(p.get("unrealized_pnl") or 0) for p in self.list_positions()),
                Decimal("0"),
            )
        cash = (
            _d(conn.execute(
                "SELECT cash_balance FROM portfolios WHERE id = ?",
                (self.portfolio_id,),
            ).fetchone()["cash_balance"])
            if conn is not None
            else self.cash_balance
        )
        realized = sum(
            (_d(p.get("realized_pnl") or 0) for p in self.list_positions()),
            Decimal("0"),
        )
        # Prefer sum of fill realized if positions empty/flat accounting differs
        fills = self.db.list_fills(self.portfolio_id)
        if fills:
            realized = sum((_d(f["realized_pnl"]) for f in fills), Decimal("0"))
        equity = cash + upnl
        fields = {
            "portfolio_id": self.portfolio_id,
            "strategy": self.strategy,
            "equity": equity,
            "cash_balance": cash,
            "unrealized_pnl": upnl,
            "realized_pnl": realized,
        }
        if conn is not None:
            self.db.insert_equity_snapshot(fields, conn=conn)
        else:
            with self.db.transaction() as c:
                self.db.insert_equity_snapshot(fields, conn=c)
        return {
            "equity": equity,
            "cash_balance": cash,
            "unrealized_pnl": upnl,
            "realized_pnl": realized,
        }
