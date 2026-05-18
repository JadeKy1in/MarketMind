"""Capital flow decomposition — entity-level "who is buying what, and why."
Phase H-1 Module 2. Uses asset-class-keyed entity types (NOT US-centric).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.config.asset_class_routing import AssetClassConfig, route_asset_class
from marketmind.config.investigation_config import MAX_PRO_CALLS_PER_SESSION
from marketmind.gateway.async_client import chat_pro
from marketmind.pipeline.investigation_types import HypothesisResult

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────────────────

_FLOW_SYSTEM = """You are a capital flow analyst. Given a market hypothesis about a specific asset class and a list of relevant entity types, analyze who is buying and who is selling.

For each entity, determine:
- direction: BUY (accumulating, inflow), SELL (distributing, outflow), or NEUTRAL (no change)
- estimated_size: significant, moderate, small, or unknown
- rationale: one-line reason in English

Also determine:
- dominant_buyer: the entity with the strongest buying pressure
- dominant_seller: the entity with the strongest selling pressure
- change_trend: 加速流入 (accelerating inflow), 流入放缓 (slowing inflow), 转向流出 (turning to outflow), or 稳定 (stable)
- confidence: 0.0-1.0

Return ONLY a JSON object (no markdown, no explanation):
{"entities": [...], "dominant_buyer": "...", "dominant_seller": "...", "change_trend": "...", "confidence": 0.0}"""


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class FlowEntity:
    name: str
    direction: str          # "BUY" | "SELL" | "NEUTRAL"
    asset_class: str
    estimated_size: str     # "significant" | "moderate" | "small" | "unknown"
    rationale: str          # one-line reason


@dataclass
class FlowAttribution:
    hypothesis: str
    asset_class: str
    entities: list[FlowEntity] = field(default_factory=list)
    dominant_buyer: str = ""
    dominant_seller: str = ""
    flow_imbalance: float = 0.0       # -1 (selling dominates) to +1 (buying dominates)
    change_trend: str = ""            # "加速流入" | "流入放缓" | "转向流出" | "稳定"
    confidence: float = 0.0


# ── Helpers ──────────────────────────────────────────────────────────

def _parse_json(content: str) -> dict | None:
    """Extract JSON object from LLM response, handling markdown wrapping."""
    if not content:
        return None
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        if len(lines) > 1:
            content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start: end + 1])
            except json.JSONDecodeError:
                pass
    return None


def _compute_flow_imbalance(entities: list[FlowEntity]) -> float:
    """(BUY count - SELL count) / total entities. Range: -1.0 to +1.0."""
    if not entities:
        return 0.0
    buy_count = sum(1 for e in entities if e.direction == "BUY")
    sell_count = sum(1 for e in entities if e.direction == "SELL")
    return (buy_count - sell_count) / len(entities)


def _detect_change_trend(rationales: list[str]) -> str:
    """Detect change trend from entity rationale text patterns."""
    if not rationales:
        return "稳定"
    combined = " ".join(rationales).lower()

    # Check in priority order — outflow reversal first (strongest signal)
    if any(kw in combined for kw in ["转向", "reversal", "outflow", "exiting", "dumping", "rotating out", "fleeing"]):
        return "转向流出"
    if any(kw in combined for kw in ["加速", "accelerating", "increasing sharply", "surging", "aggressively buying", "ramping"]):
        return "加速流入"
    if any(kw in combined for kw in ["放缓", "slowing", "decelerating", "tapering", "reducing pace", "cooling"]):
        return "流入放缓"
    return "稳定"


# ── Main ─────────────────────────────────────────────────────────────

async def attribute_flows(
    hypothesis: HypothesisResult,
    pro_calls_used: list[int] | None = None,
) -> FlowAttribution | None:
    """Attribute capital flows to entity types for a given hypothesis.

    Routes the hypothesis to an asset class, then prompts Pro to analyze
    which entities are buying vs selling and why.

    Returns None if the asset class cannot be determined, the Pro call
    budget is exhausted, or the LLM response cannot be parsed.
    """
    # 1. Cost control
    if pro_calls_used is not None and pro_calls_used[0] >= MAX_PRO_CALLS_PER_SESSION:
        logger.warning(
            "Pro call budget exhausted (%d/%d) — skipping flow decomposition",
            pro_calls_used[0], MAX_PRO_CALLS_PER_SESSION,
        )
        return None

    # 2. Route to asset class
    config, routing_confidence = route_asset_class(hypothesis.hypothesis)
    if config is None:
        logger.info("Flow decomposition: unclassifiable hypothesis — returning None")
        return None

    entity_types = config.entity_types
    asset_class_id = config.class_id
    logger.info(
        "Flow decomposition: asset_class=%s (routing_confidence=%.2f), %d entity types",
        asset_class_id, routing_confidence, len(entity_types),
    )

    # 3. Build prompt
    user_prompt = (
        f"Hypothesis: {hypothesis.hypothesis}\n"
        f"Asset class: {config.name}\n"
        f"Entity types to analyze: {', '.join(entity_types)}\n"
        f"\n"
        f"Analyze the capital flows among these entities for this hypothesis. "
        f"Return the JSON object."
    )

    # 4. Call Pro
    response = await chat_pro(
        system_prompt=_FLOW_SYSTEM,
        user_prompt=user_prompt,
        temperature=0.3,
        max_tokens=1024,
    )

    if pro_calls_used is not None:
        pro_calls_used[0] += 1

    if response.get("error"):
        logger.error("Flow decomposition: chat_pro error — %s", response["error"])
        return None

    content = response.get("content", "")
    if not content:
        logger.warning("Flow decomposition: empty response from Pro")
        return None

    # 5. Parse response
    parsed = _parse_json(content)
    if parsed is None:
        logger.warning("Flow decomposition: failed to parse Pro response: %.200s", content)
        return None

    # 6. Build entities
    entities: list[FlowEntity] = []
    for e in parsed.get("entities", []):
        direction = e.get("direction", "NEUTRAL").upper()
        if direction not in ("BUY", "SELL", "NEUTRAL"):
            direction = "NEUTRAL"

        size = e.get("estimated_size", "unknown").lower()
        if size not in ("significant", "moderate", "small", "unknown"):
            size = "unknown"

        entities.append(FlowEntity(
            name=e.get("name", "UNKNOWN"),
            direction=direction,
            asset_class=asset_class_id,
            estimated_size=size,
            rationale=e.get("rationale", ""),
        ))

    # 7. Compute derived fields
    flow_imbalance = _compute_flow_imbalance(entities)

    # Use Pro's change_trend if valid, otherwise detect from rationales
    pro_trend = parsed.get("change_trend", "")
    valid_trends = {"加速流入", "流入放缓", "转向流出", "稳定"}
    change_trend = pro_trend if pro_trend in valid_trends else _detect_change_trend(
        [e.rationale for e in entities]
    )

    dominant_buyer = parsed.get("dominant_buyer", "")
    dominant_seller = parsed.get("dominant_seller", "")
    pro_confidence = float(parsed.get("confidence", 0.5))

    logger.info(
        "Flow decomposition: %d entities, imbalance=%.2f, trend=%s, confidence=%.2f",
        len(entities), flow_imbalance, change_trend, pro_confidence,
    )

    return FlowAttribution(
        hypothesis=hypothesis.hypothesis,
        asset_class=asset_class_id,
        entities=entities,
        dominant_buyer=dominant_buyer,
        dominant_seller=dominant_seller,
        flow_imbalance=flow_imbalance,
        change_trend=change_trend,
        confidence=pro_confidence,
    )
