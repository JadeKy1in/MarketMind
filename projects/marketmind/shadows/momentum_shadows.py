"""Momentum shadows — trend-following strategies (P2 type system).

Canonical design: shadow-ecosystem-final-plan.md §3.2
  - 4 momentum shadows: always active, τ=0.40-0.50
  - 75-day evaluation window, drawdown limit ≤30%, min 50 trades
  - Assessment: MPPM 0.30 / Calmar 0.30 / Omega 0.15 / WinRate 0.25

These replace the old daredevil shadows (intraday, weekly_trend, event_hound,
rotation_engine) with their new type hierarchy under the "momentum" namespace.
"""
from __future__ import annotations

import json
import logging

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowDecision
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.momentum_shadows")


class MomentumShadow(ShadowAgent):
    """Momentum shadow — trend-following with higher turnover tolerance.

    All momentum shadows are ALWAYS ACTIVE — they find tradable trends
    every day regardless of market regime. 75-day evaluation window,
    higher drawdown tolerance (30%), and lower min trade count (50)
    compared to expert shadows.
    """

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        super().__init__(config, state_db, settings)

    async def _analyze(self, news_items: list[dict],
                       market_data: dict,
                   broadcast_messages: list | None = None) -> ShadowAnalysisOutput:
        return await super()._analyze(news_items, market_data, broadcast_messages)

    def _build_user_prompt(self, news_items: list[dict], market_data: dict,
                       broadcast_messages: list | None = None, **kwargs) -> str:
        """Momentum-specific prompt: trend identification, momentum signals."""
        headlines = []
        for item in news_items[:25]:
            h = (getattr(item, "headline", None) or
                 getattr(item, "title", None) or
                 str(item.get("headline", "")) if hasattr(item, "get") else str(item))
            if h and h not in headlines:
                headlines.append(str(h)[:200])
        news_context = "\n".join(f"- {h}" for h in headlines[:20]) if headlines else "No news"

        return (
            f"Market data: {json.dumps(market_data) if market_data else 'None'}\n\n"
            f"News headlines:\n{news_context}\n\n"
            f"Output your momentum trades using VOTE_START/VOTE_END blocks. "
            f"For each vote include: ticker, direction (long/short), "
            f"confidence (0.0-1.0), thesis (1 sentence), risk_note (1 sentence).\n"
            f"Momentum strategy rules:\n"
            f"- Identify the strongest trending assets in the current market\n"
            f"- Focus on trend continuation signals: ADX, moving average alignment, volume confirmation\n"
            f"- Use trailing stops — trend exhaustion is your primary risk\n"
            f"- Always produce at least one trade direction daily (min $100 if uncertain)\n"
            f"- Prefer liquid, large-cap names for position sizing accuracy"
        )


# ── Pre-built momentum shadow configurations ──────────────────────────────
# 4 momentum shadows: always active, 75-day evaluation window

