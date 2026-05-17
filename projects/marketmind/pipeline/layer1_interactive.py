"""L1 interactive narrative layer.

Compatibility adapter: wraps layer1_narrative for the older interactive API.
New callers should use layer1_narrative directly.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from marketmind.pipeline.layer1_narrative import Layer1Result, analyze_layer1
from marketmind.config.settings import MarketMindConfig


@dataclass
class ToolState:
    """Tracks L1 tool usage and quota during an interactive session."""
    calls_used: int = 0
    tool_results: list = field(default_factory=list)
    fact_broadcast: list = field(default_factory=list)
    tool_registry: Any = None
    gnews_remaining: int = 10
    yfinance_remaining: int = 50


@dataclass
class InteractiveState:
    """Interactive session state including tool tracking."""
    tools: ToolState = field(default_factory=ToolState)
    source_numbers: set = field(default_factory=set)


async def run_l1_interactive(
    config: MarketMindConfig,
    mock: bool = False,
    verbose: bool = False,
    shadow_count: int | None = None,
) -> tuple[Layer1Result, bool, dict[str, Any]]:
    """Run L1 narrative analysis. Returns (result, should_skip, extras)."""
    if mock:
        return (
            Layer1Result(
                event_grade="B", surprise_level="low", market_size="medium",
                matrix_quadrant="core_opportunity", price_in_score=0.5,
                cascade_rank=1, cascade_hub=False,
                sentiment_direction="bullish", sentiment_intensity=0.6,
                sentiment_vs_attention="high_sentiment",
                expert_signals=[], institutional_surprise="",
                key_characters=[], tail_risk_flags=[],
                raw_analysis="Mock L1 analysis.",
            ),
            False,
            {},
        )
    try:
        result = await analyze_layer1()
        return result, False, {}
    except Exception as e:
        return (
            Layer1Result(
                event_grade="C", surprise_level="low", market_size="small",
                matrix_quadrant="watch", price_in_score=0.5,
                cascade_rank=1, cascade_hub=False,
                sentiment_direction="neutral", sentiment_intensity=0.5,
                sentiment_vs_attention="balanced",
                expert_signals=[], institutional_surprise="",
                key_characters=[], tail_risk_flags=[],
                raw_analysis=f"L1 analysis failed: {e}",
            ),
            False,
            {},
        )
