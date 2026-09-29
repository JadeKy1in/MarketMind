"""Monthly long-horizon trend rules (docs/TREND_DESIGN.md §10, pre-registered 2026-09-29).

M1 (Faber 2007/2013): hold while the month-end close is above the average of the last
N month-end closes (N=10). M2 (12-month time-series momentum / Antonacci absolute
momentum): hold while the L-month return beats the T-bill return over the same span.
Decisions only on check days (each instrument's last trading day of the month, or the
mid-month variant); fills at the next bar's open. Backtest only - not wired into the
daily run. The output is a `state.SimResult`, so `backtest.result_from_sim` and
`backtest.run_portfolio` (1/6 slots) are reused unchanged. Pure functions, no network.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from marketmind.gateway.price_history import Bar
from marketmind.trend.backtest import PortfolioConfig
from marketmind.trend.state import CASH, EXIT, TREND, SimResult, Trade

MONTHLY_UNIVERSE: tuple[str, ...] = ("SPY", "QQQ", "GLD", "TLT", "BTC-USD", "ETH-USD")

RULE_SMA = "sma"          # M1
RULE_TSMOM = "tsmom"      # M2
RULE_ALWAYS = "always"    # equal-weight buy-and-hold benchmark (same slots, never sells)
CHECK_MONTH_END = "month_end"
CHECK_MID_MONTH = "mid_month"
EVAL_FROM = "2005-12-01"  # first check: the last trading day of Dec 2005

# 6 equal slots: each entry buys 1/6 of equity; initial_stop = 0 makes the cap bind.
SLOTS = PortfolioConfig(risk_per_trade=1.0, max_weight=1 / 6, max_positions=6)


@dataclass(frozen=True)
class MonthlyConfig:
    rule: str = RULE_SMA
    months: int = 10                   # SMA length (M1) or look-back (M2), in check periods
    check: str = CHECK_MONTH_END
    eval_from: str | None = EVAL_FROM  # checks before this date make no decision

    @property
    def min_checks(self) -> int:
        """Monthly closes needed before the first decision."""
        return self.months + 1 if self.rule == RULE_TSMOM else self.months

    @property
    def label(self) -> str:
        name = {RULE_SMA: f"M1 SMA{self.months}", RULE_TSMOM: f"M2 TSMOM{self.months}",
                RULE_ALWAYS: "always in"}[self.rule]
        return name + ("" if self.check == CHECK_MONTH_END else " mid-month")


M1 = MonthlyConfig(RULE_SMA, 10)
M2 = MonthlyConfig(RULE_TSMOM, 12)
ALWAYS = MonthlyConfig(RULE_ALWAYS, 10)          # buys once M1 could first decide


def check_indices(bars: Sequence[Bar], check: str = CHECK_MONTH_END) -> list[int]:
    """Bars that are check days. Month end: the next bar is in another month. Mid-month:
    the last bar dated on or before the 15th (the next bar is after the 15th or in
    another month). Only dates are used; the last bar is never a check (no next bar,
    and its month may be incomplete)."""
    out = []
    for i in range(len(bars) - 1):
        d, nxt = bars[i].date, bars[i + 1].date
        if check == CHECK_MONTH_END:
            if nxt[:7] != d[:7]:
                out.append(i)
        elif check == CHECK_MID_MONTH:
            if int(d[8:10]) <= 15 and (nxt[:7] != d[:7] or int(nxt[8:10]) > 15):
                out.append(i)
        else:
            raise ValueError(f"unknown check {check!r}")
    return out


def decide(mcloses: Sequence[float], cfg: MonthlyConfig, hurdle_annual: float = 0.0
           ) -> tuple[bool, float] | None:
    """(hold?, strength) from the monthly closes up to and including this check;
    None until `cfg.min_checks` closes exist. Strength ranks same-day entries."""
    k = len(mcloses)
    if k < cfg.min_checks:
        return None
    c = mcloses[-1]
    if cfg.rule == RULE_ALWAYS:
        return True, 0.0
    if cfg.rule == RULE_SMA:
        avg = sum(mcloses[-cfg.months:]) / cfg.months
        return c > avg, c / avg - 1
    if cfg.rule == RULE_TSMOM:
        base = mcloses[-1 - cfg.months]
        if base <= 0:
            return None
        ret = c / base - 1
        hurdle = (1 + hurdle_annual) ** (cfg.months / 12) - 1
        return ret > hurdle, ret - hurdle
    raise ValueError(f"unknown rule {cfg.rule!r}")


def simulate_monthly(ticker: str, bars: Sequence[Bar], cfg: MonthlyConfig = M1,
                     hurdle: float | Callable[[str], float] = 0.0) -> SimResult:
    """Replay the monthly rule over complete daily bars. A decision on check bar i uses
    closes <= i only; entries and exits fill at bar i+1's open. `first_ready` is the
    first check that could decide (on/after `cfg.eval_from`)."""
    n = len(bars)
    hurdles = [float(hurdle(b.date)) if callable(hurdle) else float(hurdle) for b in bars]
    res = SimResult(ticker, bars, None, [CASH] * n, [None] * n, hurdles)
    checks = set(check_indices(bars, cfg.check))
    mcloses: list[float] = []
    trade: Trade | None = None
    for i in range(n):          # pending fills/exits happen at this bar's open
        if trade is not None and trade.fill_idx is None:
            trade.fill_idx, trade.fill_date, trade.fill_price = i, bars[i].date, bars[i].open
        if trade is not None and trade.exit_signal_idx is not None and trade.exit_idx is None:
            trade.exit_idx, trade.exit_date, trade.exit_price = i, bars[i].date, bars[i].open
            trade = None
        res.states[i] = TREND if trade is not None else CASH
        if i not in checks:
            continue
        mcloses.append(bars[i].close)
        if cfg.eval_from is not None and bars[i].date < cfg.eval_from:
            continue
        got = decide(mcloses, cfg, hurdles[i])
        if got is None:
            continue
        if res.first_ready is None:
            res.first_ready = i
        hold, strength = got
        if hold and trade is None:
            trade = Trade(ticker, i, bars[i].date, bars[i].close, 0.0, strength, hurdles[i])
            res.trades.append(trade)
            res.states[i] = TREND
        elif not hold and trade is not None:
            trade.exit_signal_idx, trade.exit_signal_date = i, bars[i].date
            trade.exit_reason = f"{cfg.label}: no longer holding"
            res.states[i] = EXIT
    return res


def whipsaws(sim: SimResult, check: str = CHECK_MONTH_END) -> int:
    """Round trips shorter than 2 months: the exit is signalled at the very next check
    after the entry check (docs/TREND_DESIGN.md §10)."""
    checks = check_indices(sim.bars, check)
    pos = {i: k for k, i in enumerate(checks)}
    return sum(1 for tr in sim.trades
               if tr.exit_signal_idx is not None
               and pos.get(tr.exit_signal_idx, -99) - pos.get(tr.signal_idx, -99) == 1)
