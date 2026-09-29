"""SEC fails-to-deliver (FTD) data: half-month CNS fails files.

Source (keyless, verified reachable from Riyadh 2026-09-29):
- index page https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data
  links `/files/data/fails-deliver-data/cnsfailsYYYYMM{a,b}.zip` (older years under
  `/files/data/other/...`); "a" = settlement dates in the first half of the month,
  "b" = the second half.
- each ZIP holds one pipe-delimited text file:
  `SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE` + trailer lines.
  QUANTITY is the aggregate fails balance (shares) at NSCC on that settlement date,
  not new fails; PRICE is the prior day's closing price as published by the SEC.

SEC fair-access rules: a declared User-Agent with contact (same as the evidence
layer), few requests. Published ZIPs never change, so they are cached forever under
<data dir>/altdata/sec_ftd/. The SEC publishes each file roughly 2–4 weeks after
the settlement dates it covers; every output carries that lag note.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from marketmind.evidence.sources import SEC_HEADERS
from marketmind.gateway.altdata_store import altdata_dir, write_bytes_atomic

logger = logging.getLogger("marketmind.gateway.sec_ftd")

PAGE_URL = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
SEC_BASE = "https://www.sec.gov"
ZIP_PATH = "/files/data/fails-deliver-data/cnsfails{period}.zip"
HTTP_TIMEOUT_S = 60.0
HEADERS = {"User-Agent": SEC_HEADERS["User-Agent"], "Accept": "*/*"}
LAG_NOTE = ("SEC fails-to-deliver data is published about 2-4 weeks after settlement; "
            "these are not current positions")
_LINK_RE = re.compile(r'href="(/files/data/[^"]*?cnsfails(\d{6}[ab])\.zip)"')
_TRANSPORT: httpx.AsyncBaseTransport | None = None      # tests inject httpx.MockTransport


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=True,
                             headers=HEADERS, transport=_TRANSPORT)


# ── parsers (pure) ──────────────────────────────────────────────────────────

def parse_index(html: str) -> dict[str, str]:
    """period id ('202609a') -> site-relative ZIP path, from the SEC index page."""
    return {m.group(2): m.group(1) for m in _LINK_RE.finditer(html or "")}


def zip_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".txt")] or z.namelist()
        return z.read(names[0]).decode("latin-1")


def _iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


@dataclass
class TickerFails:
    symbol: str
    description: str = ""
    days: int = 0                   # settlement dates with a reported fails balance
    last_date: str = ""
    last_shares: int = 0
    last_price: float | None = None
    sum_shares: int = 0
    max_shares: int = 0
    sum_value: float = 0.0
    value_days: int = 0             # days with a usable price

    @property
    def avg_shares(self) -> float:
        return self.sum_shares / self.days if self.days else 0.0

    @property
    def avg_value(self) -> float | None:
        return self.sum_value / self.value_days if self.value_days else None

    @property
    def last_value(self) -> float | None:
        return self.last_shares * self.last_price if self.last_price is not None else None


@dataclass
class PeriodFails:
    period: str
    dates: list[str] = field(default_factory=list)        # all settlement dates in the file
    tickers: dict[str, TickerFails] = field(default_factory=dict)

    @property
    def first(self) -> str:
        return self.dates[0] if self.dates else ""

    @property
    def last(self) -> str:
        return self.dates[-1] if self.dates else ""


def parse_fails(text: str, period: str = "") -> PeriodFails:
    """Aggregate a CNS fails file per symbol (streaming; keeps no per-row list)."""
    lines = (text or "").splitlines()
    if not lines or not lines[0].upper().startswith("SETTLEMENT DATE|"):
        raise ValueError("unexpected SEC fails-to-deliver header")
    out = PeriodFails(period)
    dates: set[str] = set()
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) < 6 or not parts[0].strip().isdigit():
            continue                                    # trailer / blank lines
        day, sym = parts[0].strip(), parts[2].strip().upper()
        try:
            qty = int(parts[3].strip())
        except ValueError:
            continue
        if not sym or len(day) != 8:
            continue
        try:
            price = float(parts[-1].strip())
        except ValueError:
            price = None                                # SEC prints '.' when no price
        d = _iso(day)
        dates.add(d)
        t = out.tickers.get(sym)
        if t is None:
            t = out.tickers[sym] = TickerFails(sym, "|".join(parts[4:-1]).strip())
        t.days += 1
        t.sum_shares += qty
        t.max_shares = max(t.max_shares, qty)
        if price is not None:
            t.sum_value += qty * price
            t.value_days += 1
        if d >= t.last_date:
            t.last_date, t.last_shares, t.last_price = d, qty, price
    out.dates = sorted(dates)
    if not out.dates:
        raise ValueError("SEC fails-to-deliver file has no rows")
    return out


def compare(latest: PeriodFails, prior: PeriodFails | None, symbols) -> dict[str, dict]:
    """symbol -> latest-period stats and the change in average daily fails vs prior."""
    out: dict[str, dict] = {}
    for s in symbols:
        s = s.upper()
        t = latest.tickers.get(s)
        p = prior.tickers.get(s) if prior else None
        row: dict = {"symbol": s, "in_latest": t is not None, "in_prior": p is not None}
        if t is not None:
            row.update(days=t.days, n_dates=len(latest.dates), last_date=t.last_date,
                       last_shares=t.last_shares, last_value=t.last_value,
                       avg_shares=t.avg_shares, max_shares=t.max_shares, avg_value=t.avg_value)
        if p is not None:
            row.update(prior_avg_shares=p.avg_shares, prior_avg_value=p.avg_value)
        if t is not None and p is not None and p.avg_shares:
            row["chg_avg_shares_pct"] = (t.avg_shares / p.avg_shares - 1) * 100
        out[s] = row
    return out


def top_by_value(period: PeriodFails, n: int = 5, min_days: int = 3) -> list[TickerFails]:
    rows = [t for t in period.tickers.values() if t.days >= min_days and t.avg_value]
    return sorted(rows, key=lambda t: -(t.avg_value or 0))[:n]


# ── network + cache ─────────────────────────────────────────────────────────

async def _zip_bytes(client: httpx.AsyncClient, period: str, path: str | None,
                     cache: Path) -> bytes:
    f = cache / f"cnsfails{period}.zip"
    if f.exists() and f.stat().st_size > 0:
        return f.read_bytes()
    r = await client.get(SEC_BASE + (path or ZIP_PATH.format(period=period)))
    r.raise_for_status()
    zip_text(r.content)                                 # validate before caching
    write_bytes_atomic(f, r.content)
    return r.content


async def latest_periods(n: int = 2, data_dir: Path | None = None) -> tuple[list[PeriodFails], str]:
    """The newest `n` half-month files, newest first, and a note (empty when the SEC
    index page was read; otherwise says cached files were used)."""
    cache = altdata_dir("sec_ftd", data_dir)
    note = ""
    async with _client() as c:
        try:
            r = await c.get(PAGE_URL)
            r.raise_for_status()
            links = parse_index(r.text)
            if not links:
                raise ValueError("no fails-to-deliver links on the SEC page")
        except (httpx.HTTPError, ValueError) as e:
            cached = sorted(p.stem.removeprefix("cnsfails") for p in cache.glob("cnsfails*.zip"))
            if not cached:
                raise
            logger.warning("SEC FTD index unavailable (%s); using cached files", e)
            note = f"SEC index page unavailable ({type(e).__name__}); newest cached files used"
            links = {p: None for p in cached}
        periods = sorted(links, reverse=True)[:n]
        out = []
        for p in periods:
            out.append(parse_fails(zip_text(await _zip_bytes(c, p, links[p], cache)), p))
    return out, note


async def load_ftd(symbols, data_dir: Path | None = None) -> dict:
    """Per-symbol FTD shares / value for the latest half-month and change vs the prior."""
    periods, note = await latest_periods(2, data_dir)
    latest = periods[0]
    prior = periods[1] if len(periods) > 1 else None
    return {"latest": {"period": latest.period, "first": latest.first, "last": latest.last,
                       "n_dates": len(latest.dates)},
            "prior": ({"period": prior.period, "first": prior.first, "last": prior.last}
                      if prior else None),
            "tickers": compare(latest, prior, symbols),
            "top": [{"symbol": t.symbol, "description": t.description, "avg_value": t.avg_value,
                     "avg_shares": t.avg_shares, "days": t.days} for t in top_by_value(latest)],
            "note": note, "lag_note": LAG_NOTE}
