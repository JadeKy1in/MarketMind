"""Tests for ConsensusExtractor — R0 cross-shadow consensus aggregation."""
import pytest

from marketmind.shadows.consensus_extractor import (
    ConsensusExtractor,
    ConsensusResult,
)


# ── Test 1: Full consensus (all long) ───────────────────────────────────

def test_extract_all_long_consensus():
    """When all 15 Expert shadows say 'long', result should be 'long' with 1.0 agreement."""
    analyses = {}
    for i in range(15):
        analyses[f"expert:domain:agent_{i:02d}"] = {
            "direction": "long",
            "confidence": 0.7 + i * 0.01,
            "ticker": "AAPL",
            "thesis": f"Bullish thesis {i}",
        }

    result = ConsensusExtractor.extract(analyses)

    assert isinstance(result, ConsensusResult)
    assert result.direction == "long"
    assert result.agreement_pct == 1.0
    assert result.expert_count == 15
    assert result.long_count == 15
    assert result.short_count == 0
    assert result.abstain_count == 0
    assert result.reliability == "FULL"


# ── Test 2: Mixed consensus with abstentions ────────────────────────────

def test_extract_mixed_with_abstentions():
    """Mixed directions plus abstentions should produce correct counts."""
    analyses = {
        "expert:gold:agent_01": {"direction": "long", "confidence": 0.7},
        "expert:gold:agent_02": {"direction": "long", "confidence": 0.6},
        "expert:gold:agent_03": {"direction": "short", "confidence": 0.8},
        "expert:gold:agent_04": {"direction": "short", "confidence": 0.5},
        "expert:gold:agent_05": {"direction": "short", "confidence": 0.6},
        "expert:gold:agent_06": {"direction": "abstain", "confidence": 0.0},
        "expert:gold:agent_07": {"direction": "long", "confidence": 0.5},
        "expert:gold:agent_08": {"direction": "abstain", "confidence": 0.0},
    }

    result = ConsensusExtractor.extract(analyses)

    assert result.expert_count == 8
    assert result.long_count == 3
    assert result.short_count == 3
    assert result.abstain_count == 2
    # 3 vs 3 with 0.375 each -> tied within 5% margin -> mixed
    assert result.direction == "mixed"
    assert result.reliability == "DEGRADED"  # 8 experts


# ── Test 3: Edge cases (empty, None, invalid direction) ─────────────────

def test_extract_edge_cases():
    """Empty dict returns SKIP; None analysis skipped; invalid direction raises."""
    # Empty input
    result = ConsensusExtractor.extract({})
    assert result.direction == "mixed"
    assert result.expert_count == 0
    assert result.reliability == "SKIP"

    # None analysis skipped
    result = ConsensusExtractor.extract({
        "expert:a:agent_01": {"direction": "long"},
        "expert:a:agent_02": None,
        "expert:a:agent_03": {"direction": "long"},
    })
    assert result.expert_count == 2
    assert result.long_count == 2
    assert result.direction == "long"

    # Invalid direction raises ValueError
    with pytest.raises(ValueError, match="Invalid direction"):
        ConsensusExtractor.extract({
            "expert:a:agent_01": {"direction": "invalid_direction"},
        })

    # Wrong type raises TypeError
    with pytest.raises(TypeError, match="must be dict"):
        ConsensusExtractor.extract([{"direction": "long"}])  # type: ignore[arg-type]

    # Analysis dict type mismatch raises
    with pytest.raises(TypeError, match="must be dict"):
        ConsensusExtractor.extract({"shadow": 123})  # type: ignore[dict-item]


# ── Test 4: Strong short consensus with DEGRADED reliability ────────────

def test_extract_short_majority_degraded():
    """9 shorts vs 2 longs should produce 'short' direction with ~0.82 agreement."""
    analyses = {}
    for i in range(9):
        analyses[f"expert:x:agent_{i:02d}"] = {"direction": "short"}
    for i in range(2):
        analyses[f"expert:y:agent_{i:02d}"] = {"direction": "long"}

    result = ConsensusExtractor.extract(analyses)

    assert result.direction == "short"
    assert result.agreement_pct == pytest.approx(9 / 11, abs=0.01)
    assert result.long_count == 2
    assert result.short_count == 9
    assert result.reliability == "DEGRADED"  # 11 experts, <12
