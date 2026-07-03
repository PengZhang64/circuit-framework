"""Pydantic schemas for paper portfolio state."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class PortfolioRecord(BaseModel):
    id: int | None = None
    name: str
    strategy: str
    cash_balance: Decimal
    starting_balance: Decimal
    created_at: datetime
    updated_at: datetime


class OrderRecord(BaseModel):
    id: int | None = None
    portfolio_id: int
    strategy: str
    snapshot_id: str
    instrument: str
    side: Literal["BUY", "SELL"]
    action: Literal["LONG", "SHORT", "FLAT"]
    qty: Decimal
    leverage: Decimal
    limit_price: Decimal | None = None
    status: Literal["pending", "filled", "rejected", "cancelled"]
    rejection_reason: str | None = None
    created_at: datetime


class FillRecord(BaseModel):
    id: int | None = None
    order_id: int
    portfolio_id: int
    strategy: str
    snapshot_id: str
    instrument: str
    side: Literal["BUY", "SELL"]
    qty: Decimal
    price: Decimal
    fee: Decimal
    slippage_bps: Decimal
    realized_pnl: Decimal
    created_at: datetime


class PositionRecord(BaseModel):
    id: int | None = None
    portfolio_id: int
    strategy: str
    instrument: str
    side: Literal["LONG", "SHORT", "FLAT"]
    qty: Decimal
    entry_price: Decimal
    leverage: Decimal
    stop_loss: Decimal | None = None
    take_profits: list[float] = Field(default_factory=list)
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    mark_price: Decimal | None = None
    opened_at: datetime
    updated_at: datetime


class EquitySnapshot(BaseModel):
    id: int | None = None
    portfolio_id: int
    strategy: str
    equity: Decimal
    cash_balance: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    created_at: datetime


class StrategyRunRecord(BaseModel):
    id: int | None = None
    strategy: str
    snapshot_id: str
    instrument: str
    proposal_json: dict[str, Any]
    risk_json: dict[str, Any]
    execution_status: str
    created_at: datetime


class PerformanceMetrics(BaseModel):
    total_return: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    maximum_drawdown: float | None = None
    sharpe_ratio: float | None = None
    average_leverage: float | None = None
    fees_paid: float | None = None
    trade_count: int | None = None
