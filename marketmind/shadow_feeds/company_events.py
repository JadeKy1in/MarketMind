"""Company events from Finnhub (free tier, key env FINNHUB_KEY).

- Earnings calendar: one `/calendar/earnings?from=&to=` call for the whole
  window, filtered to the watched US stocks.
- Insider transactions: one `/stock/insider-transactions` call per stock,
  spaced to stay well under the free tier's 60 calls/min, capped per run.
  Only open-market, non-derivative purchases (code P) and sales (code S) count;
  grants, option exercises and tax withholding are not buy/sell decisions.

The watched stocks are the union of the served shadows' roster watchlists,
minus ETFs, crypto, futures, FX and foreign-listed symbols.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import date, timedelta

import httpx

from marketmind.shadow_feeds import Feed

FINNHUB_BASE = "https://finnhub.io/api/v1"
HTTP_TIMEOUT_S = 20.0
EARNINGS_DAYS = 14
INSIDER_DAYS = 30
INSIDER_MAX_TICKERS = 40
INSIDER_TOP = 10
EARNINGS_MAX_LINES = 11
MIN_SPACING_S = 1.1                  # free tier: 60 calls/min
_TRANSPORT: httpx.AsyncBaseTransport | None = None      # tests inject httpx.MockTransport

SHADOWS = ("bear_tracker", "news_hound", "silicon_oracle", "trial_reviewer",
           "wallet_watcher", "bank_examiner", "factory_floor", "squeeze_watch")

# US-listed ETFs that appear in roster watchlists (no earnings, no insiders)
ETFS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "ARKK", "SMH", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLI",
    "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "XRT", "KRE", "KBE", "IBB", "XBI", "ITA",
    "VXX", "UVXY", "SVXY", "SH", "PSQ", "TLT", "IEF", "SHY", "TIP", "EDV", "HYG", "LQD",
    "TBT", "GLD", "SLV", "GDX", "GDXJ", "SIL", "PPLT", "USO", "XOP", "UNG", "IBIT", "ETHA",
    "EEM", "UUP", "DBC", "AGG",
})

HOUR = {"bmo": "before open", "amc": "after close", "dmh": "during market"}


def is_us_stock(t: str) -> bool:
    t = t.upper()
    return (t.isascii() and t.replace("-", "").isalnum() and "." not in t
            and not t.endswith("-USD") and "=" not in t and not t[0].isdigit()
            and t not in ETFS)


def watched_stocks(shadows=SHADOWS) -> list[str]:
    from marketmind.shadows.v3 import roster
    by_name = {e.name: e for e in roster.ROSTER}
    lists = [[t.upper() for t in by_name[n].watchlist if is_us_stock(t)]
             for n in shadows if n in by_name]
    out: list[str] = []            # round-robin, so a request cap cuts every shadow evenly
    for i in range(max((len(x) for x in lists), default=0)):
        for x in lists:
            if i < len(x) and x[i] not in out:
                out.append(x[i])
    return out


def finnhub_key() -> str:
    key = os.environ.get("FINNHUB_KEY", "").strip()
    if not key and os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = str(winreg.QueryValueEx(k, "FINNHUB_KEY")[0]).strip()
        except OSError:
            key = ""
    if not key:
        raise RuntimeError("FINNHUB_KEY not set")
    return key


_locks: dict[int, asyncio.Lock] = {}          # one per event loop
_last_call = 0.0


async def _get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    """GET with global spacing between Finnhub calls (shared by all callers)."""
    global _last_call
    lock = _locks.setdefault(id(asyncio.get_running_loop()), asyncio.Lock())
    async with lock:
        wait = _last_call + MIN_SPACING_S - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()
    r = await client.get(f"{FINNHUB_BASE}{path}", params={**params, "token": finnhub_key()})
    r.raise_for_status()
    return r.json()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, transport=_TRANSPORT)


async def earnings_calendar(start: str, end: str) -> list[dict]:
    """All Finnhub earnings rows between start and end (YYYY-MM-DD, inclusive)."""
    async with _client() as c:
        data = await _get(c, "/calendar/earnings", {"from": start, "to": end})
    rows = data.get("earningsCalendar")
    if not isinstance(rows, list):
        raise ValueError("unexpected Finnhub earnings payload")
    return rows


async def earnings_for(tickers, start: str, days: int) -> dict[str, list[dict]]:
    """ticker -> its earnings rows in [start, start + days], date order."""
    end = (date.fromisoformat(start) + timedelta(days=days)).isoformat()
    want = {t.upper() for t in tickers}
    out: dict[str, list[dict]] = {}
    for row in await earnings_calendar(start, end):
        s = (row.get("symbol") or "").upper()
        if s in want:
            out.setdefault(s, []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: r.get("date") or "")
    return out


def _money(x: float) -> str:
    a = abs(x)
    if a >= 1e9:
        return f"${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"${a / 1e6:.2f}M"
    return f"${a / 1e3:.0f}K" if a >= 1e3 else f"${a:.0f}"


def earnings_lines(found: dict[str, list[dict]], watched: list[str], start: str, end: str) -> list[str]:
    rows = sorted((r for rs in found.values() for r in rs), key=lambda r: (r.get("date") or "", r["symbol"]))
    if not rows:
        return [f"- none of the {len(watched)} watched US stocks report between {start} and {end} (Finnhub)"]
    lines = []
    for r in rows[:EARNINGS_MAX_LINES]:
        est = []
        if r.get("epsEstimate") is not None:
            est.append(f"EPS est {r['epsEstimate']:.2f}")
        if r.get("revenueEstimate"):
            est.append(f"revenue est {_money(r['revenueEstimate'])}")
        q = f"Q{r['quarter']} {r['year']}" if r.get("quarter") and r.get("year") else ""
        when = HOUR.get(r.get("hour") or "", "time n/a")
        tail = ", ".join(x for x in [q] + est if x)
        lines.append(f"- {r['date']} {r['symbol'].upper()} ({when})" + (f": {tail}" if tail else ""))
    if len(rows) > EARNINGS_MAX_LINES:
        lines.append(f"- ... and {len(rows) - EARNINGS_MAX_LINES} more reports in the window")
    return lines


async def fetch_earnings(today: str) -> list[str]:
    watched = watched_stocks()
    end = (date.fromisoformat(today) + timedelta(days=EARNINGS_DAYS)).isoformat()
    found = await earnings_for(watched, today, EARNINGS_DAYS)
    return earnings_lines(found, watched, today, end)


def summarize_insiders(rows: list[dict], start: str, end: str) -> dict | None:
    """Net open-market P/S dollars over non-derivative rows with transactionDate in window."""
    buys = sells = 0
    buy_usd = sell_usd = 0.0
    names = set()
    for r in rows:
        code = r.get("transactionCode")
        d = r.get("transactionDate") or ""
        if code not in ("P", "S") or r.get("isDerivative") or not (start <= d <= end):
            continue
        usd = abs(float(r.get("change") or 0)) * float(r.get("transactionPrice") or 0)
        names.add(r.get("name"))
        if code == "P":
            buys, buy_usd = buys + 1, buy_usd + usd
        else:
            sells, sell_usd = sells + 1, sell_usd + usd
    if not buys and not sells:
        return None
    return {"buys": buys, "sells": sells, "buy_usd": buy_usd, "sell_usd": sell_usd,
            "net_usd": buy_usd - sell_usd, "insiders": len(names)}


def insider_lines(summaries: dict[str, dict], checked: list[str], skipped: int,
                  failed: list[str], start: str, end: str) -> list[str]:
    ranked = sorted(summaries.items(), key=lambda kv: -abs(kv[1]["net_usd"]))
    lines = []
    for t, s in ranked[:INSIDER_TOP]:
        side = "net buy" if s["net_usd"] > 0 else "net sell"
        lines.append(f"- {t}: {side} {_money(s['net_usd'])} ({s['buys']} buys {_money(s['buy_usd'])}, "
                     f"{s['sells']} sells {_money(s['sell_usd'])}; {s['insiders']} insider{'s' if s['insiders'] != 1 else ''})")
    note = (f"- {len(summaries)} of {len(checked)} checked US stocks had open-market insider "
            f"buys/sells (SEC Form 4 codes P/S) with trade dates {start} to {end}")
    if skipped:
        note += f"; {skipped} more not checked (request cap)"
    if failed:
        note += f"; lookup failed for {', '.join(failed[:5])}"
    return lines + [note]


async def fetch_insiders(today: str) -> list[str]:
    watched = watched_stocks()
    checked = watched[:INSIDER_MAX_TICKERS]
    start = (date.fromisoformat(today) - timedelta(days=INSIDER_DAYS)).isoformat()
    summaries: dict[str, dict] = {}
    failed: list[str] = []
    async with _client() as c:
        for t in checked:
            try:
                data = await _get(c, "/stock/insider-transactions",
                                  {"symbol": t, "from": start, "to": today})
            except httpx.HTTPError:
                failed.append(t)
                continue
            s = summarize_insiders(data.get("data") or [], start, today)
            if s:
                summaries[t] = s
    if failed and len(failed) == len(checked):
        raise RuntimeError("all Finnhub insider lookups failed")
    return insider_lines(summaries, checked, len(watched) - len(checked), failed, start, today)


FEEDS = [
    Feed("finnhub_earnings", f"Upcoming earnings (next {EARNINGS_DAYS} days, watched US stocks, Finnhub)",
         SHADOWS, fetch_earnings),
    Feed("finnhub_insiders", f"Insider transactions (last {INSIDER_DAYS} days, net buy/sell by company, Finnhub)",
         SHADOWS, fetch_insiders),
]
