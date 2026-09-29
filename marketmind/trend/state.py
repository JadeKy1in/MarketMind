"""Trend state machine: CASH / WATCH -> TREND (entry) -> EXIT -> CASH.

One simulator (`simulate`) is used both by the backtest and by the daily state
function, so today's state is exactly what the backtest would have said. Decisions
on bar t use bars <= t only; fills happen at bar t+1's open (docs/TREND_DESIGN.md).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Sequence

from marketmind.gateway.price_history import Bar
from marketmind.trend.rules import EXIT_SMA, Indicators, TrendConfig, indicators

logger = logging.getLogger("marketmind.trend.state")

CASH = "CASH"
WATCH = "WATCH"
TREND = "TREND"
EXIT = "EXIT"
UNAVAILABLE = "UNAVAILABLE"
EVENT_ENTRY = "ENTRY"
EVENT_EXIT = "EXIT"


@dataclass
class Trade:
    ticker: str
    signal_idx: int                  # bar of the entry signal (close)
    signal_date: str
    signal_close: float
    initial_stop: float
    ret_12m: float
    hurdle: float
    fill_idx: int | None = None      # signal_idx + 1 (None if the signal is on the last bar)
    fill_date: str | None = None
    fill_price: float | None = None
    exit_signal_idx: int | None = None
    exit_signal_date: str | None = None
    exit_reason: str | None = None
    exit_idx: int | None = None
    exit_date: str | None = None
    exit_price: float | None = None

    @property
    def closed(self) -> bool:
        return self.exit_price is not None


@dataclass
class SimResult:
    ticker: str
    bars: Sequence[Bar]
    ind: Indicators
    states: list[str]                # state at each bar's close
    stops: list[float | None]        # stop in force for the NEXT bar (None when flat)
    hurdles: list[float]
    trades: list[Trade] = field(default_factory=list)
    first_ready: int | None = None   # first bar where every indicator exists


def simulate(ticker: str, bars: Sequence[Bar], cfg: TrendConfig,
             hurdle: float | Callable[[str], float] = 0.0) -> SimResult:
    """Replay the rules over `bars` (complete daily bars, ascending).

    `hurdle` is the annual T-bill return used as the 12-month momentum threshold: a
    constant, or a function of the bar date (the backtest's point-in-time ^IRX mean).
    """
    ind = indicators(ticker, bars, cfg)
    n = len(bars)
    states: list[str] = [CASH] * n
    stops: list[float | None] = [None] * n
    hurdles = [float(hurdle(b.date)) if callable(hurdle) else float(hurdle) for b in bars]
    res = SimResult(ticker, bars, ind, states, stops, hurdles)
    trade: Trade | None = None
    stop = hc = 0.0
    for t in range(n):
        c = ind.close[t]
        # a pending fill / exit happens at this bar's open
        if trade is not None and trade.fill_idx is None:
            trade.fill_idx, trade.fill_date, trade.fill_price = t, bars[t].date, bars[t].open
        if trade is not None and trade.exit_signal_idx is not None:
            trade.exit_idx, trade.exit_date, trade.exit_price = t, bars[t].date, bars[t].open
            trade = None
        r12, smaf, hp, atr = ind.ret_12m[t], ind.sma_filter[t], ind.high_prior[t], ind.atr[t]
        ready = None not in (r12, smaf, hp, atr) and (
            cfg.exit_rule != EXIT_SMA or ind.sma_exit[t] is not None)
        if ready and res.first_ready is None:
            res.first_ready = t
        if trade is not None:                       # holding (signal was on an earlier bar)
            if cfg.exit_rule == EXIT_SMA:
                hit, why = ind.sma_exit[t] is not None and c < ind.sma_exit[t], \
                    f"close < SMA{cfg.exit_sma}"
            else:
                hit, why = c < stop, f"close < chandelier stop {stop:.4f}"
            if hit:
                trade.exit_signal_idx, trade.exit_signal_date = t, bars[t].date
                trade.exit_reason = why
                states[t] = EXIT
                continue
            hc = max(hc, c)
            if atr is not None:
                stop = max(stop, hc - cfg.atr_mult * atr)
            states[t], stops[t] = TREND, stop
            continue
        if not ready:
            continue
        filters = r12 > hurdles[t] and c > smaf
        if filters and c > hp:
            hc, stop = c, c - cfg.atr_mult * atr
            trade = Trade(ticker, t, bars[t].date, c, stop, r12, hurdles[t])
            res.trades.append(trade)
            states[t], stops[t] = TREND, stop
        elif filters:
            states[t] = WATCH
    return res


@dataclass
class TrendState:
    ticker: str
    state: str
    as_of: str | None = None             # last complete bar date
    event: str | None = None             # ENTRY / EXIT fired on the as_of bar -> act next open
    close: float | None = None
    ret_12m: float | None = None
    hurdle: float | None = None
    hurdle_source: str | None = None
    sma200: float | None = None
    high_55: float | None = None         # prior-N-bar closing high (the breakout level)
    atr: float | None = None
    stop_level: float | None = None      # chandelier stop in force for the next bar
    entry_signal_date: str | None = None
    entry_signal_close: float | None = None
    replay_start: str | None = None
    bars: int = 0
    source: str | None = None
    reason: str | None = None            # why UNAVAILABLE, or which conditions are missing

    def to_dict(self) -> dict:
        return asdict(self)


def _r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None else round(x, nd)


def state_from_sim(sim: SimResult, cfg: TrendConfig) -> TrendState:
    t = len(sim.bars) - 1
    ind, b = sim.ind, sim.bars[t]
    st = TrendState(ticker=sim.ticker, state=sim.states[t], as_of=b.date, close=b.close,
                    ret_12m=_r(ind.ret_12m[t]), hurdle=_r(sim.hurdles[t]),
                    sma200=_r(ind.sma_filter[t], 4), high_55=_r(ind.high_prior[t], 4),
                    atr=_r(ind.atr[t], 4), stop_level=_r(sim.stops[t], 4),
                    replay_start=sim.bars[0].date, bars=len(sim.bars))
    last = sim.trades[-1] if sim.trades else None
    if st.state in (TREND, EXIT) and last is not None:
        st.entry_signal_date, st.entry_signal_close = last.signal_date, last.signal_close
        if last.signal_idx == t:
            st.event = EVENT_ENTRY
        if last.exit_signal_idx == t:
            st.event, st.reason = EVENT_EXIT, last.exit_reason
    if st.state in (CASH, WATCH):
        missing = []
        if ind.ret_12m[t] is not None and ind.ret_12m[t] <= sim.hurdles[t]:
            missing.append("12m return <= T-bill hurdle")
        if ind.sma_filter[t] is not None and b.close <= ind.sma_filter[t]:
            missing.append(f"close <= SMA{cfg.sma_filter}")
        if ind.high_prior[t] is not None and b.close <= ind.high_prior[t]:
            gap = ind.high_prior[t] / b.close - 1
            missing.append(f"no {cfg.breakout}d closing-high breakout ({gap:.2%} below)")
        st.reason = "; ".join(missing) or None
    return st


def compute_states(histories: dict[str, Sequence[Bar] | None], hurdle: float = 0.0,
                   cfg: TrendConfig | None = None, hurdle_source: str = "given",
                   today: date | None = None,
                   sources: dict[str, str] | None = None) -> dict[str, TrendState]:
    """Today's state for every instrument. `histories` must hold COMPLETE bars only
    (gateway.price_history.complete_bars). Missing or short history -> UNAVAILABLE."""
    cfg = cfg or TrendConfig()
    today = today or datetime.now(timezone.utc).date()
    out: dict[str, TrendState] = {}
    for ticker, bars in histories.items():
        src = (sources or {}).get(ticker)
        if not bars:
            out[ticker] = TrendState(ticker, UNAVAILABLE, source=src,
                                     reason="no price history (all sources failed)")
            continue
        need = cfg.min_bars(ticker)
        last = bars[-1].date
        if len(bars) < need:
            out[ticker] = TrendState(ticker, UNAVAILABLE, as_of=last, bars=len(bars), source=src,
                                     reason=f"insufficient history: {len(bars)} < {need} bars")
            continue
        age = (today - date.fromisoformat(last)).days
        if age > cfg.max_staleness_days:
            out[ticker] = TrendState(ticker, UNAVAILABLE, as_of=last, bars=len(bars), source=src,
                                     reason=f"stale: last complete bar {last} is {age} days old")
            continue
        st = state_from_sim(simulate(ticker, bars, cfg, hurdle), cfg)
        st.hurdle_source, st.source = hurdle_source, src
        out[ticker] = st
    return out


def hurdle_from_tbill(bars: Sequence[Bar], window: int = 252) -> float | None:
    """Annual T-bill return proxy: mean of the last `window` ^IRX closes (percent) / 100."""
    vals = [b.close for b in bars[-window:] if b.close == b.close]
    if len(vals) < window // 2:
        return None
    return sum(vals) / len(vals) / 100.0


async def today_states(tickers: Sequence[str] | None = None,
                       cfg: TrendConfig | None = None) -> dict[str, TrendState]:
    """Fetch complete daily bars (5-year replay window) and compute today's states.
    Network I/O; not used by tests."""
    from marketmind.gateway.price_history import complete_bars, get_price_histories, get_price_history
    from marketmind.trend.universe import TBILL_PROXY, TREND_UNIVERSE
    tickers = list(tickers or TREND_UNIVERSE)
    hists = await get_price_histories(tickers, years=5)
    irx = await get_price_history(TBILL_PROXY, years=2)
    hurdle, src = None, "unavailable -> 0"
    if irx is not None:
        hurdle = hurdle_from_tbill(complete_bars(TBILL_PROXY, irx.daily))
        if hurdle is not None:
            src = f"{TBILL_PROXY} 252d mean ({irx.source})"
    if hurdle is None:
        logger.warning("T-bill hurdle unavailable; using 0")
        hurdle = 0.0
    bars = {t: (complete_bars(t, h.daily) if h else None) for t, h in hists.items()}
    sources = {t: h.source for t, h in hists.items() if h}
    return compute_states(bars, hurdle, cfg, hurdle_source=src, sources=sources)
