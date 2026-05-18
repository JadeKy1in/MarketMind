"""Tests for methodology convergence detection in collusion_detector."""
import pytest
from marketmind.shadows.collusion_detector import (
    detect_methodology_convergence, CATFISH_CONSENSUS_THRESHOLD
)


# ── Methodology convergence: basic detection ────────────────────────────

def test_convergence_detected_with_shared_lineage():
    """Two shadows with shared methodology lineage and high position agreement
    over 5+ days should be flagged."""
    states = [
        {
            "shadow_id": "expert:gold:01",
            "methodology_provenance": ["expert-gold", "fundamental-analysis", "narrative-analysis"],
            "positions": [
                {"AAPL", "GLD", "TLT"},
                {"AAPL", "GLD", "TLT"},
                {"AAPL", "GLD", "TLT"},
                {"AAPL", "GLD", "TLT"},
                {"AAPL", "GLD", "TLT"},
            ],
        },
        {
            "shadow_id": "expert:gold:02",
            "methodology_provenance": ["expert-gold", "fundamental-analysis", "technical-analysis"],
            "positions": [
                {"AAPL", "GLD", "TLT"},
                {"AAPL", "GLD", "TLT"},
                {"AAPL", "GLD", "TLT"},
                {"AAPL", "GLD", "TLT"},
                {"AAPL", "GLD", "TLT"},
            ],
        },
    ]
    warnings = detect_methodology_convergence(states)
    # Shared 2 out of 4 methods → Jaccard = 2/4 = 0.5, meets threshold
    # 100% position agreement over 5 days
    assert len(warnings) >= 1
    assert "methodology" in warnings[0].lower()


def test_no_convergence_without_shared_lineage():
    """Two shadows with NO shared methodology lineage should NOT be flagged,
    even if they agree on positions."""
    states = [
        {
            "shadow_id": "expert:gold:01",
            "methodology_provenance": ["expert-gold"],
            "positions": [
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
            ],
        },
        {
            "shadow_id": "expert:crypto:01",
            "methodology_provenance": ["expert-crypto"],
            "positions": [
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
            ],
        },
    ]
    warnings = detect_methodology_convergence(states)
    # No shared methodology, so no convergence warning
    assert len(warnings) == 0


def test_no_convergence_without_enough_agreement_days():
    """Shared lineage but only 3 days of data (< 5 threshold) should NOT flag."""
    states = [
        {
            "shadow_id": "expert:gold:01",
            "methodology_provenance": ["expert-gold"],
            "positions": [
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
            ],
        },
        {
            "shadow_id": "expert:gold:02",
            "methodology_provenance": ["expert-gold"],
            "positions": [
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
                {"AAPL", "GLD"},
            ],
        },
    ]
    warnings = detect_methodology_convergence(states)
    assert len(warnings) == 0


# ── Jaccard similarity thresholds ────────────────────────────────────────

def test_convergence_escalated_at_high_similarity():
    """Jaccard > 0.8 should produce 'methodology_collusion' escalated warning."""
    states = [
        {
            "shadow_id": "expert:gold:01",
            "methodology_provenance": [
                "expert-gold", "fundamental-analysis", "technical-analysis", "narrative-analysis", "expert-energy"
            ],
            "positions": [
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
            ],
        },
        {
            "shadow_id": "expert:gold:02",
            "methodology_provenance": [
                "expert-gold", "fundamental-analysis", "technical-analysis", "narrative-analysis", "expert-energy", "expert-tech"
            ],
            "positions": [
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ"},
            ],
        },
    ]
    warnings = detect_methodology_convergence(states)
    # Jaccard = 5/6 ≈ 0.833 > 0.8 → "methodology_collusion" (escalated)
    assert len(warnings) >= 1
    assert "ESCALATED" in warnings[0]


def test_empty_provenance_no_flag():
    """Shadows with empty methodology_provenance should not trigger convergence."""
    states = [
        {
            "shadow_id": "expert:new:01",
            "methodology_provenance": [],
            "positions": [
                {"AAPL"}, {"AAPL"}, {"AAPL"}, {"AAPL"}, {"AAPL"},
            ],
        },
        {
            "shadow_id": "expert:new:02",
            "methodology_provenance": [],
            "positions": [
                {"AAPL"}, {"AAPL"}, {"AAPL"}, {"AAPL"}, {"AAPL"},
            ],
        },
    ]
    warnings = detect_methodology_convergence(states)
    assert len(warnings) == 0


# ── Partial agreement ────────────────────────────────────────────────────

def test_partial_position_agreement_below_threshold():
    """When position overlap is below 80%, should NOT flag even with shared lineage."""
    states = [
        {
            "shadow_id": "expert:gold:01",
            "methodology_provenance": ["expert-gold"],
            "positions": [
                {"AAPL", "GLD", "TLT", "SPY", "QQQ", "IWM", "XLE", "XLF", "XLV", "XLI"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ", "IWM", "XLE", "XLF", "XLV", "XLI"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ", "IWM", "XLE", "XLF", "XLV", "XLI"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ", "IWM", "XLE", "XLF", "XLV", "XLI"},
                {"AAPL", "GLD", "TLT", "SPY", "QQQ", "IWM", "XLE", "XLF", "XLV", "XLI"},
            ],
        },
        {
            "shadow_id": "expert:gold:02",
            "methodology_provenance": ["expert-gold"],
            "positions": [
                {"AAPL"},           # overlap 1/10 = 10%
                {"AAPL"},           # overlap 1/10 = 10%
                {"AAPL"},           # overlap 1/10 = 10%
                {"AAPL"},           # overlap 1/10 = 10%
                {"AAPL"},           # overlap 1/10 = 10%
            ],
        },
    ]
    warnings = detect_methodology_convergence(states)
    # 10% overlap < 80% threshold
    assert len(warnings) == 0


# ── Single shadow edge case ──────────────────────────────────────────────

def test_single_shadow_no_convergence():
    """A single shadow cannot converge with itself."""
    states = [
        {
            "shadow_id": "expert:solo:01",
            "methodology_provenance": ["expert-gold"],
            "positions": [{"AAPL"}] * 10,
        },
    ]
    warnings = detect_methodology_convergence(states)
    assert len(warnings) == 0


# ── Catfish consensus threshold ──────────────────────────────────────────

def test_catfish_consensus_threshold_value():
    """CATFISH_CONSENSUS_THRESHOLD should be 0.60 (lowered from 0.80)."""
    assert CATFISH_CONSENSUS_THRESHOLD == 0.60


def test_catfish_threshold_reason():
    """With Phase I knowledge distillation, earlier catfish intervention is needed."""
    assert CATFISH_CONSENSUS_THRESHOLD < 0.80
    # Exactly 0.60 as specified in the architecture plan
    assert CATFISH_CONSENSUS_THRESHOLD == pytest.approx(0.60)
