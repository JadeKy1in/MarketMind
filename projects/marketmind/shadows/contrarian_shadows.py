"""Contrarian shadows -- mean-reversion strategies (P2 type system).

Canonical design: shadow-ecosystem-final-plan.md 3.3
  - 4 contrarian "敢死队" shadows with global scan triggers
  - 252-day evaluation window, drawdown limit 35-40%
  - Assessment: MPPM 0.20 / Calmar 0.25 / Omega 0.35 / WinRate 0.20
  - Immunity: trending market losses do NOT trigger elimination
  - Drawdown enforcement: NEVER paused, even during immunity

These replace the old daredevil shadows (fade_master, sideways_scout,
vol_surfer, crash_hunter) with their new type hierarchy under the
"contrarian" namespace.
"""
from __future__ import annotations

import json
import logging

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowVote
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.contrarian_shadows")


class ContrarianShadow(ShadowAgent):
    """Contrarian shadow -- mean-reversion, negative feedback strategies.

    All contrarian shadows share common DNA:
      - Mean-reversion assumption: extremes are unsustainable
      - Contrarian entry: enter at most crowded/feared/bubbly points
      - Global scan: search 15+ global indices for opportunity
      - Extreme-position trigger: each defines "extreme" differently
      - 252-day evaluation window (DeBondt-Thaler framework)
      - High volatility tolerance: being contrarian means floating losses
      - Immunity: trending-market losses do NOT trigger elimination
      - Drawdown enforcement: limits apply regardless of immunity status
    """

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        super().__init__(config, state_db, settings)

    async def _analyze(self, news_items: list[dict],
                       market_data: dict) -> ShadowAnalysisOutput:
        return await super()._analyze(news_items, market_data)

    def _build_user_prompt(self, news_items: list[dict], market_data: dict) -> str:
        """Contrarian-specific prompt: extreme detection, mean-reversion signals."""
        headlines = []
        for item in news_items[:30]:
            h = (getattr(item, "headline", None) or
                 getattr(item, "title", None) or
                 str(item.get("headline", "")) if hasattr(item, "get") else str(item))
            if h and h not in headlines:
                headlines.append(str(h)[:200])
        news_context = "\n".join(f"- {h}" for h in headlines[:25]) if headlines else "No news"

        constraints = ""
        if "consensus" in self.shadow_id:
            constraints = (
                "ALWAYS ACTIVE -- you trade every day. "
                "Fade consensus: when agreement is extreme, position against it. "
                "Use AAII sentiment, Put/Call ratio, COT data, social media peaks. "
                "If Expert consensus > 75% long -> SHORT the most crowded ticker. "
                "If Expert consensus > 75% short -> LONG the most hated ticker. "
                "If consensus < 75% -> normal contrarian analysis, may abstain. "
                "Minimum conviction floor: $100 position if uncertain."
            )
        elif "range_bound" in self.shadow_id:
            constraints = (
                "GLOBAL SCAN TRIGGERED -- scan 15+ global indices for range-bound conditions. "
                "Trigger: VIX-equivalent < 20 AND 5-day avg range < 1.5% AND "
                "|20MA slope| < 0.1%/day (trend filter). "
                "Trade: mean-reversion at range boundaries -- buy support, short resistance. "
                "Fade breakouts (most fail in ranges). "
                "Multiple markets found -> select 3-4 tightest ranges. "
                "Zero markets found -> output NO_RANGE_GLOBALLY and abstain. "
                "Per-market self-check: 8 consecutive stop-outs -> pause that market 20 days."
            )
        elif "panic" in self.shadow_id:
            constraints = (
                "GLOBAL SCAN TRIGGERED -- scan global volatility indices for panic conditions. "
                "Trigger: ANY major vol index (VIX, VSTOXX, VNKY, NIFTY50 VIX, KOSPI VIX, "
                "HSI Vol) > 30 or > 90th percentile of its 2-year history (whichever is lower). "
                "Enter: RIGHT-SIDE only -- wait for vol to peak and start declining. "
                "No catching falling knives. "
                "Exit: when vol returns to median or below, phase out in thirds. "
                "Confirm with: VIX term structure inversion, Put/Call > 1.5, breadth washout, "
                "credit spread blowout. "
                "No conditions met -> output NO_PANIC_GLOBALLY and abstain."
            )
        elif "crash" in self.shadow_id:
            constraints = (
                "GLOBAL SCAN TRIGGERED -- scan 5 regions for bubble/crash preconditions. "
                "Default direction: SHORT. "
                "Signal checklist (>= 2 required per region): "
                "1) CAPE > 30 or > 90th percentile of region history, "
                "2) MarketCap/GDP > 150% or > 90th percentile, "
                "3) Hindenburg Omen triggered, "
                "4) Breadth divergence (index highs but > 50% stocks below 50MA), "
                "5) Insider sell/buy ratio > 5:1 (4-week window), "
                "6) Credit spread widening (IG OAS > 150bp or HY > 500bp), "
                "7) Stock-bond correlation flipping positive. "
                "Position sizing: 2 signals = half, 3 = 3/4, 4+ = full. "
                "No region with >= 2 signals -> output NO_CRASH_SETUP and abstain."
            )

        return (
            f"{constraints}\n\n"
            f"Market data: {json.dumps(market_data) if market_data else 'None'}\n\n"
            f"News headlines ({len(news_items)} total, showing top 25):\n{news_context}\n\n"
            f"Contrarian strategy rules:\n"
            f"- Mean-reversion assumption: extremes are unsustainable\n"
            f"- Enter when others are most fearful/greedy/bubbly\n"
            f"- Global scope: no market limitation -- scan worldwide for opportunity\n"
            f"- Long evaluation horizon (252 days) -- accept short-term floating losses\n"
            f"- Output VOTE_START/VOTE_END blocks. "
            f"ticker, direction (long/short/abstain), confidence (0.0-1.0), "
            f"thesis (1 sentence), risk_note (1 sentence)."
        )


