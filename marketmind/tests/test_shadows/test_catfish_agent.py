"""Tests for Catfish Agent — minority-opinion enforcer."""
import pytest

from marketmind.shadows.catfish_agent import (
    CatfishAgent, CATFISH_CONFIG, CATFISH_SYSTEM_PROMPT, create_catfish_agent
)
from marketmind.shadows.shadow_agent import ShadowDecision
from marketmind.shadows.shadow_state import ShadowConfig
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def catfish_config():
    return ShadowConfig(
        shadow_id="catfish:primary:test_catfish",
        shadow_type="catfish",
        display_name="Test Catfish",
        methodology_prompt=CATFISH_SYSTEM_PROMPT,
        virtual_capital=30000.0,
        temperature=0.8,
        reasoning_effort="low",
    )


@pytest.fixture
def catfish(catfish_config, temp_shadow_db, settings):
    return CatfishAgent(catfish_config, temp_shadow_db, settings)


def make_vote(shadow_id, ticker, direction, confidence=0.5):
    return ShadowDecision(
        shadow_id=shadow_id, shadow_type="expert",
        date="2026-05-11", ticker=ticker, direction=direction,
        confidence=confidence, thesis="test", risk_note="test",
    )


class TestCatfishConsensusDetection:
    def test_80_percent_consensus_triggers(self, catfish):
        """>=80% agreement triggers catfish."""
        votes = [
            make_vote("s1", "SPY", "long"),
            make_vote("s2", "SPY", "long"),
            make_vote("s3", "SPY", "long"),
            make_vote("s4", "SPY", "long"),  # 4/4 = 100%
        ]
        triggered, pct, direction = catfish.check_consensus(votes, "SPY")
        assert triggered is True
        assert pct == 1.0
        assert direction == "long"

    def test_75_percent_no_trigger(self, catfish):
        """<80% agreement does NOT trigger catfish."""
        votes = [
            make_vote("s1", "SPY", "long"),
            make_vote("s2", "SPY", "long"),
            make_vote("s3", "SPY", "long"),   # 3/4 = 75%
            make_vote("s4", "SPY", "short"),
        ]
        triggered, pct, _ = catfish.check_consensus(votes, "SPY")
        assert triggered is False
        assert pct == 0.75

    def test_fewer_than_3_votes_no_trigger(self, catfish):
        """Need >=3 non-abstain votes to check consensus."""
        votes = [
            make_vote("s1", "SPY", "long"),
            make_vote("s2", "SPY", "long"),  # only 2
        ]
        triggered, pct, _ = catfish.check_consensus(votes, "SPY")
        assert triggered is False
        assert pct == 0.0

    def test_abstain_votes_excluded(self, catfish):
        """Abstain votes are excluded from consensus calculation."""
        votes = [
            make_vote("s1", "SPY", "long"),
            make_vote("s2", "SPY", "long"),
            make_vote("s3", "SPY", "long"),
            make_vote("s4", "SPY", "long"),
            make_vote("s5", "SPY", "abstain"),
        ]
        triggered, pct, _ = catfish.check_consensus(votes, "SPY")
        assert triggered is True
        assert pct == 1.0  # 4/4 non-abstain = 100%


class TestCatfishAgent:
    def test_catfish_uses_high_temperature(self, catfish):
        assert catfish.config.temperature == 0.8

    @pytest.mark.asyncio
    async def test_catfish_analyze_without_trigger(self, catfish):
        output = await catfish._analyze([], {})
        assert len(output.decisions) == 0
        assert "NO_CONSENSUS_DETECTED" in str(output.insights)

    @pytest.mark.asyncio
    async def test_catfish_analyze_with_trigger(self, catfish):
        from unittest.mock import AsyncMock, patch
        mock_result = {
            "content": "VOTE_START\nticker: SPY\ndirection: short\nconfidence: 0.5\nthesis: counter argument\nrisk_note: adverse selection\nVOTE_END",
            "latency_ms": 450
        }
        market_data = {
            "catfish_trigger_ticker": "SPY",
            "catfish_trigger_direction": "long",
            "catfish_trigger_agreement_pct": 0.85,
        }
        with patch("marketmind.gateway.async_client.chat_with_integrity", new_callable=AsyncMock, return_value=mock_result):
            output = await catfish._analyze([{"headline": "Test"}], market_data)
        assert len(output.decisions) == 1
        assert output.decisions[0].direction == "short"  # opposes long consensus
        assert output.decisions[0].ticker == "SPY"

    def test_catfish_not_valid_counter(self, catfish):
        """Catfish methodology requires NO_VALID_COUNTER response when no legitimate argument."""
        prompt = CATFISH_SYSTEM_PROMPT
        assert "NO_VALID_COUNTER" in prompt
        assert "NEVER fabricate" in prompt


def test_create_catfish_factory(temp_shadow_db):
    settings = ShadowSettings()
    agent = create_catfish_agent(temp_shadow_db, settings)
    assert isinstance(agent, CatfishAgent)
    assert agent.config.temperature == 0.8
