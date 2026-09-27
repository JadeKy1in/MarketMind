"""US stock / ETF universe from the NASDAQ Trader symbol directory (docs/S2_DESIGN.md §2).

Two pipe-delimited files are downloaded: ``nasdaqlisted.txt`` (Nasdaq-listed)
and ``otherlisted.txt`` (NYSE, NYSE American, NYSE Arca, Cboe, IEX ...). Each
ends with a ``File Creation Time`` footer; a file without it is treated as a
truncated download and rejected.

Symbol normalisation (to yfinance style):
- Test issues are dropped.
- Share classes ``BRK.B`` / ``BF.A`` become ``BRK-B`` / ``BF-A``.
- Excluded, because they are not decision-card instruments and yfinance spells
  them inconsistently: preferreds (``$``, e.g. ``BFH$A``), units (``=`` or
  ``.U``), warrants (``.W`` / ``.WS``), rights (``^`` or ``.R``), when-issued
  (``#`` or "when issued" in the name), and any other symbol with characters
  outside ``A-Z0-9.``. Nasdaq-listed warrants/units/rights use plain 5-letter
  symbols (e.g. ``ABCDW``) that yfinance also uses, so they are kept as is.

The parsed result is cached as JSON under ``<data_dir>/universe/`` with its
fetch time and refreshed when older than 7 days. If the download fails, the
cache is used and the cache date is logged; if neither is available the
universe is reported as unavailable (``None``) rather than guessed.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

logger = logging.getLogger("marketmind.universe.equities")

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
CACHE_FILENAME = "us_equities.json"
CACHE_VERSION = 1
MAX_CACHE_AGE = timedelta(days=7)
HTTP_TIMEOUT_S = 20.0

_FOOTER_PREFIX = "File Creation Time"
_OTHER_EXCHANGES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}
_EXCLUDED_CLASS_SUFFIXES = {"U", "W", "WS", "R"}  # units, warrants, rights
_PLAIN_SYMBOL = re.compile(r"^[A-Z0-9]+(\.[A-Z0-9]+)?$")

Fetcher = Callable[[str], str]


@dataclass(frozen=True)
class EquityRecord:
    symbol: str      # yfinance style
    name: str
    exchange: str
    is_etf: bool


@dataclass(frozen=True)
class EquityUniverse:
    symbols: dict[str, EquityRecord]
    fetched_at: datetime   # when the NASDAQ Trader files were downloaded (UTC)
    from_cache: bool
    stale: bool            # True when a download failed and an old cache was used

    def __contains__(self, symbol: object) -> bool:
        return symbol in self.symbols

    def get(self, symbol: str) -> EquityRecord | None:
        return self.symbols.get(symbol)

    def counts(self) -> dict[str, int]:
        etfs = sum(1 for r in self.symbols.values() if r.is_etf)
        return {"total": len(self.symbols), "stocks": len(self.symbols) - etfs, "etfs": etfs}


def default_cache_dir() -> Path:
    # Same resolution as MarketMindConfig.data_dir, without building the full config.
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "universe"


def http_fetch(url: str) -> str:
    """Default fetcher. httpx honours HTTP(S)_PROXY from the environment."""
    resp = httpx.get(url, timeout=httpx.Timeout(HTTP_TIMEOUT_S), follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def normalise_symbol(raw: str, name: str = "") -> str | None:
    """NASDAQ Trader symbol -> yfinance symbol, or None if excluded (see module doc)."""
    sym = raw.strip().upper()
    if not sym or not _PLAIN_SYMBOL.match(sym):
        return None  # $ preferred, = unit, ^ right, # when-issued, etc.
    if "when issued" in name.lower():
        return None
    if "." in sym:
        base, suffix = sym.split(".", 1)
        if suffix in _EXCLUDED_CLASS_SUFFIXES:
            return None
        return f"{base}-{suffix}"
    return sym


def _rows(text: str, source: str) -> tuple[list[str], list[list[str]]]:
    lines = [ln.rstrip("\r") for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError(f"{source}: file is empty")
    if not lines[-1].startswith(_FOOTER_PREFIX):
        raise ValueError(f"{source}: missing '{_FOOTER_PREFIX}' footer (truncated download?)")
    header = [h.strip() for h in lines[0].split("|")]
    return header, [ln.split("|") for ln in lines[1:-1]]


def _col(header: list[str], name: str, source: str) -> int:
    try:
        return header.index(name)
    except ValueError:
        raise ValueError(f"{source}: column '{name}' not found in header {header}") from None


def parse_nasdaq_listed(text: str) -> list[EquityRecord]:
    src = "nasdaqlisted.txt"
    header, rows = _rows(text, src)
    i_sym, i_name = _col(header, "Symbol", src), _col(header, "Security Name", src)
    i_test, i_etf = _col(header, "Test Issue", src), _col(header, "ETF", src)
    return _build(rows, i_sym, i_name, i_test, i_etf, lambda _row: "NASDAQ", src)


def parse_other_listed(text: str) -> list[EquityRecord]:
    src = "otherlisted.txt"
    header, rows = _rows(text, src)
    i_sym, i_name = _col(header, "ACT Symbol", src), _col(header, "Security Name", src)
    i_test, i_etf = _col(header, "Test Issue", src), _col(header, "ETF", src)
    i_exch = _col(header, "Exchange", src)

    def exchange(row: list[str]) -> str:
        code = row[i_exch].strip()
        return _OTHER_EXCHANGES.get(code, f"OTHER:{code}")

    return _build(rows, i_sym, i_name, i_test, i_etf, exchange, src)


def _build(rows, i_sym, i_name, i_test, i_etf, exchange, source) -> list[EquityRecord]:
    width = max(i_sym, i_name, i_test, i_etf) + 1
    out: list[EquityRecord] = []
    tests = excluded = malformed = 0
    for row in rows:
        if len(row) < width:
            malformed += 1
            continue
        if row[i_test].strip().upper() == "Y":
            tests += 1
            continue
        name = row[i_name].strip()
        sym = normalise_symbol(row[i_sym], name)
        if sym is None:
            excluded += 1
            continue
        out.append(EquityRecord(sym, name, exchange(row), row[i_etf].strip().upper() == "Y"))
    logger.info("%s: kept %d, dropped %d test issues, %d excluded symbols, %d malformed rows",
                source, len(out), tests, excluded, malformed)
    return out


def _merge(*groups: list[EquityRecord]) -> dict[str, EquityRecord]:
    merged: dict[str, EquityRecord] = {}
    for group in groups:
        for rec in group:
            merged.setdefault(rec.symbol, rec)  # first listing wins on (rare) duplicates
    return merged


def _write_cache(path: Path, symbols: dict[str, EquityRecord], fetched_at: datetime) -> None:
    payload = {
        "version": CACHE_VERSION,
        "fetched_at": fetched_at.isoformat(),
        "sources": [NASDAQ_LISTED_URL, OTHER_LISTED_URL],
        "symbols": {s: [r.name, r.exchange, r.is_etf] for s, r in symbols.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_cache(path: Path) -> tuple[dict[str, EquityRecord], datetime] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != CACHE_VERSION:
            logger.warning("Universe cache %s has version %r, expected %d; ignoring it",
                           path, payload.get("version"), CACHE_VERSION)
            return None
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        symbols = {
            s: EquityRecord(s, name, exch, bool(etf))
            for s, (name, exch, etf) in payload["symbols"].items()
        }
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning("Universe cache %s is unreadable (%s); ignoring it", path, e)
        return None
    if not symbols:
        logger.warning("Universe cache %s is empty; ignoring it", path)
        return None
    return symbols, fetched_at


def load_equity_universe(
    cache_dir: Path | str | None = None,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
    max_age: timedelta = MAX_CACHE_AGE,
) -> EquityUniverse | None:
    """Load the US stock/ETF universe: fresh cache, else download, else stale cache, else None.

    ``fetcher(url) -> text`` and ``cache_dir`` are injectable for tests.
    """
    cache_path = Path(cache_dir if cache_dir is not None else default_cache_dir()) / CACHE_FILENAME
    now = now or datetime.now(timezone.utc)
    fetcher = fetcher or http_fetch

    cached = _read_cache(cache_path)
    if cached is not None:
        symbols, fetched_at = cached
        if now - fetched_at <= max_age:
            return EquityUniverse(symbols, fetched_at, from_cache=True, stale=False)

    try:
        symbols = _merge(parse_nasdaq_listed(fetcher(NASDAQ_LISTED_URL)),
                         parse_other_listed(fetcher(OTHER_LISTED_URL)))
        if not symbols:
            raise ValueError("NASDAQ Trader files parsed to zero symbols")
    except Exception as e:  # any fetch/parse failure degrades to cache or "unavailable", logged below
        if cached is not None:
            logger.warning("Universe download failed (%s); using cache from %s (%s)",
                           e, cached[1].date().isoformat(), cache_path)
            return EquityUniverse(cached[0], cached[1], from_cache=True, stale=True)
        logger.error("Universe download failed (%s) and no cache at %s; "
                     "US equity universe unavailable", e, cache_path)
        return None

    try:
        _write_cache(cache_path, symbols, now)
    except OSError as e:
        logger.warning("Could not write universe cache %s (%s); continuing without it", cache_path, e)
    return EquityUniverse(symbols, now, from_cache=False, stale=False)
