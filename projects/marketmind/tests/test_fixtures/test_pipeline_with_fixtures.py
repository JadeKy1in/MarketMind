"""Fixture-driven pipeline stage tests — verify each stage in isolation.

Fixtures are synthetic representations of upstream stage output.
When --regenerate-fixtures --force is run, these get replaced with real pipeline output.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

# Ensure package root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from marketmind.test_fixtures.conftest import load_json_fixture, fixture_available


# ── Stage 1: Scout fixture → Flash Triage ───────────────────────────────────

def test_flash_triage_loads_scout_fixture():
    """Flash triage can accept scout fixture format (list of NewsItem-like dicts)."""
    data = load_json_fixture("stage1_scout", "normal")
    assert isinstance(data, list), "Scout fixture must be a list"
    assert len(data) >= 3, "Need at least 3 headlines for meaningful triage"
    for item in data:
        assert "headline" in item
        assert "source_name" in item
        assert "source_tier" in item


def test_flash_triage_parse_json_with_trailing_commas():
    """Verify _parse_json_response handles trailing commas from fixture-like JSON."""
    from marketmind.pipeline.flash_triage import _parse_json_response

    content = (
        '[{"headline_index": 0, "scores": {"market_impact": 5, "urgency": 3,},'
        '"classification": "macro",},'
        '{"headline_index": 1, "scores": {"market_impact": 2, "urgency": 1,}}]'
    )
    result = _parse_json_response(content)
    assert len(result) == 2
    assert result[0]["scores"]["urgency"] == 3


def test_flash_fixture_matches_triage_result_schema():
    """Stage 2 flash fixture matches TriageResult dataclass structure."""
    data = load_json_fixture("stage2_flash", "normal")
    assert isinstance(data, list)
    for item in data:
        assert "headline" in item
        assert "scores" in item
        assert "market_impact" in item["scores"]
        assert "urgency" in item["scores"]
        assert "classification" in item
        assert "affected_assets" in item
        assert isinstance(item["affected_assets"], list)


def test_flash_empty_fixture():
    """Empty fixture (0 signals) loads without error."""
    data = load_json_fixture("stage2_flash", "empty")
    assert data == []


# ── Stage 3: L1 → Red Team ──────────────────────────────────────────────────

def test_red_team_parse_json_with_trailing_commas():
    """Verify _parse_red_team_response handles trailing commas in fixture-like JSON."""
    from marketmind.pipeline.red_team import _parse_red_team_response

    content = (
        '{"challenges": [{"id": "c1", "severity": "critical",'
        '"challenge": "test", "evidence": "none",},],'
        '"overall_assessment": "pass"}'
    )
    result = _parse_red_team_response(content)
    assert len(result.challenges) == 1
    assert result.challenges[0].severity == "critical"


# ── Staleness & Hash checks ─────────────────────────────────────────────────

def test_fixture_metadata_has_pipeline_hash():
    """If metadata exists, it must contain pipeline_content_hash."""
    from marketmind.test_fixtures import _metadata_path, compute_pipeline_hash

    meta_path = _metadata_path("stage1_scout", "normal")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        assert "pipeline_content_hash" in meta

    current_hash = compute_pipeline_hash()
    assert len(current_hash) == 64  # SHA256


def test_scrub_output_normalizes_timestamps():
    from marketmind.test_fixtures import scrub_output

    data = {"created": "2026-05-19T02:00:00Z", "msg": "unchanged"}
    scrubbed = scrub_output(data)
    assert "[TIMESTAMP]" in str(scrubbed["created"])
    assert scrubbed["msg"] == "unchanged"
