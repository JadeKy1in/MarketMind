"""Minervini Trend Template, relative strength and VCP detection - all code (SPEC L3).

Source of the rules: M. Minervini, *Trade Like a Stock Market Wizard* (McGraw-Hill,
2013), ch. 5 (the Trend Template, 8 criteria) and ch. 10 (the volatility contraction
pattern). Each rule below is written out as a number so it can be checked and tested;
where the book describes a shape in words the precise definition is ours and says so.
None of the parameters were tuned on our data.

Trend Template (on the evaluated bar t, closes / highs / lows of complete daily bars):
  1. close > SMA150 and close > SMA200
  2. SMA150 > SMA200
  3. SMA200 rising for at least one month: SMA200[t] > SMA200[t - 21]
  4. SMA50 > SMA150 and SMA50 > SMA200
  5. close > SMA50
  6. close >= 1.30 x the 52-week low (the book's 30 %; some later summaries use 25 %)
  7. close >= 0.75 x the 52-week high ("within 25 % of the high")
  8. relative-strength rank >= 70
  52 weeks = the last 252 bars' intraday lows / highs, including bar t.

Relative strength: IBD's RS rating is proprietary. We use the common public
approximation that weights the latest quarter double:
  score = 0.4 r63 + 0.2 r126 + 0.2 r189 + 0.2 r252   (r_n = n-bar return)
ranked as a percentile 1-99 inside the scanned universe (not the whole market).

VCP (our precise reading of ch. 10: "successively smaller pullbacks, contracting volume,
a pivot, a breakout on volume"). For a breakout candidate bar t, on the bars before t:
  base start  s0 = the bar with the highest high of the last BASE_LOOKBACK (130) bars;
              the base must be >= BASE_MIN_BARS (15, three weeks) old at t.
  swing highs bar i whose high is the highest of bars i-3..i+3 (confirmed: 3 bars after).
  segments    from each swing high (s0 first) to the next swing high, the segment's low
              is the lowest low inside it; a segment whose low is not above the previous
              contraction's low extends that contraction (lower high + lower low = the
              same pullback still going; it is then measured from the higher of the two
              highs). So contractions have rising lows.
  contraction depth = (segment high - segment low) / segment high.
  pattern     2-6 contractions, each strictly shallower than the one before, the first
              <= 35 %, the last <= 10 % (the book's examples tighten to a few percent);
              volume dries up: mean volume of the last contraction < mean volume of the
              first contraction AND < the 50-bar average volume before t.
  pivot       the high of the last contraction.
  breakout    close[t] > pivot, close[t-1] <= pivot, volume[t] >= 1.4 x the 50-bar
              average volume before t (the widely quoted "40-50 % above average").
Stop: the last contraction's low, but never more than 8 % under the breakout close
(Minervini caps losses well under 10 %; 7-8 % is his and O'Neil's usual maximum).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from marketmind.gateway.price_history import Bar
from marketmind.trend.rules import sma

SMA_FAST, SMA_MID, SMA_SLOW = 50, 150, 200
RISING_BARS = 21
YEAR_BARS = 252
ABOVE_LOW = 1.30
NEAR_HIGH = 0.75
RS_MIN = 70
RS_WEIGHTS = ((63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2))
MIN_BARS = YEAR_BARS + 1                        # 52 weeks + SMA200 rising check fit inside

BASE_LOOKBACK = 130
BASE_MIN_BARS = 15
SWING_W = 3
MIN_CONTRACTIONS, MAX_CONTRACTIONS = 2, 6
MAX_FIRST_DEPTH, MAX_LAST_DEPTH = 0.35, 0.10
VOL_AVG_BARS = 50
BREAKOUT_VOL_MULT = 1.4
STOP_CAP = 0.08


# ── Trend Template ─────────────────────────────────────────────────────────

def template(bars: Sequence[Bar], rs_rank: float | None, t: int | None = None) -> dict:
    """The 8 criteria on bar t (default: the last bar): {'passed', 'criteria', values}."""
    t = len(bars) - 1 if t is None else t
    if t + 1 < MIN_BARS:
        return {"passed": False, "reason": f"insufficient history: {t + 1} < {MIN_BARS} bars"}
    closes = [b.close for b in bars[:t + 1]]
    s50, s150, s200 = (sma(closes, n) for n in (SMA_FAST, SMA_MID, SMA_SLOW))
    c = closes[-1]
    year = bars[t + 1 - YEAR_BARS:t + 1]
    lo52, hi52 = min(b.low for b in year), max(b.high for b in year)
    a50, a150, a200, a200_ago = s50[-1], s150[-1], s200[-1], s200[-1 - RISING_BARS]
    crit = {
        "close_above_sma150_sma200": c > a150 and c > a200,
        "sma150_above_sma200": a150 > a200,
        "sma200_rising_1m": a200_ago is not None and a200 > a200_ago,
        "sma50_above_sma150_sma200": a50 > a150 and a50 > a200,
        "close_above_sma50": c > a50,
        "close_30pct_above_52w_low": c >= ABOVE_LOW * lo52,
        "within_25pct_of_52w_high": c >= NEAR_HIGH * hi52,
        "rs_rank_ge_70": rs_rank is not None and rs_rank >= RS_MIN,
    }
    return {"passed": all(crit.values()), "criteria": crit, "close": c,
            "sma50": round(a50, 4), "sma150": round(a150, 4), "sma200": round(a200, 4),
            "sma200_21_bars_ago": None if a200_ago is None else round(a200_ago, 4),
            "low_52w": lo52, "high_52w": hi52,
            "pct_above_52w_low": round(c / lo52 - 1, 4) if lo52 > 0 else None,
            "pct_below_52w_high": round(1 - c / hi52, 4) if hi52 > 0 else None,
            "rs_rank": rs_rank}


# ── relative strength ──────────────────────────────────────────────────────

def rs_score(bars: Sequence[Bar], t: int | None = None) -> float | None:
    t = len(bars) - 1 if t is None else t
    total = 0.0
    for n, w in RS_WEIGHTS:
        if t - n < 0 or bars[t - n].close <= 0:
            return None
        total += w * (bars[t].close / bars[t - n].close - 1)
    return total


def rs_ranks(scores: dict[str, float | None]) -> dict[str, float]:
    """Percentile ranks 1-99 of the available scores (ties: alphabetical order)."""
    order = sorted((s, k) for k, s in scores.items() if s is not None)
    n = len(order)
    if n == 0:
        return {}
    if n == 1:
        return {order[0][1]: 99.0}
    return {k: round(1 + 98 * i / (n - 1), 1) for i, (_, k) in enumerate(order)}


# ── VCP ────────────────────────────────────────────────────────────────────

@dataclass
class Contraction:
    high_idx: int
    high: float
    low_idx: int
    low: float
    end_idx: int                     # exclusive end of the span (next contraction's start)

    @property
    def depth(self) -> float:
        return (self.high - self.low) / self.high if self.high > 0 else 0.0


@dataclass
class Vcp:
    ok: bool
    reason: str
    contractions: list[Contraction] = field(default_factory=list)
    base_start: int | None = None
    pivot: float | None = None
    pivot_idx: int | None = None
    vol_last: float | None = None
    vol_first: float | None = None
    vol_avg50: float | None = None

    def facts(self, bars: Sequence[Bar]) -> dict:
        return {"vcp_ok": self.ok, "vcp_reason": self.reason,
                "base_start": None if self.base_start is None else bars[self.base_start].date,
                "contractions": [{"high_date": bars[c.high_idx].date, "high": c.high,
                                  "low_date": bars[c.low_idx].date, "low": c.low,
                                  "depth": round(c.depth, 4)} for c in self.contractions],
                "pivot": self.pivot,
                "pivot_date": None if self.pivot_idx is None else bars[self.pivot_idx].date,
                "vol_last_contraction": _r(self.vol_last), "vol_first_contraction": _r(self.vol_first),
                "vol_avg50": _r(self.vol_avg50)}


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 2)


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def swing_highs(bars: Sequence[Bar], lo: int, hi: int, w: int = SWING_W) -> list[int]:
    """Confirmed swing highs i in [lo, hi): high[i] is the maximum of bars i-w..i+w, all
    of which lie inside [lo, hi) (a later equal high does not form a second pivot)."""
    out = []
    for i in range(lo + w, hi - w):
        h = bars[i].high
        if all(bars[j].high < h for j in range(i - w, i)) and \
                all(bars[j].high <= h for j in range(i + 1, i + w + 1)):
            out.append(i)
    return out


def contractions(bars: Sequence[Bar], s0: int, end: int) -> list[Contraction]:
    """Pullbacks from the base start s0 to `end` (exclusive), merged as described above."""
    starts = [s0] + [i for i in swing_highs(bars, s0, end) if i > s0]
    out: list[Contraction] = []
    for k, h in enumerate(starts):
        stop = starts[k + 1] if k + 1 < len(starts) else end
        span = range(h, stop)
        li = min(span, key=lambda j: (bars[j].low, j))
        seg = Contraction(h, bars[h].high, li, bars[li].low, stop)
        if out and seg.low <= out[-1].low:
            prev = out[-1]                         # the previous pullback is still going
            if seg.high > prev.high:               # measured from the higher of the two highs
                prev.high, prev.high_idx = seg.high, seg.high_idx
            prev.low, prev.low_idx, prev.end_idx = seg.low, seg.low_idx, seg.end_idx
        else:
            out.append(seg)
    return out


def detect_vcp(bars: Sequence[Bar], t: int) -> Vcp:
    """Is bar t a VCP pivot breakout? Uses bars[: t] for the pattern and bar t for the
    breakout; nothing after t."""
    if t < VOL_AVG_BARS + BASE_MIN_BARS or t < 1:
        return Vcp(False, "insufficient history")
    lo = max(0, t - BASE_LOOKBACK)
    s0 = max(range(lo, t), key=lambda i: (bars[i].high, -i))          # earliest highest high
    if t - s0 < BASE_MIN_BARS:
        return Vcp(False, f"base only {t - s0} bars old (< {BASE_MIN_BARS})", base_start=s0)
    cons = contractions(bars, s0, t)
    v = Vcp(False, "", cons, s0)
    if not MIN_CONTRACTIONS <= len(cons) <= MAX_CONTRACTIONS:
        v.reason = f"{len(cons)} contractions (need {MIN_CONTRACTIONS}-{MAX_CONTRACTIONS})"
        return v
    depths = [c.depth for c in cons]
    if any(b >= a for a, b in zip(depths, depths[1:])):
        v.reason = "pullbacks do not get successively smaller: " + \
                   ", ".join(f"{d:.1%}" for d in depths)
        return v
    if depths[0] > MAX_FIRST_DEPTH:
        v.reason = f"first pullback {depths[0]:.1%} > {MAX_FIRST_DEPTH:.0%}"
        return v
    if depths[-1] > MAX_LAST_DEPTH:
        v.reason = f"last pullback {depths[-1]:.1%} > {MAX_LAST_DEPTH:.0%}"
        return v
    first, last = cons[0], cons[-1]
    v.vol_first = _mean([b.volume for b in bars[first.high_idx:first.end_idx]])
    v.vol_last = _mean([b.volume for b in bars[last.high_idx:t]])
    v.vol_avg50 = _mean([b.volume for b in bars[t - VOL_AVG_BARS:t]])
    v.pivot, v.pivot_idx = last.high, last.high_idx
    if not (v.vol_last is not None and v.vol_first and v.vol_avg50
            and v.vol_last < v.vol_first and v.vol_last < v.vol_avg50):
        v.reason = "volume does not dry up in the last contraction"
        return v
    c, prev = bars[t].close, bars[t - 1].close
    if not (c > v.pivot and prev <= v.pivot):
        v.reason = f"no first close above the pivot {v.pivot:.4g} on {bars[t].date}"
        return v
    if bars[t].volume < BREAKOUT_VOL_MULT * v.vol_avg50:
        v.reason = (f"breakout volume {bars[t].volume / v.vol_avg50:.2f}x the 50-bar average "
                    f"(< {BREAKOUT_VOL_MULT}x)")
        return v
    v.ok, v.reason = True, "pivot breakout on volume"
    return v


def stop_level(close: float, last_low: float) -> tuple[float, str]:
    """(stop, basis): the last contraction low, capped at STOP_CAP under the close."""
    cap = close * (1 - STOP_CAP)
    if last_low >= cap:
        return round(last_low, 6), "last contraction low"
    return round(cap, 6), f"{STOP_CAP:.0%} under the breakout close (last contraction low {last_low:.4g} is deeper)"
