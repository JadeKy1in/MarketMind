"""Daily equity factor returns for the promotion diagnostics (docs/S7_DESIGN.md §三).

Two sources, both returning a `FactorTable` of DAILY SIMPLE RETURNS (decimals, not %):

1. Ken French Data Library (primary): Fama-French 5 factors (2x3) + momentum, daily.
   https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
   Verified reachable from this network 2026-09-29 (HTTP 200). The library is rebuilt
   monthly from CRSP with a lag: the 2026-09-29 download ended 2026-08-31 ("created by
   using the 202608 CRSP database"). The zipped CSVs are cached as plain CSV under
   `<data_dir>/factors/` and re-downloaded at most every REFRESH_DAYS; a failed
   download keeps using the stale cache, and no cache at all returns None.

2. ETF proxies (fallback, for dates the library does not cover yet), from our own daily
   bars (dividend-adjusted on the default Alpaca / yfinance paths):
       RF  = BIL                (1-3 month T-bill ETF)
       MKT = SPY - BIL
       SMB = IWM - SPY          (small caps minus the S&P 500)
       HML = IWD - IWF          (Russell 1000 value minus growth)
       MOM = MTUM - SPY         (MSCI USA momentum minus the S&P 500)
   RMW / CMA have no usable ETF proxy (QUAL - SPY correlates 0.16 with RMW), so the
   proxy model is 4-factor (Carhart 1997 style). Daily correlation with the French
   factors 2021-10-01 .. 2026-08-31 (1233 days, computed 2026-09-29): MKT 0.994,
   SMB 0.944, HML 0.769, MOM 0.654; BIL annualised 3.60% vs French RF 3.80%.
   Caveat: the Nasdaq fallback of price_history is NOT dividend-adjusted, which would
   put monthly distribution drops into BIL; Alpaca (configured here) is adjusted.

Pure I/O helpers, no LLM. The HTTP fetch has a timeout and is injectable for tests.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import numpy as np

log = logging.getLogger(__name__)

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FRENCH_FILES = {
    "ff5": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "mom": "F-F_Momentum_Factor_daily_CSV.zip",
}
FRENCH_NAMES = ("MKT", "SMB", "HML", "RMW", "CMA", "MOM")
_FRENCH_COLUMNS = {"Mkt-RF": "MKT", "SMB": "SMB", "HML": "HML", "RMW": "RMW", "CMA": "CMA",
                   "RF": "RF", "Mom": "MOM"}
REFRESH_DAYS = 7                 # the library is rebuilt monthly; weekly checks are plenty
HTTP_TIMEOUT_S = 30.0

PROXY_TICKERS = ("SPY", "BIL", "IWM", "IWD", "IWF", "MTUM")
PROXY_NAMES = ("MKT", "SMB", "HML", "MOM")

Fetch = Callable[[str], bytes]


@dataclass
class FactorTable:
    """Aligned daily factor returns: values[i, j] = factor names[j] on days[i]."""
    source: str                                  # "french" | "etf_proxy"
    names: tuple[str, ...]
    days: list[str]
    values: np.ndarray                           # shape (len(days), len(names))
    rf: np.ndarray                               # daily risk-free return, shape (len(days),)
    notes: list[str] = field(default_factory=list)

    @property
    def first(self) -> str | None:
        return self.days[0] if self.days else None

    @property
    def last(self) -> str | None:
        return self.days[-1] if self.days else None

    def covers(self, lo: str, hi: str) -> bool:
        return bool(self.days) and self.days[0] <= lo and self.days[-1] >= hi


# ── Ken French Data Library ────────────────────────────────────────────

def parse_french_csv(text: str) -> dict[str, dict[str, float]]:
    """{YYYY-MM-DD: {column: decimal return}} from a French daily CSV (values in %).

    Only the daily block is read: rows whose first cell is an 8-digit date under the
    first header row (",Mkt-RF,SMB,..." or ",Mom"). Missing values (-99.99) are skipped."""
    out: dict[str, dict[str, float]] = {}
    header: list[str] | None = None
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) > 1 and cells[0] == "" and header is None:
            header = [_FRENCH_COLUMNS.get(c, c) for c in cells[1:]]
            continue
        if header is None:
            continue
        if len(cells) != len(header) + 1 or not (cells[0].isdigit() and len(cells[0]) == 8):
            if out and cells[0] and not cells[0].isdigit():
                break                                 # end of the daily block
            continue
        try:
            vals = [float(c) for c in cells[1:]]
        except ValueError:
            continue
        if any(v <= -99.99 for v in vals):
            continue
        d = f"{cells[0][:4]}-{cells[0][4:6]}-{cells[0][6:]}"
        out[d] = {k: v / 100.0 for k, v in zip(header, vals)}
    return out


def _http_get(url: str) -> bytes:
    import httpx
    r = httpx.get(url, timeout=HTTP_TIMEOUT_S, follow_redirects=True)
    r.raise_for_status()
    return r.content


def _cached_csv(cache_dir: Path, key: str, fetch: Fetch, now: datetime,
                refresh_days: float) -> tuple[str | None, str | None]:
    """(csv text, fetched_at) for one French file: the cache when fresh, else a new
    download (atomic write); a failed download falls back to the stale cache."""
    csv_path = cache_dir / f"french_{key}.csv"
    meta_path = cache_dir / f"french_{key}.json"
    fetched_at = None
    if meta_path.exists():
        try:
            fetched_at = json.loads(meta_path.read_text(encoding="utf-8")).get("fetched_at")
        except ValueError:
            fetched_at = None
    fresh = False
    if fetched_at and csv_path.exists():
        age = now - datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        fresh = age.total_seconds() < refresh_days * 86400
    if not fresh:
        try:
            raw = fetch(FRENCH_BASE + FRENCH_FILES[key])
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                text = zf.read(zf.namelist()[0]).decode("latin-1")
            if not parse_french_csv(text):
                raise ValueError("no daily rows in the downloaded file")
            cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = csv_path.with_suffix(".csv.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(csv_path)
            fetched_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            meta_path.write_text(json.dumps({"fetched_at": fetched_at,
                                             "url": FRENCH_BASE + FRENCH_FILES[key]}),
                                 encoding="utf-8")
        except Exception as exc:                  # noqa: BLE001 - reported, stale cache used
            log.warning("French factor download %s failed: %s", key, exc)
    if not csv_path.exists():
        return None, None
    return csv_path.read_text(encoding="utf-8"), fetched_at


def french_factors(cache_dir: str | Path, *, fetch: Fetch | None = None,
                   now: datetime | None = None,
                   refresh_days: float = REFRESH_DAYS) -> FactorTable | None:
    """FF5 + MOM daily factors from the library (cached), or None when unavailable."""
    cache_dir = Path(cache_dir)
    now = now or datetime.now(timezone.utc)
    fetch = fetch or _http_get
    ff_text, ff_at = _cached_csv(cache_dir, "ff5", fetch, now, refresh_days)
    mom_text, _ = _cached_csv(cache_dir, "mom", fetch, now, refresh_days)
    if not ff_text or not mom_text:
        return None
    ff, mom = parse_french_csv(ff_text), parse_french_csv(mom_text)
    days = sorted(d for d in ff if d in mom and "MOM" in mom[d]
                  and all(k in ff[d] for k in ("MKT", "SMB", "HML", "RMW", "CMA", "RF")))
    if not days:
        return None
    values = np.array([[ff[d][k] for k in FRENCH_NAMES[:5]] + [mom[d]["MOM"]] for d in days])
    rf = np.array([ff[d]["RF"] for d in days])
    return FactorTable("french", FRENCH_NAMES, days, values, rf,
                       notes=[f"Ken French Data Library, fetched {ff_at}, last day {days[-1]}"])


# ── ETF proxies ────────────────────────────────────────────────────────

def close_returns(bars) -> dict[str, float]:
    """{date: close / previous close - 1} over consecutive bars (first bar dropped)."""
    out: dict[str, float] = {}
    prev = None
    for b in bars or []:
        if prev is not None and prev.close > 0 and b.close > 0:
            out[b.date] = b.close / prev.close - 1.0
        prev = b
    return out


def etf_proxy_factors(bars: Mapping[str, "list | None"]) -> FactorTable | None:
    """4 proxy factors + RF (see module docstring) on the days all six ETFs have a return."""
    rets = {t: close_returns(bars.get(t)) for t in PROXY_TICKERS}
    if any(not r for r in rets.values()):
        missing = [t for t, r in rets.items() if not r]
        log.warning("ETF factor proxies unavailable: no bars for %s", missing)
        return None
    days = sorted(set.intersection(*(set(r) for r in rets.values())))
    if not days:
        return None
    g = {t: np.array([rets[t][d] for d in days]) for t in PROXY_TICKERS}
    values = np.column_stack([g["SPY"] - g["BIL"], g["IWM"] - g["SPY"],
                              g["IWD"] - g["IWF"], g["MTUM"] - g["SPY"]])
    if not np.all(np.isfinite(values)):
        return None
    return FactorTable("etf_proxy", PROXY_NAMES, days, values, g["BIL"].copy(),
                       notes=["ETF proxies: MKT=SPY-BIL, SMB=IWM-SPY, HML=IWD-IWF, "
                              "MOM=MTUM-SPY, RF=BIL (no RMW/CMA proxy)"])


def aligned_returns(bars, calendar: list[str]) -> np.ndarray | None:
    """Close-to-close returns of an asset between consecutive `calendar` days, i.e. one
    value per calendar[1:] (e.g. BTC on US trading days: Monday includes the weekend).
    Uses the last bar on or before each calendar day; None when a calendar day has no
    bar within 4 days before it."""
    if not bars:
        return None
    dates = [b.date for b in bars]
    closes = [b.close for b in bars]
    from bisect import bisect_right
    from datetime import date as _date
    px = []
    for d in calendar:
        i = bisect_right(dates, d) - 1
        if i < 0 or (_date.fromisoformat(d) - _date.fromisoformat(dates[i])).days > 4 \
                or closes[i] <= 0:
            return None
        px.append(closes[i])
    p = np.array(px, dtype=float)
    return p[1:] / p[:-1] - 1.0
