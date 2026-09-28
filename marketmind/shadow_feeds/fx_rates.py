"""Official FX and rates: ECB euro reference rates and Japan MOF JGB yields.

Sources (keyless, verified 2026-09-28):
- ECB Data API, CSV: https://data-api.ecb.europa.eu/service/data/EXR/D.USD+JPY+GBP+CNY+CHF.EUR.SP00.A
  ?format=csvdata&lastNObservations=30 — columns CURRENCY, TIME_PERIOD, OBS_VALUE
  (units of CURRENCY per 1 EUR, 14:15 CET fixing, TARGET business days).
- MOF JGB constant-maturity yields (%), CSV, Shift-JIS footer:
  current month  https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv
  history        https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv
  (history runs to the end of the previous month, ~1.2 MB). Rows "YYYY/M/D,1Y,...,40Y";
  "-" = no value. Published with about a one-business-day lag.
- US 10Y from FRED DGS10 via gateway/fred_client (needs FRED_KEY; optional).
"""
from __future__ import annotations

import asyncio
import csv
import io
import re
from datetime import date, timedelta

import httpx

from marketmind.shadow_feeds import Feed

ECB_URL = ("https://data-api.ecb.europa.eu/service/data/EXR/D.USD+JPY+GBP+CNY+CHF.EUR.SP00.A"
           "?format=csvdata&lastNObservations=30")
JGB_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
JGB_HIST_URL = ("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
                "historical/jgbcme_all.csv")
TIMEOUT_S = 45.0
CURRENCIES = ("USD", "JPY", "GBP", "CNY", "CHF")
TENORS = ("2Y", "10Y", "30Y")
MONTH_DAYS = 30


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True,
                             headers={"User-Agent": "MarketMind/0.1"})


def _month_ago(rows: list[tuple[str, object]], last_date: str):
    """Latest row on or before last_date - 30 days (rows oldest first)."""
    cutoff = (date.fromisoformat(last_date) - timedelta(days=MONTH_DAYS)).isoformat()
    prior = [r for r in rows if r[0] <= cutoff]
    return prior[-1] if prior else None


# ── ECB ─────────────────────────────────────────────────────────────────────

def _px(v: float) -> str:
    return f"{v:.2f}" if v >= 20 else f"{v:.4f}"


def parse_ecb_csv(text: str) -> dict[str, list[tuple[str, float]]]:
    """currency -> [(date, units per EUR)] oldest first."""
    out: dict[str, list[tuple[str, float]]] = {}
    for r in csv.DictReader(io.StringIO(text or "")):
        try:
            row = (r["TIME_PERIOD"], float(r["OBS_VALUE"]))
        except (KeyError, TypeError, ValueError):
            continue
        out.setdefault(r["CURRENCY"], []).append(row)
    return {k: sorted(v) for k, v in out.items()}


def ecb_lines(series: dict[str, list[tuple[str, float]]]) -> list[str]:
    lines = []
    for ccy in CURRENCIES:
        rows = series.get(ccy) or []
        if not rows:
            lines.append(f"- EUR/{ccy}: no ECB observation")
            continue
        d, v = rows[-1]
        prev = _month_ago(rows, d)
        chg = (f", 1m {(v / prev[1] - 1) * 100:+.2f}% (vs {_px(prev[1])} on {prev[0]})"
               if prev else "")
        lines.append(f"- EUR/{ccy} {_px(v)} {ccy} per EUR ({d}){chg}")
    usd = series.get("USD") or []
    if usd:
        d, eurusd = usd[-1]
        crosses = []
        for ccy in ("JPY", "CNY", "CHF"):
            same = dict(series.get(ccy) or []).get(d)
            if same:
                crosses.append(f"USD/{ccy} {_px(same / eurusd)}")
        gbp = dict(series.get("GBP") or []).get(d)
        if gbp:
            crosses.append(f"GBP/USD {eurusd / gbp:.4f}")
        if crosses:
            lines.append(f"- Implied from the ECB fixing ({d}): " + ", ".join(crosses))
    return lines


