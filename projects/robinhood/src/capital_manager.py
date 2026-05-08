"""
capital_manager.py - Layer 3 Capital Management Module (Task 3.2)

Reads account state via account_reader and computes position-level
capital allocation suggestions. Enforces Physical Isolation Discipline:
no write-back to any brokerage API.

Key algorithms:
  1. Single-entry position sizing: risk per signal = min(25% of cash, buying_power * 0.25)
  2. Existing position check: if ticker already held, suggest add/reduce/hold
  3. Max position cap: no single position shall exceed 30% of total portfolio value
  4. Partial exit suggestion: if position has unrealized PnL > 15% of portfolio,
     suggest taking partial profit.
"""

from __future__ import annotations

from typing import Any

from src.account_reader import AccountState, read_account_state

# ---------------------------------------------------------------------------
# Constants (PM-approved defaults)
# ---------------------------------------------------------------------------

SIGNAL_MAX_PORTION: float = 0.25       # Max 25% of cash per signal
MAX_SINGLE_POSITION_RATIO: float = 0.30  # Max 30% of portfolio in one position
PARTIAL_EXIT_THRESHOLD: float = 0.15    # Take partial profit at 15% portfolio gain
NUKE_EXIT_THRESHOLD: float = -0.25      # Aggressive exit at 25% portfolio loss
PARTIAL_EXIT_FRACTION: float = 0.50     # Sell 50% of position on partial exit
RESERVE_RATIO: float = 0.10             # Always keep 10% cash reserve


