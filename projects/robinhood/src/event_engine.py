"""
event_engine.py - Layer 2 Event-Driven Analysis Engine (Task 2.3)

Implements the Adversarial Arbitration protocol:
  1. Blue Team (forward):  Uses CAUSAL_CHAIN_TEMPLATES to build forward causal chain.
  2. Red Team (adversarial): Challenges the chain with L2 data requirements and
     alternative scenarios via a physically separate DeepSeek call.
  3. Arbiter: Computes the final discount rate and outputs the unified score.

Key design features:
  - Dual LLM invocation (physically separate API calls per Q7 decision).
  - Hardcoded discount matrix per Q9 decision (calibrated in Phase 3).
  - Clean ASCII enforcement on all outputs.
"""

import json
import os
import re
from typing import Any

import httpx

from config.event_templates import (
    ALTERNATIVE_DATA_PLAYBOOK,
    CAUSAL_CHAIN_TEMPLATES,
    match_templates,
)
from src.ascii_utils import clean_ascii_only


# ---------------------------------------------------------------------------
# Hardcoded discount matrix (Phase 3 will calibrate these from backtesting)
# ---------------------------------------------------------------------------

# discount_rate_table[blue_score_bin][red_confidence_bin] = final_discount_percent
# The arbiter maps both Blue and Red outputs into 3 bins, then looks up the discount.
# discount = score * (1 - discount_rate / 100)
DISCOUNT_CURVE = {
    # Blue bullish (score >= 70)
    "blue_high": {
        "red_high": 50,  # Red strongly challenges -> cut by 50%
        "red_mid": 25,   # Red moderately challenges -> cut by 25%
        "red_low": 10,   # Red weakly challenges -> cut by 10%
    },
    # Blue neutral (30 <= score < 70)
    "blue_mid": {
        "red_high": 40,
        "red_mid": 20,
        "red_low": 5,
    },
    # Blue bearish (score < 30)
    "blue_low": {
        "red_high": 30,
        "red_mid": 15,
        "red_low": 0,
    },
}

# --- Scoring thresholds for bin classification ---
BLUE_BIN_THRESHOLDS = {"high": 70, "mid_low": 30}
RED_BIN_THRESHOLDS = {"high": 2.0, "mid_low": 1.0}  # confidence rating 0-3


def _classify_blue_bin(blue_score: int) -> str:
    if blue_score >= BLUE_BIN_THRESHOLDS["high"]:
        return "blue_high"
    elif blue_score >= BLUE_BIN_THRESHOLDS["mid_low"]:
        return "blue_mid"
    else:
        return "blue_low"


def _classify_red_bin(red_confidence: float) -> str:
    if red_confidence >= RED_BIN_THRESHOLDS["high"]:
        return "red_high"
    elif red_confidence >= RED_BIN_THRESHOLDS["mid_low"]:
        return "red_mid"
    else:
        return "red_low"


# ---------------------------------------------------------------------------
# Blue Team prompt (forward reasoning)
# ---------------------------------------------------------------------------

BLUE_TEAM_SYSTEM_PROMPT = """You are the Blue Team in an adversarial event analysis protocol.

Your role: FORWARD REASONING. Build the most compelling causal-chain argument from the given macro events, using the provided event templates as a reference.

=== INSTRUCTIONS ===
1. Given the macro events and matched event templates, construct a forward causal chain.
2. Assign an initial confidence score (0-100) and provide your reasoning.
3. Use the templates as a reference but do NOT copy-paste them verbatim. Adapt to the specific context.

=== OUTPUT RULES ===
Return ONLY a single JSON object:
{
    "score": <integer 0-100>,
    "reasoning": <ASCII-only narrative string>,
    "causal_chain": [<list of causal steps as strings>]
}

No emoji, no decorative Unicode, no text outside the JSON object.

=== INPUT DATA ===
Macro events: {macro_events_json}
Matched templates: {templates_json}
"""


def _blue_team_forward_reasoning(
    macro_events: list[dict],
    matched_templates: list[dict],
    api_key: str,
    api_url: str,
) -> dict[str, Any]:
    """Blue Team: forward causal-chain reasoning."""
    system_prompt = BLUE_TEAM_SYSTEM_PROMPT.format(
        macro_events_json=json.dumps(macro_events, ensure_ascii=True, indent=2),
        templates_json=json.dumps(matched_templates, ensure_ascii=True, indent=2),
    )

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "Analyze these events. Build the forward causal chain and provide your score.",
            },
        ],
        "temperature": 0.4,
        "max_tokens": 2048,
    }

    try:
        response = httpx.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        body = response.json()
        raw = body["choices"][0]["message"]["content"]
        result = json.loads(raw)
    except Exception as exc:
        return {
            "score": 50,
            "reasoning": clean_ascii_only(str(exc)),
            "causal_chain": [],
        }

    score = max(0, min(100, int(result.get("score", 50))))
    reasoning = clean_ascii_only(str(result.get("reasoning", "")))
    causal_chain = [clean_ascii_only(str(s)) for s in result.get("causal_chain", [])]

    return {"score": score, "reasoning": reasoning, "causal_chain": causal_chain}


