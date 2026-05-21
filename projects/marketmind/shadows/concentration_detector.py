"""Concentration detector -- monitors shadow input/output homogenization.

Renamed from CollusionDetector per final plan decision #11.

Detects three forms of concentration risk:
1. Direction concentration: >80% of shadows agree on same direction (3 consecutive days = warning)
   Regime-aware thresholds: RANGE_BOUND=70%, TRENDING=80%, CHOPPY=95%, VIX>35=95%
2. Source homogenization: >=50% shadows share same dominant data source (BlackRock warning)
3. Methodology convergence: semantic similarity between shadow methodology prompts

Phase E Module 3 — Integration layer.
"""
from __future__ import annotations

import logging
import math
from statistics import mean, stdev
from typing import Optional

logger = logging.getLogger("marketmind.shadows.concentration_detector")

# ── Regime-aware direction concentration thresholds ───────────────────────
REGIME_THRESHOLDS = {
    "RANGE_BOUND": 0.70,
    "TRENDING": 0.80,
    "TRANSITIONAL": 0.75,
    "CHOPPY": 0.95,
    "VIX_SPIKE": 0.95,  # VIX > 35
}

DEFAULT_DIRECTION_THRESHOLD = 0.80
CONSECUTIVE_DAYS_WARNING = 3

# ── BlackRock crowding warning threshold ──────────────────────────────────
SOURCE_HOMOGENIZATION_THRESHOLD = 0.50  # >=50% = warning

# ── Methodology convergence ───────────────────────────────────────────────
METHODOLOGY_SIMILARITY_WARN = 0.7
METHODOLOGY_SIMILARITY_ESCALATE = 0.85


