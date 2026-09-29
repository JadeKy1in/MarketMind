"""Settle ledger records from daily bars (SPEC_v3 §7, S2 acceptance).

Rules (all code, no judgement; see docs/S2_DESIGN.md §4):
  Entry   next_open: open of the first bar dated after the record's creation date.
          zone:      first bar (within ENTRY_WINDOW_BARS bars after creation, or
                     hold_bars if shorter) that trades into
                     the zone; long fills at min(open, entry_high), short at
                     max(open, entry_low). Never filled inside the window -> void.
          A fill at the open that is already at/beyond the target -> void
          (gap_target; owner decision 2026-09-29: the card was dead before entry).
          A fill at the open already at/beyond the stop is a loss, not void (owner
          decision 2026-09-29, second revision: voiding it biased scores upward by
          ~0.24%/trade): exit "stop" at that open, measured against the stop level,
          entry_price = stop, exit_price = open, gross = direction * (open / stop - 1).
  Exit    checked bar by bar from the fill bar, in this order:
          gap     an open already beyond the target exits there as target (the order
                  fills at that open), checked before the stop.
          stop    long: low <= stop (gap through -> the open); short mirrored.
          target  long: high >= target (gap through -> the open). On a zone fill bar
                  that did not fill at the open, the target is not credited (the
                  intrabar order is unknown). Stop and target on the same bar -> stop.
          falsifier rule  close_below / close_above -> exit at that close.
          expiry  close of the hold_bars-th bar counting the fill bar.
  Crypto  (24/7, UTC-day bars) counts calendar days: the fill bar must be the first
          expected UTC day and the holding window must have a bar for every day up to
          the exit; a missing day leaves the record unsettled ("data gap <date>").
  Returns net = direction * (exit / entry - 1) - 2 * cost_bps / 10_000.
  Benchmarks  buy-and-hold over the same dates: open on the entry date to close on
          the exit date, each aligned to the nearest benchmark bar within
          BENCHMARK_ALIGN_DAYS (entry on/after, exit on/before; e.g. a US-ETF domain
          benchmark on a foreign record whose date is a US holiday). Market benchmark:
          BTC-USD for crypto, SPY otherwise. The benchmark leg takes the record's
          direction: excess = net - sign * benchmark (sign +1 long, -1 short).
  Brier   (confidence - outcome)^2, outcome = 1 if net > 0 else 0.
  Adjusted prices  sources return split/dividend-adjusted series, so a later corporate
          action rescales past bars. Price levels (zone, stop, target, falsifier) are
          multiplied by close(snapshot date in the current series) / snapshot price
          before simulating; returns are then in the current series (total return).
          Only a snapshot from the same data source is compared (two sources differ
          by a few bp without any corporate action).
  Benchmark backfill  a settled record whose benchmark data was missing is retried
          on later runs; only the benchmark fields change. Still missing
          BENCHMARK_GIVE_UP_DAYS after the exit -> "benchmark not comparable", final.
  Missing data leaves the record unsettled with a note; nothing is estimated.
  Only complete bars are used (price_history.complete_bars: each market's own
  session close; UTC days for crypto/FX), because a data source returns the
  running session as a partial bar.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from marketmind.gateway.price_history import Bar, complete_bars
from marketmind.markets import CASH, market_for
from marketmind.ledger.prices import PriceSource, source_of
from marketmind.ledger.store import UNSETTLED, LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.ledger.settlement")


# One-way cost in basis points. Crypto: Robinhood's default (market-maker)
# routing quotes a 0.96% buy spread on $100 of BTC, $0.95 of it Robinhood's
# rebate, for every coin (robinhood.com/us/en/support/articles/crypto-order-routing,
# checked 2026-09-28) -> 100 bp for BTC/ETH; other coins have wider maker
# spreads on top (+25 bp is an estimate, not a published number).
CRYPTO_MAJORS = frozenset({"BTC", "ETH"})
CRYPTO_MAJOR_BPS = 100.0
CRYPTO_OTHER_BPS = 125.0
DEFAULT_COST_BPS = 5.0

# A zone order not reached within this many bars is void (owner decision
# 2026-09-27: do not chase; a missed entry is dropped, not left open for the
# whole holding period).
ENTRY_WINDOW_BARS = 5


def entry_window(e: LedgerEntry) -> int:
    return min(e.hold_bars, ENTRY_WINDOW_BARS)


def cost_bps(asset_type: str, ticker: str = "") -> float:
    """One-way cost: crypto by coin (majors vs the rest), else by market."""
    market = market_for(ticker) if ticker else None
    if asset_type == "crypto" or (market is not None and market.code == "CRYPTO"):
        base = ticker.upper().split("-")[0]
        return CRYPTO_MAJOR_BPS if base in CRYPTO_MAJORS else CRYPTO_OTHER_BPS
    return market.cost_bps if market is not None else DEFAULT_COST_BPS


def market_benchmark(entry: LedgerEntry) -> str:
    """SPY for US, BTC-USD for crypto, the local index/ETF abroad, CASH for FX/rates."""
    if is_crypto(entry):
        return "BTC-USD"
    return market_for(entry.ticker).benchmark


@dataclass
class Fill:
    index: int
    price: float
    at_open: bool


@dataclass
class Outcome:
    status: str                       # pending | open | settled | void
    note: str = ""
    fill: Fill | None = None
    exit_index: int | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    entry_price: float | None = None  # overrides fill.price (gap through the stop)


def _find_fill(e: LedgerEntry, bars: list[Bar]) -> Fill | None | str:
    """Fill on `bars` (already restricted to bars after creation); 'void' if the window lapsed."""
    if e.entry_rule == "next_open":
        return Fill(0, bars[0].open, True) if bars else None
    window = entry_window(e)
    for i, b in enumerate(bars[:window]):
        if e.direction == "long" and b.low <= e.entry_high:
            price = min(b.open, e.entry_high)
            return Fill(i, price, price == b.open)
        if e.direction == "short" and b.high >= e.entry_low:
            price = max(b.open, e.entry_low)
            return Fill(i, price, price == b.open)
    return "void" if len(bars) >= window else None


def first_bar_date(e: LedgerEntry) -> str | None:
    """Earliest bar date the record could trade on (None without a creation time).

    Crypto and FX bars are UTC days, so the first usable bar is the next UTC date.
    Exchange bars are local sessions (marketmind.markets): a record created before
    the local open can still fill at that day's open (e.g. a US record written at
    09:00 Beijing time, or a Tokyo record written the previous evening UTC).
    """
    ts = _parse_ts(e.created_at)
    if ts is None:
        return None
    m = market_for(e.ticker)
    if is_crypto(e) or m.utc_days:
        return (ts.astimezone(timezone.utc).date() + timedelta(days=1)).isoformat()
    local = ts.astimezone(ZoneInfo(m.tz))
    before_open = local.time() < m.open
    return (local.date() if before_open else local.date() + timedelta(days=1)).isoformat()


def bars_after_creation(e: LedgerEntry, bars: list[Bar]) -> list[Bar]:
    """Bars the record could first trade on (see first_bar_date)."""
    first = first_bar_date(e)
    return list(bars) if first is None else [b for b in bars if b.date >= first]


def target_session(e: LedgerEntry) -> str | None:
    """The session a record is a decision for: its first bar date, moved past the
    weekend for everything but crypto (no exchange holiday calendar is known, so a
    holiday is not skipped). Submissions are deduplicated on this (docs/S2_DESIGN.md §4)."""
    first = first_bar_date(e)
    if first is None or is_crypto(e):
        return first
    day = date.fromisoformat(first)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def calendar_run(e: LedgerEntry, after: list[Bar]) -> tuple[list[Bar], str | None]:
    """Crypto: the bars of consecutive calendar days from the first expected day,
    and the first missing day when a later bar shows it is a gap (else None)."""
    first = first_bar_date(e)
    if first is None:
        return after, None
    day = date.fromisoformat(first)
    for i, b in enumerate(after):
        if b.date != day.isoformat():
            return after[:i], day.isoformat()
        day += timedelta(days=1)
    return after, None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def is_crypto(e: LedgerEntry) -> bool:
    return e.asset_type == "crypto" or e.ticker.upper().endswith("-USD")


def simulate(e: LedgerEntry, bars: list[Bar], decision_price: float | None = None) -> Outcome:
    """`decision_price`: the snapshot price at decision time in the current series; a
    gap through the stop at the open is measured from it (see _simulate)."""
    after = bars_after_creation(e, bars)
    gap = None
    if is_crypto(e):
        # 24/7 market: bar index == calendar day only without holes (never estimated)
        after, gap = calendar_run(e, after)
    out = _simulate(e, after, decision_price)
    if gap and out.status in UNSETTLED:
        out.note = f"data gap {gap}"
    return out


def _simulate(e: LedgerEntry, after: list[Bar], decision_price: float | None = None) -> Outcome:
    fill = _find_fill(e, after)
    if fill is None:
        return Outcome("pending", "waiting for the first bar after creation"
                       if not after else "entry zone not reached yet")
    if fill == "void":
        return Outcome("void", f"entry zone not reached within {entry_window(e)} bars",
                       exit_reason="unfilled")

    if e.hold_bars <= 1:
        # A one-bar (intraday) call: a daily bar cannot tell whether the stop or the
        # target came first, so only the direction from fill to close is scored
        # (owner decision 2026-09-29); stop, target, falsifier and the gap rule are ignored.
        return Outcome("settled", "one-bar record: scored on fill-to-close direction only",
                       fill=fill, exit_index=fill.index, exit_price=after[fill.index].close,
                       exit_reason="expiry")
    long = e.direction == "long"
    if fill.at_open and (gap := gapped_past(e, fill.price)):
        if gap == "stop":
            # The call was already wrong by the open: score the whole adverse move from
            # the decision-time price to the open (owner decision 2026-09-29). Voiding it
            # inflated scores; measuring only the part beyond the stop understated it.
            ref = decision_price if decision_price and decision_price > 0 else e.stop_loss
            basis = "decision price" if ref == decision_price else "stop (no snapshot price)"
            return Outcome("settled", f"gapped through the stop at the open; loss from the {basis}",
                           fill=fill, exit_index=fill.index, exit_price=fill.price,
                           exit_reason="stop", entry_price=ref)
        return Outcome("void", f"opened at {fill.price:.6g}, already past the {gap} before entry",
                       exit_reason=f"gap_{gap}")
    last = fill.index + e.hold_bars - 1
    for j in range(fill.index, min(last, len(after) - 1) + 1):
        b = after[j]
        ref_open = fill.price if j == fill.index else b.open
        open_known = j > fill.index or fill.at_open
        if (open_known and e.target_price is not None
                and (b.open >= e.target_price if long else b.open <= e.target_price)):
            return Outcome("settled", fill=fill, exit_index=j, exit_price=b.open,
                           exit_reason="target")
        if e.stop_loss is not None and (b.low <= e.stop_loss if long else b.high >= e.stop_loss):
            px = min(ref_open, e.stop_loss) if long else max(ref_open, e.stop_loss)
            return Outcome("settled", fill=fill, exit_index=j, exit_price=px, exit_reason="stop")
        target_allowed = j > fill.index or fill.at_open
        if (target_allowed and e.target_price is not None
                and (b.high >= e.target_price if long else b.low <= e.target_price)):
            px = max(ref_open, e.target_price) if long else min(ref_open, e.target_price)
            return Outcome("settled", fill=fill, exit_index=j, exit_price=px, exit_reason="target")
        rule = e.falsifier_rule or {}
        level = rule.get("price")
        level = float(level) if level is not None else None
        if level is not None and (
            (rule.get("type") == "close_below" and b.close < level)
            or (rule.get("type") == "close_above" and b.close > level)
        ):
            return Outcome("settled", fill=fill, exit_index=j, exit_price=b.close,
                           exit_reason="falsifier")
        if j == last:
            return Outcome("settled", fill=fill, exit_index=j, exit_price=b.close,
                           exit_reason="expiry")
    return Outcome("open", f"{len(after) - fill.index}/{e.hold_bars} bars held", fill=fill)


def gapped_past(e: LedgerEntry, open_price: float) -> str | None:
    """'stop' / 'target' if the entry open is already at or beyond that level."""
    long = e.direction == "long"
    if e.stop_loss is not None and (open_price <= e.stop_loss if long else open_price >= e.stop_loss):
        return "stop"
    if e.target_price is not None and (open_price >= e.target_price if long
                                       else open_price <= e.target_price):
        return "target"
    return None


# A benchmark bar may be this many calendar days off the record's entry / exit date
# (the benchmark's market was closed that day, e.g. a US-ETF domain benchmark on a
# foreign record). Still missing this long after the exit -> not comparable, final.
BENCHMARK_ALIGN_DAYS = 3
BENCHMARK_GIVE_UP_DAYS = 10
BENCH_MISSING = "benchmark data unavailable"
BENCH_NOT_COMPARABLE = "benchmark not comparable"


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def benchmark_return(bars: list[Bar] | None, start: str, end: str) -> float | None:
    """Open of the first bar on/after `start` to close of the last bar on/before `end`,
    each at most BENCHMARK_ALIGN_DAYS away. A shifted date must be an interior gap
    (bars exist on its other side), so a stale or short series is never passed off
    as the real return."""
    if not bars:
        return None
    first = next((b for b in bars if b.date >= start), None)
    last = next((b for b in reversed(bars) if b.date <= end), None)
    if first is None or last is None or first.date > last.date or first.open <= 0:
        return None
    if first.date != start and (first.date > _shift(start, BENCHMARK_ALIGN_DAYS)
                                or bars[0].date >= start):
        return None
    if last.date != end and (last.date < _shift(end, -BENCHMARK_ALIGN_DAYS)
                             or bars[-1].date <= end):
        return None
    return last.close / first.open - 1


def apply_outcome(e: LedgerEntry, out: Outcome, bars: list[Bar],
                  market_bars: list[Bar] | None, domain_bars: list[Bar] | None,
                  today: str | None = None) -> None:
    after = bars_after_creation(e, bars)
    e.status = out.status
    e.settle_note = out.note
    if out.fill is not None:
        e.entry_date = after[out.fill.index].date
        e.entry_price = round(out.fill.price if out.entry_price is None else out.entry_price, 6)
    if out.status == "void":
        e.exit_reason = out.exit_reason
        e.settled_at = _now()
        return
    if out.status != "settled":
        return
    e.exit_date = after[out.exit_index].date
    e.exit_price = round(out.exit_price, 6)
    e.exit_reason = out.exit_reason
    if not e.entry_price or e.entry_price <= 0:
        e.status, e.settle_note = "open", "invalid entry price in source data (not settled)"
        return
    sign = 1.0 if e.direction == "long" else -1.0
    e.gross_return = round(sign * (e.exit_price / e.entry_price - 1), 6)
    e.cost_return = round(2 * cost_bps(e.asset_type, e.ticker) / 10_000, 6)
    e.net_return = round(e.gross_return - e.cost_return, 6)
    e.pnl_usd = round(e.position_usd * e.net_return, 2)
    apply_benchmarks(e, market_bars, domain_bars, today)
    outcome = 1.0 if e.net_return > 0 else 0.0
    e.brier = round((e.confidence - outcome) ** 2, 6)
    e.falsifier_triggered = e.exit_reason in ("stop", "falsifier")
    e.settled_at = _now()


# Bump when compute_review gains or changes fields: older reviews are then recomputed.
REVIEW_VERSION = 1


def compute_review(e: LedgerEntry, bars: list[Bar], factor: float = 1.0) -> dict | None:
    """Post-mortem facts of a settled record, from bars alone (docs/S9_DESIGN.md §3).

    `factor` (adjustment_factor for the current series) rescales the recorded levels
    like simulate() does; the entry price was taken from the series at settlement
    (settle_factor), so it is moved by factor / settle_factor into the current series.
    The fill bar's whole high/low range counts (an approximation for a zone fill
    inside that bar)."""
    from marketmind.pipeline.l3_indicators import atr
    if not (e.entry_date and e.exit_date and e.entry_price):
        return None
    dates = [b.date for b in bars]
    if e.entry_date not in dates or e.exit_date not in dates:
        return None
    i0, i1 = dates.index(e.entry_date), dates.index(e.exit_date)
    window, before = bars[i0:i1 + 1], bars[:i0]
    long = e.direction == "long"
    sign = 1.0 if long else -1.0
    p = e.entry_price * factor / settle_factor(e)
    hi, lo = max(b.high for b in window), min(b.low for b in window)
    best, worst = (hi, lo) if long else (lo, hi)
    stop = e.stop_loss * factor if e.stop_loss is not None else None
    target = e.target_price * factor if e.target_price is not None else None

    def ret(price: float) -> float:
        return round(sign * (price / p - 1), 6)

    def reaches(b: Bar, level: float | None, favourable: bool) -> bool:
        if level is None:
            return False
        return (b.high >= level) if long == favourable else (b.low <= level)

    mfe, mae = max(ret(best), 0.0), min(ret(worst), 0.0)
    stop_distance = None if stop is None else ret(stop)
    # ATR as a fraction of the last close before entry: comparable across assets
    atr_pct = (round(atr(before[-15:]) / before[-1].close, 6)
               if len(before) >= 15 and before[-1].close > 0 else None)

    # After an early exit: did the original plan work out by its own expiry?
    expiry = i0 + e.hold_bars - 1
    after_exit = bars[i1 + 1:expiry + 1]
    post_exit_complete = expiry <= i1 or len(bars) > expiry
    target_after_exit = any(reaches(b, target, True) for b in after_exit) if target else None

    gross, net, excess = e.gross_return or 0.0, e.net_return, e.excess_market
    if net is not None and net > 0:
        error_class = "win" if excess is None or excess > 0 else "beta_carried"
    elif gross > 0:
        error_class = "cost_flipped"
    elif e.exit_reason in ("stop", "falsifier") and target_after_exit:
        error_class = "right_but_stopped"
    else:
        error_class = "thesis_wrong"

    closes = [b.close for b in before]
    return {
        "v": REVIEW_VERSION,
        "direction_correct": gross > 0,
        "error_class": error_class,
        "mfe": mfe,
        "mae": mae,
        "bars_held": len(window),
        "touched_target": None if target is None else any(reaches(b, target, True) for b in window),
        "touched_stop": None if stop is None else any(reaches(b, stop, False) for b in window),
        "ambiguous_bar": (stop is not None and target is not None
                          and any(reaches(b, target, True) and reaches(b, stop, False)
                                  for b in window)),
        "target_distance": None if target is None else ret(target),
        "stop_distance": stop_distance,
        "r_multiple": (round(gross / -stop_distance, 4)
                       if stop_distance is not None and stop_distance < 0 else None),
        "atr_pct": atr_pct,
        "mfe_atr": round(mfe / atr_pct, 4) if atr_pct else None,
        "mae_atr": round(mae / atr_pct, 4) if atr_pct else None,
        "target_hit_after_exit": target_after_exit,
        "post_exit_complete": post_exit_complete,
        "regime": {
            "ret_20d": (round(closes[-1] / closes[-21] - 1, 6)
                        if len(closes) >= 21 and closes[-21] > 0 else None),
            "above_ma50": (closes[-1] > sum(closes[-50:]) / 50) if len(closes) >= 50 else None,
            "above_ma200": (closes[-1] > sum(closes[-200:]) / 200) if len(closes) >= 200 else None,
        },
        "beat_market": None if excess is None else excess > 0,
    }


def apply_benchmarks(e: LedgerEntry, market_bars: list[Bar] | None,
                     domain_bars: list[Bar] | None, today: str | None = None) -> None:
    """Fill benchmark returns of a settled record; note whichever is still missing.

    The benchmark leg takes the record's direction (a short is compared with
    shorting the benchmark). Only the benchmark segment of settle_note changes."""
    sign = 1.0 if e.direction == "long" else -1.0
    e.market_benchmark = market_benchmark(e)
    mret = (0.0 if e.market_benchmark == CASH
            else benchmark_return(market_bars, e.entry_date, e.exit_date))
    e.market_return = None if mret is None else round(mret, 6)
    e.excess_market = None if mret is None else round(e.net_return - sign * mret, 6)
    if e.domain_benchmark:
        dret = benchmark_return(domain_bars, e.entry_date, e.exit_date)
        e.domain_return = None if dret is None else round(dret, 6)
        e.excess_domain = None if dret is None else round(e.net_return - sign * dret, 6)
    missing = []                     # (ticker, its bars) of each benchmark still missing
    if mret is None:
        missing.append((e.market_benchmark, market_bars))
    if e.domain_benchmark and e.domain_return is None:
        missing.append((e.domain_benchmark, domain_bars))
    today = today or datetime.now(timezone.utc).date().isoformat()
    give_up = today >= _shift(e.exit_date, BENCHMARK_GIVE_UP_DAYS)
    # final only when the series was there but has no bar near the dates; a failed
    # fetch is retried whatever the age
    final = list(dict.fromkeys(t for t, b in missing if give_up and b))
    retry = list(dict.fromkeys(t for t, _ in missing if t not in final))
    notes = [n for n in (e.settle_note or "").split("; ")
             if n and not n.startswith((BENCH_MISSING, BENCH_NOT_COMPARABLE))]
    if final:
        notes.insert(0, f"{BENCH_NOT_COMPARABLE}: " + ", ".join(final))
    if retry:
        notes.insert(0, f"{BENCH_MISSING}: " + ", ".join(retry))
    e.settle_note = "; ".join(notes)


def _not_comparable(e: LedgerEntry) -> set[str]:
    for part in (e.settle_note or "").split("; "):
        if part.startswith(BENCH_NOT_COMPARABLE + ": "):
            return set(part[len(BENCH_NOT_COMPARABLE) + 2:].split(", "))
    return set()


def needs_benchmark(e: LedgerEntry) -> bool:
    """Settled with a benchmark still to retry (not one marked not comparable)."""
    if e.status != "settled":
        return False
    final = _not_comparable(e)
    return ((e.market_return is None and market_benchmark(e) not in final)
            or (bool(e.domain_benchmark) and e.domain_return is None
                and e.domain_benchmark not in final))


# Below this, a snapshot / series difference is rounding, not a corporate action.
ADJUSTMENT_NOOP = 5e-4


def price_adjustment(e: LedgerEntry, bars: list[Bar], snapshot: dict[str, dict],
                     series_source: str | None = None) -> tuple[float, str]:
    """(close(snapshot date) in the current series / snapshot price, settle_note text).

    1.0 if not comparable. With `series_source`, only a snapshot taken from that same
    source is compared: two providers differ by a few bp without any corporate action."""
    snap = snapshot.get(e.ticker) or {}
    price, day = snap.get("price"), snap.get("price_date")
    if not price or price <= 0 or not day:
        return 1.0, ""
    bar = next((b for b in bars if b.date == day), None)
    if bar is None or bar.close <= 0:
        return 1.0, ""
    factor = bar.close / price
    if abs(factor - 1.0) < ADJUSTMENT_NOOP:
        return 1.0, ""
    snap_source = snap.get("source")
    if series_source is not None and snap_source != series_source:
        if not 0.9 <= factor <= 1.1:
            logger.warning("Ledger: %s snapshot (%s) and series (%s) differ x%.4f; not rescaled",
                           e.ticker, snap_source, series_source, factor)
        return 1.0, (f"snapshot source {snap_source or 'unknown'}, "
                     f"settlement source {series_source} (not rescaled)")
    if not 0.01 <= factor <= 100:
        logger.warning("Ledger: implausible adjustment factor %.4f for %s, ignored",
                       factor, e.ticker)
        return 1.0, ""
    return factor, f"price levels rescaled x{factor:.4f} (adjusted series changed)"


def adjustment_factor(e: LedgerEntry, bars: list[Bar], snapshot: dict[str, dict],
                      series_source: str | None = None) -> float:
    """close(snapshot date) in the current series / snapshot price; 1.0 if not comparable."""
    return price_adjustment(e, bars, snapshot, series_source)[0]


_RESCALED = re.compile(r"price levels rescaled x([0-9.]+)")


def settle_factor(e: LedgerEntry) -> float:
    """Adjustment factor in force when the record was settled (its entry/exit prices
    are in that series): meta.price_factor, else the settle_note of older records."""
    value = (e.meta or {}).get("price_factor")
    if value is None and (m := _RESCALED.search(e.settle_note or "")):
        value = m.group(1)
    try:
        factor = float(value) if value is not None else 1.0
    except (TypeError, ValueError):
        return 1.0
    return 1.0 if factor <= 0 or abs(factor - 1.0) < ADJUSTMENT_NOOP else factor


def rescaled(e: LedgerEntry, factor: float) -> LedgerEntry:
    """Copy of `e` with every price level multiplied by `factor` (simulation only)."""
    if factor == 1.0:
        return e

    def scale(v: float | None) -> float | None:
        return None if v is None else v * factor

    rule = dict(e.falsifier_rule) if e.falsifier_rule else None
    if rule and rule.get("price") is not None:
        rule["price"] = float(rule["price"]) * factor
    return replace(e, entry_low=scale(e.entry_low), entry_high=scale(e.entry_high),
                   stop_loss=scale(e.stop_loss), target_price=scale(e.target_price),
                   falsifier_rule=rule)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SettleReport:
    checked: int = 0
    settled: int = 0
    voided: int = 0
    still_open: int = 0
    pending: int = 0
    benchmarks_backfilled: int = 0
    reviews_backfilled: int = 0
    changed_meanwhile: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        text = (f"ledger: checked {self.checked}, settled {self.settled}, void {self.voided}, "
                f"open {self.still_open}, pending {self.pending}")
        if self.benchmarks_backfilled:
            text += f", benchmarks backfilled {self.benchmarks_backfilled}"
        if self.reviews_backfilled:
            text += f", reviews backfilled {self.reviews_backfilled}"
        if self.changed_meanwhile:
            text += f", changed by another process (not overwritten): {len(self.changed_meanwhile)}"
        if self.unavailable:
            text += f", no price data: {', '.join(sorted(set(self.unavailable)))}"
        if self.errors:
            text += f", errors: {len(self.errors)} (see settle_note)"
        return text


async def settle_all(store: LedgerStore, source: PriceSource,
                     today: str | None = None) -> SettleReport:
    """Recompute every unsettled record; idempotent, safe to run on every pipeline start.

    `today` (YYYY-MM-DD, default: current UTC date) bounds the bars used.
    """
    report = SettleReport()
    cache: dict[str, list[Bar] | None] = {}
    fixed_today = today
    day = today or datetime.now(timezone.utc).date().isoformat()

    def write(e: LedgerEntry, expected: tuple[str, ...]) -> bool:
        # conditional: a record another process changed meanwhile (e.g. voided) wins
        if store.update_if_status(e, expected):
            return True
        logger.warning("Ledger: %s (%s) changed while settling; not overwritten",
                       e.entry_id, e.ticker)
        report.changed_meanwhile.append(e.entry_id)
        return False

    async def bars_for(ticker: str) -> list[Bar] | None:
        if ticker not in cache:
            bars = await source.daily_bars(ticker)
            if bars and fixed_today:        # replay / tests: a fixed cut-off date
                bars = [b for b in bars if b.date < fixed_today]
            elif bars:                      # live: each market's own session close
                bars = complete_bars(ticker, bars)
            cache[ticker] = bars
        return cache[ticker]

    for e in store.unsettled():
        report.checked += 1
        try:
            bars = await bars_for(e.ticker)
            if not bars:
                e.settle_note = "price data unavailable (not estimated)"
                report.unavailable.append(e.ticker)
                write(e, UNSETTLED)
                continue
            snapshot = store.snapshot(e.snapshot_id) if e.snapshot_id else {}
            factor, adj_note = price_adjustment(e, bars, snapshot, source_of(source, e.ticker))
            snap_px = (snapshot.get(e.ticker.upper()) or snapshot.get(e.ticker) or {}).get("price")
            out = simulate(rescaled(e, factor), bars,
                           decision_price=snap_px * factor if snap_px else None)
            market_bars = domain_bars = None
            if out.status == "settled":
                mb = market_benchmark(e)
                market_bars = None if mb == CASH else await bars_for(mb)
                if e.domain_benchmark:
                    domain_bars = await bars_for(e.domain_benchmark)
            apply_outcome(e, out, bars, market_bars, domain_bars, day)
            if e.status == "settled":
                meta = {k: v for k, v in (e.meta or {}).items() if k != "price_factor"}
                if factor != 1.0:          # entry/exit prices are in this series
                    meta["price_factor"] = round(factor, 6)
                e.meta = meta
                e.review = compute_review(e, bars, factor)
            if adj_note:
                e.settle_note = f"{e.settle_note}; {adj_note}" if e.settle_note else adj_note
            e.price_source = source_of(source, e.ticker)
            if not write(e, UNSETTLED):
                continue
        except Exception as exc:
            # One malformed record must not block settlement of all the others.
            logger.error("Ledger: settling %s (%s) failed", e.entry_id, e.ticker, exc_info=True)
            report.errors.append(e.entry_id)
            fresh = store.get(e.entry_id)
            if fresh is not None:
                fresh.settle_note = f"settlement error: {type(exc).__name__}: {exc}"[:500]
                store.update_if_status(fresh, UNSETTLED)
            continue
        if e.status == "settled":
            report.settled += 1
        elif e.status == "void":
            report.voided += 1
        elif e.status == "open":
            report.still_open += 1
        else:
            report.pending += 1

    # Settled records whose benchmark data was missing: retry the benchmark only.
    for e in store.list(status="settled"):
        if not needs_benchmark(e):
            continue
        try:
            before = (e.market_return, e.domain_return)
            mb = market_benchmark(e)
            market_bars = None if mb == CASH else await bars_for(mb)
            domain_bars = await bars_for(e.domain_benchmark) if e.domain_benchmark else None
            note_before = e.settle_note
            apply_benchmarks(e, market_bars, domain_bars, day)
            if (e.market_return, e.domain_return) != before:
                if e.review is not None:     # recompute: beat_market / error_class use it
                    e.review = None
                if write(e, ("settled",)):
                    report.benchmarks_backfilled += 1
            elif e.settle_note != note_before:          # e.g. now "not comparable"
                write(e, ("settled",))
        except Exception:
            logger.error("Ledger: benchmark backfill for %s failed", e.entry_id, exc_info=True)

    # Settled records without current post-mortem facts (settled before they existed,
    # or computed by an older REVIEW_VERSION): (re)compute them.
    for e in store.list(status="settled"):
        if (e.review is not None and e.review.get("v") == REVIEW_VERSION
                and e.review.get("post_exit_complete", True)):
            continue
        try:
            bars = await bars_for(e.ticker)
            if not bars:
                continue
            snapshot = store.snapshot(e.snapshot_id) if e.snapshot_id else {}
            factor = adjustment_factor(e, bars, snapshot, source_of(source, e.ticker))
            review = compute_review(e, bars, factor)
            if review is not None and review != e.review:
                e.review = review
                if write(e, ("settled",)):
                    report.reviews_backfilled += 1
        except Exception:
            logger.error("Ledger: review backfill for %s failed", e.entry_id, exc_info=True)

    logger.info(report.summary())
    return report
