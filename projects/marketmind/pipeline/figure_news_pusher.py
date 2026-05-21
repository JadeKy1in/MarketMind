"""FigureNewsPusher — distribute figure signals to correct pipeline stages.

Three-tier pushing: CRITICAL (instant), HIGH (15min batch), LOW (daily summary).
Different shadows receive different signal types per §7.3 of design doc.

Millennium-style Chinese Wall (§8.1): Shadows receive ONLY raw content
(person_name + text + timestamp). AWA scores and signal direction are
stripped before distribution. Only the user-facing Gate 2 display
retains AWA scores.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.pipeline.flash_triage import TriageResult

logger = logging.getLogger("marketmind.pipeline.figure_news_pusher")


# ── Data Types ──────────────────────────────────────────────────────────────────


@dataclass
class FigureSignal:
    """A scored signal from a tracked market figure.

    Defined per design doc §8.2. Used by FigureSignalExtractor (future module)
    and distributed by FigureNewsPusher.
    """
    person_name: str
    category: str                # I-VI (policy maker, politician, CEO, activist, fund manager, celebrity)
    signal_direction: str        # "directional" | "contrarian" | "confirmatory"
    event_type: str              # "speech" | "trade" | "filing" | "social_post"
    ticker: str | None = None
    direction: str | None = None  # "long" | "short" | "warn"
    awa_score: float = 0.0       # 0-1, Ability × Willingness × Acknowledgment
    confidence: float = 0.5      # 0.0-1.0 directional confidence
    summary: str = ""            # Flash-generated one-line summary
    source_url: str = ""
    timestamp: str = ""          # ISO-format UTC


@dataclass
class _PushResult:
    """Internal container for push distribution results."""
    target: str
    count: int
    signals: list[dict] = field(default_factory=list)


# ── Tier Thresholds ─────────────────────────────────────────────────────────────

CRITICAL_THRESHOLD = 0.80   # ≥80: instant push
HIGH_THRESHOLD = 0.50       # 50-79: 15min batch


# ── FigureNewsPusher ────────────────────────────────────────────────────────────


class FigureNewsPusher:
    """Push figure signals to main pipeline and shadow ecosystem.

    Three output channels:
    1. Main pipeline Flash Triage — as TriageResult with content_type="figure_signal"
    2. Shadow ecosystem — raw content only (stripped AWA scores per §8.1)
    3. Gate 2 display — user-facing "Today's Figure Activity" WITH AWA scores

    Shadow filtering (§7.3):
      - Fade Master: all sentiment signals
      - Crash Hunter: insider clusters, short reports
      - Expert shadows: domain-relevant figure activity
      - Default (remaining): only CRITICAL tier signals
    """

    # Which shadow types receive which figure signals
    SHADOW_FILTER: dict[str, list[str]] = {
        "fade_master": ["all"],
        "crash_hunter": ["insider_cluster", "short_report"],
        "expert": ["domain_relevant"],
        "default": ["critical_only"],
    }

    # ── Public API ──────────────────────────────────────────────────────────

    def push_to_pipeline(self, signals: list[FigureSignal]) -> list[dict]:
        """Route signals to main pipeline Flash Triage as 'figure_signal' type.

        Converts FigureSignals to triage-compatible dicts so flash_triage
        can ingest them alongside regular NewsItems.

        Args:
            signals: List of scored figure signals from FigureSignalExtractor.

        Returns:
            List of dicts ready for TriageResult construction, with
            content_type="figure_signal" and pre-populated scores from AWA.
        """
        results: list[dict] = []
        for s in signals:
            # Map AWA score + confidence to triage-compatible axes
            impact = min(10, round(s.awa_score * 10, 1))
            urgency = 10 if s.awa_score >= CRITICAL_THRESHOLD else min(
                10, max(1, round(s.awa_score * 8, 1)))

            results.append({
                "content_type": "figure_signal",
                "figure_signal": s,
                "headline": f"[{s.person_name}] {s.summary[:280]}",
                "source_name": f"figure:{s.person_name}",
                "source_tier": 2,  # Figure signals are tier-2: curated, not raw
                "source_reliability": s.confidence,
                "url": s.source_url,
                "published_at": s.timestamp,
                "scores": {
                    "market_impact": impact,
                    "cross_source_corroboration": 5,  # Not applicable — mid-scale default
                    "contradicts_consensus": 5,
                    "investigative_depth_needed": 3,
                    "urgency": urgency,
                },
                "classification": self._map_category_to_classification(s.category),
                "affected_assets": [s.ticker] if s.ticker else [],
                "cluster_hints": [s.person_name.lower(), s.event_type],
                "direction": s.direction or "neutral",
                "confidence": s.confidence,
                "event_type": f"figure_{s.event_type}",
            })
        return results

    def push_to_shadows(self, signals: list[FigureSignal]) -> dict[str, list[dict]]:
        """Distribute RAW content to shadows per §7.3 filtering rules.

        IMPORTANT: Shadows receive ONLY raw text (person_name + text + timestamp).
        AWA scores and signal direction are STRIPPED before distribution.
        This maintains the Millennium-style Chinese Wall per §8.1.

        Args:
            signals: List of scored figure signals.

        Returns:
            Dict mapping shadow_type → list of sanitized signal dicts.
        """
        sanitized = self._strip_scores(signals)

        distribution: dict[str, list[dict]] = {}
        for shadow_type, filter_rules in self.SHADOW_FILTER.items():
            filtered = self._apply_filter(sanitized, signals, filter_rules, shadow_type)
            if filtered:
                distribution[shadow_type] = filtered

        logger.info(
            "FigureNewsPusher: distributed %d signals to %d shadow types",
            len(signals), len(distribution),
        )
        return distribution

    def push_to_gate2(self, signals: list[FigureSignal]) -> list[dict]:
        """Prepare 'Today's Figure Activity' panel for Gate 2 display.

        This IS shown to the user WITH AWA scores — only the user sees this.
        Shadows never receive AWA data (§8.1).

        Args:
            signals: List of scored figure signals, sorted by tier descending.

        Returns:
            List of display dicts sorted by tier (CRITICAL → HIGH → LOW),
            each containing person_name, category, event_type, awa_score,
            direction, summary, and tier label.
        """
        categorized: dict[str, list[dict]] = {"CRITICAL": [], "HIGH": [], "LOW": []}

        for s in signals:
            tier = self._classify_tier(s.awa_score)
            entry = {
                "person_name": s.person_name,
                "category": s.category,
                "event_type": s.event_type,
                "awa_score": round(s.awa_score, 3),
                "direction": s.direction,
                "signal_direction": s.signal_direction,
                "summary": s.summary,
                "ticker": s.ticker,
                "timestamp": s.timestamp,
                "tier": tier,
            }
            categorized[tier].append(entry)

        # Merge: CRITICAL first, then HIGH, then LOW
        result = categorized["CRITICAL"] + categorized["HIGH"] + categorized["LOW"]
        logger.info(
            "FigureNewsPusher: Gate 2 display — %d CRITICAL, %d HIGH, %d LOW",
            len(categorized["CRITICAL"]),
            len(categorized["HIGH"]),
            len(categorized["LOW"]),
        )
        return result

    # ── Internal Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _strip_scores(signals: list[FigureSignal]) -> list[dict]:
        """Remove AWA scores and direction for shadow distribution.

        Shadows receive ONLY: person_name, summary text, timestamp, event_type.
        No AWA scores. No signal direction. No confidence values.
        """
        return [{
            "person_name": s.person_name,
            "text": s.summary,
            "timestamp": s.timestamp,
            "event_type": s.event_type,
        } for s in signals]

    @staticmethod
    def _classify_tier(awa_score: float) -> str:
        """Map AWA score to push tier label."""
        if awa_score >= CRITICAL_THRESHOLD:
            return "CRITICAL"
        elif awa_score >= HIGH_THRESHOLD:
            return "HIGH"
        return "LOW"

    @staticmethod
    def _map_category_to_classification(category: str) -> str:
        """Map figure category (I-VI) to triage classification."""
        mapping = {
            "I": "macro",
            "II": "macro",
            "III": "company",
            "IV": "company",
            "V": "macro",
            "VI": "sentiment",
        }
        return mapping.get(category, "sentiment")

    def _apply_filter(
        self,
        sanitized: list[dict],
        originals: list[FigureSignal],
        rules: list[str],
        shadow_type: str,
    ) -> list[dict]:
        """Apply shadow-type filter rules to sanitized signals.

        Uses original signals (with scores) for tier-based filtering
        but returns sanitized dicts (without scores).
        """
        if "all" in rules:
            return sanitized

        filtered: list[dict] = []
        for i, s in enumerate(originals):
            match = False

            if "critical_only" in rules:
                match = s.awa_score >= CRITICAL_THRESHOLD

            if "insider_cluster" in rules:
                if s.event_type in ("filing", "trade"):
                    match = True

            if "short_report" in rules:
                if s.direction == "short" or s.direction == "warn":
                    match = True

            if "domain_relevant" in rules:
                # Expert shadows receive all non-LOW signals — domain
                # filtering is done by the shadow based on its own expertise
                match = s.awa_score >= HIGH_THRESHOLD

            if match and i < len(sanitized):
                filtered.append(sanitized[i])

        return filtered


# ── Module-level helpers ────────────────────────────────────────────────────────


def build_triage_results_from_figures(
    signals: list[FigureSignal],
) -> list[TriageResult]:
    """Convert figure signals into TriageResult objects for pipeline ingestion.

    This is the integration bridge between FigureNewsPusher and flash_triage.
    Call this before passing figure-originated results into triage_batch()
    or the main pipeline flow.

    Args:
        signals: List of scored figure signals.

    Returns:
        List of TriageResult with content_type="figure_signal".
    """
    from marketmind.pipeline.flash_triage import TriageResult

    pusher = FigureNewsPusher()
    raw_dicts = pusher.push_to_pipeline(signals)

    results: list[TriageResult] = []
    for d in raw_dicts:
        results.append(TriageResult(
            headline=d["headline"],
            source_name=d["source_name"],
            source_tier=d["source_tier"],
            source_reliability=d["source_reliability"],
            url=d["url"],
            published_at=d["published_at"],
            scores=d["scores"],
            classification=d["classification"],
            affected_assets=d["affected_assets"],
            cluster_hints=d["cluster_hints"],
            direction=d["direction"],
            confidence=d["confidence"],
            event_type=d["event_type"],
            content_type="figure_signal",
        ))
    return results
