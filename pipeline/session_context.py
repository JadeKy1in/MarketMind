"""Session context — shared state across interactive pipeline stages.

Red Team condition 1: _shadow_task remains module-level global in app.py.
Modules receive snapshots via elite_opinions, not direct shadow DB access.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from marketmind.config.settings import MarketMindConfig
from marketmind.pipeline.layer1_narrative import Layer1Result
from marketmind.pipeline.layer2_fundamental import Layer2Result
from marketmind.pipeline.layer3_technical import Layer3BatchResult
from marketmind.pipeline.decision import DecisionOutput


@dataclass
class SessionContext:
    """Immutable-ish context passed through pipeline stages.

    Fields set by glue layer (app.py) before each stage runs.
    Modules read fields; they should NOT mutate each other's output fields.
    """
    config: MarketMindConfig
    data_dir: str = "data"

    # Inputs (set by glue layer before L1)
    news_items: list = field(default_factory=list)
    signals: list = field(default_factory=list)
    insider_items: list = field(default_factory=list)   # content_type="insider_signal", bypasses Flash
    social_items: list = field(default_factory=list)    # content_type="social_mention", bypasses Flash

    # Stage outputs (set after each stage completes)
    l1_result: Layer1Result | None = None
    l1_session: dict = field(default_factory=dict)
    l2_result: Layer2Result | None = None
    l3_result: Layer3BatchResult | None = None
    decision: DecisionOutput | None = None

    # User selections
    selected_tickers: list[str] = field(default_factory=list)
    selected_strategy: str = ""  # "conservative" | "neutral" | "aggressive" | "" (not chosen)

    # ELITE snapshot (populated once after L1, before L2)
    elite_opinions: list[str] = field(default_factory=list)

    # Pre-Decision artifacts (set by glue layer after Red Team + Resonance)
    red_team_report: Any = None
    resonance: Any = None

    # Phase G Layer 6: Economic calendar (set by glue layer at stage 0.5)
    economic_events: dict = field(default_factory=dict)  # from check_economic_calendar()

    # Timing
    stage_times: dict[str, float] = field(default_factory=dict)


def get_date_context() -> str:
    """Generate standardized date context for LLM prompts — dual time anchor.

    Called fresh on every use (not cached) to avoid timestamp staleness
    during long-running sessions. Uses UTC to eliminate DST ambiguity.

    Returns a string suitable for appending to system prompts.
    """
    from datetime import datetime, timezone as _tz
    now = datetime.now(_tz.utc)
    today_str = now.strftime("%Y年%m月%d日")
    return (
        f"\n\n[TIME ANCHOR — READ CAREFULLY]\n"
        f"CURRENT DATE: {today_str} (UTC).\n"
        f"YOUR TRAINING CUTOFF: approximately January 2026.\n"
        f"All data from the current month that you do not have in training "
        f"is provided via the NEWS HEADLINES and MARKET SIGNALS below.\n"
        f"Do NOT assume any post-cutoff events unless they appear in the provided data.\n"
        f"Do NOT fabricate dates or timestamps — use only the CURRENT DATE above."
    )
