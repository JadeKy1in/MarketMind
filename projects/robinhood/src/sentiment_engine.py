"""
sentiment_engine.py - Layer 2 Sentiment Decoding Engine (Task 2.4)

Receives unstructured text (headlines, social media posts, news snippets),
invokes DeepSeek API, and forces structured JSON output:
    ticker, sentiment (Positive/Negative/Neutral), magnitude (0-100), reasoning.

Key design features:
  - clean_ascii_only() enforced on `reasoning` field for all outputs.
  - Graceful degradation: API / JSON failure -> Neutral, magnitude=0.
  - Reuses the same httpx-based DeepSeek call pattern as fundamental_engine.
"""

import json
import os
import re
from typing import Any

import httpx

from src.ascii_utils import clean_ascii_only


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are a market sentiment analyst. Your task is to decode the emotional/market
sentiment embedded in unstructured text and output a structured assessment.

=== INSTRUCTIONS ===
Given a piece of text (headline, news snippet, social media post, or KOL statement) and
optionally a target ticker, you must:

1. Identify which financial instrument (ticker) is being discussed.
2. Classify the sentiment as Positive, Negative, or Neutral.
3. Assign a magnitude (0-100) representing the strength of the sentiment.
4. Provide a brief ASCII-only reasoning chain explaining your assessment.

=== OUTPUT RULES ===
Return ONLY a single JSON object with EXACTLY four keys:
    "ticker": <string, uppercase ticker symbol or "UNKNOWN">,
    "sentiment": <"Positive" | "Negative" | "Neutral">,
    "magnitude": <integer between 0 and 100>,
    "reasoning": <string, pure ASCII text, no emoji, no decorative symbols>

- Magnitude interpretation:
    0-20:   Very mild / barely detectable sentiment
    21-40:  Mild sentiment
    41-60:  Moderate sentiment
    61-80:  Strong sentiment
    81-100: Extreme sentiment

- The reasoning field must be pure narrative text. Use standard ASCII characters only.
  No emoji, no fancy quotes, no Unicode decorative symbols.

- Format your response as a valid JSON object. Do NOT include any text outside the JSON object.

=== INPUT TEXT ===
{input_text}
"""


def _build_system_prompt(input_text: str) -> str:
    """Build the system prompt with the input text.

    Args:
        input_text: The unstructured text to analyze.

    Returns:
        The formatted system prompt string.
    """
    return SYSTEM_PROMPT_TEMPLATE.format(input_text=input_text)


# ---------------------------------------------------------------------------
# Safe neutral fallback
# ---------------------------------------------------------------------------

_NEUTRAL_FALLBACK = {
    "ticker": "UNKNOWN",
    "sentiment": "Neutral",
    "magnitude": 0,
    "reasoning": "Sentiment analysis failed. Returning neutral fallback.",
}


def _make_neutral_fallback(reason: str) -> dict[str, Any]:
    """Create a neutral fallback dict with ASCII-cleaned reasoning.

    Args:
        reason: Description of why fallback was triggered.

    Returns:
        Dict with Neutral sentiment, magnitude 0, and cleaned reasoning.
    """
    return {
        "ticker": "UNKNOWN",
        "sentiment": "Neutral",
        "magnitude": 0,
        "reasoning": clean_ascii_only(reason),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_sentiment(
    text: str,
    api_key: str | None = None,
    deepseek_url: str | None = None,
) -> dict[str, Any]:
    """Analyze the sentiment of unstructured text via DeepSeek API.

    Args:
        text: The unstructured text to analyze (headline, news snippet, etc.).
        api_key: DeepSeek API key. Falls back to DEEPSEEK_API_KEY env var.
        deepseek_url: DeepSeek API base URL. Falls back to env var or default.

    Returns:
        Dict with keys:
            ticker (str): Uppercase ticker symbol or "UNKNOWN".
            sentiment (str): "Positive", "Negative", or "Neutral".
            magnitude (int): 0-100 intensity of sentiment.
            reasoning (str): ASCII-only reasoning text.

        On any error, returns Neutral with magnitude 0.
    """
    resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    resolved_url = deepseek_url or os.environ.get(
        "DEEPSEEK_API_URL",
        "https://api.deepseek.com/v1/chat/completions",
    )

    # --- Graceful degradation: no API key ---
    if not resolved_key:
        return _make_neutral_fallback(
            "Sentiment analysis skipped: DEEPSEEK_API_KEY not configured. "
            "Returning neutral fallback."
        )

    system_prompt = _build_system_prompt(text)

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Analyze the sentiment of the provided text. "
                    "Output JSON only."
                ),
            },
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
    }

    # --- API call ---
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
        return _make_neutral_fallback(
            f"Sentiment analysis API call failed: {clean_ascii_only(str(exc))}."
        )

    # --- JSON parsing with markdown extraction fallback ---
    try:
        result = json.loads(raw_content)
    except json.JSONDecodeError:
        json_match = re.search(r"\{[^{}]*\}", raw_content, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                return _make_neutral_fallback(
                    "Failed to parse LLM response as JSON after markdown extraction."
                )
        else:
            return _make_neutral_fallback(
                "Failed to parse LLM response as JSON."
            )

    # --- Validate and normalize fields ---
    ticker = str(result.get("ticker", "UNKNOWN")).strip().upper()
    if not ticker:
        ticker = "UNKNOWN"

    sentiment = str(result.get("sentiment", "Neutral")).strip().capitalize()
    if sentiment not in ("Positive", "Negative", "Neutral"):
        sentiment = "Neutral"

    try:
        magnitude = int(result.get("magnitude", 0))
    except (ValueError, TypeError):
        magnitude = 0
    magnitude = max(0, min(100, magnitude))

    reasoning = clean_ascii_only(str(result.get("reasoning", "")))
    if not reasoning:
        reasoning = "LLM returned empty reasoning. Neutral assessment applied."

    return {
        "ticker": ticker,
        "sentiment": sentiment,
        "magnitude": magnitude,
        "reasoning": reasoning,
    }