"""
paradigm_anchors.py — Three Macro Anchors derived from 2026 Investment Paradigm

Phase 7.4 (Layer 3) sub-module.
Maps the three macro anchors defined in the 2026 investment paradigm document
(fiscal credibility, geopolitical GII, reflexivity RAC) into runtime state
judgments, producing a hard multiplier [0.0, 0.85, 1.0] via MIN-rule.

Blueprint §1.3 — PM-approved YELLOW = 0.85 (not 0.70).
"""

from __future__ import annotations

from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Anchor State
# ---------------------------------------------------------------------------

class AnchorState(Enum):
    """Three-state anchor judgment.

    GREEN  = 1.0  — Normal exposure
    YELLOW = 0.85 — Caps position to 85% of nominal (PM-approved: not 0.70)
    RED    = 0.0  — Zero exposure / force clearout
    UNKNOWN       — Data insufficient; conservative fallback to YELLOW
    """

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"


_ANCHOR_MULTIPLIER: dict[AnchorState, float] = {
    AnchorState.GREEN: 1.0,
    AnchorState.YELLOW: 0.85,
    AnchorState.RED: 0.0,
    AnchorState.UNKNOWN: 0.85,  # Conservative: treat unknown as YELLOW
}


# ---------------------------------------------------------------------------
# ThreeAnchors — runtime container
# ---------------------------------------------------------------------------

class ThreeAnchors:
    """The three macro anchors of the 2026 investment paradigm.

    Attributes:
        fiscal_credibility: Anchor for fiscal trustworthiness (CDS spreads,
            primary dealer absorption rate).
        geopolitical_gii:   Anchor for Geopolitical Instability Index
            (BDI trend, AI-GPR monthly delta, crude oil option skew).
        reflexivity_rac:    Anchor for Reflexivity — Asset-Chain coupling
            (IAU money-flow vs price correlation, GDX relative strength).
        fiscal_evidence:    Human-readable evidence string for anchor one.
        gii_evidence:       Human-readable evidence string for anchor two.
        rac_evidence:       Human-readable evidence string for anchor three.
    """

    def __init__(
        self,
        fiscal_credibility: AnchorState = AnchorState.UNKNOWN,
        geopolitical_gii: AnchorState = AnchorState.UNKNOWN,
        reflexivity_rac: AnchorState = AnchorState.UNKNOWN,
        fiscal_evidence: str = "",
        gii_evidence: str = "",
        rac_evidence: str = "",
    ) -> None:
        self.fiscal_credibility = fiscal_credibility
        self.geopolitical_gii = geopolitical_gii
        self.reflexivity_rac = reflexivity_rac
        self.fiscal_evidence = fiscal_evidence
        self.gii_evidence = gii_evidence
        self.rac_evidence = rac_evidence

    # ------------------------------------------------------------------
    # Structural equality (for test comparisons)
    # ------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ThreeAnchors):
            return NotImplemented
        return (
            self.fiscal_credibility == other.fiscal_credibility
            and self.geopolitical_gii == other.geopolitical_gii
            and self.reflexivity_rac == other.reflexivity_rac
            and self.fiscal_evidence == other.fiscal_evidence
            and self.gii_evidence == other.gii_evidence
            and self.rac_evidence == other.rac_evidence
        )

    def __repr__(self) -> str:
        return (
            f"ThreeAnchors(fiscal={self.fiscal_credibility.value}, "
            f"gii={self.geopolitical_gii.value}, "
            f"rac={self.reflexivity_rac.value})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fiscal_credibility": self.fiscal_credibility.value,
            "geopolitical_gii": self.geopolitical_gii.value,
            "reflexivity_rac": self.reflexivity_rac.value,
            "fiscal_evidence": self.fiscal_evidence,
            "gii_evidence": self.gii_evidence,
            "rac_evidence": self.rac_evidence,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def anchor_state_multiplier(state: AnchorState) -> float:
    """Return the multiplier for a single anchor state.

    Args:
        state: The anchor state.

    Returns:
        Float multiplier in {0.0, 0.85, 1.0}.
    """
    return _ANCHOR_MULTIPLIER[state]


def compute_paradigm_multiplier(anchors: ThreeAnchors) -> float:
    """Compute the combined paradigm multiplier using MIN-rule.

    MIN-rule rationale (blueprint §1.3):
      The paradigm document emphasises "triple fragility stacking" —
      any single chain breaking triggers systemic risk.  MIN-rule ensures
      the weakest macro dimension dominates position sizing.

    Args:
        anchors: The three macro anchor states.

    Returns:
        Multiplier in {0.0, 0.85, 1.0}.
    """
    multipliers = [
        _ANCHOR_MULTIPLIER[anchors.fiscal_credibility],
        _ANCHOR_MULTIPLIER[anchors.geopolitical_gii],
        _ANCHOR_MULTIPLIER[anchors.reflexivity_rac],
    ]
    return min(multipliers)