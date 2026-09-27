"""Positioning, inventory and volatility data (key-free public APIs) as compact NewsItems.

Each fetcher returns 1-5 summary NewsItems that state the latest fact and its change,
so the downstream pipeline sees e.g. "CFTC COT (week to 2026-09-22) energy: WTI crude
spec net +212.0k (-18.0k w/w, 3y pct 12%)" instead of raw tables.

Fetchers (all ``async def fetch_xxx(source, config) -> list[NewsItem]``):

- fetch_cftc_cot          CFTC Commitments of Traders via Socrata (Legacy + TFF, futures only)
- fetch_eia_petroleum     EIA Weekly Petroleum Status Report table 1 (CSV, no key)
- fetch_eia_natgas_storage EIA Weekly Natural Gas Storage Report (JSON, no key)
- fetch_cboe_vix          Cboe VIX daily history CSV
- fetch_cboe_spx_options  Cboe delayed SPX option chain (~13 MB): put/call + 25-delta skew
- fetch_deribit_dvol      Deribit DVOL index (BTC, ETH)
- fetch_bybit_derivs      Bybit linear perps funding + open interest (BTC, ETH, SOL)
- fetch_hyperliquid_derivs Hyperliquid perps funding + open interest (BTC, ETH, SOL)

All computations are deterministic (no LLM):

- Percentile rank (``percentile_rank``): mid-rank of the current value within the
  trailing window including itself, 100 * (count(x < cur) + 0.5 * count(x == cur)) / n.
  CFTC: 156 weekly reports (~3y). VIX and DVOL: 1y of daily closes (252 / 365 points).
- CFTC spec net: Legacy report non-commercial long - short (commodities); TFF report
  leveraged funds long - short (financial futures). w/w change is vs the previous report.
- Annualised funding: rate per interval * (24 / interval_hours) * 365.

Every fetcher raises on non-200 responses or unusable payloads, so scout.fetch_source()
applies its usual failure tracking (DEGRADED -> DEAD). Existing gateway code was reviewed
but not reused for fetching: gateway.macro_data.get_cot_data() returns only the latest
row for an ambiguous LIKE filter (no history -> no change / percentile), and the gateway
EIA path needs an API key; the Cboe/Bybit gateway helpers cover other endpoints.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx

from marketmind.pipeline.official_data_sources import _client_kwargs, _reliability

logger = logging.getLogger("marketmind.pipeline.sources_positioning")

_UA = "Mozilla/5.0 (compatible; MarketMind/0.1; Financial Research Bot)"
_HEADERS = {"User-Agent": _UA}

# ── Endpoints ───────────────────────────────────────────────────────────────
CFTC_LEGACY_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
CFTC_TFF_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
CFTC_PAGE = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
EIA_WPSR_URL = "https://ir.eia.gov/wpsr/table1.csv"
EIA_WPSR_PAGE = "https://www.eia.gov/petroleum/supply/weekly/"
EIA_NGS_URL = "https://ir.eia.gov/ngs/wngsr.json"
EIA_NGS_PAGE = "https://ir.eia.gov/ngs/ngs.html"
CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
CBOE_VIX_PAGE = "https://www.cboe.com/tradable_products/vix/"
CBOE_SPX_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
CBOE_SPX_PAGE = "https://www.cboe.com/delayed_quotes/spx/quote_table"
DERIBIT_DVOL_URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
DERIBIT_PAGE = "https://www.deribit.com/statistics/BTC/volatility-index"
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"
BYBIT_OI_URL = "https://api.bybit.com/v5/market/open-interest"
BYBIT_PAGE = "https://www.bybit.com/en/trade/usdt/BTCUSDT"
HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_PAGE = "https://app.hyperliquid.xyz/trade"

# ── CFTC contract list (verified 2026-09-27 against report week 2026-09-22) ─
# (cftc_contract_market_code, label, group)
CFTC_LEGACY_CONTRACTS: tuple[tuple[str, str, str], ...] = (
    ("067651", "WTI crude", "energy"),         # WTI-PHYSICAL - NYMEX (CL)
    ("023651", "Henry Hub natgas", "energy"),  # NAT GAS NYME - NYMEX (NG)
    ("088691", "gold", "metals"),              # GOLD - COMEX
    ("084691", "silver", "metals"),            # SILVER - COMEX
    ("085692", "copper", "metals"),            # COPPER- #1 - COMEX
    ("002602", "corn", "grains"),              # CORN - CBOT
    ("005602", "soybeans", "grains"),          # SOYBEANS - CBOT
)
CFTC_TFF_CONTRACTS: tuple[tuple[str, str, str], ...] = (
    ("13874A", "S&P 500 e-mini", "financials"),  # E-MINI S&P 500 - CME
    ("043602", "10Y T-note", "financials"),      # UST 10Y NOTE - CBOT
    ("098662", "USD index", "financials"),       # USD INDEX - ICE US
    ("133741", "CME bitcoin", "financials"),     # BITCOIN - CME (5 BTC contracts)
)
CFTC_GROUP_ORDER = ("energy", "metals", "grains", "financials")
CFTC_PCT_WINDOW = 156   # weekly reports ≈ 3 years
CFTC_MIN_HISTORY = 26   # fewer points -> percentile omitted

VIX_PCT_WINDOW = 252
DVOL_PCT_WINDOW = 365
CRYPTO_SYMBOLS = ("BTC", "ETH", "SOL")
SPX_TARGET_DTE = 30
SPX_DELTA_TOL = 0.10


# ── Shared helpers ──────────────────────────────────────────────────────────

def percentile_rank(history: Iterable[float], current: float) -> float | None:
    """Mid-rank percentile (0-100) of ``current`` within ``history`` (which should include it)."""
    vals = [float(v) for v in history]
    if not vals:
        return None
    below = sum(1 for v in vals if v < current)
    equal = sum(1 for v in vals if v == current)
    return 100.0 * (below + 0.5 * equal) / len(vals)


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _k(value: float, signed: bool = True) -> str:
    """Compact count: 212345 -> '+212.3k'; 950 -> '+950'."""
    sign = "+" if signed else ""
    if abs(value) >= 1000:
        return f"{value / 1000:{sign},.1f}k"
    return f"{value:{sign},.0f}"


def _usd(value: float) -> str:
    if abs(value) >= 1e9:
        return f"${value / 1e9:,.2f}B"
    return f"${value / 1e6:,.0f}M"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}%"


def _make_item(source: Any, key: str, title: str, url: str, published_at: str,
               parts: list[str], default_rel: float) -> Any:
    from marketmind.pipeline.scout import NewsItem

    return NewsItem(
        id=hashlib.sha256(f"{key}:{published_at}:{title}".encode()).hexdigest()[:16],
        title=title,
        url=url,
        source_name=source.name,
        source_tier=int(source.tier),
        published_at=published_at,
        summary=("; ".join(p for p in parts if p))[:500],
        source_reliability=_reliability(source, default_rel),
    )


def _make_client(config: Any) -> httpx.AsyncClient:
    """Single construction point (30s timeout, config.proxy_url); tests patch this."""
    return httpx.AsyncClient(**_client_kwargs(config))


def _ms_now() -> int:
    return int(time.time() * 1000)


# ── 1. CFTC Commitments of Traders ──────────────────────────────────────────

def cot_series(rows: list[dict], code: str, long_key: str, short_key: str) -> list[tuple[str, float, float, float]]:
    """Ascending [(date, net, long, short)] for one contract, deduped on report date."""
    by_date: dict[str, tuple[float, float]] = {}
    for r in rows:
        if r.get("cftc_contract_market_code") != code:
            continue
        lng, sht = _f(r.get(long_key)), _f(r.get(short_key))
        date = str(r.get("report_date_as_yyyy_mm_dd", ""))[:10]
        if lng is None or sht is None or not date:
            continue
        by_date[date] = (lng, sht)
    return [(d, lng - sht, lng, sht) for d, (lng, sht) in sorted(by_date.items())]


def cot_stats(series: list[tuple[str, float, float, float]]) -> dict | None:
    """Latest net, w/w change and ~3y percentile from an ascending series."""
    if not series:
        return None
    date, net, lng, sht = series[-1]
    chg = net - series[-2][1] if len(series) >= 2 else None
    window = [s[1] for s in series[-CFTC_PCT_WINDOW:]]
    pct = percentile_rank(window, net) if len(window) >= CFTC_MIN_HISTORY else None
    return {"date": date, "net": net, "long": lng, "short": sht, "change": chg,
            "percentile": pct, "weeks": len(window)}


def cot_to_newsitems(legacy_rows: list[dict], tff_rows: list[dict], source: Any) -> list[Any]:
    """Group per-contract stats into one NewsItem per group (energy/metals/grains/financials)."""
    stats: dict[str, list[tuple[str, str, dict]]] = {g: [] for g in CFTC_GROUP_ORDER}
    for code, label, group in CFTC_LEGACY_CONTRACTS:
        st = cot_stats(cot_series(legacy_rows, code, "noncomm_positions_long_all", "noncomm_positions_short_all"))
        if st:
            stats[group].append((label, "non-commercial", st))
    for code, label, group in CFTC_TFF_CONTRACTS:
        st = cot_stats(cot_series(tff_rows, code, "lev_money_positions_long", "lev_money_positions_short"))
        if st:
            stats[group].append((label, "leveraged funds", st))

    items = []
    for group in CFTC_GROUP_ORDER:
        entries = stats[group]
        if not entries:
            continue
        date = max(st["date"] for _, _, st in entries)
        heads, parts = [], []
        for label, trader, st in entries:
            chg = "n/a" if st["change"] is None else _k(st["change"])
            heads.append(f"{label} {_k(st['net'])} ({chg} w/w, 3y pct {_pct(st['percentile'])})")
            stale = "" if st["date"] == date else f", as of {st['date']}"
            parts.append(f"{label}: {trader} net {_k(st['net'])} contracts (long {_k(st['long'], False)}, "
                         f"short {_k(st['short'], False)}), {chg} w/w, percentile {_pct(st['percentile'])} "
                         f"over {st['weeks']} weeks{stale}")
        who = "leveraged funds" if group == "financials" else "non-commercial"
        title = f"CFTC COT (week to {date}) {group}, {who} net: " + "; ".join(heads)
        items.append(_make_item(source, f"cftc_cot:{group}", title, CFTC_PAGE, date, parts, 0.95))
    return items


async def _socrata_rows(client: httpx.AsyncClient, url: str, codes: list[str],
                        fields: list[str], since: str) -> list[dict]:
    code_list = ",".join(f"'{c}'" for c in codes)
    params = {
        "$select": ",".join(["cftc_contract_market_code", "report_date_as_yyyy_mm_dd", *fields]),
        "$where": f"cftc_contract_market_code in({code_list}) AND report_date_as_yyyy_mm_dd >= '{since}'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": "5000",
    }
    resp = await client.get(url, params=params, headers={**_HEADERS, "Accept": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"CFTC Socrata returned non-list payload from {url}")
    return data


async def fetch_cftc_cot(source: Any, config: Any = None) -> list[Any]:
    """Weekly COT spec positioning for a fixed contract list (up to 4 group items)."""
    since = (datetime.now(timezone.utc) - timedelta(weeks=CFTC_PCT_WINDOW + 3)).strftime("%Y-%m-%d")
    async with _make_client(config) as client:
        legacy = await _socrata_rows(client, CFTC_LEGACY_URL, [c for c, _, _ in CFTC_LEGACY_CONTRACTS],
                                     ["noncomm_positions_long_all", "noncomm_positions_short_all"], since)
        tff = await _socrata_rows(client, CFTC_TFF_URL, [c for c, _, _ in CFTC_TFF_CONTRACTS],
                                  ["lev_money_positions_long", "lev_money_positions_short"], since)
    items = cot_to_newsitems(legacy, tff, source)
    if not items:
        raise ValueError("CFTC COT: no rows for any configured contract")
    return items


# ── 2. EIA weekly petroleum + natural gas storage ───────────────────────────

_EIA_PETRO_ROWS = (
    ("Commercial (Excluding SPR)", "commercial crude"),
    ("Total Motor Gasoline", "gasoline"),
    ("Distillate Fuel Oil", "distillate"),
    ("Strategic Petroleum Reserve (SPR)", "SPR"),
)


def _eia_date(text: str) -> str:
    return datetime.strptime(text.strip(), "%m/%d/%y").strftime("%Y-%m-%d")


def parse_eia_table1(text: str) -> dict:
    """First block of WPSR table1.csv (stocks, million bbl) + refinery crude input (kb/d)."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows or not rows[0] or rows[0][0] != "STUB_1" or len(rows[0]) < 7:
        raise ValueError("EIA table1.csv: unexpected header")
    header = rows[0]
    out: dict = {"week": _eia_date(header[1]), "week_prev": _eia_date(header[2]),
                 "year_ago": _eia_date(header[5]), "stocks": {}, "refinery_input": None}
    for row in rows[1:]:
        if row and row[0] == "STUB_1":  # second block (supply/disposition, kb/d)
            break
        if len(row) >= 7 and row[0] in dict(_EIA_PETRO_ROWS):
            cur, diff, yr = _f(row[1]), _f(row[3]), _f(row[5])
            if cur is not None and diff is not None:
                out["stocks"][row[0]] = {"value": cur, "wow": diff, "yoy": None if yr is None else cur - yr}
    for row in rows:
        if len(row) >= 5 and "Crude Oil Input to Refineries" in row[1]:
            cur, diff = _f(row[2]), _f(row[4])
            if cur is not None:
                out["refinery_input"] = {"value": cur, "wow": diff}
            break
    if "Commercial (Excluding SPR)" not in out["stocks"]:
        raise ValueError("EIA table1.csv: commercial crude row missing")
    return out


