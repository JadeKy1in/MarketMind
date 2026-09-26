"""Knowledge management step — memory update + crystallization wiring.

Extracted from shadow_mother.py's _step_knowledge_management per workspace
modular architecture rules (glue layer hard ceiling: 300 lines).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.shadows.shadow_mother import ShadowOrchestrationResult
    from marketmind.shadows.shadow_state import ShadowStateDB
    from marketmind.config.settings import ShadowSettings
    from marketmind.shadows.knowledge_manager import KnowledgeManager

logger = logging.getLogger("marketmind.shadows.step_knowledge")


async def run_knowledge_step(
    config: "ShadowSettings",
    knowledge_manager: "KnowledgeManager",
    state_db: "ShadowStateDB",
    result: "ShadowOrchestrationResult",
    today: str,
) -> None:
    """Update shadow memory with today's votes/analyses, run crystallization.

    Args:
        config: ShadowSettings (crystallization_enabled flag).
        knowledge_manager: KnowledgeManager instance for memory/crystallization ops.
        state_db: ShadowStateDB for methodology injector wiring.
        result: Mutable ShadowOrchestrationResult with today's votes/analyses.
        today: Date string YYYY-MM-DD.
    """
    if not getattr(config, 'crystallization_enabled', False):
        return

    # 6.6 Memory update — ingest today's votes and analyses into shadow memory
    try:
        await knowledge_manager.update_shadow_memory(result, today)
    except Exception as e:
        logger.error("Shadow memory update failed: %s", e)

    # 6.7 Crystallization check — insight -> hypothesis -> validate -> promote/retire
    try:
        crystallization_results = await knowledge_manager.run_crystallization_check()
        logger.info(
            "Crystallization complete: %d results",
            len(crystallization_results),
        )
        # P0-1: Wire crystallization results to knowledge filter
        from marketmind.shadows.knowledge_filter import KnowledgeFilter
        kf = KnowledgeFilter()
        for cr in crystallization_results:
            for source_id in cr.source_insight_ids:
                kf.record_crystallization_result(
                    source_id, cr.action,
                    source_shadow_id=source_id.split(":")[1] if ":" in source_id else ""
                )
        # P1-2: Wire crystallization results to shadow methodology prompts
        from marketmind.shadows.methodology_evolver import MethodologyInjector
        injector = MethodologyInjector(state_db)
        for cr in crystallization_results:
            sid = cr.source_shadow_id
            if not sid:
                continue
            if cr.action == "promote" and cr.methodology_changes:
                for change in cr.methodology_changes:
                    if change:
                        injector.inject_validated_insight(sid, change)
            elif cr.action == "retire":
                injector.inject_retired_insight(
                    sid, cr.evidence_summary or "Failed validation"
                )
    except Exception as e:
        logger.error("Crystallization check failed: %s", e)
