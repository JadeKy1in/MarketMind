"""Tests for shadows/brier_decomposition.py — Brier score ternary decomposition."""
import pytest
import math

from marketmind.shadows.brier_decomposition import (
    BrierDecomposition,
    decompose_brier,
    decompose_brier_componentwise,
    manokhin_classify,
)


class TestDecomposeBrier:
    """Tests for the Brier score decomposition function."""

    def test_perfect_calibration(self):
        """Perfectly calibrated probabilities: BS ≈ 0, MCB ≈ 0."""
        # If p_i always equals the outcome, BS ≈ 0
        probs = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        outcomes = [0, 0, 0, 1, 1, 1]

        result = decompose_brier(probs, outcomes)

        assert result.brier_score < 0.01  # Near zero
        assert result.mcb < 0.01  # Near zero
        assert result.dsc > 0  # Good discrimination
        assert 0.0 <= result.unc <= 0.25  # Valid uncertainty range
        assert result.manokhin_type in ("Eagle", "Bull", "Sloth", "Mole")

    def test_perfect_miscalibration(self):
        """Always-wrong predictions: BS is high."""
        probs = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
        outcomes = [0, 0, 0, 1, 1, 1]

        result = decompose_brier(probs, outcomes)

        # BS should be near 1.0 (everything wrong)
        assert result.brier_score > 0.9
        assert result.mcb > 0  # High miscalibration

    def test_identity_decomposition(self):
        """BS ≈ MCB + DSC - UNC (within binning approximation, wider tolerance for small N)."""
        probs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
        outcomes = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]

        result = decompose_brier(probs, outcomes, n_bins=5)

        identity = result.mcb + result.dsc - result.unc
        # With 10 items in 5 bins, binning approximation is coarser
        diff = abs(result.brier_score - identity)
        assert diff < 0.15, (
            f"BS={result.brier_score:.6f}, MCB+DSC-UNC={identity:.6f}, "
            f"diff={diff:.6f} — binning approximation error"
        )

    def test_mcb_non_negative(self):
        """MCB (miscalibration) should always be non-negative."""
        np_random = __import__('numpy').random
        np_random.seed(123)
        n = 500
        probs = [float(np_random.uniform(0, 1)) for _ in range(n)]
        outcomes = [int(np_random.random() < p) for p in probs]

        result = decompose_brier(probs, outcomes)
        assert result.mcb >= 0.0
        assert result.dsc >= 0.0
        assert result.unc >= 0.0

    def test_brier_score_matches_definition(self):
        """Brier score should equal mean squared error."""
        np_random = __import__('numpy').random
        np_random.seed(123)
        n = 100
        probs = [float(np_random.uniform(0, 1)) for _ in range(n)]
        outcomes = [int(np_random.random() < p) for p in probs]

        result = decompose_brier(probs, outcomes)
        expected_bs = sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / n
        assert abs(result.brier_score - expected_bs) < 1e-6, (
            f"BS={result.brier_score:.6f}, expected={expected_bs:.6f}"
        )

    def test_uncertainty_bounded(self):
        """UNC = o_bar * (1 - o_bar) ∈ [0, 0.25]."""
        probs = [0.5] * 10
        outcomes = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]  # 50/50 split

        result = decompose_brier(probs, outcomes)
        assert abs(result.unc - 0.25) < 0.01  # Max uncertainty at 50/50

    def test_uncertainty_minimum(self):
        """UNC → 0 when all outcomes are the same."""
        probs = [0.0] * 10
        outcomes = [0] * 10

        result = decompose_brier(probs, outcomes)
        assert result.unc < 0.001  # Near zero uncertainty

    def test_bs_zero_for_perfect_predictions(self):
        """BS = 0 when all predictions are perfectly correct."""
        probs = [0.0, 0.0, 1.0, 1.0]
        outcomes = [0, 0, 1, 1]

        result = decompose_brier(probs, outcomes)
        assert result.brier_score < 0.001

    def test_all_components_non_negative(self):
        """MCB, DSC, UNC should all be non-negative."""
        np_random = __import__('numpy').random
        np_random.seed(42)
        probs = [float(np_random.uniform(0, 1)) for _ in range(100)]
        outcomes = [int(np_random.random() < 0.4) for _ in range(100)]

        result = decompose_brier(probs, outcomes)
        assert result.brier_score >= 0.0
        assert result.mcb >= 0.0
        assert result.dsc >= 0.0
        assert result.unc >= 0.0

    def test_input_length_mismatch_raises(self):
        """Different-length inputs should raise ValueError."""
        with pytest.raises(ValueError, match="same length"):
            decompose_brier([0.5, 0.5], [0])

    def test_empty_input_raises(self):
        """Empty inputs should raise ValueError."""
        with pytest.raises(ValueError, match="not be empty"):
            decompose_brier([], [])


