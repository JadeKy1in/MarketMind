"""Tests for L1 Agent Tools (Phase G)."""
import json
import pytest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from marketmind.pipeline.l1_tools import (
    L1ToolRegistry, ToolResult, ToolCallRecord,
    extract_numbers_from_tool_result, inject_tool_results_into_prompt,
    MAX_GNEWS_CALLS_PER_SESSION, MAX_YFINANCE_CALLS_HARD, MAX_YFINANCE_CALLS_WARN,
    _TOOL_CALL_PATTERN,
)


# ── ToolResult tests ──────────────────────────────────────────────────────────

def test_tool_result_status_success():
    tr = ToolResult(tool_name="lookup_fundamentals", query="AAPL",
                    data={"source": "yfinance", "info": {"trailingPE": 32.5}},
                    timestamp="2026-05-16T00:00:00Z")
    assert tr.status == "success"
    assert "lookup_fundamentals" in tr.to_prompt_text()
    assert "status: success" in tr.to_prompt_text()
    assert "trailingPE" in tr.to_prompt_text()


def test_tool_result_status_error():
    tr = ToolResult(tool_name="search_news", query="test",
                    data={}, timestamp="2026-05-16T00:00:00Z",
                    error="API call failed")
    assert tr.status == "error"
    assert "API call failed" in tr.to_prompt_text()
    assert "status: error" in tr.to_prompt_text()


def test_tool_result_status_empty():
    tr = ToolResult(tool_name="lookup_fundamentals", query="INVALID",
                    data={}, timestamp="2026-05-16T00:00:00Z")
    assert tr.status == "empty"


def test_tool_result_to_broadcast_text():
    tr = ToolResult(tool_name="lookup_fundamentals", query="AAPL",
                    data={"source": "yfinance", "info": {"trailingPE": 32.5, "marketCap": 3500000000000}},
                    timestamp="2026-05-16T00:00:00Z")
    bt = tr.to_broadcast_text(query_context="Verifying overvaluation claim")
    assert "lookup_fundamentals" in bt
    assert "AAPL" in bt
    assert "Verifying overvaluation claim" in bt


def test_tool_result_to_prompt_handles_lists():
    tr = ToolResult(tool_name="search_news", query="oil",
                    data=[{"title": "Oil drops", "source": {"name": "Reuters"}},
                          {"title": "OPEC meets", "source": {"name": "Bloomberg"}}],
                    timestamp="2026-05-16T00:00:00Z")
    text = tr.to_prompt_text()
    assert "Oil drops" in text
    assert "Reuters" in text


# ── Tool call parsing tests ───────────────────────────────────────────────────

def test_parse_tool_calls_single():
    registry = L1ToolRegistry()
    text = "Let me check <tool>lookup_fundamentals|AAPL</tool> for more data."
    calls = registry.parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0] == ("lookup_fundamentals", "AAPL")


def test_parse_tool_calls_multiple():
    registry = L1ToolRegistry()
    text = ("<tool>lookup_fundamentals|AAPL</tool> and "
            "<tool>search_news|oil inventories</tool>")
    calls = registry.parse_tool_calls(text)
    assert len(calls) == 2
    assert calls[0] == ("lookup_fundamentals", "AAPL")
    assert calls[1] == ("search_news", "oil inventories")


def test_parse_tool_calls_none():
    registry = L1ToolRegistry()
    text = "No tool calls here, just a normal response."
    calls = registry.parse_tool_calls(text)
    assert len(calls) == 0


def test_parse_tool_calls_case_insensitive():
    registry = L1ToolRegistry()
    text = "<TOOL>lookup_fundamentals|NVDA</TOOL>"
    calls = registry.parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0] == ("lookup_fundamentals", "NVDA")


def test_parse_tool_calls_with_whitespace():
    registry = L1ToolRegistry()
    text = "<tool>  search_news  |  oil demand  </tool>"
    calls = registry.parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0] == ("search_news", "oil demand")


