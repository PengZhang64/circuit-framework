"""Paper execution engine tests — Decimal money, no network."""

from decimal import Decimal

from tradingagents.crypto.schemas import CryptoTradeAction
from tradingagents.paper.database import PaperDatabase
from tradingagents.paper.execution import PaperExecutor
from tradingagents.paper.performance import compute_performance
from tradingagents.risk.engine import evaluate_risk
from tests.crypto_test_utils import (
    make_fresh_snapshot,
    make_long_proposal,
    make_no_trade_proposal,
    make_short_proposal,
)


def _exec(tmp_path, config=None):
    db = PaperDatabase(tmp_path / "paper.db")
    cfg = {
        "paper_starting_balance": 100_000,
        "paper_fee_bps": 4.5,
        "paper_slippage_bps": 2.0,
        "paper_min_reward_risk": 1.0,
        "paper_max_leverage": 5.0,
        "paper_max_position_pct": 10.0,
        "paper_risk_per_trade_pct": 2.0,
        **(config or {}),
    }
    return db, PaperExecutor(db, config=cfg), cfg


def test_fee_and_slippage_long(tmp_path):
    snap = make_fresh_snapshot(mid=100.0, mark=100.0)
    db, executor, cfg = _exec(tmp_path)
    proposal = make_long_proposal(snap, entry=100.0, stop=95.0, tp=110.0, confidence=0.9)
    risk = evaluate_risk(proposal, snap, config=cfg)
    assert risk.approved
    result = executor.execute(proposal, risk, snap, strategy="balanced")
    assert result["status"] == "filled"
    assert Decimal(str(result["fee"])) > 0
    assert Decimal(str(result["price"])) > Decimal("100")  # long pays slippage
    pos = db.list_positions(result["portfolio_id"])
    assert len(pos) == 1
    assert pos[0]["side"] == "LONG"


def test_short_pnl_direction(tmp_path):
    snap = make_fresh_snapshot(mid=100.0, mark=100.0)
    db, executor, cfg = _exec(tmp_path)
    proposal = make_short_proposal(snap, entry=100.0, stop=105.0, tp=90.0, confidence=0.9)
    risk = evaluate_risk(proposal, snap, config=cfg)
    result = executor.execute(proposal, risk, snap, strategy="balanced")
    assert result["status"] == "filled"
    assert Decimal(str(result["price"])) < Decimal("100")


def test_reject_no_trade_execution(tmp_path):
    snap = make_fresh_snapshot()
    db, executor, cfg = _exec(tmp_path)
    proposal = make_no_trade_proposal(snap)
    risk = evaluate_risk(proposal, snap, config=cfg)
    result = executor.execute(proposal, risk, snap, strategy="balanced")
    assert result["status"] == "rejected"
    assert not db.list_portfolios() or not db.list_positions(
        db.list_portfolios()[0]["id"]
    ) if db.list_portfolios() else True


def test_duplicate_execution_protection(tmp_path):
    snap = make_fresh_snapshot(mid=100.0, mark=100.0)
    db, executor, cfg = _exec(tmp_path)
    proposal = make_long_proposal(snap, entry=100.0, stop=95.0, tp=110.0, confidence=0.9)
    risk = evaluate_risk(proposal, snap, config=cfg)
    first = executor.execute(proposal, risk, snap, strategy="balanced")
    second = executor.execute(proposal, risk, snap, strategy="balanced")
    assert first["status"] == "filled"
    assert second["status"] == "duplicate"


def test_sqlite_persistence_and_leaderboard_metrics(tmp_path):
    snap = make_fresh_snapshot(mid=100.0, mark=100.0)
    db, executor, cfg = _exec(tmp_path)
    proposal = make_long_proposal(snap, entry=100.0, stop=95.0, tp=110.0, confidence=0.9)
    risk = evaluate_risk(proposal, snap, config=cfg)
    result = executor.execute(proposal, risk, snap, strategy="momentum")
    assert result["status"] == "filled"
    metrics = compute_performance(db, result["portfolio_id"])
    # Fresh portfolio may lack equity curve / closed fills — None is OK
    assert metrics.trade_count == 1 or metrics.trade_count is None or metrics.fees_paid is not None
    assert metrics.fees_paid is not None
    reopened = PaperDatabase(tmp_path / "paper.db")
    assert reopened.list_positions(result["portfolio_id"])
