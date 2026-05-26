"""Daredevil shadows — direction-forced, event hound, contrarian, sector rotation."""
from __future__ import annotations

import json
import logging

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowDecision, defang_text
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.daredevil_shadows")


class DaredevilShadow(ShadowAgent):
    """Daredevil shadow with higher risk tolerance and forced direction picking."""

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        super().__init__(config, state_db, settings)
        # Higher default risk tolerance
        self.config.max_drawdown_limit = 0.35
        self.config.min_trades_for_ranking = 50

    async def _analyze(self, news_items: list[dict],
                        market_data: dict,
                        broadcast_messages: list | None = None) -> ShadowAnalysisOutput:
        """Daredevil analysis — higher temperature, forced direction."""
        return await super()._analyze(news_items, market_data)

    def _build_user_prompt(self, news_items: list[dict], market_data: dict,
                           broadcast_messages: list | None = None, **kwargs) -> str:
        """Daredevil-specific prompt: risk-on framing, forced direction constraints."""
        headlines = []
        for item in news_items[:20]:
            h = (getattr(item, "headline", None) or
                 getattr(item, "title", None) or
                 str(item.get("headline", "")) if hasattr(item, "get") else str(item))
            if h and h not in headlines:
                headlines.append(defang_text(str(h)[:200]))
        news_context = "\n".join(f"- {h}" for h in headlines[:15]) if headlines else "No news"

        constraints = ""
        if "range_bound" in self.shadow_id:
            constraints = "RANGE-BOUND MODE: Find sideways tickers. Fade breakouts, trade mean-reversion at boundaries."
        elif "panic" in self.shadow_id:
            constraints = "PANIC MODE: VIX>30. Buy fear peaks, fade panics. Counter-intuitive positioning required."
        elif "leveraged" in self.shadow_id:
            constraints = "LEVERAGED MODE: Trade LETFs only. Tight stops mandatory. Never hold through vol events."
        elif "contrarian" in self.shadow_id:
            constraints = "CONTRARIAN MODE: Consensus >80% = extreme. Take opposite side with conviction."
        elif "momentum" in self.shadow_id:
            constraints = "MOMENTUM MODE: Follow confirmed trends. Buy breakouts, add on pullbacks."
        elif "sector" in self.shadow_id:
            constraints = "SECTOR MODE: Long strongest 2 sectors, short weakest 2. Rotate weekly."
        elif "low_liq" in self.shadow_id:
            constraints = "LOW LIQ MODE: Thin markets. Limit orders only. Account for slippage."
        elif "crash" in self.shadow_id:
            constraints = "CRASH HUNTER MODE: Scan for pre-crash signals. Activate with 2+ indicators."

        return (
            f"{constraints}\n\n"
            f"Market data: {json.dumps(market_data) if market_data else 'None'}\n\n"
            f"News headlines:\n{news_context}\n\n"
            f"Output your trades using DECISION_START/DECISION_END blocks. "
            f"ticker, direction (long/short), confidence (0.35-1.0), thesis, risk_note."
        )


# ── Pre-built daredevil configurations ──────────────────────────────────────

