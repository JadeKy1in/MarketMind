"""Shared input sanitization for LLM prompt text.

Red Team finding: 4 CRITICAL findings addressed by this single module:
  1. Prompt injection pattern detection (flag, don't block)
  2. Markdown control character escaping
  3. Unicode homoglyph normalization (NFC)
  4. Length truncation with audit trail

Leaf utility -- no imports from other marketmind modules.
Standard library only + dataclasses.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SanitizedText:
    """Output of sanitize_for_llm_prompt.

    Attributes:
        sanitized: Cleaned text safe for LLM prompt insertion.
        warnings: Human-readable strings, one per flagged pattern.  Empty
            list means no patterns were detected.
        truncated: True if the text was trimmed to max_length.
        original_length: Pre-sanitization character count (audit trail).
    """
    sanitized: str
    warnings: list[str]
    truncated: bool
    original_length: int


# ---------------------------------------------------------------------------
# Prompt injection pattern library (~20 patterns)
# Each tuple: (compiled regex, human-readable warning)
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'ignore\s+(all\s+)?previous\s+instructions', re.IGNORECASE),
        'Prompt injection: "ignore previous instructions" pattern detected'),
    (re.compile(r'system\s*(override|:)', re.IGNORECASE),
        'Prompt injection: "system override/colon" role escalation pattern detected'),
    (re.compile(r'you\s+are\s+now\b', re.IGNORECASE),
        'Prompt injection: "you are now" role reassignment pattern detected'),
    (re.compile(r'output\s+your\s+(prompt|instructions|system\s+prompt)', re.IGNORECASE),
        'Prompt injection: "output your prompt/instructions" extraction attempt detected'),
    (re.compile(r'reveal\s+your\s+(instructions|system\s+prompt|prompt)', re.IGNORECASE),
        'Prompt injection: "reveal your instructions/system prompt" detected'),
    (re.compile(r'from\s+now\s+on\s+you\s+are\b', re.IGNORECASE),
        'Prompt injection: "from now on you are" role reassignment detected'),
    (re.compile(r'forget\s+(everything|all|your\s+training)', re.IGNORECASE),
        'Prompt injection: "forget everything/all/training" detected'),
    (re.compile(r'act\s+as\s+(if\s+)?you\s+(are|were)\b', re.IGNORECASE),
        'Prompt injection: "act as you are/were" detected'),
    (re.compile(r'pretend\s+(you\s+are|to\s+be)\b', re.IGNORECASE),
        'Prompt injection: "pretend you are/to be" detected'),
    (re.compile(r'\bI\s+am\s+(your|the)\s+(developer|creator|system)\b', re.IGNORECASE),
        'Prompt injection: "I am your/the developer/creator/system" authority claim detected'),
    (re.compile(r'\bnew\s+(instructions|rules|directive)\b', re.IGNORECASE),
        'Prompt injection: "new instructions/rules/directive" pattern detected'),
    (re.compile(r'\bdisregard\s+(previous|prior|all)\b', re.IGNORECASE),
        'Prompt injection: "disregard previous/prior/all" detected'),
    (re.compile(r'\bDAN\b', re.IGNORECASE),
        'Prompt injection: DAN (Do Anything Now) jailbreak detected'),
    (re.compile(r'\bdeveloper[-\s]?mode\b', re.IGNORECASE),
        'Prompt injection: "developer mode" jailbreak detected'),
    (re.compile(r'\bdo\s+not\s+(respond|answer|say|follow)\b', re.IGNORECASE),
        'Prompt injection: "do not respond/answer/say/follow" output restriction detected'),
    (re.compile(r'\bonly\s+(say|respond|output|print|answer)\b', re.IGNORECASE),
        'Prompt injection: "only say/respond/output" output restriction detected'),
    (re.compile(r'\bprint\s+(the\s+)?(system\s+)?(prompt|instructions)\b', re.IGNORECASE),
        'Prompt injection: "print prompt/instructions" extraction attempt detected'),
    (re.compile(r'\bsimulate\s+(a|the)\s+(linux|terminal|shell|bash)\b', re.IGNORECASE),
        'Prompt injection: "simulate terminal/shell" jailbreak detected'),
    (re.compile(r'\bshow\s+(me|us)\s+(the|your)\s+(system\s+)?prompt\b', re.IGNORECASE),
        'Prompt injection: "show me the prompt" extraction attempt detected'),
    (re.compile(r'\brepeat\s+(the\s+)?(words?\s+)?(above|after\s+this|back\s+to\s+me)', re.IGNORECASE),
        'Prompt injection: "repeat above/back" extraction attempt detected'),
]


# ---------------------------------------------------------------------------
# Source-specific regex patterns (use \\u escapes for portability)
# ---------------------------------------------------------------------------

# Zero-width characters common in malicious PDFs.
# U+200B ZWSP, U+200C ZWNJ, U+200D ZWJ, U+200E LRM, U+200F RLM
# U+202A-202E directional overrides, U+FEFF BOM, U+00AD soft hyphen
# U+2060-2064 word joiner / invisible operators
_ZERO_WIDTH_CHARS = re.compile(
    '[​‌‍‎‏'
    '‪‫‬‭‮'
    '﻿­⁠⁡⁢⁣⁤]'
)

# content_type / content-type claims in archived text (archive tampering).
_CONTENT_TYPE_PATTERN = re.compile(r'content[_-]?type\s*:', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Markdown control character escaping
# ---------------------------------------------------------------------------

def _escape_inline_pairs(text: str) -> str:
    """Escape paired inline Markdown formatting that could inject emphasis/code blocks."""
    # Inline code: single backtick pairs, not triple fences
    text = re.sub(r'(?<!`)`(?!`)', r'\\`', text)
    # Bold with exactly two asterisks, not part of *** (bold+italic)
    text = re.sub(r'(?<!\*)\*\*(?!\*)', r'\\*\\*', text)
    # Bold with exactly two underscores, not part of ___ (bold+italic)
    text = re.sub(r'(?<!_)__(?!_)', r'\\_\\_', text)
    return text


def _escape_markdown(text: str) -> str:
    """Escape structural and inline Markdown characters in user-provided text.

    Prevents user text from injecting fake headings, blockquotes, bold,
    code fences, horizontal rules, or inline emphasis when rendered inside
    a Markdown template.
    """
    lines = text.split('\n')
    escaped_lines: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        indent = line[:len(line) - len(stripped)]

        if stripped == '':
            escaped_lines.append(line)
            continue
        if stripped.startswith('\\'):
            # Already escaped -- do not double-escape.
            escaped_lines.append(line)
            continue

        # MEDIUM-1: Escape ALL leading # characters (### → \#\#\#)
        if stripped.startswith('#'):
            match = re.match(r'^(#+)', stripped)
            hashes = match.group(1)
            rest = stripped[len(hashes):]
            escaped_hashes = ''.join('\\' + c for c in hashes)
            escaped_lines.append(indent + escaped_hashes + _escape_inline_pairs(rest))
            continue

        if stripped.startswith('>'):
            escaped_lines.append(indent + '\\>' + _escape_inline_pairs(stripped[1:]))
            continue

        # MEDIUM-2: Code fence — escape all three backticks
        if stripped.startswith('```'):
            escaped_lines.append(indent + '\\`\\`\\`' + _escape_inline_pairs(stripped[3:]))
            continue

        # MEDIUM-2: Horizontal rule — line consists ONLY of --- or ***
        if stripped.rstrip() == '---':
            escaped_lines.append(indent + '\\---')
            continue
        if stripped.rstrip() == '***':
            escaped_lines.append(indent + '\\*\\*\\*')
            continue

        # Line-start bold/underline: escape opening, then escape inline pairs in remainder
        if stripped.startswith('**'):
            escaped_lines.append(indent + '\\*\\*' + _escape_inline_pairs(stripped[2:]))
            continue
        if stripped.startswith('__'):
            escaped_lines.append(indent + '\\_\\_' + _escape_inline_pairs(stripped[2:]))
            continue

        # MEDIUM-3: No line-start pattern — apply inline escaping
        escaped_lines.append(_escape_inline_pairs(line))

    return '\n'.join(escaped_lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sanitize_for_llm_prompt(
    text: str,
    source: str = "unknown",
    max_length: int = 50000,
) -> SanitizedText:
    """Sanitize user-provided text before embedding it in LLM prompts.

    Applies four layers of sanitization:
      1. Prompt injection pattern detection (flag only, never block)
      2. Markdown control character escaping (source-dependent)
      3. Unicode NFC normalization (homoglyph defense)
      4. Length truncation with audit marker

    Args:
        text: Raw user-provided text to sanitize.
        source: Origin of the text -- determines which rules to apply.
            ``"gate1_chat"``       -- all 4 rules at full strength
            ``"pdf_upload"``       -- all 4 rules + zero-width char detection
            ``"hypothesis_card"``  -- rules 1, 3, 4 (skip markdown escaping)
            ``"archive_replay"``   -- rules 1, 3, 4 + content_type claim check
        max_length: Character limit for the sanitized output.  Text exceeding
            this length is truncated and a clear marker is appended.

    Returns:
        SanitizedText with cleaned text, warnings list, and audit metadata.
    """
    warnings: list[str] = []
    original_length = len(text)

    # ---- Step 1: Prompt injection pattern detection (on raw text) ---------
    for pattern, warning_msg in _INJECTION_PATTERNS:
        if pattern.search(text):
            warnings.append(warning_msg)

    # ---- Step 2: Source-specific pre-checks (on raw text) ----------------
    if source == "pdf_upload":
        if _ZERO_WIDTH_CHARS.search(text):
            warnings.append(
                "Zero-width characters detected in PDF upload -- "
                "potential homoglyph or hidden-text attack"
            )
    elif source == "archive_replay":
        if _CONTENT_TYPE_PATTERN.search(text):
            warnings.append(
                "content_type claim detected in archived text -- "
                "potential archive tampering"
            )

    # ---- Step 3: Markdown control character escaping ---------------------
    if source != "hypothesis_card":
        text = _escape_markdown(text)

    # ---- Step 4: Unicode NFC normalization (homoglyph defense) -----------
    text = unicodedata.normalize('NFC', text)

    # ---- Step 5: Length truncation ---------------------------------------
    truncated = len(text) > max_length
    if truncated:
        marker = (
            f"\n\n[TRUNCATED: original was {original_length} chars,"
            f" shown {max_length}]"
        )
        text = text[:max_length] + marker

    return SanitizedText(
        sanitized=text,
        warnings=warnings,
        truncated=truncated,
        original_length=original_length,
    )
