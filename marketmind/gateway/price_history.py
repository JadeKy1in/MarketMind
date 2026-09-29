"""Long-horizon price history for code-computed technicals (SPEC_v3 §5, L3).

Returns ~5 years of daily bars plus derived weekly bars, which is what the
3-light review needs (200-week MA, 52-week range, ATR). The 3-month OHLCV in
market_data.py is too short for that.

Sources: Alpaca market data first for US stocks/ETFs when ALPACA_API_KEY_ID and
ALPACA_API_SECRET_KEY are set (owner decision 2026-09-27); yfinance for stocks,
ETFs and indices. Crypto ("BTC-USD") uses exchange candles first — Binance public
klines, then Bybit public spot klines, then Coinbase Exchange daily candles — and
yfinance only as the last resort (owner decision 2026-09-29; Yahoo's series skipped
2026-09-28 entirely); the
Nasdaq public historical API
(api.nasdaq.com) as a fallback for US stocks/ETFs. No API keys. Returns None
when every source fails — callers must report "data unavailable", never guess.

Nasdaq caveats (verified live 2026-09-27): prices ARE split-adjusted (NVDA
10:1 split on 2024-06-10 is continuous: 06-07 $120.888 -> 06-10 $121.79) but
NOT dividend-adjusted (AAPL 2021-09-27 close $145.37 = raw close), so they
differ slightly from yfinance auto_adjust closes, more so for high-yield
tickers. Indices (^...), futures/FX (=), non-US suffix tickers (.SS, .HK, ...)
and crypto are not sent to Nasdaq. Class shares map "-" -> "." (BRK-B -> BRK.B).

Alpaca (verified live 2026-09-27 on the free Basic plan): consolidated SIP daily
bars with adjustment=all, i.e. split- AND dividend-adjusted, full-market volume
(NVDA 2024-06-05 close 122.09 after the 10:1 split; AAPL 194.02 vs raw 195.87).
The Basic plan cannot query the most recent 15 minutes of SIP data, so `end` is
set 20 minutes in the past. Same symbol rules as Nasdaq (BRK-B -> BRK.B).

Bybit caveats: "BTC-USD" maps to the spot pair "BTCUSDT", i.e. prices are
quoted in USDT, treated as ~USD (same assumption as the Binance path). Bars are
UTC-day candles. Like the Binance path, the current (still-forming) UTC day's
bar is kept as the last bar. Only "-USD" tickers are sent to Bybit.

Coinbase Exchange caveats (verified live 2026-09-28): public
api.exchange.coinbase.com/products/<BASE>-USD/candles, granularity=86400, rows
[time, low, high, open, close, volume] newest first, at most 300 candles per
request, so `years` of history is paged back with start/end (ISO 8601). Real USD
pairs (not USDT). UTC-day candles; the current UTC day's partial bar is kept as
the last bar, like Binance / Bybit (callers drop it with complete_bars).
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

import httpx

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - yfinance is a hard dependency
    yf = None

logger = logging.getLogger("marketmind.gateway.price_history")

_BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
_BYBIT_KLINES = "https://api.bybit.com/v5/market/kline"
_BYBIT_TIMEOUT = 15.0
_BYBIT_PAGE = 1000
_COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/{product}/candles"
_COINBASE_TIMEOUT = 15.0
_COINBASE_PAGE = 300
_NASDAQ_HISTORICAL = "https://api.nasdaq.com/api/quote/{symbol}/historical"
_NASDAQ_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
    "Accept": "application/json",
}
_NASDAQ_TIMEOUT = 15.0
_ALPACA_BARS = "https://data.alpaca.markets/v2/stocks/bars"
_ALPACA_TIMEOUT = 15.0
_ALPACA_MAX_PAGES = 5
_YF_CONCURRENCY = asyncio.Semaphore(5)
_cache: dict[str, "PriceHistory | None"] = {}


@dataclass
class Bar:
    date: str      # YYYY-MM-DD (for weekly bars: last trading day of the week)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class PriceHistory:
    ticker: str
    source: str
    daily: list[Bar] = field(default_factory=list)
    weekly: list[Bar] = field(default_factory=list)


async def get_price_history(ticker: str, years: int = 5) -> PriceHistory | None:
    """Daily + weekly bars for `ticker`, cached per process run."""
    key = f"{ticker.upper()}:{years}"
    if key in _cache:
        return _cache[key]
    from marketmind.markets import US, market_for
    market = market_for(ticker)
    if is_crypto_ticker(ticker):
        # Exchange candles first (owner decision 2026-09-29): one consistent series for
        # snapshots, L3 and settlement. Yahoo is the last resort — on 2026-09-29 its
        # BTC-USD/SOL-USD series skipped 09-28 entirely.
        hist = await _from_binance(ticker, years)
        if hist is None:
            hist = await _from_bybit(ticker, years)
        if hist is None:
            hist = await _from_coinbase(ticker, years)
        if hist is None:
            hist = await _from_yfinance(ticker, years)
            if hist is not None and (gap := missing_utc_day(hist.daily)):
                logger.warning("yfinance %s has no bar for %s (exchange sources failed)",
                               ticker, gap)
    else:
        hist = await _from_alpaca(ticker, years) if market is US else None
        if hist is None:
            hist = await _from_yfinance(ticker, years)
        if hist is None and market is US:
            hist = await _from_nasdaq(ticker, years)
        elif hist is None:
            # non-US markets, futures, FX, indices (docs/S3_DESIGN.md §7)
            # Tencent first: it covers HK/CN, and Eastmoney hosts failed with
            # RemoteProtocolError on 2026-09-28. Eastmoney stays for the futures, FX and
            # indices only it maps (from_tencent returns None for those).
            from marketmind.gateway.global_quotes import from_eastmoney, from_tencent
            hist = await from_tencent(ticker, years)
            if hist is None:
                hist = await from_eastmoney(ticker, years)
    if hist is None:
        # last resort for every market; it declines what its plan does not cover
        from marketmind.gateway.global_quotes import from_twelvedata
        hist = await from_twelvedata(ticker, years)
    if hist is None:
        logger.warning("No price history for %s — all sources failed", ticker)
    _cache[key] = hist
    return hist


async def get_price_histories(tickers: list[str], years: int = 5) -> dict[str, PriceHistory | None]:
    results = await asyncio.gather(*(get_price_history(t, years) for t in tickers))
    return dict(zip(tickers, results))


def clear_cache() -> None:
    _cache.clear()


# ── yfinance ────────────────────────────────────────────────────────────────

async def _from_yfinance(ticker: str, years: int) -> PriceHistory | None:
    if yf is None:
        return None
    async with _YF_CONCURRENCY:
        try:
            return await asyncio.wait_for(asyncio.to_thread(_yf_sync, ticker, years), timeout=60)
        except Exception as exc:
            logger.warning("yfinance history failed for %s: %s", ticker, exc)
            return None


def _yf_sync(ticker: str, years: int) -> PriceHistory | None:
    from marketmind.markets import yahoo_symbol
    df = yf.Ticker(yahoo_symbol(ticker)).history(period=f"{years}y", interval="1d", auto_adjust=True)
    if df is None or df.empty:
        return None
    daily = _yf_bars(df)
    if not daily:
        return None
    return PriceHistory(ticker=ticker, source="yfinance", daily=daily, weekly=to_weekly(daily))


def _yf_bars(df) -> list[Bar]:
    """yfinance frame -> bars. A row with any non-finite Open/High/Low/Close is dropped
    (Yahoo sometimes leaves O/H/L NaN on a valid Close, which made ATR/stop/target NaN);
    a missing or non-finite Volume becomes 0.0."""
    import math
    bars: list[Bar] = []
    for idx, r in df.iterrows():
        try:
            o, h, lo, c = (float(r[k]) for k in ("Open", "High", "Low", "Close"))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (o, h, lo, c)):
            continue
        try:
            vol = float(r.get("Volume", 0.0))
        except (TypeError, ValueError):
            vol = 0.0
        bars.append(Bar(date=idx.strftime("%Y-%m-%d"), open=o, high=h, low=lo, close=c,
                        volume=vol if math.isfinite(vol) else 0.0))
    return bars


# ── Binance (first crypto source) ──────────────────────────────────────────────

_BINANCE_PAGE = 1000


async def _from_binance(ticker: str, years: int = 5) -> PriceHistory | None:
    """Binance spot daily klines, paged back `years` (1000 bars per request)."""
    from datetime import datetime, timedelta, timezone
    symbol = ticker.upper().replace("-USD", "USDT")
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=int(365.25 * years))
    start_ms = int(start_dt.timestamp() * 1000)
    max_pages = int(365.25 * years) // _BINANCE_PAGE + 2
    raw: list = []
    try:
        async with _binance_client() as client:
            for _ in range(max_pages):
                params = {"symbol": symbol, "interval": "1d", "limit": _BINANCE_PAGE,
                          "startTime": start_ms}
                resp = await client.get(_BINANCE_KLINES, params=params)
                resp.raise_for_status()
                rows = resp.json()
                if not isinstance(rows, list) or not rows:
                    break
                raw.extend(rows)
                # with startTime, Binance returns the oldest `limit` bars from it: walk forward
                if len(rows) < _BINANCE_PAGE:
                    break
                start_ms = int(rows[-1][0]) + 1
    except Exception as exc:
        logger.warning("Binance klines failed for %s: %s", ticker, exc)
        return None
    by_date: dict[str, Bar] = {}
    for r in raw:
        try:
            d = datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            by_date[d] = Bar(date=d, open=float(r[1]), high=float(r[2]), low=float(r[3]),
                             close=float(r[4]), volume=float(r[5]))
        except (IndexError, TypeError, ValueError, OverflowError, OSError):
            continue
    daily = [by_date[d] for d in sorted(by_date)]
    if not daily:
        return None
    return PriceHistory(ticker=ticker, source="binance", daily=daily, weekly=to_weekly(daily))


def _binance_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15)


# ── Bybit (second crypto fallback) ─────────────────────────────────────────

def _bybit_symbol(ticker: str) -> str | None:
    """"BTC-USD" -> "BTCUSDT" (USDT quote, treated as ~USD); None for non-crypto."""
    t = ticker.strip().upper()
    if not t.endswith("-USD") or len(t) <= 4:
        return None
    return t[:-4] + "USDT"


def _bybit_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_BYBIT_TIMEOUT)


def _parse_bybit(rows) -> list[Bar]:
    """Bybit kline rows (newest-first strings) -> ascending bars, deduped on date."""
    from datetime import datetime, timezone
    by_date: dict[str, Bar] = {}
    for r in rows or []:
        try:
            d = datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            by_date[d] = Bar(date=d, open=float(r[1]), high=float(r[2]), low=float(r[3]),
                             close=float(r[4]), volume=float(r[5]))
        except (IndexError, TypeError, ValueError, OverflowError, OSError):
            continue
    return [by_date[d] for d in sorted(by_date)]


async def _from_bybit(ticker: str, years: int) -> PriceHistory | None:
    symbol = _bybit_symbol(ticker)
    if symbol is None:
        return None
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=int(365.25 * years))
    start_ms = int(start_dt.timestamp() * 1000)
    cutoff = start_dt.strftime("%Y-%m-%d")
    max_pages = int(365.25 * years) // _BYBIT_PAGE + 2
    raw: list = []
    # Always send `end`: with only `start`, Bybit returns the oldest `limit`
    # bars going forward from `start` instead of the newest ones.
    end_ms = int(now.timestamp() * 1000)
    try:
        async with _bybit_client() as client:
            for _ in range(max_pages):
                params = {"category": "spot", "symbol": symbol, "interval": "D",
                          "limit": _BYBIT_PAGE, "start": start_ms, "end": end_ms}
                resp = await client.get(_BYBIT_KLINES, params=params)
                if resp.status_code != 200:
                    logger.warning("Bybit klines HTTP %s for %s", resp.status_code, ticker)
                    return None
                payload = resp.json()
                if not isinstance(payload, dict) or payload.get("retCode") != 0:
                    logger.warning("Bybit klines error for %s: retCode=%s %s", ticker,
                                   (payload or {}).get("retCode") if isinstance(payload, dict) else None,
                                   (payload or {}).get("retMsg") if isinstance(payload, dict) else payload)
                    return None
                rows = ((payload.get("result") or {}).get("list")) or []
                if not isinstance(rows, list):
                    logger.warning("Bybit klines malformed list for %s", ticker)
                    return None
                raw.extend(rows)
                starts = [int(r[0]) for r in rows]
                if len(rows) < _BYBIT_PAGE or not starts or min(starts) <= start_ms:
                    break
                end_ms = min(starts) - 1
    except Exception as exc:
        logger.warning("Bybit klines failed for %s: %s", ticker, exc)
        return None
    daily = [b for b in _parse_bybit(raw) if b.date >= cutoff]
    if not daily:
        logger.warning("Bybit klines empty for %s", ticker)
        return None
    return PriceHistory(ticker=ticker, source="bybit", daily=daily, weekly=to_weekly(daily))


# ── Coinbase Exchange (third crypto fallback) ─────────────────────────────

def _coinbase_product(ticker: str) -> str | None:
    """"BTC-USD" -> "BTC-USD" (a real USD pair); None for non-crypto."""
    t = ticker.strip().upper()
    if not t.endswith("-USD") or len(t) <= 4:
        return None
    return t


def _coinbase_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_COINBASE_TIMEOUT,
                             headers={"User-Agent": "MarketMind/0.1", "Accept": "application/json"})


def _parse_coinbase(rows) -> list[Bar]:
    """Coinbase candles [time, low, high, open, close, volume] -> ascending bars, deduped."""
    from datetime import datetime, timezone
    by_date: dict[str, Bar] = {}
    for r in rows or []:
        try:
            d = datetime.fromtimestamp(int(r[0]), tz=timezone.utc).strftime("%Y-%m-%d")
            by_date[d] = Bar(date=d, open=float(r[3]), high=float(r[2]), low=float(r[1]),
                             close=float(r[4]), volume=float(r[5]))
        except (IndexError, TypeError, ValueError, OverflowError, OSError):
            continue
    return [by_date[d] for d in sorted(by_date)]


async def _from_coinbase(ticker: str, years: int) -> PriceHistory | None:
    product = _coinbase_product(ticker)
    if product is None:
        return None
    from datetime import datetime, timedelta, timezone
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=int(365.25 * years))
    cutoff = start_dt.strftime("%Y-%m-%d")
    url = _COINBASE_CANDLES.format(product=product)
    raw: list = []
    end = now
    try:
        async with _coinbase_client() as client:
            while end > start_dt:
                # 299 days + end-inclusive stays within the 300-candle cap
                start = max(start_dt, end - timedelta(days=_COINBASE_PAGE - 1))
                resp = await client.get(url, params={"granularity": 86400,
                                                     "start": start.strftime(fmt),
                                                     "end": end.strftime(fmt)})
                if resp.status_code != 200:
                    logger.warning("Coinbase candles HTTP %s for %s", resp.status_code, ticker)
                    return None
                rows = resp.json()
                if not isinstance(rows, list):
                    logger.warning("Coinbase candles malformed for %s", ticker)
                    return None
                if not rows:
                    break            # before the product's listing
                raw.extend(rows)
                end = start - timedelta(seconds=1)
    except Exception as exc:
        logger.warning("Coinbase candles failed for %s: %s", ticker, exc)
        return None
    daily = [b for b in _parse_coinbase(raw) if b.date >= cutoff]
    if not daily:
        logger.warning("Coinbase candles empty for %s", ticker)
        return None
    return PriceHistory(ticker=ticker, source="coinbase", daily=daily, weekly=to_weekly(daily))


# ── Nasdaq (US stock/ETF fallback) ─────────────────────────────────────────

def _nasdaq_symbol(ticker: str) -> str | None:
    """yfinance-style ticker -> Nasdaq symbol; None when Nasdaq can't serve it."""
    t = ticker.strip().upper()
    if not t or t.startswith("^") or "=" in t or "." in t or t.endswith("-USD"):
        return None
    return t.replace("-", ".")


