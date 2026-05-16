"""Temp Shadow Lifecycle — creation, expiration, cleanup of temporary event shadows."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings
from marketmind.shadows.event_detector import DetectedEvent

logger = logging.getLogger("marketmind.shadows.temp_shadow_lifecycle")


@dataclass
class TempShadowSpec:
    event_id: str
    shadow_name: str
    methodology_base: str    # which expert template to clone from
    domain: str
    virtual_capital: float   # $10K-$20K based on event impact
    max_lifespan_days: int = 30
    flash_quota_per_day: int = 3


class TempShadowLifecycle:
    """Manages creation, expiration checks, and destruction of temporary shadows."""

    def __init__(self, state_db: ShadowStateDB, config: ShadowSettings):
        self.state_db = state_db
        self.config = config

    def cleanup_stale(self) -> int:
        """Destroy any temp_event shadows that have exceeded lifespan. Call once at startup."""
        cleaned = 0
        for shadow in self.state_db.get_active_shadows("temp_event"):
            if self.check_destruction_conditions(shadow.shadow_id):
                logger.info("Startup cleanup: destroying stale temp shadow %s", shadow.shadow_id)
                self.state_db.eliminate_shadow(shadow.shadow_id, "startup_cleanup_stale")
                cleaned += 1
        return cleaned

    async def create_temp_shadows(self, events: list[DetectedEvent]) -> list[str]:
        """Create Form C milestone-triggered event recorders (Phase 4).

        NOT a full shadow. A recorder that:
        - Day 1: Pro initial framework analysis (1 Pro call)
        - Day 2-9: Python silent recording (0 Pro calls)
        - Day 5: If volatility >3sigma, trigger Pro check (<=1 extra Pro call)
        - Day 10: Pro mid-term review (1 Pro call)
        - Day 30: Pro final validation + Flash summary (1 Pro + 1 Flash)

        Total: 3-5 Pro calls per 30-day event (vs. 30 previously).
        """
        created_ids: list[str] = []
        for event in events:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            shadow_id = f"temp_event:{event.event_type}:{ts}_{event.event_id[:8]}"

            methodology_prompt = (
                f"[FORM_C_EVENT_RECORDER] Event: {event.description}. "
                f"Affected assets: {', '.join(event.affected_assets[:5])}. "
                f"Impact score: {event.impact_score:.2f}. "
                f"You are a milestone-triggered event recorder. "
                f"Day 1: establish analysis framework. "
                f"Day 2-9: only record OHLC + relevant news (no analysis). "
                f"Day 5: if any affected asset moves >3sigma, analyze whether driven by original event. "
                f"Day 10: mid-term review of event impact. "
                f"Day 30: final validation report comparing actual impact to Day 1 prediction. "
                f"Max 30-day lifespan. Be concise -- you have limited Pro calls."
            )

            config = ShadowConfig(
                shadow_id=shadow_id,
                shadow_type="temp_event",
                display_name=f"FormC {event.event_type} {ts}",
                methodology_prompt=methodology_prompt,
                virtual_capital=0.0,
                domain=event.affected_assets[0] if event.affected_assets else "macro",
                temperature=0.3,
                max_positions=0,
            )
            try:
                self.state_db.create_shadow(config)
                created_ids.append(shadow_id)
                logger.info("Created Form C recorder %s for event %s", shadow_id, event.event_type)
            except ValueError as e:
                logger.warning("Form C recorder %s creation failed: %s", shadow_id, e)

        return created_ids

    def check_destruction_conditions(self, shadow_id: str) -> bool:
        config = self.state_db.get_shadow(shadow_id, caller_id="system")
        if config is None:
            return False
        if config.shadow_type != "temp_event":
            return False
        created = datetime.fromisoformat(config.created_at.replace("Z", "+00:00"))
        days_alive = (datetime.now(timezone.utc) - created).days
        if days_alive >= 30:
            return True
        snapshots = self.state_db.get_snapshot_history(shadow_id, caller_id="system", days=5)
        if len(snapshots) < 1:
            return False
        if days_alive >= 5 and len(snapshots) < days_alive:
            return True
        return False

    async def destroy_temp_shadow(self, shadow_id: str) -> None:
        self.state_db.eliminate_shadow(shadow_id, "temp_shadow_expired")
        logger.info("Destroyed temp shadow %s", shadow_id)

    def get_active_temp_shadows(self) -> list[str]:
        return [s.shadow_id for s in self.state_db.get_active_shadows("temp_event")]

    def get_event_status(self, event_id: str) -> str:
        """Returns "active" | "resolved" | "decayed" | "unknown"."""
        for shadow_id in self.get_active_temp_shadows():
            if event_id in shadow_id:
                shadow = self.state_db.get_shadow(shadow_id, caller_id="system")
                if shadow is None:
                    return "resolved"
                created = datetime.fromisoformat(shadow.created_at.replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - created).days
                if days > 20:
                    return "decayed"
                return "active"
        return "unknown"
