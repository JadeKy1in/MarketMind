"""Shadow Mother — daily orchestration glue for the shadow ecosystem."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_agent import ShadowAgent, ShadowAnalysisOutput, ShadowDecision
from marketmind.config.settings import ShadowSettings

# Re-export types that consumers import from this module (preserve public API)
from marketmind.shadows.event_detector import DetectedEvent  # noqa: F401
from marketmind.shadows.temp_shadow_lifecycle import TempShadowSpec  # noqa: F401

from marketmind.shadows.event_detector import EventDetector
from marketmind.shadows.temp_shadow_lifecycle import TempShadowLifecycle

# ── Memory & crystallization extracted to shadows/shadow_memory_updater.py ──
from marketmind.shadows.shadow_memory_updater import update_shadow_memory, run_crystallization_check

# ── Challenger execution extracted to shadows/shadow_challenger_executor.py ──
from marketmind.shadows.shadow_challenger_executor import execute_challenger_trials

# ── Analysis runner & ranking compute extracted from this module ──
from marketmind.shadows.shadow_analysis_runner import run_shadow_analyses
from marketmind.shadows.shadow_ranking_compute import compute_market_anchor, compute_rankings

logger = logging.getLogger("marketmind.shadows.shadow_mother")

# ── Domain coverage guard ────────────────────────────────────────────────────

# Every domain that the shadow ecosystem should cover with >=1 shadow.
ALL_REQUIRED_DOMAINS: set[str] = {
    "gold", "crypto", "energy", "bonds", "volatility", "emerging",
    "tech", "financials", "healthcare", "consumer", "industrials",
    "metals", "real_estate", "fx", "macro", "short",
}


def get_all_active_domains(state_db: ShadowStateDB) -> set[str]:
    """Collect unique domain names from all visible (active) shadows.

    Args:
        state_db: ShadowStateDB instance for querying shadow configs.

    Returns:
        Set of unique domain strings for currently visible shadows.
    """
    domains: set[str] = set()
    for shadow in state_db.get_visible_shadows():
        if shadow.domain:
            domains.add(shadow.domain)
    return domains


def get_default_template(domain: str) -> ShadowConfig:
    """Build a minimal BETA ShadowConfig for a given domain.

    The returned config enters as shadow_type="beta", status="beta" so it
    undergoes the full 20-day validation cycle before ranking eligibility.

    Args:
        domain: Domain name (e.g. "tech", "macro", "gold").

    Returns:
        ShadowConfig seeded with a generic domain-specific methodology prompt.
    """
    from datetime import timezone as _tz
    ts = datetime.now(_tz).strftime("%Y%m%d%H%M%S")
    shadow_id = f"beta:auto:{domain}_{ts}"
    display_name = f"Auto-Seed {domain.title()}"
    methodology_prompt = (
        f"You are an autonomous BETA shadow covering the {domain} domain. "
        f"You have been auto-seeded because all prior {domain} shadows were "
        f"eliminated. Your methodology is under development. You analyze "
        f"{domain}-specific news, fundamentals, and technicals. "
        f"Output VOTE_START/VOTE_END blocks with direction, confidence "
        f"(0.0-1.0), thesis (1 sentence), and risk_note (1 sentence)."
    )
    return ShadowConfig(
        shadow_id=shadow_id,
        shadow_type="beta",
        display_name=display_name,
        methodology_prompt=methodology_prompt,
        virtual_capital=30000.0,
        domain=domain,
        temperature=0.35,
        status="beta",
    )


def ensure_domain_coverage(state_db: ShadowStateDB) -> None:
    """Guarantee at least one shadow per required domain.

    After challenger trials may eliminate a domain's last shadow, this
    function auto-seeds a BETA shadow for any depleted domain.

    Args:
        state_db: ShadowStateDB instance.
    """
    domains = get_all_active_domains(state_db)
    for domain in sorted(ALL_REQUIRED_DOMAINS):
        if domain not in domains:
            config = get_default_template(domain)
            config.shadow_type = "beta"
            config.status = "beta"
            try:
                state_db.create_shadow(config)
                logger.warning(
                    "Domain %s depleted — auto-seeded BETA shadow (requires 20d validation)",
                    domain,
                )
            except Exception as exc:
                logger.error(
                    "Failed to auto-seed BETA shadow for domain %s: %s", domain, exc
                )


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

        # 3.5-4. Run all shadow analyses (extracted to shadow_analysis_runner)
        shadow_analyses, votes_collected, all_votes = await run_shadow_analyses(
            self.state_db, self.config, visible, today, news_items, market_data
        )
        result.shadow_analyses.update(shadow_analyses)
        result.votes_collected = votes_collected

        # 4.5 Market anchor computation (extracted to shadow_ranking_compute)
        market_accuracy = compute_market_anchor(
            self.state_db, self.config, visible, all_votes, today
        )

        # 5. Compute rankings (extracted to shadow_ranking_compute)
        ranking_results = compute_rankings(
            self.state_db, self.config, visible, all_votes, today, market_accuracy
        )
        result.rankings = ranking_results["rankings"]
        result.plateau_flags.extend(ranking_results["plateau_flags"])
        result.reset_candidates.extend(ranking_results["reset_candidates"])
        result.ecosystem_alerts.extend(ranking_results["ecosystem_alerts"])
        performances = ranking_results["performances"]

        # 5b. Paper-to-live gap calibration
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

        # 6.4 Shadow health monitor
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
                await update_shadow_memory(self.state_db, self.config, result.shadow_analyses, today)
            except Exception as e:
                logger.error("Shadow memory update failed: %s", e)

        # 6.7 Crystallization check
        if getattr(self.config, 'crystallization_enabled', False):
            try:
                crystallization_results = await run_crystallization_check(self.state_db, self.config)
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
            await execute_challenger_trials(self.state_db, self.config, challenger, result)
        except Exception as e:
            logger.error("Challenger check failed: %s", e)

        # 7.1 Domain coverage guard — auto-seed BETA if any domain depleted
        try:
            ensure_domain_coverage(self.state_db)
        except Exception as e:
            logger.error("Domain coverage guard failed: %s", e)

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