def eia_petroleum_to_newsitem(parsed: dict, source: Any) -> Any:
    heads, parts = [], []
    for key, label in _EIA_PETRO_ROWS:
        st = parsed["stocks"].get(key)
        if not st:
            continue
        txt = f"{label} {st['value']:,.1f}M bbl ({st['wow']:+,.1f}M w/w)"
        if key != "Strategic Petroleum Reserve (SPR)":
            heads.append(txt)
        yoy = "" if st["yoy"] is None else f", {st['yoy']:+,.1f}M y/y"
        parts.append(txt + yoy)
    ri = parsed.get("refinery_input")
    if ri:
        wow = "" if ri["wow"] is None else f" ({ri['wow']:+,.0f} w/w)"
        parts.append(f"refinery crude input {ri['value']:,.0f} kb/d{wow}")
    week = parsed["week"]
    title = f"EIA weekly petroleum (week to {week}): " + ", ".join(heads)
    return _make_item(source, "eia_wpsr", title, EIA_WPSR_PAGE, week, parts, 0.97)


async def fetch_eia_petroleum(source: Any, config: Any = None) -> list[Any]:
    async with _make_client(config) as client:
        resp = await client.get(EIA_WPSR_URL, headers=_HEADERS)
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig", errors="replace")
    return [eia_petroleum_to_newsitem(parse_eia_table1(text), source)]


