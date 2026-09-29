"""Keyless crypto signal data: on-chain valuation, crypto sentiment, spot BTC ETF flows.

Sources (all verified live from the owner's network on 2026-09-29; no API keys):

- Coin Metrics Community API v4, daily asset metrics
  https://community-api.coinmetrics.io/v4/timeseries/asset-metrics
  ?assets=btc&metrics=CapMVRVCur,CapMrktCurUSD&frequency=1d&page_size=10000&paging_from=start
  -> {"data": [{"asset", "time": "2010-07-18T00:00:00.000000000Z", "CapMVRVCur": "146.04",
  "CapMrktCurUSD": "295959.15"}, ...], "next_page_url"?}. Values are strings. BTC history
  starts 2010-07-18 (5,917 rows), ETH 2015-08-08 (4,070 rows); the latest row is the
  previous UTC day. Free metrics verified: CapMVRVCur, CapMrktCurUSD, PriceUSD, SplyCur.
  NOT free (HTTP 403 "not available with supplied credentials"): CapRealUSD, CapMVRVFF,
  NVTAdj. Realized cap is therefore derived here as CapMrktCurUSD / CapMVRVCur (exact
  by definition of MVRV = market cap / realized cap), not fetched.
  Rate limit: the community docs state 10 requests per 6 seconds per IP; requests are
  spaced CM_MIN_INTERVAL_S apart and an HTTP 429 is retried once after Retry-After /
  x-ratelimit-reset (capped). Docs: https://docs.coinmetrics.io/api/v4 ,
  https://gitbook-docs.coinmetrics.io/packages/coin-metrics-community-data
- alternative.me Crypto Fear & Greed Index, https://api.alternative.me/fng/?limit=0&format=json
  -> {"data": [{"value": "73", "value_classification": "Greed", "timestamp": "1790640000"},
  ...], "metadata": {"error": null}}, newest first, one value per UTC day since
  2018-02-01 (3,159 rows). Classes seen in the data: Extreme Fear 0-25, Fear 26-46,
  Neutral 47-54, Greed 55-75, Extreme Greed 76-100. Docs:
  https://alternative.me/crypto/fear-and-greed-index/ (API section).
- TFTC "US Spot Bitcoin ETF Daily Flows", https://www.tftc.io/bitcoin-etf-flows/data.json
  -> {"license": ".../by/4.0/", "attribution": "TFTC — tftc.io/bitcoin-etf-flows",
  "updatedThrough": "2026-09-28", "days": [{"date", "netFlowUsd", "totalNetAssetsUsd",
  "btcCloseUsd", "perEtfUsd": {...}}, ...]} since 2024-01-11 (US trading days).
  Licence CC BY 4.0: every place that shows these numbers must carry ETF_ATTRIBUTION.

Every series is cached once per UTC day under <MARKETMIND_DATA_DIR>/crypto_signals/
(<name>.json = {"fetched_on", "data"}). If today's fetch fails, the last cached copy is
returned with origin "stale-cache" and its own dates, so callers can judge staleness;
with no cache at all CryptoDataUnavailable is raised. Nothing is ever interpolated.
"""
from __future__ import annotations

import asyncio
import bisect
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import httpx

logger = logging.getLogger("marketmind.gateway.crypto_signals")

CM_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
CM_METRICS = ("CapMVRVCur", "CapMrktCurUSD")
CM_PAGE_SIZE = 10000
CM_MAX_PAGES = 5
CM_MIN_INTERVAL_S = 0.6            # 10 requests / 6 s (community rate limit)
RATE_LIMIT_WAIT_CAP_S = 30.0
FNG_URL = "https://api.alternative.me/fng/"
ETF_URL = "https://www.tftc.io/bitcoin-etf-flows/data.json"
ETF_PAGE = "https://www.tftc.io/bitcoin-etf-flows"
ETF_ATTRIBUTION = "TFTC — tftc.io/bitcoin-etf-flows (CC BY 4.0)"
HTTP_TIMEOUT_S = 30.0
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketMind research)",
           "Accept": "application/json"}
Z_MIN_DAYS = 365                   # MVRV Z needs a year of market caps for sigma

_TRANSPORT: httpx.AsyncBaseTransport | None = None      # tests inject httpx.MockTransport
_last_cm_request = 0.0


class CryptoDataUnavailable(RuntimeError):
    """A source failed and no cached copy exists."""


