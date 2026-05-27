"""Test serenity-reply playground agent adapter."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketmind.playground.agents.serenity_reply.adapter import (
    _filter_semicon_news,
    _build_news_summary,
    _parse_response,
    _validate_output,
    _parse_research_response,
    _identify_research_leads,
    _find_relevant_articles,
    _format_articles_for_research,
    _empty_result,
    analyze,
)


def test_filter_semicon_news_matches_keywords():
    """Filters news to semiconductor-related items."""
    news = [
        {"title": "NVIDIA announces new GPU architecture", "summary": "AI chips get faster"},
        {"title": "Coffee prices surge amid drought", "summary": "Brazil crop failure"},
        {"title": "AXTI substrates in high demand for photonics", "summary": "Supply chain bottleneck"},
        {"title": "EU passes new AI regulation", "summary": "Compliance costs rise"},
        {"title": "TSMC 3nm yield improves", "summary": "Chip manufacturing milestone"},
    ]
    filtered = _filter_semicon_news(news)
    assert len(filtered) == 3
    titles = {f["title"] for f in filtered}
    assert "NVIDIA announces new GPU architecture" in titles
    assert "AXTI substrates in high demand for photonics" in titles
    assert "TSMC 3nm yield improves" in titles


def test_filter_semicon_news_empty():
    """Returns empty list when no semiconductor news."""
    news = [
        {"title": "Coffee prices surge", "summary": "Drought in Brazil"},
        {"title": "Oil futures decline", "summary": "OPEC+ output increase"},
    ]
    filtered = _filter_semicon_news(news)
    assert filtered == []


def test_filter_semicon_news_handles_non_dict():
    """Handles non-dict news items gracefully."""
    news = [
        "NVIDIA chip news",
        {"title": "Oil prices fall", "summary": "Supply glut"},
        "Some random text about semiconductors and photonics",
    ]
    filtered = _filter_semicon_news(news)
    # The first and third strings contain semiconductor keywords
    assert len(filtered) >= 2


def test_build_news_summary():
    """Builds a formatted news summary string."""
    news = [
        {"title": "NVIDIA GPU launch", "source_name": "Reuters", "summary": "New chips"},
        {"title": "AXTI supply shortage", "source_name": "Bloomberg", "summary": "Photonics demand"},
    ]
    summary = _build_news_summary(news)
    assert "NVIDIA GPU launch" in summary
    assert "AXTI supply shortage" in summary
    assert "Reuters" in summary
    assert "Bloomberg" in summary


def test_build_news_summary_empty():
    """Returns placeholder for empty news."""
    summary = _build_news_summary([])
    assert "No semiconductor" in summary


def test_parse_response_valid_json():
    """Parses valid JSON response."""
    content = json.dumps({
        "directional_calls": [
            {"ticker": "AXTI", "direction": "bullish", "confidence": 0.8,
             "thesis": "InP substrate monopoly", "mental_model_used": "chokepoint_theory"},
        ],
        "no_calls_reason": "",
        "supply_chain_observations": ["Photonics demand accelerating"],
    })
    result = _parse_response(content)
    assert len(result["directional_calls"]) == 1
    assert result["directional_calls"][0]["ticker"] == "AXTI"


def test_parse_response_markdown_wrapped():
    """Strips markdown code fences from response."""
    content = '```json\n{"directional_calls": [], "no_calls_reason": "Nothing today"}\n```'
    result = _parse_response(content)
    assert result["directional_calls"] == []
    assert "Nothing today" in result["no_calls_reason"]


def test_parse_response_json_in_text():
    """Extracts JSON from surrounding text."""
    content = 'Here is my analysis:\n{"directional_calls": [], "no_calls_reason": "No signals"}\nLet me know if you need more.'
    result = _parse_response(content)
    assert result["directional_calls"] == []


def test_parse_response_invalid():
    """Returns graceful output on parse failure."""
    result = _parse_response("not json at all, just some random thoughts about the market")
    assert result["directional_calls"] == []
    assert "Failed to parse" in result["no_calls_reason"]


def test_validate_output_filters_low_confidence():
    """Removes calls with confidence < 0.6."""
    parsed = {
        "directional_calls": [
            {"ticker": "AXTI", "direction": "bullish", "confidence": 0.9,
             "thesis": "Strong bottleneck", "mental_model_used": "chokepoint_theory"},
            {"ticker": "TEST", "direction": "bearish", "confidence": 0.3,
             "thesis": "Weak signal", "mental_model_used": "nvidia_signal"},
        ],
    }
    result = _validate_output(parsed)
    assert len(result["directional_calls"]) == 1
    assert result["directional_calls"][0]["ticker"] == "AXTI"


def test_validate_output_rejects_large_caps():
    """Removes calls on large-cap stocks per framework rules."""
    parsed = {
        "directional_calls": [
            {"ticker": "NVDA", "direction": "bullish", "confidence": 0.9,
             "thesis": "Good company", "mental_model_used": "chokepoint_theory"},
            {"ticker": "AXTI", "direction": "bullish", "confidence": 0.8,
             "thesis": "Small cap bottleneck", "mental_model_used": "chokepoint_theory"},
            {"ticker": "ASML", "direction": "bullish", "confidence": 0.85,
             "thesis": "Monopoly", "mental_model_used": "chokepoint_theory"},
        ],
    }
    result = _validate_output(parsed)
    assert len(result["directional_calls"]) == 1
    assert result["directional_calls"][0]["ticker"] == "AXTI"


def test_validate_output_limits_to_three():
    """Keeps at most 3 calls, sorted by confidence."""
    parsed = {
        "directional_calls": [
            {"ticker": "AAA", "direction": "bullish", "confidence": 0.7,
             "thesis": "t1", "mental_model_used": "chokepoint_theory"},
            {"ticker": "BBB", "direction": "bullish", "confidence": 0.9,
             "thesis": "t2", "mental_model_used": "nvidia_signal"},
            {"ticker": "CCC", "direction": "bearish", "confidence": 0.8,
             "thesis": "t3", "mental_model_used": "information_asymmetry"},
            {"ticker": "DDD", "direction": "bullish", "confidence": 0.95,
             "thesis": "t4", "mental_model_used": "geopolitical_premium"},
        ],
    }
    result = _validate_output(parsed)
    assert len(result["directional_calls"]) == 3
    # Should keep the top 3 by confidence: DDD(0.95), BBB(0.9), CCC(0.8)
    tickers = {c["ticker"] for c in result["directional_calls"]}
    assert tickers == {"DDD", "BBB", "CCC"}


@pytest.mark.asyncio
async def test_analyze_mock_mode():
    """Mock mode returns empty calls without API call."""
    context = {
        "news": [{"title": "NVIDIA news", "source_name": "Reuters", "summary": "Test"}],
        "timestamp": "2026-05-27T00:00:00Z",
    }
    result = await analyze(context, mock=True)
    assert result["directional_calls"] == []
    assert "Mock mode" in result["no_calls_reason"]


@pytest.mark.asyncio
async def test_analyze_no_news():
    """Returns empty calls when no news provided."""
    result = await analyze({"news": [], "timestamp": "2026-05-27T00:00:00Z"}, mock=False)
    assert result["directional_calls"] == []
    assert "No news" in result["no_calls_reason"]


@pytest.mark.asyncio
async def test_analyze_no_semicon_news():
    """Returns empty calls when no semiconductor news found."""
    context = {
        "news": [
            {"title": "Coffee prices rise", "source_name": "Reuters", "summary": "Drought"},
            {"title": "Oil market update", "source_name": "Bloomberg", "summary": "OPEC cuts"},
        ],
        "timestamp": "2026-05-27T00:00:00Z",
    }
    result = await analyze(context, mock=False)
    assert result["directional_calls"] == []
    assert "No semiconductor" in result["no_calls_reason"]


def test_information_firewall_no_pipeline_data():
    """The adapter does not accept or read any main pipeline analysis fields.

    Even if they were accidentally passed, the adapter only reads 'news',
    'market_data', and 'timestamp' from the context dict.
    """
    context = {
        "news": [{"title": "NVIDIA GPU launch", "source_name": "Reuters", "summary": "New chips"}],
        "timestamp": "2026-05-27T00:00:00Z",
        # These fields should be ignored even if present:
        "l1_result": {"quadrant": "risk-on"},
        "l2_result": {"ticker_candidates": ["NVDA", "AMD"]},
        "shadow_analysis": "top secret shadow output",
    }
    # The adapter's _filter_semicon_news only looks at title/summary.
    # It cannot read l1_result or l2_result because the code doesn't
    # reference those keys. This test verifies the function doesn't crash
    # when such keys are present (it ignores them).
    filtered = _filter_semicon_news(context["news"])
    assert len(filtered) == 1
    assert filtered[0]["title"] == "NVIDIA GPU launch"


# ── Research loop tests ──────────────────────────────────────────────────


def test_identify_research_leads_borderline_confidence():
    """Calls with confidence 0.6-0.8 and a research question are leads."""
    pass1 = {
        "directional_calls": [
            {"ticker": "AXTI", "direction": "bullish", "confidence": 0.72,
             "thesis": "InP substrate supplier", "needs_deeper_research": False,
             "research_question": "Is AXTI the sole InP substrate supplier for CPO?"},
            {"ticker": "TEST", "direction": "bearish", "confidence": 0.90,
             "thesis": "Clear overvaluation", "needs_deeper_research": False,
             "research_question": ""},
        ],
    }
    leads = _identify_research_leads(pass1)
    assert len(leads) == 1
    assert leads[0]["ticker"] == "AXTI"


def test_identify_research_leads_explicit_flag():
    """Calls with needs_deeper_research=true are leads regardless of confidence."""
    pass1 = {
        "directional_calls": [
            {"ticker": "AXTI", "direction": "bullish", "confidence": 0.85,
             "thesis": "Strong signal", "needs_deeper_research": True,
             "research_question": "Verify substrate capacity expansion plans"},
        ],
    }
    leads = _identify_research_leads(pass1)
    assert len(leads) == 1


def test_identify_research_leads_skips_high_confidence_no_flag():
    """High confidence without needs_deeper_research flag is skipped."""
    pass1 = {
        "directional_calls": [
            {"ticker": "AXTI", "direction": "bullish", "confidence": 0.90,
             "thesis": "Clear winner", "needs_deeper_research": False,
             "research_question": ""},
        ],
    }
    leads = _identify_research_leads(pass1)
    assert len(leads) == 0


def test_identify_research_leads_skips_low_confidence():
    """Below 0.6 is not in directional_calls (filtered by validate_output)."""
    pass1 = {"directional_calls": []}
    leads = _identify_research_leads(pass1)
    assert leads == []


def test_find_relevant_articles_ticker_match():
    """Articles mentioning the ticker score highest."""
    articles = [
        {"title": "AXTI reports record revenue", "summary": "Photonics demand",
         "full_content": "AXTI, the leading InP substrate manufacturer, announced..."},
        {"title": "Oil prices fall", "summary": "OPEC decision",
         "full_content": ""},
        {"title": "Semiconductor supply chain update", "summary": "Various companies",
         "full_content": "AXTI subsidiary also mentioned in context of photonics..."},
    ]
    relevant = _find_relevant_articles("AXTI", "InP substrate supply", articles)
    assert len(relevant) >= 2
    # First result should be the one with ticker in title
    assert "AXTI" in relevant[0]["title"]


def test_find_relevant_articles_none_found():
    """Returns empty list when nothing matches."""
    articles = [
        {"title": "Oil news", "summary": "OPEC", "full_content": ""},
        {"title": "Coffee prices", "summary": "Drought", "full_content": ""},
    ]
    relevant = _find_relevant_articles("AXTI", "photonics supply", articles)
    assert relevant == []


def test_format_articles_for_research():
    """Formats articles into readable research text."""
    articles = [
        {"title": "AXTI InP Supply", "source_name": "EE Times",
         "url": "https://example.com/1", "full_content": "AXTI controls 80% of InP substrate market."},
        {"title": "CPO Market Growth", "source_name": "Photonics Spectra",
         "url": "https://example.com/2", "full_content": "Co-packaged optics demand surging."},
    ]
    text = _format_articles_for_research(articles)
    assert "AXTI InP Supply" in text
    assert "CPO Market Growth" in text
    assert "https://example.com/1" in text
    assert "80% of InP substrate" in text


def test_parse_research_response_valid():
    """Parse a valid research response."""
    content = json.dumps({
        "finding": "CLEAR_BULLISH",
        "confidence_adjustment": 0.08,
        "key_evidence": ["AXTI confirmed as sole InP supplier for CPO"],
        "counter_evidence": ["Valuation at 85x revenue"],
        "updated_thesis": "AXTI has an InP substrate monopoly",
        "recommendation": "UPGRADE_TO_CALL",
    })
    result = _parse_research_response(content)
    assert result is not None
    assert result["finding"] == "CLEAR_BULLISH"
    assert result["confidence_adjustment"] == 0.08
    assert result["recommendation"] == "UPGRADE_TO_CALL"


def test_parse_research_response_invalid():
    """Returns None on unparseable input."""
    result = _parse_research_response("not json at all")
    assert result is None


def test_empty_result():
    result = _empty_result("Test reason")
    assert result["directional_calls"] == []
    assert result["no_calls_reason"] == "Test reason"
    assert result["_research_log"] == []


@pytest.mark.asyncio
async def test_analyze_mock_returns_research_log():
    """Mock mode still returns _research_log and _passes fields."""
    context = {
        "news": [{"title": "NVIDIA GPU news", "source_name": "Reuters", "summary": "Test"}],
        "timestamp": "2026-05-27T00:00:00Z",
    }
    result = await analyze(context, mock=True)
    assert "_research_log" in result
    assert "_passes" in result
    assert result["_passes"] == 1
