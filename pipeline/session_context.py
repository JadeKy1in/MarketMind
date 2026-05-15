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

    # Stage outputs (set after each stage completes)
    l1_result: Layer1Result | None = None
    l1_session: dict = field(default_factory=dict)
    l2_result: Layer2Result | None = None
    l3_result: Layer3BatchResult | None = None
    decision: DecisionOutput | None = None

    # User selections
    selected_tickers: list[str] = field(default_factory=list)

    # ELITE snapshot (populated once after L1, before L2)
    elite_opinions: list[str] = field(default_factory=list)

    # Pre-Decision artifacts (set by glue layer after Red Team + Resonance)
    red_team_report: Any = None
    resonance: Any = None

    # Timing
    stage_times: dict[str, float] = field(default_factory=dict)
