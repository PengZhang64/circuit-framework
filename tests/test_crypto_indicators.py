"""Deterministic indicator unit tests."""

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


def test_ema_known_values():
    closes = [float(i) for i in range(1, 40)]
    ema = calculate_ema(closes, 20)
    assert ema is not None
    assert ema > closes[0]
    assert calculate_ema(closes[:5], 20) is None


def test_rsi_bounds_and_flat():
    # Mixed series with both gains and losses so RSI is defined
    mixed = [100, 102, 101, 103, 102, 104, 103, 105, 104, 106] * 3
    rsi = calculate_rsi(mixed, 14)
    assert rsi is not None
    assert 0 <= rsi <= 100
    flat = [50.0] * 30
    assert calculate_rsi(flat, 14) == 50.0


def test_atr_positive():
    highs = [11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26]
    lows = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
    closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25]
    atr = calculate_atr(highs, lows, closes, 14)
    assert atr is not None and atr > 0


def test_returns_helper():
    closes = [100.0, 110.0, 121.0]
    assert abs(calculate_returns(closes, 1) - 0.1) < 1e-9
    assert abs(calculate_returns(closes, 2) - 0.21) < 1e-9
    assert calculate_returns(closes, 5) is None


def test_spread_imbalance_volume_vol():
    assert calculate_spread_bps(100, 100.1) is not None
    assert calculate_order_book_imbalance([2, 1], [1, 1]) > 0
    vol = calculate_realized_volatility([100 + i * 0.5 for i in range(40)], 24)
    assert vol is not None
    vchg = calculate_volume_change([1] * 20 + [2] * 24, 24)
    assert vchg is not None


def test_support_resistance_and_regime():
    closes = [100 + (i % 5) for i in range(60)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    support, resistance = calculate_support_resistance(highs, lows, closes, 50)
    assert isinstance(support, list) and isinstance(resistance, list)
    regime = classify_market_regime(
        returns_24h=0.05,
        ema_20=110,
        ema_50=100,
        last_price=112,
        realized_vol=0.01,
        spread_bps=5,
        imbalance=0.2,
    )
    assert regime.trend in {
        "strong_uptrend",
        "uptrend",
        "range",
        "downtrend",
        "strong_downtrend",
    }
