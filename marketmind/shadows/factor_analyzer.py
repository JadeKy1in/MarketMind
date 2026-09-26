"""Factor exposure analysis for shadow strategies.

Pure Python, zero LLM. Computes Carhart 4-factor regression,
detects style drift, and classifies strategies by factor archetype.

Phase E Module 1 — Integration layer.
"""
from __future__ import annotations

import logging
import math
from statistics import mean, stdev
from typing import Optional

import numpy as np

logger = logging.getLogger("marketmind.shadows.factor_analyzer")

# ── Strategy archetype thresholds ─────────────────────────────────────────
_MOMENTUM_THRESHOLD = 0.05
_VALUE_THRESHOLD = -0.05
_SIZE_THRESHOLD = 0.03
_MARKET_BETA_NEUTRAL = 0.30


class FactorAnalyzer:
    """Analyze shadow factor exposures for style drift and strategy classification.

    All methods are @staticmethod — this is a pure computation class with no state.
    """

    @staticmethod
    def compute_carhart_alpha(
        returns: list[float],
        mkt_returns: list[float],
        smb: list[float],
        hml: list[float],
        mom: list[float],
    ) -> dict:
        """Carhart 4-factor regression.

        Regresses excess returns on market, size (SMB), value (HML),
        and momentum (MOM) factors, returning alpha, betas, and t-statistics.

        Args:
            returns: List of excess returns for the strategy/portfolio.
            mkt_returns: Market factor (Rm - Rf) time series.
            smb: Size factor (Small Minus Big) time series.
            hml: Value factor (High Minus Low) time series.
            mom: Momentum factor (Winners Minus Losers) time series.

        Returns:
            Dict with keys: alpha, alpha_tstat, beta_mkt, beta_mkt_tstat,
            beta_smb, beta_smb_tstat, beta_hml, beta_hml_tstat,
            beta_mom, beta_mom_tstat, r_squared, adj_r_squared, n_obs.

        Raises:
            ValueError: If all input lists are not the same length, or n < 6.
        """
        n = len(returns)
        lengths = [len(mkt_returns), len(smb), len(hml), len(mom)]
        if any(l != n for l in lengths):
            raise ValueError(
                f"All input arrays must have the same length. "
                f"Got returns={n}, mkt={len(mkt_returns)}, smb={len(smb)}, "
                f"hml={len(hml)}, mom={len(mom)}"
            )
        if n < 6:
            raise ValueError(f"Need at least 6 observations for 4-factor regression, got {n}")

        # Build design matrix: [intercept, mkt, smb, hml, mom]
        X = np.column_stack([
            np.ones(n),
            np.array(mkt_returns),
            np.array(smb),
            np.array(hml),
            np.array(mom),
        ])
        y = np.array(returns)

        # OLS via least squares
        coeffs, residuals, rank, singulars = np.linalg.lstsq(X, y, rcond=None)
        alpha, beta_mkt, beta_smb, beta_hml, beta_mom = coeffs

        # Residuals
        y_pred = X @ coeffs
        resid = y - y_pred
        ss_resid = float(np.sum(resid ** 2))
        ss_total = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - (ss_resid / ss_total) if ss_total > 0 else 0.0

        # Adjusted R-squared: 1 - (1-R^2)*(n-1)/(n-k-1), k=4 factors
        adj_r_squared = 1.0 - (1.0 - r_squared) * (n - 1) / (n - 5) if n > 5 else r_squared

        # Standard errors and t-stats
        # Var(beta) = sigma^2 * (X'X)^-1, sigma^2 = SSR / (n - k - 1)
        dof = n - 5
        sigma2 = ss_resid / dof if dof > 0 else 0.0
        try:
            cov_matrix = np.linalg.inv(X.T @ X) * sigma2
            se = np.sqrt(np.diag(cov_matrix))
        except np.linalg.LinAlgError:
            se = np.array([float('nan')] * 5)

        def _tstat(coef: float, se_val: float) -> float:
            return coef / se_val if se_val > 0 else float('nan')

        return {
            "alpha": round(float(alpha), 6),
            "alpha_tstat": round(_tstat(float(alpha), float(se[0])), 4),
            "beta_mkt": round(float(beta_mkt), 6),
            "beta_mkt_tstat": round(_tstat(float(beta_mkt), float(se[1])), 4),
            "beta_smb": round(float(beta_smb), 6),
            "beta_smb_tstat": round(_tstat(float(beta_smb), float(se[2])), 4),
            "beta_hml": round(float(beta_hml), 6),
            "beta_hml_tstat": round(_tstat(float(beta_hml), float(se[3])), 4),
            "beta_mom": round(float(beta_mom), 6),
            "beta_mom_tstat": round(_tstat(float(beta_mom), float(se[4])), 4),
            "r_squared": round(r_squared, 4),
            "adj_r_squared": round(adj_r_squared, 4),
            "n_obs": n,
        }

    @staticmethod
    def detect_style_drift(
        factor_exposures: list[dict],
        window: int = 3,
    ) -> bool:
        """Detect style drift: monthly factor exposure change > 2σ for 3 consecutive months.

        Checks each factor (mkt, smb, hml, mom) independently. If any single
        factor shows abnormal change (> 2σ) in each of the last `window` months,
        style drift is flagged.

        Args:
            factor_exposures: List of monthly exposure dicts, each with keys
                              'beta_mkt', 'beta_smb', 'beta_hml', 'beta_mom'.
                              Ordered chronologically (oldest first).
            window: Number of consecutive months to check (default 3).

        Returns:
            True if style drift detected (any factor exceeds 2σ for N consecutive months),
            False otherwise.
        """
        if len(factor_exposures) < window + 1:
            return False

        factor_keys = ["beta_mkt", "beta_smb", "beta_hml", "beta_mom"]

        for key in factor_keys:
            # Extract the time series of this factor's exposures
            series = [e.get(key, 0.0) for e in factor_exposures]
            if len(series) < window + 1:
                continue

            # Compute month-over-month changes
            diffs = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]

            # Compute mean and std of the full change history
            if len(diffs) < 2:
                continue
            mu = mean(diffs)
            sigma = stdev(diffs) if len(diffs) >= 2 else 0.0
            if sigma == 0.0:
                continue

            # Check the last `window` changes
            recent = diffs[-window:]
            if all(abs(d - mu) / sigma > 2.0 for d in recent):
                logger.warning(
                    "Style drift detected for factor=%s: last %d monthly changes "
                    "all exceed 2σ (μ=%.4f, σ=%.4f, recent=%s)",
                    key, window, mu, sigma, [round(d, 4) for d in recent],
                )
                return True

        return False

    @staticmethod
    def classify_strategy(factor_exposures: dict) -> str:
        """Map factor exposures to strategy archetype.

        Uses factor loadings to determine the dominant strategy style.

        | Archetype         | Criteria                                          |
        |-------------------|---------------------------------------------------|
        | Momentum          | beta_mom > 0.05, |beta_mom| dominates other factors|
        | Value             | beta_hml < -0.05                                  |
        | Growth            | beta_hml > 0.05                                   |
        | Small-Cap         | beta_smb > 0.03, beta_mkt near 1                 |
        | Large-Cap         | beta_smb < -0.03, beta_mkt near 1                |
        | Market Neutral    | abs(beta_mkt) < 0.30                             |
        | High Beta         | beta_mkt > 1.20                                   |
        | Low Beta          | beta_mkt < 0.70                                   |
        | Balanced          | default fallback                                  |

        Args:
            factor_exposures: Dict with keys 'beta_mkt', 'beta_smb', 'beta_hml', 'beta_mom'.

        Returns:
            Strategy archetype string (one of the 9 types above).
        """
        beta_mkt = factor_exposures.get("beta_mkt", 1.0)
        beta_smb = factor_exposures.get("beta_smb", 0.0)
        beta_hml = factor_exposures.get("beta_hml", 0.0)
        beta_mom = factor_exposures.get("beta_mom", 0.0)

        # Check market neutrality first (strongest classification signal)
        if abs(beta_mkt) < _MARKET_BETA_NEUTRAL:
            return "Market Neutral"

        # Momentum-dominated
        if abs(beta_mom) > _MOMENTUM_THRESHOLD and abs(beta_mom) > max(
            abs(beta_smb), abs(beta_hml)
        ):
            return "Momentum"

        # Value / Growth
        if beta_hml < _VALUE_THRESHOLD:
            return "Value"
        if beta_hml > -_VALUE_THRESHOLD:
            return "Growth"

        # Size tilt
        if beta_smb > _SIZE_THRESHOLD:
            return "Small-Cap"
        if beta_smb < -_SIZE_THRESHOLD:
            return "Large-Cap"

        # Market beta extremes
        if beta_mkt > 1.20:
            return "High Beta"
        if beta_mkt < 0.70:
            return "Low Beta"

        return "Balanced"
