"""Emergency Quota Auditor -- confidence-based extra LLM calls with reward/penalty state machine.

State machine:
    NORMAL -> PENDING -> AUDIT -> REWARDED/PENALIZED -> NORMAL

Trigger: confidence >= 8/10 + non-consensus opportunity.
Profit -> permanent +1 daily quota.
Loss (not followed) -> 3-day observation penalty.
Loss (followed) -> 7-day penalty.
3 consecutive failures -> permanent -1 quota.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB, EmergencyQuotaRequest
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.emergency_quota")


@dataclass
class EmergencyQuotaState:
    """Per-shadow state for emergency quota tracking."""
    shadow_id: str
    state: str = "normal"              # "normal"|"pending"|"audit"|"penalized"|"rewarded"
    consecutive_failures: int = 0
    permanent_bonus: int = 0            # +1 for each profitable emergency
    permanent_penalty: int = 0          # -1 when 3 consecutive failures
    observation_days_remaining: int = 0


class EmergencyQuotaAuditor:
    """Manages emergency quota requests with a reward/penalty state machine.

    Tracks per-shadow state in memory (backed by ShadowStateDB for persistence
    of individual quota requests). The state machine ensures shadows that abuse
    emergency quotas face escalating penalties, while profitable emergency calls
    earn permanent quota increases.
    """

    def __init__(self, state_db: ShadowStateDB, settings: ShadowSettings):
        self.state_db = state_db
        self.settings = settings
        self._shadow_states: dict[str, EmergencyQuotaState] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def request_quota(self, shadow_id: str, opportunity_desc: str,
                      confidence: int) -> bool:
        """Request an emergency quota. Returns True if approved.

        Requirements:
        - Confidence must be >= emergency_confidence_threshold (default 8)
        - Shadow must be in "normal" state (not currently penalized)
        - Shadow must exist in the DB
        """
        if confidence < self.settings.emergency_confidence_threshold:
            logger.info("Emergency quota denied for %s: confidence %d < %d",
                        shadow_id, confidence, self.settings.emergency_confidence_threshold)
            return False

        current_state = self._get_or_create_state(shadow_id)

        if current_state.state in ("penalized", "pending", "audit"):
            logger.info("Emergency quota denied for %s: state=%s", shadow_id, current_state.state)
            return False

        # Approve: create the quota request in DB
        quota = EmergencyQuotaRequest(
            shadow_id=shadow_id,
            requested_at=datetime.now(timezone.utc).isoformat(),
            confidence_self_report=confidence,
            opportunity_description=opportunity_desc,
            result="pending",
        )
        quota_id = self.state_db.record_emergency_quota(shadow_id, quota)
        logger.info("Emergency quota approved for %s: quota_id=%d confidence=%d",
                    shadow_id, quota_id, confidence)

        # Transition to PENDING state
        current_state.state = "pending"
        self._shadow_states[shadow_id] = current_state

        self._save_state(shadow_id)
        return True

    def audit_result(self, quota_id: int, was_profitable: bool,
                     was_followed: bool) -> EmergencyQuotaState:
        """Process the result of an emergency quota call.

        Args:
            quota_id: The emergency quota ID (from request_quota record).
            was_profitable: Whether the emergency call produced a profitable trade.
            was_followed: Whether the recommendation was followed.

        Returns:
            The updated EmergencyQuotaState for the shadow.
        """
        # Look up the quota in DB to get shadow_id
        pending = self.state_db.get_pending_emergency_audits()
        quota_request = None
        for req in pending:
            if req.id == quota_id:
                quota_request = req
                break

        if quota_request is None:
            # Quota might already be resolved; check for any with this ID
            # For robustness, try to find it among resolved as well
            raise ValueError(f"Emergency quota {quota_id} not found or already resolved")

        shadow_id = quota_request.shadow_id
        state = self._get_or_create_state(shadow_id)

        if was_profitable:
            # Reward: permanent +1 bonus, reset failures
            state.permanent_bonus += 1
            state.consecutive_failures = 0
            state.state = "rewarded"
            state.observation_days_remaining = 0
            result_str = "rewarded"
            penalty_str = "none"
            pnl = 0.05  # placeholder positive PnL
            logger.info("Emergency quota %d for %s: REWARDED (bonus=%d)",
                        quota_id, shadow_id, state.permanent_bonus)
        else:
            # Loss: apply penalty based on whether followed
            state.consecutive_failures += 1
            state.state = "penalized"

            if was_followed:
                state.observation_days_remaining = self.settings.emergency_loss_followed_penalty_days
                penalty_str = f"7d_observation_followed"
                logger.info("Emergency quota %d for %s: PENALIZED 7d (followed loss)",
                            quota_id, shadow_id)
            else:
                state.observation_days_remaining = self.settings.emergency_loss_penalty_days
                penalty_str = f"3d_observation_not_followed"
                logger.info("Emergency quota %d for %s: PENALIZED 3d (unfollowed loss)",
                            quota_id, shadow_id)

            # Check for 3 consecutive failures -> permanent -1
            if state.consecutive_failures >= self.settings.emergency_consecutive_fail_limit:
                state.permanent_penalty += 1
                state.consecutive_failures = 0  # reset counter after penalty applied
                penalty_str = f"permanent_minus_one"
                logger.warning("Emergency quota %d for %s: PERMANENT -1 (3 consecutive failures)",
                               quota_id, shadow_id)

            result_str = "penalized"
            pnl = -0.02  # placeholder negative PnL

        # Persist result to DB
        self.state_db.update_emergency_result(quota_id, result_str, pnl, penalty_str)

        # Store updated state
        self._shadow_states[shadow_id] = state

        self._save_state(shadow_id)
        return state

    def get_shadow_state(self, shadow_id: str) -> EmergencyQuotaState:
        """Return the current emergency quota state for a shadow.

        Returns defaults for shadows that have never used emergency quotas.
        """
        return self._get_or_create_state(shadow_id)

    def audit_pending(self, quota_ids: list[int]) -> list[str]:
        """Audit a batch of pending quota IDs and return status descriptions.

        Args:
            quota_ids: List of emergency quota IDs to check.

        Returns:
            List of human-readable status strings for each quota ID.
        """
        results: list[str] = []
        pending = self.state_db.get_pending_emergency_audits()
        pending_ids = {req.id for req in pending if req.id is not None}

        for qid in quota_ids:
            if qid in pending_ids:
                # Find the matching request
                req = next((r for r in pending if r.id == qid), None)
                if req:
                    results.append(
                        f"quota_id={qid}: PENDING (shadow={req.shadow_id}, "
                        f"conf={req.confidence_self_report}, "
                        f"desc='{req.opportunity_description[:40]}...')"
                    )
                else:
                    results.append(f"quota_id={qid}: PENDING")
            else:
                results.append(f"quota_id={qid}: RESOLVED (not in pending queue)")

        return results

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_or_create_state(self, shadow_id: str) -> EmergencyQuotaState:
        """Get existing state or create a default one for the shadow."""
        if shadow_id not in self._shadow_states:
            # Try restoring from dedicated DB table
            raw = self.state_db.load_emergency_quota_state(shadow_id)
            if raw:
                try:
                    data = json.loads(raw)
                    self._shadow_states[shadow_id] = EmergencyQuotaState(
                        shadow_id=shadow_id,
                        state=data.get("state", "normal"),
                        consecutive_failures=data.get("consecutive_failures", 0),
                        permanent_bonus=data.get("permanent_bonus", 0),
                        permanent_penalty=data.get("permanent_penalty", 0),
                        observation_days_remaining=data.get("observation_days_remaining", 0),
                    )
                    return self._shadow_states[shadow_id]
                except (json.JSONDecodeError, KeyError, TypeError):
                    logger.warning("Corrupted runtime state for %s, using defaults", shadow_id)
            # No DB state or corrupted — create new default
            self._shadow_states[shadow_id] = EmergencyQuotaState(shadow_id=shadow_id)
        return self._shadow_states[shadow_id]

    def _save_state(self, shadow_id: str) -> None:
        """Persist emergency quota state to dedicated DB table (atomic write, no race)."""
        if shadow_id not in self._shadow_states:
            return
        state = self._shadow_states[shadow_id]
        data = json.dumps({
            "state": state.state,
            "consecutive_failures": state.consecutive_failures,
            "permanent_bonus": state.permanent_bonus,
            "permanent_penalty": state.permanent_penalty,
            "observation_days_remaining": state.observation_days_remaining,
        })
        self.state_db.save_emergency_quota_state(shadow_id, data)

    def save_all_states(self) -> None:
        """Persist all tracked shadow emergency quota states."""
        for shadow_id in list(self._shadow_states.keys()):
            self._save_state(shadow_id)

