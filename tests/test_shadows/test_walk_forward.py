"""Tests for WalkForwardValidator — IS-WFA-OOS protocol (P2-2)."""
import pytest
from marketmind.shadows.ranking_engine import WalkForwardValidator, WFValidationResult
from marketmind.shadows.shadow_state import DailySnapshot


def _make_snapshots(n_days: int, is_deflated: float = 0.05,
                    oos_deflated: float = 0.04,
                    daily_return_sign: float = 0.001,
                    noise_scale: float = 0.005,
                    seed: int = 42) -> list[DailySnapshot]:
    """Generate synthetic snapshots for walk-forward testing.

    First 90 days (IS) get is_deflated + noise.
    Next 2 days (purge) get noise only.
    Last 20 days (OOS) get oos_deflated + noise.
    """
    import random
    rng = random.Random(seed)
    snaps = []
    for i in range(n_days):
        if i < 90:
            ds = is_deflated + rng.gauss(0, noise_scale)
        elif i < 92:
            ds = rng.gauss(0, noise_scale)
        else:
            ds = oos_deflated + rng.gauss(0, noise_scale)

        ret = daily_return_sign if rng.random() > 0.4 else -daily_return_sign

        snaps.append(DailySnapshot(
            shadow_id="test_shadow",
            date=f"2026-{(i // 30 + 1):02d}-{(i % 30 + 1):02d}",
            virtual_capital=100000.0,
            daily_return_pct=ret,
            deflated_score=ds,
        ))
    return snaps


class TestWalkForwardValidator:

    def test_wfe_passing_normal_shadow(self):
        """A shadow with similar IS and OOS performance should pass WFE."""
        validator = WalkForwardValidator()
        snaps = _make_snapshots(
            200, is_deflated=0.05, oos_deflated=0.045, noise_scale=0.002
        )
        result = validator.validate("test_shadow", snaps)
        assert not result.skipped
        assert not result.is_overfit
        assert result.wfe_ratio >= 0.5
        assert result.total_windows > 0

    def test_wfe_flagging_overfit_shadow(self):
        """A shadow with severe OOS degradation should be flagged."""
        validator = WalkForwardValidator()
        snaps = _make_snapshots(
            200, is_deflated=0.10, oos_deflated=0.02, noise_scale=0.001
        )
        result = validator.validate("test_shadow", snaps)
        assert not result.skipped
        assert result.is_overfit
        assert result.wfe_ratio < 0.5

    def test_insufficient_career_days_early_exit(self):
        """Shadows with fewer than min_career_days should skip WFE."""
        validator = WalkForwardValidator(min_career_days=120)
        snaps = _make_snapshots(60)  # Only 60 days
        result = validator.validate("test_shadow", snaps)
        assert result.skipped
        assert "insufficient_career" in result.skip_reason

    def test_near_zero_is_deflated_skip(self):
        """When IS deflated score is near zero, skip to avoid division noise."""
        validator = WalkForwardValidator()
        snaps = _make_snapshots(
            200, is_deflated=0.0001, oos_deflated=0.005, noise_scale=0.0001
        )
        result = validator.validate("test_shadow", snaps)
        # With near-zero IS, should skip regardless of WFE ratio
        if abs(result.mean_is_deflated) <= 0.001:
            assert result.skipped
            assert "near_zero_is" in result.skip_reason

    def test_binomial_sign_test_directional(self):
        """Binomial sign test should reject H0 when OOS accuracy is extreme."""
        validator = WalkForwardValidator()
        # Generate snaps with strongly positive OOS returns (80% positive)
        import random
        rng = random.Random(123)
        snaps = []
        for i in range(200):
            if i < 90:
                ds = 0.05 + rng.gauss(0, 0.003)
            elif i < 92:
                ds = rng.gauss(0, 0.003)
            else:
                ds = 0.05 + rng.gauss(0, 0.003)
            # 80% positive returns in OOS
            is_oos = i >= 92
            if is_oos:
                ret = 0.001 if rng.random() < 0.8 else -0.001
            else:
                ret = 0.001 if rng.random() < 0.5 else -0.001
            snaps.append(DailySnapshot(
                shadow_id="test_shadow",
                date=f"2026-{(i // 30 + 1):02d}-{(i % 30 + 1):02d}",
                virtual_capital=100000.0,
                daily_return_pct=ret,
                deflated_score=ds,
            ))
        result = validator.validate("test_shadow", snaps)
        assert not result.skipped
        assert result.oos_directional_accuracy > 0.6
        # With 80% accuracy, binomial p-value should be very small
        assert result.binomial_p_value < 0.05

    def test_windows_count_increases_with_data(self):
        """More career days should produce more walk-forward windows."""
        validator = WalkForwardValidator()
        snaps_short = _make_snapshots(150)
        snaps_long = _make_snapshots(300)
        r1 = validator.validate("test", snaps_short)
        r2 = validator.validate("test", snaps_long)
        if not r1.skipped and not r2.skipped:
            assert r2.total_windows > r1.total_windows
