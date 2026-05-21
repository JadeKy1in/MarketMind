"""Tests for shadows/data_fingerprint.py — per-shadow data source fingerprints.

Minimum tests (per Phase A spec §18):
  test_compute_fingerprint — creates DataFingerprint from source weight vector
  test_fingerprint_similarity_identical — same fingerprint → similarity 1.0
  test_detect_homogenization — flags shadows whose similarity exceeds threshold
"""
from __future__ import annotations
import pytest

from marketmind.shadows.data_fingerprint import (
    DataFingerprint,
    DataFingerprinter,
    SOURCE_CATALOG,
)


# ---------------------------------------------------------------------------
# Test 1: compute_fingerprint
# ---------------------------------------------------------------------------

class TestComputeFingerprint:
    """DataFingerprinter.compute_fingerprint() — fingerprint creation."""

    def test_compute_fingerprint_normalizes_weights(self):
        """Fingerprint normalizes weights to sum to 1.0 and computes uniqueness."""
        weights = {"fred": 5.0, "cboe": 3.0, "yfinance": 2.0}
        fp = DataFingerprinter.compute_fingerprint("shadow_01", weights)

        assert fp.shadow_id == "shadow_01"
        assert len(fp.source_weights) == 3
        # Normalized weights should sum to 1.0
        total = sum(fp.source_weights.values())
        assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"
        # Individual weights should be proportional
        assert abs(fp.source_weights["fred"] - 0.5) < 0.01
        assert abs(fp.source_weights["cboe"] - 0.3) < 0.01
        assert abs(fp.source_weights["yfinance"] - 0.2) < 0.01
        # Uniqueness should be in [0, 1]
        assert 0.0 <= fp.uniqueness_score <= 1.0
        # Primary sources: all three above 10%
        assert sorted(fp.primary_sources) == ["cboe", "fred", "yfinance"]

    def test_compute_fingerprint_single_source(self):
        """Single source yields uniqueness = 0.0."""
        fp = DataFingerprinter.compute_fingerprint("mono_source", {"yfinance": 1.0})
        assert fp.uniqueness_score == 0.0
        assert fp.primary_sources == ["yfinance"]

    def test_compute_fingerprint_uniform_yields_high_uniqueness(self):
        """Uniform weights (3 equal sources) yield high uniqueness."""
        fp = DataFingerprinter.compute_fingerprint("uniform", {"a": 1.0, "b": 1.0, "c": 1.0})
        assert fp.uniqueness_score > 0.9  # nearly perfectly even

    def test_compute_fingerprint_all_zero_weights(self):
        """All-zero weights are treated as uniform distribution."""
        fp = DataFingerprinter.compute_fingerprint("zero", {"fred": 0.0, "cboe": 0.0})
        assert len(fp.source_weights) == 2
        assert abs(sum(fp.source_weights.values()) - 1.0) < 0.001

    def test_compute_fingerprint_rejects_empty_id(self):
        """Empty shadow_id raises ValueError."""
        with pytest.raises(ValueError, match="shadow_id"):
            DataFingerprinter.compute_fingerprint("", {"fred": 1.0})

    def test_compute_fingerprint_rejects_empty_weights(self):
        """Empty source_weights raises ValueError."""
        with pytest.raises(ValueError, match="source_weights"):
            DataFingerprinter.compute_fingerprint("s1", {})

    def test_compute_fingerprint_rejects_negative_weight(self):
        """Negative weight raises ValueError."""
        with pytest.raises(ValueError, match="must be >= 0"):
            DataFingerprinter.compute_fingerprint("s1", {"fred": -0.5})


# ---------------------------------------------------------------------------
# Test 2: fingerprint_similarity_identical
# ---------------------------------------------------------------------------

