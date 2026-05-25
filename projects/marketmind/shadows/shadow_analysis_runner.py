"""Shadow analysis runner — parallel shadow analysis with checkpointing."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.shadow_analysis_runner")


async def run_shadow_analyses(
    state_db: ShadowStateDB,
    config: ShadowSettings,
    visible: list[ShadowConfig],
    today: str,
    news_items: list[dict],
    market_data: dict,
):
    """Run all shadow analyses in parallel with semaphore and checkpointing.

    Reads broadcast messages, manages per-shadow checkpoints, runs each
    shadow's daily analysis, collects votes and snapshots, and cleans up
    checkpoints after completion.

    Returns:
        (shadow_analyses: dict, votes_collected: int, all_votes: list)
    """
    # Read broadcast messages
    broadcast_messages: list = []
    try:
        from marketmind.shadows.broadcast import BroadcastReader
        reader = BroadcastReader(str(Path(config.shadows_db_path).parent))
        broadcast_messages = reader.poll_today(today)
        if broadcast_messages:
            logger.info("Broadcast: %d messages available for shadow analysis", len(broadcast_messages))
    except Exception as e:
        logger.debug("Broadcast read skipped (non-critical): %s", e)

    # Per-shadow checkpoints (P3-4): check which shadows already completed today
    checkpoint_lock = asyncio.Lock()
    completed_shadows: set[str] = set()

    for cfg in visible:
        chk = state_db.get_checkpoint(today, cfg.shadow_id)
        if chk and chk.get("status") == "completed":
            completed_shadows.add(cfg.shadow_id)

    if completed_shadows:
        logger.info(
            "Resuming from checkpoints for %s: %d/%d shadows already completed",
            today, len(completed_shadows), len(visible)
        )
        for sid in completed_shadows:
            cached_output = state_db.get_raw_output(sid, today)
            if cached_output:
                logger.debug("Replaying cached output for %s", sid)

    from marketmind.shadows.shadow_agent import create_shadow_agent
    all_votes: list = []
    semaphore = asyncio.Semaphore(config.max_concurrent_shadows)

    async def _run_one(cfg):
        sid = cfg.shadow_id
        if sid in completed_shadows:
            cached_output = state_db.get_raw_output(sid, today)
            if cached_output:
                return sid, None, None

        async with semaphore:
            try:
                agent = create_shadow_agent(cfg, state_db, config)
                output = await asyncio.wait_for(
                    agent.run_daily_analysis(
                        news_items, market_data, broadcast_messages=broadcast_messages
                    ),
                    timeout=config.shadow_analysis_timeout_s,
                )
                if output.decisions:
                    try:
                        state_db.save_votes(sid, today, output.decisions)
                    except Exception as e:
                        logger.error("Failed to save votes for %s: %s", sid, e)
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
                try:
                    state_db.save_checkpoint(
                        today, sid, "completed", step=4,
                        analysis_json=None
                    )
                except Exception:
                    logger.debug("Checkpoint save failed for %s", sid)
                return sid, output, None
            except Exception as e:
                logger.error("Shadow %s analysis failed: %s (type=%s)", sid, e, type(e).__name__)
                return sid, None, e

    tasks = [_run_one(c) for c in visible]
    results_list = await asyncio.gather(*tasks)

    shadow_analyses: dict = {}
    votes_collected = 0
    for sid, output, err in results_list:
        if output is not None:
            shadow_analyses[sid] = output
            votes_collected += len(output.decisions)
            all_votes.extend(output.decisions)
        elif err is None and sid in completed_shadows:
            cached_raw = state_db.get_raw_output(sid, today)
            if cached_raw:
                logger.info("Replaying cached analysis for %s", sid)

    # Checkpoint cleanup after all shadows completed
    try:
        state_db.clear_date_checkpoints(today)
    except Exception as e:
        logger.debug("Checkpoint cleanup failed for %s: %s", today, e)

    return shadow_analyses, votes_collected, all_votes
