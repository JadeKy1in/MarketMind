"""Event study runner — statistical validation of figure signal impact.

Pure Python, zero LLM. Computes abnormal returns around figure events.
Phase 1: daily frequency only. Phase 3: intraday [0, +30min] window.

Based on standard event study methodology (MacKinlay 1997).
Design: docs/dev/plans/market-figure-intelligence-module.md §6
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class EventStudyResult:
    """Result of a single event study run.

    Attributes:
        person_name: The market figure's name.
        event_date: ISO-format date string of the event.
        event_type: One of 'speech', 'trade', 'filing', 'social_post'.
        ar_daily: Abnormal return on the event day (decimal, e.g. 0.0025 = 25 bp).
        car_2day: Cumulative abnormal return over [0, +1] window.
        is_significant: True when |AR| > 2 * sigma_estimation.
        avg_historical_ar: Mean absolute AR from past events (or 0.0).
        direction_match: True when AR sign matches the signal's stated direction.
    """

    person_name: str = ""
    event_date: str = ""
    event_type: str = ""
    ar_daily: float = 0.0
    car_2day: float = 0.0
    is_significant: bool = False
    avg_historical_ar: float = 0.0
    direction_match: bool = False


class EventStudyRunner:
    """Run event studies on figure signals.

    Market model: CAPM (default). Optional FF3/FF5 for Phase 2.
    Estimation window: [-120, -20] days before event.
    Event window: day 0 and [+0, +1] for CAR.

    Usage:
        runner = EventStudyRunner()
        result = runner.run(signal, price_data, market_returns)
    """

    # Minimum number of observations in the estimation window before
    # the OLS regression is considered reliable.
    _MIN_ESTIMATION_POINTS: int = 20

    # Range of the estimation window relative to the event return index.
    # [-120, -20] means we use returns from event_idx - 120 through
    # event_idx - 20 (inclusive start, exclusive end in Python slicing).
    _ESTIMATION_START: int = -120
    _ESTIMATION_END: int = -20

    def __init__(self, market_model: str = "capm") -> None:
        """Initialise the runner.

        Args:
            market_model: 'capm' (default), 'ff3', or 'ff5'.
                          Only 'capm' is implemented in Phase 1.
        """
        self.market_model = market_model

    # ── Main entry point ────────────────────────────────────────────────

    def run(
        self,
        signal,  # dict | FigureSignal
        price_data: dict[str, list[float]],
        market_returns: list[float],
    ) -> EventStudyResult:
        """Run event study for one figure signal.

        Args:
            signal: Dict or object with keys/attrs:
                - event_date (str): ISO date of the event.
                - direction (str | None): 'long', 'short', or 'warn'.
                - person_name (str): Name of the market figure.
                - event_type (str): Event classification.
            price_data: dict with:
                - 'close': list of daily close prices (oldest first).
                - 'dates' (optional): list of ISO date strings aligned
                  to 'close'.
            market_returns: List of benchmark (SPY) daily log returns,
                            aligned to the *returns* derived from 'close'.
                            Length = len(close) - 1.

        Returns:
            EventStudyResult with AR, CAR, significance test, and
            direction match.
        """
        # ── 1. Unpack signal ────────────────────────────────────────
        event_date = self._get_attr(signal, "event_date", "")
        direction = self._get_attr(signal, "direction", None)
        person_name = self._get_attr(signal, "person_name", "")
        event_type = self._get_attr(signal, "event_type", "")

        # ── 2. Compute asset returns ────────────────────────────────
        closes = price_data.get("close", [])
        dates = price_data.get("dates", [])

        asset_returns = self._compute_log_returns(closes)
        n_returns = len(asset_returns)

        # ── 3. Locate event index ───────────────────────────────────
        event_return_idx = self._find_event_index(
            event_date, dates, n_returns
        )

        # ── 4. Validate data sufficiency ────────────────────────────
        if (
            event_return_idx is None
            or n_returns < self._MIN_ESTIMATION_POINTS + 1
        ):
            return EventStudyResult(
                person_name=person_name,
                event_date=event_date,
                event_type=event_type,
            )

        # Align market_returns — must be same length as asset_returns.
        mr = market_returns
        if len(mr) != n_returns:
            # Truncate or pad to match.
            mr = mr[:n_returns] if len(mr) > n_returns else mr

        # ── 5. Estimation window ────────────────────────────────────
        est_start = event_return_idx + self._ESTIMATION_START
        est_end = event_return_idx + self._ESTIMATION_END

        if est_start < 0 or est_end <= est_start:
            return EventStudyResult(
                person_name=person_name,
                event_date=event_date,
                event_type=event_type,
            )

        est_asset = asset_returns[est_start:est_end]
        est_market = mr[est_start:est_end]

        if len(est_asset) < self._MIN_ESTIMATION_POINTS:
            return EventStudyResult(
                person_name=person_name,
                event_date=event_date,
                event_type=event_type,
            )

        # ── 6. Estimate market model ────────────────────────────────
        alpha, beta = self._estimate_market_model(est_asset, est_market)
        sigma = self._compute_regression_sigma(
            est_asset, est_market, alpha, beta
        )

        # ── 7. Event-day abnormal return ────────────────────────────
        if event_return_idx >= len(asset_returns):
            return EventStudyResult(
                person_name=person_name,
                event_date=event_date,
                event_type=event_type,
            )

        ar_daily = self._compute_abnormal_return(
            asset_returns[event_return_idx],
            mr[event_return_idx] if event_return_idx < len(mr) else 0.0,
            alpha,
            beta,
        )

        # ── 8. CAR [0, +1] ──────────────────────────────────────────
        car_2day = ar_daily
        if event_return_idx + 1 < len(asset_returns):
            ar_t1 = self._compute_abnormal_return(
                asset_returns[event_return_idx + 1],
                (
                    mr[event_return_idx + 1]
                    if event_return_idx + 1 < len(mr)
                    else 0.0
                ),
                alpha,
                beta,
            )
            car_2day += ar_t1

        # ── 9. Significance test ────────────────────────────────────
        is_significant = abs(ar_daily) > 2.0 * sigma if sigma > 0 else False

        # ── 10. Direction match ─────────────────────────────────────
        direction_match = self._check_direction_match(ar_daily, direction)

        return EventStudyResult(
            person_name=person_name,
            event_date=event_date,
            event_type=event_type,
            ar_daily=round(ar_daily, 6),
            car_2day=round(car_2day, 6),
            is_significant=is_significant,
            direction_match=direction_match,
        )

    # ── Core computations ───────────────────────────────────────────────

    def _compute_abnormal_return(
        self,
        asset_return: float,
        market_return: float,
        alpha: float,
        beta: float,
    ) -> float:
        """AR = R_asset - (alpha + beta * R_market)"""
        expected = alpha + beta * market_return
        return asset_return - expected

    def _estimate_market_model(
        self,
        returns: list[float],
        market_returns: list[float],
    ) -> tuple[float, float]:
        """OLS regression: R_asset = alpha + beta * R_market + epsilon

        Returns:
            (alpha, beta) tuple.
        """
        n = len(returns)
        if n < 2:
            return 0.0, 1.0

        mean_r = sum(returns) / n
        mean_m = sum(market_returns) / n

        # Cov(R_asset, R_market) and Var(R_market) — population formulae.
        cov = 0.0
        var_m = 0.0
        for i in range(n):
            d_r = returns[i] - mean_r
            d_m = market_returns[i] - mean_m
            cov += d_r * d_m
            var_m += d_m * d_m

        if var_m == 0.0:
            return mean_r, 0.0

        beta = cov / var_m
        alpha = mean_r - beta * mean_m
        return alpha, beta

    def _compute_regression_sigma(
        self,
        returns: list[float],
        market_returns: list[float],
        alpha: float,
        beta: float,
    ) -> float:
        """Standard error of the market-model regression.

        sigma = sqrt( SSR / (n - 2) )
        where SSR = sum of squared residuals.
        """
        n = len(returns)
        if n <= 2:
            return 0.01  # sensible default

        ssr = 0.0
        for i in range(n):
            predicted = alpha + beta * market_returns[i]
            residual = returns[i] - predicted
            ssr += residual * residual

        variance = ssr / (n - 2)
        return math.sqrt(variance) if variance > 0 else 0.0001

    # ── Historical accuracy ─────────────────────────────────────────────

    @staticmethod
    def update_historical_accuracy(
        person_name: str,
        results: list[EventStudyResult],
    ) -> dict:
        """Compute rolling accuracy: % of events where direction matches AR sign.

        Args:
            person_name: Name of the figure (unused in computation; reserved
                         for future per-person calibration).
            results: List of past EventStudyResult objects.

        Returns:
            dict with keys 'accuracy' (float) and 'n' (int).
        """
        if not results:
            return {"accuracy": 0.50, "n": 0}

        n = len(results)
        matches = sum(1 for r in results if r.direction_match)
        accuracy = matches / n
        return {"accuracy": round(accuracy, 4), "n": n}

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _compute_log_returns(prices: list[float]) -> list[float]:
        """Compute log returns from a price series (oldest first)."""
        if len(prices) < 2:
            return []
        rets: list[float] = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0 and prices[i] > 0:
                rets.append(math.log(prices[i] / prices[i - 1]))
            else:
                rets.append(0.0)
        return rets

    @staticmethod
    def _find_event_index(
        event_date: str,
        dates: list[str],
        n_returns: int,
    ) -> int | None:
        """Locate the event return index within the returns array.

        The return at index *i* is the return from close[i] → close[i+1].
        The *event* return is the one whose period ends on the event date,
        i.e. from close[event_idx - 1] to close[event_idx].

        If dates are provided we look up the exact index; otherwise we
        assume the last return is the event return.
        """
        if dates and event_date:
            # Find the price index of the event date.
            try:
                price_idx = dates.index(event_date)
            except ValueError:
                # Try stripping time portion if present.
                for i, d in enumerate(dates):
                    if d.startswith(event_date):
                        price_idx = i
                        break
                else:
                    return None
            # The return whose period ends on event_date is at
            # price_idx - 1 in the returns array.
            ret_idx = price_idx - 1
            if 0 <= ret_idx < n_returns:
                return ret_idx
            return None

        # Fallback: use the last return as the event.
        if n_returns > 0:
            return n_returns - 1
        return None

    @staticmethod
    def _check_direction_match(ar: float, direction: str | None) -> bool:
        """Return True when the AR sign matches the signal direction.

        - 'long'  → AR > 0  (positive surprise confirms bullish signal)
        - 'short' → AR < 0  (negative surprise confirms bearish signal)
        - 'warn' / None → always False (no clear directional expectation)
        """
        if direction == "long":
            return ar > 0
        if direction == "short":
            return ar < 0
        return False

    @staticmethod
    def _get_attr(obj, key: str, default=None):
        """Safe attribute / key access for dict-like and object-like signals."""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
