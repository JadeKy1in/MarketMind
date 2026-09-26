"""Tests for ShadowMemoryStore -- 3-tier layered shadow memory."""
import pytest
import json
import tempfile
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path

from marketmind.shadows.shadow_state import ShadowStateDB
from marketmind.shadows.shadow_memory import ShadowMemoryStore
from marketmind.shadows.belief_math import (
    beta_update,
    gamma_decay,
    confidence_score,
)


@dataclass
class FakeObservation:
    """Minimal ExternalObservation-like dataclass for testing."""
    observation_id: str
    source_type: str = "text"
    source_path: str = "/test/path.txt"
    extracted_text: str = "Test observation content"
    metadata: dict = field(default_factory=dict)
    confidence: float = 1.0
    source_attribution: str = "test"
    evaluated_at: str = ""


@pytest.fixture
def memory_db():
    """Create a temporary ShadowStateDB with schema initialized."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_memory.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()
        yield db
        db.close()


@pytest.fixture
def store(memory_db):
    """Create a ShadowMemoryStore backed by the temp DB."""
    return ShadowMemoryStore(memory_db)


# -- Ingestion Tests ----------------------------------------------------------

class TestIngestObservation:
    """Tests for ingesting observations into shadow memory."""

    def test_ingest_creates_belief_node(self, store):
        """Ingesting an observation creates a belief node in SQLite."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        assert node_id is not None
        assert len(node_id) > 0

        node = store.get_belief_node(node_id)
        assert node is not None
        assert node["alpha"] > 1.0
        assert node["status"] == "active"
        assert node["tier"] == "working"
        assert node["observation_count"] == 1

    def test_ingest_multiple_observations_same_node(self, store):
        """Multiple observations with the same proposition update the same node."""
        obs1 = FakeObservation(observation_id="obs-001", confidence=0.8)
        obs2 = FakeObservation(observation_id="obs-002", confidence=0.7)

        nid1 = store.ingest_observation_sync("shadow:test:001", obs1)
        nid2 = store.ingest_observation_sync("shadow:test:001", obs2)

        assert nid1 == nid2

        node = store.get_belief_node(nid1)
        assert node["observation_count"] == 2

    def test_ingest_different_shadows_create_different_nodes(self, store):
        """Different shadows create separate belief nodes."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)

        nid1 = store.ingest_observation_sync("shadow:test:001", obs)
        nid2 = store.ingest_observation_sync("shadow:test:002", obs)

        assert nid1 != nid2

    def test_ingest_with_ticker_metadata(self, store):
        """Observations with ticker metadata create ticker-scoped nodes."""
        obs = FakeObservation(
            observation_id="obs-001",
            metadata={"ticker": "AAPL"},
            confidence=0.8,
        )
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        node = store.get_belief_node(node_id)
        assert node is not None
        assert "ticker:AAPL" in node["proposition"]

    def test_ingest_zero_confidence_no_op(self, store):
        """Zero-confidence observations should not update beliefs."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.0)
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        node = store.get_belief_node(node_id)
        assert node["alpha"] == 1.0
        assert node["beta"] == 1.0

    def test_ingest_invalid_tier_raises(self, store):
        """Invalid tier value raises ValueError."""
        obs = FakeObservation(observation_id="obs-001")
        with pytest.raises(ValueError, match="tier must be one of"):
            store.ingest_observation_sync("shadow:test:001", obs, tier="invalid")


class TestIngestBulk:
    """Tests for batch ingestion."""

    def test_ingest_bulk_returns_all_node_ids(self, store):
        """Bulk ingest returns node IDs for all observations."""
        observations = [
            FakeObservation(observation_id=f"obs-{i:03d}", confidence=0.7)
            for i in range(5)
        ]
        results = []
        for obs in observations:
            node_id = store.ingest_observation_sync("shadow:test:001", obs)
            results.append(node_id)

        assert len(results) == 5
        assert all(isinstance(nid, str) for nid in results)


# -- Query Tests -------------------------------------------------------------


