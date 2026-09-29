"""Prompt-injection defanging for text that enters LLM prompts.

Moved from marketmind/shadows/shadow_agent.py (legacy shadow ecosystem removed 2026-09-28).
"""
from __future__ import annotations

import re


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


# Instruction-override phrasings, matched case-insensitively with any whitespace.
# The zero-width space goes before the last word ("ignore previous\u200b instructions").
_OVERRIDE_PHRASES = [
    r"ignore\s+(?:all\s+|any\s+)?(?:the\s+|your\s+)?(?:previous|prior|above|earlier|preceding)"
    r"\s+(?:instructions?|prompts?|rules|directions|messages?)",
    r"disregard\s+(?:all\s+|any\s+)?(?:the\s+|your\s+)?(?:previous\s+|prior\s+|above\s+|earlier\s+)?"
    r"(?:instructions?|prompts?|rules|directions|messages?)",
    r"forget\s+(?:all\s+)?(?:your\s+|the\s+|previous\s+|prior\s+)+(?:instructions?|prompts?|rules)",
    r"system\s+prompt",
    r"you\s+are\s+now",
    r"new\s+instructions",
]
# Single words, zero-width space after the first letter.
_OVERRIDE_WORDS = [r"\bdisregard\b"]


def _build():
    rules: list[tuple[str, str]] = []          # (regex, cut kind)
    for phrase in _OVERRIDE_PHRASES:
        rules.append((phrase, "last_space"))
    for pattern, replacement in _DEFANG:       # literal tokens keep their original cut
        rules.append((re.escape(pattern).replace(r"\ ", r"\s+"),
                      f"at:{replacement.index(_ZWS)}"))
    for word in _OVERRIDE_WORDS:
        rules.append((word, "at:1"))
    names = {f"r{i}": cut for i, (_, cut) in enumerate(rules)}
    combined = "|".join(f"(?P<r{i}>{rx})" for i, (rx, _) in enumerate(rules))
    return re.compile(combined, re.IGNORECASE), names


_ZWS = "\u200b"
_RX, _CUTS = _build()


def _cut(m: re.Match) -> str:
    text = m.group(0)
    name = next(k for k, v in m.groupdict().items() if v is not None)
    cut = _CUTS[name]
    if cut == "last_space":
        i = max(i for i, ch in enumerate(text) if ch.isspace())
        while i > 0 and text[i - 1].isspace():
            i -= 1
    else:
        i = min(int(cut[3:]), len(text))
    return text[:i] + _ZWS + text[i:]


def defang_text(text: str) -> str:
    """Break prompt-injection patterns before text enters an LLM prompt.

    Matching is case-insensitive and whitespace-tolerant, in one pass (a match is
    never re-defanged by a shorter rule inside it). A zero-width space (U+200B) is
    inserted, so the text stays readable.

    Args:
        text: Raw text that may contain injection vectors.

    Returns:
        Text with all dangerous patterns defanged by zero-width space insertion.
    """
    if not isinstance(text, str) or not text:
        return text
    return _RX.sub(_cut, text)
