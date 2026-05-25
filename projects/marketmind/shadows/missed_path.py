"""Missed path tracking — counterfactual path shadows, survivorship bias warning."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import ShadowStateDB
from marketmind.shadows.shadow_agent import ShadowAgent, ShadowAnalysisOutput
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.missed_path")


@dataclass
class MissedPathReport:
    shadow_id: str
    rejected_direction: str
    days_tracked: int
    cumulative_return: float
    would_have_been_profitable: bool
    survivorship_bias_warning: str


class MissedPathAgent(ShadowAgent):
    """Read-only shadow that tracks a rejected Gate 1 direction.
    Does NOT generate investment votes. Records-only.
    """

    def __init__(self, config, state_db: ShadowStateDB, settings: ShadowSettings):
        super().__init__(config, state_db, settings)

    async def _analyze(self, news_items: list,
                        market_data: dict,
                        broadcast_messages: list | None = None) -> ShadowAnalysisOutput:
        """Missed path only records, never votes."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return ShadowAnalysisOutput(
            shadow_id=self.shadow_id,
            date=today,
            decisions=[],  # Read-only agent — no trades
            methodology_notes="Missed path: tracking rejected direction counterfactually.",
        )

    def generate_report(self, days_tracked: int = 30) -> MissedPathReport:
        """Generate counterfactual performance report with survivorship bias warning."""
        snapshots = self.state_db.get_snapshot_history(self.shadow_id, days=days_tracked)
        if not snapshots:
            return MissedPathReport(
                shadow_id=self.shadow_id,
                rejected_direction=self.config.methodology_prompt.split(":")[-1].strip()
                if ":" in self.config.methodology_prompt else "unknown",
                days_tracked=0,
                cumulative_return=0.0,
                would_have_been_profitable=False,
                survivorship_bias_warning=_SURVIVORSHIP_WARNING,
            )

        # Calculate cumulative return from snapshots
        returns = [s.daily_return_pct or 0.0 for s in snapshots if s.daily_return_pct is not None]
        cum_return = sum(returns) if returns else 0.0

        return MissedPathReport(
            shadow_id=self.shadow_id,
            rejected_direction=self.config.methodology_prompt.split(":")[-1].strip()
            if ":" in self.config.methodology_prompt else "unknown",
            days_tracked=len(snapshots),
            cumulative_return=cum_return,
            would_have_been_profitable=cum_return > 0,
            survivorship_bias_warning=_SURVIVORSHIP_WARNING,
        )


_SURVIVORSHIP_WARNING = (
    "SURVIVORSHIP BIAS WARNING: This missed-path analysis tracks only directions "
    "that were actively rejected. It does NOT account for the universe of all possible "
    "directions that were never considered. The observed performance of rejected paths "
    "may be inflated by post-hoc selection. Use this data as a directional sanity check, "
    "not as a basis for strategy modification."
)


def create_missed_path_report(state_db: ShadowStateDB,
                               settings: ShadowSettings,
                               days: int = 30) -> list[MissedPathReport]:
    """Generate reports for all active missed_path shadows."""
    reports = []
    for shadow in state_db.get_active_shadows("missed_path"):
        agent = MissedPathAgent(shadow, state_db, settings)
        reports.append(agent.generate_report(days))
    return reports