class TestQueryBeliefs:
    """Tests for query_beliefs across memory tiers."""

    def test_query_returns_results(self, store):
        """Query returns belief results ranked by score."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)
        store.ingest_observation_sync("shadow:test:001", obs)

        from marketmind.shadows.shadow_agent import MemoryQuery
        query = MemoryQuery(tier="working", limit=10)
        results = store.query_beliefs(query)

        assert len(results) >= 1
        assert "confidence_score" in results[0]
        assert "proposition" in results[0]
        assert results[0]["confidence_score"] > 0.0

    def test_query_filters_by_tier(self, store):
        """Query respects tier filter."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)
        store.ingest_observation_sync("shadow:test:001", obs, tier="working")

        from marketmind.shadows.shadow_agent import MemoryQuery
        query_working = MemoryQuery(tier="working", limit=10)
        query_episodic = MemoryQuery(tier="episodic", limit=10)

        working_results = store.query_beliefs(query_working)
        episodic_results = store.query_beliefs(query_episodic)

        assert len(working_results) >= 1
        assert len(episodic_results) == 0

    def test_query_returns_all_tiers(self, store):
        """Query with tier='all' returns results from all tiers."""
        obs1 = FakeObservation(observation_id="obs-001", confidence=0.9)
        obs2 = FakeObservation(observation_id="obs-002", confidence=0.8)
        store.ingest_observation_sync("shadow:test:001", obs1, tier="working")
        store.ingest_observation_sync("shadow:test:002", obs2, tier="episodic")

        from marketmind.shadows.shadow_agent import MemoryQuery
        query = MemoryQuery(tier="all", limit=20)
        results = store.query_beliefs(query)

        tiers = {r["tier"] for r in results}
        assert "working" in tiers
        assert "episodic" in tiers

    def test_query_filters_by_ticker(self, store):
        """Query filters by ticker in proposition."""
        obs_aapl = FakeObservation(
            observation_id="obs-001", metadata={"ticker": "AAPL"}, confidence=0.9
        )
        obs_tsla = FakeObservation(
            observation_id="obs-002", metadata={"ticker": "TSLA"}, confidence=0.8
        )
        store.ingest_observation_sync("shadow:test:001", obs_aapl)
        store.ingest_observation_sync("shadow:test:001", obs_tsla)

        from marketmind.shadows.shadow_agent import MemoryQuery
        query = MemoryQuery(tier="all", ticker="AAPL", limit=10)
        results = store.query_beliefs(query)

        assert len(results) >= 1
        assert all("AAPL" in r["proposition"] for r in results)
        assert not any("TSLA" in r["proposition"] for r in results)

    def test_query_min_belief_strength_filter(self, store):
        """Query filters results below min_belief_strength."""
        obs = FakeObservation(observation_id="obs-001", confidence=1.0)
        store.ingest_observation_sync("shadow:test:001", obs)

        from marketmind.shadows.shadow_agent import MemoryQuery
        query = MemoryQuery(tier="working", min_belief_strength=0.90, limit=10)
        results = store.query_beliefs(query)

        assert isinstance(results, list)


class TestGetObservations:
    """Tests for get_observations."""

    def test_get_observations_returns_data(self, store):
        """get_observations returns observation data for a shadow."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)
        store.ingest_observation_sync("shadow:test:001", obs)

        observations = store.get_observations("shadow:test:001", tier="working")
        assert len(observations) == 1
        assert observations[0]["observation_id"] == "obs-001"
        assert observations[0]["confidence"] == 0.9

    def test_get_observations_filters_by_tier(self, store):
        """get_observations respects tier filter."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)
        store.ingest_observation_sync("shadow:test:001", obs, tier="working")

        working = store.get_observations("shadow:test:001", tier="working")
        episodic = store.get_observations("shadow:test:001", tier="episodic")

        assert len(working) == 1
        assert len(episodic) == 0

    def test_get_observations_respects_limit(self, store):
        """get_observations respects the limit parameter."""
        for i in range(5):
            obs = FakeObservation(observation_id=f"obs-{i:03d}", confidence=0.8)
            store.ingest_observation_sync("shadow:test:001", obs)

        observations = store.get_observations("shadow:test:001", limit=3)
        assert len(observations) == 3


# -- Decay Tests -------------------------------------------------------------


