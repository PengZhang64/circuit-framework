"""Crypto decision evaluation helpers for the memory / reflection layer.

Evaluates LONG/SHORT outcomes against future Hyperliquid (or fixture-injected)
candles. Stock memory resolution is unchanged; this module is used when the
current run or pending entry is crypto.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from tradingagents.crypto.instruments import parse_crypto_instrument
from tradingagents.crypto.schemas import CryptoTradeAction, OHLCVCandle

CRYPTO_META_RE = re.compile(
    r"<!--\s*CRYPTO_META\s*(\{.*?\})\s*-->",
    re.DOTALL,
)

CandleProvider = Callable[
    [str, str, datetime, datetime],
    Sequence[OHLCVCandle] | list[dict[str, Any]],
]


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_trade_date(trade_date: str) -> datetime:
    raw = (trade_date or "").strip()
    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
    return _ensure_utc(dt)


def _candle_close(c: OHLCVCandle | dict[str, Any]) -> float:
    if isinstance(c, OHLCVCandle):
        return float(c.close)
    return float(c["close"] if "close" in c else c.get("c"))


def _candle_high(c: OHLCVCandle | dict[str, Any]) -> float:
    if isinstance(c, OHLCVCandle):
        return float(c.high)
    return float(c["high"] if "high" in c else c.get("h"))


def _candle_low(c: OHLCVCandle | dict[str, Any]) -> float:
    if isinstance(c, OHLCVCandle):
        return float(c.low)
    return float(c["low"] if "low" in c else c.get("l"))


def _candle_ts(c: OHLCVCandle | dict[str, Any]) -> datetime:
    if isinstance(c, OHLCVCandle):
        return _ensure_utc(c.timestamp)
    if isinstance(c.get("timestamp"), datetime):
        return _ensure_utc(c["timestamp"])
    t = c.get("t") or c.get("T") or c.get("time")
    if isinstance(t, datetime):
        return _ensure_utc(t)
    return datetime.fromtimestamp(int(t) / 1000.0, tz=timezone.utc)


def build_crypto_meta_block(
    *,
    asset_type: str = "crypto",
    action: str | None = None,
    entry: float | None = None,
    stop_loss: float | None = None,
    take_profit_levels: list[float] | None = None,
    confidence: float | None = None,
    instrument: str | None = None,
    venue: str | None = None,
    snapshot_id: str | None = None,
    trade_proposal: dict[str, Any] | None = None,
) -> str:
    """Serialize structured crypto fields as a markdown HTML comment."""
    meta: dict[str, Any] = {"asset_type": asset_type}
    if trade_proposal:
        action = action or trade_proposal.get("action")
        entry_min = trade_proposal.get("entry_min")
        entry_max = trade_proposal.get("entry_max")
        if entry is None and entry_min is not None and entry_max is not None:
            entry = (float(entry_min) + float(entry_max)) / 2.0
        stop_loss = stop_loss if stop_loss is not None else trade_proposal.get("stop_loss")
        take_profit_levels = take_profit_levels or trade_proposal.get("take_profit_levels")
        confidence = (
            confidence if confidence is not None else trade_proposal.get("confidence")
        )
        inst = trade_proposal.get("instrument") or {}
        if isinstance(inst, dict):
            instrument = instrument or inst.get("display_symbol") or inst.get("venue_symbol")
        venue = venue or trade_proposal.get("venue")
        snapshot_id = snapshot_id or trade_proposal.get("snapshot_id")
    if action is not None:
        meta["action"] = action if isinstance(action, str) else getattr(action, "value", str(action))
    if entry is not None:
        meta["entry"] = float(entry)
    if stop_loss is not None:
        meta["stop_loss"] = float(stop_loss)
    if take_profit_levels:
        meta["take_profit_levels"] = [float(x) for x in take_profit_levels]
    if confidence is not None:
        meta["confidence"] = float(confidence)
    if instrument:
        meta["instrument"] = instrument
    if venue:
        meta["venue"] = venue
    if snapshot_id:
        meta["snapshot_id"] = snapshot_id
    return f"\n\n<!-- CRYPTO_META\n{json.dumps(meta, separators=(',', ':'))}\n-->\n"


def parse_crypto_meta(decision_text: str) -> dict[str, Any] | None:
    """Extract CRYPTO_META JSON from a decision body, if present."""
    if not decision_text:
        return None
    match = CRYPTO_META_RE.search(decision_text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def is_crypto_memory_entry(
    ticker: str,
    decision_text: str = "",
    *,
    asset_type: str | None = None,
) -> bool:
    """True when an entry should use crypto evaluation."""
    if asset_type == "crypto":
        return True
    meta = parse_crypto_meta(decision_text or "")
    if meta and meta.get("asset_type") == "crypto":
        return True
    try:
        parse_crypto_instrument(ticker)
        # Prefer known bases / PERP forms so stock tickers like "A" don't match.
        from tradingagents.crypto.instruments import is_standalone_crypto_symbol

        return is_standalone_crypto_symbol(ticker) or "-PERP" in ticker.upper()
    except ValueError:
        return False


def default_candle_provider(
    coin: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> list[OHLCVCandle]:
    """Fetch candles via the crypto interface (may hit network — tests inject)."""
    from tradingagents.dataflows.crypto_interface import get_crypto_candles

    start_ms = int(_ensure_utc(start).timestamp() * 1000)
    end_ms = int(_ensure_utc(end).timestamp() * 1000)
    return get_crypto_candles(coin, interval, start_time=start_ms, end_time=end_ms)


def evaluate_crypto_decision(
    *,
    ticker: str,
    trade_date: str,
    decision_text: str,
    holding_hours: int = 24,
    interval: str = "1h",
    candle_provider: CandleProvider | None = None,
    btc_candle_provider: CandleProvider | None = None,
) -> dict[str, Any] | None:
    """Evaluate a pending crypto decision against future candles.

    Returns None when future data is insufficient (caller should keep pending).
    Does not score NO_TRADE as a directional position.
    """
    meta = parse_crypto_meta(decision_text) or {}
    action_raw = (meta.get("action") or "").upper()
    try:
        action = CryptoTradeAction(action_raw) if action_raw else None
    except ValueError:
        action = None

    # Infer action from rating-like text if meta missing
    if action is None:
        upper = (decision_text or "").upper()
        if "NO_TRADE" in upper or "NO TRADE" in upper:
            action = CryptoTradeAction.NO_TRADE
        elif "SHORT" in upper:
            action = CryptoTradeAction.SHORT
        elif "LONG" in upper or "BUY" in upper:
            action = CryptoTradeAction.LONG
        else:
            return None

    if action == CryptoTradeAction.NO_TRADE:
        return {
            "action": "NO_TRADE",
            "raw_return": 0.0,
            "alpha_return": 0.0,
            "holding_hours": 0,
            "mfe": None,
            "mae": None,
            "stop_hit": False,
            "tp_hit": False,
            "skipped_as_position": True,
            "reflection_note": "NO_TRADE was not scored as a directional position.",
        }

    try:
        instrument = parse_crypto_instrument(ticker)
    except ValueError:
        return None

    coin = instrument.venue_symbol
    start = _parse_trade_date(trade_date)
    end = start + timedelta(hours=holding_hours)
    provider = candle_provider or default_candle_provider
    candles = list(provider(coin, interval, start, end))
    # Need candles strictly after the decision timestamp
    future = [c for c in candles if _candle_ts(c) > start]
    if len(future) < 2:
        return None

    entry = meta.get("entry")
    entry = _candle_close(future[0]) if entry is None else float(entry)

    exit_px = _candle_close(future[-1])
    if action == CryptoTradeAction.LONG:
        raw_return = (exit_px - entry) / entry if entry else 0.0
    else:
        raw_return = (entry - exit_px) / entry if entry else 0.0

    highs = [_candle_high(c) for c in future]
    lows = [_candle_low(c) for c in future]
    if action == CryptoTradeAction.LONG:
        mfe = (max(highs) - entry) / entry if entry else 0.0
        mae = (min(lows) - entry) / entry if entry else 0.0
    else:
        mfe = (entry - min(lows)) / entry if entry else 0.0
        mae = (entry - max(highs)) / entry if entry else 0.0

    stop = meta.get("stop_loss")
    tps = meta.get("take_profit_levels") or []
    stop_hit = False
    tp_hit = False
    if stop is not None:
        stop = float(stop)
        if action == CryptoTradeAction.LONG:
            stop_hit = any(low <= stop for low in lows)
        else:
            stop_hit = any(high >= stop for high in highs)
    if tps:
        for tp in tps:
            tp = float(tp)
            if action == CryptoTradeAction.LONG and any(high >= tp for high in highs):
                tp_hit = True
                break
            if action == CryptoTradeAction.SHORT and any(low <= tp for low in lows):
                tp_hit = True
                break
    # BTC benchmark for alts; raw-only for BTC
    alpha_return = raw_return
    if coin.upper() != "BTC":
        btc_provider = btc_candle_provider or provider
        btc_candles = list(btc_provider("BTC", interval, start, end))
        btc_future = [c for c in btc_candles if _candle_ts(c) > start]
        if len(btc_future) >= 2:
            btc_entry = _candle_close(btc_future[0])
            btc_exit = _candle_close(btc_future[-1])
            btc_ret = (btc_exit - btc_entry) / btc_entry if btc_entry else 0.0
            # Directional alpha vs BTC buy-and-hold
            if action == CryptoTradeAction.LONG:
                alpha_return = raw_return - btc_ret
            else:
                alpha_return = raw_return + btc_ret  # short profits when BTC falls
        else:
            return None  # insufficient benchmark history for alts

    holding = max(1, int((_candle_ts(future[-1]) - start).total_seconds() // 3600))
    return {
        "action": action.value,
        "raw_return": raw_return,
        "alpha_return": alpha_return,
        "holding_hours": holding,
        "holding_days": max(1, holding // 24),
        "mfe": mfe,
        "mae": mae,
        "stop_hit": stop_hit,
        "tp_hit": tp_hit,
        "skipped_as_position": False,
        "entry": entry,
        "exit": exit_px,
        "confidence": meta.get("confidence"),
    }


def format_crypto_reflection(outcome: dict[str, Any]) -> str:
    """Build a deterministic reflection string (no LLM)."""
    if outcome.get("skipped_as_position"):
        return outcome.get(
            "reflection_note",
            "NO_TRADE was not scored as a directional position.",
        )
    parts = [
        f"Action={outcome.get('action')}",
        f"raw={outcome['raw_return']:+.2%}",
        f"alpha={outcome['alpha_return']:+.2%}",
        f"holding={outcome.get('holding_hours', 0)}h",
    ]
    if outcome.get("mfe") is not None:
        parts.append(f"MFE={outcome['mfe']:+.2%}")
    if outcome.get("mae") is not None:
        parts.append(f"MAE={outcome['mae']:+.2%}")
    parts.append(f"stop_hit={outcome.get('stop_hit')}")
    parts.append(f"tp_hit={outcome.get('tp_hit')}")
    if outcome.get("confidence") is not None:
        parts.append(f"confidence={outcome['confidence']}")
    return "Crypto outcome: " + "; ".join(parts)
