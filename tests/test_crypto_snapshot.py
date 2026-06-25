"""Snapshot builder / immutability / ID stability tests."""

from tradingagents.crypto.instruments import parse_crypto_instrument
from tradingagents.crypto.snapshot_store import (
    clear_snapshot,
    get_snapshot,
    set_snapshot,
)
from tradingagents.dataflows.hyperliquid import HyperliquidClient
from tests.crypto_test_utils import install_hyperliquid_fixtures, make_fresh_snapshot


def test_snapshot_immutability():
    snap = make_fresh_snapshot()
    try:
        snap.mark_price = 1  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised


def test_snapshot_store_roundtrip():
    clear_snapshot()
    snap = make_fresh_snapshot()
    set_snapshot(snap)
    assert get_snapshot() is snap
    clear_snapshot()
    assert get_snapshot() is None


def test_fixture_snapshot_id_stability(monkeypatch):
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
    assert a.instrument.venue_symbol == "BTC"
    assert a.technical.spread_bps is not None or a.order_book is not None
