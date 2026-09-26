"""Knowledge Manager — shadow memory updates and knowledge crystallization.

Extracted from shadow_mother.py's _update_shadow_memory and _run_crystallization_check
to satisfy the 500-line hard ceiling (CLAUDE.md §3.1).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.shadows.shadow_state import ShadowStateDB
    from marketmind.shadows.shadow_mother import ShadowOrchestrationResult
    from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.knowledge_manager")


class KnowledgeManager:
    """Manages shadow episodic memory ingestion and knowledge crystallization cycles."""

    def __init__(self, state_db: "ShadowStateDB", config: "ShadowSettings"):
        self.state_db = state_db
        self.config = config

    async def update_shadow_memory(
        self, result: "ShadowOrchestrationResult", today: str
    ) -> None:
        """Ingest today's votes and analyses into shadow memory.

        Stores shadow analyses as episodic memory observations, preserving
        the reasoning chain for knowledge crystallization.
        """
        from marketmind.shadows.shadow_memory import ShadowMemoryStore
        from marketmind.shadows.shadow_agent import ExternalObservation

        store = ShadowMemoryStore(self.state_db)

        for shadow_id, analysis in result.shadow_analyses.items():
            # Create observations from insights
            for insight in analysis.insights:
                obs = ExternalObservation(
                    observation_id=f"insight:{shadow_id}:{today}:{hash(insight) & 0xFFFFFFFF:x}",
                    source_type="text",
                    source_path=f"shadow:{shadow_id}",
                    extracted_text=insight[:500],
                    metadata={"shadow_id": shadow_id, "date": today, "type": "insight"},
                    confidence=0.7,
                    source_attribution=f"shadow:{shadow_id}:daily_analysis",
                    evaluated_at=today,
                )
                store.ingest_observation_sync(shadow_id, obs, tier="episodic")

            # Create observations from votes
            for vote in analysis.decisions:
                ticker = vote.ticker
                obs = ExternalObservation(
                    observation_id=f"vote:{shadow_id}:{today}:{ticker}:{hash(vote.thesis) & 0xFFFFFFFF:x}",
                    source_type="text",
                    source_path=f"shadow:{shadow_id}",
                    extracted_text=(
                        f"VOTE: {vote.direction} {ticker} "
                        f"(confidence={vote.confidence:.2f}) "
                        f"Thesis: {vote.thesis[:200]}"
                    ),
                    metadata={
                        "shadow_id": shadow_id,
                        "date": today,
                        "type": "vote",
                        "ticker": ticker,
                        "direction": vote.direction,
                        "confidence": vote.confidence,
                    },
                    confidence=vote.confidence,
                    source_attribution=f"shadow:{shadow_id}:daily_analysis",
                    evaluated_at=today,
                )
                store.ingest_observation_sync(shadow_id, obs, tier="episodic")

        logger.info(
            "Shadow memory updated: ingested analyses for %d shadows",
            len(result.shadow_analyses),
        )

    async def run_crystallization_check(self) -> list:
        """Run knowledge crystallization for shadows with sufficient vote history.

        Queries episodic memory for insights with high belief but low confidence,
        backtest validates against shadow_analyses, and promotes or retires insights.
        """
        from marketmind.shadows.shadow_memory import ShadowMemoryStore
        from marketmind.shadows.methodology_evolver import MethodologyEvolver
        from marketmind.shadows.crystallization import CrystallizationEngine

        store = ShadowMemoryStore(self.state_db)
        evolver = MethodologyEvolver()

        significance = getattr(
            self.config, 'crystallization_significance_threshold', 0.6
        )
        min_samples = getattr(
            self.config, 'crystallization_min_samples', 10
        )

        engine = CrystallizationEngine(
            memory_store=store,
            state_db=self.state_db,
            methodology_evolver=evolver,
            significance_threshold=significance,
            min_samples=min_samples,
        )

        results = await engine.run_crystallization_cycle()
        return results
