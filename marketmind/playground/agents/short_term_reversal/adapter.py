"""Short-term (weekly) reversal on the 11 Select Sector SPDR ETFs - pure code.

Jegadeesh (1990, JF 45:881-898) and Lehmann (1990, QJE 105:1-28): last week's
relative losers outperform last week's relative winners over the following week
(Lehmann's contrarian portfolio weights securities by minus their return relative to
the cross-sectional mean). Parameters fixed from those papers: 5-bar (one week)
formation, 5-bar hold, weekly rebalance. Zero LLM tokens.

Long-only (the owner's live book is long-only, SPEC_v3 §1): each week buy the two
biggest relative losers (the bottom ~quintile of 11). The short leg of the papers is
left out on purpose, so this agent tests the loser leg only.
Caveat recorded up front: the papers study individual stocks; at the industry level
short-horizon returns tend to continue rather than reverse (Moskowitz & Grinblatt
1999, JF 54:1249-1290), so this agent may well be a negative baseline.

One record set per ISO week (the bridge's signal_key is the week), on the first run
of the week, from the last 5 complete bars.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Sequence

from marketmind.gateway.price_history import Bar
from marketmind.playground.agents import _quant as q

AGENT_ID = "short_term_reversal"
MODEL = "weekly_reversal_jegadeesh_1990_lehmann_1990"
UNIVERSE: tuple[str, ...] = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE",
                             "XLU", "XLV", "XLY")
FORMATION = 5
HOLD = 5
N_LONG = 2
MIN_CROSS_SECTION = 8          # of 11: fewer aligned ETFs -> no ranking

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched."}


def signals(histories: dict[str, Sequence[Bar] | None],
            today: date) -> tuple[dict[str, dict], dict[str, str], str | None]:
    """({ticker: facts incl. rank and z}, {ticker: unavailable reason}, cross-section date).
    Only ETFs whose last complete bar is the common (latest) date are ranked."""
    missing: dict[str, str] = {}
    usable: dict[str, Sequence[Bar]] = {}
    for t in UNIVERSE:
        bars = histories.get(t)
        why = q.unavailable(t, bars, q.ATR_PERIOD + 2, today)
        if why:
            missing[t] = why
        else:
            usable[t] = bars
    if not usable:
        return {}, missing, None
    as_of = max(b[-1].date for b in usable.values())
    rets: dict[str, float] = {}
    for t, bars in usable.items():
        r = q.trailing(bars, FORMATION)
        if bars[-1].date != as_of:
            missing[t] = f"misaligned: last complete bar {bars[-1].date}, cross-section {as_of}"
        elif r is None:
            missing[t] = "5-bar return not computable"
        else:
            rets[t] = r
    if len(rets) < MIN_CROSS_SECTION:
        return {}, missing, as_of
    mean = sum(rets.values()) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets.values()) / len(rets))
    order = sorted(rets, key=lambda t: (rets[t], t))            # biggest loser first
    rows = {t: {"as_of": as_of, "close": usable[t][-1].close, "ret_5d": q.r4(rets[t]),
                "cross_mean": q.r4(mean), "cross_sd": q.r4(sd),
                "z": q.r4((rets[t] - mean) / sd) if sd > 0 else 0.0,
                "rank": i + 1, "n": len(rets)} for i, t in enumerate(order)}
    return rows, missing, as_of


def build_calls(rows: dict[str, dict], histories: dict, week: str) -> tuple[list[dict], dict]:
    calls, missing = [], {}
    losers = [t for t, s in sorted(rows.items(), key=lambda kv: kv[1]["rank"])][:N_LONG]
    for t in losers:
        s = rows[t]
        if s["z"] >= 0:                  # a flat cross-section has no relative loser
            continue
        stop = q.atr_stop(histories[t], "long")
        if stop is None:
            missing[t] = "ATR20 not computable (no stop)"
            continue
        text, rule = q.falsifier(t, "long", stop[0], stop[1], HOLD)
        calls.append({
            "ticker": t, "direction": "long", "confidence": q.confidence(-s["z"]),
            "hold_bars": HOLD, "hold_days": HOLD,
            "thesis": (f"周度反转：{t} 过去 5 根 K 线收益 {s['ret_5d']:+.2%}，在 {s['n']} 个行业 ETF 中排第 "
                       f"{s['rank']}（均值 {s['cross_mean']:+.2%}，z={s['z']:+.2f}）→ 买入上周相对输家，持有 5 根"
                       f"（Jegadeesh 1990 / Lehmann 1990，只做多）"),
            "falsifier": text, "falsifier_rule": rule, "mental_model_used": MODEL,
            "signal_key": week, "signal": s,
        })
    return calls, missing


async def analyze(context: dict, *, mock: bool = False, fetch=None,
                  now: datetime | None = None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    week = q.week_key(today)
    if fetch is None:
        from marketmind.trend.state import fetch_inputs as fetch
    histories, sources, _, _ = await fetch(list(UNIVERSE))
    rows, missing, as_of = signals(histories, today)
    calls, no_stop = build_calls(rows, histories, week) if rows else ([], {})
    missing.update(no_stop)
    out = {"directional_calls": calls, "as_of_run": today.isoformat(), "week": week,
           "cross_section_date": as_of, "signals": rows, "unavailable": missing,
           "sources": {t: sources.get(t) for t in rows}}
    if not calls:
        out["no_calls_reason"] = (f"fewer than {MIN_CROSS_SECTION} sector ETFs with aligned data"
                                  if not rows else "no relative loser (flat cross-section)")
    return out
