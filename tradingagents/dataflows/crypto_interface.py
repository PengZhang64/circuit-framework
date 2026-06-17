"""Thin crypto market-data facade used by agents and tools.

Reads configuration from ``tradingagents.dataflows.config`` / ``DEFAULT_CONFIG``
and delegates to the Hyperliquid Info adapter. Callers should use this module
rather than constructing ``HyperliquidClient`` directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tradingagents.crypto.instruments import CryptoInstrument, parse_crypto_instrument
from tradingagents.crypto.schemas import (
    CryptoMarketSnapshot,
    OHLCVCandle,
    OrderBookSnapshot,
)
from tradingagents.dataflows import config as config_module
from tradingagents.dataflows.hyperliquid import (
    HyperliquidClient,
    HyperliquidError,
    build_client_from_config,
)

_client: HyperliquidClient | None = None


def _get_config() -> dict[str, Any]:
    return config_module.get_config()


def get_client(*, force_new: bool = False) -> HyperliquidClient:
    """Return a process-wide Hyperliquid client bound to current config."""
    global _client
    if _client is None or force_new:
        _client = build_client_from_config(_get_config())
    return _client


def reset_client() -> None:
    """Drop the cached client (useful in tests)."""
    global _client
    _client = None


def _resolve_instrument(instrument: CryptoInstrument | str) -> CryptoInstrument:
    if isinstance(instrument, CryptoInstrument):
        return instrument
    cfg = _get_config()
    return parse_crypto_instrument(
        instrument,
        venue=str(cfg.get("crypto_venue", "hyperliquid")),
        instrument_type=cfg.get("crypto_instrument_type", "perp"),  # type: ignore[arg-type]
        quote_currency=str(cfg.get("crypto_quote_currency", "USDG")),
    )


def get_asset_contexts() -> dict[str, Any]:
    return get_client().get_asset_contexts()


def get_crypto_candles(
    coin: str,
    interval: str | None = None,
    *,
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int | None = None,
) -> list[OHLCVCandle]:
    cfg = _get_config()
    client = get_client()
    interval = interval or str(cfg.get("crypto_default_interval", "1h"))
    candle_limit = int(limit if limit is not None else cfg.get("crypto_candle_limit", 300))
    from tradingagents.dataflows.hyperliquid import INTERVAL_MS

    if interval not in INTERVAL_MS:
        raise HyperliquidError(f"unsupported interval: {interval!r}")
    if end_time is None:
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    if start_time is None:
        start_time = int(end_time) - candle_limit * INTERVAL_MS[interval]
    return client.get_candles(coin, interval, int(start_time), int(end_time))


def get_crypto_order_book(coin: str) -> OrderBookSnapshot:
    return get_client().get_l2_book(coin)


def get_crypto_funding_history(
    coin: str,
    *,
    start_time: int | None = None,
    end_time: int | None = None,
) -> list[dict[str, Any]]:
    if end_time is None:
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    if start_time is None:
        start_time = int(end_time) - 7 * 86_400_000
    return get_client().get_funding_history(coin, int(start_time), int(end_time))


def get_crypto_market_snapshot(
    instrument: CryptoInstrument | str,
    as_of: datetime | None = None,
    *,
    intervals: list[str] | None = None,
) -> CryptoMarketSnapshot:
    resolved = _resolve_instrument(instrument)
    return get_client().get_market_snapshot(resolved, as_of=as_of, intervals=intervals)


def get_crypto_derivatives(instrument: CryptoInstrument | str) -> dict[str, Any]:
    snap = get_crypto_market_snapshot(instrument)
    return snap.derivatives.model_dump(mode="json")


def get_crypto_regime(instrument: CryptoInstrument | str) -> dict[str, Any]:
    snap = get_crypto_market_snapshot(instrument)
    return snap.regime.model_dump(mode="json")


__all__ = [
    "HyperliquidError",
    "get_asset_contexts",
    "get_client",
    "get_crypto_candles",
    "get_crypto_derivatives",
    "get_crypto_funding_history",
    "get_crypto_market_snapshot",
    "get_crypto_order_book",
    "get_crypto_regime",
    "reset_client",
]
