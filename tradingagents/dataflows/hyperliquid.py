"""Hyperliquid public Info API adapter for Circuit Framework.

Uses only ``POST https://api.hyperliquid.xyz/info`` — no Exchange endpoint,
no authentication, no wallet credentials.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from tradingagents.crypto.indicators import (
    calculate_atr,
    calculate_ema,
    calculate_order_book_imbalance,
    calculate_realized_volatility,
    calculate_returns,
    calculate_rsi,
    calculate_spread_bps,
    calculate_support_resistance,
    calculate_volume_change,
    classify_market_regime,
)
from tradingagents.crypto.instruments import CryptoInstrument
from tradingagents.crypto.schemas import (
    CryptoMarketSnapshot,
    DataQuality,
    DerivativesSnapshot,
    OHLCVCandle,
    OrderBookLevel,
    OrderBookSnapshot,
    TechnicalSnapshot,
)

logger = logging.getLogger(__name__)

INFO_URL = "https://api.hyperliquid.xyz/info"
USER_AGENT = "CircuitFramework/0.3 (+https://github.com; Hyperliquid Info client)"
DEFAULT_TIMEOUT = 15
DEFAULT_CACHE_TTL = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.5

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
    "1M": 2_592_000_000,
}

# Candle count lookbacks for multi-interval returns on the primary series.
_RETURNS_LOOKBACK_1H = {"15m": 4, "1h": 1, "4h": None, "1d": None}
_RETURNS_LOOKBACK_4H = {"15m": 16, "1h": 4, "4h": 1, "1d": None}
_RETURNS_LOOKBACK_24H = {"15m": 96, "1h": 24, "4h": 6, "1d": 1}


class HyperliquidError(Exception):
    """Base error for Hyperliquid Info client failures."""


class HyperliquidTimeoutError(HyperliquidError):
    """Request timed out talking to the Info endpoint."""


class HyperliquidTransientError(HyperliquidError):
    """Transient network / 5xx failure eligible for retry."""


class HyperliquidResponseError(HyperliquidError):
    """Response was present but could not be validated or parsed."""


class HyperliquidSymbolError(HyperliquidError):
    """Requested coin / instrument is not available on the venue."""


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ms_to_utc(ms: Any) -> datetime | None:
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    # Accept seconds accidentally; treat small values as seconds.
    if value < 1_000_000_000_000:
        value *= 1000
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _stable_snapshot_id(
    venue: str,
    instrument: CryptoInstrument,
    source_timestamps: dict[str, datetime],
) -> str:
    """Build a content-stable ID from venue + instrument + market data timestamps.

    Wall-clock fetch times (e.g. asset_ctx) are excluded so repeated fetches of
    the same candles / book / funding produce the same snapshot_id.
    """
    parts = [
        venue,
        instrument.venue_symbol,
        instrument.instrument_type,
        instrument.display_symbol,
    ]
    for key in sorted(source_timestamps):
        if key == "asset_ctx":
            continue
        ts = source_timestamps[key]
        parts.append(f"{key}:{_ensure_utc(ts).isoformat()}")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"hl_{instrument.venue_symbol.lower()}_{digest}"


class _TTLCache:
    def __init__(self, ttl_seconds: float) -> None:
        self.ttl = float(ttl_seconds)
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic() + self.ttl, value)

    def clear(self) -> None:
        self._store.clear()


class HyperliquidClient:
    """Public Hyperliquid Info API client with TTL cache and retries."""

    def __init__(
        self,
        *,
        base_url: str = INFO_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL,
        max_data_age_seconds: float = 180.0,
        candle_limit: int = 300,
        analysis_intervals: list[str] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout_seconds)
        self.max_data_age_seconds = float(max_data_age_seconds)
        self.candle_limit = int(candle_limit)
        self.analysis_intervals = list(
            analysis_intervals or ["15m", "1h", "4h", "1d"]
        )
        self._cache = _TTLCache(cache_ttl_seconds)
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------ HTTP
    def _cache_key(self, body: dict[str, Any]) -> str:
        return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)

    def _post(self, body: dict[str, Any], *, use_cache: bool = True) -> Any:
        key = self._cache_key(body)
        if use_cache:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = self._session.post(
                    self.base_url, json=body, timeout=self.timeout
                )
            except requests.Timeout as exc:
                last_error = HyperliquidTimeoutError(str(exc))
                if attempt + 1 < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise last_error from exc
            except requests.RequestException as exc:
                last_error = HyperliquidTransientError(str(exc))
                if attempt + 1 < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise last_error from exc

            if response.status_code >= 500:
                last_error = HyperliquidTransientError(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                if attempt + 1 < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise last_error

            if response.status_code == 429:
                last_error = HyperliquidTransientError(
                    f"rate limited: {response.text[:200]}"
                )
                if attempt + 1 < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1) * 2)
                    continue
                raise last_error

            if response.status_code >= 400:
                # Client errors (invalid coin / payload) — do not retry.
                raise HyperliquidResponseError(
                    f"HTTP {response.status_code}: {response.text[:300]}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise HyperliquidResponseError(
                    f"non-JSON response: {response.text[:200]}"
                ) from exc

            if use_cache:
                self._cache.set(key, payload)
            return payload

        raise last_error or HyperliquidTransientError("request failed")

    # -------------------------------------------------------------- endpoints
    def get_asset_contexts(self) -> dict[str, Any]:
        """Return meta universe + asset contexts keyed by coin name."""
        raw = self._post({"type": "metaAndAssetCtxs"})
        if not isinstance(raw, list) or len(raw) < 2:
            raise HyperliquidResponseError(
                "metaAndAssetCtxs expected [meta, assetCtxs]"
            )
        meta, asset_ctxs = raw[0], raw[1]
        if not isinstance(meta, dict) or "universe" not in meta:
            raise HyperliquidResponseError("meta missing universe")
        if not isinstance(asset_ctxs, list):
            raise HyperliquidResponseError("assetCtxs must be a list")

        universe = meta.get("universe") or []
        by_coin: dict[str, dict[str, Any]] = {}
        for idx, asset in enumerate(universe):
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            if not name:
                continue
            ctx = asset_ctxs[idx] if idx < len(asset_ctxs) else {}
            if not isinstance(ctx, dict):
                ctx = {}
            by_coin[str(name)] = {
                "meta": asset,
                "ctx": ctx,
                "index": idx,
            }
        return {
            "raw": raw,
            "meta": meta,
            "asset_ctxs": asset_ctxs,
            "by_coin": by_coin,
            "fetched_at": datetime.now(timezone.utc),
        }

    def get_candles(
        self,
        coin: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> list[OHLCVCandle]:
        if interval not in INTERVAL_MS:
            raise HyperliquidResponseError(f"unsupported interval: {interval!r}")
        body = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": int(start_time),
                "endTime": int(end_time),
            },
        }
        raw = self._post(body)
        if not isinstance(raw, list):
            raise HyperliquidResponseError("candleSnapshot must return a list")

        candles: list[OHLCVCandle] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            ts = _ms_to_utc(row.get("t") if row.get("t") is not None else row.get("T"))
            o = _parse_float(row.get("o"))
            h = _parse_float(row.get("h"))
            low_px = _parse_float(row.get("l"))
            c = _parse_float(row.get("c"))
            v = _parse_float(row.get("v"))
            if ts is None or None in (o, h, low_px, c):
                continue
            candles.append(
                OHLCVCandle(
                    timestamp=ts,
                    open=float(o),
                    high=float(h),
                    low=float(low_px),
                    close=float(c),
                    volume=float(v) if v is not None else 0.0,
                )
            )
        candles.sort(key=lambda x: x.timestamp)
        return candles

    def get_l2_book(self, coin: str) -> OrderBookSnapshot:
        raw = self._post({"type": "l2Book", "coin": coin})
        if not isinstance(raw, dict):
            raise HyperliquidResponseError("l2Book must return an object")
        levels = raw.get("levels")
        if not isinstance(levels, list) or len(levels) < 2:
            raise HyperliquidResponseError("l2Book.levels must be [bids, asks]")

        def _parse_side(side: Any) -> list[OrderBookLevel]:
            out: list[OrderBookLevel] = []
            if not isinstance(side, list):
                return out
            for level in side:
                if not isinstance(level, dict):
                    continue
                px = _parse_float(level.get("px"))
                sz = _parse_float(level.get("sz"))
                if px is None or sz is None:
                    continue
                out.append(OrderBookLevel(price=px, size=sz))
            return out

        bids = _parse_side(levels[0])
        asks = _parse_side(levels[1])
        # Ensure best bid/ask ordering
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        return OrderBookSnapshot(
            bids=bids,
            asks=asks,
            timestamp=_ms_to_utc(raw.get("time")),
        )

    def get_funding_history(
        self,
        coin: str,
        start_time: int,
        end_time: int | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": int(start_time),
        }
        if end_time is not None:
            body["endTime"] = int(end_time)
        raw = self._post(body)
        if not isinstance(raw, list):
            raise HyperliquidResponseError("fundingHistory must return a list")

        history: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            ts = _ms_to_utc(row.get("time"))
            rate = _parse_float(row.get("fundingRate"))
            premium = _parse_float(row.get("premium"))
            history.append(
                {
                    "coin": row.get("coin", coin),
                    "funding_rate": rate,
                    "premium": premium,
                    "time": ts.isoformat() if ts else None,
                    "time_ms": int(row["time"]) if row.get("time") is not None else None,
                }
            )
        history.sort(key=lambda x: x.get("time_ms") or 0)
        return history

    # ----------------------------------------------------------- snapshot
    def _window_ms(self, interval: str) -> tuple[int, int]:
        interval_ms = INTERVAL_MS[interval]
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = end_ms - (self.candle_limit * interval_ms)
        return start_ms, end_ms

    def _resolve_ctx(self, coin: str) -> tuple[dict[str, Any], datetime]:
        contexts = self.get_asset_contexts()
        by_coin = contexts["by_coin"]
        if coin not in by_coin:
            raise HyperliquidSymbolError(f"coin not found on Hyperliquid: {coin!r}")
        return by_coin[coin], contexts["fetched_at"]

    def get_market_snapshot(
        self,
        instrument: CryptoInstrument | str,
        as_of: datetime | None = None,
        *,
        intervals: list[str] | None = None,
    ) -> CryptoMarketSnapshot:
        if isinstance(instrument, str):
            from tradingagents.crypto.instruments import parse_crypto_instrument

            instrument = parse_crypto_instrument(instrument)

        coin = instrument.venue_symbol
        use_intervals = list(intervals or self.analysis_intervals)
        warnings: list[str] = []
        missing: list[str] = []
        source_timestamps: dict[str, datetime] = {}
        now = datetime.now(timezone.utc)
        as_of_utc = _ensure_utc(as_of) if as_of else None
        end_dt = as_of_utc or now
        end_ms = int(end_dt.timestamp() * 1000)

        # --- asset context -------------------------------------------------
        mark_price = mid_price = oracle_price = None
        funding_rate = open_interest = premium = day_ntl = day_chg = None
        try:
            entry, ctx_fetched = self._resolve_ctx(coin)
            ctx = entry.get("ctx") or {}
            mark_price = _parse_float(ctx.get("markPx"))
            mid_price = _parse_float(ctx.get("midPx"))
            oracle_price = _parse_float(ctx.get("oraclePx"))
            funding_rate = _parse_float(ctx.get("funding"))
            open_interest = _parse_float(ctx.get("openInterest"))
            premium = _parse_float(ctx.get("premium"))
            day_ntl = _parse_float(ctx.get("dayNtlVlm"))
            prev = _parse_float(ctx.get("prevDayPx"))
            ref = mark_price if mark_price is not None else mid_price
            if prev is not None and prev != 0 and ref is not None:
                day_chg = (ref - prev) / prev
            source_timestamps["asset_ctx"] = ctx_fetched
        except HyperliquidSymbolError:
            raise
        except HyperliquidError as exc:
            missing.append("asset_ctx")
            warnings.append(f"asset context unavailable: {exc}")

        # --- candles -------------------------------------------------------
        candles: dict[str, list[OHLCVCandle]] = {}
        for interval in use_intervals:
            if interval not in INTERVAL_MS:
                warnings.append(f"skipping unsupported interval {interval}")
                continue
            try:
                start_ms = end_ms - (self.candle_limit * INTERVAL_MS[interval])
                bars = self.get_candles(coin, interval, start_ms, end_ms)
                if as_of_utc is not None:
                    bars = [b for b in bars if b.timestamp <= as_of_utc]
                candles[interval] = bars
                if bars:
                    source_timestamps[f"candles_{interval}"] = bars[-1].timestamp
                else:
                    missing.append(f"candles_{interval}")
            except HyperliquidError as exc:
                missing.append(f"candles_{interval}")
                warnings.append(f"candles {interval} unavailable: {exc}")
                candles[interval] = []

        primary_interval = "1h" if "1h" in candles and candles["1h"] else None
        if primary_interval is None:
            for cand in ("15m", "4h", "1d"):
                if cand in candles and candles[cand]:
                    primary_interval = cand
                    break
        primary = candles.get(primary_interval or "", [])

        # --- order book ----------------------------------------------------
        order_book: OrderBookSnapshot | None = None
        try:
            order_book = self.get_l2_book(coin)
            if order_book.timestamp:
                source_timestamps["l2_book"] = order_book.timestamp
            else:
                source_timestamps["l2_book"] = now
            if mid_price is None and order_book.bids and order_book.asks:
                mid_price = (order_book.bids[0].price + order_book.asks[0].price) / 2.0
        except HyperliquidError as exc:
            missing.append("l2_book")
            warnings.append(f"order book unavailable: {exc}")

        # --- funding history -----------------------------------------------
        funding_history: list[dict[str, Any]] = []
        try:
            start_funding = end_ms - (7 * 86_400_000)
            funding_history = self.get_funding_history(coin, start_funding, end_ms)
            if funding_history:
                last = funding_history[-1]
                if last.get("time"):
                    source_timestamps["funding_history"] = datetime.fromisoformat(
                        last["time"]
                    )
                if funding_rate is None and last.get("funding_rate") is not None:
                    funding_rate = last["funding_rate"]
            else:
                missing.append("funding_history")
        except HyperliquidError as exc:
            missing.append("funding_history")
            warnings.append(f"funding history unavailable: {exc}")

        # --- technicals ----------------------------------------------------
        closes = [c.close for c in primary]
        highs = [c.high for c in primary]
        lows = [c.low for c in primary]
        volumes = [c.volume for c in primary]

        def _returns_for(hours_key: str) -> float | None:
            table = {
                "1h": _RETURNS_LOOKBACK_1H,
                "4h": _RETURNS_LOOKBACK_4H,
                "24h": _RETURNS_LOOKBACK_24H,
            }[hours_key]
            # Prefer matching interval series when available.
            if hours_key == "1h" and candles.get("1h"):
                return calculate_returns([c.close for c in candles["1h"]], 1)
            if hours_key == "4h" and candles.get("4h"):
                return calculate_returns([c.close for c in candles["4h"]], 1)
            if hours_key == "24h":
                if candles.get("1h"):
                    return calculate_returns([c.close for c in candles["1h"]], 24)
                if candles.get("1d"):
                    return calculate_returns([c.close for c in candles["1d"]], 1)
            lookback = table.get(primary_interval or "")
            if lookback is None or not primary:
                return None
            return calculate_returns(closes, lookback)

        best_bid = order_book.bids[0].price if order_book and order_book.bids else None
        best_ask = order_book.asks[0].price if order_book and order_book.asks else None
        spread = calculate_spread_bps(best_bid, best_ask)
        imbalance = None
        if order_book and order_book.bids and order_book.asks:
            imbalance = calculate_order_book_imbalance(
                [lvl.size for lvl in order_book.bids],
                [lvl.size for lvl in order_book.asks],
            )

        ema_20 = calculate_ema(closes, 20) if closes else None
        ema_50 = calculate_ema(closes, 50) if closes else None
        last_price = closes[-1] if closes else (mark_price or mid_price)
        rsi_14 = calculate_rsi(closes, 14) if closes else None
        atr_14 = calculate_atr(highs, lows, closes, 14) if closes else None
        realized_vol = calculate_realized_volatility(closes, 24) if closes else None
        vol_chg = calculate_volume_change(volumes, 24) if volumes else None
        support, resistance = (
            calculate_support_resistance(highs, lows, closes, 50)
            if closes
            else ([], [])
        )

        def _dist(ema: float | None) -> float | None:
            if ema is None or last_price is None or ema == 0:
                return None
            return (last_price - ema) / ema

        returns_1h = _returns_for("1h")
        returns_4h = _returns_for("4h")
        returns_24h = _returns_for("24h")

        technical = TechnicalSnapshot(
            returns_1h=returns_1h,
            returns_4h=returns_4h,
            returns_24h=returns_24h,
            ema_20=ema_20,
            ema_50=ema_50,
            rsi_14=rsi_14,
            atr_14=atr_14,
            realized_volatility=realized_vol,
            volume_change_pct=vol_chg,
            distance_from_ema20_pct=_dist(ema_20),
            distance_from_ema50_pct=_dist(ema_50),
            order_book_imbalance=imbalance,
            spread_bps=spread,
            support_levels=support,
            resistance_levels=resistance,
        )

        regime = classify_market_regime(
            returns_24h=returns_24h,
            ema_20=ema_20,
            ema_50=ema_50,
            last_price=last_price,
            realized_vol=realized_vol,
            spread_bps=spread,
            imbalance=imbalance,
        )

        derivatives = DerivativesSnapshot(
            funding_rate=funding_rate,
            funding_history=funding_history,
            open_interest=open_interest,
            open_interest_change_24h_pct=None,  # not available from public Info
            perpetual_premium=premium,
            day_notional_volume=day_ntl,
            day_price_change_pct=day_chg,
            long_liquidations=None,
            short_liquidations=None,
        )

        candles_ok = any(bool(v) for v in candles.values())
        order_book_ok = order_book is not None and bool(
            order_book.bids or order_book.asks
        )
        derivatives_ok = funding_rate is not None or bool(funding_history)

        # Max age relative to freshest source (or now if none).
        freshest = max(source_timestamps.values()) if source_timestamps else now
        age = (now - _ensure_utc(freshest)).total_seconds()
        is_stale = age > self.max_data_age_seconds

        if not candles_ok and "candles" not in missing:
            missing.append("candles")
        if not order_book_ok and "l2_book" not in missing:
            missing.append("l2_book")
        if not derivatives_ok and "derivatives" not in missing:
            missing.append("derivatives")

        data_quality = DataQuality(
            candles_ok=candles_ok,
            order_book_ok=order_book_ok,
            derivatives_ok=derivatives_ok,
            missing_sources=sorted(set(missing)),
            max_data_age_seconds=age,
            is_stale=is_stale,
        )

        if not source_timestamps:
            source_timestamps["snapshot"] = now

        snapshot_id = _stable_snapshot_id(
            instrument.venue, instrument, source_timestamps
        )

        return CryptoMarketSnapshot(
            snapshot_id=snapshot_id,
            timestamp=now,
            instrument=instrument,
            mark_price=mark_price,
            mid_price=mid_price,
            oracle_price=oracle_price,
            candles=candles,
            order_book=order_book,
            derivatives=derivatives,
            technical=technical,
            regime=regime,
            data_quality=data_quality,
            source_timestamps=source_timestamps,
            warnings=warnings,
        )


def build_client_from_config(config: dict[str, Any] | None = None) -> HyperliquidClient:
    """Construct a client from a TradingAgents / Circuit config dict."""
    cfg = config or {}
    return HyperliquidClient(
        timeout_seconds=float(cfg.get("crypto_request_timeout_seconds", DEFAULT_TIMEOUT)),
        cache_ttl_seconds=float(cfg.get("crypto_snapshot_cache_seconds", DEFAULT_CACHE_TTL)),
        max_data_age_seconds=float(cfg.get("crypto_max_data_age_seconds", 180)),
        candle_limit=int(cfg.get("crypto_candle_limit", 300)),
        analysis_intervals=list(
            cfg.get("crypto_analysis_intervals") or ["15m", "1h", "4h", "1d"]
        ),
    )
