"""Simulated paper execution — mid ± slippage, fees, no live exchange."""

from __future__ import annotations

import contextlib
from decimal import Decimal
from typing import Any

from tradingagents.crypto.schemas import (
    CryptoMarketSnapshot,
    CryptoTradeAction,
    CryptoTradeProposal,
)
from tradingagents.paper.database import PaperDatabase
from tradingagents.paper.portfolio import PaperPortfolio
from tradingagents.risk.schemas import RiskDecision


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


class PaperExecutor:
    """Execute risk-approved crypto proposals into the paper database."""

    def __init__(
        self,
        db: PaperDatabase,
        *,
        config: dict[str, Any] | None = None,
        portfolio_name: str = "default",
    ) -> None:
        self.db = db
        self.config = dict(config or {})
        self.fee_bps = _d(self.config.get("paper_fee_bps", 4.5))
        self.slippage_bps = _d(self.config.get("paper_slippage_bps", 2.0))
        self.starting_balance = _d(self.config.get("paper_starting_balance", 100_000))
        self.portfolio_name = portfolio_name

    def execute(
        self,
        proposal: CryptoTradeProposal,
        risk: RiskDecision,
        snapshot: CryptoMarketSnapshot,
        *,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        """Simulate a fill for an approved directional proposal.

        Never executes rejected or NO_TRADE decisions. Dedupes on
        strategy + snapshot_id. Returns a structured execution result dict.
        """
        strategy_name = strategy or self.config.get("strategy_profile") or "balanced"

        if not risk.approved:
            return self._rejected(
                strategy_name,
                proposal,
                risk,
                "risk decision not approved",
            )
        if risk.final_action == CryptoTradeAction.NO_TRADE:
            return self._rejected(
                strategy_name,
                proposal,
                risk,
                "NO_TRADE — nothing to execute",
            )
        if proposal.action == CryptoTradeAction.NO_TRADE:
            return self._rejected(
                strategy_name,
                proposal,
                risk,
                "proposal is NO_TRADE",
            )

        if self.db.has_strategy_run(strategy_name, proposal.snapshot_id):
            return {
                "status": "duplicate",
                "strategy": strategy_name,
                "snapshot_id": proposal.snapshot_id,
                "reason": "strategy+snapshot_id already executed",
            }

        mid = snapshot.mid_price
        if mid is None:
            mid = snapshot.mark_price
        if mid is None:
            return self._rejected(
                strategy_name,
                proposal,
                risk,
                "no current mid or mark price",
                record_run=True,
            )

        mid_d = _d(mid)
        slip = self.slippage_bps / _d(10_000)
        action = risk.final_action
        # BUY for LONG (pay ask-ish), SELL for SHORT (hit bid-ish)
        if action == CryptoTradeAction.LONG:
            side = "BUY"
            fill_price = mid_d * (Decimal("1") + slip)
            pos_side = "LONG"
        else:
            side = "SELL"
            fill_price = mid_d * (Decimal("1") - slip)
            pos_side = "SHORT"

        portfolio = PaperPortfolio(
            self.db,
            name=self.portfolio_name,
            strategy=strategy_name,
            starting_balance=self.starting_balance,
        )
        equity = portfolio.equity({snapshot.instrument.display_symbol: mid_d})
        position_pct = _d(risk.approved_position_pct)
        leverage = _d(risk.approved_leverage)
        notional = equity * (position_pct / Decimal("100"))
        if fill_price <= 0 or notional <= 0:
            return self._rejected(
                strategy_name,
                proposal,
                risk,
                "non-positive notional or price",
                record_run=True,
            )
        qty = notional / fill_price
        fee = notional * (self.fee_bps / _d(10_000))
        instrument = proposal.instrument.display_symbol

        with self.db.transaction() as conn:
            # Re-check dedupe inside transaction
            existing = conn.execute(
                "SELECT 1 FROM strategy_runs WHERE strategy = ? AND snapshot_id = ?",
                (strategy_name, proposal.snapshot_id),
            ).fetchone()
            if existing:
                return {
                    "status": "duplicate",
                    "strategy": strategy_name,
                    "snapshot_id": proposal.snapshot_id,
                    "reason": "strategy+snapshot_id already executed",
                }

            cash = _d(
                conn.execute(
                    "SELECT cash_balance FROM portfolios WHERE id = ?",
                    (portfolio.portfolio_id,),
                ).fetchone()["cash_balance"]
            )
            # Margin reserved ≈ notional / leverage; fee deducted from cash
            margin = notional / leverage if leverage > 0 else notional
            if cash < margin + fee:
                self.db.insert_strategy_run(
                    strategy=strategy_name,
                    snapshot_id=proposal.snapshot_id,
                    instrument=instrument,
                    proposal_json=proposal.to_json_dict(),
                    risk_json=risk.model_dump(mode="json"),
                    execution_status="rejected_insufficient_cash",
                    conn=conn,
                )
                order_id = self.db.insert_order(
                    {
                        "portfolio_id": portfolio.portfolio_id,
                        "strategy": strategy_name,
                        "snapshot_id": proposal.snapshot_id,
                        "instrument": instrument,
                        "side": side,
                        "action": action.value,
                        "qty": qty,
                        "leverage": leverage,
                        "limit_price": fill_price,
                        "status": "rejected",
                        "rejection_reason": "insufficient cash for margin+fee",
                    },
                    conn=conn,
                )
                return {
                    "status": "rejected",
                    "reason": "insufficient cash for margin+fee",
                    "order_id": order_id,
                }

            prior = self.db.get_position(
                portfolio.portfolio_id,
                strategy_name,
                instrument,
                conn=conn,
            )
            realized = Decimal("0")
            new_qty = qty
            new_entry = fill_price
            new_side = pos_side
            new_realized_cum = Decimal("0")

            if prior and prior["side"] not in ("FLAT",) and _d(prior["qty"]) > 0:
                prior_side = prior["side"]
                prior_qty = _d(prior["qty"])
                prior_entry = _d(prior["entry_price"])
                prior_realized = _d(prior.get("realized_pnl") or 0)

                if prior_side == pos_side:
                    # Add to position — VWAP entry
                    total_qty = prior_qty + qty
                    new_entry = (
                        (prior_entry * prior_qty) + (fill_price * qty)
                    ) / total_qty
                    new_qty = total_qty
                    new_realized_cum = prior_realized
                else:
                    # Reduce / flip
                    close_qty = min(prior_qty, qty)
                    if prior_side == "LONG":
                        realized = (fill_price - prior_entry) * close_qty
                    else:
                        realized = (prior_entry - fill_price) * close_qty
                    remaining_prior = prior_qty - close_qty
                    leftover = qty - close_qty
                    new_realized_cum = prior_realized + realized
                    if remaining_prior > 0:
                        new_qty = remaining_prior
                        new_entry = prior_entry
                        new_side = prior_side
                    elif leftover > 0:
                        new_qty = leftover
                        new_entry = fill_price
                        new_side = pos_side
                    else:
                        new_qty = Decimal("0")
                        new_entry = fill_price
                        new_side = "FLAT"

            # Cash: release opposing margin simplistically — deduct fee always;
            # for net new margin, debit margin for added notional.
            cash_after = cash - fee
            if not prior or prior["side"] == "FLAT" or _d(prior["qty"]) == 0:
                cash_after -= margin
            elif prior["side"] == pos_side:
                added_notional = qty * fill_price
                cash_after -= added_notional / leverage
            else:
                # On reduce, free margin proportionally; on flip, debit new margin
                prior_notional = _d(prior["qty"]) * _d(prior["entry_price"])
                prior_margin = prior_notional / _d(prior["leverage"] or 1)
                if new_side == "FLAT":
                    cash_after += prior_margin + realized
                elif new_side == prior["side"]:
                    # partial close
                    freed = prior_margin * (min(_d(prior["qty"]), qty) / _d(prior["qty"]))
                    cash_after += freed + realized
                else:
                    # flip
                    cash_after += prior_margin + realized
                    new_margin = (new_qty * new_entry) / leverage
                    cash_after -= new_margin

            self.db.update_cash(portfolio.portfolio_id, cash_after, conn=conn)

            order_id = self.db.insert_order(
                {
                    "portfolio_id": portfolio.portfolio_id,
                    "strategy": strategy_name,
                    "snapshot_id": proposal.snapshot_id,
                    "instrument": instrument,
                    "side": side,
                    "action": action.value,
                    "qty": qty,
                    "leverage": leverage,
                    "limit_price": fill_price,
                    "status": "filled",
                    "rejection_reason": None,
                },
                conn=conn,
            )
            fill_id = self.db.insert_fill(
                {
                    "order_id": order_id,
                    "portfolio_id": portfolio.portfolio_id,
                    "strategy": strategy_name,
                    "snapshot_id": proposal.snapshot_id,
                    "instrument": instrument,
                    "side": side,
                    "qty": qty,
                    "price": fill_price,
                    "fee": fee,
                    "slippage_bps": self.slippage_bps,
                    "realized_pnl": realized,
                },
                conn=conn,
            )

            mark = _d(snapshot.mark_price if snapshot.mark_price is not None else mid_d)
            if new_side == "LONG":
                upnl = (mark - new_entry) * new_qty
            elif new_side == "SHORT":
                upnl = (new_entry - mark) * new_qty
            else:
                upnl = Decimal("0")

            self.db.upsert_position(
                {
                    "portfolio_id": portfolio.portfolio_id,
                    "strategy": strategy_name,
                    "instrument": instrument,
                    "side": new_side,
                    "qty": new_qty,
                    "entry_price": new_entry,
                    "leverage": leverage,
                    "stop_loss": proposal.stop_loss,
                    "take_profits": list(proposal.take_profit_levels),
                    "unrealized_pnl": upnl,
                    "realized_pnl": new_realized_cum,
                    "mark_price": mark,
                },
                conn=conn,
            )

            self.db.insert_strategy_run(
                strategy=strategy_name,
                snapshot_id=proposal.snapshot_id,
                instrument=instrument,
                proposal_json=proposal.to_json_dict(),
                risk_json=risk.model_dump(mode="json"),
                execution_status="filled",
                conn=conn,
            )

            portfolio.record_equity_snapshot(
                marks={instrument: mark},
                conn=conn,
            )

        return {
            "status": "filled",
            "strategy": strategy_name,
            "snapshot_id": proposal.snapshot_id,
            "instrument": instrument,
            "side": side,
            "action": action.value,
            "qty": str(qty),
            "price": str(fill_price),
            "fee": str(fee),
            "slippage_bps": str(self.slippage_bps),
            "leverage": str(leverage),
            "order_id": order_id,
            "fill_id": fill_id,
            "realized_pnl": str(realized),
            "portfolio_id": portfolio.portfolio_id,
        }

    def _rejected(
        self,
        strategy: str,
        proposal: CryptoTradeProposal,
        risk: RiskDecision,
        reason: str,
        *,
        record_run: bool = False,
    ) -> dict[str, Any]:
        if record_run and not self.db.has_strategy_run(strategy, proposal.snapshot_id):
            with self.db.transaction() as conn, contextlib.suppress(Exception):
                self.db.insert_strategy_run(
                    strategy=strategy,
                    snapshot_id=proposal.snapshot_id,
                    instrument=proposal.instrument.display_symbol,
                    proposal_json=proposal.to_json_dict(),
                    risk_json=risk.model_dump(mode="json"),
                    execution_status=f"rejected:{reason}",
                    conn=conn,
                )
        return {
            "status": "rejected",
            "strategy": strategy,
            "snapshot_id": proposal.snapshot_id,
            "reason": reason,
        }
