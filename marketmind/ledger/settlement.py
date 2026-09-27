"""Settle ledger records from daily bars (SPEC_v3 §7, S2 acceptance).

Rules (all code, no judgement; see docs/S2_DESIGN.md §4):
  Entry   next_open: open of the first bar dated after the record's creation date.
          zone:      first bar (within hold_bars bars after creation) that trades into
                     the zone; long fills at min(open, entry_high), short at
                     max(open, entry_low). Never filled inside the window -> void.
  Exit    checked bar by bar from the fill bar, in this order:
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
  Missing data leaves the record unsettled with a note; nothing is estimated.
  Only complete bars are used: bars dated on or after today (UTC) are dropped,
  because a data source returns the running session as a partial bar.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import PriceSource
from marketmind.ledger.store import LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.ledger.settlement")

# One-way cost in basis points. Crypto reflects Robinhood's quoted spread; the
# 50 bp figure is an estimate, not a verified number (to confirm in S6).
COST_BPS = {"crypto": 50.0}
DEFAULT_COST_BPS = 5.0


def cost_bps(asset_type: str) -> float:
    return COST_BPS.get(asset_type, DEFAULT_COST_BPS)


def market_benchmark(entry: LedgerEntry) -> str:
    return "BTC-USD" if entry.asset_type == "crypto" or entry.ticker.upper().endswith("-USD") else "SPY"


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
    for i, b in enumerate(bars[:e.hold_bars]):
        if e.direction == "long" and b.low <= e.entry_high:
            price = min(b.open, e.entry_high)
            return Fill(i, price, price == b.open)
        if e.direction == "short" and b.high >= e.entry_low:
            price = max(b.open, e.entry_low)
            return Fill(i, price, price == b.open)
    return "void" if len(bars) >= e.hold_bars else None


def simulate(e: LedgerEntry, bars: list[Bar]) -> Outcome:
    created = (e.created_at or "")[:10]
    after = [b for b in bars if b.date > created]
    fill = _find_fill(e, after)
    if fill is None:
        return Outcome("pending", "waiting for the first bar after creation"
                       if not after else "entry zone not reached yet")
    if fill == "void":
        return Outcome("void", f"entry zone not reached within {e.hold_bars} bars",
                       exit_reason="unfilled")

    long = e.direction == "long"
    last = fill.index + e.hold_bars - 1
    for j in range(fill.index, min(last, len(after) - 1) + 1):
        b = after[j]
        ref_open = fill.price if j == fill.index else b.open
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


def benchmark_return(bars: list[Bar] | None, start: str, end: str) -> float | None:
    if not bars:
        return None
    window = [b for b in bars if start <= b.date <= end]
    if not window or window[0].open <= 0:
        return None
    return window[-1].close / window[0].open - 1


def apply_outcome(e: LedgerEntry, out: Outcome, bars: list[Bar],
                  market_bars: list[Bar] | None, domain_bars: list[Bar] | None) -> None:
    created = (e.created_at or "")[:10]
    after = [b for b in bars if b.date > created]
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
    sign = 1.0 if e.direction == "long" else -1.0
    e.gross_return = round(sign * (e.exit_price / e.entry_price - 1), 6)
    e.cost_return = round(2 * cost_bps(e.asset_type) / 10_000, 6)
    e.net_return = round(e.gross_return - e.cost_return, 6)
    e.pnl_usd = round(e.position_usd * e.net_return, 2)
    e.market_benchmark = market_benchmark(e)
    mret = benchmark_return(market_bars, e.entry_date, e.exit_date)
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
    outcome = 1.0 if e.net_return > 0 else 0.0
    e.brier = round((e.confidence - outcome) ** 2, 6)
    e.falsifier_triggered = e.exit_reason in ("stop", "falsifier")
    e.settled_at = _now()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SettleReport:
    checked: int = 0
    settled: int = 0
    voided: int = 0
    still_open: int = 0
    pending: int = 0
    unavailable: list[str] = field(default_factory=list)

    def summary(self) -> str:
        text = (f"ledger: checked {self.checked}, settled {self.settled}, void {self.voided}, "
                f"open {self.still_open}, pending {self.pending}")
        if self.unavailable:
            text += f", no price data: {', '.join(sorted(set(self.unavailable)))}"
        return text


async def settle_all(store: LedgerStore, source: PriceSource,
                     today: str | None = None) -> SettleReport:
    """Recompute every unsettled record; idempotent, safe to run on every pipeline start.

    `today` (YYYY-MM-DD, default: current UTC date) bounds the bars used.
    """
    report = SettleReport()
    cache: dict[str, list[Bar] | None] = {}
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def bars_for(ticker: str) -> list[Bar] | None:
        if ticker not in cache:
            bars = await source.daily_bars(ticker)
            cache[ticker] = [b for b in bars if b.date < today] if bars else bars
        return cache[ticker]

    for e in store.unsettled():
        report.checked += 1
        bars = await bars_for(e.ticker)
        if not bars:
            e.settle_note = "price data unavailable (not estimated)"
            report.unavailable.append(e.ticker)
            store.update(e)
            continue
        out = simulate(e, bars)
        market_bars = domain_bars = None
        if out.status == "settled":
            market_bars = await bars_for(market_benchmark(e))
            if e.domain_benchmark:
                domain_bars = await bars_for(e.domain_benchmark)
        apply_outcome(e, out, bars, market_bars, domain_bars)
        e.price_source = source.name
        store.update(e)
        if e.status == "settled":
            report.settled += 1
        elif e.status == "void":
            report.voided += 1
        elif e.status == "open":
            report.still_open += 1
        else:
            report.pending += 1
    logger.info(report.summary())
    return report
