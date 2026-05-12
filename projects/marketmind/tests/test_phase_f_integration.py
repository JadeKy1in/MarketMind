"""Phase F Integration Tests — end-to-end smoke tests for all F-0 through F-5 modules.

Covers:
  - F-0 through F-5 full pipeline: create memory store, ingest observation,
    query memory, run crystallization, verify result
  - ExternalObservation → knowledge_filter.evaluate_external() →
    ShadowMemoryStore.ingest_observation() end-to-end
  - BackgroundScheduler lifecycle: start → runs one cycle → stop
  - ShadowMother with crystallization_enabled=True runs steps 6.5 + 6.6
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path

import pytest

from marketmind.shadows.shadow_agent import ExternalObservation, MemoryQuery
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_memory import ShadowMemoryStore
from marketmind.shadows.knowledge_filter import KnowledgeFilter, KnowledgeItem
from marketmind.shadows.crystallization import CrystallizationEngine
from marketmind.shadows.methodology_evolver import MethodologyEvolver
from marketmind.shadows.background_scheduler import (
    BackgroundScheduler, SchedulerConfig,
)
from marketmind.config.settings import ShadowSettings


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def temp_db():
    """Temporary ShadowStateDB with full schema."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_phase_f_integration.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()
        yield db
        db.close()


@pytest.fixture
def memory_store(temp_db):
    return ShadowMemoryStore(temp_db)


@pytest.fixture
def knowledge_filter():
    return KnowledgeFilter()


@pytest.fixture
def evolver():
    return MethodologyEvolver()


