"""Tests for CollusionDetector -- agreement statistics, convergence vs herding discrimination, escalation pipeline."""
import pytest
from unittest.mock import MagicMock

from projects.marketmind.shadows.shadow_state import CollusionFlag
from projects.marketmind.config.settings import ShadowSettings
from projects.marketmind.shadows.shadow_agent import ShadowVote
# Module under test (will be created)
from projects.marketmind.shadows.collusion_detector import CollusionDetector


@pytest.fixture
def settings():
    return ShadowSettings(
        collusion_agreement_threshold=0.80,
        collusion_consecutive_days_flag=3,
        collusion_consecutive_days_audit=10,
        collusion_market_signal_threshold=0.70,
    )


@pytest.fixture
def detector(settings):
    return CollusionDetector(settings)


def make_votes(ticker, directions_and_confidences):
    """Helper: create a list of ShadowVote objects from (direction, confidence) tuples."""
    votes = []
    for i, (direction, confidence) in enumerate(directions_and_confidences):
        votes.append(ShadowVote(
            shadow_id=f"shadow_{i:02d}",
            shadow_type="expert",
            date="2026-05-11",
            ticker=ticker,
            direction=direction,
            confidence=confidence,
            thesis=f"Thesis for {ticker}",
            risk_note=f"Risk note for {ticker}",
        ))
    return votes


def make_market_data(ticker, price_trend=0.5, volume_conf=0.5, news_align=0.5):
    """Helper: create synthetic market data dict."""
    return {
        ticker: {
            "price_trend_strength": price_trend,
            "volume_confirmation": volume_conf,
            "news_sentiment_alignment": news_align,
            "close": 100.0,
            "volume": 1_000_000,
        }
    }


# ── Test: 80% agreement 3 days flags collusion ─────────────────────────────

def test_80pct_agreement_3_days_flags_collusion(detector):
    """If >=80% of shadows agree for 3 consecutive days, collusion should be flagged."""
    ticker = "AAPL"
    # 12 out of 15 agree on "long" -> 80% agreement
    votes = make_votes(ticker, [("long", 0.7)] * 12 + [("short", 0.6)] * 3)
    market_data = make_market_data(ticker, price_trend=0.6, volume_conf=0.5, news_align=0.5)

    # Run for 3 consecutive days
    flags = []
    for day in range(3):
        daily_flags = detector.run_daily_check(
            f"2026-05-{11+day:02d}",
            votes,
            market_data,
        )
        flags.extend(daily_flags)

    assert len(flags) > 0, "Should have at least one collusion flag"
    assert all(f.agreement_pct >= 80.0 for f in flags)


# ── Test: High market signal classified as convergence ────────────────────

def test_high_market_signal_classified_as_convergence(detector):
    """When market signal strength > 0.70, classify as 'convergence' (market-driven)."""
    verdict = detector.discriminate_convergence_vs_herding(
        agreement_pct=85.0,
        market_signal_strength=0.75,
        consecutive_days=3,
    )
    assert verdict == "convergence"


# ── Test: Low market signal classified as herding ─────────────────────────

def test_low_market_signal_classified_as_herding(detector):
    """When market signal strength <= 0.70, classify as 'herding' (behavioral)."""
    verdict = detector.discriminate_convergence_vs_herding(
        agreement_pct=88.0,
        market_signal_strength=0.45,
        consecutive_days=3,
    )
    assert verdict == "herding"


# ── Test: 10 days consecutive escalates ───────────────────────────────────

def test_10_days_consecutive_escalates(detector):
    """When consecutive days >= 10, escalate to institutional analysis."""
    ticker = "AAPL"
    votes = make_votes(ticker, [("long", 0.7)] * 13 + [("short", 0.6)] * 2)
    market_data = make_market_data(ticker, price_trend=0.5, volume_conf=0.5, news_align=0.5)

    # Run for 10 consecutive days
    flags = []
    for day in range(10):
        daily_flags = detector.run_daily_check(
            f"2026-05-{11+day:02d}",
            votes,
            market_data,
        )
        flags.extend(daily_flags)

    # Check if any flag has consecutive_days >= 10
    high_consecutive = [f for f in flags if f.consecutive_days >= 10]
    assert len(high_consecutive) > 0, "Should have a flag with >= 10 consecutive days"


# ── Test: Binomial test random null ───────────────────────────────────────

def test_binomial_test_random_null(detector):
    """P(>=12 out of 15 agree | p=0.5) should be ~0.018, which is significant at 0.05."""
    p_value = detector._binomial_test(n_agree=12, n_total=15, null_prob=0.5)
    # P(X >= 12) for Binomial(15, 0.5) ~ 0.0176
    assert p_value < 0.05, f"Expected p < 0.05, got {p_value}"
    assert p_value > 0.01, f"P-value {p_value} should be ~0.018"


# ── Test: No flag when below 80% ──────────────────────────────────────────

def test_no_flag_when_below_80pct(detector):
    """Agreement below 80% should NOT trigger a collusion flag."""
    ticker = "AAPL"
    # 11 out of 15 agree -> 73.3%, below 80% threshold
    votes = make_votes(ticker, [("long", 0.7)] * 11 + [("short", 0.6)] * 4)
    market_data = make_market_data(ticker)

    flags = detector.run_daily_check("2026-05-11", votes, market_data)
    assert len(flags) == 0


# ── Test: Compute agreement rate returns correct stats ────────────────────

def test_compute_agreement_rate_stats(detector):
    """compute_agreement_rate should return correct counts and percentages."""
    ticker = "TSLA"
    votes = make_votes(
        ticker,
        [("long", 0.8)] * 10 + [("short", 0.5)] * 3 + [("abstain", 0.0)] * 2,
    )
    stats = detector.compute_agreement_rate(votes, ticker)

    assert stats["total_votes"] == 15
    assert stats["long_count"] == 10
    assert stats["short_count"] == 3
    assert stats["abstain_count"] == 2
    # Non-abstaining = 13, 10/13 = ~76.9%
    assert stats["agreement_pct"] == pytest.approx(10 / 13 * 100, rel=0.01)
    assert stats["dominant_direction"] == "long"


# ── Test: Market signal strength computation ──────────────────────────────

def test_market_signal_strength_computation(detector):
    """compute_market_signal_strength should return weighted blend of components."""
    ticker = "AAPL"
    market_data = make_market_data(ticker, price_trend=0.8, volume_conf=0.6, news_align=0.4)

    strength = detector.compute_market_signal_strength(ticker, market_data)
    assert 0.0 <= strength <= 1.0
    # Weighted blend: ~0.8*0.4 + 0.6*0.3 + 0.4*0.3 = 0.62
    assert strength == pytest.approx(0.62, rel=0.1)
