"""
event_engine.py - Layer 2 Event-Driven Analysis Engine (Task 2.3)

Implements the Adversarial Arbitration protocol:
  1. Blue Team: Forward causal-chain reasoning using event templates.
  2. Red Team: Adversarial challenge to Blue Team's logic.
  3. Arbiter: Computes discount and unified score.

Routes through DeepSeekClient when provided; falls back to template-only mode.
"""

import json
import os
import re
from typing import Any, Optional

import httpx

from config.event_templates import (
    ALTERNATIVE_DATA_PLAYBOOK,
    CAUSAL_CHAIN_TEMPLATES,
    match_templates,
)
from src.ascii_utils import clean_ascii_only
from src.deepseek_client import DeepSeekClient


# Hardcoded discount matrix
DISCOUNT_CURVE = {
    "blue_high": {"red_high": 50, "red_mid": 25, "red_low": 10},
    "blue_mid": {"red_high": 40, "red_mid": 20, "red_low": 5},
    "blue_low": {"red_high": 30, "red_mid": 15, "red_low": 0},
}

BLUE_BIN_THRESHOLDS = {"high": 70, "mid_low": 30}
RED_BIN_THRESHOLDS = {"high": 2.0, "mid_low": 1.0}


def _classify_blue_bin(blue_score):
    if blue_score >= BLUE_BIN_THRESHOLDS["high"]:
        return "blue_high"
    elif blue_score >= BLUE_BIN_THRESHOLDS["mid_low"]:
        return "blue_mid"
    return "blue_low"


def _classify_red_bin(red_confidence):
    if red_confidence >= RED_BIN_THRESHOLDS["high"]:
        return "red_high"
    elif red_confidence >= RED_BIN_THRESHOLDS["mid_low"]:
        return "red_mid"
    return "red_low"


BLUE_TEAM_SYSTEM_PROMPT = """You are the Blue Team in an adversarial event analysis protocol.
Your role: FORWARD REASONING. Build the most compelling causal-chain argument.
Return ONLY a JSON object: {"score": <int 0-100>, "reasoning": <ASCII string>, "causal_chain": [<strings>]}
Macro events: {macro_events_json}
Matched templates: {templates_json}
"""

RED_TEAM_SYSTEM_PROMPT = """You are the Red Team in an adversarial event analysis protocol.
Your role: ADVERSARIAL CHALLENGER. Find flaws in the Blue Team's reasoning.
Return ONLY a JSON object: {"confidence": <float 0.0-3.0>, "challenge_summary": <ASCII string>, "physical_evidence_required": [<strings>], "relevant_alt_data_categories": [<strings>]}
Blue Team reasoning: {blue_reasoning}
Blue Team causal chain: {blue_chain}
Matched templates: {templates_json}
Alt data categories: {alt_data_categories}
"""


def _arbitrate(blue_result, red_result):
    blue_score = blue_result.get("score", 50)
    red_confidence = red_result.get("confidence", 0.0)
    blue_bin = _classify_blue_bin(blue_score)
    red_bin = _classify_red_bin(red_confidence)
    discount_rate = DISCOUNT_CURVE[blue_bin][red_bin]
    final_score = int(round(blue_score * (1 - discount_rate / 100)))
    final_score = max(0, min(100, final_score))
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
    return {"score": final_score, "reasoning": " | ".join(parts)}


def _template_only_mode(macro_events):
    event_titles = [e.get("title", "") for e in macro_events]
    matched = match_templates(event_titles)
    if not matched:
        return {"score": 50, "reasoning": "Event-driven analysis: no events matched any known causal chain template. Neutral score assigned."}
    matched_names = [m.get("name", "unknown") for m in matched]
    base_score = min(70, 40 + len(matched) * 10)
    discounted = int(round(base_score * 0.7))
    return {
        "score": max(0, min(100, discounted)),
        "reasoning": f"Event-driven analysis (template-only mode). Matched templates: {', '.join(matched_names)}. Base score={base_score}, discounted 30%. Final score={discounted}/100.",
    }


def analyze_event_driven(
    macro_events,
    api_key=None,
    deepseek_url=None,
    client=None,
):
    """Main entry point: adversarial arbitration with Blue/Red team review.

    When client is provided, routes both teams through DeepSeekClient.
    Otherwise uses template-only mode (no LLM calls).
    """
    event_titles = [e.get("title", "") for e in macro_events]
    matched_templates = match_templates(event_titles)

    if client is not None:
        # Blue Team via client
        blue_system = BLUE_TEAM_SYSTEM_PROMPT.format(
            macro_events_json=json.dumps(macro_events, ensure_ascii=True, indent=2),
            templates_json=json.dumps(matched_templates, ensure_ascii=True, indent=2),
        )
        try:
            br = client.dispatch(
                system_prompt=blue_system,
                user_prompt="Analyze these events. Build the forward causal chain and provide your score.",
                model="deepseek-v4-pro",
                call_profile="analysis",
            )
            if "error" in br:
                raise RuntimeError(str(br["error"].get("message", "Unknown")))
            blue_result = {"score": max(0, min(100, int(br.get("score", 50)))),
                           "reasoning": clean_ascii_only(str(br.get("reasoning", ""))),
                           "causal_chain": [clean_ascii_only(str(s)) for s in br.get("causal_chain", [])]}
        except Exception as exc:
            blue_result = {"score": 50, "reasoning": clean_ascii_only(str(exc)), "causal_chain": []}

        # Red Team via client
        alt_cats = ", ".join(ALTERNATIVE_DATA_PLAYBOOK.keys())
        red_system = RED_TEAM_SYSTEM_PROMPT.format(
            blue_reasoning=blue_result.get("reasoning", ""),
            blue_chain=json.dumps(blue_result.get("causal_chain", []), ensure_ascii=True),
            templates_json=json.dumps(matched_templates, ensure_ascii=True, indent=2),
            alt_data_categories=alt_cats,
        )
        try:
            rr = client.dispatch(
                system_prompt=red_system,
                user_prompt="Challenge the Blue Team's analysis. Identify gaps and output your confidence rating.",
                model="deepseek-v4-pro",
                call_profile="reasoning",
            )
            if "error" in rr:
                raise RuntimeError(str(rr["error"].get("message", "Unknown")))
            red_result = {
                "confidence": max(0.0, min(3.0, float(rr.get("confidence", 0.0)))),
                "challenge_summary": clean_ascii_only(str(rr.get("challenge_summary", ""))),
                "physical_evidence_required": [clean_ascii_only(str(s)) for s in rr.get("physical_evidence_required", [])],
                "relevant_alt_data_categories": [str(c) for c in rr.get("relevant_alt_data_categories", []) if str(c) in ALTERNATIVE_DATA_PLAYBOOK],
            }
        except Exception as exc:
            red_result = {"confidence": 0.0, "challenge_summary": clean_ascii_only(str(exc)),
                          "physical_evidence_required": [], "relevant_alt_data_categories": []}

        return _arbitrate(blue_result, red_result)

    # No client: template-only mode
    return _template_only_mode(macro_events)
