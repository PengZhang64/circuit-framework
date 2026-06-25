"""Tests for Hyperliquid public Info adapter — fixture-backed, no network."""

from datetime import datetime, timezone

import pytest

from tradingagents.crypto.instruments import parse_crypto_instrument
from tradingagents.dataflows.hyperliquid import (
    HyperliquidClient,
    HyperliquidResponseError,
    HyperliquidSymbolError,
    _parse_float,
)
from tests.crypto_test_utils import install_hyperliquid_fixtures, load_fixture


def test_string_to_number_parsing():
    assert _parse_float("97500.5") == 97500.5
    assert _parse_float(None) is None
    assert _parse_float("bad") is None
    assert _parse_float(True) is None


def test_get_asset_contexts(monkeypatch):
    client = HyperliquidClient(cache_ttl_seconds=0)
    install_hyperliquid_fixtures(monkeypatch, client)
    ctx = client.get_asset_contexts()
    assert "BTC" in ctx["by_coin"]
    mark = _parse_float(ctx["by_coin"]["BTC"]["ctx"]["markPx"])
    assert mark == 97500.5


def test_get_candles_sorted(monkeypatch):
    client = HyperliquidClient(cache_ttl_seconds=0)
    install_hyperliquid_fixtures(monkeypatch, client)
    bars = client.get_candles("BTC", "1h", 0, 9_999_999_999_999)
    assert len(bars) > 10
    assert all(bars[i].timestamp <= bars[i + 1].timestamp for i in range(len(bars) - 1))


def test_empty_candles(monkeypatch):
    client = HyperliquidClient(cache_ttl_seconds=0)

    def _post(body, *, use_cache=True):
        if body.get("type") == "candleSnapshot":
            return []
        raise AssertionError(body)

    monkeypatch.setattr(client, "_post", _post)
    assert client.get_candles("BTC", "1h", 0, 1) == []


def test_unsorted_candles_get_sorted(monkeypatch):
    client = HyperliquidClient(cache_ttl_seconds=0)
    raw = load_fixture("candle_snapshot_btc_1h.json")
    shuffled = list(reversed(raw[:5]))

    def _post(body, *, use_cache=True):
        return shuffled

    monkeypatch.setattr(client, "_post", _post)
    bars = client.get_candles("BTC", "1h", 0, 1)
    assert [b.timestamp for b in bars] == sorted(b.timestamp for b in bars)


def test_missing_api_fields_in_book(monkeypatch):
    client = HyperliquidClient(cache_ttl_seconds=0)

    def _post(body, *, use_cache=True):
        return {"levels": [[{"px": "1"}], []], "time": None}

    monkeypatch.setattr(client, "_post", _post)
    book = client.get_l2_book("BTC")
    # sz missing → incomplete levels skipped
    assert book.bids == []
    assert book.asks == []


def test_invalid_symbol(monkeypatch):
    client = HyperliquidClient(cache_ttl_seconds=0)
    install_hyperliquid_fixtures(monkeypatch, client)
    with pytest.raises(HyperliquidSymbolError):
        client._resolve_ctx("NOTACOIN123")


def test_market_snapshot_stable_id(monkeypatch):
    client = HyperliquidClient(
        cache_ttl_seconds=0,
        analysis_intervals=["1h"],
        max_data_age_seconds=10**9,
    )
    install_hyperliquid_fixtures(monkeypatch, client)
    inst = parse_crypto_instrument("BTC")
    a = client.get_market_snapshot(inst, intervals=["1h"])
    b = client.get_market_snapshot(inst, intervals=["1h"])
    assert a.snapshot_id == b.snapshot_id
    assert a.mark_price == 97500.5
    assert a.mid_price == 97501.0
    assert a.data_quality.candles_ok


def test_unsupported_interval():
    client = HyperliquidClient()
    with pytest.raises(HyperliquidResponseError):
        client.get_candles("BTC", "7m", 0, 1)
