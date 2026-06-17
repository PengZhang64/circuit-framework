"""Typed crypto market and trade schemas for Circuit Framework."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from tradingagents.crypto.instruments import CryptoInstrument


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _reject_nan(value: float | None, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError(f"{field} must not be NaN or infinite")
    return value


class OHLCVCandle(BaseModel):
    model_config = {"frozen": True}

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class OrderBookLevel(BaseModel):
    model_config = {"frozen": True}

    price: float
    size: float


class OrderBookSnapshot(BaseModel):
    model_config = {"frozen": True}

    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    timestamp: datetime | None = None


class DerivativesSnapshot(BaseModel):
    model_config = {"frozen": True}

    funding_rate: float | None = None
    funding_history: list[dict[str, Any]] = Field(default_factory=list)
    open_interest: float | None = None
    open_interest_change_24h_pct: float | None = None
    perpetual_premium: float | None = None
    day_notional_volume: float | None = None
    day_price_change_pct: float | None = None
    long_liquidations: float | None = None
    short_liquidations: float | None = None


class TechnicalSnapshot(BaseModel):
    model_config = {"frozen": True}

    returns_1h: float | None = None
    returns_4h: float | None = None
    returns_24h: float | None = None
    ema_20: float | None = None
    ema_50: float | None = None
    rsi_14: float | None = None
    atr_14: float | None = None
    realized_volatility: float | None = None
    volume_change_pct: float | None = None
    distance_from_ema20_pct: float | None = None
    distance_from_ema50_pct: float | None = None
    order_book_imbalance: float | None = None
    spread_bps: float | None = None
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)


class MarketRegimeSnapshot(BaseModel):
    model_config = {"frozen": True}

    trend: Literal[
        "strong_uptrend", "uptrend", "range", "downtrend", "strong_downtrend"
    ] = "range"
    volatility: Literal["low", "normal", "high", "extreme"] = "normal"
    liquidity: Literal["thin", "normal", "deep"] = "normal"
    risk_mode: Literal["risk_on", "neutral", "risk_off"] = "neutral"
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class DataQuality(BaseModel):
    model_config = {"frozen": True}

    candles_ok: bool = False
    order_book_ok: bool = False
    derivatives_ok: bool = False
    missing_sources: list[str] = Field(default_factory=list)
    max_data_age_seconds: float | None = None
    is_stale: bool = False


class EvidenceItem(BaseModel):
    model_config = {"frozen": True}

    metric: str
    value: str | float | int | None = None
    note: str = ""
    snapshot_id: str | None = None


class CryptoMarketSnapshot(BaseModel):
    model_config = {"frozen": True}

    snapshot_id: str
    timestamp: datetime
    instrument: CryptoInstrument
    mark_price: float | None = None
    mid_price: float | None = None
    oracle_price: float | None = None
    candles: dict[str, list[OHLCVCandle]] = Field(default_factory=dict)
    order_book: OrderBookSnapshot | None = None
    derivatives: DerivativesSnapshot = Field(default_factory=DerivativesSnapshot)
    technical: TechnicalSnapshot = Field(default_factory=TechnicalSnapshot)
    regime: MarketRegimeSnapshot = Field(default_factory=MarketRegimeSnapshot)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    source_timestamps: dict[str, datetime] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def summary_dict(self) -> dict[str, Any]:
        """Concise LLM-safe representation (no raw candle dump)."""
        recent: dict[str, Any] = {}
        for interval, bars in self.candles.items():
            if not bars:
                continue
            tail = bars[-5:]
            recent[interval] = {
                "n": len(bars),
                "last_close": tail[-1].close,
                "last_ts": tail[-1].timestamp.isoformat(),
                "recent_closes": [b.close for b in tail],
            }
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp.isoformat(),
            "instrument": self.instrument.model_dump(),
            "mark_price": self.mark_price,
            "mid_price": self.mid_price,
            "oracle_price": self.oracle_price,
            "technical": self.technical.model_dump(),
            "regime": self.regime.model_dump(),
            "derivatives": {
                k: v
                for k, v in self.derivatives.model_dump().items()
                if k != "funding_history"
            },
            "funding_history_points": len(self.derivatives.funding_history),
            "order_book": {
                "best_bid": self.order_book.bids[0].price if self.order_book and self.order_book.bids else None,
                "best_ask": self.order_book.asks[0].price if self.order_book and self.order_book.asks else None,
                "spread_bps": self.technical.spread_bps,
                "imbalance": self.technical.order_book_imbalance,
            },
            "candle_summary": recent,
            "data_quality": self.data_quality.model_dump(),
            "warnings": list(self.warnings),
        }


class CryptoTradeAction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class CryptoTradeProposal(BaseModel):
    action: CryptoTradeAction
    instrument: CryptoInstrument
    venue: str = "hyperliquid"
    time_horizon: str = "1h"
    entry_min: float | None = None
    entry_max: float | None = None
    stop_loss: float | None = None
    take_profit_levels: list[float] = Field(default_factory=list)
    requested_position_pct: float = 0.0
    requested_leverage: float = 1.0
    confidence: float = 0.0
    thesis: str = ""
    invalidation: str = ""
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    snapshot_id: str
    data_timestamp: datetime
    no_trade_reason: str | None = None

    @field_validator(
        "entry_min",
        "entry_max",
        "stop_loss",
        "requested_position_pct",
        "requested_leverage",
        "confidence",
        mode="before",
    )
    @classmethod
    def _no_nan(cls, v, info):
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return v
        return _reject_nan(f, info.field_name)

    @field_validator("take_profit_levels", mode="before")
    @classmethod
    def _tp_no_nan(cls, v):
        if not v:
            return []
        out = []
        for item in v:
            f = float(item)
            if math.isnan(f) or math.isinf(f):
                raise ValueError("take_profit_levels must not contain NaN or infinite")
            out.append(f)
        return out

    @model_validator(mode="after")
    def _validate_logic(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0 and 1")
        if self.requested_position_pct < 0:
            raise ValueError("requested_position_pct cannot be negative")
        if not self.snapshot_id:
            raise ValueError("snapshot_id is required")

        if self.action == CryptoTradeAction.NO_TRADE:
            if not self.no_trade_reason:
                raise ValueError("NO_TRADE must contain no_trade_reason")
            if self.requested_position_pct > 0:
                raise ValueError("NO_TRADE must not request position size")
            return self

        if self.requested_leverage < 1:
            raise ValueError("leverage must be at least 1 when trading")
        if self.entry_min is None or self.entry_max is None or self.stop_loss is None:
            raise ValueError("LONG/SHORT require entry_min, entry_max, and stop_loss")
        if not self.take_profit_levels:
            raise ValueError("at least one take-profit level is required for LONG or SHORT")

        entry_mid = (self.entry_min + self.entry_max) / 2.0
        if self.action == CryptoTradeAction.LONG and self.stop_loss >= entry_mid:
            raise ValueError("LONG requires stop below entry")
        if self.action == CryptoTradeAction.SHORT and self.stop_loss <= entry_mid:
            raise ValueError("SHORT requires stop above entry")
        return self

    def to_markdown(self) -> str:
        lines = [
            f"# Crypto Trade Proposal — {self.action.value}",
            "",
            f"- Instrument: `{self.instrument.display_symbol}` ({self.venue})",
            f"- Horizon: {self.time_horizon}",
            f"- Confidence: {self.confidence:.2f}",
            f"- Snapshot: `{self.snapshot_id}`",
            f"- Data time: {self.data_timestamp.isoformat()}",
        ]
        if self.action == CryptoTradeAction.NO_TRADE:
            lines.extend(["", f"**No trade:** {self.no_trade_reason}", ""])
        else:
            lines.extend(
                [
                    f"- Entry: {self.entry_min} – {self.entry_max}",
                    f"- Stop: {self.stop_loss}",
                    f"- Take profits: {', '.join(str(x) for x in self.take_profit_levels)}",
                    f"- Requested size: {self.requested_position_pct:.2f}% @ {self.requested_leverage:.2f}x",
                    "",
                    "## Thesis",
                    self.thesis or "_(empty)_",
                    "",
                    "## Invalidation",
                    self.invalidation or "_(empty)_",
                ]
            )
        if self.supporting_evidence:
            lines.append("")
            lines.append("## Evidence")
            for e in self.supporting_evidence:
                lines.append(f"- {e.metric}: {e.value} — {e.note}")
        if self.risks:
            lines.append("")
            lines.append("## Risks")
            for r in self.risks:
                lines.append(f"- {r}")
        return "\n".join(lines) + "\n"

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