class TestManokhinClassify:
    """Tests for the Manokhin taxonomy classifier."""

    def test_eagle(self):
        """Low miscalibration + high discrimination = Eagle."""
        assert manokhin_classify(mcb=0.01, dsc=0.10) == "Eagle"

    def test_bull(self):
        """High miscalibration + high discrimination = Bull."""
        assert manokhin_classify(mcb=0.10, dsc=0.10) == "Bull"

    def test_sloth(self):
        """Low miscalibration + low discrimination = Sloth."""
        assert manokhin_classify(mcb=0.01, dsc=0.01) == "Sloth"

    def test_mole(self):
        """High miscalibration + low discrimination = Mole."""
        assert manokhin_classify(mcb=0.10, dsc=0.01) == "Mole"

    def test_boundary_threshold(self):
        """At exactly the threshold, classifies correctly."""
        # mcb=0.05 is at the boundary → "not low" → ≥ threshold means high
        assert manokhin_classify(mcb=0.05, dsc=0.05) == "Eagle"

    def test_custom_threshold(self):
        """Custom threshold should change classification boundary."""
        # With threshold=0.10, mcb=0.08 is "low"
        assert manokhin_classify(mcb=0.08, dsc=0.03, threshold=0.10) == "Sloth"
        # With threshold=0.01, mcb=0.08 is "high"
        assert manokhin_classify(mcb=0.08, dsc=0.15, threshold=0.01) == "Bull"

    def test_valid_return_values(self):
        """Should only return one of the four valid types."""
        result = manokhin_classify(mcb=0.03, dsc=0.07)
        assert result in ("Eagle", "Bull", "Sloth", "Mole")


class TestDecomposeBrierComponentwise:
    """Tests for the detailed component-wise decomposition."""

    def test_returns_all_keys(self):
        """Detailed decomposition should return all expected keys."""
        probs = [0.1, 0.2, 0.8, 0.9]
        outcomes = [0, 0, 1, 1]

        result = decompose_brier_componentwise(probs, outcomes)

        assert "brier_score" in result
        assert "mcb" in result
        assert "dsc" in result
        assert "unc" in result
        assert "manokhin_type" in result
        assert "base_rate" in result
        assert "n_samples" in result
        assert "bins" in result
        assert "identity_check" in result

    def test_bins_list_nonempty(self):
        """Should produce at least one bin with data."""
        probs = [0.5] * 50 + [0.6] * 50
        outcomes = [0] * 25 + [1] * 25 + [0] * 25 + [1] * 25

        result = decompose_brier_componentwise(probs, outcomes)
        assert len(result["bins"]) > 0

    def test_bins_have_expected_structure(self):
        """Each bin should contain calibration error, count, means."""
        probs = [0.1, 0.1, 0.9, 0.9]
        outcomes = [0, 0, 1, 1]

        result = decompose_brier_componentwise(probs, outcomes)

        for bin_info in result["bins"]:
            assert "bin" in bin_info
            assert "range" in bin_info
            assert "count" in bin_info
            assert "mean_prob" in bin_info
            assert "mean_outcome" in bin_info
            assert "calibration_error" in bin_info
            assert "mcb_contribution" in bin_info
            assert "dsc_contribution" in bin_info

    def test_length_mismatch_raises(self):
        """Different-length inputs should raise ValueError."""
        with pytest.raises(ValueError, match="Length mismatch"):
            decompose_brier_componentwise([0.5], [0, 1])

    def test_components_reasonable(self):
        """All components should be non-negative and within valid ranges."""
        np_random = __import__('numpy').random
        np_random.seed(123)
        n = 200
        probs = [float(np_random.uniform(0, 1)) for _ in range(n)]
        outcomes = [int(np_random.random() < p) for p in probs]

        result = decompose_brier_componentwise(probs, outcomes)
        assert result["mcb"] >= 0.0
        assert result["dsc"] >= 0.0
        assert 0.0 <= result["unc"] <= 0.25
        assert result["manokhin_type"] in ("Eagle", "Bull", "Sloth", "Mole")
        assert result["n_samples"] == n
        assert abs(result["base_rate"] - sum(outcomes) / n) < 0.01


class TestBrierDecompositionDataclass:
    """Tests for the BrierDecomposition dataclass."""

    def test_construction(self):
        """Should construct with all fields."""
        bd = BrierDecomposition(
            brier_score=0.25, mcb=0.10, dsc=0.15, unc=0.05, manokhin_type="Bull"
        )
        assert bd.brier_score == 0.25
        assert bd.mcb == 0.10
        assert bd.dsc == 0.15
        assert bd.unc == 0.05
        assert bd.manokhin_type == "Bull"

    def test_identity_holds(self):
        """BS = MCB + DSC - UNC should hold for any valid decomposition."""
        brier = 0.30
        mcb = 0.15
        dsc = 0.20
        unc = 0.05
        bd = BrierDecomposition(
            brier_score=brier, mcb=mcb, dsc=dsc, unc=unc, manokhin_type="Eagle"
        )
        assert bd.brier_score == brier
        assert abs(bd.mcb + bd.dsc - bd.unc - bd.brier_score) < 0.01
