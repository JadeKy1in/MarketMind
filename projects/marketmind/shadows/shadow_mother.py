"""Shadow Mother — event detection, temp shadow lifecycle, daily orchestration."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_agent import ShadowAgent, ShadowAnalysisOutput, ShadowVote
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.shadow_mother")


@dataclass
class DetectedEvent:
    event_id: str
    event_type: str          # "cb_shock" | "geopolitical" | "vol_shock" | "personnel"
    description: str
    affected_assets: list[str]
    impact_score: float      # 0-1 normalized impact
    detected_at: str         # ISO 8601
    vix_level: float | None = None
    max_zscore: float | None = None
    news_volume: int | None = None


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
    ael_debriefs: list = field(default_factory=list)       # Phase 7
    challenger_actions: list[str] = field(default_factory=list)
    emergency_audits: list[str] = field(default_factory=list)


class ShadowMother:
    """Detects events, creates/destroys temporary shadows, manages event lifecycle."""

    def __init__(self, config: ShadowSettings, state_db: ShadowStateDB):
        self.config = config
        self.state_db = state_db
        self._cleanup_stale_temp_shadows()

    def _cleanup_stale_temp_shadows(self) -> int:
        """On init: destroy any temp_event shadows that have exceeded lifespan."""
        cleaned = 0
        for shadow in self.state_db.get_active_shadows("temp_event"):
            if self.check_destruction_conditions(shadow.shadow_id):
                logger.info("Startup cleanup: destroying stale temp shadow %s", shadow.shadow_id)
                self.state_db.eliminate_shadow(shadow.shadow_id, "startup_cleanup_stale")
                cleaned += 1
        return cleaned

    # ── Event scanning ───────────────────────────────────────────────────

    async def scan_events(self, news_items: list[dict]) -> list[DetectedEvent]:
        """Scan news for trigger events. Returns detected events sorted by impact."""
        events = []
        events.extend(self.detect_cb_shock(news_items))
        events.extend(self.detect_geopolitical(news_items))
        events.extend(self.detect_vol_shock(None))  # market_data passed separately
        events.extend(self.detect_personnel_change(news_items))
        events.sort(key=lambda e: e.impact_score, reverse=True)
        return events

    def detect_cb_shock(self, news_items: list[dict]) -> list[DetectedEvent]:
        """E1: Central bank action |actual - expected| >= 50bp."""
        cb_keywords = [
            r'(?:Fed|Federal Reserve|ECB|BOJ|BOE|PBOC|RBA|RBNZ|BOC|SNB)\s',
            r'(?:rate|hike|cut|ease|tighten|basis point|bp)\s',
            r'(?:surprise|unexpected|vs\s+\d+(?:\.\d+)?%\s+expected)',
        ]
        return self._detect_by_keywords(
            news_items, "cb_shock", cb_keywords, base_impact=0.6
        )

    def detect_geopolitical(self, news_items: list[dict]) -> list[DetectedEvent]:
        """E2: VIX ratio >= 1.5 AND delta >= 5 points."""
        geo_keywords = [
            r'(?:war|conflict|sanctions|tensions?|missile|invasion|military|coup)',
            r'(?:geopolitical|crisis|escalation|attack|embargo)',
            r'(?:VIX\s+(?:surge|spike|jump|soar)s?)',
        ]
        return self._detect_by_keywords(
            news_items, "geopolitical", geo_keywords, base_impact=0.5
        )

    def detect_vol_shock(self, market_data: dict[str, float] | None = None) -> list[DetectedEvent]:
        """E3: Single-asset 24h |return| >= 5 * sigma_60d."""
        if market_data is None:
            return []
        events = []
        for ticker, zscore in market_data.items():
            abs_z = abs(zscore)
            if abs_z >= 5.0:
                event_id = hashlib.sha256(
                    f"vol_shock:{ticker}:{datetime.now(timezone.utc).date()}".encode()
                ).hexdigest()[:16]
                impact = min(abs_z / 10.0, 1.0)
                events.append(DetectedEvent(
                    event_id=event_id,
                    event_type="vol_shock",
                    description=f"{ticker} volatility shock: {abs_z:.1f} sigma move",
                    affected_assets=[ticker],
                    impact_score=impact,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    max_zscore=abs_z,
                ))
        return events

    def detect_personnel_change(self, news_items: list[dict]) -> list[DetectedEvent]:
        """E4: Key personnel change via keyword detection."""
        personnel_keywords = [
            r'(?:Treasury Secretary|Fed Chair|SEC Chair|CFTC|OCC|FDIC)\b',
            r'(?:resign|fired|replaced|appointed|nominated|confirmed)\b',
        ]
        return self._detect_by_keywords(
            news_items, "personnel", personnel_keywords, base_impact=0.4
        )

    def _detect_by_keywords(self, news_items: list, event_type: str,
                             keywords: list[str], base_impact: float) -> list[DetectedEvent]:
        """Generic keyword-based event detection. Handles both dict and object items."""
        events = []
        seen_headlines = set()
        for item in news_items:
            headline = (
                str(getattr(item, "headline", "")) or
                str(getattr(item, "title", "")) or
                str(item.get("headline", "")) if hasattr(item, "get") else ""
            )
            if not headline or headline in seen_headlines:
                continue
            matched = sum(1 for kw in keywords if re.search(kw, headline, re.IGNORECASE))
            if matched >= 2:  # at least 2 keyword groups match
                seen_headlines.add(headline)
                event_id = hashlib.sha256(
                    f"{event_type}:{headline}:{datetime.now(timezone.utc).date()}".encode()
                ).hexdigest()[:16]
                impact = min(base_impact + matched * 0.1, 1.0)
                # Extract ticker mentions
                tickers = re.findall(r'\b[A-Z]{1,5}\b', headline)
                events.append(DetectedEvent(
                    event_id=event_id,
                    event_type=event_type,
                    description=headline[:200],
                    affected_assets=tickers[:5],
                    impact_score=impact,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    news_volume=1,
                ))
        return events

    # ── Prioritization ───────────────────────────────────────────────────

    def prioritize_events(self, events: list[DetectedEvent],
                          max_shadows: int = 5) -> list[DetectedEvent]:
        """Top N events by impact_score get shadows."""
        sorted_events = sorted(events, key=lambda e: e.impact_score, reverse=True)
        return sorted_events[:max_shadows]

    # ── Temp shadow lifecycle ────────────────────────────────────────────

    async def create_temp_shadows(self, events: list[DetectedEvent]) -> list[str]:
        """Create Form C milestone-triggered event recorders (Phase 4).

        NOT a full shadow. A recorder that:
        - Day 1: Pro initial framework analysis (1 Pro call)
        - Day 2-9: Python silent recording (0 Pro calls)
        - Day 5: If volatility >3σ, trigger Pro check (≤1 extra Pro call)
        - Day 10: Pro mid-term review (1 Pro call)
        - Day 30: Pro final validation + Flash summary (1 Pro + 1 Flash)

        Total: 3-5 Pro calls per 30-day event (vs. 30 previously).
        """
        created_ids = []
        for event in events:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            shadow_id = f"temp_event:{event.event_type}:{ts}_{event.event_id[:8]}"

            # Form C: milestone-triggered methodology
            methodology_prompt = (
                f"[FORM_C_EVENT_RECORDER] Event: {event.description}. "
                f"Affected assets: {', '.join(event.affected_assets[:5])}. "
                f"Impact score: {event.impact_score:.2f}. "
                f"You are a milestone-triggered event recorder. "
                f"Day 1: establish analysis framework. "
                f"Day 2-9: only record OHLC + relevant news (no analysis). "
                f"Day 5: if any affected asset moves >3σ, analyze whether driven by original event. "
                f"Day 10: mid-term review of event impact. "
                f"Day 30: final validation report comparing actual impact to Day 1 prediction. "
                f"Max 30-day lifespan. Be concise — you have limited Pro calls."
            )

            config = ShadowConfig(
                shadow_id=shadow_id,
                shadow_type="temp_event",
                display_name=f"FormC {event.event_type} {ts}",
                methodology_prompt=methodology_prompt,
                virtual_capital=0.0,  # Read-only recorder, no trading
                domain=event.affected_assets[0] if event.affected_assets else "macro",
                temperature=0.3,
                max_positions=0,
            )
            try:
                self.state_db.create_shadow(config)
                created_ids.append(shadow_id)
                logger.info("Created Form C recorder %s for event %s", shadow_id, event.event_type)
            except ValueError as e:
                logger.warning("Form C recorder %s creation failed: %s", shadow_id, e)

        return created_ids

    def check_destruction_conditions(self, shadow_id: str) -> bool:
        """Check if a temporary shadow should be destroyed."""
        config = self.state_db.get_shadow(shadow_id)
        if config is None:
            return False
        if config.shadow_type != "temp_event":
            return False
        # Check max lifespan
        created = datetime.fromisoformat(config.created_at.replace("Z", "+00:00"))
        days_alive = (datetime.now(timezone.utc) - created).days
        if days_alive >= 30:
            return True
        # If shadow has been inactive (no snapshots or no trades)
        snapshots = self.state_db.get_snapshot_history(shadow_id, days=5)
        if len(snapshots) < 1:
            return False  # New shadow, not yet active
        # Check for 5+ no-trade days
        if days_alive >= 5 and len(snapshots) < days_alive:
            return True
        return False

    async def destroy_temp_shadow(self, shadow_id: str) -> None:
        """Destroy shadow, archive knowledge, notify relevant expert shadows."""
        self.state_db.eliminate_shadow(shadow_id, "temp_shadow_expired")
        logger.info("Destroyed temp shadow %s", shadow_id)

    # ── Missed path shadows ──────────────────────────────────────────────

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
                virtual_capital=0.0,  # Read-only, no trading
                max_positions=0,
            )
            try:
                self.state_db.create_shadow(config)
                created_ids.append(shadow_id)
            except ValueError:
                pass
        return created_ids

    # ── Status cards ─────────────────────────────────────────────────────

    async def generate_status_cards(self, date: str) -> dict[str, dict]:
        """Generate today's status card for every active shadow."""
        cards = {}
        for shadow in self.state_db.get_visible_shadows():
            from marketmind.shadows.shadow_agent import ShadowAgent
            agent = ShadowAgent(shadow, self.state_db, self.config)
            cards[shadow.shadow_id] = await agent.receive_status_card()
        return cards

    # ── Daily orchestration ──────────────────────────────────────────────

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
        6.6. Run crystallization check (insight → hypothesis → validate)
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

        # Destroy expired temp shadows
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

        # 4. Run shadow analyses + collect votes
        from marketmind.shadows.shadow_agent import create_shadow_agent
        all_votes: list = []
        semaphore = asyncio.Semaphore(self.config.max_concurrent_shadows)
        async def _run_one(config):
            async with semaphore:
                try:
                    agent = create_shadow_agent(config, self.state_db, self.config)
                    output = await agent.run_daily_analysis(news_items, market_data)
                    # Persist votes for backtest/audit
                    if output.votes:
                        try:
                            self.state_db.save_votes(config.shadow_id, today, output.votes)
                        except Exception as e:
                            logger.error("Failed to save votes for %s: %s", config.shadow_id, e)
                    return config.shadow_id, output, None
                except Exception as e:
                    logger.error("Shadow %s analysis failed: %s", config.shadow_id, e)
                    return config.shadow_id, None, e

        tasks = [_run_one(c) for c in visible]
        results_list = await asyncio.gather(*tasks)
        for sid, output, err in results_list:
            if output is not None:
                result.shadow_analyses[sid] = output
                result.votes_collected += len(output.votes)
                all_votes.extend(output.votes)
                # Populate insights_generated + votes_produced in today's snapshot (Phase 2)
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

        # 5. Compute rankings (if we have performance data)
        try:
            engine = RankingEngine(self.config)
            performances = {}
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
                    # Count actual abstention days from snapshot history
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
                rankings = engine.rank_shadows(performances, {}, today)
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

                        # Plateau detection
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

                        # Reset eligibility
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

        # 6. Detect collusion
        try:
            collusion = CollusionDetector(self.config)
            collusion_flags = collusion.run_daily_check(today, all_votes, market_data)
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

        # 6.55 Ecosystem health — collective degradation detection (Phase 3, Item 12)
        try:
            from marketmind.shadows.ecosystem_health import EcosystemHealthMonitor
            eco_health = EcosystemHealthMonitor()
            token_data = {}
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

        # 6.6 Memory update — ingest today's votes and analyses into shadow memory
        if getattr(self.config, 'crystallization_enabled', False):
            try:
                await self._update_shadow_memory(result, today)
            except Exception as e:
                logger.error("Shadow memory update failed: %s", e)

        # 6.7 Crystallization check — insight → hypothesis → validate → promote/retire
        if getattr(self.config, 'crystallization_enabled', False):
            try:
                crystallization_results = await self._run_crystallization_check()
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

        # 6.8 AEL Evolution — monthly debrief (Phase 7, gated behind config flag)
        if getattr(self.config, 'ael_experiment_enabled', False):
            try:
                from marketmind.shadows.ael_evolution import AELEvolutionEngine
                ael = AELEvolutionEngine(state_db=self.state_db)
                debrief_day = getattr(self.config, 'ael_debrief_day', 1)
                today_day = int(today.split("-")[2])  # extract day-of-month

                # Run debrief on configured day of month
                if today_day == debrief_day:
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
                                from marketmind.shadows.methodology_evolver import MethodologyInjector
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

        # 7. Check challenger conditions + execute trials (P0-2)
        try:
            challenger = ChallengerEngine(self.state_db, self.config)
            for config in visible:
                stage = challenger.check_elimination_stage(config.shadow_id)
                if stage.current_stage >= 2:
                    result.challenger_actions.append(
                        f"Shadow {config.shadow_id} at stage {stage.current_stage}"
                    )
            # Execute pending challenger trials
            await self._execute_challenger_trials(challenger, result)
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

        return result

    # ── Memory & Crystallization ──────────────────────────────────────────

    async def _update_shadow_memory(
        self, result: ShadowOrchestrationResult, today: str
    ) -> None:
        """Ingest today's votes and analyses into shadow memory.

        Stores shadow analyses as episodic memory observations, preserving
        the reasoning chain for knowledge crystallization.
        """
        from marketmind.shadows.shadow_memory import ShadowMemoryStore
        from marketmind.shadows.shadow_agent import ExternalObservation

        store = ShadowMemoryStore(self.state_db)

        for shadow_id, analysis in result.shadow_analyses.items():
            # Create observations from insights
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

            # Create observations from votes
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
        """Run knowledge crystallization for shadows with sufficient vote history.

        Queries episodic memory for insights with high belief but low confidence,
        backtest validates against shadow_votes, and promotes or retires insights.
        """
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

    # ── Queries ──────────────────────────────────────────────────────────

    def get_active_temp_shadows(self) -> list[str]:
        return [s.shadow_id for s in self.state_db.get_active_shadows("temp_event")]

    async def _execute_challenger_trials(
        self, challenger: "ChallengerEngine", result: ShadowOrchestrationResult
    ) -> None:
        """Execute pending challenger comparison trials (P0-2).

        For each challenger shadow with sufficient trial data:
        1. Run paired t-test comparison (challenger vs target)
        2. REPLACE_TARGET: eliminate target, promote challenger, transfer knowledge
        3. RESTORE_TARGET: eliminate challenger
        4. INCONCLUSIVE: extend trial by 10 days (max 2 extensions)
        """
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
                    # Update challenger's shadow_type to inherit target's role
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
                    # Extend trial — challenger continues collecting data
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

    def get_event_status(self, event_id: str) -> str:
        """Returns "active" | "resolved" | "decayed" | "unknown"."""
        for shadow_id in self.get_active_temp_shadows():
            if event_id in shadow_id:
                shadow = self.state_db.get_shadow(shadow_id)
                if shadow is None:
                    return "resolved"
                created = datetime.fromisoformat(shadow.created_at.replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - created).days
                if days > 20:
                    return "decayed"
                return "active"
        return "unknown"
