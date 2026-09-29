"""Dual momentum (Antonacci 2012, "Risk Premia Harvesting Through Dual Momentum",
SSRN 2042750; J. Management & Entrepreneurship 2017) - pure code, long-only.

Rule (lookback from the paper, not tuned): once a month, relative momentum picks the
risk asset with the highest 12-month return among SPY, EFA and BTC-USD; absolute
momentum then holds it only if that return beats the 12-month T-bill return
("To determine absolute momentum, we see if an asset has outperformed Treasury bills
over the past year"); otherwise hold bonds (IEF, or TLT if IEF has no data; the paper
uses aggregate bonds). One call per month. Zero LLM tokens.

The Playground is not under the shadows' daily forced-decision rule (ledger_bridge):
between rebalances this agent records nothing, so every record is a real monthly
decision and holdings never overlap. The rebalance is the first run in calendar days
1-7 (UTC); the bridge's signal_key (the month) records it once.
Confidence: 0.50-0.65 from the winner's 12-month excess return / annual volatility;
a bond fallback is a rule, not a belief, and gets 0.50.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

from marketmind.gateway.price_history import Bar
from marketmind.playground.agents import _quant as q

AGENT_ID = "dual_momentum"
MODEL = "dual_momentum_antonacci_2012"
RISK: tuple[str, ...] = ("SPY", "EFA", "BTC-USD")
SAFE: tuple[str, ...] = ("IEF", "TLT")                 # first with data wins

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched."}


def decide(histories: dict[str, Sequence[Bar] | None], hurdle: float,
           today: date) -> dict:
    """{'pick', 'reason', 'returns', 'unavailable', ...}; pick is None when undecidable."""
    rets: dict[str, float] = {}
    missing: dict[str, str] = {}
    for t in RISK + SAFE:
        bars = histories.get(t)
        n = q.momentum_bars(t)
        why = q.unavailable(t, bars, n + 1, today)
        r = None if why else q.trailing(bars, n)
        if r is None:
            missing[t] = why or "12-month return not computable"
        else:
            rets[t] = r
    out = {"returns": {t: q.r4(r) for t, r in rets.items()}, "hurdle": q.r4(hurdle),
           "unavailable": missing, "pick": None}
    lacking = [t for t in RISK if t not in rets]
    if lacking:
        out["reason"] = f"relative momentum needs all of {', '.join(RISK)}; missing {', '.join(lacking)}"
        return out
    winner = max(RISK, key=lambda t: (rets[t], t))
    out["winner"] = winner
    if rets[winner] > hurdle:
        out.update(pick=winner, leg="risk",
                   reason=f"{winner} 12 个月收益 {rets[winner]:+.1%} 最高且高于 T-bill {hurdle:.2%}")
        return out
    safe = next((t for t in SAFE if t in rets), None)
    if safe is None:
        out["reason"] = "absolute momentum says bonds, but IEF and TLT have no usable data"
        return out
    out.update(pick=safe, leg="bonds",
               reason=f"最强的 {winner} 12 个月收益 {rets[winner]:+.1%} 未超过 T-bill {hurdle:.2%} → 债券 {safe}")
    return out


def build_call(d: dict, histories: dict, month: str) -> tuple[dict | None, str | None]:
    t = d["pick"]
    bars = histories[t]
    stop = q.atr_stop(bars, "long")
    if stop is None:
        return None, f"{t}: ATR20 not computable (no stop)"
    if d["leg"] == "risk":
        vol = q.ewma_vol(bars, t)
        strength = (d["returns"][t] - d["hurdle"]) / vol if vol else 0.0
        conf = q.confidence(strength)
    else:
        strength, conf = None, q.CONF_FLOOR
    hold = q.hold_month(t)
    text, rule = q.falsifier(t, "long", stop[0], stop[1], hold)
    signal = {"as_of": bars[-1].date, "close": bars[-1].close, "leg": d["leg"],
              "winner": d["winner"], "returns_12m": d["returns"], "hurdle": d["hurdle"],
              "strength": q.r4(strength)}
    return {"ticker": t, "direction": "long", "confidence": conf, "hold_bars": hold,
            "hold_days": hold,
            "thesis": f"双动量月度调仓：{d['reason']}；持有一个月（Antonacci 2012）",
            "falsifier": text, "falsifier_rule": rule, "mental_model_used": MODEL,
            "signal_key": month, "signal": signal}, None


async def analyze(context: dict, *, mock: bool = False, fetch=None,
                  now: datetime | None = None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    month = q.month_rebalance_key(today)
    if month is None:
        return {"directional_calls": [], "as_of_run": today.isoformat(),
                "no_calls_reason": "not a rebalance window: monthly, calendar days 1-7 (UTC); "
                                   "no record between rebalances"}
    if fetch is None:
        from marketmind.trend.state import fetch_inputs as fetch
    histories, sources, hurdle, hurdle_source = await fetch(list(RISK + SAFE))
    if hurdle_source.startswith("unavailable"):
        return {"directional_calls": [], "as_of_run": today.isoformat(),
                "no_calls_reason": "T-bill hurdle (^IRX) unavailable: absolute momentum not computable"}
    d = decide(histories, hurdle, today)
    out = {"directional_calls": [], "as_of_run": today.isoformat(), "rebalance": month,
           "hurdle_source": hurdle_source, "decision": d}
    if d["pick"] is None:
        out["no_calls_reason"] = d["reason"]
        return out
    call, why = build_call(d, histories, month)
    if call is None:
        out["no_calls_reason"] = why
    else:
        out["directional_calls"] = [call]
    return out
