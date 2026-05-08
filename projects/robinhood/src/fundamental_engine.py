"""
fundamental_engine.py - Layer 2 Fundamental Analysis Engine (Task 2.1)

Uses DeepSeek API with a Soros reflexivity theory System Prompt to
reason about macro events and derive causal-chain logic.

Key design elements:
  - clean_ascii_only(): Strips all non-ASCII characters from LLM output
    (emojis, decorative symbols, etc.) to enforce output discipline.
  - Dual-invocation pattern: The caller (event_engine) may invoke this
    engine twice (Blue Team / Red Team) with physically separate API calls.
  - JSON-only output contract: LLM must return {score: 0-100, reasoning: str}.
"""

import json
import os
import re
from typing import Any

import httpx

from src.ascii_utils import clean_ascii_only  # re-exported for backward compat


# ---------------------------------------------------------------------------
# Reflexivity system prompt (immutable template)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are a macro-economic fundamental analyst operating under the Soros theory of reflexivity.

Your task is to analyze macro-economic and geopolitical events, then produce a structured assessment.

=== REFLEXIVITY FRAMEWORK ===
Apply the following three-layer reasoning chain:

1. POSITIONAL BIAS IDENTIFICATION:
   - Identify the prevailing market narrative (the "prevailing bias").
   - Is this bias self-reinforcing or self-correcting?
   - What is the gap between market perception and underlying reality?

2. REFLEXIVE LOOP MAPPING:
   - Trace how the prevailing bias feeds back into the underlying fundamentals.
   - Is the market entering a virtuous cycle (rising prices -> more capital -> more innovation) or a vicious cycle?
   - Identify potential pivot points where the loop could break.

3. CALCULATED SKEPTICISM:
   - What specific assumptions would have to be wrong for this narrative to collapse?
   - What observable data (physical, financial, regulatory) would provide early warning?
   - Under what timeframe does this thesis expire?

=== INDUSTRY CHAIN TRACING ===
For any event affecting a specific sector, trace the full vertical industry chain:
  - Upstream input cost impact
  - Mid-stream processing/margin impact
  - Downstream demand impact
  - Substitution effects and alternative supply routes

=== OUTPUT RULES ===
- Return ONLY a single JSON object with EXACTLY two keys:
    "score": <integer between 0 and 100>
    "reasoning": <string, pure ASCII text, no emoji, no decorative symbols>

- Score interpretation:
    0-20:  Severe fundamental headwinds, avoid or short
    21-40: Negative fundamental tilt, caution required
    41-60: Neutral / mixed fundamentals, wait for clarity
    61-80: Positive fundamental tilt, constructive setup
    81-100: Strong fundamental tailwinds, highly constructive

- The reasoning field must be pure narrative text. Use standard ASCII characters only.
  No emoji, no fancy quotes, no Unicode decorative symbols.

- Format your response as a valid JSON object on a single line or pretty-printed.
  Do NOT include any text outside the JSON object.

=== INPUT DATA ===
Macro events: {macro_events_json}
Current positions: {positions_json}
"""


def _build_system_prompt(macro_events: list[dict], positions: list[dict]) -> str:
    """Build the system prompt with reflexivity framework, filled with actual data.

    Args:
        macro_events: List of macro event dicts with 'title', 'description', 'category',
                      'date' keys.
        positions: List of position dicts with 'ticker', 'shares', 'avg_cost' keys.

    Returns:
        The formatted system prompt string (ASCII-safe).
    """
    return SYSTEM_PROMPT_TEMPLATE.format(
        macro_events_json=json.dumps(macro_events, ensure_ascii=True, indent=2),
        positions_json=json.dumps(positions, ensure_ascii=True, indent=2),
    )


def analyze_fundamental(
    macro_events: list[dict],
    positions: list[dict],
    api_key: str | None = None,
    deepseek_url: str | None = None,
) -> dict[str, Any]:
    """Main entry point: send macro events to DeepSeek with reflexivity prompt.

    Args:
        macro_events: Macro calendar events from macro_calendar.
        positions: Current portfolio positions from account_reader.
        api_key: DeepSeek API key. Falls back to DEEPSEEK_API_KEY env var.
        deepseek_url: DeepSeek API base URL. Falls back to env var or default.

    Returns:
        Dict with 'score' (0-100) and 'reasoning' (ASCII-only string).
        On error, returns a safe fallback dict with score 50 and explanation.
    """
    resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    resolved_url = deepseek_url or os.environ.get(
        "DEEPSEEK_API_URL",
        "https://api.deepseek.com/v1/chat/completions",
    )

    if not resolved_key:
        return {
            "score": 50,
            "reasoning": (
                "Fundamental analysis skipped: DEEPSEEK_API_KEY not configured. "
                "Returning neutral score as fallback."
            ),
        }

    system_prompt = _build_system_prompt(macro_events, positions)

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Analyze the current macro event set using the reflexivity framework. "
                    "Output JSON only."
                ),
            },
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    try:
        response = httpx.post(
            resolved_url,
            headers={
                "Authorization": f"Bearer {resolved_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        body = response.json()

        raw_content = body["choices"][0]["message"]["content"]
    except Exception as exc:
        return {
            "score": 50,
            "reasoning": (
                f"Fundamental analysis failed: {clean_ascii_only(str(exc))}. "
                "Returning neutral score as fallback."
            ),
        }

    # Parse and clean LLM response
    try:
        result = json.loads(raw_content)
    except json.JSONDecodeError:
        # Try to extract JSON from the response if it's wrapped in markdown etc.
        json_match = re.search(r"\{[^{}]*\}", raw_content, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                result = {"score": 50, "reasoning": "Failed to parse LLM response as JSON."}
        else:
            result = {"score": 50, "reasoning": "Failed to parse LLM response as JSON."}

    # Normalize and clean
    score = int(result.get("score", 50))
    score = max(0, min(100, score))
    reasoning = clean_ascii_only(str(result.get("reasoning", "")))

    if not reasoning:
        reasoning = "LLM returned empty reasoning. Neutral assessment applied."

    return {"score": score, "reasoning": reasoning}