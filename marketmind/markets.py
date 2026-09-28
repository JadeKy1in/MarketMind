"""Where a ticker trades: exchange timezone, session times, costs, market benchmark.

Tickers use Yahoo-style symbols (docs/S3_DESIGN.md §7): plain US symbols, BASE-USD
crypto, `.HK/.SS/.SZ/.T/.DE/...` exchange suffixes, `=F` futures, `=X` FX pairs,
`^` indices (priced, but not tradable - use an ETF or future instead).
Pure lookups, no I/O: used by price_history, the ledger and the shadow runner.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

CASH = "CASH"   # benchmark that earns 0 (FX pairs, rates futures)


@dataclass(frozen=True)
class Market:
    code: str
    tz: str                 # IANA timezone of the exchange ("UTC" = UTC-day bars)
    open: time
    close: time
    cost_bps: float         # one-way cost estimate
    benchmark: str          # market benchmark ticker, or CASH
    asset_class: str        # equity | crypto | future | fx | index
    utc_days: bool = False  # bars are UTC calendar days (crypto, FX)


US = Market("US", "America/New_York", time(9, 30), time(16, 0), 5.0, "SPY", "equity")
CRYPTO = Market("CRYPTO", "UTC", time(0, 0), time(23, 59), 100.0, "BTC-USD", "crypto", True)
FX = Market("FX", "UTC", time(0, 0), time(23, 59), 2.0, CASH, "fx", True)
# CME/ICE daily bars are dated by trade date and settle in the New York afternoon.
FUTURE = Market("FUTURE", "America/New_York", time(9, 30), time(17, 0), 2.0, "DBC", "future")
RATES_FUTURE = Market("RATES_FUTURE", "America/New_York", time(9, 30), time(17, 0), 2.0,
                      CASH, "future")
INDEX = Market("INDEX", "America/New_York", time(9, 30), time(16, 0), 0.0, CASH, "index")

_SUFFIX: dict[str, Market] = {
    "HK": Market("HK", "Asia/Hong_Kong", time(9, 30), time(16, 0), 10.0, "2800.HK", "equity"),
    "SS": Market("CN", "Asia/Shanghai", time(9, 30), time(15, 0), 10.0, "510300.SS", "equity"),
    "SZ": Market("CN", "Asia/Shanghai", time(9, 30), time(15, 0), 10.0, "510300.SS", "equity"),
    "T": Market("JP", "Asia/Tokyo", time(9, 0), time(15, 30), 10.0, "1306.T", "equity"),
    "DE": Market("DE", "Europe/Berlin", time(9, 0), time(17, 30), 10.0, "^GDAXI", "equity"),
    "PA": Market("FR", "Europe/Paris", time(9, 0), time(17, 30), 10.0, "^FCHI", "equity"),
    "AS": Market("NL", "Europe/Amsterdam", time(9, 0), time(17, 30), 10.0, "^AEX", "equity"),
    "L": Market("UK", "Europe/London", time(8, 0), time(16, 30), 10.0, "^FTSE", "equity"),
    "CO": Market("DK", "Europe/Copenhagen", time(9, 0), time(17, 0), 10.0, "^OMXC25", "equity"),
    "SW": Market("CH", "Europe/Zurich", time(9, 0), time(17, 30), 10.0, "^SSMI", "equity"),
    "MI": Market("IT", "Europe/Rome", time(9, 0), time(17, 30), 10.0, "FTSEMIB.MI", "equity"),
    "MC": Market("ES", "Europe/Madrid", time(9, 0), time(17, 30), 10.0, "^IBEX", "equity"),
    "NS": Market("IN", "Asia/Kolkata", time(9, 15), time(15, 30), 10.0, "^NSEI", "equity"),
    "KS": Market("KR", "Asia/Seoul", time(9, 0), time(15, 30), 10.0, "^KS11", "equity"),
    "TW": Market("TW", "Asia/Taipei", time(9, 0), time(13, 30), 10.0, "^TWII", "equity"),
    "AX": Market("AU", "Australia/Sydney", time(10, 0), time(16, 0), 10.0, "^AXJO", "equity"),
    "TO": Market("CA", "America/Toronto", time(9, 30), time(16, 0), 10.0, "^GSPTSE", "equity"),
    "SA": Market("BR", "America/Sao_Paulo", time(10, 0), time(17, 0), 10.0, "^BVSP", "equity"),
    "MX": Market("MX", "America/Mexico_City", time(8, 30), time(15, 0), 10.0, "^MXX", "equity"),
}

_RATES_ROOTS = {"ZN", "ZB", "ZF", "ZT", "UB", "TN", "SR3", "ZQ"}


def market_for(ticker: str) -> Market:
    t = (ticker or "").strip().upper()
    if t.startswith("^"):
        return INDEX
    if t.endswith("-USD"):
        return CRYPTO
    if t.endswith("=X"):
        return FX
    if t.endswith("=F"):
        return RATES_FUTURE if t[:-2] in _RATES_ROOTS else FUTURE
    if "." in t:
        suffix = t.rsplit(".", 1)[1]
        if suffix in _SUFFIX:
            return _SUFFIX[suffix]
    return US


def is_shadow_tradable(ticker: str) -> bool:
    """Shadows may trade anything with a real market except a bare index (docs/S3_DESIGN §7)."""
    t = (ticker or "").strip().upper()
    return bool(t) and market_for(t).asset_class != "index"


def yahoo_symbol(ticker: str) -> str:
    """Symbol to send to Yahoo/yfinance. HK codes use Yahoo's 4-digit form.

    Yahoo 404s on 5-digit HK codes ("09866.HK") but serves "9866.HK"; "0700.HK" stays.
    Only the request symbol changes: ledgers keep the ticker as written.
    """
    t = (ticker or "").strip()
    if t.upper().endswith(".HK") and t[:-3].isdigit():
        return (t[:-3].lstrip("0") or "0").zfill(4) + ".HK"
    return t
