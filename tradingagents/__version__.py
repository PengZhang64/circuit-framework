"""Package version for Circuit Framework / TradingAgents."""

from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("tradingagents")
    except PackageNotFoundError:
        __version__ = "0.3.1"
except ImportError:  # pragma: no cover
    __version__ = "0.3.1"
