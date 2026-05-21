"""Shadow Mother — daily orchestration facade for the shadow ecosystem.

Delegates event detection, temp shadow lifecycle, ranking/surveillance orchestration,
knowledge management, and challenger execution to focused modules.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_agent import ShadowAnalysisOutput
from marketmind.config.settings import ShadowSettings
from marketmind.shadows.event_detector import EventDetector
from marketmind.shadows.temp_shadow_lifecycle import TempShadowLifecycle
from marketmind.shadows.orchestrator import Orchestrator
from marketmind.shadows.knowledge_manager import KnowledgeManager
from marketmind.shadows.challenger_execution import ChallengerExecutor
from marketmind.shadows.market_anchor import MarketAnchorStep
from marketmind.shadows import shadow_vote_collector
from marketmind.shadows import step_knowledge
from marketmind.shadows import step_ael
from marketmind.shadows import step_maintenance
from marketmind.shadows import beta_lifecycle

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

        Delegates to beta_lifecycle.create_beta_shadow().
        """
        return await beta_lifecycle.create_beta_shadow(
            self.state_db, template_shadow_id, methodology_variant)

    async def promote_beta_shadow(self, shadow_id: str) -> bool:
        """Promote beta to active after 20-day positive track record.

        Delegates to beta_lifecycle.promote_beta_shadow().
        """
        return await beta_lifecycle.promote_beta_shadow(self.state_db, shadow_id)

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
        events = await self._event_detector.scan_events(news_items)
        prioritized = self._event_detector.prioritize_events(events)
        created = await self._temp_lifecycle.create_temp_shadows(prioritized)
        result.temp_shadows_created = len(created)

        # Destroy expired temp shadows
        for shadow in self.state_db.get_active_shadows("temp_event"):
            if self._temp_lifecycle.check_destruction_conditions(shadow.shadow_id):
                await self._temp_lifecycle.destroy_temp_shadow(shadow.shadow_id)
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

        Delegates to shadow_vote_collector.collect_votes(). See that module
        for P3-4 partial-state recovery and checkpoint save/load details.
        """
        return await shadow_vote_collector.collect_votes(
            self.state_db, self.config, news_items, market_data,
            visible, today, result,
        )

    # ── P2-4: Market anchor step ─────────────────────────────────────────

    async def _step_market_anchor(
        self, today: str, result: ShadowOrchestrationResult
    ) -> dict[str, float]:
        """Fetch external market data and compute per-shadow directional accuracy.

        Delegates to MarketAnchorStep. See shadows/market_anchor.py for details.
        """
        step = MarketAnchorStep(self.state_db)
        return await step.execute(today, result.shadow_analyses)

    # ── Step 6: Knowledge management ───────────────────────────────────────

    async def _step_knowledge_management(self, result: ShadowOrchestrationResult,
                                          today: str) -> None:
        """Update shadow memory, run crystallization wiring.

        Delegates to step_knowledge.run_knowledge_step().
        """
        await step_knowledge.run_knowledge_step(
            self.config, self._knowledge_manager, self.state_db,
            result, today,
        )

    # ── Step 7: AEL evolution ──────────────────────────────────────────────

    async def _step_ael_evolution(self, performances: dict, market_data: dict,
                                   today: str, result: ShadowOrchestrationResult) -> None:
        """Run AEL monthly debrief.

        Delegates to step_ael.run_ael_step().
        """
        await step_ael.run_ael_step(
            self.config, self.state_db, performances, market_data,
            today, result,
        )

    # ── Step 8: Maintenance ────────────────────────────────────────────────

    async def _step_maintenance(self, visible: list,
                                 result: ShadowOrchestrationResult) -> None:
        """Run challenger checks/trials, method breeding, emergency audits.

        Delegates to step_maintenance.run_maintenance_step().
        """
        await step_maintenance.run_maintenance_step(
            self.config, self.state_db, self._challenger_executor,
            visible, result,
        )
