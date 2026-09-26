"""Tests for LearningStore — SQLite predictions, lessons, entity memories, calibration data."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from marketmind.storage.learning_store import LearningStore


class FakePrediction:
    """Minimal stub matching PredictableHypothesis fields."""

    def __init__(self, hypothesis_id="test-001", **kwargs):
        self.hypothesis_id = hypothesis_id
        self.hypothesis_text = kwargs.get("hypothesis_text", "")
        self.prediction = kwargs.get("prediction", "")
        self.confidence = kwargs.get("confidence", 0.75)
        self.direction = kwargs.get("direction", "above")
        self.success_value = kwargs.get("success_value", 100.0)
        self.verification_metric = kwargs.get("verification_metric", "EUR/USD close price")
        self.verification_source = kwargs.get("verification_source", "market_data:EUR/USD")
        self.prediction_window_days = kwargs.get("prediction_window_days", 30)
        self.expiry_date = kwargs.get("expiry_date", "2026-07-01")
        self.status = kwargs.get("status", "PENDING")
        self.actual_value = kwargs.get("actual_value", None)
        self.verified_at = kwargs.get("verified_at", None)
        self.created_at = kwargs.get("created_at", "")
        self.entity = kwargs.get("entity", None)
        self.shadow_id = kwargs.get("shadow_id", None)


def test_save_and_retrieve_prediction():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        store = LearningStore(db_path)

        p = FakePrediction(
            hypothesis_id="h1",
            hypothesis_text="EUR/USD will rise above 1.15",
            prediction="EUR/USD above 1.15 in 30 days",
            confidence=0.8,
            direction="above",
            success_value=1.15,
            entity="EUR/USD",
        )
        store.save_prediction(p)

        results = store.get_predictions_by_status("PENDING")
        assert len(results) == 1
        assert results[0]["hypothesis_id"] == "h1"
        assert results[0]["direction"] == "above"
        assert results[0]["success_value"] == 1.15
        assert results[0]["entity"] == "EUR/USD"
        assert results[0]["status"] == "PENDING"

        store.close()


def test_get_expired_predictions():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        store = LearningStore(db_path)

        past_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        future_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

        expired = FakePrediction(
            hypothesis_id="expired-1",
            expiry_date=past_date,
            status="PENDING",
        )
        future = FakePrediction(
            hypothesis_id="future-1",
            expiry_date=future_date,
            status="PENDING",
        )
        store.save_prediction(expired)
        store.save_prediction(future)

        expired_list = store.get_expired_predictions()
        assert len(expired_list) == 1
        assert expired_list[0]["hypothesis_id"] == "expired-1"

        store.close()


def test_save_and_retrieve_lesson():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        store = LearningStore(db_path)

        lesson = {
            "lesson_id": "lesson-001",
            "prediction_id": "h1",
            "outcome": "correct_direction_wrong_magnitude",
            "root_cause": "macro_timing_error",
            "updated_belief": "Fed rate cuts take 2-3 months to impact EUR/USD",
            "entity": "EUR/USD",
            "relevance_score": 0.9,
        }
        store.save_lesson(lesson)

        retrieved = store.get_lessons_for_entity("EUR/USD")
        assert len(retrieved) == 1
        assert retrieved[0]["outcome"] == "correct_direction_wrong_magnitude"
        assert retrieved[0]["root_cause"] == "macro_timing_error"

        by_cause = store.get_lessons_by_root_cause("macro_timing_error")
        assert len(by_cause) == 1
        assert by_cause[0]["lesson_id"] == "lesson-001"

        store.close()


def test_entity_memory_crud():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        store = LearningStore(db_path)

        data = {
            "entity_type": "currency_pair",
            "avg_accuracy": 0.72,
            "recurring_patterns": ["mean_reversion_weekly", "trend_following_daily"],
            "key_levels": [1.08, 1.12, 1.15],
            "best_shadows": ["fx_macro_trader", "carry_trade_specialist"],
            "common_blind_spots": ["correlation_breakdown", "central_bank_surprise"],
        }
        store.update_entity_memory("EUR/USD", data)

        mem = store.get_entity_memory("EUR/USD")
        assert mem is not None
        assert mem["entity_id"] == "EUR/USD"
        assert mem["analysis_count"] == 1
        assert mem["avg_accuracy"] == 0.72

        # Update again — count increments
        store.update_entity_memory("EUR/USD", {"entity_type": "currency_pair"})
        mem = store.get_entity_memory("EUR/USD")
        assert mem["analysis_count"] == 2

        # Non-existent returns None
        assert store.get_entity_memory("NONEXISTENT") is None

        store.close()


def test_calibration_data_crud():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        store = LearningStore(db_path)

        calib = {
            "entity_type": "shadow",
            "total_predictions": 50,
            "brier_score_cumulative": 6.5,
            "direction_accuracy": 0.68,
            "ece": 0.12,
            "platt_a": 1.3,
            "platt_b": -0.2,
        }
        store.update_calibration("shadow_macro_001", calib)

        result = store.get_calibration("shadow_macro_001")
        assert result is not None
        assert result["total_predictions"] == 50
        assert result["brier_score_cumulative"] == 6.5
        assert result["direction_accuracy"] == 0.68
        assert result["ece"] == 0.12

        # Update existing
        store.update_calibration("shadow_macro_001", {"total_predictions": 51})
        result = store.get_calibration("shadow_macro_001")
        assert result["total_predictions"] == 51

        # Non-existent
        assert store.get_calibration("nonexistent") is None

        store.close()


def test_verify_prediction_success():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        store = LearningStore(db_path)

        p = FakePrediction(
            hypothesis_id="verify-1",
            direction="above",
            success_value=100.0,
            status="PENDING",
        )
        store.save_prediction(p)
        store.verify_prediction("verify-1", 105.0)

        results = store.get_predictions_by_status("VERIFIED_SUCCESS")
        assert len(results) == 1
        assert results[0]["actual_value"] == 105.0

        store.close()


def test_verify_prediction_failure():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        store = LearningStore(db_path)

        p = FakePrediction(
            hypothesis_id="verify-2",
            direction="below",
            success_value=50.0,
            status="PENDING",
        )
        store.save_prediction(p)
        store.verify_prediction("verify-2", 55.0)

        results = store.get_predictions_by_status("VERIFIED_FAILURE")
        assert len(results) == 1
        assert results[0]["actual_value"] == 55.0

        store.close()


def test_expire_unverifiable():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        store = LearningStore(db_path)

        p = FakePrediction(hypothesis_id="expire-me", status="PENDING")
        store.save_prediction(p)
        store.expire_unverifiable("expire-me")

        results = store.get_predictions_by_status("EXPIRED_UNVERIFIABLE")
        assert len(results) == 1

        store.close()


def test_context_manager():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        with LearningStore(db_path) as store:
            p = FakePrediction(hypothesis_id="ctx-test")
            store.save_prediction(p)
        # __exit__ should close the store silently
