"""Tests for ExpertShadow and factory."""
import pytest
from unittest.mock import AsyncMock, patch

from marketmind.shadows.expert_shadows import (
    ExpertShadow, create_expert_shadows, EXPERT_SHADOW_CONFIGS
)
from marketmind.shadows.shadow_state import ShadowConfig
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def expert_config():
    return ShadowConfig(
        shadow_id="expert:gold:test_bug",
        shadow_type="expert",
        display_name="Test Gold Bug",
        methodology_prompt="You are a gold expert.",
        virtual_capital=50000.0,
        domain="gold",
    )


@pytest.fixture
def expert(expert_config, temp_shadow_db, settings):
    return ExpertShadow(expert_config, temp_shadow_db, settings)


class TestExpertShadow:
    @pytest.mark.asyncio
    async def test_expert_produces_analysis_output(self, expert):
        news = [{"headline": "Gold hits new high on rate cut hopes"}]
        output = await expert.run_daily_analysis(news, {})
        assert output.shadow_id == "expert:gold:test_bug"
        assert output.date is not None

    @pytest.mark.asyncio
    async def test_expert_filters_news_by_domain(self, expert):
        news = [
            {"headline": "Gold hits new high"},
            {"headline": "Oil prices crash on OPEC decision"},
            {"headline": "Tech stocks rally on AI earnings"},
            {"headline": "Gold ETF inflows surge 5%"},
        ]
        filtered = expert._filter_news_by_domain(news)
        assert len(filtered) >= 2
        gold_news = [n for n in filtered if "gold" in str(n.get("headline", "")).lower()]
        assert len(gold_news) >= 2

    @pytest.mark.asyncio
    async def test_macro_expert_sees_all_news(self):
        """Macro expert should not filter news."""
        config = ShadowConfig(
            shadow_id="expert:macro:test_macro",
            shadow_type="expert",
            display_name="Test Macro",
            methodology_prompt="You are a macro expert.",
            virtual_capital=60000.0,
            domain="macro",
        )
        from marketmind.shadows.expert_shadows import ExpertShadow
        from marketmind.config.settings import ShadowSettings
        import tempfile
        from pathlib import Path
        from marketmind.shadows.shadow_state import ShadowStateDB

        with tempfile.TemporaryDirectory() as td:
            db = ShadowStateDB(str(Path(td) / "test.db"))
            db.init_schema()
            macro = ExpertShadow(config, db, ShadowSettings())
            news = [{"headline": "Gold"}, {"headline": "Oil"}, {"headline": "Tech"}]
            filtered = macro._filter_news_by_domain(news)
            assert len(filtered) == 3
            db.close()

    def test_parse_votes_empty_output(self, expert):
        votes = expert._parse_votes("No signal today.")
        assert len(votes) == 0

    def test_parse_votes_single_vote(self, expert):
        text = """VOTE_START
ticker: GLD
direction: long
confidence: 0.75
thesis: Real rates falling support gold rally
risk_note: DXY strength could cap upside
VOTE_END"""
        votes = expert._parse_votes(text)
        assert len(votes) == 1
        assert votes[0].ticker == "GLD"
        assert votes[0].direction == "long"
        assert votes[0].confidence == 0.75
        assert votes[0].emergency_flag is False

    def test_parse_votes_emergency_flag(self, expert):
        text = """VOTE_START
ticker: SPY
direction: short
confidence: 0.90
thesis: Credit event risk elevated
risk_note: Central bank intervention possible
VOTE_END"""
        votes = expert._parse_votes(text)
        assert len(votes) == 1
        assert votes[0].emergency_flag is True


def test_all_15_configs_unique_ids():
    ids = [c.shadow_id for c in EXPERT_SHADOW_CONFIGS]
    assert len(ids) == len(set(ids)) == 15


def test_all_15_configs_valid_domains():
    domains = {c.domain for c in EXPERT_SHADOW_CONFIGS}
    expected = {"gold", "crypto", "energy", "bonds", "volatility", "emerging",
                "tech", "financials", "healthcare", "consumer", "industrials",
                "metals", "real_estate", "fx", "macro"}
    assert domains == expected


