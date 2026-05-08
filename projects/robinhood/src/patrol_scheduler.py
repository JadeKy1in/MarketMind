"""
patrol_scheduler.py — Stage 2.5: Automated Patrol Scheduler

Lightweight timer-based patrol scheduler for daily macro/market data ingestion.
Zero external dependencies — built on threading.Timer + datetime.

SPARC:
  Specification: PM-approved blueprint — daily patrol slots, idleempotent, non-blocking
  Pseudocode: threading.Timer loop with slot dedup via _last_patrol_times dict
  Architecture: Single-instance scheduler, callback-based dispatch (decoupled from fetcher)
  Refinement: Timer precision ±1s is sufficient for daily patrol frequency
  Completion: Ready for test_patrol_scheduler.py
"""

from __future__ import annotations

import datetime
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class PatrolSlotType(Enum):
    """Named patrol time slots.

    MORNING = 09:00 local — Pre-market macro data
    EVENING = 21:00 local — Post-market summary and overnight indicators
    """
    MORNING = "morning"
    EVENING = "evening"


@dataclass(frozen=True)
class PatrolSlot:
    """A patrol time slot definition.

    Attributes:
        name: Unique slot name (e.g., "morning", "evening")
        hour: Hour of the day (0-23) in local time
        minute: Minute of the hour (0-59)
        slot_type: Categorization of the slot
    """
    name: str
    hour: int
    minute: int = 0
    slot_type: PatrolSlotType = PatrolSlotType.MORNING

    def next_trigger(self, now: Optional[datetime.datetime] = None) -> datetime.datetime:
        """Compute the next datetime when this slot should fire.

        Args:
            now: Reference time. If None, uses datetime.datetime.now().

        Returns:
            The next datetime (today if not yet passed, tomorrow otherwise).
        """
        if now is None:
            now = datetime.datetime.now()

        today_trigger = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)

        if now <= today_trigger:
            return today_trigger
        else:
            # Advance to tomorrow
            return today_trigger + datetime.timedelta(days=1)


