"""End-to-end crypto smoke: fixture → snapshot → proposal → risk → paper."""

from decimal import Decimal

from tradingagents.crypto.instruments import parse_crypto_instrument
from tradingagents.dataflows.hyperliquid import HyperliquidClient
from tradingagents.paper.database import PaperDatabase
from tradingagents.paper.execution import PaperExecutor
from tradingagents.risk.engine import evaluate_risk
from tests.crypto_test_utils import install_hyperliquid_fixtures, make_long_proposal


def test_crypto_smoke_vertical_slice(tmp_path, monkeypatch):
    client = HyperliquidClient(
        cache_ttl_seconds=0,
        analysis_intervals=["1h"],
        max_data_age_seconds=10**9,
    )
    install_hyperliquid_fixtures(monkeypatch, client)

    # 1. Load BTC fixture → build snapshot
    snap = client.get_market_snapshot(parse_crypto_instrument("BTC"), intervals=["1h"])
    assert snap.mark_price is not None
    assert snap.data_quality.candles_ok

    # 2. Build valid LONG proposal from mid
    mid = snap.mid_price or snap.mark_price
    proposal = make_long_proposal(
        snap,
        entry=mid,
        stop=mid * 0.97,
        tp=mid * 1.06,
        confidence=0.85,
        position_pct=5.0,
        leverage=2.0,
    )
    assert proposal.action.value == "LONG"

    # 3. Risk engine approve
    cfg = {
        "paper_min_reward_risk": 1.0,
        "paper_max_leverage": 5.0,
        "paper_max_position_pct": 10.0,
        "paper_risk_per_trade_pct": 2.0,
        "crypto_max_data_age_seconds": 10**9,
        "paper_starting_balance": 100_000,
        "paper_fee_bps": 4.5,
        "paper_slippage_bps": 2.0,
    }
    # Force non-stale for smoke
    from tradingagents.crypto.schemas import DataQuality
    from datetime import datetime, timezone

    snap = snap.model_copy(
        update={
            "timestamp": datetime.now(timezone.utc),
            "data_quality": DataQuality(
                candles_ok=True,
                order_book_ok=True,
                derivatives_ok=True,
                is_stale=False,
                max_data_age_seconds=1.0,
            ),
        }
    )
    risk = evaluate_risk(proposal, snap, config=cfg)
    assert risk.approved, risk.rejection_reasons

    # 4. Paper execute in temp db
    db = PaperDatabase(tmp_path / "smoke.db")
    executor = PaperExecutor(db, config=cfg)
    result = executor.execute(proposal, risk, snap, strategy="balanced")
    assert result["status"] == "filled"

    # 5. Read position back
    positions = db.list_positions(result["portfolio_id"])
    assert len(positions) == 1
    assert positions[0]["instrument"] == snap.instrument.display_symbol
    assert positions[0]["side"] == "LONG"
    assert Decimal(str(positions[0]["qty"])) > 0
