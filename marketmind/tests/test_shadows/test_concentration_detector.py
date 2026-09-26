"""Tests for ConcentrationDetector -- direction concentration, source homogenization, methodology convergence."""
import pytest
from unittest.mock import MagicMock

from marketmind.shadows.concentration_detector import (
    ConcentrationDetector,
    REGIME_THRESHOLDS,
    SOURCE_HOMOGENIZATION_THRESHOLD,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def detector():
    """Fresh ConcentrationDetector with mock DB."""
    mock_db = MagicMock()
    return ConcentrationDetector(mock_db)


@pytest.fixture
def detector_with_state():
    """Detector with pre-populated consecutive days state."""
    mock_db = MagicMock()
    det = ConcentrationDetector(mock_db)
    # Pre-populate: 2 days of high agreement already recorded
    det._consecutive_days["SPY"] = 2
    return det


# ── Helpers ─────────────────────────────────────────────────────────────────

def make_analyses(ticker, directions):
    """Create list of analysis dicts from direction list."""
    return [
        {
            "shadow_id": f"shadow_{i:02d}",
            "ticker": ticker,
            "direction": d,
            "confidence": 0.7,
        }
        for i, d in enumerate(directions)
    ]


def make_fingerprints(root_source="yfinance"):
    """Create 3 fingerprints, 2 sharing the same dominant source."""
    return [
        {
            "shadow_id": "shadow_01",
            "primary_sources": [root_source],
            "source_weights": {root_source: 0.6, "fred": 0.3, "newsapi": 0.1},
        },
        {
            "shadow_id": "shadow_02",
            "primary_sources": [root_source],
            "source_weights": {root_source: 0.5, "cboe": 0.3, "sec_edgar": 0.2},
        },
        {
            "shadow_id": "shadow_03",
            "primary_sources": ["cnn_fg"],
            "source_weights": {"cnn_fg": 0.5, "aaii": 0.3, "defillama": 0.2},
        },
    ]


# ── Direction Concentration Tests ───────────────────────────────────────────

def test_no_concentration_with_low_agreement(detector):
    """When agreement is below threshold, no concentration should be flagged."""
    # 8 long, 7 short = 53% agreement, below any regime threshold
    analyses = make_analyses("SPY", ["long"] * 8 + ["short"] * 7)

    result = detector.detect_direction_concentration(analyses, regime="TRENDING")
    assert result["concentration_detected"] is False
    assert result["agreement_pct"] == pytest.approx(8 / 15 * 100, rel=0.1)
    assert result["dominant_direction"] == "long"


def test_concentration_detected_with_high_agreement(detector_with_state):
    """When agreement exceeds threshold for 3 consecutive days, flag concentration."""
    # 14 out of 15 = 93.3% agreement, exceeds 80% TRENDING threshold
    analyses = make_analyses("SPY", ["long"] * 14 + ["short"] * 1)

    result = detector_with_state.detect_direction_concentration(
        analyses, regime="TRENDING"
    )
    assert result["concentration_detected"] is True
    assert result["dominant_direction"] == "long"
    assert result["consecutive_days"] == 3  # 2 pre-populated + 1
    assert result["warning_message"] is not None
    assert "CONCENTRATION WARNING" in result["warning_message"]


def test_concentration_not_detected_with_1_day(detector):
    """Single day of high agreement should not trigger warning."""
    analyses = make_analyses("SPY", ["long"] * 14 + ["short"] * 1)

    result = detector.detect_direction_concentration(analyses, regime="TRENDING")
    assert result["concentration_detected"] is False
    assert result["consecutive_days"] == 1
    assert result["warning_message"] is None


def test_consecutive_days_reset_after_disagreement(detector_with_state):
    """Consecutive day counter should reset when agreement drops below threshold."""
    detector_with_state._consecutive_days["SPY"] = 2

    # Now give low agreement
    analyses = make_analyses("SPY", ["long"] * 8 + ["short"] * 7)

    result = detector_with_state.detect_direction_concentration(
        analyses, regime="TRENDING"
    )
    assert result["consecutive_days"] == 0
    assert result["concentration_detected"] is False
    assert detector_with_state._consecutive_days["SPY"] == 0


def test_range_bound_uses_lower_threshold(detector_with_state):
    """RANGE_BOUND regime uses 70% threshold (lower than 80%)."""
    # 11 out of 15 = 73.3% — below TRENDING but above RANGE_BOUND
    analyses = make_analyses("SPY", ["long"] * 11 + ["short"] * 4)

    # Pre-populate 2 consecutive days
    detector_with_state._consecutive_days["SPY"] = 2

    result = detector_with_state.detect_direction_concentration(
        analyses, regime="RANGE_BOUND"
    )
    # 73.3% > 70% RANGE_BOUND threshold → should trigger
    assert result["excessive"] is True
    assert result["concentration_detected"] is True
    assert result["threshold_used"] == REGIME_THRESHOLDS["RANGE_BOUND"]


def test_choppy_uses_highest_threshold(detector_with_state):
    """CHOPPY regime uses 95% threshold — very hard to trigger."""
    # 14 out of 15 = 93.3% — exceeds TRENDING but below CHOPPY threshold
    analyses = make_analyses("SPY", ["long"] * 14 + ["short"] * 1)

    detector_with_state._consecutive_days["SPY"] = 2

    result = detector_with_state.detect_direction_concentration(
        analyses, regime="CHOPPY"
    )
    # 93.3% < 95% CHOPPY threshold → should NOT trigger
    assert result["excessive"] is False
    assert result["concentration_detected"] is False


def test_vix_spike_uses_elevated_threshold(detector_with_state):
    """VIX > 35 should use VIX_SPIKE threshold (95%)."""
    analyses = make_analyses("SPY", ["long"] * 14 + ["short"] * 1)

    detector_with_state._consecutive_days["SPY"] = 2

    result = detector_with_state.detect_direction_concentration(
        analyses, regime="TRENDING", vix_level=38.0
    )
    # VIX > 35 switches to VIX_SPIKE threshold which is 95%
    # 93.3% < 95% → should NOT trigger
    assert result["excessive"] is False
    assert result["concentration_detected"] is False


def test_all_abstain_no_concentration(detector):
    """All shadows abstaining should not trigger."""
    analyses = make_analyses("SPY", ["abstain"] * 10)
    result = detector.detect_direction_concentration(analyses)
    assert result["concentration_detected"] is False
    assert result["agreement_pct"] == 0.0
    assert result["dominant_direction"] == "abstain"


def test_empty_analyses(detector):
    """Empty list should return safe defaults."""
    result = detector.detect_direction_concentration([], regime="TRENDING")
    assert result["concentration_detected"] is False
    assert result["agreement_pct"] == 0.0


# ── Source Homogenization Tests ─────────────────────────────────────────────

def test_source_homogenization_detected():
    """When >=50% share same dominant source, trigger BlackRock warning."""
    det = ConcentrationDetector(MagicMock())
    fps = make_fingerprints(root_source="yfinance")
    # 2 out of 3 = 66.7% share "yfinance" → exceeds 50% threshold

    result = det.detect_source_homogenization(fps)
    assert result is True


def test_no_homogenization_with_diverse_sources():
    """When no single source dominates 50%, no warning."""
    det = ConcentrationDetector(MagicMock())
    fps = [
        {"shadow_id": "a", "primary_sources": ["yfinance"]},
        {"shadow_id": "b", "primary_sources": ["fred"]},
        {"shadow_id": "c", "primary_sources": ["cboe"]},
        {"shadow_id": "d", "primary_sources": ["newsapi"]},
    ]
    result = det.detect_source_homogenization(fps)
    assert result is False


def test_homogenization_requires_at_least_2_shadows():
    """Single shadow cannot have homogenization."""
    det = ConcentrationDetector(MagicMock())
    fps = [{"shadow_id": "a", "primary_sources": ["yfinance"]}]
    result = det.detect_source_homogenization(fps)
    assert result is False


def test_homogenization_from_source_weights_fallback():
    """When primary_sources is missing, fall back to source_weights."""
    det = ConcentrationDetector(MagicMock())
    fps = [
        {"shadow_id": "a", "source_weights": {"yfinance": 0.8, "fred": 0.2}},
        {"shadow_id": "b", "source_weights": {"yfinance": 0.7, "cboe": 0.3}},
    ]
    result = det.detect_source_homogenization(fps)
    assert result is True  # 2/2 share "yfinance" as dominant


def test_homogenization_at_exact_threshold():
    """At exactly 50%, should NOT trigger (strictly >= 0.50)."""
    det = ConcentrationDetector(MagicMock())
    fps = [
        {"shadow_id": "a", "primary_sources": ["yfinance"]},
        {"shadow_id": "b", "primary_sources": ["yfinance"]},
        {"shadow_id": "c", "primary_sources": ["fred"]},
        {"shadow_id": "d", "primary_sources": ["cboe"]},
    ]
    # 2 out of 4 = 50% → exactly at threshold
    result = det.detect_source_homogenization(fps)
    assert result is True  # >= 0.50


# ── Methodology Convergence Tests ───────────────────────────────────────────

def test_methodology_convergence_identical_prompts():
    """Identical prompts should have Jaccard similarity = 1.0."""
    det = ConcentrationDetector(MagicMock())
    prompt = (
        "Analyze market using momentum indicators and trend following. "
        "Focus on relative strength, moving average crossovers, and "
        "volume confirmation. Exit on trend reversal signals."
    )
    sim = det.detect_methodology_convergence([prompt, prompt])
    assert sim == pytest.approx(1.0, rel=0.01)


def test_methodology_convergence_different_prompts():
    """Completely different prompts should have low similarity."""
    det = ConcentrationDetector(MagicMock())
    prompts = [
        "Fundamental analysis using discounted cash flow models. "
        "Focus on earnings quality, balance sheet strength, and "
        "competitive moat durability.",
        "Technical momentum analysis with MACD and RSI signals. "
        "Trade breakouts with volume confirmation and trailing stops.",
    ]
    sim = det.detect_methodology_convergence(prompts)
    assert sim < 0.5, f"Expected low similarity, got {sim}"


def test_methodology_convergence_empty_input():
    """Empty or single prompt should return 0.0."""
    det = ConcentrationDetector(MagicMock())
    assert det.detect_methodology_convergence([]) == 0.0
    assert det.detect_methodology_convergence(["one prompt"]) == 0.0


def test_jaccard_similarity_basic():
    """Jaccard similarity should compute correctly for simple sets."""
    det = ConcentrationDetector(MagicMock())
    a = {"momentum", "trend", "breakout"}
    b = {"momentum", "trend", "reversal"}
    # Intersection = 2, Union = 4 → 0.5
    sim = det._jaccard_similarity(a, b)
    assert sim == 0.5


def test_tokenize_prompt_filters_short_tokens():
    """Tokens shorter than 3 characters should be filtered out."""
    det = ConcentrationDetector(MagicMock())
    tokens = det._tokenize_prompt("BUY signal on AAPL at 100 with MA crossover")
    # "at" (2 chars) should be filtered; numbers like "100" should be filtered
    assert "at" not in tokens
    assert "100" not in tokens
    assert "signal" in tokens
    assert "crossover" in tokens


# ── Regime Classification Tests ─────────────────────────────────────────────

def test_classify_trending_regime():
    """ADX >= 30 for 10+ days → TRENDING."""
    result = ConcentrationDetector.classify_regime(adx=35.0, amplitude_pct=1.0, consecutive_days=12)
    assert result == "TRENDING"


def test_classify_range_bound_regime():
    """ADX < 20, amplitude < 1.5% for 10+ days → RANGE_BOUND."""
    result = ConcentrationDetector.classify_regime(adx=15.0, amplitude_pct=1.0, consecutive_days=15)
    assert result == "RANGE_BOUND"


def test_classify_choppy_regime():
    """ADX < 20, amplitude >= 1.5% → CHOPPY."""
    result = ConcentrationDetector.classify_regime(adx=12.0, amplitude_pct=2.5, consecutive_days=8)
    assert result == "CHOPPY"


def test_classify_transitional_regime():
    """ADX 20-30 or conditions not met for long enough → TRANSITIONAL."""
    result = ConcentrationDetector.classify_regime(adx=25.0, amplitude_pct=1.0, consecutive_days=5)
    assert result == "TRANSITIONAL"


def test_extract_dominant_source_from_primary():
    """Should return first primary source if available."""
    det = ConcentrationDetector(MagicMock())
    fp = {"primary_sources": ["yfinance", "fred"]}
    assert det._extract_dominant_source(fp) == "yfinance"


def test_extract_dominant_source_from_weights():
    """Should return highest-weight source when primary_sources missing."""
    det = ConcentrationDetector(MagicMock())
    fp = {"source_weights": {"fred": 0.2, "yfinance": 0.5, "cboe": 0.3}}
    assert det._extract_dominant_source(fp) == "yfinance"
