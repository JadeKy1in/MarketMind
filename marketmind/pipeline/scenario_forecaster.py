"""Branching scenario tree generator for ACTIONABLE hypotheses.

Replaces single-point confidence forecasts with conditional multi-path
projections. Each scenario depends on key condition variables being met.
Only ACTIONABLE hypotheses trigger forecasting (MONITOR requires explicit
include_tail_risk=True for tail-risk sampling).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from marketmind.config.investigation_config import MAX_PRO_CALLS_PER_SESSION
from marketmind.gateway.async_client import chat_pro
from marketmind.gateway.token_budget import TokenBudget
from marketmind.pipeline.investigation_loop import HypothesisResult

logger = logging.getLogger("marketmind.pipeline.scenario_forecaster")

# ── Data types ──────────────────────────────────────────────────────────────────


@dataclass
class ScenarioBranch:
    conditions: dict[str, str]  # {"10Y收益率": "保持在4.5%以下"}
    probability: float
    outcome: str
    confidence: float
    timeline: str               # "3-6个月"


@dataclass
class ScenarioTree:
    hypothesis: str
    base_case: ScenarioBranch
    upside_case: ScenarioBranch
    downside_case: ScenarioBranch
    tail_risk_case: ScenarioBranch | None
    key_condition_variables: list[str]
    disclaimer: str
    generated_at: str = ""


# ── Prompt constants ─────────────────────────────────────────────────────────────

_SCENARIO_SYSTEM = (
    "你是一个宏观经济学情景分析专家。你接收投资假设，识别关键条件变量，"
    "然后生成条件化的多路径情景预测。"
    "输出必须是严格的JSON格式，包含所有字段。概率以0-1之间的小数表示。"
    "每个条件变量的值是必须满足的条件。"
    "免责声明必须提醒用户所有情景都是条件化的，依赖假设前提成立。"
)

_SCENARIO_USER = """给定以下投资假设及其置信度，请：

1. 识别2-3个关键条件变量（驱动结果的核心宏观/市场条件）
2. 生成3个情景：
   - **基准情景**（base_case）：最可能的路径，假设条件变量按当前趋势发展
   - **乐观情景**（upside_case）：条件向有利方向发展的路径
   - **悲观情景**（downside_case）：条件向不利方向发展的路径

对于每个情景，提供：
- conditions：必须满足的条件及其具体阈值（dict[str, str]）
- probability：情景发生的概率（0-1）
- outcome：该情景下的投资结果描述
- confidence：该预测的置信度（0-1）
- timeline：预期时间范围（如"1-3个月"、"3-6个月"）

投资假设：
- 假设：{hypothesis}
- 置信度：{confidence}
- 预期缺口：{expectation_gap}
- 核心逻辑：{core_logic}
- 方向：{direction}
- 风险等级：{risk_level}
- 时间窗口：{time_window}

输出严格JSON格式：
{{
  "key_condition_variables": ["变量1", "变量2"],
  "base_case": {{
    "conditions": {{"条件A": "保持在X以下"}},
    "probability": 0.50,
    "outcome": "基本情景结果描述",
    "confidence": 0.70,
    "timeline": "3-6个月"
  }},
  "upside_case": {{ ... }},
  "downside_case": {{ ... }},
  "disclaimer": "以下为条件预测，每个路径依赖假设条件成立。实际结果可能因未预期的外部冲击或条件变量的非对称变动而偏离。"
}}"""

_TAIL_RISK_USER = """给定以下投资假设，额外生成一个**尾部风险情景**（tail_risk_case）：

尾部风险情景应：
- 概率低（通常<10%），但影响严重
- 代表极端尾部事件（黑天鹅、系统性冲击、政策突变等）
- outcome描述为具体的极端情况
- confidence可以低于其他情景（反映对尾部事件预测的内在高不确定性）

投资假设：
- 假设：{hypothesis}
- 置信度：{confidence}