DAREDEVIL_SHADOW_CONFIGS: list[ShadowConfig] = [
    # Phase 6: 7 environment-locked Daredevils + Crash Hunter (7+1)
    # 1. Range-Bound — sideways, no-trend markets
    ShadowConfig(
        shadow_id="daredevil:range_bound:sideways_scout", shadow_type="daredevil",
        display_name="Sideways Scout",
        methodology_prompt=(
            "You are the Sideways Scout. ENVIRONMENT LOCKED: range-bound markets "
            "(VIX < 20, daily range < 1.5%). In sideways conditions, direction "
            "is hardest to call. Your edge: mean-reversion at range boundaries. "
            "Buy at support, short at resistance. Fade breakouts — most are fake "
            "in ranges. Key signals: volume contraction near boundaries, RSI "
            "divergence, Bollinger Band squeezes. Risk: breakout breakage. "
            "ALWAYS find range-bound tickers regardless of broad market regime. "
            "Prefer large-cap liquid names. Output DECISION_START/DECISION_END blocks."
        ),
        virtual_capital=25000.0, domain="macro", temperature=0.45,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),
    # 2. Panic — VIX > 30 high-volatility markets
    ShadowConfig(
        shadow_id="daredevil:panic:vol_surfer", shadow_type="daredevil",
        display_name="Vol Surfer",
        methodology_prompt=(
            "You are the Vol Surfer. ENVIRONMENT LOCKED: panic markets (VIX > 30). "
            "In extreme fear, information is chaotic but opportunity is greatest. "
            "Your edge: buying when fear peaks, selling when panic subsides. "
            "Key signals: VIX term structure inversion, put/call ratio extremes, "
            "breadth washout readings, credit spread blowout. Counter-intuitive: "
            "fade the panic when VIX starts declining from peak. Risk: catching "
            "a falling knife in genuine crash. ALWAYS find high-VIX tickers. "
            "Prefer large-cap liquid names. Output DECISION_START/DECISION_END blocks."
        ),
        virtual_capital=30000.0, domain="macro", temperature=0.6,
        max_positions=3, max_drawdown_limit=0.40, min_trades_for_ranking=50,
    ),
    # 3. Leveraged ETFs — 3x levered products
    ShadowConfig(
        shadow_id="daredevil:leveraged:lever_hunter", shadow_type="daredevil",
        display_name="Lever Hunter",
        methodology_prompt=(
            "You are the Lever Hunter. ENVIRONMENT LOCKED: leveraged ETFs "
            "(TQQQ, SQQQ, SOXL, SOXS, UCO, SCO — 3x daily reset products). "
            "Leverage amplifies everything: gains, losses, decay. Your edge: "
            "momentum + tight risk management. Key signals: underlying index "
            "trend strength, volatility drag estimation, overnight gap risk. "
            "Never hold through volatility events — decay destroys you. "
            "Position size max 10% due to extreme risk. ALWAYS trade LETFs. "
            "Output DECISION_START/DECISION_END blocks."
        ),
        virtual_capital=20000.0, domain="macro", temperature=0.5,
        max_positions=2, max_drawdown_limit=0.45, min_trades_for_ranking=50,
    ),
    # 4. Contrarian — fade extreme consensus
    ShadowConfig(
        shadow_id="daredevil:contrarian:herd_fader", shadow_type="daredevil",
        display_name="Herd Fader",
        methodology_prompt=(
            "You are the Herd Fader. ENVIRONMENT LOCKED: sentiment extremes "
            "(consensus > 80% in either direction). When everyone agrees, "
            "the trade is crowded and the reversal is near. Your edge: "
            "fading consensus at extremes. Key signals: AAII sentiment extremes, "
            "put/call ratio extremes, COT report positioning, analyst consensus "
            "uniformity. Buy when fear is consensus, short when greed is. "
            "Risk: trends can persist longer than contrarians stay solvent. "
            "Use tight stops. Output DECISION_START/DECISION_END blocks."
        ),
        virtual_capital=20000.0, domain="contrarian", temperature=0.6,
        max_positions=4, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),
    # 5. Momentum/Chasing — trend-following
    ShadowConfig(
        shadow_id="daredevil:momentum:trend_chaser", shadow_type="daredevil",
        display_name="Trend Chaser",
        methodology_prompt=(
            "You are the Trend Chaser. ENVIRONMENT LOCKED: trending markets "
            "(ADX > 25, price above/below moving averages, clear direction). "
            "When trends are strong, momentum works until it doesn't. Your edge: "
            "catching mid-trend continuation. Key signals: ADX strength, "
            "moving average slope, volume confirmation, relative strength. "
            "Buy breakouts, add on pullbacks, exit when momentum diverges. "
            "Risk: trend exhaustion and violent reversals. ALWAYS find "
            "trending tickers regardless of broad market. Prefer large-cap. "
            "Output DECISION_START/DECISION_END blocks."
        ),
        virtual_capital=30000.0, domain="macro", temperature=0.4,
        max_positions=3, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),
    # 6. Sector Rotation — relative strength across sectors
    ShadowConfig(
        shadow_id="daredevil:sector:sector_spinner", shadow_type="daredevil",
        display_name="Sector Spinner",
        methodology_prompt=(
            "You are the Sector Spinner. ENVIRONMENT LOCKED: sector rotation "
            "(always-on, sector-relative). Your edge: identifying which sectors "
            "are gaining vs losing relative momentum. Key signals: sector ETF "
            "relative strength rankings, intermarket relationships, yield curve "
            "signals for cyclical vs defensive rotation, fund flow data. "
            "Go long strongest 2 sectors, short weakest 2. Rotate weekly. "
            "Risk: sector correlations converge in crashes. Output "
            "DECISION_START/DECISION_END blocks with sector-level analysis."
        ),
        virtual_capital=30000.0, domain="macro", temperature=0.4,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),
    # 7. Low Liquidity — thin markets, wide spreads
    ShadowConfig(
        shadow_id="daredevil:low_liq:depth_diver", shadow_type="daredevil",
        display_name="Depth Diver",
        methodology_prompt=(
            "You are the Depth Diver. ENVIRONMENT LOCKED: low-liquidity markets "
            "(wide bid-ask spreads, low daily volume, but NOT completely illiquid "
            "— there must be a counterparty). Your edge: exploiting pricing "
            "inefficiencies in overlooked corners. Key signals: volume percentile, "
            "spread analysis, block trade detection, insider accumulation. "
            "Exception: not required to trade large-cap. Trade small/mid-cap "
            "with adequate daily volume (>$1M notional). Risk: cannot exit "
            "quickly — must use limit orders, account for slippage. "
            "Output DECISION_START/DECISION_END blocks."
        ),
        virtual_capital=15000.0, domain="macro", temperature=0.45,
        max_positions=5, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),
    # Phase 5: Crash Hunter — pre-crash signal specialist (Item 16)
    ShadowConfig(
        shadow_id="daredevil:crash:hunter", shadow_type="daredevil",
        display_name="Crash Hunter",
        methodology_prompt=(
            "You are the Crash Hunter, a pre-crash detection specialist. "
            "Your environment: overvalued markets with accumulating crash signals. "
            "You look for: Shiller CAPE > 30, Buffett Indicator > 150%, rising "
            "cross-asset correlation, VIX term structure inversion, Hindenburg Omen "
            "signals, declining breadth despite index highs, insider selling surges, "
            "and credit spread widening. You are SHORT-BIASED — your purpose is to "
            "identify assets most vulnerable to a crash and position accordingly. "
            "You only activate when at least 2 pre-crash signals are present. "
            "If conditions don't warrant crash positioning, report 'NO_CRASH_SETUP' "
            "and abstain. Analyze: valuations → correlations → breadth → credit → "
            "sentiment extremes. Output DECISION_START/DECISION_END blocks."
        ),
        virtual_capital=30000.0, domain="short", temperature=0.5,
        max_positions=3, max_drawdown_limit=0.40, min_trades_for_ranking=50,
    ),
]


def create_daredevil_shadows(state_db: ShadowStateDB,
                              settings: ShadowSettings) -> list[DaredevilShadow]:
    """Instantiate all 8 daredevil shadows (7+1) from configs."""
    shadows = []
    for config in DAREDEVIL_SHADOW_CONFIGS:
        if state_db.get_shadow(config.shadow_id) is None:
            state_db.create_shadow(config)
        shadows.append(DaredevilShadow(config, state_db, settings))
    return shadows
