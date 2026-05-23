"""Shadow memory update and crystallization — ingest daily analyses, validate hypotheses.

Extracted from shadows/shadow_mother.py for modular compliance (grandfather reduction).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("marketmind.shadows.shadow_memory_updater")


async def update_shadow_memory(state_db, config, shadow_analyses: dict, today: str) -> None:
    """Ingest each shadow's daily insights and votes into the shadow memory store.

    Called by ShadowMother.orchestrate_daily_cycle after all shadow analyses complete.
    """
    from marketmind.shadows.shadow_memory import ShadowMemoryStore
    from marketmind.shadows.shadow_agent import ExternalObservation

    store = ShadowMemoryStore(state_db)

    for shadow_id, analysis in shadow_analyses.items():
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

        for vote in analysis.votes:
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
        len(shadow_analyses),
    )


async def run_crystallization_check(state_db, config) -> list:
    """Run crystallization cycle: validate hypotheses, promote/retire insights.

    Called by ShadowMother.orchestrate_daily_cycle after memory update.
    """
    from marketmind.shadows.shadow_memory import ShadowMemoryStore
    from marketmind.shadows.methodology_evolver import MethodologyEvolver
    from marketmind.shadows.crystallization import CrystallizationEngine

    store = ShadowMemoryStore(state_db)
    evolver = MethodologyEvolver()

    significance = getattr(
        config, 'crystallization_significance_threshold', 0.6
    )
    min_samples = getattr(
        config, 'crystallization_min_samples', 10
    )

    engine = CrystallizationEngine(
        memory_store=store,
        state_db=state_db,
        methodology_evolver=evolver,
        significance_threshold=significance,
        min_samples=min_samples,
    )

    results = await engine.run_crystallization_cycle()
    return results
