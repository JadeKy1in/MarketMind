"""Settle ledger records from daily bars (SPEC_v3 §7, S2 acceptance).

Rules (all code, no judgement; see docs/S2_DESIGN.md §4):
  Entry   next_open: open of the first bar dated after the record's creation date.
          zone:      first bar (within ENTRY_WINDOW_BARS bars after creation, or
                     hold_bars if shorter) that trades into
                     the zone; long fills at min(open, entry_high), short at
                     max(open, entry_low). Never filled inside the window -> void.
          A fill at the open that is already at/beyond the stop or the target
          -> void (owner decision 2026-09-29: the card was dead before entry; no
          one would buy and sell at the same open, so it is not scored).
  Exit    checked bar by bar from the fill bar, in this order:
          gap     an open already beyond the target exits there as target (the order
                  fills at that open), checked before the stop.
          stop    long: low <= stop (gap through -> the open); short mirrored.
          target  long: high >= target (gap through -> the open). On a zone fill bar
                  that did not fill at the open, the target is not credited (the
                  intrabar order is unknown). Stop and target on the same bar -> stop.
          falsifier rule  close_below / close_above -> exit at that close.
          expiry  close of the hold_bars-th bar counting the fill bar.
  Returns net = direction * (exit / entry - 1) - 2 * cost_bps / 10_000.
  Benchmarks  buy-and-hold over the same dates: open on the entry date to close on
          the exit date. Market benchmark: BTC-USD for crypto, SPY otherwise.
          Excess = net - benchmark for both directions ("did this beat simply
          holding the benchmark").
  Brier   (confidence - outcome)^2, outcome = 1 if net > 0 else 0.
  Adjusted prices  sources return split/dividend-adjusted series, so a later corporate
          action rescales past bars. Price levels (zone, stop, target, falsifier) are
          multiplied by close(snapshot date in the current series) / snapshot price
          before simulating; returns are then in the current series (total return).
  Benchmark backfill  a settled record whose benchmark data was missing is retried
          on later runs; only the benchmark fields change.
  Missing data leaves the record unsettled with a note; nothing is estimated.
  Only complete bars are used (price_history.complete_bars: each market's own
  session close; UTC days for crypto/FX), because a data source returns the
  running session as a partial bar.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from marketmind.gateway.price_history import Bar, complete_bars
from marketmind.markets import CASH, market_for
from marketmind.ledger.prices import PriceSource, source_of
from marketmind.ledger.store import LedgerEntry, LedgerStore

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


def bars_after_creation(e: LedgerEntry, bars: list[Bar]) -> list[Bar]:
    """Bars the record could first trade on.

    Crypto and FX bars are UTC days, so the first usable bar is the next UTC date.
    Exchange bars are local sessions (marketmind.markets): a record created before
    the local open can still fill at that day's open (e.g. a US record written at
    09:00 Beijing time, or a Tokyo record written the previous evening UTC).
    """
    ts = _parse_ts(e.created_at)
    if ts is None:
        return list(bars)
    m = market_for(e.ticker)
    if is_crypto(e) or m.utc_days:
        first = (ts.astimezone(timezone.utc).date() + timedelta(days=1)).isoformat()
    else:
        local = ts.astimezone(ZoneInfo(m.tz))
        before_open = local.time() < m.open
        first = (local.date() if before_open else local.date() + timedelta(days=1)).isoformat()
    return [b for b in bars if b.date >= first]


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


def simulate(e: LedgerEntry, bars: list[Bar]) -> Outcome:
    after = bars_after_creation(e, bars)
    fill = _find_fill(e, after)
    if fill is None:
        return Outcome("pending", "waiting for the first bar after creation"
                       if not after else "entry zone not reached yet")
    if fill == "void":
        return Outcome("void", f"entry zone not reached within {entry_window(e)} bars",
                       exit_reason="unfilled")

    long = e.direction == "long"
    if fill.at_open and (gap := gapped_past(e, fill.price)):
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


def benchmark_return(bars: list[Bar] | None, start: str, end: str) -> float | None:
    if not bars:
        return None
    window = [b for b in bars if start <= b.date <= end]
    # A stale or gappy series must not pass off a partial window as the real return.
    if not window or window[0].date != start or window[-1].date != end or window[0].open <= 0:
        return None
    return window[-1].close / window[0].open - 1


def apply_outcome(e: LedgerEntry, out: Outcome, bars: list[Bar],
                  market_bars: list[Bar] | None, domain_bars: list[Bar] | None) -> None:
    after = bars_after_creation(e, bars)
    e.status = out.status
    e.settle_note = out.note
    if out.fill is not None:
        e.entry_date = after[out.fill.index].date
        e.entry_price = round(out.fill.price, 6)
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
    apply_benchmarks(e, market_bars, domain_bars)
    outcome = 1.0 if e.net_return > 0 else 0.0
    e.brier = round((e.confidence - outcome) ** 2, 6)
    e.falsifier_triggered = e.exit_reason in ("stop", "falsifier")
    e.settled_at = _now()


def apply_benchmarks(e: LedgerEntry, market_bars: list[Bar] | None,
                     domain_bars: list[Bar] | None) -> None:
    """Fill benchmark returns of a settled record; note whichever is still missing."""
    e.market_benchmark = market_benchmark(e)
    mret = (0.0 if e.market_benchmark == CASH
            else benchmark_return(market_bars, e.entry_date, e.exit_date))
    e.market_return = None if mret is None else round(mret, 6)
    e.excess_market = None if mret is None else round(e.net_return - mret, 6)
    if e.domain_benchmark:
        dret = benchmark_return(domain_bars, e.entry_date, e.exit_date)
        e.domain_return = None if dret is None else round(dret, 6)
        e.excess_domain = None if dret is None else round(e.net_return - dret, 6)
    missing = [n for n, r in ((e.market_benchmark, mret),) if r is None]
    if e.domain_benchmark and e.domain_return is None:
        missing.append(e.domain_benchmark)
    if missing:
        e.settle_note = "benchmark data unavailable: " + ", ".join(missing)
    elif e.settle_note.startswith("benchmark data unavailable"):
        e.settle_note = ""


def needs_benchmark(e: LedgerEntry) -> bool:
    return e.status == "settled" and (
        e.market_return is None or (bool(e.domain_benchmark) and e.domain_return is None))


def adjustment_factor(e: LedgerEntry, bars: list[Bar], snapshot: dict[str, dict]) -> float:
    """close(snapshot date) in the current series / snapshot price; 1.0 if not comparable."""
    snap = snapshot.get(e.ticker) or {}
    price, day = snap.get("price"), snap.get("price_date")
    if not price or price <= 0 or not day:
        return 1.0
    bar = next((b for b in bars if b.date == day), None)
    if bar is None or bar.close <= 0:
        return 1.0
    factor = bar.close / price
    if abs(factor - 1.0) < 1e-4:
        return 1.0
    if not 0.01 <= factor <= 100:
        logger.warning("Ledger: implausible adjustment factor %.4f for %s, ignored",
                       factor, e.ticker)
        return 1.0
    return factor


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
    unavailable: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        text = (f"ledger: checked {self.checked}, settled {self.settled}, void {self.voided}, "
                f"open {self.still_open}, pending {self.pending}")
        if self.benchmarks_backfilled:
            text += f", benchmarks backfilled {self.benchmarks_backfilled}"
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
                store.update(e)
                continue
            snapshot = store.snapshot(e.snapshot_id) if e.snapshot_id else {}
            factor = adjustment_factor(e, bars, snapshot)
            out = simulate(rescaled(e, factor), bars)
            market_bars = domain_bars = None
            if out.status == "settled":
                mb = market_benchmark(e)
                market_bars = None if mb == CASH else await bars_for(mb)
                if e.domain_benchmark:
                    domain_bars = await bars_for(e.domain_benchmark)
            apply_outcome(e, out, bars, market_bars, domain_bars)
            if factor != 1.0:
                note = f"price levels rescaled x{factor:.4f} (adjusted series changed)"
                e.settle_note = f"{e.settle_note}; {note}" if e.settle_note else note
            e.price_source = source_of(source, e.ticker)
            store.update(e)
        except Exception as exc:
            # One malformed record must not block settlement of all the others.
            logger.error("Ledger: settling %s (%s) failed", e.entry_id, e.ticker, exc_info=True)
            report.errors.append(e.entry_id)
            fresh = store.get(e.entry_id)
            if fresh is not None:
                fresh.settle_note = f"settlement error: {type(exc).__name__}: {exc}"[:500]
                store.update(fresh)
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
            apply_benchmarks(e, market_bars, domain_bars)
            if (e.market_return, e.domain_return) != before:
                store.update(e)
                report.benchmarks_backfilled += 1
        except Exception:
            logger.error("Ledger: benchmark backfill for %s failed", e.entry_id, exc_info=True)
    logger.info(report.summary())
    return report
