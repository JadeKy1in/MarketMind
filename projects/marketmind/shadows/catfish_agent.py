"""Catfish Agent — DEPRECATED. Replaced by EcosystemAuditor (Phase 0).

ECOSYSTEM AUDITOR — NOT A SHADOW. Reads shadow output, does not produce votes.
This module exists for backward compatibility. New code should import directly
from `marketmind.shadows.ecosystem_auditor`.

The original Catfish was a minority-opinion enforcer triggered at >=80% consensus.
It has been replaced by the EcosystemAuditor, which provides broader blind-spot
detection: direction concentration, asset class neglect, methodology convergence,
and uncovered tickers. Python computes metrics, Pro interprets only when thresholds
are breached.
"""
from __future__ import annotations

import logging
import warnings

from marketmind.shadows.ecosystem_auditor import EcosystemAuditor, EcosystemAlert

logger = logging.getLogger("marketmind.shadows.catfish_agent")

# Re-export for backward compatibility
CATFISH_SYSTEM_PROMPT = (
    "CATFISH IS DEPRECATED. The ecosystem auditor now handles blind-spot detection. "
    "See marketmind.shadows.ecosystem_auditor."
)


class CatfishAgent:
    """DEPRECATED: Minority-opinion enforcer replaced by EcosystemAuditor.

    This wrapper delegates to EcosystemAuditor for backward compatibility.
    Catfish is now a mechanism, NOT a shadow — it does not produce votes.
    """

    def __init__(self, config=None, state_db=None, settings=None):
        warnings.warn(
            "CatfishAgent is deprecated. Use EcosystemAuditor instead.",
            DeprecationWarning, stacklevel=2,
        )
        self._auditor = EcosystemAuditor()
        self.config = config
        self.shadow_id = getattr(config, "shadow_id", "catfish:deprecated") if config else "catfish:deprecated"

    def check_consensus(self, votes, ticker):
        """DEPRECATED: Consensus check replaced by direction concentration audit."""
        if not votes or len(votes) < 3:
            return False, 0.0, "none"
        ticker_votes = [v for v in votes
                        if getattr(v, "ticker", "") == ticker
                        and getattr(v, "direction", "abstain") != "abstain"]
        if len(ticker_votes) < 3:
            return False, 0.0, "none"
        directions = {}
        for v in ticker_votes:
            d = getattr(v, "direction", "abstain")
            directions[d] = directions.get(d, 0) + 1
        max_dir = max(directions, key=directions.get)
        max_count = directions[max_dir]
        agreement_pct = max_count / len(ticker_votes) if ticker_votes else 0.0
        triggered = agreement_pct >= 0.80
        return triggered, agreement_pct, max_dir

    async def _analyze(self, news_items, market_data):
        """DEPRECATED: Returns empty analysis. Use EcosystemAuditor.run_audit()."""
        from datetime import datetime, timezone
        from marketmind.shadows.shadow_agent import ShadowAnalysisOutput
        return ShadowAnalysisOutput(
            shadow_id=self.shadow_id,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            votes=[],
            insights=["CATFISH_DEPRECATED — use EcosystemAuditor.run_audit()"],
            methodology_notes=CATFISH_SYSTEM_PROMPT[:200],
            quota_used=0,
        )

    def run_audit(self, votes, date=None):
        """Delegate to EcosystemAuditor.run_audit()."""
        return self._auditor.run_audit(votes, date)

    async def run_daily_analysis(self, news_items, market_data):
        """DEPRECATED: Returns empty output. Catfish no longer produces votes."""
        from datetime import datetime, timezone
        from marketmind.shadows.shadow_agent import ShadowAnalysisOutput
        return ShadowAnalysisOutput(
            shadow_id=self.shadow_id,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            votes=[],
            insights=["CATFISH_DEPRECATED — EcosystemAuditor handles blind spots"],
            methodology_notes=CATFISH_SYSTEM_PROMPT[:200],
            quota_used=0,
        )


# Backward-compatible config (deprecated)
CATFISH_CONFIG = None  # No longer a shadow config — use EcosystemAuditor directly


def create_catfish_agent(state_db=None, settings=None):
    """DEPRECATED: Creates a CatfishAgent wrapper. Use EcosystemAuditor instead."""
    warnings.warn(
        "create_catfish_agent is deprecated. Use EcosystemAuditor directly.",
        DeprecationWarning, stacklevel=2,
    )
    return CatfishAgent()
