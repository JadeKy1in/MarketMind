"""Forecast tracking — Phase C PMV (prediction log + daily scan)."""
from __future__ import annotations
import json
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from marketmind.shadows.shadow_state import ShadowStateDB

logger = logging.getLogger("marketmind.pipeline.forecast_tracker")

@dataclass
class ForecastMatch:
    scenario_id: int
    prediction_label: str
    predicted_probability: float
    matched_actual: str
    group_id: str

class ForecastTracker:
    """Store and track A→B scenario predictions."""

    def __init__(self, state_db: ShadowStateDB):
        self.state_db = state_db

    def store_prediction(self, trigger_event: str, predictions: list[dict], created_by: str = "main_ai") -> str:
        """Store a set of scenario predictions (B1-B4) for an event A.

        Args:
            trigger_event: The 'A' event description
            predictions: List of {label, probability, trigger_conditions, evidence}
            created_by: "main_ai" or "shadow:{id}"
        Returns:
            scenario_group_id
        """
        group_id = hashlib.sha256(
            f"{trigger_event}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:16]

        now = datetime.now(timezone.utc).isoformat()
        conn = self.state_db._connect()
        try:
            for p in predictions:
                conn.execute(
                    """INSERT INTO forecast_scenarios
                       (scenario_group_id, trigger_event_summary, prediction_label,
                        predicted_probability, trigger_conditions, evidence_chain,
                        forecast_window_end, status, belief_alpha, belief_beta,
                        created_at, updated_at, created_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 1.0, 1.0, ?, ?, ?)""",
                    (group_id, trigger_event, p["label"], p["probability"],
                     json.dumps(p.get("trigger_conditions", {})),
                     p.get("evidence", ""), p.get("window_end", ""),
                     now, now, created_by)
                )
            conn.commit()
        finally:
            conn.close()

        logger.info("Stored %d predictions for group %s", len(predictions), group_id)
        return group_id

    def scan_today(self, today: str, market_data: dict) -> list[ForecastMatch]:
        """Check all pending forecasts against today's market data."""
        conn = self.state_db._connect()
        matches = []
        try:
            rows = conn.execute(
                """SELECT * FROM forecast_scenarios
                   WHERE status = 'pending' AND forecast_window_end >= ?""",
                (today,)
            ).fetchall()

            for row in rows:
                triggers = json.loads(row["trigger_conditions"] or "{}")
                if self._check_triggers(triggers, market_data):
                    match = ForecastMatch(
                        scenario_id=row["id"],
                        prediction_label=row["prediction_label"],
                        predicted_probability=row["predicted_probability"],
                        matched_actual=json.dumps(market_data),
                        group_id=row["scenario_group_id"],
                    )
                    matches.append(match)
                    # Mark as matched
                    conn.execute(
                        """UPDATE forecast_scenarios
                           SET status = 'matched', matched_actual = ?,
                               matched_at = ?, updated_at = ?
                           WHERE id = ?""",
                        (match.matched_actual, datetime.now(timezone.utc).isoformat(),
                         datetime.now(timezone.utc).isoformat(), row["id"])
                    )
            conn.commit()
        finally:
            conn.close()

        if matches:
            logger.info("Found %d forecast matches today", len(matches))
        return matches

    def expire_stale(self, today: str) -> int:
        """Mark expired forecasts."""
        conn = self.state_db._connect()
        try:
            cur = conn.execute(
                """UPDATE forecast_scenarios SET status = 'expired', updated_at = ?
                   WHERE status = 'pending' AND forecast_window_end < ?""",
                (datetime.now(timezone.utc).isoformat(), today)
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    @staticmethod
    def _check_triggers(triggers: dict, market_data: dict) -> bool:
        """Check if trigger conditions are met. Safe — no eval()."""
        if not triggers:
            return False
        for key, condition in triggers.items():
            actual = market_data.get(key)
            if actual is None:
                return False
            if isinstance(condition, dict):
                op = condition.get("op", "gte")
                threshold = condition.get("threshold", 0)
                if op == "gte" and not (actual >= threshold):
                    return False
                elif op == "lte" and not (actual <= threshold):
                    return False
                elif op == "eq" and not (actual == threshold):
                    return False
                elif op == "gt" and not (actual > threshold):
                    return False
                elif op == "lt" and not (actual < threshold):
                    return False
        return True

    def get_active_predictions(self, created_by: str | None = None) -> list[dict]:
        """Get all pending predictions, optionally filtered by creator."""
        conn = self.state_db._connect()
        try:
            if created_by:
                rows = conn.execute(
                    """SELECT * FROM forecast_scenarios
                       WHERE status = 'pending' AND created_by = ?
                       ORDER BY created_at DESC""",
                    (created_by,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM forecast_scenarios
                       WHERE status = 'pending'
                       ORDER BY created_at DESC"""
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
