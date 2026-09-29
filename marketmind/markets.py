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
    asset_class: str        # equity | crypto | future | fx | index | unknown
    utc_days: bool = False  # bars are UTC calendar days (crypto, FX)


US = Market("US", "America/New_York", time(9, 30), time(16, 0), 5.0, "SPY", "equity")
CRYPTO = Market("CRYPTO", "UTC", time(0, 0), time(23, 59), 100.0, "BTC-USD", "crypto", True)
FX = Market("FX", "UTC", time(0, 0), time(23, 59), 2.0, CASH, "fx", True)
# CME/ICE daily bars are dated by trade date and settle in the New York afternoon.
FUTURE = Market("FUTURE", "America/New_York", time(9, 30), time(17, 0), 2.0, "DBC", "future")
RATES_FUTURE = Market("RATES_FUTURE", "America/New_York", time(9, 30), time(17, 0), 2.0,
                      CASH, "future")
INDEX = Market("INDEX", "America/New_York", time(9, 30), time(16, 0), 0.0, CASH, "index")
# A suffix we have no session/benchmark data for. Not settleable and not shadow-tradable
# (it used to fall back to US hours, costs and SPY). UTC-day bars: today's bar is only
# treated as complete after the UTC day ends, which is conservative for any exchange.
UNKNOWN = Market("UNKNOWN", "UTC", time(0, 0), time(23, 59), 10.0, CASH, "unknown", True)

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
    # Added 2026-09-29 (red-team fix: these fell back to US). Benchmarks checked live on
    # Yahoo 2026-09-29 (>= 1 year of daily bars each); cost = the existing non-US default.
    "SI": Market("SG", "Asia/Singapore", time(9, 0), time(17, 0), 10.0, "^STI", "equity"),
    "KQ": Market("KR", "Asia/Seoul", time(9, 0), time(15, 30), 10.0, "^KQ11", "equity"),
    "ST": Market("SE", "Europe/Stockholm", time(9, 0), time(17, 30), 10.0, "^OMX", "equity"),
    "OL": Market("NO", "Europe/Oslo", time(9, 0), time(16, 20), 10.0, "OSEBX.OL", "equity"),
    "F": Market("DE", "Europe/Berlin", time(8, 0), time(22, 0), 10.0, "^GDAXI", "equity"),
    "JK": Market("ID", "Asia/Jakarta", time(9, 0), time(16, 0), 10.0, "^JKSE", "equity"),
    "BO": Market("IN", "Asia/Kolkata", time(9, 15), time(15, 30), 10.0, "^BSESN", "equity"),
    "HE": Market("FI", "Europe/Helsinki", time(10, 0), time(18, 30), 10.0, "^OMXH25", "equity"),
    "BR": Market("BE", "Europe/Brussels", time(9, 0), time(17, 30), 10.0, "^BFX", "equity"),
    "VI": Market("AT", "Europe/Vienna", time(9, 0), time(17, 30), 10.0, "^ATX", "equity"),
    "IR": Market("IE", "Europe/Dublin", time(8, 0), time(16, 30), 10.0, "^ISEQ", "equity"),
    "KL": Market("MY", "Asia/Kuala_Lumpur", time(9, 0), time(17, 0), 10.0, "^KLSE", "equity"),
    "NZ": Market("NZ", "Pacific/Auckland", time(10, 0), time(16, 45), 10.0, "^NZ50", "equity"),
    "IS": Market("TR", "Europe/Istanbul", time(10, 0), time(18, 0), 10.0, "XU100.IS", "equity"),
    # Not added (checked 2026-09-29): .SR (Tadawul) - ^TASI.SR has no Yahoo history
    # (1 bar in 1y), so there is no benchmark series; it maps to UNKNOWN like any other
    # unlisted suffix until a benchmark is sourced.
    # ICE US Dollar Index (DX-Y.NYB): an index, not tradable; bars dated by the New York
    # trade date, which ends with the 17:00 ET futures settlement break.
    "NYB": Market("INDEX", "America/New_York", time(9, 30), time(17, 0), 0.0, CASH, "index"),
}

# US share classes written with a dot ("BRK.B"); Yahoo form is "BRK-B".
_US_CLASS_SUFFIXES = {"A", "B", "C"}


def _index_market(m: Market) -> Market:
    """Index priced in an exchange's own session (not tradable, no benchmark)."""
    return Market("INDEX", m.tz, m.open, m.close, 0.0, CASH, "index")


# Indices keep the timezone and session of their home exchange (e.g. ^MXX closes in
# Mexico City, not New York). Built from the suffix markets' own benchmarks, plus the
# main indices that are not a benchmark here. Unlisted ^ symbols keep INDEX (New York).
_INDEX: dict[str, Market] = {
    m.benchmark: _index_market(m)
    for m in _SUFFIX.values() if m.benchmark.startswith("^")
}
_INDEX.update({
    "^N225": _index_market(_SUFFIX["T"]),
    "^HSI": _index_market(_SUFFIX["HK"]),
    "^HSCE": _index_market(_SUFFIX["HK"]),
    "^STOXX50E": _index_market(_SUFFIX["DE"]),
    # Tadawul (no .SR market entry: see above); Sunday-Thursday 10:00-15:00 Riyadh
    "^TASI.SR": Market("INDEX", "Asia/Riyadh", time(10, 0), time(15, 0), 0.0, CASH, "index"),
    # Cboe computes VIX until 16:15 ET
    "^VIX": Market("INDEX", "America/New_York", time(9, 30), time(16, 15), 0.0, CASH, "index"),
})

_RATES_ROOTS = {"ZN", "ZB", "ZF", "ZT", "UB", "TN", "SR3", "ZQ"}


def market_for(ticker: str) -> Market:
    t = (ticker or "").strip().upper()
    if t.startswith("^"):
        if t in _INDEX:
            return _INDEX[t]
        if "." in t and (suffix := t.rsplit(".", 1)[1]) in _SUFFIX:
            return _index_market(_SUFFIX[suffix])
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
        if suffix in _US_CLASS_SUFFIXES:
            return US
        return UNKNOWN
    return US


def is_shadow_tradable(ticker: str) -> bool:
    """Shadows may trade anything with a real market except a bare index (docs/S3_DESIGN §7)
    or an exchange suffix we have no market data for (UNKNOWN: not settleable)."""
    t = (ticker or "").strip().upper()
    return bool(t) and market_for(t).asset_class not in ("index", "unknown")


def is_settleable(ticker: str) -> bool:
    """False for a ticker whose exchange suffix is unknown (no session/benchmark data)."""
    return market_for(ticker).code != UNKNOWN.code


def yahoo_symbol(ticker: str) -> str:
    """Symbol to send to Yahoo/yfinance. HK codes use Yahoo's 4-digit form.

    Yahoo 404s on 5-digit HK codes ("09866.HK") but serves "9866.HK"; "0700.HK" stays.
    Only the request symbol changes: ledgers keep the ticker as written.
    """
    t = (ticker or "").strip()
    if t.upper().endswith(".HK") and t[:-3].isdigit():
        return (t[:-3].lstrip("0") or "0").zfill(4) + ".HK"
    return t
