"""
test_account_reader.py - Unit tests for the account_reader module.

Tests cover:
- Successful read with valid JSON input
- FileNotFoundError when file is missing
- AccountStateError for malformed data (non-numeric cash field)
"""

import json
import pytest
from pathlib import Path

from src.account_reader import (
    read_account_state,
    AccountState,
    AccountStateError,
    Position,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_json_path(tmp_path: Path) -> Path:
    """Create a temporary valid account_state.json and return its path."""
    data = {
        "last_updated": "2026-05-04",
        "cash": 100000.00,
        "buying_power": 90000.00,
        "positions": [
            {
                "ticker": "NVDA",
                "shares": 10,
                "avg_cost": 950.00,
                "current_price": 980.00,
            }
        ],
        "notes": "Test fixture.",
    }
    filepath = tmp_path / "account_state.json"
    filepath.write_text(json.dumps(data), encoding="utf-8")
    return filepath


@pytest.fixture
def malformed_json_path(tmp_path: Path) -> Path:
    """Create a JSON file where 'cash' is a string instead of a number."""
    data = {
        "last_updated": "2026-05-04",
        "cash": "one hundred thousand",  # <-- invalid type
        "buying_power": 90000.00,
        "positions": [],
    }
    filepath = tmp_path / "bad_cash.json"
    filepath.write_text(json.dumps(data), encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReadAccountStateSuccess:
    """Tests for successful reading of a valid account state file."""

    def test_reads_valid_file(self, valid_json_path: Path):
        """Should return an AccountState with the correct values."""
        state = read_account_state(str(valid_json_path))

        assert isinstance(state, AccountState)
        assert state.last_updated == "2026-05-04"
        assert state.cash == 100000.00
        assert state.buying_power == 90000.00
        assert len(state.positions) == 1

        pos = state.positions[0]
        assert isinstance(pos, Position)
        assert pos.ticker == "NVDA"
        assert pos.shares == 10
        assert pos.avg_cost == 950.00
        assert pos.current_price == 980.00

    def test_to_dict_roundtrip(self, valid_json_path: Path):
        """AccountState.to_dict() should reproduce the original data."""
        state = read_account_state(str(valid_json_path))
        d = state.to_dict()

        assert d["cash"] == 100000.00
        assert d["buying_power"] == 90000.00
        assert d["positions"][0]["ticker"] == "NVDA"


class TestReadAccountStateErrors:
    """Tests for error handling."""

    def test_file_not_found(self):
        """Should raise FileNotFoundError when the file does not exist."""
        missing_path = Path("/nonexistent/path/account_state.json")
        with pytest.raises(FileNotFoundError) as exc_info:
            read_account_state(str(missing_path))
        assert "Account state file not found" in str(exc_info.value)

    def test_invalid_json_syntax(self, tmp_path: Path):
        """Should raise json.JSONDecodeError on malformed JSON content."""
        bad_file = tmp_path / "bad_syntax.json"
        bad_file.write_text("{invalid json}", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            read_account_state(str(bad_file))

    def test_non_numeric_cash_raises_error(self, malformed_json_path: Path):
        """Should raise AccountStateError when 'cash' is not a number."""
        with pytest.raises(AccountStateError) as exc_info:
            read_account_state(str(malformed_json_path))
        assert "cash" in str(exc_info.value)
        assert "must be a number" in str(exc_info.value)