def test_regex_matches_valid_format():
    """Verify the regex pattern matches the expected format."""
    valid = [
        "<tool>lookup_fundamentals|AAPL</tool>",
        "<tool>search_news|oil inventories EIA</tool>",
        "<tool>get_elite_opinion|energy</tool>",
        "<TOOL>lookup_fundamentals|MSFT</TOOL>",
        "<tool>  lookup_fundamentals  |  NVDA  </tool>",
    ]
    for text in valid:
        assert _TOOL_CALL_PATTERN.search(text), f"Should match: {text}"

    invalid = [
        "<tool>lookup_fundamentals</tool>",  # no arg
        "<tool>|AAPL</tool>",  # no tool name
        "lookup_fundamentals|AAPL",  # no tags
        "<not_a_tool>test</not_a_tool>",
    ]
    for text in invalid:
        assert not _TOOL_CALL_PATTERN.search(text), f"Should NOT match: {text}"


# ── L1ToolRegistry tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lookup_fundamentals_with_mock():
    mock_fetcher = AsyncMock(return_value={
        "source": "yfinance",
        "info": {"trailingPE": 32.5, "marketCap": 3500000000000},
    })
    registry = L1ToolRegistry(market_data_fetcher=mock_fetcher)
    result = await registry.lookup_fundamentals("AAPL")

    assert result.tool_name == "lookup_fundamentals"
    assert result.query == "AAPL"
    assert result.status == "success"
    assert len(registry.tool_calls) == 1
    assert len(registry.fact_broadcast) == 1
    assert registry.fact_broadcast[0]["ticker"] == "AAPL"
    mock_fetcher.assert_called_once_with("AAPL", "fundamentals")


@pytest.mark.asyncio
async def test_lookup_fundamentals_yfinance_cap_reached():
    registry = L1ToolRegistry()
    registry._yfinance_calls = MAX_YFINANCE_CALLS_HARD
    result = await registry.lookup_fundamentals("AAPL")
    assert result.status == "error"
    assert "Session limit reached" in result.error


@pytest.mark.asyncio
async def test_search_news_no_api_key():
    registry = L1ToolRegistry(gnews_key=None)
    result = await registry.search_news("oil")
    assert result.status == "error"
    assert "API key not configured" in result.error


@pytest.mark.asyncio
async def test_search_news_cap_reached():
    registry = L1ToolRegistry(gnews_key="test_key")
    registry._gnews_calls = MAX_GNEWS_CALLS_PER_SESSION
    result = await registry.search_news("oil")
    assert result.status == "error"
    assert "temporarily limited" in result.error


@pytest.mark.asyncio
async def test_get_elite_opinion_no_registry():
    registry = L1ToolRegistry()
    result = await registry.get_elite_opinion("energy")
    assert result.status == "error"
    assert "ELITE registry not initialized" in result.error


@pytest.mark.asyncio
async def test_execute_dispatches_correctly():
    mock_fetcher = AsyncMock(return_value={
        "source": "yfinance",
        "info": {"trailingPE": 32.5},
    })
    registry = L1ToolRegistry(market_data_fetcher=mock_fetcher)
    result = await registry.execute("lookup_fundamentals", "AAPL")
    assert result.tool_name == "lookup_fundamentals"
    assert result.status == "success"


@pytest.mark.asyncio
async def test_execute_unknown_tool():
    registry = L1ToolRegistry()
    result = await registry.execute("unknown_tool", "arg")
    assert result.status == "error"
    assert "Unknown tool" in result.error


# ── ToolResult static methods ─────────────────────────────────────────────────

def test_extract_key_fundamentals():
    data = {
        "source": "yfinance",
        "info": {
            "trailingPE": 32.5, "forwardPE": 28.1, "marketCap": 3500000000000,
            "sector": "Technology", "irrelevantField": "should be excluded",
        },
    }
    result = L1ToolRegistry._extract_key_fundamentals(data)
    assert "trailingPE" in result
    assert "forwardPE" in result
    assert "marketCap" in result
    assert "sector" in result
    assert "irrelevantField" not in result