# ── JGB ─────────────────────────────────────────────────────────────────────

_DATE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")


def parse_jgb_csv(raw: bytes | str) -> list[tuple[str, dict[str, float]]]:
    """[(date, {tenor: yield %})] oldest first; header row names the tenors."""
    text = raw.decode("cp932", errors="replace") if isinstance(raw, bytes) else raw
    header: list[str] | None = None
    out: dict[str, dict[str, float]] = {}
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if row[0].strip() == "Date":
            header = [c.strip() for c in row]
            continue
        m = _DATE.match(row[0].strip())
        if not m or header is None:
            continue
        d = date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        vals = {}
        for name, cell in zip(header[1:], row[1:]):
            try:
                vals[name] = float(cell)
            except ValueError:
                continue
        if vals:
            out[d] = vals
    return sorted(out.items())


def jgb_lines(rows: list[tuple[str, dict[str, float]]],
              us10y: tuple[str, float] | None) -> list[str]:
    rows = [r for r in rows if all(t in r[1] for t in TENORS)]
    if not rows:
        return []
    d, last = rows[-1]
    lines = ["- JGB yields (MOF, " + d + "): "
             + ", ".join(f"{t} {last[t]:.3f}%" for t in TENORS)]
    prev = _month_ago(rows, d)
    if prev:
        lines.append(f"- JGB 1m change (vs {prev[0]}): "
                     + ", ".join(f"{t} {(last[t] - prev[1][t]) * 100:+.1f}bp" for t in TENORS)
                     + f"; 2s30s curve {(last['30Y'] - last['2Y']) * 100:.0f}bp")
    if us10y is not None:
        ud, uv = us10y
        lines.append(f"- US10Y - JGB10Y: {uv:.2f}% ({ud}, FRED DGS10) - {last['10Y']:.3f}% ({d}) "
                     f"= {(uv - last['10Y']) * 100:.0f}bp")
    else:
        lines.append("- US10Y - JGB10Y: US 10Y unavailable (FRED DGS10)")
    return lines


# ── feeds ───────────────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    resp = await client.get(url)
    resp.raise_for_status()
    return resp


async def fetch_ecb(today: str) -> list[str]:
    async with _client() as c:
        resp = await _get(c, ECB_URL)
    series = parse_ecb_csv(resp.text)
    if not series:
        raise ValueError("ECB CSV had no observations")
    return ecb_lines(series)


async def _us10y() -> tuple[str, float] | None:
    try:
        from marketmind.gateway.fred_client import get_fred_series
        r = await get_fred_series("DGS10")
    except Exception:
        return None
    if not isinstance(r, dict) or r.get("error") or r.get("value") is None:
        return None
    return str(r.get("date") or "?"), float(r["value"])


async def fetch_jgb(today: str) -> list[str]:
    async with _client() as c:
        cur, hist, us = await asyncio.gather(_get(c, JGB_URL), _get(c, JGB_HIST_URL), _us10y(),
                                             return_exceptions=True)
    if isinstance(cur, Exception) and isinstance(hist, Exception):
        raise cur
    rows: dict[str, dict[str, float]] = {}
    for resp in (hist, cur):            # current month wins on overlap
        if not isinstance(resp, Exception):
            rows.update(parse_jgb_csv(resp.content))
    lines = jgb_lines(sorted(rows.items()), us if isinstance(us, tuple) else None)
    if not lines:
        raise ValueError("MOF JGB CSV had no complete rows")
    return lines


FEEDS = [
    Feed("ecb_fx", "ECB euro reference rates (official daily fixing)",
         ("currency_dealer", "carry_watch", "euro_watch"), fetch_ecb),
    Feed("jgb_yields", "Japan government bond yields (MOF, %)",
         ("currency_dealer", "carry_watch", "euro_watch"), fetch_jgb),
]
