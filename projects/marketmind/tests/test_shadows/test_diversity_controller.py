"""Tests for shadows/diversity_controller.py — five-layer diversity monitoring."""
import pytest

from marketmind.shadows.data_fingerprint import (
    DataFingerprint,
    DataFingerprinter,
)
from marketmind.shadows.diversity_controller import (
    DiversityController,
    DiversityReport,
)


class TestDiversityController:
    """Tests for the five-layer DiversityController."""

    @pytest.fixture
    def controller(self):
        return DiversityController()

    @pytest.fixture
    def sample_fingerprints(self):
        """Create 5 diverse data fingerprints."""
        return {
            "shadow_1": DataFingerprinter.compute_fingerprint(
                "shadow_1",
                {"fred": 0.5, "cboe": 0.3, "eia": 0.2},
            ),
            "shadow_2": DataFingerprinter.compute_fingerprint(
                "shadow_2",
                {"fred": 0.6, "cboe": 0.2, "eia": 0.2},
            ),
            "shadow_3": DataFingerprinter.compute_fingerprint(
                "shadow_3",
                {"defillama": 0.5, "blockchain_com": 0.3, "newsapi": 0.2},
            ),
            "shadow_4": DataFingerprinter.compute_fingerprint(
                "shadow_4",
                {"yfinance": 0.4, "sec_edgar": 0.3, "bls": 0.3},
            ),
            "shadow_5": DataFingerprinter.compute_fingerprint(
                "shadow_5",
                {"lme": 0.4, "usda": 0.3, "eia": 0.3},
            ),
        }

    @pytest.fixture
    def strategy_vectors(self):
        """Strategy vectors with varied methodology mixes."""
        return {
            "shadow_1": {"fundamental": 0.6, "technical": 0.2, "sentiment": 0.2},
            "shadow_2": {"fundamental": 0.5, "technical": 0.3, "sentiment": 0.2},
            "shadow_3": {"onchain": 0.7, "sentiment": 0.2, "technical": 0.1},
            "shadow_4": {"fundamental": 0.4, "quantitative": 0.5, "macro": 0.1},
            "shadow_5": {"supply_demand": 0.6, "seasonal": 0.3, "macro": 0.1},
        }

    @pytest.fixture
    def decision_directions(self):
        """Decision direction sequences over time."""
        return {
            "shadow_1": [0.5, 0.3, -0.2, 0.8, 0.1, -0.3, 0.6],
            "shadow_2": [0.4, 0.2, -0.1, 0.7, 0.2, -0.2, 0.5],
            "shadow_3": [-0.4, -0.6, 0.1, -0.3, 0.5, 0.2, -0.1],
            "shadow_4": [0.1, 0.1, 0.0, 0.2, 0.0, 0.1, 0.0],
            "shadow_5": [-0.5, 0.3, 0.7, -0.2, 0.4, 0.6, -0.3],
        }

    # ── Layer 1: Source similarity ─────────────────────────────────────────

    def test_source_similarity_returns_valid_range(self, controller, sample_fingerprints):
        """Source similarity should be a valid cosine similarity in [0, 1]."""
        sim = controller.check_source_similarity("shadow_1", sample_fingerprints)
        assert 0.0 <= sim <= 1.0, f"Source similarity {sim:.4f} out of range"

    def test_source_similarity_diverse_returns_low(self, controller, sample_fingerprints):
        """Shadows with completely different sources should have low similarity."""
        sim = controller.check_source_similarity("shadow_3", sample_fingerprints)
        # shadow_3 uses crypto/onchain sources → low similarity with others
        assert sim < 0.8, f"Expected moderate-low similarity for diverse sources, got {sim:.4f}"

    def test_source_similarity_self_returns_zero_with_single_shadow(self, controller):
        """A single shadow should have similarity 0 (no cohort to compare)."""
        fps = {
            "lone_shadow": DataFingerprinter.compute_fingerprint(
                "lone_shadow", {"fred": 1.0}
            ),
        }
        sim = controller.check_source_similarity("lone_shadow", fps)
        assert sim == 0.0

    # ── Layer 2: Strategy similarity ───────────────────────────────────────

    def test_strategy_similarity_returns_valid_range(self, controller, strategy_vectors):
        """Strategy similarity should return a value in [0, 1]."""
        sim = controller.check_strategy_similarity("shadow_1", strategy_vectors)
        assert 0.0 <= sim <= 1.0, f"Strategy similarity {sim:.4f} out of range"

    def test_strategy_similarity_different_methodology(self, controller, strategy_vectors):
        """Shadows with disjoint methodologies should have low similarity."""
        sim = controller.check_strategy_similarity("shadow_3", strategy_vectors)
        # shadow_3 uses onchain methodology → low similarity with others
        assert sim < 0.9, f"Expected lower strategy similarity for crypto, got {sim:.4f}"

    # ── Layer 3: Output correlation ────────────────────────────────────────

    def test_output_correlation_correlated_returns_high(self, controller, decision_directions):
        """Shadows with correlated directions should show high correlation."""
        corr = controller.check_output_correlation("shadow_1", decision_directions)
        # shadow_1 and shadow_2 move in similar directions
        assert corr > 0.3, f"Expected moderate-high correlation, got {corr:.4f}"

    def test_output_correlation_anticorrelated_returns_abs(self, controller, decision_directions):
        """Anti-correlated shadows should still show high absolute correlation."""
        corr = controller.check_output_correlation("shadow_3", decision_directions)
        # shadow_3 is anticorrelated with shadow_1/shadow_2
        assert corr >= 0.0, f"Correlation should be non-negative (abs), got {corr:.4f}"

    # ── Layer 4: Map-Elites cell ───────────────────────────────────────────

    def test_map_elites_cell_output_format(self, controller):
        """Cell string should follow the R{x}_T{y}_A{z} format."""
        cell = controller.compute_map_elites_cell(0.5, 45, 3)
        assert cell == "R1_T1_A1", f"Expected R1_T1_A1, got {cell}"

    def test_map_elites_cell_extremes(self, controller):
        """Test edge cell assignments."""
        # Conservative, short-term, single asset
        assert controller.compute_map_elites_cell(0.1, 10, 1) == "R0_T0_A0"
        # Aggressive, long-term, macro
        assert controller.compute_map_elites_cell(0.9, 120, 10) == "R2_T2_A2"

    def test_detect_cell_crowding(self, controller):
        """Should flag cells with >30% of shadows."""
        cells = {
            "a": "R0_T0_A0",
            "b": "R0_T0_A0",
            "c": "R0_T0_A0",
            "d": "R0_T0_A0",  # 4/10 = 40% in this cell
            "e": "R1_T1_A1",
            "f": "R1_T1_A1",
            "g": "R2_T2_A2",
            "h": "R2_T2_A2",
            "i": "R0_T1_A0",
            "j": "R1_T0_A2",
        }
        crowded = controller.detect_cell_crowding(cells)
        # 4/10 = 40% > 30% threshold
        assert "a" in crowded
        assert "d" in crowded
        # 2/10 = 20% — not crowded
        assert "e" not in crowded

    # ── Layer 5: Homogenization ────────────────────────────────────────────

    def test_check_homogenized_strict_all_low(self, controller):
        """All scores low → not homogenized."""
        result = controller.check_homogenized(0.3, 0.2, 0.1, False)
        assert result is False

    def test_check_homogenized_high_source(self, controller):
        """High source similarity → homogenized."""
        result = controller.check_homogenized(0.9, 0.3, 0.1, False)
        assert result is True

    def test_check_homogenized_cell_crowded(self, controller):
        """Crowded cell → homogenized."""
        result = controller.check_homogenized(0.3, 0.2, 0.1, True)
        assert result is True

    # ── Full diversity check ───────────────────────────────────────────────

    def test_check_diversity_returns_report(self, controller, sample_fingerprints,
                                            strategy_vectors, decision_directions):
        """Full check should return a DiversityReport with all fields."""
        report = controller.check_diversity(
            "shadow_1", sample_fingerprints, strategy_vectors, decision_directions,
        )
        assert isinstance(report, DiversityReport)
        assert report.shadow_id == "shadow_1"
        assert 0.0 <= report.source_similarity <= 1.0
        assert 0.0 <= report.strategy_similarity <= 1.0
        assert 0.0 <= report.output_correlation <= 1.0
        assert isinstance(report.is_homogenized, bool)

    def test_check_diversity_with_map_elites(self, controller, sample_fingerprints,
                                             strategy_vectors, decision_directions):
        """Diversity check with map_elites_params should populate cell field."""
        map_params = {
            "shadow_1": (0.5, 45, 3),
            "shadow_2": (0.4, 40, 4),
            "shadow_3": (0.8, 15, 2),
            "shadow_4": (0.2, 100, 8),
            "shadow_5": (0.6, 60, 5),
        }
        report = controller.check_diversity(
            "shadow_1", sample_fingerprints, strategy_vectors,
            decision_directions, map_elites_params=map_params,
        )
        assert report.map_elites_cell != ""

    # ── BlackRock warning ──────────────────────────────────────────────────

    def test_blackrock_warning_majority_same_dominant(self, controller):
        """>=50% shadows share same dominant source → warning triggered."""
        fps = [
            DataFingerprinter.compute_fingerprint(f"s{i}", {"fred": 0.7, "other": 0.3})
            for i in range(6)
        ]
        fps += [
            DataFingerprinter.compute_fingerprint(f"s{i+6}", {"cboe": 0.7, "other": 0.3})
            for i in range(4)
        ]
        # 6/10 = 60% have dominant source "fred" → warning
        assert controller.detect_blackrock_warning(fps) is True

    def test_blackrock_warning_no_majority(self, controller):
        """Diverse dominant sources → no warning."""
        fps = [
            DataFingerprinter.compute_fingerprint(
                f"s{i}", {f"source_{i}": 0.5, "misc": 0.5}
            )
            for i in range(5)
        ]
        assert controller.detect_blackrock_warning(fps) is False

    def test_blackrock_warning_empty(self, controller):
        """Empty fingerprint list → no warning."""
        assert controller.detect_blackrock_warning([]) is False


