"""PICA-Unit tests for tools/scout_monitor.py — 3 tests minimum."""

import json
import tempfile
from pathlib import Path
from io import StringIO

import pytest

# Import the module under test
import tools.scout_monitor as sm
from tools.scout_monitor import SourceReport, load_state, print_report


class TestLoadState:
    """Test load_state() — valid state load and corrupted state fallback."""

    def test_valid_state_load(self, monkeypatch, tmp_path):
        """Load a well-formed state file returns the expected dict."""
        state_file = tmp_path / "scout_state.json"
        expected = {
            "sources": {"FRED": "OK", "SEC EDGAR": "FAILED"},
            "last_run": "2026-05-17T00:00:00Z",
        }
        state_file.write_text(json.dumps(expected), encoding="utf-8")

        # Patch STATE_FILE to point to our temp file
        monkeypatch.setattr(sm, "STATE_FILE", state_file)

        result = load_state()
        assert result == expected
        assert result["sources"]["FRED"] == "OK"
        assert result["last_run"] == "2026-05-17T00:00:00Z"

    def test_corrupted_state_fallback(self, monkeypatch, tmp_path):
        """Corrupted JSON returns default empty state without crashing."""
        state_file = tmp_path / "scout_state.json"
        state_file.write_text("{corrupted json!!!", encoding="utf-8")

        monkeypatch.setattr(sm, "STATE_FILE", state_file)

        result = load_state()
        assert result == {"sources": {}, "last_run": None}
        assert isinstance(result, dict)
        assert "sources" in result

    def test_missing_file_returns_default(self, monkeypatch, tmp_path):
        """Non-existent state file returns default empty state."""
        state_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr(sm, "STATE_FILE", state_file)

        result = load_state()
        assert result == {"sources": {}, "last_run": None}


class TestPrintReport:
    """Test print_report() — report generation with mock data."""

    def test_report_with_mock_data(self):
        """Print report with mixed status sources produces expected output sections."""
        reports = [
            SourceReport("FRED", "PRIMARY", 15, 12, 200, "OK", "OK", "STABLE", "", False),
            SourceReport("SEC EDGAR", "PRIMARY", 0, 0, 0, "FAILED", "OK", "NEW_FAILURE",
                         "HTTP 503", True),
            SourceReport("BLS", "PRIMARY", -1, -1, 0, "OK", "unknown", "FIRST_RUN",
                         "COT available (latest: 2026-05-15)", False),
            SourceReport("NewsAPI", "RELIABLE", -1, -1, 0, "API", "API", "STABLE",
                         "API key not configured", False),
            SourceReport("MarketWatch", "RELIABLE", 8, 5, 150, "OK", "FAILED", "RECOVERED",
                         "", False),
        ]

        buf = StringIO()
        # print_report writes to sys.stdout — redirect for capture
        import sys
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            print_report(reports, use_color=False)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()

        # Verify key sections present
        assert "Scout Monitor" in output
        assert "FRED" in output
        assert "SEC EDGAR" in output
        assert "NEW FAILURES" in output
        assert "HTTP 503" in output
        assert "RECOVERED" in output
        assert "MarketWatch" in output
        assert "API" in output or "NewsAPI" in output
        # First-run source should NOT appear as RECOVERED
        assert "FIRST_RUN" not in output  # FIRST_RUN is internal, not displayed as label

    def test_empty_reports_handled(self):
        """Empty report list does not crash."""
        buf = StringIO()
        import sys
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            print_report([], use_color=False)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        assert "Scout Monitor" in output
        # Should show "No sources configured" (not "All sources healthy") when empty
        assert "No sources configured" in output

    def test_critical_alert_section(self):
        """PRIMARY source failure triggers CRITICAL section."""
        reports = [
            SourceReport("FRED", "PRIMARY", 0, 0, 0, "FAILED", "OK", "NEW_FAILURE",
                         "Connection timeout", True),
            SourceReport("MarketWatch", "RELIABLE", 10, 8, 180, "OK", "OK", "STABLE",
                         "", False),
        ]

        buf = StringIO()
        import sys
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            print_report(reports, use_color=False)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        assert "CRITICAL" in output
        assert "FRED" in output
        assert "Connection timeout" in output
        assert "ACTION REQUIRED" in output
