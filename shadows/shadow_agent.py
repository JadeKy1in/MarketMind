"""Base ShadowAgent class — daily analysis cycle, virtual portfolio, integrity tracking."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, VirtualTradeOpen, VirtualTrade,
    DailySnapshot, IntegrityEvent, EmergencyQuotaRequest
)
from marketmind.config.settings import ShadowSettings

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
    confidence: float | None = None   # LLM-parsed confidence


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


@dataclass
class ExternalObservation:
    """Observation from external multi-modal input (screenshot, PDF, audio, text)."""
    observation_id: str
    source_type: str          # "image" | "pdf" | "screenshot" | "text" | "audio"
    source_path: str          # original file path or URI
    extracted_text: str       # text extracted by Gemini Flash / OCR
    metadata: dict = field(default_factory=dict)
    confidence: float = 1.0   # extraction confidence 0.0-1.0
    source_attribution: str = ""  # who/what provided this observation
    evaluated_at: str = ""    # ISO 8601 timestamp of ingestion


@dataclass
class MemoryQuery:
    """Query parameters for searching layered shadow memory."""
    tier: str = "working"     # "working" | "episodic" | "semantic" | "all"
    ticker: str | None = None
    domain: str | None = None
    min_belief_strength: float = 0.0
    limit: int = 20
    tags: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class CrystallizationResult:
    """Output from knowledge crystallization cycle."""
    insight_id: str
    hypothesis: str
    validation_score: float   # backtest hit_rate or statistical significance
    action: str               # "promote" | "retire" | "hold"
    methodology_changes: list[str] = field(default_factory=list)
    source_insight_ids: list[str] = field(default_factory=list)
    evidence_summary: str = ""
    source_shadow_id: str = ""  # P1-2: direct shadow_id for prompt injection


# Patterns that could be misread as control sequences by vote parsers
# or used for injection attacks against LLM prompts.
# Defanged by inserting a zero-width space (U+200B) to break the pattern
# without losing information value in the headline.
# Module-level constant so pipeline layers can import it directly (Batch 2).
_DEFANG = [
    # Original control-sequence tokens
    ("VOTE_START", "VOTE​_START"),
    ("VOTE_END", "VOTE​_END"),
    ("EXIT_DECISION:", "EXIT​_DECISION:"),
    ("INSIGHT:", "INSIGHT​:"),
    ("OBSERVATION:", "OBSERVATION​:"),
    ("DATA_INTEGRITY_PROTOCOL", "DATA​_INTEGRITY_PROTOCOL"),
    ("CASH_REFRAMING_PROTOCOL", "CASH​_REFRAMING_PROTOCOL"),
    # Role-switching injection vectors
    ("[SYSTEM]", "[​SYSTEM]"),
    ("Assistant:", "Assistant​:"),
    ("Human:", "Human​:"),
    ("User:", "User​:"),
    ("</output>", "</​output>"),
    # Instruction-override injection
    ("Ignore all previous instructions", "Ignore all previous​ instructions"),
    ("Ignore previous", "Ignore​ previous"),
    ("Forget your instructions", "Forget your​ instructions"),
    # Additional control tokens
    ("SYSTEM OVERRIDE", "SYSTEM​ OVERRIDE"),
    ("SYSTEM:", "SYSTEM​:"),
    ("override", "​override"),
]


def defang_text(text: str) -> str:
    """Apply _DEFANG sanitization to any text before it enters LLM prompts.

    Args:
        text: Raw text that may contain injection vectors.

    Returns:
        Text with all dangerous patterns defanged by zero-width space insertion.
    """
    for pattern, replacement in _DEFANG:
        text = text.replace(pattern, replacement)
    return text


class ShadowAgent:
    """Base class for all shadow agents. Handles daily analysis cycle, virtual portfolio,
    integrity tracking, and state persistence."""

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        self.config = config
        self.state_db = state_db
        self.settings = settings

        # Ensure shadow exists in DB (idempotent)
        existing = state_db.get_shadow(config.shadow_id, caller_id=f"shadow:{config.shadow_id}")
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
        latest = self.state_db.get_latest_snapshot(self.shadow_id, caller_id=f"shadow:{self.shadow_id}")
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
                                  market_data: dict,
                                  broadcast_messages: list | None = None) -> ShadowAnalysisOutput:
        """Execute one day's analysis. Subclasses override _analyze()."""
        output = await self._analyze(news_items, market_data, broadcast_messages)
        await self.save_daily_snapshot()
        return output

    async def _analyze(self, news_items: list,
                        market_data: dict,
                        broadcast_messages: list | None = None) -> ShadowAnalysisOutput:
        """Execute analysis with LLM call using this shadow's methodology prompt.

        Subclasses override _build_user_prompt() and _parse_output() to customize
        domain filtering, prompt construction, and vote extraction. This base
        implementation works for temp_event, challenger, and beta shadows that
        use the config methodology_prompt directly.
        """
        from marketmind.gateway.async_client import chat_with_integrity

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        user_prompt = self._build_user_prompt(news_items, market_data, broadcast_messages)
        caller_agent = f"shadow:{self.config.shadow_type}:{self.config.display_name}"

        try:
            result = await chat_with_integrity(
                model=self.config.model,
                system_prompt=self.config.methodology_prompt,
                user_prompt=user_prompt,
                caller_agent=caller_agent,
                temperature=self.config.temperature,
                reasoning_effort=self.config.reasoning_effort,
            )
            content = result.get("content", "")
            latency_ms = result.get("latency_ms", 0)
        except Exception as e:
            logger.error("LLM call failed for %s: %s", self.shadow_id, e)
            content = ""
            latency_ms = 0

        votes = self._parse_votes(content)
        insights = self._extract_insights(content, news_items)

        # Persist raw LLM output for health monitoring (Phase 3)
        if content:
            try:
                token_count = result.get("usage", {}).get("total_tokens", 0)
                self.state_db.save_raw_output(
                    self.shadow_id, today, content, token_count, self.config.model
                )
            except Exception as e:
                logger.debug("Raw output persistence failed for %s: %s", self.shadow_id, e)

        return ShadowAnalysisOutput(
            shadow_id=self.shadow_id,
            date=today,
            votes=votes,
            insights=insights,
            methodology_notes=self.config.methodology_prompt[:200],
            quota_used=1 if content else 0,
            latency_ms=latency_ms,
        )

    def _build_user_prompt(self, news_items: list, market_data: dict,
                           broadcast_messages: list | None = None) -> str:
        """Build the user prompt from news, market data, and broadcast messages."""
        headlines = []
        for item in news_items[:20]:
            h = (getattr(item, "headline", None) or
                 getattr(item, "title", None) or
                 str(item.get("headline", "")) if hasattr(item, "get") else str(item))
            if h and h not in headlines:
                sanitized = str(h)[:200]
                for pattern, replacement in _DEFANG:
                    sanitized = sanitized.replace(pattern, replacement)
                headlines.append(sanitized)
        news_context = "\n".join(f"- {h}" for h in headlines[:15]) if headlines else "No news available"
        tickers_context = json.dumps(market_data) if market_data else "No market data"

        # Broadcast: user L1 viewpoints (for non-ELITE shadow analysis)
        broadcast_context = ""
        if broadcast_messages:
            from marketmind.shadows.broadcast import BroadcastReader
            opinions = BroadcastReader.extract_user_opinions(broadcast_messages)
            if opinions:
                broadcast_context = (
                    "\n\n=== USER L1 VIEWPOINTS (for independent analysis) ===\n"
                    "The user discussed the following in L1. Analyze independently:\n"
                    + "\n".join(f"- [USER OPINION]: {defang_text(o)[:300]}" for o in opinions[:5])
                    + "\n\nInstructions:\n"
                    "1. Evaluate whether each opinion has merit based on YOUR domain expertise.\n"
                    "2. Do NOT blindly agree — you are an independent analyst.\n"
                    "3. If an opinion is valid, you may incorporate it into your analysis.\n"
                    "4. If an opinion lacks evidence, explain why in your risk_note.\n"
                    "5. Do NOT base your entire analysis on user opinions — use news/market data as primary source.\n"
                )

        return (
            f"Today's market data:\n{tickers_context}\n\n"
            f"Relevant news headlines:\n{news_context}"
            f"{broadcast_context}\n\n"
            f"Analyze these inputs from your perspective and output your vote(s) "
            f"using VOTE_START/VOTE_END blocks. "
            f"For each vote include: ticker, direction (long/short/abstain), "
            f"confidence (0.0-1.0), thesis (1 sentence), risk_note (1 sentence)."
        )

    @staticmethod
    def _parse_votes(text: str) -> list[ShadowVote]:
        """Parse VOTE_START/VOTE_END blocks from LLM output."""
        votes = []
        pattern = re.compile(
            r'VOTE_START\s*\n(.*?)\nVOTE_END', re.DOTALL
        )
        for match in pattern.finditer(text):
            block = match.group(1)
            ticker = _extract_field(block, "ticker")
            direction = _extract_field(block, "direction")
            # Normalize: LLM may output buy/sell/hold instead of long/short/abstain
            if direction:
                direction = direction.strip().lower()
                _dm = {"buy": "long", "sell": "short", "hold": "abstain",
                       "neutral": "abstain", "bullish": "long", "bearish": "short"}
                direction = _dm.get(direction, direction)
                if direction not in ("long", "short", "abstain"):
                    direction = "abstain"
            confidence = float(_extract_field(block, "confidence") or 0.5)
            thesis = _extract_field(block, "thesis") or ""
            risk = _extract_field(block, "risk_note") or ""
            if ticker and direction:
                votes.append(ShadowVote(
                    shadow_id="", shadow_type="unknown",
                    date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    ticker=ticker, direction=direction,
                    confidence=min(max(confidence, 0.0), 1.0),
                    thesis=thesis[:200], risk_note=risk[:200],
                    emergency_flag=confidence >= 0.8,
                ))
        return votes

    @staticmethod
    def _extract_insights(text: str, news_items: list) -> list[str]:
        """Extract non-vote insights from LLM output."""
        insights = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("INSIGHT:") or line.startswith("OBSERVATION:"):
                insights.append(line[:300])
        if not insights:
            insights.append(f"Scanned {len(news_items)} news items, "
                          f"produced {len(re.findall(r'VOTE_START', text))} votes")
        return insights[:5]

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

    async def analyze_position_exits(self) -> list[PositionCheck]:
        """LLM-based exit analysis for open positions >= 5 days old."""
        from marketmind.gateway.async_client import chat_with_integrity

        open_trades = self.state_db.get_open_trades(self.shadow_id)
        today = datetime.now(timezone.utc).date()
        results = []

        for trade in open_trades:
            entry_date = datetime.strptime(trade.entry_date, "%Y-%m-%d").date()
            days_held = (today - entry_date).days

            if days_held < 5:
                results.append(PositionCheck(
                    trade_id=trade.trade_id, ticker=trade.ticker,
                    direction=trade.direction, entry_price=trade.entry_price,
                    current_pnl_pct=trade.pnl_pct or 0.0, days_held=days_held,
                    should_exit=False,
                ))
                continue

            # Build position context prompt
            user_prompt = (
                f"Position Review for {trade.ticker}:\n"
                f"Direction: {trade.direction}\n"
                f"Entry Price: ${trade.entry_price:.2f}\n"
                f"Current P&L: {trade.pnl_pct or 0.0:+.2%}\n"
                f"Days Held: {days_held}\n"
                f"Position Size: {trade.position_size_pct:.1%} of portfolio\n\n"
                f"Based on your methodology, decide whether to hold or exit this position.\n"
                f"Output format:\n"
                f"EXIT_DECISION: hold|exit\n"
                f"EXIT_REASON: <1-2 sentence reason>\n"
                f"CONFIDENCE: <0.0-1.0>"
            )

            caller = f"shadow:{self.config.shadow_type}:{self.config.display_name}"

            try:
                result = await chat_with_integrity(
                    model=self.config.model,
                    system_prompt=self.config.methodology_prompt,
                    user_prompt=user_prompt,
                    caller_agent=caller,
                    cash_reframing_ticker=trade.ticker,
                    cash_reframing_capital=self.config.virtual_capital,
                    temperature=self.config.temperature,
                    reasoning_effort=self.config.reasoning_effort,
                )
                content = result.get("content", "")
                decision = _extract_field(content, "EXIT_DECISION")
                reason = _extract_field(content, "EXIT_REASON") or ""
                conf = float(_extract_field(content, "CONFIDENCE") or 0.5)

                should_exit = (decision or "").lower().strip() == "exit"
                results.append(PositionCheck(
                    trade_id=trade.trade_id, ticker=trade.ticker,
                    direction=trade.direction, entry_price=trade.entry_price,
                    current_pnl_pct=trade.pnl_pct or 0.0, days_held=days_held,
                    should_exit=should_exit, exit_reason=reason,
                    confidence=min(max(conf, 0.0), 1.0),
                ))
            except Exception as e:
                logger.warning("Position exit analysis failed for %s trade %d: %s",
                              self.shadow_id, trade.trade_id, e)
                results.append(PositionCheck(
                    trade_id=trade.trade_id, ticker=trade.ticker,
                    direction=trade.direction, entry_price=trade.entry_price,
                    current_pnl_pct=trade.pnl_pct or 0.0, days_held=days_held,
                    should_exit=False,
                ))

        return results

    async def open_virtual_position(self, trade: VirtualTradeOpen) -> int:
        return self.state_db.record_trade_open(self.shadow_id, trade)

    async def close_virtual_position(self, trade_id: int, exit_price: float,
                                      reason: str) -> None:
        # Calculate PnL from trade history
        trades = self.state_db.get_trade_history(self.shadow_id, caller_id=f"shadow:{self.shadow_id}", limit=1)
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

    # Tier-based quota mapping (from design doc section 7.2)
    _TIER_QUOTA = {
        "elite": 7,
        "excellent": 6,
        "normal": 5,
        "watch": 3,
        "endangered": 1,
    }

    def get_daily_quota(self) -> int:
        latest = self.state_db.get_latest_snapshot(self.shadow_id, caller_id=f"shadow:{self.shadow_id}")
        if latest and latest.achievement_tier:
            return self._TIER_QUOTA.get(latest.achievement_tier, self.settings.shadow_flash_quota_default)
        return self.settings.shadow_flash_quota_default

    def get_pro_quota(self) -> int:
        return self.settings.shadow_pro_quota_default

    async def request_emergency_quota(self, opportunity: str) -> bool:
        """Request emergency quota triggered by base quota exhaustion (Phase 2).

        The shadow checks whether it has exhausted its daily base quota.
        Emergency quota is only available after base quota is fully used.
        """
        base_quota_total = self.get_daily_quota()
        latest = self.state_db.get_latest_snapshot(self.shadow_id, caller_id=f"shadow:{self.shadow_id}")
        base_quota_used = latest.flash_quota_used if latest else 0

        from marketmind.shadows.emergency_quota import EmergencyQuotaAuditor
        auditor = EmergencyQuotaAuditor(self.state_db, self.settings)
        return await auditor.request_quota(
            self.shadow_id, opportunity,
            base_quota_used=base_quota_used,
            base_quota_total=base_quota_total,
        )

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


def _extract_field(block: str, field: str) -> str | None:
    match = re.search(rf'{re.escape(field)}:\s*(.+)', block, re.IGNORECASE)
    return match.group(1).strip() if match else None


def create_shadow_agent(config: ShadowConfig, state_db: ShadowStateDB,
                        settings: ShadowSettings) -> ShadowAgent:
    """Factory: instantiate the correct shadow subclass for a given config."""
    from marketmind.shadows.expert_shadows import ExpertShadow
    shadow_type = config.shadow_type

    if shadow_type == "expert":
        return ExpertShadow(config, state_db, settings)
    elif shadow_type == "daredevil":
        from marketmind.shadows.daredevil_shadows import DaredevilShadow
        return DaredevilShadow(config, state_db, settings)
    elif shadow_type == "catfish":
        from marketmind.shadows.catfish_agent import CatfishAgent
        return CatfishAgent(config, state_db, settings)
    elif shadow_type == "missed_path":
        from marketmind.shadows.missed_path import MissedPathAgent
        return MissedPathAgent(config, state_db, settings)
    elif shadow_type in ("temp_event", "challenger", "beta"):
        return ShadowAgent(config, state_db, settings)
    else:
        return ShadowAgent(config, state_db, settings)
