"""Process-local store for the current crypto market snapshot.

The Snapshot Builder is the only writer on the crypto analysis path. Analyst
tools read from here so every agent operates on the same immutable snapshot
for a run without re-fetching live market data.
"""

from __future__ import annotations

import threading

from tradingagents.crypto.schemas import CryptoMarketSnapshot

_lock = threading.Lock()
_current: CryptoMarketSnapshot | None = None


def set_snapshot(snapshot: CryptoMarketSnapshot) -> None:
    """Replace the current-run snapshot."""
    global _current
    with _lock:
        _current = snapshot


def get_snapshot() -> CryptoMarketSnapshot | None:
    """Return the current-run snapshot, or None if unset."""
    with _lock:
        return _current


def clear_snapshot() -> None:
    """Clear the current-run snapshot."""
    global _current
    with _lock:
        _current = None


def get_snapshot_required() -> CryptoMarketSnapshot:
    """Return the current snapshot or raise if it has not been built."""
    snapshot = get_snapshot()
    if snapshot is None:
        raise RuntimeError(
            "crypto market snapshot unavailable — Snapshot Builder must run first"
        )
    return snapshot