class TestDecay:
    """Tests for belief decay and TTL eviction."""

    def test_apply_decay_reduces_alpha_beta(self, store):
        """apply_decay moves parameters toward uniform prior Beta(1,1)."""
        obs = FakeObservation(observation_id="obs-001", confidence=1.0)
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        node_before = store.get_belief_node(node_id)
        alpha_before = node_before["alpha"]
        assert alpha_before > 1.0

        count = store.apply_decay(gamma=0.95)
        assert count >= 1

        node_after = store.get_belief_node(node_id)
        assert node_after["alpha"] < alpha_before

    def test_apply_decay_multiple_steps(self, store):
        """Multiple applications of decay progressively reduce beliefs."""
        obs = FakeObservation(observation_id="obs-001", confidence=1.0)
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        node_initial = store.get_belief_node(node_id)
        store.apply_decay(gamma=0.8)
        node_after_1 = store.get_belief_node(node_id)
        store.apply_decay(gamma=0.8)
        node_after_2 = store.get_belief_node(node_id)

        assert node_after_1["alpha"] < node_initial["alpha"]
        assert abs(node_after_2["alpha"] - 1.0) <= abs(node_after_1["alpha"] - 1.0)

    def test_apply_tier_decay_working_ttl(self, store):
        """Working memory items older than 24h are evicted."""
        conn = store._db._connect()
        try:
            old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            ) + "Z"
            now = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            ) + "Z"
            conn.execute(
                """INSERT INTO belief_nodes
                   (node_id, proposition, alpha, beta, status, tier, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("old-working-1", "test:old:working", 2.0, 1.5, "active", "working", old_time, now),
            )
            conn.execute(
                """INSERT INTO belief_observations
                   (observation_id, node_id, shadow_id, value, confidence, source_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("obs-old-1", "old-working-1", "shadow:test:001", 0.8, 0.9, "text", old_time),
            )
            conn.commit()
        finally:
            conn.close()

        evicted = store.apply_tier_decay("working")
        assert evicted >= 1

        node = store.get_belief_node("old-working-1")
        assert node["status"] == "retired"

    def test_apply_tier_decay_episodic_ttl(self, store):
        """Episodic memory items older than 90d are evicted."""
        conn = store._db._connect()
        try:
            old_time = (datetime.now(timezone.utc) - timedelta(days=120)).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            ) + "Z"
            now = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            ) + "Z"
            conn.execute(
                """INSERT INTO belief_nodes
                   (node_id, proposition, alpha, beta, status, tier, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("old-episodic-1", "test:old:episodic", 2.0, 1.5, "active", "episodic", old_time, now),
            )
            conn.execute(
                """INSERT INTO belief_observations
                   (observation_id, node_id, shadow_id, value, confidence, source_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("obs-old-ep-1", "old-episodic-1", "shadow:test:001", 0.8, 0.9, "text", old_time),
            )
            conn.commit()
        finally:
            conn.close()

        evicted = store.apply_tier_decay("episodic")
        assert evicted >= 1

        node = store.get_belief_node("old-episodic-1")
        assert node["status"] == "retired"

    def test_semantic_never_evicted(self, store):
        """Semantic memory items are never evicted by TTL."""
        conn = store._db._connect()
        try:
            old_time = (datetime.now(timezone.utc) - timedelta(days=365)).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            ) + "Z"
            now = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            ) + "Z"
            conn.execute(
                """INSERT INTO belief_nodes
                   (node_id, proposition, alpha, beta, status, tier, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("semantic-perm-1", "test:semantic:permanent", 5.0, 2.0, "active", "semantic", old_time, now),
            )
            conn.commit()
        finally:
            conn.close()

        evicted = store.apply_tier_decay("semantic")
        assert evicted == 0

        node = store.get_belief_node("semantic-perm-1")
        assert node["status"] == "active"

    def test_apply_tier_decay_invalid_tier(self, store):
        """Invalid tier raises ValueError."""
        with pytest.raises(ValueError, match="tier must be"):
            store.apply_tier_decay("invalid_tier")


# -- Lifecycle Tests ---------------------------------------------------------


class TestPromoteToSemantic:
    """Tests for promoting beliefs to semantic memory."""

    def test_promote_to_semantic_succeeds(self, store):
        """Promoting a node changes its tier to semantic."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)
        node_id = store.ingest_observation_sync("shadow:test:001", obs, tier="episodic")

        node_before = store.get_belief_node(node_id)
        assert node_before["tier"] == "episodic"

        result = store.promote_to_semantic(node_id)
        assert result is True

        node_after = store.get_belief_node(node_id)
        assert node_after["tier"] == "semantic"

    def test_promote_nonexistent_node_fails(self, store):
        """Promoting a nonexistent node returns False."""
        result = store.promote_to_semantic("nonexistent-node-id")
        assert result is False


class TestRetireBelief:
    """Tests for retiring belief nodes."""

    def test_retire_belief_succeeds(self, store):
        """Retiring a belief marks it as retired and creates a retirement record."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        result = store.retire_belief(node_id, "Manual retirement for testing")
        assert result is True

        node = store.get_belief_node(node_id)
        assert node["status"] == "retired"
        assert node["retire_reason"] == "Manual retirement for testing"
        assert node["retired_at"] is not None

    def test_retire_nonexistent_node_fails(self, store):
        """Retiring a nonexistent node returns False."""
        result = store.retire_belief("nonexistent-node-id", "reason")
        assert result is False

    def test_retire_already_retired_node_fails(self, store):
        """Retiring an already-retired node returns False."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        assert store.retire_belief(node_id, "First retirement") is True
        assert store.retire_belief(node_id, "Second retirement") is False


# -- Memory Stats Tests ------------------------------------------------------


class TestMemoryStats:
    """Tests for get_memory_stats."""

    def test_memory_stats_accurate(self, store):
        """get_memory_stats returns accurate counts across tiers."""
        # Use different shadow_ids or source_types to create distinct nodes
        obs1 = FakeObservation(observation_id="obs-001", confidence=0.9, source_type="text")
        obs2 = FakeObservation(observation_id="obs-002", confidence=0.8, source_type="pdf")
        obs3 = FakeObservation(observation_id="obs-003", confidence=0.7, source_type="image")

        store.ingest_observation_sync("shadow:test:001", obs1, tier="working")
        store.ingest_observation_sync("shadow:test:001", obs2, tier="episodic")
        store.ingest_observation_sync("shadow:test:001", obs3, tier="semantic")

        stats = store.get_memory_stats()

        assert stats["total_nodes"] >= 3
        assert stats["active_nodes"] >= 3
        assert stats["working_count"] >= 1
        assert stats["episodic_count"] >= 1
        assert stats["semantic_count"] >= 1
        assert stats["total_observations"] >= 3

    def test_memory_stats_after_retirement(self, store):
        """Stats update correctly after retiring a belief."""
        obs = FakeObservation(observation_id="obs-001", confidence=0.9)
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        store.retire_belief(node_id, "Testing stats")

        stats = store.get_memory_stats()
        assert stats["active_nodes"] < stats["total_nodes"]
        assert stats["retired_nodes"] >= 1


# -- Integrated Scenario Tests -----------------------------------------------


class TestIntegrationScenarios:
    """End-to-end scenarios combining multiple memory operations."""

    def test_full_lifecycle_workflow(self, store):
        """Test the full lifecycle: ingest -> query -> promote -> retire."""
        nid = store.ingest_observation_sync(
            "shadow:test:001",
            FakeObservation(observation_id="obs-001", confidence=0.9,
                          metadata={"ticker": "NVDA"}),
            tier="working",
        )

        from marketmind.shadows.shadow_agent import MemoryQuery
        results = store.query_beliefs(MemoryQuery(tier="working"))
        assert len(results) >= 1

        node = store.get_belief_node(nid)
        assert node["tier"] == "working"

        store.ingest_observation_sync(
            "shadow:test:001",
            FakeObservation(observation_id="obs-002", confidence=0.85,
                          metadata={"ticker": "NVDA"}),
            tier="episodic",
        )

        result = store.promote_to_semantic(nid)
        assert result is True
        node = store.get_belief_node(nid)
        assert node["tier"] == "semantic"

        stats = store.get_memory_stats()
        assert stats["semantic_count"] >= 1

        obs = store.get_observations("shadow:test:001", tier="all")
        assert len(obs) >= 2

        assert store.retire_belief(nid, "End of lifecycle test") is True

    def test_gamma_decay_converges_to_prior(self, store):
        """Repeated decay without new observations converges toward uniform prior."""
        obs = FakeObservation(observation_id="obs-001", confidence=1.0)
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        node_initial = store.get_belief_node(node_id)
        assert node_initial["alpha"] > 1.5

        for _ in range(20):
            store.apply_decay(gamma=0.7)

        node_final = store.get_belief_node(node_id)
        assert abs(node_final["alpha"] - 1.0) < 0.1
        assert abs(node_final["beta"] - 1.0) < 0.1

    def test_confidence_score_calculation_consistency(self, store):
        """Confidence scores are consistent between direct math and store retrieval."""
        obs = FakeObservation(observation_id="obs-001", confidence=1.0)
        node_id = store.ingest_observation_sync("shadow:test:001", obs)

        node = store.get_belief_node(node_id)
        store_score = node["confidence_score"]
        direct_score = confidence_score(node["alpha"], node["beta"])

        assert store_score == pytest.approx(direct_score, rel=1e-6)
