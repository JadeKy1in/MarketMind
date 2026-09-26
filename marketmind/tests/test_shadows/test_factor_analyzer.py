"""Tests for FactorAnalyzer -- Carhart 4-factor regression, style drift detection, strategy classification."""
import pytest
import numpy as np

from marketmind.shadows.factor_analyzer import FactorAnalyzer


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_factor_data():
    """Generate synthetic factor data with known properties.

    Returns: (returns, mkt, smb, hml, mom) as lists.
    Returns have known alpha=0.001 (1bp/day), beta_mkt=1.0, beta_smb=0.3,
    beta_hml=-0.2, beta_mom=0.05 + noise.
    """
    np.random.seed(42)
    n = 252  # one year of daily data
    mkt = list(np.random.normal(0.0005, 0.01, n))
    smb = list(np.random.normal(0.0001, 0.005, n))
    hml = list(np.random.normal(0.0002, 0.004, n))
    mom = list(np.random.normal(0.0003, 0.006, n))

    alpha = 0.001
    returns = [
        alpha + 1.0 * mkt[i] + 0.3 * smb[i] + (-0.2) * hml[i] + 0.05 * mom[i]
        + np.random.normal(0, 0.002)  # idiosyncratic noise
        for i in range(n)
    ]
    return returns, mkt, smb, hml, mom


@pytest.fixture
def monthly_exposures():
    """Generate 12 months of factor exposures with no drift."""
    return [
        {"beta_mkt": 1.0, "beta_smb": 0.3, "beta_hml": -0.2, "beta_mom": 0.05}
        for _ in range(12)
    ]


@pytest.fixture
def drifting_exposures():
    """Generate 18 months: 15 stable base + 3 with abrupt drift in beta_smb.

    Base values are identical (zero variance in diffs), so any substantial
    change registers as >2σ. The drift changes beta_smb by +1.2 per month
    (from 0.3 to 1.5 to 2.7 to 3.9), yielding z-score ~2.1 per step.
    """
    base = [
        {"beta_mkt": 1.0, "beta_smb": 0.3, "beta_hml": -0.2, "beta_mom": 0.05}
        for _ in range(15)
    ]
    # Abrupt drift: beta_smb jumps from 0.3 → 1.5 → 2.7 → 3.9
    drifted = [
        {"beta_mkt": 1.0, "beta_smb": 1.5, "beta_hml": -0.2, "beta_mom": 0.05},
        {"beta_mkt": 1.0, "beta_smb": 2.7, "beta_hml": -0.2, "beta_mom": 0.05},
        {"beta_mkt": 1.0, "beta_smb": 3.9, "beta_hml": -0.2, "beta_mom": 0.05},
    ]
    return base + drifted


# ── Test: Carhart 4-factor regression recovers known parameters ─────────────

def test_carhart_recoveres_known_parameters(sample_factor_data):
    """Carhart regression should approximately recover the known factor loadings."""
    returns, mkt, smb, hml, mom = sample_factor_data

    result = FactorAnalyzer.compute_carhart_alpha(returns, mkt, smb, hml, mom)

    # Known alpha = 0.001 (1bp/day)
    assert abs(result["alpha"] - 0.001) < 0.002, (
        f"Alpha should be ~0.001, got {result['alpha']}"
    )
    # Known beta_mkt = 1.0
    assert abs(result["beta_mkt"] - 1.0) < 0.2, (
        f"beta_mkt should be ~1.0, got {result['beta_mkt']}"
    )
    # Known beta_smb = 0.3
    assert abs(result["beta_smb"] - 0.3) < 0.2, (
        f"beta_smb should be ~0.3, got {result['beta_smb']}"
    )
    # Known beta_hml = -0.2
    assert abs(result["beta_hml"] - (-0.2)) < 0.2, (
        f"beta_hml should be ~-0.2, got {result['beta_hml']}"
    )
    # Known beta_mom = 0.05
    assert abs(result["beta_mom"] - 0.05) < 0.1, (
        f"beta_mom should be ~0.05, got {result['beta_mom']}"
    )

    # R-squared should be reasonable for synthetic data
    assert result["r_squared"] > 0.5, f"R-squared too low: {result['r_squared']}"
    assert result["n_obs"] == 252


# ── Test: Regression validates input lengths ────────────────────────────────

def test_carhart_validates_input_lengths():
    """Regression should raise ValueError if input arrays have different lengths."""
    returns = [0.01] * 20
    mkt = [0.005] * 20
    smb = [0.001] * 19  # Wrong length
    hml = [0.002] * 20
    mom = [0.003] * 20

    with pytest.raises(ValueError, match="same length"):
        FactorAnalyzer.compute_carhart_alpha(returns, mkt, smb, hml, mom)


# ── Test: Regression requires minimum observations ─────────────────────────

