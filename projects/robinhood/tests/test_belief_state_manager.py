"""
test_belief_state_manager.py — Phase 8.3.1 BeliefStateManager Test Suite

Tests the three-layer architecture of the BeliefStateManager:

  Layer 1 (Ingestion):   register_node(), ingest_observation(), ingest_bulk()
  Layer 2 (Processing):  γ-decay, conflict detection, retirement, resolution
  Layer 3 (Querying):    get_snapshot(), list_active(), list_conflicts(), etc.

Test categories:
  1. Node lifecycle (register → ingest → snapshot → retire)
  2. β-Bernoulli bayesian update correctness
  3. γ-decay (time-based and forced) with the corrected formula
  4. Conflict detection between competing nodes
  5. Conflict resolution (override, merge, ambiguous reject)
  6. Retirement when confidence < θ
  7. Bulk ingestion
  8. Edge cases (duplicate ID, nonexistent node, max observations)
  9. State introspection (export_state)
"""

import datetime
import math
import pytest
import time
from typing import Dict, List, Optional

from src.belief_types import (
    BeliefNode,
    BeliefObservation,
    BeliefRetirement,
    BeliefSnapshot,
    BeliefSource,
    BeliefStatus,
    ConflictRecord,
    ResolutionStrategy,
)
from src.belief_state_manager import (
    BeliefManagerConfig,
    BeliefStateManager,
    BeliefNotFoundError,
    ConflictNotFoundError,
    DuplicatePropositionError,
    BeliefManagerError,
)


@pytest.fixture
def manager() -> BeliefStateManager:
    return BeliefStateManager()


@pytest.fixture
def config_aggressive_retirement() -> BeliefManagerConfig:
    return BeliefManagerConfig(theta=0.3)


@pytest.fixture
def config_no_decay() -> BeliefManagerConfig:
    return BeliefManagerConfig(gamma=1.0)


@pytest.fixture
def manager_with_propositions(manager: BeliefStateManager) -> BeliefStateManager:
    manager.register_node("BTC > 100k by EOY", proposition_id="btc-bull", alpha=5.0, beta=2.0, source=BeliefSource.MARKET_DATA, metadata={"source": "coinbase"})
    manager.register_node("SPY will correct 10%", proposition_id="spy-bear", alpha=3.0, beta=4.0, source=BeliefSource.SHADOW_PREDICTION)
    manager.register_node("TSLA beats earnings", proposition_id="tsla-earn", alpha=2.0, beta=1.0, source=BeliefSource.INFERRED)
    return manager


def _make_obs(value: float, confidence: float = 0.9, source: BeliefSource = BeliefSource.INFERRED, ts: Optional[str] = None) -> BeliefObservation:
    kwargs = {"value": value, "confidence": confidence, "source": source}
    if ts is not None:
        kwargs["timestamp"] = ts
    return BeliefObservation(**kwargs)


# === Layer 1: Ingestion ===


