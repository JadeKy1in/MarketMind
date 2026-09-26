"""Tests for single-input Kelly position sizing."""
from __future__ import annotations

import pytest
from marketmind.pipeline.position_sizing import (
    PositionSizeResult,
    compute_position_size,
)


class TestBasicKelly:
    def test_symmetric_bet_zero_kelly(self):
        """50% win rate at 1:1 ratio gives zero Kelly fraction."""
        result = compute_position_size(
            win_probability=0.5,
            win_loss_ratio=1.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.0,
        )
        assert result.raw_kelly_pct == 0.0
        assert result.half_kelly_pct == 0.0
        assert result.recommended_pct == 0.0

    def test_high_edge_positive_kelly(self):
        """81% win rate at 2:1 ratio gives significant Kelly fraction."""
        result = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.0,
            portfolio_pct_limit=0.50,  # raise cap so raw result shows
        )
        # K% = 0.81 - (1 - 0.81) / 2.0 = 0.81 - 0.095 = 0.715
        # Half = 0.3575, vol_adj=1.0, corr_adj=1.0 → ~0.3575
        assert result.raw_kelly_pct == pytest.approx(0.715, abs=0.001)
        assert result.half_kelly_pct == pytest.approx(0.3575, abs=0.001)
        assert result.recommended_pct == pytest.approx(0.3575, abs=0.001)
        assert result.risk_bps == pytest.approx(3575.0, abs=1.0)

    def test_user_conviction_discount_reduces_position(self):
        """User conviction discount should reduce, never increase, position."""
        result_full = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.0,
        )
        result_discounted = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=0.6,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.0,
        )
        assert result_discounted.recommended_pct < result_full.recommended_pct

    def test_conviction_cannot_increase_beyond_input(self):
        """User conviction 1.0 means no discount; probability stays at win_probability."""
        result = compute_position_size(
            win_probability=0.70,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.0,
        )
        # adjusted_prob = 0.70 * 1.0 = 0.70, same as input
        expected_kelly = 0.70 - (1.0 - 0.70) / 2.0  # = 0.70 - 0.15 = 0.55
        assert result.raw_kelly_pct == pytest.approx(0.55, abs=0.001)


class TestHardCap:
    def test_hard_cap_enforced(self):
        """Position above 25% cap should be clamped and flagged."""
        result = compute_position_size(
            win_probability=0.95,
            win_loss_ratio=5.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.0,
            portfolio_pct_limit=0.25,
        )
        assert result.capped is True
        assert result.recommended_pct == 0.25

    def test_hard_cap_not_triggered_when_below(self):
        """Position below cap should not be flagged."""
        result = compute_position_size(
            win_probability=0.55,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.0,
            portfolio_pct_limit=0.25,
        )
        assert result.capped is False
        assert result.recommended_pct < 0.25

    def test_custom_cap_respected(self):
        """Custom portfolio_pct_limit should be respected."""
        result = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.0,
            portfolio_pct_limit=0.15,
        )
        # Half Kelly ~0.3575 capped at 0.15
        assert result.recommended_pct == 0.15
        assert result.capped is True


class TestVolatilityAdjustment:
    def test_high_vol_reduces_position(self):
        """High volatility percentile should reduce position size."""
        result_high_vol = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.9,
            correlation_to_portfolio=0.0,
            portfolio_pct_limit=0.50,  # prevent cap from masking the difference
        )
        result_low_vol = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.1,
            correlation_to_portfolio=0.0,
            portfolio_pct_limit=0.50,
        )
        assert result_high_vol.recommended_pct < result_low_vol.recommended_pct
        assert result_high_vol.volatility_adjustment < 1.0
        assert result_low_vol.volatility_adjustment > 1.0

    def test_vol_adj_floor(self):
        """Volatility adjustment should not drop below 0.3."""
        result = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=1.0,
            correlation_to_portfolio=0.0,
        )
        assert result.volatility_adjustment >= 0.3