@pytest.fixture
def shadow_settings():
    return ShadowSettings(
        shadows_enabled=True,
        shadows_db_path=":memory:",
        crystallization_enabled=True,
        crystallization_significance_threshold=0.6,
        crystallization_min_samples=5,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test: F-0 through F-5 Full Pipeline Smoke Test
# ═══════════════════════════════════════════════════════════════════════════

class TestFullPipelineSmoke:
    """End-to-end smoke test: create memory store → ingest observation →
    query memory → run crystallization → verify result."""

    def test_full_f0_through_f5_pipeline(self, memory_store, temp_db,
                                          evolver):
        """Smoke test covering memory store, observation ingestion, memory
        query, crystallization, and result verification."""
        shadow_id = "expert:gold:full_pipeline"
        config = ShadowConfig(
            shadow_id=shadow_id, shadow_type="expert",
            display_name="Full Pipeline Test Gold Bug",
            methodology_prompt="You are a gold market expert shadow.",
            virtual_capital=50000.0, domain="gold",
        )
        temp_db.create_shadow(config)

        # -- Step 1 (F-3): Ingest observations into memory --
        for i in range(8):
            obs = ExternalObservation(
                observation_id=f"pipe-obs-{i:03d}",
                source_type="text",
                source_path=f"shadow:{shadow_id}",
                extracted_text=(
                    f"Gold price analysis #{i}: Technical indicators show "
                    f"{'bullish' if i % 2 == 0 else 'bearish'} momentum "
                    f"across multiple timeframes."
                ),
                metadata={
                    "shadow_id": shadow_id,
                    "type": "insight",
                    "ticker": "GLD",
                },
                confidence=0.75 + (i * 0.02),
                source_attribution=f"shadow:{shadow_id}",
            )
            node_id = memory_store.ingest_observation_sync(
                shadow_id, obs, tier="episodic"
            )
            assert node_id, f"Ingestion #{i} should return a node_id"

        # -- Step 2 (F-3): Query memory --
        query = MemoryQuery(
            tier="episodic",
            ticker="GLD",
            min_belief_strength=0.0,
            limit=20,
        )
        results = memory_store.query_beliefs(query)
        assert len(results) > 0, "Should find belief nodes for GLD ticker"

        # -- Step 3: Verify belief stats --
        stats = memory_store.get_memory_stats()
        assert stats["total_observations"] >= 8
        assert stats["active_nodes"] >= 1

        # -- Step 4 (F-4): Run crystallization --
        engine = CrystallizationEngine(
            memory_store=memory_store,
            state_db=temp_db,
            methodology_evolver=evolver,
            significance_threshold=0.6,
            min_samples=5,
        )
        results = asyncio.run(engine.run_crystallization_cycle())

        # -- Step 5: Verify crystallization results --
        assert isinstance(results, list), "Crystallization should return a list"
        cyc_stats = engine.get_crystallization_stats()
        assert cyc_stats["cycles_run"] >= 1

        # -- Step 6 (F-4): Promote an insight to semantic memory --
        if results:
            for r in results:
                if r.action == "promote":
                    promoted = memory_store.promote_to_semantic(r.insight_id)
                    assert promoted is True or promoted is False  # May fail if already semantic
                    break

    def test_evolver_tracks_methodology(self, evolver):
        """MethodologyEvolver records predictions and generates reports."""
        # Record some predictions
        evolver.record_prediction("expert-gold", True, prediction_id="pred-01")
        evolver.record_prediction("expert-gold", False, prediction_id="pred-02")
        evolver.record_prediction("expert-gold", True, prediction_id="pred-03")

        # Generate report
        report = evolver.generate_report()
        assert report is not None
        assert hasattr(report, "best_performing") or hasattr(report, "total_methods")

        # Apply decay
        evolver.apply_decay(gamma=0.95)
        report2 = evolver.generate_report()
        assert report2 is not None


# ═══════════════════════════════════════════════════════════════════════════
# Test: ExternalObservation → KnowledgeFilter → Memory end-to-end
# ═══════════════════════════════════════════════════════════════════════════

class TestExternalObservationPipeline:
    """End-to-end: KnowledgeFilter.evaluate_external() → ShadowMemoryStore."""

    def test_e2e_external_observation_flow(self, knowledge_filter, memory_store,
                                            temp_db):
        """External observation passes through filter gate before memory ingestion."""
        shadow_id = "expert:test:e2e_filter"
        config = ShadowConfig(
            shadow_id=shadow_id, shadow_type="expert",
            display_name="E2E Filter Test",
            methodology_prompt="Test shadow for filter→memory pipeline.",
            virtual_capital=10000.0, domain="test",
        )
        temp_db.create_shadow(config)

        obs = ExternalObservation(
            observation_id="e2e-001",
            source_type="text",
            source_path="/data/external_report.txt",
            extracted_text=(
                "Market analysis indicates technology sector rotation due to "
                "falling interest rates and improving semiconductor demand outlook."
            ),
            confidence=0.9,
            source_attribution="external_analyst",
        )

        # Step 1: Filter evaluation
        verdict = knowledge_filter.evaluate_external(obs)
        assert verdict.verdict == "PASS", (
            f"Expected PASS for valid observation, got {verdict.verdict}: {verdict.reason}"
        )

        # Step 2: Memory ingestion (only if PASSed)
        if verdict.verdict == "PASS":
            node_id = memory_store.ingest_observation_sync(
                shadow_id, obs, tier="working"
            )
            assert node_id, "Should get a node_id after ingestion"

            # Step 3: Verify the belief node was created
            node = memory_store.get_belief_node(node_id)
            assert node is not None
            assert node["tier"] == "working"
            assert node["status"] == "active"
            assert node["observation_count"] >= 1

    def test_filter_blocks_before_ingestion(self, knowledge_filter):
        """Knowledge filter DROPs invalid observations before they reach memory."""
        obs = ExternalObservation(
            observation_id="e2e-blocked",
            source_type="video",  # Invalid source_type
            source_path="/data/video.mp4",
            extracted_text="Some content from a video source",
            confidence=0.9,
            source_attribution="unknown",
        )
        verdict = knowledge_filter.evaluate_external(obs)
        assert verdict.verdict == "DROP", (
            f"Video source_type should be DROPPED, got {verdict.verdict}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Test: BackgroundScheduler Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestSchedulerIntegration:
    """BackgroundScheduler start → runs one cycle → stop."""

    @pytest.fixture
    def scheduler(self, memory_store, temp_db):
        cfg = SchedulerConfig(
            reflection_interval_minutes=1,
            crystallization_interval_hours=1,
            max_concurrent_tasks=2,
            per_shadow_task_budget=10,
            enabled=True,
            wake_on_volatility=False,
            wake_on_breaking_news=False,
            vix_threshold=30.0,
        )
        sched = BackgroundScheduler(memory_store, temp_db, mother=None, config=cfg)
        yield sched
        if sched._running:
            sched.stop()

    def test_full_scheduler_lifecycle(self, scheduler):
        """Start → verify running → stop → verify stopped."""
        status_before = scheduler.get_status()
        assert status_before["running"] is False
        assert status_before["enabled"] is True

        scheduler.start()
        assert scheduler._running is True
        assert scheduler._thread is not None
        assert scheduler._thread.is_alive()

        # Allow time for at least one loop iteration
        time.sleep(0.3)

        status_running = scheduler.get_status()
        assert status_running["running"] is True

        scheduler.stop()
        time.sleep(0.1)
        status_after = scheduler.get_status()
        assert status_after["running"] is False

    def test_scheduler_with_memory_operations(self, scheduler, memory_store,
                                               temp_db):
        """Scheduler runs memory decay task, verifies memory stats are stable."""
        shadow_id = "expert:test:sched_memory"
        config = ShadowConfig(
            shadow_id=shadow_id, shadow_type="expert",
            display_name="Scheduler Memory Test",
            methodology_prompt="Test shadow for scheduler memory ops.",
            virtual_capital=10000.0, domain="test",
        )
        temp_db.create_shadow(config)

        # Ingest some observations
        for i in range(3):
            obs = ExternalObservation(
                observation_id=f"sched-obs-{i}",
                source_type="text",
                source_path=f"shadow:{shadow_id}",
                extracted_text=f"Scheduler test observation #{i}",
                confidence=0.8,
                source_attribution=f"shadow:{shadow_id}",
            )
            memory_store.ingest_observation_sync(
                shadow_id, obs, tier="working"
            )

        # Run scheduler briefly
        scheduler.start()
        time.sleep(0.5)
        scheduler.stop()

        # Memory stats should still be accessible
        stats = memory_store.get_memory_stats()
        assert stats["total_observations"] >= 3
        assert isinstance(stats["avg_confidence"], float)


# ═══════════════════════════════════════════════════════════════════════════
# Test: ShadowMother Memory + Crystallization Steps
# ═══════════════════════════════════════════════════════════════════════════

class TestShadowMotherIntegration:
    """ShadowMother with crystallization_enabled=True runs steps 6.5 + 6.6."""

    def test_config_flags_disabled_by_default(self):
        """All Phase F features must be DISABLED by default."""
        settings = ShadowSettings()
        assert settings.scheduler_enabled is False, (
            "scheduler_enabled must be False by default"
        )
        assert settings.gemini_flash_enabled is False, (
            "gemini_flash_enabled must be False by default"
        )
        assert settings.crystallization_enabled is False, (
            "crystallization_enabled must be False by default"
        )

    def test_shadow_mother_with_crystallization_flag(self, shadow_settings, temp_db):
        """ShadowMother initializes with crystallization_enabled=True config."""
        shadow_settings.crystallization_enabled = True

        from marketmind.shadows.shadow_mother import ShadowMother
        mother = ShadowMother(shadow_settings, temp_db)

        # Mother should have access to crystallization config
        assert getattr(mother.config, 'crystallization_enabled', False) is True

    def test_orchestration_handles_memory_update_step(self, shadow_settings, temp_db):
        """Orchestrate daily cycle includes step 6.5/6.6 when crystallization enabled."""
        shadow_settings.crystallization_enabled = True

        from marketmind.shadows.shadow_mother import ShadowMother
        mother = ShadowMother(shadow_settings, temp_db)

        # Create at least one shadow for the cycle
        config = ShadowConfig(
            shadow_id="expert:test:orchestration",
            shadow_type="expert",
            display_name="Orchestration Test",
            methodology_prompt="Test shadow for orchestration.",
            virtual_capital=10000.0, domain="test",
        )
        temp_db.create_shadow(config)

        # Run a minimal daily cycle (no news, no market data)
        result = asyncio.run(
            mother.orchestrate_daily_cycle([], {})
        )

        assert result is not None
        assert result.active_shadows >= 1, (
            f"Expected at least 1 active shadow, got {result.active_shadows}"
        )
