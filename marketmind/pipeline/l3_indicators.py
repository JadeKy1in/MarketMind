"""Code-computed technicals for the Layer 3 three-light review (SPEC_v3 §5 step 3).

Pure functions, no I/O, no LLM. Every number that reaches a decision card
(entry zone, stop, target, reward/risk) comes from here.

Rules (design spec v1.2 §4.3, made explicit):
  1. above_200wma      last close > SMA(weekly close, 200). Needs >= 200 weekly
                       bars; with less history the condition fails (young assets
                       are not "proven" above their long-term trend).
  2. structure_intact  close > SMA50, SMA50 rising vs 20 sessions ago, and the
                       latest 20-session low is above the prior 20-session low
                       (higher low).
  3. clear_of_resistance  key resistance = highest CLOSE of the last 252 sessions
                       excluding the most recent 10 (closing highs, so a single
                       intraday wick does not block a trending stock). If price has
                       broken above it there is no overhead resistance (pass);
                       otherwise it must be more than 3% away.
  Light: 3 pass -> green, 0 pass -> red, otherwise yellow (design spec wording:
  a falling asset far below resistance is yellow/"wait", never "enter").

Levels (long setups only; L3 gates buys):
  support zone  [min low of last 20 sessions, + 0.5 * ATR14]
  stop          support low - 1 * ATR14
  entry zone    [max(close * 0.98, stop + 0.5 * ATR14), close * 1.005]
                (up to 2.5% wide, never a point, always above the stop)
  target        key resistance if above close, else close + 2 * (close - stop)
  reward/risk   (target - close) / (close - stop)
  recommendation  green & R/R >= 2 -> enter; green -> wait; yellow -> wait; red -> avoid
"""
from __future__ import annotations

from dataclasses import dataclass

from marketmind.gateway.price_history import Bar, PriceHistory

WMA_WEEKS = 200
RESISTANCE_LOOKBACK = 252
RESISTANCE_EXCLUDE_RECENT = 10
NEAR_RESISTANCE_PCT = 3.0
MIN_DAILY_BARS = 60
DEFAULT_MAX_HOLD_DAYS = 30


@dataclass
class TechnicalSnapshot:
    ticker: str
    close: float
    daily_return_pct: float | None
    wma200: float | None
    weekly_bars: int
    above_200wma: bool
    structure_intact: bool
    key_resistance: float | None
    resistance_distance_pct: float | None
    near_key_resistance: bool
    atr14: float
    support_low: float
    support_high: float
    entry_low: float
    entry_high: float
    stop_loss: float
    target_price: float
    reward_risk_ratio: float
    light: str
    recommendation: str
    as_of: str
    notes: list[str]


def sma(values: list[float], n: int) -> float | None:
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / n


def atr(bars: list[Bar], n: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs = []
    for prev, cur in zip(bars[:-1], bars[1:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    window = trs[-n:]
    return sum(window) / len(window)


def compute_snapshot(hist: PriceHistory) -> TechnicalSnapshot | None:
    """Return None when history is too short to say anything honest."""
    daily = hist.daily
    if len(daily) < MIN_DAILY_BARS:
        return None
    closes = [b.close for b in daily]
    close = closes[-1]
    notes: list[str] = []

    daily_ret = (close / closes[-2] - 1) * 100 if len(closes) >= 2 and closes[-2] else None

    weekly_closes = [b.close for b in hist.weekly]
    wma = sma(weekly_closes, WMA_WEEKS)
    above_wma = wma is not None and close > wma
    if wma is None:
        notes.append(f"only {len(weekly_closes)} weekly bars (<{WMA_WEEKS}); 200WMA condition fails")

    sma50_now = sma(closes, 50)
    sma50_prev = sma(closes[:-20], 50)
    lows = [b.low for b in daily]
    recent_low = min(lows[-20:])
    prior_low = min(lows[-40:-20]) if len(lows) >= 40 else None
    structure = bool(
        sma50_now and sma50_prev and close > sma50_now and sma50_now > sma50_prev
        and prior_low is not None and recent_low > prior_low
    )

    window = daily[-RESISTANCE_LOOKBACK:-RESISTANCE_EXCLUDE_RECENT] if len(daily) > RESISTANCE_EXCLUDE_RECENT else []
    key_res = max((b.close for b in window), default=None)
    if key_res is None or close >= key_res:
        res_dist = None
        near_res = False
        if key_res is not None:
            notes.append("price above 52-week resistance (breakout, no overhead resistance)")
    else:
        res_dist = (key_res - close) / close * 100
        near_res = res_dist <= NEAR_RESISTANCE_PCT

    passes = sum([above_wma, structure, not near_res])
    light = "green" if passes == 3 else ("red" if passes == 0 else "yellow")

    a = atr(daily)
    support_low = recent_low
    support_high = recent_low + 0.5 * a
    stop = support_low - a
    # Entry zone must sit above the stop, otherwise a fill at the low end is
    # already stopped out (seen live on TLT, 2026-09-25).
    entry_low = min(max(close * 0.98, stop + 0.5 * a), close)
    entry_high = close * 1.005
    risk = close - stop
    if key_res is not None and key_res > close:
        target = key_res
    else:
        target = close + 2 * risk
    rr = (target - close) / risk if risk > 0 else 0.0

    if light == "green":
        recommendation = "enter" if rr >= 2 else "wait"
    elif light == "yellow":
        recommendation = "wait"
    else:
        recommendation = "avoid"

    return TechnicalSnapshot(
        ticker=hist.ticker, close=round(close, 4),
        daily_return_pct=round(daily_ret, 3) if daily_ret is not None else None,
        wma200=round(wma, 4) if wma is not None else None, weekly_bars=len(weekly_closes),
        above_200wma=above_wma, structure_intact=structure,
        key_resistance=round(key_res, 4) if key_res is not None else None,
        resistance_distance_pct=round(res_dist, 2) if res_dist is not None else None,
        near_key_resistance=near_res, atr14=round(a, 4),
        support_low=round(support_low, 4), support_high=round(support_high, 4),
        entry_low=round(entry_low, 4), entry_high=round(entry_high, 4),
        stop_loss=round(stop, 4), target_price=round(target, 4),
        reward_risk_ratio=round(rr, 2), light=light, recommendation=recommendation,
        as_of=daily[-1].date, notes=notes,
    )


def describe(s: TechnicalSnapshot) -> str:
    """Human-readable, fully traceable explanation of the light."""
    wma = f"{s.wma200:.2f}" if s.wma200 is not None else "n/a"
    res = (f"{s.key_resistance:.2f} ({s.resistance_distance_pct:.1f}% away)"
           if s.resistance_distance_pct is not None else "none overhead")
    parts = [
        f"{s.ticker} {s.as_of} close {s.close:.2f} -> {s.light.upper()} ({s.recommendation})",
        f"200WMA {wma}: {'above' if s.above_200wma else 'NOT above'}",
        f"structure {'intact' if s.structure_intact else 'broken'}",
        f"resistance {res}{' - too close' if s.near_key_resistance else ''}",
        f"entry {s.entry_low:.2f}-{s.entry_high:.2f}, stop {s.stop_loss:.2f}, "
        f"target {s.target_price:.2f}, R/R {s.reward_risk_ratio:.2f}, ATR14 {s.atr14:.2f}",
    ]
    parts.extend(s.notes)
    return " | ".join(parts)
