"""ConsensusExtractor — pure Python aggregation of Expert shadow directions.

The ONLY cross-shadow communication allowed (R0 rule). Extracts direction
labels + agreement percentages from Expert shadow analyses. Does NOT pass
any individual shadow's analysis content — only aggregated statistics.

Used by Fade Master to determine when consensus is too crowded.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConsensusResult:
    """Aggregated direction consensus from Expert shadow analyses.

    Attributes:
        direction: "long", "short", or "mixed"
        agreement_pct: Fraction of total shadows in the majority direction (0.0-1.0)
        expert_count: Total number of Expert shadows that provided analyses
        long_count: Number of Expert shadows with "long" direction
        short_count: Number of Expert shadows with "short" direction
        abstain_count: Number of Expert shadows that abstained
        reliability: "FULL" (>=12 experts), "DEGRADED" (8-11), "SKIP" (<8)
    """
    direction: str          # "long", "short", "mixed"
    agreement_pct: float    # 0.0-1.0
    expert_count: int
    long_count: int
    short_count: int
    abstain_count: int = 0
    reliability: str = "SKIP"  # "FULL", "DEGRADED", "SKIP"


class ConsensusExtractor:
    """R0: the ONLY cross-shadow communication mechanism.

    Extracts direction consensus from Expert shadow analyses without
    revealing any individual shadow's analysis content. Output is
    purely statistical — which direction the experts favor and
    how strongly they agree.

    PICA-Logical: This module enforces the R0 isolation rule.
    No shadow receives another's analysis; only aggregated statistics
    are available to the Fade Master.
    """

    _RELIABILITY_FULL_THRESHOLD = 12
    _RELIABILITY_DEGRADED_THRESHOLD = 8
    _AGREEMENT_TIE_MARGIN = 0.05  # within 5% = "mixed"

    @staticmethod
    def extract(shadow_analyses: dict[str, dict]) -> ConsensusResult:
        """Compute direction consensus from Expert shadow analyses.

        Args:
            shadow_analyses: Dict mapping shadow_id -> analysis dict.
                Each analysis dict must have at least a "direction" key
                with value "long", "short", or "abstain".

        Returns:
            ConsensusResult with aggregated direction statistics.
            If no analyses provided, returns an empty result with
            direction="mixed" and reliability="SKIP".

        Raises:
            TypeError: If shadow_analyses is not a dict.
            ValueError: If an analysis dict has an invalid direction.
        """
        if not isinstance(shadow_analyses, dict):
            raise TypeError(
                f"shadow_analyses must be dict, got {type(shadow_analyses).__name__}"
            )

        if not shadow_analyses:
            return ConsensusResult(
                direction="mixed",
                agreement_pct=0.0,
                expert_count=0,
                long_count=0,
                short_count=0,
                abstain_count=0,
                reliability="SKIP",
            )

        _VALID_DIRECTIONS = {"long", "short", "abstain"}
        long_count = 0
        short_count = 0
        abstain_count = 0
        total = 0

        for shadow_id, analysis in shadow_analyses.items():
            if analysis is None:
                continue
            if not isinstance(analysis, dict):
                raise TypeError(
                    f"Analysis for '{shadow_id}' must be dict, "
                    f"got {type(analysis).__name__}"
                )
            direction = analysis.get("direction", "abstain")
            if direction not in _VALID_DIRECTIONS:
                raise ValueError(
                    f"Invalid direction '{direction}' for '{shadow_id}'. "
                    f"Must be one of {_VALID_DIRECTIONS}"
                )
            total += 1
            if direction == "long":
                long_count += 1
            elif direction == "short":
                short_count += 1
            else:
                abstain_count += 1

        if total == 0:
            return ConsensusResult(
                direction="mixed",
                agreement_pct=0.0,
                expert_count=0,
                long_count=0,
                short_count=0,
                abstain_count=0,
                reliability="SKIP",
            )

        # Determine majority direction
        decisive_count = long_count + short_count
        if decisive_count == 0:
            # All abstained
            return ConsensusResult(
                direction="mixed",
                agreement_pct=0.0,
                expert_count=total,
                long_count=0,
                short_count=0,
                abstain_count=abstain_count,
                reliability=_compute_reliability(total),
            )

        long_pct = long_count / total if total > 0 else 0.0
        short_pct = short_count / total if total > 0 else 0.0

        # Determine direction with tie-breaking
        if abs(long_pct - short_pct) <= ConsensusExtractor._AGREEMENT_TIE_MARGIN:
            direction = "mixed"
            agreement_pct = max(long_pct, short_pct)
        elif long_pct > short_pct:
            direction = "long"
            agreement_pct = long_pct
        else:
            direction = "short"
            agreement_pct = short_pct

        return ConsensusResult(
            direction=direction,
            agreement_pct=round(agreement_pct, 4),
            expert_count=total,
            long_count=long_count,
            short_count=short_count,
            abstain_count=abstain_count,
            reliability=_compute_reliability(total),
        )


def _compute_reliability(expert_count: int) -> str:
    """Map expert count to reliability tier."""
    if expert_count >= ConsensusExtractor._RELIABILITY_FULL_THRESHOLD:
        return "FULL"
    elif expert_count >= ConsensusExtractor._RELIABILITY_DEGRADED_THRESHOLD:
        return "DEGRADED"
    return "SKIP"
