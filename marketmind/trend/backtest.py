"""Backtest of the trend state machine (docs/TREND_DESIGN.md §6).

Pure functions over bars: per-instrument long-only simulation (the same `simulate`
the daily state uses), big-move capture, and an owner-level portfolio ($30k, 1% risk
per position via the stop distance, 25% cap, max 6 positions). No network here;
`run()` reads the JSON cache written by marketmind.trend.data.
"""
from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Callable, Sequence

from marketmind.gateway.price_history import Bar, is_crypto_ticker
from marketmind.trend.rules import TrendConfig
from marketmind.trend.state import SimResult, Trade, simulate


def one_way_cost(ticker: str) -> float:
    """Ledger settlement's one-way cost (5 bp US; 100 bp BTC/ETH; 125 bp other coins)."""
    from marketmind.ledger.settlement import cost_bps
    return cost_bps("crypto" if is_crypto_ticker(ticker) else "", ticker) / 10_000


# ── hurdle ──────────────────────────────────────────────────────────────────

def tbill_hurdle_fn(irx: Sequence[Bar] | None, window: int = 252) -> tuple[Callable[[str], float], str]:
    """Point-in-time hurdle: mean of the last `window` ^IRX closes on or before the date,
    / 100. Dates before the series starts (or no series) -> 0.0."""
    if not irx:
        return (lambda d: 0.0), "unavailable -> 0"
    dates = [b.date for b in irx]
    means: list[float] = []
    total = 0.0
    for i, b in enumerate(irx):
        total += b.close
        if i >= window:
            total -= irx[i - window].close
        means.append(total / min(i + 1, window) / 100.0)

    def fn(d: str) -> float:
        i = bisect.bisect_right(dates, d) - 1
        return means[i] if i >= 0 else 0.0
    return fn, "^IRX 252-day mean (yfinance)"


# ── per-instrument ──────────────────────────────────────────────────────────

@dataclass
class InstrumentResult:
    ticker: str
    source: str
    first_date: str
    last_date: str
    eval_start: str | None
    years: float
    cost: float
    sim: SimResult
    trades: list[Trade]
    strat_equity: list[float]          # from eval_start
    bh_equity: list[float]
    gross_ret: list[float]             # per bar, strategy gross daily return
    held: list[bool]                   # position held at bar's close
    metrics: dict = field(default_factory=dict)
    moves: list[dict] = field(default_factory=list)


def trade_net_return(tr: Trade, cost: float, mark: float | None = None) -> float | None:
    exit_px = tr.exit_price if tr.exit_price is not None else mark
    if tr.fill_price is None or exit_px is None:
        return None
    return exit_px / tr.fill_price * (1 - cost) ** 2 - 1


def daily_returns(bars: Sequence[Bar], trades: Sequence[Trade], cost: float
                  ) -> tuple[list[float], list[float], list[bool]]:
    """(net, gross) strategy return per bar and whether a position is held at the close."""
    n = len(bars)
    net, gross, held = [0.0] * n, [0.0] * n, [False] * n
    for tr in trades:
        f = tr.fill_idx
        if f is None:
            continue
        x = tr.exit_idx if tr.exit_idx is not None else n       # n = still open
        for d in range(f, min(x + 1, n)):
            if d == f:
                r = bars[d].close / bars[d].open - 1
                rn = (1 + r) * (1 - cost) - 1
            elif d == x:
                r = bars[d].open / bars[d - 1].close - 1
                rn = (1 + r) * (1 - cost) - 1
            else:
                r = bars[d].close / bars[d - 1].close - 1
                rn = r
            gross[d], net[d] = r, rn
            if d < x:
                held[d] = True
        if tr.fill_idx == x:     # cannot happen (exit >= fill + 1); guard anyway
            held[f] = False
    return net, gross, held


def equity_curve(rets: Sequence[float]) -> list[float]:
    eq, v = [], 1.0
    for r in rets:
        v *= 1 + r
        eq.append(v)
    return eq


def max_drawdown(eq: Sequence[float]) -> float:
    peak, mdd = -math.inf, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd


