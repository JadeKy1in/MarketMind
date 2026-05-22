"""AEL evolution step — monthly debrief + lesson injection wiring.

Extracted from shadow_mother.py's _step_ael_evolution per workspace
modular architecture rules (glue layer hard ceiling: 300 lines).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.shadows.shadow_mother import ShadowOrchestrationResult
    from marketmind.shadows.shadow_state import ShadowStateDB

logger = logging.getLogger("marketmind.shadows.step_ael")


async def run_ael_step(
    config,
    state_db: "ShadowStateDB",
    performances: dict,
    market_data: dict,
    today: str,
    result: "ShadowOrchestrationResult",
) -> None:
    """Run AEL monthly debrief if today is the configured debrief day.

    Args:
        config: ShadowSettings (ael_experiment_enabled, ael_debrief_day flags).
        state_db: ShadowStateDB for methodology injector wiring.
        performances: Dict of shadow_id -> PerformanceData from ranking step.
        market_data: Market data dict (VIX, SPY for market context).
        today: Date string YYYY-MM-DD.
        result: Mutable ShadowOrchestrationResult (ael_debriefs populated).
    """
    if not getattr(config, 'ael_experiment_enabled', False):
        return

    try:
        from marketmind.shadows.ael_evolution import AELEvolutionEngine
        from marketmind.shadows.methodology_injector import MethodologyInjector

        ael = AELEvolutionEngine(state_db=state_db)
        ael.ensure_control_replicas(state_db)
        debrief_day = getattr(config, 'ael_debrief_day', 1)
        today_day = int(today.split("-")[2])

        if today_day != debrief_day:
            return

        # Build performance dicts for treatment shadows
        treatment_ids = {
            "daredevil:range_bound:sideways_scout",
            "daredevil:weekly:trend_rider",
            "expert:tech:silicon_oracle",
            "expert:macro:cycle_reader",
        }
        for sid in treatment_ids:
            perf_data = performances.get(sid)
            if not perf_data:
                continue
            market_ctx = (
                f"VIX: {market_data.get('VIX', 'N/A')}, "
                f"SPY: {market_data.get('SPY', 'N/A')}"
            )
            debrief = await ael.run_monthly_debrief(sid, {
                "win_rate": perf_data.win_rate,
                "cumulative_return": perf_data.cumulative_return,
                "total_trades": perf_data.total_trades,
                "profitable_trades": perf_data.profitable_trades,
                "losing_trades": perf_data.losing_trades,
            }, market_ctx)
            if debrief.lessons_learned:
                injected = ael.inject_lesson(sid, debrief.lessons_learned)
                debrief.prompt_injected = injected
                if injected:
                    # P1-3: Wire AEL lessons to shadow prompts via MethodologyInjector
                    active_lessons = ael.get_active_lessons(sid)
                    MethodologyInjector(state_db).inject_lessons(
                        sid, active_lessons
                    )
                logger.info(
                    "AEL debrief for %s: lesson %s", sid,
                    "injected" if injected else "rejected (cap)"
                )
            result.ael_debriefs.append(debrief)
    except Exception as e:
        logger.error("AEL evolution step failed: %s", e)
