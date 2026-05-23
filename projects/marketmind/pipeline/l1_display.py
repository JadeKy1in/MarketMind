"""L1 Display Utilities — console output and text processing helpers.

Extracted from layer1_interactive.py per modular architecture rules (§3.1).
Handles safe printing (Windows GBK consoles), summary extraction, truncation
detection, discussion text formatting, and AI proceed-suggestion detection.
"""
from __future__ import annotations

import sys


def safe_print(text: str) -> None:
    """Print text safely on Windows GBK consoles (handle emoji in AI output)."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="backslashreplace").decode(encoding))


def extract_concise_summary(deep_analysis: str) -> str:
    """Extract the user-facing concise summary from the deep analysis output."""
    markers = [
        "## Concise Summary",
        "## 简报格式",
        "=== CONCISE ===",
        "简明版",
        "面向用户",
        "——— 以下为面向用户的简明版",
        "**投资方向**",
        "**Direction**",
    ]
    for marker in markers:
        idx = deep_analysis.find(marker)
        if idx != -1:
            return deep_analysis[idx:].strip()
    return deep_analysis[-1200:].strip()


def response_looks_truncated(text: str) -> bool:
    """Check if text appears to have been cut off mid-sentence."""
    if len(text) < 80:
        return False
    sentence_end = {'.', '!', '?', '。', '！', '？', '"', "'", ')', ']', '》'}
    return text.rstrip()[-1] not in sentence_end


def build_discussion_text(history: list[dict]) -> str:
    """Build a flattened chat transcript from discussion history."""
    lines = []
    for msg in history:
        role = "用户" if msg["role"] == "user" else "分析师"
        content = msg.get("content", "")[:500]
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


def ai_suggests_proceeding(ai_response: str) -> bool:
    """Check if the AI is suggesting to proceed to L2."""
    proceed_phrases = [
        "enough information to proceed",
        "move to l2",
        "proceed to l2",
        "move to sector",
        "sufficient information",
        "we have enough",
        "shall we proceed",
        "ready for l2",
        "继续",
        "进入",
        "可以开始",
        "准备好了",
        "信息足够",
        "足够了",
    ]
    response_lower = ai_response.lower()
    return any(p in response_lower for p in proceed_phrases)


def format_history(history: list[dict]) -> str:
    """Format recent discussion history for the prompt."""
    lines = []
    for msg in history:
        role = "Investor" if msg["role"] == "user" else "Analyst"
        content = msg["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"**{role}**: {content}")
    return "\n\n".join(lines)
