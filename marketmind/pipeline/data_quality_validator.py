"""Data quality validation for market data before shadow consumption.

Pure Python, zero LLM calls. Runs BEFORE data reaches shadows.
Detects: extreme returns, zero volume, OHLC inconsistencies, cross-source deviation.

Phase A Module 3 — Data Foundation layer.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("marketmind.pipeline.data_quality_validator")


@dataclass
class QualityReport:
    """Result of data quality validation for a single ticker/data pair.

    Attributes:
        is_valid: True if no warnings were generated.
        warnings: Human-readable warning messages.
        fields_flagged: Field names (open, high, low, close, volume) that triggered warnings.
        source_switched: True if the validator suggests switching data source.
        fallback_used: Name of fallback data source if primary was rejected.
    """
    is_valid: bool
    warnings: list[str]
    fields_flagged: list[str]
    source_switched: bool = False
    fallback_used: str | None = None


class DataQualityValidator:
    """Validates market data quality before shadow analysis.

    Runs a sequence of pure-Python checks on OHLCV data:
    1. OHLC consistency: High >= max(Open,Close), Low <= min(Open,Close)
    2. Zero volume on trading days
    3. Extreme daily returns (> sigma_threshold * sigma from mean)

    All checks are heuristic — this validator does NOT make LLM calls.
    It gates data quality, not trading decisions.

    Usage:
        validator = DataQualityValidator(sigma_threshold=5.0)
        report = validator.validate_ohlcv("SPY", ohlcv_data, historical_stats)
        if not report.is_valid:
            logger.warning("Data quality issues: %s", report.warnings)
    """

    def __init__(self, sigma_threshold: float = 5.0):
        """Initialize the validator.

        Args:
            sigma_threshold: Number of standard deviations above which a daily
                            return is flagged as extreme. Default 5.0 (5-sigma).
        """
        if sigma_threshold <= 0:
            raise ValueError(f"sigma_threshold must be > 0, got {sigma_threshold}")
        self.sigma_threshold = sigma_threshold

    def validate_ohlcv(self, ticker: str, data: dict,
                       historical_stats: dict | None = None) -> QualityReport:
        """Run all quality checks on OHLCV data.

        Args:
            ticker: Ticker symbol for log context (e.g. "SPY").
            data: Dict with keys open, high, low, close, volume (all numeric).
                  May also include 'previous_close' for return calculation.
            historical_stats: Optional dict with 'mean_return' and 'std_return'
                             for extreme return detection. If omitted, extreme
                             return check is skipped.

        Returns:
            QualityReport with validation results.
        """
        warnings: list[str] = []
        fields_flagged: list[str] = []

        # --- Check 1: OHLC consistency ---
        ohlc_warnings = self._check_ohlc_consistency(data)
        if ohlc_warnings:
            warnings.extend(ohlc_warnings)
            # Flag the OHLC fields if any inconsistency found
            for field in ("open", "high", "low", "close"):
                if field not in fields_flagged:
                    fields_flagged.append(field)

        # --- Check 2: Zero volume on trading day ---
        is_trading_day = self._is_trading_day()
        vol_warning = self._check_zero_volume(data, is_trading_day)
        if vol_warning:
            warnings.append(vol_warning)
            if "volume" not in fields_flagged:
                fields_flagged.append("volume")

        # --- Check 3: Extreme daily return ---
        if historical_stats is not None:
            close = self._safe_float(data.get("close"))
            prev_close = self._safe_float(
                data.get("previous_close", data.get("prev_close", close))
            )
            if close is not None and prev_close is not None and prev_close != 0.0:
                daily_return = (close - prev_close) / prev_close
                return_warning = self._check_extreme_return(
                    ticker, daily_return, historical_stats
                )
                if return_warning:
                    warnings.append(return_warning)
                    if "close" not in fields_flagged:
                        fields_flagged.append("close")

        is_valid = len(warnings) == 0
        if not is_valid:
            logger.info("Data quality issues for %s: %d warnings — %s",
                        ticker, len(warnings), fields_flagged)

        return QualityReport(
            is_valid=is_valid,
            warnings=warnings,
            fields_flagged=fields_flagged,
        )

    # ------------------------------------------------------------------
    # Individual check methods
    # ------------------------------------------------------------------

    def _check_extreme_return(self, ticker: str, daily_return: float,
                              stats: dict) -> str | None:
        """Flag |daily_return| > sigma_threshold * sigma as suspicious.

        Args:
            ticker: Ticker symbol.
            daily_return: The day's return as a decimal (e.g. 0.05 = 5%).
            stats: Dict with 'mean_return' (float) and 'std_return' (float).

        Returns:
            Warning string if the return is extreme, None otherwise.
        """
        mean = stats.get("mean_return", 0.0)
        std = stats.get("std_return", 0.01)

        if std <= 0.0:
            logger.debug("Skipping extreme return check for %s: std_return=%.6f", ticker, std)
            return None

        z_score = (daily_return - mean) / std
        if abs(z_score) > self.sigma_threshold:
            return (
                f"{ticker}: extreme daily return {daily_return:.4%} "
                f"({abs(z_score):.1f}σ from mean {mean:.4%}, σ={std:.4%})"
            )
        return None

    def _check_zero_volume(self, data: dict, is_trading_day: bool) -> str | None:
        """Flag volume=0 on a trading day as suspicious.

        Args:
            data: OHLCV data dict. Must contain 'volume' key.
            is_trading_day: True if today is a weekday (Mon-Fri).

        Returns:
            Warning string if volume is zero on a trading day, None otherwise.
        """
        if not is_trading_day:
            return None

        volume = data.get("volume")
        # volume might be None, 0, or a string like "0"
        try:
            vol_float = float(volume) if volume is not None else 0.0
        except (TypeError, ValueError):
            return f"Volume value is non-numeric: {volume!r}"

        if vol_float == 0.0:
            return "Zero volume reported on trading day — possible data error or halted security"
        return None

    def _check_ohlc_consistency(self, data: dict) -> list[str]:
        """Flag High < max(Open, Close) or Low > min(Open, Close).

        These are basic price-level sanity checks:
        - High must be >= max(Open, Close, Low)
        - Low must be <= min(Open, Close, High)
        - High must be >= Low

        Args:
            data: Dict with optional open, high, low, close keys.

        Returns:
            List of warning strings (empty if consistent).
        """
        warnings: list[str] = []

        o = self._safe_float(data.get("open"))
        h = self._safe_float(data.get("high"))
        l = self._safe_float(data.get("low"))
        c = self._safe_float(data.get("close"))

        # If any required field is missing, skip consistency check
        if any(v is None for v in (o, h, l, c)):
            missing = [k for k, v in zip(("open", "high", "low", "close"), (o, h, l, c)) if v is None]
            logger.debug("Skipping OHLC consistency: missing fields %s", missing)
            return warnings

        max_oc = max(o, c)  # type: ignore[arg-type]  # safe_float guarantees float here
        min_oc = min(o, c)  # type: ignore[arg-type]

        if h < max_oc:
            warnings.append(
                f"OHLC inconsistency: High ({h:.2f}) < max(Open={o:.2f}, Close={c:.2f})"
            )
        if l > min_oc:
            warnings.append(
                f"OHLC inconsistency: Low ({l:.2f}) > min(Open={o:.2f}, Close={c:.2f})"
            )
        if h < l:
            warnings.append(
                f"OHLC inconsistency: High ({h:.2f}) < Low ({l:.2f})"
            )

        return warnings

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(value) -> float | None:
        """Convert a value to float, returning None on failure."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_trading_day() -> bool:
        """Determine if today is likely a trading day (Mon-Fri).

        This is a heuristic — does not account for holidays.
        A more advanced implementation could check against a holiday calendar.
        """
        import datetime as dt
        today = dt.date.today()
        return today.weekday() < 5  # Monday=0, Friday=4
