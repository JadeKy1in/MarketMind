"""
Tests for SourceGovernor — 信源治理引擎 (Phase 5: The Scout)
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from src.scout_types import MacroTag, NewsSignal, TriangleValidation
from src.source_governor import (
    SourceGovernor,
    ValidationStatus,
    AuthorityLevel,
    NARRATIVE_VALIDATION_MAP,
)
# Local NewsItem dataclass — sentiment_collector.py no longer exports it
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NewsItem:
    """Simple news item structure (local replica for source_governor tests)."""
    title: str = ""
    source: str = ""
    publish_time: str = ""
    summary: str = ""
    sentiment_score: float = 0.0


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def mock_sentiment():
    """Mock SentimentCollector that returns controlled news items."""
    collector = MagicMock()
    collector.fetch_market_news.return_value = [
        NewsItem(
            title="Fed Signals Potential Rate Cut in September",
            source="Reuters",
            publish_time="2026-05-05T08:00:00Z",
            summary="Federal Reserve Chair indicates possible rate reduction",
            sentiment_score=0.6,
        ),
        NewsItem(
            title="Oil Prices Surge on Supply Concerns",
            source="Bloomberg",
            publish_time="2026-05-05T07:30:00Z",
            summary="Brent crude rises 3% amid production cuts",
            sentiment_score=-0.4,  # negative for bullish oil = bearish for economy
        ),
        NewsItem(
            title="Rumors of Recession Circulating on Social Media",
            source="Twitter",
            publish_time="2026-05-05T06:00:00Z",
            summary="Speculative posts about economic downturn gaining traction",
            sentiment_score=-0.5,
        ),
        NewsItem(
            title="Tech Stocks Rally on Earnings Optimism",
            source="Yahoo Finance",
            publish_time="2026-05-05T05:00:00Z",
            summary="Major tech companies beat earnings expectations",
            sentiment_score=0.8,
        ),
        NewsItem(
            title="NFP Release Shows Strong Job Growth",
            source="BLS",
            publish_time="2026-05-05T04:00:00Z",
            summary="Non-farm payrolls increased by 275K, beating expectations",
            sentiment_score=0.7,
        ),
    ]
    return collector


@pytest.fixture
def governor(mock_sentiment):
    """Standard SourceGovernor instance with mock sentiment."""
    return SourceGovernor(
        sentiment_collector=mock_sentiment,
        min_sar_threshold=0.3,
        lookback_hours=24,
    )


# =========================================================================
# SAR Filter Tests
# =========================================================================

class TestSARFilter:
    """信源权重过滤测试"""

    def test_get_authority_official(self, governor):
        """官方数据源应该获得最高权重 1.0."""
        assert governor._get_authority("Federal Reserve") == 1.0
        assert governor._get_authority("BLS") == 1.0
        assert governor._get_authority("ECB") == 1.0

    def test_get_authority_semi_official(self, governor):
        """半官方信源应该获得 0.8."""
        assert governor._get_authority("Reuters") == 0.8
        assert governor._get_authority("Bloomberg") == 0.8
        assert governor._get_authority("WSJ") == 0.8

    def test_get_authority_major_media(self, governor):
        """主流媒体应该获得 0.6."""
        assert governor._get_authority("CNBC") == 0.6
        assert governor._get_authority("Yahoo Finance") == 0.6

    def test_get_authority_social_media(self, governor):
        """社交媒体应该获得最低 0.2."""
        assert governor._get_authority("Twitter") == 0.2
        assert governor._get_authority("Reddit") == 0.2

    def test_get_authority_unknown(self, governor):
        """未知信源应该获得默认 0.4."""
        assert governor._get_authority("SomeRandomBlog") == 0.4

    def test_apply_sar_filter_filters_low_authority(self, governor):
        """低权威 + 低情绪的新闻应该被过滤."""
        raw = [
            NewsItem(
                title="Random noise about stocks",
                source="UnknownBlog",
                publish_time="2026-05-05T00:00:00Z",
                summary="No meaningful content",
                sentiment_score=0.1,
            ),
        ]
        signals = governor._apply_sar_filter(raw, max_items=100)
        assert len(signals) == 0  # 应该被过滤

    def test_apply_sar_filter_keeps_high_authority(self, governor):
        """高权威信源的新闻应该保留."""
        raw = [
            NewsItem(
                title="Fed Holds Rates Steady",
                source="Reuters",
                publish_time="2026-05-05T00:00:00Z",
                summary="Fed maintains current interest rate policy",
                sentiment_score=0.3,
            ),
        ]
        signals = governor._apply_sar_filter(raw, max_items=100)
        assert len(signals) == 1
        assert signals[0].sources == ["reuters"]

    def test_apply_sar_filter_updates_authority_level(self, governor):
        """信号应该保留权威等级."""
        raw = [
            NewsItem(
                title="Crude Oil Inventory Drops Sharply",
                source="EIA",
                publish_time="2026-05-05T00:00:00Z",
                summary="EIA reports significant draw in crude stocks",
                sentiment_score=0.5,
            ),
        ]
        signals = governor._apply_sar_filter(raw, max_items=100)
        assert len(signals) == 1
        assert signals[0].authority_level == 0.8  # EIA matches semi_keywords


# =========================================================================
# Triangle Validation Tests
# =========================================================================

class TestTriangleValidation:
    """三角形校验逻辑测试"""

    def test_validation_passed_with_sufficient_proofs(self, governor):
        """足够的 proof 匹配应该标记为 PASSED."""
        signal = NewsSignal(
            narrative="oil_shortage",
            authority_level=0.8,
            sentiment_score=-0.4,
            confidence=0.6,
            sources=["eia", "bloomberg"],
            original_titles=["Oil Prices Surge"],
        )
        result = governor._apply_triangle_validation([signal])
        assert len(result) == 1
        assert result[0].validation_status == ValidationStatus.PASSED
        assert result[0].validation.is_passed is True

    def test_validation_failed_without_proofs(self, governor):
        """没有 proof 匹配应该标记为 FAILED."""
        signal = NewsSignal(
            narrative="oil_shortage",
            authority_level=0.2,
            sentiment_score=-0.5,
            confidence=0.3,
            sources=["twitter", "reddit"],
            original_titles=["Oil prices might go up"],
        )
        result = governor._apply_triangle_validation([signal])
        assert len(result) == 1
        assert result[0].validation_status == ValidationStatus.FAILED
        assert result[0].validation.is_passed is False

    def test_validation_partial_with_some_proofs(self, governor):
        """部分 proof 匹配应该标记为 PARTIAL."""
        signal = NewsSignal(
            narrative="recession_fear",
            authority_level=0.5,
            sentiment_score=-0.6,
            confidence=0.5,
            sources=["bls"],  # Only 1 of 3 required proofs
            original_titles=["Recession fears growing"],
        )
        result = governor._apply_triangle_validation([signal])
        assert len(result) == 1
        assert result[0].validation_status == ValidationStatus.PARTIAL
        assert result[0].validation.is_passed is False

    def test_unknown_narrative_partial(self, governor):
        """未在映射表中定义的叙事应该标记为 PARTIAL."""
        signal = NewsSignal(
            narrative="crypto_market_boom",
            authority_level=0.6,
            sentiment_score=0.7,
            confidence=0.6,
            sources=["cnbc"],
            original_titles=["Crypto rally continues"],
        )
        result = governor._apply_triangle_validation([signal])
        assert len(result) == 1
        assert result[0].validation_status == ValidationStatus.PARTIAL

    def test_passed_validation_boosts_confidence(self, governor):
        """通过三角形校验应该提升置信度."""
        signal = NewsSignal(
            narrative="oil_shortage",
            authority_level=0.8,
            sentiment_score=-0.4,
            confidence=0.5,
            sources=["eia", "opec"],
            original_titles=["Oil shortage warning"],
        )
        result = governor._apply_triangle_validation([signal])
        assert result[0].confidence > 0.5

    def test_failed_validation_penalizes_confidence(self, governor):
        """未通过校验应该大幅降低置信度."""
        signal = NewsSignal(
            narrative="oil_shortage",
            authority_level=0.2,
            sentiment_score=-0.5,
            confidence=0.5,
            sources=["twitter"],
            original_titles=["Oil shortage rumor"],
        )
        result = governor._apply_triangle_validation([signal])
        assert result[0].confidence < 0.5


# =========================================================================
# Deduplication Tests
# =========================================================================

class TestDeduplication:
    """信号去重测试"""

    def test_deduplicate_identical_narratives(self, governor):
        """相同的叙事应该合并为一个信号."""
        signals = [
            NewsSignal(
                narrative="oil_shortage", authority_level=0.6,
                sentiment_score=-0.4, confidence=0.5,
                sources=["bloomberg"], original_titles=["Oil warning 1"],
            ),
            NewsSignal(
                narrative="oil_shortage", authority_level=0.8,
                sentiment_score=-0.4, confidence=0.7,
                sources=["eia"], original_titles=["Oil warning 2"],
            ),
        ]
        deduped = governor._deduplicate_signals(signals)
        assert len(deduped) == 1
        # 应该取最高 confidence
        assert deduped[0].confidence == 0.7
        # sources 应该合并
        assert "eia" in deduped[0].sources
        assert "bloomberg" in deduped[0].sources

    def test_deduplicate_unique_narratives(self, governor):
        """不同的叙事不应该合并."""
        signals = [
            NewsSignal(
                narrative="oil_shortage", authority_level=0.6,
                sentiment_score=-0.4, confidence=0.5,
                sources=["bloomberg"], original_titles=["Oil"],
            ),
            NewsSignal(
                narrative="rate_cut", authority_level=0.8,
                sentiment_score=0.3, confidence=0.6,
                sources=["reuters"], original_titles=["Fed cut"],
            ),
        ]
        deduped = governor._deduplicate_signals(signals)
        assert len(deduped) == 2


# =========================================================================
# Full Pipeline Tests
# =========================================================================

class TestFullPipeline:
    """完整扫描管道的端到端测试"""

    def test_scan_recent_news_returns_signals(self, governor):
        """scan_recent_news 应该返回 NewsSignal 列表."""
        signals = governor.scan_recent_news("general")
        assert isinstance(signals, list)
        if len(signals) > 0:
            assert hasattr(signals[0], "narrative")
            assert hasattr(signals[0], "confidence")

    def test_scan_recent_news_sorts_by_confidence(self, governor):
        """返回的信号应该按置信度降序排列."""
        signals = governor.scan_recent_news("general")
        for i in range(len(signals) - 1):
            assert signals[i].confidence >= signals[i + 1].confidence

    def test_scan_recent_news_without_sentiment(self):
        """没有 SentimentCollector 时应该返回空."""
        empty_gov = SourceGovernor(sentiment_collector=None)
        signals = empty_gov.scan_recent_news()
        assert signals == []

    def test_empty_news_feed(self, governor):
        """空新闻流应该返回空列表."""
        governor._sentiment.fetch_market_news.return_value = []
        signals = governor.scan_recent_news()
        assert signals == []

    def test_get_top_signals_returns_top_n(self, governor):
        """get_top_signals 应该返回置信度最高的前 N 个."""
        # 先执行扫描
        governor.scan_recent_news()
        top = governor.get_top_signals(min_confidence=0.0, top_n=3)
        assert len(top) <= 3
        for s in top:
            assert s.confidence >= 0.0

    def test_get_top_signals_confidence_filter(self, governor):
        """get_top_signals 应该根据 min_confidence 过滤."""
        governor.scan_recent_news()
        high_confidence = governor.get_top_signals(min_confidence=0.8, top_n=10)
        for s in high_confidence:
            assert s.confidence >= 0.8

    def test_get_validation_detail_found(self, governor):
        """get_validation_detail 应该返回存在的叙事详情."""
        governor.scan_recent_news()
        # 使用第一个信号的叙事
        if governor._last_signals:
            narrative = governor._last_signals[0].narrative
            detail = governor.get_validation_detail(narrative)
            assert detail is not None
            assert detail["narrative"] == narrative

    def test_get_validation_detail_not_found(self, governor):
        """get_validation_detail 对不存在的叙事应该返回 None."""
        governor.scan_recent_news()
        detail = governor.get_validation_detail("nonexistent_narrative_xyz")
        assert detail is None


# =========================================================================
# MacroTag Conversion Tests
# =========================================================================

class TestMacroTagConversion:
    """signals_to_macro_tags 转换测试"""

    def test_converts_only_passed_signals(self):
        """只有 PASSED 的信号应该转换为 MacroTag."""
        governor = SourceGovernor(sentiment_collector=None)
        signals = [
            NewsSignal(
                narrative="oil_shortage", authority_level=0.8,
                sentiment_score=-0.4, confidence=0.7,
                sources=["eia"], original_titles=["Oil"],
                validation_status=ValidationStatus.PASSED,
                validation=TriangleValidation(is_passed=True),
            ),
            NewsSignal(
                narrative="recession_fear", authority_level=0.5,
                sentiment_score=-0.5, confidence=0.3,
                sources=["twitter"], original_titles=["Recession"],
                validation_status=ValidationStatus.FAILED,
                validation=TriangleValidation(is_passed=False),
            ),
        ]
        tags = governor.signals_to_macro_tags(signals)
        assert len(tags) == 1
        assert tags[0].narrative == "oil_shortage"

    def test_macro_tag_contains_confidence(self):
        """MacroTag 应该包含治理后的置信度."""
        governor = SourceGovernor(sentiment_collector=None)
        signals = [
            NewsSignal(
                narrative="rate_cut", authority_level=1.0,
                sentiment_score=0.6, confidence=0.9,
                sources=["fed"], original_titles=["Fed cut"],
                validation_status=ValidationStatus.PASSED,
                validation=TriangleValidation(is_passed=True),
            ),
        ]
        tags = governor.signals_to_macro_tags(signals)
        assert len(tags) == 1
        assert tags[0].confidence > 0.8


# =========================================================================
# Narrative Extraction Tests
# =========================================================================

class TestNarrativeExtraction:
    """叙事关键词提取测试"""

    def test_extract_known_narrative_oil(self, governor):
        """应该正确提取已知叙事 'oil_shortage'."""
        result = governor._extract_narrative(
            "Oil prices surge on supply concerns",
            "Crude oil inventories drop",
        )
        assert result == "oil_shortage"

    def test_extract_known_narrative_inflation(self, governor):
        """应该正确提取已知叙事 'inflation_surge'."""
        result = governor._extract_narrative(
            "Inflation surge worries investors",
            "CPI data shows accelerating prices",
        )
        assert result == "inflation_surge"

    def test_extract_unknown_narrative_fallback(self, governor):
        """没有匹配的已知叙事时应该 fallback 到 title."""
        result = governor._extract_narrative(
            "Bitcoin Reaches New All-Time High",
            "Cryptocurrency market cap surpasses $3 trillion",
        )
        assert result == "Bitcoin Reaches New All-Time High"

    def test_extract_narrative_empty_input(self, governor):
        """空输入应该返回 None."""
        result = governor._extract_narrative("", "")
        assert result is None


# =========================================================================
# Category Inference Tests
# =========================================================================

class TestCategoryInference:
    """宏观类别推断测试"""

    def test_infer_category_oil(self, governor):
        assert governor._infer_category("oil_shortage") == "commodity"

    def test_infer_category_rate(self, governor):
        assert governor._infer_category("rate_cut") == "monetary_policy"

    def test_infer_category_recession(self, governor):
        assert governor._infer_category("recession_fear") == "growth"

    def test_infer_category_geopolitical(self, governor):
        assert governor._infer_category("geopolitical_conflict") == "geopolitical"

    def test_infer_category_supply_chain(self, governor):
        assert governor._infer_category("supply_chain_crisis") == "supply_chain"

    def test_infer_category_general(self, governor):
        assert governor._infer_category("crypto_boom") == "general"


# =========================================================================
# Edge Case Tests
# =========================================================================

class TestEdgeCases:
    """边界和异常情况测试"""

    def test_very_low_authority_source_gets_filtered(self):
        """超低权威信源即使情绪高也应该被过滤."""
        collector = MagicMock()
        collector.fetch_market_news.return_value = [
            NewsItem(
                title="Major market move coming",
                source="UnknownTrollBlog",
                publish_time="2026-05-05T00:00:00Z",
                summary="Trust me bro",
                sentiment_score=0.9,
            ),
        ]
        gov = SourceGovernor(sentiment_collector=collector, min_sar_threshold=0.5)
        signals = gov.scan_recent_news()
        # authority < 0.5 → 应该被过滤
        assert len(signals) == 0

    def test_lookback_hours_config(self):
        """lookback_hours 配置应该生效."""
        gov = SourceGovernor(
            sentiment_collector=MagicMock(),
            lookback_hours=48,
        )
        assert gov._lookback.total_seconds() == 172800  # 48 * 3600

    def test_multiple_sources_merged_correctly(self, governor):
        """多个信源报告同一事件时应该正确合并."""
        raw = [
            NewsItem(
                title="Oil shortage warning from EIA",
                source="EIA",
                publish_time="2026-05-05T00:00:00Z",
                summary="EIA reports low inventory",
                sentiment_score=0.5,
            ),
            NewsItem(
                title="Oil shortage confirmed by OPEC",
                source="OPEC",
                publish_time="2026-05-05T01:00:00Z",
                summary="OPEC confirms production cuts",
                sentiment_score=0.4,
            ),
        ]
        collector = MagicMock()
        collector.fetch_market_news.return_value = raw
        gov = SourceGovernor(sentiment_collector=collector)
        signals = gov.scan_recent_news()

        # 只期望 1 个去重后的 oil_shortage 信号
        oil_signals = [s for s in signals if "oil" in s.narrative.lower()]
        assert len(oil_signals) <= 1
        if oil_signals:
            # 多个 source 应该合并
            assert len(oil_signals[0].sources) >= 2