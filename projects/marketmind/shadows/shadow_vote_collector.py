"""Shadow vote collector — runs all shadow analyses in parallel.

Extracted from shadow_mother.py's _step_collect_votes method per workspace
modular architecture rules (glue layer hard ceiling: 300 lines).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from marketmind.shadows.shadow_state import ShadowStateDB
from marketmind.config.settings import ShadowSettings

if TYPE_CHECKING:
    from marketmind.shadows.shadow_mother import ShadowOrchestrationResult

logger = logging.getLogger("marketmind.shadows.shadow_vote_collector")


async def collect_votes(
    state_db: ShadowStateDB,
    config: ShadowSettings,
    news_items: list[dict],
    market_data: dict,
    visible: list,
    today: str,
    result: "ShadowOrchestrationResult",
) -> list:
    """Run all shadow analyses in parallel, collect votes, update snapshots.

    P3-4 partial-state recovery: filters out already-completed shadows
    (cached replay) and saves a per-shadow checkpoint after EACH
    individual analysis. If the cycle crashes mid-step, the next run
    skips completed shadows and only re-runs incomplete/failed ones.

    Args:
        state_db: ShadowStateDB for checkpoint/vote/snapshot persistence.
        config: ShadowSettings (max_concurrent_shadows, etc.).
        news_items: Raw news headlines for shadow analysis.
        market_data: Market data dict for shadow context.
        visible: List of visible ShadowConfig objects to analyze.
        today: Date string YYYY-MM-DD.
        result: Mutable ShadowOrchestrationResult to populate.

    Returns:
        List of all collected (non-beta) votes.
    """
    from marketmind.shadows.shadow_agent import create_shadow_agent

    # P3-4 RESUME CHECK: Filter out shadows that already completed
    # successfully in a previous (crashed) run.
    visible_to_run: list = []
    resume_count = 0
    for s in visible:
        cp = state_db.get_checkpoint(today, s.shadow_id)
        if cp and cp.get("status") == "completed":
            logger.info(
                "Shadow %s already completed — skipping (cached replay)", s.shadow_id
            )
            continue
        if cp and cp.get("status") in ("pending", "failed"):
            resume_count += 1
        visible_to_run.append(s)

    if resume_count > 0:
        logger.info(
            "Resuming %d incomplete/failed shadows from previous run", resume_count
        )

    if not visible_to_run:
        logger.info("All shadows already completed — nothing to run")
        return []

    all_votes: list = []
    semaphore = asyncio.Semaphore(config.max_concurrent_shadows)

    async def _run_one(shadow_config):
        # P3-4: Save "pending" checkpoint BEFORE analysis starts
        state_db.save_checkpoint(
            date=today, shadow_id=shadow_config.shadow_id,
            status='pending', step=4
        )

        async with semaphore:
            try:
                agent = create_shadow_agent(shadow_config, state_db, config)
                output = await agent.run_daily_analysis(news_items, market_data)
                if output.decisions:
                    is_beta = shadow_config.status == "beta"
                    try:
                        if is_beta:
                            state_db.save_beta_analyses(
                                shadow_config.shadow_id, today, output.decisions)
                        else:
                            state_db.save_analyses(
                                shadow_config.shadow_id, today, output.decisions)
                    except Exception as e:
                        logger.error("Failed to save analyses for %s: %s",
                                     shadow_config.shadow_id, e)

                # P3-4: Save successful checkpoint with cached analysis output
                try:
                    analysis_dict = {
                        "shadow_id": output.shadow_id,
                        "date": output.date,
                        "vote_count": len(output.decisions),
                        "insight_count": len(output.insights),
                        "quota_used": output.quota_used,
                        "latency_ms": output.latency_ms,
                    }
                    state_db.save_checkpoint(
                        date=today, shadow_id=shadow_config.shadow_id,
                        status='completed', step=4,
                        analysis_json=json.dumps(analysis_dict)
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to save completed checkpoint for %s: %s",
                        shadow_config.shadow_id, e
                    )

                return shadow_config.shadow_id, output, None, shadow_config.status
            except Exception as e:
                logger.error("Shadow %s analysis failed: %s", shadow_config.shadow_id, e)

                # P3-4: Save failed checkpoint for retry on resume
                try:
                    state_db.save_checkpoint(
                        date=today, shadow_id=shadow_config.shadow_id,
                        status='failed', step=4, error_message=str(e)
                    )
                except Exception as ckpt_err:
                    logger.warning(
                        "Failed to save failure checkpoint for %s: %s",
                        shadow_config.shadow_id, ckpt_err
                    )

                return shadow_config.shadow_id, None, e, shadow_config.status

    tasks = [_run_one(c) for c in visible_to_run]
    results_list = await asyncio.gather(*tasks)

    for sid, output, err, status in results_list:
        if output is not None:
            is_beta = (status == "beta")
            result.shadow_analyses[sid] = output
            if not is_beta:
                result.decisions_collected += len(output.decisions)
                all_votes.extend(output.decisions)
            try:
                latest = state_db.get_latest_snapshot(sid)
                if latest and latest.date == today:
                    state_db.update_snapshot_fields(
                        sid, today,
                        insights_generated=len(output.insights),
                        votes_produced=len(output.decisions),
                        flash_quota_used=output.quota_used,
                    )
            except Exception as e:
                logger.debug("Snapshot update failed for %s: %s", sid, e)

    return all_votes
