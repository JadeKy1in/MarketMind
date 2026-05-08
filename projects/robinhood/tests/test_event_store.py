"""Tests for event_store.py — Phase 8.0 immutable event persistence."""
from __future__ import annotations

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone
from pathlib import Path

from src.event_store import (
    EventStore,
    EventStoreError,
    EVENT_TYPE_PREDICTION,
    EVENT_TYPE_VERDICT,
    EVENT_TYPE_BATCH,
)
from src.shadow_types import (
    BatchShadowRun,
    ShadowPrediction,
    ShadowScenario,
    ShadowMode,
    ScenarioLabel,
    PredictionTarget,
    TribunalVerdict,
    VerdictStatus,
)


def _make_prediction() -> ShadowPrediction:
    return ShadowPrediction(
        target_ticker="IAU",
        target_type=PredictionTarget.DIRECTIONAL_MOVE,
        predicted_value=1.5,
        comparison_operator="gt",
    )


def _make_batch() -> BatchShadowRun:
    pred = _make_prediction()
    scenario = ShadowScenario(
        label=ScenarioLabel.AGGRESSIVE_BULL,
        predictions=[pred],
        target_ticker="IAU",
    )
    return BatchShadowRun(
        tickers=["IAU"],
        scenarios=[scenario],
        mode=ShadowMode.AGGRESSIVE,
    )


def _make_verdict() -> TribunalVerdict:
    return TribunalVerdict(
        prediction_id="pred-1",
        target_ticker="IAU",
        status=VerdictStatus.PASS,
        deviation_pct=0.0,
        actual_close=39.50,
        predicted_value=39.00,
        reason="Close above support",
        scenario_id="scn-1",
    )


def _collect(gen):
    """Collect generator results into a list."""
    return list(gen)


class TestEventStoreInit:
    def test_creates_files_on_init(self):
        """EventStore creates all three JSONL files on init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            assert os.path.exists(os.path.join(tmpdir, "predictions.jsonl"))
            assert os.path.exists(os.path.join(tmpdir, "verdicts.jsonl"))
            assert os.path.exists(os.path.join(tmpdir, "batches.jsonl"))

    def test_empty_store_returns_no_events(self):
        """Empty store yields no events on replay."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            preds = _collect(store.replay_predictions())
            verdicts = _collect(store.replay_verdicts())
            batches = _collect(store.replay_batches())
            assert preds == []
            assert verdicts == []
            assert batches == []


class TestEventStoreAppend:
    def test_append_batch(self):
        """AppendBatch writes one JSONL line retrievable via replay_batches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            batch = _make_batch()
            store.append_batch(batch)
            events = _collect(store.replay_batches(batch_id=batch.batch_id))
            assert len(events) == 1
            assert events[0]["event_type"] == EVENT_TYPE_BATCH
            assert events[0]["payload"]["batch_id"] == batch.batch_id

    def test_append_verdict(self):
        """AppendVerdict writes one JSONL line retrievable via replay_verdicts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            v = _make_verdict()
            store.append_verdict(v)
            events = _collect(store.replay_verdicts(prediction_id="pred-1"))
            assert len(events) == 1
            assert events[0]["event_type"] == EVENT_TYPE_VERDICT
            assert events[0]["payload"]["prediction_id"] == "pred-1"

    def test_append_prediction(self):
        """AppendPrediction writes one JSONL line retrievable via replay_predictions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            p = _make_prediction()
            store.append_prediction(p)
            events = _collect(store.replay_predictions(ticker="IAU"))
            assert len(events) == 1
            assert events[0]["event_type"] == EVENT_TYPE_PREDICTION
            assert events[0]["payload"]["target_ticker"] == "IAU"

    def test_append_multiple(self):
        """Append multiple events, all preserved across streams."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            batch = _make_batch()
            store.append_batch(batch)
            v = _make_verdict()
            store.append_verdict(v)
            store.append_verdict(v)
            batches = _collect(store.replay_batches())
            verdicts = _collect(store.replay_verdicts())
            assert len(batches) == 1
            assert batches[0]["event_type"] == EVENT_TYPE_BATCH
            assert len(verdicts) == 2
            assert verdicts[0]["event_type"] == EVENT_TYPE_VERDICT
            assert verdicts[1]["event_type"] == EVENT_TYPE_VERDICT


