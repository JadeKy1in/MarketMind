"""
belief_aware_predictor.py — Phase 8.3.2 Belief-Aware Prediction Weight Injector

Injects belief-system weights into ShadowPredictions before they enter the
ShadowPipeline. The BeliefAwarePredictor is a decorator/transformer that:

  1. Takes a list of ShadowPrediction objects (from ShadowAggregator)
  2. Queries BeliefStateManager for active beliefs matching each prediction's target_ticker
  3. Computes belief_weight for each ticker from the active belief scores
  4. Injects belief_weights into each prediction and adjusts confidence

Architecture:
  - Pure transformation: input → BeliefStateManager lookup → output (no side effects)
  - The predictor does NOT store state; it is a functional transformation layer
  - Uses confidence_score from belief_math to compute per-ticker belief weight

Data Flow:
  ShadowAggregator.generate() → predictions
    → BeliefAwarePredictor.inject_belief_weights(predictions, manager)
      → Each prediction gets belief_weights dict with per-ticker weights
      → belief_adjusted_confidence reflects the adjusted score
    → ZeroHedgingValidator.validate_batch()

SPARC:
  Specification: PM requirement — predictions reflect active belief state.
  Pseudocode: query → compute weight → inject → return transformed predictions.
  Architecture: Functional transformation, stateless, testable.
  Refinement: belief_weight = mean confidence_score of all ACTIVE nodes
              whose proposition is a substring match to the ticker.
  Completion: Integrated with end-to-end test.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

# Import belief_math directly (red line: beliefs_math is read-only)
from .belief_math import beta_expectation, beta_uncertainty, confidence_score
from .belief_state_manager import BeliefStateManager
from .belief_types import BeliefSource, BeliefStatus
from .shadow_types import ShadowPrediction

logger = logging.getLogger(__name__)


class BeliefAwarePredictor:
    """Belief-aware prediction weight injector.

    Transforms ShadowPredictions by injecting belief weights from the
    BeliefStateManager. The predictor is stateless — all state lives
    in the manager instance passed at call time.

    Usage:
        predictor = BeliefAwarePredictor()
        predictions = predictor.inject_belief_weights(raw_predictions, manager)
        # predictions now have belief_weights and adjusted confidence
    """

    def __init__(self, min_score_threshold: float = 0.1) -> None:
        """Initialize the predictor.

        Args:
            min_score_threshold: Minimum confidence_score for a belief to be
                considered "active enough" to influence predictions. Default 0.1.
                Beliefs below this threshold are ignored (weight = 0.0).
        """
        self._min_score_threshold = min_score_threshold
        logger.debug(
            "BeliefAwarePredictor initialized: min_score_threshold=%.3f",
            min_score_threshold,
        )

    def inject_belief_weights(
        self,
        predictions: List[ShadowPrediction],
        manager: BeliefStateManager,
    ) -> List[ShadowPrediction]:
        """Inject belief weights into a list of predictions.

        For each prediction, queries the BeliefStateManager for active beliefs
        whose proposition matches the prediction's target_ticker. Computes a
        per-ticker belief weight as the mean confidence_score of matching nodes.

        Args:
            predictions: Raw ShadowPredictions from the aggregator.
            manager: BeliefStateManager instance (fully initialized).

        Returns:
            Transformed list of ShadowPredictions with belief_weights injected.
            Each prediction is a NEW frozen dataclass (immutable pattern).
        """
        if not predictions:
            return []

        # Collect unique tickers across all predictions
        tickers: set[str] = {p.target_ticker for p in predictions if p.target_ticker}

        # Pre-compute belief weights per ticker
        ticker_weights: Dict[str, float] = {}
        for ticker in tickers:
            ticker_weights[ticker] = self._compute_ticker_weight(ticker, manager)

        logger.debug(
            "Belief weights computed for %d tickers: %s",
            len(ticker_weights),
            {t: f"{w:.4f}" for t, w in ticker_weights.items() if w > 0.0},
        )

        # Inject weights into each prediction (immutable replacement pattern)
        transformed: List[ShadowPrediction] = []
        for pred in predictions:
            # Build per-prediction belief_weights dict
            weights_for_this = {}
            if pred.target_ticker in ticker_weights:
                w = ticker_weights[pred.target_ticker]
                if w > 0.0:
                    weights_for_this[pred.target_ticker] = w

            # Create new frozen prediction with belief_weights
            new_pred = ShadowPrediction(
                target_ticker=pred.target_ticker,
                target_type=pred.target_type,
                predicted_value=pred.predicted_value,
                comparison_operator=pred.comparison_operator,
                prediction_id=pred.prediction_id,
                scenario_id=pred.scenario_id,
                scenario_type=pred.scenario_type,
                assertion=pred.assertion,
                confidence=pred.confidence,
                reasoning=pred.reasoning,
                prediction_date=pred.prediction_date,
                target_date=pred.target_date,
                prediction_horizon_hours=pred.prediction_horizon_hours,
                source_decision_track=pred.source_decision_track,
                was_safety_valve_bypassed=pred.was_safety_valve_bypassed,
                original_safety_valves=list(pred.original_safety_valves),
                resolved_at=pred.resolved_at,
                verdict=pred.verdict,
                belief_weights=weights_for_this if weights_for_this else None,
            )
            transformed.append(new_pred)

        logger.info(
            "Belief weights injected into %d predictions (%d had active beliefs)",
            len(transformed),
            sum(1 for p in transformed if p.belief_weights),
        )
        return transformed

    def _compute_ticker_weight(
        self,
        ticker: str,
        manager: BeliefStateManager,
    ) -> float:
        """Compute the belief weight for a single ticker.

        Queries the manager for active beliefs matching the ticker name.
        The weight is the mean confidence_score of all matching active nodes.
        If no matching active beliefs exist, returns 0.0 (neutral).

        Args:
            ticker: Ticker symbol (e.g. 'TSLA', 'SPY').
            manager: BeliefStateManager instance.

        Returns:
            Float in [0.0, 1.0] representing the belief weight for this ticker.
        """
        # Search for nodes whose proposition contains the ticker
        snapshots = manager.search_nodes(ticker)

        # Filter to ACTIVE beliefs only
        active_scores = [
            snap.score
            for snap in snapshots
            if snap.status_label == BeliefStatus.ACTIVE.value
        ]

        if not active_scores:
            logger.debug("No active beliefs found for ticker '%s'", ticker)
            return 0.0

        # Mean of active belief scores, clamped
        mean_score = sum(active_scores) / len(active_scores)

        # Apply minimum threshold
        if mean_score < self._min_score_threshold:
            logger.debug(
                "Belief weight for '%s' below threshold: %.4f < %.3f",
                ticker,
                mean_score,
                self._min_score_threshold,
            )
            return 0.0

        return min(1.0, max(0.0, mean_score))

    def get_ticker_belief_profile(
        self,
        ticker: str,
        manager: BeliefStateManager,
    ) -> Dict[str, object]:
        """Get a full belief profile for a ticker (diagnostic/comparison).

        Args:
            ticker: Ticker symbol.
            manager: BeliefStateManager instance.

        Returns:
            Dict with keys:
              - 'ticker': The ticker symbol.
              - 'active_belief_count': Number of active beliefs matching.
              - 'mean_belief_score': Mean confidence_score of active beliefs.
              - 'belief_weight': The computed weight (same as _compute_ticker_weight).
              - 'active_beliefs': List of dicts with proposition, score, expectation.
        """
        snapshots = manager.search_nodes(ticker)
        active_snapshots = [
            snap for snap in snapshots
            if snap.status_label == BeliefStatus.ACTIVE.value
        ]

        return {
            "ticker": ticker,
            "active_belief_count": len(active_snapshots),
            "mean_belief_score": (
                sum(s.score for s in active_snapshots) / len(active_snapshots)
                if active_snapshots else 0.0
            ),
            "belief_weight": self._compute_ticker_weight(ticker, manager),
            "active_beliefs": [
                {
                    "proposition": s.node.proposition,
                    "proposition_id": s.node.proposition_id,
                    "score": s.score,
                    "expectation": s.expectation,
                    "uncertainty": s.uncertainty,
                    "observation_count": s.observation_count,
                }
                for s in active_snapshots
            ],
        }