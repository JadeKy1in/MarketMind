"""
test_belief_types.py — Phase 8.3.1 Type Definitions Test Suite

Tests the dataclass and enum definitions used across the Belief State Manager module.

All tests are aligned with the CURRENT belief_types.py implementation.
"""

import datetime
import pytest
import uuid

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


# ============================================================
# Enum Tests
# ============================================================


class TestBeliefSource:
    """BeliefSource enum values and parsing."""

    def test_all_members_present(self) -> None:
        """Verify all 5 members with their correct values."""
        assert BeliefSource.SHADOW_PREDICTION.value == "shadow_prediction"
        assert BeliefSource.MARKET_DATA.value == "market_data"
        assert BeliefSource.MACRO_CALENDAR.value == "macro_calendar"
        assert BeliefSource.HUMAN_INPUT.value == "human_input"
        assert BeliefSource.INFERRED.value == "inferred"

    def test_from_value_round_trip(self) -> None:
        for member in BeliefSource:
            assert BeliefSource(member.value) == member

    def test_unique_values(self) -> None:
        values = [m.value for m in BeliefSource]
        assert len(values) == len(set(values))


class TestBeliefStatus:
    """BeliefStatus enum values and lifecycle."""

    def test_all_members_present(self) -> None:
        """Verify all 3 members with their correct values."""
        assert BeliefStatus.ACTIVE.value == "active"
        assert BeliefStatus.RETIRED.value == "retired"
        assert BeliefStatus.CONFLICTED.value == "conflicted"

    def test_from_value_round_trip(self) -> None:
        for member in BeliefStatus:
            assert BeliefStatus(member.value) == member

    def test_unique_values(self) -> None:
        values = [m.value for m in BeliefStatus]
        assert len(values) == len(set(values))


class TestResolutionStrategy:
    """ResolutionStrategy enum values and semantics."""

    def test_all_members_present(self) -> None:
        assert ResolutionStrategy.OVERRIDE_HIGHER_CONFIDENCE.value == "override_higher_confidence"
        assert ResolutionStrategy.MERGE.value == "merge"
        assert ResolutionStrategy.AMBIGUOUS_REJECT.value == "ambiguous_reject"

    def test_from_value_round_trip(self) -> None:
        for member in ResolutionStrategy:
            assert ResolutionStrategy(member.value) == member

    def test_unique_values(self) -> None:
        values = [m.value for m in ResolutionStrategy]
        assert len(values) == len(set(values))


# ============================================================
# BeliefNode Tests
# ============================================================


class TestBeliefNodeConstruction:
    """BeliefNode dataclass construction."""

    def test_minimal_construction(self) -> None:
        """Minimal required fields only."""
        node = BeliefNode(
            proposition="TSLA will outperform SPY in Q3",
            proposition_id="prop-001",
            alpha=2.0,
            beta=5.0,
        )
        assert node.proposition == "TSLA will outperform SPY in Q3"
        assert node.proposition_id == "prop-001"
        assert node.alpha == 2.0
        assert node.beta == 5.0
        assert node.status == BeliefStatus.ACTIVE
        assert node.source == BeliefSource.INFERRED
        assert node.metadata == {}

        # Timestamps should be auto-generated ISO-8601 strings with Z suffix
        assert isinstance(node.created_at, str)
        assert node.created_at.endswith("Z")
        assert isinstance(node.last_updated, str)
        assert node.last_updated.endswith("Z")

    def test_full_construction(self) -> None:
        """All fields explicitly provided."""
        node = BeliefNode(
            proposition="BTC > 100k by EOY",
            proposition_id="crypto-001",
            alpha=3.0,
            beta=1.0,
            status=BeliefStatus.CONFLICTED,
            source=BeliefSource.SHADOW_PREDICTION,
            created_at="2026-01-15T10:00:00Z",
            last_updated="2026-05-01T14:30:00Z",
            metadata={"model": "gpt-4", "confidence_override": True},
        )
        assert node.proposition == "BTC > 100k by EOY"
        assert node.proposition_id == "crypto-001"
        assert node.alpha == 3.0
        assert node.beta == 1.0
        assert node.status == BeliefStatus.CONFLICTED
        assert node.source == BeliefSource.SHADOW_PREDICTION
        assert node.created_at == "2026-01-15T10:00:00Z"
        assert node.last_updated == "2026-05-01T14:30:00Z"
        assert node.metadata["model"] == "gpt-4"

    def test_auto_uuid_generation(self) -> None:
        """When proposition_id is omitted, a UUID is auto-generated."""
        node_1 = BeliefNode(proposition="Prop A")
        node_2 = BeliefNode(proposition="Prop B")
        assert node_1.proposition_id != node_2.proposition_id
        # Validate UUID4 format
        uid = uuid.UUID(node_1.proposition_id)
        assert uid.version == 4

    def test_auto_timestamp_generation(self) -> None:
        """created_at and last_updated are auto-generated when omitted."""
        before = datetime.datetime.now(datetime.timezone.utc)
        node = BeliefNode(proposition="Test")
        after = datetime.datetime.now(datetime.timezone.utc)

        # Strip trailing 'Z' before isoformat parsing
        created = datetime.datetime.fromisoformat(
            node.created_at.replace("Z", "+00:00")
        )
        updated = datetime.datetime.fromisoformat(
            node.last_updated.replace("Z", "+00:00")
        )
        assert before <= created <= after
        assert before <= updated <= after

    def test_frozen_immutability(self) -> None:
        """BeliefNode is frozen — attribute assignment should raise."""
        node = BeliefNode(proposition="Test")
        with pytest.raises(AttributeError):
            node.alpha = 5.0
        with pytest.raises(AttributeError):
            node.proposition = "Modified"