def test_carhart_requires_minimum_observations():
    """Regression should raise ValueError with fewer than 6 observations."""
    r = [0.01] * 5
    with pytest.raises(ValueError, match="at least 6"):
        FactorAnalyzer.compute_carhart_alpha(r, r, r, r, r)


# ── Test: Style drift not detected in stable exposures ──────────────────────

def test_no_drift_in_stable_exposures(monthly_exposures):
    """Style drift should not be flagged when exposures are stable."""
    result = FactorAnalyzer.detect_style_drift(monthly_exposures, window=3)
    assert result is False, "Should not detect drift in stable exposures"


# ── Test: Style drift detected with sudden change ───────────────────────────

def test_drift_detected_with_sudden_change(drifting_exposures):
    """Style drift should be flagged when factor exposures change abruptly."""
    result = FactorAnalyzer.detect_style_drift(drifting_exposures, window=3)
    assert result is True, "Should detect drift when beta_mkt jumps >2σ for 3 months"


# ── Test: Style drift requires sufficient history ───────────────────────────

def test_drift_requires_sufficient_history():
    """Style drift should return False with too few data points."""
    short_history = [
        {"beta_mkt": 1.0, "beta_smb": 0.3, "beta_hml": -0.2, "beta_mom": 0.05},
        {"beta_mkt": 3.0, "beta_smb": 0.3, "beta_hml": -0.2, "beta_mom": 0.05},
    ]
    result = FactorAnalyzer.detect_style_drift(short_history, window=3)
    assert result is False, "Should not flag drift with insufficient history"


# ── Test: Classify momentum strategy ────────────────────────────────────────

def test_classify_momentum_strategy():
    """Strong momentum loading with neutral other factors -> Momentum."""
    exposures = {"beta_mkt": 1.0, "beta_smb": 0.01, "beta_hml": 0.01, "beta_mom": 0.10}
    result = FactorAnalyzer.classify_strategy(exposures)
    assert result == "Momentum"


# ── Test: Classify value strategy ───────────────────────────────────────────

def test_classify_value_strategy():
    """Negative beta_hml with market beta near 1 -> Value."""
    exposures = {"beta_mkt": 1.0, "beta_smb": 0.0, "beta_hml": -0.15, "beta_mom": 0.0}
    result = FactorAnalyzer.classify_strategy(exposures)
    assert result == "Value"


# ── Test: Classify market neutral ───────────────────────────────────────────

def test_classify_market_neutral():
    """Market beta near zero -> Market Neutral regardless of other factors."""
    exposures = {"beta_mkt": 0.10, "beta_smb": 0.01, "beta_hml": -0.01, "beta_mom": 0.8}
    result = FactorAnalyzer.classify_strategy(exposures)
    assert result == "Market Neutral"


# ── Test: Classify balanced as fallback ─────────────────────────────────────

def test_classify_balanced_as_fallback():
    """Moderate factor loadings with no clear dominance -> Balanced."""
    exposures = {"beta_mkt": 0.90, "beta_smb": 0.01, "beta_hml": 0.02, "beta_mom": 0.01}
    result = FactorAnalyzer.classify_strategy(exposures)
    assert result == "Balanced"


# ── Test: Strategy classifier returns valid archetypes ──────────────────────

def test_classifier_returns_valid_archetype():
    """All classification results should be from the valid archetype set."""
    valid = {"Momentum", "Value", "Growth", "Small-Cap", "Large-Cap",
             "Market Neutral", "High Beta", "Low Beta", "Balanced"}

    test_cases = [
        {"beta_mkt": 1.0, "beta_smb": 0.01, "beta_hml": 0.01, "beta_mom": 0.15},
        {"beta_mkt": 0.95, "beta_smb": 0.01, "beta_hml": 0.10, "beta_mom": 0.02},
        {"beta_mkt": 0.95, "beta_smb": 0.01, "beta_hml": -0.10, "beta_mom": 0.01},
        {"beta_mkt": 1.0, "beta_smb": 0.10, "beta_hml": 0.01, "beta_mom": 0.01},
        {"beta_mkt": 1.0, "beta_smb": -0.10, "beta_hml": 0.01, "beta_mom": 0.02},
        {"beta_mkt": 0.20, "beta_smb": 0.5, "beta_hml": 0.0, "beta_mom": 0.0},
        {"beta_mkt": 1.50, "beta_smb": 0.01, "beta_hml": 0.02, "beta_mom": 0.03},
        {"beta_mkt": 0.50, "beta_smb": 0.01, "beta_hml": 0.01, "beta_mom": 0.01},
    ]

    for exposures in test_cases:
        result = FactorAnalyzer.classify_strategy(exposures)
        assert result in valid, f"Classification '{result}' not in valid set {valid}"
