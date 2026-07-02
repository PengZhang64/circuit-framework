"""Strategy profile loader tests."""

import pytest

from tradingagents.strategies import apply_strategy_to_config, list_strategies, load_strategy
from tradingagents.default_config import DEFAULT_CONFIG


def test_list_strategies_includes_expected():
    names = list_strategies()
    for expected in (
        "balanced",
        "momentum",
        "mean_reversion",
        "derivatives",
        "narrative",
        "macro_regime",
        "quant_systematic",
    ):
        assert expected in names


def test_load_strategy_required_keys():
    profile = load_strategy("balanced")
    assert profile["name"]
    assert isinstance(profile["analyst_weights"], dict)
    assert profile["max_leverage"] > 0


def test_apply_strategy_overlays_risk():
    cfg = apply_strategy_to_config(DEFAULT_CONFIG.copy(), "momentum")
    mom = load_strategy("momentum")
    assert cfg["paper_max_leverage"] == float(mom["max_leverage"])
    assert cfg["paper_max_position_pct"] == float(mom["max_position_pct"])
    assert cfg["strategy_profile"] == mom["name"]
    assert cfg["strategy_prompt_overlay"]


def test_unknown_strategy():
    with pytest.raises(FileNotFoundError):
        load_strategy("not_a_real_strategy")
