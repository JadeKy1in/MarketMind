"""Volatility term structure from Cboe's public daily index history CSVs.

Source: https://cdn.cboe.com/api/global/us_indices/daily_prices/<SYMBOL>_History.csv
(redirects to cdn-api.cboe.com; columns DATE,OPEN,HIGH,LOW,CLOSE, SKEW has DATE,SKEW).
All numbers are index points at the Cboe daily close; ratios are computed here.
"""
from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime

import httpx

from marketmind.shadow_feeds import Feed

CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
SYMBOLS = ("VIX", "VIX9D", "VIX3M", "SKEW")
PERCENTILE_WINDOW = 20
HTTP_TIMEOUT_S = 30.0
_TRANSPORT: httpx.AsyncBaseTransport | None = None      # tests inject httpx.MockTransport


def parse_history(text: str) -> list[tuple[str, float]]:
    """[(YYYY-MM-DD, close)] in date order; the close is the last column."""
    rows = list(csv.reader(io.StringIO(text.strip())))
    if not rows or rows[0][0].strip().upper() != "DATE":
        raise ValueError("unexpected Cboe CSV header")
    out = []
    for r in rows[1:]:
        if len(r) < 2 or not r[-1].strip():
            continue
        d = datetime.strptime(r[0].strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
        out.append((d, float(r[-1])))
    if not out:
        raise ValueError("empty Cboe history")
    out.sort()
    return out


async def fetch_histories(symbols=SYMBOLS) -> dict[str, list[tuple[str, float]]]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=True,
                                 transport=_TRANSPORT,
                                 headers={"User-Agent": "Mozilla/5.0 MarketMind"}) as c:
        async def one(s):
            r = await c.get(CBOE_URL.format(symbol=s))
            r.raise_for_status()
            return s, parse_history(r.text)
        return dict(await asyncio.gather(*(one(s) for s in symbols)))


def _at(hist: list[tuple[str, float]], date: str) -> float | None:
    return dict(hist).get(date)


def build_lines(h: dict[str, list[tuple[str, float]]]) -> list[str]:
    vix = h["VIX"]
    d, v = vix[-1]
    lines = []
    chg = f", {v - vix[-2][1]:+.2f} vs {vix[-2][0]}" if len(vix) > 1 else ""
    lines.append(f"- VIX {v:.2f} (Cboe close {d}{chg})")
    for s in ("VIX9D", "VIX3M"):
        sd, sv = h[s][-1]
        lines.append(f"- {s} {sv:.2f} (Cboe close {sd})")
    v9, v3 = _at(h["VIX9D"], d), _at(h["VIX3M"], d)
    if v9 is not None:
        r = v9 / v
        lines.append(f"- VIX9D/VIX {r:.3f} on {d} ({'>1: 9-day above 30-day, near-term stress' if r > 1 else '<1: near-term calmer than 30-day'})")
    if v3 is not None:
        r = v / v3
        lines.append(f"- VIX/VIX3M {r:.3f} on {d} ({'>1: backwardation (stress)' if r > 1 else '<1: contango (normal)'})")
    last = [c for _, c in vix[-PERCENTILE_WINDOW:]]
    pct = 100.0 * sum(1 for c in last if c <= v) / len(last)
    lines.append(f"- VIX {len(last)}-day percentile {pct:.0f}% (share of last {len(last)} closes <= "
                 f"latest; range {min(last):.2f}-{max(last):.2f}, {vix[-len(last)][0]} to {d})")
    sd, sk = h["SKEW"][-1]
    sk_last = [c for _, c in h["SKEW"][-PERCENTILE_WINDOW:]]
    lines.append(f"- SKEW {sk:.2f} (Cboe close {sd}; {len(sk_last)}-day avg {sum(sk_last) / len(sk_last):.2f}; "
                 f">100 = priced tail risk)")
    return lines


async def fetch(today: str) -> list[str]:
    return build_lines(await fetch_histories())


FEEDS = [Feed("cboe_vol_term", "Volatility term structure (Cboe VIX / VIX9D / VIX3M / SKEW)",
              ("vega_trader", "vol_surfer", "crash_hunter", "cycle_reader"), fetch)]
