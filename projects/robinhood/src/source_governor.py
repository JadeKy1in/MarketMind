"""
source_governor.py — Layer 0: 信源治理引擎 (Source Authority Rating + Triangle Validation)
Part of Phase 5 (The Scout)

三层过滤管道：
  Layer 1: SAR 过滤 → 信源权威评分过滤 (剔除低权威/低情绪新闻)
  Layer 2: 三角形校验 → 叙事逻辑校验 (至少 2 个互不相关信源佐证)
  Layer 3: 去重 + 排序 → 按置信度降序输出
"""

import logging
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone

from src.scout_types import MacroTag, NewsItem, NewsSignal, TriangleValidation

logger = logging.getLogger(__name__)

# =========================================================================
# Constants — SAR 权威分级
# =========================================================================

# 官方数据源 (authority = 1.0)
_OFFICIAL_KEYWORDS = [
    "federal reserve", "federalreserve", "fed",
    "bls", "bureau of labor statistics",
    "ecb", "european central bank",
    "treasury", "us treasury",
    "imf", "international monetary fund",
]

# 半官方权威媒体 (authority = 0.8)
_SEMI_KEYWORDS = [
    "reuters", "bloomberg", "wsj", "wall street journal",
    "ft", "financial times", "eia",
    "opec",
]

# 主流媒体 (authority = 0.6)
_MAJOR_MEDIA_KEYWORDS = [
    "cnbc", "yahoo finance", "yahoo",
    "marketwatch", "investopedia", "barron",
    "forbes", "fortune",
]

# 社交媒体 (authority = 0.2)
_SOCIAL_KEYWORDS = [
    "twitter", "x.com", "reddit",
    "social media", "facebook", "telegram",
]

# 未知信源默认值 (authority = 0.4)
_DEFAULT_AUTHORITY = 0.4

# =========================================================================
# 叙事关键词提取映射
# =========================================================================

_NARRATIVE_KEYWORDS: Dict[str, List[str]] = {
    "oil_shortage": ["oil", "crude", "petroleum", "supply", "inventory", "brent", "wti"],
    "inflation_surge": ["inflation", "cpi", "consumer price", "price", "pce", "core inflation"],
    "rate_cut": ["rate cut", "interest rate", "fomc", "monetary policy", "fed", "federal reserve"],
    "recession_fear": ["recession", "gdp", "economic downturn", "slowdown", "contraction"],
    "geopolitical_conflict": ["conflict", "war", "sanction", "geopolitical", "tension", "military"],
    "supply_chain_crisis": ["supply chain", "shortage", "bottleneck", "logistics", "chip"],
}

# =========================================================================
# 宏观类别推断映射
# =========================================================================

_CATEGORY_MAP: Dict[str, str] = {
    "oil_shortage": "commodity",
    "inflation_surge": "inflation",
    "rate_cut": "monetary_policy",
    "recession_fear": "growth",
    "geopolitical_conflict": "geopolitical",
    "supply_chain_crisis": "supply_chain",
}

# =========================================================================
# 三角形校验映射 — 每种叙事需要的证据信源列表
# =========================================================================

NARRATIVE_VALIDATION_MAP: Dict[str, Dict[str, Any]] = {
    "oil_shortage": {
        "required_proofs": ["eia", "opec", "bloomberg", "reuters"],
        "min_proofs_required": 2,
    },
    "inflation_surge": {
        "required_proofs": ["bls", "fed", "bloomberg", "reuters"],
        "min_proofs_required": 2,
    },
    "rate_cut": {
        "required_proofs": ["fed", "bloomberg", "reuters", "wsj"],
        "min_proofs_required": 2,
    },
    "recession_fear": {
        "required_proofs": ["bls", "fed", "bloomberg"],
        "min_proofs_required": 2,
    },
    "geopolitical_conflict": {
        "required_proofs": ["reuters", "bloomberg", "bbc"],
        "min_proofs_required": 2,
    },
    "supply_chain_crisis": {
        "required_proofs": ["bloomberg", "reuters", "wsj"],
        "min_proofs_required": 2,
    },
}

