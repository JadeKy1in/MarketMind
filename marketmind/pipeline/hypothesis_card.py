"""Hypothesis card generator for MarketMind Gate 1.

Pure transformation of HypothesisResult data into display-ready cards.
No LLM calls -- all reasoning was already done in the investigation loop.
"""

from __future__ import annotations

import random
import re
import uuid
from dataclasses import dataclass, field

from marketmind.pipeline.investigation_loop import HypothesisResult
from marketmind.integrity.input_guard import sanitize_for_llm_prompt


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class HypothesisCard:
    """Display-ready hypothesis card with 3-layer progressive disclosure."""

    direction: str
    strength_label: str        # "强" | "中" | "弱"
    frequency_frame: str       # "~4/5 情景中盈利"
    one_line_thesis: str
    max_downside_pct: float
    max_downside_prob: float
    expected_range: str
    upside_scenario: str
    downside_scenario: str
    risk_level: str
    time_window: str

    # Layer 2 (available on request)
    layer_evidence: dict
    bear_case_summary: str
    pre_mortem_triggers: list[str]

    # Layer 3 (available on explicit request)
    source_detail: str
    gscp_breakdown: dict
    raw_confidence: float

    # Metadata
    hypothesis_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── Constants ───────────────────────────────────────────────────────────────

_STRENGTH_THRESHOLDS: list[tuple[float, str]] = [
    (0.70, "强"),
    (0.50, "中"),
    (0.00, "弱"),
]

_RISK_MULTIPLIER: dict[str, float] = {"低": 0.5, "中等": 0.8, "高": 1.0}

# Patterns for pre-mortem trigger extraction
_IF_THEN_PATTERN = re.compile(
    r'如果[^。；,.;]+(?:则|将|会|可能)[^。；,.;]*[。；,.;]?'
)
_NUMBER_PATTERN = re.compile(r'\d+(?:\.\d+)?%?')


# ── Helper functions ────────────────────────────────────────────────────────

def _compute_strength_label(confidence: float) -> str:
    for threshold, label in _STRENGTH_THRESHOLDS:
        if confidence >= threshold:
            return label
    return "弱"


def _compute_frequency_frame(confidence: float) -> str:
    n = max(1, min(5, round(confidence * 5)))
    return f"~{n}/5 情景中盈利"


def _compute_downside(
    bear_confidence: float, risk_level: str
) -> tuple[float, float]:
    multiplier = _RISK_MULTIPLIER.get(risk_level, 0.8)
    downside_pct = -round(bear_confidence * multiplier * 10, 1)
    return downside_pct, round(bear_confidence, 2)


def _extract_pre_mortem_triggers(bear_case: str) -> list[str]:
    """Extract 2-3 falsifiable kill criteria from bear case text."""
    triggers: list[str] = []

    if_matches = _IF_THEN_PATTERN.findall(bear_case)
    for match in if_matches:
        cleaned = match.strip().rstrip("。；,.;")
        if len(cleaned) > 8 and cleaned not in triggers:
            triggers.append(cleaned)
        if len(triggers) >= 3:
            break

    if len(triggers) < 2:
        sentences = re.split(r'[。；\n]', bear_case)
        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 10:
                continue
            if _NUMBER_PATTERN.search(sent) and sent not in triggers:
                triggers.append(sent)
            if len(triggers) >= 3:
                break

    if len(triggers) < 2:
        sentences = [
            s.strip() for s in re.split(r'[。；\n]', bear_case) if len(s.strip()) > 10
        ]
        for sent in sentences:
            if sent not in triggers:
                triggers.append(sent)
            if len(triggers) >= 3:
                break

    return triggers[:3]


def _build_gscp_breakdown(
    confidence: float, result: HypothesisResult
) -> dict[str, float]:
    """Build GSCP multi-criteria decomposition from confidence heuristics."""
    core_len = len(result.core_logic) if result.core_logic else 0
    thematic = min(0.95, confidence * (0.90 + 0.10 * min(1.0, core_len / 50)))

    if result.time_window and result.time_window not in ("N/A", "已过期"):
        time_specificity = 0.70 if "月" in result.time_window else 0.60
    else:
        time_specificity = 0.50

    if result.direction and result.core_logic:
        catalyst = 0.85 if core_len > 30 else 0.70
    else:
        catalyst = 0.50

    spread = abs(confidence - result.bear_case_confidence)
    calibration = 0.60 + 0.30 * spread

    return {
        "主题匹配度": round(min(0.95, thematic), 2),
        "时间框架契合度": round(time_specificity, 2),
        "催化剂清晰度": round(min(0.95, catalyst), 2),
        "概率校准": round(min(0.95, calibration), 2),
    }


