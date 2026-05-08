"""
belief_modifier.py — Sprint 3: 信念修改建议生成器

将 FactCheckReport 与 ScrapedContent 综合后，生成对 BeliefStateManager
的修改建议（注册新命题、注入观测、更新配置）。

此模块是情报管线的"终末执行器"——输出可直接被 BeliefStateManager 消费的建议。

SPARC:
  Specification: V2.0 Sprint 3 — 从核查报告到信念修改建议
  Pseudocode: report → score conversion → proposition candidates → belief suggestions
  Architecture: 纯数据变换，无 I/O 副作用
  Refinement: 建议是可选的（可选应用/手动审批），输出 IDEMPOTENT 的建议集
  Completion: 测试覆盖率 ≥ 85%
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Enums
# ============================================================


class SuggestionActionType(str, Enum):
    """建议操作类型。"""
    REGISTER_PROPOSITION = "register_proposition"    # 注册新信念命题
    INJECT_OBSERVATION = "inject_observation"        # 注入一条观测
    ADJUST_CONFIDENCE = "adjust_confidence"          # 调整现有命题的置信度
    RETIRE_PROPOSITION = "retire_proposition"        # 建议移除一个低确信命题
    SET_CONFIG = "set_config"                        # 建议修改配置


class SuggestionUrgency(str, Enum):
    """建议紧急程度。"""
    CRITICAL = "critical"     # 必须立即处理
    HIGH = "high"             # 本轮调仓前应处理
    MEDIUM = "medium"         # 建议纳入下一轮
    LOW = "low"               # 可延迟处理
    INFO = "info"             # 仅信息性


# ============================================================
# Data Models
# ============================================================


@dataclass(frozen=True)
class BeliefModificationSuggestion:
    """单条信念修改建议。

    Attributes:
        action_type: 操作类型
        proposition_id: 目标命题 ID（可选，None 表示新建）
        proposition_text: 命题文字描述（注册时必填）
        observation_value: 观测值 [0, 1]（注入时必填）
        observation_confidence: 观测置信度 [0, 1]
        direction: 方向（bullish/bearish/neutral）
        urgency: 紧急程度
        reason: 修改理由
        source_url: 来源 URL
        evidence: 支撑证据的文本片段
        metadata: 扩展字段
    """
    action_type: SuggestionActionType = SuggestionActionType.INJECT_OBSERVATION
    proposition_id: str = ""
    proposition_text: str = ""
    observation_value: float = 0.5
    observation_confidence: float = 0.5
    direction: str = "neutral"
    urgency: SuggestionUrgency = SuggestionUrgency.MEDIUM
    reason: str = ""
    source_url: str = ""
    evidence: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BeliefModificationPlan:
    """一组信念修改建议（原子批次）。

    Attributes:
        suggestions: 建议列表
        source_url: 触发该计划的源 URL
        source_confidence: 源内容的综合可信度 [0, 1]
        report_score: 事实核查评分 [0, 100]
        urgency_override: 整体紧急程度覆盖
        generated_at: ISO-8601 生成时间
        error: 生成失败时的错误信息
    """
    suggestions: List[BeliefModificationSuggestion] = field(default_factory=list)
    source_url: str = ""
    source_confidence: float = 0.5
    report_score: float = 50.0
    urgency_override: Optional[SuggestionUrgency] = None
    generated_at: str = field(default_factory=lambda: (
        datetime.datetime.now(datetime.timezone.utc).isoformat()
    ))
    error: Optional[str] = None


@dataclass
class BeliefModifierConfig:
    """BeliefModifier 配置。

    Attributes:
        min_report_score: 低于此评分的核查结果不生成建议（默认 20）
        max_suggestions_per_plan: 单计划最大建议数（默认 5）
        auto_high_urgency_if_score_above: 评分高于此值自动升为 HIGH（默认 80）
        mock_mode: 强制 Mock 模式
    """
    min_report_score: float = 20.0
    max_suggestions_per_plan: int = 5
    auto_high_urgency_if_score_above: float = 80.0
    mock_mode: bool = False


# ============================================================
# Proposition 注册表（与 robinhood ingestion_pipeline 对齐）
# ============================================================

PRELOADED_PROPOSITIONS: Dict[str, str] = {
    "macro_us_recession_risk": "美国经济在未来 6 个月内进入衰退的概率",
    "macro_fed_rate_path": "美联储未来 3 个月将降息的概率",
    "macro_inflation_trend": "核心通胀持续下行的概率",
    "geo_us_china_tension": "中美贸易摩擦升级的概率",
    "sentiment_market_greed": "市场情绪处于贪婪区间的概率",
    "sector_tech_outperform": "科技板块未来 1 个月跑赢大盘的概率",
    "sector_energy_weakness": "能源板块未来 1 个月走弱的概率",
    "sector_financial_stress": "金融板块系统性压力上升的概率",
}


# ============================================================
# BeliefModifier — 主实现
# ============================================================


class BeliefModifier:
    """信念修改建议生成器。

    从 ScrapedContent + FactCheckReport 综合生成对 BeliefStateManager
    的修改建议。支持三种模式：自动、半自动（人工确认）、仅报告。

    用法:
        modifier = BeliefModifier()
        plan = modifier.build_plan(content, report)
        for suggestion in plan.suggestions:
            # 应用到 BeliefStateManager
            manager.ingest_observation(suggestion.proposition_id, ...)
    """

    def __init__(self, config: Optional[BeliefModifierConfig] = None) -> None:
        self._config = config or BeliefModifierConfig()

    # ============================================================
    # 公共 API
    # ============================================================

    def build_plan(
        self,
        content: Any,  # ScrapedContent or dict
        report: Any,   # FactCheckReport or dict
    ) -> BeliefModificationPlan:
        """构建信念修改计划。

        Args:
            content: ScrapedContent 实例或类似 dict
            report: FactCheckReport 实例或类似 dict

        Returns:
            BeliefModificationPlan: 计划（含 0 到多个建议）
        """
        # 标准化输入
        url = self._safe_get(content, "url", "")
        summary = self._safe_get(content, "summary", "")
        sentiment = self._safe_get(content, "sentiment", "neutral")
        extract_confidence = float(self._safe_get(content, "confidence", 0.5))
        entities = self._safe_get(content, "extracted_entities", [])

        report_score = float(self._safe_get(report, "score", 50.0))
        overall = self._safe_get(report, "overall", "indeterminate")

        # 检查评分是否低于最小阈值
        if report_score < self._config.min_report_score:
            return BeliefModificationPlan(
                source_url=url,
                source_confidence=0.0,
                report_score=report_score,
                error=(
                    f"Report score {report_score:.1f} below minimum "
                    f"threshold {self._config.min_report_score}. "
                    "No suggestions generated."
                ),
            )

        suggestions: List[BeliefModificationSuggestion] = []

        # Step 1: 根据情绪和置信度确定主要方向
        direction = sentiment if sentiment in ("bullish", "bearish", "neutral") else "neutral"
        source_confidence = min(1.0, (report_score / 100.0 + extract_confidence) / 2.0)

        # Step 2: 映射到最相关的命题
        propositions = self._match_propositions(summary, sentiment, entities, direction)

        # Step 3: 为每个匹配的命题生成注入建议
        for prop_id, relevance_score in propositions[:self._config.max_suggestions_per_plan]:
            # 根据方向计算 observation_value
            if direction == "bullish":
                obs_value = 0.5 + (source_confidence * relevance_score / 2.0)
            elif direction == "bearish":
                obs_value = 0.5 - (source_confidence * relevance_score / 2.0)
            else:
                obs_value = 0.5  # 中性

            obs_value = max(0.05, min(0.95, obs_value))

            # 确定紧急程度
            urgency = self._determine_urgency(report_score, relevance_score, direction)

            suggestion = BeliefModificationSuggestion(
                action_type=SuggestionActionType.INJECT_OBSERVATION,
                proposition_id=prop_id,
                proposition_text=PRELOADED_PROPOSITIONS.get(prop_id, ""),
                observation_value=obs_value,
                observation_confidence=source_confidence * relevance_score,
                direction=direction,
                urgency=urgency,
                reason=(
                    f"Scraped content from {url} "
                    f"with sentiment={sentiment}, confidence={source_confidence:.2f}, "
                    f"relevance={relevance_score:.2f}, "
                    f"score={report_score}/100"
                ),
                source_url=url,
                evidence=summary[:200],
                metadata={
                    "sentiment": sentiment,
                    "report_score": report_score,
                    "extract_confidence": extract_confidence,
                    "relevance_score": relevance_score,
                    "entities": entities,
                },
            )
            suggestions.append(suggestion)

        # Step 4: 如果没有匹配到任何已注册命题，生成注册建议
        if not suggestions:
            suggestions.append(self._build_register_suggestion(
                url=url,
                summary=summary,
                direction=direction,
                source_confidence=source_confidence,
                report_score=report_score,
            ))

        return BeliefModificationPlan(
            suggestions=suggestions,
            source_url=url,
            source_confidence=source_confidence,
            report_score=report_score,
        )

    # ============================================================
    # 命题匹配
    # ============================================================

    def _match_propositions(
        self,
        summary: str,
        sentiment: str,
        entities: List[Any],
        direction: str,
    ) -> List[tuple[str, float]]:
        """将内容匹配到已注册的命题。

        Returns:
            List of (proposition_id, relevance_score)
        """
        matches: List[tuple[str, float]] = []
        summary_lower = summary.lower()
        entity_names = [e.get("name", "").lower() if isinstance(e, dict) else str(e).lower() for e in entities]

        # 关键词 → 命题映射
        keyword_map: Dict[str, List[str]] = {
            "recession": ["macro_us_recession_risk"],
            "gdp": ["macro_us_recession_risk"],
            "economic slowdown": ["macro_us_recession_risk"],
            "rate cut": ["macro_fed_rate_path"],
            "interest rate": ["macro_fed_rate_path"],
            "fed": ["macro_fed_rate_path", "macro_inflation_trend"],
            "inflation": ["macro_inflation_trend"],
            "cpi": ["macro_inflation_trend"],
            "china": ["geo_us_china_tension"],
            "trade war": ["geo_us_china_tension"],
            "tariff": ["geo_us_china_tension"],
            "market sentiment": ["sentiment_market_greed"],
            "fear & greed": ["sentiment_market_greed"],
            "greed": ["sentiment_market_greed"],
            "tech": ["sector_tech_outperform"],
            "technology": ["sector_tech_outperform"],
            "ai": ["sector_tech_outperform"],
            "energy": ["sector_energy_weakness"],
            "oil": ["sector_energy_weakness"],
            "financial": ["sector_financial_stress"],
            "bank": ["sector_financial_stress"],
            "banking": ["sector_financial_stress"],
        }

        # 对每个关键词检查命中
        for keyword, prop_ids in keyword_map.items():
            if keyword in summary_lower or any(keyword in e for e in entity_names):
                for pid in prop_ids:
                    # 计算相关性分数
                    score = 0.7  # 基础命中
                    if keyword in summary_lower:
                        score += 0.1  # 摘要命中加分
                    if direction == "bullish" and pid in ("sector_tech_outperform",):
                        score += 0.1
                    if direction == "bearish" and pid in ("macro_us_recession_risk", "geo_us_china_tension"):
                        score += 0.1
                    matches.append((pid, min(1.0, score)))

        # 去重（保留最高分）
        seen: Dict[str, float] = {}
        for pid, score in matches:
            if pid not in seen or score > seen[pid]:
                seen[pid] = score

        # 按分数降序排列
        result = sorted(seen.items(), key=lambda x: x[1], reverse=True)
        return result

    # ============================================================
    # 辅助
    # ============================================================

    def _determine_urgency(
        self,
        report_score: float,
        relevance_score: float,
        direction: str,
    ) -> SuggestionUrgency:
        """根据评分、相关性、方向确定紧急程度。"""
        if report_score >= self._config.auto_high_urgency_if_score_above and relevance_score >= 0.7:
            return SuggestionUrgency.HIGH
        if report_score >= 60 and relevance_score >= 0.6:
            return SuggestionUrgency.MEDIUM
        if report_score >= 40:
            return SuggestionUrgency.LOW
        return SuggestionUrgency.INFO

    def _build_register_suggestion(
        self,
        url: str,
        summary: str,
        direction: str,
        source_confidence: float,
        report_score: float,
    ) -> BeliefModificationSuggestion:
        """当没有匹配到任何已注册命题时，生成注册新命题的建议。"""
        # 推断命题文本
        if not summary:
            prop_text = f"Market conditions from {url}"
        else:
            prop_text = summary[:100]

        return BeliefModificationSuggestion(
            action_type=SuggestionActionType.REGISTER_PROPOSITION,
            proposition_text=prop_text,
            observation_value=0.5 + (0.3 * source_confidence) if direction == "bullish" else 0.5 - (0.3 * source_confidence),
            observation_confidence=source_confidence,
            direction=direction,
            urgency=SuggestionUrgency.LOW,
            reason=f"No matching proposition found. Auto-generated from {url}",
            source_url=url,
            evidence=summary[:200],
            metadata={
                "source_confidence": source_confidence,
                "report_score": report_score,
                "direction": direction,
            },
        )

    @staticmethod
    def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
        """安全地从对象或 dict 中获取属性。"""
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)