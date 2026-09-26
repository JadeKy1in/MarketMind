"""L1 Data Mining — Flash-driven knowledge base search during Socratic dialogue.

Extracted from layer1_interactive.py per modular architecture rules (§3.1).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from marketmind.gateway.async_client import chat_flash
from marketmind.shadows.shadow_agent import defang_text

if TYPE_CHECKING:
    from marketmind.pipeline.layer1_interactive import InteractiveState

logger = logging.getLogger("marketmind.pipeline.l1_data_mining")


def is_data_mining_request(user_text: str) -> bool:
    """Detect if user is requesting data mining / Flash search."""
    mining_keywords = [
        "search for", "look up", "find data", "check", "verify",
        "what does the data say", "get data on", "research",
        "查一下", "搜索", "查查", "查", "找一下", "核实",
        "cross reference", "cross-reference",
    ]
    text_lower = user_text.lower()
    return any(kw in text_lower for kw in mining_keywords)


async def execute_data_mining(direction: str, state: "InteractiveState") -> str:
    """Execute knowledge-base data mining (training data only; no live web search)."""
    try:
        result = await chat_flash(
            system_prompt=(
                "You are a data retrieval assistant working from your training knowledge "
                "(cutoff: early 2025). You do NOT have live web search. If you do not know "
                "something or the information may be outdated, clearly state that limitation. "
                "Summarize what you know concisely."
            ),
            user_prompt=f"Find data related to: {defang_text(direction)[:500]}. Summarize key findings concisely. ",
            temperature=0.1,
            max_tokens=1024,
        )
        content = result.get("content") if isinstance(result, dict) else None
        return content or "No search results available."
    except Exception as e:
        logger.warning("Data mining Flash call failed: %s", e)
        return f"Search unavailable: {e}"
