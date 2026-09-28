"""Watch-item confirmation conditions (docs/S10_DESIGN.md §3). Pure code, no I/O, no LLM.

Only code-checkable conditions are accepted; anything else is rejected at
validation time so an LLM cannot smuggle in a vague "wait for strength".
Every condition is evaluated on one completed daily bar, using the complete
series up to and including that bar:

  close_above            {"price": p}      close > p
  close_below            {"price": p}      close < p
  close_above_ma         {"period": n}     close > SMA(close, n), n in 20/50/200
  close_below_ma         {"period": n}     close < SMA(close, n)
  volume_ratio_at_least  {"ratio": r}      volume >= r * mean(volume of the prior 20 bars)
  after_date             {"date": d}       bar date > d (e.g. wait for a data release on d)
  breakout_20d           {}                long: close > max(high of the prior 20 bars);
                                           short: close < min(low of the prior 20 bars)

An optional free-text "note" is kept for display and never evaluated.
A condition that cannot be evaluated (too little history, zero volume) is not met.
"""
from __future__ import annotations

from datetime import date

from marketmind.gateway.price_history import Bar
from marketmind.pipeline.l3_indicators import sma

MA_PERIODS = (20, 50, 200)
VOLUME_LOOKBACK = 20
BREAKOUT_LOOKBACK = 20
MAX_VOLUME_RATIO = 50.0

# type -> required parameter keys
SCHEMA: dict[str, tuple[str, ...]] = {
    "close_above": ("price",),
    "close_below": ("price",),
    "close_above_ma": ("period",),
    "close_below_ma": ("period",),
    "volume_ratio_at_least": ("ratio",),
    "after_date": ("date",),
    "breakout_20d": (),
}
OPTIONAL_KEYS = ("note",)


def validate_condition(cond) -> dict:
    """Normalised copy of `cond`; ValueError for anything outside SCHEMA."""
    if not isinstance(cond, dict):
        raise ValueError(f"condition must be an object, got {type(cond).__name__}")
    ctype = cond.get("type")
    if ctype not in SCHEMA:
        raise ValueError(f"unknown condition type {ctype!r} (allowed: {', '.join(SCHEMA)})")
    required = SCHEMA[ctype]
    extra = set(cond) - {"type", *required, *OPTIONAL_KEYS}
    if extra:
        raise ValueError(f"{ctype}: unexpected keys {sorted(extra)}")
    missing = [k for k in required if cond.get(k) is None]
    if missing:
        raise ValueError(f"{ctype}: missing {missing}")
    out: dict = {"type": ctype}
    if "price" in required:
        out["price"] = _positive(cond["price"], f"{ctype}.price")
    if "period" in required:
        try:
            period = int(cond["period"])
        except (TypeError, ValueError):
            raise ValueError(f"{ctype}.period must be one of {MA_PERIODS}") from None
        if period not in MA_PERIODS or float(cond["period"]) != period:
            raise ValueError(f"{ctype}.period must be one of {MA_PERIODS}")
        out["period"] = period
    if "ratio" in required:
        ratio = _positive(cond["ratio"], f"{ctype}.ratio")
        if ratio > MAX_VOLUME_RATIO:
            raise ValueError(f"{ctype}.ratio must be <= {MAX_VOLUME_RATIO}")
        out["ratio"] = ratio
    if "date" in required:
        try:
            out["date"] = date.fromisoformat(str(cond["date"])).isoformat()
        except ValueError:
            raise ValueError(f"{ctype}.date must be YYYY-MM-DD") from None
        if out["date"] != str(cond["date"]):
            raise ValueError(f"{ctype}.date must be YYYY-MM-DD")
    note = cond.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise ValueError(f"{ctype}.note must be text")
        out["note"] = note.strip()[:200]
    return out


def validate_conditions(conds, *, allow_empty: bool = False) -> list[dict]:
    if conds is None:
        conds = []
    if not isinstance(conds, (list, tuple)):
        raise ValueError("conditions must be a list")
    if not conds and not allow_empty:
        raise ValueError("at least one condition is required")
    return [validate_condition(c) for c in conds]


def _positive(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not v > 0 or v == float("inf"):          # also rejects NaN
        raise ValueError(f"{name} must be a positive number")
    return v


def evaluate(cond: dict, bars: list[Bar], direction: str) -> tuple[bool, str]:
    """(met, detail) on the last bar of `bars` (complete bars, oldest first)."""
    if not bars:
        return False, "no bars"
    b = bars[-1]
    ctype = cond["type"]
    if ctype == "close_above":
        return b.close > cond["price"], f"close {b.close:.4g} vs {cond['price']:.4g}"
    if ctype == "close_below":
        return b.close < cond["price"], f"close {b.close:.4g} vs {cond['price']:.4g}"
    if ctype in ("close_above_ma", "close_below_ma"):
        n = cond["period"]
        ma = sma([x.close for x in bars], n)
        if ma is None:
            return False, f"only {len(bars)} bars (< {n}); MA{n} unavailable"
        met = b.close > ma if ctype == "close_above_ma" else b.close < ma
        return met, f"close {b.close:.4g} vs MA{n} {ma:.4g}"
    if ctype == "volume_ratio_at_least":
        prior = bars[-VOLUME_LOOKBACK - 1:-1]
        if len(prior) < VOLUME_LOOKBACK:
            return False, f"only {len(prior)} prior bars (< {VOLUME_LOOKBACK}); volume ratio unavailable"
        avg = sum(x.volume for x in prior) / len(prior)
        if avg <= 0:
            return False, "no volume data"
        ratio = b.volume / avg
        return ratio >= cond["ratio"], f"volume {ratio:.2f}x 20-day avg vs {cond['ratio']:g}x"
    if ctype == "after_date":
        return b.date > cond["date"], f"bar {b.date} vs after {cond['date']}"
    if ctype == "breakout_20d":
        prior = bars[-BREAKOUT_LOOKBACK - 1:-1]
        if len(prior) < BREAKOUT_LOOKBACK:
            return False, f"only {len(prior)} prior bars (< {BREAKOUT_LOOKBACK}); 20-day range unavailable"
        if direction == "short":
            low = min(x.low for x in prior)
            return b.close < low, f"close {b.close:.4g} vs prior 20-day low {low:.4g}"
        high = max(x.high for x in prior)
        return b.close > high, f"close {b.close:.4g} vs prior 20-day high {high:.4g}"
    raise ValueError(f"unknown condition type {ctype!r}")


def describe(cond: dict, direction: str = "long") -> str:
    """Short Chinese label for reports and push messages."""
    ctype = cond["type"]
    if ctype == "close_above":
        return f"收盘价上破 {cond['price']:g}"
    if ctype == "close_below":
        return f"收盘价跌破 {cond['price']:g}"
    if ctype == "close_above_ma":
        return f"收盘站上 {cond['period']} 日均线"
    if ctype == "close_below_ma":
        return f"收盘跌破 {cond['period']} 日均线"
    if ctype == "volume_ratio_at_least":
        return f"成交量 ≥ {cond['ratio']:g} 倍 20 日均量"
    if ctype == "after_date":
        return f"{cond['date']} 之后"
    if ctype == "breakout_20d":
        return "收盘跌破前 20 日低点" if direction == "short" else "收盘突破前 20 日高点"
    return ctype