def eia_natgas_to_newsitem(payload: dict, source: Any) -> Any:
    series = {s.get("name"): s for s in payload.get("series", []) if isinstance(s, dict)}
    total = series.get("total lower 48 states")
    if not total or not total.get("data"):
        raise ValueError("EIA wngsr.json: 'total lower 48 states' series missing")
    week, level = total["data"][0][0], _f(total["data"][0][1])
    calc = total.get("calculated", {})
    net, avg5 = _f(calc.get("net_change")), _f(calc.get("5yr-avg"))
    vs5, yoy, flow = _f(calc.get("pct-chg_5yr-avg")), _f(calc.get("pct-change_yrago")), _f(calc.get("implied_flow"))
    if level is None or net is None:
        raise ValueError("EIA wngsr.json: missing level / net change")
    vs5_txt = "" if vs5 is None else f", {vs5:+.1f}% vs 5-yr avg" + ("" if avg5 is None else f" ({avg5:,.0f})")
    yoy_txt = "" if yoy is None else f", {yoy:+.1f}% y/y"
    title = f"EIA natgas storage (week to {week}): Lower 48 {level:,.0f} Bcf, {net:+,.0f} Bcf w/w{vs5_txt}{yoy_txt}"
    parts = [f"release {str(payload.get('release_date', ''))[:11]}"]
    if flow is not None and flow != net:
        parts.append(f"implied flow {flow:+,.0f} Bcf (reclassification)")
    for name, s in series.items():
        if name == "total lower 48 states" or not s.get("data"):
            continue
        c = s.get("calculated", {})
        n, v5 = _f(c.get("net_change")), _f(c.get("pct-chg_5yr-avg"))
        if n is not None:
            parts.append(f"{name.replace(' region', '')} {_f(s['data'][0][1]) or 0:,.0f} ({n:+,.0f}"
                         + ("" if v5 is None else f", {v5:+.1f}% vs 5y") + ")")
    return _make_item(source, "eia_ngs", title, EIA_NGS_PAGE, week, parts, 0.97)


