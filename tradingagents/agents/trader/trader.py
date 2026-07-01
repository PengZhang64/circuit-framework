"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

import functools
import logging

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    CryptoTradeProposal,
    TraderProposal,
    render_trader_proposal,
)
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)

logger = logging.getLogger(__name__)


def _crypto_reports_block(state: dict) -> str:
    parts = [
        ("Market Structure", state.get("market_report") or ""),
        ("Derivatives", state.get("derivatives_report") or ""),
        ("Sentiment", state.get("sentiment_report") or ""),
        ("Catalyst", state.get("catalyst_report") or ""),
        ("Regime", state.get("regime_report") or ""),
    ]
    blocks = []
    for title, body in parts:
        if body:
            blocks.append(f"### {title}\n{body}")
    return "\n\n".join(blocks) if blocks else "_(no analyst reports)_"


def _invoke_crypto_proposal(structured_llm, plain_llm, messages) -> tuple[str, dict | None]:
    """Return (markdown, json_dict) for a crypto trade proposal."""
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(messages)
            if result is None:
                raise ValueError("structured output returned no parsed result")
            if isinstance(result, CryptoTradeProposal):
                return result.to_markdown(), result.to_json_dict()
            # Some providers wrap as dict-like / adapter
            proposal = CryptoTradeProposal.model_validate(result)
            return proposal.to_markdown(), proposal.to_json_dict()
        except Exception as exc:
            logger.warning(
                "Crypto Trader: structured-output invocation failed (%s); "
                "retrying once as free text",
                exc,
            )

    response = plain_llm.invoke(messages)
    content = response.content if hasattr(response, "content") else str(response)
    return content, None


def create_trader(llm):
    stock_structured_llm = bind_structured(llm, TraderProposal, "Trader")
    crypto_structured_llm = bind_structured(llm, CryptoTradeProposal, "Crypto Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        investment_plan = state["investment_plan"]
        is_crypto = state.get("asset_type") == "crypto"

        if is_crypto:
            snapshot = state.get("crypto_snapshot") or {}
            snapshot_id = ""
            data_ts = ""
            if isinstance(snapshot, dict):
                snapshot_id = snapshot.get("snapshot_id") or ""
                data_ts = snapshot.get("timestamp") or ""
            strategy_overlay = ""
            if state.get("strategy_profile"):
                strategy_overlay = (
                    f"\nActive strategy profile: {state.get('strategy_profile')}.\n"
                )
            # Prefer overlay from config if present in state-adjacent sources
            from tradingagents.dataflows.config import get_config

            cfg = get_config() or {}
            prompt_overlay = cfg.get("strategy_prompt_overlay") or ""
            if prompt_overlay:
                strategy_overlay += f"Strategy guidance: {prompt_overlay}\n"

            reports = _crypto_reports_block(state)
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a crypto perpetual-futures trading agent. Produce a "
                        "CryptoTradeProposal. LONG / SHORT / NO_TRADE are all valid — "
                        "explicitly prefer NO_TRADE when conviction, data quality, or "
                        "regime does not support a directional trade. Do not force a "
                        "directional recommendation.\n"
                        "Cite supporting_evidence by metric name and snapshot_id "
                        f"(expected snapshot_id={snapshot_id!r}, data_timestamp={data_ts!r}). "
                        "Entry, stop, and take-profits must be consistent with the "
                        "action; NO_TRADE requires no_trade_reason and zero position size."
                        + strategy_overlay
                        + get_language_instruction()
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Instrument: {company_name}. {instrument_context}\n\n"
                        f"Research Manager plan:\n{investment_plan}\n\n"
                        f"Analyst reports:\n{reports}\n\n"
                        "Return a structured CryptoTradeProposal grounded in the "
                        "reports and the shared snapshot identity above."
                    ),
                },
            ]
            trader_plan, trade_proposal = _invoke_crypto_proposal(
                crypto_structured_llm, llm, messages
            )
            return {
                "messages": [AIMessage(content=trader_plan)],
                "trader_investment_plan": trader_plan,
                "trade_proposal": trade_proposal,
                "sender": name,
            }

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    "Anchor your reasoning in the analysts' reports and the research plan."
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Based on a comprehensive analysis by a team of analysts, here is an investment "
                    f"plan tailored for {company_name}. {instrument_context} This plan incorporates "
                    f"insights from current technical market trends, macroeconomic indicators, and "
                    f"social media sentiment. Use this plan as a foundation for evaluating your next "
                    f"trading decision.\n\nProposed Investment Plan: {investment_plan}\n\n"
                    f"Leverage these insights to make an informed and strategic decision."
                ),
            },
        ]

        trader_plan = invoke_structured_or_freetext(
            stock_structured_llm,
            llm,
            messages,
            render_trader_proposal,
            "Trader",
        )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
