"""Tests for Event Study Runner — abnormal return computation,
significance detection, and direction matching."""
import math

import pytest

from marketmind.pipeline.event_study_runner import (
    EventStudyResult,
    EventStudyRunner,
)


class TestEventStudyRunner:
    """Tests for the EventStudyRunner class."""

    @pytest.fixture
    def runner(self) -> EventStudyRunner:
        return EventStudyRunner()

    # ── test_abnormal_return_computation ────────────────────────────

    def test_abnormal_return_computation(
        self, runner: EventStudyRunner
    ) -> None:
        """AR = R_asset - (alpha + beta * R_market)

        With alpha=0.001, beta=1.2, R_asset=0.02, R_market=0.01:
          expected = 0.001 + 1.2 * 0.01 = 0.013
          AR = 0.02 - 0.013 = 0.007
        """
        ar = runner._compute_abnormal_return(
            asset_return=0.02,
            market_return=0.01,
            alpha=0.001,
            beta=1.2,
        )
        expected = 0.02 - (0.001 + 1.2 * 0.01)  # = 0.007
        assert abs(ar - expected) < 1e-10, (
            f"Expected AR={expected}, got {ar}"
        )

    def test_abnormal_return_zero_beta(
        self, runner: EventStudyRunner
    ) -> None:
        """With beta=0 the expected return is just alpha."""
        ar = runner._compute_abnormal_return(
            asset_return=0.005,
            market_return=0.03,
            alpha=0.0005,
            beta=0.0,
        )
        expected = 0.005 - 0.0005  # = 0.0045
        assert abs(ar - expected) < 1e-10

    # ── test_significance_detection ─────────────────────────────────

    def test_significance_detection(
        self, runner: EventStudyRunner
    ) -> None:
        """When |AR| > 2 * sigma the result should be marked significant.

        Construct a clean scenario: an asset whose returns are exactly
        CAPM-driven (alpha=0, beta=1) except for a large spike on the
        event day.  The estimation-period sigma should be tiny, making
        the spike easily detectable.
        """
        n_total = 200  # total returns
        event_idx = 150  # event return index (spike goes here)

        # Generate market returns — small random walk.
        mr = [0.0]
        for _ in range(n_total - 1):
            mr.append(mr[-1] + 0.0002)  # gentle upward drift

        # Asset returns = CAPM (alpha=0, beta=1) plus tiny noise … except
        # on the event day where we inject a +5 % return.
        asset_returns = []
        for i in range(n_total):
            if i == event_idx:
                asset_returns.append(0.05)  # huge positive spike
            else:
                asset_returns.append(mr[i] + 0.0001)

        # Build closes: start at 100, walk forward via log-return inversion.
        closes = [100.0]
        for r in asset_returns:
            closes.append(closes[-1] * math.exp(r))

        # Create date labels so the runner can locate the event return.
        # price index = return index + 1 (the return ends at that close).
        dates = [f"D{i:03d}" for i in range(len(closes))]
        event_date = f"D{event_idx + 1:03d}"

        signal = {
            "event_date": event_date,
            "direction": "long",
            "person_name": "Test Figure",
            "event_type": "speech",
        }

        result = runner.run(
            signal, {"close": closes, "dates": dates}, mr
        )

        assert result.is_significant, (
            "Expected a significant AR with a 5 % spike, "
            f"got is_significant={result.is_significant}, "
            f"ar_daily={result.ar_daily}"
        )
        # The spike direction is positive, so direction_match should be
        # True for a 'long' signal.
        assert result.direction_match

    def test_no_significance_without_spike(
        self, runner: EventStudyRunner
    ) -> None:
        """When there is no abnormal event-day return the test should
        NOT flag significance."""
        n_total = 200
        event_idx = 150

        # All returns perfectly follow CAPM (alpha=0, beta=1).
        mr = [0.0]
        for _ in range(n_total - 1):
            mr.append(mr[-1] + 0.0002)

        asset_returns = [m + 0.00005 for m in mr]

        closes = [100.0]
        for r in asset_returns:
            closes.append(closes[-1] * math.exp(r))

        dates = [f"D{i:03d}" for i in range(len(closes))]
        event_date = f"D{event_idx + 1:03d}"

        signal = {
            "event_date": event_date,
            "direction": None,
            "person_name": "Test Figure",
            "event_type": "speech",
        }

        result = runner.run(
            signal, {"close": closes, "dates": dates}, mr
        )

        # Without a spike the AR should be tiny and NOT significant.
        assert not result.is_significant, (
            f"Expected is_significant=False without spike, "
            f"got ar_daily={result.ar_daily}"
        )

    # ── test_direction_match ────────────────────────────────────────

    def test_direction_match(self, runner: EventStudyRunner) -> None:
        """Verify direction match logic for long / short / warn."""
        # Long signal + positive AR → match
        assert runner._check_direction_match(0.03, "long") is True
        # Long signal + negative AR → no match
        assert runner._check_direction_match(-0.01, "long") is False
        # Short signal + negative AR → match
        assert runner._check_direction_match(-0.02, "short") is True
        # Short signal + positive AR → no match
        assert runner._check_direction_match(0.01, "short") is False
        # Warn / None → never a match
        assert runner._check_direction_match(0.05, "warn") is False
        assert runner._check_direction_match(-0.05, None) is False
        assert runner._check_direction_match(0.0, "long") is False

    # ── test_market_model_estimation ─────────────────────────────────

    def test_market_model_estimation(
        self, runner: EventStudyRunner
    ) -> None:
        """OLS recovers alpha=0, beta=1 when asset returns equal
        market returns exactly."""
        mr = [0.001 * i for i in range(100)]
        asset_ret = list(mr)  # perfect CAPM with alpha=0, beta=1

        alpha, beta = runner._estimate_market_model(asset_ret, mr)
        assert abs(alpha) < 1e-10, f"Expected alpha ≈ 0, got {alpha}"
        assert abs(beta - 1.0) < 1e-10, f"Expected beta ≈ 1, got {beta}"

    # ── test_regression_sigma ───────────────────────────────────────

    def test_regression_sigma_zero_residuals(
        self, runner: EventStudyRunner
    ) -> None:
        """When residuals are all zero sigma should be tiny (~0)."""
        mr = [0.001 * i for i in range(30)]
        asset_ret = list(mr)
        alpha, beta = runner._estimate_market_model(asset_ret, mr)
        sigma = runner._compute_regression_sigma(
            asset_ret, mr, alpha, beta
        )
        # With zero residuals sigma should be near zero.
        assert sigma < 0.001, f"Expected sigma ≈ 0, got {sigma}"

    # ── test_historical_accuracy ────────────────────────────────────

    def test_historical_accuracy(self) -> None:
        """update_historical_accuracy computes the fraction of events
        where direction_match is True."""
        results = [
            EventStudyResult(direction_match=True),
            EventStudyResult(direction_match=True),
            EventStudyResult(direction_match=False),
            EventStudyResult(direction_match=True),
        ]
        acc = EventStudyRunner.update_historical_accuracy("Test", results)
        assert acc["n"] == 4
        assert acc["accuracy"] == 0.75  # 3 out of 4

    def test_historical_accuracy_empty(self) -> None:
        """Empty result list returns default accuracy of 0.50."""
        acc = EventStudyRunner.update_historical_accuracy("Test", [])
        assert acc["n"] == 0
        assert acc["accuracy"] == 0.50
