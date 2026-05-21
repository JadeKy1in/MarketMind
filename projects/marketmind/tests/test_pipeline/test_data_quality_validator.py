"""Tests for pipeline/data_quality_validator.py — OHLCV data quality checks.

Minimum tests (per Phase A spec §18):
  test_extreme_return_flagged — |return| > 5σ gets flagged
  test_zero_volume_flagged — volume=0 on trading day flagged
  test_ohlc_consistency — High < Open detected
"""
from __future__ import annotations
import pytest
from unittest.mock import patch

from marketmind.pipeline.data_quality_validator import (
    DataQualityValidator,
    QualityReport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def validator():
    """Default validator with sigma_threshold=5.0."""
    return DataQualityValidator(sigma_threshold=5.0)


def _make_ohlcv(open=100.0, high=105.0, low=98.0, close=103.0, volume=1000000,
                previous_close=None):
    """Create a standard OHLCV data dict."""
    data = {
        "open": open,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }
    if previous_close is not None:
        data["previous_close"] = previous_close
    return data


# ---------------------------------------------------------------------------
# Test 1: extreme_return_flagged
# ---------------------------------------------------------------------------

class TestExtremeReturnFlagging:
    """_check_extreme_return — flags |return| > sigma_threshold * sigma."""

    def test_extreme_return_flagged_above_threshold(self, validator):
        """A 10σ return gets flagged with sigma_threshold=5.0."""
        stats = {"mean_return": 0.001, "std_return": 0.01}  # 1bp mean, 1% std
        # daily_return = 0.10 (10%), z = (0.10 - 0.001) / 0.01 = 9.9σ
        msg = validator._check_extreme_return("SPY", 0.10, stats)
        assert msg is not None
        assert "extreme daily return" in msg
        assert "SPY" in msg

    def test_extreme_return_below_threshold_not_flagged(self, validator):
        """A 2σ return is NOT flagged with sigma_threshold=5.0."""
        stats = {"mean_return": 0.001, "std_return": 0.01}
        # daily_return = 0.02 (2%), z = (0.02 - 0.001) / 0.01 = 1.9σ
        msg = validator._check_extreme_return("SPY", 0.02, stats)
        assert msg is None

    def test_extreme_return_small_std_amplifies_zscore(self, validator):
        """A small 3% return against a tiny std (0.1%) gets flagged as extreme."""
        stats = {"mean_return": 0.0005, "std_return": 0.001}  # 0.1% std
        # daily_return = 0.03, z = (0.03 - 0.0005) / 0.001 = 29.5σ
        msg = validator._check_extreme_return("QQQ", 0.03, stats)
        assert msg is not None
        assert "extreme" in msg

    def test_extreme_return_zero_std_skips_check(self, validator):
        """Zero std_return skips the check (avoids division by zero)."""
        stats = {"mean_return": 0.001, "std_return": 0.0}
        msg = validator._check_extreme_return("SPY", 0.10, stats)
        assert msg is None


# ---------------------------------------------------------------------------
# Test 2: zero_volume_flagged
# ---------------------------------------------------------------------------

class TestZeroVolumeFlagging:
    """_check_zero_volume — flags volume=0 on trading day."""

    def test_zero_volume_flagged_on_trading_day(self, validator):
        """Volume=0 on a trading day triggers a warning."""
        data = {"volume": 0}
        msg = validator._check_zero_volume(data, is_trading_day=True)
        assert msg is not None
        assert "Zero volume" in msg

    def test_zero_volume_not_flagged_on_weekend(self, validator):
        """Volume=0 on a non-trading day does NOT trigger a warning."""
        data = {"volume": 0}
        msg = validator._check_zero_volume(data, is_trading_day=False)
        assert msg is None

    def test_nonzero_volume_not_flagged_on_trading_day(self, validator):
        """Positive volume on a trading day is fine."""
        data = {"volume": 500000}
        msg = validator._check_zero_volume(data, is_trading_day=True)
        assert msg is None

    def test_none_volume_treated_as_zero(self, validator):
        """None volume on a trading day is flagged."""
        data = {"volume": None}
        msg = validator._check_zero_volume(data, is_trading_day=True)
        assert msg is not None

    def test_string_volume_non_numeric_flagged(self, validator):
        """Non-numeric volume string is flagged."""
        data = {"volume": "N/A"}
        msg = validator._check_zero_volume(data, is_trading_day=True)
        assert msg is not None
        assert "non-numeric" in msg


# ---------------------------------------------------------------------------
# Test 3: ohlc_consistency
# ---------------------------------------------------------------------------

class TestOhlcConsistency:
    """_check_ohlc_consistency — flags High < Open and other inconsistencies."""

    def test_ohlc_consistency_high_below_open_flagged(self, validator):
        """High < Open triggers a warning."""
        data = {"open": 100.0, "high": 99.0, "low": 95.0, "close": 98.0}
        warnings = validator._check_ohlc_consistency(data)
        assert len(warnings) >= 1
        assert any("High" in w for w in warnings)

    def test_ohlc_consistency_high_below_close_flagged(self, validator):
        """High < Close triggers a warning (High < max(Open, Close))."""
        data = {"open": 100.0, "high": 102.0, "low": 101.0, "close": 105.0}
        warnings = validator._check_ohlc_consistency(data)
        assert len(warnings) >= 1
        # High (102) < Close (105)
        assert any("High" in w and "Close" in w for w in warnings)

    def test_ohlc_consistency_high_below_low_flagged(self, validator):
        """High < Low is nonsensical and should be flagged."""
        data = {"open": 100.0, "high": 95.0, "low": 98.0, "close": 97.0}
        warnings = validator._check_ohlc_consistency(data)
        assert len(warnings) >= 1
        assert any("High" in w and "Low" in w for w in warnings)

    def test_ohlc_consistency_low_above_open_flagged(self, validator):
        """Low > Open triggers a warning."""
        data = {"open": 95.0, "high": 105.0, "low": 98.0, "close": 100.0}
        warnings = validator._check_ohlc_consistency(data)
        assert len(warnings) >= 1
        assert any("Low" in w for w in warnings)

    def test_ohlc_consistent_data_no_warnings(self, validator):
        """Valid OHLC data produces no warnings."""
        data = {"open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0}
        warnings = validator._check_ohlc_consistency(data)
        assert warnings == []

    def test_ohlc_missing_fields_skips_check(self, validator):
        """Missing fields (None values) skip the consistency check gracefully."""
        data = {"open": 100.0, "high": None, "low": 98.0, "close": 103.0}
        warnings = validator._check_ohlc_consistency(data)
        assert warnings == []


# ---------------------------------------------------------------------------
# validate_ohlcv integration tests
# ---------------------------------------------------------------------------

class TestValidateOhlcvIntegration:
    """End-to-end validate_ohlcv() with multiple checks."""

    def test_clean_data_passes_all_checks(self, validator):
        """Valid OHLCV data with reasonable return passes all checks."""
        data = _make_ohlcv(
            open=100.0, high=105.0, low=98.0, close=103.0, volume=500000,
            previous_close=100.0,
        )
        stats = {"mean_return": 0.001, "std_return": 0.01}

        with patch.object(DataQualityValidator, "_is_trading_day", return_value=True):
            report = validator.validate_ohlcv("SPY", data, stats)

        assert report.is_valid is True
        assert report.warnings == []
        assert report.fields_flagged == []

    def test_multiple_issues_aggregated_in_report(self, validator):
        """When multiple checks fail, all warnings are collected."""
        data = _make_ohlcv(
            open=100.0, high=99.0, low=101.0, close=98.0, volume=0,
            previous_close=100.0,
        )
        stats = {"mean_return": 0.001, "std_return": 0.01}

        with patch.object(DataQualityValidator, "_is_trading_day", return_value=True):
            report = validator.validate_ohlcv("BAD", data, stats)

        assert report.is_valid is False
        # Should have OHLC inconsistencies + zero volume
        assert len(report.warnings) >= 2
        assert len(report.fields_flagged) >= 2

    def test_missing_historical_stats_skips_return_check(self, validator):
        """When historical_stats is None, extreme return check is skipped.

        The data is OHLC-consistent (High >= max(Open,Close), Low <= min(Open,Close)).
        Even though close=90.0 would be a -10% drop (triggering extreme return check
        if stats were provided), without historical_stats the check is skipped.
        """
        data = _make_ohlcv(
            open=100.0, high=105.0, low=88.0, close=90.0, volume=500000,
            previous_close=100.0,
        )

        with patch.object(DataQualityValidator, "_is_trading_day", return_value=True):
            report = validator.validate_ohlcv("SPY", data, historical_stats=None)

        # Without historical_stats, extreme return is not checked
        # OHLC data is consistent: High(105) >= max(100,90)=100, Low(88) <= min(100,90)=90
        assert report.is_valid is True


class TestQualityReport:
    """QualityReport dataclass structure."""

    def test_quality_report_defaults(self):
        report = QualityReport(is_valid=True, warnings=[], fields_flagged=[])
        assert report.source_switched is False
        assert report.fallback_used is None

    def test_quality_report_with_fallback(self):
        report = QualityReport(
            is_valid=False,
            warnings=["OHLC inconsistency"],
            fields_flagged=["open", "high"],
            source_switched=True,
            fallback_used="yfinance",
        )
        assert report.source_switched is True
        assert report.fallback_used == "yfinance"