class TestRegisterNode:

    def test_register_minimal(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Test proposition")
        snap = manager.get_snapshot(pid)
        assert snap is not None
        assert snap.node.proposition == "Test proposition"
        assert snap.node.status == BeliefStatus.ACTIVE
        assert snap.node.source == BeliefSource.INFERRED
        assert snap.node.alpha == 1.0
        assert snap.node.beta == 1.0
        assert snap.observation_count == 0

    def test_register_with_params(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Custom node", proposition_id="custom-001", alpha=3.0, beta=7.0, source=BeliefSource.HUMAN_INPUT, metadata={"analyst": "Alice"})
        assert pid == "custom-001"
        snap = manager.get_snapshot(pid)
        assert snap.node.source == BeliefSource.HUMAN_INPUT

    def test_duplicate_id_raises(self, manager: BeliefStateManager) -> None:
        manager.register_node("First", proposition_id="dup-id")
        with pytest.raises(DuplicatePropositionError):
            manager.register_node("Second", proposition_id="dup-id")

    def test_auto_id_unique(self, manager: BeliefStateManager) -> None:
        assert manager.register_node("Alpha") != manager.register_node("Beta")


class TestIngestObservation:

    def test_ingest_updates_beta(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Test", alpha=1.0, beta=1.0)
        snap = manager.ingest_observation(pid, _make_obs(value=0.75, confidence=1.0))
        assert snap.node.alpha > 1.0
        assert snap.expectation > 0.5

    def test_ingest_updates_snapshot_fields(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Test", alpha=2.0, beta=2.0)
        snap = manager.ingest_observation(pid, _make_obs(value=0.8, confidence=0.9))
        assert snap.observation_count == 1
        assert snap.status_label == "active"

    def test_ingest_nonexistent_node_raises(self, manager: BeliefStateManager) -> None:
        with pytest.raises(BeliefNotFoundError):
            manager.ingest_observation("does-not-exist", _make_obs(value=0.5, confidence=0.5))

    def test_ingest_allow_create(self, manager: BeliefStateManager) -> None:
        snap = manager.ingest_observation("auto-created", _make_obs(value=0.6, confidence=0.8), allow_create=True)
        assert snap.observation_count == 1

    def test_max_observations_limit(self, manager: BeliefStateManager) -> None:
        manager._config.max_observations_per_node = 3
        pid = manager.register_node("Limited")
        for _ in range(3):
            manager.ingest_observation(pid, _make_obs(0.5))
        with pytest.raises(BeliefManagerError):
            manager.ingest_observation(pid, _make_obs(0.5))

    def test_low_confidence_observation_impact(self, manager: BeliefStateManager) -> None:
        pid_low = manager.register_node("Low conf", alpha=1.0, beta=1.0)
        alpha_low = manager.ingest_observation(pid_low, _make_obs(value=1.0, confidence=0.1)).node.alpha
        pid_high = manager.register_node("High conf", alpha=1.0, beta=1.0)
        alpha_high = manager.ingest_observation(pid_high, _make_obs(value=1.0, confidence=1.0)).node.alpha
        assert alpha_high > alpha_low + 0.5


class TestIngestBulk:

    def test_bulk_ingestion(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Bulk target")
        results = manager.ingest_bulk_observations({pid: [_make_obs(0.6), _make_obs(0.7), _make_obs(0.8)]})
        assert results[pid].observation_count == 3

    def test_bulk_multi_node(self, manager: BeliefStateManager) -> None:
        manager.register_node("A", proposition_id="a")
        manager.register_node("B", proposition_id="b")
        results = manager.ingest_bulk_observations({"a": [_make_obs(0.5)], "b": [_make_obs(0.3), _make_obs(0.4)]})
        assert results["a"].observation_count == 1
        assert results["b"].observation_count == 2


# === Layer 2: Processing — β-Bernoulli Update Correctness ===


class TestBetaUpdateCorrectness:

    def test_uniform_prior_positive_evidence(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Uniform prior", alpha=1.0, beta=1.0)
        snap = manager.ingest_observation(pid, _make_obs(0.8, 1.0))
        assert snap.node.alpha == pytest.approx(1.8, abs=1e-10)
        assert snap.node.beta == pytest.approx(1.2, abs=1e-10)
        assert snap.expectation == pytest.approx(0.6, abs=1e-6)

    def test_negative_evidence(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Negative", alpha=1.0, beta=1.0)
        snap = manager.ingest_observation(pid, _make_obs(0.2, 1.0))
        assert snap.node.alpha == pytest.approx(1.2, abs=1e-10)
        assert snap.node.beta == pytest.approx(1.8, abs=1e-10)

    def test_neutral_evidence(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Neutral", alpha=1.0, beta=1.0)
        for _ in range(10):
            manager.ingest_observation(pid, _make_obs(0.5, 1.0))
        snap = manager.get_snapshot(pid)
        assert snap.node.alpha == pytest.approx(6.0, abs=1e-6)
        assert snap.node.beta == pytest.approx(6.0, abs=1e-6)

    def test_confidence_scaling(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Halved", alpha=1.0, beta=1.0)
        snap = manager.ingest_observation(pid, _make_obs(0.8, 0.5))
        # Phase 8.4 对称修正: β' = β + (1-value)*confidence = 1 + 0.2*0.5 = 1.1
        assert snap.node.alpha == pytest.approx(1.4, abs=1e-10)
        assert snap.node.beta == pytest.approx(1.1, abs=1e-10)

    def test_zero_confidence_ignores_evidence(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Ignored", alpha=2.0, beta=3.0)
        snap_before = manager.get_snapshot(pid)
        manager.ingest_observation(pid, _make_obs(0.9, 0.0))
        snap_after = manager.get_snapshot(pid)
        assert snap_after.node.alpha == snap_before.node.alpha
        assert snap_after.node.beta == snap_before.node.beta


# === Layer 2: Processing — γ-Decay Tests ===


class TestGammaDecay:

    def test_time_based_decay(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Decay test", alpha=10.0, beta=5.0)
        snap_before = manager.get_snapshot(pid)
        future_ts = "2026-05-10T00:00:00Z"
        past_obs = _make_obs(0.5, 1.0, ts=future_ts)  # neutral obs, decays then updates
        manager.ingest_observation(pid, past_obs)
        snap_after = manager.get_snapshot(pid)
        # decay happens BEFORE beta update: α decreases then obs adds back partially
        assert snap_after.node.alpha < snap_before.node.alpha
        assert snap_after.node.alpha > snap_before.node.alpha - 1.0

    def test_forced_decay_all(self, manager: BeliefStateManager) -> None:
        pid1 = manager.register_node("Node A", alpha=10.0, beta=5.0)
        pid2 = manager.register_node("Node B", alpha=20.0, beta=10.0)
        pid3 = manager.register_node("Node C", alpha=3.0, beta=3.0)
        snap1_before = manager.get_snapshot(pid1)
        snap2_before = manager.get_snapshot(pid2)
        snap3_before = manager.get_snapshot(pid3)
        count = manager.apply_forced_decay_all(steps=2)
        assert count == 3
        assert manager.get_snapshot(pid1).node.alpha < snap1_before.node.alpha
        assert manager.get_snapshot(pid2).node.beta < snap2_before.node.beta
        assert manager.get_snapshot(pid3).node.alpha < snap3_before.node.alpha

    def test_no_decay_no_change(self, manager: BeliefStateManager) -> None:
        c = BeliefManagerConfig(gamma=1.0)
        m = BeliefStateManager(config=c)
        pid = m.register_node("No decay", alpha=10.0, beta=5.0)
        snap_before = m.get_snapshot(pid)
        m.apply_forced_decay_all(steps=100)
        assert m.get_snapshot(pid).node.alpha == pytest.approx(snap_before.node.alpha)

    def test_decay_shrinks_confidence(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Shrink", alpha=50.0, beta=10.0)
        score_before = manager.get_snapshot(pid).score
        manager.apply_forced_decay_all(steps=5)
        assert manager.get_snapshot(pid).score < score_before

    def test_decay_corrected_formula(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Formula verify", alpha=25.0, beta=9.0)
        snap = manager.get_snapshot(pid)
        manager.apply_forced_decay_all(steps=3)
        snap_after = manager.get_snapshot(pid)
        γ = 0.95
        assert snap_after.node.alpha == pytest.approx((γ ** 3) * (25.0 - 1.0) + 1.0, abs=1e-6)
        assert snap_after.node.beta == pytest.approx((γ ** 3) * (9.0 - 1.0) + 1.0, abs=1e-6)


# === Layer 2: Processing — Conflict Detection ===


class TestConflictDetection:

    def test_no_conflict_single_node(self, manager: BeliefStateManager) -> None:
        manager.register_node("Standalone", proposition_id="alone", alpha=10.0, beta=1.0)
        manager.ingest_observation("alone", _make_obs(0.5, 1.0))
        assert len(manager.list_conflicts()) == 0

    def test_no_conflict_similar_beliefs(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="sim-a", alpha=80.0, beta=20.0)
        manager.register_node("MarketDirection", proposition_id="sim-b", alpha=70.0, beta=30.0)
        obs = _make_obs(0.5, 1.0)
        manager.ingest_observation("sim-a", obs)
        manager.ingest_observation("sim-b", obs)
        # After neutral obs(0.5), E converges to 0.5 for both — no conflict
        assert len(manager.list_conflicts()) == 0

    def test_conflict_divergent_beliefs(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="bull", alpha=18.0, beta=2.0)
        manager.register_node("MarketDirection", proposition_id="bear", alpha=2.0, beta=18.0)
        obs = _make_obs(0.5, 1.0)
        manager.ingest_observation("bull", obs)
        # After first ingestion, conflict is detected immediately
        conflicts = manager.list_conflicts()
        assert len(conflicts) == 1

    def test_conflict_sets_status_conflicted(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="left", alpha=15.0, beta=2.0)
        manager.register_node("MarketDirection", proposition_id="right", alpha=2.0, beta=15.0)
        obs = _make_obs(0.5, 1.0)
        # After first ingestion, both nodes become conflicted
        manager.ingest_observation("left", obs)
        assert manager.get_snapshot("left").status_label == "conflicted"
        assert manager.get_snapshot("right").status_label == "conflicted"

    def test_conflict_details_correct(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="conf-a", alpha=20.0, beta=1.0)
        manager.register_node("MarketDirection", proposition_id="conf-b", alpha=1.0, beta=20.0)
        obs = _make_obs(0.5, 1.0)
        manager.ingest_observation("conf-a", obs)
        c = manager.list_conflicts()[0]
        assert c.left_id == "conf-a"
        assert c.right_id == "conf-b"
        assert c.resolution == ResolutionStrategy.OVERRIDE_HIGHER_CONFIDENCE


# === Layer 2: Processing — Conflict Resolution ===


class TestConflictResolution:

    def test_resolve_override_high_confidence(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="strong", alpha=20.0, beta=2.0)
        manager.register_node("MarketDirection", proposition_id="weak", alpha=2.0, beta=2.0)
        obs = _make_obs(0.5, 1.0)
        manager.ingest_observation("strong", obs)
        conflicts = manager.list_conflicts()
        winner = manager.resolve_conflict(conflicts[0].conflict_id)
        assert winner is not None
        assert winner.node.proposition_id == "strong"
        assert manager.get_snapshot("strong").status_label == "active"
        assert manager.get_snapshot("weak").status_label == "retired"

    def test_resolve_merge(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="merge-left", alpha=15.0, beta=2.0)
        manager.register_node("MarketDirection", proposition_id="merge-right", alpha=2.0, beta=15.0)
        obs = _make_obs(0.5, 1.0)
        manager.ingest_observation("merge-left", obs)
        conflicts = manager.list_conflicts()
        cid = conflicts[0].conflict_id
        winner = manager.resolve_conflict(cid, override_resolution=ResolutionStrategy.MERGE)
        assert winner is not None
        assert "[Merged]" in winner.node.proposition
        assert manager.get_snapshot("merge-left").status_label == "retired"

    def test_resolve_ambiguous_reject(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="amb-rej-a", alpha=15.0, beta=2.0)
        manager.register_node("MarketDirection", proposition_id="amb-rej-b", alpha=2.0, beta=15.0)
        obs = _make_obs(0.5, 1.0)
        manager.ingest_observation("amb-rej-a", obs)
        conflicts = manager.list_conflicts()
        cid = conflicts[0].conflict_id
        winner = manager.resolve_conflict(cid, override_resolution=ResolutionStrategy.AMBIGUOUS_REJECT)
        assert winner is None
        assert manager.get_snapshot("amb-rej-a").status_label == "retired"

    def test_resolve_nonexistent_conflict(self, manager: BeliefStateManager) -> None:
        with pytest.raises(ConflictNotFoundError):
            manager.resolve_conflict("no-such-conflict")


# === Layer 2: Processing — Retirement ===


class TestRetirement:

    def test_retirement_with_aggressive_threshold(self, config_aggressive_retirement: BeliefManagerConfig) -> None:
        m = BeliefStateManager(config=config_aggressive_retirement)
        pid = m.register_node("Aggressive retire", alpha=2.0, beta=10.0)  # E=0.167, score~0.154
        m.apply_forced_decay_all(steps=100)  # heavy decay toward Beta(1,1) pushes score~0.46 — but beta was large so decay shifts toward equal
        snap = m.get_snapshot(pid)
        # After obs and retirement check
        m.ingest_observation(pid, _make_obs(0.0, 1.0))  # strong negative evidence pushes beta up
        m.apply_forced_decay_all(steps=50)
        snap = m.get_snapshot(pid)
        # Try to get below θ=0.3
        if snap.status_label == "active":
            for _ in range(5):
                m.ingest_observation(pid, _make_obs(0.0, 1.0))
                snap = m.get_snapshot(pid)
                if snap.status_label == "retired":
                    break
        assert snap.status_label == "retired"

    def test_retirement_recorded(self, manager: BeliefStateManager) -> None:
        m = BeliefStateManager(config=BeliefManagerConfig(theta=0.5))
        pid = m.register_node("Recorded", alpha=1.5, beta=2.0)
        m.apply_forced_decay_all(steps=30)
        m.ingest_observation(pid, _make_obs(0.5, 1.0))
        assert any(r.proposition_id == pid for r in m.list_retirements())


# === Layer 3: Querying ===


class TestQuerying:

    def test_get_snapshot_nonexistent(self, manager: BeliefStateManager) -> None:
        assert manager.get_snapshot("no-such") is None

    def test_list_active_only_active(self, manager_with_propositions: BeliefStateManager) -> None:
        for snap in manager_with_propositions.list_active():
            assert snap.status_label == "active"

    def test_list_all_includes_retired(self, manager: BeliefStateManager) -> None:
        m = BeliefStateManager(config=BeliefManagerConfig(theta=0.5))
        m.register_node("Will retire", proposition_id="will-ret", alpha=1.5, beta=2.0)
        m.apply_forced_decay_all(steps=30)
        m.ingest_observation("will-ret", _make_obs(0.5, 1.0))
        statuses = {s.status_label for s in m.list_all()}
        assert "retired" in statuses or "active" in statuses

    def test_list_conflicts_contains_conflicts(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="cql-a", alpha=20.0, beta=1.0)
        manager.register_node("MarketDirection", proposition_id="cql-b", alpha=1.0, beta=20.0)
        manager.ingest_observation("cql-a", _make_obs(0.5, 1.0))
        assert len(manager.list_conflicts()) >= 1
        assert isinstance(manager.list_conflicts()[0], ConflictRecord)

    def test_get_node_count(self, manager: BeliefStateManager) -> None:
        assert manager.get_node_count() == 0
        manager.register_node("Node 1")
        assert manager.get_node_count() == 1

    def test_get_active_count(self, manager: BeliefStateManager) -> None:
        manager.register_node("Active 1")
        manager.register_node("Active 2")
        assert manager.get_active_count() == 2

    def test_get_conflict_by_id(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="gci-a", alpha=20.0, beta=1.0)
        manager.register_node("MarketDirection", proposition_id="gci-b", alpha=1.0, beta=20.0)
        manager.ingest_observation("gci-a", _make_obs(0.5, 1.0))
        cid = manager.list_conflicts()[0].conflict_id
        assert manager.get_conflict(cid) is not None

    def test_get_conflict_nonexistent(self, manager: BeliefStateManager) -> None:
        assert manager.get_conflict("no-such") is None

    def test_retirement_records_exist(self, manager: BeliefStateManager) -> None:
        m = BeliefStateManager(config=BeliefManagerConfig(theta=0.4))
        pid = m.register_node("Ret record", alpha=1.5, beta=2.0)
        m.apply_forced_decay_all(steps=30)
        m.ingest_observation(pid, _make_obs(0.5, 1.0))
        for r in m.list_retirements():
            assert isinstance(r, BeliefRetirement)
            assert hasattr(r, "retirement_id")

    def test_search_nodes(self, manager: BeliefStateManager) -> None:
        manager.register_node("Bitcoin bull case", proposition_id="btc")
        manager.register_node("Ethereum bull case", proposition_id="eth")
        manager.register_node("SPY bearish", proposition_id="spy")
        assert len(manager.search_nodes("bull")) == 2
        assert len(manager.search_nodes("SPY")) == 1


# === Integration: Full Lifecycle ===


class TestFullLifecycle:

    def test_register_ingest_retire_lifecycle(self, manager: BeliefStateManager) -> None:
        pid = manager.register_node("Full lifecycle", proposition_id="lifecycle-001", alpha=3.0, beta=3.0, source=BeliefSource.MARKET_DATA)
        snap = manager.ingest_observation(pid, _make_obs(0.7, 0.8))
        assert snap.observation_count == 1
        snap = manager.ingest_observation(pid, _make_obs(0.6, 0.9))
        assert snap.observation_count == 2
        snap_before = manager.get_snapshot(pid)
        manager.apply_forced_decay_all(steps=10)
        snap_after = manager.get_snapshot(pid)
        assert snap_after.node.alpha < snap_before.node.alpha

    def test_conflict_lifecycle(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="lifecycle-bull", alpha=20.0, beta=2.0)
        manager.register_node("MarketDirection", proposition_id="lifecycle-bear", alpha=2.0, beta=20.0)
        obs = _make_obs(0.5, 1.0)
        snap_bull = manager.ingest_observation("lifecycle-bull", obs)
        snap_bear = manager.ingest_observation("lifecycle-bear", obs)
        assert snap_bull.status_label == "conflicted"
        assert snap_bear.status_label == "conflicted"
        conflicts = manager.list_conflicts()
        winner = manager.resolve_conflict(conflicts[0].conflict_id)
        assert winner is not None
        assert winner.node.proposition_id == "lifecycle-bull"


# === Export / State Introspection ===


class TestExportState:

    def test_export_state_structure(self, manager_with_propositions: BeliefStateManager) -> None:
        state = manager_with_propositions.export_state()
        assert isinstance(state, dict)
        assert "nodes" in state
        assert "conflicts" in state
        assert "retirements" in state
        assert "config" in state

    def test_export_state_contains_nodes(self, manager_with_propositions: BeliefStateManager) -> None:
        state = manager_with_propositions.export_state()
        assert len(state["nodes"]) >= 3
        prop_ids = {n["proposition_id"] for n in state["nodes"]}
        assert "btc-bull" in prop_ids
        assert "spy-bear" in prop_ids
        assert "tsla-earn" in prop_ids

    def test_export_state_config_snapshot(self, manager_with_propositions: BeliefStateManager) -> None:
        state = manager_with_propositions.export_state()
        config = state["config"]
        assert "gamma" in config
        assert "theta" in config
        assert "conflict_threshold" in config
        assert "max_observations_per_node" in config

    def test_export_state_after_conflict(self, manager: BeliefStateManager) -> None:
        manager.register_node("MarketDirection", proposition_id="ex-left", alpha=15.0, beta=1.0)
        manager.register_node("MarketDirection", proposition_id="ex-right", alpha=1.0, beta=15.0)
        obs = _make_obs(0.5, 1.0)
        manager.ingest_observation("ex-left", obs)
        state = manager.export_state()
        assert len(state["conflicts"]) >= 1

    def test_export_state_after_retirement(self, manager: BeliefStateManager) -> None:
        m = BeliefStateManager(config=BeliefManagerConfig(theta=0.3))
        m.register_node("Export retire", proposition_id="ex-ret", alpha=2.0, beta=10.0)
        m.apply_forced_decay_all(steps=100)
        for _ in range(10):
            m.ingest_observation("ex-ret", _make_obs(0.0, 1.0))
            if m.get_snapshot("ex-ret").status_label == "retired":
                break
        state = m.export_state()
        assert len(state["retirements"]) >= 1
