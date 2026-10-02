"""More free daily-bar sources (owner approval 2026-10-02; docs/DATA_SOURCES_2026-09-29.md §4).

Wired into price_history.get_price_history after Yahoo / Tencent / Eastmoney:
- Stooq (STOOQ_API_KEY): JP (.T), HK, DE (Xetra), UK (.L), metal/energy futures,
  FX and a few indices. Second source for those markets and the first source used to
  repair Yahoo's close-only bars. The key must go in the URL (`apikey=`), so URLs are
  never logged. Errors (no key, quota, unknown symbol, browser check) come back as
  HTTP 200 with a text/HTML body, so the body is validated: only a CSV whose header
  starts "Date,Open,High,Low,Close" is parsed. Quota / key / browser-check answers
  disable Stooq for the rest of the process.
- baostock (no key, `pip install baostock`): A-shares (.SS/.SZ), forward-adjusted
  (adjustflag=2, the same basis as Yahoo auto_adjust). Synchronous library with a
  global socket, so all calls run in ONE worker thread with a timeout.
- FinMind (optional FINMIND_TOKEN, works without one at a lower hourly limit):
  Taiwan (.TW/.TWO). TaiwanStockPrice is NOT dividend-adjusted (the adjusted dataset
  needs a paid level, checked 2026-10-02), like the Nasdaq fallback.
- EODHD (EODHD_API_KEY, free plan: 20 calls/day, 1 year of history): last resort for
  every market. A persisted per-UTC-day slot counter (one file per call under
  altdata/eodhd/budget/) makes it impossible to exceed EODHD_DAILY_LIMIT, also across
  processes. Prices are scaled by adjusted_close/close (split + dividend adjusted).
A source whose env var is missing is skipped with one debug log per process.
Any failure returns None and the caller moves on; nothing is estimated.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx

from marketmind.gateway.altdata_store import altdata_dir

logger = logging.getLogger("marketmind.gateway.free_quotes")

TIMEOUT_S = 20.0
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}

# ── key redaction ───────────────────────────────────────────────────────────

_SECRET_PARAM = re.compile(r"((?:apikey|api_token|token)=)[^&\s'\"<>]+", re.IGNORECASE)


def redact(text) -> str:
    """Mask query-string secrets (apikey=, api_token=, token=) in a URL or message."""
    return _SECRET_PARAM.sub(r"\1***", str(text))


class _RedactFilter(logging.Filter):
    """httpx logs every request URL at INFO ("HTTP Request: GET https://...?apikey=...");
    the scheduled runs log INFO to files, so the query secrets are masked first."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:          # malformed record: leave it to logging's own handling
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


_httpx_logger = logging.getLogger("httpx")
if not any(isinstance(f, _RedactFilter) for f in _httpx_logger.filters):
    _httpx_logger.addFilter(_RedactFilter())


_skipped: set[str] = set()


def _env_key(var: str) -> str:
    """The env var's value, or "" with one debug log per process when it is not set."""
    value = os.environ.get(var, "").strip()
    if not value and var not in _skipped:
        _skipped.add(var)
        logger.debug("%s not set; that price source is skipped", var)
    return value


def _client(headers: dict | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_S, headers=headers or HEADERS)


def _f(v) -> float:
    return float(str(v).replace(",", "").strip())


def _bar(d: str, o, h, low, c, vol):
    """Bar from raw values, or None when a price is missing / non-positive / inconsistent."""
    from marketmind.gateway.price_history import Bar
    try:
        o, h, low, c = _f(o), _f(h), _f(low), _f(c)
    except (TypeError, ValueError):
        return None
    if min(o, h, low, c) <= 0 or low > min(o, c) or h < max(o, c):
        return None
    try:
        v = _f(vol) if vol not in (None, "", "-") else 0.0
    except (TypeError, ValueError):
        v = 0.0
    return Bar(date=str(d)[:10], open=o, high=h, low=low, close=c, volume=v)


def _history(ticker: str, source: str, bars: list):
    from marketmind.gateway.price_history import PriceHistory, to_weekly
    daily = sorted({b.date: b for b in bars}.values(), key=lambda b: b.date)
    return PriceHistory(ticker=ticker, source=source, daily=daily, weekly=to_weekly(daily))


# ── Stooq ───────────────────────────────────────────────────────────────────

