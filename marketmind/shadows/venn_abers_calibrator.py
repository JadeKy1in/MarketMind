"""Inductive conformal prediction for confidence calibration.

Uses Venn-Abers predictors to calibrate raw confidence scores into
well-calibrated probabilities. First attempts to use the venn_abers PyPI
library; falls back to sklearn.isotonic.IsotonicRegression if unavailable.

Phase D Module 3 — Analysis Middleware. Zero LLM dependencies.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("marketmind.shadows.venn_abers_calibrator")

# ── Lazy import tracking ────────────────────────────────────────────────────
# All optional dependencies are loaded on first use, not at module level.
# This prevents ImportError when sklearn or venn_abers are not installed
# until calibrate() is actually called.

_va_import_error: str | None = None
_sklearn_import_error: str | None = None


def _get_sklearn_isotonic() -> Any:
    """Lazy-import sklearn.isotonic.IsotonicRegression.

    Raises:
        ImportError: If sklearn is not installed.
    """
    global _sklearn_import_error
    try:
        from sklearn.isotonic import IsotonicRegression
        return IsotonicRegression
    except ImportError as e:
        _sklearn_import_error = str(e)
        raise ImportError(
            "sklearn is required for VennAbersCalibrator fallback. "
            f"Install with: pip install scikit-learn. Original error: {e}"
        ) from e


def _get_venn_abers() -> Any:
    """Lazy-import venn_abers.VennAbers.

    Raises:
        ImportError: If venn_abers is not installed.
    """
    global _va_import_error
    try:
        from venn_abers import VennAbers  # type: ignore[import-untyped]
        return VennAbers
    except ImportError as e:
        _va_import_error = str(e)
        raise ImportError(
            "venn_abers is not installed. "
            f"Install with: pip install venn-abers. Original error: {e}"
        ) from e


def _is_venn_abers_available() -> bool:
    """Check if venn_abers can be imported (without raising)."""
    try:
        _get_venn_abers()
        return True
    except ImportError:
        return False


def _is_sklearn_available() -> bool:
    """Check if sklearn can be imported (without raising)."""
    try:
        _get_sklearn_isotonic()
        return True
    except ImportError:
        return False


class VennAbersCalibrator:
    """Calibrate shadow confidence scores using Venn-Abers predictors.

    Inductive conformal prediction framework:
    1. Split data into proper training set (for the underlying model) and
       calibration set (for the isotonic calibrator).
    2. Train an isotonic regression on (score, label) pairs from calibration.
    3. Apply to new scores to produce calibrated probabilities.

    Reference: Vovk, Gammerman, & Shafer (2005) "Algorithmic Learning in
    a Random World" and the venn-abers PyPI implementation.
    """

    def __init__(self):
        """Initialize with lazy-setup calibrator.

        Does NOT import sklearn or venn_abers at init time — only when
        calibrate() is first called. This allows the module to be imported
        without having either library installed.
        """
        self._calibrator: Any = None
        self._fitted = False
        self._using_venn_abers: bool | None = None  # None = not yet determined

    def _resolve_backend(self) -> str:
        """Determine which backend to use. Called lazily on first calibrate().

        Returns:
            "venn_abers" or "sklearn".

        Raises:
            RuntimeError: If neither backend is available.
        """
        if _is_venn_abers_available():
            logger.info("venn_abers library available; using VennAbers predictor")
            return "venn_abers"
        elif _is_sklearn_available():
            logger.info("venn_abers not found; using sklearn IsotonicRegression fallback")
            return "sklearn"
        else:
            raise RuntimeError(
                "Neither venn_abers nor sklearn is installed. "
                "Install one with: pip install venn-abers  OR  pip install scikit-learn"
            )

    def calibrate(
        self,
        scores: list[float],
        labels: list[int],
        calibration_scores: list[float] | None = None,
        calibration_labels: list[int] | None = None,
    ) -> list[float]:
        """Calibrate raw confidence scores into well-calibrated probabilities.

        When using the sklearn fallback: fits isotonic regression on
        (scores, labels) and applies it to scores. For inductive conformal
        prediction with a separate calibration set, pass calibration_scores
        and calibration_labels.

        When using venn_abers: uses the VennAbers library with scores/labels
        as training data and calibration data for inductive prediction.

        Args:
            scores: Raw confidence scores in [0, 1] for items to calibrate.
            labels: Binary labels {0, 1} for each score (1 = correct prediction).
            calibration_scores: Optional separate calibration set scores.
            calibration_labels: Optional separate calibration set labels.

        Returns:
            Calibrated probabilities in [0, 1] for each input score.
        """
        if not scores:
            return []

        # Resolve backend on first call
        if self._using_venn_abers is None:
            backend = self._resolve_backend()
            self._using_venn_abers = (backend == "venn_abers")

        scores_arr = np.asarray(scores, dtype=np.float64)
        labels_arr = np.asarray(labels, dtype=np.int64)

        if self._using_venn_abers:
            return self._venn_abers_calibrate(
                scores_arr, labels_arr,
                calibration_scores, calibration_labels,
            )
        else:
            return self._isotonic_calibrate(
                scores_arr, labels_arr,
                calibration_scores, calibration_labels,
            )

    def _venn_abers_calibrate(
        self,
        scores: np.ndarray,
        labels: np.ndarray,
        calibration_scores: list[float] | None,
        calibration_labels: list[int] | None,
    ) -> list[float]:
        """Use venn_abers library for inductive conformal calibration.

        The VennAbers predictor computes both the lower and upper probability
        bounds. We return the midpoint as the calibrated probability.
        """
        try:
            VennAbers = _get_venn_abers()

            if calibration_scores is not None and calibration_labels is not None:
                cal_scores = np.asarray(calibration_scores, dtype=np.float64)
                cal_labels = np.asarray(calibration_labels, dtype=np.int64)

                va = VennAbers()
                va.fit(scores, labels)
                p0, p1 = va.predict_proba(cal_scores)

                if p0.ndim == 2 and p1.ndim == 2:
                    calibrated = (p0[:, 1] + p1[:, 1]) / 2.0
                elif p0.ndim == 1 and p1.ndim == 1:
                    calibrated = (p0 + p1) / 2.0
                else:
                    calibrated = p1 if p1.ndim == 1 else p1[:, 1]
            else:
                va = VennAbers()
                va.fit(scores, labels)
                p0, p1 = va.predict_proba(scores)

                if p0.ndim == 2 and p1.ndim == 2:
                    calibrated = (p0[:, 1] + p1[:, 1]) / 2.0
                elif p0.ndim == 1 and p1.ndim == 1:
                    calibrated = (p0 + p1) / 2.0
                else:
                    calibrated = p1 if p1.ndim == 1 else p1[:, 1]

            return [round(float(max(0.0, min(1.0, v))), 6) for v in calibrated]

        except ImportError:
            logger.warning("venn_abers not available; falling back to isotonic")
            return self._isotonic_calibrate(
                scores, labels, calibration_scores, calibration_labels
            )
        except Exception as e:
            logger.warning(
                "venn_abers calibration failed: %s — falling back to isotonic", e
            )
            return self._isotonic_calibrate(
                scores, labels, calibration_scores, calibration_labels
            )

    def _isotonic_calibrate(
        self,
        scores: np.ndarray,
        labels: np.ndarray,
        calibration_scores: list[float] | None = None,
        calibration_labels: list[int] | None = None,
    ) -> list[float]:
        """Fallback: sklearn.isotonic.IsotonicRegression.

        If calibration data is provided, fits on calibration set and applies
        to scores. Otherwise fits on (scores, labels) and applies to same.

        Args:
            scores: Scores to calibrate.
            labels: Binary labels for each score.
            calibration_scores: Optional separate calibration set.
            calibration_labels: Optional separate calibration set labels.

        Returns:
            Calibrated probabilities in [0, 1].
        """
        IsotonicRegression = _get_sklearn_isotonic()

        if calibration_scores is not None and calibration_labels is not None:
            cal_scores = np.asarray(calibration_scores, dtype=np.float64)
            cal_labels = np.asarray(calibration_labels, dtype=np.int64)

            iso = IsotonicRegression(
                y_min=0.0, y_max=1.0, out_of_bounds="clip"
            )
            iso.fit(cal_scores, cal_labels)
            calibrated = iso.transform(scores)
        else:
            iso = IsotonicRegression(
                y_min=0.0, y_max=1.0, out_of_bounds="clip"
            )
            iso.fit(scores, labels)
            calibrated = iso.transform(scores)

        return [round(float(max(0.0, min(1.0, v))), 6) for v in calibrated]

    def calibrate_with_prior(
        self,
        scores: list[float],
        labels: list[int],
        prior_prob: float = 0.5,
    ) -> list[float]:
        """Calibrate with a base-rate prior for small-sample robustness.

        Blends the calibrated probability with the prior using a simple
        shrinkage estimator based on sample size. This prevents extreme
        calibrated values when working with very few samples.

        Args:
            scores: Raw confidence scores in [0, 1].
            labels: Binary labels {0, 1} for each score.
            prior_prob: Base-rate prior probability (default 0.5).

        Returns:
            Shrinkage-calibrated probabilities in [0, 1].
        """
        calibrated = self.calibrate(scores, labels)
        n = len(scores)

        if n == 0:
            return []

        # Shrinkage weight: small n -> more prior weight
        # Based on empirical Bayes: weight = n / (n + lambda), lambda = 10
        shrinkage_factor = n / (n + 10.0)

        result = []
        for cp in calibrated:
            shrunk = shrinkage_factor * cp + (1.0 - shrinkage_factor) * prior_prob
            result.append(round(float(max(0.0, min(1.0, shrunk))), 6))

        return result