async def fetch_eia_natgas_storage(source: Any, config: Any = None) -> list[Any]:
    async with _make_client(config) as client:
        resp = await client.get(EIA_NGS_URL, headers=_HEADERS)
        resp.raise_for_status()
        payload = json.loads(resp.content.decode("utf-8-sig"))  # body starts with a BOM
    return [eia_natgas_to_newsitem(payload, source)]


# ── 3. Cboe VIX history + SPX option chain ──────────────────────────────────

def parse_vix_history(text: str) -> list[tuple[str, float]]:
    """Ascending [(YYYY-MM-DD, close)] from VIX_History.csv."""
    out = []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        close = _f(row.get("CLOSE"))
        try:
            date = datetime.strptime(str(row.get("DATE", "")).strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        if close is not None:
            out.append((date, close))
    out.sort()
    return out


def vix_to_newsitem(history: list[tuple[str, float]], source: Any) -> Any:
    if len(history) < 6:
        raise ValueError("VIX history too short")
    date, cur = history[-1]
    d1 = cur - history[-2][1]
    d5 = cur - history[-6][1]
    window = [c for _, c in history[-VIX_PCT_WINDOW:]]
    pct = percentile_rank(window, cur)
    title = (f"Cboe VIX {date}: {cur:.2f} ({d1:+.2f} d/d, {d5:+.2f} over 5 sessions), "
             f"1y percentile {_pct(pct)}")
    parts = [f"1y range {min(window):.2f}-{max(window):.2f}", f"1y median {sorted(window)[len(window) // 2]:.2f}"]
    return _make_item(source, "cboe_vix", title, CBOE_VIX_PAGE, date, parts, 0.95)


async def fetch_cboe_vix(source: Any, config: Any = None) -> list[Any]:
    async with _make_client(config) as client:
        resp = await client.get(CBOE_VIX_URL, headers=_HEADERS)
        resp.raise_for_status()
        text = resp.text
    return [vix_to_newsitem(parse_vix_history(text), source)]


_OCC_RE = re.compile(r"^(?P<root>[A-Z]+)(?P<exp>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


def spx_chain_stats(payload: dict) -> dict:
    """Total put/call volume + OI ratios and a 25-delta risk-reversal skew at ~30 DTE.

    Skew = IV(put with delta nearest -0.25) - IV(call with delta nearest +0.25) at the
    expiry whose DTE is closest to 30, in vol points (Cboe 'iv' is a fraction). Omitted
    if no strike lies within 0.10 delta of the target.
    """
    data = payload.get("data") or {}
    options = data.get("options") or []
    if not options:
        raise ValueError("Cboe SPX chain: no options in payload")
    asof_txt = str(payload.get("timestamp", ""))[:10]
    try:
        asof = datetime.strptime(asof_txt, "%Y-%m-%d").date()
    except ValueError:
        asof = datetime.now(timezone.utc).date()
        asof_txt = asof.isoformat()
    vol = {"C": 0.0, "P": 0.0}
    oi = {"C": 0.0, "P": 0.0}
    by_exp: dict[str, list[tuple[str, float, float]]] = {}
    for o in options:
        m = _OCC_RE.match(str(o.get("option", "")))
        if not m:
            continue
        cp = m["cp"]
        vol[cp] += _f(o.get("volume")) or 0.0
        oi[cp] += _f(o.get("open_interest")) or 0.0
        delta, iv = _f(o.get("delta")), _f(o.get("iv"))
        if delta is not None and iv and iv > 0:
            by_exp.setdefault(m["exp"], []).append((cp, delta, iv))
    if vol["C"] <= 0 or oi["C"] <= 0:
        raise ValueError("Cboe SPX chain: zero call volume / open interest")

    skew = None
    candidates = []
    for exp, rows in by_exp.items():
        try:
            dte = (datetime.strptime(exp, "%y%m%d").date() - asof).days
        except ValueError:
            continue
        if dte >= 7 and len(rows) >= 20:
            candidates.append((abs(dte - SPX_TARGET_DTE), dte, exp))
    if candidates:
        _, dte, exp = min(candidates)
        puts = [(abs(d + 0.25), iv) for cp, d, iv in by_exp[exp] if cp == "P"]
        calls = [(abs(d - 0.25), iv) for cp, d, iv in by_exp[exp] if cp == "C"]
        if puts and calls:
            p, c = min(puts), min(calls)
            if p[0] <= SPX_DELTA_TOL and c[0] <= SPX_DELTA_TOL:
                skew = {"expiry": datetime.strptime(exp, "%y%m%d").strftime("%Y-%m-%d"), "dte": dte,
                        "put_iv": p[1] * 100, "call_iv": c[1] * 100, "rr": (p[1] - c[1]) * 100}
    # Label with the underlying's last trade date (payload timestamp can be a weekend).
    last_trade = str(data.get("last_trade_time") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_trade):
        asof_txt = last_trade
    return {"asof": asof_txt, "put_volume": vol["P"], "call_volume": vol["C"],
            "pc_volume": vol["P"] / vol["C"], "put_oi": oi["P"], "call_oi": oi["C"],
            "pc_oi": oi["P"] / oi["C"], "spot": _f(data.get("current_price")),
            "iv30": _f(data.get("iv30")), "skew": skew, "contracts": len(options)}


def spx_to_newsitem(st: dict, source: Any) -> Any:
    head = f"Cboe SPX options {st['asof']}: put/call volume {st['pc_volume']:.2f}, put/call OI {st['pc_oi']:.2f}"
    if st["skew"]:
        head += f", 25d put-call skew {st['skew']['rr']:+.1f} vol pts ({st['skew']['dte']}d)"
    parts = [f"put vol {_k(st['put_volume'], False)} / call vol {_k(st['call_volume'], False)}",
             f"put OI {_k(st['put_oi'], False)} / call OI {_k(st['call_oi'], False)}"]
    if st["iv30"] is not None:
        parts.append(f"SPX IV30 {st['iv30']:.2f}%")
    if st["spot"] is not None:
        parts.append(f"SPX {st['spot']:,.2f}")
    if st["skew"]:
        s = st["skew"]
        parts.append(f"skew expiry {s['expiry']}: 25d put IV {s['put_iv']:.1f}% vs 25d call IV {s['call_iv']:.1f}%")
    parts.append(f"{st['contracts']} contracts incl. SPXW; 15-min delayed")
    return _make_item(source, "cboe_spx", head, CBOE_SPX_PAGE, st["asof"], parts, 0.90)


async def fetch_cboe_spx_options(source: Any, config: Any = None) -> list[Any]:
    async with _make_client(config) as client:
        resp = await client.get(CBOE_SPX_URL, headers=_HEADERS)
        resp.raise_for_status()
        payload = resp.json()
    return [spx_to_newsitem(spx_chain_stats(payload), source)]


# ── 4. Crypto derivatives ───────────────────────────────────────────────────

def dvol_stats(candles: list[list]) -> dict:
    """Candles [ts_ms, open, high, low, close] ascending -> level, 1d/7d change, 1y pct."""
    closes = [(int(c[0]), float(c[4])) for c in candles if isinstance(c, list) and len(c) >= 5]
    closes.sort()
    if len(closes) < 8:
        raise ValueError("DVOL history too short")
    cur = closes[-1][1]
    window = [c for _, c in closes[-DVOL_PCT_WINDOW:]]
    return {"date": datetime.fromtimestamp(closes[-1][0] / 1000, timezone.utc).strftime("%Y-%m-%d"),
            "level": cur, "d1": cur - closes[-2][1], "d7": cur - closes[-8][1],
            "percentile": percentile_rank(window, cur), "days": len(window)}


def dvol_to_newsitem(stats: dict[str, dict], source: Any) -> Any:
    date = max(s["date"] for s in stats.values())
    heads = [f"{cur} {s['level']:.1f} ({s['d1']:+.1f} d/d, {s['d7']:+.1f} w/w, 1y pct {_pct(s['percentile'])})"
             for cur, s in stats.items()]
    title = "Deribit DVOL implied vol: " + "; ".join(heads)
    parts = [f"{cur} DVOL 30d implied vol index {s['level']:.2f}, percentile over {s['days']} daily closes"
             for cur, s in stats.items()]
    parts.append("latest candle is the current UTC day (intraday)")
    return _make_item(source, "deribit_dvol", title, DERIBIT_PAGE, date, parts, 0.85)


async def fetch_deribit_dvol(source: Any, config: Any = None) -> list[Any]:
    now = _ms_now()
    stats = {}
    async with _make_client(config) as client:
        for cur in ("BTC", "ETH"):
            resp = await client.get(DERIBIT_DVOL_URL, headers=_HEADERS, params={
                "currency": cur, "resolution": "1D",
                "start_timestamp": now - (DVOL_PCT_WINDOW + 10) * 86_400_000, "end_timestamp": now})
            resp.raise_for_status()
            stats[cur] = dvol_stats(((resp.json().get("result") or {}).get("data")) or [])
    return [dvol_to_newsitem(stats, source)]


def _annualised(rate: float, interval_hours: float) -> float:
    return rate * (24.0 / interval_hours) * 365.0 * 100.0


def bybit_to_newsitem(tickers: list[dict], oi_hist: dict[str, list[dict]], source: Any) -> Any:
    by_sym = {t.get("symbol"): t for t in tickers}
    heads, parts = [], []
    for coin in CRYPTO_SYMBOLS:
        t = by_sym.get(f"{coin}USDT")
        if not t:
            continue
        rate, oi_val = _f(t.get("fundingRate")), _f(t.get("openInterestValue"))
        hours = _f(t.get("fundingIntervalHour")) or 8.0
        if rate is None or oi_val is None:
            continue
        hist = oi_hist.get(coin) or []
        oi_chg = None
        if len(hist) >= 25:  # newest first, hourly -> [0] vs [24] = 24h
            now_oi, then_oi = _f(hist[0].get("openInterest")), _f(hist[24].get("openInterest"))
            if now_oi and then_oi:
                oi_chg = (now_oi / then_oi - 1) * 100
        chg_txt = "" if oi_chg is None else f" ({oi_chg:+.1f}% 24h)"
        heads.append(f"{coin} funding {_annualised(rate, hours):+.1f}% ann., OI {_usd(oi_val)}{chg_txt}")
        px = _f(t.get("price24hPcnt"))
        parts.append(f"{coin}USDT funding {rate * 100:+.4f}%/{hours:.0f}h, OI {_f(t.get('openInterest')) or 0:,.0f} {coin}"
                     f" = {_usd(oi_val)}{chg_txt}" + ("" if px is None else f", price {px * 100:+.1f}% 24h"))
    if not heads:
        raise ValueError("Bybit: none of the configured symbols returned")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts.append("OI change is in coin units (excludes price effect)")
    return _make_item(source, "bybit_derivs", "Bybit perps: " + "; ".join(heads), BYBIT_PAGE, date, parts, 0.80)


def _bybit_list(resp: httpx.Response) -> list[dict]:
    resp.raise_for_status()
    body = resp.json()
    if body.get("retCode") != 0:
        raise ValueError(f"Bybit retCode {body.get('retCode')}: {body.get('retMsg')}")
    return (body.get("result") or {}).get("list") or []


async def fetch_bybit_derivs(source: Any, config: Any = None) -> list[Any]:
    async with _make_client(config) as client:
        tickers = _bybit_list(await client.get(BYBIT_TICKERS_URL, params={"category": "linear"}, headers=_HEADERS))
        oi_hist = {}
        for coin in CRYPTO_SYMBOLS:
            oi_hist[coin] = _bybit_list(await client.get(BYBIT_OI_URL, headers=_HEADERS, params={
                "category": "linear", "symbol": f"{coin}USDT", "intervalTime": "1h", "limit": 25}))
    return [bybit_to_newsitem(tickers, oi_hist, source)]


def hyperliquid_to_newsitem(payload: list, source: Any) -> Any:
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError("Hyperliquid: unexpected metaAndAssetCtxs payload")
    universe = (payload[0] or {}).get("universe") or []
    ctxs = payload[1] or []
    by_name = {u.get("name"): ctxs[i] for i, u in enumerate(universe) if i < len(ctxs)}
    heads, parts = [], []
    for coin in CRYPTO_SYMBOLS:
        c = by_name.get(coin)
        if not c:
            continue
        rate, oi, mark, prev = (_f(c.get("funding")), _f(c.get("openInterest")),
                                _f(c.get("markPx")), _f(c.get("prevDayPx")))
        if rate is None or oi is None or mark is None:
            continue
        notional = oi * mark
        heads.append(f"{coin} funding {_annualised(rate, 1):+.1f}% ann., OI {_usd(notional)}")
        chg = "" if not prev else f", price {(mark / prev - 1) * 100:+.1f}% 24h"
        prem = _f(c.get("premium"))
        parts.append(f"{coin} funding {rate * 100:+.5f}%/1h, OI {oi:,.0f} {coin} = {_usd(notional)}{chg}"
                     + ("" if prem is None else f", premium {prem * 100:+.3f}%"))
    if not heads:
        raise ValueError("Hyperliquid: none of the configured coins returned")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _make_item(source, "hyperliquid_derivs", "Hyperliquid perps: " + "; ".join(heads),
                      HYPERLIQUID_PAGE, date, parts, 0.75)


async def fetch_hyperliquid_derivs(source: Any, config: Any = None) -> list[Any]:
    async with _make_client(config) as client:
        resp = await client.post(HYPERLIQUID_URL, json={"type": "metaAndAssetCtxs"}, headers=_HEADERS)
        resp.raise_for_status()
        payload = resp.json()
    return [hyperliquid_to_newsitem(payload, source)]


# feed_type -> fetcher, for scout.fetch_source dispatch (the lead wires this in).
POSITIONING_FETCHERS = {
    "cftc_cot": fetch_cftc_cot,
    "eia_petroleum": fetch_eia_petroleum,
    "eia_natgas": fetch_eia_natgas_storage,
    "cboe_vix": fetch_cboe_vix,
    "cboe_spx_options": fetch_cboe_spx_options,
    "deribit_dvol": fetch_deribit_dvol,
    "bybit_derivs": fetch_bybit_derivs,
    "hyperliquid_derivs": fetch_hyperliquid_derivs,
}
