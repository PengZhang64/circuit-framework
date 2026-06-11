"""Load YAML strategy profiles and apply risk overrides to config."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_STRATEGIES_DIR = Path(__file__).resolve().parent

_REQUIRED_KEYS = (
    "name",
    "description",
    "analyst_weights",
    "prompt_overlay",
    "preferred_time_horizon",
    "minimum_confidence",
    "max_position_pct",
    "max_leverage",
    "risk_per_trade_pct",
)


def _strategy_path(name: str) -> Path:
    safe = name.strip().lower().replace(" ", "_")
    path = _STRATEGIES_DIR / f"{safe}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"strategy profile not found: {name!r} ({path})")
    return path


def list_strategies() -> list[str]:
    """Return available strategy profile names (yaml stem), sorted."""
    names = sorted(p.stem for p in _STRATEGIES_DIR.glob("*.yaml"))
    return names


@lru_cache(maxsize=32)
def _load_yaml(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"strategy file must be a mapping: {path}")
    return data


def load_strategy(name: str) -> dict[str, Any]:
    """Load and validate a strategy profile by name."""
    path = _strategy_path(name)
    data = dict(_load_yaml(str(path)))
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"strategy {name!r} missing keys: {missing}")
    if not isinstance(data.get("analyst_weights"), dict):
        raise ValueError(f"strategy {name!r} analyst_weights must be a mapping")
    # Normalize name to stem for consistency
    data["name"] = str(data.get("name") or path.stem)
    return data


def apply_strategy_to_config(
    config: dict[str, Any],
    strategy: str | dict[str, Any],
) -> dict[str, Any]:
    """Return a deep-copied config with strategy risk overrides applied.

    Maps:
      max_position_pct  -> paper_max_position_pct
      max_leverage      -> paper_max_leverage
      risk_per_trade_pct -> paper_risk_per_trade_pct
      minimum_confidence -> crypto_minimum_confidence
      preferred_time_horizon -> crypto_preferred_time_horizon
      name -> strategy_profile / default_crypto_strategy
    """
    profile = load_strategy(strategy) if isinstance(strategy, str) else dict(strategy)
    out = deepcopy(config)
    out["paper_max_position_pct"] = float(profile["max_position_pct"])
    out["paper_max_leverage"] = float(profile["max_leverage"])
    out["paper_risk_per_trade_pct"] = float(profile["risk_per_trade_pct"])
    out["crypto_minimum_confidence"] = float(profile["minimum_confidence"])
    out["crypto_preferred_time_horizon"] = str(profile["preferred_time_horizon"])
    out["strategy_profile"] = str(profile["name"])
    out["default_crypto_strategy"] = str(profile["name"])
    out["strategy_prompt_overlay"] = str(profile.get("prompt_overlay") or "")
    out["strategy_analyst_weights"] = dict(profile.get("analyst_weights") or {})
    return out
