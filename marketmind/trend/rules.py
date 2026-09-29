"""Trend rule parameters and the code-computed indicators behind them (SPEC L3).

All parameters live in TrendConfig (docs/TREND_DESIGN.md §3). Indicators are plain
lists aligned to the input bars; an element is None until enough history exists, so
nothing is ever computed from a partial window.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from marketmind.gateway.price_history import Bar, is_crypto_ticker

EXIT_CHANDELIER = "chandelier"
EXIT_SMA = "sma"


@dataclass(frozen=True)
class TrendConfig:
    momentum_bars_equity: int = 252     # 12 months of trading days
    momentum_bars_crypto: int = 365     # 12 months of UTC-day bars
    sma_filter: int = 200               # close must be above this SMA
    breakout: int = 55                  # close above the prior N closes' high
    atr_period: int = 20                # Wilder ATR (turtle N)
    atr_mult: float = 3.0               # chandelier: highest close since entry - k*ATR
    exit_rule: str = EXIT_CHANDELIER    # or EXIT_SMA (close below `exit_sma`)
    exit_sma: int = 100
    min_bars_equity: int = 260          # fewer complete bars -> UNAVAILABLE
    min_bars_crypto: int = 366
    max_staleness_days: int = 7         # last complete bar older than this -> UNAVAILABLE

    def momentum_bars(self, ticker: str) -> int:
        return self.momentum_bars_crypto if is_crypto_ticker(ticker) else self.momentum_bars_equity

    def min_bars(self, ticker: str) -> int:
        need = max(self.momentum_bars(ticker) + 1, self.sma_filter, self.breakout + 1,
                   self.atr_period + 1, self.exit_sma if self.exit_rule == EXIT_SMA else 0)
        floor = self.min_bars_crypto if is_crypto_ticker(ticker) else self.min_bars_equity
        return max(need, floor)


def sma(values: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def prior_high(values: Sequence[float], n: int) -> list[float | None]:
    """Highest of the n values BEFORE index i (today's close is not included)."""
    from collections import deque
    out: list[float | None] = [None] * len(values)
    dq: deque[int] = deque()          # indices of a decreasing run of values
    for i, v in enumerate(values):
        if i >= n:
            while dq and dq[0] < i - n:
                dq.popleft()
            out[i] = values[dq[0]]
        while dq and values[dq[-1]] <= v:
            dq.pop()
        dq.append(i)
    return out


def wilder_atr(bars: Sequence[Bar], n: int) -> list[float | None]:
    """Wilder ATR: first value = mean of the first n true ranges (bars 1..n)."""
    out: list[float | None] = [None] * len(bars)
    trs: list[float] = []
    atr: float | None = None
    for i in range(1, len(bars)):
        b, pc = bars[i], bars[i - 1].close
        tr = max(b.high - b.low, abs(b.high - pc), abs(b.low - pc))
        if atr is None:
            trs.append(tr)
            if len(trs) == n:
                atr = sum(trs) / n
                out[i] = atr
        else:
            atr = (atr * (n - 1) + tr) / n
            out[i] = atr
    return out


def trailing_return(values: Sequence[float], n: int) -> list[float | None]:
    return [None if i < n or values[i - n] <= 0 else values[i] / values[i - n] - 1
            for i in range(len(values))]


@dataclass
class Indicators:
    close: list[float]
    ret_12m: list[float | None]
    sma_filter: list[float | None]
    high_prior: list[float | None]
    atr: list[float | None]
    sma_exit: list[float | None]


def indicators(ticker: str, bars: Sequence[Bar], cfg: TrendConfig) -> Indicators:
    closes = [b.close for b in bars]
    return Indicators(
        close=closes,
        ret_12m=trailing_return(closes, cfg.momentum_bars(ticker)),
        sma_filter=sma(closes, cfg.sma_filter),
        high_prior=prior_high(closes, cfg.breakout),
        atr=wilder_atr(bars, cfg.atr_period),
        sma_exit=sma(closes, cfg.exit_sma),
    )
