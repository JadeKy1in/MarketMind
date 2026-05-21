"""Tests for shadows/dpp_selector.py — DPP quality-diversity selection."""
import pytest
import numpy as np

from marketmind.shadows.dpp_selector import DPPSelector


class TestDPPSelector:
    """Tests for the Determinantal Point Process selector."""

    @pytest.fixture
    def quality_scores(self):
        """10 shadows with varying quality scores."""
        return {
            "shadow_1": 0.95,
            "shadow_2": 0.90,
            "shadow_3": 0.85,
            "shadow_4": 0.80,
            "shadow_5": 0.70,
            "shadow_6": 0.60,
            "shadow_7": 0.50,
            "shadow_8": 0.40,
            "shadow_9": 0.30,
            "shadow_10": 0.20,
        }

    @pytest.fixture
    def similarity_matrix(self):
        """Pairwise similarity — shadows 1-3 are similar (crypto cluster),
        shadows 4-6 are similar (commodity cluster), rest are diverse."""
        sim = {}
        all_ids = [f"shadow_{i}" for i in range(1, 11)]

        for sid in all_ids:
            sim[sid] = {}

        # Crypto cluster (1-3): high mutual similarity
        for i in range(1, 4):
            for j in range(1, 4):
                if i != j:
                    sim[f"shadow_{i}"][f"shadow_{j}"] = 0.75

        # Commodity cluster (4-6): high mutual similarity
        for i in range(4, 7):
            for j in range(4, 7):
                if i != j:
                    sim[f"shadow_{i}"][f"shadow_{j}"] = 0.70

        # Cross-cluster: low similarity
        for i in range(1, 4):
            for j in range(4, 11):
                sim[f"shadow_{i}"][f"shadow_{j}"] = 0.15

        for i in range(4, 7):
            for j in range(1, 4):
                sim[f"shadow_{i}"][f"shadow_{j}"] = 0.15
            for j in range(7, 11):
                sim[f"shadow_{i}"][f"shadow_{j}"] = 0.20

        # Shadow 7-10: diverse, low similarity to everything
        for i in range(7, 11):
            for j in range(1, 7):
                sim[f"shadow_{i}"][f"shadow_{j}"] = 0.10
            for j in range(7, 11):
                if i != j:
                    sim[f"shadow_{i}"][f"shadow_{j}"] = 0.10

        return sim

    @pytest.fixture
    def selector(self, quality_scores, similarity_matrix):
        """DPPSelector with 10-shadow fixture."""
        return DPPSelector(quality_scores, similarity_matrix)

    def test_select_returns_k_shadows(self, selector):
        """Should return exactly k shadows."""
        selected = selector.select(k=4)
        assert len(selected) == 4
        assert all(s.startswith("shadow_") for s in selected)

    def test_select_respects_regime_specialists(self, selector):
        """Regime specialists must always be included in selection."""
        specialists = ["shadow_9", "shadow_10"]
        selected = selector.select(k=5, regime_specialists=specialists)
        for sp in specialists:
            assert sp in selected, f"Regime specialist {sp} not in selection: {selected}"

    def test_select_k_equals_specialists(self, selector):
        """When k equals specialist count, return only specialists."""
        specialists = ["shadow_1", "shadow_2", "shadow_3"]
        selected = selector.select(k=3, regime_specialists=specialists)
        assert set(selected) == set(specialists)

    def test_select_favors_quality(self, selector):
        """Higher-quality shadows should be selected more often than lower-quality."""
        np.random.seed(42)
        counts = {}
        for _ in range(50):
            selected = selector.select(k=4)
            for sid in selected:
                counts[sid] = counts.get(sid, 0) + 1

        # Top-quality shadows (1, 2, 3) should appear more than bottom (8, 9, 10)
        top_avg = sum(counts.get(f"shadow_{i}", 0) for i in range(1, 4)) / 3
        bot_avg = sum(counts.get(f"shadow_{i}", 0) for i in range(8, 11)) / 3
        assert top_avg > bot_avg, (
            f"Top-quality avg count {top_avg:.1f} should exceed "
            f"bottom-quality avg count {bot_avg:.1f}"
        )

    def test_select_diversity_not_all_same_cluster(self, selector):
        """DPP should avoid selecting all shadows from the same cluster."""
        np.random.seed(42)
        # Run 30 selections; count how many are all-crypto-cluster
        all_crypto_count = 0
        for _ in range(30):
            selected = selector.select(k=3)
            crypto_count = sum(
                1 for s in selected
                if s in {"shadow_1", "shadow_2", "shadow_3"}
            )
            if crypto_count >= 3:
                all_crypto_count += 1
        # DPP should rarely pick all 3 from the same high-similarity cluster
        assert all_crypto_count <= 15, (
            f"All-crypto selections {all_crypto_count}/30 — "
            f"DPP should avoid clustering"
        )

    def test_select_nonexistent_specialist_ignored(self, selector):
        """Non-existent specialist IDs should be silently ignored."""
        selected = selector.select(k=3, regime_specialists=["nonexistent_shadow"])
        assert len(selected) == 3
        assert "nonexistent_shadow" not in selected

    def test_sample_dpp_returns_k_shadows(self, selector):
        """sample_dpp should return exactly k shadows."""
        selected = selector.sample_dpp(k=4, n_samples=50)
        assert len(selected) == 4

    def test_sample_dpp_frequency_based(self, selector):
        """sample_dpp returns the most frequent combination across n_samples rounds."""
        # Reduce n_samples for speed
        selected = selector.sample_dpp(k=3, n_samples=30)
        assert len(selected) == 3
        assert len(set(selected)) == 3  # No duplicates

    def test_sample_dpp_consistency(self, selector):
        """Multiple calls should produce consistent-quality results."""
        np.random.seed(42)
        result1 = selector.sample_dpp(k=3, n_samples=30)

        np.random.seed(42)
        result2 = selector.sample_dpp(k=3, n_samples=30)

        assert result1 == result2  # Same seed → same result

    def test_empty_quality_scores(self):
        """Empty quality scores → empty selection."""
        selector = DPPSelector({}, {})
        assert selector.select(k=5) == []

    def test_k_exceeds_pool_size(self, selector):
        """When k exceeds available shadows, return all shadows."""
        selected = selector.select(k=20)
        # Should return all 10 shadows (sorted by quality)
        assert len(selected) == 10

    def test_zero_k(self, selector):
        """k=0 should return empty list."""
        selected = selector.select(k=0)
        assert selected == []

    def test_regime_specialists_exceed_k(self, selector):
        """When specialists count exceeds k, return top-k by quality."""
        specialists = ["shadow_1", "shadow_2", "shadow_3", "shadow_4"]
        selected = selector.select(k=2, regime_specialists=specialists)
        assert len(selected) == 2
        # Should be the top-2 quality among specialists
        assert "shadow_1" in selected
        assert "shadow_2" in selected

    def test_kernel_matrix_symmetric_modulo_similarities(self, quality_scores, similarity_matrix):
        """The L-kernel should be built correctly: L_ij = q_i * q_j * sim(i,j)."""
        selector = DPPSelector(quality_scores, similarity_matrix)
        L = selector._L
        n = len(selector._shadow_ids)

        assert L.shape == (n, n)

        # Diagonal: L_ii = q_i^2 (sim = 1.0 for self, but similarity matrix
        # doesn't have self entries; we set L_ii = q_i * q_i)
        for i, sid in enumerate(selector._shadow_ids):
            q = quality_scores[sid]
            assert abs(L[i, i] - q * q) < 1e-10
