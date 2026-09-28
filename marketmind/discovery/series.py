"""Registry of cold official series for the data-first anomaly scan (docs/S10_DESIGN.md §1).

Each `Series` fetches its own history as `[(YYYY-MM-DD, float)]` (oldest first,
about a year or more when the source keeps it) and names its tradable proxies
with an *implied direction when the series rises* (+1 = the proxy should rise,
-1 = fall). These directions are documented priors, not conclusions: the ledger
tests them per series (S10 risks). A fetch that fails raises; the runner lists
the series as unavailable with the reason, never an invented number.

Fetch code reuses the existing clients and parsers:
- FRED: gateway/fred_client (base URL, key lookup, key redaction) and the
  observation parser in gateway/fragility_inputs (FRED_KEY / FRED_API_KEY).
- NY Fed SOMA / standing repo: shadow_feeds/fed_liquidity parsers.
- Treasury auctions (FiscalData), DefiLlama stablecoins: evidence/sources parsers.
- MOF JGB, ECB reference rates: shadow_feeds/fx_rates parsers and URLs.
- Cboe VIX family and SKEW: shadow_feeds/volatility.fetch_histories.
- OKX funding / open interest: public endpoints (history variants, verified 2026-09-28).
- EIA weekly petroleum stocks: API v2 `seriesid` route (EIA_KEY / EIA_API_KEY).

Out of this first version: per-stock series (FINRA short volume, Finnhub insiders),
auction tails (FiscalData has no when-issued yield), anything needing a key we lack.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger("marketmind.discovery.series")

HTTP_TIMEOUT_S = 45.0
USER_AGENT = "Mozilla/5.0 (MarketMind research)"
B = 1e9

Obs = list[tuple[str, float]]


# ── registry types ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Series:
    id: str                                   # "<source>:<code>", e.g. "fred:WRESBAL"
    title: str
    frequency: str                            # daily | weekly | monthly
    unit: str
    source: str                               # human-readable source and endpoint
    fetch: Callable[["FetchContext"], Awaitable[Obs]] = field(compare=False, repr=False)
    proxies: tuple[tuple[str, int], ...] = ()  # (ticker, implied direction when the series rises)
    keywords: tuple[str, ...] = ()            # news-coverage keywords (case-insensitive)
    prior: str = ""                           # why the implied directions were chosen
    window: int | None = None                 # override of the frequency's change window
    lookback_days: int | None = None          # override of the 1-year stats lookback
    release_lag_days: int | None = None       # override of RELEASE_LAG_DAYS (see below)


# Days after the observation date whose close still predates publication, so the
# "already priced in" move is measured from the last close before the market
# could see the number. Daily FRED/MOF/ECB/Cboe data and Treasury auction results
# are out by the next session; H.4.1 / SOMA (Wednesday data) come Thursday after
# the close; EIA petroleum stocks (as of Friday) come the next Wednesday morning;
# STLFSI4 (week ending Friday) comes the next Thursday.
RELEASE_LAG_DAYS = {"daily": 0, "weekly": 1, "monthly": 0}
RELEASE_LAG_OVERRIDES = {"fred:STLFSI4": 5, "eia:WCESTUS1": 4, "eia:WGTSTUS1": 4, "eia:WDISTUS1": 4}


def pricing_base_date(s: "Series", obs_date: str) -> str:
    from datetime import date as _date, timedelta as _td
    lag = s.release_lag_days
    if lag is None:
        lag = RELEASE_LAG_OVERRIDES.get(s.id, RELEASE_LAG_DAYS.get(s.frequency, 0))
    return (_date.fromisoformat(obs_date) + _td(days=lag)).isoformat()


class FetchContext:
    """One per run: shared HTTP client plus per-key memo, so series that come from
    the same payload (SOMA buckets, JGB tenors, ECB currencies...) fetch it once."""

    def __init__(self, today: date, client: httpx.AsyncClient | None = None):
        self.today = today
        self._client = client
        self._own_client = client is None
        self._memo: dict[str, asyncio.Future] = {}

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=True,
                                             headers={"User-Agent": USER_AGENT})
        return self._client

    async def aclose(self) -> None:
        if self._own_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def memo(self, key: str, factory: Callable[[], Awaitable]):
        """Run `factory()` once per key; later callers share the result or the exception."""
        fut = self._memo.get(key)
        if fut is None:
            fut = asyncio.ensure_future(factory())
            self._memo[key] = fut
        return await asyncio.shield(fut)

    async def get(self, url: str, params: dict | None = None,
                  headers: dict | None = None) -> httpx.Response:
        resp = await self.client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp

    def since(self, days: int) -> str:
        return (self.today - timedelta(days=days)).isoformat()


def _clean(rows) -> Obs:
    """Sorted, one value per date (last wins), finite floats only."""
    out: dict[str, float] = {}
    for d, v in rows:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f and f not in (float("inf"), float("-inf")):
            out[str(d)[:10]] = f
    return sorted(out.items())


# ── FRED ────────────────────────────────────────────────────────────────────

FRED_HISTORY_DAYS = 800


async def fred_history(ctx: FetchContext, series_id: str, days: int = FRED_HISTORY_DAYS) -> Obs:
    from marketmind.gateway.fragility_inputs import _parse_fred_observations
    from marketmind.gateway.fred_client import _FRED_BASE, _get_fred_key, _redact

    async def load() -> Obs:
        key = _get_fred_key()
        if not key:
            raise RuntimeError("FRED key not configured (FRED_KEY / FRED_API_KEY)")
        try:
            resp = await ctx.get(_FRED_BASE, params={
                "series_id": series_id, "api_key": key, "file_type": "json",
                "observation_start": ctx.since(days), "sort_order": "asc"})
            rows = _parse_fred_observations(resp.json())
        except Exception as e:           # the URL carries the key: never let it escape
            raise RuntimeError(f"FRED {series_id}: {_redact(str(e))}") from None
        return _clean(rows)
    return await ctx.memo(f"fred:{series_id}", load)


def _fred(series_id: str):
    async def fetch(ctx: FetchContext) -> Obs:
        return await fred_history(ctx, series_id)
    return fetch


async def _sofr_minus_iorb(ctx: FetchContext) -> Obs:
    sofr, iorb = await asyncio.gather(fred_history(ctx, "SOFR"), fred_history(ctx, "IORB"))
    ib = dict(iorb)
    return [(d, round((v - ib[d]) * 100, 4)) for d, v in sofr if d in ib]


# ── NY Fed ──────────────────────────────────────────────────────────────────

NYFED_REPO_SEARCH = "https://markets.newyorkfed.org/api/rp/results/search.json"


async def _soma_rows(ctx: FetchContext) -> list[dict]:
    from marketmind.shadow_feeds.fed_liquidity import SOMA_URL, soma_totals

    async def load():
        return soma_totals((await ctx.get(SOMA_URL, headers={"Accept": "application/json"})).json())
    return await ctx.memo("nyfed:soma", load)


def _soma(bucket: str):
    async def fetch(ctx: FetchContext) -> Obs:
        return _clean((r["date"], r[bucket] / B) for r in await _soma_rows(ctx))
    return fetch


async def _standing_repo(ctx: FetchContext) -> Obs:
    from marketmind.shadow_feeds.fed_liquidity import daily_operations
    resp = await ctx.get(NYFED_REPO_SEARCH, params={
        "startDate": ctx.since(400), "endDate": ctx.today.isoformat(), "operationTypes": "Repo"},
        headers={"Accept": "application/json"})
    return _clean((r["date"], r["accepted"] / B) for r in daily_operations(resp.json(), "Repo"))


# ── Treasury auctions (FiscalData) ──────────────────────────────────────────

AUCTION_HISTORY_DAYS = 3 * 365 + 30


async def _auctions(ctx: FetchContext) -> list[dict]:
    from marketmind.evidence.sources import AUCTIONS_URL, parse_auctions

    async def load():
        resp = await ctx.get(AUCTIONS_URL, params={
            "sort": "-auction_date", "page[size]": "10000",
            "filter": (f"security_type:in:(Note,Bond),auction_date:gte:{ctx.since(AUCTION_HISTORY_DAYS)},"
                       f"auction_date:lte:{ctx.today.isoformat()}")})
        return parse_auctions(resp.json())
    return await ctx.memo("fiscaldata:auctions", load)


def _bid_to_cover(term: str):
    async def fetch(ctx: FetchContext) -> Obs:
        return _clean((a["date"], a["bid_to_cover"]) for a in await _auctions(ctx)
                      if a["type"] in ("Note", "Bond") and a["term"] == term)
    return fetch


# ── MOF JGB, ECB ────────────────────────────────────────────────────────────

async def _jgb_rows(ctx: FetchContext) -> list[tuple[str, dict[str, float]]]:
    from marketmind.shadow_feeds.fx_rates import JGB_HIST_URL, JGB_URL, parse_jgb_csv

    async def load():
        hist, cur = await asyncio.gather(ctx.get(JGB_HIST_URL), ctx.get(JGB_URL),
                                         return_exceptions=True)
        if isinstance(hist, Exception):
            raise hist                   # the current-month file alone is not a history
        rows: dict[str, dict[str, float]] = dict(parse_jgb_csv(hist.content))
        if not isinstance(cur, Exception):
            rows.update(parse_jgb_csv(cur.content))
        cutoff = ctx.since(800)
        return sorted((d, v) for d, v in rows.items() if d >= cutoff)
    return await ctx.memo("mof:jgb", load)


def _jgb(tenor: str):
    async def fetch(ctx: FetchContext) -> Obs:
        return _clean((d, v[tenor]) for d, v in await _jgb_rows(ctx) if tenor in v)
    return fetch


ECB_HIST_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD+JPY+GBP+CNY+CHF.EUR.SP00.A"


async def _ecb_rows(ctx: FetchContext) -> dict[str, Obs]:
    from marketmind.shadow_feeds.fx_rates import parse_ecb_csv

    async def load():
        resp = await ctx.get(ECB_HIST_URL, params={"format": "csvdata", "startPeriod": ctx.since(800)})
        return parse_ecb_csv(resp.text)
    return await ctx.memo("ecb:exr", load)


def _ecb(ccy: str):
    async def fetch(ctx: FetchContext) -> Obs:
        return _clean((await _ecb_rows(ctx)).get(ccy) or [])
    return fetch


# ── Cboe ────────────────────────────────────────────────────────────────────

async def _cboe(ctx: FetchContext) -> dict[str, Obs]:
    from marketmind.shadow_feeds.volatility import fetch_histories
    return await ctx.memo("cboe", lambda: fetch_histories(("VIX", "VIX9D", "VIX3M", "SKEW")))


def _cboe_ratio(num: str, den: str):
    async def fetch(ctx: FetchContext) -> Obs:
        h = await _cboe(ctx)
        d = dict(h[den])
        cutoff = ctx.since(800)
        return _clean((day, v / d[day]) for day, v in h[num] if day >= cutoff and d.get(day))
    return fetch


async def _cboe_skew(ctx: FetchContext) -> Obs:
    cutoff = ctx.since(800)
    return _clean((d, v) for d, v in (await _cboe(ctx))["SKEW"] if d >= cutoff)


# ── OKX (history kept by OKX: funding ~3 months, open interest ~180 days) ───

OKX_FUNDING_HISTORY = "https://www.okx.com/api/v5/public/funding-rate-history"
OKX_OI_HISTORY = "https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume"
OKX_FUNDING_PAGES = 4


def _okx_data(payload) -> list:
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise ValueError(f"OKX error {payload.get('code') if isinstance(payload, dict) else payload!r}")
    return payload.get("data") or []


def _utc_day(ms) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def daily_mean_funding(rows: list[dict]) -> Obs:
    """OKX funding-rate-history rows -> [(UTC day, mean funding % per period)]."""
    by_day: dict[str, list[float]] = {}
    for r in rows:
        try:
            rate = float(r.get("realizedRate") or r["fundingRate"])
            by_day.setdefault(_utc_day(r["fundingTime"]), []).append(rate * 100)
        except (KeyError, TypeError, ValueError):
            continue
    return sorted((d, sum(v) / len(v)) for d, v in by_day.items())


def _okx_funding(coin: str):
    async def fetch(ctx: FetchContext) -> Obs:
        rows: list[dict] = []
        after = None
        for _ in range(OKX_FUNDING_PAGES):
            params = {"instId": f"{coin}-USDT-SWAP", "limit": "100"}
            if after:
                params["after"] = after
            page = _okx_data((await ctx.get(OKX_FUNDING_HISTORY, params=params)).json())
            if not page:
                break
            rows += page
            after = min(str(r["fundingTime"]) for r in page)
        # today's UTC day is still accruing periods: keep complete days only
        return [(d, v) for d, v in daily_mean_funding(rows) if d < ctx.today.isoformat()]
    return fetch


def _okx_oi(coin: str):
    async def fetch(ctx: FetchContext) -> Obs:
        data = _okx_data((await ctx.get(OKX_OI_HISTORY, params={"ccy": coin, "period": "1D"})).json())
        return _clean((_utc_day(r[0]), float(r[1]) / B) for r in data if len(r) >= 2)
    return fetch


# ── DefiLlama ───────────────────────────────────────────────────────────────

async def _stablecoins(ctx: FetchContext) -> Obs:
    from marketmind.evidence.sources import STABLE_URL, parse_stablecoin_supply
    rows = parse_stablecoin_supply((await ctx.get(STABLE_URL)).json())
    cutoff = ctx.since(800)
    return _clean((d, v / B) for d, v in rows if d >= cutoff)


# ── EIA ─────────────────────────────────────────────────────────────────────

EIA_SERIESID = "https://api.eia.gov/v2/seriesid/{sid}"


def parse_eia_series(payload: dict) -> Obs:
    rows = ((payload or {}).get("response") or {}).get("data") or []
    return _clean((r.get("period"), r.get("value")) for r in rows if r.get("period"))


def _eia(sid: str):
    async def fetch(ctx: FetchContext) -> Obs:
        from marketmind.gateway.fred_client import _redact
        from marketmind.gateway.macro_data import _get_eia_key
        key = _get_eia_key()
        if not key:
            raise RuntimeError("EIA key not configured (EIA_KEY / EIA_API_KEY)")
        try:
            resp = await ctx.get(EIA_SERIESID.format(sid=sid),
                                 params={"api_key": key, "start": ctx.since(800), "length": "500"})
            return parse_eia_series(resp.json())
        except Exception as e:
            raise RuntimeError(f"EIA {sid}: {_redact(str(e))}") from None
    return fetch


# ── registry ────────────────────────────────────────────────────────────────

LIQ_UP = "more reserves / liquidity -> risk assets up (prior)"
DRAIN = "cash drained from the banking system -> risk assets down (prior)"
STRESS = "wider spreads / more stress -> risk assets down, duration up (prior)"

REGISTRY: tuple[Series, ...] = (
    # FRED — liquidity plumbing
    Series("fred:WRESBAL", "Reserve balances with Federal Reserve Banks", "weekly", "M USD",
           "FRED WRESBAL", _fred("WRESBAL"), (("SPY", 1), ("QQQ", 1), ("BTC-USD", 1)),
           ("bank reserves", "reserve balances", "reserves at the fed", "银行准备金", "准备金余额"), LIQ_UP),
    Series("fred:WTREGEN", "Treasury General Account (TGA)", "weekly", "M USD",
           "FRED WTREGEN", _fred("WTREGEN"), (("SPY", -1), ("BTC-USD", -1)),
           ("treasury general account", "TGA", "财政部一般账户"), DRAIN),
    Series("fred:RRPONTSYD", "Overnight reverse repo (ON RRP) usage", "daily", "B USD",
           "FRED RRPONTSYD", _fred("RRPONTSYD"), (("SPY", -1), ("IWM", -1)),
           ("reverse repo", "ON RRP", "RRP facility", "逆回购"), "cash parked at the Fed -> risk assets down (prior)"),
    Series("fred:SOFR_IORB", "SOFR minus IORB", "daily", "bp",
           "FRED SOFR - FRED IORB", _sofr_minus_iorb, (("KRE", -1), ("SPY", -1)),
           ("SOFR", "repo rate", "funding stress", "IORB", "回购利率"),
           "repo trading above IORB = reserve scarcity -> banks and risk assets down (prior)"),
    # FRED — credit and stress
    Series("fred:BAMLH0A0HYM2", "ICE BofA US high-yield OAS", "daily", "%",
           "FRED BAMLH0A0HYM2", _fred("BAMLH0A0HYM2"), (("HYG", -1), ("SPY", -1)),
           ("high yield spread", "high-yield spread", "junk bond spread", "credit spreads", "高收益债利差"), STRESS),
    Series("fred:BAMLC0A4CBBB", "ICE BofA US BBB corporate OAS", "daily", "%",
           "FRED BAMLC0A4CBBB", _fred("BAMLC0A4CBBB"), (("LQD", -1), ("SPY", -1)),
           ("BBB spread", "investment-grade spread", "investment grade spread", "投资级利差"), STRESS),
    Series("fred:BAMLH0A3HYC", "ICE BofA US CCC & lower OAS", "daily", "%",
           "FRED BAMLH0A3HYC", _fred("BAMLH0A3HYC"), (("HYG", -1), ("IWM", -1)),
           ("CCC spread", "distressed debt", "CCC-rated", "垃圾债"), STRESS),
    Series("fred:STLFSI4", "St. Louis Fed Financial Stress Index", "weekly", "index",
           "FRED STLFSI4", _fred("STLFSI4"), (("SPY", -1), ("TLT", 1)),
           ("financial stress index", "STLFSI", "金融压力指数"), STRESS),
    Series("fred:DTWEXBGS", "Nominal broad US dollar index", "daily", "index",
           "FRED DTWEXBGS", _fred("DTWEXBGS"), (("UUP", 1), ("GLD", -1), ("EEM", -1)),
           ("broad dollar", "trade-weighted dollar", "dollar index", "美元指数"),
           "stronger dollar -> gold and EM down (prior)"),
    # NY Fed
    Series("nyfed:SOMA_TOTAL", "SOMA holdings, total", "weekly", "B USD",
           "NY Fed soma/summary.json total", _soma("total"), (("TLT", 1), ("SPY", 1)),
           ("Fed balance sheet", "quantitative tightening", "SOMA", "balance sheet runoff", "缩表", "扩表"),
           "Fed buying securities adds duration demand and liquidity (prior)"),
    Series("nyfed:SOMA_BILLS", "SOMA holdings, Treasury bills", "weekly", "B USD",
           "NY Fed soma/summary.json bills", _soma("bills"), (("SPY", 1), ("BTC-USD", 1)),
           ("reserve management purchases", "bill purchases", "T-bill purchases", "购买短债"), LIQ_UP),
    Series("nyfed:SOMA_MBS", "SOMA holdings, agency MBS (incl. CMBS)", "weekly", "B USD",
           "NY Fed soma/summary.json mbs+cmbs", _soma("mbs"), (("MBB", 1), ("XHB", 1)),
           ("MBS runoff", "mortgage-backed securities", "Fed MBS", "抵押贷款支持证券"),
           "Fed MBS holdings up = mortgage spread support (prior)"),
    Series("nyfed:STANDING_REPO", "Fed standing repo operations, accepted", "daily", "B USD",
           "NY Fed rp/results/search.json (Repo)", _standing_repo, (("KRE", -1), ("SPY", -1)),
           ("standing repo", "repo facility", "SRF", "常备回购"),
           "dealers tapping the Fed's repo backstop = funding stress (prior)"),
    # Treasury auctions: bid-to-cover per auction, compared auction to auction over 3 years
    Series("treasury:BTC_2Y", "2-year note auction bid-to-cover", "monthly", "ratio",
           "FiscalData auctions_query", _bid_to_cover("2-Year"), (("SHY", 1),),
           ("2-year note auction", "two-year auction", "2年期国债拍卖"), "strong demand -> yields down, prices up (prior)",
           window=1, lookback_days=3 * 365),
    Series("treasury:BTC_10Y", "10-year note auction bid-to-cover", "monthly", "ratio",
           "FiscalData auctions_query", _bid_to_cover("10-Year"), (("IEF", 1), ("TLT", 1)),
           ("10-year note auction", "10-year auction", "ten-year auction", "10年期国债拍卖"),
           "strong demand -> yields down, prices up (prior)", window=1, lookback_days=3 * 365),
    Series("treasury:BTC_30Y", "30-year bond auction bid-to-cover", "monthly", "ratio",
           "FiscalData auctions_query", _bid_to_cover("30-Year"), (("TLT", 1),),
           ("30-year bond auction", "30-year auction", "long bond auction", "30年期国债拍卖"),
           "strong demand -> yields down, prices up (prior)", window=1, lookback_days=3 * 365),
    # MOF JGB
    Series("mof:JGB2Y", "JGB 2-year yield", "daily", "%", "MOF jgbcme CSV", _jgb("2Y"),
           (("FXY", 1),), ("2-year JGB", "JGB yields", "BOJ rate hike", "日本国债收益率", "日债"),
           "higher Japanese front-end yields -> yen up (prior)"),
    Series("mof:JGB10Y", "JGB 10-year yield", "daily", "%", "MOF jgbcme CSV", _jgb("10Y"),
           (("FXY", 1), ("EWJ", -1), ("TLT", -1)),
           ("10-year JGB", "JGB yields", "Japanese government bond", "日本国债收益率", "日债"),
           "higher JGB yields -> yen up, carry unwind, global duration down (prior)"),
    Series("mof:JGB30Y", "JGB 30-year yield", "daily", "%", "MOF jgbcme CSV", _jgb("30Y"),
           (("TLT", -1), ("FXY", 1)),
           ("30-year JGB", "super-long JGB", "Japanese government bond", "超长期国债", "日债"),
           "higher super-long JGB yields pull global long yields up (prior)"),
    # ECB reference rates (units of currency per EUR)
    Series("ecb:EURUSD", "ECB reference rate EUR/USD", "daily", "USD per EUR", "ECB EXR", _ecb("USD"),
           (("FXE", 1), ("UUP", -1)), ("EUR/USD", "euro dollar", "欧元兑美元"), "EUR/USD up = euro up, dollar down"),
    Series("ecb:EURJPY", "ECB reference rate EUR/JPY", "daily", "JPY per EUR", "ECB EXR", _ecb("JPY"),
           (("FXY", -1),), ("EUR/JPY", "euro yen", "欧元兑日元"), "EUR/JPY up = yen weaker"),
    Series("ecb:EURCHF", "ECB reference rate EUR/CHF", "daily", "CHF per EUR", "ECB EXR", _ecb("CHF"),
           (("FXF", -1),), ("EUR/CHF", "Swiss franc", "瑞郎"), "EUR/CHF up = franc weaker (risk-on)"),
    Series("ecb:EURGBP", "ECB reference rate EUR/GBP", "daily", "GBP per EUR", "ECB EXR", _ecb("GBP"),
           (("FXB", -1),), ("EUR/GBP", "sterling", "英镑"), "EUR/GBP up = pound weaker"),
    Series("ecb:EURCNY", "ECB reference rate EUR/CNY", "daily", "CNY per EUR", "ECB EXR", _ecb("CNY"),
           (("FXI", -1),), ("yuan", "renminbi", "EUR/CNY", "人民币"),
           "EUR/CNY up = yuan weaker -> China equities in USD down (weak prior)"),
    # Cboe
    Series("cboe:VIX9D_VIX", "VIX9D / VIX ratio", "daily", "ratio", "Cboe daily_prices CSV",
           _cboe_ratio("VIX9D", "VIX"), (("SPY", -1),),
           ("VIX9D", "short-term volatility", "vol term structure", "波动率期限结构"),
           "near-term implied vol above 30-day = near-term stress (prior)"),
    Series("cboe:VIX_VIX3M", "VIX / VIX3M ratio", "daily", "ratio", "Cboe daily_prices CSV",
           _cboe_ratio("VIX", "VIX3M"), (("SPY", -1),),
           ("VIX3M", "backwardation", "volatility curve inversion", "VIX倒挂"),
           "ratio > 1 = backwardation / stress (prior)"),
    Series("cboe:SKEW", "Cboe SKEW index", "daily", "index", "Cboe daily_prices CSV", _cboe_skew,
           (("SPY", -1),), ("SKEW index", "tail risk hedging", "tail-risk", "尾部风险"),
           "more priced tail risk -> equities down (weak prior)"),
    # OKX
    Series("okx:BTC_FUNDING", "BTC perpetual funding rate, daily mean (OKX)", "daily", "% per period",
           "OKX funding-rate-history BTC-USDT-SWAP", _okx_funding("BTC"), (("BTC-USD", -1),),
           ("funding rate", "perpetual funding", "资金费率"),
           "crowded longs paying high funding -> mean reversion down (contrarian prior)"),
    Series("okx:ETH_FUNDING", "ETH perpetual funding rate, daily mean (OKX)", "daily", "% per period",
           "OKX funding-rate-history ETH-USDT-SWAP", _okx_funding("ETH"), (("ETH-USD", -1),),
           ("ETH funding", "ether funding rate", "以太坊资金费率"),
           "crowded longs paying high funding -> mean reversion down (contrarian prior)"),
    Series("okx:BTC_OI", "BTC perpetual open interest (OKX)", "daily", "B USD",
           "OKX rubik open-interest-volume ccy=BTC", _okx_oi("BTC"), (("BTC-USD", 1),),
           ("bitcoin open interest", "BTC open interest", "未平仓合约"),
           "new money entering derivatives -> price up (prior)"),
    # DefiLlama
    Series("defillama:STABLECOIN_SUPPLY", "Stablecoin total supply (USD-pegged)", "daily", "B USD",
           "DefiLlama stablecoincharts/all", _stablecoins, (("BTC-USD", 1), ("ETH-USD", 1)),
           ("stablecoin supply", "stablecoin market cap", "USDT supply", "稳定币"),
           "more stablecoin dry powder -> crypto up (prior)"),
    # EIA weekly petroleum stocks (thousand barrels)
    Series("eia:WCESTUS1", "US crude oil stocks excl. SPR", "weekly", "k bbl", "EIA API v2 PET.WCESTUS1.W",
           _eia("PET.WCESTUS1.W"), (("USO", -1), ("XLE", -1)),
           ("crude inventories", "crude stocks", "crude oil inventory", "原油库存"), "more supply on hand -> oil down (prior)"),
    Series("eia:WGTSTUS1", "US total gasoline stocks", "weekly", "k bbl", "EIA API v2 PET.WGTSTUS1.W",
           _eia("PET.WGTSTUS1.W"), (("UGA", -1),),
           ("gasoline inventories", "gasoline stocks", "汽油库存"), "more supply on hand -> gasoline down (prior)"),
    Series("eia:WDISTUS1", "US distillate fuel oil stocks", "weekly", "k bbl", "EIA API v2 PET.WDISTUS1.W",
           _eia("PET.WDISTUS1.W"), (("USO", -1),),
           ("distillate inventories", "diesel stocks", "distillate stocks", "馏分油库存"),
           "more supply on hand -> oil down (prior)"),
)


def default_registry() -> list[Series]:
    return list(REGISTRY)
