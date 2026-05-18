"""Daredevil shadows — 5 active + 2 environment-locked + 1 crash hunter (8 total).

Canonical design (shadow-ecosystem-full-design.md §1.2):
  - 5 ACTIVE (must make decisions every day): Intraday Direction, Weekly Trend,
    Event Hound, Fade Master, Rotation Engine
  - 2 ENVIRONMENT-LOCKED: Range-Bound (sideways markets), Panic (VIX>30)
  - 1 SHORT-BIASED: Crash Hunter (overvalued/bubble conditions)

Active daredevils do NOT wait for environment triggers — they find opportunities
daily regardless of market regime.
"""
from __future__ import annotations

import json
import logging

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowVote
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.daredevil_shadows")


class DaredevilShadow(ShadowAgent):
    """Daredevil shadow with higher risk tolerance (35% vs 25% drawdown limit).

    Subclassed for environment-locked daredevils that gate on market conditions.
    Active daredevils use the base class directly — no environment gating.
    """

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        super().__init__(config, state_db, settings)
        self.config.max_drawdown_limit = 0.35
        self.config.min_trades_for_ranking = 50

    async def _analyze(self, news_items: list[dict],
                        market_data: dict) -> ShadowAnalysisOutput:
        return await super()._analyze(news_items, market_data)

    def _build_user_prompt(self, news_items: list[dict], market_data: dict) -> str:
        """Strategy-specific prompt with constraints based on shadow type."""
        headlines = []
        for item in news_items[:20]:
            h = (getattr(item, "headline", None) or
                 getattr(item, "title", None) or
                 str(item.get("headline", "")) if hasattr(item, "get") else str(item))
            if h and h not in headlines:
                headlines.append(str(h)[:200])
        news_context = "\n".join(f"- {h}" for h in headlines[:15]) if headlines else "No news"

        constraints = ""
        if "range_bound" in self.shadow_id:
            constraints = (
                "ENVIRONMENT LOCKED: Range-bound markets (VIX < 20, daily range < 1.5%). "
                "Find sideways tickers. Fade breakouts, trade mean-reversion at boundaries."
            )
        elif "panic" in self.shadow_id:
            constraints = (
                "ENVIRONMENT LOCKED: Panic markets (VIX > 30). "
                "Buy fear peaks, fade panics. Counter-intuitive positioning required."
            )
        elif "crash" in self.shadow_id:
            constraints = (
                "SHORT-BIASED: Crash Hunter mode. Scan for overvalued assets, bubble conditions, "
                "pre-crash signals. Look for Shiller CAPE > 30, Hindenburg Omen, "
                "declining breadth, insider selling surges, credit spread widening. "
                "Activate with 2+ pre-crash signals. Default direction: short."
            )

        return (
            f"{constraints}\n\n"
            f"Market data: {json.dumps(market_data) if market_data else 'None'}\n\n"
            f"News headlines:\n{news_context}\n\n"
            f"Output your trades using VOTE_START/VOTE_END blocks. "
            f"ticker, direction (long/short), confidence (0.35-1.0), thesis, risk_note."
        )


# ── Pre-built daredevil configurations ──────────────────────────────────────
# 5 ACTIVE + 2 ENVIRONMENT-LOCKED + 1 SHORT-BIASED = 8 total

