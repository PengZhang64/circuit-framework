"""Position sizing helpers using Decimal for money arithmetic."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


def _d(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"cannot convert to Decimal: {value!r}") from exc


def stop_distance_pct(entry_price: Any, stop_loss: Any) -> Decimal | None:
    entry = _d(entry_price)
    stop = _d(stop_loss)
    if entry <= 0:
        return None
    return abs(entry - stop) / entry


def reward_risk_ratio(
    *,
    entry_price: Any,
    stop_loss: Any,
    take_profit: Any,
) -> Decimal | None:
    entry = _d(entry_price)
    stop = _d(stop_loss)
    tp = _d(take_profit)
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    reward = abs(tp - entry)
    return reward / risk


def risk_based_notional(
    *,
    portfolio_equity: Any,
    risk_per_trade_pct: Any,
    entry_price: Any,
    stop_loss: Any,
) -> Decimal | None:
    """Notional size such that loss at stop ≈ equity * risk_per_trade_pct/100."""
    equity = _d(portfolio_equity)
    risk_pct = _d(risk_per_trade_pct)
    if equity <= 0 or risk_pct <= 0:
        return None
    dist = stop_distance_pct(entry_price, stop_loss)
    if dist is None or dist <= 0:
        return None
    risk_budget = equity * (risk_pct / Decimal("100"))
    return risk_budget / dist


def position_cap_notional(
    *,
    portfolio_equity: Any,
    max_position_pct: Any,
) -> Decimal:
    return _d(portfolio_equity) * (_d(max_position_pct) / Decimal("100"))


def clamp_leverage(requested: Any, max_leverage: Any) -> tuple[Decimal, bool]:
    req = _d(requested)
    cap = _d(max_leverage)
    if req < 1:
        req = Decimal("1")
    if req > cap:
        return cap, True
    return req, False


def clamp_position_pct(requested: Any, max_position_pct: Any) -> tuple[Decimal, bool]:
    req = max(_d(requested), Decimal("0"))
    cap = _d(max_position_pct)
    if req > cap:
        return cap, True
    return req, False


def notional_to_position_pct(notional: Any, portfolio_equity: Any) -> Decimal:
    equity = _d(portfolio_equity)
    if equity <= 0:
        return Decimal("0")
    return (_d(notional) / equity) * Decimal("100")


def apply_volatility_scalar(
    position_pct: Any,
    *,
    realized_vol: float | None,
    volatility_regime: str | None,
) -> tuple[Decimal, str | None]:
    """Reduce size in elevated volatility regimes."""
    pct = _d(position_pct)
    regime = (volatility_regime or "").lower()
    if regime == "extreme":
        return pct * Decimal("0.40"), "reduced size 60% for extreme volatility"
    if regime == "high":
        return pct * Decimal("0.70"), "reduced size 30% for high volatility"
    if realized_vol is not None and realized_vol >= 0.03:
        return pct * Decimal("0.50"), "reduced size 50% for realized vol >= 3%"
    if realized_vol is not None and realized_vol >= 0.015:
        return pct * Decimal("0.80"), "reduced size 20% for elevated realized vol"
    return pct, None


def apply_confidence_scalar(position_pct: Any, confidence: float) -> tuple[Decimal, str | None]:
    pct = _d(position_pct)
    if confidence < 0.60:
        return pct * Decimal("0.50"), "reduced size 50% for confidence < 0.60"
    if confidence < 0.70:
        return pct * Decimal("0.75"), "reduced size 25% for confidence < 0.70"
    return pct, None


def quantize_pct(value: Decimal, places: str = "0.0001") -> float:
    return float(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))