class TestFingerprintSimilarity:
    """DataFingerprinter.fingerprint_similarity() — cosine similarity."""

    def test_fingerprint_similarity_identical(self):
        """Same fingerprint → similarity = 1.0."""
        weights = {"fred": 0.5, "cboe": 0.5}
        fp1 = DataFingerprinter.compute_fingerprint("s1", weights)
        fp2 = DataFingerprinter.compute_fingerprint("s2", dict(weights))

        sim = DataFingerprinter.fingerprint_similarity(fp1, fp2)
        assert abs(sim - 1.0) < 0.001, f"Expected 1.0, got {sim}"

    def test_fingerprint_similarity_different(self):
        """Completely disjoint source vectors → similarity = 0.0."""
        fp1 = DataFingerprinter.compute_fingerprint("s1", {"fred": 1.0})
        fp2 = DataFingerprinter.compute_fingerprint("s2", {"yfinance": 1.0})

        sim = DataFingerprinter.fingerprint_similarity(fp1, fp2)
        assert sim < 0.01, f"Expected near 0.0, got {sim}"

    def test_fingerprint_similarity_partial_overlap(self):
        """Partially overlapping source vectors → 0 < similarity < 1."""
        fp1 = DataFingerprinter.compute_fingerprint("s1", {"fred": 0.5, "cboe": 0.5})
        fp2 = DataFingerprinter.compute_fingerprint("s2", {"fred": 0.5, "yfinance": 0.5})

        sim = DataFingerprinter.fingerprint_similarity(fp1, fp2)
        assert 0.0 < sim < 1.0

    def test_fingerprint_similarity_edge_shared_source(self):
        """A single shared dominant source (95%) yields high similarity > 0.85."""
        fp1 = DataFingerprinter.compute_fingerprint("s1", {"fred": 0.95, "cboe": 0.05})
        fp2 = DataFingerprinter.compute_fingerprint("s2", {"fred": 0.95, "yfinance": 0.05})

        sim = DataFingerprinter.fingerprint_similarity(fp1, fp2)
        # Should be very high since fred dominates both
        assert sim > 0.85, f"Expected > 0.85, got {sim}"


# ---------------------------------------------------------------------------
# Test 3: detect_homogenization
# ---------------------------------------------------------------------------

class TestDetectHomogenization:
    """DataFingerprinter.detect_homogenization() — group similarity scanning."""

    def test_detect_homogenization(self):
        """Flags shadows whose fingerprint similarity exceeds threshold."""
        # s1 and s2 are nearly identical (high fred weight)
        # s3 uses completely different sources
        weights = {"fred": 0.9, "cboe": 0.1}
        fp1 = DataFingerprinter.compute_fingerprint("s1", weights)
        fp2 = DataFingerprinter.compute_fingerprint("s2", weights)
        fp3 = DataFingerprinter.compute_fingerprint("s3", {"yfinance": 1.0})

        flagged = DataFingerprinter.detect_homogenization([fp1, fp2, fp3], threshold=0.85)
        assert "s1" in flagged
        assert "s2" in flagged
        assert "s3" not in flagged

    def test_detect_homogenization_empty_list(self):
        """Empty fingerprint list returns empty result."""
        flagged = DataFingerprinter.detect_homogenization([], threshold=0.85)
        assert flagged == []

    def test_detect_homogenization_single_shadow(self):
        """Single shadow cannot be homogenized."""
        fp = DataFingerprinter.compute_fingerprint("lone", {"fred": 1.0})
        flagged = DataFingerprinter.detect_homogenization([fp], threshold=0.85)
        assert flagged == []

    def test_detect_homogenization_all_diverse(self):
        """When all shadows use disjoint sources, none flagged."""
        fp1 = DataFingerprinter.compute_fingerprint("s1", {"fred": 1.0})
        fp2 = DataFingerprinter.compute_fingerprint("s2", {"yfinance": 1.0})
        fp3 = DataFingerprinter.compute_fingerprint("s3", {"cboe": 1.0})

        flagged = DataFingerprinter.detect_homogenization([fp1, fp2, fp3], threshold=0.85)
        assert flagged == []


# ---------------------------------------------------------------------------
# SOURCE_CATALOG validation
# ---------------------------------------------------------------------------

class TestSourceCatalog:
    """SOURCE_CATALOG structure and content validation."""

    def test_catalog_has_entries(self):
        """SOURCE_CATALOG is non-empty."""
        assert len(SOURCE_CATALOG) >= 16

    def test_catalog_entries_have_required_fields(self):
        """Each entry has 'type' and 'cost' fields."""
        for name, info in SOURCE_CATALOG.items():
            assert "type" in info, f"Source '{name}' missing 'type' field"
            assert "cost" in info, f"Source '{name}' missing 'cost' field"
            assert isinstance(info["type"], str)
            assert isinstance(info["cost"], str)
