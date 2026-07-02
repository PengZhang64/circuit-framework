"""Deterministic risk engine — final authority on crypto trade proposals."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from tradingagents.crypto.schemas import (
    CryptoMarketSnapshot,
    CryptoTradeAction,
    CryptoTradeProposal,
)
from tradingagents.risk import sizing
from tradingagents.risk.schemas import RiskDecision

MIN_CONFIDENCE = 0.50


def _cfg(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is not None:
        return dict(config)
    from tradingagents.dataflows.config import get_config

    return get_config()


def _entry_mid(proposal: CryptoTradeProposal) -> float | None:
    if proposal.entry_min is None or proposal.entry_max is None:
        return None
    return (proposal.entry_min + proposal.entry_max) / 2.0


def _nearest_tp_rr(proposal: CryptoTradeProposal, entry: float) -> float | None:
    """Reward/risk vs the take-profit closest to entry (conservative)."""
    if not proposal.take_profit_levels or proposal.stop_loss is None:
        return None
    closest = None
    closest_dist = None
    for tp in proposal.take_profit_levels:
        dist = abs(tp - entry)
        if closest_dist is None or dist < closest_dist:
            closest_dist = dist
            closest = tp
    if closest is None:
        return None
    rr = sizing.reward_risk_ratio(
        entry_price=entry, stop_loss=proposal.stop_loss, take_profit=closest
    )
    return float(rr) if rr is not None else None


def evaluate_risk(
    proposal: CryptoTradeProposal,
    snapshot: CryptoMarketSnapshot | None = None,
    config: dict[str, Any] | None = None,
    *,
    portfolio_equity: float | None = None,
) -> RiskDecision:
    """Apply deterministic risk rules to a crypto trade proposal.

    Rules are evaluated in a fixed order and produce stable reason strings.
    """
    cfg = _cfg(config)
    adjustments: list[str] = []
    rejections: list[str] = []
    warnings: list[str] = []

    risk_per_trade = float(cfg.get("paper_risk_per_trade_pct", 1.0))
    max_leverage = float(cfg.get("paper_max_leverage", 3.0))
    max_position_pct = float(cfg.get("paper_max_position_pct", 10.0))
    min_rr = float(cfg.get("paper_min_reward_risk", 1.5))
    max_spread = float(cfg.get("paper_max_spread_bps", 30.0))
    max_age = float(cfg.get("crypto_max_data_age_seconds", 180))
    equity = float(
        portfolio_equity
        if portfolio_equity is not None
        else cfg.get("paper_starting_balance", 100_000)
    )

    spread_bps = None
    if snapshot is not None:
        spread_bps = snapshot.technical.spread_bps

    # 13. Preserve NO_TRADE without converting it into a trade.
    if proposal.action == CryptoTradeAction.NO_TRADE:
        return RiskDecision(
            approved=True,
            final_action=CryptoTradeAction.NO_TRADE,
            approved_position_pct=0.0,
            approved_leverage=1.0,
            risk_per_trade_pct=risk_per_trade,
            estimated_reward_risk=None,
            estimated_spread_bps=spread_bps,
            rejection_reasons=[],
            adjustments=["preserved NO_TRADE decision"],
            warnings=list(proposal.risks) if proposal.risks else [],
        )

    entry = _entry_mid(proposal)
    estimated_rr = _nearest_tp_rr(proposal, entry) if entry is not None else None

    # 1. Reject missing entry / stop / TP
    if (
        proposal.entry_min is None
        or proposal.entry_max is None
        or proposal.stop_loss is None
        or not proposal.take_profit_levels
    ):
        rejections.append("missing entry, stop, or take-profit")

    # 2. Reject stale snapshots
    if snapshot is not None:
        if snapshot.data_quality.is_stale:
            rejections.append("market snapshot is stale")
        elif (
            snapshot.data_quality.max_data_age_seconds is not None
            and snapshot.data_quality.max_data_age_seconds > max_age
        ):
            rejections.append(
                f"market snapshot age {snapshot.data_quality.max_data_age_seconds:.0f}s "
                f"exceeds max {max_age:.0f}s"
            )
        # Also check wall-clock age of snapshot timestamp
        snap_ts = snapshot.timestamp
        if snap_ts.tzinfo is None:
            snap_ts = snap_ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - snap_ts.astimezone(timezone.utc)).total_seconds()
        if (
            age > max_age
            and "market snapshot is stale" not in rejections
            and not snapshot.data_quality.is_stale
        ):
            rejections.append(
                f"market snapshot age {age:.0f}s exceeds max {max_age:.0f}s"
            )
    else:
        warnings.append("no market snapshot provided; stale check skipped")

    # 3. Reject logically invalid stops
    if entry is not None and proposal.stop_loss is not None:
        if proposal.action == CryptoTradeAction.LONG and proposal.stop_loss >= entry:
            rejections.append("LONG requires stop below entry")
        if proposal.action == CryptoTradeAction.SHORT and proposal.stop_loss <= entry:
            rejections.append("SHORT requires stop above entry")

    # 4. Reject below minimum reward-to-risk
    if estimated_rr is None and entry is not None and proposal.take_profit_levels:
        rejections.append("unable to compute reward-to-risk")
    elif estimated_rr is not None and estimated_rr < min_rr:
        rejections.append(
            f"reward-to-risk {estimated_rr:.4f} below minimum {min_rr:.4f}"
        )

    # 5. Reject when spread exceeds maximum
    if spread_bps is not None and spread_bps > max_spread:
        rejections.append(
            f"spread {spread_bps:.2f} bps exceeds maximum {max_spread:.2f} bps"
        )
    elif spread_bps is None and snapshot is not None:
        warnings.append("spread unavailable; spread check skipped")

    # 12. Reject confidence < 0.50
    if proposal.confidence < MIN_CONFIDENCE:
        rejections.append(
            f"confidence {proposal.confidence:.4f} below minimum {MIN_CONFIDENCE:.2f}"
        )

    # Early reject path — still report clamped values for transparency
    if rejections:
        return RiskDecision(
            approved=False,
            final_action=CryptoTradeAction.NO_TRADE,
            approved_position_pct=0.0,
            approved_leverage=1.0,
            risk_per_trade_pct=risk_per_trade,
            estimated_reward_risk=estimated_rr,
            estimated_spread_bps=spread_bps,
            rejection_reasons=rejections,
            adjustments=adjustments,
            warnings=warnings,
        )

    assert entry is not None and proposal.stop_loss is not None

    # 6. Clamp leverage
    lev, lev_clamped = sizing.clamp_leverage(proposal.requested_leverage, max_leverage)
    if lev_clamped:
        adjustments.append(
            f"clamped leverage from {proposal.requested_leverage:.4f} to {float(lev):.4f}"
        )
    if proposal.requested_leverage < 1:
        adjustments.append("raised leverage to minimum 1.0")

    # 7–11. Position sizing pipeline
    # Start from requested pct, then apply risk-based notional / caps.
    pos_pct, size_clamped = sizing.clamp_position_pct(
        proposal.requested_position_pct, max_position_pct
    )
    if size_clamped:
        adjustments.append(
            f"clamped position from {proposal.requested_position_pct:.4f}% "
            f"to {float(pos_pct):.4f}%"
        )

    # 8. Volatility / stop-adjusted sizing
    risk_notional = sizing.risk_based_notional(
        portfolio_equity=equity,
        risk_per_trade_pct=risk_per_trade,
        entry_price=entry,
        stop_loss=proposal.stop_loss,
    )
    cap_notional = sizing.position_cap_notional(
        portfolio_equity=equity, max_position_pct=max_position_pct
    )
    if risk_notional is not None:
        approved_notional = min(risk_notional, cap_notional)
        risk_pct = sizing.notional_to_position_pct(approved_notional, equity)
        if risk_pct < pos_pct:
            adjustments.append(
                f"stop-distance sizing reduced position from {float(pos_pct):.4f}% "
                f"to {float(risk_pct):.4f}%"
            )
            pos_pct = risk_pct
        elif risk_pct > pos_pct and proposal.requested_position_pct <= 0:
            # If trader requested 0 somehow (should be rejected earlier), keep 0
            pass

    # Also express requested size as notional and ensure stop loss ≤ risk budget
    # 9. Max portfolio risk at stop
    stop_dist = sizing.stop_distance_pct(entry, proposal.stop_loss)
    if stop_dist is not None and stop_dist > 0:
        # Loss at stop for current position pct (notional / equity * stop_dist * 100)
        notional = (pos_pct / Decimal("100")) * Decimal(str(equity))
        loss_at_stop = notional * stop_dist
        max_loss = Decimal(str(equity)) * (Decimal(str(risk_per_trade)) / Decimal("100"))
        if loss_at_stop > max_loss:
            # Scale down so loss_at_stop == max_loss
            scale = max_loss / loss_at_stop
            new_pct = pos_pct * scale
            adjustments.append(
                f"portfolio risk at stop reduced position from {float(pos_pct):.4f}% "
                f"to {float(new_pct):.4f}%"
            )
            pos_pct = new_pct

    # Leverage must not bypass max loss: cap notional by equity * max_position,
    # leverage only affects margin, not allowed loss. Already enforced via notional.
    # If leverage * margin would imply larger exposure than approved notional we
    # already sized notional; keep leverage as clamped value.

    # 10. Reduce size in high vol
    realized_vol = snapshot.technical.realized_volatility if snapshot else None
    vol_regime = snapshot.regime.volatility if snapshot else None
    pos_pct, vol_note = sizing.apply_volatility_scalar(
        pos_pct, realized_vol=realized_vol, volatility_regime=vol_regime
    )
    if vol_note:
        adjustments.append(vol_note)

    # 11. Reduce size for low confidence
    pos_pct, conf_note = sizing.apply_confidence_scalar(pos_pct, proposal.confidence)
    if conf_note:
        adjustments.append(conf_note)

    # Re-clamp after scalars
    pos_pct, reclamped = sizing.clamp_position_pct(pos_pct, max_position_pct)
    if reclamped:
        adjustments.append(
            f"re-clamped position to max {max_position_pct:.4f}% after adjustments"
        )

    if pos_pct <= 0:
        return RiskDecision(
            approved=False,
            final_action=CryptoTradeAction.NO_TRADE,
            approved_position_pct=0.0,
            approved_leverage=1.0,
            risk_per_trade_pct=risk_per_trade,
            estimated_reward_risk=estimated_rr,
            estimated_spread_bps=spread_bps,
            rejection_reasons=["approved position size reduced to zero"],
            adjustments=adjustments,
            warnings=warnings,
        )

    return RiskDecision(
        approved=True,
        final_action=proposal.action,
        approved_position_pct=sizing.quantize_pct(pos_pct),
        approved_leverage=float(lev),
        risk_per_trade_pct=risk_per_trade,
        estimated_reward_risk=estimated_rr,
        estimated_spread_bps=spread_bps,
        rejection_reasons=[],
        adjustments=adjustments,
        warnings=warnings,
    )


def merge_strategy_risk_overrides(
    config: dict[str, Any], strategy: dict[str, Any]
) -> dict[str, Any]:
    """Return a config copy with strategy risk knobs applied."""
    out = deepcopy(config)
    mapping = {
        "max_position_pct": "paper_max_position_pct",
        "max_leverage": "paper_max_leverage",
        "risk_per_trade_pct": "paper_risk_per_trade_pct",
        "minimum_confidence": "crypto_minimum_confidence",
    }
    for src, dst in mapping.items():
        if src in strategy and strategy[src] is not None:
            out[dst] = strategy[src]
    return out