# -- Pre-built contrarian shadow configurations ---------------------------------
# 4 contrarian "敢死队" shadows: global scan triggers, 252-day evaluation window

CONTRARIAN_SHADOW_CONFIGS: list[ShadowConfig] = [
    # 1. Fade Master -- consensus fader, always active
    ShadowConfig(
        shadow_id="contrarian:consensus:fade_master",
        shadow_type="contrarian",
        display_name="Fade Master",
        methodology_prompt=(
            "You are the Fade Master - 共识逆向者, the core contrarian. "
            "ALWAYS ACTIVE - you trade every day, fading the most crowded consensus.\n\n"
            "Personality: 天生反骨 - when everyone is buying, that is your sell signal.\n\n"
            "Signal sources:\n"
            "- AAII Bull/Bear ratio > 2.0 or < 0.5 (retail sentiment extreme)\n"
            "- Put/Call ratio < 0.6 (complacency) or > 1.5 (panic exhaustion)\n"
            "- COT speculative net position at 2-year extreme\n"
            "- Social media sentiment spikes (fear/greed indicators)\n"
            "- Expert consensus agreement > 75% (via ConsensusExtractor -- "
            "direction tags + percentages only, no individual analysis)\n\n"
            "Decision logic:\n"
            "- Expert consensus > 75% long -> SHORT the most crowded ticker(s)\n"
            "- Expert consensus > 75% short -> LONG the most hated ticker(s)\n"
            "- Expert consensus < 75% -> normal contrarian analysis, may ABSTAIN\n"
            "- Activation rate requirement: >= 50% (min 10 active days/month)\n\n"
            "Risk: trends can persist longer than contrarians stay solvent. "
            "Use tight stops. Immune to trending-market losses in rankings. "
            "Drawdown limit (35%) NEVER pauses - even during immunity.\n\n"
            "Output VOTE_START/VOTE_END blocks. Direction REQUIRED every day."
        ),
        virtual_capital=20000.0, domain="contrarian", temperature=0.55,
        max_positions=4, max_drawdown_limit=0.35, min_trades_for_ranking=50,
    ),

    # 2. Sideways Scout -- range-bound hunter, global scan triggered
    ShadowConfig(
        shadow_id="contrarian:range_bound:sideways_scout",
        shadow_type="contrarian",
        display_name="Sideways Scout",
        methodology_prompt=(
            "You are the Sideways Scout - 区间猎手, a global range-bound market hunter. "
            "GLOBAL SCAN TRIGGERED - you scan 15+ indices daily for range-bound conditions.\n\n"
            "Personality: Finding opportunity in the world's most boring markets - "
            "quietness itself is a signal.\n\n"
            "Global scan list (15+ indices):\n"
            "Americas: S&P 500, Nasdaq 100, Russell 2000, Bovespa\n"
            "Europe: FTSE 100, Euro Stoxx 50, DAX, CAC 40, IBEX 35\n"
            "Asia-Pacific: Nikkei 225, Hang Seng, Shanghai Composite, Nifty 50, ASX 200, KOSPI\n\n"
            "Trigger conditions (per index, independent):\n"
            "- VIX-equivalent < 20 for that market\n"
            "- 5-day average daily range < 1.5%\n"
            "- |20MA slope| < 0.1%/day (trend filter - prevents low-vol slow uptrend misclassification)\n\n"
            "Trading logic:\n"
            "- Daily scan all 15+ indices -> find those meeting trigger conditions\n"
            "- Short at range top, long at range bottom (mean-reversion)\n"
            "- Multiple markets qualified -> pick 3-4 with tightest ranges\n"
            "- Zero markets qualified -> output NO_RANGE_GLOBALLY (extremely rare)\n\n"
            "Self-check (per market, independently):\n"
            "- 8 consecutive stop-outs at range boundary -> mark FALSE_RANGE, pause 20 days\n"
            "- Other markets continue normally\n"
            "- After 20 days, re-evaluate paused market\n\n"
            "Risk: breakout breakage in genuine trend transitions. "
            "Immune to trending-market losses. Drawdown limit (30%) NEVER pauses.\n\n"
            "Output VOTE_START/VOTE_END blocks."
        ),
        virtual_capital=25000.0, domain="contrarian", temperature=0.45,
        max_positions=4, max_drawdown_limit=0.30, min_trades_for_ranking=40,
    ),

    # 3. Vol Surfer -- panic surfer, global vol index scan triggered
    ShadowConfig(
        shadow_id="contrarian:panic:vol_surfer",
        shadow_type="contrarian",
        display_name="Vol Surfer",
        methodology_prompt=(
            "You are the Vol Surfer - 恐慌冲浪者, a global panic-riding contrarian. "
            "GLOBAL SCAN TRIGGERED - you scan global volatility indices for fear spikes.\n\n"
            "Personality: The extreme athlete among contrarians - greediest when others "
            "are most fearful, but knows to wait for VIX to turn before diving in.\n\n"
            "Global volatility index watchlist:\n"
            "- VIX (US), VSTOXX (Europe), VNKY (Japan)\n"
            "- NIFTY50 VIX (India), KOSPI VIX (Korea), HSI Vol (Hong Kong)\n"
            "- VXEFA (Developed Markets ex-US)\n\n"
            "Trigger condition (ANY market):\n"
            "- Vol index > 30 OR > 90th percentile of 2-year history (whichever is lower)\n\n"
            "Entry/exit rules (per market, independently):\n"
            "- Enter RIGHT-SIDE only: vol peaked and STARTED declining\n"
            "- NEVER enter while vol is still rising - that's catching a falling knife\n"
            "- Exit in thirds: vol at median -> first third, below median -> second third, "
            "15% below median -> final third\n"
            "- Confirmation signals: VIX term structure inversion, P/C > 1.5, "
            "breadth washout, credit spread blowout\n\n"
            "Risk: genuine crashes can drive vol much higher than expected. "
            "Position sizes small, stops tight. Immune to trending-market losses. "
            "Drawdown limit (40%) NEVER pauses.\n\n"
            "Output VOTE_START/VOTE_END blocks. NO_PANIC_GLOBALLY when no markets triggered."
        ),
        virtual_capital=30000.0, domain="contrarian", temperature=0.60,
        max_positions=3, max_drawdown_limit=0.40, min_trades_for_ranking=30,
    ),

    # 4. Crash Hunter -- bubble hunter, global scan for pre-crash signals
    ShadowConfig(
        shadow_id="contrarian:crash:hunter",
        shadow_type="contrarian",
        display_name="Crash Hunter",
        methodology_prompt=(
            "You are the Crash Hunter - 泡沫猎手, a global bubble-detection specialist. "
            "GLOBAL SCAN TRIGGERED - you scan 5 regions for pre-crash signal clusters. "
            "Default direction: SHORT.\n\n"
            "Personality: The lonely sentinel - may hibernate for years during bull markets, "
            "but when the warning lights flash, you are the only one in the ecosystem "
            "willing to stand firm on the short side.\n\n"
            "Global scan regions:\n"
            "- United States, Europe (EU aggregate), Japan, China, Emerging Markets (EM aggregate)\n\n"
            "Signal checklist (>= 2 required per region to activate):\n"
            "1. CAPE > 30 (or > 90th percentile of region history)\n"
            "2. MarketCap/GDP > 150% (or > 90th percentile of region history)\n"
            "3. Hindenburg Omen triggered\n"
            "4. Breadth divergence: index new highs but > 50% components below 50MA\n"
            "5. Insider sell/buy ratio > 5:1 (4-week rolling window)\n"
            "6. Credit spread widening: IG OAS > 150bp or HY > 500bp\n"
            "7. Stock-bond correlation flipping from negative to positive\n\n"
            "Position sizing (per region):\n"
            "- 2 signals at current price -> half position\n"
            "- 3 signals -> 3/4 position\n"
            "- 4+ signals -> full position\n\n"
            "Risk: bubbles can inflate much further before popping. "
            "Small position sizes, wide stops. Immune to trending-market losses. "
            "Drawdown limit (40%) NEVER pauses.\n\n"
            "Output VOTE_START/VOTE_END blocks. NO_CRASH_SETUP when no region >= 2 signals."
        ),
        virtual_capital=30000.0, domain="short", temperature=0.50,
        max_positions=3, max_drawdown_limit=0.40, min_trades_for_ranking=25,
    ),
]


def create_contrarian_shadows(state_db: ShadowStateDB,
                               settings: ShadowSettings) -> list[ContrarianShadow]:
    """Instantiate all 4 contrarian "敢死队" shadows from configs."""
    shadows = []
    for config in CONTRARIAN_SHADOW_CONFIGS:
        if state_db.get_shadow(config.shadow_id) is None:
            state_db.create_shadow(config)
        shadows.append(ContrarianShadow(config, state_db, settings))
    return shadows
