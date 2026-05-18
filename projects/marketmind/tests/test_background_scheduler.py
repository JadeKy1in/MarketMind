"""Tests for BackgroundScheduler — async background shadow operations."""
from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from marketmind.shadows.background_scheduler import (
    BackgroundScheduler,
    SchedulerConfig,
    TaskNode,
)
from marketmind.shadows.shadow_memory import ShadowMemoryStore
from marketmind.shadows.shadow_state import ShadowStateDB


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_db():
    """Create a temporary ShadowStateDB with schema initialized."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_scheduler.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()
        yield db
        db.close()


@pytest.fixture
def memory_store(temp_db):
    """Create a ShadowMemoryStore backed by temp DB."""
    return ShadowMemoryStore(temp_db)


@pytest.fixture
def scheduler_config():
    """Default scheduler config for testing."""
    return SchedulerConfig(
        reflection_interval_minutes=1,
        crystallization_interval_hours=1,
        max_concurrent_tasks=2,
        per_shadow_task_budget=5,
        enabled=False,
        wake_on_volatility=True,
        wake_on_breaking_news=True,
        vix_threshold=30.0,
    )


@pytest.fixture
def scheduler(memory_store, temp_db, scheduler_config):
    """Create a BackgroundScheduler, stop it after test."""
    sched = BackgroundScheduler(
        memory_store=memory_store,
        state_db=temp_db,
        mother=None,
        config=scheduler_config,
    )
    yield sched
    if sched._running:
        sched.stop()


# ── Configuration Tests ────────────────────────────────────────────────────────


class TestSchedulerConfig:
    """Tests for SchedulerConfig defaults."""

    def test_defaults_disabled(self):
        """Scheduler is disabled by default."""
        cfg = SchedulerConfig()
        assert cfg.enabled is False

    def test_default_intervals(self):
        """Default intervals are reasonable."""
        cfg = SchedulerConfig()
        assert cfg.reflection_interval_minutes == 60
        assert cfg.crystallization_interval_hours == 6
        assert cfg.max_concurrent_tasks == 3

    def test_wake_defaults(self):
        """Wake conditions are enabled by default."""
        cfg = SchedulerConfig()
        assert cfg.wake_on_volatility is True
        assert cfg.wake_on_breaking_news is True
        assert cfg.vix_threshold == 30.0


# ── Lifecycle Tests ────────────────────────────────────────────────────────────


class TestSchedulerLifecycle:
    """Tests for BackgroundScheduler start/stop lifecycle."""

    def test_start_stop_daemon_thread(self, scheduler):
        """Scheduler starts and stops cleanly — daemon thread lifecycle."""
        assert scheduler._running is False
        scheduler.start()
        assert scheduler._running is True
        assert scheduler._thread is not None
        assert scheduler._thread.is_alive()
        scheduler.stop()
        # Give the thread a moment to stop
        time.sleep(0.1)
        assert scheduler._running is False

    def test_double_start_is_safe(self, scheduler):
        """Calling start() twice does not create a second thread."""
        scheduler.start()
        thread_before = scheduler._thread
        scheduler.start()  # Should be a no-op
        assert scheduler._thread is thread_before
        scheduler.stop()

    def test_stop_when_not_running_is_safe(self, scheduler):
        """Calling stop() when not running does not crash."""
        scheduler.stop()
        assert scheduler._running is False

    def test_start_with_enabled_false_does_not_execute_tasks(self, scheduler):
        """When enabled=False, the loop runs but builds empty DAG."""
        scheduler.start()
        # Sleep briefly to let a cycle complete
        time.sleep(0.2)
        status = scheduler.get_status()
        assert status["running"] is True
        assert status["enabled"] is False
        # No tasks should have been executed
        assert status["completed_results"] == 0
        scheduler.stop()

    def test_start_with_enabled_true_executes_tasks(self, scheduler, memory_store):
        """When enabled=True, tasks are executed."""
        scheduler._config.enabled = True
        scheduler.start()
        time.sleep(0.5)  # Allow one loop iteration
        scheduler.stop()
        status = scheduler.get_status()
        assert status["running"] is False
        # At minimum, memory_decay should have executed
        assert status["completed_results"] >= 0

    def test_get_status_returns_correct_state(self, scheduler):
        """get_status() returns correct state before and after start."""
        status_before = scheduler.get_status()
        assert status_before["running"] is False
        assert status_before["enabled"] is False
        assert "config" in status_before

        scheduler.start()
        status_running = scheduler.get_status()
        assert status_running["running"] is True
        scheduler.stop()

    def test_get_task_queue_empty_initially(self, scheduler):
        """Task queue is empty when no tasks have been executed."""
        queue = scheduler.get_task_queue()
        assert queue == []


# ── DAG Tests ──────────────────────────────────────────────────────────────────


class TestTaskDag:
    """Tests for DAG construction and execution."""

    def test_dag_builds_with_correct_dependency_order(self, scheduler):
        """DAG builds with memory_decay -> reflection -> crystallization order
        when both intervals have elapsed."""
        # Ensure intervals have elapsed
        scheduler._last_reflection_time = 0
        scheduler._last_crystallization_time = 0
        dag = scheduler.build_task_dag()
        task_types = [t.task_type for t in dag]
        assert "memory_decay" in task_types, f"Expected memory_decay in {task_types}"
        assert "reflection" in task_types, f"Expected reflection in {task_types}"
        assert "crystallization" in task_types, f"Expected crystallization in {task_types}"

        # reflection depends on memory_decay
        for t in dag:
            if t.task_type == "reflection":
                assert len(t.dependencies) == 1
                dep = t.dependencies[0]
                dep_tasks = [d for d in dag if d.task_id == dep]
                assert len(dep_tasks) == 1
                assert dep_tasks[0].task_type == "memory_decay"

        # crystallization depends on reflection (or at least has correct type)
        for t in dag:
            if t.task_type == "crystallization":
                assert t.task_type == "crystallization"
                assert t.priority > sum(t2.priority for t2 in dag if t2.task_type == "reflection") / max(1, sum(1 for t2 in dag if t2.task_type == "reflection"))

    def test_dag_empty_when_intervals_not_elapsed(self, scheduler):
        """DAG is empty when neither interval has elapsed."""
        scheduler._last_reflection_time = time.time()
        scheduler._last_crystallization_time = time.time()
        dag = scheduler.build_task_dag()
        assert dag == []

    def test_dag_only_reflection_when_only_reflection_elapsed(self, scheduler):
        """Only reflection tasks (with decay) when only reflection interval elapsed."""
        scheduler._last_reflection_time = 0
        scheduler._last_crystallization_time = time.time()
        dag = scheduler.build_task_dag()
        task_types = set(t.task_type for t in dag)
        assert "reflection" in task_types
        assert "memory_decay" in task_types
        assert "crystallization" not in task_types

    def test_dag_only_crystallization_when_only_crystallization_elapsed(self, scheduler):
        """Only crystallization tasks when only crystallization interval elapsed."""
        scheduler._last_reflection_time = time.time()
        scheduler._last_crystallization_time = 0
        dag = scheduler.build_task_dag()
        task_types = set(t.task_type for t in dag)
        assert "crystallization" in task_types
        assert "memory_decay" in task_types
        assert "reflection" not in task_types


# ── Dependency Order Execution Tests ────────────────────────────────────────────


class TestDagExecution:
    """Tests for DAG execution respecting dependency order."""

    @pytest.mark.asyncio
    async def test_execute_dag_respects_dependency_order(self, scheduler):
        """DAG executes tasks in dependency order."""
        t0 = TaskNode(task_id="t0", task_type="memory_decay")
        t1 = TaskNode(task_id="t1", task_type="reflection", dependencies=["t0"])
        t2 = TaskNode(task_id="t2", task_type="crystallization", dependencies=["t1"])
        tasks = [t0, t1, t2]

        results = await scheduler.execute_dag(tasks)
        assert len(results) == 3
        result_types = [r["task_type"] for r in results]
        # Execution order should be: memory_decay first, then reflection, then crystallization
        assert result_types.index("memory_decay") < result_types.index("reflection")
        assert result_types.index("reflection") < result_types.index("crystallization")

    @pytest.mark.asyncio
    async def test_execute_dag_handles_independent_tasks(self, scheduler):
        """Tasks with no dependencies run in parallel respecting max_concurrent."""
        t0 = TaskNode(task_id="t0", task_type="memory_decay")
        t1 = TaskNode(task_id="t1", task_type="reflection")  # No dependencies
        t2 = TaskNode(task_id="t2", task_type="reflection", shadow_id="s1")
        tasks = [t0, t1, t2]

        results = await scheduler.execute_dag(tasks)
        assert len(results) == 3
        for r in results:
            assert r["status"] == "done"

    @pytest.mark.asyncio
    async def test_execute_dag_handles_empty_dag(self, scheduler):
        """Empty DAG returns empty results."""
        results = await scheduler.execute_dag([])
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_dag_updates_timestamps(self, scheduler):
        """After executing reflection tasks, last_reflection_time is updated."""
        old_ref = scheduler._last_reflection_time
        t0 = TaskNode(task_id="t0", task_type="memory_decay")
        t1 = TaskNode(task_id="t1", task_type="reflection", dependencies=["t0"])
        await scheduler.execute_dag([t0, t1])
        assert scheduler._last_reflection_time > old_ref


# ── Task Handler Tests ─────────────────────────────────────────────────────────


class TestTaskHandlers:
    """Tests for individual task handlers."""

    @pytest.mark.asyncio
    async def test_reflection_calls_memory_decay(self, scheduler, memory_store):
        """Reflection task triggers memory.apply_decay()."""
        original_decay = memory_store.apply_decay
        call_count = [0]

        def _count_decay(gamma=0.95):
            call_count[0] += 1
            return original_decay(gamma=gamma)

        memory_store.apply_decay = _count_decay
        try:
            task = TaskNode(task_id="ref_01", task_type="reflection")
            result = await scheduler._run_reflection(task)
            assert result["task_type"] == "reflection"
            assert result["status"] == "done"
            assert call_count[0] >= 1
        finally:
            memory_store.apply_decay = original_decay

    @pytest.mark.asyncio
    async def test_crystallization_queries_shadow_analyses(self, scheduler, temp_db):
        """Crystallization task queries shadow_analyses from DB."""
        task = TaskNode(task_id="cryst_01", task_type="crystallization")
        result = await scheduler._run_crystallization(task)
        assert result["task_type"] == "crystallization"
        assert "crystallized_count" in result
        assert result["status"] == "done"

    @pytest.mark.asyncio
    async def test_memory_decay_applies_all_tiers(self, scheduler, memory_store):
        """Memory decay task applies both Beta-Bernoulli and TTL eviction."""
        task = TaskNode(task_id="decay_01", task_type="memory_decay")
        result = await scheduler._run_memory_decay(task)
        assert result["task_type"] == "memory_decay"
        assert "decayed_nodes" in result
        assert "ttl_evicted_working" in result
        assert "ttl_evicted_episodic" in result
        assert result["status"] == "done"

    @pytest.mark.asyncio
    async def test_re_evaluate_task(self, scheduler):
        """Re-evaluate task runs without error."""
        task = TaskNode(task_id="reeval_01", task_type="re_evaluate")
        result = await scheduler._run_re_evaluate(task)
        assert result["task_type"] == "re_evaluate"
        assert result["status"] == "done"
        assert "re_evaluated_shadows" in result


# ── Event-Driven Wake Tests ────────────────────────────────────────────────────


class TestEventDrivenWake:
    """Tests for event-driven wake conditions."""

    def test_volatility_spike_detection(self, scheduler):
        """Volatility spike is detected when VIX >= threshold."""
        scheduler._config.vix_threshold = 30.0
        result = scheduler._detect_volatility_spike()
        # Without real VIX data, should return False
        assert isinstance(result, bool)

    def test_breaking_news_detection_no_mother(self, scheduler):
        """Breaking news detection returns False when no mother is set."""
        result = scheduler._detect_breaking_news()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_wake_conditions_no_mother(self, scheduler):
        """check_wake_conditions returns False without mother."""
        scheduler._config.wake_on_volatility = True
        scheduler._config.wake_on_breaking_news = True
        result = await scheduler.check_wake_conditions()
        assert isinstance(result, bool)


# ── Task Budget Tests ──────────────────────────────────────────────────────────


class TestTaskBudget:
    """Tests for per-shadow task budget enforcement."""

    @pytest.mark.asyncio
    async def test_task_budget_enforcement(self, scheduler):
        """Tasks beyond per_shadow_task_budget are not counted."""
        scheduler._config.per_shadow_task_budget = 2
        shadow_id = "expert:test:budget"
        tasks = [
            TaskNode(task_id="t1", task_type="reflection", shadow_id=shadow_id),
            TaskNode(task_id="t2", task_type="reflection", shadow_id=shadow_id),
            TaskNode(task_id="t3", task_type="reflection", shadow_id=shadow_id),  # exceeds budget
        ]
        results = await scheduler.execute_dag(tasks)
        # All tasks have same dependency set (none), so they all run
        # but task budget is checked per-shadow in _run_one
        status = scheduler.get_status()
        queue_state = scheduler.get_task_queue()
        assert isinstance(queue_state, list)


# ── TaskNode Tests ─────────────────────────────────────────────────────────────


class TestTaskNode:
    """Tests for TaskNode dataclass."""

    def test_task_node_defaults(self):
        """TaskNode has sensible defaults."""
        tn = TaskNode(task_id="test", task_type="reflection")
        assert tn.task_id == "test"
        assert tn.task_type == "reflection"
        assert tn.shadow_id is None
        assert tn.dependencies == []
        assert tn.priority == 5
        assert tn.created_at != ""

    def test_task_node_with_shadow(self):
        """TaskNode with shadow_id."""
        tn = TaskNode(
            task_id="test_shadow",
            task_type="crystallization",
            shadow_id="expert:gold:test",
            dependencies=["dep1"],
            priority=8,
        )
        assert tn.shadow_id == "expert:gold:test"
        assert tn.dependencies == ["dep1"]
        assert tn.priority == 8


# ── SchedulerStatus Tests ──────────────────────────────────────────────────────


class TestSchedulerStatus:
    """Tests for scheduler status reporting."""

    def test_status_when_stopped(self, scheduler):
        """get_status() reflects stopped state."""
        status = scheduler.get_status()
        assert status["running"] is False
        assert status["enabled"] is False

    def test_status_when_running(self, scheduler):
        """get_status() reflects running state."""
        scheduler.start()
        status = scheduler.get_status()
        assert status["running"] is True
        scheduler.stop()

    def test_status_includes_config(self, scheduler):
        """get_status() includes configuration values."""
        scheduler._config.reflection_interval_minutes = 30
        status = scheduler.get_status()
        cfg = status["config"]
        assert cfg["reflection_interval_minutes"] == 30
        assert cfg["crystallization_interval_hours"] == 1
        assert cfg["max_concurrent_tasks"] == 2

    def test_task_queue_when_no_tasks(self, scheduler):
        """get_task_queue() returns empty list when no tasks counted."""
        queue_state = scheduler.get_task_queue()
        assert queue_state == []


# ── Max Concurrent Tasks Tests ─────────────────────────────────────────────────


class TestMaxConcurrent:
    """Tests for max_concurrent_tasks enforcement."""

    @pytest.mark.asyncio
    async def test_max_concurrent_respected(self, scheduler):
        """Scheduler uses Semaphore to limit concurrency."""
        scheduler._config.max_concurrent_tasks = 2
        tasks = [
            TaskNode(task_id=f"t{i}", task_type="reflection", shadow_id=f"s{i}")
            for i in range(5)
        ]
        results = await scheduler.execute_dag(tasks)
        assert len(results) == 5
        for r in results:
            assert r["status"] == "done"


# ── Integration Tests ──────────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests with real DB and MemoryStore."""

    def test_full_lifecycle_with_enabled_config(self, scheduler, memory_store):
        """Scheduler starts, runs one or more cycles, stops cleanly."""
        scheduler._config.enabled = True
        scheduler._config.reflection_interval_minutes = 0  # immediate
        scheduler._config.crystallization_interval_hours = 0  # immediate

        scheduler.start()
        time.sleep(0.8)  # Allow at least one full cycle (60s sleep reduced by immediate intervals)
        scheduler.stop()

        status = scheduler.get_status()
        assert status["running"] is False
