"""
event_store.py — Phase 8.0 Immutable Event Sourcing & Dimensional Snapshot Store

Core data layer for the Shadow Mode / Tribunal audit trail.  Every prediction,
verdict, and scenario run is recorded as an append-only event.  Events are NEVER
updated or deleted — this is the Event Sourcing discipline mandated by the
Phase 8.1 blueprint.

Three event streams:
  1. Prediction Stream    — Every ShadowPrediction created
  2. Verdict Stream       — Every TribunalVerdict rendered
  3. Batch Stream         — Every BatchShadowRun executed (links predictions + verdicts)

Dimensional Snapshots are materialised views (sorted by timestamp) derived from
the event streams. They are cached representations, NOT authoritative state.
The event streams are always the source of truth.

SPARC:
  Specification: append-only file-backed event store with JSON serialisation.
  Pseudocode: three append-only log files, read-side replay functions.
  Architecture: filesystem-backed (no external DB), JSONL format.
  Refinement: no CRUD operations — only append() and replay().
  Completion: full test coverage with temp directories.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Generator, List, Optional, Type, TypeVar

from src.shadow_types import (
    BatchShadowRun,
    ShadowPrediction,
    ShadowScenario,
    TribunalVerdict,
    VerdictStatus,
)

# ============================================================
# Type variable for generic replay
# ============================================================

T = TypeVar("T")


# ============================================================
# Event types — string constants for the event kind discriminator
# ============================================================

EVENT_TYPE_PREDICTION = "shadow_prediction"
EVENT_TYPE_VERDICT = "shadow_verdict"
EVENT_TYPE_BATCH = "shadow_batch"


# ============================================================
# Exceptions
# ============================================================

class EventStoreError(Exception):
    """Raised on event store I/O failures."""


class EventStoreConflictError(EventStoreError):
    """Raised when trying to append an event that already exists (duplicate ID)."""


# ============================================================
# Encoder / Decoder helpers
# ============================================================

def _serialise_event(
    event_type: str,
    payload: Dict[str, Any],
) -> str:
    """Serialise an event to a JSON line with type discriminator.

    The event record has a header envelope:
      {"event_type": "...", "timestamp": "...", "payload": {...}}
    """
    record = {
        "event_type": event_type,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
        "payload": payload,
    }
    return json.dumps(record, sort_keys=True, default=str) + "\n"


def _prediction_to_payload(prediction: ShadowPrediction) -> Dict[str, Any]:
    """Convert a ShadowPrediction to a serialisable dict."""
    return {
        "prediction_id": prediction.prediction_id,
        "scenario_id": prediction.scenario_id,
        "scenario_type": prediction.scenario_type.value,
        "target_ticker": prediction.target_ticker,
        "target_type": prediction.target_type.value,
        "assertion": prediction.assertion,
        "predicted_value": prediction.predicted_value,
        "comparison_operator": prediction.comparison_operator,
        "confidence": prediction.confidence,
        "prediction_date": prediction.prediction_date,
        "target_date": prediction.target_date,
        "prediction_horizon_hours": prediction.prediction_horizon_hours,
        "source_decision_track": prediction.source_decision_track,
        "was_safety_valve_bypassed": prediction.was_safety_valve_bypassed,
        "original_safety_valves": list(prediction.original_safety_valves),
        "resolved_at": prediction.resolved_at,
        "verdict": prediction.verdict.value if prediction.verdict else None,
    }


def _verdict_to_payload(verdict: TribunalVerdict) -> Dict[str, Any]:
    """Convert a TribunalVerdict to a serialisable dict."""
    return {
        "verdict_id": verdict.verdict_id,
        "prediction_id": verdict.prediction_id,
        "scenario_id": verdict.scenario_id,
        "target_ticker": verdict.target_ticker,
        "status": verdict.status.value,
        "predicted_value": verdict.predicted_value,
        "actual_value": verdict.actual_value,
        "deviation_pct": verdict.deviation_pct,
        "tolerance_pct": verdict.tolerance_pct,
        "market_data_snapshot": dict(verdict.market_data_snapshot),
        "verdict_date": verdict.verdict_date,
    }


def _batch_to_payload(batch: BatchShadowRun) -> Dict[str, Any]:
    """Convert a BatchShadowRun to a serialisable dict."""
    return {
        "batch_id": batch.batch_id,
        "mode": batch.mode,
        "generated_at": batch.generated_at,
        "tickers": list(batch.tickers),
        "scenario_ids": [s.scenario_id for s in batch.scenarios],
        "total_predictions": batch.total_predictions,
        "source_reports": list(batch.source_reports),
        "account_snapshot_id": batch.account_snapshot_id,
    }


# ============================================================
# Event Store — the immutable append-only log
# ============================================================

class EventStore:
    """Append-only, file-backed event store for Shadow Mode records.

    Each event stream is a separate JSONL file.  Events are appended
    atomically (thread-safe via Lock).  No deletes, no updates —
    Event Sourcing discipline.

    Directory structure:
      <base_dir>/
        predictions.jsonl
        verdicts.jsonl
        batches.jsonl

    Usage:
        store = EventStore("/path/to/data")
        store.append_prediction(prediction)
        store.append_verdict(verdict)
        store.append_batch(batch)

        for event in store.replay_predictions():
            ...
    """

    # File names for each stream
    PREDICTIONS_FILE = "predictions.jsonl"
    VERDICTS_FILE = "verdicts.jsonl"
    BATCHES_FILE = "batches.jsonl"

    def __init__(self, base_dir: str | Path) -> None:
        """Initialise the event store.

        Creates the base directory and all stream files if they don't exist.

        Args:
            base_dir: Directory path for the JSONL files.
        """
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        self._pred_file = self._base_dir / self.PREDICTIONS_FILE
        self._verdict_file = self._base_dir / self.VERDICTS_FILE
        self._batch_file = self._base_dir / self.BATCHES_FILE

        # Touch files to ensure they exist
        for f in (self._pred_file, self._verdict_file, self._batch_file):
            if not f.exists():
                f.write_text("", encoding="utf-8")

        self._lock = Lock()

    # ------------------------------------------------------------------
    # Append operations — each is a single atomic write
    # ------------------------------------------------------------------

    def append_prediction(self, prediction: ShadowPrediction) -> None:
        """Append a prediction event to the stream.

        Args:
            prediction: The ShadowPrediction to record.

        Raises:
            EventStoreError: On I/O failure.
        """
        payload = _prediction_to_payload(prediction)
        line = _serialise_event(EVENT_TYPE_PREDICTION, payload)
        self._append_line(self._pred_file, line)

    def append_verdict(self, verdict: TribunalVerdict) -> None:
        """Append a verdict event to the stream.

        Args:
            verdict: The TribunalVerdict to record.

        Raises:
            EventStoreError: On I/O failure.
        """
        payload = _verdict_to_payload(verdict)
        line = _serialise_event(EVENT_TYPE_VERDICT, payload)
        self._append_line(self._verdict_file, line)

    def append_batch(self, batch: BatchShadowRun) -> None:
        """Append a batch run event to the stream.

        Args:
            batch: The BatchShadowRun to record.

        Raises:
            EventStoreError: On I/O failure.
        """
        payload = _batch_to_payload(batch)
        line = _serialise_event(EVENT_TYPE_BATCH, payload)
        self._append_line(self._batch_file, line)

    # ------------------------------------------------------------------
    # Append batch of verdicts (atomic per file)
    # ------------------------------------------------------------------

    def append_verdicts_batch(self, verdicts: List[TribunalVerdict]) -> None:
        """Append multiple verdicts atomically (same file lock).

        Args:
            verdicts: List of TribunalVerdicts to record.
        """
        with self._lock:
            with open(self._verdict_file, "a", encoding="utf-8") as f:
                for v in verdicts:
                    payload = _verdict_to_payload(v)
                    line = _serialise_event(EVENT_TYPE_VERDICT, payload)
                    f.write(line)
                    f.flush()

    # ------------------------------------------------------------------
    # Replay / read operations — pure read from stream files
    # ------------------------------------------------------------------

    def replay_predictions(
        self,
        ticker: Optional[str] = None,
        scenario_id: Optional[str] = None,
        limit: int = 0,
    ) -> Generator[Dict[str, Any], None, None]:
        """Replay prediction events, optionally filtered.

        Args:
            ticker: If set, only return predictions for this ticker.
            scenario_id: If set, only return predictions for this scenario.
            limit: Max records to return (0 = no limit).

        Yields:
            Raw event dicts with event_type, timestamp, payload.
        """
        return self._replay_stream(
            self._pred_file,
            ticker_filter=ticker,
            scenario_id_filter=scenario_id,
            limit=limit,
        )

    def replay_verdicts(
        self,
        prediction_id: Optional[str] = None,
        scenario_id: Optional[str] = None,
        status_filter: Optional[VerdictStatus] = None,
        limit: int = 0,
    ) -> Generator[Dict[str, Any], None, None]:
        """Replay verdict events, optionally filtered.

        Args:
            prediction_id: If set, only return verdicts for this prediction.
            scenario_id: If set, only return verdicts for this scenario.
            status_filter: If set, only return verdicts with this status.
            limit: Max records to return (0 = no limit).

        Yields:
            Raw event dicts with event_type, timestamp, payload.
        """
        count = 0
        for event in self._replay_stream(self._verdict_file, limit=limit):
            payload = event["payload"]
            if prediction_id and payload.get("prediction_id") != prediction_id:
                continue
            if scenario_id and payload.get("scenario_id") != scenario_id:
                continue
            if status_filter and payload.get("status") != status_filter.value:
                continue
            yield event
            count += 1
            if limit > 0 and count >= limit:
                break

    def replay_batches(
        self,
        batch_id: Optional[str] = None,
        ticker: Optional[str] = None,
        limit: int = 0,
    ) -> Generator[Dict[str, Any], None, None]:
        """Replay batch events, optionally filtered.

        Args:
            batch_id: If set, only return this specific batch.
            ticker: If set, only return batches containing this ticker.
            limit: Max records to return (0 = no limit).

        Yields:
            Raw event dicts with event_type, timestamp, payload.
        """
        count = 0
        for event in self._replay_stream(self._batch_file, limit=limit):
            payload = event["payload"]
            if batch_id and payload.get("batch_id") != batch_id:
                continue
            if ticker and ticker not in payload.get("tickers", []):
                continue
            yield event
            count += 1
            if limit > 0 and count >= limit:
                break

    # ------------------------------------------------------------------
    # Dimensional Snapshots — materialised read-side views
    # ------------------------------------------------------------------

    def get_scenario_predictions(
        self,
        scenario_id: str,
    ) -> List[ShadowPrediction]:
        """Reconstruct all predictions for a given scenario (sorted by time)."""
        results: List[ShadowPrediction] = []
        for event in self.replay_predictions(scenario_id=scenario_id):
            p = event["payload"]
            results.append(ShadowPrediction(
                prediction_id=p["prediction_id"],
                scenario_id=p["scenario_id"],
                scenario_type=_parse_scenario_type(p["scenario_type"]),
                target_ticker=p["target_ticker"],
                target_type=_parse_target_type(p["target_type"]),
                assertion=p["assertion"],
                predicted_value=p["predicted_value"],
                comparison_operator=p["comparison_operator"],
                confidence=p["confidence"],
                prediction_date=p["prediction_date"],
                target_date=p["target_date"],
                prediction_horizon_hours=p["prediction_horizon_hours"],
                source_decision_track=p["source_decision_track"],
                was_safety_valve_bypassed=p["was_safety_valve_bypassed"],
                original_safety_valves=list(p["original_safety_valves"]),
                resolved_at=p.get("resolved_at", ""),
                verdict=_parse_verdict_status(p.get("verdict")),
            ))
        return results

    def get_ticker_accuracy(
        self,
        ticker: str,
        max_predictions: int = 100,
    ) -> Dict[str, Any]:
        """Compute the aggregate PASS / FAIL accuracy for a ticker.

        Returns:
            {
                "ticker": str,
                "total": int,
                "passed": int,
                "failed": int,
                "accuracy_pct": float,
                "avg_deviation_pct": float,
            }
        """
        total = 0
        passed = 0
        failed = 0
        deviations: List[float] = []

        for verdict_event in self.replay_verdicts(limit=max_predictions):
            payload = verdict_event["payload"]
            if payload.get("target_ticker") != ticker:
                continue
            total += 1
            if payload["status"] == VerdictStatus.PASS.value:
                passed += 1
            elif payload["status"] == VerdictStatus.FAIL.value:
                failed += 1
            deviations.append(payload.get("deviation_pct", 0.0))

        avg_dev = sum(deviations) / len(deviations) if deviations else 0.0
        accuracy = (passed / total * 100.0) if total > 0 else 0.0

        return {
            "ticker": ticker,
            "total": total,
            "passed": passed,
            "failed": failed,
            "accuracy_pct": round(accuracy, 2),
            "avg_deviation_pct": round(avg_dev, 2),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_line(self, file_path: Path, line: str) -> None:
        """Thread-safe append to a JSONL file."""
        with self._lock:
            try:
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
            except OSError as e:
                raise EventStoreError(
                    f"Failed to append to {file_path}: {e}"
                ) from e

    def _replay_stream(
        self,
        file_path: Path,
        ticker_filter: Optional[str] = None,
        scenario_id_filter: Optional[str] = None,
        limit: int = 0,
    ) -> Generator[Dict[str, Any], None, None]:
        """Replay events from a JSONL stream file, with optional filters."""
        count = 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    event = json.loads(raw_line)
                    payload = event.get("payload", {})

                    # Apply filters
                    if ticker_filter and payload.get("target_ticker") != ticker_filter:
                        continue
                    if scenario_id_filter and payload.get("scenario_id") != scenario_id_filter:
                        continue

                    yield event
                    count += 1
                    if limit > 0 and count >= limit:
                        break
        except FileNotFoundError:
            return  # Empty stream — no events yet
        except json.JSONDecodeError as e:
            raise EventStoreError(
                f"Corrupt event stream in {file_path}: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @property
    def total_predictions(self) -> int:
        """Count of all prediction events in the store."""
        return sum(1 for _ in self.replay_predictions())

    @property
    def total_verdicts(self) -> int:
        """Count of all verdict events in the store."""
        return sum(1 for _ in self.replay_verdicts())

    @property
    def total_batches(self) -> int:
        """Count of all batch events in the store."""
        return sum(1 for _ in self.replay_batches())

    def clear(self) -> None:
        """Clear all event streams (DESTRUCTIVE — for test isolation only).

        This is NOT part of the Event Sourcing discipline.  Only used in
        test teardown to avoid polluting test state across runs.
        """
        for f in (self._pred_file, self._verdict_file, self._batch_file):
            f.write_text("", encoding="utf-8")


# ============================================================
# Parser helpers (safe deserialisation of enums)
# ============================================================

def _parse_scenario_type(value: str) -> Any:
    """Parse a scenario type string, defaulting to AGGRESSIVE."""
    from src.shadow_types import ShadowScenarioType
    try:
        return ShadowScenarioType(value)
    except ValueError:
        return ShadowScenarioType.AGGRESSIVE


def _parse_target_type(value: str) -> Any:
    """Parse a target type string, defaulting to DIRECTIONAL_MOVE."""
    from src.shadow_types import PredictionTarget
    try:
        return PredictionTarget(value)
    except ValueError:
        return PredictionTarget.DIRECTIONAL_MOVE


def _parse_verdict_status(value: Optional[str]) -> Any:
    """Parse a verdict status string, returning None if missing."""
    from src.shadow_types import VerdictStatus
    if value is None:
        return None
    try:
        return VerdictStatus(value)
    except ValueError:
        return VerdictStatus.PENDING