def cagr(v0: float, v1: float, d0: str, d1: str) -> float | None:
    days = (date.fromisoformat(d1) - date.fromisoformat(d0)).days
    if days <= 0 or v0 <= 0 or v1 <= 0:
        return None
    return (v1 / v0) ** (365.25 / days) - 1


def big_moves(closes: Sequence[float], start: int, min_rise: float, max_bars: int
              ) -> list[tuple[int, int]]:
    """Non-overlapping (trough, peak) index pairs: close rises >= min_rise within <= max_bars.

    Greedy left to right: at i, if the highest close in (i, i+max_bars] is >= close[i] *
    (1+min_rise), the trough is the lowest close in [i, that high], the peak the highest
    close in (trough, trough+max_bars]; continue after the peak.
    """
    out: list[tuple[int, int]] = []
    n, i = len(closes), start
    while i < n - 1:
        hi_end = min(n, i + max_bars + 1)
        j = max(range(i + 1, hi_end), key=lambda k: closes[k])
        if closes[j] >= closes[i] * (1 + min_rise):
            trough = min(range(i, j + 1), key=lambda k: closes[k])
            p_end = min(n, trough + max_bars + 1)
            peak = max(range(trough + 1, p_end), key=lambda k: closes[k])
            out.append((trough, peak))
            i = peak + 1
        else:
            i += 1
    return out


def move_capture(closes: Sequence[float], gross: Sequence[float], held: Sequence[bool],
                 trough: int, peak: int) -> dict:
    total = math.log(closes[peak] / closes[trough])
    got = sum(math.log(1 + gross[d]) for d in range(trough + 1, peak + 1))
    half = math.log(closes[trough]) + total / 2
    mid = next(d for d in range(trough + 1, peak + 1) if math.log(closes[d]) >= half)
    return {
        "trough": trough, "peak": peak, "rise": closes[peak] / closes[trough] - 1,
        "participated": any(held[d] for d in range(trough, peak + 1)),
        "in_at_mid": held[mid],
        "capture": got / total if total > 0 else 0.0,
    }


BIG_MOVE_RISE = 0.20
BIG_MOVE_BARS = 120              # trading days; crypto scaled to calendar time


def big_move_bars(ticker: str) -> int:
    return round(BIG_MOVE_BARS * 365 / 252) if is_crypto_ticker(ticker) else BIG_MOVE_BARS


def backtest_instrument(ticker: str, bars: Sequence[Bar], cfg: TrendConfig,
                        hurdle: float | Callable[[str], float], source: str = "") -> InstrumentResult:
    cost = one_way_cost(ticker)
    sim = simulate(ticker, bars, cfg, hurdle)
    net, gross, held = daily_returns(bars, sim.trades, cost)
    s = sim.first_ready
    res = InstrumentResult(ticker, source, bars[0].date, bars[-1].date,
                           bars[s].date if s is not None else None, 0.0, cost, sim, sim.trades,
                           [], [], gross, held)
    if s is None:
        res.metrics = {"unavailable": f"insufficient history ({len(bars)} bars)"}
        return res
    closes = [b.close for b in bars]
    res.strat_equity = equity_curve([0.0] + net[s + 1:])
    res.bh_equity = [(c / closes[s]) * (1 - cost) for c in closes[s:]]
    d0, d1 = bars[s].date, bars[-1].date
    res.years = (date.fromisoformat(d1) - date.fromisoformat(d0)).days / 365.25
    closed = [tr for tr in sim.trades if tr.closed]
    rets = [trade_net_return(tr, cost) for tr in closed]
    hold = [(date.fromisoformat(tr.exit_date) - date.fromisoformat(tr.fill_date)).days
            for tr in closed]
    in_mkt = sum(held[s + 1:]) / max(1, len(held) - s - 1)
    moves = [move_capture(closes, gross, held, a, b)
             for a, b in big_moves(closes, s, BIG_MOVE_RISE, big_move_bars(ticker))]
    res.moves = moves
    res.metrics = {
        "signals": len(sim.trades),
        "signals_per_year": len(sim.trades) / res.years if res.years else None,
        "closed": len(closed),
        "hit_rate": sum(r > 0 for r in rets) / len(rets) if rets else None,
        "avg_trade": statistics.fmean(rets) if rets else None,
        "median_trade": statistics.median(rets) if rets else None,
        "avg_hold_days": statistics.fmean(hold) if hold else None,
        "time_in_market": in_mkt,
        "cagr": cagr(1.0, res.strat_equity[-1], d0, d1),
        "bh_cagr": cagr(1.0, res.bh_equity[-1], d0, d1),
        "mdd": max_drawdown(res.strat_equity),
        "bh_mdd": max_drawdown(res.bh_equity),
        "moves": len(moves),
        "participation": (sum(m["participated"] for m in moves) / len(moves)) if moves else None,
        "in_at_mid": (sum(m["in_at_mid"] for m in moves) / len(moves)) if moves else None,
        "capture": statistics.fmean(m["capture"] for m in moves) if moves else None,
    }
    return res


