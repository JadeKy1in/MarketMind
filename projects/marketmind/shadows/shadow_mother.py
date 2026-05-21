"""Shadow Mother — daily orchestration facade for the shadow ecosystem.

Delegates event detection, temp shadow lifecycle, ranking/surveillance orchestration,
knowledge management, and challenger execution to focused modules.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_agent import ShadowAnalysisOutput
from marketmind.config.settings import ShadowSettings
from marketmind.shadows.event_detector import EventDetector, DetectedEvent
from marketmind.shadows.temp_shadow_lifecycle import TempShadowLifecycle
from marketmind.shadows.orchestrator import Orchestrator
from marketmind.shadows.knowledge_manager import KnowledgeManager
from marketmind.shadows.challenger_execution import ChallengerExecutor
from marketmind.shadows.market_data_fetcher import MarketDataFetcher

logger = logging.getLogger("marketmind.shadows.shadow_mother")


@dataclass
class TempShadowSpec:
    event_id: str
    shadow_name: str
    methodology_base: str    # which expert template to clone from
    domain: str
    virtual_capital: float   # $10K-$20K based on event impact
    max_lifespan_days: int = 30
    flash_quota_per_day: int = 3


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
    ael_debriefs: list = field(default_factory=list)
    challenger_actions: list[str] = field(default_factory=list)
    emergency_audits: list[str] = field(default_factory=list)


class ShadowMother:
    """Detects events, creates/destroys temporary shadows, manages event lifecycle.

    Delegates to: EventDetector, TempShadowLifecycle, Orchestrator, KnowledgeManager,
    ChallengerExecutor. The orchestrate_daily_cycle method sequences all steps.
    """

    def __init__(self, config: ShadowSettings, state_db: ShadowStateDB):
        self.config = config
        self.state_db = state_db
        self._event_detector = EventDetector()
        self._temp_lifecycle = TempShadowLifecycle(state_db, config)
        self._orchestrator = Orchestrator(state_db, config)
        self._knowledge_manager = KnowledgeManager(state_db, config)
        self._challenger_executor = ChallengerExecutor(state_db)
        self._temp_lifecycle.cleanup_stale()

    # ── Event detection (delegate to EventDetector) ────────────────────────

    async def scan_events(self, news_items: list[dict]) -> list[DetectedEvent]:
        """Scan news for trigger events. Returns detected events sorted by impact."""
        return await self._event_detector.scan_events(news_items)

    def detect_cb_shock(self, news_items: list[dict]) -> list[DetectedEvent]:
        """E1: Central bank action |actual - expected| >= 50bp."""
        return self._event_detector.detect_cb_shock(news_items)

    def detect_geopolitical(self, news_items: list[dict]) -> list[DetectedEvent]:
        """E2: VIX ratio >= 1.5 AND delta >= 5 points."""
        return self._event_detector.detect_geopolitical(news_items)

    def detect_vol_shock(self, market_data: dict[str, float] | None = None) -> list[DetectedEvent]:
        """E3: Single-asset 24h |return| >= 5 * sigma_60d."""
        return self._event_detector.detect_vol_shock(market_data)

    def detect_personnel_change(self, news_items: list[dict]) -> list[DetectedEvent]:
        """E4: Key personnel change via keyword detection."""
        return self._event_detector.detect_personnel_change(news_items)

    def _detect_by_keywords(self, news_items: list, event_type: str,
                             keywords: list[str], base_impact: float) -> list[DetectedEvent]:
        """Generic keyword-based event detection."""
        return self._event_detector._detect_by_keywords(news_items, event_type, keywords, base_impact)

    def prioritize_events(self, events: list[DetectedEvent],
                          max_shadows: int = 5) -> list[DetectedEvent]:
        """Top N events by impact_score get shadows."""
        return self._event_detector.prioritize_events(events, max_shadows)

    # ── Temp shadow lifecycle (delegate to TempShadowLifecycle) ────────────

    async def create_temp_shadows(self, events: list[DetectedEvent]) -> list[str]:
        """Create Form C milestone-triggered event recorders (Phase 4)."""
        return await self._temp_lifecycle.create_temp_shadows(events)

    def check_destruction_conditions(self, shadow_id: str) -> bool:
        """Check if a temporary shadow should be destroyed."""
        return self._temp_lifecycle.check_destruction_conditions(shadow_id)

    async def destroy_temp_shadow(self, shadow_id: str) -> None:
        """Destroy shadow, archive knowledge, notify relevant expert shadows."""
        await self._temp_lifecycle.destroy_temp_shadow(shadow_id)

    def get_active_temp_shadows(self) -> list[str]:
        """Return shadow_id list of all active temp_event shadows."""
        return self._temp_lifecycle.get_active_temp_shadows()

    def get_event_status(self, event_id: str) -> str:
        """Returns "active" | "resolved" | "decayed" | "unknown"."""
        return self._temp_lifecycle.get_event_status(event_id)

    # ── Missed path shadows ────────────────────────────────────────────────

    async def create_missed_path_shadows(self, rejected_directions: list[str]) -> list[str]:
        """Gate 1: user chose direction A. Create missed_path shadows for B and C."""
        created_ids = []
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

    # ── Keyword-triggered temp shadows ──────────────────────────────────────

    def detect_keyword_triggers(self, user_text: str) -> list[str]:
        """Delegate to EventDetector's session-level keyword frequency counter."""
        return self._event_detector.detect_keyword_triggers(user_text)

    # ── Beta shadows ───────────────────────────────────────────────────────

    async def create_beta_shadow(self, template_shadow_id: str,
                                  methodology_variant: dict) -> str:
        """Create a beta shadow from an expert template with methodology tweaks.
        Beta shadows are ISOLATED — excluded from ranking, voting, collusion detection."""
        template = self.state_db.get_shadow(template_shadow_id)
        if not template:
            raise ValueError(f"Template shadow '{template_shadow_id}' not found")

        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        shadow_id = f"beta:{template.domain or 'general'}:{ts}"

        variant_text = " ".join(f"{k}: {v}" for k, v in methodology_variant.items())
        methodology = (
            f"{template.methodology_prompt}\n\n"
            f"[BETA METHODOLOGY VARIANT]\n"
            f"Methodology tweaks under test: {variant_text}\n"
            f"Status: sandboxed. This output is isolated from ranking and consensus."
        )

        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="beta",
            display_name=f"Beta {template.display_name}",
            methodology_prompt=methodology,
            virtual_capital=template.virtual_capital,
            max_positions=template.max_positions,
            model=template.model,
            temperature=template.temperature,
            domain=template.domain,
            parent_shadow_id=template_shadow_id,
            generation=template.generation + 1,
            status="beta",
        )
        self.state_db.create_shadow(config)
        logger.info("Created beta shadow %s from template %s", shadow_id, template_shadow_id)
        return shadow_id

    async def promote_beta_shadow(self, shadow_id: str) -> bool:
        """Promote beta to active after 20-day positive track record.
        Requires Brier score < 0.20 and Sharpe > 0.5 over evaluation window."""
        shadow = self.state_db.get_shadow(shadow_id)
        if not shadow:
            logger.warning("promote_beta_shadow: shadow %s not found", shadow_id)
            return False
        if shadow.status != "beta":
            logger.warning("promote_beta_shadow: shadow %s is not beta (status=%s)",
                           shadow_id, shadow.status)
            return False

        snapshots = self.state_db.get_snapshot_history(shadow_id, days=20)
        if len(snapshots) < 20:
            logger.info("promote_beta_shadow: %s has %d days (< 20 required)",
                        shadow_id, len(snapshots))
            return False

        avg_sharpe = sum(
            s.sharpe_ratio for s in snapshots if s.sharpe_ratio is not None
        ) / max(len(snapshots), 1)
        cumulative_return = snapshots[-1].cumulative_return_pct or 0.0

        if avg_sharpe <= 0.5:
            logger.info("promote_beta_shadow: %s Sharpe %.3f <= 0.5", shadow_id, avg_sharpe)
            return False

        self.state_db.update_shadow_status(shadow_id, "active")
        logger.info("Promoted beta shadow %s to active (Sharpe=%.3f, return=%.2f%%)",
                     shadow_id, avg_sharpe, cumulative_return * 100)
        return True

    # ── Status cards ───────────────────────────────────────────────────────

    async def generate_status_cards(self, date: str) -> dict[str, dict]:
        """Generate today's status card for every active shadow."""
        from marketmind.shadows.shadow_agent import ShadowAgent
        cards = {}
        for shadow in self.state_db.get_visible_shadows():
            agent = ShadowAgent(shadow, self.state_db, self.config)
            cards[shadow.shadow_id] = await agent.receive_status_card()
        return cards

    # ── Daily orchestration ────────────────────────────────────────────────

    async def orchestrate_daily_cycle(self, news_items: list[dict],
                                       market_data: dict,
                                       rejected_directions: list[str] | None = None
                                       ) -> ShadowOrchestrationResult:
        """Full daily cycle for the shadow ecosystem:

        1. Scan events -> create/destroy temp shadows
        2. Create missed_path shadows, count visible
        3. Run all shadow analyses, collect votes
        4. Compute rankings, detect plateaus, calibrate gaps
        5. Ecosystem surveillance (collusion, health, blind-spots)
        6. Knowledge management (memory update, crystallization)
        7. AEL evolution (monthly debrief)
        8. Maintenance (challenger trials, breeding, emergency audits)
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = ShadowOrchestrationResult(date=today)

        # 1. Scan events, create/destroy temp shadows
        await self._step_event_lifecycle(news_items, result)

        # 2. Setup missed-path shadows, count visible shadows
        visible = await self._step_setup_ecosystem(rejected_directions, result)

        # 3. Run all shadow analyses, collect votes
        all_votes = await self._step_collect_votes(news_items, market_data, visible, today, result)

        # 3b. P2-4: Fetch external market data, compute per-shadow accuracy
        market_accuracies = await self._step_market_anchor(today, result)

        # 4-5. Rankings + plateau detection + paper-live gap + surveillance
        # Beta shadows excluded from ranking, collusion, and challenger engine.
        ranking_eligible = self.state_db.get_ranking_eligible_shadows()
        performances = await self._orchestrator.step_rank_and_calibrate(
            ranking_eligible, today, result, market_data,
            market_accuracies=market_accuracies)
        await self._orchestrator.step_surveillance(
            all_votes, market_data, today, result, ranking_eligible)

        # 6. Knowledge management (memory update, crystallization)
        await self._step_knowledge_management(result, today)

        # 7. AEL evolution (monthly debrief)
        await self._step_ael_evolution(performances, market_data, today, result)

        # 8. Maintenance (challenger trials, breeding, emergency quotas)
        await self._step_maintenance(ranking_eligible, result)

        return result

    # ── Step 1: Event lifecycle ────────────────────────────────────────────

    async def _step_event_lifecycle(self, news_items: list[dict],
                                     result: ShadowOrchestrationResult) -> None:
        """Scan events, create temp shadows for prioritized events, destroy expired ones."""
        events = await self.scan_events(news_items)
        prioritized = self.prioritize_events(events)
        created = await self.create_temp_shadows(prioritized)
        result.temp_shadows_created = len(created)

        # Destroy expired temp shadows
        for shadow in self.state_db.get_active_shadows("temp_event"):
            if self.check_destruction_conditions(shadow.shadow_id):
                await self.destroy_temp_shadow(shadow.shadow_id)
                result.temp_shadows_destroyed += 1

    # ── Step 2: Ecosystem setup ────────────────────────────────────────────

    async def _step_setup_ecosystem(self, rejected_directions: list[str] | None,
                                     result: ShadowOrchestrationResult) -> list:
        """Create missed-path shadows if needed, count visible shadows."""
        if rejected_directions:
            await self.create_missed_path_shadows(rejected_directions)
        visible = self.state_db.get_visible_shadows()
        result.active_shadows = len(visible)
        return visible

    # ── Step 3: Vote collection ────────────────────────────────────────────

    async def _step_collect_votes(self, news_items: list[dict], market_data: dict,
                                   visible: list, today: str,
                                   result: ShadowOrchestrationResult) -> list:
        """Run all shadow analyses in parallel, collect votes, update snapshots.

        P3-4 partial-state recovery: filters out already-completed shadows
        (cached replay) and saves a per-shadow checkpoint after EACH
        individual analysis. If the cycle crashes mid-step, the next run
        skips completed shadows and only re-runs incomplete/failed ones.
        """
        from marketmind.shadows.shadow_agent import create_shadow_agent

        # P3-4 RESUME CHECK: Filter out shadows that already completed
        # successfully in a previous (crashed) run.
        visible_to_run: list = []
        resume_count = 0
        for s in visible:
            cp = self.state_db.get_checkpoint(today, s.shadow_id)
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
        semaphore = asyncio.Semaphore(self.config.max_concurrent_shadows)

        async def _run_one(config):
            # P3-4: Save "pending" checkpoint BEFORE analysis starts
            self.state_db.save_checkpoint(
                date=today, shadow_id=config.shadow_id,
                status='pending', step=4
            )

            async with semaphore:
                try:
                    agent = create_shadow_agent(config, self.state_db, self.config)
                    output = await agent.run_daily_analysis(news_items, market_data)
                    if output.votes:
                        is_beta = config.status == "beta"
                        try:
                            if is_beta:
                                self.state_db.save_beta_analyses(
                                    config.shadow_id, today, output.votes)
                            else:
                                self.state_db.save_analyses(
                                    config.shadow_id, today, output.votes)
                        except Exception as e:
                            logger.error("Failed to save analyses for %s: %s", config.shadow_id, e)

                    # P3-4: Save successful checkpoint with cached analysis output
                    try:
                        analysis_dict = {
                            "shadow_id": output.shadow_id,
                            "date": output.date,
                            "vote_count": len(output.votes),
                            "insight_count": len(output.insights),
                            "quota_used": output.quota_used,
                            "latency_ms": output.latency_ms,
                        }
                        self.state_db.save_checkpoint(
                            date=today, shadow_id=config.shadow_id,
                            status='completed', step=4,
                            analysis_json=json.dumps(analysis_dict)
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to save completed checkpoint for %s: %s",
                            config.shadow_id, e
                        )

                    return config.shadow_id, output, None, config.status
                except Exception as e:
                    logger.error("Shadow %s analysis failed: %s", config.shadow_id, e)

                    # P3-4: Save failed checkpoint for retry on resume
                    try:
                        self.state_db.save_checkpoint(
                            date=today, shadow_id=config.shadow_id,
                            status='failed', step=4, error_message=str(e)
                        )
                    except Exception as ckpt_err:
                        logger.warning(
                            "Failed to save failure checkpoint for %s: %s",
                            config.shadow_id, ckpt_err
                        )

                    return config.shadow_id, None, e, config.status

        tasks = [_run_one(c) for c in visible_to_run]
        results_list = await asyncio.gather(*tasks)

        for sid, output, err, status in results_list:
            if output is not None:
                is_beta = (status == "beta")
                result.shadow_analyses[sid] = output
                if not is_beta:
                    result.votes_collected += len(output.votes)
                    all_votes.extend(output.votes)
                try:
                    latest = self.state_db.get_latest_snapshot(sid)
                    if latest and latest.date == today:
                        self.state_db.update_snapshot_fields(
                            sid, today,
                            insights_generated=len(output.insights),
                            votes_produced=len(output.votes),
                            flash_quota_used=output.quota_used,
                        )
                except Exception as e:
                    logger.debug("Snapshot update failed for %s: %s", sid, e)

        return all_votes

    # ── P2-4: Market anchor step ─────────────────────────────────────────

    async def _step_market_anchor(
        self, today: str, result: ShadowOrchestrationResult
    ) -> dict[str, float]:
        """Fetch external market data and compute per-shadow directional accuracy.

        Runs between vote collection and ranking. Fetches OHLCV data for
        tickers referenced by shadow analyses, stores prices in market_prices
        table, and computes directional accuracy per shadow.

        Returns dict mapping shadow_id -> market_accuracy (0.0-1.0).
        """
        market_accuracies: dict[str, float] = {}
        fetcher = MarketDataFetcher()

        # Collect unique tickers from today's shadow analyses
        tickers_needed: set[str] = set()
        for sid, output in result.shadow_analyses.items():
            analyses = getattr(output, "analyses", []) or []
            for a in analyses:
                ticker = a.get("ticker", "") if isinstance(a, dict) else getattr(a, "ticker", "")
                if ticker:
                    tickers_needed.add(ticker)

        if not tickers_needed:
            logger.debug("No tickers to fetch for market anchor")
            return market_accuracies

        # Fetch OHLCV for each ticker
        for ticker in tickers_needed:
            data = await fetcher.fetch_ohlcv(ticker, period="5d")
            if data is None:
                continue
            try:
                # Look up yesterday's close to compute next_day_return
                yesterday_prices = self.state_db.get_market_prices(
                    ticker, end_date=data["date"])
                ndr = None
                if yesterday_prices:
                    yesterday_close = yesterday_prices[-1].get("close", 0)
                    if yesterday_close and yesterday_close > 0:
                        ndr = (data["close"] - yesterday_close) / yesterday_close
                        # Update yesterday's next_day_return
                        yesterday_date = yesterday_prices[-1].get("date", "")
                        if yesterday_date:
                            conn = self.state_db._connect()
                            try:
                                conn.execute(
                                    "UPDATE market_prices SET next_day_return = ? "
                                    "WHERE ticker = ? AND date = ?",
                                    (ndr, ticker, yesterday_date))
                                conn.commit()
                            finally:
                                conn.close()

                self.state_db.insert_market_price(
                    ticker=ticker, date=data["date"],
                    open_price=data["open"], high=data["high"],
                    low=data["low"], close=data["close"],
                    volume=data["volume"],
                    next_day_return=None)
            except Exception as e:
                logger.debug("Failed to insert market price for %s: %s", ticker, e)

        # Compute per-shadow accuracy from historical analyses
        for sid in result.shadow_analyses:
            try:
                analyses = self.state_db.get_analyses_with_direction(sid, days=90)
                if not analyses:
                    continue
                correct = 0
                total = 0
                for a in analyses:
                    ndr = self.state_db.get_next_day_return(a["ticker"], a["date"])
                    if ndr is not None:
                        if fetcher.compute_accuracy(a["direction"], ndr):
                            correct += 1
                        total += 1
                if total > 0:
                    market_accuracies[sid] = correct / total
            except Exception as e:
                logger.debug("Accuracy computation failed for %s: %s", sid, e)

        return market_accuracies

    # ── Step 6: Knowledge management ───────────────────────────────────────

    async def _step_knowledge_management(self, result: ShadowOrchestrationResult,
                                          today: str) -> None:
        """Update shadow memory with today's votes/analyses, run crystallization."""
        if not getattr(self.config, 'crystallization_enabled', False):
            return

        # 6.6 Memory update — ingest today's votes and analyses into shadow memory
        try:
            await self._knowledge_manager.update_shadow_memory(result, today)
        except Exception as e:
            logger.error("Shadow memory update failed: %s", e)

        # 6.7 Crystallization check — insight -> hypothesis -> validate -> promote/retire
        try:
            crystallization_results = await self._knowledge_manager.run_crystallization_check()
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

    # ── Step 7: AEL evolution ──────────────────────────────────────────────

    async def _step_ael_evolution(self, performances: dict, market_data: dict,
                                   today: str, result: ShadowOrchestrationResult) -> None:
        """Run AEL monthly debrief if today is the configured debrief day."""
        if not getattr(self.config, 'ael_experiment_enabled', False):
            return

        try:
            from marketmind.shadows.ael_evolution import AELEvolutionEngine
            from marketmind.shadows.methodology_evolver import MethodologyInjector

            ael = AELEvolutionEngine(state_db=self.state_db)
            debrief_day = getattr(self.config, 'ael_debrief_day', 1)
            today_day = int(today.split("-")[2])

            if today_day != debrief_day:
                return

            # Build performance dicts for treatment shadows
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
                        # P1-3: Wire AEL lessons to shadow prompts via MethodologyInjector
                        active_lessons = ael.get_active_lessons(sid)
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

    # ── Step 8: Maintenance ────────────────────────────────────────────────

    async def _step_maintenance(self, visible: list,
                                 result: ShadowOrchestrationResult) -> None:
        """Run challenger checks/trials, method breeding, and emergency quota audits."""
        from marketmind.shadows.challenger_engine import ChallengerEngine
        from marketmind.shadows.emergency_quota import EmergencyQuotaAuditor

        # 7. Check challenger conditions + execute trials (P0-2)
        try:
            challenger = ChallengerEngine(self.state_db, self.config)
            for config in visible:
                stage = challenger.check_elimination_stage(config.shadow_id)
                if stage.current_stage >= 2:
                    result.challenger_actions.append(
                        f"Shadow {config.shadow_id} at stage {stage.current_stage}"
                    )
            await self._challenger_executor.execute_trials(challenger, result)
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
            auditor = EmergencyQuotaAuditor(self.state_db, self.config)
            pending = self.state_db.get_pending_emergency_audits()
            if pending:
                audits = auditor.audit_pending([q.id for q in pending if q.id])
                result.emergency_audits = audits
        except Exception as e:
            logger.error("Emergency quota audit failed: %s", e)
