"""Crypto time-series momentum, 1-4 weeks, volatility-scaled, long/flat - pure code.

Evidence: Liu & Tsyvinski (2021), "Risks and Returns of Cryptocurrency", Review of
Financial Studies 34(6):2689-2727: strong time-series momentum in cryptocurrency returns
at one- to four-week horizons.

Pre-registered rule (house construction on the paper's horizons; not tuned):
  for each coin, r_k = return over the last k complete UTC-day bars, k = 7, 14, 21, 28;
  s_k = r_k / (sigma_ann * sqrt(k / 365)), sigma_ann = EWMA volatility with a 60-day
  centre of mass (agents/_quant, Moskowitz-Ooi-Pedersen 2012), i.e. each lookback's
  return in units of its own expected volatility; strength = mean(s_7..s_28).
  strength > 0 -> long, else flat (the owner's book is long-only). Confidence
  0.5 + 0.15 * min(1, strength / 2) (agents/_quant). Hold 7 bars (one week), stop at
  3 x Wilder ATR(20) below the signal close. At most one call per coin per ISO week
  (signal_key "<ticker>:<ISO week>").
Universe: large caps that Robinhood lists for trading (support article "Coin
availability", checked 2026-09-29) and whose exchange candles gateway.price_history
returned from this machine on 2026-09-29 (Binance, 729 complete daily bars each).
Missing / short / stale candles -> unavailable, never guessed. Zero LLM tokens.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Sequence

from marketmind.gateway.price_history import Bar
from marketmind.playground.agents import _quant as q

AGENT_ID = "crypto_tsmom"
MODEL = "crypto_tsmom_liu_tsyvinski_2021"
UNIVERSE: tuple[str, ...] = ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD",
                             "ADA-USD", "LINK-USD", "LTC-USD", "BCH-USD", "AVAX-USD")
LOOKBACKS = (7, 14, 21, 28)
HOLD = 7
MIN_BARS = 3 * q.MOP_COM + 1          # a full EWMA window

MOCK_OUTPUT = {"directional_calls": [], "no_calls_reason": "Mock mode - no data fetched."}


def signals(histories: dict[str, Sequence[Bar] | None],
            today: date) -> tuple[dict[str, dict], dict[str, str]]:
    rows, missing = {}, {}
    for t in UNIVERSE:
        bars = histories.get(t)
        why = q.unavailable(t, bars, MIN_BARS, today)
        vol = None if why else q.ewma_vol(bars, t)
        rets = {} if why else {k: q.trailing(bars, k) for k in LOOKBACKS}
        if not why and (vol is None or vol <= 0 or any(r is None for r in rets.values())):
            why = "returns or volatility not computable"
        if why:
            missing[t] = why
            continue
        scaled = {k: r / (vol * math.sqrt(k / 365)) for k, r in rets.items()}
        strength = sum(scaled.values()) / len(scaled)
        rows[t] = {"as_of": bars[-1].date, "close": bars[-1].close,
                   "ret": {f"{k}d": q.r4(r) for k, r in rets.items()},
                   "scaled": {f"{k}d": q.r4(s) for k, s in scaled.items()},
                   "vol_ann": q.r4(vol), "strength": q.r4(strength),
                   "direction": "long" if strength > 0 else None}
    return rows, missing


def build_calls(rows: dict[str, dict], histories: dict, week: str) -> tuple[list[dict], dict]:
    calls, missing = [], {}
    for t, s in rows.items():
        if s["direction"] is None:
            continue
        stop = q.atr_stop(histories[t], "long")
        if stop is None:
            missing[t] = "ATR20 not computable (no stop)"
            continue
        text, rule = q.falsifier(t, "long", stop[0], stop[1], HOLD)
        rets = " / ".join(f"{k} {v:+.1%}" for k, v in s["ret"].items())
        calls.append({
            "ticker": t, "direction": "long", "confidence": q.confidence(s["strength"]),
            "hold_bars": HOLD, "hold_days": HOLD,
            "thesis": (f"加密 TSMOM：{t} 过去 1–4 周收益 {rets}，年化波动 {s['vol_ann']:.0%}，"
                       f"波动缩放后平均强度 {s['strength']:+.2f} → 做多，持有 {HOLD} 根"
                       f"（Liu & Tsyvinski 2021）"),
            "falsifier": text, "falsifier_rule": rule, "mental_model_used": MODEL,
            "signal_key": f"{t}:{week}", "signal": {**s, "stop": stop[0], "atr20": round(stop[1], 6)},
        })
    return calls, missing


async def _default_fetch(tickers: list[str]) -> dict[str, list[Bar] | None]:
    from marketmind.gateway.price_history import complete_bars, get_price_histories
    hists = await get_price_histories(tickers, years=1)
    return {t: (complete_bars(t, h.daily) if h else None) for t, h in hists.items()}


async def analyze(context: dict, *, mock: bool = False, fetch=None,
                  now: datetime | None = None) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    today = q.utc_today(now)
    week = q.week_key(today)
    histories = await (fetch or _default_fetch)(list(UNIVERSE))
    rows, missing = signals(histories, today)
    calls, no_stop = build_calls(rows, histories, week)
    missing.update(no_stop)
    out = {"directional_calls": calls, "as_of_run": today.isoformat(), "week": week,
           "signals": rows, "unavailable": missing}
    if not calls:
        out["no_calls_reason"] = "no coin with usable data and positive 1-4 week momentum"
    return out
