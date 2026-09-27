"""Maintained lists for the parts of the tradable universe we cannot sync by API.

Crypto (Robinhood Crypto, US)
    Source: https://robinhood.com/us/en/support/articles/coin-availability/
    ("Supported crypto" table), accessed 2026-09-27. The page carries no
    publication date. A coin is listed here only when its row says
    "Tradable in-app and on web classic with market maker routing: Yes".
    Robinhood's crypto trading-pairs API needs signed keys we do not have yet;
    once we do, replace this list with an API sync (docs/S2_DESIGN.md §2).

    ZRX (0x Protocol) is kept out of the verified set: on the same page it is
    both in the tradable table and in the "market data only, not tradable" list.

    State restrictions from the same page are recorded for information only;
    tradability is judged for the US as a whole.

Futures (Robinhood Derivatives)
    Source: https://robinhood.com/us/en/about/futures/ (product tables for
    stock index, energy, currency, metals and crypto), accessed 2026-09-27.
    Registered for classification only: futures are NOT settleable yet (S3+).
    The currency-table names below are inferred from standard CME product
    codes; the page's JSON listed the codes, only the first rows were read
    with their names.

Event contracts (Robinhood prediction markets)
    Source: https://robinhood.com/us/en/prediction-markets/ (category tabs),
    accessed 2026-09-27. Event contracts have no stable ticker scheme, so the
    codebase uses the convention ``EVENT:<slug>``. Individual contracts are not
    verified against Robinhood; they are NOT settleable yet.
"""
from __future__ import annotations

CRYPTO_SOURCE = "https://robinhood.com/us/en/support/articles/coin-availability/"
FUTURES_SOURCE = "https://robinhood.com/us/en/about/futures/"
EVENT_SOURCE = "https://robinhood.com/us/en/prediction-markets/"
REGISTRY_CHECKED_ON = "2026-09-27"

# Base symbols of coins tradable on Robinhood Crypto (US). yfinance ticker is "<SYM>-USD".
ROBINHOOD_CRYPTO: frozenset[str] = frozenset({
    "BTC", "ETH", "DOGE", "LTC", "SHIB", "AAVE", "AERO", "ALGO", "ARB", "FET",
    "ASTER", "AVAX", "AVNT", "AXS", "BAT", "BILL", "BIO", "BCH", "BNB", "BONK",
    "CC", "ADA", "CASHCAT", "MEW", "LINK", "COMP", "ATOM", "CRV", "WIF", "EIGEN",
    "ENA", "ETC", "FLR", "FLOKI", "USDG", "GRAM", "HBAR", "HYPE", "IMX", "INJ",
    "JTO", "ZRO", "LDO", "LIT", "MNT", "SYRUP", "MEGA", "MOODENG", "MORPHO", "NEAR",
    "TRUMP", "ONDO", "XCN", "OP", "ORCA", "PAXG", "PNUT", "PEPE", "XPL", "DOT",
    "POPCAT", "PENGU", "PYTH", "QNT", "RAY", "RE", "RENDER", "SKR", "SEI", "SENT",
    "SKY", "SOL", "STRK", "SUI", "XLM", "SNX", "XTZ", "GRT", "UNI", "USDC",
    "CHIP", "VVV", "VIRTUAL", "WLFI", "WLD", "W", "XRP", "ZEC", "ZORA",
})

# Listed ambiguously by the source; classified as crypto but not as tradable.
UNVERIFIED_CRYPTO: frozenset[str] = frozenset({"ZRX"})

# Informational: "Not available for trading in New York" (¹) / "... in Texas" (²).
CRYPTO_STATE_RESTRICTIONS: dict[str, tuple[str, ...]] = {
    **{sym: ("NY",) for sym in (
        "ASTER", "AVNT", "BILL", "BNB", "CASHCAT", "MEW", "EIGEN", "FLOKI", "USDG",
        "GRAM", "HYPE", "JTO", "ZRO", "LIT", "MEGA", "MOODENG", "TRUMP", "ONDO",
        "PAXG", "PNUT", "XPL", "POPCAT", "PENGU", "RE", "SENT", "SKY", "SNX",
        "CHIP", "WLFI", "WLD", "ZORA",
    )},
    "USDC": ("TX",),
}

# Root symbol -> product name, as listed by Robinhood. Written "/ES" on Robinhood,
# "ES=F" on yfinance.
ROBINHOOD_FUTURES: dict[str, str] = {
    # Stock index
    "ES": "E-mini S&P 500", "MES": "Micro S&P 500", "NES": "Nano S&P 500",
    "NQ": "E-mini Nasdaq 100", "MNQ": "Micro Nasdaq 100", "NNQ": "Nano Nasdaq-100",
    "YM": "E-mini Dow Jones", "MYM": "Micro Dow Jones", "NDOW": "Nano Dow Jones",
    "RTY": "E-mini Russell 2000", "M2K": "Micro Russell 2000", "N2K": "Nano Russell 2000",
    # Energy
    "CL": "Crude Oil", "MCL": "Micro Crude Oil", "NG": "Natural Gas",
    "MNG": "Micro Natural Gas", "RB": "RBOB Gasoline",
    # Currency
    "6E": "Euro", "M6E": "Micro Euro", "6J": "Japanese Yen", "6B": "British Pound",
    "M6B": "Micro British Pound", "6A": "Australian Dollar", "M6A": "Micro Australian Dollar",
    "6C": "Canadian Dollar", "MCD": "Micro Canadian Dollar", "6S": "Swiss Franc",
    "MSF": "Micro Swiss Franc", "6N": "New Zealand Dollar",
    # Metals
    "GC": "Gold", "MGC": "Micro Gold", "1OZ": "1-Ounce Gold", "SI": "Silver",
    "SIL": "Micro Silver", "HG": "Copper", "MHG": "Micro Copper", "SIC": "100-Ounce Silver",
    # Crypto
    "BTC": "Bitcoin", "MBT": "Micro Bitcoin", "BFF": "Bitcoin Friday", "ETH": "Ether",
    "MET": "Micro Ether", "SOL": "Solana", "MSL": "Micro Solana", "XRP": "XRP",
    "MXP": "Micro XRP", "ADA": "Cardano", "MCA": "Micro Cardano", "LNK": "Chainlink",
    "MLN": "Micro Chainlink", "XLM": "Stellar", "MXL": "Micro Stellar",
}

# Prediction-market categories shown on Robinhood; used only to document scope.
EVENT_CONTRACT_CATEGORIES: frozenset[str] = frozenset({
    "economics", "financial", "commodities", "metals", "crypto", "climate",
    "politics", "elections", "technology", "entertainment", "education", "sports",
})
EVENT_CONTRACT_PREFIX = "EVENT:"
