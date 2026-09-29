"""Forced daily decision: schema, parsing and validation (docs/S3_DESIGN.md §3.2).

The LLM returns JSON; code decides what is valid. Hard errors drop a decision
(unknown ticker, bad direction, missing falsifier ...); soft errors drop only
the offending optional field (an inverted stop, a falsifier rule on the wrong
side) and are reported. Nothing is invented to fill a gap.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

MIN_DECISIONS = 1
MAX_DECISIONS = 3
MIN_HOLD, MAX_HOLD = 1, 60
MIN_POSITION_USD, MAX_POSITION_USD = 100.0, 1000.0


@dataclass
class Decision:
    ticker: str
    direction: str                 # long | short
    hold_days: int
    confidence: float
    falsifier: str
    thesis: str
    falsifier_rule: dict | None = None
    stop: float | None = None
    target: float | None = None

    @property
    def position_usd(self) -> float:
        return position_for(self.confidence)


@dataclass
class ParseResult:
    decisions: list[Decision] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)      # decision dropped
    warnings: list[str] = field(default_factory=list)    # field dropped

    @property
    def ok(self) -> bool:
        return len(self.decisions) >= MIN_DECISIONS


def position_for(confidence: float) -> float:
    """$100 at confidence <= 0.5, linear to $1,000 at 1.0 (SPEC §6.1: minimum $100)."""
    if confidence <= 0.5:
        return MIN_POSITION_USD
    frac = min(1.0, (confidence - 0.5) / 0.5)
    return round(MIN_POSITION_USD + frac * (MAX_POSITION_USD - MIN_POSITION_USD), 2)


def extract_json(text: str) -> Any:
    """First JSON object in `text` (fenced or bare); raises ValueError if none parses."""
    if not text or not text.strip():
        raise ValueError("empty response")
    candidates = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    # outermost object or list, whichever opens first
    spans = [(text.find(o), text.rfind(c) + 1) for o, c in (("{", "}"), ("[", "]"))]
    for start, end in sorted(sp for sp in spans if sp[0] >= 0):
        candidates.append(text[start:end])
    for c in candidates:
        try:
            return json.loads(c.strip())
        except json.JSONDecodeError:
            continue
    raise ValueError("no parseable JSON object in response")


def _num(v) -> float | None:
    """A finite float, or None. json.loads accepts NaN/Infinity and float() accepts
    "nan"/"inf"; neither is a usable price, probability or day count."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _bad_number(v) -> bool:
    """True when a value was given but is not a finite number."""
    return v is not None and v != "" and _num(v) is None


def parse_decisions(text: str, closes: dict[str, float], fixed_hold: int | None = None,
                    no_levels: set[str] | frozenset = frozenset()) -> ParseResult:
    """Validate the LLM's decisions against today's context.

    `closes`: ticker -> last close for every tradable ticker with data (the
    context plus any off-context ticker the runner priced). `no_levels`: tickers
    the shadow never saw prices for - their stop/target/rule are dropped, since
    those numbers could only be invented. `fixed_hold` forces hold_days (scalper = 1).
    """
    res = ParseResult()
    try:
        data = extract_json(text)
    except ValueError as e:
        res.errors.append(str(e))
        return res
    raw = data.get("decisions") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        res.errors.append("'decisions' must be a list")
        return res
    if len(raw) > MAX_DECISIONS:
        res.warnings.append(f"{len(raw)} decisions given, only the first {MAX_DECISIONS} kept")
        raw = raw[:MAX_DECISIONS]

    upper = {t.upper(): t for t in closes}
    seen: set[tuple[str, str]] = set()
    for i, d in enumerate(raw, 1):
        tag = f"decision {i}"
        if not isinstance(d, dict):
            res.errors.append(f"{tag}: not an object")
            continue
        try:
            _parse_one(d, tag, closes, upper, seen, fixed_hold, no_levels, res)
        except Exception as e:  # noqa: BLE001 - one bad decision must not cost the day
            res.errors.append(f"{tag}: could not be read ({type(e).__name__}: {e})")
    return res


