"""Canonical crypto instrument parsing for Circuit Framework."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

_CRYPTO_BASES = frozenset(
    {
        "BTC",
        "ETH",
        "SOL",
        "HYPE",
        "BNB",
        "XRP",
        "DOGE",
        "ADA",
        "AVAX",
        "LINK",
        "MATIC",
        "DOT",
        "ATOM",
        "NEAR",
        "ARB",
        "OP",
        "APT",
        "SUI",
        "TIA",
        "INJ",
        "SEI",
        "WIF",
        "PEPE",
        "WLD",
        "RENDER",
        "FIL",
        "AAVE",
        "UNI",
        "LTC",
        "BCH",
        "TRX",
        "TON",
        "kPEPE",
        "PURR",
    }
)

_QUOTE_ALIASES = {
    "USD": "USDG",
    "USDT": "USDG",
    "USDC": "USDG",
    "USDG": "USDG",
}


class CryptoInstrument(BaseModel):
    """Immutable canonical crypto instrument identity."""

    model_config = {"frozen": True}

    base_asset: str
    quote_asset: str = "USDG"
    venue: str = "hyperliquid"
    instrument_type: Literal["perp", "spot"] = "perp"
    venue_symbol: str
    display_symbol: str

    @property
    def symbol(self) -> str:
        return self.display_symbol


def _clean_token(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", (raw or "").strip()).upper()


def parse_crypto_instrument(
    symbol: str,
    *,
    venue: str = "hyperliquid",
    instrument_type: Literal["perp", "spot"] = "perp",
    quote_currency: str = "USDG",
) -> CryptoInstrument:
    """Normalize human crypto symbols into a canonical CryptoInstrument.

    Accepts: BTC, BTC-USD, BTC-USDT, BTC/USDC, BTC-PERP, ETH, SOL-PERP, HYPE.
    For Hyperliquid perps the venue_symbol is the base asset (e.g. BTC).
    """
    if not symbol or not str(symbol).strip():
        raise ValueError("symbol is required")

    raw = str(symbol).strip().upper().replace(" ", "")
    raw = raw.replace("/", "-")

    base = raw
    quote = quote_currency.upper()

    if raw.endswith("-PERP"):
        base = raw[: -len("-PERP")]
    elif "-" in raw:
        parts = [p for p in raw.split("-") if p]
        if len(parts) >= 2 and parts[-1] in _QUOTE_ALIASES:
            base = parts[0]
            quote = _QUOTE_ALIASES[parts[-1]]
        elif len(parts) >= 2 and parts[-1] == "PERP":
            base = parts[0]
        else:
            base = parts[0]
    else:
        # Compact forms: BTCUSD, BTCUSDT
        for q_in, q_out in (("USDT", "USDG"), ("USDC", "USDG"), ("USD", "USDG")):
            if base.endswith(q_in) and len(base) > len(q_in):
                maybe = base[: -len(q_in)]
                if maybe:
                    base = maybe
                    quote = q_out
                    break

    base = _clean_token(base)
    if not base:
        raise ValueError(f"could not parse crypto symbol: {symbol!r}")

    # Reject clearly invalid (stock-like with digits only / exchange suffix)
    if re.fullmatch(r"\d+", base):
        raise ValueError(f"invalid crypto symbol: {symbol!r}")

    venue_symbol = base
    display = f"{base}-PERP" if instrument_type == "perp" else f"{base}-{quote}"

    return CryptoInstrument(
        base_asset=base,
        quote_asset=_QUOTE_ALIASES.get(quote, quote),
        venue=venue,
        instrument_type=instrument_type,
        venue_symbol=venue_symbol,
        display_symbol=display,
    )


def is_known_crypto_base(symbol: str) -> bool:
    try:
        inst = parse_crypto_instrument(symbol)
    except ValueError:
        return False
    return inst.base_asset in _CRYPTO_BASES or len(inst.base_asset) <= 10


def is_standalone_crypto_symbol(symbol: str) -> bool:
    """True for bare bases like BTC/ETH/SOL/HYPE (no exchange suffix)."""
    cleaned = (symbol or "").strip().upper()
    if not cleaned or any(ch in cleaned for ch in ".=^"):
        return False
    try:
        inst = parse_crypto_instrument(cleaned)
    except ValueError:
        return False
    # Known bases, or compact USD pairs that resolve to a clean base
    return inst.base_asset in _CRYPTO_BASES or (
        cleaned.replace("-", "").replace("/", "").endswith(("USD", "USDT", "USDC", "PERP"))
        and len(inst.base_asset) <= 10
    )
