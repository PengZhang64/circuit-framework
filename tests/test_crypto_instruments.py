"""Tests for canonical crypto instrument parsing."""

import pytest

from tradingagents.crypto.instruments import (
    is_standalone_crypto_symbol,
    parse_crypto_instrument,
)


@pytest.mark.parametrize(
    "raw,base,display",
    [
        ("BTC", "BTC", "BTC-PERP"),
        ("btc", "BTC", "BTC-PERP"),
        ("BTC-USD", "BTC", "BTC-PERP"),
        ("BTC-USDT", "BTC", "BTC-PERP"),
        ("BTC/USDC", "BTC", "BTC-PERP"),
        ("BTC-PERP", "BTC", "BTC-PERP"),
        ("ETH", "ETH", "ETH-PERP"),
        ("SOL-PERP", "SOL", "SOL-PERP"),
        ("HYPE", "HYPE", "HYPE-PERP"),
        ("BTCUSD", "BTC", "BTC-PERP"),
    ],
)
def test_accepted_symbol_normalization(raw, base, display):
    inst = parse_crypto_instrument(raw)
    assert inst.base_asset == base
    assert inst.venue_symbol == base
    assert inst.display_symbol == display
    assert inst.instrument_type == "perp"
    assert inst.venue == "hyperliquid"
    assert inst.quote_asset == "USDG"


def test_spot_instrument_type():
    inst = parse_crypto_instrument("ETH", instrument_type="spot")
    assert inst.instrument_type == "spot"
    assert inst.display_symbol == "ETH-USDG"


@pytest.mark.parametrize("raw", ["", "   ", "123", None])
def test_invalid_symbol_rejection(raw):
    with pytest.raises((ValueError, TypeError, AttributeError)):
        if raw is None:
            parse_crypto_instrument(None)  # type: ignore[arg-type]
        else:
            parse_crypto_instrument(raw)


def test_standalone_crypto_detection():
    assert is_standalone_crypto_symbol("BTC")
    assert is_standalone_crypto_symbol("HYPE")
    assert not is_standalone_crypto_symbol("AAPL")
    assert not is_standalone_crypto_symbol("BRK.B")
