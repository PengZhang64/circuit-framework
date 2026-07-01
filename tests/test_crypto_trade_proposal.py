"""Structured crypto trade proposal validation tests."""

from datetime import datetime, timezone

import pytest

from tradingagents.crypto.instruments import parse_crypto_instrument
from tradingagents.crypto.schemas import CryptoTradeAction, CryptoTradeProposal
from tests.crypto_test_utils import (
    make_fresh_snapshot,
    make_long_proposal,
    make_no_trade_proposal,
    make_short_proposal,
)


def test_valid_long_proposal():
    snap = make_fresh_snapshot()
    p = make_long_proposal(snap)
    assert p.action == CryptoTradeAction.LONG
    assert p.stop_loss < (p.entry_min + p.entry_max) / 2
    assert p.take_profit_levels
    md = p.to_markdown()
    assert "LONG" in md
    assert p.to_json_dict()["action"] == "LONG"


def test_valid_short_proposal():
    snap = make_fresh_snapshot()
    p = make_short_proposal(snap)
    assert p.action == CryptoTradeAction.SHORT
    assert p.stop_loss > (p.entry_min + p.entry_max) / 2


def test_valid_no_trade():
    snap = make_fresh_snapshot()
    p = make_no_trade_proposal(snap)
    assert p.action == CryptoTradeAction.NO_TRADE
    assert p.no_trade_reason
    assert p.requested_position_pct == 0


def test_nan_rejected():
    inst = parse_crypto_instrument("BTC")
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        CryptoTradeProposal(
            action=CryptoTradeAction.LONG,
            instrument=inst,
            entry_min=float("nan"),
            entry_max=100,
            stop_loss=90,
            take_profit_levels=[110],
            requested_position_pct=5,
            requested_leverage=2,
            confidence=0.8,
            snapshot_id="x",
            data_timestamp=now,
        )