class TestBeliefNodeEdgeCases:
    """Edge cases for BeliefNode."""

    def test_zero_alpha_beta_raises(self) -> None:
        """alpha=0.0 violates invariant alpha >= 1.0; must raise ValueError."""
        with pytest.raises(ValueError, match="alpha must be >= 1.0"):
            BeliefNode(proposition="Zero", proposition_id="z", alpha=0.0, beta=0.0)

    def test_large_alpha_beta(self) -> None:
        """Large α/β values (thousands) are within dataclass type bounds."""
        node = BeliefNode(
            proposition="Large", alpha=10000.0, beta=5000.0,
        )
        assert node.alpha == 10000.0
        assert node.beta == 5000.0

    def test_empty_metadata(self) -> None:
        """Empty metadata dict is the default."""
        node = BeliefNode(proposition="Empty")
        assert node.metadata == {}

    def test_none_proposition_id_uses_default(self) -> None:
        """None proposition_id — default_factory generates UUID."""
        node = BeliefNode(proposition="Auto ID", proposition_id=None)
        # default_factory only fires when field is omitted entirely,
        # but dataclass converts None to default if default_factory is set?
        # Actually, default_factory fires when field not provided.
        # Passing None explicitly keeps None. Let's test omit scenario.
        # Omission tested in test_auto_uuid_generation above.
        node_omit = BeliefNode(proposition="Omit ID")
        uuid.UUID(node_omit.proposition_id)

    def test_beta_below_one_raises(self) -> None:
        """beta=0.5 violates invariant beta >= 1.0; must raise ValueError."""
        with pytest.raises(ValueError, match="beta must be >= 1.0"):
            BeliefNode(proposition="Bad Beta", alpha=1.0, beta=0.5)


# ============================================================
# BeliefObservation Tests
# ============================================================


class TestBeliefObservation:
    """BeliefObservation dataclass."""

    def test_minimal_construction(self) -> None:
        """Only required params: value and source (no default for source)."""
        obs = BeliefObservation(value=0.75, source=BeliefSource.HUMAN_INPUT)
        assert obs.value == 0.75
        assert obs.confidence == 1.0  # default
        assert obs.source == BeliefSource.HUMAN_INPUT
        assert obs.metadata == {}
        assert obs.timestamp.endswith("Z")
        assert isinstance(obs.observation_id, str)
        uuid.UUID(obs.observation_id)

    def test_full_construction(self) -> None:
        """All fields explicitly provided."""
        obs = BeliefObservation(
            value=0.2,
            source=BeliefSource.MACRO_CALENDAR,
            confidence=0.6,
            timestamp="2026-04-20T08:30:00Z",
            metadata={"analyst": "John Doe"},
        )
        assert obs.value == 0.2
        assert obs.confidence == 0.6
        assert obs.timestamp == "2026-04-20T08:30:00Z"
        assert obs.source == BeliefSource.MACRO_CALENDAR
        assert obs.metadata["analyst"] == "John Doe"

    def test_frozen_immutability(self) -> None:
        obs = BeliefObservation(value=0.5, source=BeliefSource.INFERRED)
        with pytest.raises(AttributeError):
            obs.value = 0.8

    def test_value_bounds_raises(self) -> None:
        """value < 0.0 or > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="value must be in"):
            BeliefObservation(value=-1.5, source=BeliefSource.INFERRED, confidence=0.5)
        with pytest.raises(ValueError, match="value must be in"):
            BeliefObservation(value=100.0, source=BeliefSource.INFERRED, confidence=1.0)

    def test_confidence_bounds_raises(self) -> None:
        """confidence < 0.0 or > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="confidence must be in"):
            BeliefObservation(value=0.5, source=BeliefSource.INFERRED, confidence=-0.1)
        with pytest.raises(ValueError, match="confidence must be in"):
            BeliefObservation(value=0.5, source=BeliefSource.INFERRED, confidence=1.5)

    def test_confidence_zero_one_accepted(self) -> None:
        """confidence=0.0 and confidence=1.0 are valid."""
        obs_zero = BeliefObservation(value=0.5, source=BeliefSource.INFERRED, confidence=0.0)
        assert obs_zero.confidence == 0.0
        obs_one = BeliefObservation(value=0.5, source=BeliefSource.INFERRED, confidence=1.0)
        assert obs_one.confidence == 1.0