STOOQ_URL = "https://stooq.com/q/d/l/"
STOOQ_MIN_INTERVAL_S = 1.0
_stooq_lock = asyncio.Lock()
_stooq_last = 0.0
_stooq_disabled: str | None = None      # reason; set once per process

_STOOQ_SUFFIX = {"T": "jp", "HK": "hk", "DE": "de", "L": "uk"}
# Yahoo futures root -> Stooq continuous contract (same CME/NYMEX/COMEX contract)
_STOOQ_FUTURES = {"CL": "cl.f", "NG": "ng.f", "GC": "gc.f", "SI": "si.f",
                  "HG": "hg.f", "PL": "pl.f", "PA": "pa.f"}
_STOOQ_INDICES = {"^N225": "^nkx", "^GDAXI": "^dax", "^FTSE": "^ukx", "^HSI": "^hsi",
                  "^GSPC": "^spx", "^FCHI": "^cac"}


def stooq_symbol(ticker: str) -> str | None:
    """Yahoo-style ticker -> Stooq symbol; None for markets this module does not send
    to Stooq (US stocks have four other sources; other EU exchanges are not on Stooq)."""
    t = ticker.strip().upper()
    if not t or t.endswith("-USD"):
        return None
    if t.startswith("^"):
        return _STOOQ_INDICES.get(t)
    if t.endswith("=F"):
        return _STOOQ_FUTURES.get(t[:-2])
    if t.endswith("=X"):
        pair = t[:-2]
        if len(pair) == 3:            # Yahoo "JPY=X" means USDJPY
            pair = "USD" + pair
        return pair.lower() if len(pair) == 6 and pair.isalpha() else None
    if "." not in t:
        return None
    code, suffix = t.rsplit(".", 1)
    ext = _STOOQ_SUFFIX.get(suffix)
    if ext is None or not code:
        return None
    if ext == "hk":
        if not code.isdigit():
            return None
        code = str(int(code))         # Stooq writes 700.hk, not 0700.hk
    return f"{code.lower()}.{ext}"


def classify_stooq_body(text: str) -> str:
    """'csv' for a daily CSV, else the kind of error page Stooq answered with HTTP 200:
    'challenge' (browser check), 'quota', 'apikey', 'nodata' or 'unknown'."""
    head = (text or "").lstrip("﻿ \r\n\t")[:400]
    low = head.lower()
    if low.startswith("date,open,high,low,close"):
        return "csv"
    if "verify your browser" in low or "requires javascript" in low:
        return "challenge"
    if "exceeded" in low or "limit" in low:
        return "quota"
    if "apikey" in low or "api key" in low:
        return "apikey"
    if low.startswith("no data") or low.strip() == "":
        return "nodata"
    return "unknown"


def parse_stooq_csv(text: str) -> list:
    """Stooq CSV (Date,Open,High,Low,Close[,Volume], oldest first) -> bars."""
    rows = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    bars = []
    for r in rows:
        r = {(k or "").strip().lower(): v for k, v in r.items()}
        try:
            b = _bar(r["date"], r["open"], r["high"], r["low"], r["close"], r.get("volume"))
        except KeyError:
            continue
        if b is not None:
            bars.append(b)
    return bars


