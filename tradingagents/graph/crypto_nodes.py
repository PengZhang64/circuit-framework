"""Crypto-specific graph nodes: snapshot builder and deterministic risk gate."""

from __future__ import annotations

import logging
from typing import Any

from tradingagents.crypto.schemas import CryptoMarketSnapshot, CryptoTradeProposal
from tradingagents.crypto.snapshot_store import clear_snapshot, get_snapshot, set_snapshot
from tradingagents.dataflows.crypto_interface import get_crypto_market_snapshot
from tradingagents.risk.engine import evaluate_risk
from tradingagents.risk.schemas import RiskDecision

logger = logging.getLogger(__name__)


def _runtime_config(fallback: dict[str, Any] | None) -> dict[str, Any]:
    from tradingagents.dataflows.config import get_config

    try:
        cfg = get_config()
    except Exception:
        cfg = None
    if isinstance(cfg, dict) and cfg:
        return dict(cfg)
    return dict(fallback or {})


def create_snapshot_builder_node(config: dict[str, Any] | None = None):
    """Fetch once, store shared snapshot, and mirror it into graph state."""

    def snapshot_builder_node(state: dict[str, Any]) -> dict[str, Any]:
        clear_snapshot()
        instrument = state.get("company_of_interest") or ""
        _runtime_config(config)  # ensure config layer is warm for crypto_interface
        warnings: list[str] = []

        try:
            snapshot = get_crypto_market_snapshot(instrument)
        except Exception as exc:
            logger.exception("Snapshot Builder failed for %s", instrument)
            warnings.append(f"snapshot fetch failed: {exc}")
            return {
                "crypto_snapshot": {
                    "error": str(exc),
                    "warnings": warnings,
                    "data_quality": {
                        "candles_ok": False,
                        "order_book_ok": False,
                        "derivatives_ok": False,
                        "missing_sources": ["hyperliquid"],
                        "is_stale": True,
                    },
                },
                "sender": "Snapshot Builder",
            }

        set_snapshot(snapshot)
        payload = snapshot.model_dump(mode="json")
        if snapshot.warnings:
            warnings.extend(snapshot.warnings)
        dq = snapshot.data_quality
        if dq.missing_sources:
            warnings.append(
                "missing_sources: " + ", ".join(dq.missing_sources)
            )
        if dq.is_stale:
            warnings.append("snapshot marked stale by data_quality")
        if warnings and not payload.get("warnings"):
            payload["warnings"] = list(warnings)
        elif warnings:
            # Merge builder-side notes without dropping snapshot warnings.
            existing = list(payload.get("warnings") or [])
            for w in warnings:
                if w not in existing:
                    existing.append(w)
            payload["warnings"] = existing

        # Ensure data_quality block remains present for downstream consumers.
        if "data_quality" not in payload:
            payload["data_quality"] = dq.model_dump(mode="json")

        return {
            "crypto_snapshot": payload,
            "sender": "Snapshot Builder",
        }

    return snapshot_builder_node


def _load_proposal(state: dict[str, Any]) -> CryptoTradeProposal | None:
    raw = state.get("trade_proposal")
    if isinstance(raw, CryptoTradeProposal):
        return raw
    if isinstance(raw, dict) and raw:
        try:
            return CryptoTradeProposal.model_validate(raw)
        except Exception as exc:
            logger.warning("Could not validate trade_proposal dict: %s", exc)
    return None


def _load_snapshot(state: dict[str, Any]) -> CryptoMarketSnapshot | None:
    snap = get_snapshot()
    if snap is not None:
        return snap
    raw = state.get("crypto_snapshot")
    if isinstance(raw, CryptoMarketSnapshot):
        return raw
    if isinstance(raw, dict) and raw:
        try:
            return CryptoMarketSnapshot.model_validate(raw)
        except Exception as exc:
            logger.warning("Could not validate crypto_snapshot dict: %s", exc)
    return None


