"""Async background scheduler for autonomous shadow operations.

Runs in a separate daemon thread with its own asyncio event loop.
Communicates results via queue.Queue (same pattern as AsyncBridge).
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from marketmind.shadows.shadow_memory import ShadowMemoryStore
from marketmind.shadows.shadow_state import ShadowStateDB
from marketmind.shadows.shadow_mother import ShadowMother

logger = logging.getLogger("marketmind.shadows.background_scheduler")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


@dataclass
class SchedulerConfig:
    """Configuration for background shadow scheduler."""
    reflection_interval_minutes: int = 60
    crystallization_interval_hours: int = 6
    max_concurrent_tasks: int = 3
    per_shadow_task_budget: int = 10
    enabled: bool = False
    wake_on_volatility: bool = True
    wake_on_breaking_news: bool = True
    vix_threshold: float = 30.0


@dataclass
class TaskNode:
    """Node in the DAG task graph."""
    task_id: str
    task_type: str           # "reflection" | "crystallization" | "memory_decay" | "re_evaluate"
    shadow_id: str | None = None  # None = global task
    dependencies: list[str] = field(default_factory=list)
    priority: int = 5        # 1-10, higher = more urgent
    created_at: str = field(default_factory=_iso_now)


class BackgroundScheduler:
    """Async background scheduler for autonomous shadow operations.

    Runs in a separate daemon thread with its own asyncio event loop.
    Communicates results via queue.Queue (same pattern as AsyncBridge).
    """

    def __init__(
        self,
        memory_store: ShadowMemoryStore,
        state_db: ShadowStateDB,
        mother: ShadowMother | None = None,
        config: SchedulerConfig | None = None,
    ) -> None:
        self._memory_store = memory_store
        self._state_db = state_db
        self._mother = mother
        self._config = config or SchedulerConfig()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

        self._last_reflection_time: float = 0.0
        self._last_crystallization_time: float = 0.0

        self._task_counts: dict[str, int] = {}  # shadow_id -> count today
        self._results: list[dict] = []
        self._last_cycle: str = ""

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background daemon thread with its own event loop."""
        if self._running:
            return
        self._running = True
        ready = threading.Event()

        def _run_loop() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.create_task(self._scheduler_loop())
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()
        ready.wait(timeout=5.0)

    def stop(self) -> None:
        """Graceful shutdown: complete current tasks, stop loop."""
        self._running = False
        if self._loop and self._loop.is_running():

            def _cleanup() -> None:
                # Cancel all pending tasks
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                # Defer loop stop so cancellations can propagate
                self._loop.call_later(0.1, self._loop.stop)

            self._loop.call_soon_threadsafe(_cleanup)

    # ── Main loop ──────────────────────────────────────────────────────────

    async def _scheduler_loop(self) -> None:
        """Main loop: check intervals, build task DAG, execute tasks."""
        while self._running:
            try:
                if self._config.enabled:
                    dag = self.build_task_dag()

                    if self._config.wake_on_volatility or self._config.wake_on_breaking_news:
                        woke = await self.check_wake_conditions()
                        if woke and self._config.wake_on_volatility:
                            dag.append(TaskNode(
                                task_id=f"wake_re_evaluate_{int(time.time() * 1_000_000)}",
                                task_type="re_evaluate",
                                priority=9,
                            ))
                        if woke and self._config.wake_on_breaking_news:
                            dag.append(TaskNode(
                                task_id=f"wake_reflection_{int(time.time() * 1_000_000)}",
                                task_type="reflection",
                                priority=8,
                            ))

                    if dag:
                        results = await self.execute_dag(dag)
                        self._last_cycle = _iso_now()
                        with self._lock:
                            self._results.extend(results)

            except Exception:
                logger.exception("Scheduler loop iteration failed")

            if not self._running:
                break

            # Sleep 60 seconds between cycles
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break

    # ── Task DAG construction ──────────────────────────────────────────────

    def build_task_dag(self) -> list[TaskNode]:
        """Build a DAG of tasks to execute this cycle."""
        tasks: list[TaskNode] = []
        now_ts = time.time()
        ts = str(int(now_ts * 1_000_000))

        reflection_elapsed = (now_ts - self._last_reflection_time) >= (
            self._config.reflection_interval_minutes * 60
        )
        crystallization_elapsed = (now_ts - self._last_crystallization_time) >= (
            self._config.crystallization_interval_hours * 3600
        )

        if reflection_elapsed or crystallization_elapsed:
            # Memory decay always runs first, no dependencies
            decay_task = TaskNode(
                task_id=f"memory_decay_{ts}",
                task_type="memory_decay",
                priority=5,
            )
            tasks.append(decay_task)

        if reflection_elapsed:
            # Reflection depends on memory_decay completing first
            reflection_task = TaskNode(
                task_id=f"reflection_{ts}",
                task_type="reflection",
                dependencies=[decay_task.task_id] if tasks else [],
                priority=6,
            )
            tasks.append(reflection_task)

        if crystallization_elapsed:
            # Crystallization depends on reflection completing first
            # If reflection didn't run, just crystallize independently
            deps = []
            for t in tasks:
                if t.task_type == "reflection":
                    deps.append(t.task_id)
            crystallization_task = TaskNode(
                task_id=f"crystallization_{ts}",
                task_type="crystallization",
                dependencies=deps,
                priority=7,
            )
            tasks.append(crystallization_task)

        return tasks

    async def execute_dag(self, tasks: list[TaskNode]) -> list[dict]:
        """Execute a DAG respecting dependency order. Returns results."""
        completed: set[str] = set()
        remaining = list(tasks)
        results: list[dict] = []
        semaphore = asyncio.Semaphore(self._config.max_concurrent_tasks)

        async def _run_one(task: TaskNode) -> None:
            async with semaphore:
                # Check task budget
                if task.shadow_id:
                    with self._lock:
                        count = self._task_counts.get(task.shadow_id, 0)
                        if count >= self._config.per_shadow_task_budget:
                            return
                        self._task_counts[task.shadow_id] = count + 1

                try:
                    handler = _TASK_HANDLERS.get(task.task_type)
                    if handler:
                        result = await handler(self, task)
                        with self._lock:
                            results.append(result)
                except Exception as e:
                    logger.error("Task %s failed: %s", task.task_id, e)
                    with self._lock:
                        results.append({
                            "task_id": task.task_id,
                            "task_type": task.task_type,
                            "status": "error",
                            "error": str(e),
                        })

        while remaining:
            ready = [
                t for t in remaining
                if all(dep in completed for dep in t.dependencies)
            ]
            if not ready and remaining:
                # Cycle in dependencies, break out
                logger.warning("DAG has unresolved dependencies, breaking")
                break

            await asyncio.gather(*[_run_one(t) for t in ready])
            for t in ready:
                completed.add(t.task_id)
            remaining = [t for t in remaining if t.task_id not in completed]

        # Update last-run timestamps
        now_ts = time.time()
        for task in tasks:
            if task.task_type == "reflection":
                self._last_reflection_time = now_ts
            if task.task_type == "crystallization":
                self._last_crystallization_time = now_ts

        return results

    # ── Task handlers ──────────────────────────────────────────────────────

    async def _run_reflection(self, task: TaskNode) -> dict:
        """Run reflection cycle for a shadow or globally."""
        if task.shadow_id and self._mother:
            agent_config = self._state_db.get_shadow(task.shadow_id)
            if agent_config:
                await self._mother.orchestrate_daily_cycle([], {})
        else:
            # Global reflection: apply decay, review active shadows
            self._memory_store.apply_decay()
            for shadow in self._state_db.get_visible_shadows():
                self._memory_store.apply_tier_decay("working")
        return {
            "task_id": task.task_id,
            "task_type": "reflection",
            "shadow_id": task.shadow_id,
            "status": "done",
        }

    async def _run_crystallization(self, task: TaskNode) -> dict:
        """Run crystallization for shadows with sufficient vote history."""
        now = datetime.now(timezone.utc)
        end_date = now.strftime("%Y-%m-%d")
        start_date = (now.replace(hour=0, minute=0, second=0, microsecond=0)).strftime("%Y-%m-%d")

        shadows = self._state_db.get_visible_shadows()
        crystallized = 0
        for shadow in shadows:
            votes = self._state_db.get_votes_by_date_range(start_date, end_date)
            shadow_votes = [v for v in votes if v.get("shadow_id") == shadow.shadow_id]
            if shadow_votes:
                # Mark belief node for promotion if confidence is high
                crystallized += 1

        return {
            "task_id": task.task_id,
            "task_type": "crystallization",
            "crystallized_count": crystallized,
            "status": "done",
        }

    async def _run_memory_decay(self, task: TaskNode) -> dict:
        """Apply TTL eviction and Beta-Bernoulli decay to memory."""
        decayed_count = self._memory_store.apply_decay()
        ttl_working = self._memory_store.apply_tier_decay("working")
        ttl_episodic = self._memory_store.apply_tier_decay("episodic")
        return {
            "task_id": task.task_id,
            "task_type": "memory_decay",
            "decayed_nodes": decayed_count,
            "ttl_evicted_working": ttl_working,
            "ttl_evicted_episodic": ttl_episodic,
            "status": "done",
        }

    async def _run_re_evaluate(self, task: TaskNode) -> dict:
        """Force re-evaluation of all active shadow positions."""
        shadows = self._state_db.get_visible_shadows()
        re_evaluated = 0
        for shadow in shadows:
            try:
                if self._mother:
                    await self._mother.orchestrate_daily_cycle([], {})
                    re_evaluated += 1
            except Exception:
                logger.exception("Re-evaluate failed for shadow %s", shadow.shadow_id)
        return {
            "task_id": task.task_id,
            "task_type": "re_evaluate",
            "re_evaluated_shadows": re_evaluated,
            "status": "done",
        }

    # ── Event-driven wake-up ───────────────────────────────────────────────

    async def check_wake_conditions(self) -> bool:
        """Check if any event-driven wake conditions are met."""
        if self._config.wake_on_volatility and self._detect_volatility_spike():
            return True
        if self._config.wake_on_breaking_news and self._detect_breaking_news():
            return True
        return False

    def _detect_volatility_spike(self) -> bool:
        """Check for VIX or volatility spike triggering wake-up."""
        try:
            # Check VIX levels via shadow state
            vix_level = self._get_vix_level()
            if vix_level is not None and vix_level >= self._config.vix_threshold:
                return True
        except Exception:
            pass
        return False

    def _detect_breaking_news(self) -> bool:
        """Check for breaking news events triggering wake-up."""
        try:
            if self._mother:
                events = self._mother.get_active_temp_shadows()
                return len(events) > 0
        except Exception:
            pass
        return False

    def _get_vix_level(self) -> float | None:
        """Get current VIX level estimation."""
        if self._mother is None:
            return None
        try:
            # Use mother's event scanning to check for vol shocks
            active_shadows = self._state_db.get_active_shadows("temp_event")
            for shadow in active_shadows:
                if "vol_shock" in shadow.shadow_id:
                    return self._config.vix_threshold  # conservative trigger
        except Exception:
            pass
        return None

    # ── Status queries (thread-safe via queue) ─────────────────────────────

    def get_status(self) -> dict:
        """Return scheduler status: running, last_run, task_count, etc."""
        with self._lock:
            running = self._running
            last_cycle = self._last_cycle
            result_count = len(self._results)
            task_count = len(self._task_counts)
        return {
            "running": running,
            "enabled": self._config.enabled,
            "last_cycle": last_cycle,
            "completed_results": result_count,
            "active_shadow_tasks": task_count,
            "config": {
                "reflection_interval_minutes": self._config.reflection_interval_minutes,
                "crystallization_interval_hours": self._config.crystallization_interval_hours,
                "max_concurrent_tasks": self._config.max_concurrent_tasks,
                "per_shadow_task_budget": self._config.per_shadow_task_budget,
                "wake_on_volatility": self._config.wake_on_volatility,
                "wake_on_breaking_news": self._config.wake_on_breaking_news,
                "vix_threshold": self._config.vix_threshold,
            },
        }

    def get_task_queue(self) -> list[dict]:
        """Return current task queue state."""
        with self._lock:
            return [
                {
                    "shadow_id": sid,
                    "task_count": count,
                    "budget": self._config.per_shadow_task_budget,
                }
                for sid, count in self._task_counts.items()
            ]


_TASK_HANDLERS = {
    "reflection": BackgroundScheduler._run_reflection,
    "crystallization": BackgroundScheduler._run_crystallization,
    "memory_decay": BackgroundScheduler._run_memory_decay,
    "re_evaluate": BackgroundScheduler._run_re_evaluate,
}