MOMENTUM_SHADOW_CONFIGS: list[ShadowConfig] = [
    # 1. Intraday Scalper — intraday momentum breakouts, 1-3 day holding
    ShadowConfig(
        shadow_id="momentum:intraday:scalper",
        shadow_type="momentum",
        display_name="Intraday Scalper",
        methodology_prompt=(
            "You are the Intraday Scalper — 日内猎手, an intraday momentum breakout "
            "trader. ALWAYS ACTIVE — you find tradable momentum every day, 1-3 day "
            "holding period.\n\n"
            "Strategy: 日内动量突破 (Intraday Momentum Breakout)\n"
            "Personality: 快进快出——手速是你的Alpha。所有影子中换手率最高。\n\n"
            "Key signals:\n"
            "- Opening Range Breakout (ORB): price breaks above/below the 30-minute opening range\n"
            "- Relative Volume (RVOL) > 2.0 for signal confirmation\n"
            "- VWAP deviation > 2σ for mean-reversion entries\n"
            "- Volume profile anomalies and order flow imbalances\n\n"
            "Trading rules:\n"
            "- Skip trading during 11:30-14:00 (lunch liquidity lull)\n"
            "- No new positions after 15:30 — manage existing positions only\n"
            "- Hard stop: -2% per position, -5% per day\n"
            "- Max 3 trades per day; 3 consecutive losses → cooldown 1 day\n"
            "- Skip FOMC/CPI/NFP data release mornings\n\n"
            "Risk: tight stops mandatory. Never hold through major data releases. "
            "Prefer liquid large-cap names. Output VOTE_START/VOTE_END blocks. "
            "Direction is REQUIRED every day."
        ),
        virtual_capital=25000.0, domain="macro", temperature=0.50,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),

    # 2. Trend Rider — weekly trend following, 5-15 day holding
    ShadowConfig(
        shadow_id="momentum:weekly:trend_rider",
        shadow_type="momentum",
        display_name="Trend Rider",
        methodology_prompt=(
            "You are the Trend Rider — 趋势骑士, a weekly trend-following specialist. "
            "ALWAYS ACTIVE — trends exist in every market, you find the strongest ones, "
            "5-15 day holding period.\n\n"
            "Strategy: 周线趋势跟随 (Weekly Trend Following)\n"
            "Personality: 耐心果断——不预测趋势何时开始，只判断现在是什么方向。\n\n"
            "Key signals:\n"
            "- ADX > 20 and rising — trend strength confirmation\n"
            "- Moving average alignment: 20MA > 50MA > 200MA (uptrend) or reverse (downtrend)\n"
            "- Relative strength rankings across sectors/asset classes\n"
            "- Volume confirmation: increasing volume in trend direction\n"
            "- Multi-timeframe alignment: daily + weekly charts\n\n"
            "Trading rules:\n"
            "- Enter on pullbacks to 20MA when trend is confirmed\n"
            "- Trailing stops: 2× ATR(14) from entry\n"
            "- Never fight the trend — no counter-trend entries\n"
            "- Risk: trend exhaustion and sharp reversals. Exit when ADX starts declining.\n\n"
            "Output VOTE_START/VOTE_END blocks. Direction is REQUIRED every day."
        ),
        virtual_capital=30000.0, domain="macro", temperature=0.40,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),

    # 3. Event Hound — event-driven momentum, 1-5 day holding
    ShadowConfig(
        shadow_id="momentum:event:news_hound",
        shadow_type="momentum",
        display_name="Event Hound",
        methodology_prompt=(
            "You are the Event Hound — 事件猎犬, an event-driven momentum chaser. "
            "ALWAYS ACTIVE — catalysts exist every day, you hunt the reaction gap, "
            "1-5 day holding period.\n\n"
            "Strategy: 事件驱动追入 (Event-Driven Momentum Chase)\n"
            "Personality: 嗅觉敏锐——闻到血腥味就出发，不犹豫。\n\n"
            "Key signals:\n"
            "- Earnings surprises (beat/miss > 5% vs consensus)\n"
            "- FDA drug approvals, clinical trial results\n"
            "- M&A announcements, activist investor filings\n"
            "- Regulatory changes, policy shifts\n"
            "- Geopolitical developments with market impact\n"
            "- Post-event drift: price continues moving in event direction for days\n\n"
            "Trading rules:\n"
            "- Enter within 30 minutes of event confirmation (not before)\n"
            "- Size positions at 50% of normal on rumored-but-unconfirmed events\n"
            "- Exit on day 5 or when event drift exhausts (whichever comes first)\n"
            "- Risk: event risk can compound — never hold through competing events\n\n"
            "Output VOTE_START/VOTE_END blocks. Direction is REQUIRED every day."
        ),
        virtual_capital=25000.0, domain="macro", temperature=0.45,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),

    # 4. Rotation Engine — sector ETF rotation, 5-20 day holding
    ShadowConfig(
        shadow_id="momentum:sector:rotation_engine",
        shadow_type="momentum",
        display_name="Rotation Engine",
        methodology_prompt=(
            "You are the Rotation Engine — 轮动引擎, a sector/industry rotation "
            "specialist. ALWAYS ACTIVE — capital is always moving between sectors, "
            "you identify where it's flowing, 5-20 day holding period.\n\n"
            "Strategy: 行业板块轮动 (Sector/Industry Rotation)\n"
            "Personality: 策略至上——不赌个股，赌资金流向哪个行业。\n\n"
            "Key signals:\n"
            "- Sector ETF relative strength rankings (12-week and 4-week momentum)\n"
            "- Intermarket relationships: yield curve slope for cyclical vs defensive rotation\n"
            "- Fund flow data: ETF inflows/outflows by sector\n"
            "- Correlation analysis: which sectors are diverging from broad market\n"
            "- Economic cycle positioning: early-cycle (industrials, financials) vs late-cycle (staples, utilities)\n\n"
            "Trading rules:\n"
            "- Go long 2 strongest sectors, short 2 weakest sectors\n"
            "- Rotate weekly — reassess every Monday\n"
            "- Position size: equal weight per sector, rebalance weekly\n"
            "- Risk: sector correlations converge in crashes — reduce all positions to 50% when VIX > 25\n\n"
            "Output VOTE_START/VOTE_END blocks. Direction is REQUIRED every day."
        ),
        virtual_capital=30000.0, domain="macro", temperature=0.40,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=50,
    ),
]


def create_momentum_shadows(state_db: ShadowStateDB,
                             settings: ShadowSettings) -> list[MomentumShadow]:
    """Instantiate all 4 momentum shadows from configs."""
    shadows = []
    for config in MOMENTUM_SHADOW_CONFIGS:
        if state_db.get_shadow(config.shadow_id) is None:
            state_db.create_shadow(config)
        shadows.append(MomentumShadow(config, state_db, settings))
    return shadows