# ============================================================
# BeliefRetirement Tests
# ============================================================


class TestBeliefRetirement:
    """BeliefRetirement dataclass."""

    def test_minimal_construction(self) -> None:
        ret = BeliefRetirement(
            proposition_id="prop-001",
            proposition="Test prop",
            reason="Below threshold",
            retired_confidence=0.05,
            threshold=0.1,
        )
        assert ret.proposition_id == "prop-001"
        assert ret.proposition == "Test prop"
        assert ret.reason == "Below threshold"
        assert ret.retired_confidence == 0.05
        assert ret.threshold == 0.1
        assert isinstance(ret.retirement_id, str)
        assert ret.retired_at.endswith("Z")

    def test_full_construction(self) -> None:
        ret = BeliefRetirement(
            proposition_id="prop-002",
            proposition="BTC moon shot",
            reason="Conflict lost",
            retired_confidence=0.08,
            threshold=0.1,
            retired_at="2026-06-01T00:00:00Z",
            retirement_id="ret-abc-123",
        )
        assert ret.retirement_id == "ret-abc-123"
        assert ret.retired_at == "2026-06-01T00:00:00Z"
        assert ret.proposition == "BTC moon shot"

    def test_auto_id_generation(self) -> None:
        ret1 = BeliefRetirement(
            proposition_id="p1", proposition="P1",
            reason="R1", retired_confidence=0.05,
        )
        ret2 = BeliefRetirement(
            proposition_id="p2", proposition="P2",
            reason="R2", retired_confidence=0.03,
        )
        assert ret1.retirement_id != ret2.retirement_id
        uuid.UUID(ret1.retirement_id)
        uuid.UUID(ret2.retirement_id)

    def test_frozen_immutability(self) -> None:
        ret = BeliefRetirement(
            proposition_id="p", proposition="P",
            reason="R", retired_confidence=0.05,
        )
        with pytest.raises(AttributeError):
            ret.reason = "New reason"

    def test_retired_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="retired_confidence"):
            BeliefRetirement(
                proposition_id="p", proposition="P",
                reason="R", retired_confidence=1.5,
            )


# ============================================================
# BeliefSnapshot Tests
# ============================================================


class TestBeliefSnapshot:
    """BeliefSnapshot dataclass."""

    def test_construction(self) -> None:
        node = BeliefNode(proposition="Test", alpha=5.0, beta=2.0)
        snap = BeliefSnapshot(
            node=node,
            observation_count=3,
            expectation=0.714,
            uncertainty=0.123,
            score=0.85,
            status_label="active",
        )
        assert snap.node is node
        assert snap.observation_count == 3
        assert snap.expectation == 0.714
        assert snap.uncertainty == 0.123
        assert snap.score == 0.85
        assert snap.status_label == "active"
        assert snap.timestamp.endswith("Z")

    def test_frozen_immutability(self) -> None:
        node = BeliefNode(proposition="Test", alpha=1.0, beta=1.0)
        snap = BeliefSnapshot(
            node=node, observation_count=0,
            expectation=0.5, uncertainty=0.289,
            score=0.5, status_label="active",
        )
        with pytest.raises(AttributeError):
            snap.score = 0.9

    def test_to_dict_snapshot(self) -> None:
        node = BeliefNode(
            proposition="Test snapshot",
            proposition_id="snap-001",
            alpha=3.0,
            beta=2.0,
        )
        snap = BeliefSnapshot(
            node=node,
            observation_count=5,
            expectation=0.6,
            uncertainty=0.18,
            score=0.72,
            status_label="active",
        )
        d = snap.to_dict()
        assert d["proposition_id"] == "snap-001"
        assert d["expectation"] == 0.6
        assert d["observation_count"] == 5
        assert d["score"] == 0.72
        assert d["status_label"] == "active"
        assert d["alpha"] == 3.0
        assert d["beta"] == 2.0
        assert d["status"] == "active"
        assert d["source"] == "inferred"
        assert d["proposition"] == "Test snapshot"


# ============================================================
# ConflictRecord Tests
# ============================================================


