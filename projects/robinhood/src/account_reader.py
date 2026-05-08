"""
account_reader.py - Read and validate local account state from JSON file.

This module provides a single function, read_account_state(), that reads
the account_state.json file from the input/ directory and validates its
structure. It enforces the Physical Isolation Discipline: the system
never connects to any brokerage API; account state comes from a manually
maintained local JSON file.
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Any


# Path constants
DEFAULT_INPUT_DIR = Path(__file__).resolve().parent.parent / "input"
DEFAULT_STATE_FILE = "account_state.json"


class AccountStateError(Exception):
    """Raised when account state file is missing, malformed, or contains
    invalid data."""
    pass


class Position:
    """Represents a single stock position."""
    def __init__(self, ticker: str, shares: int, avg_cost: float,
                 current_price: float):
        self.ticker = ticker
        self.shares = shares
        self.avg_cost = avg_cost
        self.current_price = current_price

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "shares": self.shares,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
        }


class AccountState:
    """Holds the full account state after reading and validation."""
    def __init__(self, last_updated: str, cash: float, buying_power: float,
                 positions: List[Position], notes: str = ""):
        self.last_updated = last_updated
        self.cash = cash
        self.buying_power = buying_power
        self.positions = positions
        self.notes = notes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_updated": self.last_updated,
            "cash": self.cash,
            "buying_power": self.buying_power,
            "positions": [p.to_dict() for p in self.positions],
            "notes": self.notes,
        }


def _validate_numeric(value: Any, field_name: str) -> float:
    """Validate that a value is a number (int or float)."""
    if not isinstance(value, (int, float)):
        raise AccountStateError(
            f"Field '{field_name}' must be a number, got {type(value).__name__}"
        )
    return float(value)


def _validate_string(value: Any, field_name: str) -> str:
    """Validate that a value is a string."""
    if not isinstance(value, str):
        raise AccountStateError(
            f"Field '{field_name}' must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise AccountStateError(
            f"Field '{field_name}' must not be empty"
        )
    return value.strip()


def _validate_positive(value: float, field_name: str) -> float:
    """Validate that a numeric value is non-negative."""
    if value < 0:
        raise AccountStateError(
            f"Field '{field_name}' must be non-negative, got {value}"
        )
    return value


def read_account_state(filepath: str = None) -> AccountState:
    """Read and validate the account state JSON file.

    Args:
        filepath: Path to the JSON file. If None, defaults to
                  input/account_state.json relative to project root.

    Returns:
        An AccountState object with validated data.

    Raises:
        AccountStateError: If the file is missing, malformed, or
                          contains invalid data.
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    if filepath is None:
        filepath = str(DEFAULT_INPUT_DIR / DEFAULT_STATE_FILE)

    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(
            f"Account state file not found: {path.resolve()}"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate top-level fields
    last_updated = _validate_string(data.get("last_updated", ""),
                                    "last_updated")
    cash = _validate_numeric(data.get("cash", None), "cash")
    cash = _validate_positive(cash, "cash")

    buying_power = _validate_numeric(data.get("buying_power", None),
                                     "buying_power")
    buying_power = _validate_positive(buying_power, "buying_power")

    notes = data.get("notes", "")
    if not isinstance(notes, str):
        notes = str(notes)

    # Validate positions array
    raw_positions = data.get("positions", [])
    if not isinstance(raw_positions, list):
        raise AccountStateError(
            f"Field 'positions' must be a list, got "
            f"{type(raw_positions).__name__}"
        )

    positions: List[Position] = []
    for i, pos in enumerate(raw_positions):
        if not isinstance(pos, dict):
            raise AccountStateError(
                f"positions[{i}] must be an object, got "
                f"{type(pos).__name__}"
            )

        ticker = _validate_string(pos.get("ticker", ""),
                                  f"positions[{i}].ticker")
        shares = _validate_numeric(pos.get("shares", None),
                                   f"positions[{i}].shares")
        if shares != int(shares):
            raise AccountStateError(
                f"positions[{i}].shares must be an integer, got {shares}"
            )
        shares = int(shares)
        if shares < 0:
            raise AccountStateError(
                f"positions[{i}].shares must be non-negative, got {shares}"
            )

        avg_cost = _validate_numeric(pos.get("avg_cost", None),
                                     f"positions[{i}].avg_cost")
        avg_cost = _validate_positive(avg_cost,
                                      f"positions[{i}].avg_cost")

        current_price = _validate_numeric(pos.get("current_price", None),
                                          f"positions[{i}].current_price")
        current_price = _validate_positive(current_price,
                                           f"positions[{i}].current_price")

        positions.append(Position(ticker, shares, avg_cost, current_price))

    return AccountState(last_updated, cash, buying_power, positions, notes)


def main():
    """CLI entry point: read and display account state."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Read and validate Robinhood account state from local JSON."
    )
    parser.add_argument(
        "-f", "--file",
        default=None,
        help="Path to account state JSON file (default: input/account_state.json)"
    )
    args = parser.parse_args()

    try:
        state = read_account_state(args.file)
        print("Account state loaded successfully.")
        print(f"  Last updated : {state.last_updated}")
        print(f"  Cash         : ${state.cash:,.2f}")
        print(f"  Buying power : ${state.buying_power:,.2f}")
        print(f"  Positions    : {len(state.positions)} holdings")
        for p in state.positions:
            print(f"    {p.ticker}: {p.shares} shares @ "
                  f"${p.avg_cost:.2f} avg (current: ${p.current_price:.2f})")
        if state.notes:
            print(f"  Notes        : {state.notes}")
    except (FileNotFoundError, json.JSONDecodeError, AccountStateError) as e:
        print(f"ERROR: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())