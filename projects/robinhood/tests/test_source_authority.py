"""
Tests for config/source_authority.py - 信源权重系统
"""

import sys
sys.path.insert(0, 'e:/AI_Studio_Workspace/projects/robinhood')

import pytest
from config.source_authority import (
    AuthorityTier,
    SOURCE_REGISTRY,
    get_min_corroboration,
    get_required_authority_tier,
    get_sources_by_tier,
    get_sources_by_category,
    get_tier_for_source,
    is_authoritative_enough,
)


class TestAuthorityTier:
    """权威等级枚举测试"""

    def test_tier_values(self):
        assert AuthorityTier.TIER_1.value == 1
        assert AuthorityTier.TIER_2.value == 2
        assert AuthorityTier.TIER_3.value == 3
        assert AuthorityTier.TIER_4.value == 4

    def test_tier_ordering(self):
        """数值越小越权威"""
        assert AuthorityTier.TIER_1 < AuthorityTier.TIER_2
        assert AuthorityTier.TIER_2 < AuthorityTier.TIER_3
        assert AuthorityTier.TIER_3 < AuthorityTier.TIER_4


class TestSourceRegistry:
    """信源注册表完整性测试"""

    def test_registry_not_empty(self):
        assert len(SOURCE_REGISTRY) > 0

    def test_all_sources_have_required_fields(self):
        """每个信源必须有 name, tier, category, feed_type, url, description"""
        for key, entry in SOURCE_REGISTRY.items():
            assert "name" in entry, f"{key} missing 'name'"
            assert "tier" in entry, f"{key} missing 'tier'"
            assert "category" in entry, f"{key} missing 'category'"
            assert "feed_type" in entry, f"{key} missing 'feed_type'"
            assert "url" in entry, f"{key} missing 'url'"
            assert "description" in entry, f"{key} missing 'description'"

    def test_tier_distribution(self):
        """至少每个 TIER 都有信源"""
        for tier in AuthorityTier:
            sources = get_sources_by_tier(tier)
            assert len(sources) > 0, f"No sources for {tier}"

    def test_categories_exist(self):
        """验证几个关键类别存在"""
        categories = set(s["category"] for s in SOURCE_REGISTRY.values())
        assert "central_bank" in categories
        assert "government_agency" in categories
        assert "news_agency" in categories
        assert "social_media" in categories


class TestGetMinCorroboration:
    """最小佐证数阈值测试"""

    def test_tier1_needs_one(self):
        assert get_min_corroboration(AuthorityTier.TIER_1) == 1

    def test_tier2_needs_two(self):
        assert get_min_corroboration(AuthorityTier.TIER_2) == 2

    def test_tier3_needs_two(self):
        assert get_min_corroboration(AuthorityTier.TIER_3) == 2

    def test_tier4_needs_three(self):
        assert get_min_corroboration(AuthorityTier.TIER_4) == 3

    def test_unknown_tier(self):
        """未知等级默认返回 3"""
        class Unknown:
            value = 99
        assert get_min_corroboration(Unknown()) == 3


class TestGetRequiredAuthorityTier:
    """佐证所需最低权威等级测试"""

    def test_tier1_requires_tier1(self):
        assert get_required_authority_tier(AuthorityTier.TIER_1) == AuthorityTier.TIER_1

    def test_tier2_requires_tier2(self):
        assert get_required_authority_tier(AuthorityTier.TIER_2) == AuthorityTier.TIER_2

    def test_tier3_requires_tier2(self):
        assert get_required_authority_tier(AuthorityTier.TIER_3) == AuthorityTier.TIER_2

    def test_tier4_requires_tier3(self):
        assert get_required_authority_tier(AuthorityTier.TIER_4) == AuthorityTier.TIER_3


class TestGetSourcesByTier:
    """按等级筛选测试"""

    def test_tier1_sources(self):
        sources = get_sources_by_tier(AuthorityTier.TIER_1)
        assert "fed" in sources
        assert "bls" in sources
        assert "opec" in sources

    def test_tier3_sources(self):
        sources = get_sources_by_tier(AuthorityTier.TIER_3)
        assert "reuters" in sources
        assert "bloomberg" in sources

    def test_invalid_tier_returns_empty(self):
        """无效等级返回空列表"""
        class Invalid:
            value = 99
        sources = get_sources_by_tier(Invalid())
        assert sources == []


