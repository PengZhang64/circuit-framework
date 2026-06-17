"""Deterministic crypto indicators (no LLM, no third-party TA APIs)."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import pandas as pd

from tradingagents.crypto.schemas import MarketRegimeSnapshot


def _to_float_series(values: Iterable) -> pd.Series:
    out: list[float] = []
    for v in values:
        if v is None:
            out.append(float("nan"))
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return pd.Series(out, dtype="float64")


def calculate_ema(closes: Sequence, period: int = 20) -> float | None:
    s = _to_float_series(closes).dropna()
    if period <= 0 or len(s) < period:
        return None
    ema = s.ewm(span=period, adjust=False).mean()
    val = float(ema.iloc[-1])
    return None if math.isnan(val) else val


def calculate_rsi(closes: Sequence, period: int = 14) -> float | None:
    s = _to_float_series(closes).dropna()
    if period <= 0 or len(s) < period + 1:
        return None
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    val = float(rsi.iloc[-1])
    if math.isnan(val):
        # Flat prices -> RSI undefined; treat as neutral 50 when no movement
        if float(loss.sum()) == 0 and float(gain.sum()) == 0:
            return 50.0
        return None
    return val


def calculate_atr(highs: Sequence, lows: Sequence, closes: Sequence, period: int = 14) -> float | None:
    h = _to_float_series(highs)
    low = _to_float_series(lows)
    c = _to_float_series(closes)
    n = min(len(h), len(low), len(c))
    if period <= 0 or n < period + 1:
        return None
    h, low, c = h.iloc[-n:], low.iloc[-n:], c.iloc[-n:]
    prev_close = c.shift(1)
    tr = pd.concat(
        [(h - low).abs(), (h - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    val = float(atr.iloc[-1])
    return None if math.isnan(val) else val


def calculate_realized_volatility(closes: Sequence, window: int = 24) -> float | None:
    s = _to_float_series(closes).dropna()
    if window <= 1 or len(s) < window + 1:
        return None
    rets = s.pct_change().dropna()
    if len(rets) < window:
        return None
    vol = float(rets.iloc[-window:].std(ddof=0))
    if math.isnan(vol):
        return None
    return vol


def calculate_returns(closes: Sequence, lookback: int) -> float | None:
    s = _to_float_series(closes).dropna()
    if lookback <= 0 or len(s) <= lookback:
        return None
    start = float(s.iloc[-(lookback + 1)])
    end = float(s.iloc[-1])
    if start == 0 or math.isnan(start) or math.isnan(end):
        return None
    return (end - start) / start


def calculate_volume_change(volumes: Sequence, lookback: int = 24) -> float | None:
    s = _to_float_series(volumes).dropna()
    if lookback <= 0 or len(s) <= lookback:
        return None
    base = float(s.iloc[-(lookback + 1) : -1].mean())
    latest = float(s.iloc[-1])
    if base == 0 or math.isnan(base) or math.isnan(latest):
        return None
    return (latest - base) / base


def calculate_order_book_imbalance(bid_sizes: Sequence, ask_sizes: Sequence) -> float | None:
    bids = _to_float_series(bid_sizes).dropna()
    asks = _to_float_series(ask_sizes).dropna()
    if bids.empty or asks.empty:
        return None
    b = float(bids.sum())
    a = float(asks.sum())
    denom = b + a
    if denom <= 0:
        return None
    return (b - a) / denom


def calculate_spread_bps(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    try:
        bid = float(best_bid)
        ask = float(best_ask)
    except (TypeError, ValueError):
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0 or ask < bid:
        return None
    return ((ask - bid) / mid) * 10_000.0


def calculate_support_resistance(
    highs: Sequence, lows: Sequence, closes: Sequence, lookback: int = 50
) -> tuple[list[float], list[float]]:
    h = _to_float_series(highs).dropna()
    low = _to_float_series(lows).dropna()
    c = _to_float_series(closes).dropna()
    n = min(len(h), len(low), len(c), lookback)
    if n < 5:
        return [], []
    h, low, c = h.iloc[-n:], low.iloc[-n:], c.iloc[-n:]
    last = float(c.iloc[-1])
    supports = sorted({float(x) for x in low.nsmallest(3).tolist() if x < last})
    resistances = sorted({float(x) for x in h.nlargest(3).tolist() if x > last})
    return supports[:3], resistances[:3]


def classify_market_regime(
    *,
    returns_24h: float | None,
    ema_20: float | None,
    ema_50: float | None,
    last_price: float | None,
    realized_vol: float | None,
    spread_bps: float | None,
    imbalance: float | None,
) -> MarketRegimeSnapshot:
    reasons: list[str] = []
    trend: str = "range"
    if last_price and ema_20 and ema_50:
        if last_price > ema_20 > ema_50 and (returns_24h or 0) > 0.02:
            trend = "strong_uptrend"
            reasons.append("Price above EMA20>EMA50 with strong positive 24h return")
        elif last_price > ema_20 > ema_50:
            trend = "uptrend"
            reasons.append("Price above EMA20>EMA50")
        elif last_price < ema_20 < ema_50 and (returns_24h or 0) < -0.02:
            trend = "strong_downtrend"
            reasons.append("Price below EMA20<EMA50 with strong negative 24h return")
        elif last_price < ema_20 < ema_50:
            trend = "downtrend"
            reasons.append("Price below EMA20<EMA50")
        else:
            reasons.append("EMAs mixed — ranging")
    else:
        reasons.append("Insufficient EMA data for trend")

    volatility = "normal"
    if realized_vol is None:
        reasons.append("Realized volatility unavailable")
    elif realized_vol < 0.005:
        volatility = "low"
    elif realized_vol < 0.015:
        volatility = "normal"
    elif realized_vol < 0.03:
        volatility = "high"
    else:
        volatility = "extreme"
        reasons.append("Extreme realized volatility")

    liquidity = "normal"
    if spread_bps is None:
        reasons.append("Spread unavailable")
    elif spread_bps > 25:
        liquidity = "thin"
        reasons.append(f"Wide spread {spread_bps:.1f} bps")
    elif spread_bps < 5:
        liquidity = "deep"

    risk_mode = "neutral"
    if trend in ("strong_uptrend", "uptrend") and volatility in ("low", "normal"):
        risk_mode = "risk_on"
    elif trend in ("strong_downtrend", "downtrend") or volatility == "extreme":
        risk_mode = "risk_off"

    confidence = 0.4
    if ema_20 and ema_50 and last_price:
        confidence += 0.25
    if realized_vol is not None:
        confidence += 0.15
    if spread_bps is not None:
        confidence += 0.1
    if imbalance is not None:
        confidence += 0.1
    confidence = min(1.0, confidence)

    return MarketRegimeSnapshot(
        trend=trend,  # type: ignore[arg-type]
        volatility=volatility,  # type: ignore[arg-type]
        liquidity=liquidity,  # type: ignore[arg-type]
        risk_mode=risk_mode,  # type: ignore[arg-type]
        confidence=confidence,
        reasons=reasons,
    )