def _compose_final_decision(
    *,
    trader_plan: str,
    pm_view: str,
    risk: RiskDecision,
) -> str:
    parts = [
        "# Final Crypto Decision",
        "",
        "## Trader Proposal",
        trader_plan.strip() or "_(empty)_",
        "",
        "## PM View",
        (pm_view or "").strip() or "_(empty)_",
        "",
        "## Risk Decision",
        risk.to_markdown().strip(),
        "",
        "## Final Approved Action",
        f"**{risk.final_action.value}**",
        f"- Approved: {'yes' if risk.approved else 'no'}",
        f"- Position: {risk.approved_position_pct:.4f}%",
        f"- Leverage: {risk.approved_leverage:.2f}x",
    ]
    if risk.rejection_reasons:
        parts.append("- Rejection: " + "; ".join(risk.rejection_reasons))
    return "\n".join(parts) + "\n"


def _maybe_paper_execute(
    *,
    proposal: CryptoTradeProposal,
    risk: RiskDecision,
    snapshot: CryptoMarketSnapshot | None,
    config: dict[str, Any],
    strategy_profile: str,
) -> dict[str, Any] | None:
    if snapshot is None:
        return {
            "status": "skipped",
            "reason": "no market snapshot available for paper execution",
        }
    try:
        from tradingagents.paper.database import PaperDatabase
        from tradingagents.paper.execution import PaperExecutor

        db_path = config.get("paper_database_path")
        if not db_path:
            return {
                "status": "skipped",
                "reason": "paper_database_path not configured",
            }
        db = PaperDatabase(db_path)
        executor = PaperExecutor(db, config=config)
        return executor.execute(
            proposal,
            risk,
            snapshot,
            strategy=strategy_profile or None,
        )
    except Exception as exc:
        logger.exception("Paper execution failed")
        return {
            "status": "error",
            "reason": str(exc),
        }


def create_deterministic_risk_gate_node(config: dict[str, Any] | None = None):
    """Final authority after Portfolio Manager: evaluate_risk (+ optional paper)."""

    def risk_gate_node(state: dict[str, Any]) -> dict[str, Any]:
        cfg = _runtime_config(config)
        proposal = _load_proposal(state)
        snapshot = _load_snapshot(state)
        pm_view = state.get("final_trade_decision") or ""
        trader_plan = state.get("trader_investment_plan") or ""

        if proposal is None:
            # Soft reject: no structured proposal → treat as NO_TRADE path.
            from datetime import datetime, timezone

            from tradingagents.crypto.instruments import parse_crypto_instrument
            from tradingagents.crypto.schemas import CryptoTradeAction

            instrument_raw = state.get("company_of_interest") or "BTC"
            try:
                instrument = parse_crypto_instrument(
                    instrument_raw,
                    venue=str(cfg.get("crypto_venue", "hyperliquid")),
                    instrument_type=cfg.get("crypto_instrument_type", "perp"),
                    quote_currency=str(cfg.get("crypto_quote_currency", "USDG")),
                )
            except Exception:
                from tradingagents.crypto.instruments import CryptoInstrument

                instrument = CryptoInstrument(
                    base_asset="BTC",
                    venue_symbol="BTC",
                    display_symbol=str(instrument_raw),
                )
            snap_id = ""
            data_ts = datetime.now(timezone.utc)
            if snapshot is not None:
                snap_id = snapshot.snapshot_id
                data_ts = snapshot.timestamp
            if not snap_id:
                snap_id = "missing"
            proposal = CryptoTradeProposal(
                action=CryptoTradeAction.NO_TRADE,
                instrument=instrument,
                snapshot_id=snap_id,
                data_timestamp=data_ts,
                no_trade_reason="missing structured CryptoTradeProposal in state",
                thesis=trader_plan[:500] if trader_plan else "",
            )

        risk = evaluate_risk(proposal, snapshot, cfg)
        risk_dict = risk.model_dump(mode="json")
        final_md = _compose_final_decision(
            trader_plan=trader_plan or proposal.to_markdown(),
            pm_view=pm_view,
            risk=risk,
        )

        updates: dict[str, Any] = {
            "risk_decision": risk_dict,
            "final_trade_decision": final_md,
            "sender": "Deterministic Risk Gate",
        }

        if state.get("paper_execution_requested"):
            strategy = (
                state.get("strategy_profile")
                or cfg.get("strategy_profile")
                or cfg.get("default_crypto_strategy")
                or "balanced"
            )
            updates["paper_execution_result"] = _maybe_paper_execute(
                proposal=proposal,
                risk=risk,
                snapshot=snapshot,
                config=cfg,
                strategy_profile=str(strategy),
            )

        return updates

    return risk_gate_node