def test_factory_creates_15_shadows(temp_shadow_db):
    """Factory creates 15 shadows without errors."""
    settings = ShadowSettings()
    shadows = create_expert_shadows(temp_shadow_db, settings)
    assert len(shadows) == 15
    assert all(isinstance(s, ExpertShadow) for s in shadows)
    visible = temp_shadow_db.get_visible_shadows()
    assert len(visible) == 15


# ── C.7 LLM integration tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_expert_analyze_with_mock_llm_produces_votes(temp_shadow_db):
    """ExpertShadow._analyze() 调用 mock LLM 并正确解析投票"""
    from marketmind.shadows.expert_shadows import ExpertShadow
    from marketmind.shadows.shadow_state import ShadowConfig

    config = ShadowConfig(
        shadow_id="expert:gold:test_llm", shadow_type="expert",
        display_name="Test Gold LLM", methodology_prompt="You are a gold expert.",
        virtual_capital=50000.0, domain="gold", temperature=0.3,
    )
    agent = ExpertShadow(config, temp_shadow_db, ShadowSettings())

    mock_result = {
        "content": (
            "INSIGHT: Gold looks bullish\n"
            "VOTE_START\n"
            "ticker: GLD\ndirection: long\nconfidence: 0.75\n"
            "thesis: Central bank buying supports prices\n"
            "risk_note: USD strength could reverse\n"
            "VOTE_END\n"
            "VOTE_START\n"
            "ticker: GDX\ndirection: short\nconfidence: 0.45\n"
            "thesis: Mining costs rising\n"
            "risk_note: Gold price may offset costs\n"
            "VOTE_END"
        ),
        "latency_ms": 600,
    }

    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        output = await agent._analyze(
            [{"headline": "Gold hits new high as central banks stockpile"}], {}
        )

    assert len(output.votes) == 2
    assert output.votes[0].ticker == "GLD"
    assert output.votes[0].direction == "long"
    assert output.votes[0].confidence == 0.75
    assert output.votes[1].ticker == "GDX"
    assert output.votes[1].direction == "short"


@pytest.mark.asyncio
async def test_expert_domain_filtering_applied(temp_shadow_db):
    """领域过滤生效：无关新闻被排除"""
    from marketmind.shadows.expert_shadows import ExpertShadow
    from marketmind.shadows.shadow_state import ShadowConfig

    config = ShadowConfig(
        shadow_id="expert:gold:test_filter", shadow_type="expert",
        display_name="Test Filter", methodology_prompt="Gold expert.",
        virtual_capital=50000.0, domain="gold", temperature=0.3,
    )
    agent = ExpertShadow(config, temp_shadow_db, ShadowSettings())

    news = [
        {"headline": "Gold prices surge on safe-haven demand"},
        {"headline": "Bitcoin drops 5% as crypto selloff intensifies"},
        {"headline": "Oil prices steady after OPEC meeting"},
        {"headline": "Silver follows gold higher in precious metals rally"},
    ]

    # 验证过滤逻辑
    filtered = agent._filter_news_by_domain(news)
    headlines = [item.get("headline", "") for item in filtered]
    assert any("Gold" in h for h in headlines)
    assert any("Silver" in h for h in headlines)
    # Bitcoin和Oil不应出现在黄金领域的过滤结果中
    bitcoin_items = [h for h in headlines if "Bitcoin" in h]
    assert len(bitcoin_items) == 0


@pytest.mark.asyncio
async def test_expert_empty_llm_response_graceful(temp_shadow_db):
    """LLM返回空内容 -> 不崩溃，不产生投票"""
    from marketmind.shadows.expert_shadows import ExpertShadow
    from marketmind.shadows.shadow_state import ShadowConfig

    config = ShadowConfig(
        shadow_id="expert:gold:test_empty", shadow_type="expert",
        display_name="Test Empty", methodology_prompt="Gold expert.",
        virtual_capital=50000.0, domain="gold", temperature=0.3,
    )
    agent = ExpertShadow(config, temp_shadow_db, ShadowSettings())

    mock_result = {"content": "", "latency_ms": 100}
    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        output = await agent._analyze([{"headline": "Gold steady"}], {})

    assert len(output.votes) == 0
    assert output.quota_used == 0  # 空内容不消耗配额
