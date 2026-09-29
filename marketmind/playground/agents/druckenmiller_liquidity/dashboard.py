"""Weekly liquidity dashboard and rule gate of the Druckenmiller agent - code only (SPEC L3).

Net liquidity (FRED, all converted to billions of USD):
    net = WALCL / 1000 - WTREGEN / 1000 - RRPONTSYD
  WALCL      Fed total assets, Wednesday level, millions USD (H.4.1)
  WTREGEN    Treasury General Account, week average ending Wednesday, millions USD (H.4.1)
  RRPONTSYD  overnight reverse repo take-up, daily, billions USD (NY Fed)
  One point per WALCL Wednesday: the TGA week ending that Wednesday, the RRP of that day
  (else the latest within 5 days before). Mixing a Wednesday level with a week average
  is the usual practical shortcut of this formula; the error is small next to 13-week moves.
Impulse over weekly points: d4 = net - net 4 weeks earlier, d13 = 13 weeks earlier.
  rising   d13 > +0.5 % of net and d4 > 0
  falling  d13 < -0.5 % of net and d4 < 0
  mixed    otherwise                         (0.5 % ~ $30B today; a prior, not tuned)
Context (reported, and shown to the LLM; not part of the gate except DGS10 for TLT):
  DGS2 / DGS10 (%), 4- and 13-week change in percentage points; DTWEXBGS broad dollar
  index and its 13-week % change; BAMLH0A0HYM2 high-yield OAS (%) and 13-week change.
Trend states of SPY QQQ TLT GLD BTC-USD: marketmind.trend.state on complete daily bars
(the same code that writes data/trend/<date>.json), recomputed so that last week's state
is available too.

Gate (both sides must agree - liquidity impulse and the asset's own trend):
  long  candidate  impulse rising AND the asset's trend state is TREND
  short candidate  TLT only: impulse falling AND TLT is CASH or EXIT AND close < SMA200
                   AND the 10-year yield rose >= 0.25 pp over 13 weeks. Rates are the one
                   place the framework is explicitly two-sided (Druckenmiller's largest
                   wins were bond positions, both ways); for equities, gold and bitcoin a
                   falling impulse only means stand aside.
  stand aside      everything else, with the reason.
A candidate is fresh when it is in the gate now and was in none of the weekly gates of
the previous 13 weeks (as of D-7, D-14, ..., D-91: the impulse horizon). Only fresh
candidates go to the LLM, so an open gate is offered once, and a gate that flickers
open / shut is not re-offered every few weeks. The 13-week cooldown is a cost setting:
with a 1-week lookback the gate opened in ~8.8 weeks a year on 2023-01..2026-09 data,
with 13 weeks ~4.4 (owner target 2-6 LLM calls a year); no returns were looked at.

Point in time: an evaluation "as of" day D uses observations dated before D and bars
dated on or before D. FRED revises little in these series; revisions are not modelled.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

from marketmind.gateway.price_history import Bar
from marketmind.trend.rules import TrendConfig
from marketmind.trend.state import (CASH, EXIT, TREND, UNAVAILABLE, simulate, state_from_sim,
                                    unavailable_state)

logger = logging.getLogger("marketmind.playground.druckenmiller_liquidity")

SERIES = ("WALCL", "WTREGEN", "RRPONTSYD", "DGS2", "DGS10", "DTWEXBGS", "BAMLH0A0HYM2")
ASSETS = ("SPY", "QQQ", "TLT", "GLD", "BTC-USD")
SHORTABLE = ("TLT",)
HISTORY_DAYS = 400
DEADBAND = 0.005
TLT_SHORT_YIELD_RISE = 0.25                      # percentage points over 13 weeks
MAX_WEEKLY_AGE = 14                              # days: WALCL older than this -> unavailable
MAX_DAILY_AGE = 7
RRP_LOOKBACK = 5
TGA_LOOKBACK = 6
FRESH_DAYS = 7                                   # weekly evaluation grid
COOLDOWN_WEEKS = 13

Obs = list[tuple[str, float]]


# ── FRED history (network; tests pass their own) ───────────────────────────

async def fetch_fred(series: Sequence[str], today: date, days: int = HISTORY_DAYS
                     ) -> dict[str, Obs | str]:
    """{series id: ascending [(date, value)]} or an error string per series. The URL
    carries the key: errors are redacted before they are logged or returned."""
    import asyncio

    import httpx

    from marketmind.gateway.fragility_inputs import _parse_fred_observations
    from marketmind.gateway.fred_client import _FRED_BASE, _get_fred_key, _redact
    key = _get_fred_key()
    if not key:
        return {s: "FRED key not configured (FRED_KEY)" for s in series}
    start = (today - timedelta(days=days)).isoformat()

    async def one(client, sid):
        try:
            resp = await client.get(_FRED_BASE, params={
                "series_id": sid, "api_key": key, "file_type": "json",
                "observation_start": start, "sort_order": "asc"})
            resp.raise_for_status()
            return sorted(_parse_fred_observations(resp.json()))
        except Exception as exc:                # noqa: BLE001 - reported per series
            msg = _redact(str(exc))
            logger.warning("FRED %s failed: %s", sid, msg)
            return f"FRED {sid} unavailable ({type(exc).__name__})"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        rows = await asyncio.gather(*(one(client, s) for s in series))
    return dict(zip(series, rows))


# ── helpers ────────────────────────────────────────────────────────────────

def _before(obs: Obs, cutoff: str) -> Obs:
    return [(d, v) for d, v in obs if d < cutoff]


def _latest_on_or_before(obs: Obs, day: str, lookback: int) -> float | None:
    lo = (date.fromisoformat(day) - timedelta(days=lookback)).isoformat()
    vals = [v for d, v in obs if lo <= d <= day]
    return vals[-1] if vals else None


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


def net_liquidity(walcl: Obs, tga: Obs, rrp: Obs) -> list[dict]:
    """Weekly points {date, net, walcl, tga, rrp} in billions USD (see module docstring)."""
    out = []
    for d, w in walcl:
        t = _latest_on_or_before(tga, d, TGA_LOOKBACK)
        r = _latest_on_or_before(rrp, d, RRP_LOOKBACK)
        if t is None or r is None:
            continue
        out.append({"date": d, "walcl": w / 1000, "tga": t / 1000, "rrp": r,
                    "net": w / 1000 - t / 1000 - r})
    return out


def impulse(points: list[dict], as_of: date) -> dict:
    """Net-liquidity level, 4 / 13-week change and the impulse label as of `as_of`."""
    pts = [p for p in points if p["date"] < as_of.isoformat()]
    if len(pts) < 14:
        return {"impulse": UNAVAILABLE, "reason": f"only {len(pts)} weekly net-liquidity points (< 14)"}
    last = pts[-1]
    age = (as_of - date.fromisoformat(last["date"])).days
    if age > MAX_WEEKLY_AGE:
        return {"impulse": UNAVAILABLE, "reason": f"stale: last H.4.1 point {last['date']} ({age} days)"}
    net, d4, d13 = last["net"], last["net"] - pts[-5]["net"], last["net"] - pts[-14]["net"]
    band = DEADBAND * abs(net)
    label = ("rising" if d13 > band and d4 > 0 else
             "falling" if d13 < -band and d4 < 0 else "mixed")
    return {"impulse": label, "as_of": last["date"], "net_bn": _r(net, 1),
            "walcl_bn": _r(last["walcl"], 1), "tga_bn": _r(last["tga"], 1), "rrp_bn": _r(last["rrp"], 1),
            "d4_bn": _r(d4, 1), "d13_bn": _r(d13, 1), "d4_pct": _r(d4 / net), "d13_pct": _r(d13 / net),
            "deadband_bn": _r(band, 1), "from_4w": pts[-5]["date"], "from_13w": pts[-14]["date"]}


def change(obs: Obs | str | None, as_of: date, days: int, pct: bool = False) -> dict:
    """Latest value before as_of (<= MAX_DAILY_AGE days old) and its change over `days`."""
    if not isinstance(obs, list):
        return {"value": None, "reason": obs or "no data"}
    pts = _before(obs, as_of.isoformat())
    if not pts:
        return {"value": None, "reason": "no observation"}
    d, v = pts[-1]
    if (as_of - date.fromisoformat(d)).days > MAX_DAILY_AGE:
        return {"value": None, "reason": f"stale ({d})"}
    then = [x for x in pts if x[0] <= (date.fromisoformat(d) - timedelta(days=days)).isoformat()]
    if not then:
        return {"value": v, "as_of": d, "change": None}
    base = then[-1][1]
    delta = (v / base - 1) if pct and base else (v - base)
    return {"value": v, "as_of": d, "change": _r(delta), "from": then[-1][0],
            "unit": "pct" if pct else "pp"}


def dashboard(fred: dict[str, Obs | str], as_of: date) -> dict:
    """All dashboard numbers as of `as_of` (unavailable pieces carry a reason)."""
    missing = {s: v for s, v in fred.items() if not isinstance(v, list)}
    if any(s in missing for s in ("WALCL", "WTREGEN", "RRPONTSYD")):
        liq = {"impulse": UNAVAILABLE,
               "reason": "; ".join(f"{s}: {missing[s]}" for s in ("WALCL", "WTREGEN", "RRPONTSYD")
                                   if s in missing)}
    else:
        liq = impulse(net_liquidity(fred["WALCL"], fred["WTREGEN"], fred["RRPONTSYD"]), as_of)
    return {"as_of": as_of.isoformat(), "liquidity": liq,
            "dgs2": {"4w": change(fred.get("DGS2"), as_of, 28), "13w": change(fred.get("DGS2"), as_of, 91)},
            "dgs10": {"4w": change(fred.get("DGS10"), as_of, 28), "13w": change(fred.get("DGS10"), as_of, 91)},
            "usd_broad": change(fred.get("DTWEXBGS"), as_of, 91, pct=True),
            "hy_oas": change(fred.get("BAMLH0A0HYM2"), as_of, 91)}


# ── trend states ───────────────────────────────────────────────────────────

def trend_at(ticker: str, bars: Sequence[Bar] | None, hurdle: float, as_of: date,
             cfg: TrendConfig | None = None) -> dict:
    """marketmind.trend state of `ticker` on the bars dated on or before `as_of`."""
    cfg = cfg or TrendConfig()
    sub = [b for b in bars or [] if b.date <= as_of.isoformat()]
    bad = unavailable_state(ticker, sub, cfg, as_of)
    if bad is not None:
        return {"state": UNAVAILABLE, "reason": bad.reason}
    st = state_from_sim(simulate(ticker, sub, cfg, hurdle), cfg)
    return {"state": st.state, "as_of": st.as_of, "close": st.close, "sma200": st.sma200,
            "ret_12m": st.ret_12m, "hurdle": _r(hurdle), "stop_level": st.stop_level,
            "entry_signal_date": st.entry_signal_date, "reason": st.reason}


# ── gate ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Candidate:
    ticker: str
    direction: str            # long | short
    why: str


def gate(dash: dict, trends: dict[str, dict]) -> tuple[list[Candidate], dict[str, str]]:
    """(candidates, {ticker: why stand aside}) - see the module docstring."""
    liq = dash["liquidity"]["impulse"]
    y13 = dash["dgs10"]["13w"].get("change")
    cands, aside = [], {}
    for t in ASSETS:
        tr = trends.get(t) or {"state": UNAVAILABLE, "reason": "no bars"}
        st = tr["state"]
        if liq == UNAVAILABLE:
            aside[t] = "liquidity impulse unavailable"
        elif st == UNAVAILABLE:
            aside[t] = f"trend unavailable ({tr.get('reason')})"
        elif liq == "rising" and st == TREND:
            cands.append(Candidate(t, "long", "net liquidity rising (13w and 4w) and trend state TREND"))
        elif (t in SHORTABLE and liq == "falling" and st in (CASH, EXIT)
              and tr.get("sma200") is not None and tr["close"] < tr["sma200"]
              and y13 is not None and y13 >= TLT_SHORT_YIELD_RISE):
            cands.append(Candidate(t, "short", f"net liquidity falling, {t} {st} below SMA200, "
                                               f"10y yield +{y13:.2f} pp in 13 weeks"))
        elif liq == "mixed":
            aside[t] = f"liquidity impulse mixed; trend {st}"
        elif liq == "rising":
            aside[t] = f"liquidity rising but trend {st} (no agreement)"
        else:
            aside[t] = f"liquidity falling, trend {st}: stand aside"
    return cands, aside


def fresh(now: list[Candidate], recent: list[set[tuple[str, str]]]) -> list[Candidate]:
    """Candidates in none of the `recent` weekly gates ({(ticker, direction)} each)."""
    seen = set().union(*recent) if recent else set()
    return [c for c in now if (c.ticker, c.direction) not in seen]


def gate_on(fred: dict, bars: dict, hurdle: float, day: date) -> tuple[dict, dict, list[Candidate], dict]:
    """(dashboard, trends, candidates, stand aside) as of `day`."""
    dash = dashboard(fred, day)
    trends = {t: trend_at(t, bars.get(t), hurdle, day) for t in ASSETS}
    cands, aside = gate(dash, trends)
    return dash, trends, cands, aside


def _keys(cands: list[Candidate]) -> set[tuple[str, str]]:
    return {(c.ticker, c.direction) for c in cands}


def evaluate(fred: dict, bars: dict, hurdle: float, as_of: date) -> dict:
    """Dashboard, trends and gate now; the gates of the previous COOLDOWN_WEEKS weeks;
    fresh candidates."""
    dash, trends, cands, aside = gate_on(fred, bars, hurdle, as_of)
    recent = [_keys(gate_on(fred, bars, hurdle, as_of - timedelta(days=FRESH_DAYS * k))[2])
              for k in range(1, COOLDOWN_WEEKS + 1)]
    prev_day = as_of - timedelta(days=FRESH_DAYS)
    return {"dashboard": dash, "trends": trends, "candidates": cands, "stand_aside": aside,
            "candidates_prev": sorted(recent[0]), "recently_gated": sorted(set().union(*recent)),
            "fresh": fresh(cands, recent), "prev_as_of": prev_day.isoformat()}


def gate_history(fred: dict, bars: dict, hurdle: float, start: date, end: date) -> list[dict]:
    """Weekly (every 7 days from `start`) fresh candidates: how often the LLM would be asked.
    Uses today's constant hurdle, so it estimates the frequency; it is not a backtest."""
    days = [start + timedelta(days=FRESH_DAYS * k)
            for k in range(-COOLDOWN_WEEKS, (end - start).days // FRESH_DAYS + 1)]
    gates = [gate_on(fred, bars, hurdle, d) for d in days]
    out = []
    for i in range(COOLDOWN_WEEKS, len(days)):
        f = fresh(gates[i][2], [_keys(g[2]) for g in gates[i - COOLDOWN_WEEKS:i]])
        if f:
            out.append({"as_of": days[i].isoformat(), "impulse": gates[i][0]["liquidity"]["impulse"],
                        "fresh": [f"{c.ticker}:{c.direction}" for c in f]})
    return out
