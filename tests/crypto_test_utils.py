"""Shared helpers for crypto unit tests — fixture-backed Hyperliquid mocking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.crypto.instruments import parse_crypto_instrument
from tradingagents.crypto.schemas import (
    CryptoMarketSnapshot,
    CryptoTradeAction,
    CryptoTradeProposal,
    DataQuality,
    DerivativesSnapshot,
    MarketRegimeSnapshot,
    OHLCVCandle,
    OrderBookLevel,
    OrderBookSnapshot,
    TechnicalSnapshot,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "hyperliquid"


def load_fixture(name: str) -> Any:
    path = FIXTURES / name
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def install_hyperliquid_fixtures(monkeypatch, client) -> None:
    """Monkeypatch ``client._post`` to serve local fixture JSON (no network)."""

    meta = load_fixture("meta_and_asset_ctxs.json")
    candles = load_fixture("candle_snapshot_btc_1h.json")
    book = load_fixture("l2_book_btc.json")
    funding = load_fixture("funding_history_btc.json")

    def _post(body: dict[str, Any], *, use_cache: bool = True) -> Any:
        typ = body.get("type")
        if typ == "metaAndAssetCtxs":
            return meta
        if typ == "candleSnapshot":
            return candles
        if typ == "l2Book":
            return book
        if typ == "fundingHistory":
            return funding
        raise AssertionError(f"unexpected Hyperliquid request: {body!r}")

    monkeypatch.setattr(client, "_post", _post)


def make_candles(
    closes: list[float],
    *,
    start: datetime | None = None,
    interval_seconds: int = 3600,
) -> list[OHLCVCandle]:
    start = start or datetime(2026, 7, 1, tzinfo=timezone.utc)
    out: list[OHLCVCandle] = []
    for i, c in enumerate(closes):
        ts = start.timestamp() + i * interval_seconds
        px = float(c)
        out.append(
            OHLCVCandle(
                timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                open=px,
                high=px * 1.01,
                low=px * 0.99,
                close=px,
                volume=100.0 + i,
            )
        )
    return out


def make_fresh_snapshot(
    *,
    mark: float = 97500.0,
    mid: float = 97501.0,
    symbol: str = "BTC",
    stale: bool = False,
    spread_bps: float = 2.0,
    realized_vol: float | None = 0.01,
    volatility: str = "normal",
    closes: list[float] | None = None,
) -> CryptoMarketSnapshot:
    instrument = parse_crypto_instrument(symbol)
    candles = {"1h": make_candles(closes or [97000 + i * 10 for i in range(60)])}
    now = datetime.now(timezone.utc)
    half = mid * (spread_bps / 20_000.0)
    book = OrderBookSnapshot(
        bids=[OrderBookLevel(price=mid - half, size=1.0)],
        asks=[OrderBookLevel(price=mid + half, size=1.0)],
        timestamp=now,
    )
    return CryptoMarketSnapshot(
        snapshot_id=f"test_{instrument.venue_symbol.lower()}_snap",
        timestamp=now,
        instrument=instrument,
        mark_price=mark,
        mid_price=mid,
        oracle_price=mark,
        candles=candles,
        order_book=book,
        derivatives=DerivativesSnapshot(funding_rate=0.0001, open_interest=1000.0),
        technical=TechnicalSnapshot(
            atr_14=500.0,
            realized_volatility=realized_vol,
            spread_bps=spread_bps,
            rsi_14=55.0,
            ema_20=mark,
            ema_50=mark * 0.99,
        ),
        regime=MarketRegimeSnapshot(
            trend="uptrend",
            volatility=volatility,  # type: ignore[arg-type]
            liquidity="normal",
            risk_mode="risk_on",
            confidence=0.7,
            reasons=["test"],
        ),
        data_quality=DataQuality(
            candles_ok=True,
            order_book_ok=True,
            derivatives_ok=True,
            is_stale=stale,
            max_data_age_seconds=10.0 if not stale else 9999.0,
        ),
        source_timestamps={"asset_ctx": now},
        warnings=[],
    )


def make_long_proposal(
    snapshot: CryptoMarketSnapshot,
    *,
    entry: float | None = None,
    stop: float | None = None,
    tp: float | None = None,
    leverage: float = 2.0,
    position_pct: float = 5.0,
    confidence: float = 0.75,
) -> CryptoTradeProposal:
    mid = entry or snapshot.mid_price or snapshot.mark_price or 97500.0
    stop = stop if stop is not None else mid * 0.97
    tp = tp if tp is not None else mid * 1.06
    return CryptoTradeProposal(
        action=CryptoTradeAction.LONG,
        instrument=snapshot.instrument,
        venue="hyperliquid",
        time_horizon="1h",
        entry_min=mid * 0.999,
        entry_max=mid * 1.001,
        stop_loss=stop,
        take_profit_levels=[tp],
        requested_position_pct=position_pct,
        requested_leverage=leverage,
        confidence=confidence,
        thesis="Unit-test long setup",
        invalidation="Break of structure",
        snapshot_id=snapshot.snapshot_id,
        data_timestamp=snapshot.timestamp,
    )


def make_short_proposal(
    snapshot: CryptoMarketSnapshot,
    *,
    entry: float | None = None,
    stop: float | None = None,
    tp: float | None = None,
    leverage: float = 2.0,
    position_pct: float = 5.0,
    confidence: float = 0.75,
) -> CryptoTradeProposal:
    mid = entry or snapshot.mid_price or snapshot.mark_price or 97500.0
    stop = stop if stop is not None else mid * 1.03
    tp = tp if tp is not None else mid * 0.94
    return CryptoTradeProposal(
        action=CryptoTradeAction.SHORT,
        instrument=snapshot.instrument,
        venue="hyperliquid",
        time_horizon="1h",
        entry_min=mid * 0.999,
        entry_max=mid * 1.001,
        stop_loss=stop,
        take_profit_levels=[tp],
        requested_position_pct=position_pct,
        requested_leverage=leverage,
        confidence=confidence,
        thesis="Unit-test short setup",
        invalidation="Break higher",
        snapshot_id=snapshot.snapshot_id,
        data_timestamp=snapshot.timestamp,
    )


def make_no_trade_proposal(snapshot: CryptoMarketSnapshot) -> CryptoTradeProposal:
    return CryptoTradeProposal(
        action=CryptoTradeAction.NO_TRADE,
        instrument=snapshot.instrument,
        venue="hyperliquid",
        time_horizon="1h",
        requested_position_pct=0.0,
        requested_leverage=1.0,
        confidence=0.4,
        thesis="",
        invalidation="",
        snapshot_id=snapshot.snapshot_id,
        data_timestamp=snapshot.timestamp,
        no_trade_reason="Insufficient edge",
    )