# ── portfolio ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PortfolioConfig:
    capital: float = 30_000.0
    risk_per_trade: float = 0.01
    max_weight: float = 0.25
    max_positions: int = 6
    min_position: float = 100.0         # dollars; smaller -> skipped ("no cash")


@dataclass
class PortfolioResult:
    dates: list[str]
    equity: list[float]
    taken: list[dict]
    skipped: list[dict]
    metrics: dict


def run_portfolio(results: dict[str, InstrumentResult], pcfg: PortfolioConfig = PortfolioConfig(),
                  cash_rate: Callable[[str], float] | None = None,
                  start: str | None = None) -> PortfolioResult:
    """Take every trend signal while a slot and cash are free. `cash_rate(date)` is the
    annual rate paid on idle cash (None -> 0)."""
    closes: dict[str, dict[str, float]] = {}
    entries: dict[str, list[tuple[str, Trade, InstrumentResult]]] = {}
    exits: dict[str, list[tuple[str, Trade]]] = {}
    for tk, r in results.items():
        if r.eval_start is None:
            continue
        closes[tk] = {b.date: b.close for b in r.sim.bars}
        for tr in r.trades:
            if tr.fill_date is None:
                continue
            entries.setdefault(tr.fill_date, []).append((tk, tr, r))
            if tr.exit_date is not None:
                exits.setdefault(tr.exit_date, []).append((tk, tr))
    starts = [r.eval_start for r in results.values() if r.eval_start]
    start = start or min(starts)
    all_dates = sorted({d for c in closes.values() for d in c if d >= start})
    cash = pcfg.capital
    pos: dict[int, dict] = {}                   # id(trade) -> position
    marks: dict[str, float] = {}
    eq: list[float] = []
    exposure: list[float] = []
    taken: list[dict] = []
    skipped: list[dict] = []
    prev_d: str | None = None
    for d in all_dates:
        if cash_rate is not None and prev_d is not None and cash > 0:
            days = (date.fromisoformat(d) - date.fromisoformat(prev_d)).days
            cash *= (1 + cash_rate(prev_d)) ** (days / 365.0)
        for tk, tr in exits.get(d, []):
            p = pos.pop(id(tr), None)
            if p is not None:
                cash += p["units"] * tr.exit_price * (1 - p["cost"])
                p["exit_date"], p["exit_price"] = d, tr.exit_price
                p["pnl"] = p["units"] * tr.exit_price * (1 - p["cost"]) - p["outlay"]
        equity = cash + sum(p["units"] * marks.get(p["ticker"], p["entry"]) for p in pos.values())
        todays = sorted(entries.get(d, []), key=lambda e: -(e[1].ret_12m - e[1].hurdle))
        for tk, tr, r in todays:
            rec = {"ticker": tk, "signal_date": tr.signal_date, "fill_date": d}
            dist = tr.fill_price - tr.initial_stop
            if len(pos) >= pcfg.max_positions:
                skipped.append({**rec, "why": "max positions"})
                continue
            if dist <= 0:
                skipped.append({**rec, "why": "opened below stop"})
                continue
            value = min(pcfg.risk_per_trade * equity / dist * tr.fill_price,
                        pcfg.max_weight * equity, cash / (1 + r.cost))
            if value < pcfg.min_position:
                skipped.append({**rec, "why": "no cash"})
                continue
            units = value / tr.fill_price
            cash -= value * (1 + r.cost)
            p = {**rec, "units": units, "entry": tr.fill_price, "cost": r.cost,
                 "outlay": value * (1 + r.cost), "weight": value / equity, "trade": tr}
            pos[id(tr)] = p
            taken.append(p)
        for tk in {p["ticker"] for p in pos.values()}:
            if d in closes[tk]:
                marks[tk] = closes[tk][d]
        invested = sum(p["units"] * marks.get(p["ticker"], p["entry"]) for p in pos.values())
        eq.append(cash + invested)
        exposure.append(invested / eq[-1] if eq[-1] > 0 else 0.0)
        prev_d = d
    metrics = portfolio_metrics(all_dates, eq, taken, results, start)
    if exposure:
        metrics["avg_exposure"] = sum(exposure) / len(exposure)
        metrics["flat_share"] = sum(x == 0 for x in exposure) / len(exposure)
    return PortfolioResult(all_dates, eq, taken, skipped, metrics)


