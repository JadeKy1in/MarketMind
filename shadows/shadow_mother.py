"""Shadow Mother — daily orchestration glue for the shadow ecosystem."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_agent import ShadowAgent, ShadowAnalysisOutput, ShadowVote
from marketmind.config.settings import ShadowSettings

# Re-export types that consumers import from this module (preserve public API)
from marketmind.shadows.event_detector import DetectedEvent  # noqa: F401
from marketmind.shadows.temp_shadow_lifecycle import TempShadowSpec  # noqa: F401

from marketmind.shadows.event_detector import EventDetector
from marketmind.shadows.temp_shadow_lifecycle import TempShadowLifecycle

logger = logging.getLogger("marketmind.shadows.shadow_mother")


@dataclass
class ShadowOrchestrationResult:
    date: str
    active_shadows: int = 0
    temp_shadows_created: int = 0
    temp_shadows_destroyed: int = 0
    votes_collected: int = 0
    shadow_analyses: dict[str, ShadowAnalysisOutput] = field(default_factory=dict)
    rankings: list = field(default_factory=list)
    collusion_flags: list = field(default_factory=list)
    ecosystem_alerts: list = field(default_factory=list)
    ecosystem_interpretation: str = ""
    health_alerts: dict[str, list[str]] = field(default_factory=dict)
    ecosystem_health_snapshot: dict | None = None
    plateau_flags: list = field(default_factory=list)
    reset_candidates: list = field(default_factory=list)
    ael_debriefs: list = field(default_factory=list)       # Phase 7
    challenger_actions: list[str] = field(default_factory=list)
    emergency_audits: list[str] = field(default_factory=list)


class ShadowMother:
    """Orchestrates the daily shadow ecosystem cycle.

    Delegates event detection to EventDetector and temp shadow lifecycle to
    TempShadowLifecycle. Keeps orchestration, memory, crystallization, and
    challenger coordination in this module.
    """

    def __init__(self, config: ShadowSettings, state_db: ShadowStateDB):
        self.config = config
        self.state_db = state_db
        self._detector = EventDetector()
        self._lifecycle = TempShadowLifecycle(state_db, config)
        self._lifecycle.cleanup_stale()

    # ── Event scanning (delegated to EventDetector) ────────────────────────

    async def scan_events(self, news_items: list[dict]) -> list[DetectedEvent]:
        return await self._detector.scan_events(news_items)

    def detect_cb_shock(self, news_items: list[dict]) -> list[DetectedEvent]:
        return self._detector.detect_cb_shock(news_items)

    def detect_geopolitical(self, news_items: list[dict]) -> list[DetectedEvent]:
        return self._detector.detect_geopolitical(news_items)

    def detect_vol_shock(self, market_data: dict[str, float] | None = None) -> list[DetectedEvent]:
        return self._detector.detect_vol_shock(market_data)

    def detect_personnel_change(self, news_items: list[dict]) -> list[DetectedEvent]:
        return self._detector.detect_personnel_change(news_items)

    def prioritize_events(self, events: list[DetectedEvent],
                           max_shadows: int = 5) -> list[DetectedEvent]:
        return self._detector.prioritize_events(events, max_shadows)

    # ── Temp shadow lifecycle (delegated to TempShadowLifecycle) ────────────

    async def create_temp_shadows(self, events: list[DetectedEvent]) -> list[str]:
        return await self._lifecycle.create_temp_shadows(events)

    def check_destruction_conditions(self, shadow_id: str) -> bool:
        return self._lifecycle.check_destruction_conditions(shadow_id)

    async def destroy_temp_shadow(self, shadow_id: str) -> None:
        await self._lifecycle.destroy_temp_shadow(shadow_id)

    def get_active_temp_shadows(self) -> list[str]:
        return self._lifecycle.get_active_temp_shadows()

    def get_event_status(self, event_id: str) -> str:
        return self._lifecycle.get_event_status(event_id)

    # ── Missed path shadows ─────────────────────────────────────────────────

    async def create_missed_path_shadows(self, rejected_directions: list[str]) -> list[str]:
        created_ids: list[str] = []
        for i, direction in enumerate(rejected_directions[:self.config.missed_path_max_per_gate]):
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            shadow_id = f"missed_path:gate1:{ts}_{i}"
            config = ShadowConfig(
                shadow_id=shadow_id,
                shadow_type="missed_path",
                display_name=f"Missed Path {direction}",
                methodology_prompt=(
                    f"You are tracking the counterfactual path: {direction}. "
                    f"This path was rejected at Gate 1. You record what WOULD have happened "
                    f"if this direction was chosen. You do NOT generate investment votes. "
                    f"Track performance of this direction for {self.config.missed_path_report_days} days "
                    f"and report survivorship bias warning."
                ),
                virtual_capital=0.0,
                max_positions=0,
            )
            try:
                self.state_db.create_shadow(config)
                created_ids.append(shadow_id)
            except ValueError:
                pass
        return created_ids

    # ── Status cards ────────────────────────────────────────────────────────

    async def generate_status_cards(self, date: str) -> dict[str, dict]:
        cards: dict[str, dict] = {}
        for shadow in self.state_db.get_visible_shadows():
            from marketmind.shadows.shadow_agent import ShadowAgent
            agent = ShadowAgent(shadow, self.state_db, self.config)
            cards[shadow.shadow_id] = await agent.receive_status_card()
        return cards

    # ── Daily orchestration ─────────────────────────────────────────────────

    async def orchestrate_daily_cycle(self, news_items: list[dict],
                                       market_data: dict,
                                       rejected_directions: list[str] | None = None
                                       ) -> ShadowOrchestrationResult:
        """Full daily cycle for the shadow ecosystem:
        1. Scan events -> create/destroy temp shadows
        2. Create missed_path shadows
        3. Generate status cards
        4. Run all shadow analyses (collect votes)
        5. Compute rankings + backfill snapshots
        6. Detect collusion
        6.5. Update shadow memory (ingest today's votes/analyses)
        6.6. Run crystallization check (insight -> hypothesis -> validate)
        7. Check challenger conditions
        8. Audit emergency quotas
        """
        from marketmind.shadows.shadow_agent import ShadowAgent
        from marketmind.shadows.ranking_engine import RankingEngine, ShadowPerformance
        from marketmind.shadows.collusion_detector import CollusionDetector
        from marketmind.shadows.challenger_engine import ChallengerEngine
        from marketmind.shadows.emergency_quota import EmergencyQuotaAuditor

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = ShadowOrchestrationResult(date=today)

        # 1. Scan events -> create/destroy temp shadows
        events = await self.scan_events(news_items)
        prioritized = self.prioritize_events(events)
        created = await self.create_temp_shadows(prioritized)
        result.temp_shadows_created = len(created)

        for shadow in self.state_db.get_active_shadows("temp_event"):
            if self.check_destruction_conditions(shadow.shadow_id):
                await self.destroy_temp_shadow(shadow.shadow_id)
                result.temp_shadows_destroyed += 1

        # 2. Create missed_path shadows
        if rejected_directions:
            await self.create_missed_path_shadows(rejected_directions)

        # 3. Count active shadows
        visible = self.state_db.get_visible_shadows()
        result.active_shadows = len(visible)

        # 3.5 Read broadcast messages
        broadcast_messages: list = []
        try:
            from pathlib import Path
            from marketmind.shadows.broadcast import BroadcastReader
            reader = BroadcastReader(str(Path(self.config.shadows_db_path).parent))
            broadcast_messages = reader.poll_today(today)
            if broadcast_messages:
                logger.info("Broadcast: %d messages available for shadow analysis", len(broadcast_messages))
        except Exception as e:
            logger.debug("Broadcast read skipped (non-critical): %s", e)

        # 4. Run shadow analyses + collect votes
        checkpoint_lock = asyncio.Lock()
        checkpoint = self.state_db.get_cycle_checkpoint(today)
        completed_shadows: set[str] = set()

        if checkpoint and checkpoint["status"] == "running":
            completed_shadows = set(checkpoint["shadow_states"].get("completed", []))
            logger.info(
                "Resuming from checkpoint %s: %d/%d shadows already completed",
                today, len(completed_shadows), len(visible)
            )
            for sid in completed_shadows:
                cached_output = self.state_db.get_raw_output(sid, today, caller_id="system")
                if cached_output:
                    logger.debug("Replaying cached output for %s", sid)

        from marketmind.shadows.shadow_agent import create_shadow_agent
        all_votes: list = []
        semaphore = asyncio.Semaphore(self.config.max_concurrent_shadows)

        async def _run_one(config):
            sid = config.shadow_id
            if sid in completed_shadows:
                cached_output = self.state_db.get_raw_output(sid, today, caller_id="system")
                if cached_output:
                    return sid, None, None

            async with semaphore:
                try:
                    agent = create_shadow_agent(config, self.state_db, self.config)
                    output = await asyncio.wait_for(
                        agent.run_daily_analysis(
                            news_items, market_data, broadcast_messages=broadcast_messages
                        ),
                        timeout=self.config.shadow_analysis_timeout_s,
                    )
                    if output.votes:
                        try:
                            self.state_db.save_votes(sid, today, output.votes)
                        except Exception as e:
                            logger.error("Failed to save votes for %s: %s", sid, e)
                    try:
                        latest = self.state_db.get_latest_snapshot(sid, caller_id="system")
                        if latest and latest.date == today:
                            self.state_db.update_snapshot_fields(
                                sid, today,
                                insights_generated=len(output.insights),
                                votes_produced=len(output.votes),
                                flash_quota_used=output.quota_used,
                            )
                    except Exception as e:
                        logger.debug("Snapshot update failed for %s: %s", sid, e)
                    async with checkpoint_lock:
                        _cp = self.state_db.get_cycle_checkpoint(today)
                        _completed = set((_cp or {}).get("shadow_states", {}).get("completed", []))
                        _completed.add(sid)
                        self.state_db.save_cycle_checkpoint(
                            today, {"completed": sorted(_completed)}, step_completed=4
                        )
                    return sid, output, None
                except Exception as e:
                    logger.error("Shadow %s analysis failed: %s (type=%s)", sid, e, type(e).__name__)
                    return sid, None, e

        if not checkpoint:
            try:
                self.state_db.save_cycle_checkpoint(
                    today, {"completed": []}, step_completed=4
                )
            except Exception:
                logger.debug("Checkpoint already exists for %s", today)

        tasks = [_run_one(c) for c in visible]
        results_list = await asyncio.gather(*tasks)
        for sid, output, err in results_list:
            if output is not None:
                result.shadow_analyses[sid] = output
                result.votes_collected += len(output.votes)
                all_votes.extend(output.votes)
            elif err is None and sid in completed_shadows:
                cached_raw = self.state_db.get_raw_output(sid, today, caller_id="system")
                if cached_raw:
                    logger.info("Replaying cached analysis for %s", sid)

        try:
            self.state_db.save_cycle_checkpoint(
                today, {"completed": sorted(completed_shadows | set(
                    sid for sid, out, _ in results_list if out is not None
                ))}, status="completed", step_completed=4
            )
        except Exception as e:
            logger.error("Failed to mark checkpoint complete: %s", e)

        # 4.5 Market anchor
        market_accuracy: dict[str, float] = {}
        try:
            from marketmind.shadows.market_data_fetcher import MarketDataFetcher
            mdf = MarketDataFetcher()
            all_tickers: set[str] = set()
            for vote in all_votes:
                ticker = getattr(vote, "ticker", None) or vote.get("ticker", "")
                if ticker:
                    all_tickers.add(ticker)
            if all_tickers:
                lookback_start = (datetime.now(timezone.utc) -
                                 timedelta(days=self.config.evaluation_window_days + 5)
                                 ).strftime("%Y-%m-%d")
                for ticker in list(all_tickers)[:10]:
                    prices = mdf.fetch_ohlcv(ticker, lookback_start)
                    if prices:
                        self.state_db.save_market_prices(ticker, prices)
                all_saved_votes = self.state_db.get_votes_by_date_range(
                    lookback_start, today, caller_id="system"
                )
                votes_by_shadow: dict[str, list[dict]] = {}
                from collections import Counter
                for v in all_saved_votes:
                    sid = v.get("shadow_id", "")
                    if sid:
                        votes_by_shadow.setdefault(sid, []).append(v)

                for config in visible:
                    shadow_votes = votes_by_shadow.get(config.shadow_id, [])
                    if not shadow_votes:
                        continue
                    ticker_counts = Counter(
                        v.get("ticker", "") for v in shadow_votes
                    )
                    primary_ticker = ticker_counts.most_common(1)[0][0] if ticker_counts else ""
                    if not primary_ticker:
                        continue
                    acc = mdf.compute_market_accuracy(
                        shadow_votes, primary_ticker, lookback_start, today
                    )
                    market_accuracy[config.shadow_id] = acc
                    logger.debug(
                        "Market accuracy for %s on %s: %.3f",
                        config.shadow_id, primary_ticker, acc
                    )
        except Exception as e:
            logger.error("Market anchor computation failed: %s", e)

        # 5. Compute rankings
        try:
            engine = RankingEngine(self.config)
            performances: dict[str, ShadowPerformance] = {}
            for config in visible:
                snapshots = self.state_db.get_snapshot_history(
                    config.shadow_id, caller_id="system", days=self.config.evaluation_window_days
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
                rankings = engine.rank_shadows(performances, {}, today,
                                                market_accuracy=market_accuracy if market_accuracy else None,
                                                wfe_results=None)
                result.rankings = rankings
                for rr in rankings:
                    agent_config = self.state_db.get_shadow(rr.shadow_id, caller_id="system")
                    if agent_config:
                        agent = ShadowAgent(agent_config, self.state_db, self.config)
                        agent.apply_ranking_to_snapshot(rr)

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
                            logger.info("Reset eligible: %s -- %s", config.shadow_id, reset_reason)
                            result.reset_candidates.append({
                                "shadow_id": config.shadow_id,
                                "reason": reset_reason,
                                "date": today,
                            })
                    except Exception as e:
                        logger.debug("Plateau/reset check failed for %s: %s", config.shadow_id, e)

                wfe_ratios: dict[str, float] = {}
                try:
                    from marketmind.shadows.ranking_engine import WalkForwardValidator
                    wf_validator = WalkForwardValidator()
                    for config in visible:
                        snapshots = self.state_db.get_snapshot_history(
                            config.shadow_id, caller_id="system", days=max(365, wf_validator.min_career_days)
                        )
                        if not snapshots:
                            continue
                        wf_result = wf_validator.validate(config.shadow_id, snapshots)
                        if not wf_result.skipped:
                            wfe_ratios[config.shadow_id] = wf_result.wfe_ratio
                        if wf_result.skipped:
                            logger.debug(
                                "WFE skipped for %s: %s", config.shadow_id, wf_result.skip_reason
                            )
                            continue
                        if wf_result.is_overfit:
                            logger.warning(
                                "WFE overfit detected: %s (WFE=%.3f, IS=%.4f, OOS=%.4f, "
                                "OOS_acc=%.2f, windows=%d, binomial_p=%.4f)",
                                config.shadow_id, wf_result.wfe_ratio,
                                wf_result.mean_is_deflated, wf_result.mean_oos_deflated,
                                wf_result.oos_directional_accuracy, wf_result.total_windows,
                                wf_result.binomial_p_value
                            )
                            result.ecosystem_alerts.append({
                                "type": "wfe_overfit",
                                "shadow_id": config.shadow_id,
                                "wfe_ratio": wf_result.wfe_ratio,
                                "date": today,
                            })
                except Exception as e:
                    logger.error("Walk-forward validation failed: %s", e)

        except Exception as e:
            logger.error("Ranking computation failed: %s", e)

        # 5b. Paper-to-live gap calibration
        try:
            from marketmind.shadows.paper_live_gap import PaperLiveGapManager
            gap_manager = PaperLiveGapManager(self.state_db, self.config)
            for config in visible:
                trades = self.state_db.get_trade_history(config.shadow_id, caller_id="system", limit=100)
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

        # 6. Detect collusion
        try:
            collusion = CollusionDetector(self.config)
            collusion_flags = collusion.run_daily_check(today, all_votes, market_data)
            result.collusion_flags = collusion_flags
            for flag in collusion_flags:
                self.state_db.record_collusion_flag(flag)
        except Exception as e:
            logger.error("Collusion detection failed: %s", e)

        # 6.4 Shadow health monitor
        try:
            from marketmind.shadows.shadow_health_monitor import ShadowHealthMonitor
            health_monitor = ShadowHealthMonitor(state_db=self.state_db)
            for sid, output in result.shadow_analyses.items():
                raw_text = self.state_db.get_raw_output(sid, today, caller_id="system") or ""
                snapshot = health_monitor.run_daily_check(
                    sid, raw_text, len(output.insights), today
                )
                if snapshot.alerts:
                    result.health_alerts[sid] = snapshot.alerts
                    logger.info("Health alert for %s: %s", sid, snapshot.alerts)
        except Exception as e:
            logger.error("Shadow health monitor failed: %s", e)

        # 6.5 Ecosystem audit
        try:
            from marketmind.shadows.ecosystem_auditor import EcosystemAuditor
            auditor = EcosystemAuditor()
            ecosystem_alerts = auditor.run_audit(all_votes, today)
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

        # 6.55 Ecosystem health
        try:
            from marketmind.shadows.ecosystem_health import EcosystemHealthMonitor
            eco_health = EcosystemHealthMonitor()
            token_data: dict[str, list] = {}
            for config in visible:
                tokens = self.state_db.get_token_history(config.shadow_id, days=30)
                if tokens:
                    token_data[config.shadow_id] = tokens
            eco_snapshot = eco_health.run_daily_check(all_votes, token_data, today)
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

        # 6.6 Memory update
        if getattr(self.config, 'crystallization_enabled', False):
            try:
                await self._update_shadow_memory(result, today)
            except Exception as e:
                logger.error("Shadow memory update failed: %s", e)

        # 6.7 Crystallization check
        if getattr(self.config, 'crystallization_enabled', False):
            try:
                crystallization_results = await self._run_crystallization_check()
                logger.info(
                    "Crystallization complete: %d results",
                    len(crystallization_results),
                )
                from marketmind.shadows.knowledge_filter import KnowledgeFilter
                kf = KnowledgeFilter()
                for cr in crystallization_results:
                    for source_id in cr.source_insight_ids:
                        kf.record_crystallization_result(
                            source_id, cr.action,
                            source_shadow_id=source_id.split(":")[1] if ":" in source_id else ""
                        )
                from marketmind.shadows.methodology_injector import MethodologyInjector
                injector = MethodologyInjector(self.state_db)
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

        today_day = datetime.strptime(today, "%Y-%m-%d").day

        # 6.8 AEL Evolution
        if getattr(self.config, 'ael_experiment_enabled', False):
            try:
                from marketmind.shadows.ael_evolution import AELEvolutionEngine
                ael = AELEvolutionEngine(state_db=self.state_db)
                debrief_day = getattr(self.config, 'ael_debrief_day', 1)

                if today_day == debrief_day:
                    treatment_ids = {
                        "daredevil:range_bound:sideways_scout",
                        "daredevil:momentum:trend_chaser",
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
                                active_lessons = ael.get_active_lessons(sid)
                                from marketmind.shadows.methodology_injector import MethodologyInjector
                                MethodologyInjector(self.state_db).inject_lessons(
                                    sid, active_lessons
                                )
                            logger.info(
                                "AEL debrief for %s: lesson %s", sid,
                                "injected" if injected else "rejected (cap)"
                            )
                        result.ael_debriefs.append(debrief)
            except Exception as e:
                logger.error("AEL evolution step failed: %s", e)

        # 6.9 Quarterly systemic review
        _quarter_ends = {"03-31", "06-30", "09-30", "12-31"}
        _today_md = today[5:]
        if _today_md in _quarter_ends:
            try:
                from marketmind.shadows.ael_evolution import AELEvolutionEngine
                ael_q = AELEvolutionEngine(state_db=self.state_db)
                eco_summary = {
                    "active_shadows": result.active_shadows,
                    "avg_win_rate": sum(
                        p.win_rate for p in performances.values()
                    ) / max(len(performances), 1) if performances else 0.0,
                    "avg_cum_return": sum(
                        p.cumulative_return for p in performances.values()
                    ) / max(len(performances), 1) if performances else 0.0,
                    "plateau_count": len(result.plateau_flags),
                    "reset_count": len(result.reset_candidates),
                }
                col_summary = {
                    "total_flags": len(result.collusion_flags),
                    "herding_pct": 0.0,
                    "convergence_pct": 0.0,
                    "avg_agreement": 0.0,
                }
                _year = today[:4]
                _q = {"03": "Q1", "06": "Q2", "09": "Q3", "12": "Q4"}.get(today[5:7], "Q?")
                quarter = f"{_year}-{_q}"
                review = await ael_q.run_quarterly_review(
                    eco_summary, col_summary, quarter
                )
                logger.info(
                    "Quarterly review for %s: %d action items, %d risks",
                    quarter, len(review.get("action_items", [])),
                    len(review.get("key_risks", []))
                )
                try:
                    from marketmind.storage.archivist import get_archivist
                    with get_archivist() as archivist:
                        archivist.save_json(
                            "review", f"quarterly_{quarter}",
                            {"quarter": quarter, **review}
                        )
                except Exception:
                    pass
            except Exception as e:
                logger.error("Quarterly review failed: %s", e)

        # 7. Check challenger conditions + execute trials
        try:
            challenger = ChallengerEngine(self.state_db, self.config)
            for config in visible:
                stage = challenger.check_elimination_stage(config.shadow_id)
                if stage.current_stage >= 2:
                    result.challenger_actions.append(
                        f"Shadow {config.shadow_id} at stage {stage.current_stage}"
                    )
            await self._execute_challenger_trials(challenger, result)
        except Exception as e:
            logger.error("Challenger check failed: %s", e)

        # 7.5 Method breeding
        if today_day % 7 == 1:
            try:
                from marketmind.shadows.method_breeding import maintain_population
                maintain_population(min_active=6, max_active=15)
                logger.info("Methodology population maintained")
            except Exception as e:
                logger.error("Method breeding failed: %s", e)

        # 8. Audit emergency quotas
        try:
            auditor = EmergencyQuotaAuditor(self.state_db, self.config)
            pending = self.state_db.get_pending_emergency_audits()
            if pending:
                audits = auditor.audit_pending([q.id for q in pending if q.id])
                result.emergency_audits = audits
        except Exception as e:
            logger.error("Emergency quota audit failed: %s", e)

        return result

    # ── Memory & Crystallization ──────────────────────────────────────────

    async def _update_shadow_memory(
        self, result: ShadowOrchestrationResult, today: str
    ) -> None:
        from marketmind.shadows.shadow_memory import ShadowMemoryStore
        from marketmind.shadows.shadow_agent import ExternalObservation

        store = ShadowMemoryStore(self.state_db)

        for shadow_id, analysis in result.shadow_analyses.items():
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
            len(result.shadow_analyses),
        )

    async def _run_crystallization_check(self) -> list:
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

    async def _execute_challenger_trials(
        self, challenger: "ChallengerEngine", result: ShadowOrchestrationResult
    ) -> None:
        from marketmind.shadows.methodology_injector import MethodologyInjector
        injector = MethodologyInjector(self.state_db)

        active_challengers = self.state_db.get_active_shadows("challenger")
        for ch_config in active_challengers:
            target_id = ch_config.parent_shadow_id
            if not target_id:
                continue

            ch_snaps = self.state_db.get_snapshot_history(ch_config.shadow_id, caller_id="system", days=90)
            tg_snaps = self.state_db.get_snapshot_history(target_id, caller_id="system", days=90)
            if len(ch_snaps) < 10 or len(tg_snaps) < 10:
                continue

            trial = await challenger.run_comparison_trial(ch_config.shadow_id, target_id)
            verdict = trial.verdict

            if verdict == "REPLACE_TARGET":
                target_config = self.state_db.get_shadow(target_id, caller_id="system")
                if target_config:
                    self.state_db.eliminate_shadow(target_id, "challenger_replaced")
                    ch_config_new = self.state_db.get_shadow(ch_config.shadow_id, caller_id="system")
                    if ch_config_new:
                        self.state_db.update_shadow_type(
                            ch_config.shadow_id,
                            target_config.shadow_type
                        )
                    try:
                        from marketmind.shadows.ael_evolution import AELEvolutionEngine
                        ael = AELEvolutionEngine(state_db=self.state_db)
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
                    self.state_db.eliminate_shadow(ch_config.shadow_id, "challenger_max_extensions")
                    result.challenger_actions.append(
                        f"MAX_EXTENSIONS for {ch_config.shadow_id} -- restoring {target_id}"
                    )
