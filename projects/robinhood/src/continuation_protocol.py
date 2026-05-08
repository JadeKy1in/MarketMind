"""
continuation_protocol.py - Phase 5 (The Scout) Deep Dive Continuation Protocol.

Core logic of the Continuation Protocol as designed in phase5_blueprint.md:

  The DeepSeek API may truncate long reports due to max_tokens limits.
  This module implements a recursive multi-turn protocol:

    1. The initial prompt includes a continuation contract instructing the LLM
       to emit a JSON block containing `has_more` and `continuation_prompt` fields.
    2. If `has_more == true`, the module re-dispatches with the returned
       `continuation_prompt` as the user message.
    3. All returned JSON fragments are accumulated via ContinuationState
       (from scout_types.py) and finally merged with `merge_strict()`.
    4. The merged JSON is returned for downstream processing (output_formatter).

  The module wraps deepseek_client.dispatch_prompt() and provides a seamless
  "unbounded depth" experience despite API token limits.

Usage:
    from src.continuation_protocol import continuation_generate

    result = continuation_generate(
        system_prompt="You are a global macro analyst...",
        user_prompt="Analyze the impact of Fed rate cuts...",
        max_continuations=3,
        mock=True,
        ticker="GLD",
    )
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.deepseek_client import dispatch_prompt
from src.scout_types import ContinuationState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default continuation contract — injected into system prompt
# ---------------------------------------------------------------------------

_CONTINUATION_CONTRACT = """

[SYSTEM CONTRACT — Continuation Protocol]
You MUST follow these rules EXACTLY for every response:

1. Your response MUST be a valid JSON object. No markdown fences, no extra text.
2. The JSON MUST contain the following fields at minimum:
   - "has_more": <bool> — true if there is more content to generate
   - "fragment_index": <int> — starting from 0, incremented each turn
   - (all other fields relevant to the analysis)

3. If has_more == true, you MUST ALSO include a field:
   - "continuation_prompt": "<string>" — a concise instruction telling the
     model what to generate next. This should pick up exactly where the
     current fragment left off, as if the analysis was interrupted mid-sentence.

4. On the final turn (has_more == false), do NOT include continuation_prompt.

5. All string values MUST be pure ASCII. No emoji, no Unicode symbols.

FAILURE TO FOLLOW THIS CONTRACT WILL CAUSE DATA LOSS.
"""


def _ensure_contract(system_prompt: str) -> str:
    """Append the continuation contract to the system prompt if not already present."""
    if "[SYSTEM CONTRACT — Continuation Protocol]" in system_prompt:
        return system_prompt
    # Trim trailing whitespace, append contract
    return system_prompt.rstrip() + _CONTINUATION_CONTRACT


# ---------------------------------------------------------------------------
# Core entry point
# ---------------------------------------------------------------------------


def continuation_generate(
    system_prompt: str,
    user_prompt: str,
    *,
    max_continuations: int = 3,
    mock: bool = False,
    ticker: str = "UNKNOWN",
    api_key: str | None = None,
    deepseek_url: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 8192,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Execute the Continuation Protocol to generate a full-length report.

    Args:
        system_prompt: Base system prompt (contract will be appended).
        user_prompt: Initial user message to start the analysis.
        max_continuations: Maximum number of continuation rounds (safety limit).
        mock: Passed through to dispatch_prompt.
        ticker: Ticker symbol for context (mock mode).
        api_key: DeepSeek API key.
        deepseek_url: DeepSeek API base URL.
        temperature: LLM temperature.
        max_tokens: Max tokens per turn.
        timeout_seconds: HTTP timeout per turn.

    Returns:
        Merged JSON dict from all fragments, or error dict on failure.
    """
    # 1. Ensure contract is in the system prompt
    augmented_system = _ensure_contract(system_prompt)

    # 2. Initial dispatch
    state = ContinuationState(session_id=_generate_session_id())

    current_prompt = user_prompt
    for turn in range(max_continuations + 1):  # +1 for the initial turn
        logger.info(
            "Continuation turn %d/%d (session=%s)",
            turn, max_continuations, state.session_id,
        )

        result = dispatch_prompt(
            system_prompt=augmented_system,
            user_prompt=current_prompt,
            mock=mock,
            ticker=ticker,
            api_key=api_key,
            deepseek_url=deepseek_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )

        # -- Error handling --
        if "error" in result:
            logger.error(
                "Continuation dispatch failed at turn %d: %s",
                turn, result["error"],
            )
            state.is_complete = True
            # Return what we have so far with the error
            merged = state.merge_strict() if state.fragments else result
            if isinstance(merged, dict) and "error" not in merged:
                merged["_continuation_error"] = result["error"]
            return merged

        # -- Register fragment --
        state.add_fragment(turn, result)

        # -- Check for continuation --
        has_more = result.get("has_more", False)
        if not has_more:
            logger.info("Continuation complete after %d turn(s).", turn + 1)
            state.is_complete = True
            break

        continuation_prompt = result.get("continuation_prompt", "")
        if not continuation_prompt:
            logger.warning(
                "has_more=true but no continuation_prompt at turn %d. "
                "Stopping.", turn,
            )
            state.is_complete = True
            break

        current_prompt = continuation_prompt

    # -- Merge all fragments --
    merged = state.merge_strict()

    # If we exhausted max_continuations, mark as incomplete
    if not state.is_complete:
        logger.warning(
            "Continuation exceeded max_continuations=%d. "
            "Result may be truncated.",
            max_continuations,
        )
        merged["_continuation_truncated"] = True

    return merged


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _generate_session_id() -> str:
    """Generate a short unique session identifier."""
    import uuid
    return uuid.uuid4().hex[:12]