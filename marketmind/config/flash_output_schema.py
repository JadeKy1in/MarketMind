"""Flash LLM output JSON schema validation.

Red Team finding C1: Flash LLM output directly drives Pro tool calls with no
validation. This module defines the EXPECTED schema for Flash triage output,
providing schema validation and tool allowlist filtering.

This schema is designed to be used by the future flash_triage.py module.
"""

from __future__ import annotations

from typing import Any


FLASH_TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["headline", "source_tier", "scores", "classification"],
    "properties": {
        "headline": {"type": "string", "maxLength": 300},
        "source_tier": {"type": "integer", "minimum": 1, "maximum": 4},
        "scores": {
            "type": "object",
            "required": [
                "market_impact",
                "cross_source_corroboration",
                "contradicts_consensus",
                "investigative_depth_needed",
                "urgency",
            ],
            "properties": {
                "market_impact": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "0=no impact, 10=market-moving",
                },
                "cross_source_corroboration": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "0=uncorroborated, 10=widely reported",
                },
                "contradicts_consensus": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "0=aligned with consensus, 10=strongly contradicts",
                },
                "investigative_depth_needed": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "0=shallow, 10=deep multi-source investigation needed",
                },
                "urgency": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "0=background, 10=immediate action may be warranted",
                },
            },
        },
        "classification": {
            "type": "string",
            "enum": ["macro", "company", "geopolitical", "sentiment", "technical"],
        },
        "suggested_tools": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
        },
        "tickers": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 10,
        },
        "rationale": {"type": "string", "maxLength": 500},
    },
}

# Tool allowlist: which tools Flash may suggest based on classification.
# Any tool NOT in the allowlist for the given classification is rejected.
TOOL_ALLOWLIST: dict[str, list[str]] = {
    "macro": [
        "fred_api",
        "eia_api",
        "bls_api",
        "ecb_rss",
        "world_bank_api",
        "imf_api",
    ],
    "company": [
        "sec_edgar",
        "yfinance",
        "finnhub",
        "alpha_vantage",
    ],
    "geopolitical": [
        "commodity_api",
        "currency_api",
        "eia_api",
    ],
    "sentiment": [
        "reddit_rss",
        "bluesky_api",
        "twitter_api",
    ],
    "technical": [
        "yfinance",
        "finnhub",
        "binance",
        "alpha_vantage",
    ],
}


def validate_flash_output(data: dict) -> bool:
    """Validate Flash output against the schema.

    Performs lightweight structural validation:
    - All required top-level keys present
    - Scores are integers in [0, 10]
    - Classification is a known enum value
    - Suggested tools (if present) are a list of strings

    This is NOT a full JSON Schema validator — it checks the critical
    structural constraints that prevent malformed Flash output from
    reaching downstream Pro tool calls.

    Args:
        data: Flash LLM output dict to validate.

    Returns:
        True if the output passes validation, False otherwise.
    """
    if not isinstance(data, dict):
        return False

    schema = FLASH_TRIAGE_SCHEMA

    # Required top-level keys
    for key in schema["required"]:
        if key not in data:
            return False

    # Headline must be a string
    if not isinstance(data.get("headline"), str):
        return False

    # Source tier must be integer in [1, 4]
    st = data.get("source_tier")
    if not isinstance(st, int) or st < 1 or st > 4:
        return False

    # Scores object validation
    scores = data.get("scores", {})
    if not isinstance(scores, dict):
        return False

    if not scores:
        return False  # truly malformed: no score data

    # Validate each score that IS present (accept string-to-int coercion).
    # Missing keys are allowed — TriageResult constructor fills defaults (0).
    score_props = schema["properties"]["scores"]["properties"]
    for score_key, val in scores.items():
        if isinstance(val, str):
            try:
                val = int(val)
            except (ValueError, TypeError):
                return False
        if not isinstance(val, (int, float)):
            return False
        spec = score_props.get(score_key)
        if spec is not None:
            if val < spec.get("minimum", 0) or val > spec.get("maximum", 10):
                return False

    # Classification must be a valid enum value
    classification = data.get("classification")
    valid_classes = schema["properties"]["classification"]["enum"]
    if classification not in valid_classes:
        return False

    # Suggested tools (optional) must be a list of strings if present
    tools = data.get("suggested_tools")
    if tools is not None:
        if not isinstance(tools, list):
            return False
        if len(tools) > schema["properties"]["suggested_tools"].get("maxItems", 5):
            return False
        if not all(isinstance(t, str) for t in tools):
            return False

    return True


def filter_suggested_tools(classification: str, suggested: list[str]) -> list[str]:
    """Filter Flash-suggested tools against the allowlist.

    Only tools in the TOOL_ALLOWLIST for the given classification are permitted.
    Tools not in the allowlist are silently dropped.

    Args:
        classification: One of the valid classification enum values.
        suggested: List of tool names suggested by Flash LLM.

    Returns:
        Filtered list containing only allowed tools.
    """
    allowed = TOOL_ALLOWLIST.get(classification, [])
    if not allowed:
        return []
    return [tool for tool in suggested if tool in allowed]
