"""Type definitions for shadow ecosystem — dataclasses extracted from shadow_agent.py."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShadowDecision:
    """A shadow's independent investment decision for a single ticker.

    NOT a vote — each shadow makes its own trade judgment (long/short/abstain).
    Renamed from ShadowVote to reflect that DD-001 (shadows do not vote on
    collective decisions) is LOCKED. These are individual trade decisions,
    NOT votes in a consensus mechanism.
    """
    shadow_id: str
    shadow_type: str
    date: str
    ticker: str
    direction: str           # "long" | "short" | "abstain"
    confidence: float        # 0.0-1.0
    thesis: str              # 1-sentence reason
    risk_note: str           # 1-sentence risk
    emergency_flag: bool = False  # confidence >= 8/10?


@dataclass
class PositionCheck:
    trade_id: int
    ticker: str
    direction: str
    entry_price: float
    current_pnl_pct: float
    days_held: int
    should_exit: bool
    exit_reason: str | None = None
    confidence: float | None = None   # LLM-parsed confidence


@dataclass
class ShadowAnalysisOutput:
    shadow_id: str
    date: str
    decisions: list[ShadowDecision] = field(default_factory=list)
    position_checks: list[PositionCheck] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    methodology_notes: str = ""
    quota_used: int = 0
    latency_ms: int = 0


@dataclass
class ExternalObservation:
    """Observation from external multi-modal input (screenshot, PDF, audio, text)."""
    observation_id: str
    source_type: str          # "image" | "pdf" | "screenshot" | "text" | "audio"
    source_path: str          # original file path or URI
    extracted_text: str       # text extracted by Gemini Flash / OCR
    metadata: dict = field(default_factory=dict)
    confidence: float = 1.0   # extraction confidence 0.0-1.0
    source_attribution: str = ""  # who/what provided this observation
    evaluated_at: str = ""    # ISO 8601 timestamp of ingestion


@dataclass
class MemoryQuery:
    """Query parameters for searching layered shadow memory."""
    tier: str = "working"     # "working" | "episodic" | "semantic" | "all"
    ticker: str | None = None
    domain: str | None = None
    min_belief_strength: float = 0.0
    limit: int = 20
    tags: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class CrystallizationResult:
    """Output from knowledge crystallization cycle."""
    insight_id: str
    hypothesis: str
    validation_score: float   # backtest hit_rate or statistical significance
    action: str               # "promote" | "retire" | "hold"
    methodology_changes: list[str] = field(default_factory=list)
    source_insight_ids: list[str] = field(default_factory=list)
    evidence_summary: str = ""
    source_shadow_id: str = ""  # P1-2: direct shadow_id for prompt injection