async def _stooq_get(client: httpx.AsyncClient, params: dict) -> httpx.Response:
    """Serialised and spaced (one request a second)."""
    global _stooq_last
    async with _stooq_lock:
        wait = STOOQ_MIN_INTERVAL_S - (time.monotonic() - _stooq_last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await client.get(STOOQ_URL, params=params)
        finally:
            _stooq_last = time.monotonic()


def _stooq_disable(reason: str) -> None:
    global _stooq_disabled
    if _stooq_disabled is None:
        _stooq_disabled = reason
        logger.warning("Stooq disabled for this run: %s", reason)


async def from_stooq(ticker: str, years: int = 5):
    sym = stooq_symbol(ticker)
    if sym is None or _stooq_disabled is not None:
        return None
    key = _env_key("STOOQ_API_KEY")
    if not key:
        return None
    today = date.today()
    params = {"s": sym, "i": "d", "apikey": key,
              "d1": (today - timedelta(days=int(365.25 * years))).strftime("%Y%m%d"),
              "d2": today.strftime("%Y%m%d")}
    try:
        async with _client() as client:
            resp = await _stooq_get(client, params)
        text = resp.text
    except Exception as e:
        logger.warning("Stooq failed for %s: %s: %s", ticker, type(e).__name__, redact(e))
        return None
    if resp.status_code != 200:
        logger.warning("Stooq HTTP %d for %s", resp.status_code, ticker)
        return None
    kind = classify_stooq_body(text)
    if kind == "challenge":
        _stooq_disable("answered with a browser (JavaScript) check instead of CSV")
        return None
    if kind == "quota":
        _stooq_disable("daily request limit reached")
        return None
    if kind == "apikey":
        _stooq_disable("STOOQ_API_KEY rejected or missing")
        return None
    if kind != "csv":
        logger.warning("Stooq returned no data for %s (%s): %s", ticker, sym,
                       redact(text.strip()[:80]))
        return None
    bars = parse_stooq_csv(text)
    if not bars:
        logger.warning("Stooq CSV had no valid bars for %s (%s)", ticker, sym)
        return None
    return _history(ticker, "stooq", bars)


# ── baostock (A-shares) ─────────────────────────────────────────────────────

BAOSTOCK_TIMEOUT_S = 60.0
_bs_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="baostock")
_bs_disabled: str | None = None


def baostock_code(ticker: str) -> str | None:
    t = ticker.strip().upper()
    if t.endswith(".SS") and t[:-3].isdigit():
        return "sh." + t[:-3]
    if t.endswith(".SZ") and t[:-3].isdigit():
        return "sz." + t[:-3]
    return None


def parse_baostock(rows) -> list:
    """Rows [date, open, high, low, close, volume, tradestatus]; suspended days
    (tradestatus 0: price copied from the last close, no trading) are dropped."""
    bars = []
    for r in rows or []:
        try:
            if len(r) > 6 and str(r[6]) == "0":
                continue
            b = _bar(r[0], r[1], r[2], r[3], r[4], r[5])
        except (IndexError, TypeError):
            continue
        if b is not None:
            bars.append(b)
    return bars