def _extract_expected_range(result: HypothesisResult) -> str:
    """Extract expected price/range from layer narratives."""
    for narrative in [result.layer_1_narrative, result.layer_2_narrative]:
        if not narrative:
            continue
        range_match = re.search(
            r'(\d+\.?\d*)\s*[-–到]\s*(\d+\.?\d*)', narrative
        )
        if range_match:
            base = result.direction.split()[0] if " " in result.direction else ""
            return f"{base} {range_match.group(1)}-{range_match.group(2)}" if base else result.direction
        price_match = re.search(r'(\d+\.\d{2,})', narrative)
        if price_match:
            base = result.direction.split()[0] if " " in result.direction else ""
            return f"{base} {price_match.group(1)}" if base else result.direction

    time_part = (
        f" ({result.time_window})"
        if result.time_window and result.time_window not in ("N/A", "已过期")
        else ""
    )
    return f"{result.direction}{time_part}"


def _extract_scenarios(result: HypothesisResult) -> tuple[str, str]:
    """Extract upside and downside scenarios from narratives and bear case."""
    upside = result.core_logic if result.core_logic else result.layer_1_narrative
    upside = upside[:200] + "..." if len(upside) > 200 else upside

    downside = result.bear_case
    downside = downside[:200] + "..." if len(downside) > 200 else downside

    return upside, downside


def _build_layer_evidence(result: HypothesisResult) -> dict[str, str]:
    """Build layer_evidence dict from narrative fields, sanitizing each."""
    evidence: dict[str, str] = {}
    narrative_map = {
        "L1 市场定价": result.layer_1_narrative,
        "L2 基本面": result.layer_2_narrative,
        "L3 多源验证": result.layer_3_narrative,
        "L4 历史回测": result.layer_4_narrative,
    }
    for label, narrative in narrative_map.items():
        if narrative:
            evidence[label] = sanitize_for_llm_prompt(
                narrative, source="hypothesis_card"
            ).sanitized
    return evidence


def _build_source_detail(result: HypothesisResult) -> str:
    """Extract source detail from layer_3 multisource narrative."""
    source_text = result.layer_3_narrative if result.layer_3_narrative else ""
    if source_text:
        return sanitize_for_llm_prompt(
            source_text, source="hypothesis_card"
        ).sanitized
    return f"来源: {result.direction} 相关分析数据"


# ── Card builder ────────────────────────────────────────────────────────────

def _build_single_card(result: HypothesisResult) -> HypothesisCard:
    """Build a single HypothesisCard from a HypothesisResult."""
    confidence = result.confidence
    bear_conf = result.bear_case_confidence

    upside_scenario, downside_scenario = _extract_scenarios(result)

    return HypothesisCard(
        direction=result.direction,
        strength_label=_compute_strength_label(confidence),
        frequency_frame=_compute_frequency_frame(confidence),
        one_line_thesis=sanitize_for_llm_prompt(
            result.core_logic, source="hypothesis_card"
        ).sanitized,
        max_downside_pct=_compute_downside(bear_conf, result.risk_level)[0],
        max_downside_prob=_compute_downside(bear_conf, result.risk_level)[1],
        expected_range=_extract_expected_range(result),
        upside_scenario=sanitize_for_llm_prompt(
            upside_scenario, source="hypothesis_card"
        ).sanitized,
        downside_scenario=sanitize_for_llm_prompt(
            downside_scenario, source="hypothesis_card"
        ).sanitized,
        risk_level=result.risk_level,
        time_window=result.time_window,
        layer_evidence=_build_layer_evidence(result),
        bear_case_summary=sanitize_for_llm_prompt(
            result.bear_case, source="hypothesis_card"
        ).sanitized,
        pre_mortem_triggers=_extract_pre_mortem_triggers(result.bear_case),
        source_detail=_build_source_detail(result),
        gscp_breakdown=_build_gscp_breakdown(confidence, result),
        raw_confidence=confidence,
    )


# ── Public API ──────────────────────────────────────────────────────────────

async def generate_cards(
    hypotheses: list[HypothesisResult],
    mode: str = "full",
    session_id: str = "",
) -> list[HypothesisCard]:
    """Generate display-ready hypothesis cards from investigation results.

    Args:
        hypotheses: Investigation results from the HVR loop (up to 5).
        mode: "full" (top-3), "quick" (top-1), "catchup" (top-3).
        session_id: Stable identifier for reproducible card ordering.

    Returns:
        List of HypothesisCard objects, randomized in display order.
    """
    if not hypotheses:
        return []

    select_count = 1 if mode == "quick" else 3

    sorted_hyps = sorted(hypotheses, key=lambda h: h.confidence, reverse=True)
    selected = sorted_hyps[:select_count]

    cards = [_build_single_card(hyp) for hyp in selected]

    if session_id:
        rng = random.Random(hash(session_id) % (2**31))
        rng.shuffle(cards)
    else:
        random.shuffle(cards)

    return cards
