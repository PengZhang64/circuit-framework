"""Reusable report-tree writer shared by the CLI and the programmatic API.

Writes a run's per-section markdown (analysts, research, trading, risk,
portfolio) plus a consolidated ``complete_report.md`` under ``save_path``. The
CLI and ``TradingAgentsGraph.save_reports`` both call this, so a headless / API
run produces the same on-disk report tree a CLI run does.

Crypto runs additionally write a flat Circuit Framework audit bundle
(``write_crypto_report_bundle``) per the reporting contract.
"""

from __future__ import annotations

import json
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_report_tree(final_state: dict, ticker: str, save_path) -> Path:
    """Save a completed run's reports to ``save_path``; return the complete-report path."""
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("market_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "market.md").write_text(final_state["market_report"], encoding="utf-8")
        analyst_parts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"], encoding="utf-8")
        analyst_parts.append(("Sentiment Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "news.md").write_text(final_state["news_report"], encoding="utf-8")
        analyst_parts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"], encoding="utf-8")
        analyst_parts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    # Crypto analysts
    if final_state.get("derivatives_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "derivatives.md").write_text(
            final_state["derivatives_report"], encoding="utf-8"
        )
        analyst_parts.append(("Derivatives Analyst", final_state["derivatives_report"]))
    if final_state.get("catalyst_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "catalyst.md").write_text(
            final_state["catalyst_report"], encoding="utf-8"
        )
        analyst_parts.append(("Catalyst Analyst", final_state["catalyst_report"]))
    if final_state.get("regime_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "regime.md").write_text(final_state["regime_report"], encoding="utf-8")
        analyst_parts.append(("Regime Analyst", final_state["regime_report"]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bull.md").write_text(debate["bull_history"], encoding="utf-8")
            research_parts.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bear.md").write_text(debate["bear_history"], encoding="utf-8")
            research_parts.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "manager.md").write_text(debate["judge_decision"], encoding="utf-8")
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{final_state['trader_investment_plan']}")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "aggressive.md").write_text(risk["aggressive_history"], encoding="utf-8")
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "conservative.md").write_text(risk["conservative_history"], encoding="utf-8")
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "neutral.md").write_text(risk["neutral_history"], encoding="utf-8")
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(risk["judge_decision"], encoding="utf-8")
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{risk['judge_decision']}")

    # Write consolidated report
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    (save_path / "complete_report.md").write_text(header + "\n\n".join(sections), encoding="utf-8")
    return save_path / "complete_report.md"


def _framework_version() -> str:
    try:
        from tradingagents.__version__ import __version__

        return __version__
    except Exception:
        return "0.3.1"


def _json_dump(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _md_write(path: Path, content: str | None, fallback: str = "_(empty)_\n") -> None:
    path.write_text((content if content else fallback), encoding="utf-8")


def write_crypto_report_bundle(
    final_state: dict,
    ticker: str,
    save_path,
    config: dict | None = None,
    meta: dict | None = None,
) -> Path:
    """Write the flat Circuit Framework crypto report bundle under ``save_path``.

    Also writes the stock-style tree subdirectory ``stock_tree/`` when useful,
    without replacing the flat audit files.
    """
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    cfg = dict(config or {})
    extra = dict(meta or {})
    now = datetime.now(timezone.utc)

    proposal = final_state.get("trade_proposal")
    risk = final_state.get("risk_decision")
    snapshot = final_state.get("crypto_snapshot")
    paper_requested = bool(
        extra.get("paper_execution_requested")
        or final_state.get("paper_execution_requested")
    )

    snapshot_id = None
    snapshot_ts = None
    canonical = None
    if isinstance(snapshot, dict):
        snapshot_id = snapshot.get("snapshot_id")
        snapshot_ts = snapshot.get("timestamp")
        inst = snapshot.get("instrument")
        if isinstance(inst, dict):
            canonical = inst
    elif snapshot is not None and hasattr(snapshot, "model_dump"):
        dumped = snapshot.model_dump(mode="json")
        snapshot_id = dumped.get("snapshot_id")
        snapshot_ts = dumped.get("timestamp")
        canonical = dumped.get("instrument")
        snapshot = dumped

    if isinstance(proposal, dict):
        proposal_dict = proposal
    elif proposal is not None and hasattr(proposal, "model_dump"):
        proposal_dict = proposal.model_dump(mode="json")
    else:
        proposal_dict = None

    if isinstance(risk, dict):
        risk_dict = risk
    elif risk is not None and hasattr(risk, "model_dump"):
        risk_dict = risk.model_dump(mode="json")
    else:
        risk_dict = None

    run_id = extra.get("run_id") or str(uuid.uuid4())
    strategy = (
        extra.get("strategy")
        or final_state.get("strategy_profile")
        or cfg.get("strategy_profile")
        or cfg.get("default_crypto_strategy")
        or "balanced"
    )
    venue = (
        extra.get("venue")
        or (canonical or {}).get("venue")
        or cfg.get("crypto_venue")
        or "hyperliquid"
    )

    metadata = {
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "symbol": ticker,
        "canonical_instrument": canonical,
        "venue": venue,
        "strategy": strategy,
        "analysis_timestamp": now.isoformat(),
        "snapshot_timestamp": snapshot_ts,
        "asset_type": "crypto",
        "model_provider": cfg.get("llm_provider"),
        "quick_model": cfg.get("quick_think_llm"),
        "deep_model": cfg.get("deep_think_llm"),
        "framework_version": _framework_version(),
        "paper_execution_requested": paper_requested,
    }
    # Never dump env / secrets
    for key in list(metadata):
        if key.endswith("_key") or "secret" in key.lower() or "password" in key.lower():
            metadata.pop(key, None)

    _json_dump(save_path / "run_metadata.json", metadata)

    if snapshot is not None:
        if hasattr(snapshot, "model_dump"):
            _json_dump(save_path / "market_snapshot.json", snapshot.model_dump(mode="json"))
        else:
            _json_dump(save_path / "market_snapshot.json", snapshot)
    else:
        _json_dump(save_path / "market_snapshot.json", {})

    # Market-structure report uses the market analyst output for crypto mode
    _md_write(save_path / "market_structure_report.md", final_state.get("market_report"))
    _md_write(save_path / "derivatives_report.md", final_state.get("derivatives_report"))
    _md_write(save_path / "sentiment_report.md", final_state.get("sentiment_report"))
    _md_write(save_path / "catalyst_report.md", final_state.get("catalyst_report"))
    _md_write(save_path / "regime_report.md", final_state.get("regime_report"))

    debate = final_state.get("investment_debate_state") or {}
    debate_md_parts = []
    if debate.get("bull_history"):
        debate_md_parts.append(f"## Bull\n\n{debate['bull_history']}")
    if debate.get("bear_history"):
        debate_md_parts.append(f"## Bear\n\n{debate['bear_history']}")
    if debate.get("history"):
        debate_md_parts.append(f"## History\n\n{debate['history']}")
    _md_write(
        save_path / "research_debate.md",
        "\n\n".join(debate_md_parts) if debate_md_parts else None,
    )
    _md_write(
        save_path / "research_plan.md",
        debate.get("judge_decision") or final_state.get("investment_plan"),
    )

    if proposal_dict is not None:
        _json_dump(save_path / "trade_proposal.json", proposal_dict)
        # Prefer structured markdown when available
        md = None
        if proposal is not None and hasattr(proposal, "to_markdown"):
            md = proposal.to_markdown()
        elif final_state.get("trader_investment_plan"):
            md = final_state["trader_investment_plan"]
        else:
            md = "```json\n" + json.dumps(proposal_dict, indent=2, default=str) + "\n```\n"
        _md_write(save_path / "trade_proposal.md", md)
    else:
        _json_dump(save_path / "trade_proposal.json", {})
        _md_write(
            save_path / "trade_proposal.md",
            final_state.get("trader_investment_plan"),
        )

    risk_state = final_state.get("risk_debate_state") or {}
    _md_write(
        save_path / "portfolio_manager_report.md",
        risk_state.get("judge_decision") or final_state.get("final_trade_decision"),
    )

    if risk_dict is not None:
        _json_dump(save_path / "risk_decision.json", risk_dict)
    else:
        _json_dump(save_path / "risk_decision.json", {})

    _md_write(save_path / "final_decision.md", final_state.get("final_trade_decision"))

    if paper_requested:
        paper_result = final_state.get("paper_execution_result") or {}
        _json_dump(save_path / "paper_execution.json", paper_result)
    else:
        paper_path = save_path / "paper_execution.json"
        if paper_path.exists():
            paper_path.unlink()

    # Also write stock-style tree (useful for reading) without replacing flat files
    with suppress(Exception):
        write_report_tree(final_state, ticker, save_path / "stock_tree")

    return save_path / "run_metadata.json"
