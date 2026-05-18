"""Pre-trade checklist — automated validation before Gate 3 completes.

Market data staleness check (SH-4): rejects data older than 5 minutes.
All BLOCK-level failures must be resolved before the ticket is accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ChecklistItem:
    name: str
    passed: bool
    detail: str
    severity: str  # "BLOCK" | "WARN" | "INFO"


@dataclass
class PreTradeReport:
    items: list[ChecklistItem]
    all_blockers_passed: bool
    warnings: list[str]


async def run_pre_trade_checklist(
    decision_ticket: dict,
    market_data: dict,
) -> PreTradeReport:
    """Run all pre-trade validation checks.

    Args:
        decision_ticket: Dict with keys direction, instrument, position_size_pct,
            entry_level, stop_loss, take_profit, risk_budget_consumed_bps.
        market_data: Dict with keys current_price, atr_20, support_levels,
            resistance_levels, timestamp, and optionally existing_positions,
            kill_criteria_have_hooks.

    Returns:
        PreTradeReport with items list, all_blockers_passed flag, and warnings.
    """
    items: list[ChecklistItem] = []
    warnings: list[str] = []

    # ── Unpack market data with defaults ───────────────────────────────────
    current_price = market_data.get("current_price")
    atr_20 = market_data.get("atr_20")
    support_levels = market_data.get("support_levels", [])
    resistance_levels = market_data.get("resistance_levels", [])
    data_timestamp = market_data.get("timestamp")
    existing_positions = market_data.get("existing_positions", [])
    kill_criteria_have_hooks = market_data.get("kill_criteria_have_hooks", True)
    portfolio_pct_limit = market_data.get("portfolio_pct_limit", 0.25)

    # ── Unpack ticket fields ───────────────────────────────────────────────
    instrument = decision_ticket.get("instrument", "")
    direction = decision_ticket.get("direction", "")
    position_size_pct = decision_ticket.get("position_size_pct", 0.0)
    entry_level = decision_ticket.get("entry_level")
    stop_loss = decision_ticket.get("stop_loss")
    risk_budget_consumed_bps = decision_ticket.get("risk_budget_consumed_bps", 0.0)

    # ── SH-4: Market data staleness check ──────────────────────────────────
    if data_timestamp and current_price is not None:
        try:
            ts = datetime.fromisoformat(data_timestamp.replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
            stale = age_seconds > 300
        except (ValueError, TypeError):
            stale = True
            age_seconds = -1
    else:
        stale = True
        age_seconds = -1

    if stale:
        items.append(ChecklistItem(
            name="MARKET_DATA_FRESH",
            passed=False,
            detail=(
                f"Market data is stale ({age_seconds:.0f}s old, max 300s). "
                "Cannot validate price-dependent checks."
            ),
            severity="BLOCK",
        ))
        # With stale data, price-dependent checks cannot run reliably
        items.append(ChecklistItem(
            name="STOP_NOT_TOO_TIGHT",
            passed=False,
            detail="Skipped: market data is stale.",
            severity="BLOCK",
        ))
        items.append(ChecklistItem(
            name="STOP_NOT_TOO_LOOSE",
            passed=False,
            detail="Skipped: market data is stale.",
            severity="BLOCK",
        ))
        items.append(ChecklistItem(
            name="STOP_AT_MEANINGFUL_LEVEL",
            passed=False,
            detail="Skipped: market data is stale.",
            severity="WARN",
        ))
    else:
        items.append(ChecklistItem(
            name="MARKET_DATA_FRESH",
            passed=True,
            detail=f"Market data is fresh ({age_seconds:.0f}s old).",
            severity="BLOCK",
        ))
        # ── CHECK 1: STOP_NOT_TOO_TIGHT ────────────────────────────────────
        # Stop distance > ATR(20) * 2 from current price
        if stop_loss is not None and current_price is not None and atr_20 is not None and atr_20 > 0:
            stop_distance = abs(current_price - stop_loss)
            min_distance = atr_20 * 2.0
            too_tight = stop_distance < min_distance
            items.append(ChecklistItem(
                name="STOP_NOT_TOO_TIGHT",
                passed=not too_tight,
                detail=(
                    f"Stop distance ({stop_distance:.2f}) "
                    f"{'<' if too_tight else '>'} ATRx2 ({min_distance:.2f}). "
                    + (f"Stop is too close to current price. Min distance: {min_distance:.2f}."
                       if too_tight else "Stop distance is sufficient.")
                ),
                severity="BLOCK",
            ))
        else:
            items.append(ChecklistItem(
                name="STOP_NOT_TOO_TIGHT",
                passed=False,
                detail="Cannot validate: missing stop_loss, current_price, or atr_20.",
                severity="WARN",
            ))

        # ── CHECK 2: STOP_NOT_TOO_LOOSE ────────────────────────────────────
        # (entry - stop) * position_size_pct * portfolio_value <= risk_budget
        # risk_budget_consumed_bps is in basis points of portfolio
        if (entry_level is not None and stop_loss is not None
                and position_size_pct > 0 and risk_budget_consumed_bps > 0):
            entry_stop_pct = abs(entry_level - stop_loss) / entry_level
            max_loss_bps = entry_stop_pct * position_size_pct * 10000.0
            too_loose = max_loss_bps > risk_budget_consumed_bps
            items.append(ChecklistItem(
                name="STOP_NOT_TOO_LOOSE",
                passed=not too_loose,
                detail=(
                    f"Max loss ({max_loss_bps:.0f} bps) "
                    f"{'>' if too_loose else '<='} risk budget ({risk_budget_consumed_bps:.0f} bps). "
                    + (f"Stop is too far — max loss exceeds risk budget."
                       if too_loose else "Max loss within risk budget.")
                ),
                severity="BLOCK",
            ))
        else:
            items.append(ChecklistItem(
                name="STOP_NOT_TOO_LOOSE",
                passed=False,
                detail="Cannot validate: missing entry_level, stop_loss, or risk budget.",
                severity="WARN",
            ))

        # ── CHECK 3: STOP_AT_MEANINGFUL_LEVEL ──────────────────────────────
        # Stop is near a recent support/resistance level (within ATR * 0.5)
        if stop_loss is not None and atr_20 is not None and atr_20 > 0:
            all_levels = list(support_levels) + list(resistance_levels)
            if all_levels:
                proximity = atr_20 * 0.5
                near_level = any(
                    abs(stop_loss - lvl) <= proximity for lvl in all_levels
                )
                items.append(ChecklistItem(
                    name="STOP_AT_MEANINGFUL_LEVEL",
                    passed=near_level,
                    detail=(
                        f"Stop ({stop_loss}) is {'near' if near_level else 'not near'} "
                        f"a known S/R level (tolerance: {proximity:.2f})."
                    ),
                    severity="WARN",
                ))
            else:
                items.append(ChecklistItem(
                    name="STOP_AT_MEANINGFUL_LEVEL",
                    passed=True,
                    detail="No S/R levels provided — check skipped.",
                    severity="INFO",
                ))
        else:
            items.append(ChecklistItem(
                name="STOP_AT_MEANINGFUL_LEVEL",
                passed=True,
                detail="Cannot validate without ATR data — check skipped.",
                severity="INFO",
            ))

    # ── CHECK 4: POSITION_WITHIN_LIMIT ─────────────────────────────────────
    if position_size_pct > portfolio_pct_limit:
        items.append(ChecklistItem(
            name="POSITION_WITHIN_LIMIT",
            passed=False,
            detail=(
                f"Position size ({position_size_pct:.1%}) exceeds hard cap "
                f"({portfolio_pct_limit:.1%})."
            ),
            severity="BLOCK",
        ))
    else:
        items.append(ChecklistItem(
            name="POSITION_WITHIN_LIMIT",
            passed=True,
            detail=(
                f"Position size ({position_size_pct:.1%}) within limit "
                f"({portfolio_pct_limit:.1%})."
            ),
            severity="BLOCK",
        ))

    # ── CHECK 5: NO_CONFLICTING_POSITIONS ──────────────────────────────────
    conflict_found = False
    conflict_detail = ""
    for pos in existing_positions:
        if (pos.get("instrument", "").upper() == instrument.upper()
                and pos.get("direction", "") != direction
                and pos.get("direction", "")):
            conflict_found = True
            conflict_detail = (
                f"Existing {pos.get('direction')} position on {instrument} "
                f"({pos.get('size_pct', 0):.1%}) conflicts with new {direction}."
            )
            break

    items.append(ChecklistItem(
        name="NO_CONFLICTING_POSITIONS",
        passed=not conflict_found,
        detail=conflict_detail or f"No conflicting positions on {instrument}.",
        severity="BLOCK",
    ))

    # ── CHECK 6: KILL_CRITERIA_MONITORED ───────────────────────────────────
    if kill_criteria_have_hooks:
        items.append(ChecklistItem(
            name="KILL_CRITERIA_MONITORED",
            passed=True,
            detail="All kill criteria have monitoring hooks.",
            severity="WARN",
        ))
    else:
        msg = "Some kill criteria lack monitoring hooks — auto-kill may not trigger."
        items.append(ChecklistItem(
            name="KILL_CRITERIA_MONITORED",
            passed=False,
            detail=msg,
            severity="WARN",
        ))
        warnings.append(msg)

    # ── Aggregate results ──────────────────────────────────────────────────
    all_blockers_passed = all(
        item.passed for item in items if item.severity == "BLOCK"
    )

    return PreTradeReport(
        items=items,
        all_blockers_passed=all_blockers_passed,
        warnings=warnings,
    )
