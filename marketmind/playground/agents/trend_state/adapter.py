"""The trend state machine (marketmind.trend, docs/TREND_DESIGN.md) as a Playground agent.

No new rules: this wraps `trend.state.compute_states` on TREND_UNIVERSE with the
module's own TrendConfig (12-month excess return > T-bill, close > SMA200, 55-day
closing-high breakout; chandelier exit at highest close - 3 x ATR20; Moskowitz-Ooi-
Pedersen 2012, Faber 2007, the turtle rules). Zero LLM tokens.

A fresh entry signal (on one of the instrument's last 3 complete bars, still TREND)
becomes one long call. The ledger needs a fixed holding period and a fixed level, so:
  hold_bars  60 (the bridge maximum) as the stand-in for "until the trend exit";
  falsifier  close_below the chandelier stop in force at the signal. The ledger level
             does not trail upward like the state machine's stop, so a record may exit
             later than the state machine would.
Confidence: the instrument's 12-month excess-return percentile rank among all
instruments with data that day, 0.50 (lowest) to 0.65 (highest).
The bridge's signal_key (ticker + signal date) records each entry once.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

from marketmind.gateway.price_history import Bar
from marketmind.playground.agents import _quant as q

AGENT_ID = "trend_state"
MODEL = "trend_state_machine_v1"
HOLD = 60
FRESH_BARS = 3

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched."}


def excess_ranks(states: dict) -> dict[str, float]:
    """Percentile (0..1) of each available instrument's 12-month excess return."""
    ex = {t: s.ret_12m - (s.hurdle or 0.0) for t, s in states.items() if s.ret_12m is not None}
    order = sorted(ex, key=lambda t: (ex[t], t))
    n = len(order)
    return {t: (i / (n - 1) if n > 1 else 1.0) for i, t in enumerate(order)}


def build_calls(states: dict, histories: dict[str, Sequence[Bar] | None]) -> list[dict]:
    from marketmind.trend.state import TREND
    ranks = excess_ranks(states)
    calls = []
    for t, s in sorted(states.items()):
        bars = histories.get(t) or []
        if s.state != TREND or not s.entry_signal_date or len(bars) < FRESH_BARS:
            continue
        if s.entry_signal_date < bars[-FRESH_BARS].date or s.stop_level is None:
            continue                                  # an older entry, or no stop level
        pct = ranks.get(t, 0.0)
        conf = round(q.CONF_FLOOR + q.CONF_SPAN * pct, 4)
        text, rule = q.falsifier(t, "long", s.stop_level, s.atr or 0.0, HOLD,
                                 basis=f"吊灯止损：信号以来最高收盘 − 3×ATR20，ATR={s.atr}；账本止损不上移")
        signal = {"as_of": s.as_of, "close": s.close, "entry_signal_date": s.entry_signal_date,
                  "ret_12m": s.ret_12m, "hurdle": s.hurdle, "sma200": s.sma200,
                  "high_55": s.high_55, "atr": s.atr, "stop_level": s.stop_level,
                  "excess_rank_pct": q.r4(pct), "source": s.source}
        calls.append({
            "ticker": t, "direction": "long", "confidence": conf, "hold_bars": HOLD,
            "hold_days": HOLD,
            "thesis": (f"趋势状态机入场（{s.entry_signal_date}）：12 个月收益 {s.ret_12m:+.1%} > T-bill "
                       f"{(s.hurdle or 0):.2%}，收盘 {s.close} > SMA200 {s.sma200}，突破 55 日收盘高点 "
                       f"{s.high_55}；12 个月超额收益排名分位 {pct:.0%}"),
            "falsifier": text, "falsifier_rule": rule, "mental_model_used": MODEL,
            "signal_key": f"{t}:{s.entry_signal_date}", "signal": signal,
        })
    return calls


async def analyze(context: dict, *, mock: bool = False, fetch=None,
                  now: datetime | None = None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    from marketmind.trend.state import TREND, UNAVAILABLE, compute_states
    from marketmind.trend.universe import TREND_UNIVERSE
    today: date = q.utc_today(now)
    if fetch is None:
        from marketmind.trend.state import fetch_inputs as fetch
    histories, sources, hurdle, hurdle_source = await fetch(list(TREND_UNIVERSE))
    states = compute_states(histories, hurdle, hurdle_source=hurdle_source, today=today,
                            sources=sources)
    calls = build_calls(states, histories)
    out = {"directional_calls": calls, "as_of_run": today.isoformat(),
           "hurdle": q.r4(hurdle), "hurdle_source": hurdle_source,
           "in_trend": sorted(t for t, s in states.items() if s.state == TREND),
           "unavailable": {t: s.reason for t, s in states.items() if s.state == UNAVAILABLE}}
    if not calls:
        out["no_calls_reason"] = f"no fresh entry signal in the last {FRESH_BARS} bars"
    return out
