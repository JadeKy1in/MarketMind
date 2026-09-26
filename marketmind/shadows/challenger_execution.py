"""Challenger Execution — executes pending challenger comparison trials.

Extracted from shadow_mother.py's _execute_challenger_trials to satisfy the 500-line
hard ceiling (CLAUDE.md §3.1).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.shadows.shadow_state import ShadowStateDB
    from marketmind.shadows.shadow_mother import ShadowOrchestrationResult
    from marketmind.shadows.challenger_engine import ChallengerEngine

logger = logging.getLogger("marketmind.shadows.challenger_execution")


class ChallengerExecutor:
    """Executes pending challenger comparison trials (P0-2).

    For each challenger shadow with sufficient trial data:
    1. Run paired t-test comparison (challenger vs target)
    2. REPLACE_TARGET: eliminate target, promote challenger, transfer knowledge
    3. RESTORE_TARGET: eliminate challenger
    4. INCONCLUSIVE: extend trial by 10 days (max 2 extensions)
    """

    def __init__(self, state_db: "ShadowStateDB"):
        self.state_db = state_db

    async def execute_trials(
        self,
        challenger: "ChallengerEngine",
        result: "ShadowOrchestrationResult",
    ) -> None:
        from marketmind.shadows.methodology_evolver import MethodologyInjector

        injector = MethodologyInjector(self.state_db)

        active_challengers = self.state_db.get_active_shadows("challenger")
        for ch_config in active_challengers:
            target_id = ch_config.parent_shadow_id
            if not target_id:
                continue

            # Check if enough trial data exists
            ch_snaps = self.state_db.get_snapshot_history(ch_config.shadow_id, days=90)
            tg_snaps = self.state_db.get_snapshot_history(target_id, days=90)
            if len(ch_snaps) < 10 or len(tg_snaps) < 10:
                continue  # insufficient data for trial

            trial = await challenger.run_comparison_trial(ch_config.shadow_id, target_id)
            verdict = trial.verdict

            if verdict == "REPLACE_TARGET":
                # Promote challenger — change type from "challenger" to target's type
                target_config = self.state_db.get_shadow(target_id)
                if target_config:
                    self.state_db.eliminate_shadow(target_id, "challenger_replaced")
                    ch_config_new = self.state_db.get_shadow(ch_config.shadow_id)
                    if ch_config_new:
                        self.state_db.update_shadow_type(
                            ch_config.shadow_id,
                            target_config.shadow_type
                        )
                    # Transfer predecessor failure patterns to challenger
                    try:
                        from marketmind.shadows.ael_evolution import AELEvolutionEngine
                        ael = AELEvolutionEngine(state_db=self.state_db)
                        debriefs = ael._debrief_history.get(target_id, [])
                        if debriefs:
                            failures = []
                            for d in debriefs[-3:]:  # last 3 debriefs
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
                self.state_db.eliminate_shadow(ch_config.shadow_id, "challenger_lost_trial")
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
                    # Max extensions reached — restore target, kill challenger
                    self.state_db.eliminate_shadow(ch_config.shadow_id, "challenger_max_extensions")
                    result.challenger_actions.append(
                        f"MAX_EXTENSIONS for {ch_config.shadow_id} — restoring {target_id}"
                    )
