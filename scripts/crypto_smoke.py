#!/usr/bin/env python3
"""Runnable crypto smoke without pytest (fixture-backed, no network/LLM)."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.crypto.instruments import parse_crypto_instrument  # noqa: E402
from tradingagents.crypto.schemas import (  # noqa: E402
    CryptoTradeAction,
    CryptoTradeProposal,
    DataQuality,
)
from tradingagents.dataflows.hyperliquid import HyperliquidClient  # noqa: E402
from tradingagents.paper.database import PaperDatabase  # noqa: E402
from tradingagents.paper.execution import PaperExecutor  # noqa: E402
from tradingagents.risk.engine import evaluate_risk  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "hyperliquid"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def main() -> int:
    client = HyperliquidClient(
        cache_ttl_seconds=0,
        analysis_intervals=["1h"],
        max_data_age_seconds=10**9,
    )
    meta = _load("meta_and_asset_ctxs.json")
    candles = _load("candle_snapshot_btc_1h.json")
    book = _load("l2_book_btc.json")
    funding = _load("funding_history_btc.json")

    def _post(body, *, use_cache=True):
        typ = body.get("type")
        if typ == "metaAndAssetCtxs":
            return meta
        if typ == "candleSnapshot":
            return candles
        if typ == "l2Book":
            return book
        if typ == "fundingHistory":
            return funding
        raise RuntimeError(f"unexpected request {body}")

    client._post = _post  # type: ignore[method-assign]

    print("1) Building BTC snapshot from fixtures…")
    snap = client.get_market_snapshot(parse_crypto_instrument("BTC"), intervals=["1h"])
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
    mid = float(snap.mid_price or snap.mark_price)
    print(f"   mid={mid} snapshot_id={snap.snapshot_id}")

    print("2) Building LONG proposal…")
    proposal = CryptoTradeProposal(
        action=CryptoTradeAction.LONG,
        instrument=snap.instrument,
        entry_min=mid * 0.999,
        entry_max=mid * 1.001,
        stop_loss=mid * 0.97,
        take_profit_levels=[mid * 1.06],
        requested_position_pct=5.0,
        requested_leverage=2.0,
        confidence=0.85,
        thesis="smoke",
        invalidation="smoke",
        snapshot_id=snap.snapshot_id,
        data_timestamp=snap.timestamp,
    )

    print("3) Risk evaluation…")
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
    risk = evaluate_risk(proposal, snap, config=cfg)
    if not risk.approved:
        print("FAIL risk:", risk.rejection_reasons)
        return 1
    print(f"   approved size={risk.approved_position_pct}% lev={risk.approved_leverage}")

    print("4) Paper execute…")
    with tempfile.TemporaryDirectory() as td:
        db = PaperDatabase(Path(td) / "smoke.db")
        result = PaperExecutor(db, config=cfg).execute(
            proposal, risk, snap, strategy="balanced"
        )
        if result.get("status") != "filled":
            print("FAIL execute:", result)
            return 1
        positions = db.list_positions(result["portfolio_id"])
        print("5) Position:", positions[0] if positions else None)
        assert positions and Decimal(str(positions[0]["qty"])) > 0

    print("OK — crypto smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
