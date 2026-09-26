"""Ecosystem Health Monitor — collective degradation detection (Phase 3, Item 12).

Three system-level signals that detect when the ENTIRE shadow ecosystem is
degrading (not just individual shadows):
1. Vote entropy classifier (Pattern Matcher / Balanced / Explorer)
2. Relative token efficiency trend (Mann-Kendall)
3. Plateau ratio from tightened thresholds

All signals are pure Python compute, zero LLM calls.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.shadows.ecosystem_health")


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class ShadowProfile:
    """Monthly behavioral profile for one shadow."""
    shadow_id: str
    month: str
    avg_entropy: float         # vote direction entropy (0-1.58 bits)
    profile: str               # "pattern_matcher" | "balanced" | "explorer"
    avg_tokens_per_decision: float
    token_trend: str           # "decreasing" | "stable" | "increasing"


@dataclass
class EcosystemHealthSnapshot:
    """Daily ecosystem health summary."""
    date: str
    active_shadows: int = 0
    pattern_matcher_pct: float = 0.0
    balanced_pct: float = 0.0
    explorer_pct: float = 0.0
    avg_entropy: float = 0.0
    collusion_flag_count: int = 0
    token_trend_increasing_pct: float = 0.0
    alerts: list[str] = field(default_factory=list)


# ── Vote entropy ─────────────────────────────────────────────────────────────

class EcosystemHealthMonitor:
    """Daily ecosystem-level health checks."""

    # Entropy classification thresholds
    ENTROPY_PATTERN_MATCHER = 0.2    # 0.0-0.2: mechanical voting
    ENTROPY_EXPLORER = 1.2           # 1.2-1.58: genuine diverse reasoning

    # Alert thresholds
    PATTERN_MATCHER_ALERT_RATIO = 0.30   # >30% of shadows are pattern matchers
    TOKEN_TREND_ALERT_DAYS = 30          # 30-day window for trend test

    def __init__(self):
        self._daily_entropies: dict[str, list[float]] = {}

    # ── Vote entropy ─────────────────────────────────────────────────────

    def compute_vote_entropy(self, votes: list) -> dict[str, float]:
        """Compute per-shadow vote direction entropy for today.

        Returns {shadow_id: entropy_bits}.
        """
        from collections import defaultdict
        shadow_votes: dict[str, list[str]] = defaultdict(list)
        for v in votes:
            if hasattr(v, 'direction') and v.direction != "abstain":
                shadow_votes[v.shadow_id].append(v.direction)

        entropies = {}
        for sid, directions in shadow_votes.items():
            entropies[sid] = self._entropy(directions)
        return entropies

    @staticmethod
    def _entropy(directions: list[str]) -> float:
        """Shannon entropy of vote directions. Range [0, log2(3)] ≈ [0, 1.58]."""
        if not directions:
            return 0.0
        n = len(directions)
        counts = Counter(directions)
        entropy = 0.0
        for count in counts.values():
            p = count / n
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def classify_profile(self, entropy: float) -> str:
        """Classify a shadow based on vote entropy."""
        if entropy <= self.ENTROPY_PATTERN_MATCHER:
            return "pattern_matcher"
        elif entropy >= self.ENTROPY_EXPLORER:
            return "explorer"
        return "balanced"

    def compute_ecosystem_profile(self, entropies: dict[str, float]) -> dict:
        """Aggregate profile ratios across the ecosystem."""
        if not entropies:
            return {"pattern_matcher_pct": 0.0, "balanced_pct": 0.0, "explorer_pct": 0.0}

        total = len(entropies)
        profiles = [self.classify_profile(e) for e in entropies.values()]
        counts = Counter(profiles)
        return {
            "pattern_matcher_pct": counts.get("pattern_matcher", 0) / total,
            "balanced_pct": counts.get("balanced", 0) / total,
            "explorer_pct": counts.get("explorer", 0) / total,
        }

    # ── Token efficiency trend ───────────────────────────────────────────

    @staticmethod
    def compute_token_trend(token_history: list[int]) -> tuple[str, float]:
        """Mann-Kendall trend test on 30-day token history.

        Returns (trend_direction, tau_correlation).
        trend_direction: "increasing" | "stable" | "decreasing"
        """
        if len(token_history) < 10:
            return "stable", 0.0

        n = len(token_history)
        s = 0
        for i in range(n - 1):
            for j in range(i + 1, n):
                diff = token_history[j] - token_history[i]
                if diff > 0:
                    s += 1
                elif diff < 0:
                    s -= 1

        # Kendall's tau
        denom = n * (n - 1) / 2
        tau = s / denom if denom > 0 else 0.0

        if tau > 0.3:
            return "increasing", tau
        elif tau < -0.3:
            return "decreasing", tau
        return "stable", tau

    # ── Full daily check ─────────────────────────────────────────────────

    def run_daily_check(
        self, votes: list, token_data: dict[str, list[int]], date: str | None = None
    ) -> EcosystemHealthSnapshot:
        """Run all ecosystem-level checks and produce a health snapshot."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        entropies = self.compute_vote_entropy(votes)
        profiles = self.compute_ecosystem_profile(entropies)

        snapshot = EcosystemHealthSnapshot(
            date=date,
            active_shadows=len(entropies),
            pattern_matcher_pct=profiles["pattern_matcher_pct"],
            balanced_pct=profiles["balanced_pct"],
            explorer_pct=profiles["explorer_pct"],
            avg_entropy=sum(entropies.values()) / max(len(entropies), 1),
        )

        alerts = []

        # Alert: too many pattern matchers
        if profiles["pattern_matcher_pct"] >= self.PATTERN_MATCHER_ALERT_RATIO:
            alerts.append(
                f"ECOSYSTEM CONVERGENCE: {profiles['pattern_matcher_pct']:.0%} "
                f"of shadows are Pattern Matchers (mechanical voting)"
            )

        # Token trend per shadow
        increasing_count = 0
        for sid, tokens in token_data.items():
            trend, _ = self.compute_token_trend(tokens)
            if trend == "increasing":
                increasing_count += 1

        if token_data:
            snapshot.token_trend_increasing_pct = increasing_count / len(token_data)
            if snapshot.token_trend_increasing_pct >= 0.50:
                alerts.append(
                    f"TOKEN INFLATION: {snapshot.token_trend_increasing_pct:.0%} "
                    f"of shadows using more tokens without improvement"
                )

        snapshot.alerts = alerts
        return snapshot
