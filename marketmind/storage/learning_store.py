"""SQLite store for Phase I learning layer — predictions, lessons, entity memories, calibration data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class LearningStore:
    """Persistent storage for the Phase I self-evolving learning layer.

    Four tables:
      - predictions: time-anchored verifiable predictions
      - lessons: structured post-mortem reflections (Layer 3)
      - entity_memories: per-entity accumulated knowledge (Layer 4)
      - calibration_data: Brier/Platt calibration tracking (Layer 2, 5)

    All methods use parameterized queries. All timestamps are UTC.
    """

    def __init__(self, db_path: str | Path = "data/learning.db"):
        self.db_path = Path(db_path)
        self._db: sqlite3.Connection | None = None

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self.db_path))
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._init_tables()
        return self._db

    def _init_tables(self) -> None:
        db = self._get_db()

        db.execute("""CREATE TABLE IF NOT EXISTS predictions (
            hypothesis_id TEXT PRIMARY KEY,
            hypothesis_text TEXT,
            prediction TEXT,
            confidence REAL,
            direction TEXT,
            success_value REAL,
            verification_metric TEXT,
            verification_source TEXT,
            prediction_window_days INTEGER,
            expiry_date TEXT,
            status TEXT DEFAULT 'PENDING',
            actual_value REAL,
            verified_at TEXT,
            created_at TEXT,
            entity TEXT,
            shadow_id TEXT
        )""")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions(status)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_predictions_expiry ON predictions(expiry_date)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_predictions_entity ON predictions(entity)"
        )

        db.execute("""CREATE TABLE IF NOT EXISTS lessons (
            lesson_id TEXT PRIMARY KEY,
            prediction_id TEXT,
            outcome TEXT,
            root_cause TEXT,
            updated_belief TEXT,
            entity TEXT,
            relevance_score REAL,
            created_at TEXT,
            decay_factor REAL DEFAULT 1.0
        )""")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_lessons_entity ON lessons(entity)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_lessons_root_cause ON lessons(root_cause)"
        )

        db.execute("""CREATE TABLE IF NOT EXISTS entity_memories (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT,
            analysis_count INTEGER DEFAULT 0,
            avg_accuracy REAL,
            recurring_patterns TEXT,
            key_levels TEXT,
            best_shadows TEXT,
            common_blind_spots TEXT,
            last_analyzed TEXT,
            memory_freshness REAL DEFAULT 1.0,
            recent_lessons TEXT
        )""")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_type ON entity_memories(entity_type)"
        )

        db.execute("""CREATE TABLE IF NOT EXISTS calibration_data (
            tracker_id TEXT PRIMARY KEY,
            entity_type TEXT,
            total_predictions INTEGER DEFAULT 0,
            brier_score_cumulative REAL DEFAULT 0.0,
            direction_accuracy REAL DEFAULT 0.0,
            ece REAL,
            platt_a REAL,
            platt_b REAL,
            last_updated TEXT
        )""")

        db.commit()

    # ── Predictions ─────────────────────────────────────────────────────

    def save_prediction(self, p) -> None:
        """Insert or replace a prediction row."""
        db = self._get_db()
        ts = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT OR REPLACE INTO predictions
               (hypothesis_id, hypothesis_text, prediction, confidence,
                direction, success_value, verification_metric,
                verification_source, prediction_window_days, expiry_date,
                status, actual_value, verified_at, created_at, entity, shadow_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                getattr(p, "hypothesis_id", ""),
                getattr(p, "hypothesis_text", ""),
                getattr(p, "prediction", ""),
                getattr(p, "confidence", 0.0),
                getattr(p, "direction", ""),
                getattr(p, "success_value", 0.0),
                getattr(p, "verification_metric", ""),
                getattr(p, "verification_source", ""),
                getattr(p, "prediction_window_days", 30),
                getattr(p, "expiry_date", ""),
                getattr(p, "status", "PENDING"),
                getattr(p, "actual_value", None),
                getattr(p, "verified_at", None),
                getattr(p, "created_at", ts),
                getattr(p, "entity", None),
                getattr(p, "shadow_id", None),
            ),
        )
        db.commit()

    def get_expired_predictions(self) -> list[dict]:
        """Return all PENDING predictions past their expiry_date."""
        db = self._get_db()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cursor = db.execute(
            "SELECT * FROM predictions WHERE status = ? AND expiry_date < ?",
            ("PENDING", today),
        )
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    def verify_prediction(self, hypothesis_id: str, actual_value: float) -> None:
        """Mark a prediction as VERIFIED_SUCCESS or VERIFIED_FAILURE."""
        db = self._get_db()
        ts = datetime.now(timezone.utc).isoformat()
        cursor = db.execute(
            "SELECT direction, success_value FROM predictions WHERE hypothesis_id = ?",
            (hypothesis_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return

        direction, threshold = row[0], row[1]
        if direction == "above":
            success = actual_value > threshold
        elif direction == "below":
            success = actual_value < threshold
        elif direction == "within_range":
            success = abs(actual_value - threshold) / abs(threshold) < 0.05
        else:
            success = actual_value > threshold

        new_status = "VERIFIED_SUCCESS" if success else "VERIFIED_FAILURE"
        db.execute(
            "UPDATE predictions SET status = ?, actual_value = ?, verified_at = ? WHERE hypothesis_id = ?",
            (new_status, actual_value, ts, hypothesis_id),
        )
        db.commit()

    def get_predictions_by_status(self, status: str, limit: int = 100) -> list[dict]:
        """Get predictions filtered by status."""
        db = self._get_db()
        cursor = db.execute(
            "SELECT * FROM predictions WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    def expire_unverifiable(self, hypothesis_id: str) -> None:
        """Mark an expired prediction as EXPIRED_UNVERIFIABLE."""
        db = self._get_db()
        ts = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE predictions SET status = 'EXPIRED_UNVERIFIABLE', verified_at = ? WHERE hypothesis_id = ?",
            (ts, hypothesis_id),
        )
        db.commit()

    # ── Lessons ─────────────────────────────────────────────────────────

    def save_lesson(self, lesson: dict) -> None:
        """Save a lesson (post-mortem reflection)."""
        db = self._get_db()
        ts = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT OR REPLACE INTO lessons
               (lesson_id, prediction_id, outcome, root_cause, updated_belief,
                entity, relevance_score, created_at, decay_factor)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                lesson.get("lesson_id", ""),
                lesson.get("prediction_id", ""),
                lesson.get("outcome", ""),
                lesson.get("root_cause", ""),
                lesson.get("updated_belief", ""),
                lesson.get("entity", ""),
                lesson.get("relevance_score", 1.0),
                ts,
                lesson.get("decay_factor", 1.0),
            ),
        )
        db.commit()

    def get_lessons_for_entity(
        self, entity_id: str, limit: int = 5
    ) -> list[dict]:
        """Retrieve top lessons for an entity, ordered by relevance."""
        db = self._get_db()
        cursor = db.execute(
            "SELECT * FROM lessons WHERE entity = ? ORDER BY relevance_score DESC LIMIT ?",
            (entity_id, limit),
        )
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    def get_lessons_by_root_cause(
        self, root_cause: str, limit: int = 20
    ) -> list[dict]:
        """Retrieve lessons with a given root cause category."""
        db = self._get_db()
        cursor = db.execute(
            "SELECT * FROM lessons WHERE root_cause = ? ORDER BY created_at DESC LIMIT ?",
            (root_cause, limit),
        )
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    # ── Entity Memories ─────────────────────────────────────────────────

    def get_entity_memory(self, entity_id: str) -> dict | None:
        """Retrieve accumulated memory for an entity."""
        db = self._get_db()
        cursor = db.execute(
            "SELECT * FROM entity_memories WHERE entity_id = ?",
            (entity_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))

    def update_entity_memory(self, entity_id: str, data: dict) -> None:
        """Insert or update entity memory."""
        db = self._get_db()
        ts = datetime.now(timezone.utc).isoformat()
        existing = self.get_entity_memory(entity_id)
        if existing:
            analysis_count = existing.get("analysis_count", 0) + 1
        else:
            analysis_count = 1

        db.execute(
            """INSERT OR REPLACE INTO entity_memories
               (entity_id, entity_type, analysis_count, avg_accuracy,
                recurring_patterns, key_levels, best_shadows,
                common_blind_spots, last_analyzed, memory_freshness,
                recent_lessons)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entity_id,
                data.get("entity_type", ""),
                analysis_count,
                data.get("avg_accuracy", 0.0),
                _serialize_json(data.get("recurring_patterns")),
                _serialize_json(data.get("key_levels")),
                _serialize_json(data.get("best_shadows")),
                _serialize_json(data.get("common_blind_spots")),
                ts,
                data.get("memory_freshness", 1.0),
                _serialize_json(data.get("recent_lessons")),
            ),
        )
        db.commit()

    # ── Calibration Data ────────────────────────────────────────────────

    def get_calibration(self, tracker_id: str) -> dict | None:
        """Retrieve calibration data for a tracker."""
        db = self._get_db()
        cursor = db.execute(
            "SELECT * FROM calibration_data WHERE tracker_id = ?",
            (tracker_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))

    def update_calibration(self, tracker_id: str, data: dict) -> None:
        """Insert or update calibration data."""
        db = self._get_db()
        ts = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT OR REPLACE INTO calibration_data
               (tracker_id, entity_type, total_predictions,
                brier_score_cumulative, direction_accuracy,
                ece, platt_a, platt_b, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tracker_id,
                data.get("entity_type", ""),
                data.get("total_predictions", 0),
                data.get("brier_score_cumulative", 0.0),
                data.get("direction_accuracy", 0.0),
                data.get("ece", None),
                data.get("platt_a", None),
                data.get("platt_b", None),
                ts,
            ),
        )
        db.commit()

    # ── Lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self) -> "LearningStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _serialize_json(value) -> str:
    """Serialize a Python value to a JSON string, or return empty-JSON for None."""
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
