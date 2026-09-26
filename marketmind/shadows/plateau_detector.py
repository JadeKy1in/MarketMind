"""Plateau detection and reset eligibility for shadow ranking.

Extracted from ranking_engine.py per modular architecture rules (§3.1).
Handles: plateau detection (stagnation + WR stability + insight drought),
and reset eligibility (three-condition check for methodology baseline reset).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from marketmind.config.settings import ShadowSettings


class PlateauDetector:
    """Detects shadow performance plateaus and reset eligibility.

    Pure computation — no LLM calls. Uses config thresholds from ShadowSettings.
    """

    def __init__(self, config: ShadowSettings):
        self.config = config

    def detect_plateau(
        self,
        shadow_id: str,
        tier_history: list[tuple[str, str]],
        win_rate_history: list[tuple[str, float]],
        insight_dates: list[str],
    ) -> tuple[bool, float]:
        """Returns (is_plateaued, plateau_score) where higher score = more stale.

        Plateau weights: 0.5 stagnation + 0.3 wr_stability + 0.2 insight_drought
        """
        cfg = self.config

        # Minimum-age guard: new shadows (< plateau_no_elite_days snapshots) skip detection
        if len(tier_history) < cfg.plateau_no_elite_days:
            return False, 0.0
        scores = []

        # Stagnation: no elite in plateau_no_elite_days
        sorted_tiers = sorted(tier_history, key=lambda x: x[0], reverse=True)
        recent_tiers = [t for d, t in sorted_tiers[:cfg.plateau_no_elite_days]]
        no_elite = "elite" not in recent_tiers if recent_tiers else True
        scores.append(0.5 if no_elite else 0.0)

        # WR stability: range of win rates in recent history
        sorted_wr = sorted(win_rate_history, key=lambda x: x[0], reverse=True)
        recent_wr = [wr for _, wr in sorted_wr[:cfg.plateau_no_elite_days]]
        if len(recent_wr) >= 2:
            wr_range = max(recent_wr) - min(recent_wr)
            scores.append(0.3 * min(wr_range / cfg.plateau_wr_range_pp, 1.0))
        else:
            scores.append(0.0)

        # Insight drought
        if insight_dates:
            latest_insight = max(insight_dates)
            days_since = (datetime.now(timezone.utc).date() -
                          datetime.strptime(latest_insight, "%Y-%m-%d").date()).days
            drought = min(days_since / cfg.plateau_no_insight_days, 1.0)
        else:
            drought = 1.0
        scores.append(0.2 * drought)

        plateau_score = sum(scores)
        return plateau_score >= 0.5, plateau_score

    def check_reset_eligibility(
        self,
        tier_history: list[tuple[str, str]],     # (date, tier)
        wr_history: list[tuple[str, float]],      # (date, win_rate)
        insight_dates: list[str],                  # dates with insights
    ) -> tuple[bool, str]:
        """Check if a shadow should be reset to baseline methodology.

        Three conditions must ALL be met:
        1. No EXCELLENT or higher in reset_no_excellent_months
        2. Win rate fluctuation < ±5% for reset_flat_wr_months
        3. No insight produced in reset_no_insight_months

        Returns (should_reset, reason).
        """
        cfg = self.config
        today = datetime.now(timezone.utc).date()
        months_ago_6 = today - timedelta(days=cfg.reset_no_excellent_months * 30)
        months_ago_3 = today - timedelta(days=cfg.reset_flat_wr_months * 30)
        insight_cutoff = today - timedelta(days=cfg.reset_no_insight_months * 30)

        # Condition 1: No EXCELLENT in N months
        has_excellent = False
        for date_str, tier in tier_history:
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
                if d >= months_ago_6 and tier in ("excellent", "elite"):
                    has_excellent = True
                    break
            except ValueError:
                continue

        if has_excellent:
            return False, ""

        # Condition 2: WR flat for N months
        recent_wr = [
            wr for date_str, wr in wr_history
            if (d := datetime.strptime(date_str, "%Y-%m-%d").date()) and d >= months_ago_3
        ]
        if recent_wr and len(recent_wr) >= 5:
            wr_range = max(recent_wr) - min(recent_wr)
            if wr_range > 0.05:
                return False, ""

        # Condition 3: No insight in N months
        has_insight = any(
            datetime.strptime(d, "%Y-%m-%d").date() >= insight_cutoff
            for d in insight_dates
        )

        if not has_insight and (not recent_wr or len(recent_wr) < 5 or wr_range <= 0.05):
            return True, (
                f"No EXCELLENT tier in {cfg.reset_no_excellent_months} months, "
                f"WR range {max(recent_wr)-min(recent_wr):.2%} in "
                f"{cfg.reset_flat_wr_months} months, "
                f"no insight in {cfg.reset_no_insight_months} months"
            )

        return False, ""
