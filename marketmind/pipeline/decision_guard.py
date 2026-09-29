"""Code-enforced guard on LLM decision cards (SPEC_v3 §5 step 6, law L3).

The LLM writes the thesis, risk statement and red-team note. It does not get to
set numbers: price levels come from Layer 3, and position size is computed here
from the L3 stop distance (fixed risk per trade), then bounded by the single-position,
position-count and total-heat caps. The LLM's own size is kept only for the record. Every change is recorded in the notes, so the dashboard can
show what the guard did.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger("marketmind.pipeline.decision_guard")

MAX_SINGLE_POSITION_PCT = 25.0   # gate23-architecture.md: single-position hard cap
MAX_TOTAL_HEAT_PCT = 25.0        # design spec §6.3: all stops hit together <= 25% equity
MAX_POSITIONS = 6                # design spec §6.3: attention constraint
# Owner decision 2026-09-29: size = risk budget / stop distance. 1% of the paper capital
# (ledger.recorder.PAPER_CAPITAL_USD) is lost if the L3 stop is hit. Confidence does not
# enter sizing until it is calibrated (S9).
RISK_PER_TRADE_PCT = 1.0

# Fallback when the tradable universe (marketmind.universe) cannot be loaded:
# a foreign-exchange suffix (600900.SS, 0700.HK, 7203.T ...) is never tradable on
# Robinhood US; everything else is given the benefit of the doubt.
_FOREIGN_SUFFIXES = (".SS", ".SZ", ".HK", ".T", ".L", ".PA", ".DE", ".TO", ".AX",
                     ".KS", ".KQ", ".TW", ".NS", ".BO", ".SW", ".AS", ".MI", ".SA")


# Owner decision 2026-09-27: ultra-short T-bill ETFs are cash, not trades. Holding
# them is the no-trade state, so they never take a decision-card slot.
CASH_EQUIVALENT_ETFS = frozenset({
    "SHV", "BIL", "SGOV", "USFR", "TFLO", "BILS", "GBIL", "TBIL", "XBIL", "CLTL",
})


def is_robinhood_tradable(ticker: str) -> bool:
    t = (ticker or "").strip().upper()
    if not t:
        return False
    from marketmind.universe import is_tradable
    verdict = is_tradable(t)
    if verdict is not None:
        return verdict
    logger.warning("Tradable universe unavailable; %s judged by suffix rule", t)
    if t.endswith("-USD"):
        return True
    return not t.endswith(_FOREIGN_SUFFIXES)


@dataclass
class GuardReport:
    kept: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return "; ".join(self.notes)


def enforce(cards: list, l3, max_single_pct: float = MAX_SINGLE_POSITION_PCT,
            max_heat_pct: float = MAX_TOTAL_HEAT_PCT, max_positions: int = MAX_POSITIONS) -> GuardReport:
    """Return the cards that survive, with L3 levels and bounded sizes."""
    report = GuardReport()
    green = {r.ticker: r for r in getattr(l3, "green_lights", [])}

    for card in cards:
        t = (card.ticker or "").strip().upper()
        lvl = green.get(t) or green.get(card.ticker)
        if lvl is None:
            report.notes.append(f"dropped {card.ticker}: not an L3 green light")
            continue
        if getattr(lvl, "recommendation", "enter") != "enter":
            report.notes.append(f"dropped {card.ticker}: L3 says '{lvl.recommendation}' "
                                f"(R/R {lvl.reward_risk_ratio:.2f} < 2)")
            continue
        if card.direction != "long":
            report.notes.append(f"dropped {card.ticker}: L3 only validates long setups (got {card.direction})")
            continue
        if not is_robinhood_tradable(card.ticker):
            report.notes.append(f"dropped {card.ticker}: not tradable on Robinhood US")
            continue
        if t in CASH_EQUIVALENT_ETFS:
            report.notes.append(f"dropped {card.ticker}: cash-equivalent T-bill ETF counts as no-trade")
            continue
        card.entry_low, card.entry_high = lvl.entry_zone_low, lvl.entry_zone_high
        card.stop_loss, card.target_price = lvl.stop_loss, lvl.target_price
        card.reward_risk_ratio, card.max_hold_days = lvl.reward_risk_ratio, lvl.max_hold_days
        stop_pct = stop_distance_pct(card)
        if stop_pct is None:
            report.notes.append(f"dropped {card.ticker}: L3 stop distance is not positive and "
                                f"finite (entry {card.entry_low}-{card.entry_high}, stop "
                                f"{card.stop_loss}); size cannot be computed")
            continue
        # stop > 0 bounds stop_pct below 100, so the size is always at least RISK_PER_TRADE_PCT.
        card.position_size_pct = risk_sized_pct(stop_pct, max_single_pct)
        capped = " (single-position cap)" if card.position_size_pct >= max_single_pct else ""
        report.notes.append(f"{card.ticker}: size {card.position_size_pct:.2f}% = "
                            f"{RISK_PER_TRADE_PCT:g}% risk / {stop_pct:.2f}% stop{capped}")
        report.kept.append(card)

    if len(report.kept) > max_positions:
        report.kept.sort(key=lambda c: c.reward_risk_ratio, reverse=True)
        for c in report.kept[max_positions:]:
            report.notes.append(f"dropped {c.ticker}: over the {max_positions}-position limit")
        report.kept = report.kept[:max_positions]

    heat = sum(card_heat_pct(c) for c in report.kept)
    if heat > max_heat_pct and heat > 0:
        scale = max_heat_pct / heat
        for c in report.kept:
            c.position_size_pct = round(c.position_size_pct * scale, 2)
        report.notes.append(f"total heat {heat:.1f}% > {max_heat_pct:.0f}%: sizes scaled x{scale:.2f}")
    return report


def stop_distance_pct(card) -> float | None:
    """(entry_mid - stop) / entry_mid * 100, or None when not positive and finite."""
    try:
        entry_mid = (float(card.entry_low) + float(card.entry_high)) / 2
        stop = float(card.stop_loss)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(entry_mid) and math.isfinite(stop)) or entry_mid <= 0 or stop <= 0:
        return None
    pct = (entry_mid - stop) / entry_mid * 100
    return pct if math.isfinite(pct) and pct > 0 else None


def risk_sized_pct(stop_pct: float, max_single_pct: float = MAX_SINGLE_POSITION_PCT,
                   risk_pct: float = RISK_PER_TRADE_PCT) -> float:
    """Size % of capital so that a stop-out loses `risk_pct` % of capital, capped."""
    return round(min(max_single_pct, risk_pct / stop_pct * 100), 2)


def card_heat_pct(card) -> float:
    """Equity % lost if the stop is hit: size% * (entry_mid - stop) / entry_mid."""
    entry_mid = (card.entry_low + card.entry_high) / 2
    if entry_mid <= 0 or card.stop_loss <= 0 or card.stop_loss >= entry_mid:
        return 0.0
    return card.position_size_pct * (entry_mid - card.stop_loss) / entry_mid
