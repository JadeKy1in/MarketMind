"""Base ShadowAgent class — daily analysis cycle, virtual portfolio, integrity tracking."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from projects.marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, VirtualTradeOpen, VirtualTrade,
    DailySnapshot, IntegrityEvent, EmergencyQuotaRequest
)
from projects.marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.shadow_agent")


@dataclass
class ShadowVote:
    shadow_id: str
    shadow_type: str
    date: str
    ticker: str
    direction: str           # "long" | "short" | "abstain"
    confidence: float        # 0.0-1.0
    thesis: str              # 1-sentence reason
    risk_note: str           # 1-sentence risk
    emergency_flag: bool = False  # confidence >= 8/10?


@dataclass
class PositionCheck:
    trade_id: int
    ticker: str
    direction: str
    entry_price: float
    current_pnl_pct: float
    days_held: int
    should_exit: bool
    exit_reason: str | None = None


@dataclass
class ShadowAnalysisOutput:
    shadow_id: str
    date: str
    votes: list[ShadowVote] = field(default_factory=list)
    position_checks: list[PositionCheck] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    methodology_notes: str = ""
    quota_used: int = 0
    latency_ms: int = 0


class ShadowAgent:
    """Base class for all shadow agents. Handles daily analysis cycle, virtual portfolio,
    integrity tracking, and state persistence."""

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        self.config = config
        self.state_db = state_db
        self.settings = settings

        # Ensure shadow exists in DB (idempotent)
        existing = state_db.get_shadow(config.shadow_id)
        if existing is None:
            state_db.create_shadow(config)
        elif existing.status == "eliminated":
            logger.warning("Shadow %s is eliminated, reactivating", config.shadow_id)

    @property
    def shadow_id(self) -> str:
        return self.config.shadow_id

    # ── Status card ──────────────────────────────────────────────────────

    async def receive_status_card(self) -> dict:
        """Get today's ranking, tier, quota, promotion requirements."""
        latest = self.state_db.get_latest_snapshot(self.shadow_id)
        return {
            "shadow_id": self.shadow_id,
            "display_name": self.config.display_name,
            "shadow_type": self.config.shadow_type,
            "tier": latest.achievement_tier if latest else "normal",
            "daily_quota": self.get_daily_quota(),
            "pro_quota": self.get_pro_quota(),
            "virtual_capital": latest.virtual_capital if latest else self.config.virtual_capital,
            "integrity_score": self.get_integrity_score(),
        }

    # ── Daily cycle ──────────────────────────────────────────────────────

    async def run_daily_analysis(self, news_items: list,
                                  market_data: dict) -> ShadowAnalysisOutput:
        """Execute one day's analysis. Subclasses override _analyze()."""
        output = await self._analyze(news_items, market_data)
        await self.save_daily_snapshot()
        return output

    async def _analyze(self, news_items: list,
                        market_data: dict) -> ShadowAnalysisOutput:
        """Override in subclasses with methodology-specific analysis."""
        raise NotImplementedError("Subclass must implement _analyze()")

    # ── Virtual portfolio ────────────────────────────────────────────────

    async def get_open_positions(self) -> list[VirtualTrade]:
        return self.state_db.get_open_trades(self.shadow_id)

    async def check_positions(self) -> list[PositionCheck]:
        """Check all open positions for exit conditions."""
        open_trades = self.state_db.get_open_trades(self.shadow_id)
        results = []
        today = datetime.now(timezone.utc).date()
        for trade in open_trades:
            entry_date = datetime.strptime(trade.entry_date, "%Y-%m-%d").date()
            days_held = (today - entry_date).days
            results.append(PositionCheck(
                trade_id=trade.trade_id,
                ticker=trade.ticker,
                direction=trade.direction,
                entry_price=trade.entry_price,
                current_pnl_pct=trade.pnl_pct or 0.0,
                days_held=days_held,
                should_exit=False,
            ))
        return results

    async def open_virtual_position(self, trade: VirtualTradeOpen) -> int:
        return self.state_db.record_trade_open(self.shadow_id, trade)

    async def close_virtual_position(self, trade_id: int, exit_price: float,
                                      reason: str) -> None:
        # Calculate PnL from trade history
        trades = self.state_db.get_trade_history(self.shadow_id, limit=1)
        entry = None
        for t in trades:
            if t.trade_id == trade_id:
                entry = t
                break
        if entry is None:
            open_trades = self.state_db.get_open_trades(self.shadow_id)
            for t in open_trades:
                if t.trade_id == trade_id:
                    entry = t
                    break

        if entry:
            if entry.direction == "long":
                pnl = (exit_price - entry.entry_price) / entry.entry_price
            else:
                pnl = (entry.entry_price - exit_price) / entry.entry_price
        else:
            pnl = 0.0

        self.state_db.record_trade_close(trade_id, exit_price, reason, pnl)

    # ── Integrity ────────────────────────────────────────────────────────

    def get_integrity_score(self) -> int:
        return self.state_db.get_integrity_score(self.shadow_id)

    def report_integrity_event(self, event: IntegrityEvent) -> bool:
        return self.state_db.record_integrity_event(self.shadow_id, event)

    # ── Quota ────────────────────────────────────────────────────────────

    def get_daily_quota(self) -> int:
        return self.settings.shadow_flash_quota_default

    def get_pro_quota(self) -> int:
        return self.settings.shadow_pro_quota_default

    async def request_emergency_quota(self, opportunity: str,
                                       confidence: int) -> bool:
        """Request emergency quota via the auditor state machine (not direct DB)."""
        if confidence < self.settings.emergency_confidence_threshold:
            return False
        from projects.marketmind.shadows.emergency_quota import EmergencyQuotaAuditor
        auditor = EmergencyQuotaAuditor(self.state_db, self.settings)
        return auditor.request_quota(self.shadow_id, opportunity, confidence)

    # ── Persistence ──────────────────────────────────────────────────────

    async def save_daily_snapshot(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snap = DailySnapshot(
            shadow_id=self.shadow_id,
            date=today,
            virtual_capital=self.config.virtual_capital,
        )
        self.state_db.save_snapshot(self.shadow_id, snap)

    def apply_ranking_to_snapshot(self, ranking_result) -> None:
        """Backfill ranking metrics into today's snapshot. Called by orchestrator
        after ranking computation."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snap = DailySnapshot(
            shadow_id=self.shadow_id,
            date=today,
            virtual_capital=self.config.virtual_capital,
            composite_score=ranking_result.composite_score,
            deflated_score=ranking_result.deflated_score,
            percentile_rank=ranking_result.percentile_rank,
            achievement_tier=ranking_result.achievement_tier,
        )
        for name, score in ranking_result.component_scores.items():
            if name == "mppm":
                snap.mppm_score = score
            elif name == "calmar":
                snap.calmar_ratio = score
            elif name == "omega":
                snap.omega_ratio = score
            elif name == "win_rate":
                snap.win_rate_pct = score
        self.state_db.save_snapshot(self.shadow_id, snap)
