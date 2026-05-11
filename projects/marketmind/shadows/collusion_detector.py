"""Collusion Detector -- detects when shadows move in lockstep.

Detects:
- >=80% agreement for 3 consecutive days -> FLAG (binomial test P~4.4e-5)
- market_signal_strength > 0.70 -> "convergence" (market-driven)
- market_signal_strength <= 0.70 -> "herding" (behavioral)
- >=10 consecutive days -> escalate to institutional analysis
"""
from __future__ import annotations

import logging
import math
from statistics import mean

from projects.marketmind.shadows.shadow_state import CollusionFlag
from projects.marketmind.config.settings import ShadowSettings
from projects.marketmind.shadows.shadow_agent import ShadowVote

logger = logging.getLogger("marketmind.shadows.collusion_detector")


class CollusionDetector:
    """Detects collusion (lockstep movement) among shadow agents.

    Uses agreement rate tracking over consecutive days with binomial
    significance testing. Discriminates between market-driven convergence
    and behavioral herding using market signal strength analysis.
    """

    def __init__(self, settings: ShadowSettings):
        self.settings = settings
        # Track consecutive agreement days per ticker
        self._consecutive_days: dict[str, int] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def compute_agreement_rate(self, votes: list[ShadowVote],
                               ticker: str) -> dict[str, float]:
        """Compute agreement statistics for a single ticker across all shadows.

        Filters votes to the given ticker, then computes:
        - total_votes: count of all votes for the ticker
        - long_count, short_count, abstain_count
        - agreement_pct: % of non-abstaining votes in dominant direction
        - dominant_direction: "long", "short", or "abstain"

        Returns:
            Dict with keys: total_votes, long_count, short_count, abstain_count,
            agreement_pct, dominant_direction.
        """
        ticker_votes = [v for v in votes if v.ticker == ticker]

        long_count = sum(1 for v in ticker_votes if v.direction == "long")
        short_count = sum(1 for v in ticker_votes if v.direction == "short")
        abstain_count = sum(1 for v in ticker_votes if v.direction == "abstain")
        total = len(ticker_votes)

        # Agreement is measured among non-abstaining votes
        non_abstaining = long_count + short_count
        if non_abstaining == 0:
            agreement_pct = 0.0
            dominant_direction = "abstain"
        elif long_count >= short_count:
            agreement_pct = (long_count / non_abstaining) * 100.0
            dominant_direction = "long"
        else:
            agreement_pct = (short_count / non_abstaining) * 100.0
            dominant_direction = "short"

        return {
            "total_votes": total,
            "long_count": long_count,
            "short_count": short_count,
            "abstain_count": abstain_count,
            "agreement_pct": agreement_pct,
            "dominant_direction": dominant_direction,
        }

    def check_consecutive_flag(self,
                               agreement_history: list[float]) -> bool:
        """Check if agreement history shows >= threshold for >= N consecutive days.

        Args:
            agreement_history: List of agreement percentages for consecutive days
                              (most recent last).

        Returns:
            True if collusion should be flagged (>= threshold for >= N days).
        """
        threshold = self.settings.collusion_agreement_threshold * 100.0
        required_days = self.settings.collusion_consecutive_days_flag

        if len(agreement_history) < required_days:
            return False

        # Check the last N days
        recent = agreement_history[-required_days:]
        return all(pct >= threshold for pct in recent)

    def compute_market_signal_strength(self, ticker: str,
                                       market_data: dict) -> float:
        """Compute market signal strength (0.0-1.0) for a ticker.

        Uses weighted blend of:
        - price_trend_strength (weight: 0.4)
        - volume_confirmation (weight: 0.3)
        - news_sentiment_alignment (weight: 0.3)

        Returns 0.5 as neutral default if no data is available.
        """
        ticker_data = market_data.get(ticker, {})
        if not ticker_data:
            return 0.5

        price_trend = ticker_data.get("price_trend_strength", 0.5)
        volume_conf = ticker_data.get("volume_confirmation", 0.5)
        news_align = ticker_data.get("news_sentiment_alignment", 0.5)

        # Weighted blend
        strength = price_trend * 0.4 + volume_conf * 0.3 + news_align * 0.3
        return max(0.0, min(1.0, strength))

    def discriminate_convergence_vs_herding(self, agreement_pct: float,
                                            market_signal_strength: float,
                                            consecutive_days: int) -> str:
        """Classify lockstep agreement as 'convergence' or 'herding'.

        Args:
            agreement_pct: Percentage of shadows agreeing on direction.
            market_signal_strength: 0.0-1.0 signal strength from market data.
            consecutive_days: Number of consecutive days of high agreement.

        Returns:
            "convergence" if market_signal > threshold (market-driven),
            "herding" if market_signal <= threshold (behavioral),
            "pending_review" if agreement_pct is borderline.
        """
        threshold = self.settings.collusion_market_signal_threshold

        # Borderline case: agreement is right at threshold
        if agreement_pct < self.settings.collusion_agreement_threshold * 100.0:
            return "pending_review"

        if market_signal_strength > threshold:
            return "convergence"
        else:
            return "herding"

    def run_daily_check(self, date: str, votes: list[ShadowVote],
                        market_data: dict) -> list[CollusionFlag]:
        """Run the full daily collusion check across all tickers.

        Args:
            date: Date string (YYYY-MM-DD).
            votes: List of ShadowVote objects from all shadows.
            market_data: Dict keyed by ticker with market signal components.

        Returns:
            List of CollusionFlag objects for any detected collusion.
        """
        flags: list[CollusionFlag] = []

        # Find unique tickers in votes
        tickers = set(v.ticker for v in votes)
        if not tickers:
            return flags

        # For each ticker, compute agreement and check for collusion
        for ticker in sorted(tickers):
            stats = self.compute_agreement_rate(votes, ticker)
            agreement_pct = stats["agreement_pct"]

            # Update consecutive days tracker
            threshold = self.settings.collusion_agreement_threshold * 100.0
            prev_consecutive = self._consecutive_days.get(ticker, 0)

            if agreement_pct >= threshold:
                self._consecutive_days[ticker] = prev_consecutive + 1
                consecutive_days = prev_consecutive + 1
            else:
                # Reset if agreement drops below threshold
                self._consecutive_days[ticker] = 0
                consecutive_days = 0

            # Check if we should flag
            if consecutive_days < self.settings.collusion_consecutive_days_flag:
                continue

            # Compute market signal strength
            market_signal = self.compute_market_signal_strength(ticker, market_data)

            # Classify
            verdict = self.discriminate_convergence_vs_herding(
                agreement_pct, market_signal, consecutive_days
            )

            flag = CollusionFlag(
                date=date,
                agreement_pct=agreement_pct,
                consecutive_days=consecutive_days,
                market_signal_strength=market_signal,
                verdict=verdict,
            )

            # Escalate to institutional analysis if >= 10 days
            if consecutive_days >= self.settings.collusion_consecutive_days_audit:
                flag.user_action = "ESCALATE_TO_INSTITUTIONAL_ANALYSIS"
                logger.warning(
                    "COLLUSION ESCALATION: ticker=%s agreement=%.1f%% "
                    "consecutive_days=%d verdict=%s",
                    ticker, agreement_pct, consecutive_days, verdict,
                )

            flags.append(flag)
            logger.info(
                "Collusion flag: ticker=%s agreement=%.1f%% days=%d verdict=%s",
                ticker, agreement_pct, consecutive_days, verdict,
            )

        return flags

    # ── Binomial test (exposed for testing) ──────────────────────────────────

    def _binomial_test(self, n_agree: int, n_total: int,
                       null_prob: float = 0.5) -> float:
        """Compute one-sided binomial test p-value.

        Tests the null hypothesis that shadow agreement is random (50/50)
        against the alternative that agreement is higher than expected.

        P(X >= n_agree) for X ~ Binomial(n_total, null_prob).

        Args:
            n_agree: Number of shadows agreeing on the dominant direction.
            n_total: Total number of non-abstaining votes.
            null_prob: Null hypothesis probability (default 0.5 for binomial).

        Returns:
            Two-tailed p-value (doubled one-sided for conservatism).
        """
        n_agree = min(n_agree, n_total)  # sanity check

        # Compute P(X >= n_agree) = sum_{k=n_agree}^{n_total} C(n,k) * p^k * (1-p)^(n-k)
        p_value = 0.0
        for k in range(n_agree, n_total + 1):
            # Binomial coefficient: C(n,k) = n!/(k!(n-k)!)
            log_prob = (
                math.lgamma(n_total + 1)
                - math.lgamma(k + 1)
                - math.lgamma(n_total - k + 1)
                + k * math.log(null_prob)
                + (n_total - k) * math.log(1.0 - null_prob)
            )
            p_value += math.exp(log_prob)

        # Return two-tailed for conservatism (multiply by 2)
        two_tailed = min(1.0, p_value * 2.0)
        return two_tailed
