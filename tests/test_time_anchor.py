"""Tests for time_anchor.py hook — mechanical time-awareness enforcement.

Tests:
  1. test_time_anchor_outputs_timestamp — get_real_time() returns a valid ISO 8601 timestamp
  2. test_current_time_file_created — write_current_time creates a file with expected content
"""

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add the hooks directory to path so we can import the hook module
HOOKS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import time_anchor  # noqa: E402


def test_time_anchor_outputs_timestamp():
    """get_real_time() returns a valid ISO 8601 UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format."""
    ts = time_anchor.get_real_time()

    # Must be a non-empty string
    assert ts, "Should return a non-empty string"

    # Must contain ISO 8601 separator
    assert "T" in ts, f"Should contain ISO separator 'T', got: {ts}"

    # Must be UTC (Z suffix)
    assert ts.endswith("Z"), f"Should end with 'Z' (UTC), got: {ts}"

    # Must be parseable as a datetime and year must be >= 2026
    try:
        dt = datetime.strptime(ts.replace("Z", "+00:00"), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        # Try the powershell format as fallback
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))

    assert dt.year >= 2026, f"Year should be >= 2026, got {dt.year}"
    assert dt.tzinfo is not None or ts.endswith("Z"), "Must be timezone-aware or UTC"


def test_current_time_file_created():
    """write_current_time creates a file with expected content fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ts = "2026-05-17T14:30:00Z"
        filepath = time_anchor.write_current_time(ts, tmp)

        # File must exist at the returned path
        assert filepath.exists(), f"File should exist at: {filepath}"
        assert filepath == tmp / "current_time.txt", "Should be named current_time.txt"

        content = filepath.read_text(encoding="utf-8")

        # Check all required content fields
        assert "Session start: 2026-05-17T14:30:00Z" in content, (
            "Should contain the session start timestamp"
        )
        assert "Training cutoff: 2026-01-01" in content, (
            "Should contain the training cutoff date"
        )
        assert "Delta:" in content, "Should contain the delta line"
        assert "~4 months" in content or "~5 months" in content, (
            "Should compute ~4-5 month delta from Jan 2026 to May 2026"
        )


def test_format_display_contains_expected_fields():
    """format_display returns a string with expected substrings."""
    result = time_anchor.format_display("2026-05-17T14:30:00Z")

    assert "[time_anchor]" in result, "Should contain the hook tag"
    assert "Real time:" in result, "Should contain the time label"
    assert "Delta from training:" in result, "Should contain the delta label"
    assert "UTC" in result, "Should indicate UTC"