def yearly_returns(dates: Sequence[str], eq: Sequence[float]) -> dict[int, float]:
    out: dict[int, float] = {}
    prev = eq[0]
    for i, d in enumerate(dates):
        y = int(d[:4])
        last = i == len(dates) - 1 or dates[i + 1][:4] != d[:4]
        if last:
            out[y] = eq[i] / prev - 1
            prev = eq[i]
    return out


def portfolio_metrics(dates, eq, taken, results, start) -> dict:
    if not dates:
        return {}
    yr = yearly_returns(dates, eq)
    signals_by_year: dict[int, int] = {}
    for r in results.values():
        for tr in r.trades:
            if tr.signal_date >= start:
                y = int(tr.signal_date[:4])
                signals_by_year[y] = signals_by_year.get(y, 0) + 1
    taken_by_year: dict[int, int] = {}
    for p in taken:
        y = int(p["fill_date"][:4])
        taken_by_year[y] = taken_by_year.get(y, 0) + 1
    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    closed = [p for p in taken if "pnl" in p]
    return {
        "start": dates[0], "end": dates[-1], "years": years,
        "final": eq[-1], "cagr": cagr(eq[0], eq[-1], dates[0], dates[-1]),
        "mdd": max_drawdown(eq), "yearly": yr,
        "worst_year": min(yr.items(), key=lambda kv: kv[1]) if yr else None,
        "signals_by_year": signals_by_year, "taken_by_year": taken_by_year,
        "taken": len(taken), "taken_per_year": len(taken) / years if years else None,
        "hit_rate": (sum(p["pnl"] > 0 for p in closed) / len(closed)) if closed else None,
        "avg_weight": (sum(p["weight"] for p in taken) / len(taken)) if taken else None,
    }


def slice_metrics(dates: Sequence[str], eq: Sequence[float], d0: str, d1: str) -> dict:
    idx = [i for i, d in enumerate(dates) if d0 <= d <= d1]
    if len(idx) < 2:
        return {}
    sub = [eq[i] for i in idx]
    return {"cagr": cagr(sub[0], sub[-1], dates[idx[0]], dates[idx[-1]]),
            "mdd": max_drawdown(sub)}


def bh_series(bars: Sequence[Bar], dates: Sequence[str]) -> list[float]:
    """Buy-and-hold closes aligned to `dates` (forward-filled)."""
    by = {b.date: b.close for b in bars}
    out, last = [], None
    for d in dates:
        last = by.get(d, last)
        out.append(last if last is not None else float("nan"))
    first = next(v for v in out if v == v)
    return [(v if v == v else first) / first for v in out]


def run_universe(data: dict[str, tuple[str, list[Bar]]], cfg: TrendConfig,
                 hurdle: Callable[[str], float]) -> dict[str, InstrumentResult]:
    return {tk: backtest_instrument(tk, bars, cfg, hurdle, src) for tk, (src, bars) in data.items()}


def variants(base: TrendConfig) -> list[tuple[str, TrendConfig]]:
    out = []
    for br in (40, 55, 80):
        for k in (2.5, 3.0, 4.0):
            out.append((f"breakout {br} / {k:g}xATR", replace(base, breakout=br, atr_mult=k)))
    out.append(("breakout 55 / exit close<SMA100", replace(base, exit_rule="sma")))
    return out
