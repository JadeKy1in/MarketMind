"""Live inputs for the fragility scanner (SPEC_v3 S1: fragility no longer gets `{}`).

Maps each threshold metric in config/fragility_thresholds.py to a real source,
converted into the threshold's unit. Metrics without a verified source or unit
are reported as unavailable instead of being guessed: a failed or missing fetch
never produces a number.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from marketmind.gateway.fred_client import _FRED_BASE, _get_fred_key, _redact, get_fred_series

logger = logging.getLogger("marketmind.gateway.fragility_inputs")

_TIMEOUT = httpx.Timeout(30.0)
_UA = {"User-Agent": "Mozilla/5.0 (MarketMind research)"}
OFR_FSI_CSV = "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
WB_EM_IMPORT_COVER = ("https://api.worldbank.org/v2/country/LMY/indicator/FI.RES.TOTL.MO"
                      "?format=json&mrv=5")
DEFILLAMA_PROTOCOLS = "https://api.llama.fi/protocols"

LB_PER_METRIC_TON = 2204.62262
# Annual World Bank data older than this many years is treated as missing.
_WB_MAX_AGE_YEARS = 2
# Share of CEX TVL that must report a 7-day change for the aggregate to be computed.
_CEX_MIN_COVERAGE = 0.9
# SOFR-IORB persistence rule: the value fed is the minimum spread over this many most
# recent SOFR observations, so "> 10bp" means every one of them exceeded 10bp.
_SOFR_PERSIST_OBS = 3

# Metrics we deliberately do not feed yet, with the reason shown to the user.
UNSOURCED: dict[str, str] = {}


@dataclass
class FragilityInputs:
    values: dict[str, float] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)


async def fetch_fragility_inputs() -> FragilityInputs:
    out = FragilityInputs(unavailable=dict(UNSOURCED))
    fred_keys = ["DGS10", "RRPONTSYD", "WTREGEN", "WRESBAL", "BAMLH0A3HYC",
                 "BAMLH0A0HYM2", "BAMLC0A0CM"]
    (fred_results, yf_results, margin, gdp, copper, stlfsi, bbb, ofr, em_cover, cex,
     gold_monthly, sofr, iorb) = await asyncio.gather(
        asyncio.gather(*(get_fred_series(k) for k in fred_keys)),
        asyncio.gather(*(_yf_last(s) for s in ("^VIX", "^TNX", "DX-Y.NYB"))),
        _fred_observations("BOGZ1FL663067003Q", limit=8),
        _fred_observations("GDP", limit=8),
        _fred_observations("PCOPPUSDM", limit=3),
        _fred_observations("STLFSI4", limit=5),
        _fred_observations("BAMLC0A4CBBB", limit=5),
        _ofr_fsi_latest(),
        _worldbank_em_import_cover(),
        _defillama_cex_7d_change(),
        _gold_monthly_avg(),
        _fred_observations("SOFR", limit=10),
        _fred_observations("IORB", limit=15),
    )
    fred = {k: _fred_value(r) for k, r in zip(fred_keys, fred_results)}
    fred_dates = {k: r.get("date") if isinstance(r, dict) else None
                  for k, r in zip(fred_keys, fred_results)}
    vix, tnx, dxy = yf_results

    def put(metric: str, value: float | None, source: str, missing_reason: str) -> None:
        if value is None:
            out.unavailable[metric] = missing_reason or "no value"
        else:
            out.values[metric] = round(value, 4)
            out.sources[metric] = source
            out.unavailable.pop(metric, None)

    fred_missing = "FRED unavailable (FRED_KEY/FRED_API_KEY not set or unreachable)"
    if fred["DGS10"] is not None:
        put("us10y_yield", fred["DGS10"], "FRED:DGS10", "")
    else:
        put("us10y_yield", tnx, "yfinance:^TNX", "neither FRED nor yfinance returned 10Y yield")
    put("on_rrp", fred["RRPONTSYD"], "FRED:RRPONTSYD", fred_missing)
    put("tga", fred["WTREGEN"] / 1000 if fred["WTREGEN"] is not None else None,
        "FRED:WTREGEN (M->B USD)", fred_missing)
    # bank_reserves (percent of nominal GDP): WRESBAL is published in millions of USD
    # (checked 2026-09-28: 2,930,193 = $2.93T); GDP in billions USD SAAR (latest quarter).
    # pct = WRESBAL_M / (GDP_B * 1000) * 100.
    put("bank_reserves", *_reserves_to_gdp(fred["WRESBAL"], fred_dates["WRESBAL"], gdp,
                                           fred_missing))
    # sofr_iorb_spread: minimum (SOFR - IORB) in bp over the last 3 SOFR observations.
    put("sofr_iorb_spread", *_sofr_iorb_persistent(sofr, iorb))
    put("ccc_treasury_spread", fred["BAMLH0A3HYC"] * 100 if fred["BAMLH0A3HYC"] is not None else None,
        "FRED:BAMLH0A3HYC (%->bp)", fred_missing)
    # hyg_lqd_spread: threshold is "HY vs IG spread >200bp" sourced from ICE BofA OAS
    # data, so we read it as HY OAS minus IG OAS, in basis points. FRED publishes both
    # indices' OAS in percent (e.g. 2.80 and 0.79), so the difference is x100 -> bp.
    # These are the index OAS the HYG/LQD ETFs track, not the ETFs' own spreads.
    hy, ig = fred["BAMLH0A0HYM2"], fred["BAMLC0A0CM"]
    hy_ig, hy_ig_missing = None, fred_missing
    if None not in (hy, ig):
        if fred_dates["BAMLH0A0HYM2"] == fred_dates["BAMLC0A0CM"]:
            hy_ig = (hy - ig) * 100
        else:
            hy_ig_missing = (f"HY/IG OAS dates differ ({fred_dates['BAMLH0A0HYM2']} vs "
                             f"{fred_dates['BAMLC0A0CM']})")
    put("hyg_lqd_spread", hy_ig, "FRED:BAMLH0A0HYM2-BAMLC0A0CM (%->bp)", hy_ig_missing)
    put("vix", vix, "yfinance:^VIX", "yfinance ^VIX unavailable")
    put("dollar_index", dxy, "yfinance:DX-Y.NYB", "yfinance DX-Y.NYB unavailable")

    # margin_debt_gdp (percent of GDP): Z.1 broker-dealer margin loans & other receivables
    # (millions USD, quarter-end level) / nominal GDP (billions USD, SAAR) for the SAME
    # quarter. pct = margin_M / (GDP_B * 1000) * 100. 2026Q2: 742,321 / 32,486,066 = 2.29%.
    value, date, why = _same_date_ratio(margin, gdp)
    put("margin_debt_gdp", None if value is None else value / 1000 * 100,
        f"FRED:BOGZ1FL663067003Q/GDP ({date}; M USD / (B USD*1000) -> % of GDP)", why)

    # copper_gold_ratio: copper USD/lb divided by gold USD/troy oz, x1000 (market
    # convention; ~1.5 in 2026). Copper = FRED PCOPPUSDM monthly average (USD/metric ton,
    # /2204.62262 -> USD/lb); gold = yfinance GC=F daily closes averaged over the SAME month.
    put(*_copper_gold(copper, gold_monthly))

    # Financial-stress indices (0 = average stress by construction).
    put("stlfsi", *_latest_or_reason(stlfsi, "FRED:STLFSI4 (index, 0=avg)"))
    put("ofr_fsi", *ofr)
    bbb_val, bbb_src, bbb_why = _latest_or_reason(bbb, "FRED:BAMLC0A4CBBB (%->bp)")
    put("bbb_oas", None if bbb_val is None else bbb_val * 100, bbb_src, bbb_why)

    put("em_import_cover", *em_cover)
    put("crypto_exchange_reserves", *cex)
    return out


def _fred_value(result: dict) -> float | None:
    if not isinstance(result, dict) or result.get("error") or result.get("value") is None:
        return None
    return float(result["value"])


def _latest_or_reason(obs, label: str) -> tuple[float | None, str, str]:
    """obs: list of (date, value) newest first, or an error string."""
    if isinstance(obs, str):
        return None, "", obs
    if not obs:
        return None, "", f"{label}: no numeric observation"
    date, value = obs[0]
    return value, f"{label} {date}", ""


def _same_date_ratio(num, den) -> tuple[float | None, str, str]:
    """num/den for the newest date both series share (lists of (date, value))."""
    for obs in (num, den):
        if isinstance(obs, str):
            return None, "", obs
    den_by_date = dict(den or [])
    for date, value in num or []:
        d = den_by_date.get(date)
        if d:
            return value / d, date, ""
    return None, "", "margin loans and GDP share no recent quarter"


def _reserves_to_gdp(wresbal_m: float | None, wresbal_date, gdp,
                     fred_missing: str) -> tuple[float | None, str, str]:
    """Reserve balances as % of nominal GDP (latest GDP quarter), or a reason."""
    if wresbal_m is None:
        return None, "", fred_missing
    if isinstance(gdp, str):
        return None, "", gdp
    if not gdp:
        return None, "", "FRED:GDP no numeric observation"
    gdp_date, gdp_b = gdp[0]
    if gdp_b <= 0:
        return None, "", f"FRED:GDP {gdp_date} non-positive ({gdp_b})"
    return (wresbal_m / (gdp_b * 1000) * 100,
            f"FRED:WRESBAL {wresbal_date} / FRED:GDP {gdp_date} "
            f"(M USD / (B USD SAAR*1000) -> % of GDP)", "")


def _sofr_iorb_persistent(sofr, iorb, n: int = _SOFR_PERSIST_OBS) -> tuple[float | None, str, str]:
    """Minimum SOFR-IORB spread (bp) over the n most recent SOFR observations.

    sofr / iorb: newest-first (date, percent) lists, or an error string. IORB must be
    observed on each of those SOFR dates, otherwise the metric is unavailable.
    min > 10bp <=> every one of the last n consecutive observations exceeded 10bp.
    """
    for obs in (sofr, iorb):
        if isinstance(obs, str):
            return None, "", obs
    recent = list(sofr or [])[:n]
    if len(recent) < n:
        return None, "", f"FRED SOFR has only {len(recent)} recent observations (need {n})"
    iorb_by_date = dict(iorb or [])
    missing = [d for d, _ in recent if d not in iorb_by_date]
    if missing:
        return None, "", f"FRED IORB has no observation on SOFR date(s) {', '.join(missing)}"
    spreads = [round((v - iorb_by_date[d]) * 100, 4) for d, v in recent]
    return (min(spreads),
            f"FRED:SOFR-IORB min of last {n} obs {recent[-1][0]}..{recent[0][0]} "
            f"(bp; each: {', '.join(f'{x:g}' for x in spreads)})", "")


def _copper_gold(copper, gold_monthly) -> tuple[str, float | None, str, str]:
    metric = "copper_gold_ratio"
    if isinstance(copper, str):
        return metric, None, "", copper
    if not copper:
        return metric, None, "", "FRED:PCOPPUSDM no numeric observation"
    if isinstance(gold_monthly, str):
        return metric, None, "", gold_monthly
    month, cu_usd_per_t = copper[0]
    gold = gold_monthly.get(month[:7])
    if not gold:
        return metric, None, "", f"no GC=F gold closes for copper month {month[:7]}"
    ratio = (cu_usd_per_t / LB_PER_METRIC_TON) / gold * 1000
    return (metric, ratio,
            f"FRED:PCOPPUSDM/yfinance:GC=F monthly avg {month[:7]} (USD/lb / USD/oz x1000)", "")


async def _fred_observations(series_id: str, limit: int = 5):
    """Newest-first numeric (date, value) observations, or an error string."""
    key = _get_fred_key()
    if not key:
        return "FRED unavailable (FRED_KEY/FRED_API_KEY not set)"
    url = (f"{_FRED_BASE}?series_id={series_id}&api_key={key}&file_type=json"
           f"&sort_order=desc&limit={limit}")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return _parse_fred_observations(resp.json())
    except Exception as exc:
        logger.warning("FRED %s failed: %s", series_id, _redact(str(exc)))
        return f"FRED {series_id} unavailable ({type(exc).__name__})"


def _parse_fred_observations(payload: dict) -> list[tuple[str, float]]:
    rows = []
    for o in payload.get("observations", []) or []:
        try:
            rows.append((o["date"], float(o["value"])))
        except (KeyError, TypeError, ValueError):
            continue  # FRED uses "." for missing
    return rows


async def _ofr_fsi_latest() -> tuple[float | None, str, str]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(OFR_FSI_CSV, headers=_UA)
            resp.raise_for_status()
            return _parse_ofr_fsi(resp.text)
    except Exception as exc:
        logger.warning("OFR FSI fetch failed: %s", exc)
        return None, "", f"OFR FSI CSV unavailable ({type(exc).__name__})"


def _parse_ofr_fsi(text: str) -> tuple[float | None, str, str]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "OFR FSI" not in reader.fieldnames or "Date" not in reader.fieldnames:
        return None, "", "OFR FSI CSV missing Date/OFR FSI columns"
    latest = None
    for row in reader:
        try:
            latest = (row["Date"], float(row["OFR FSI"]))
        except (TypeError, ValueError):
            continue
    if latest is None:
        return None, "", "OFR FSI CSV had no numeric rows"
    return latest[1], f"OFR:FSI {latest[0]} (index, 0=avg)", ""


async def _worldbank_em_import_cover() -> tuple[float | None, str, str]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(WB_EM_IMPORT_COVER, headers=_UA)
            resp.raise_for_status()
            return _parse_worldbank(resp.json())
    except Exception as exc:
        logger.warning("World Bank FI.RES.TOTL.MO fetch failed: %s", exc)
        return None, "", f"World Bank API unavailable ({type(exc).__name__})"


def _parse_worldbank(payload, now: datetime | None = None) -> tuple[float | None, str, str]:
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        return None, "", "World Bank response had no data rows"
    year = (now or datetime.now(timezone.utc)).year
    for row in payload[1]:  # newest year first
        value, date = row.get("value"), str(row.get("date", ""))
        if value is None or not date.isdigit():
            continue
        if year - int(date) > _WB_MAX_AGE_YEARS:
            return None, "", f"World Bank LMY import cover too old (latest {date})"
        return (float(value),
                f"WorldBank:FI.RES.TOTL.MO LMY {date} (months of imports)", "")
    return None, "", "World Bank LMY import cover has no numeric value"


async def _defillama_cex_7d_change() -> tuple[float | None, str, str]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(DEFILLAMA_PROTOCOLS, headers=_UA)
            resp.raise_for_status()
            return _parse_cex_change(resp.json())
    except Exception as exc:
        logger.warning("DefiLlama protocols fetch failed: %s", exc)
        return None, "", f"DefiLlama /protocols unavailable ({type(exc).__name__})"


def _parse_cex_change(protocols) -> tuple[float | None, str, str]:
    """Aggregate 7-day % change of USD TVL over DefiLlama category "CEX".

    prev_i = tvl_i / (1 + change_7d_i/100); change = sum(tvl)/sum(prev) - 1, in percent.
    """
    if not isinstance(protocols, list):
        return None, "", "DefiLlama /protocols returned no list"
    cex = [p for p in protocols if isinstance(p, dict) and p.get("category") == "CEX"
           and isinstance(p.get("tvl"), (int, float)) and p["tvl"] > 0]
    total = sum(p["tvl"] for p in cex)
    if not total:
        return None, "", "DefiLlama has no CEX TVL"
    cur = prev = 0.0
    for p in cex:
        ch = p.get("change_7d")
        if isinstance(ch, (int, float)) and ch > -100:
            cur += p["tvl"]
            prev += p["tvl"] / (1 + ch / 100)
    if cur / total < _CEX_MIN_COVERAGE or prev <= 0:
        return None, "", (f"DefiLlama CEX 7d change covers only {cur / total:.0%} of "
                          f"${total / 1e9:.0f}B TVL")
    return ((cur / prev - 1) * 100,
            f"DefiLlama:CEX TVL 7d change (USD, {len(cex)} CEX, ${total / 1e9:.0f}B)", "")


async def _gold_monthly_avg():
    """{'YYYY-MM': mean GC=F close in USD/oz} for the last year, or an error string."""
    try:
        import yfinance as yf
        df = await asyncio.wait_for(
            asyncio.to_thread(lambda: yf.Ticker("GC=F").history(period="1y")), timeout=30)
        if df is None or df.empty:
            return "yfinance GC=F unavailable"
        closes = df["Close"].dropna()
        by_month: dict[str, list[float]] = {}
        for ts, v in closes.items():
            by_month.setdefault(ts.strftime("%Y-%m"), []).append(float(v))
        return {m: sum(v) / len(v) for m, v in by_month.items() if v}
    except Exception as exc:
        logger.warning("yfinance GC=F failed: %s", exc)
        return f"yfinance GC=F unavailable ({type(exc).__name__})"


async def _yf_last(symbol: str) -> float | None:
    try:
        import yfinance as yf
        df = await asyncio.wait_for(
            asyncio.to_thread(lambda: yf.Ticker(symbol).history(period="5d")), timeout=30)
        if df is None or df.empty:
            return None
        return float(df["Close"].dropna().iloc[-1])
    except Exception as exc:
        logger.warning("yfinance last close failed for %s: %s", symbol, exc)
        return None
