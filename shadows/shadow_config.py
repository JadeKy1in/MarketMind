"""Shadow configuration data types and validation.

Extracted from shadow_state.py per modular architecture rules (§3.1).
All dataclasses are pure data containers with no DB dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ShadowConfig:
    """JSON-serializable shadow configuration."""
    shadow_id: str
    shadow_type: str                 # "beta" | "expert" | "daredevil" | "temp_event" | "challenger" | "missed_path" | "catfish"
    display_name: str
    methodology_prompt: str          # the shadow's entire system prompt
    virtual_capital: float
    max_positions: int = 3
    model: str = "pro"               # "flash" | "pro"
    temperature: float = 0.3
    reasoning_effort: str = "max"
    domain: str | None = None
    max_drawdown_limit: float = 0.35
    min_trades_for_ranking: int = 5
    parent_shadow_id: str | None = None
    generation: int = 0
    status: str = "active"           # "active" | "paused" | "watch" | "endangered" | "eliminated"
    eliminated_at: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    _VALID_TYPES = {"beta", "expert", "daredevil", "temp_event", "challenger", "missed_path", "catfish"}
    _VALID_STATUSES = {"active", "paused", "watch", "endangered", "eliminated"}

    def __post_init__(self):
        if not self.shadow_id:
            raise ValueError("shadow_id must not be empty")
        if self.shadow_type not in self._VALID_TYPES:
            raise ValueError(f"shadow_type must be one of {self._VALID_TYPES}, got '{self.shadow_type}'")
        if self.status not in self._VALID_STATUSES:
            raise ValueError(f"status must be one of {self._VALID_STATUSES}, got '{self.status}'")
        if self.virtual_capital < 0:
            raise ValueError(f"virtual_capital must be >= 0, got {self.virtual_capital}")
        if self.virtual_capital == 0 and self.shadow_type not in ("missed_path", "temp_event"):
            raise ValueError(f"virtual_capital must be positive for shadow_type '{self.shadow_type}'")
        if self.max_positions < 0:
            raise ValueError(f"max_positions must be >= 0, got {self.max_positions}")
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError(f"temperature must be in [0.0, 2.0], got {self.temperature}")
        if self.max_drawdown_limit < 0:
            raise ValueError(f"max_drawdown_limit must be >= 0, got {self.max_drawdown_limit}")
        if self.min_trades_for_ranking < 0:
            raise ValueError(f"min_trades_for_ranking must be >= 0, got {self.min_trades_for_ranking}")
        if self.generation < 0:
            raise ValueError(f"generation must be >= 0, got {self.generation}")


@dataclass
class VirtualTradeOpen:
    shadow_id: str
    ticker: str
    direction: str                  # "long" | "short"
    entry_price: float
    position_size_pct: float
    entry_date: str


@dataclass
class VirtualTrade:
    trade_id: int
    shadow_id: str
    ticker: str
    direction: str
    entry_price: float
    exit_price: float | None
    position_size_pct: float
    entry_date: str
    exit_date: str | None
    exit_reason: str | None
    pnl_pct: float | None
    virtual_slippage_applied: float
    confidence_discount_applied: float
    paper_live_gap_ratio: float


@dataclass
class DailySnapshot:
    shadow_id: str
    date: str
    virtual_capital: float
    daily_return_pct: float | None = None
    cumulative_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    win_rate_pct: float | None = None
    sharpe_ratio: float | None = None
    calmar_ratio: float | None = None
    omega_ratio: float | None = None
    mppm_score: float | None = None
    composite_score: float | None = None
    deflated_score: float | None = None
    percentile_rank: float | None = None
    achievement_tier: str | None = None
    flash_quota_used: int = 0
    pro_quota_used: int = 0
    emergency_quotas_used: int = 0
    insights_generated: int = 0
    votes_produced: int = 0
    discount_rate: float | None = None


@dataclass
class IntegrityEvent:
    shadow_id: str
    date: str
    event_type: str                # "unverifiable_claim" | "false_claim" | "missing_source" | "verified_true"
    claim_detail: str              # JSON string
    score_change: int
    new_score: int


@dataclass
class EmergencyQuotaRequest:
    shadow_id: str
    requested_at: str
    confidence_self_report: int    # 8-10
    opportunity_description: str
    result: str = "pending"
    pnl_impact_pct: float | None = None
    quota_penalty_applied: str | None = None
    id: int | None = None          # set when loaded from DB


@dataclass
class CollusionFlag:
    date: str
    agreement_pct: float
    consecutive_days: int
    market_signal_strength: float  # 0-1
    verdict: str                   # "convergence" | "herding" | "pending_review"
    user_action: str | None = None