# ---------------------------------------------------------------------------
# Red Team prompt (adversarial challenge)
# ---------------------------------------------------------------------------

RED_TEAM_SYSTEM_PROMPT = """You are the Red Team in an adversarial event analysis protocol.

Your role: ADVERSARIAL CHALLENGER. Your only job is to find flaws, gaps, and overconfidence in the Blue Team's forward reasoning.

=== INSTRUCTIONS ===
1. Read the Blue Team's causal chain and reasoning below.
2. For each step in the causal chain, identify:
   a) What physical-world evidence would be REQUIRED to validate this step? (L2 data requirement)
   b) What alternative outcome could break this chain?
   c) What historical precedent contradicts this chain?
3. Assign a CHALLENGE CONFIDENCE rating (0.0 = no challenge, 3.0 = extremely strong challenge)
4. Output the ALTERNATIVE_DATA_PLAYBOOK categories that are relevant.

=== OUTPUT RULES ===
Return ONLY a single JSON object:
{
    "confidence": <float 0.0-3.0>,
    "challenge_summary": <ASCII-only string, max 500 chars>,
    "physical_evidence_required": [<list of specific L2 data requirements as strings>],
    "relevant_alt_data_categories": [<list of category names from ALTERNATIVE_DATA_PLAYBOOK>]
}

No emoji, no decorative Unicode, no text outside the JSON object.

=== INPUT DATA ===
Blue Team reasoning: {blue_reasoning}
Blue Team causal chain: {blue_chain}
Matched templates: {templates_json}
Alternative data playbook categories available: {alt_data_categories}
"""


def _red_team_adversarial_challenge(
    blue_result: dict[str, Any],
    matched_templates: list[dict],
    api_key: str,
    api_url: str,
) -> dict[str, Any]:
    """Red Team: adversarial challenge to Blue Team's reasoning."""
    # Flatten alt data categories for the prompt
    alt_data_categories_str = ", ".join(ALTERNATIVE_DATA_PLAYBOOK.keys())

    system_prompt = RED_TEAM_SYSTEM_PROMPT.format(
        blue_reasoning=blue_result.get("reasoning", ""),
        blue_chain=json.dumps(blue_result.get("causal_chain", []), ensure_ascii=True),
        templates_json=json.dumps(matched_templates, ensure_ascii=True, indent=2),
        alt_data_categories=alt_data_categories_str,
    )

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Challenge the Blue Team's analysis. Identify gaps, "
                    "demand physical evidence, and output your confidence rating."
                ),
            },
        ],
        "temperature": 0.6,  # Higher temp for more diverse challenges
        "max_tokens": 2048,
    }

    try:
        response = httpx.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        body = response.json()
        raw = body["choices"][0]["message"]["content"]
        result = json.loads(raw)
    except Exception as exc:
        return {
            "confidence": 0.0,
            "challenge_summary": clean_ascii_only(str(exc)),
            "physical_evidence_required": [],
            "relevant_alt_data_categories": [],
        }

    confidence = float(result.get("confidence", 0.0))
    confidence = max(0.0, min(3.0, confidence))

    challenge_summary = clean_ascii_only(str(result.get("challenge_summary", "")))
    physical_evidence = [
        clean_ascii_only(str(s)) for s in result.get("physical_evidence_required", [])
    ]
    alt_cats = [
        str(c) for c in result.get("relevant_alt_data_categories", [])
        if str(c) in ALTERNATIVE_DATA_PLAYBOOK
    ]

    return {
        "confidence": confidence,
        "challenge_summary": challenge_summary,
        "physical_evidence_required": physical_evidence,
        "relevant_alt_data_categories": alt_cats,
    }


# ---------------------------------------------------------------------------
# Arbiter: compute discount and final score
# ---------------------------------------------------------------------------

