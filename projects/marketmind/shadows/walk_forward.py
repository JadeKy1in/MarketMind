"""Walk-Forward Validation (P2-2) — IS-WFA-OOS protocol for shadow overfitting detection.

Detects overfitting by comparing in-sample vs out-of-sample performance
across rolling time windows. Based on AlgoXpert IS-WFA-OOS protocol
(Pham, Mar 2026) and HypoDriven framework (Deep et al., Dec 2025).

Zero LLM calls. All computation is deterministic mathematical formulas.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger("marketmind.shadows.walk_forward")


@dataclass
class WalkForwardResult:
    """Result of walk-forward validation for a single shadow."""
    shadow_id: str
    is_overfit: bool
    wfe_ratio: float
    is_signals: list[float] = field(default_factory=list)
    oos_signals: list[float] = field(default_factory=list)
    binomial_p_value: float = 1.0
    career_days: int = 0
    skipped: bool = False
    skip_reason: str = ""


class WalkForwardValidator:
    """Walk-forward validation for shadow strategy evaluation.

    Detects overfitting by comparing in-sample vs out-of-sample performance
    across rolling time windows. Based on AlgoXpert IS-WFA-OOS protocol
    (Pham, Mar 2026) and HypoDriven framework (Deep et al., Dec 2025).

    WFE ratio < 0.5 flags overfitting.
    """

    _MIN_CAREER_DAYS = 120
    _IS_NEAR_ZERO_THRESHOLD = 0.001
    _WFE_OVERFIT_THRESHOLD = 0.5

    def __init__(self, train_days: int = 90, purge_days: int = 2,
                 test_days: int = 20):
        self.train_days = train_days
        self.purge_days = purge_days
        self.test_days = test_days

    @property
    def min_career_days(self) -> int:
        return self._MIN_CAREER_DAYS

    def validate(self, shadow_id: str,
                 daily_snapshots: list) -> WalkForwardResult:
        career_days = len(daily_snapshots)

        if career_days < self._MIN_CAREER_DAYS:
            return WalkForwardResult(
                shadow_id=shadow_id, skipped=True,
                skip_reason=f"Insufficient career days: {career_days} < {self._MIN_CAREER_DAYS}",
                career_days=career_days,
            )

        sorted_snaps = sorted(daily_snapshots, key=lambda s: s.date)
        window_size = self.train_days + self.purge_days + self.test_days
        all_is_signals: list[float] = []
        all_oos_signals: list[float] = []
        oos_correct = 0
        oos_total = 0

        start_idx = 0
        while start_idx + window_size <= career_days:
            train_end = start_idx + self.train_days
            purge_end = train_end + self.purge_days
            test_end = purge_end + self.test_days

            is_win = sorted_snaps[start_idx:train_end]
            oos_win = sorted_snaps[purge_end:test_end]

            is_sig = self._compute_deflated_signals(is_win)
            oos_sig = self._compute_deflated_signals(oos_win)

            if is_sig and oos_sig:
                all_is_signals.extend(is_sig)
                all_oos_signals.extend(oos_sig)

            for snap in oos_win:
                ret = snap.daily_return_pct
                if ret is not None:
                    oos_total += 1
                    if ret > 0:
                        oos_correct += 1

            start_idx += self.test_days

        if not all_is_signals or not all_oos_signals:
            return WalkForwardResult(
                shadow_id=shadow_id, skipped=True,
                skip_reason="No valid signal windows",
                career_days=career_days,
            )

        is_mean = sum(all_is_signals) / len(all_is_signals)

        if abs(is_mean) <= self._IS_NEAR_ZERO_THRESHOLD:
            return WalkForwardResult(
                shadow_id=shadow_id, skipped=True,
                skip_reason=f"IS deflated near zero: {is_mean:.6f}",
                is_signals=all_is_signals, oos_signals=all_oos_signals,
                career_days=career_days,
            )

        oos_mean = sum(all_oos_signals) / len(all_oos_signals)
        wfe_ratio = oos_mean / is_mean if is_mean != 0 else 1.0
        is_overfit = wfe_ratio < self._WFE_OVERFIT_THRESHOLD
        binomial_p = self._binomial_p_value(oos_correct, oos_total)

        return WalkForwardResult(
            shadow_id=shadow_id, is_overfit=is_overfit,
            wfe_ratio=wfe_ratio,
            is_signals=all_is_signals, oos_signals=all_oos_signals,
            binomial_p_value=binomial_p, career_days=career_days,
        )

    @staticmethod
    def _compute_deflated_signals(snapshots: list) -> list[float]:
        signals = []
        for snap in snapshots:
            if snap.deflated_score is not None:
                signals.append(snap.deflated_score)
            elif snap.cumulative_return_pct is not None:
                signals.append(snap.cumulative_return_pct)
            else:
                signals.append(0.0)
        return signals

    @staticmethod
    def _binomial_p_value(k: int, n: int) -> float:
        if n == 0:
            return 1.0
        expected = n * 0.5
        if k <= expected:
            p = sum(math.comb(n, i) * (0.5 ** n) for i in range(k + 1))
        else:
            p = sum(math.comb(n, i) * (0.5 ** n) for i in range(k, n + 1))
        return min(p * 2.0, 1.0)