def test_extract_key_fundamentals_empty():
    result = L1ToolRegistry._extract_key_fundamentals({})
    assert isinstance(result, dict)
    assert len(result) == 0


# ── Flush efficacy tests ─────────────────────────────────────────────────────

def test_flush_efficacy_creates_file(tmp_path):
    registry = L1ToolRegistry()
    registry._efficacy_records.append(ToolCallRecord(
        tool="lookup_fundamentals", args={"ticker": "AAPL"},
        status="success", latency_ms=500.0,
    ))
    path = registry.flush_efficacy(str(tmp_path))
    assert path is not None
    assert path.exists()
    data = json.loads(path.read_text())
    assert len(data) == 1
    assert data[0]["tool"] == "lookup_fundamentals"
    assert data[0]["status"] == "success"


def test_flush_efficacy_empty_returns_none(tmp_path):
    registry = L1ToolRegistry()
    path = registry.flush_efficacy(str(tmp_path))
    assert path is None


# ── Summarize tests ───────────────────────────────────────────────────────────

def test_summarize_no_calls():
    registry = L1ToolRegistry()
    assert "未使用工具" in registry.summarize()


def test_summarize_with_calls():
    registry = L1ToolRegistry()
    registry.tool_calls.append(ToolResult(
        tool_name="lookup_fundamentals", query="AAPL",
        data={"source": "yfinance", "info": {}},
        timestamp="2026-05-16T00:00:00Z",
    ))
    summary = registry.summarize()
    assert "lookup_fundamentals" in summary
    assert "1 次工具调用" in summary


# ── Module-level helpers ──────────────────────────────────────────────────────

def test_extract_numbers_from_tool_result():
    tr = ToolResult(
        tool_name="lookup_fundamentals", query="AAPL",
        data={"source": "yfinance", "info": {"trailingPE": 32.5, "marketCap": 3500000000000}},
        timestamp="2026-05-16T00:00:00Z",
    )
    nums = extract_numbers_from_tool_result(tr)
    assert 32.5 in nums
    assert 3500000000000 in nums


def test_inject_tool_results_into_prompt():
    tr = ToolResult(
        tool_name="lookup_fundamentals", query="AAPL",
        data={"source": "yfinance", "info": {"trailingPE": 32.5}},
        timestamp="2026-05-16T00:00:00Z",
    )
    base = "Original prompt text."
    injected = inject_tool_results_into_prompt(base, [tr])
    assert "Original prompt text." in injected
    assert "TOOL RESULTS" in injected
    assert "trailingPE" in injected
    assert "END TOOL RESULTS" in injected


def test_inject_tool_results_empty_list():
    base = "Original prompt text."
    result = inject_tool_results_into_prompt(base, [])
    assert result == base


# ── L1ToolRegistry set_elite_registry ─────────────────────────────────────────

def test_set_elite_registry():
    class MockRegistry:
        pass
    registry = L1ToolRegistry()
    mr = MockRegistry()
    registry.set_elite_registry(mr)
    assert registry._elite_registry is mr


# ── ToolState integration (via layer1_interactive imports) ────────────────────

def test_tool_state_defaults():
    """Verify ToolState dataclass has correct defaults for integration."""
    from marketmind.pipeline.layer1_interactive import ToolState
    ts = ToolState()
    assert ts.calls_used == 0
    assert ts.tool_results == []
    assert ts.fact_broadcast == []
    assert ts.tool_registry is None
    assert ts.gnews_remaining == 10
    assert ts.yfinance_remaining == 50


def test_interactive_state_includes_tools():
    """Verify InteractiveState now includes ToolState."""
    from marketmind.pipeline.layer1_interactive import InteractiveState, ToolState
    state = InteractiveState()
    assert isinstance(state.tools, ToolState)
    assert state.tools.calls_used == 0
    assert isinstance(state.source_numbers, set)
    assert len(state.source_numbers) == 0
