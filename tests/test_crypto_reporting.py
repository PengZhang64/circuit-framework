"""Crypto report bundle writer tests."""

import json
from pathlib import Path

from tradingagents.reporting import write_crypto_report_bundle, write_report_tree
from tests.crypto_test_utils import make_fresh_snapshot, make_long_proposal
from tradingagents.risk.engine import evaluate_risk


def test_stock_report_tree_still_works(tmp_path):
    state = {
        "market_report": "m",
        "sentiment_report": "s",
        "news_report": "n",
        "fundamentals_report": "f",
        "investment_debate_state": {
            "bull_history": "bull",
            "bear_history": "bear",
            "judge_decision": "hold",
        },
        "trader_investment_plan": "plan",
        "risk_debate_state": {
            "aggressive_history": "a",
            "conservative_history": "c",
            "neutral_history": "n",
            "judge_decision": "Buy",
        },
        "final_trade_decision": "Buy",
    }
    path = write_report_tree(state, "AAPL", tmp_path / "stock")
    assert path.exists()
    assert (tmp_path / "stock" / "1_analysts" / "market.md").exists()


def test_crypto_bundle_files(tmp_path):
    snap = make_fresh_snapshot(mid=100.0, mark=100.0)
    proposal = make_long_proposal(snap, entry=100.0, stop=95.0, tp=110.0, confidence=0.9)
    risk = evaluate_risk(proposal, snap, config={"paper_min_reward_risk": 1.0})
    state = {
        "market_report": "structure",
        "derivatives_report": "derivs",
        "sentiment_report": "sent",
        "catalyst_report": "cat",
        "regime_report": "reg",
        "investment_debate_state": {
            "bull_history": "bull",
            "bear_history": "bear",
            "judge_decision": "plan",
        },
        "trader_investment_plan": proposal.to_markdown(),
        "trade_proposal": proposal.model_dump(mode="json"),
        "risk_decision": risk.model_dump(mode="json"),
        "crypto_snapshot": snap.model_dump(mode="json"),
        "risk_debate_state": {"judge_decision": "PM says go"},
        "final_trade_decision": "LONG",
        "strategy_profile": "balanced",
        "paper_execution_requested": False,
    }
    out = tmp_path / "crypto_run"
    write_crypto_report_bundle(
        state,
        "BTC",
        out,
        config={"llm_provider": "openai", "quick_think_llm": "x", "deep_think_llm": "y"},
        meta={"paper_execution_requested": False},
    )
    expected = [
        "run_metadata.json",
        "market_snapshot.json",
        "market_structure_report.md",
        "derivatives_report.md",
        "sentiment_report.md",
        "catalyst_report.md",
        "regime_report.md",
        "research_debate.md",
        "research_plan.md",
        "trade_proposal.json",
        "trade_proposal.md",
        "portfolio_manager_report.md",
        "risk_decision.json",
        "final_decision.md",
    ]
    for name in expected:
        assert (out / name).exists(), name
    assert not (out / "paper_execution.json").exists()
    meta = json.loads((out / "run_metadata.json").read_text())
    assert meta["asset_type"] == "crypto"
    assert meta["framework_version"]
    assert meta["paper_execution_requested"] is False
    assert (out / "stock_tree" / "complete_report.md").exists()


def test_paper_execution_file_only_when_requested(tmp_path):
    snap = make_fresh_snapshot()
    state = {
        "final_trade_decision": "LONG",
        "trade_proposal": {},
        "risk_decision": {},
        "crypto_snapshot": snap.model_dump(mode="json"),
        "paper_execution_result": {"status": "filled"},
        "paper_execution_requested": True,
    }
    out = tmp_path / "paper_run"
    write_crypto_report_bundle(
        state, "ETH", out, meta={"paper_execution_requested": True}
    )
    assert (out / "paper_execution.json").exists()
