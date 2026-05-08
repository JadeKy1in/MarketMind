"""
shadow_tribunal.py — Phase 8.4 The Shadow Tribunal

The Shadow Tribunal is the judgement engine for Shadow Mode. For each
prediction in a BatchShadowRun, it:

  1. Loads the next-day market data snapshot (via MarketDataReplayer).
  2. Compares the prediction's assertion against actual price/vol/flow data.
  3. Issues a PASS or FAIL verdict with deviation magnitude.
  4. Appends each verdict to the EventStore as an immutable audit record.

Core principle (Phase 8.1 Zero-Hedging Protocol):
  Every prediction is a binary testable assertion. There is no "partial credit".
  If IAU was predicted to close above 39.00 and it closes at 38.95, that is a FAIL.

SPARC:
  Specification: binary PASS/FAIL judgement for each shadow prediction.
  Pseudocode: compare predicted vs actual values, quantise as PASS/FAIL.
  Architecture: pure logic — data injected via replayer, persistence via EventStore.
  Refinement: strict binary by default, tolerant mode for numeric close calls.
  Completion: ready for integration into main.py.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from src.event_store import EventStore
from src.market_data_replayer import (
    DailyPriceSnapshot,
    MarketDataReplayer,
    MarketDataSnapshot,
)
from src.shadow_types import (
    BatchShadowRun,
    PredictionTarget,
    ShadowPrediction,
    ShadowScenario,
    TribunalVerdict,
    VerdictStatus,
)

logger = logging.getLogger(__name__)


# ============================================================
# Config
# ============================================================

# Default tolerance for numeric comparisons (0.5% deviation allowed before FAIL)
_DEFAULT_TOLERANCE_PCT: float = 0.5

# Strict mode tolerance (0.0% — any deviation = FAIL)
_STRICT_TOLERANCE_PCT: float = 0.0


# ============================================================
# The Tribunal
# ============================================================

class ShadowTribunal:
    """Binary judgement engine for Shadow Mode predictions.

    The Tribunal operates in two phases:
      1. judge_batch() — Judge all predictions in a batch against market data.
      2. persist_verdicts() — Write all verdicts to the EventStore.

    Each verdict is an immutable EVENT in the event store (no UPDATE, no DELETE).

    Attributes:
        replayer: MarketDataReplayer for next-day data.
        event_store: EventStore for persisting verdicts.
        strict_mode: If True, any numeric deviation = FAIL (default: True).
        tolerance_pct: Allowed deviation before FAIL (0.0 in strict mode).
    """

    def __init__(
        self,
        replayer: MarketDataReplayer,
        event_store: Optional[EventStore] = None,
        strict_mode: bool = True,
    ) -> None:
        self._replayer = replayer
        self._event_store = event_store
        self._strict_mode = strict_mode
        self._tolerance_pct = _STRICT_TOLERANCE_PCT if strict_mode else _DEFAULT_TOLERANCE_PCT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def judge_batch(
        self,
        batch: BatchShadowRun,
        previous_date: str,
    ) -> List[TribunalVerdict]:
        """Judge all predictions in a batch against next-day market data.

        Args:
            batch: The BatchShadowRun containing predictions to judge.
            previous_date: The date of the predictions (YYYY-MM-DD).
                           The replayer fetches data for the next trading day.

        Returns:
            List of TribunalVerdict, one per prediction.

        Raises:
            ValueError: If batch has no scenarios or predictions.
        """
        if not batch.scenarios:
            logger.warning("Batch has no scenarios — nothing to judge.")
            return []

        # Get next-day market data
        snapshot = self._replayer.get_next_day_snapshot(
            previous_date=previous_date,
            tickers=batch.tickers,
        )

        verdicts: List[TribunalVerdict] = []

        for scenario in batch.scenarios:
            for prediction in scenario.predictions:
                verdict = self._judge_prediction(prediction, snapshot)
                verdicts.append(verdict)

        # Persist to event store if available
        if self._event_store:
            self._persist_verdicts(verdicts)

        logger.info(
            "Tribunal judged %d predictions: %d PASS, %d FAIL",
            len(verdicts),
            sum(1 for v in verdicts if v.status == VerdictStatus.PASS),
            sum(1 for v in verdicts if v.status == VerdictStatus.FAIL),
        )

        return verdicts

    def judge_prediction(
        self,
        prediction: ShadowPrediction,
        previous_date: str,
    ) -> TribunalVerdict:
        """Judge a single prediction against next-day data.

        Convenience method for single-prediction judgement (e.g., live debugging).

        Args:
            prediction: The prediction to judge.
            previous_date: The date of the prediction (YYYY-MM-DD).

        Returns:
            TribunalVerdict.
        """
        snapshot = self._replayer.get_next_day_snapshot(
            previous_date=previous_date,
            tickers=[prediction.target_ticker],
        )

        return self._judge_prediction(prediction, snapshot)

    # ------------------------------------------------------------------
    # Judgement logic (per prediction type)
    # ------------------------------------------------------------------

    def _judge_prediction(
        self,
        prediction: ShadowPrediction,
        snapshot: MarketDataSnapshot,
    ) -> TribunalVerdict:
        """Judge one prediction against a market data snapshot.

        Dispatches to type-specific judgement methods.
        """
        ticker = prediction.target_ticker
        price_data = snapshot.prices.get(ticker)

        if price_data is None:
            return TribunalVerdict(
                prediction_id=prediction.prediction_id,
                target_ticker=ticker,
                status=VerdictStatus.FAIL,
                deviation_pct=100.0,
                actual_close=0.0,
                predicted_value=prediction.predicted_value,
                reason=f"Market data unavailable for {ticker} on {snapshot.date}",
            )

        target_type = prediction.target_type

        if target_type == PredictionTarget.DIRECTIONAL_MOVE:
            return self._judge_directional(prediction, price_data)
        elif target_type == PredictionTarget.SUPPORT_BREAK:
            return self._judge_support_break(prediction, price_data)
        elif target_type == PredictionTarget.RESISTANCE_BREAK:
            return self._judge_resistance_break(prediction, price_data)
        elif target_type == PredictionTarget.RELATIVE_OUTPERFORM:
            # Relative outperform requires cluster peers — use close vs predicted
            return self._judge_relative(prediction, price_data, snapshot)
        elif target_type == PredictionTarget.VOLATILITY_BREAKOUT:
            return self._judge_volatility(prediction, price_data)
        elif target_type == PredictionTarget.FLOW_REVERSAL:
            return self._judge_flow(prediction, price_data)
        else:
            return self._judge_default(prediction, price_data)

    def _judge_directional(
        self,
        prediction: ShadowPrediction,
        price: DailyPriceSnapshot,
    ) -> TribunalVerdict:
        """Judgement: did the ticker close in the predicted direction?"""
        prev_close = price.open_price  # open is the reference
        actual_change = (price.close_price - prev_close) / prev_close * 100.0

        # Predicted value encodes expected % change (or 0 for flat)
        predicted_change = prediction.predicted_value

        is_correct = False
        reason = ""

        if prediction.comparison_operator == "gt":
            is_correct = price.close_price > prev_close
            deviation = actual_change  # positive = correct if gt
            reason = (
                f"Close {price.close_price} vs Open {prev_close}: "
                f"{'+' if actual_change >= 0 else ''}{actual_change:.2f}%"
            )
        elif prediction.comparison_operator == "lt":
            is_correct = price.close_price < prev_close
            deviation = -actual_change  # positive = correct if lt
            reason = (
                f"Close {price.close_price} vs Open {prev_close}: "
                f"{actual_change:.2f}%"
            )
        else:
            # Flat: within 0.5% of open
            change_pct = abs(actual_change)
            is_correct = change_pct <= 0.5
            deviation = change_pct
            reason = f"Close {price.close_price} vs Open {prev_close}: change {actual_change:.2f}%"

        status = VerdictStatus.PASS if is_correct else VerdictStatus.FAIL
        deviation_pct = round(abs(deviation), 2)

        return TribunalVerdict(
            prediction_id=prediction.prediction_id,
            target_ticker=prediction.target_ticker,
            status=status,
            deviation_pct=deviation_pct,
            actual_close=price.close_price,
            predicted_value=prediction.predicted_value,
            reason=reason,
        )

    def _judge_support_break(
        self,
        prediction: ShadowPrediction,
        price: DailyPriceSnapshot,
    ) -> TribunalVerdict:
        """Judgement: did the price hold above support?"""
        support_level = prediction.predicted_value
        low_price = price.low_price

        # "will hold above support" → low must NOT go below support
        held_above = low_price >= support_level

        deviation = abs(support_level - low_price) / support_level * 100.0 if support_level > 0 else 0.0

        status = VerdictStatus.PASS if held_above else VerdictStatus.FAIL
        reason = (
            f"Low {low_price} vs Support {support_level}: "
            f"{'Held' if held_above else 'BROKEN'} (dev: {deviation:.2f}%)"
        )

        return TribunalVerdict(
            prediction_id=prediction.prediction_id,
            target_ticker=prediction.target_ticker,
            status=status,
            deviation_pct=round(deviation, 2),
            actual_close=price.close_price,
            predicted_value=prediction.predicted_value,
            reason=reason,
        )

    def _judge_resistance_break(
        self,
        prediction: ShadowPrediction,
        price: DailyPriceSnapshot,
    ) -> TribunalVerdict:
        """Judgement: did the price break above resistance?"""
        resistance_level = prediction.predicted_value
        high_price = price.high_price

        broke_above = high_price > resistance_level
        deviation = abs(high_price - resistance_level) / resistance_level * 100.0 if resistance_level > 0 else 0.0

        status = VerdictStatus.PASS if broke_above else VerdictStatus.FAIL
        reason = (
            f"High {high_price} vs Resistance {resistance_level}: "
            f"{'BROKEN' if broke_above else 'Held'} (dev: {deviation:.2f}%)"
        )

        return TribunalVerdict(
            prediction_id=prediction.prediction_id,
            target_ticker=prediction.target_ticker,
            status=status,
            deviation_pct=round(deviation, 2),
            actual_close=price.close_price,
            predicted_value=prediction.predicted_value,
            reason=reason,
        )

    def _judge_relative(
        self,
        prediction: ShadowPrediction,
        price: DailyPriceSnapshot,
        snapshot: MarketDataSnapshot,
    ) -> TribunalVerdict:
        """Judgement: did the ticker outperform/underperform peer?"""
        # For relative judgement, we compare the predicted vs actual close move
        # This is a simplified heuristic — real implementation needs peer data.
        prev_close = price.open_price
        actual_return = (price.close_price - prev_close) / prev_close * 100.0

        predicted_return = prediction.predicted_value
        is_correct = (
            (prediction.comparison_operator == "gt" and actual_return > predicted_return)
            or (prediction.comparison_operator == "lt" and actual_return < predicted_return)
        )

        deviation = abs(actual_return - predicted_return)

        status = VerdictStatus.PASS if is_correct else VerdictStatus.FAIL
        reason = (
            f"Actual return {actual_return:.2f}% vs predicted {predicted_return:.2f}%: "
            f"{'Correct' if is_correct else 'Incorrect'} (dev: {deviation:.2f}%)"
        )

        return TribunalVerdict(
            prediction_id=prediction.prediction_id,
            target_ticker=prediction.target_ticker,
            status=status,
            deviation_pct=round(deviation, 2),
            actual_close=price.close_price,
            predicted_value=prediction.predicted_value,
            reason=reason,
        )

    def _judge_volatility(
        self,
        prediction: ShadowPrediction,
        price: DailyPriceSnapshot,
    ) -> TribunalVerdict:
        """Judgement: did implied volatility expand by predicted %?"""
        # Approximate IV expansion by daily range expansion
        daily_range_pct = (price.high_price - price.low_price) / price.close_price * 100.0

        predicted_expansion = prediction.predicted_value  # e.g., 10.0%
        is_expanded = daily_range_pct > predicted_expansion

        deviation = abs(daily_range_pct - predicted_expansion)
        status = VerdictStatus.PASS if is_expanded else VerdictStatus.FAIL
        reason = (
            f"Daily range {daily_range_pct:.2f}% vs predicted {predicted_expansion:.2f}%: "
            f"{'Expanded' if is_expanded else 'Contained'} (dev: {deviation:.2f}%)"
        )

        return TribunalVerdict(
            prediction_id=prediction.prediction_id,
            target_ticker=prediction.target_ticker,
            status=status,
            deviation_pct=round(deviation, 2),
            actual_close=price.close_price,
            predicted_value=prediction.predicted_value,
            reason=reason,
        )

    def _judge_flow(
        self,
        prediction: ShadowPrediction,
        price: DailyPriceSnapshot,
    ) -> TribunalVerdict:
        """Judgement: did flow/volume exceed predicted threshold?"""
        # Use volume as a flow proxy
        actual_volume_ratio = price.volume / 5_000_000  # Normalise to baseline
        predicted_ratio = prediction.predicted_value

        is_correct = (
            (prediction.comparison_operator == "gt" and actual_volume_ratio > predicted_ratio)
            or (prediction.comparison_operator == "lt" and actual_volume_ratio < predicted_ratio)
        )

        deviation = abs(actual_volume_ratio - predicted_ratio) / max(abs(predicted_ratio), 0.01) * 100.0

        status = VerdictStatus.PASS if is_correct else VerdictStatus.FAIL
        reason = (
            f"Volume ratio {actual_volume_ratio:.2f}x vs predicted {predicted_ratio:.2f}x: "
            f"{'Correct' if is_correct else 'Incorrect'} (dev: {deviation:.2f}%)"
        )

        return TribunalVerdict(
            prediction_id=prediction.prediction_id,
            target_ticker=prediction.target_ticker,
            status=status,
            deviation_pct=round(deviation, 2),
            actual_close=price.close_price,
            predicted_value=prediction.predicted_value,
            reason=reason,
        )

    def _judge_default(
        self,
        prediction: ShadowPrediction,
        price: DailyPriceSnapshot,
    ) -> TribunalVerdict:
        """Fallback judgement for unknown target types."""
        return TribunalVerdict(
            prediction_id=prediction.prediction_id,
            target_ticker=prediction.target_ticker,
            status=VerdictStatus.FAIL,
            deviation_pct=100.0,
            actual_close=price.close_price,
            predicted_value=prediction.predicted_value,
            reason=f"Unsupported target_type: {prediction.target_type}",
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_verdicts(self, verdicts: List[TribunalVerdict]) -> None:
        """Write all verdicts to the EventStore as immutable events."""
        if not self._event_store:
            return

        for verdict in verdicts:
            self._event_store.append_verdict(verdict)