class ConcentrationDetector:
    """Monitor shadow input/output homogenization risk.

    Three detection dimensions:
    1. Direction concentration — lockstep agreement risk
    2. Source homogenization — BlackRock crowding warning
    3. Methodology convergence — shared thinking patterns

    The detector is regime-aware: thresholds adjust based on market regime
    because high agreement is normal in trending markets but suspicious in
    range-bound markets.
    """

    def __init__(self, state_db):
        """Initialize with a database connection for persistence.

        Args:
            state_db: ShadowStateDB instance for querying shadow data,
                      fingerprints, and analysis history.
        """
        self.state_db = state_db
        # Track consecutive days of high agreement per ticker
        self._consecutive_days: dict[str, int] = {}

    # ── Direction Concentration ──────────────────────────────────────────────

    def detect_direction_concentration(
        self,
        analyses: list[dict],
        regime: str = "TRENDING",
        vix_level: Optional[float] = None,
    ) -> dict:
        """Check if shadow analyses show direction concentration.

        Flags when the proportion of shadows agreeing on the same direction
        exceeds the regime-aware threshold for 3 consecutive days.

        Args:
            analyses: List of dicts, each with at least:
                - shadow_id: str
                - ticker: str
                - direction: str ("long", "short", "abstain")
            regime: Market regime string. One of "RANGE_BOUND", "TRENDING",
                    "TRANSITIONAL", "CHOPPY". Default "TRENDING".
            vix_level: Current VIX level. If >35, uses VIX_SPIKE threshold.

        Returns:
            Dict with keys:
                - concentration_detected: bool
                - agreement_pct: float (0-100)
                - dominant_direction: str
                - threshold_used: float
                - excessive: bool (True if agreement exceeds threshold)
                - warning_message: str or None
        """
        if not analyses:
            return {
                "concentration_detected": False,
                "agreement_pct": 0.0,
                "dominant_direction": "none",
                "threshold_used": DEFAULT_DIRECTION_THRESHOLD,
                "excessive": False,
                "warning_message": None,
            }

        # Determine threshold
        if vix_level is not None and vix_level > 35:
            threshold = REGIME_THRESHOLDS["VIX_SPIKE"]
        else:
            threshold = REGIME_THRESHOLDS.get(regime, DEFAULT_DIRECTION_THRESHOLD)

        # Count directions
        long_count = sum(1 for a in analyses if a.get("direction") == "long")
        short_count = sum(1 for a in analyses if a.get("direction") == "short")
        abstain_count = sum(1 for a in analyses if a.get("direction") == "abstain")
        total = len(analyses)

        non_abstaining = long_count + short_count
        if non_abstaining == 0:
            agreement_pct = 0.0
            dominant_direction = "abstain"
        elif long_count >= short_count:
            agreement_pct = (long_count / non_abstaining) * 100.0
            dominant_direction = "long"
        else:
            agreement_pct = (short_count / non_abstaining) * 100.0
            dominant_direction = "short"

        excessive = (agreement_pct / 100.0) >= threshold

        # Track consecutive days
        ticker = analyses[0].get("ticker", "global") if analyses else "global"
        prev = self._consecutive_days.get(ticker, 0)

        if excessive:
            self._consecutive_days[ticker] = prev + 1
            consecutive = prev + 1
        else:
            self._consecutive_days[ticker] = 0
            consecutive = 0

        concentration_detected = excessive and consecutive >= CONSECUTIVE_DAYS_WARNING

        warning_message = None
        if concentration_detected:
            direction_pct = agreement_pct
            warning_message = (
                f"CONCENTRATION WARNING: {direction_pct:.1f}% of shadows agree on "
                f"'{dominant_direction}' for {consecutive} consecutive days. "
                f"(Regime: {regime}, Threshold: {threshold:.0%}, "
                f"VIX: {vix_level or 'N/A'})"
            )
            logger.warning(warning_message)

        return {
            "concentration_detected": concentration_detected,
            "agreement_pct": round(agreement_pct, 1),
            "dominant_direction": dominant_direction,
            "threshold_used": threshold,
            "threshold_pct": round(threshold * 100, 0),
            "consecutive_days": consecutive,
            "excessive": excessive,
            "warning_message": warning_message,
        }

    # ── Source Homogenization ────────────────────────────────────────────────

    def detect_source_homogenization(self, fingerprints: list) -> bool:
        """BlackRock warning: >=50% shadows share same dominant data source.

        A dominant source is the source with the highest weight in a shadow's
        fingerprint. If half or more shadows all rely on the same dominant source,
        the ecosystem has a single-source dependency risk.

        Args:
            fingerprints: List of dicts, each with at least:
                - shadow_id: str
                - source_weights: dict[str, float] mapping source name to weight
                  OR
                - primary_sources: list[str] of this shadow's primary sources

        Returns:
            True if BlackRock crowding warning is triggered (>=50% share same
            dominant source), False otherwise.
        """
        if len(fingerprints) < 2:
            return False

        # Extract dominant source per shadow
        source_counts: dict[str, int] = {}

        for fp in fingerprints:
            dominant = self._extract_dominant_source(fp)
            if dominant:
                source_counts[dominant] = source_counts.get(dominant, 0) + 1

        n_shadows = len(fingerprints)
        for source, count in source_counts.items():
            if count / n_shadows >= SOURCE_HOMOGENIZATION_THRESHOLD:
                logger.warning(
                    "BLACKROCK CROWDING WARNING: %d/%d (%.0f%%) shadows share "
                    "dominant data source '%s'. Threshold: %.0f%%",
                    count, n_shadows, count / n_shadows * 100,
                    source, SOURCE_HOMOGENIZATION_THRESHOLD * 100,
                )
                return True

        return False

    # ── Methodology Convergence ──────────────────────────────────────────────

    def detect_methodology_convergence(self, prompts: list[str]) -> float:
        """Semantic similarity between shadow methodology prompts.

        Computes a simple word-overlap similarity metric between methodology
        prompts. High similarity (>0.7) suggests shadows are converging on
        the same thinking patterns, reducing ecosystem diversity.

        Uses Jaccard similarity on tokenized methodology prompts. This is a
        lightweight, fast approximation — for production, this should be
        replaced with embedding-based cosine similarity.

        Args:
            prompts: List of methodology prompt strings, one per shadow.

        Returns:
            Maximum pairwise similarity score in [0.0, 1.0].
            Returns 0.0 if fewer than 2 prompts.
        """
        if len(prompts) < 2:
            return 0.0

        tokenized = [self._tokenize_prompt(p) for p in prompts]
        max_similarity = 0.0

        for i in range(len(tokenized)):
            for j in range(i + 1, len(tokenized)):
                sim = self._jaccard_similarity(tokenized[i], tokenized[j])
                if sim > max_similarity:
                    max_similarity = sim

        if max_similarity >= METHODOLOGY_SIMILARITY_ESCALATE:
            logger.warning(
                "METHODOLOGY CONVERGENCE ESCALATION: max pairwise similarity "
                "= %.4f (threshold: %.2f). Shadow thinking patterns are "
                "converging dangerously.",
                max_similarity, METHODOLOGY_SIMILARITY_ESCALATE,
            )
        elif max_similarity >= METHODOLOGY_SIMILARITY_WARN:
            logger.info(
                "Methodology convergence warning: max similarity = %.4f "
                "(threshold: %.2f). Monitor for further convergence.",
                max_similarity, METHODOLOGY_SIMILARITY_WARN,
            )

        return round(max_similarity, 4)

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_dominant_source(fingerprint: dict) -> Optional[str]:
        """Extract the dominant data source from a fingerprint.

        Args:
            fingerprint: Dict with source_weights (dict) or primary_sources (list).

        Returns:
            Name of the highest-weighted source, or None if indeterminate.
        """
        # Prefer primary_sources if available
        primary = fingerprint.get("primary_sources", [])
        if primary and isinstance(primary, list) and len(primary) > 0:
            return primary[0]

        # Fall back to source_weights
        weights = fingerprint.get("source_weights", {})
        if not weights:
            return None

        max_source = None
        max_weight = -1.0
        for src, w in weights.items():
            if w > max_weight:
                max_weight = w
                max_source = src
        return max_source

    @staticmethod
    def _tokenize_prompt(text: str) -> set[str]:
        """Tokenize a methodology prompt into a set of lowercase tokens.

        Strips punctuation, lowercases, and splits on whitespace.
        Filters tokens shorter than 3 characters to reduce noise.

        Args:
            text: Raw methodology prompt text.

        Returns:
            Set of lowercase word tokens.
        """
        import re
        # Strip common prompt template markers
        text = re.sub(r'[\[\]\{\}\(\)"\'`#*_~]', ' ', text)
        tokens = text.lower().split()
        # Filter short tokens and pure numbers
        return {
            t for t in tokens
            if len(t) >= 3 and not t.isdigit()
        }

    @staticmethod
    def _jaccard_similarity(a: set, b: set) -> float:
        """Compute Jaccard similarity between two token sets.

        J(A, B) = |A ∩ B| / |A ∪ B|

        Args:
            a, b: Sets of tokens.

        Returns:
            Jaccard similarity in [0.0, 1.0].
        """
        if not a or not b:
            return 0.0
        intersection = a & b
        union = a | b
        return len(intersection) / len(union) if union else 0.0

    # ── Regime classification helper ─────────────────────────────────────────

    @staticmethod
    def classify_regime(
        adx: float,
        amplitude_pct: float,
        consecutive_days: int = 10,
    ) -> str:
        """Classify market regime from ADX and amplitude.

        Uses the hysteresis rule from final plan §15: regime changes require
        10 consecutive days of the new condition.

        Args:
            adx: Average Directional Index value.
            amplitude_pct: Daily amplitude as percentage of price.
            consecutive_days: Days the condition has persisted (default 10).

        Returns:
            One of "TRENDING", "RANGE_BOUND", "TRANSITIONAL", "CHOPPY".
        """
        if adx >= 30 and consecutive_days >= 10:
            return "TRENDING"
        elif adx < 20 and amplitude_pct < 1.5 and consecutive_days >= 10:
            return "RANGE_BOUND"
        elif adx < 20 and amplitude_pct >= 1.5:
            return "CHOPPY"
        else:
            return "TRANSITIONAL"
