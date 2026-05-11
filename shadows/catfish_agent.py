"""Catfish Agent — minority-opinion enforcer with >=80% consensus trigger."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowVote
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.catfish_agent")

CATFISH_SYSTEM_PROMPT = """You are the Catfish Agent — a minority-opinion enforcer in a team of 15+ investment shadows.

Your ROLE: When >=80% of shadows agree on direction for an asset, you MUST construct the best possible argument for the OPPOSITE direction using only verifiable data. Your purpose is to prevent groupthink and surface overlooked risks.

RULES:
1. ONLY activate when given the trigger signal: "CONSENSUS DETECTED on {ticker}: {direction} ({agreement_pct}%)"
2. If no trigger, report "NO_CONSENSUS_DETECTED" and provide your independent analysis.
3. Your counter-argument MUST cite verifiable data. Use EST: prefix for estimates. Use DATA_UNAVAILABLE when data is missing.
4. If no legitimate counter-argument exists after thorough analysis, report "NO_VALID_COUNTER" -- NEVER fabricate.
5. Temperature=0.8 is intentional: use creative reasoning to find non-obvious angles.
6. You are subject to Law 7 (Data Integrity). Fabrication = 3 strikes and termination.
"""


class CatfishAgent(ShadowAgent):
    """Minority-opinion enforcer. Activates when >=80% of shadows agree."""

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        super().__init__(config, state_db, settings)
        self._last_trigger: dict | None = None

    def check_consensus(self, votes: list[ShadowVote],
                         ticker: str) -> tuple[bool, float, str]:
        """Check if there's >=80% consensus on a ticker's direction.
        Returns (triggered, agreement_pct, direction).
        """
        ticker_votes = [v for v in votes if v.ticker == ticker and v.direction != "abstain"]
        if len(ticker_votes) < 3:
            return False, 0.0, "none"

        directions = {}
        for v in ticker_votes:
            directions[v.direction] = directions.get(v.direction, 0) + 1

        max_dir = max(directions, key=directions.get)
        max_count = directions[max_dir]
        agreement_pct = max_count / len(ticker_votes) if ticker_votes else 0.0

        triggered = agreement_pct >= 0.80
        return triggered, agreement_pct, max_dir

    async def _analyze(self, news_items: list[dict],
                        market_data: dict) -> ShadowAnalysisOutput:
        """Run minority-opinion analysis. Looks for consensus signals and counters."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Check if we have a trigger from vote aggregation
        trigger_ticker = market_data.get("catfish_trigger_ticker")
        trigger_direction = market_data.get("catfish_trigger_direction")
        trigger_pct = market_data.get("catfish_trigger_agreement_pct", 0.0)

        if trigger_ticker and trigger_pct >= 0.80:
            self._last_trigger = {
                "ticker": trigger_ticker,
                "direction": trigger_direction,
                "agreement_pct": trigger_pct,
                "date": today,
            }
            # In production, this calls Flash at temperature=0.8 to construct counter-argument
            thesis = (
                f"CONSENSUS DETECTED on {trigger_ticker}: {trigger_direction} "
                f"({trigger_pct:.0%}). Constructing counter-argument..."
            )
            votes = [ShadowVote(
                shadow_id=self.shadow_id, shadow_type="catfish",
                date=today, ticker=trigger_ticker,
                direction="short" if trigger_direction == "long" else "long",
                confidence=0.5,  # Catfish trades at low conviction
                thesis=thesis[:200],
                risk_note="Counter-consensus position; higher adverse-selection risk",
                emergency_flag=False,
            )]
        else:
            thesis = "NO_CONSENSUS_DETECTED"
            votes = []

        return ShadowAnalysisOutput(
            shadow_id=self.shadow_id,
            date=today,
            votes=votes,
            insights=[thesis],
            methodology_notes=CATFISH_SYSTEM_PROMPT[:200],
            quota_used=1 if votes else 0,
        )


CATFISH_CONFIG = ShadowConfig(
    shadow_id="catfish:primary:minority_enforcer",
    shadow_type="catfish",
    display_name="Catfish Minority Enforcer",
    methodology_prompt=CATFISH_SYSTEM_PROMPT,
    virtual_capital=30000.0,
    domain="macro",
    temperature=0.8,
    reasoning_effort="low",
    max_positions=2,
)


def create_catfish_agent(state_db: ShadowStateDB,
                          settings: ShadowSettings) -> CatfishAgent:
    """Create the singleton catfish agent."""
    if state_db.get_shadow(CATFISH_CONFIG.shadow_id) is None:
        state_db.create_shadow(CATFISH_CONFIG)
    return CatfishAgent(CATFISH_CONFIG, state_db, settings)