class TestCorrelationDiscount:
    def test_high_correlation_reduces_position(self):
        """Highly correlated positions should be discounted."""
        result_corr = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.9,
        )
        result_uncorr = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=0.0,
        )
        assert result_corr.recommended_pct < result_uncorr.recommended_pct
        assert result_corr.correlation_discount < 1.0

    def test_negative_correlation_no_discount(self):
        """Negative correlation means no discount (diversification benefit)."""
        result = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=-0.5,
        )
        # corr_discount = 1.0 - (-0.5) * 0.6 = 1.3, clamped to 1.0
        assert result.correlation_discount == 1.0

    def test_corr_discount_floor(self):
        """Correlation discount should not drop below 0.2."""
        result = compute_position_size(
            win_probability=0.81,
            win_loss_ratio=2.0,
            user_conviction_discount=1.0,
            volatility_percentile=0.5,
            correlation_to_portfolio=1.0,
        )
        assert result.correlation_discount >= 0.2


class TestInputValidation:
    def test_win_probability_out_of_range(self):
        with pytest.raises(ValueError, match="win_probability"):
            compute_position_size(
                win_probability=1.5,
                win_loss_ratio=2.0,
                user_conviction_discount=1.0,
                volatility_percentile=0.5,
                correlation_to_portfolio=0.0,
            )

    def test_win_probability_negative(self):
        with pytest.raises(ValueError, match="win_probability"):
            compute_position_size(
                win_probability=-0.1,
                win_loss_ratio=2.0,
                user_conviction_discount=1.0,
                volatility_percentile=0.5,
                correlation_to_portfolio=0.0,
            )

    def test_win_loss_ratio_zero(self):
        with pytest.raises(ValueError, match="win_loss_ratio"):
            compute_position_size(
                win_probability=0.81,
                win_loss_ratio=0.0,
                user_conviction_discount=1.0,
                volatility_percentile=0.5,
                correlation_to_portfolio=0.0,
            )

    def test_win_loss_ratio_negative(self):
        with pytest.raises(ValueError, match="win_loss_ratio"):
            compute_position_size(
                win_probability=0.81,
                win_loss_ratio=-1.0,
                user_conviction_discount=1.0,
                volatility_percentile=0.5,
                correlation_to_portfolio=0.0,
            )

    def test_user_conviction_out_of_range(self):
        with pytest.raises(ValueError, match="user_conviction_discount"):
            compute_position_size(
                win_probability=0.81,
                win_loss_ratio=2.0,
                user_conviction_discount=1.5,
                volatility_percentile=0.5,
                correlation_to_portfolio=0.0,
            )

    def test_volatility_percentile_out_of_range(self):
        with pytest.raises(ValueError, match="volatility_percentile"):
            compute_position_size(
                win_probability=0.81,
                win_loss_ratio=2.0,
                user_conviction_discount=1.0,
                volatility_percentile=-0.1,
                correlation_to_portfolio=0.0,
            )

    def test_correlation_out_of_range(self):
        with pytest.raises(ValueError, match="correlation_to_portfolio"):
            compute_position_size(
                win_probability=0.81,
                win_loss_ratio=2.0,
                user_conviction_discount=1.0,
                volatility_percentile=0.5,
                correlation_to_portfolio=1.5,
            )

    def test_portfolio_pct_limit_invalid(self):
        with pytest.raises(ValueError, match="portfolio_pct_limit"):
            compute_position_size(
                win_probability=0.81,
                win_loss_ratio=2.0,
                user_conviction_discount=1.0,
                volatility_percentile=0.5,
                correlation_to_portfolio=0.0,
                portfolio_pct_limit=0.0,
            )


class TestResultRounding:
    def test_position_size_result_rounding(self):
        """Output values should be rounded and RiskBps should be round."""
        result = compute_position_size(
            win_probability=0.8123,
            win_loss_ratio=2.345,
            user_conviction_discount=0.876,
            volatility_percentile=0.543,
            correlation_to_portfolio=0.321,
        )
        # All floats should be rounded to 4 decimal places (or 0 for bps)
        assert result.recommended_pct == round(result.recommended_pct, 4)
        assert result.risk_bps == round(result.risk_bps, 0)
        assert isinstance(result.capped, bool)
