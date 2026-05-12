"""
fundamental_engine.py - Layer 2 Fundamental Analysis Engine (Task 2.1)

Uses DeepSeek API with a Soros reflexivity theory System Prompt to
reason about macro events and derive causal-chain logic.

Routes through DeepSeekClient when provided, falls back to legacy httpx.
"""

import json
import os
import re
from typing import Any, Optional

import httpx

from src.ascii_utils import clean_ascii_only
from src.deepseek_client import DeepSeekClient


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
   - Is the market entering a virtuous cycle or a vicious cycle?
   - Identify potential pivot points where the loop could break.

3. CALCULATED SKEPTICISM:
   - What specific assumptions would have to be wrong for this narrative to collapse?
   - What observable data would provide early warning?
   - Under what timeframe does this thesis expire?

=== INDUSTRY CHAIN TRACING ===
For any event affecting a specific sector, trace the full vertical industry chain:
  - Upstream input cost impact
  - Mid-stream processing/margin impact
  - Downstream demand impact
  - Substitution effects and alternative supply routes

=== OUTPUT RULES ===
Return ONLY a single JSON object with EXACTLY two keys:
    "score": <integer between 0 and 100>
    "reasoning": <string, pure ASCII text, no emoji, no decorative symbols>

Score interpretation:
    0-20:  Severe fundamental headwinds, avoid or short
    21-40: Negative fundamental tilt, caution required
    41-60: Neutral / mixed fundamentals, wait for clarity
    61-80: Positive fundamental tilt, constructive setup
    81-100: Strong fundamental tailwinds, highly constructive

Format your response as a valid JSON object. Do NOT include any text outside the JSON object.

=== INPUT DATA ===
Macro events: {macro_events_json}
Current positions: {positions_json}
"""


def _build_system_prompt(macro_events, positions):
    return SYSTEM_PROMPT_TEMPLATE.format(
        macro_events_json=json.dumps(macro_events, ensure_ascii=True, indent=2),
        positions_json=json.dumps(positions, ensure_ascii=True, indent=2),
    )


def analyze_fundamental(
    macro_events,
    positions,
    api_key=None,
    deepseek_url=None,
    client=None,
):
    """Main entry point for fundamental analysis.

    Args:
        macro_events: Macro calendar events from macro_calendar.
        positions: Current portfolio positions from account_reader.
        api_key: DeepSeek API key (legacy path).
        deepseek_url: DeepSeek API URL (legacy path).
        client: Optional DeepSeekClient for unified LLM routing.

    Returns:
        Dict with 'score' (0-100) and 'reasoning' (ASCII-only string).
    """
    system_prompt = _build_system_prompt(macro_events, positions)
    user_prompt = "Analyze the macro event set using the reflexivity framework. Output JSON only."

    # Preferred path: use unified client
    if client is not None:
        try:
            result = client.dispatch(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model="deepseek-v4-pro",
                call_profile="analysis",
            )
            if "error" in result:
                raise RuntimeError(str(result.get("error", {}).get("message", "Unknown")))
            score = int(result.get("score", 50))
            score = max(0, min(100, score))
            reasoning = clean_ascii_only(str(result.get("reasoning", "")))
            if not reasoning:
                reasoning = "LLM returned empty reasoning. Neutral assessment applied."
            return {"score": score, "reasoning": reasoning}
        except Exception as exc:
            return {"score": 50, "reasoning": f"Fundamental analysis failed: {clean_ascii_only(str(exc))}. Returning neutral score."}

    # Legacy path: direct httpx
    resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    resolved_url = deepseek_url or os.environ.get(
        "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
    )

    if not resolved_key:
        return {"score": 50, "reasoning": "Fundamental analysis skipped: DEEPSEEK_API_KEY not configured. Returning neutral score."}

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    try:
        response = httpx.post(
            resolved_url,
            headers={"Authorization": f"Bearer {resolved_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        body = response.json()
        raw_content = body["choices"][0]["message"]["content"]
    except Exception as exc:
        return {"score": 50, "reasoning": f"Fundamental analysis failed: {clean_ascii_only(str(exc))}. Returning neutral score."}

    # Parse and clean LLM response
    try:
        result = json.loads(raw_content)
    except json.JSONDecodeError:
        json_match = re.search(r"\{[^{}]*\}", raw_content, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                result = {"score": 50, "reasoning": "Failed to parse LLM response as JSON."}
        else:
            result = {"score": 50, "reasoning": "Failed to parse LLM response as JSON."}

    score = int(result.get("score", 50))
    score = max(0, min(100, score))
    reasoning = clean_ascii_only(str(result.get("reasoning", "")))

    if not reasoning:
        reasoning = "LLM returned empty reasoning. Neutral assessment applied."

    return {"score": score, "reasoning": reasoning}
