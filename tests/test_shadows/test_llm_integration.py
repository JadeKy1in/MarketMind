"""Phase C: LLM integration cross-cutting tests."""
import pytest
from unittest.mock import AsyncMock, patch

from marketmind.shadows.shadow_state import ShadowConfig
from marketmind.shadows.shadow_agent import ShadowAgent
from marketmind.config.settings import ShadowSettings


@pytest.mark.asyncio
async def test_shadow_factory_creates_correct_type(temp_shadow_db):
    """create_shadow_agent 为每种类型创建正确的子类"""
    from marketmind.shadows.shadow_agent import create_shadow_agent
    from marketmind.shadows.expert_shadows import ExpertShadow
    from marketmind.shadows.daredevil_shadows import DaredevilShadow
    from marketmind.shadows.catfish_agent import CatfishAgent
    from marketmind.shadows.missed_path import MissedPathAgent

    settings = ShadowSettings()

    expert = create_shadow_agent(ShadowConfig(
        shadow_id="test:expert", shadow_type="expert", display_name="E",
        methodology_prompt="test", virtual_capital=10000.0,
    ), temp_shadow_db, settings)
    assert isinstance(expert, ExpertShadow)

    daredevil = create_shadow_agent(ShadowConfig(
        shadow_id="test:daredevil", shadow_type="daredevil", display_name="D",
        methodology_prompt="test", virtual_capital=10000.0,
    ), temp_shadow_db, settings)
    assert isinstance(daredevil, DaredevilShadow)

    # Catfish deprecated (Phase 0) — now creates base ShadowAgent
    catfish = create_shadow_agent(ShadowConfig(
        shadow_id="test:catfish", shadow_type="catfish", display_name="C",
        methodology_prompt="test", virtual_capital=10000.0,
    ), temp_shadow_db, settings)
    assert isinstance(catfish, ShadowAgent)  # deprecated type → base agent

    missed = create_shadow_agent(ShadowConfig(
        shadow_id="test:missed", shadow_type="missed_path", display_name="M",
        methodology_prompt="test", virtual_capital=0.0,
    ), temp_shadow_db, settings)
    assert isinstance(missed, MissedPathAgent)


@pytest.mark.asyncio
async def test_shadow_llm_call_includes_caller_agent(temp_shadow_db):
    """chat_with_integrity 收到正确的 caller_agent 参数"""
    from marketmind.shadows.shadow_agent import ShadowAgent
    from marketmind.shadows.shadow_state import ShadowConfig

    config = ShadowConfig(
        shadow_id="expert:gold:test_caller", shadow_type="expert",
        display_name="Caller Test", methodology_prompt="Expert prompt.",
        virtual_capital=50000.0, domain="gold",
    )
    agent = ShadowAgent(config, temp_shadow_db, ShadowSettings())

    mock_result = {
        "content": (
            "VOTE_START\n"
            "ticker: GLD\ndirection: long\nconfidence: 0.5\n"
            "thesis: t\nrisk_note: r\n"
            "VOTE_END"
        ),
        "latency_ms": 200,
    }

    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result) as mock_chat:
        await agent._analyze([{"headline": "Test"}], {})

        # 验证caller_agent参数
        call_kwargs = mock_chat.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs[1] if call_kwargs[1] else {}
        assert "shadow:expert:Caller Test" in str(kwargs.get("caller_agent", ""))


@pytest.mark.asyncio
async def test_all_shadow_types_analyze_without_error(temp_shadow_db):
    """所有shadow类型在mock LLM下都能正常完成_analyze()"""
    from marketmind.shadows.shadow_agent import create_shadow_agent
    from marketmind.shadows.expert_shadows import ExpertShadow
    from marketmind.shadows.daredevil_shadows import DaredevilShadow
    from marketmind.shadows.catfish_agent import CatfishAgent

    settings = ShadowSettings()
    mock_result = {
        "content": (
            "VOTE_START\n"
            "ticker: SPY\ndirection: long\nconfidence: 0.6\n"
            "thesis: t\nrisk_note: r\n"
            "VOTE_END"
        ),
        "latency_ms": 300,
    }

    configs = [
        ShadowConfig(shadow_id="expert:macro:test_e2e", shadow_type="expert",
                     display_name="Test Expert", methodology_prompt="Expert.",
                     virtual_capital=50000.0, domain="macro"),
        ShadowConfig(shadow_id="daredevil:event:test_e2e", shadow_type="daredevil",
                     display_name="Test Daredevil", methodology_prompt="Daredevil.",
                     virtual_capital=25000.0),
    ]

    for config in configs:
        agent = create_shadow_agent(config, temp_shadow_db, settings)
        with patch("marketmind.gateway.async_client.chat_with_integrity",
                   new_callable=AsyncMock, return_value=mock_result):
            output = await agent._analyze([{"headline": "Test headline"}], {})
            assert output is not None
            assert output.shadow_id == config.shadow_id
