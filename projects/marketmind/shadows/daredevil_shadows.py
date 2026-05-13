"""Daredevil shadows — direction-forced, event hound, contrarian, sector rotation."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowVote
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings
from marketmind.config import load_shadow_prompts

logger = logging.getLogger("marketmind.shadows.daredevil_shadows")


def _load_daredevil_prompts() -> dict:
    """Load daredevil prompts from JSON config."""
    prompts = load_shadow_prompts()
    return prompts.get("daredevil", {})


_DD_PROMPTS = _load_daredevil_prompts()

_SCALPER_PROMPT = _DD_PROMPTS.get("scalper", "You are the Scalper. Pick a direction daily.")
_TREND_RIDER_PROMPT = _DD_PROMPTS.get("trend_rider", "You are the Trend Rider. Follow multi-week trends.")
_NEWS_HOUND_PROMPT = _DD_PROMPTS.get("news_hound", "You are the News Hound. Trade event-driven moves.")
_FADE_MASTER_PROMPT = _DD_PROMPTS.get("fade_master", "You are the Fade Master. Fade crowded consensus.")
_ROTATION_ENGINE_PROMPT = _DD_PROMPTS.get("rotation_engine", "You are the Rotation Engine. Rotate between sectors.")


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
        """Daredevil analysis — higher temperature, forced direction."""
        return await super()._analyze(news_items, market_data)

    def _build_user_prompt(self, news_items: list[dict], market_data: dict) -> str:
        """Daredevil-specific prompt: risk-on framing, forced direction constraints."""
        headlines = []
        for item in news_items[:20]:
            h = (getattr(item, "headline", None) or
                 getattr(item, "title", None) or
                 str(item.get("headline", "")) if hasattr(item, "get") else str(item))
            if h and h not in headlines:
                headlines.append(str(h)[:200])
        news_context = "\n".join(f"- {h}" for h in headlines[:15]) if headlines else "No news"

        constraints = ""
        if "scalper" in self.shadow_id:
            constraints = "DANGER ZONE: You MUST pick a direction for at least one asset today. Abstaining is not allowed."
        elif "fade" in self.shadow_id:
            constraints = "CONTRARIAN MODE: Look for crowded consensus and take the opposite side."
        elif "trend" in self.shadow_id:
            constraints = "TREND MODE: Identify developing multi-week trends with momentum confirmation."
        elif "news" in self.shadow_id:
            constraints = "EVENT MODE: Trade news-driven moves within 1-5 days."

        return (
            f"{constraints}\n\n"
            f"Market data: {json.dumps(market_data) if market_data else 'None'}\n\n"
            f"News headlines:\n{news_context}\n\n"
            f"Output your trades using VOTE_START/VOTE_END blocks. "
            f"ticker, direction (long/short), confidence (0.35-1.0), thesis, risk_note."
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
            "sentiment extremes. Output VOTE_START/VOTE_END blocks."
        ),
        virtual_capital=30000.0, domain="short", temperature=0.5,
        max_positions=3, max_drawdown_limit=0.40, min_trades_for_ranking=50,
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
