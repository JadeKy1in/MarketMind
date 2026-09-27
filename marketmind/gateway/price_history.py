"""Long-horizon price history for code-computed technicals (SPEC_v3 §5, L3).

Returns ~5 years of daily bars plus derived weekly bars, which is what the
3-light review needs (200-week MA, 52-week range, ATR). The 3-month OHLCV in
market_data.py is too short for that.

Sources: yfinance for stocks, ETFs, indices and crypto (e.g. "BTC-USD");
Binance public klines as a crypto fallback; the Nasdaq public historical API
(api.nasdaq.com) as a fallback for US stocks/ETFs. No API keys. Returns None
when every source fails — callers must report "data unavailable", never guess.

Nasdaq caveats (verified live 2026-09-27): prices ARE split-adjusted (NVDA
10:1 split on 2024-06-10 is continuous: 06-07 $120.888 -> 06-10 $121.79) but
NOT dividend-adjusted (AAPL 2021-09-27 close $145.37 = raw close), so they
differ slightly from yfinance auto_adjust closes, more so for high-yield
tickers. Indices (^...), futures/FX (=), non-US suffix tickers (.SS, .HK, ...)
and crypto are not sent to Nasdaq. Class shares map "-" -> "." (BRK-B -> BRK.B).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - yfinance is a hard dependency
    yf = None

logger = logging.getLogger("marketmind.gateway.price_history")

_BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
_NASDAQ_HISTORICAL = "https://api.nasdaq.com/api/quote/{symbol}/historical"
_NASDAQ_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
    "Accept": "application/json",
}
_NASDAQ_TIMEOUT = 15.0
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
    hist = await _from_yfinance(ticker, years)
    if hist is None and ticker.upper().endswith("-USD"):
        hist = await _from_binance(ticker)
    elif hist is None:
        hist = await _from_nasdaq(ticker, years)
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
    df = yf.Ticker(ticker).history(period=f"{years}y", interval="1d", auto_adjust=True)
    if df is None or df.empty:
        return None
    df = df.dropna(subset=["Close"])
    daily = [
        Bar(date=idx.strftime("%Y-%m-%d"), open=float(r["Open"]), high=float(r["High"]),
            low=float(r["Low"]), close=float(r["Close"]), volume=float(r.get("Volume", 0) or 0))
        for idx, r in df.iterrows()
    ]
    return PriceHistory(ticker=ticker, source="yfinance", daily=daily, weekly=to_weekly(daily))


# ── Binance (crypto fallback) ──────────────────────────────────────────────

async def _from_binance(ticker: str) -> PriceHistory | None:
    symbol = ticker.upper().replace("-USD", "USDT")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_BINANCE_KLINES,
                                    params={"symbol": symbol, "interval": "1d", "limit": 1000})
            resp.raise_for_status()
            rows = resp.json()
    except Exception as exc:
        logger.warning("Binance klines failed for %s: %s", ticker, exc)
        return None
    from datetime import datetime, timezone
    daily = [
        Bar(date=datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
            open=float(r[1]), high=float(r[2]), low=float(r[3]), close=float(r[4]),
            volume=float(r[5]))
        for r in rows
    ]
    if not daily:
        return None
    return PriceHistory(ticker=ticker, source="binance", daily=daily, weekly=to_weekly(daily))


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
