"""Shadow Health Monitor — individual shadow degradation detection (Phase 3, Item 11).

Three daily checks per shadow (pure Python, zero LLM calls):
- Check C: Insight production rate (7-day drought = alert)
- Check A: Semantic drift from methodology prompt (cohort-relative)
- Check B: Reasoning chain quality (causal density + hedge ratio, corroborator only)
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("marketmind.shadows.shadow_health_monitor")


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class ShadowHealthSnapshot:
    shadow_id: str
    date: str
    insight_drought_days: int = 0
    has_insight_drought: bool = False
    reasoning_quality: float = 1.0      # [0, 1], 1=healthy
    causal_density: float = 0.0
    hedge_ratio: float = 0.0
    alerts: list[str] = field(default_factory=list)


# ── Health Monitor ───────────────────────────────────────────────────────────

class ShadowHealthMonitor:
    """Daily per-shadow health checks."""

    INSIGHT_DROUGHT_DAYS = 7
    CAUSAL_CONNECTIVES = {"because", "therefore", "thus", "hence", "since",
                          "as a result", "consequently", "due to", "leads to",
                          "drives", "implies", "indicates"}
    HEDGE_WORDS = {"maybe", "perhaps", "could", "might", "possibly",
                   "uncertain", "unclear", "however", "but", "although",
                   "unless", "risk", "caution", "potentially"}

    def __init__(self, state_db=None):
        self._state_db = state_db  # for DB-backed drought tracking

    def check_insight_drought(self, shadow_id: str, insight_count: int,
                              date: str) -> tuple[bool, int]:
        """Check C: consecutive days without insights.

        Uses DB-backed counting (survives process restart).

        Returns (is_drought_alert, drought_days).
        """
        if self._state_db:
            # DB-backed: count consecutive recent days with 0 insights
            drought_days = self._state_db.count_consecutive_zero_insights(
                shadow_id, self.INSIGHT_DROUGHT_DAYS + 1
            )
        else:
            # Fallback: in-memory (for testing)
            if not hasattr(self, '_drought_tracker'):
                self._drought_tracker: dict[str, int] = defaultdict(int)
            if insight_count == 0:
                self._drought_tracker[shadow_id] += 1
            else:
                self._drought_tracker[shadow_id] = 0
            drought_days = self._drought_tracker[shadow_id]

        return drought_days >= self.INSIGHT_DROUGHT_DAYS, drought_days

    def check_reasoning_quality(self, raw_text: str) -> dict:
        """Check B: measure causal density and hedge ratio.

        Returns dict with causal_density, hedge_ratio, quality_score.
        Quality score = 1.0 when causal density is high and hedge ratio is moderate.
        """
        if not raw_text or len(raw_text) < 50:
            return {"causal_density": 0.0, "hedge_ratio": 0.0, "quality_score": 0.5}

        text_lower = raw_text.lower()
        # Strip punctuation from each word for accurate matching
        words = [w.strip(".,;:!?()[]\"'-") for w in text_lower.split()]
        word_count = max(len(words), 1)

        # Single-pass: count multi-word phrases via regex, single words via set
        causal_count = 0
        for phrase in self.CAUSAL_CONNECTIVES:
            if " " in phrase:
                causal_count += len(re.findall(re.escape(phrase), text_lower))
            else:
                causal_count += sum(1 for w in words if w == phrase)

        hedge_count = sum(1 for w in words if w in self.HEDGE_WORDS)

        causal_density = causal_count / word_count
        hedge_ratio = hedge_count / word_count

        # Quality: reward causal density, penalize extreme hedge (>15%) or zero hedge
        quality = 0.5
        quality += min(causal_density * 50, 0.3)  # up to +0.3 for causality
        if 0.02 <= hedge_ratio <= 0.12:
            quality += 0.2  # healthy hedging
        elif hedge_ratio > 0.15:
            quality -= 0.2  # over-hedging
        elif hedge_ratio < 0.01:
            quality -= 0.1  # no hedging at all (overconfident)

        return {
            "causal_density": round(causal_density, 4),
            "hedge_ratio": round(hedge_ratio, 4),
            "quality_score": round(max(0.0, min(1.0, quality)), 2),
        }

    def check_semantic_drift(
        self, shadow_id: str, raw_text: str, date: str
    ) -> float | None:
        """Check A: placeholder for semantic drift detection.

        Returns drift score or None if insufficient data.
        Full implementation requires embedding model (sentence-transformers).
        This is deferred to calibration phase (30+ days of Pro output).
        """
        # Deferred: requires embedding model and baseline calibration
        # Will compute cosine_similarity(methodology_prompt_embedding,
        # raw_output_embedding) and flag if drift > calibrated_threshold
        return None

    def run_daily_check(
        self, shadow_id: str, raw_text: str, insight_count: int,
        date: str | None = None
    ) -> ShadowHealthSnapshot:
        """Run all health checks for one shadow."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Check C: insight drought
        has_drought, drought_days = self.check_insight_drought(shadow_id, insight_count, date)

        # Check B: reasoning quality
        quality = self.check_reasoning_quality(raw_text) if raw_text else {}

        # Check A: semantic drift (deferred)
        drift = self.check_semantic_drift(shadow_id, raw_text, date)

        alerts = []
        if has_drought:
            alerts.append(f"INSIGHT DROUGHT: {drought_days} days without insights")
        if quality.get("quality_score", 1.0) < 0.4:
            alerts.append(f"LOW REASONING QUALITY: score={quality['quality_score']}")

        return ShadowHealthSnapshot(
            shadow_id=shadow_id,
            date=date,
            insight_drought_days=drought_days,
            has_insight_drought=has_drought,
            reasoning_quality=quality.get("quality_score", 1.0),
            causal_density=quality.get("causal_density", 0.0),
            hedge_ratio=quality.get("hedge_ratio", 0.0),
            alerts=alerts,
        )
