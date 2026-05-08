"""
test_ascii_utils.py - Phase 4: ASCII purification unit tests.

Tests the shared clean_ascii_only() function that enforces the
"zero emoji / non-ASCII decorative characters" rule across the pipeline.
"""

from __future__ import annotations

import pytest

from src.ascii_utils import clean_ascii_only


class TestCleanAsciiOnly:
    """Test suite for the clean_ascii_only function."""

    def test_pure_ascii_passthrough(self) -> None:
        """Text with only ASCII printable chars is returned unchanged (modulo strip)."""
        text = "Hello, World! AAPL +2.3% [BUY] $175.50"
        assert clean_ascii_only(text) == text.strip()

    def test_emoji_stripped(self) -> None:
        """Emoji characters are removed."""
        text = "Strong buy signal!  AAPL to the moon!   "
        result = clean_ascii_only(text)
        assert result == "Strong buy signal! AAPL to the moon!"
    def test_fancy_quotes_replaced(self) -> None:
        """Non-ASCII fancy quotes / curly quotes are stripped."""
        text = "AAPL\u2019s revenue grew \u201csignificantly\u201d in Q4."
        result = clean_ascii_only(text)
        assert "'" not in result  # Left/right single quote replaced
        assert "\u201c" not in result  # Left double quote
        assert "\u201d" not in result  # Right double quote
        # Only ASCII chars should remain
        assert all(32 <= ord(c) <= 126 or c in "\n\t" for c in result)

    def test_unicode_fractions_stripped(self) -> None:
        """Unicode fraction characters (e.g. 1/2, 3/4) are removed."""
        text = "AAPL P/E ratio improved to 28.5x, \u2154 of analysts agree."
        result = clean_ascii_only(text)
        assert "\u2154" not in result
        assert "analysts" in result

    def test_newline_and_tab_preserved(self) -> None:
        """Newline and tab characters are preserved."""
        text = "Column1\tColumn2\nValue1\t42\n"
        result = clean_ascii_only(text)
        assert "\n" in result
        assert "\t" in result
        assert result == text.strip()

    def test_control_chars_stripped(self) -> None:
        """Non-printable control characters (e.g. null, bell) are removed."""
        text = "AAPL\x00 is \x07 great"
        result = clean_ascii_only(text)
        assert "\x00" not in result
        assert "\x07" not in result
        assert result == "AAPL is great"

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert clean_ascii_only("") == ""

    def test_only_whitespace(self) -> None:
        """Whitespace-only string returns empty after strip."""
        assert clean_ascii_only("   \t\n  ") == ""

    def test_idempotent(self) -> None:
        """Applying the function twice yields the same result."""
        text = "Hello \u2014 World!  "
        first = clean_ascii_only(text)
        second = clean_ascii_only(first)
        assert first == second

    def test_wide_chinese_chars_stripped(self) -> None:
        """Chinese characters are not ASCII printable and are stripped."""
        text = "AAPL \u4e2d\u56fd market"
        result = clean_ascii_only(text)
        assert "\u4e2d" not in result
        assert "\u56fd" not in result
        assert result == "AAPL market"

    def test_mixed_ascii_and_unicode(self) -> None:
        """Complex mix with various Unicode symbols is properly cleaned."""
        text = (
            "AAPL \u2606 (+2.3%) \u2192 $175 | \u00b1 5% \u20ac "
            "\u201cStrong Buy\u201d \ud83d\udcc8\ufe0f"
        )
        result = clean_ascii_only(text)
        # All non-ASCII chars removed
        assert all(32 <= ord(c) <= 126 or c in "\n\t" for c in result)
        # Key ASCII content preserved
        assert "AAPL" in result
        assert "+2.3%" in result
        assert "$175" in result