class TestEventStoreImmutability:
    def test_no_overwrite(self):
        """Writing same data twice produces two lines, not one."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            store.append_batch(_make_batch())
            store.append_batch(_make_batch())
            events = _collect(store.replay_batches())
            assert len(events) == 2

    def test_no_delete_method(self):
        """No delete/update/remove method exists."""
        store = EventStore(base_dir=tempfile.mkdtemp())
        assert not hasattr(store, "delete")
        assert not hasattr(store, "update")
        assert not hasattr(store, "remove")


class TestEventStoreFilter:
    def test_filter_by_ticker_on_predictions(self):
        """replay_predictions filters by ticker correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            p1 = ShadowPrediction("IAU", PredictionTarget.DIRECTIONAL_MOVE, 1.0, "gt")
            p2 = ShadowPrediction("GDX", PredictionTarget.DIRECTIONAL_MOVE, 2.0, "gt")
            store.append_prediction(p1)
            store.append_prediction(p2)
            iau_events = _collect(store.replay_predictions(ticker="IAU"))
            all_events = _collect(store.replay_predictions())
            assert len(iau_events) == 1
            assert iau_events[0]["payload"]["target_ticker"] == "IAU"
            assert len(all_events) == 2

    def test_filter_verdicts_by_status(self):
        """replay_verdicts filters by status correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            v1 = _make_verdict()
            v2 = TribunalVerdict(
                prediction_id="pred-2",
                target_ticker="GDX",
                status=VerdictStatus.FAIL,
                deviation_pct=5.0,
                actual_close=30.0,
                predicted_value=35.0,
                reason="Missed target",
            )
            store.append_verdict(v1)
            store.append_verdict(v2)
            pass_events = _collect(store.replay_verdicts(status_filter=VerdictStatus.PASS))
            fail_events = _collect(store.replay_verdicts(status_filter=VerdictStatus.FAIL))
            assert len(pass_events) == 1
            assert len(fail_events) == 1
            assert pass_events[0]["payload"]["status"] == "PASS"
            assert fail_events[0]["payload"]["status"] == "FAIL"

    def test_append_verdicts_batch(self):
        """append_verdicts_batch writes multiple verdicts atomically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            v1 = _make_verdict()
            v2 = TribunalVerdict(
                prediction_id="pred-2",
                target_ticker="GDX",
                status=VerdictStatus.FAIL,
                deviation_pct=3.0,
                actual_close=30.0,
                predicted_value=31.0,
                reason="Missed",
            )
            store.append_verdicts_batch([v1, v2])
            events = _collect(store.replay_verdicts())
            assert len(events) == 2


class TestEventStoreDimensionalSnapshots:
    def test_get_ticker_accuracy(self):
        """get_ticker_accuracy computes pass/fail stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            for i in range(3):
                store.append_verdict(TribunalVerdict(
                    prediction_id=f"p-{i}",
                    target_ticker="IAU",
                    status=VerdictStatus.PASS if i < 2 else VerdictStatus.FAIL,
                    deviation_pct=0.5 * i,
                    actual_close=40.0,
                    predicted_value=39.0,
                    reason="test",
                ))
            stats = store.get_ticker_accuracy("IAU")
            assert stats["ticker"] == "IAU"
            assert stats["total"] == 3
            assert stats["passed"] == 2
            assert stats["failed"] == 1
            assert stats["accuracy_pct"] == pytest.approx(66.67, rel=0.01)

    def test_clear_resets_store(self):
        """clear() empties all streams."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            store.append_batch(_make_batch())
            assert _collect(store.replay_batches()) != []
            store.clear()
            assert _collect(store.replay_batches()) == []

    def test_total_properties(self):
        """total_predictions/verdicts/batches return correct counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(base_dir=tmpdir)
            assert store.total_predictions == 0
            assert store.total_verdicts == 0
            assert store.total_batches == 0
            store.append_prediction(_make_prediction())
            store.append_verdict(_make_verdict())
            store.append_batch(_make_batch())
            assert store.total_predictions == 1
            assert store.total_verdicts == 1
            assert store.total_batches == 1