输出严格JSON格式，只包含尾部风险情景（将合并到已有情景树中）：
{{
  "tail_risk_case": {{
    "conditions": {{"条件A": "极端情况描述"}},
    "probability": 0.05,
    "outcome": "尾部风险结果描述",
    "confidence": 0.40,
    "timeline": "6-12个月"
  }}
}}"""

# ── JSON parsing ────────────────────────────────────────────────────────────────


def _parse_json_strict(content: str) -> dict | None:
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
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


def _parse_branch(raw: dict) -> ScenarioBranch:
    return ScenarioBranch(
        conditions={str(k): str(v) for k, v in raw.get("conditions", {}).items()},
        probability=float(raw.get("probability", 0.0)),
        outcome=str(raw.get("outcome", "")),
        confidence=float(raw.get("confidence", 0.0)),
        timeline=str(raw.get("timeline", "N/A")),
    )


# ── Main function ───────────────────────────────────────────────────────────────


async def forecast_scenarios(
    hypothesis: HypothesisResult,
    include_tail_risk: bool = False,
    budget: TokenBudget | None = None,
) -> ScenarioTree | None:
    """Generate branching scenario tree for an actionable hypothesis.

    Args:
        hypothesis: The HypothesisResult to generate scenarios for.
        include_tail_risk: If True, also generate a tail risk case (MONITOR sampling).
        budget: Optional TokenBudget for cost control. Returns None if exhausted.

    Returns:
        ScenarioTree if generation succeeded, None if skipped or parse failed.
    """
    # Only ACTIONABLE or (MONITOR with tail risk flag)
    if hypothesis.verdict == "ACTIONABLE":
        pass
    elif hypothesis.verdict == "MONITOR" and include_tail_risk:
        pass
    else:
        logger.debug(
            "Skipping scenario forecast: verdict=%s include_tail_risk=%s",
            hypothesis.verdict,
            include_tail_risk,
        )
        return None

    # Budget check
    if budget is not None and not budget.can_call_pro():
        logger.warning("Skipping scenario forecast: Pro call budget exhausted")
        return None

    try:
        user_prompt = _SCENARIO_USER.format(
            hypothesis=hypothesis.hypothesis[:1200],
            confidence=hypothesis.confidence,
            expectation_gap=hypothesis.expectation_gap,
            core_logic=hypothesis.core_logic or "N/A",
            direction=hypothesis.direction or "N/A",
            risk_level=hypothesis.risk_level or "N/A",
            time_window=hypothesis.time_window or "N/A",
        )

        if budget is not None:
            budget.reserve_pro(1536)

        response = await chat_pro(
            system_prompt=_SCENARIO_SYSTEM,
            user_prompt=user_prompt,
            temperature=0.3,
        )

        content = response.get("content", "")
        parsed = _parse_json_strict(content)

        if parsed is None:
            logger.warning("Scenario forecast: could not parse Pro response: %.200s", content)
            return None

        tree = ScenarioTree(
            hypothesis=hypothesis.hypothesis[:200],
            base_case=_parse_branch(parsed.get("base_case", {})),
            upside_case=_parse_branch(parsed.get("upside_case", {})),
            downside_case=_parse_branch(parsed.get("downside_case", {})),
            tail_risk_case=None,
            key_condition_variables=[
                str(v) for v in parsed.get("key_condition_variables", [])
            ],
            disclaimer=str(
                parsed.get(
                    "disclaimer",
                    "以下为条件预测，每个路径依赖假设条件成立",
                )
            ),
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        # Tail risk: separate Pro call for MONITOR sampling
        if include_tail_risk and hypothesis.verdict == "MONITOR":
            if budget is not None and not budget.can_call_pro():
                logger.warning("Tail risk skipped: budget exhausted after main call")
                return tree

            tail_parsed = await _generate_tail_risk(hypothesis, budget)
            if tail_parsed:
                tree.tail_risk_case = _parse_branch(tail_parsed)

        return tree

    except Exception:
        logger.exception("Scenario forecast failed for hypothesis: %.100s", hypothesis.hypothesis)
        return None


async def _generate_tail_risk(
    hypothesis: HypothesisResult,
    budget: TokenBudget | None = None,
) -> dict | None:
    """Generate tail risk scenario in a separate Pro call."""
    try:
        user_prompt = _TAIL_RISK_USER.format(
            hypothesis=hypothesis.hypothesis[:1200],
            confidence=hypothesis.confidence,
        )

        if budget is not None:
            budget.reserve_pro(1024)

        response = await chat_pro(
            system_prompt=_SCENARIO_SYSTEM,
            user_prompt=user_prompt,
            temperature=0.3,
        )

        content = response.get("content", "")
        parsed = _parse_json_strict(content)

        if parsed is None:
            logger.warning("Tail risk: could not parse Pro response: %.200s", content)
            return None

        return parsed.get("tail_risk_case", None)

    except Exception:
        logger.exception("Tail risk generation failed")
        return None
