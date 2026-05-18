"""Tests for pipeline/calibration_tracker.py — pure computation, no LLM calls."""

import math
from types import SimpleNamespace

import pytest

from marketmind.pipeline.calibration_tracker import (
    CalibrationResult,
    compute_brier_score,
    compute_calibration_buckets,
    compute_direction_accuracy,
    compute_ece,
    track_calibration,
)


def _pred(status: str, confidence: float) -> SimpleNamespace:
    """Factory for test prediction objects."""
    return SimpleNamespace(status=status, confidence=confidence)


class _MockStore:
    """Mock LearningStore for testing track_calibration."""
    def __init__(self):
        self.last_call: tuple | None = None

    def update_calibration(self, tracker_id: str, data: dict):
        self.last_call = (tracker_id, data)


# ── Brier Score ──────────────────────────────────────────────────────────────

def test_brier_score_perfect():
    """All predictions correct at 1.0 confidence -> BS=0.0."""
    preds = [_pred("VERIFIED_SUCCESS", 1.0) for _ in range(10)]
    assert compute_brier_score(preds) == 0.0


def test_brier_score_worst():
    """All predictions wrong at 1.0 confidence -> BS=1.0."""
    preds = [_pred("VERIFIED_FAILURE", 1.0) for _ in range(10)]
    assert compute_brier_score(preds) == 1.0


def test_brier_score_ignores_pending():
    """Pending predictions should not affect score."""
    preds = [
        _pred("VERIFIED_SUCCESS", 1.0),
        _pred("VERIFIED_SUCCESS", 1.0),
        _pred("PENDING", 0.3),
        _pred("PENDING", 0.9),
    ]
    assert compute_brier_score(preds) == 0.0


def test_brier_score_mixed():
    """Mixed outcomes with 0.8 confidence."""
    preds = [
        _pred("VERIFIED_SUCCESS", 0.8),
        _pred("VERIFIED_FAILURE", 0.8),
    ]
    # BS = ((0.8-1)^2 + (0.8-0)^2) / 2 = (0.04 + 0.64) / 2 = 0.34
    assert compute_brier_score(preds) == 0.34


def test_brier_score_no_verified():
    """No verified predictions -> NaN."""
    preds = [_pred("PENDING", 0.5) for _ in range(5)]
    assert math.isnan(compute_brier_score(preds))


# ── Direction Accuracy ───────────────────────────────────────────────────────

def test_direction_accuracy():
    """3 correct out of 5 -> 0.6."""
    preds = [
        _pred("VERIFIED_SUCCESS", 0.7),
        _pred("VERIFIED_SUCCESS", 0.8),
        _pred("VERIFIED_SUCCESS", 0.6),
        _pred("VERIFIED_FAILURE", 0.5),
        _pred("VERIFIED_FAILURE", 0.9),
    ]
    assert compute_direction_accuracy(preds) == 0.6


def test_direction_accuracy_all_correct():
    """All correct -> 1.0."""
    preds = [_pred("VERIFIED_SUCCESS", 0.8) for _ in range(5)]
    assert compute_direction_accuracy(preds) == 1.0


def test_direction_accuracy_all_wrong():
    """All wrong -> 0.0."""
    preds = [_pred("VERIFIED_FAILURE", 0.8) for _ in range(5)]
    assert compute_direction_accuracy(preds) == 0.0


def test_direction_accuracy_no_verified():
    """No verified predictions -> NaN."""
    preds = [_pred("PENDING", 0.5) for _ in range(3)]
    assert math.isnan(compute_direction_accuracy(preds))


# ── ECE ──────────────────────────────────────────────────────────────────────

def test_ece_insufficient_data():
    """<10 verified -> ECE=None."""
    preds = [_pred("VERIFIED_SUCCESS", 0.8) for _ in range(9)]
    assert compute_ece(preds) is None


def test_ece_perfectly_calibrated():
    """Every bucket has accuracy matching confidence -> ECE=0.0."""
    preds = []
    for i in range(20):
        preds.append(_pred("VERIFIED_SUCCESS" if i % 2 == 0 else "VERIFIED_FAILURE", 0.5))
    ece = compute_ece(preds)
    assert ece is not None
    assert ece == 0.0