@dataclass
class PatrolResult:
    """Result of a single patrol execution.

    Attributes:
        slot_name: Name of the slot that executed
        success: Whether the full patrol completed without unhandled error
        events_ingested: Number of events successfully ingested into BeliefStateManager
        error: Error message if success is False
        started_at: ISO-8601 timestamp of patrol start
        finished_at: ISO-8601 timestamp of patrol finish
    """
    slot_name: str
    success: bool = True
    events_ingested: int = 0
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class PatrolScheduler:
    """Lightweight daily patrol scheduler with idempotent guards.

    Design:
      - Pure threading.Timer — 零 Celery/Redis/cron 依赖
      - 幂等守卫: 同一 slot 在 60 分钟内不重复执行
      - 后台线程: daemon=True, 不阻塞主进程退出
      - 失败隔离: on_patrol 回调异常被捕获后记录日志, 不影响下次调度

    Usage:
        def my_patrol(slot: PatrolSlot) -> PatrolResult:
            logger.info(f"Patrol slot {slot.name} firing")
            return PatrolResult(slot_name=slot.name, success=True)

        scheduler = PatrolScheduler(
            slots=[
                PatrolSlot("morning", 9, 0, PatrolSlotType.MORNING),
                PatrolSlot("evening", 21, 0, PatrolSlotType.EVENING),
            ],
            on_patrol=my_patrol,
        )
        scheduler.start()
    """

    # 幂等守卫窗口（秒）: 同一 slot 在此窗口内不重复触发
    IDEMPOTENCY_WINDOW_SECONDS: int = 3600  # 60 minutes

    def __init__(
        self,
        slots: List[PatrolSlot],
        on_patrol: Callable[[PatrolSlot], PatrolResult],
    ):
        """Initialize the scheduler.

        Args:
            slots: List of patrol slot definitions.
            on_patrol: Callback invoked when a slot fires.
                       Must be thread-safe and should not raise.
        """
        if not slots:
            raise ValueError("At least one patrol slot is required")

        self._slots = slots
        self._on_patrol = on_patrol
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._lock = threading.Lock()
        # 幂等守卫字典: slot_name -> last trigger datetime
        self._last_patrol_times: Dict[str, datetime.datetime] = {}

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler background loop.

        Calculates the closest future slot and schedules the first timer.
        After each patrol callback completes, schedules the next slot.
        Thread-safe; idempotent (calling start() twice is a no-op).
        """
        with self._lock:
            if self._running:
                logger.warning("PatrolScheduler is already running; start() ignored")
                return
            self._running = True

        self._schedule_next()
        logger.info(
            "PatrolScheduler started: %d slots configured",
            len(self._slots),
        )

    def stop(self) -> None:
        """Stop the scheduler. Cancels any pending timer.

        Thread-safe; idempotent.
        """
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        logger.info("PatrolScheduler stopped")

    def trigger_now(self, slot_name: Optional[str] = None) -> PatrolResult:
        """Manually trigger a patrol slot immediately.

        Used for testing, debugging, or PM override.
        Checks the idempotency guard before firing.

        Args:
            slot_name: Name of the slot to trigger. If None, triggers the next
                       scheduled slot.

        Returns:
            PatrolResult from the callback, or an error result if the slot
            is idempotency-guarded or unknown.
        """
        if slot_name is None:
            next_slot = self._get_next_slot()
            if next_slot is None:
                return PatrolResult(
                    slot_name="unknown",
                    success=False,
                    error="No patrol slots configured",
                )
            slot_name = next_slot.name

        # Find the slot definition
        slot = next((s for s in self._slots if s.name == slot_name), None)
        if slot is None:
            return PatrolResult(
                slot_name=slot_name,
                success=False,
                error=f"Unknown patrol slot: {slot_name}",
            )

        # Check idempotency guard
        with self._lock:
            last_time = self._last_patrol_times.get(slot_name)
            if last_time is not None:
                elapsed = (datetime.datetime.now() - last_time).total_seconds()
                if elapsed < self.IDEMPOTENCY_WINDOW_SECONDS:
                    return PatrolResult(
                        slot_name=slot_name,
                        success=False,
                        error=(
                            f"Idempotency guard: slot '{slot_name}' was triggered "
                            f"{elapsed:.0f}s ago (window={self.IDEMPOTENCY_WINDOW_SECONDS}s)"
                        ),
                    )

        return self._fire_patrol(slot)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def configured_slots(self) -> List[str]:
        return [s.name for s in self._slots]

    # ---------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------

    def _schedule_next(self) -> None:
        """Find the next nearest slot and schedule a Timer."""
        with self._lock:
            if not self._running:
                return

        next_slot = self._get_next_slot()
        if next_slot is None:
            logger.error("PatrolScheduler: no slots configured, cannot schedule")
            return

        now = datetime.datetime.now()
        next_time = next_slot.next_trigger(now)
        delay = max(0.0, (next_time - now).total_seconds())

        logger.debug(
            "Scheduling slot '%s' in %.1f seconds (at %s)",
            next_slot.name,
            delay,
            next_time.isoformat(),
        )

        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(delay, self._on_timer_fire, args=[next_slot])
            self._timer.daemon = True
            self._timer.start()

    def _get_next_slot(self) -> Optional[PatrolSlot]:
        """Return the slot with the nearest future trigger time."""
        now = datetime.datetime.now()
        best: Optional[PatrolSlot] = None
        best_delta: float = float("inf")

        for slot in self._slots:
            delta = (slot.next_trigger(now) - now).total_seconds()
            if delta < best_delta:
                best_delta = delta
                best = slot

        return best

    def _on_timer_fire(self, slot: PatrolSlot) -> None:
        """Called by Timer thread when a slot fires.

        Executes the patrol callback, then schedules the next slot.
        """
        self._fire_patrol(slot)
        self._schedule_next()

    def _fire_patrol(self, slot: PatrolSlot) -> PatrolResult:
        """Execute the patrol callback with safety wrapping.

        All exceptions from on_patrol are caught and returned as error results.
        Idempotency guard is updated regardless of success/failure.
        """
        started_at = datetime.datetime.now().isoformat()
        logger.info("Patrol slot '%s' firing at %s", slot.name, started_at)

        result: PatrolResult
        try:
            # Update idempotency guard BEFORE the call (prevent double-trigger)
            with self._lock:
                self._last_patrol_times[slot.name] = datetime.datetime.now()

            result = self._on_patrol(slot)
            result.slot_name = slot.name
            result.started_at = started_at
            result.finished_at = datetime.datetime.now().isoformat()

        except Exception as e:
            logger.exception("Patrol slot '%s' failed with exception", slot.name)
            result = PatrolResult(
                slot_name=slot.name,
                success=False,
                error=f"Unhandled exception: {type(e).__name__}: {e}",
                started_at=started_at,
                finished_at=datetime.datetime.now().isoformat(),
            )

        if result.success:
            logger.info(
                "Patrol slot '%s' completed: %d events ingested",
                slot.name,
                result.events_ingested,
            )
        else:
            logger.error(
                "Patrol slot '%s' failed: %s",
                slot.name,
                result.error,
            )

        return result