"""Shared helpers for the pure-code quant Playground agents (docs/PLAYGROUND_AGENTS.md).

Not an agent (no manifest.json, so discover_agents skips it). Everything here is
deterministic code: no LLM, no guessed numbers. Price data comes from
marketmind.trend.state.fetch_inputs (gateway.price_history, complete bars only, plus
the ^IRX T-bill hurdle), so these agents see exactly the series the trend state
machine and the ledger settle on.

House conventions shared by all four agents (fixed, not tuned on our data):
  stop        close-based disaster stop at 3 x Wilder ATR(20) from the signal close
              (the trend module's chandelier distance, TrendConfig.atr_mult/atr_period),
              recorded as a ledger falsifier_rule (close_below for longs,
              close_above for shorts).
  confidence  0.5 + 0.15 * min(1, strength / 2), strength in volatility units, so it
              stays in 0.50-0.65: these are baselines with modest documented hit rates,
              and the ledger's Brier score will calibrate them.
  staleness   a last complete bar older than 7 days -> unavailable (TrendConfig).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Sequence

from marketmind.gateway.price_history import Bar, is_crypto_ticker
from marketmind.trend.rules import TrendConfig, wilder_atr

ATR_PERIOD = TrendConfig.atr_period
STOP_ATR_MULT = TrendConfig.atr_mult
MAX_STALE_DAYS = TrendConfig.max_staleness_days
CONF_FLOOR, CONF_SPAN = 0.5, 0.15
MOP_COM = 60                      # EWMA centre of mass in days (Moskowitz et al. 2012)


def utc_today(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()


def momentum_bars(ticker: str) -> int:
    """12 months of bars: 252 trading days, or 365 UTC days for crypto (trend module)."""
    return TrendConfig().momentum_bars(ticker)


def unavailable(ticker: str, bars: Sequence[Bar] | None, need: int, today: date) -> str | None:
    """Why `bars` cannot be used (missing, too short, stale), or None."""
    if not bars:
        return "no price history (all sources failed)"
    if len(bars) < need:
        return f"insufficient history: {len(bars)} < {need} bars"
    age = (today - date.fromisoformat(bars[-1].date)).days
    if age > MAX_STALE_DAYS:
        return f"stale: last complete bar {bars[-1].date} is {age} days old"
    return None


def trailing(bars: Sequence[Bar], n: int) -> float | None:
    """Return over the last n bars (close[-1] / close[-1-n] - 1)."""
    if len(bars) <= n or bars[-1 - n].close <= 0:
        return None
    return bars[-1].close / bars[-1 - n].close - 1


def ewma_vol(bars: Sequence[Bar], ticker: str, com: int = MOP_COM) -> float | None:
    """Annualised ex-ante volatility as in Moskowitz, Ooi & Pedersen (2012):
    sigma^2 = A * sum (1-d) d^i (r_{t-i} - rbar)^2 with d/(1-d) = com, A = 261 trading
    days (365 for crypto). Uses daily close-to-close returns of the last 3*com+1 bars."""
    window = bars[-(3 * com + 1):]
    rets = [b.close / a.close - 1 for a, b in zip(window, window[1:]) if a.close > 0]
    if len(rets) < com:
        return None
    d = com / (com + 1.0)
    weights = [(1 - d) * d ** i for i in range(len(rets))]          # i = 0 is the latest
    rets = rets[::-1]
    total = sum(weights)
    mean = sum(w * r for w, r in zip(weights, rets)) / total
    var = sum(w * (r - mean) ** 2 for w, r in zip(weights, rets)) / total
    annual = 365 if is_crypto_ticker(ticker) else 261
    return math.sqrt(var * annual)


def confidence(strength: float) -> float:
    return round(CONF_FLOOR + CONF_SPAN * min(1.0, abs(strength) / 2.0), 4)


def atr_stop(bars: Sequence[Bar], direction: str) -> tuple[float, float] | None:
    """(stop level, ATR20) at STOP_ATR_MULT x ATR from the last close; None without ATR."""
    atr = wilder_atr(bars, ATR_PERIOD)[-1] if len(bars) > ATR_PERIOD else None
    if atr is None or atr <= 0:
        return None
    c = bars[-1].close
    level = c - STOP_ATR_MULT * atr if direction == "long" else c + STOP_ATR_MULT * atr
    if level <= 0:
        return None
    return round(level, 6), atr


def falsifier(ticker: str, direction: str, level: float, atr: float, hold: int,
              basis: str | None = None) -> tuple[str, dict]:
    """(human text, ledger falsifier_rule) for a close-based stop."""
    sign = "−" if direction == "long" else "+"
    basis = basis or f"信号收盘 {sign} {STOP_ATR_MULT:g}×ATR{ATR_PERIOD}，ATR={atr:.4g}"
    if direction == "long":
        return (f"{ticker} 收盘跌破 {level:.4g}（{basis}），或 {hold} 根 K 线后净收益为负",
                {"type": "close_below", "price": level})
    return (f"{ticker} 收盘升破 {level:.4g}（{basis}），或 {hold} 根 K 线后净收益为负",
            {"type": "close_above", "price": level})


def hold_month(ticker: str) -> int:
    """One month in the ledger's bar unit: 21 trading days, 30 UTC days for crypto."""
    return 30 if is_crypto_ticker(ticker) else 21


def month_rebalance_key(today: date, window_days: int = 7) -> str | None:
    """'YYYY-MM' during the first `window_days` calendar days of a month, else None.
    With the bridge's signal_key the first run inside the window records the month's
    rebalance; later runs record nothing, so monthly holdings do not pile up."""
    return f"{today:%Y-%m}" if today.day <= window_days else None


def week_key(today: date) -> str:
    y, w, _ = today.isocalendar()
    return f"{y}-W{w:02d}"


def r4(x: float | None) -> float | None:
    return None if x is None else round(x, 4)
