"""Tests for Layer 1 narrative analysis."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from projects.marketmind.pipeline.layer1_narrative import (
    Layer1Result, analyze_layer1, _parse_layer1_response, _format_signals,
)
from projects.marketmind.pipeline.flash_preprocessor import FlashSignal
from projects.marketmind.pipeline.scout import NewsItem


def make_signal() -> FlashSignal:
    return FlashSignal(
        signal_id="SIG-1", event_type="monetary_policy", event_grade="A",
        direction="bearish", confidence=0.8, affected_assets=["TLT", "SPY"],
        key_facts=["Fed raised rates"], noise_flag=False,
        cascade_potential="high", source_headline="Fed Raises Rates"
    )


def make_item() -> NewsItem:
    return NewsItem(
        id="id1", title="Fed Raises Rates", url="https://test.com/1",
        source_name="TestSource", source_tier=1,
        published_at="2026-05-11T10:00:00Z", summary="The Federal Reserve raised rates."
    )


def test_parse_layer1_response_clean():
    content = json.dumps({
        "event_grade": "A", "surprise_level": "high", "market_size": "big",
        "matrix_quadrant": "core_opportunity", "price_in_score": 0.3,
        "cascade_rank": 2, "cascade_hub": True,
        "sentiment_direction": "bearish", "sentiment_intensity": 0.8,
        "sentiment_vs_attention": "high_sentiment",
        "expert_signals": [], "institutional_surprise": "Hawkish turn",
        "key_characters": [], "tail_risk_flags": ["vol_clustering"],
        "narrative_summary": "Fed hawkish pivot"
    })
    result = _parse_layer1_response(content)
    assert result.event_grade == "A"
    assert result.matrix_quadrant == "core_opportunity"
    assert result.price_in_score == 0.3
    assert result.cascade_hub is True


def test_parse_layer1_response_defaults_on_empty():
    result = _parse_layer1_response("{}")
    assert result.event_grade == "E"
    assert result.sentiment_direction == "neutral"


def test_format_signals():
    signals = [make_signal()]
    items = [make_item()]
    text = _format_signals(signals, items)
    assert "Fed Raises Rates" in text
    assert "[A]" in text
    assert "bearish" in text


@pytest.mark.asyncio
async def test_analyze_layer1_returns_result():
    mock_content = json.dumps({
        "event_grade": "B", "surprise_level": "low", "market_size": "big",
        "matrix_quadrant": "trend_opportunity", "price_in_score": 0.6,
        "cascade_rank": 1, "cascade_hub": False,
        "sentiment_direction": "bullish", "sentiment_intensity": 0.6,
        "sentiment_vs_attention": "high_attention",
        "expert_signals": [], "institutional_surprise": "",
        "key_characters": [], "tail_risk_flags": [],
        "narrative_summary": "Earnings beat driving rally."
    })
    mock_result = {"content": mock_content, "usage": {}}
    with patch("projects.marketmind.pipeline.layer1_narrative.chat_pro", AsyncMock(return_value=mock_result)):
        result = await analyze_layer1([make_signal()], [make_item()])
        assert isinstance(result, Layer1Result)
        assert result.event_grade == "B"
        assert result.matrix_quadrant == "trend_opportunity"


@pytest.mark.asyncio
async def test_analyze_layer1_empty_signals():
    result = await analyze_layer1([], [])
    assert result.event_grade == "E"
    assert result.matrix_quadrant == "observe_skip"