@dataclass(frozen=True)
class MvrvPoint:
    date: str
    mvrv: float
    market_cap: float

    @property
    def realized_cap(self) -> float:
        return self.market_cap / self.mvrv


@dataclass(frozen=True)
class FngPoint:
    date: str
    value: int
    label: str


@dataclass(frozen=True)
class EtfFlowDay:
    date: str
    net_flow_usd: float
    total_net_assets_usd: float | None


@dataclass(frozen=True)
class Series:
    name: str
    points: tuple
    fetched_on: str                 # UTC date of the HTTP fetch
    origin: str                     # live | cache | stale-cache
    meta: dict | None = None


# ── cache ───────────────────────────────────────────────────────────────────

def cache_dir(data_dir: str | Path | None = None) -> Path:
    return Path(data_dir or os.getenv("MARKETMIND_DATA_DIR", "data")) / "crypto_signals"


def _read_cache(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.warning("crypto_signals cache %s unreadable: %s", path, e)
        return None


def _write_cache(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("crypto_signals cache %s not written: %s", path, e)


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _cached(name: str, today: str | None, data_dir, fetch_raw, parse) -> Series:
    """Once per UTC day per series: cache hit, live fetch, or labelled stale cache."""
    today = today or _utc_today()
    path = cache_dir(data_dir) / f"{name}.json"
    cached = _read_cache(path)
    if cached and cached.get("fetched_on") == today:
        points, meta = parse(cached["data"])
        return Series(name, tuple(points), today, "cache", meta)
    try:
        raw = await fetch_raw()
        points, meta = parse(raw)
        if not points:
            raise ValueError("no usable rows")
    except Exception as e:
        if cached:
            logger.warning("%s fetch failed (%s: %s); using cache from %s", name,
                           type(e).__name__, e, cached.get("fetched_on"))
            points, meta = parse(cached["data"])
            return Series(name, tuple(points), str(cached.get("fetched_on")), "stale-cache", meta)
        raise CryptoDataUnavailable(f"{name}: {type(e).__name__}: {e}") from e
    _write_cache(path, {"fetched_on": today, "data": raw})
    return Series(name, tuple(points), today, "live", meta)


# ── HTTP ────────────────────────────────────────────────────────────────────

def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, headers=HEADERS, follow_redirects=True,
                             transport=_TRANSPORT)


def _retry_after(resp: httpx.Response) -> float:
    for h in ("Retry-After", "x-ratelimit-reset"):
        try:
            return min(RATE_LIMIT_WAIT_CAP_S, max(0.0, float(resp.headers[h])))
        except (KeyError, ValueError):
            continue
    return CM_MIN_INTERVAL_S * 10


async def _cm_get(client: httpx.AsyncClient, url: str, params: dict | None) -> dict:
    """One Coin Metrics request, spaced for the community limit; one retry on 429."""
    global _last_cm_request
    for attempt in (1, 2):
        wait = _last_cm_request + CM_MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_cm_request = time.monotonic()
        resp = await client.get(url, params=params)
        if resp.status_code == 429 and attempt == 1:
            delay = _retry_after(resp)
            logger.warning("Coin Metrics HTTP 429; retrying once in %.1fs", delay)
            await asyncio.sleep(delay)
            continue
        if resp.status_code >= 400:
            try:
                msg = resp.json()["error"]["message"]
            except Exception:
                msg = resp.text[:200]
            raise httpx.HTTPStatusError(f"Coin Metrics HTTP {resp.status_code}: {msg}",
                                        request=resp.request, response=resp)
        return resp.json()
    raise RuntimeError("unreachable")


async def _fetch_cm(asset: str) -> list[dict]:
    rows: list[dict] = []
    params = {"assets": asset, "metrics": ",".join(CM_METRICS), "frequency": "1d",
              "page_size": CM_PAGE_SIZE, "paging_from": "start"}
    url: str | None = CM_URL
    async with _client() as c:
        for _ in range(CM_MAX_PAGES):
            payload = await _cm_get(c, url, params)
            rows.extend(payload.get("data") or [])
            url, params = payload.get("next_page_url"), None
            if not url:
                break
        else:
            logger.warning("Coin Metrics %s: stopped after %d pages", asset, CM_MAX_PAGES)
    return rows


async def _fetch_json(url: str, params: dict | None = None) -> dict:
    async with _client() as c:
        resp = await c.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


# ── parsers (pure) ──────────────────────────────────────────────────────────

def _pos(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def parse_mvrv(rows) -> tuple[list[MvrvPoint], None]:
    out: dict[str, MvrvPoint] = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d, mv, mc = str(r.get("time", ""))[:10], _pos(r.get("CapMVRVCur")), _pos(r.get("CapMrktCurUSD"))
        if len(d) == 10 and mv is not None and mc is not None:
            out[d] = MvrvPoint(d, mv, mc)
    return [out[d] for d in sorted(out)], None


def parse_fng(payload) -> tuple[list[FngPoint], None]:
    if not isinstance(payload, dict):
        raise ValueError("fear & greed payload is not an object")
    err = (payload.get("metadata") or {}).get("error")
    if err:
        raise ValueError(f"alternative.me error: {err}")
    out: dict[str, FngPoint] = {}
    for r in payload.get("data") or []:
        try:
            d = datetime.fromtimestamp(int(r["timestamp"]), timezone.utc).date().isoformat()
            v = int(r["value"])
        except (KeyError, TypeError, ValueError, OSError):
            continue
        if 0 <= v <= 100:
            out[d] = FngPoint(d, v, str(r.get("value_classification") or ""))
    return [out[d] for d in sorted(out)], None


def parse_etf(payload) -> tuple[list[EtfFlowDay], dict]:
    if not isinstance(payload, dict):
        raise ValueError("ETF flow payload is not an object")
    out: dict[str, EtfFlowDay] = {}
    for r in payload.get("days") or []:
        try:
            d, flow = str(r["date"])[:10], float(r["netFlowUsd"])
        except (KeyError, TypeError, ValueError):
            continue
        if len(d) == 10 and math.isfinite(flow):
            tna = r.get("totalNetAssetsUsd")
            out[d] = EtfFlowDay(d, flow, float(tna) if isinstance(tna, (int, float)) else None)
    meta = {"updated_through": payload.get("updatedThrough"), "license": payload.get("license"),
            "attribution": ETF_ATTRIBUTION}
    return [out[d] for d in sorted(out)], meta


# ── public API ──────────────────────────────────────────────────────────────

async def mvrv_history(asset: str, *, today: str | None = None,
                       data_dir: str | Path | None = None) -> Series:
    """Daily CapMVRVCur + CapMrktCurUSD for 'btc' / 'eth' (full history, ascending)."""
    asset = asset.lower()
    return await _cached(f"coinmetrics_{asset}", today, data_dir,
                         lambda: _fetch_cm(asset), parse_mvrv)


async def fear_greed_history(*, today: str | None = None,
                             data_dir: str | Path | None = None) -> Series:
    return await _cached("fear_greed", today, data_dir,
                         lambda: _fetch_json(FNG_URL, {"limit": 0, "format": "json"}), parse_fng)


async def etf_flow_history(*, today: str | None = None,
                           data_dir: str | Path | None = None) -> Series:
    return await _cached("btc_etf_flows", today, data_dir, lambda: _fetch_json(ETF_URL), parse_etf)


# ── derived statistics (pure, no look-ahead) ────────────────────────────────

def expanding_percentiles(values: Sequence[float]) -> list[float]:
    """For each day, % of days up to and including it whose value is <= that day's."""
    seen: list[float] = []
    out = []
    for v in values:
        bisect.insort(seen, v)
        out.append(100.0 * bisect.bisect_right(seen, v) / len(seen))
    return out


def expanding_mvrv_z(points: Sequence[MvrvPoint], min_days: int = Z_MIN_DAYS) -> list[float | None]:
    """MVRV Z = (market cap - realized cap) / sigma(market cap), sigma over all days up to
    and including t (population std; Mahmudov & Puell 2018 as used by Grobys et al. 2026).
    None before `min_days` of history."""
    n, s, ss, out = 0, 0.0, 0.0, []
    for p in points:
        n += 1
        s += p.market_cap
        ss += p.market_cap * p.market_cap
        var = ss / n - (s / n) ** 2
        sd = math.sqrt(var) if var > 0 else 0.0
        out.append((p.market_cap - p.realized_cap) / sd if n >= min_days and sd > 0 else None)
    return out


def point_on_or_before(points: Sequence, date: str):
    """Latest point dated <= `date` (points ascending), else None."""
    dates = [p.date for p in points]
    i = bisect.bisect_right(dates, date)
    return points[i - 1] if i else None