def compute_position_sizing(
    ticker: str,
    signal: str,
    account: AccountState,
    current_price: float | None = None,
) -> dict[str, Any]:
    """Compute capital allocation for a single ticker based on the signal.

    Args:
        ticker: Uppercase ticker symbol.
        signal: One of "STRONG_BUY", "BUY", "SELL", "HOLD", "WAIT".
        account: AccountState object from account_reader.
        current_price: Current market price for the ticker.
            If None, uses avg_cost from existing position or raises ValueError.

    Returns:
        Dict with:
        {
            "ticker": <str>,
            "action": <"BUY" | "SELL" | "HOLD" | "AVOID">,
            "max_shares": <int>,
            "max_notional": <float>,
            "cash_reserve_kept": <float>,
            "reasoning": <str>,
            "position_adjustment": <dict | None>,
            "exit_suggestion": <dict | None>
        }
    """
    # Resolve current price
    position = _find_position(ticker, account)
    price = current_price

    if price is None:
        if position is not None:
            price = position.current_price
        else:
            raise ValueError(
                f"Cannot price ticker {ticker}: no current_price provided "
                f"and no existing position found."
            )

    # Compute available cash respecting reserve
    available_cash = account.cash * (1.0 - RESERVE_RATIO)
    buying_power = account.buying_power * (1.0 - RESERVE_RATIO)

    # Portfolio total value
    portfolio_value = account.cash + _compute_positions_value(account.positions)

    # Max position limit check
    max_position_notional = portfolio_value * MAX_SINGLE_POSITION_RATIO
    existing_position_notional = (
        position.shares * price if position is not None else 0.0
    )
    remaining_position_capacity = max(0.0, max_position_notional - existing_position_notional)

    # Determine action and sizing
    signal_upper = signal.upper()
    if signal_upper in ("STRONG_BUY", "BUY"):
        # Compute max cash to deploy: min(25% cash, 25% buying_power, remaining capacity)
        max_notional = min(
            available_cash * SIGNAL_MAX_PORTION,
            buying_power * SIGNAL_MAX_PORTION,
            remaining_position_capacity,
        )
        if max_notional < price:
            action = "AVOID"
            max_notional = 0.0
            max_shares = 0
        else:
            action = "BUY"
            max_shares = int(max_notional // price)

        exit_suggestion = None
        position_adjustment = None

    elif signal_upper == "SELL":
        action = "SELL"
        max_notional = 0.0
        max_shares = 0
        exit_suggestion = None
        # If held, suggest full liquidation
        if position is not None:
            exit_suggestion = {
                "type": "FULL_EXIT",
                "shares_to_sell": position.shares,
                "estimated_notional": round(position.shares * price, 2),
                "reason": "SELL signal triggered on this position.",
            }
        position_adjustment = None

    elif signal_upper == "WAIT":
        action = "AVOID"
        max_notional = 0.0
        max_shares = 0
        exit_suggestion = None
        position_adjustment = None

    else:  # HOLD
        action = "HOLD"
        max_notional = 0.0
        max_shares = 0
        exit_suggestion = None
        position_adjustment = None

    # Check partial exit / nuke exit for existing positions
    if position is not None:
        unrealized_pnl = (price - position.avg_cost) * position.shares
        pnl_ratio = unrealized_pnl / portfolio_value if portfolio_value > 0 else 0.0

        if pnl_ratio >= PARTIAL_EXIT_THRESHOLD and signal_upper not in ("SELL",):
            shares_to_sell = int(position.shares * PARTIAL_EXIT_FRACTION)
            if shares_to_sell > 0:
                exit_suggestion = {
                    "type": "PARTIAL_EXIT",
                    "shares_to_sell": shares_to_sell,
                    "estimated_notional": round(shares_to_sell * price, 2),
                    "reason": (
                        f"Unrealized PnL ({pnl_ratio*100:.1f}% of portfolio) "
                        f"exceeds {PARTIAL_EXIT_THRESHOLD*100:.0f}% threshold. "
                        f"Take {PARTIAL_EXIT_FRACTION*100:.0f}% profit."
                    ),
                }
        elif pnl_ratio <= NUKE_EXIT_THRESHOLD and signal_upper not in ("SELL",):
            # Nuke exit: heavy loss
            shares_to_sell = int(position.shares * 0.75)
            if shares_to_sell > 0:
                exit_suggestion = {
                    "type": "NUKE_EXIT",
                    "shares_to_sell": shares_to_sell,
                    "estimated_notional": round(shares_to_sell * price, 2),
                    "reason": (
                        f"Unrealized loss ({pnl_ratio*100:.1f}% of portfolio) "
                        f"exceeds nuke threshold ({NUKE_EXIT_THRESHOLD*100:.0f}%). "
                        f"Aggressive 75% position reduction suggested."
                    ),
                }

        # Position adjustment suggestion
        if signal_upper == "STRONG_BUY" and action == "BUY":
            position_adjustment = {
                "type": "ADD_TO_POSITION",
                "suggested_shares": max_shares,
                "suggested_notional": round(max_shares * price, 2),
                "reason": "STRONG_BUY signal allows position averaging up.",
            }
        elif signal_upper == "SELL":
            if position is not None and position.shares > 0:
                position_adjustment = {
                    "type": "FULL_LIQUIDATE",
                    "reason": "SELL signal: full liquidation recommended.",
                }
        elif signal_upper == "HOLD":
            if position is not None:
                position_adjustment = {
                    "type": "MAINTAIN",
                    "reason": "HOLD signal: maintain current position.",
                }

    # Build reasoning
    parts = [
        f"Signal: {signal_upper}",
        f"Cash available (post-reserve): ${available_cash:.2f}",
        f"Max position capacity remaining: ${remaining_position_capacity:.2f}",
    ]
    if action == "BUY":
        parts.append(
            f"Action: BUY up to {max_shares} shares @ ${price:.2f} "
            f"(notional: ${max_shares * price:.2f})"
        )
    else:
        parts.append(f"Action: {action}")

    if exit_suggestion:
        parts.append(
            f"Exit suggestion: {exit_suggestion['type']} "
            f"({exit_suggestion['shares_to_sell']} shares)"
        )

    cash_reserve_kept = account.cash * RESERVE_RATIO

    return {
        "ticker": ticker,
        "action": action,
        "max_shares": max_shares,
        "max_notional": round(max_shares * price if action == "BUY" else 0.0, 2),
        "cash_reserve_kept": round(cash_reserve_kept, 2),
        "reasoning": " | ".join(parts),
        "position_adjustment": position_adjustment,
        "exit_suggestion": exit_suggestion,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_position(
    ticker: str, account: AccountState
) -> Any | None:
    """Find a position by ticker in the account.

    Args:
        ticker: Uppercase ticker symbol.
        account: AccountState object.

    Returns:
        Position object or None.
    """
    for pos in account.positions:
        if pos.ticker.upper() == ticker.upper():
            return pos
    return None


def _compute_positions_value(positions: list[Any]) -> float:
    """Compute total market value of all positions.

    Args:
        positions: List of Position objects.

    Returns:
        Total float value.
    """
    total = 0.0
    for pos in positions:
        total += pos.shares * pos.current_price
    return total


def compute_full_portfolio(
    account: AccountState,
    resonance_result: dict[str, Any],
) -> dict[str, Any]:
    """Compute capital suggestions for the full portfolio based on resonance.

    For each ticker in the current positions, evaluates whether the resonance
    signal suggests action. Also computes overall cash allocation.

    Args:
        account: AccountState object.
        resonance_result: Output from resonance_aggregator.compute_resonance().

    Returns:
        Dict with 'position_actions' (list of per-ticker results),
        'cash_summary', and 'overall_strategy'.
    """
    signal = resonance_result.get("signal", "WAIT")

    # Evaluate each existing position
    position_actions: list[dict[str, Any]] = []
    for pos in account.positions:
        sizing = compute_position_sizing(
            ticker=pos.ticker,
            signal=signal,
            account=account,
            current_price=pos.current_price,
        )
        position_actions.append(sizing)

    # Cash allocation summary
    reserved_cash = account.cash * RESERVE_RATIO
    deployable_cash = account.cash * (1.0 - RESERVE_RATIO)

    if signal in ("STRONG_BUY", "BUY"):
        deploy = deployable_cash * SIGNAL_MAX_PORTION
        cash_strategy = (
            f"Bullish signal ({signal}): deploy up to "
            f"${deploy:.2f} ({SIGNAL_MAX_PORTION*100:.0f}% of deployable cash)"
        )
    elif signal == "SELL":
        cash_strategy = (
            f"Bearish signal ({signal}): increase cash reserve to "
            f"${account.cash * 0.5:.2f} (50% of total cash)"
        )
    else:
        cash_strategy = (
            f"Neutral signal ({signal}): maintain current cash position "
            f"(${account.cash:.2f}) with ${reserved_cash:.2f} reserve"
        )

    return {
        "position_actions": position_actions,
        "cash_summary": {
            "total_cash": account.cash,
            "reserved_cash": reserved_cash,
            "deployable_cash": deployable_cash,
        },
        "overall_strategy": cash_strategy,
    }