"""Tests for Layer 2 fundamental analysis engine."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from projects.marketmind.pipeline.layer2_fundamental import (
    Layer2Result, analyze_layer2, _parse_layer2_response, _build_context,
)
from projects.marketmind.pipeline.layer1_narrative import Layer1Result


def _sample_l1():
    return Layer1Result(
        event_grade="B",
        surprise_level="high",
        market_size="big",
        matrix_quadrant="core_opportunity",
        price_in_score=0.30,
        cascade_rank=2,
        cascade_hub=True,
        sentiment_direction="risk_on",
        sentiment_intensity=0.75,
        sentiment_vs_attention="high_sentiment",
        expert_signals=[{"expert": "Druckenmiller", "position": "long tech", "historical_accuracy": 0.72}],
        institutional_surprise="Fed dovish pivot faster than expected",
        key_characters=[{"name": "Powell", "capability": "high", "will": "moderate", "market_trust": "high"}],
        tail_risk_flags=[],
    )


def test_parse_layer2_response_clean_json():
    data = json.dumps({
        "macro_quadrant": "expansion", "macro_direction": "risk_on",
        "preferred_assets": ["equities", "crypto"], "sector_shortlist": ["Tech", "Financials"],
        "sector_momentum": {"Tech": "accelerating"}, "factor_scores": {"AAPL": 0.85},
        "ticker_candidates": ["AAPL", "MSFT"], "ticker_weights": {"AAPL": 0.3},
        "tier_challenges": ["L2.2: bonds looking attractive too"],
    })
    result = _parse_layer2_response(data)
    assert result.macro_quadrant == "expansion"
    assert len(result.ticker_candidates) == 2
    assert result.ticker_weights["AAPL"] == 0.3
    assert len(result.red_team_notes) == 1


def test_parse_layer2_response_markdown_wrapped():
    data = "```json\n" + json.dumps({"macro_quadrant": "recovery"}) + "\n```"
    result = _parse_layer2_response(data)
    assert result.macro_quadrant == "recovery"


def test_parse_layer2_response_defaults_on_empty():
    result = _parse_layer2_response("{}")
    assert result.macro_quadrant == "contraction"
    assert result.macro_direction == "risk_off"
    assert result.ticker_candidates == []


def test_build_context_includes_l1_fields():
    l1 = _sample_l1()
    ctx = _build_context(l1, None)
    assert "Layer 1 Context" in ctx
    assert "Event Grade: B" in ctx
    assert "risk_on" in ctx


def test_build_context_includes_market_data():
    l1 = _sample_l1()
    ctx = _build_context(l1, {"vix": 18.5, "dxy": 104.2})
    assert "Market Data" in ctx
    assert "vix: 18.5" in ctx


@pytest.mark.asyncio
async def test_analyze_layer2_returns_result():
    l1 = _sample_l1()
    mock_content = json.dumps({
        "macro_quadrant": "expansion", "macro_direction": "risk_on",
        "preferred_assets": ["equities"], "sector_shortlist": ["Tech"],
        "sector_momentum": {}, "factor_scores": {}, "ticker_candidates": ["AAPL"],
        "ticker_weights": {"AAPL": 0.5}, "tier_challenges": [],
    })
    with patch("projects.marketmind.pipeline.layer2_fundamental.chat_pro",
               AsyncMock(return_value={"content": mock_content})):
        result = await analyze_layer2(l1)
        assert result.macro_quadrant == "expansion"
        assert "AAPL" in result.ticker_candidates


@pytest.mark.asyncio
async def test_analyze_layer2_returns_defaults_on_failure():
    l1 = _sample_l1()
    with patch("projects.marketmind.pipeline.layer2_fundamental.chat_pro",
               side_effect=RuntimeError("API error")):
        result = await analyze_layer2(l1)
        assert result.macro_quadrant == "contraction"
        assert result.macro_direction == "risk_off"
        assert len(result.red_team_notes) == 1
