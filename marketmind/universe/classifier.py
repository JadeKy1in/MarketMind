"""Ticker classification against the tradable universe (docs/S2_DESIGN.md §2).

Layers:
- ``tradable``: can be traded on Robinhood US (listed US stock/ETF, listed coin,
  registered future or event contract).
- ``linkage``: price signal only, e.g. foreign listings (``600900.SS``,
  ``0700.HK``), indices (``^GSPC``), FX (``EURUSD=X``), non-Robinhood futures.
- ``unknown``: anything else, including US-style tickers when the equity
  universe could not be loaded (then ``is_tradable`` returns None so the caller
  can fall back to its own heuristic).

The equity universe loads lazily once per process; importing this module does
not touch the network.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

from marketmind.universe.equities import EquityUniverse, load_equity_universe
from marketmind.universe.registry import (
    CRYPTO_SOURCE,
    EVENT_CONTRACT_PREFIX,
    EVENT_SOURCE,
    FUTURES_SOURCE,
    ROBINHOOD_CRYPTO,
    ROBINHOOD_FUTURES,
    UNVERIFIED_CRYPTO,
)

logger = logging.getLogger("marketmind.universe.classifier")

SOURCE_EQUITIES = "nasdaqtrader"
SOURCE_UNAVAILABLE = "equity_universe_unavailable"

# yfinance exchange suffixes for non-US listings.
FOREIGN_SUFFIXES = (
    ".SS", ".SZ", ".BJ", ".HK", ".T", ".KS", ".KQ", ".TW", ".TWO", ".NS", ".BO",
    ".SI", ".JK", ".BK", ".KL", ".AX", ".NZ", ".L", ".DE", ".F", ".PA", ".AS",
    ".BR", ".MI", ".MC", ".LS", ".SW", ".VI", ".ST", ".OL", ".CO", ".HE", ".IR",
    ".TO", ".V", ".NE", ".MX", ".SA", ".BA", ".JO", ".TA", ".SR", ".QA",
)
_FUTURE_MONTH = re.compile(r"^(?P<root>[A-Z0-9]+?)[FGHJKMNQUVXZ]\d{1,2}$")
_CRYPTO_ID_SUFFIX = re.compile(r"^(?P<base>[A-Z]+?)\d+$")  # yfinance "UNI7083-USD" style

_UNLOADED = object()
_universe: object = _UNLOADED
_lock = threading.Lock()


@dataclass(frozen=True)
class Classification:
    ticker: str          # normalised input
    layer: str           # "tradable" | "linkage" | "unknown"
    asset_type: str      # "stock" | "etf" | "crypto" | "future" | "event_contract" | "index" | "unknown"
    source: str
    settleable: bool = False  # the S2 ledger can settle it (stocks, ETFs, crypto)


def get_equity_universe() -> EquityUniverse | None:
    """Process-wide equity universe, loaded on first use (None if unavailable)."""
    global _universe
    if _universe is _UNLOADED:
        with _lock:
            if _universe is _UNLOADED:
                loaded = load_equity_universe()
                if loaded is None:
                    logger.warning("US equity universe unavailable for this process; "
                                   "is_tradable() returns None for US-style tickers")
                else:
                    c = loaded.counts()
                    logger.info("US equity universe loaded: %d stocks, %d ETFs (fetched %s%s)",
                                c["stocks"], c["etfs"], loaded.fetched_at.date().isoformat(),
                                ", stale cache" if loaded.stale else "")
                _universe = loaded
    return _universe  # type: ignore[return-value]


def set_equity_universe(universe: EquityUniverse | None) -> None:
    """Install a universe (tests, or a caller that loaded one with custom args)."""
    global _universe
    with _lock:
        _universe = universe


def reset_equity_universe() -> None:
    """Forget the loaded universe; the next call loads again."""
    global _universe
    with _lock:
        _universe = _UNLOADED


def _classify_crypto(t: str) -> Classification:
    base = t[: -len("-USD")]
    candidates = [base]
    m = _CRYPTO_ID_SUFFIX.match(base)
    if m:
        candidates.append(m.group("base"))
    for b in candidates:
        if b in ROBINHOOD_CRYPTO:
            return Classification(t, "tradable", "crypto", CRYPTO_SOURCE, settleable=True)
    for b in candidates:
        if b in UNVERIFIED_CRYPTO:
            return Classification(t, "unknown", "crypto", "robinhood_crypto_unverified")
    return Classification(t, "unknown", "crypto", "not_in_robinhood_crypto_list")


def _future_root(t: str) -> str | None:
    if t.endswith("=F"):
        return t[:-2]
    if t.startswith("/") and len(t) > 1:
        body = t[1:]
        if body in ROBINHOOD_FUTURES:
            return body
        m = _FUTURE_MONTH.match(body)
        if m and m.group("root") in ROBINHOOD_FUTURES:
            return m.group("root")
        return body
    return None


def classify(ticker: str) -> Classification:
    t = (ticker or "").strip().upper()
    if not t:
        return Classification(t, "unknown", "unknown", "empty")

    if t.startswith(EVENT_CONTRACT_PREFIX):
        return Classification(t, "tradable", "event_contract", EVENT_SOURCE)
    if t.startswith("^"):
        return Classification(t, "linkage", "index", "index_prefix")

    root = _future_root(t)
    if root is not None:
        if root in ROBINHOOD_FUTURES:
            return Classification(t, "tradable", "future", FUTURES_SOURCE)
        return Classification(t, "linkage", "future", "not_in_robinhood_futures_list")
    if t.endswith("=X"):
        return Classification(t, "linkage", "unknown", "fx_pair")
    if t.endswith("-USD"):
        return _classify_crypto(t)

    universe = get_equity_universe()
    # US share classes arrive as "BRK.B" or "BRK-B"; check the universe before the
    # foreign-suffix rule so a class letter never reads as an exchange (e.g. MKC.V).
    candidate = t.replace(".", "-").replace("/", "-")
    if universe is not None and candidate in universe:
        rec = universe.get(candidate)
        return Classification(candidate, "tradable", "etf" if rec.is_etf else "stock",
                              SOURCE_EQUITIES, settleable=True)
    if t.endswith(FOREIGN_SUFFIXES):
        return Classification(t, "linkage", "unknown", "foreign_exchange_suffix")
    if universe is None:
        return Classification(candidate, "unknown", "unknown", SOURCE_UNAVAILABLE)
    return Classification(candidate, "unknown", "unknown", "not_in_us_equity_universe")


def is_tradable(ticker: str) -> bool | None:
    """True/False from the universe; None when the equity universe is unavailable
    and the ticker is not crypto/future/event (caller falls back to its heuristic)."""
    c = classify(ticker)
    if c.layer == "tradable":
        return True
    if c.source == SOURCE_UNAVAILABLE:
        return None
    return False
