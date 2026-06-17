"""LangChain tools that read the shared crypto market snapshot.

These tools never fetch live market data. The Snapshot Builder populates
``tradingagents.crypto.snapshot_store`` once per run; tools return a clear
unavailable message when that store is empty.
"""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.crypto.snapshot_store import get_snapshot

_UNAVAILABLE = (
    "snapshot unavailable — crypto market snapshot has not been built for this run"
)


def _snapshot_or_unavailable():
    return get_snapshot()


@tool
def get_crypto_market_snapshot() -> str:
    """Return a concise JSON summary of the verified crypto market snapshot.

    Reads the shared run snapshot (no live re-fetch). Includes calculated
    metrics, recent candle summary, levels, derivatives, order-book metrics,
    data-quality warnings, snapshot timestamp, and snapshot ID.
    """
    snap = _snapshot_or_unavailable()
    if snap is None:
        return _UNAVAILABLE
    return json.dumps(snap.summary_dict(), default=str)


@tool
def get_crypto_candles(
    interval: Annotated[
        str,
        "Candle interval key as stored on the snapshot (e.g. '15m', '1h', '4h', '1d')",
    ] = "1h",
) -> str:
    """Return a recent-candle summary for the given interval from the shared snapshot."""
    snap = _snapshot_or_unavailable()
    if snap is None:
        return _UNAVAILABLE
    bars = snap.candles.get(interval) or []
    if not bars:
        return json.dumps(
            {
                "interval": interval,
                "n": 0,
                "message": f"no candles for interval {interval!r} in snapshot",
                "snapshot_id": snap.snapshot_id,
            }
        )
    tail = bars[-10:]
    payload = {
        "interval": interval,
        "n": len(bars),
        "snapshot_id": snap.snapshot_id,
        "last_close": tail[-1].close,
        "last_ts": tail[-1].timestamp.isoformat(),
        "recent": [
            {
                "ts": b.timestamp.isoformat(),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in tail
        ],
        "technical": snap.technical.model_dump(mode="json"),
    }
    return json.dumps(payload, default=str)


@tool
def get_crypto_derivatives() -> str:
    """Return the derivatives portion of the shared crypto market snapshot."""
    snap = _snapshot_or_unavailable()
    if snap is None:
        return _UNAVAILABLE
    data = snap.derivatives.model_dump(mode="json")
    data["snapshot_id"] = snap.snapshot_id
    data["timestamp"] = snap.timestamp.isoformat()
    return json.dumps(data, default=str)


@tool
def get_crypto_order_book() -> str:
    """Return an order-book summary from the shared crypto market snapshot."""
    snap = _snapshot_or_unavailable()
    if snap is None:
        return _UNAVAILABLE
    ob = snap.order_book
    if ob is None:
        return json.dumps(
            {
                "snapshot_id": snap.snapshot_id,
                "message": "order book missing from snapshot",
                "order_book_ok": snap.data_quality.order_book_ok,
            }
        )
    top_n = 5
    payload = {
        "snapshot_id": snap.snapshot_id,
        "timestamp": ob.timestamp.isoformat() if ob.timestamp else None,
        "best_bid": ob.bids[0].price if ob.bids else None,
        "best_ask": ob.asks[0].price if ob.asks else None,
        "spread_bps": snap.technical.spread_bps,
        "imbalance": snap.technical.order_book_imbalance,
        "bids": [{"price": L.price, "size": L.size} for L in ob.bids[:top_n]],
        "asks": [{"price": L.price, "size": L.size} for L in ob.asks[:top_n]],
    }
    return json.dumps(payload, default=str)


@tool
def get_crypto_regime() -> str:
    """Return the market-regime portion of the shared crypto market snapshot."""
    snap = _snapshot_or_unavailable()
    if snap is None:
        return _UNAVAILABLE
    data = snap.regime.model_dump(mode="json")
    data["snapshot_id"] = snap.snapshot_id
    data["timestamp"] = snap.timestamp.isoformat()
    data["technical_context"] = {
        "realized_volatility": snap.technical.realized_volatility,
        "atr_14": snap.technical.atr_14,
        "returns_24h": snap.technical.returns_24h,
    }
    return json.dumps(data, default=str)
