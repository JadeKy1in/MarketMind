"""Challenger trial execution — compare challenger vs target, apply verdict.

Extracted from shadows/shadow_mother.py for modular compliance (grandfather reduction).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("marketmind.shadows.shadow_challenger_executor")


async def execute_challenger_trials(state_db, config, challenger, result) -> None:
    """Execute pending challenger trials and apply verdicts (REPLACE/RESTORE/INCONCLUSIVE).

    Called by ShadowMother.orchestrate_daily_cycle after ranking computation.
    The result object (ShadowOrchestrationResult) is mutated in-place to record actions.
    """
    from marketmind.shadows.methodology_injector import MethodologyInjector
    injector = MethodologyInjector(state_db)

    active_challengers = state_db.get_active_shadows("challenger")
    for ch_config in active_challengers:
        target_id = ch_config.parent_shadow_id
        if not target_id:
            continue

        ch_snaps = state_db.get_snapshot_history(ch_config.shadow_id, days=90)
        tg_snaps = state_db.get_snapshot_history(target_id, days=90)
        if len(ch_snaps) < 10 or len(tg_snaps) < 10:
            continue

        trial = await challenger.run_comparison_trial(ch_config.shadow_id, target_id)
        verdict = trial.verdict

        if verdict == "REPLACE_TARGET":
            target_config = state_db.get_shadow(target_id)
            if target_config:
                state_db.eliminate_shadow(target_id, "challenger_replaced")
                ch_config_new = state_db.get_shadow(ch_config.shadow_id)
                if ch_config_new:
                    state_db.update_shadow_type(
                        ch_config.shadow_id,
                        target_config.shadow_type
                    )
                try:
                    from marketmind.shadows.ael_evolution import AELEvolutionEngine
                    ael = AELEvolutionEngine(state_db=state_db)
                    debriefs = ael._debrief_history.get(target_id, [])
                    if debriefs:
                        failures = []
                        for d in debriefs[-3:]:
                            failures.extend(d.failure_patterns)
                        if failures:
                            injector.inject_failure_patterns(
                                ch_config.shadow_id, failures[:5]
                            )
                except Exception as e:
                    logger.debug("Failure pattern transfer skipped: %s", e)

                result.challenger_actions.append(
                    f"REPLACED {target_id} with {ch_config.shadow_id}"
                )
                logger.info("Challenger %s replaces target %s", ch_config.shadow_id, target_id)

        elif verdict == "RESTORE_TARGET":
            state_db.eliminate_shadow(ch_config.shadow_id, "challenger_lost_trial")
            result.challenger_actions.append(
                f"RESTORED {target_id}, eliminated challenger {ch_config.shadow_id}"
            )
            logger.info("Challenger %s eliminated, target %s restored", ch_config.shadow_id, target_id)

        elif verdict == "INCONCLUSIVE":
            trial_extensions = getattr(ch_config, 'trial_extensions', 0)
            if trial_extensions < 2:
                result.challenger_actions.append(
                    f"INCONCLUSIVE for {ch_config.shadow_id} vs {target_id} "
                    f"(extension {trial_extensions + 1}/2)"
                )
            else:
                state_db.eliminate_shadow(ch_config.shadow_id, "challenger_max_extensions")
                result.challenger_actions.append(
                    f"MAX_EXTENSIONS for {ch_config.shadow_id} -- restoring {target_id}"
                )