def _arbitrate(
    blue_result: dict[str, Any],
    red_result: dict[str, Any],
) -> dict[str, Any]:
    """Arbiter: compute the final discount and unified score.

    Steps:
      1. Classify Blue score into {blue_high, blue_mid, blue_low}.
      2. Classify Red confidence into {red_high, red_mid, red_low}.
      3. Look up discount rate from the hardcoded matrix.
      4. Compute final_score = blue_score * (1 - discount_rate / 100).
      5. Merge reasoning.

    Args:
        blue_result: Dict from blue team with 'score', 'reasoning', 'causal_chain'.
        red_result: Dict from red team with 'confidence', 'challenge_summary',
                    'physical_evidence_required', 'relevant_alt_data_categories'.

    Returns:
        Dict with 'score' (0-100) and 'reasoning' (ASCII-only string).
    """
    blue_score = blue_result.get("score", 50)
    red_confidence = red_result.get("confidence", 0.0)

    blue_bin = _classify_blue_bin(blue_score)
    red_bin = _classify_red_bin(red_confidence)

    discount_rate = DISCOUNT_CURVE[blue_bin][red_bin]
    final_score = int(round(blue_score * (1 - discount_rate / 100)))
    final_score = max(0, min(100, final_score))

    # Build unified reasoning
    parts = [
        f"Blue Team score: {blue_score}/100 (bin: {blue_bin})",
        f"Red Team confidence: {red_confidence:.1f}/3.0 (bin: {red_bin})",
        f"Discount rate applied: {discount_rate}%",
        f"Final score: {final_score}/100",
    ]

    if blue_result.get("reasoning"):
        parts.append(f"Blue Team reasoning: {blue_result['reasoning']}")

    red_summary = red_result.get("challenge_summary", "")
    if red_summary:
        parts.append(f"Red Team challenge: {red_summary}")

    evidence = red_result.get("physical_evidence_required", [])
    if evidence:
        evidence_str = "; ".join(evidence[:3])  # Top 3
        parts.append(f"L2 physical evidence required: {evidence_str}")

    alt_cats = red_result.get("relevant_alt_data_categories", [])
    if alt_cats:
        parts.append(f"Relevant alt-data categories: {', '.join(alt_cats)}")

    reasoning = " | ".join(parts)

    return {
        "score": final_score,
        "reasoning": clean_ascii_only(reasoning),
        "discount_applied": discount_rate,
        "blue_team_output": {
            "score": blue_score,
            "reasoning": clean_ascii_only(blue_result.get("reasoning", "")),
            "causal_chain": [
                clean_ascii_only(str(s)) for s in blue_result.get("causal_chain", [])
            ],
        },
        "red_team_output": {
            "confidence": red_confidence,
            "challenge_summary": clean_ascii_only(red_summary),
            "physical_evidence_required": [
                clean_ascii_only(str(s)) for s in evidence
            ],
            "relevant_alt_data_categories": alt_cats,
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_event_driven(
    macro_events: list[dict],
    api_key: str | None = None,
    deepseek_url: str | None = None,
) -> dict[str, Any]:
    """Main entry point: run full adversarial arbitration and return unified score.

    This function:
      1. Matches macro events to causal chain templates.
      2. Invokes Blue Team (forward reasoning).
      3. Invokes Red Team (adversarial challenge) in a separate API call.
      4. Arbiter computes discount and final score.
      5. Returns results matching the EngineOutput interface.

    Args:
        macro_events: List of macro event dicts.
        api_key: DeepSeek API key. Falls back to DEEPSEEK_API_KEY env var.
        deepseek_url: DeepSeek API base URL. Falls back to env var or default.

    Returns:
        Dict with 'score' (0-100) and 'reasoning' (ASCII-only string).
    """
    resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    resolved_url = deepseek_url or os.environ.get(
        "DEEPSEEK_API_URL",
        "https://api.deepseek.com/v1/chat/completions",
    )

    if not resolved_key:
        # No API key: use template-only mode (no LLM calls)
        return _template_only_mode(macro_events)

    # Step 1: Match templates
    event_titles = [e.get("title", "") for e in macro_events]
    matched_templates = match_templates(event_titles)

    # Step 2: Blue Team forward reasoning (separate API call)
    blue_result = _blue_team_forward_reasoning(
        macro_events, matched_templates, resolved_key, resolved_url,
    )

    # Step 3: Red Team adversarial challenge (separate API call - physical isolation)
    red_result = _red_team_adversarial_challenge(
        blue_result, matched_templates, resolved_key, resolved_url,
    )

    # Step 4: Arbiter
    final_result = _arbitrate(blue_result, red_result)

    # Return only the EngineOutput interface fields
    return {
        "score": final_result["score"],
        "reasoning": final_result["reasoning"],
    }


def _template_only_mode(macro_events: list[dict]) -> dict[str, Any]:
    """Fallback mode when no API key is available.

    Uses only the template matching system without LLM calls.
    Provides a rough score based on matched template count and confidence.
    """
    event_titles = [e.get("title", "") for e in macro_events]
    matched = match_templates(event_titles)

    if not matched:
        return {
            "score": 50,
            "reasoning": (
                "Event-driven analysis in template-only mode: no events matched "
                "any known causal chain template. Neutral score assigned."
            ),
        }

    matched_names = [m.get("name", "unknown") for m in matched]
    # Heuristic: more matched templates = higher potential impact
    base_score = min(70, 40 + len(matched) * 10)

    # Apply a conservative discount since we have no LLM reasoning
    discounted = int(round(base_score * 0.7))

    return {
        "score": max(0, min(100, discounted)),
        "reasoning": (
            f"Event-driven analysis in template-only mode (no API key). "
            f"Matched templates: {', '.join(matched_names)}. "
            f"Base score={base_score}, discounted 30% for lack of LLM reasoning. "
            f"Final score={discounted}/100."
        ),
    }