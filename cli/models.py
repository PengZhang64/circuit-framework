from enum import Enum


class AnalystType(str, Enum):
    MARKET = "market"
    # Wire value stays "social" for saved-config and string-keyed-caller
    # back-compat; the user-facing label is "Sentiment Analyst".
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"
    # Circuit Framework crypto analysts
    DERIVATIVES = "derivatives"
    CATALYST = "catalyst"
    REGIME = "regime"


class AssetType(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