def _baostock_sync(code: str, start: str, end: str) -> list:
    import baostock as bs
    # it prints "login success!"; not silenced: redirect_stdout swaps sys.stdout for the
    # whole process, and this runs in a worker thread while the run prints step lines
    lg = bs.login()
    if str(lg.error_code) != "0":
        raise RuntimeError(f"login failed: {lg.error_code} {lg.error_msg}")
    try:
        rs = bs.query_history_k_data_plus(
            code, "date,open,high,low,close,volume,tradestatus",
            start_date=start, end_date=end, frequency="d", adjustflag="2")
        if str(rs.error_code) != "0":
            raise RuntimeError(f"query failed: {rs.error_code} {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return rows
    finally:
        bs.logout()


async def from_baostock(ticker: str, years: int = 5):
    global _bs_disabled
    code = baostock_code(ticker)
    if code is None or _bs_disabled is not None:
        return None
    try:
        import baostock  # noqa: F401
    except ImportError:
        _bs_disabled = "not installed"
        logger.debug("baostock not installed; A-share source skipped")
        return None
    today = date.today()
    start = (today - timedelta(days=int(365.25 * years))).isoformat()
    loop = asyncio.get_running_loop()
    try:
        rows = await asyncio.wait_for(
            loop.run_in_executor(_bs_executor, _baostock_sync, code, start, today.isoformat()),
            timeout=BAOSTOCK_TIMEOUT_S)
    except TimeoutError:
        # the worker thread may still be stuck on the socket: stop queueing behind it
        _bs_disabled = "timed out"
        logger.warning("baostock timed out for %s; disabled for this run", ticker)
        return None
    except Exception as e:
        logger.warning("baostock failed for %s: %s: %s", ticker, type(e).__name__, e)
        return None
    bars = parse_baostock(rows)
    if not bars:
        logger.warning("baostock returned no bars for %s (%s)", ticker, code)
        return None
    return _history(ticker, "baostock", bars)


# ── FinMind (Taiwan) ────────────────────────────────────────────────────────

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
_fm_disabled: str | None = None


def finmind_id(ticker: str) -> str | None:
    t = ticker.strip().upper()
    for suffix in (".TW", ".TWO"):
        if t.endswith(suffix) and t[:-len(suffix)].isalnum():
            return t[:-len(suffix)]
    return None


def parse_finmind(payload: dict) -> list:
    """TaiwanStockPrice rows: date, open, max, min, close, Trading_Volume (shares)."""
    bars = []
    for r in (payload or {}).get("data") or []:
        try:
            b = _bar(r["date"], r["open"], r["max"], r["min"], r["close"],
                     r.get("Trading_Volume"))
        except (KeyError, TypeError):
            continue
        if b is not None:
            bars.append(b)
    return bars


async def from_finmind(ticker: str, years: int = 5):
    global _fm_disabled
    data_id = finmind_id(ticker)
    if data_id is None or _fm_disabled is not None:
        return None
    token = os.environ.get("FINMIND_TOKEN", "").strip()   # optional
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    start = (date.today() - timedelta(days=int(365.25 * years))).isoformat()
    params = {"dataset": "TaiwanStockPrice", "data_id": data_id, "start_date": start}
    try:
        async with _client(headers) as client:
            resp = await client.get(FINMIND_URL, params=params)
        payload = resp.json()
    except Exception as e:
        logger.warning("FinMind failed for %s: %s: %s", ticker, type(e).__name__, redact(e))
        return None
    if not isinstance(payload, dict):
        logger.warning("FinMind malformed answer for %s (HTTP %d)", ticker, resp.status_code)
        return None
    if payload.get("status") != 200:
        msg = str(payload.get("msg") or "")[:120]          # never log token_tail
        if "upper limit" in msg.lower():
            _fm_disabled = "request limit"
            logger.warning("FinMind request limit reached; disabled for this run")
        else:
            logger.warning("FinMind error for %s: %s %s", ticker, payload.get("status"), msg)
        return None
    bars = parse_finmind(payload)
    if not bars:
        logger.warning("FinMind returned no bars for %s", ticker)
        return None
    return _history(ticker, "finmind", bars)


# ── EODHD (budget-guarded last resort) ──────────────────────────────────────

EODHD_URL = "https://eodhd.com/api/eod/{symbol}"
EODHD_DAILY_LIMIT = 20            # free plan, resets at midnight UTC
EODHD_MAX_YEARS = 1               # free plan history depth
_eodhd_disabled: str | None = None
_eodhd_exhausted_logged: set[str] = set()

_EODHD_SUFFIX = {"T": "TSE", "HK": "HK", "DE": "XETRA", "F": "F", "L": "LSE", "PA": "PA",
                 "AS": "AS", "SW": "SW", "MI": "MI", "MC": "MC", "CO": "CO", "SS": "SHG",
                 "SZ": "SHE", "TW": "TW", "KS": "KO", "KQ": "KQ", "NS": "NSE", "TO": "TO",
                 "AX": "AU", "ST": "ST", "OL": "OL", "SA": "SA", "MX": "MX"}
_EODHD_INDICES = {"^GSPC", "^N225", "^GDAXI", "^FTSE", "^HSI", "^FCHI"}


def eodhd_symbol(ticker: str) -> str | None:
    """Yahoo-style ticker -> EODHD "<code>.<exchange>"; None for futures (not on the
    free plan) and unmapped exchanges."""
    from marketmind.markets import UNKNOWN, market_for
    t = ticker.strip().upper()
    if not t or t.endswith("=F"):
        return None
    if t.startswith("^"):
        return f"{t[1:]}.INDX" if t in _EODHD_INDICES else None
    if t.endswith("=X"):
        pair = t[:-2]
        if len(pair) == 3:
            pair = "USD" + pair
        return f"{pair}.FOREX" if len(pair) == 6 and pair.isalpha() else None
    if t.endswith("-USD"):
        return f"{t}.CC"
    if "." in t:
        code, suffix = t.rsplit(".", 1)
        exch = _EODHD_SUFFIX.get(suffix)
        if exch is not None:
            if suffix == "HK" and code.isdigit():
                code = (code.lstrip("0") or "0").zfill(4)     # 09866 -> 9866, 700 -> 0700
            return f"{code}.{exch}"
    m = market_for(t)
    if m is UNKNOWN or m.code != "US":
        return None
    return f"{t.replace('.', '-')}.US"        # BRK.B / BRK-B -> BRK-B.US


def _budget_dir():
    return altdata_dir("eodhd") / "budget"


def eodhd_calls_used(day: str | None = None) -> int:
    day = day or datetime.now(timezone.utc).date().isoformat()
    d = _budget_dir()
    return len(list(d.glob(f"{day}.*"))) if d.exists() else 0


def take_eodhd_slot(day: str | None = None) -> bool:
    """Reserve one of today's EODHD_DAILY_LIMIT calls. Each call creates a file
    `<day>.<n>` with O_EXCL, so two processes can never take the same slot and the
    total can never exceed the limit. Fails closed (False) when the dir is unusable.
    Slot files of earlier days are removed."""
    day = day or datetime.now(timezone.utc).date().isoformat()
    d = _budget_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("????-??-??.*"):
            if old.name[:10] < day:
                old.unlink(missing_ok=True)
        for n in range(1, EODHD_DAILY_LIMIT + 1):
            try:
                fd = os.open(d / f"{day}.{n:02d}", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            os.close(fd)
            return True
    except OSError as e:
        logger.warning("EODHD budget counter unusable (%s); not calling EODHD", e)
        return False
    return False


def parse_eodhd(rows) -> list:
    """[{date, open, high, low, close, adjusted_close, volume}] -> bars scaled by
    adjusted_close / close (split + dividend adjusted, like Yahoo auto_adjust)."""
    bars = []
    for r in rows or []:
        try:
            c = _f(r["close"])
            adj = _f(r.get("adjusted_close") or c)
            k = adj / c if c > 0 and adj > 0 else 1.0
            b = _bar(r["date"], _f(r["open"]) * k, _f(r["high"]) * k, _f(r["low"]) * k,
                     c * k, r.get("volume"))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        if b is not None:
            bars.append(b)
    return bars


async def from_eodhd(ticker: str, years: int = 5):
    global _eodhd_disabled
    from marketmind.markets import is_settleable
    sym = eodhd_symbol(ticker)
    if sym is None or _eodhd_disabled is not None or not is_settleable(ticker):
        return None
    key = _env_key("EODHD_API_KEY")
    if not key:
        return None
    day = datetime.now(timezone.utc).date().isoformat()
    if not take_eodhd_slot(day):
        if day not in _eodhd_exhausted_logged:
            _eodhd_exhausted_logged.add(day)
            logger.info("EODHD daily budget (%d calls) used up for %s", EODHD_DAILY_LIMIT, day)
        return None
    start = (date.today() - timedelta(days=int(365.25 * min(years, EODHD_MAX_YEARS))))
    params = {"api_token": key, "fmt": "json", "period": "d", "from": start.isoformat()}
    try:
        async with _client() as client:
            resp = await client.get(EODHD_URL.format(symbol=sym), params=params)
    except Exception as e:
        logger.warning("EODHD failed for %s: %s: %s", ticker, type(e).__name__, redact(e))
        return None
    if resp.status_code in (401, 402, 403, 429):
        _eodhd_disabled = f"HTTP {resp.status_code}"
        logger.warning("EODHD HTTP %d (%s); disabled for this run", resp.status_code,
                       redact(resp.text.strip()[:80]))
        return None
    if resp.status_code != 200:
        logger.warning("EODHD HTTP %d for %s (%s)", resp.status_code, ticker, sym)
        return None
    try:
        rows = resp.json()
    except ValueError:
        logger.warning("EODHD non-JSON answer for %s: %s", ticker, redact(resp.text.strip()[:80]))
        return None
    bars = parse_eodhd(rows if isinstance(rows, list) else [])
    if not bars:
        logger.warning("EODHD returned no bars for %s (%s)", ticker, sym)
        return None
    return _history(ticker, "eodhd", bars)


# ── close-only repair ───────────────────────────────────────────────────────

async def repair_reference(ticker: str, exclude: str, years: int = 2):
    """A second full-OHLC series for repairing close-only bars: Stooq, then the
    market's own free source (baostock for A-shares, FinMind for Taiwan, Tencent for
    HK/A-shares). `exclude` is the primary series' source (not used twice). EODHD is
    never used here: its 20 calls a day are kept for missing series."""
    from marketmind.gateway import global_quotes
    for name, fetch in (("stooq", from_stooq), ("baostock", from_baostock),
                        ("finmind", from_finmind), ("tencent", global_quotes.from_tencent)):
        if name == exclude:
            continue
        hist = await fetch(ticker, years)
        if hist is not None and hist.daily:
            return hist
    return None
