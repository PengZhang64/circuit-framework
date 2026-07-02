"""Deterministic risk engine unit tests."""

from datetime import datetime, timedelta, timezone

from tradingagents.crypto.schemas import CryptoTradeAction, DataQuality
from tradingagents.risk.engine import evaluate_risk
from tests.crypto_test_utils import (
    make_fresh_snapshot,
    make_long_proposal,
    make_no_trade_proposal,
    make_short_proposal,
)


def test_preserve_no_trade():
    snap = make_fresh_snapshot()
    decision = evaluate_risk(make_no_trade_proposal(snap), snap)
    assert decision.approved
    assert decision.final_action == CryptoTradeAction.NO_TRADE
    assert decision.approved_position_pct == 0


def test_reject_poor_reward_risk():
    snap = make_fresh_snapshot(mid=100.0, mark=100.0, spread_bps=2.0)
    # stop 1 away, tp 1 away -> RR = 1.0 < 1.5
    p = make_long_proposal(snap, entry=100.0, stop=99.0, tp=101.0, confidence=0.8)
    decision = evaluate_risk(p, snap, config={"paper_min_reward_risk": 1.5})
    assert not decision.approved
    assert any("reward-to-risk" in r for r in decision.rejection_reasons)


def test_reject_invalid_stop_via_risk_path():
    """Risk rejects logically invalid stops even if a raw dict slips through."""
    snap = make_fresh_snapshot(mid=100.0, mark=100.0)
    from tradingagents.crypto.schemas import CryptoTradeProposal, CryptoTradeAction

    mutated = CryptoTradeProposal.model_construct(
        action=CryptoTradeAction.LONG,
        instrument=snap.instrument,
        venue="hyperliquid",
        time_horizon="1h",
        entry_min=99.0,
        entry_max=101.0,
        stop_loss=105.0,
        take_profit_levels=[120.0],
        requested_position_pct=5.0,
        requested_leverage=2.0,
        confidence=0.9,
        thesis="x",
        invalidation="y",
        supporting_evidence=[],
        risks=[],
        snapshot_id=snap.snapshot_id,
        data_timestamp=snap.timestamp,
        no_trade_reason=None,
    )
    decision = evaluate_risk(
        mutated,
        snap,
        config={"paper_min_reward_risk": 0.1, "crypto_max_data_age_seconds": 10**9},
    )
    assert not decision.approved
    assert any("stop" in r.lower() for r in decision.rejection_reasons)


def test_leverage_clamping():
    snap = make_fresh_snapshot(mid=100.0, mark=100.0)
    p = make_long_proposal(
        snap, entry=100.0, stop=95.0, tp=110.0, leverage=20.0, confidence=0.9
    )
    decision = evaluate_risk(
        p, snap, config={"paper_max_leverage": 3.0, "paper_min_reward_risk": 1.0}
    )
    assert decision.approved
    assert decision.approved_leverage == 3.0
    assert any("clamped leverage" in a for a in decision.adjustments)


def test_position_size_clamping():
    snap = make_fresh_snapshot(mid=100.0, mark=100.0)
    p = make_long_proposal(
        snap,
        entry=100.0,
        stop=95.0,
        tp=110.0,
        position_pct=50.0,
        leverage=2.0,
        confidence=0.9,
    )
    decision = evaluate_risk(
        p,
        snap,
        config={
            "paper_max_position_pct": 10.0,
            "paper_min_reward_risk": 1.0,
            "paper_risk_per_trade_pct": 5.0,
        },
    )
    assert decision.approved
    assert decision.approved_position_pct <= 10.0


def test_high_volatility_size_reduction():
    snap = make_fresh_snapshot(
        mid=100.0, mark=100.0, realized_vol=0.04, volatility="high"
    )
    p = make_long_proposal(
        snap, entry=100.0, stop=95.0, tp=115.0, position_pct=10.0, confidence=0.9
    )
    decision = evaluate_risk(
        p,
        snap,
        config={
            "paper_min_reward_risk": 1.0,
            "paper_max_position_pct": 10.0,
            "paper_risk_per_trade_pct": 10.0,
        },
    )
    assert decision.approved
    assert any("volatil" in a.lower() for a in decision.adjustments)


def test_stale_data_rejection():
    snap = make_fresh_snapshot(stale=True)
    # Also age the timestamp
    object.__setattr__(
        snap,
        "timestamp",
        datetime.now(timezone.utc) - timedelta(hours=1),
    )
    # frozen model — rebuild instead
    from tradingagents.crypto.schemas import CryptoMarketSnapshot

    stale = snap.model_copy(
        update={
            "timestamp": datetime.now(timezone.utc) - timedelta(hours=1),
            "data_quality": DataQuality(
                candles_ok=True,
                order_book_ok=True,
                derivatives_ok=True,
                is_stale=True,
                max_data_age_seconds=9999.0,
            ),
        }
    )
    p = make_long_proposal(stale, entry=100.0, stop=95.0, tp=110.0)
    decision = evaluate_risk(p, stale, config={"crypto_max_data_age_seconds": 180})
    assert not decision.approved
    assert any("stale" in r.lower() or "age" in r.lower() for r in decision.rejection_reasons)


def test_short_approved_path():
    snap = make_fresh_snapshot(mid=100.0, mark=100.0)
    p = make_short_proposal(snap, entry=100.0, stop=105.0, tp=90.0, confidence=0.85)
    decision = evaluate_risk(p, snap, config={"paper_min_reward_risk": 1.0})
    assert decision.approved
    assert decision.final_action == CryptoTradeAction.SHORT
