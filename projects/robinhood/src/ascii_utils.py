"""
ascii_utils.py - Shared ASCII purification layer (Phase 4 refactoring)

Centralizes the `clean_ascii_only()` function previously embedded in
src/fundamental_engine.py.  All engine modules that need to strip non-ASCII
characters from LLM output MUST import from this module.

Design:
  - Single regex compiled at module load for performance.
  - Pure-python; no external dependencies.
  - Function is idempotent: applying it twice yields the same result.
"""

import re

# Allowable ASCII printable characters (codes 32-126) plus newline/tab.
_ASCII_SAFE_RE = re.compile(r"[^\x20-\x7e\n\t]")

# Collapse multiple consecutive ASCII spaces into a single space.
# This prevents "ghost gaps" when non-ASCII chars are removed.
_MULTISPACE_RE = re.compile(r" {2,}")


def clean_ascii_only(text: str) -> str:
    """Strip all non-ASCII-printable characters from a string.

    This is the single enforcement point for the "no emoji, no decorative
    Unicode" rule. Applied to every LLM string that enters the system.

    Also collapses runs of 2+ ASCII spaces into a single space after
    non-ASCII characters have been removed (prevents "ghost gaps").

    Args:
        text: Raw string potentially containing emoji, fancy quotes, etc.

    Returns:
        Clean string containing only ASCII printable characters.
    """
    cleaned = _ASCII_SAFE_RE.sub("", text)
    # Iteratively collapse multiple consecutive spaces left by character removal.
    # A single re.sub(r" {2,}", " ", ...) can miss overlapping "ghost gaps"
    # on certain Python runtimes (observed on Python 3.14 / Windows).
    while "  " in cleaned:
        cleaned = cleaned.replace("  ", " ")
    return cleaned.strip()