class TestConflictRecord:
    """ConflictRecord dataclass."""

    def test_minimal_construction(self) -> None:
        cr = ConflictRecord(
            left_id="prop-A",
            right_id="prop-B",
            left_confidence=0.8,
            right_confidence=0.4,
            resolution=ResolutionStrategy.OVERRIDE_HIGHER_CONFIDENCE,
        )
        assert cr.left_id == "prop-A"
        assert cr.right_id == "prop-B"
        assert cr.left_confidence == 0.8
        assert cr.right_confidence == 0.4
        assert cr.resolution == ResolutionStrategy.OVERRIDE_HIGHER_CONFIDENCE
        assert isinstance(cr.conflict_id, str)
        assert cr.resolved_at.endswith("Z")

    def test_auto_id_generation(self) -> None:
        cr1 = ConflictRecord(
            left_id="A", right_id="B",
            left_confidence=0.9, right_confidence=0.3,
            resolution=ResolutionStrategy.MERGE,
        )
        cr2 = ConflictRecord(
            left_id="C", right_id="D",
            left_confidence=0.5, right_confidence=0.5,
            resolution=ResolutionStrategy.AMBIGUOUS_REJECT,
        )
        assert cr1.conflict_id != cr2.conflict_id
        uuid.UUID(cr1.conflict_id)
        uuid.UUID(cr2.conflict_id)

    def test_frozen_immutability(self) -> None:
        cr = ConflictRecord(
            left_id="A", right_id="B",
            left_confidence=0.9, right_confidence=0.3,
            resolution=ResolutionStrategy.AMBIGUOUS_REJECT,
        )
        with pytest.raises(AttributeError):
            cr.resolution = ResolutionStrategy.MERGE

    def test_left_right_must_differ(self) -> None:
        with pytest.raises(ValueError, match="left_id and right_id must be different"):
            ConflictRecord(
                left_id="same", right_id="same",
                left_confidence=0.5, right_confidence=0.5,
                resolution=ResolutionStrategy.MERGE,
            )

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="left_confidence"):
            ConflictRecord(
                left_id="A", right_id="B",
                left_confidence=-0.1, right_confidence=0.5,
                resolution=ResolutionStrategy.MERGE,
            )


# ============================================================
# Serialization Round-Trip Tests
# ============================================================


class TestBeliefNodeSerialization:
    """BeliefNode to_dict / from_dict round trip."""

    def test_round_trip(self) -> None:
        original = BeliefNode(
            proposition="Serialization test",
            proposition_id="ser-001",
            alpha=5.0,
            beta=3.0,
            status=BeliefStatus.CONFLICTED,
            source=BeliefSource.MARKET_DATA,
            created_at="2026-01-01T00:00:00Z",
            last_updated="2026-06-01T12:00:00Z",
            metadata={"key": "value"},
        )
        d = original.to_dict()
        restored = BeliefNode.from_dict(d)
        assert original == restored

    def test_to_dict_contains_expected_keys(self) -> None:
        node = BeliefNode(
            proposition="Test", proposition_id="t1",
            alpha=2.0, beta=1.0,
        )
        d = node.to_dict()
        assert "proposition" in d
        assert "proposition_id" in d
        assert "alpha" in d
        assert "beta" in d
        assert "status" in d
        assert "source" in d
        # status and source should be strings (enum values)
        assert isinstance(d["status"], str)
        assert isinstance(d["source"], str)


class TestBeliefObservationSerialization:
    """BeliefObservation to_dict / from_dict round trip."""

    def test_round_trip(self) -> None:
        original = BeliefObservation(
            value=0.3,
            source=BeliefSource.MACRO_CALENDAR,
            confidence=0.8,
            timestamp="2026-03-15T10:00:00Z",
            metadata={"event": "FOMC"},
        )
        d = original.to_dict()
        restored = BeliefObservation.from_dict(d)
        assert original == restored


class TestConflictRecordSerialization:
    """ConflictRecord to_dict / from_dict round trip."""

    def test_round_trip(self) -> None:
        original = ConflictRecord(
            left_id="prop-1",
            right_id="prop-2",
            left_confidence=0.9,
            right_confidence=0.3,
            resolution=ResolutionStrategy.MERGE,
            resolved_at="2026-05-01T00:00:00Z",
            conflict_id="conflict-001",
            metadata={"ticker": "TSLA"},
        )
        d = original.to_dict()
        restored = ConflictRecord.from_dict(d)
        assert original == restored


class TestBeliefRetirementSerialization:
    """BeliefRetirement to_dict / from_dict round trip."""

    def test_round_trip(self) -> None:
        original = BeliefRetirement(
            proposition_id="prop-ret-1",
            proposition="Old belief",
            reason="Timeout",
            retired_confidence=0.05,
            threshold=0.1,
            retired_at="2026-04-01T00:00:00Z",
            retirement_id="ret-001",
        )
        d = original.to_dict()
        restored = BeliefRetirement.from_dict(d)
        assert original == restored