# =========================================================================
# Enums / Data Classes
# =========================================================================

class ValidationStatus(str, Enum):
    """三角形校验状态"""
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"


class AuthorityLevel:
    """SAR 权威等级常量"""
    OFFICIAL = 1.0
    SEMI_OFFICIAL = 0.8
    MAJOR_MEDIA = 0.6
    UNKNOWN = 0.4
    SOCIAL_MEDIA = 0.2


# =========================================================================
# 三角形校验常量 (置信度调整)
# =========================================================================

_CONFIDENCE_BOOST_FACTOR = 1.2       # PASSED 提升 20%
_CONFIDENCE_PENALTY_FACTOR = 0.5     # FAILED 减半
_CONFIDENCE_MAX_CAP = 1.0            # 上限 1.0


# =========================================================================
# SourceGovernor — 信源治理引擎
# =========================================================================

class SourceGovernor:
    """
    信源治理引擎（Layer 0 核心）

    管道流程：
      1. fetch_market_news() → 原始新闻流
      2. _apply_sar_filter() → SAR 权威过滤
      3. _apply_triangle_validation() → 三角形校验
      4. _deduplicate_signals() → 叙事去重
      5. get_top_signals() / signals_to_macro_tags() → 输出

    参数:
      sentiment_collector: SentimentCollector 实例（或 MagicMock）
      min_sar_threshold:  最小权威阈值 (默认 0.3)
      lookback_hours:     新闻回溯窗口 (默认 24)
    """

    def __init__(
        self,
        sentiment_collector: Any = None,
        min_sar_threshold: float = 0.3,
        lookback_hours: int = 24,
    ):
        self._sentiment = sentiment_collector
        self._min_sar = min_sar_threshold
        self._lookback = timedelta(hours=lookback_hours)
        self._last_signals: List[NewsSignal] = []
        self._validation_details: Dict[str, Dict[str, Any]] = {}

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def scan_recent_news(self, category: str = "general") -> List[NewsSignal]:
        """
        执行完整扫描管道：
          拉取新闻 → SAR 过滤 → 三角形校验 → 去重 → 排序
        """
        if not self._sentiment:
            logger.warning("No sentiment_collector available, returning empty")
            return []

        raw_items = self._sentiment.fetch_market_news(category)
        if not raw_items:
            logger.info("No news items returned from collector")
            self._last_signals = []
            return []

        # Layer 1: SAR 过滤
        signals = self._apply_sar_filter(raw_items, max_items=100)
        if not signals:
            self._last_signals = []
            return []

        # Layer 2: 三角形校验
        signals = self._apply_triangle_validation(signals)

        # Layer 3: 去重
        signals = self._deduplicate_signals(signals)

        # 按置信度降序排序
        signals.sort(key=lambda s: s.confidence, reverse=True)

        self._last_signals = signals
        return signals

    def get_top_signals(
        self,
        min_confidence: float = 0.0,
        top_n: int = 5,
    ) -> List[NewsSignal]:
        """获取置信度最高的前 N 个信号，支持置信度下限过滤"""
        filtered = [s for s in self._last_signals if s.confidence >= min_confidence]
        return filtered[:top_n]

    def get_validation_detail(self, narrative: str) -> Optional[Dict[str, Any]]:
        """获取某个叙事的校验详情"""
        return self._validation_details.get(narrative)

    def signals_to_macro_tags(
        self,
        signals: List[NewsSignal],
    ) -> List[MacroTag]:
        """
        将通过三角形校验的 NewsSignal 列表转换为 MacroTag 列表。
        只转换状态为 PASSED 的信号。
        """
        tags: List[MacroTag] = []
        for sig in signals:
            if sig.validation_status != ValidationStatus.PASSED:
                continue
            tag = MacroTag(
                narrative=sig.narrative,
                category=self._infer_category(sig.narrative),
                confidence=sig.confidence,
                related_assets=[],
                source_ids=list(sig.sources),
                source_weights=sum(
                    self._get_authority(src) for src in sig.sources
                ) / max(len(sig.sources), 1),
            )
            tags.append(tag)
        return tags

    # -----------------------------------------------------------------
    # Layer 1: SAR 权威过滤
    # -----------------------------------------------------------------

    def _get_authority(self, source_name: str) -> float:
        """根据信源名称返回 SAR 权威评分。"""
        name_lower = source_name.lower().strip()

        # 检查官方信源
        for kw in _OFFICIAL_KEYWORDS:
            if kw in name_lower:
                return AuthorityLevel.OFFICIAL

        # 检查半官方信源
        for kw in _SEMI_KEYWORDS:
            if kw in name_lower:
                return AuthorityLevel.SEMI_OFFICIAL

        # 检查主流媒体
        for kw in _MAJOR_MEDIA_KEYWORDS:
            if kw in name_lower:
                return AuthorityLevel.MAJOR_MEDIA

        # 检查社交媒体
        for kw in _SOCIAL_KEYWORDS:
            if kw in name_lower:
                return AuthorityLevel.SOCIAL_MEDIA

        return _DEFAULT_AUTHORITY

    def _apply_sar_filter(
        self,
        items: List[NewsItem],
        max_items: int = 100,
    ) -> List[NewsSignal]:
        """
        SAR 过滤：保留 authority >= min_sar 且 composite >= min_sar 的信号。
        composite = (authority + abs(sentiment)) / 2
        """
        signals: List[NewsSignal] = []

        for item in items[:max_items]:
            authority = self._get_authority(item.source)
            sentiment = abs(item.sentiment_score)

            # 复合评分 = 权威度与情绪强度的加权平均
            composite = (authority + sentiment) / 2.0

            if authority < self._min_sar or composite < self._min_sar:
                continue

            # 提取叙事
            narrative = self._extract_narrative(item.title, item.summary)
            if narrative is None:
                continue

            signal = NewsSignal(
                narrative=narrative,
                authority_level=authority,
                sentiment_score=item.sentiment_score,
                confidence=composite,
                sources=[item.source.lower()],
                original_titles=[item.title],
            )
            signals.append(signal)

        return signals

    # -----------------------------------------------------------------
    # Layer 2: 三角形校验
    # -----------------------------------------------------------------

    def _apply_triangle_validation(
        self,
        signals: List[NewsSignal],
    ) -> List[NewsSignal]:
        """
        三角形校验：对每个信号，检查其信源列表是否匹配 NARRATIVE_VALIDATION_MAP 中
        定义的必要 proof 信源。

        规则：
          - 匹配 >= min_proofs_required → PASSED（置信度提升 20%）
          - 匹配 == 0                  → FAILED（置信度减半）
          - 匹配 >= 1 但 < min_proofs   → PARTIAL（置信度不变）
          - 未在映射表中注册的叙事      → PARTIAL（默认保守）
        """
        validated: List[NewsSignal] = []

        for sig in signals:
            mapping = NARRATIVE_VALIDATION_MAP.get(sig.narrative)

            if mapping is None:
                # 未知叙事 → PARTIAL
                sig.validation_status = ValidationStatus.PARTIAL
                sig.validation = TriangleValidation(
                    matched_proofs=[],
                    missing_proofs=[],
                    is_passed=False,
                )
                # 更新校验详情缓存
                self._validation_details[sig.narrative] = {
                    "narrative": sig.narrative,
                    "status": ValidationStatus.PARTIAL.value,
                    "matched_proofs": [],
                    "missing_proofs": [],
                }
                validated.append(sig)
                continue

            required_proofs: List[str] = mapping["required_proofs"]
            min_proofs: int = mapping["min_proofs_required"]

            # 计算匹配的 proof 信源
            matched: List[str] = []
            missing: List[str] = []
            for proof_source in required_proofs:
                found = False
                for signal_source in sig.sources:
                    # 模糊匹配：proof key 在信源名称中
                    if proof_source in signal_source.lower():
                        matched.append(proof_source)
                        found = True
                        break
                if not found:
                    missing.append(proof_source)

            matched_count = len(matched)

            # 判定状态
            if matched_count >= min_proofs:
                sig.validation_status = ValidationStatus.PASSED
                sig.validation = TriangleValidation(
                    matched_proofs=matched,
                    missing_proofs=missing,
                    is_passed=True,
                )
                # 置信度提升
                new_confidence = sig.confidence * _CONFIDENCE_BOOST_FACTOR
                sig.confidence = min(new_confidence, _CONFIDENCE_MAX_CAP)

            elif matched_count == 0:
                sig.validation_status = ValidationStatus.FAILED
                sig.validation = TriangleValidation(
                    matched_proofs=matched,
                    missing_proofs=missing,
                    is_passed=False,
                )
                # 置信度减半
                sig.confidence *= _CONFIDENCE_PENALTY_FACTOR

            else:
                # 1 <= matched_count < min_proofs → PARTIAL
                sig.validation_status = ValidationStatus.PARTIAL
                sig.validation = TriangleValidation(
                    matched_proofs=matched,
                    missing_proofs=missing,
                    is_passed=False,
                )
                # 置信度不变

            # 更新校验详情缓存
            self._validation_details[sig.narrative] = {
                "narrative": sig.narrative,
                "status": sig.validation_status.value,
                "matched_proofs": matched,
                "missing_proofs": missing,
            }

            validated.append(sig)

        return validated

    # -----------------------------------------------------------------
    # Layer 3: 去重 (按叙事合并)
    # -----------------------------------------------------------------

    def _deduplicate_signals(
        self,
        signals: List[NewsSignal],
    ) -> List[NewsSignal]:
        """
        按 narrative 去重合并：
          - 保留最高 confidence 的信号
          - 合并 sources 列表（去重）
          - 合并 original_titles 列表
        """
        narrative_map: Dict[str, NewsSignal] = {}

        for sig in signals:
            existing = narrative_map.get(sig.narrative)
            if existing is None:
                narrative_map[sig.narrative] = sig
            else:
                if sig.confidence > existing.confidence:
                    # Replace with higher-confidence signal, but carry over
                    # all sources and titles from the existing lower-confidence one
                    sig.append_sources(existing.sources)
                    sig.append_titles(existing.original_titles)
                    narrative_map[sig.narrative] = sig
                else:
                    # Keep existing, merge new sources/titles into it
                    existing.append_sources(sig.sources)
                    existing.append_titles(sig.original_titles)

        return list(narrative_map.values())

    # -----------------------------------------------------------------
    # 叙事提取
    # -----------------------------------------------------------------

    def _extract_narrative(
        self,
        title: str,
        summary: str,
    ) -> Optional[str]:
        """
        从标题和摘要中提取叙事关键词。
        返回匹配的叙事名称，无匹配时返回原标题。
        """
        text = f"{title} {summary}".strip()
        if not text:
            return None

        text_lower = text.lower()

        # 检查已知叙事关键词
        for narrative, keywords in _NARRATIVE_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    return narrative

        # 无匹配则返回原标题（fallback）
        return title

    # -----------------------------------------------------------------
    # 类别推断
    # -----------------------------------------------------------------

    def _infer_category(self, narrative: str) -> str:
        """
        从叙事名称推断宏观类别。
        返回 _CATEGORY_MAP 中定义的类别，未知叙事返回 "general"。
        """
        return _CATEGORY_MAP.get(narrative, "general")