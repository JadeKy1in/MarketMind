"""Time-series momentum (Moskowitz, Ooi & Pedersen 2012, JFE 104:228-250) - pure code.

Rule (parameters from the paper, not tuned): once a month, for each instrument, the
sign of its past 12-month excess return (return minus the T-bill hurdle) is the
position: long if positive, short if negative. The paper scales each position by
40% / ex-ante volatility (EWMA, centre of mass 60 days); here that volatility turns
the 12-month excess return into a strength (excess / annual vol), which sets the
confidence (see agents/_quant). One-month holding. Zero LLM tokens.

Calls are made only in the monthly rebalance window (calendar days 1-7, UTC); the
ledger bridge's signal_key records each instrument once per month.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

from marketmind.gateway.price_history import Bar
from marketmind.playground.agents import _quant as q

AGENT_ID = "tsmom"
MODEL = "tsmom_moskowitz_ooi_pedersen_2012"
UNIVERSE: tuple[str, ...] = ("SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD",
                             "DBC", "USO", "BTC-USD", "ETH-USD")

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched."}


def signals(histories: dict[str, Sequence[Bar] | None], hurdle: float,
            today: date) -> tuple[dict[str, dict], dict[str, str]]:
    """({ticker: signal facts}, {ticker: unavailable reason}) for the whole universe."""
    rows: dict[str, dict] = {}
    missing: dict[str, str] = {}
    for t in UNIVERSE:
        bars = histories.get(t)
        n = q.momentum_bars(t)
        why = q.unavailable(t, bars, n + 1, today)
        r12 = vol = None
        if why is None:
            r12, vol = q.trailing(bars, n), q.ewma_vol(bars, t)
            if r12 is None or vol is None or vol <= 0:
                why = "12-month return or volatility not computable"
        if why:
            missing[t] = why
            continue
        excess = r12 - hurdle
        rows[t] = {"as_of": bars[-1].date, "close": bars[-1].close, "ret_12m": q.r4(r12),
                   "hurdle": q.r4(hurdle), "excess_12m": q.r4(excess), "vol_ann": q.r4(vol),
                   "strength": q.r4(excess / vol),
                   "direction": "long" if excess > 0 else "short" if excess < 0 else None}
    return rows, missing


def build_calls(rows: dict[str, dict], histories: dict, month: str) -> tuple[list[dict], dict]:
    calls, missing = [], {}
    for t, s in rows.items():
        if s["direction"] is None:
            continue
        stop = q.atr_stop(histories[t], s["direction"])
        if stop is None:
            missing[t] = "ATR20 not computable (no stop)"
            continue
        hold = q.hold_month(t)
        text, rule = q.falsifier(t, s["direction"], stop[0], stop[1], hold)
        side = "做多" if s["direction"] == "long" else "做空"
        calls.append({
            "ticker": t, "direction": s["direction"], "confidence": q.confidence(s["strength"]),
            "hold_bars": hold, "hold_days": hold,
            "thesis": (f"TSMOM：12 个月收益 {s['ret_12m']:+.1%}，减 T-bill {s['hurdle']:.2%} 后超额 "
                       f"{s['excess_12m']:+.1%}，年化波动 {s['vol_ann']:.1%}（强度 {s['strength']:+.2f}）"
                       f" → {side}，持有一个月（Moskowitz-Ooi-Pedersen 2012）"),
            "falsifier": text, "falsifier_rule": rule, "mental_model_used": MODEL,
            "signal_key": f"{month}:{t}", "signal": s,
        })
    return calls, missing


async def analyze(context: dict, *, mock: bool = False, fetch=None,
                  now: datetime | None = None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    month = q.month_rebalance_key(today)
    if month is None:
        return {"directional_calls": [], "as_of_run": today.isoformat(),
                "no_calls_reason": "not a rebalance window: monthly, calendar days 1-7 (UTC)"}
    if fetch is None:
        from marketmind.trend.state import fetch_inputs as fetch
    histories, sources, hurdle, hurdle_source = await fetch(list(UNIVERSE))
    if hurdle_source.startswith("unavailable"):
        return {"directional_calls": [], "as_of_run": today.isoformat(),
                "no_calls_reason": "T-bill hurdle (^IRX) unavailable: excess return not computable"}
    rows, missing = signals(histories, hurdle, today)
    calls, no_stop = build_calls(rows, histories, month)
    missing.update(no_stop)
    out = {"directional_calls": calls, "as_of_run": today.isoformat(), "rebalance": month,
           "hurdle_source": hurdle_source, "signals": rows, "unavailable": missing,
           "sources": {t: sources.get(t) for t in rows}}
    if not calls:
        out["no_calls_reason"] = "no instrument with usable data and a non-zero signal"
    return out