def _parse_one(d: dict, tag: str, closes: dict[str, float], upper: dict[str, str],
               seen: set[tuple[str, str]], fixed_hold: int | None,
               no_levels: set[str] | frozenset, res: ParseResult) -> None:
    """Validate one decision; appends to res.decisions or res.errors."""
    ticker = upper.get(str(d.get("ticker", "")).strip().upper().lstrip("$"))
    if ticker is None:
        res.errors.append(f"{tag}: ticker {d.get('ticker')!r} is not in today's context")
        return
    direction = str(d.get("direction", "")).strip().lower()
    if direction not in ("long", "short"):
        res.errors.append(f"{tag}: direction must be long or short (no abstaining), "
                          f"got {d.get('direction')!r}")
        return
    if (ticker, direction) in seen:
        res.errors.append(f"{tag}: duplicate {direction} {ticker}")
        return
    conf = _num(d.get("confidence"))
    if conf is None or not 0.0 <= conf <= 1.0:
        res.errors.append(f"{tag}: confidence must be a number in 0-1, "
                          f"got {d.get('confidence')!r}")
        return
    for key in ("stop", "target") + (("hold_days",) if fixed_hold is None else ()):
        if _bad_number(d.get(key)):
            res.errors.append(f"{tag}: {key} must be a finite number, got {d.get(key)!r}")
            return
    hold = _num(d.get("hold_days"))
    if fixed_hold is not None:
        if hold is not None and int(hold) != fixed_hold:
            res.warnings.append(f"{tag}: hold_days set to {fixed_hold} for this shadow")
        hold = fixed_hold
    if hold is None or int(hold) != hold or not MIN_HOLD <= hold <= MAX_HOLD:
        res.errors.append(f"{tag}: hold_days must be an integer {MIN_HOLD}-{MAX_HOLD}, "
                          f"got {d.get('hold_days')!r}")
        return
    falsifier = str(d.get("falsifier") or "").strip()
    thesis = str(d.get("thesis") or "").strip()
    if not falsifier:
        res.errors.append(f"{tag}: falsifier is required")
        return
    if not thesis:
        res.errors.append(f"{tag}: thesis is required")
        return

    close = closes[ticker]
    long = direction == "long"
    stop, target = _num(d.get("stop")), _num(d.get("target"))
    if ticker in no_levels and (stop is not None or target is not None
                                or d.get("falsifier_rule")):
        res.warnings.append(f"{tag}: {ticker} was not in your context, so its price "
                            f"levels are dropped (text falsifier kept)")
        stop = target = None
        d = {**d, "falsifier_rule": None}
    if stop is not None and not (stop < close if long else stop > close):
        res.warnings.append(f"{tag}: stop {stop} on the wrong side of close {close}, dropped")
        stop = None
    if target is not None and not (target > close if long else target < close):
        res.warnings.append(f"{tag}: target {target} on the wrong side of close {close}, "
                            f"dropped")
        target = None
    rule = _falsifier_rule(d.get("falsifier_rule"), long, close, tag, res)

    seen.add((ticker, direction))
    res.decisions.append(Decision(
        ticker=ticker, direction=direction, hold_days=int(hold), confidence=round(conf, 4),
        falsifier=falsifier[:500], thesis=thesis[:500], falsifier_rule=rule,
        stop=stop, target=target,
    ))


def _falsifier_rule(raw, long: bool, close: float, tag: str, res: ParseResult) -> dict | None:
    """close_below below the price for longs, close_above above it for shorts; else dropped."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        res.warnings.append(f"{tag}: falsifier_rule is not an object, dropped")
        return None
    kind, price = raw.get("type"), _num(raw.get("price"))
    valid = price is not None and (
        (kind == "close_below" and long and price < close)
        or (kind == "close_above" and not long and price > close))
    if not valid:
        res.warnings.append(f"{tag}: falsifier_rule {raw!r} does not fit a "
                            f"{'long' if long else 'short'} at {close}, dropped")
        return None
    return {"type": kind, "price": price}


OUTPUT_INSTRUCTIONS = f"""
## Output format (required)
Reply with ONE JSON object and nothing else:
{{"decisions": [
  {{"ticker": "<symbol from today's context>",
    "direction": "long" | "short",
    "hold_days": <integer {MIN_HOLD}-{MAX_HOLD}>,
    "confidence": <probability this trade is profitable after costs, 0-1>,
    "thesis": "<one sentence, in Chinese>",
    "falsifier": "<I am wrong if ..., concrete and checkable, in Chinese>",
    "falsifier_rule": {{"type": "close_below" | "close_above", "price": <number>}} or null,
    "stop": <number or null>,
    "target": <number or null>}}
]}}
Rules: {MIN_DECISIONS}-{MAX_DECISIONS} decisions, at least one every day - abstaining is not
allowed. Any instrument in your domain that trades on a real market worldwide is allowed
(Yahoo-style symbols: AAPL, 0700.HK, 600519.SS, 7203.T, SAP.DE, CL=F, EURUSD=X, BTC-USD;
not bare indices like ^N225 - use an ETF or future). Prefer tickers in today's context:
for any other ticker you have no prices, so give no stop/target/falsifier_rule for it.
Entry is the next session's open.
falsifier_rule: close_below (for a long) or close_above (for a short) a price level.
For a long, stop < last close < target; mirrored for a short. Use prices from the
context only; never invent data. The placeholders above are not suggestions.
""".strip()
