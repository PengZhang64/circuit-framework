"""Tests for crypto Pydantic schemas."""

from datetime import datetime, timezone

import pytest

from tradingagents.crypto.instruments import parse_crypto_instrument
from tradingagents.crypto.schemas import (
    CryptoMarketSnapshot,
    CryptoTradeAction,
    CryptoTradeProposal,
    DataQuality,
    OHLCVCandle,
)


def test_ohlcv_candle_immutable():
    c = OHLCVCandle(
        timestamp=datetime.now(timezone.utc),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
    )
    with pytest.raises(Exception):
        c.close = 99.0  # type: ignore[misc]


def test_long_validation_requires_stop_below_entry():
    inst = parse_crypto_instrument("BTC")
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="stop below"):
        CryptoTradeProposal(
            action=CryptoTradeAction.LONG,
            instrument=inst,
            entry_min=100,
            entry_max=101,
            stop_loss=110,
            take_profit_levels=[120],
            requested_position_pct=5,
            requested_leverage=2,
            confidence=0.7,
            snapshot_id="s1",
            data_timestamp=now,
        )


def test_short_validation_requires_stop_above_entry():
    inst = parse_crypto_instrument("BTC")
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="stop above"):
        CryptoTradeProposal(
            action=CryptoTradeAction.SHORT,
            instrument=inst,
            entry_min=100,
            entry_max=101,
            stop_loss=90,
            take_profit_levels=[80],
            requested_position_pct=5,
            requested_leverage=2,
            confidence=0.7,
            snapshot_id="s1",
            data_timestamp=now,
        )


def test_no_trade_requires_reason_and_zero_size():
    inst = parse_crypto_instrument("ETH")
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="no_trade_reason"):
        CryptoTradeProposal(
            action=CryptoTradeAction.NO_TRADE,
            instrument=inst,
            snapshot_id="s1",
            data_timestamp=now,
            confidence=0.3,
        )
    with pytest.raises(ValueError, match="position size"):
        CryptoTradeProposal(
            action=CryptoTradeAction.NO_TRADE,
            instrument=inst,
            snapshot_id="s1",
            data_timestamp=now,
            confidence=0.3,
            no_trade_reason="wait",
            requested_position_pct=1.0,
        )


def test_snapshot_summary_dict():
    inst = parse_crypto_instrument("BTC")
    now = datetime.now(timezone.utc)
    snap = CryptoMarketSnapshot(
        snapshot_id="abc",
        timestamp=now,
        instrument=inst,
        mark_price=100.0,
        candles={
            "1h": [
                OHLCVCandle(
                    timestamp=now, open=1, high=2, low=0.5, close=1.5, volume=1
                )
            ]
        },
        data_quality=DataQuality(candles_ok=True),
    )
    summary = snap.summary_dict()
    assert summary["snapshot_id"] == "abc"
    assert "1h" in summary["candle_summary"]
    assert snap.model_config.get("frozen") is True
