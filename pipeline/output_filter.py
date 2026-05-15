"""Output filter — deterministic hallucination guard (P0 layer 5-6).

Before LLM calls: extracts all numeric values from source context (whitelist).
After LLM calls: scans output for numbers, flags fabricated values.
Replaces hallucinated numbers with [NOT IN SOURCE] marker.

Red Team condition: deterministic (no LLM call) to prevent recursive hallucination.
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger("marketmind.pipeline.output_filter")

# Thresholds for number filtering
_SMALL_NUMBER_THRESHOLD = 0.001   # skip very small numbers (often structural)
_WHITELIST_MATCH_TOLERANCE = 0.01 # relative tolerance for whitelist matching

# Patterns that should NOT be flagged as fabricated numbers
_SAFE_PATTERNS = [
    r"\b[12]\d{3}年\d{1,2}月\d{1,2}日\b",   # dates: 2026年05月15日
    r"\b\d{4}-\d{2}-\d{2}\b",                 # ISO dates
    r"\b\d+/\d+/\d+\b",                        # slash dates
    r"TODAY IS.*",                              # date context line
    r"\[NO DATA\]",                             # our own markers
    r"\[NOT IN SOURCE\]",                      # our own markers
    r"\[NUMBER NOT IN SOURCE",                  # our own markers
]

# Patterns for numbers to check (both int and float)
_NUMBER_PATTERN = re.compile(
    r'(?<![a-zA-Z0-9_])(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![a-zA-Z0-9_])'
)

# Common hallucinated probability formats
_PROBABILITY_PATTERNS = [
    r'(?:probability|概率|confidence|置信度)\s*(?:is|:|=|：|为|约|大约|大概)\s*(\d+(?:\.\d+)?)\s*%?',
    r'(?:B\d|B\d)\s*[（(]\s*(\d+(?:\.\d+)?)\s*%?\s*[）)]',  # B1 (40%)
]


def extract_numbers(text: str) -> set[float]:
    """Extract all numeric values from source context (build whitelist)."""
    if not text:
        return set()
    numbers: set[float] = set()
    for match in _NUMBER_PATTERN.finditer(text):
        try:
            numbers.add(float(match.group(1)))
        except ValueError:
            pass
    return numbers


def scan_output(output: str, source_numbers: set[float],
                strip_hallucinations: bool = True) -> tuple[str, list[str]]:
    """Scan LLM output for numbers not in the source whitelist.

    Args:
        output: LLM-generated text
        source_numbers: whitelist of numbers from source context
        strip_hallucinations: if True, replace fabricated numbers with marker

    Returns:
        (filtered_output, list of warnings)
    """
    if not output or not source_numbers:
        return output, []

    # Remove safe patterns before scanning
    cleaned = output
    for pattern in _SAFE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)

    warnings: list[str] = []
    fabricated: list[tuple[str, str]] = []  # (original, replacement)

    for match in _NUMBER_PATTERN.finditer(cleaned):
        num_str = match.group(1)
        try:
            num_val = float(num_str)
        except ValueError:
            continue

        # Skip zero and very small numbers (often structural, not fabricated)
        if abs(num_val) < _SMALL_NUMBER_THRESHOLD:
            continue

        # Check against whitelist with tolerance
        found = any(abs(num_val - src) / max(abs(src), _SMALL_NUMBER_THRESHOLD) < _WHITELIST_MATCH_TOLERANCE
                    for src in source_numbers if src != 0)
        if not found:
            warnings.append(f"Fabricated number: {num_str}")
            if strip_hallucinations:
                fabricated.append((match.group(0), match.group(0).replace(
                    num_str, f"[NOT IN SOURCE was:{num_str}]"
                )))

    # Apply replacements (reverse order to preserve positions)
    filtered = output
    for orig, repl in reversed(fabricated):
        filtered = filtered.replace(orig, repl, 1)

    if warnings:
        logger.warning("Output filter: %d fabricated numbers detected", len(warnings))

    return filtered, warnings


def has_fabricated_probabilities(text: str) -> bool:
    """Quick check: does the output contain probability-like fabricated numbers?"""
    for pattern in _PROBABILITY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def strip_meta_commentary(text: str) -> str:
    """Remove LLM meta-commentary about its own limitations.

    Strips SHORT clauses (up to 60 chars) containing meta phrases.
    Uses non-greedy matching to avoid eating the entire text.
    """
    patterns = [
        # Chinese patterns — match single clause only
        (r'作为(AI|人工智能|语言模型)[^，。]{0,50}[，。]', ''),
        (r'(基于|根据)(我|我的|训练)(数据|知识)[^，。]{0,50}[，。]', ''),
        (r'(我|我们)(不知道|不清楚|没有|无法获取)(实时|当前|最新)[^，。]{0,50}[，。]', ''),
        (r'(我的|我们的)(知识|数据)(截止|只到)[^，。]{0,50}[，。]', ''),
        # English patterns — match single sentence only
        (r'(?i)as an (AI|language model|artificial intelligence)[^.!]{0,50}[.!]', ''),
        (r'(?i)based on my (training|knowledge)[^.!]{0,50}[.!]', ''),
        (r'(?i)I (don\.t have|do not have) (access to |real.time |current )[^.!]{0,50}[.!]', ''),
        (r'(?i)(my |the )?(knowledge cutoff|training data)[^.!]{0,50}[.!]', ''),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text