def test_ece_with_data():
    """ECE should be computable with >=10 verified."""
    preds = [_pred("VERIFIED_SUCCESS", 0.7) for _ in range(10)]
    ece = compute_ece(preds)
    assert ece is not None
    assert 0.0 <= ece <= 1.0


# ── Calibration Buckets ──────────────────────────────────────────────────────

def test_calibration_buckets():
    """Predictions should be grouped into 10 confidence buckets."""
    preds = [
        _pred("VERIFIED_SUCCESS", 0.05),
        _pred("VERIFIED_FAILURE", 0.05),
        _pred("VERIFIED_SUCCESS", 0.55),
        _pred("VERIFIED_SUCCESS", 0.55),
        _pred("VERIFIED_FAILURE", 0.55),
    ]
    buckets = compute_calibration_buckets(preds)
    assert isinstance(buckets, dict)
    # 0.05 -> bucket "0.0-0.1"
    assert "0.0-0.1" in buckets
    assert buckets["0.0-0.1"]["predicted"] == 2
    assert buckets["0.0-0.1"]["actual_success"] == 1
    assert buckets["0.0-0.1"]["actual_rate"] == 0.5
    # 0.55 -> bucket "0.5-0.6"
    assert "0.5-0.6" in buckets
    assert buckets["0.5-0.6"]["predicted"] == 3
    assert buckets["0.5-0.6"]["actual_success"] == 2


def test_calibration_buckets_ignores_pending():
    """Pending predictions should be excluded from buckets."""
    preds = [
        _pred("VERIFIED_SUCCESS", 0.5),
        _pred("PENDING", 0.5),
        _pred("PENDING", 0.5),
    ]
    buckets = compute_calibration_buckets(preds)
    assert buckets["0.5-0.6"]["predicted"] == 1


def test_calibration_buckets_empty():
    """No verified predictions -> empty dict."""
    preds = [_pred("PENDING", 0.5)]
    assert compute_calibration_buckets(preds) == {}


# ── Track Calibration ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_track_calibration_basic():
    """Track calibration with verified predictions."""
    preds = [
        _pred("VERIFIED_SUCCESS", 1.0),
        _pred("VERIFIED_FAILURE", 1.0),
        _pred("PENDING", 0.6),
    ]
    store = _MockStore()
    result = await track_calibration(preds, "test_tracker", store)

    assert isinstance(result, CalibrationResult)
    assert result.tracker_id == "test_tracker"
    assert result.total_predictions == 3
    assert result.verified_predictions == 2
    assert result.brier_score == 0.5
    assert result.needs_more_data is True  # 2 verified < 10


@pytest.mark.asyncio
async def test_track_calibration_needs_more_data():
    """Fewer than 10 verified -> needs_more_data=True."""
    preds = [_pred("VERIFIED_SUCCESS", 0.8) for _ in range(5)]
    store = _MockStore()
    result = await track_calibration(preds, "t1", store)
    assert result.needs_more_data is True


@pytest.mark.asyncio
async def test_track_calibration_sufficient_data():
    """10+ verified -> needs_more_data=False."""
    preds = [_pred("VERIFIED_SUCCESS", 0.8) for _ in range(10)]
    store = _MockStore()
    result = await track_calibration(preds, "t1", store)
    assert result.needs_more_data is False


@pytest.mark.asyncio
async def test_track_calibration_updates_store():
    """Should call store.update_calibration with correct data."""
    preds = [_pred("VERIFIED_SUCCESS", 1.0) for _ in range(10)]
    store = _MockStore()
    await track_calibration(preds, "my_tracker", store)

    assert store.last_call is not None
    tracker_id, data = store.last_call
    assert tracker_id == "my_tracker"
    assert data["total_predictions"] == 10
    assert data["brier_score_cumulative"] == 0.0
    assert data["direction_accuracy"] == 1.0
    assert "last_updated" in data
