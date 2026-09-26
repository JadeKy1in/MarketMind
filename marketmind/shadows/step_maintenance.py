"""Maintenance step — challenger trials, method breeding, emergency audits.

Extracted from shadow_mother.py's _step_maintenance per workspace
modular architecture rules (glue layer hard ceiling: 300 lines).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.shadows.shadow_mother import ShadowOrchestrationResult
    from marketmind.shadows.shadow_state import ShadowStateDB
    from marketmind.config.settings import ShadowSettings
    from marketmind.shadows.challenger_execution import ChallengerExecutor

logger = logging.getLogger("marketmind.shadows.step_maintenance")


async def run_maintenance_step(
    config: "ShadowSettings",
    state_db: "ShadowStateDB",
    challenger_executor: "ChallengerExecutor",
    visible: list,
    result: "ShadowOrchestrationResult",
) -> None:
    """Run challenger checks/trials, method breeding, and emergency quota audits.

    Args:
        config: ShadowSettings for challenger/breeding config.
        state_db: ShadowStateDB for emergency quota access.
        challenger_executor: ChallengerExecutor for trial execution.
        visible: List of ranking-eligible ShadowConfig objects.
        result: Mutable ShadowOrchestrationResult (challenger_actions, emergency_audits).
    """
    from marketmind.shadows.challenger_engine import ChallengerEngine
    from marketmind.shadows.emergency_quota import EmergencyQuotaAuditor

    # 7. Check challenger conditions + execute trials (P0-2)
    try:
        challenger = ChallengerEngine(state_db, config)
        for shadow_config in visible:
            stage = challenger.check_elimination_stage(shadow_config.shadow_id)
            if stage.current_stage >= 2:
                result.challenger_actions.append(
                    f"Shadow {shadow_config.shadow_id} at stage {stage.current_stage}"
                )
        await challenger_executor.execute_trials(challenger, result)
    except Exception as e:
        logger.error("Challenger check failed: %s", e)

    # 7.5 Method breeding — weekly population maintenance (P1-4)
    today_day = datetime.now(timezone.utc).day
    if today_day % 7 == 1:  # run every 7 days (day 1, 8, 15, 22, 29)
        try:
            from marketmind.shadows.methodology_evolver import MethodologyEvolver
            evolver = MethodologyEvolver()
            evolver.maintain_population(min_active=6, max_active=15)
            logger.info("Methodology population maintained")
        except Exception as e:
            logger.error("Method breeding failed: %s", e)

    # 8. Audit emergency quotas
    try:
        auditor = EmergencyQuotaAuditor(state_db, config)
        pending = state_db.get_pending_emergency_audits()
        if pending:
            audits = auditor.audit_pending([q.id for q in pending if q.id])
            result.emergency_audits = audits
    except Exception as e:
        logger.error("Emergency quota audit failed: %s", e)