class TestDiversityReport:
    """Tests for DiversityReport dataclass."""

    def test_report_defaults(self):
        """Report should initialize with sensible defaults."""
        report = DiversityReport(shadow_id="test_shadow")
        assert report.shadow_id == "test_shadow"
        assert report.source_similarity == 0.0
        assert report.strategy_similarity == 0.0
        assert report.output_correlation == 0.0
        assert report.map_elites_cell == ""
        assert report.is_homogenized is False

    def test_report_homogenized_flag(self):
        """Homogenized flag should be settable."""
        report = DiversityReport(shadow_id="bad_shadow", is_homogenized=True)
        assert report.is_homogenized is True


class TestCosineSimilarity:
    """Tests for the static _cosine_similarity helper."""

    def test_identical_vectors(self):
        """Identical vectors → similarity = 1.0."""
        sim = DiversityController._cosine_similarity(
            {"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}
        )
        assert abs(sim - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        """Orthogonal vectors → similarity ≈ 0.0."""
        sim = DiversityController._cosine_similarity(
            {"a": 1.0}, {"b": 1.0}
        )
        assert abs(sim - 0.0) < 1e-6

    def test_empty_vectors(self):
        """Empty vectors → similarity = 0.0."""
        sim = DiversityController._cosine_similarity({}, {})
        assert sim == 0.0
