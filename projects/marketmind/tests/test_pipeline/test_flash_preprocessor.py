"""Tests for Flash preprocessor."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from projects.marketmind.pipeline.flash_preprocessor import (
    FlashSignal, preprocess_batch, preprocess_single,
    _parse_json_response, _build_headline_text, FLASH_SYSTEM_PROMPT,
)
from projects.marketmind.pipeline.scout import NewsItem


def make_item(idx: int, title: str) -> NewsItem:
    return NewsItem(
        id=f"id{idx}",
        title=title,
        url=f"https://test.com/{idx}",
        source_name="TestSource",
        source_tier=2,
        published_at="2026-05-11T10:00:00Z",
        summary="Test summary",
    )


def test_flash_signal_from_dict():
    d = {
        "signal_id": "SIG-001",
        "event_type": "monetary_policy",
        "event_grade": "A",
        "direction": "bearish",
        "confidence": 0.85,
        "affected_assets": ["TLT", "SPY"],
        "key_facts": ["Fed raised rates 25bp"],
        "noise_flag": False,
        "cascade_potential": "high",
    }
    s = FlashSignal.from_dict(d)
    assert s.signal_id == "SIG-001"
    assert s.event_grade == "A"
    assert s.direction == "bearish"
    assert s.confidence == 0.85
    assert "TLT" in s.affected_assets
    assert not s.noise_flag


def test_flash_signal_defaults():
    s = FlashSignal.from_dict({})
    assert s.event_type == "macro_data"
    assert s.event_grade == "E"
    assert s.direction == "neutral"
    assert s.confidence == 0.5
    assert len(s.affected_assets) == 0


def test_parse_json_response_clean_array():
    content = '[{"signal_id": "SIG-1", "event_type": "macro_data"}]'
    result = _parse_json_response(content)
    assert len(result) == 1
    assert result[0]["signal_id"] == "SIG-1"


def test_parse_json_response_markdown_wrapped():
    content = '```json\n[{"signal_id": "SIG-2"}]\n```'
    result = _parse_json_response(content)
    assert len(result) == 1
    assert result[0]["signal_id"] == "SIG-2"


def test_parse_json_response_single_object():
    content = '{"signal_id": "SIG-3", "event_type": "geopolitical"}'
    result = _parse_json_response(content)
    assert len(result) == 1
    assert result[0]["signal_id"] == "SIG-3"


def test_parse_json_response_extracts_from_text():
    content = 'Here is the analysis: [{"signal_id": "SIG-4"}] with more text after.'
    result = _parse_json_response(content)
    assert len(result) == 1


def test_parse_json_response_invalid_returns_empty():
    assert _parse_json_response("Just some regular text, no JSON here.") == []


def test_build_headline_text():
    items = [
        make_item(0, "Fed raises rates"),
        make_item(1, "Oil prices surge"),
    ]
    text = _build_headline_text(items)
    assert "Fed raises rates" in text
    assert "Oil prices surge" in text
    assert "[0]" in text
    assert "[1]" in text


def test_flash_system_prompt_has_integrity():
    assert "Never fabricate" in FLASH_SYSTEM_PROMPT
    assert "DATA_UNAVAILABLE" not in FLASH_SYSTEM_PROMPT  # in chat_with_integrity instead


@pytest.mark.asyncio
async def test_preprocess_batch_returns_signals():
    mock_result = {
        "content": json.dumps([{
            "signal_id": "SIG-TEST-1",
            "event_type": "macro_data",
            "event_grade": "E",
            "direction": "bullish",
            "confidence": 0.75,
            "affected_assets": ["SPY"],
            "key_facts": ["GDP grew 3.2% (BEA)"],
            "noise_flag": False,
            "cascade_potential": "low",
        }]),
        "usage": {"total_tokens": 100},
        "latency_ms": 200,
    }
    with patch("projects.marketmind.pipeline.flash_preprocessor.chat_flash", AsyncMock(return_value=mock_result)):
        items = [make_item(0, "GDP Report Shows Growth")]
        signals = await preprocess_batch(items, batch_size=1)
        assert len(signals) == 1
        assert signals[0].direction == "bullish"
        assert signals[0].source_headline == "GDP Report Shows Growth"


@pytest.mark.asyncio
async def test_preprocess_empty_returns_empty():
    signals = await preprocess_batch([])
    assert signals == []


@pytest.mark.asyncio
async def test_preprocess_single_returns_signal():
    mock_result = {
        "content": json.dumps([{
            "signal_id": "SIG-SINGLE-1",
            "event_type": "corporate_action",
            "event_grade": "B",
            "direction": "bearish",
            "confidence": 0.6,
            "affected_assets": ["AAPL"],
            "key_facts": ["Earnings miss"],
            "noise_flag": False,
            "cascade_potential": "medium",
        }]),
    }
    with patch("projects.marketmind.pipeline.flash_preprocessor.chat_flash", AsyncMock(return_value=mock_result)):
        item = make_item(0, "Apple Misses Earnings")
        signal = await preprocess_single(item)
        assert signal is not None
        assert signal.event_type == "corporate_action"
        assert "AAPL" in signal.affected_assets
