"""Session context — shared state passed through the interactive pipeline stages."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionContext:
    """Mutable context carried through all pipeline stages.

    Each stage reads from and writes to this context. No stage modifies
    another stage's private fields directly.
    """
    config: Any  # MarketMindConfig

    # L2 output
    selected_tickers: list[str] = field(default_factory=list)
    selected_strategy: str = ""

    # Stage results (populated by each stage on completion)
    l1_result: Any = None
    l2_result: Any = None
    l3_result: Any = None
    decision: Any = None
