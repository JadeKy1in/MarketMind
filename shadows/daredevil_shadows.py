"""Daredevil shadows — direction-forced, event hound, contrarian, sector rotation."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowVote
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.daredevil_shadows")

# ── Daredevil methodology prompts ──────────────────────────────────────────

_SCALPER_PROMPT = (
    "You are the Scalper, an intraday direction daredevil. You MUST pick a direction "
    "for at least one asset every day — abstaining is not allowed. Hold for 1-3 days. "
    "Your edge is speed and pattern recognition. Max position size: 15%. "
    "Risk: higher turnover means higher slippage. Track your realized vs. paper PnL gap. "
    "Output VOTE_START/VOTE_END blocks. Floor confidence: 0.35 (you must trade)."
)

_TREND_RIDER_PROMPT = (
    "You are the Trend Rider, a weekly trend daredevil. Identify developing multi-week "
    "trends in equities, commodities, or FX. Hold 5-15 days. Your edge is momentum "
    "continuation. Use moving average crossovers, ADX > 25, and volume confirmation. "
    "Max position: 20%. Stop: trend break confirmed by 2 consecutive closes below 20-day MA. "
    "Output VOTE_START/VOTE_END blocks."
)

_NEWS_HOUND_PROMPT = (
    "You are the News Hound, an event-driven daredevil. Trade news-driven moves within "
    "1-5 days. Your edge is rapid information processing. Focus on earnings surprises, "
    "M&A announcements, regulatory changes, and macro data beats. "
    "Max position: 12%. Stop: if the news catalyst proves false or market reverses >50% "
    "of initial move. Output VOTE_START/VOTE_END blocks."
)

_FADE_MASTER_PROMPT = (
    "You are the Fade Master, a contrarian daredevil. Systematically fade crowded consensus. "
    "When >75% of expert shadows agree on a direction, take the opposite side. "
    "Hold 3-10 days. Your edge is mean reversion. Use sentiment extremes, COT positioning, "
    "put/call ratios, and AAII survey. Max position: 10%. Stop: if the crowd was right "
    "(positioning confirms with price, not against it). Output VOTE_START/VOTE_END blocks."
)

_ROTATION_ENGINE_PROMPT = (
    "You are the Rotation Engine, a sector rotation daredevil. Rotate between sector ETFs "
    "based on business cycle phase analysis. Hold 5-20 days. Your edge is macro regime "
    "detection. Use relative strength across 11 GICS sectors, yield curve shape, and "
    "leading indicators. Max position: 20%. Output VOTE_START/VOTE_END blocks."
)


class DaredevilShadow(ShadowAgent):
    """Daredevil shadow with higher risk tolerance and forced direction picking."""

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        super().__init__(config, state_db, settings)
        # Higher default risk tolerance
        self.config.max_drawdown_limit = 0.35
        self.config.min_trades_for_ranking = 50

    async def _analyze(self, news_items: list[dict],
                        market_data: dict) -> ShadowAnalysisOutput:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # News hound: look for event-driven opportunities
        headlines = [item.get("headline", "")[:150] for item in news_items[:15]]
        news_context = "\n".join(f"- {h}" for h in headlines) if headlines else "No news"

        return ShadowAnalysisOutput(
            shadow_id=self.shadow_id,
            date=today,
            votes=[],
            insights=[f"Daredevil scan: {len(news_items)} items, type={self.config.shadow_type}"],
            methodology_notes=f"Daredevil {self.config.display_name}: {self.config.methodology_prompt[:200]}",
            quota_used=1,
        )


# ── Pre-built daredevil configurations ──────────────────────────────────────

DAREDEVIL_SHADOW_CONFIGS: list[ShadowConfig] = [
    ShadowConfig(
        shadow_id="daredevil:intraday:scalper", shadow_type="daredevil",
        display_name="Scalper", methodology_prompt=_SCALPER_PROMPT,
        virtual_capital=25000.0, domain="macro", temperature=0.5,
        max_positions=4, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),
    ShadowConfig(
        shadow_id="daredevil:swing:trend_rider", shadow_type="daredevil",
        display_name="Trend Rider", methodology_prompt=_TREND_RIDER_PROMPT,
        virtual_capital=30000.0, domain="macro", temperature=0.4,
        max_positions=3, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),
    ShadowConfig(
        shadow_id="daredevil:event:news_hound", shadow_type="daredevil",
        display_name="News Hound", methodology_prompt=_NEWS_HOUND_PROMPT,
        virtual_capital=25000.0, domain="macro", temperature=0.45,
        max_positions=5, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),
    ShadowConfig(
        shadow_id="daredevil:contrarian:fade_master", shadow_type="daredevil",
        display_name="Fade Master", methodology_prompt=_FADE_MASTER_PROMPT,
        virtual_capital=20000.0, domain="macro", temperature=0.55,
        max_positions=4, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),
    ShadowConfig(
        shadow_id="daredevil:sector:rotation_engine", shadow_type="daredevil",
        display_name="Rotation Engine", methodology_prompt=_ROTATION_ENGINE_PROMPT,
        virtual_capital=30000.0, domain="macro", temperature=0.4,
        max_positions=3, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),
]


def create_daredevil_shadows(state_db: ShadowStateDB,
                              settings: ShadowSettings) -> list[DaredevilShadow]:
    """Instantiate all 5 daredevil shadows from configs."""
    shadows = []
    for config in DAREDEVIL_SHADOW_CONFIGS:
        if state_db.get_shadow(config.shadow_id) is None:
            state_db.create_shadow(config)
        shadows.append(DaredevilShadow(config, state_db, settings))
    return shadows