def _nasdaq_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_NASDAQ_TIMEOUT, headers=_NASDAQ_HEADERS)


def _num(text) -> float:
    return float(str(text).replace("$", "").replace(",", "").strip())


def _parse_nasdaq(payload: dict) -> list[Bar]:
    """Nasdaq JSON -> ascending daily bars. Unparseable rows are skipped."""
    from datetime import datetime
    rows = (((payload or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
    bars: list[Bar] = []
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%m/%d/%Y").strftime("%Y-%m-%d")
            try:
                vol = _num(r.get("volume"))
            except (TypeError, ValueError):
                vol = 0.0
            bars.append(Bar(date=d, open=_num(r["open"]), high=_num(r["high"]),
                            low=_num(r["low"]), close=_num(r["close"]), volume=vol))
        except (KeyError, TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b.date)
    return bars


async def _from_nasdaq(ticker: str, years: int) -> PriceHistory | None:
    symbol = _nasdaq_symbol(ticker)
    if symbol is None:
        return None
    from datetime import date, timedelta
    today = date.today()
    start = today - timedelta(days=int(365.25 * years))
    params = {"fromdate": start.isoformat(), "todate": today.isoformat(), "limit": 9999}
    try:
        async with _nasdaq_client() as client:
            for assetclass in ("stocks", "etf"):
                resp = await client.get(_NASDAQ_HISTORICAL.format(symbol=symbol),
                                        params={**params, "assetclass": assetclass})
                if resp.status_code != 200:
                    logger.warning("Nasdaq history HTTP %s for %s (%s)",
                                   resp.status_code, ticker, assetclass)
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    logger.warning("Nasdaq history non-JSON for %s (%s)", ticker, assetclass)
                    continue
                daily = [b for b in _parse_nasdaq(payload) if b.date >= start.isoformat()]
                if daily:
                    return PriceHistory(ticker=ticker, source="nasdaq",
                                        daily=daily, weekly=to_weekly(daily))
    except Exception as exc:
        logger.warning("Nasdaq history failed for %s: %s", ticker, exc)
        return None
    logger.warning("Nasdaq history empty for %s", ticker)
    return None


# ── Alpaca ──────────────────────────────────────────────────────────────────

def _alpaca_headers() -> dict | None:
    key = os.environ.get("ALPACA_API_KEY_ID", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
    if not key or not secret:
        return None
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _alpaca_client(headers: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_ALPACA_TIMEOUT, headers=headers)


def _parse_alpaca(rows) -> list[Bar]:
    bars: list[Bar] = []
    for r in rows or []:
        try:
            bars.append(Bar(date=str(r["t"])[:10], open=float(r["o"]), high=float(r["h"]),
                            low=float(r["l"]), close=float(r["c"]), volume=float(r.get("v") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return bars


async def _from_alpaca(ticker: str, years: int) -> PriceHistory | None:
    """Split- and dividend-adjusted SIP daily bars; None without credentials or data."""
    symbol = _nasdaq_symbol(ticker)  # same universe: US stocks/ETFs only
    headers = _alpaca_headers()
    if symbol is None or headers is None:
        return None
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    params = {"symbols": symbol, "timeframe": "1Day", "adjustment": "all", "feed": "sip",
              "start": (now - timedelta(days=int(365.25 * years))).strftime("%Y-%m-%d"),
              "end": (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "limit": 10000}
    rows: list = []
    try:
        async with _alpaca_client(headers) as client:
            for _ in range(_ALPACA_MAX_PAGES):
                resp = await client.get(_ALPACA_BARS, params=params)
                if resp.status_code != 200:
                    logger.warning("Alpaca bars HTTP %s for %s", resp.status_code, ticker)
                    return None
                payload = resp.json()
                rows.extend(((payload or {}).get("bars") or {}).get(symbol) or [])
                token = (payload or {}).get("next_page_token")
                if not token:
                    break
                params["page_token"] = token
    except Exception as exc:
        logger.warning("Alpaca bars failed for %s: %s", ticker, exc)
        return None
    daily = sorted({b.date: b for b in _parse_alpaca(rows)}.values(), key=lambda b: b.date)
    if not daily:
        logger.warning("Alpaca bars empty for %s", ticker)
        return None
    return PriceHistory(ticker=ticker, source="alpaca", daily=daily, weekly=to_weekly(daily))


# ── Helpers ─────────────────────────────────────────────────────────────────

def to_weekly(daily: list[Bar]) -> list[Bar]:
    """Aggregate daily bars into ISO-week bars (close = last close of the week)."""
    from datetime import date
    weeks: list[Bar] = []
    current_key = None
    for b in daily:
        y, w, _ = date.fromisoformat(b.date).isocalendar()
        if (y, w) != current_key:
            weeks.append(Bar(b.date, b.open, b.high, b.low, b.close, b.volume))
            current_key = (y, w)
        else:
            wk = weeks[-1]
            wk.date = b.date
            wk.high = max(wk.high, b.high)
            wk.low = min(wk.low, b.low)
            wk.close = b.close
            wk.volume += b.volume
    return weeks


def is_crypto_ticker(ticker: str) -> bool:
    return ticker.upper().endswith("-USD")


def missing_utc_day(daily: list[Bar], lookback: int = 30) -> str | None:
    """First calendar date missing among the last `lookback` bars of a 7-day market."""
    from datetime import date, timedelta
    recent = daily[-lookback:]
    for prev, cur in zip(recent, recent[1:]):
        expected = date.fromisoformat(prev.date) + timedelta(days=1)
        if cur.date > expected.isoformat():
            return expected.isoformat()
    return None


def complete_bars(ticker: str, daily: list[Bar], now=None) -> list[Bar]:
    """Drop the running session's partial bar.

    Crypto and FX bars are UTC days: only dates before today (UTC) are complete.
    Exchange-traded bars are local sessions: today's bar is complete only after
    that exchange's close in its own timezone (marketmind.markets).
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from marketmind.markets import market_for
    now = now or datetime.now(timezone.utc)
    m = market_for(ticker)
    if m.utc_days:
        cutoff = now.astimezone(timezone.utc).date().isoformat()
        return [b for b in daily if b.date < cutoff]
    local = now.astimezone(ZoneInfo(m.tz))
    today = local.date().isoformat()
    closed = local.time() >= m.close
    return [b for b in daily if b.date < today or (b.date == today and closed)]


def completed_history(hist: PriceHistory, now=None) -> PriceHistory:
    """`hist` without a partial last bar (weekly bars rebuilt if anything was dropped)."""
    daily = complete_bars(hist.ticker, hist.daily, now)
    if len(daily) == len(hist.daily):
        return hist
    return PriceHistory(ticker=hist.ticker, source=hist.source, daily=daily,
                        weekly=to_weekly(daily))
