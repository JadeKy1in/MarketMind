"""Tests for Red Team adversarial engine."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from marketmind.pipeline.red_team import (
    RedTeamChallenge, RedTeamReport, run_red_team, _parse_red_team_response,
)


def test_red_team_report_counts():
    report = RedTeamReport(
        challenges=[
            RedTeamChallenge(id="1", target="layer1", severity="critical", challenge="c1", evidence="e1", suggested_fix="f1"),
            RedTeamChallenge(id="2", target="layer2", severity="major", challenge="c2", evidence="e2", suggested_fix="f2"),
            RedTeamChallenge(id="3", target="layer1", severity="critical", challenge="c3", evidence="e3", suggested_fix="f3"),
        ]
    )
    assert report.critical_count == 2
    assert report.a_grade_count == 0  # not set unless parsed


def test_parse_red_team_response():
    content = json.dumps({
        "challenges": [
            {"id": "RT-1", "target": "layer1_sentiment", "severity": "critical",
             "challenge": "Sentiment reading ignores contrarian indicators",
             "evidence": "Put-call ratio shows opposite signal",
             "suggested_fix": "Cross-reference with options flow data"}
        ],
        "overall_assessment": "One critical finding, otherwise solid.",
        "no_valid_objection": False
    })
    report = _parse_red_team_response(content)
    assert len(report.challenges) == 1
    assert report.challenges[0].severity == "critical"
    assert report.critical_count == 1
    assert report.a_grade_count == 1


def test_parse_red_team_empty():
    content = json.dumps({"challenges": [], "overall_assessment": "Clean analysis", "no_valid_objection": True})
    report = _parse_red_team_response(content)
    assert len(report.challenges) == 0
    assert report.no_valid_objection is True


def test_parse_red_team_markdown_wrapped():
    content = '```json\n{"challenges": [{"id": "RT-1", "target": "layer2", "severity": "minor", "challenge": "test", "evidence": "test", "suggested_fix": "test"}], "overall_assessment": "ok"}\n```'
    report = _parse_red_team_response(content)
    assert len(report.challenges) == 1


@pytest.mark.asyncio
async def test_run_red_team_returns_report():
    mock_content = json.dumps({
        "challenges": [
            {"id": "RT-1", "target": "layer1_sentiment", "severity": "critical",
             "challenge": "Overly bullish read in high VIX environment",
             "evidence": "VIX at 28, historically bearish for equities",
             "suggested_fix": "Adjust sentiment weight for volatility regime"}
        ],
        "overall_assessment": "One critical finding.",
        "no_valid_objection": False
    })
    with patch("marketmind.pipeline.red_team.chat_pro", AsyncMock(return_value={"content": mock_content})):
        report = await run_red_team("L1 raw text", "L2 raw text", ["AAPL"])
        assert isinstance(report, RedTeamReport)
        assert report.critical_count >= 1
        assert not report.no_valid_objection
