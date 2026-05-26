"""Daily Orchestrator — ranking computation, plateau detection, and ecosystem surveillance.

Extracted from shadow_mother.py's _step_rank_and_calibrate and _step_surveillance
to satisfy the 500-line hard ceiling (CLAUDE.md §3.1).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
    from marketmind.shadows.shadow_mother import ShadowOrchestrationResult
    from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.orchestrator")


class Orchestrator:
    """Orchestrates ranking computation, plateau detection, paper-live gap calibration,
    and ecosystem surveillance (collusion, health, blind-spot audit)."""

    def __init__(self, state_db: "ShadowStateDB", config: "ShadowSettings"):
        self.state_db = state_db
        self.config = config

    async def step_rank_and_calibrate(
        self,
        visible: list,
        today: str,
        result: "ShadowOrchestrationResult",
        market_data: dict,
        market_accuracies: dict[str, float] | None = None,
    ) -> dict:
        """Compute composite rankings, detect plateaus, check reset eligibility,
        and calibrate paper-to-live gap. Returns performances dict."""
        from marketmind.shadows.shadow_agent import ShadowAgent
        from marketmind.shadows.ranking_engine import RankingEngine, ShadowPerformance

        performances: dict = {}

        # 5. Compute rankings (if we have performance data)
        try:
            engine = RankingEngine(self.config)
            for config in visible:
                snapshots = self.state_db.get_snapshot_history(
                    config.shadow_id, days=self.config.evaluation_window_days
                )
                if snapshots:
                    returns = [s.daily_return_pct or 0.0 for s in snapshots
                               if s.daily_return_pct is not None]
                    cum = sum(returns)
                    peak = 0.0; running = 0.0; mdd = 0.0
                    for r in returns:
                        running += r
                        if running > peak: peak = running
                        dd = running - peak
                        if dd < mdd: mdd = dd
                    abst_days = sum(1 for s in snapshots
                                    if getattr(s, 'votes_produced', 0) == 0)
                    perf = ShadowPerformance(
                        shadow_id=config.shadow_id,
                        daily_returns=returns,
                        cumulative_return=cum,
                        max_drawdown=abs(mdd) if mdd < 0 else 0.01,
                        max_drawdown_duration_days=0,
                        win_rate=sum(1 for r in returns if r > 0) / len(returns) if returns else 0.5,
                        total_trades=len(returns),
                        profitable_trades=sum(1 for r in returns if r > 0),
                        losing_trades=sum(1 for r in returns if r <= 0),
                        abstention_days=abst_days,
                        cagr=cum * 252 / len(returns) if len(returns) > 0 else 0.0,
                        domain=config.domain,
                        shadow_type=config.shadow_type,
                        career_days=len(snapshots),
                    )
                    performances[config.shadow_id] = perf

            if performances:
                rankings = engine.rank_shadows(
                    performances, {}, today,
                    market_accuracies=market_accuracies)
                result.rankings = rankings
                # Backfill ranking data into snapshots
                for rr in rankings:
                    agent_config = self.state_db.get_shadow(rr.shadow_id)
                    if agent_config:
                        agent = ShadowAgent(agent_config, self.state_db, self.config)
                        agent.apply_ranking_to_snapshot(rr)

                # Plateau detection + reset eligibility checks (Phase 2)
                for config in visible:
                    try:
                        tier_hist = self.state_db.get_tier_history(
                            config.shadow_id, days=self.config.plateau_no_elite_days * 2
                        )
                        wr_hist = self.state_db.get_wr_history(
                            config.shadow_id, days=self.config.plateau_no_elite_days * 2
                        )
                        insight_dates = self.state_db.get_insight_dates(
                            config.shadow_id, days=self.config.plateau_no_insight_days * 2
                        )

                        is_plateau, plateau_score = engine.detect_plateau(
                            config.shadow_id, tier_hist, wr_hist, insight_dates
                        )
                        if is_plateau:
                            logger.info("Plateau detected: %s (score=%.2f)", config.shadow_id, plateau_score)
                            result.plateau_flags.append({
                                "shadow_id": config.shadow_id,
                                "plateau_score": plateau_score,
                                "date": today,
                            })

                        should_reset, reset_reason = engine.check_reset_eligibility(
                            tier_hist, wr_hist, insight_dates
                        )
                        if should_reset:
                            logger.info("Reset eligible: %s — %s", config.shadow_id, reset_reason)
                            result.reset_candidates.append({
                                "shadow_id": config.shadow_id,
                                "reason": reset_reason,
                                "date": today,
                            })
                    except Exception as e:
                        logger.debug("Plateau/reset check failed for %s: %s", config.shadow_id, e)

        except Exception as e:
            logger.error("Ranking computation failed: %s", e)

        # 5b. Calibrate paper-to-live gap (per-asset discount rate adjustment)
        try:
            from marketmind.shadows.paper_live_gap import PaperLiveGapManager
            gap_manager = PaperLiveGapManager(self.state_db, self.config)
            for config in visible:
                trades = self.state_db.get_trade_history(config.shadow_id, limit=100)
                if not trades:
                    continue
                from collections import Counter
                ticker_counts = Counter(t.ticker for t in trades)
                most_common = ticker_counts.most_common(1)
                if most_common:
                    ticker = most_common[0][0]
                    gap_manager.update_discount_rate(config.shadow_id, ticker)
            gap_manager.save_all_states()
        except Exception as e:
            logger.error("Paper-to-live gap calibration failed: %s", e)

        return performances

    async def step_surveillance(
        self,
        all_decisions: list,
        market_data: dict,
        today: str,
        result: "ShadowOrchestrationResult",
        visible: list,
    ) -> None:
        """Run ecosystem surveillance: collusion detection, shadow health monitor,
        ecosystem blind-spot audit, and ecosystem health check."""

        # 6. Detect collusion
        try:
            from marketmind.shadows.collusion_detector import CollusionDetector
            collusion = CollusionDetector(self.config)
            collusion_flags = collusion.run_daily_check(today, all_decisions, market_data)
            result.collusion_flags = collusion_flags
            for flag in collusion_flags:
                self.state_db.record_collusion_flag(flag)
        except Exception as e:
            logger.error("Collusion detection failed: %s", e)

        # 6.4 Shadow health monitor — individual checks (Phase 3, Item 11)
        try:
            from marketmind.shadows.shadow_health_monitor import ShadowHealthMonitor
            health_monitor = ShadowHealthMonitor(state_db=self.state_db)
            for sid, output in result.shadow_analyses.items():
                raw_text = self.state_db.get_raw_output(sid, today) or ""
                snapshot = health_monitor.run_daily_check(
                    sid, raw_text, len(output.insights), today
                )
                if snapshot.alerts:
                    result.health_alerts[sid] = snapshot.alerts
                    logger.info("Health alert for %s: %s", sid, snapshot.alerts)
        except Exception as e:
            logger.error("Shadow health monitor failed: %s", e)

        # 6.5 Ecosystem audit — blind-spot scan (replaces Catfish, Phase 0)
        try:
            from marketmind.shadows.ecosystem_auditor import EcosystemAuditor
            auditor = EcosystemAuditor()
            ecosystem_alerts = auditor.run_audit(all_decisions, today)
            result.ecosystem_alerts = ecosystem_alerts
            if ecosystem_alerts:
                logger.info("Ecosystem audit: %d blind-spot alerts", len(ecosystem_alerts))
                try:
                    interpretation = await auditor.interpret_alerts(
                        ecosystem_alerts, market_data
                    )
                    result.ecosystem_interpretation = interpretation
                except Exception as e:
                    logger.error("Ecosystem audit Pro interpretation failed: %s", e)
        except Exception as e:
            logger.error("Ecosystem audit failed: %s", e)

        # 6.55 Ecosystem health — collective degradation detection (Phase 3, Item 12)
        try:
            from marketmind.shadows.ecosystem_health import EcosystemHealthMonitor
            eco_health = EcosystemHealthMonitor()
            token_data = {}
            for config in visible:
                tokens = self.state_db.get_token_history(config.shadow_id, days=30)
                if tokens:
                    token_data[config.shadow_id] = tokens
            eco_snapshot = eco_health.run_daily_check(all_decisions, token_data, today)
            result.ecosystem_health_snapshot = {
                "date": eco_snapshot.date,
                "active_shadows": eco_snapshot.active_shadows,
                "pattern_matcher_pct": eco_snapshot.pattern_matcher_pct,
                "balanced_pct": eco_snapshot.balanced_pct,
                "explorer_pct": eco_snapshot.explorer_pct,
                "avg_entropy": eco_snapshot.avg_entropy,
                "alerts": eco_snapshot.alerts,
            }
            if eco_snapshot.alerts:
                logger.info("Ecosystem health: %d alerts", len(eco_snapshot.alerts))
        except Exception as e:
            logger.error("Ecosystem health check failed: %s", e)