class TestGetSourcesByCategory:
    """按类别筛选测试"""

    def test_central_bank(self):
        sources = get_sources_by_category("central_bank")
        assert "fed" in sources

    def test_government_agency(self):
        sources = get_sources_by_category("government_agency")
        assert "eia" in sources
        assert "bls" in sources
        assert "bea" in sources

    def test_news_agency(self):
        sources = get_sources_by_category("news_agency")
        assert "reuters" in sources
        assert "bloomberg" in sources

    def test_invalid_category(self):
        sources = get_sources_by_category("nonexistent")
        assert sources == []


class TestGetTierForSource:
    """信源等级查询测试"""

    def test_known_source(self):
        assert get_tier_for_source("fed") == AuthorityTier.TIER_1
        assert get_tier_for_source("reuters") == AuthorityTier.TIER_3

    def test_unknown_source(self):
        assert get_tier_for_source("nonexistent") is None

    def test_empty_key(self):
        assert get_tier_for_source("") is None


class TestIsAuthoritativeEnough:
    """三角形校验核心逻辑测试"""

    def test_tier1_single_source(self):
        """TIER_1 单源即可通过"""
        assert is_authoritative_enough(["fed"], AuthorityTier.TIER_2)

    def test_tier2_two_sources(self):
        """TIER_2 需要至少 2 个 TIER_2+ 源"""
        assert is_authoritative_enough(["cftc", "cme"], AuthorityTier.TIER_2)

    def test_tier2_insufficient(self):
        """TIER_2 只有 1 个源不够"""
        assert not is_authoritative_enough(["cftc"], AuthorityTier.TIER_2)

    def test_tier3_two_sources(self):
        """TIER_3 需要 2 个 TIER_2+ 源"""
        assert is_authoritative_enough(["cftc", "cme"], AuthorityTier.TIER_3)

    def test_tier3_mixed_tiers(self):
        """TIER_3 可以由 TIER_1 + TIER_4 组成但 TIER_4 不合格"""
        # TIER_1 可以独立验证
        assert is_authoritative_enough(["fed"], AuthorityTier.TIER_3)

    def test_tier4_three_sources(self):
        """TIER_4 需要 3 个 TIER_3+ 源"""
        assert is_authoritative_enough(
            ["reuters", "bloomberg", "cnbc"], AuthorityTier.TIER_4
        )

    def test_tier4_insufficient_two(self):
        """TIER_4 只有 2 个 TIER_3 源不够"""
        assert not is_authoritative_enough(
            ["reuters", "bloomberg"], AuthorityTier.TIER_4
        )

    def test_empty_sources(self):
        """空信源集合永远不通过"""
        assert not is_authoritative_enough([], AuthorityTier.TIER_1)

    def test_all_unknown_sources(self):
        """全是未知信源不通过"""
        assert not is_authoritative_enough(["unknown1", "unknown2"], AuthorityTier.TIER_2)

    def test_tier1_with_tier4_sources(self):
        """即使只有 TIER_1 一个源也可以通过 TIER_4 校验"""
        assert is_authoritative_enough(["fed"], AuthorityTier.TIER_4)

    def test_mixed_known_unknown(self):
        """混合已知+未知信源，应只统计已知的"""
        assert not is_authoritative_enough(
            ["cftc", "unknown_source"], AuthorityTier.TIER_2
        )

    # ── 实战场景测试 ──

    def test_scenario_oil_shortage_narrrative(self):
        """
        场景：侦测到"石油短缺情绪"
        用 eia (TIER_1) + opec (TIER_1) → 通过（TIER_1 单源即可）
        """
        assert is_authoritative_enough(["eia", "opec"], AuthorityTier.TIER_3)

    def test_scenario_oil_shortage_news_only(self):
        """
        场景：只有新闻情绪 (reuters, bloomberg) 无数据源
        reuters (TIER_3) + bloomberg (TIER_3) 都是 TIER_3 → 需要 TIER_2+ 源佐证 → 不通过
        这正是"三角形校验法则"的核心：新闻机构不能自己验证自己。
        纯新闻情绪无数据支撑应标注为"不可靠"。
        """
        assert not is_authoritative_enough(["reuters", "bloomberg"], AuthorityTier.TIER_3)

    def test_scenario_social_media_rumor(self):
        """
        场景：社交媒体谣言 (seeking_alpha + twitter_finance)
        两个 TIER_4 → TIER_4 需要 3 个 TIER_3+ 源 → 不通过
        """
        assert not is_authoritative_enough(
            ["seeking_alpha", "twitter_finance"], AuthorityTier.TIER_4
        )

    def test_scenario_gold_rally_narrative(self):
        """
        场景："黄金大涨"叙事
        fed (TIER_1) + bls (TIER_1) + reuters (TIER_3) → 通过
        """
        assert is_authoritative_enough(
            ["fed", "bls", "reuters"], AuthorityTier.TIER_2
        )