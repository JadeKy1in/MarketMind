"""Prompt-injection defanging for text that enters LLM prompts.

Moved from marketmind/shadows/shadow_agent.py (legacy shadow ecosystem removed 2026-09-28).
"""
from __future__ import annotations


# Patterns that could be misread as control sequences by vote parsers
# or used for injection attacks against LLM prompts.
# Defanged by inserting a zero-width space (U+200B) to break the pattern
# without losing information value in the headline.
_DEFANG = [
    # Original control-sequence tokens
    ("DECISION_START", "DECISION​_START"),
    ("DECISION_END", "DECISION​_END"),
    # Backward compat with old VOTE_* tokens (pre-2026-05-26 rename)
    ("VOTE_START", "VOTE​_START"),
    ("VOTE_END", "VOTE​_END"),
    ("EXIT_DECISION:", "EXIT​_DECISION:"),
    ("INSIGHT:", "INSIGHT​:"),
    ("OBSERVATION:", "OBSERVATION​:"),
    ("DATA_INTEGRITY_PROTOCOL", "DATA​_INTEGRITY_PROTOCOL"),
    ("CASH_REFRAMING_PROTOCOL", "CASH​_REFRAMING_PROTOCOL"),
    # Role-switching injection vectors
    ("[SYSTEM]", "[​SYSTEM]"),
    ("Assistant:", "Assistant​:"),
    ("Human:", "Human​:"),
    ("User:", "User​:"),
    ("</output>", "</​output>"),
    # Instruction-override injection
    ("Ignore all previous instructions", "Ignore all previous​ instructions"),
    ("Ignore previous", "Ignore​ previous"),
    ("Forget your instructions", "Forget your​ instructions"),
    # Additional control tokens
    ("SYSTEM OVERRIDE", "SYSTEM​ OVERRIDE"),
    ("SYSTEM:", "SYSTEM​:"),
    ("override", "​override"),
]


def defang_text(text: str) -> str:
    """Apply _DEFANG sanitization to any text before it enters LLM prompts.

    Args:
        text: Raw text that may contain injection vectors.

    Returns:
        Text with all dangerous patterns defanged by zero-width space insertion.
    """
    for pattern, replacement in _DEFANG:
        text = text.replace(pattern, replacement)
    return text