DAREDEVIL_SHADOW_CONFIGS: list[ShadowConfig] = [
    # ── 5 ACTIVE (must make decisions every day) ────────────────────────

    # 1. Intraday Direction — direction-forced, 1-3 day holding
    ShadowConfig(
        shadow_id="daredevil:intraday:scalper", shadow_type="daredevil",
        display_name="Intraday Scalper",
        methodology_prompt=(
            "You are the Intraday Direction scalper. ACTIVE — you MUST pick a "
            "direction daily, no abstaining. 1-3 day holding period. Your edge: "
            "reading intraday momentum and sentiment shifts. Key signals: opening "
            "range breakouts, volume profile anomalies, order flow imbalances, "
            "overnight gap patterns. You find opportunities EVERY day regardless "
            "of broad market conditions. Risk: tight stops mandatory, never hold "
            "through major data releases. Prefer liquid large-cap names. "
            "Output VOTE_START/VOTE_END blocks. Direction is REQUIRED."
        ),
        virtual_capital=25000.0, domain="macro", temperature=0.5,
        max_positions=3, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),

    # 2. Weekly Trend — trend identification, 5-15 day holding
    ShadowConfig(
        shadow_id="daredevil:weekly:trend_rider", shadow_type="daredevil",
        display_name="Trend Rider",
        methodology_prompt=(
            "You are the Weekly Trend rider. ACTIVE — you find developing trends "
            "every week, 5-15 day holding period. Your edge: identifying trends "
            "before they become obvious to the crowd. Key signals: ADX > 20 and "
            "rising, moving average crossovers, relative strength rankings, "
            "volume confirmation of trend direction. You find the strongest "
            "trends in the market every day — there is always something trending. "
            "Risk: trend exhaustion and sharp reversals. Use trailing stops. "
            "Output VOTE_START/VOTE_END blocks."
        ),
        virtual_capital=30000.0, domain="macro", temperature=0.4,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),

    # 3. Event Hound — event-driven, 1-5 day holding
    ShadowConfig(
        shadow_id="daredevil:event:news_hound", shadow_type="daredevil",
        display_name="Event Hound",
        methodology_prompt=(
            "You are the Event Hound. ACTIVE — you hunt event-driven opportunities "
            "every day, 1-5 day holding period. Your edge: trading the reaction gap "
            "between event impact and market pricing. Key signals: earnings surprises, "
            "FDA decisions, M&A announcements, regulatory changes, geopolitical "
            "developments. You find tradable events in EVERY news cycle — catalysts "
            "exist every day. Risk: event risk can compound, position size accordingly. "
            "Output VOTE_START/VOTE_END blocks."
        ),
        virtual_capital=25000.0, domain="macro", temperature=0.45,
        max_positions=3, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),

    # 4. Fade Master — systematic contrarian, fades crowded consensus
    ShadowConfig(
        shadow_id="daredevil:contrarian:fade_master", shadow_type="daredevil",
        display_name="Fade Master",
        methodology_prompt=(
            "You are the Fade Master. ACTIVE — you systematically fade consensus "
            "every day. When everyone agrees, the trade is crowded. Your edge: "
            "identifying when consensus has become extreme and positioning for "
            "reversal. Key signals: AAII sentiment extremes, put/call ratio "
            "extremes, COT report positioning, analyst consensus uniformity, "
            "social media sentiment spikes. You find fading opportunities EVERY "
            "day — there is always something the crowd is wrong about. "
            "Risk: trends can persist longer than contrarians stay solvent. "
            "Use tight stops. Output VOTE_START/VOTE_END blocks."
        ),
        virtual_capital=20000.0, domain="contrarian", temperature=0.55,
        max_positions=4, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),

    # 5. Rotation Engine — sector ETF rotation, 5-20 day holding
    ShadowConfig(
        shadow_id="daredevil:sector:rotation_engine", shadow_type="daredevil",
        display_name="Rotation Engine",
        methodology_prompt=(
            "You are the Rotation Engine. ACTIVE — you rotate across sector ETFs "
            "daily, 5-20 day holding period. Your edge: identifying which sectors "
            "are gaining vs losing relative momentum. Key signals: sector ETF "
            "relative strength rankings, intermarket relationships, yield curve "
            "signals for cyclical vs defensive rotation, fund flow data. "
            "Go long strongest 2 sectors, short weakest 2. Rotate weekly. "
            "You find rotation opportunities EVERY day — capital is always "
            "moving between sectors. Risk: sector correlations converge in "
            "crashes. Output VOTE_START/VOTE_END blocks."
        ),
        virtual_capital=30000.0, domain="macro", temperature=0.4,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),

    # ── 2 ENVIRONMENT-LOCKED ─────────────────────────────────────────────

    # 6. Range-Bound — sideways, no-trend markets (VIX < 20, daily range < 1.5%)
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
            "Prefer large-cap liquid names. Output VOTE_START/VOTE_END blocks."
        ),
        virtual_capital=25000.0, domain="macro", temperature=0.45,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),

    # 7. Panic — VIX > 30 high-volatility markets
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
            "Prefer large-cap liquid names. Output VOTE_START/VOTE_END blocks."
        ),
        virtual_capital=30000.0, domain="macro", temperature=0.6,
        max_positions=3, max_drawdown_limit=0.40, min_trades_for_ranking=50,
    ),

    # ── 1 SHORT-BIASED ──────────────────────────────────────────────────

    # 8. Crash Hunter — short-biased, looking for overvalued/bubble conditions
    ShadowConfig(
        shadow_id="daredevil:crash:hunter", shadow_type="daredevil",
        display_name="Crash Hunter",
        methodology_prompt=(
            "You are the Crash Hunter, a pre-crash detection specialist. "
            "SHORT-BIASED — you look for overvalued markets with accumulating "
            "crash signals. You look for: Shiller CAPE > 30, Buffett Indicator "
            "> 150%, rising cross-asset correlation, VIX term structure inversion, "
            "Hindenburg Omen signals, declining breadth despite index highs, "
            "insider selling surges, and credit spread widening. You only activate "
            "when at least 2 pre-crash signals are present. If conditions don't "
            "warrant crash positioning, report 'NO_CRASH_SETUP' and abstain. "
            "Your default direction is SHORT. Analyze: valuations → correlations "
            "→ breadth → credit → sentiment extremes. "
            "Output VOTE_START/VOTE_END blocks."
        ),
        virtual_capital=30000.0, domain="short", temperature=0.5,
        max_positions=3, max_drawdown_limit=0.40, min_trades_for_ranking=50,
    ),
]


def create_daredevil_shadows(state_db: ShadowStateDB,
                              settings: ShadowSettings) -> list[DaredevilShadow]:
    """Instantiate all 8 daredevil shadows (5 active + 2 env-locked + 1 short-biased)."""
    shadows = []
    for config in DAREDEVIL_SHADOW_CONFIGS:
        if state_db.get_shadow(config.shadow_id) is None:
            state_db.create_shadow(config)
        shadows.append(DaredevilShadow(config, state_db, settings))
    return shadows
