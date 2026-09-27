"""Code-enforced guard on LLM decision cards (SPEC_v3 §5 step 6, law L3).

The LLM writes the thesis, risk statement and red-team note. It does not get to
set numbers: price levels come from Layer 3, and position size and total heat
are bounded here. Every change is recorded in the notes, so the dashboard can
show what the guard did.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

MAX_SINGLE_POSITION_PCT = 25.0   # gate23-architecture.md: single-position hard cap
MAX_TOTAL_HEAT_PCT = 25.0        # design spec §6.3: all stops hit together <= 25% equity
MAX_POSITIONS = 6                # design spec §6.3: attention constraint

# Interim tradability rule until the Robinhood universe lands (SPEC_v3 S2):
# a ticker with a foreign-exchange suffix (600900.SS, 0700.HK, 7203.T ...) cannot be
# bought on Robinhood US. "-USD" crypto pairs are allowed.
_FOREIGN_SUFFIXES = (".SS", ".SZ", ".HK", ".T", ".L", ".PA", ".DE", ".TO", ".AX",
                     ".KS", ".KQ", ".TW", ".NS", ".BO", ".SW", ".AS", ".MI", ".SA")


def is_robinhood_tradable(ticker: str) -> bool:
    t = (ticker or "").strip().upper()
    if not t:
        return False
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
        card.entry_low, card.entry_high = lvl.entry_zone_low, lvl.entry_zone_high
        card.stop_loss, card.target_price = lvl.stop_loss, lvl.target_price
        card.reward_risk_ratio, card.max_hold_days = lvl.reward_risk_ratio, lvl.max_hold_days
        size = card.position_size_pct
        if not isinstance(size, (int, float)) or math.isnan(size) or size < 0:
            report.notes.append(f"{card.ticker}: invalid size {size!r} -> 0")
            size = 0.0
        if size > max_single_pct:
            report.notes.append(f"{card.ticker}: size {size:.1f}% capped to {max_single_pct:.0f}%")
            size = max_single_pct
        if size <= 0:
            report.notes.append(f"dropped {card.ticker}: position size 0 is not a recommendation")
            continue
        card.position_size_pct = round(float(size), 2)
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


def card_heat_pct(card) -> float:
    """Equity % lost if the stop is hit: size% * (entry_mid - stop) / entry_mid."""
    entry_mid = (card.entry_low + card.entry_high) / 2
    if entry_mid <= 0 or card.stop_loss <= 0 or card.stop_loss >= entry_mid:
        return 0.0
    return card.position_size_pct * (entry_mid - card.stop_loss) / entry_mid
