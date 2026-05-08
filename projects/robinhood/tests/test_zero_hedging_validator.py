"""Tests for zero_hedging_validator.py — Phase 8.1 absolute assertion protocol."""
from __future__ import annotations

import pytest

from src.zero_hedging_validator import ZeroHedgingValidator, _HEDGING_PATTERNS
from src.shadow_types import (
    BatchShadowRun,
    ShadowPrediction,
    ShadowScenario,
    ShadowMode,
    ScenarioLabel,
    PredictionTarget,
)


@pytest.fixture
def validator() -> ZeroHedgingValidator:
    return ZeroHedgingValidator()


@pytest.fixture
def clean_prediction() -> ShadowPrediction:
    return ShadowPrediction(
        target_ticker="IAU",
        target_type=PredictionTarget.DIRECTIONAL_MOVE,
        predicted_value=1.5,
        comparison_operator="gt",
        reasoning="Gold holding above 200-day MA, DXY rolling over.",
    )


@pytest.fixture
def clean_batch(clean_prediction) -> BatchShadowRun:
    scenario = ShadowScenario(
        label=ScenarioLabel.AGGRESSIVE_BULL,
        predictions=[clean_prediction],
    )
    return BatchShadowRun(
        tickers=["IAU"],
        scenarios=[scenario],
        mode=ShadowMode.AGGRESSIVE,
    )


def _make_pred_with_reasoning(reasoning: str) -> ShadowPrediction:
    return ShadowPrediction(
        target_ticker="IAU",
        target_type=PredictionTarget.DIRECTIONAL_MOVE,
        predicted_value=1.5,
        comparison_operator="gt",
        reasoning=reasoning,
    )


class TestHedgingPatterns:
    """Verify the hedging regex patterns catch known hedging language."""

    def test_ambiguous_modal(self):
        """Pattern matches 'may', 'might', 'could', 'would', 'should'."""
        assert _HEDGING_PATTERNS.search("IAU may decline") is not None
        assert _HEDGING_PATTERNS.search("GDX might bounce") is not None
        assert _HEDGING_PATTERNS.search("TLT could rally") is not None

    def test_uncertainty_phrases(self):
        """Pattern matches uncertainty phrases."""
        assert _HEDGING_PATTERNS.search("The market is uncertain") is not None
        assert _HEDGING_PATTERNS.search("Outlook is unclear") is not None
        assert _HEDGING_PATTERNS.search("The picture remains ambiguous") is not None

    def test_hedging_verbs(self):
        """Pattern matches hedging verbs."""
        assert _HEDGING_PATTERNS.search("Prices appear to be stabilizing") is not None
        assert _HEDGING_PATTERNS.search("This seems like a reversal") is not None
        assert _HEDGING_PATTERNS.search("It suggests support will hold") is not None

    def test_tentative_qualifiers(self):
        """Pattern matches tentative qualifiers."""
        assert _HEDGING_PATTERNS.search("Possibly breaking out") is not None
        assert _HEDGING_PATTERNS.search("Perhaps a buying opportunity") is not None
        assert _HEDGING_PATTERNS.search("Potentially bullish setup") is not None

    def test_conditional_language(self):
        """Pattern matches conditional language."""
        assert _HEDGING_PATTERNS.search("If DXY strengthens then") is not None
        assert _HEDGING_PATTERNS.search("Depending on the outcome") is not None
        assert _HEDGING_PATTERNS.search("Unless support breaks") is not None

    def test_observation_language(self):
        """Pattern matches observation/consideration language."""
        assert _HEDGING_PATTERNS.search("We note that volume is declining") is not None
        assert _HEDGING_PATTERNS.search("Consider the risk of reversal") is not None
        assert _HEDGING_PATTERNS.search("It is worth watching closely") is not None

    def test_clean_sentence_not_matched(self):
        """Assertive sentences should not match."""
        clean = [
            "IAU will close above 39.00 tomorrow.",
            "GDX breaks support at 30.00.",
            "TLT rallies 2% on rate cut expectations.",
            "SPY drops 1.5% as DXY surges.",
            "Conclusion: BUY IAU at market.",
        ]
        for sentence in clean:
            assert _HEDGING_PATTERNS.search(sentence) is None, f"False positive: {sentence}"

    def test_safe_modal_uses(self):
        """Modals used in assertive technical contexts are not false positives."""
        safe = [
            "Gold can hold above 39.00 because support is strong.",
            "Will IAU break resistance? Yes, above 40.00.",
        ]
        for sentence in safe:
            assert _HEDGING_PATTERNS.search(sentence) is None


class TestZeroHedgingValidator:
    def test_clean_prediction_pass(self, validator, clean_prediction):
        """Clean prediction passes validation."""
        result = validator.validate_prediction(clean_prediction)
        assert result.is_valid is True
        assert result.hedging_found == []
        assert result.sanitized_reasoning == clean_prediction.reasoning

    def test_hedged_prediction_fail(self, validator):
        """Hedged prediction fails validation."""
        pred = _make_pred_with_reasoning("IAU may possibly decline if DXY strengthens.")
        result = validator.validate_prediction(pred)
        assert result.is_valid is False
        assert len(result.hedging_found) > 0

    def test_hedged_prediction_sanitized(self, validator):
        """Sanitized version removes hedged patterns."""
        pred = _make_pred_with_reasoning("IAU may possibly decline.")
        result = validator.validate_prediction(pred)
        assert "may" not in result.sanitized_reasoning
        assert "possibly" not in result.sanitized_reasoning

    def test_partial_hedging(self, validator):
        """Partially hedged reasoning is flagged but sanitized."""
        pred = _make_pred_with_reasoning(
            "GDX appears to be breaking support at 30.00."
        )
        result = validator.validate_prediction(pred)
        assert result.is_valid is False
        assert "appears" in result.hedging_found[0].lower()

    def test_validate_batch_all_clean(self, validator, clean_batch):
        """Batch with all clean predictions passes."""
        result = validator.validate_batch(clean_batch)
        assert result.total_predictions == 1
        assert result.scenarios[0].predictions[0] is not None

    def test_validate_batch_with_hedging(self, validator):
        """Batch with hedged predictions has them sanitized."""
        pred = _make_pred_with_reasoning("IAU may possibly decline.")
        scenario = ShadowScenario(label=ScenarioLabel.AGGRESSIVE_BEAR, predictions=[pred])
        batch = BatchShadowRun(
            tickers=["IAU"],
            scenarios=[scenario],
            mode=ShadowMode.AGGRESSIVE,
        )
        result = validator.validate_batch(batch)
        sanitized = result.scenarios[0].predictions[0]
        assert "may" not in sanitized.reasoning

    def test_validate_batch_preserves_clean(self, validator):
        """Clean predictions are preserved unchanged."""
        pred = _make_pred_with_reasoning("IAU will close above 39.00.")
        scenario = ShadowScenario(label=ScenarioLabel.AGGRESSIVE_BULL, predictions=[pred])
        batch = BatchShadowRun(
            tickers=["IAU"],
            scenarios=[scenario],
            mode=ShadowMode.AGGRESSIVE,
        )
        result = validator.validate_batch(batch)
        preserved = result.scenarios[0].predictions[0]
        assert preserved.reasoning == "IAU will close above 39.00."
        assert preserved.prediction_id == pred.prediction_id

    def test_empty_batch(self, validator):
        """Empty batch passes validation."""
        batch = BatchShadowRun(
            tickers=["IAU"],
            scenarios=[],
            mode=ShadowMode.AGGRESSIVE,
        )
        result = validator.validate_batch(batch)
        assert result.total_predictions == 0