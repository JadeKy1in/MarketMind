"""Tests for fact checker — claim extraction + Pro verification + report synthesis."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from marketmind.integrity.fact_checker import (
    FactCheckReport, run_fact_check, _parse_fact_check_response,
)
from marketmind.integrity.watchdog import NumericClaim


def test_parse_fact_check_response_extracts_claims():
    data = json.dumps({
        "claims": [
            {"claim_value": "520.50", "claim_context": "SPY price", "verdict": "TRUE",
             "ground_truth": "520.50", "source": "yfinance", "confidence": 0.95},
            {"claim_value": "999", "claim_context": "fake price", "verdict": "FALSE",
             "ground_truth": "520.50", "source": "yfinance", "confidence": 0.99},
        ],
        "summary": "One true, one false",
        "critical_alerts": ["Price hallucination: 999"],
    })
    original = [
        NumericClaim(value="520.50", claim_type="price", context="SPY price",
                     source_agent="test", session_id="s1", timestamp="2026-01-01"),
    ]
    report = _parse_fact_check_response(data, original)
    assert report.total_claims == 1
    assert report.verified == 1
    assert report.falsified == 1  # claim at index 1 flagged FALSE -> alerts
    assert "Price hallucination" in str(report.critical_alerts)


def test_parse_fact_check_response_handles_markdown_fence():
    data = "```json\n" + json.dumps({"claims": [], "summary": "all clean", "critical_alerts": []}) + "\n```"
    report = _parse_fact_check_response(data, [])
    assert report.summary == "all clean"


def test_parse_fact_check_response_handles_array():
    """LLM may return a bare array instead of object with claims key."""
    data = json.dumps([
        {"claim_value": "15.3", "verdict": "TRUE"},
    ])
    original = [NumericClaim(value="15.3", claim_type="percentage", context="gain",
                              source_agent="test", session_id="s1", timestamp="2026-01-01")]
    report = _parse_fact_check_response(data, original)
    assert report.total_claims == 1


def test_parse_fact_check_response_invalid_json():
    report = _parse_fact_check_response("not json at all", [])
    assert "Failed to parse" in report.summary


@pytest.mark.asyncio
async def test_run_fact_check_no_claims():
    report = await run_fact_check("Just some qualitative text with no numbers.", "test", "s1")
    assert report.total_claims == 0
    assert "No numeric claims" in report.summary


@pytest.mark.asyncio
async def test_run_fact_check_with_claims():
    content = "SPY is at $520.50. Sharpe ratio of 2.5. Strong 15.3% gain."
    mock_response = {
        "claims": [
            {"claim_value": "520.50", "verdict": "TRUE", "ground_truth": "520.50",
             "source": "yfinance", "confidence": 0.95, "claim_context": "SPY price"},
            {"claim_value": "2.5", "verdict": "TRUE", "ground_truth": "2.5",
             "source": "yfinance", "confidence": 0.9, "claim_context": "Sharpe"},
            {"claim_value": "15.3", "verdict": "TRUE", "ground_truth": "15.3",
             "source": "calculation", "confidence": 0.8, "claim_context": "gain"},
        ],
        "summary": "All claims verified",
        "critical_alerts": [],
    }
    with patch("marketmind.integrity.fact_checker.chat_pro",
               AsyncMock(return_value={"content": json.dumps(mock_response)})):
        report = await run_fact_check(content, "builder", "s1")
        assert report.total_claims == 3
        assert report.verified == 3


@pytest.mark.asyncio
async def test_run_fact_check_handles_api_failure():
    content = "SPY is at $520.50."
    with patch("marketmind.integrity.fact_checker.chat_pro",
               side_effect=RuntimeError("API error")):
        report = await run_fact_check(content, "builder", "s2")
        assert report.total_claims == 1
        assert "API call failed" in report.summary
