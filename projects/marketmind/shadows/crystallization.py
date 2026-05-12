"""Crystallization Engine -- Knowledge crystallization: insight → hypothesis → validate → promote/retire.

Inner loop: Collect insights from shadow memory → formalize hypothesis →
            tweak methodology → backtest validate against shadow_votes
Outer loop: Track methodology performance → significance gate →
            promote to semantic memory or retire
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from marketmind.shadows.shadow_state import ShadowStateDB
from marketmind.shadows.shadow_memory import ShadowMemoryStore
from marketmind.shadows.methodology_evolver import MethodologyEvolver
from marketmind.shadows.shadow_agent import CrystallizationResult

logger = logging.getLogger("marketmind.shadows.crystallization")


def _auto_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _auto_uuid() -> str:
    return str(uuid.uuid4())


class CrystallizationEngine:
    """Knowledge crystallization engine for the shadow ecosystem.

    Inner loop: Collect insights from episodic memory → formalize hypothesis →
                tweak methodology → backtest validate against shadow_votes.

    Outer loop: Track methodology performance → significance gate →
                promote to semantic memory or retire.
    """

    def __init__(
        self,
        memory_store: ShadowMemoryStore,
        state_db: ShadowStateDB,
        methodology_evolver: MethodologyEvolver,
        significance_threshold: float = 0.6,
        min_samples: int = 10,
    ) -> None:
        self._memory = memory_store
        self._db = state_db
        self._evolver = methodology_evolver
        self._significance_threshold = significance_threshold
        self._min_samples = min_samples

        # Track stats
        self._cycles_run: int = 0
        self._promotions: int = 0
        self._retirements: int = 0
        self._skipped_cold_start: int = 0

    # -- Public API ---------------------------------------------------------

    async def run_crystallization_cycle(self) -> list[CrystallizationResult]:
        """Run full inner+outer loop. Returns list of crystallization results.

        Queries episodic memory for high-belief but uncertain insights, runs
        inner loop (backtest validation) for each, then applies outer loop
        (significance gate: promote or retire).
        """
        self._cycles_run += 1
        results: list[CrystallizationResult] = []

        # Query episodic memory for candidate insights
        candidates = self._get_candidate_insights()
        logger.info(
            "Crystallization cycle %d: %d candidate insights from episodic memory",
            self._cycles_run, len(candidates),
        )

        for candidate in candidates:
            node_id = candidate.get("node_id", "")
            result = await self._inner_loop(node_id)
            if result is not None:
                # Apply outer loop significance gate
                promoted = self._outer_loop(result)
                if promoted:
                    self._promotions += 1
                elif result.action == "retire":
                    self._retirements += 1
                results.append(result)

        return results

    async def _inner_loop(self, insight_node_id: str) -> Optional[CrystallizationResult]:
        """Single insight → hypothesis → methodology tweak → backtest validate.

        Args:
            insight_node_id: The belief node ID from episodic memory.

        Returns:
            CrystallizationResult with validation_score and action, or None if
            insufficient data (cold start).
        """
        # Get the belief node
        node = self._memory.get_belief_node(insight_node_id)
        if node is None:
            logger.debug("Belief node %s not found, skipping", insight_node_id)
            return None

        proposition = node.get("proposition", "")
        expectation = node.get("expectation", 0.5)
        uncertainty = node.get("uncertainty", 1.0)
        obs_count = node.get("observation_count", 0)

        # Extract shadow_id and ticker/domain from proposition
        shadow_id, ticker = self._parse_proposition(proposition)

        # Formalize hypothesis from the belief
        hypothesis = self._formalize_hypothesis(proposition, expectation, uncertainty)

        # Backtest validate against shadow_votes
        validation_score, sample_count, evidence_lines = self._backtest_validate(
            shadow_id, ticker, expectation
        )

        # Cold start guard
        if sample_count < self._min_samples:
            self._skipped_cold_start += 1
            logger.debug(
                "Cold start: insight %s has only %d samples (< %d), skipping",
                insight_node_id, sample_count, self._min_samples,
            )
            return CrystallizationResult(
                insight_id=insight_node_id,
                hypothesis=hypothesis,
                validation_score=validation_score,
                action="hold",
                methodology_changes=[],
                source_insight_ids=[insight_node_id],
                evidence_summary=f"Insufficient data: {sample_count}/{self._min_samples} minimum samples",
            )

        # Determine action based on validation score
        action = "hold"
        methodology_changes: list[str] = []
        if validation_score >= self._significance_threshold:
            action = "promote"
            method_id = self._derive_method_id(shadow_id, ticker)
            self._evolver.record_prediction(method_id, True, prediction_id=insight_node_id)
            methodology_changes.append(
                f"Promoted: {proposition} with score {validation_score:.2f}"
            )
        elif validation_score < 0.4:
            action = "retire"
            method_id = self._derive_method_id(shadow_id, ticker)
            self._evolver.record_prediction(method_id, False, prediction_id=insight_node_id)
            methodology_changes.append(
                f"Retiring: {proposition} with score {validation_score:.2f}"
            )
        else:
            # Hold: record the prediction but don't take action
            method_id = self._derive_method_id(shadow_id, ticker)
            self._evolver.record_prediction(method_id, validation_score >= 0.5, prediction_id=insight_node_id)

        evidence_summary = (
            f"Backtest: {validation_score:.2f} hit_rate over {sample_count} samples. "
            + "; ".join(evidence_lines[:3])
        )

        return CrystallizationResult(
            insight_id=_auto_uuid(),
            hypothesis=hypothesis,
            validation_score=validation_score,
            action=action,
            methodology_changes=methodology_changes,
            source_insight_ids=[insight_node_id],
            evidence_summary=evidence_summary,
        )

    def _outer_loop(self, result: CrystallizationResult) -> bool:
        """Check if result meets significance gate. Promote or retire.

        Returns:
            True if the insight was promoted to semantic memory.
        """
        if result.action == "promote":
            # Promote all source insights to semantic memory
            for source_id in result.source_insight_ids:
                self.promote_to_semantic(source_id)
            return True
        elif result.action == "retire":
            for source_id in result.source_insight_ids:
                self.retire_insight(
                    source_id,
                    f"Failed significance gate: score {result.validation_score:.2f} < 0.4"
                )
            return False
        return False

    # -- Semantic memory operations -----------------------------------------

    def promote_to_semantic(self, insight_id: str) -> bool:
        """Promote an insight/belief node to semantic memory (no TTL)."""
        return self._memory.promote_to_semantic(insight_id)

    def retire_insight(self, insight_id: str, reason: str) -> bool:
        """Retire an insight/belief node."""
        return self._memory.retire_belief(insight_id, reason)

    # -- Stats --------------------------------------------------------------

    def get_crystallization_stats(self) -> dict[str, Any]:
        """Get statistics about crystallization cycles."""
        return {
            "cycles_run": self._cycles_run,
            "promotions": self._promotions,
            "retirements": self._retirements,
            "skipped_cold_start": self._skipped_cold_start,
            "significance_threshold": self._significance_threshold,
            "min_samples": self._min_samples,
        }

    # -- Internal helpers ---------------------------------------------------

    def _get_candidate_insights(self) -> list[dict[str, Any]]:
        """Query episodic memory for insights with high belief strength but high uncertainty.

        These are insights that the shadow agents believe in strongly (high expectation)
        but the system has low confidence in (high uncertainty) -- prime candidates
        for crystallization (validation or retirement).
        """
        conn = self._db._connect()
        try:
            # Query active belief nodes in episodic tier with:
            # - high expectation (> 0.6) but low confidence (< 0.5)
            # - at least 3 observations
            rows = conn.execute(
                """SELECT node_id, proposition, alpha, beta,
                   created_at, updated_at, observation_count
                   FROM (
                       SELECT n.node_id, n.proposition, n.alpha, n.beta,
                          n.created_at, n.updated_at,
                          (SELECT COUNT(*) FROM belief_observations o
                           WHERE o.node_id = n.node_id) AS observation_count
                       FROM belief_nodes n
                       WHERE n.status = 'active'
                         AND n.tier = 'episodic'
                   ) sub
                   WHERE observation_count >= 3
                   ORDER BY updated_at DESC
                   LIMIT 50"""
            ).fetchall()

            from marketmind.shadows.belief_math import (
                beta_expectation, beta_uncertainty, confidence_score,
            )

            candidates = []
            for row in rows:
                alpha = row["alpha"]
                beta = row["beta"]
                exp = beta_expectation(alpha, beta)
                unc = beta_uncertainty(alpha, beta)
                conf = confidence_score(alpha, beta)

                # Select: high belief (expectation away from 0.5) but low confidence
                belief_strength = abs(exp - 0.5) * 2  # 0-1 scale
                if belief_strength >= 0.3 and conf < 0.6:
                    candidates.append({
                        "node_id": row["node_id"],
                        "proposition": row["proposition"],
                        "alpha": alpha,
                        "beta": beta,
                        "expectation": exp,
                        "uncertainty": unc,
                        "confidence": conf,
                        "observation_count": row["observation_count"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    })

            return candidates
        finally:
            conn.close()

    def _backtest_validate(
        self, shadow_id: str, ticker: str, expectation: float
    ) -> tuple[float, int, list[str]]:
        """Backtest validate a hypothesis against historical shadow_votes.

        Queries the shadow_votes table for this shadow on this ticker,
        compares vote direction against actual outcomes (from virtual_trades PnL).

        Args:
            shadow_id: The shadow that generated the insight.
            ticker: The ticker the insight is about.
            expectation: The expected outcome probability (0-1).

        Returns:
            Tuple of (hit_rate, sample_count, evidence_lines).
        """
        conn = self._db._connect()
        try:
            # Get all votes for this shadow on this ticker
            votes = conn.execute(
                """SELECT sv.date, sv.direction, sv.confidence
                   FROM shadow_votes sv
                   WHERE sv.shadow_id = ? AND sv.ticker = ?
                   ORDER BY sv.date ASC""",
                (shadow_id, ticker),
            ).fetchall()

            from marketmind.shadows.belief_math import confidence_score

            sample_count = len(votes)
            if sample_count == 0:
                return 0.0, 0, ["No vote data available for backtest"]

            hits = 0
            evidence_lines: list[str] = []

            for vote in votes:
                vote_date = vote["date"]
                direction = vote["direction"]
                vote_confidence = vote["confidence"]

                if direction == "abstain":
                    continue

                # Get actual next-day return sign for this ticker
                actual_sign = self._db.get_next_day_return_sign(ticker, vote_date)

                if actual_sign is None:
                    continue

                # A vote is correct if:
                # - long vote + positive return → hit
                # - short vote + negative return → hit
                vote_correct = (
                    (direction == "long" and actual_sign == 1) or
                    (direction == "short" and actual_sign == -1)
                )
                if vote_correct:
                    hits += 1
                evidence_lines.append(
                    f"{vote_date}: {direction} vote (conf={vote_confidence:.2f}) "
                    f"→ {'CORRECT' if vote_correct else 'wrong'} (actual={'up' if actual_sign == 1 else 'down'})"
                )

            valid_samples = sum(1 for v in votes if v["direction"] != "abstain")
            hit_rate = hits / valid_samples if valid_samples > 0 else 0.0

            return hit_rate, valid_samples, evidence_lines
        finally:
            conn.close()

    @staticmethod
    def _parse_proposition(proposition: str) -> tuple[str, str]:
        """Parse shadow_id and ticker from a belief proposition string.

        Proposition format: "shadow:{shadow_id}:ticker:{TICKER}" or
                          "shadow:{shadow_id}:source:{source_type}"

        Handles multi-part shadow IDs (e.g., "shadow:expert:gold:agent_01:ticker:AAPL").

        Returns:
            Tuple of (shadow_id, ticker). ticker may be empty string.
        """
        ticker = ""
        shadow_id = ""

        # Extract ticker if present: find ":ticker:" and take everything after it
        ticker_idx = proposition.find(":ticker:")
        if ticker_idx >= 0:
            ticker = proposition[ticker_idx + len(":ticker:"):]
            # Truncate proposition at ticker marker for shadow_id extraction
            remainder = proposition[:ticker_idx]
        else:
            # Try source marker
            source_idx = proposition.find(":source:")
            if source_idx >= 0:
                remainder = proposition[:source_idx]
            else:
                remainder = proposition

        # Extract shadow_id: everything after the first "shadow:"
        if remainder.startswith("shadow:"):
            shadow_id = remainder[len("shadow:"):]

        return shadow_id, ticker

    @staticmethod
    def _formalize_hypothesis(
        proposition: str, expectation: float, uncertainty: float
    ) -> str:
        """Formalize a testable hypothesis from a belief proposition.

        Args:
            proposition: The belief proposition string.
            expectation: Beta distribution expectation (0-1).
            uncertainty: Beta distribution uncertainty (0-1).

        Returns:
            A human-readable hypothesis string.
        """
        direction = "outperform" if expectation >= 0.5 else "underperform"
        confidence_label = "low" if uncertainty > 0.5 else "moderate"
        return (
            f"Hypothesis: Assets linked to '{proposition}' will {direction} "
            f"the market (E[belief]={expectation:.2f}, uncertainty={uncertainty:.2f}, "
            f"confidence={confidence_label}). Testable via shadow_votes backtest."
        )

    @staticmethod
    def _derive_method_id(shadow_id: str, ticker: str) -> str:
        """Derive a method ID from shadow_id and ticker for methodology tracking.

        Maps shadow types to their corresponding methodology categories.
        """
        if "expert:gold" in shadow_id:
            return "expert-gold"
        elif "expert:crypto" in shadow_id:
            return "expert-crypto"
        elif "expert:tech" in shadow_id:
            return "expert-tech"
        elif "expert:energy" in shadow_id:
            return "expert-energy"
        elif "expert:healthcare" in shadow_id:
            return "expert-healthcare"
        elif "expert:realestate" in shadow_id or "expert:real_estate" in shadow_id:
            return "expert-realestate"
        elif "daredevil" in shadow_id:
            if "scalp" in shadow_id:
                return "daredevil-scalper"
            elif "trend" in shadow_id:
                return "daredevil-trend-rider"
            elif "news" in shadow_id:
                return "daredevil-news-hound"
            elif "fade" in shadow_id:
                return "daredevil-fade-master"
            elif "rotation" in shadow_id:
                return "daredevil-rotation"
            return "daredevil-scalper"
        elif "catfish" in shadow_id:
            return "catfish-contrarian"
        elif ticker:
            return "fundamental-analysis"
        else:
            return "narrative-analysis"
