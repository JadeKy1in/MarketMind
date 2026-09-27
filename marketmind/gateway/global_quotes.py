"""Fallback daily bars: Eastmoney and Tencent (no API key), Twelve Data (free key).

docs/S3_DESIGN.md §7. Order in price_history: Yahoo first, then these.
- Eastmoney (push2his): HK, A-shares, continuous futures, FX, global indices.
  Kline fields are date, OPEN, CLOSE, HIGH, LOW, volume (close before high).
  It drops connections under bursts, so requests are serialised and spaced.
- Tencent (ifzq.gtimg.cn): HK and A-shares, forward-adjusted.
- Twelve Data (TWELVEDATA_API_KEY): last resort for every market. The free plan
  (verified 2026-09-28) covers US stocks/ETFs, FX and crypto only; Japanese and
  European stocks answer "available starting with the Grow plan", after which
  that market is skipped for the rest of the process. 8 requests/minute, so
  requests are serialised and spaced. The key goes in a header, never the URL.
Eastmoney and Tencent are unofficial endpoints. Any failure returns None and the
caller moves on.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, timedelta

import httpx

logger = logging.getLogger("marketmind.gateway.global_quotes")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
TIMEOUT_S = 20.0
EASTMONEY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EASTMONEY_UT = "fa5fd1943c7b386f172d6893dbfba10b"   # public token used by its own web pages
EASTMONEY_MIN_INTERVAL_S = 1.0
TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

TWELVEDATA_URL = "https://api.twelvedata.com/time_series"
TWELVEDATA_MIN_INTERVAL_S = 7.5     # free plan: 8 requests per minute

_em_lock = asyncio.Lock()
_em_last = 0.0
_td_lock = asyncio.Lock()
_td_last = 0.0
_td_plan_blocked: set[str] = set()  # market codes the key's plan does not cover

# Yahoo futures root -> Eastmoney continuous contract (verified 2026-09-28)
_EM_FUTURES = {
    "CL": "102.CL00Y", "NG": "102.NG00Y", "GC": "101.GC00Y", "SI": "101.SI00Y",
    "HG": "101.HG00Y", "ZC": "103.ZC00Y", "ZW": "103.ZW00Y", "ZS": "103.ZS00Y",
}
_EM_INDICES = {"^N225": "100.N225", "^GDAXI": "100.GDAXI", "^FTSE": "100.FTSE",
               "^HSI": "100.HSI", "^GSPC": "100.SPX", "^FCHI": "100.FCHI"}


def eastmoney_secid(ticker: str) -> str | None:
    t = ticker.strip().upper()
    if t.endswith(".HK"):
        code = t[:-3]
        return f"116.{code.zfill(5)}" if code.isdigit() else None
    if t.endswith(".SS"):
        return f"1.{t[:-3]}"
    if t.endswith(".SZ"):
        return f"0.{t[:-3]}"
    if t.endswith("=F"):
        return _EM_FUTURES.get(t[:-2])
    if t.endswith("=X"):
        pair = t[:-2]
        if len(pair) == 3:            # Yahoo "JPY=X" means USDJPY
            pair = "USD" + pair
        if len(pair) != 6:
            return None
        return f"133.{pair}" if pair == "USDCNH" else f"119.{pair}"
    return _EM_INDICES.get(t)


def tencent_code(ticker: str) -> str | None:
    t = ticker.strip().upper()
    if t.endswith(".HK") and t[:-3].isdigit():
        return "hk" + t[:-3].zfill(5)
    if t.endswith(".SS"):
        return "sh" + t[:-3]
    if t.endswith(".SZ"):
        return "sz" + t[:-3]
    return None


# Yahoo suffix -> ISO 10383 MIC for Twelve Data (JP/EU only; HK/CN use Eastmoney/Tencent)
_TD_MIC = {"T": "XJPX", "DE": "XETR", "PA": "XPAR", "AS": "XAMS", "L": "XLON",
           "SW": "XSWX", "MI": "XMIL", "MC": "XMAD", "CO": "XCSE"}


def twelvedata_symbol(ticker: str) -> tuple[str, str | None] | None:
    """(symbol, mic_code) for Twelve Data, or None when it has no equivalent.
    Futures and indices map to None: its spot commodities are not the contract."""
    t = ticker.strip().upper()
    if not t or t.startswith("^") or t.endswith("=F"):
        return None
    if t.endswith("=X"):
        pair = t[:-2]
        if len(pair) == 3:            # Yahoo "JPY=X" means USDJPY
            pair = "USD" + pair
        return (f"{pair[:3]}/{pair[3:]}", None) if len(pair) == 6 else None
    if t.endswith("-USD"):
        return (f"{t[:-4]}/USD", None)
    if "." in t:
        code, suffix = t.rsplit(".", 1)
        mic = _TD_MIC.get(suffix)
        return (code, mic) if mic else None
    return (t.replace("-", "."), None)   # BRK-B -> BRK.B


def _f(v) -> float:
    return float(str(v).replace(",", ""))


def parse_eastmoney(payload: dict):
    from marketmind.gateway.price_history import Bar
    lines = (((payload or {}).get("data") or {}).get("klines")) or []
    bars = []
    for line in lines:
        parts = str(line).split(",")
        try:
            d, o, c, h, low = parts[0], _f(parts[1]), _f(parts[2]), _f(parts[3]), _f(parts[4])
            vol = _f(parts[5]) if len(parts) > 5 and parts[5] not in ("", "-") else 0.0
        except (IndexError, ValueError):
            continue
        if min(o, c, h, low) <= 0:
            continue
        bars.append(Bar(date=d, open=o, high=h, low=low, close=c, volume=vol))
    bars.sort(key=lambda b: b.date)
    return bars


def parse_tencent(payload: dict, code: str):
    from marketmind.gateway.price_history import Bar
    node = (((payload or {}).get("data") or {}).get(code)) or {}
    rows = node.get("qfqday") or node.get("day") or []
    bars = []
    for r in rows:
        try:
            d, o, c, h, low = r[0], _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4])
            vol = _f(r[5]) if len(r) > 5 else 0.0
        except (IndexError, TypeError, ValueError):
            continue
        if min(o, c, h, low) <= 0:
            continue
        bars.append(Bar(date=d, open=o, high=h, low=low, close=c, volume=vol))
    bars.sort(key=lambda b: b.date)
    return bars


def parse_twelvedata(payload: dict):
    from marketmind.gateway.price_history import Bar
    rows = (payload or {}).get("values") or []
    bars = []
    for r in rows:
        try:
            d = str(r["datetime"])[:10]
            o, h, low, c = _f(r["open"]), _f(r["high"]), _f(r["low"]), _f(r["close"])
            vol = _f(r["volume"]) if r.get("volume") not in (None, "") else 0.0
        except (KeyError, TypeError, ValueError):
            continue
        if min(o, c, h, low) <= 0:
            continue
        bars.append(Bar(date=d, open=o, high=h, low=low, close=c, volume=vol))
    bars.sort(key=lambda b: b.date)
    return bars


async def _em_get(client: httpx.AsyncClient, params: dict) -> httpx.Response:
    """Serialised and spaced: Eastmoney resets connections under bursts."""
    global _em_last
    async with _em_lock:
        wait = EASTMONEY_MIN_INTERVAL_S - (time.monotonic() - _em_last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await client.get(EASTMONEY_URL, params=params)
        finally:
            _em_last = time.monotonic()


async def from_eastmoney(ticker: str, years: int = 5):
    from marketmind.gateway.price_history import PriceHistory, to_weekly
    secid = eastmoney_secid(ticker)
    if secid is None:
        return None
    start = (date.today() - timedelta(days=int(365.25 * years))).strftime("%Y%m%d")
    params = {"secid": secid, "ut": EASTMONEY_UT, "klt": 101, "fqt": 1, "beg": start,
              "end": "20500101", "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, headers=HEADERS) as client:
            resp = await _em_get(client, params)
        if resp.status_code != 200:
            logger.warning("Eastmoney HTTP %d for %s", resp.status_code, ticker)
            return None
        bars = parse_eastmoney(resp.json())
    except Exception as e:
        logger.warning("Eastmoney failed for %s: %s", ticker, e)
        return None
    if not bars:
        logger.warning("Eastmoney returned no bars for %s (%s)", ticker, secid)
        return None
    return PriceHistory(ticker=ticker, source="eastmoney", daily=bars, weekly=to_weekly(bars))


async def from_tencent(ticker: str, years: int = 5):
    from marketmind.gateway.price_history import PriceHistory, to_weekly
    code = tencent_code(ticker)
    if code is None:
        return None
    start = (date.today() - timedelta(days=int(365.25 * years))).isoformat()
    params = {"param": f"{code},day,{start},2050-12-31,2000,qfq"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, headers=HEADERS) as client:
            resp = await client.get(TENCENT_URL, params=params)
        if resp.status_code != 200:
            logger.warning("Tencent HTTP %d for %s", resp.status_code, ticker)
            return None
        bars = parse_tencent(resp.json(), code)
    except Exception as e:
        logger.warning("Tencent failed for %s: %s", ticker, e)
        return None
    if not bars:
        logger.warning("Tencent returned no bars for %s (%s)", ticker, code)
        return None
    return PriceHistory(ticker=ticker, source="tencent", daily=bars, weekly=to_weekly(bars))


async def _td_get(client: httpx.AsyncClient, params: dict, key: str) -> httpx.Response:
    """Serialised and spaced to stay under the free plan's per-minute limit."""
    global _td_last
    async with _td_lock:
        wait = TWELVEDATA_MIN_INTERVAL_S - (time.monotonic() - _td_last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await client.get(TWELVEDATA_URL, params=params,
                                    headers={"Authorization": f"apikey {key}"})
        finally:
            _td_last = time.monotonic()


async def from_twelvedata(ticker: str, years: int = 5):
    from marketmind.gateway.price_history import PriceHistory, to_weekly
    from marketmind.markets import market_for
    key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    sym = twelvedata_symbol(ticker)
    market = market_for(ticker).code
    if not key or sym is None or market in _td_plan_blocked:
        return None
    symbol, mic = sym
    start = (date.today() - timedelta(days=int(365.25 * years))).isoformat()
    params = {"symbol": symbol, "interval": "1day", "start_date": start,
              "outputsize": 5000, "adjust": "all"}
    if mic:
        params["mic_code"] = mic
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await _td_get(client, params, key)
        payload = resp.json()
    except Exception as e:
        logger.warning("Twelve Data failed for %s: %s", ticker, e)
        return None
    if payload.get("status") != "ok":
        msg = str(payload.get("message") or "")
        if "available starting with" in msg:
            _td_plan_blocked.add(market)
            logger.info("Twelve Data plan does not cover market %s; skipping it", market)
        else:
            logger.warning("Twelve Data error for %s: %s %s", ticker,
                           payload.get("code", resp.status_code), msg[:120])
        return None
    bars = parse_twelvedata(payload)
    if not bars:
        logger.warning("Twelve Data returned no bars for %s", ticker)
        return None
    return PriceHistory(ticker=ticker, source="twelvedata", daily=bars, weekly=to_weekly(bars))
