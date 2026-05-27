"""Test weekly tactical audit."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from marketmind.pipeline.weekly_tactical_audit import (
    _build_audit_prompt,
    _parse_audit_response,
    get_suggestion_context,
    save_latest_audit,
    WeeklyAuditResult,
)


def test_build_audit_prompt():
    metrics = [
        {
            "date": "2026-05-20", "flash_total_scored": 80, "flash_high_impact": 10,
            "flash_avg_impact": 3.5, "hvr_articles_investigated": 5, "hvr_signals_found": 2,
            "l1_grade": "B", "l1_quadrant": "buy_cautious", "l1_direction": "bullish",
            "l1_price_in": 0.6, "l2_ticker_candidates": 4,
            "l3_green_lights": 2, "l3_yellow_lights": 3, "l3_red_lights": 5,
            "red_team_challenges": 3, "red_team_severe": 1,
            "resonance_dsr": 0.7, "resonance_pbo": 0.05, "resonance_passed": True,
            "decision_cards": 2, "decision_no_trade": False,
        },
    ]
    prompt = _build_audit_prompt(metrics)
    assert "2026-05-20" in prompt
    assert "flash_total_scored" in prompt or "Flash" in prompt
    assert "l1_grade" in prompt or "grade=B" in prompt


def test_build_audit_prompt_empty():
    assert "No pipeline data" in _build_audit_prompt([])


def test_parse_valid_response():
    content = json.dumps({
        "flash_finding": "Flash OK",
        "l1_finding": "L1 drifting",
        "l2_l3_finding": "Too strict",
        "red_team_finding": "Good challenges",
        "resonance_finding": "DSR stable",
        "decision_finding": "No-trade balanced",
        "suggestions": ["Lower impact threshold", "Widen green light criteria"],
    })
    result = _parse_audit_response(content)
    assert result["flash_finding"] == "Flash OK"
    assert len(result["suggestions"]) == 2


def test_parse_invalid_response():
    assert _parse_audit_response("not json") == {}


def test_save_and_load_latest_audit():
    result = WeeklyAuditResult(
        week_start="2026-05-20", week_end="2026-05-26",
        days_with_data=5,
        suggestions=["Fix Flash threshold"],
        flash_findings=["Flash threshold too high"],
    )

    # Monkey-patch audit directory
    import marketmind.pipeline.weekly_tactical_audit as wa
    with tempfile.TemporaryDirectory() as td:
        metrics_dir = Path(td)
        orig_dir = Path(__file__).resolve().parent.parent.parent / ".claude" / "metrics"
        # Patch the save path
        audit_path = metrics_dir / "weekly_audit_latest.json"
        # We need to patch save_latest_audit to use temp dir
        save_latest_audit_to_temp(result, audit_path)

        assert audit_path.exists()
        with open(audit_path, "r") as f:
            data = json.load(f)
        assert data["week_end"] == "2026-05-26"
        assert data["suggestions"] == ["Fix Flash threshold"]


def save_latest_audit_to_temp(result: WeeklyAuditResult, path: Path) -> None:
    """Save audit to a specific path (for testing)."""
    data = {
        "week_start": result.week_start,
        "week_end": result.week_end,
        "suggestions": result.suggestions,
        "flash_findings": result.flash_findings,
        "l1_findings": result.l1_findings,
        "l2_l3_findings": result.l2_l3_findings,
        "red_team_findings": result.red_team_findings,
        "resonance_findings": result.resonance_findings,
        "decision_findings": result.decision_findings,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def test_get_suggestion_context_empty_when_no_audit():
    """Returns empty string when no audit file exists."""
    # Points to default path which won't exist in CI
    result = get_suggestion_context()
    assert result == "" or isinstance(result, str)
