"""Shared LLM response JSON extraction — handles markdown fences and malformed output."""
from __future__ import annotations
import json
import re


def extract_json(content: str) -> dict | list:
    """Extract JSON object/array from LLM response.

    Handles: ```json fences, bare ``` fences, leading/trailing text, nested brackets.
    Raises ValueError if no valid JSON found.
    """
    content = content.strip()

    # Strip ``` fences (with or without language tag)
    fence_stripped = _strip_fences(content)
    if fence_stripped != content:
        try:
            return json.loads(fence_stripped)
        except json.JSONDecodeError:
            pass

    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try extracting {...} or [...] substring using bracket matching
    for open_b, close_b in [("[", "]"), ("{", "}")]:
        start = content.find(open_b)
        if start != -1:
            end = _find_matching_bracket(content, start, open_b, close_b)
            if end != -1:
                try:
                    return json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    pass

    raise ValueError(f"No valid JSON found in response content (first 200 chars): {content[:200]}")


def _strip_fences(content: str) -> str:
    """Remove ``` markers. Handles leading language tags like ```json."""
    lines = content.split("\n")
    # Find first fence line
    start_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            start_idx = i
            break
    if start_idx == -1:
        return content

    # Find matching closing fence (must be on its own line or at end of text)
    end_idx = -1
    for i in range(len(lines) - 1, start_idx, -1):
        stripped = lines[i].strip()
        if stripped == "```" or stripped.startswith("```"):
            end_idx = i
            break

    if end_idx == -1 or end_idx <= start_idx:
        # Only opening fence found — strip it and return the rest
        return "\n".join(lines[start_idx + 1:])

    return "\n".join(lines[start_idx + 1:end_idx])


def _find_matching_bracket(text: str, start: int, open_b: str, close_b: str) -> int:
    """Find matching closing bracket accounting for nesting."""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == open_b:
            depth += 1
        elif ch == close_b:
            depth -= 1
            if depth == 0:
                return i
    return -1
