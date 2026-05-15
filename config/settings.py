"""MarketMind configuration loaded from environment variables."""
from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class ShadowSettings:
    """Phase B shadow ecosystem configuration."""
    # General
    shadows_enabled: bool = True
    shadows_db_path: str = "data/shadows/shadows.db"
    max_concurrent_shadows: int = 5
    shadow_flash_quota_default: int = 5
    shadow_pro_quota_default: int = 1
    shadow_consensus_timeout_s: int = 60  # D: max wait for shadow results before Decision

    # Ranking
    evaluation_window_days: int = 90
    progressive_window_floor: int = 30
    parametric_threshold_n: int = 30
    composite_weights: dict = field(default_factory=lambda: {
        "mppm": 0.35, "calmar": 0.25, "omega": 0.20, "win_rate": 0.20
    })
    achievement_percentiles: dict = field(default_factory=lambda: {
        "endangered": 0.15, "watch": 0.30, "excellent": 0.70, "elite": 0.85
    })
    elite_consecutive_days: int = 30
    excellent_consecutive_days: int = 10
    watch_consecutive_days: int = 10
    endangered_consecutive_days: int = 20
    elite_deflated_sharpe_min: float = 0.8
    excellent_deflated_sharpe_min: float = 0.6
    watch_mdd_threshold: float = 0.30

    # Emergency quota
    emergency_confidence_threshold: int = 8
    emergency_extra_calls: int = 3
    emergency_profit_reward_perm: bool = True
    emergency_loss_penalty_days: int = 3
    emergency_loss_followed_penalty_days: int = 7
    emergency_consecutive_fail_limit: int = 3

    # Challenger
    challenger_stage1_periods: int = 2
    challenger_stage2_periods: int = 3
    challenger_stage3_weeks: int = 2
    challenger_trial_alpha: float = 0.10
    challenger_calmar_gate: float = 0.3

    # Paper-to-Live gap
    virtual_slippage_atr_pct: float = 0.005
    confidence_discount_default: float = 0.20
    confidence_discount_floor: float = 0.05
    gap_closure_adjustment_factor: float = 0.75
    absolute_return_benchmark: float = 0.04  # risk-free rate proxy for calibration
    live_ready_min_trades: int = 10
    live_ready_max_gap: float = 0.30

    # Collusion
    collusion_agreement_threshold: float = 0.80
    collusion_consecutive_days_flag: int = 3
    collusion_consecutive_days_audit: int = 10
    collusion_market_signal_threshold: float = 0.70

    # Cash reframing A/B test
    cash_reframing_cohort_size: int = 6
    cash_reframing_test_days: int = 90
    cash_reframing_non_inferiority_margin: float = 0.02
    cash_reframing_de_alpha: float = 0.10

    # Plateau detection (thresholds tightened in Phase 2)
    plateau_no_elite_days: int = 60
    plateau_wr_range_pp: float = 10.0
    plateau_no_insight_days: int = 30
    max_resets_per_month: int = 2
    # Anti-conservatism weights (Phase 2)
    abstention_penalty_weight: float = 0.05
    quota_efficiency_weight: float = 0.05
    # Reset eligibility (Phase 2)
    reset_no_excellent_months: int = 6
    reset_flat_wr_months: int = 3
    reset_no_insight_months: int = 3

    # Scheduler settings
    scheduler_enabled: bool = False
    reflection_interval_minutes: int = 60
    crystallization_interval_hours: int = 6
    max_concurrent_tasks: int = 3

    # Gemini Flash settings
    gemini_api_key: str = field(default="", repr=False)
    gemini_flash_enabled: bool = False

    # Missed paths
    missed_path_max_per_gate: int = 2
    missed_path_report_days: int = 30

    # AEL Evolution Experiment (Phase 7 — set to True to activate)
    # When enabled, selected shadows get monthly Pro debriefs (slow-layer evolution).
    # Requires: Phase 6 daredevil restructure, Pro default (Phase 0), health monitoring (Phase 3).
    # Experiment pairs: Range-Bound/Momentum Daredevils + Tech/Macro Experts.
    # Each treatment shadow has a replica (control) — compare after 2-3 months.
    # NOTE: Challengers inherit ORIGINAL methodology prompts, not AEL-evolved ones.
    ael_experiment_enabled: bool = False
    ael_debrief_day: int = 1  # day of month to run debrief (1st)

    # Crystallization (knowledge crystallization engine)
    crystallization_enabled: bool = False
    crystallization_significance_threshold: float = 0.6
    crystallization_min_samples: int = 10

    # Circuit breaker (P3-3)
    fallback_provider_url: str = ""
    fallback_model: str = ""
    fallback_api_key: str = field(default="", repr=False)
    circuit_breaker_threshold: int = 3
    circuit_breaker_timeout_s: int = 30
    proxy_url: str = ""  # HTTP(S) proxy for outbound requests (e.g., VPN local proxy)


@dataclass
class MarketMindConfig:
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""), repr=False)
    deepseek_api_keys: list[str] = field(default_factory=lambda: [
        k.strip() for k in os.getenv("DEEPSEEK_API_KEYS", "").split(",") if k.strip()
    ], repr=False)
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    newsapi_key: str | None = field(default_factory=lambda: os.getenv("NEWSAPI_KEY"))
    gnews_key: str | None = field(default_factory=lambda: os.getenv("GNEWS_API_KEY"))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("MARKETMIND_DATA_DIR", "data")))
    max_position_count: int = 6
    max_total_heat_pct: float = 0.25
    daily_token_budget: int = 2_000_000
    daily_pro_limit: int = 30
    daily_flash_limit: int = 100
    cache_ttl_seconds: int = 300
    proxy_url: str = field(default_factory=lambda: os.getenv("HTTP_PROXY", os.getenv("HTTPS_PROXY", "")))
    session_checkpoint_dir: Path | None = None
    position_protection_days: int = 60
    shadow: ShadowSettings = field(default_factory=ShadowSettings)

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        if self.session_checkpoint_dir is None:
            self.session_checkpoint_dir = self.data_dir / "sessions"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @classmethod
    def from_env(cls) -> "MarketMindConfig":
        return cls()

    def validate(self) -> list[str]:
        errors = []
        if not self.deepseek_api_key:
            errors.append("DEEPSEEK_API_KEY is required")
        if self.max_position_count < 1:
            errors.append("max_position_count must be >= 1")
        if self.max_total_heat_pct <= 0 or self.max_total_heat_pct > 1:
            errors.append("max_total_heat_pct must be in (0, 1]")
        if self.shadow.shadows_enabled:
            if self.shadow.max_concurrent_shadows < 1:
                errors.append("shadow.max_concurrent_shadows must be >= 1")
            if self.shadow.evaluation_window_days < 30:
                errors.append("shadow.evaluation_window_days must be >= 30")
            if not (0 < self.shadow.collusion_agreement_threshold <= 1):
                errors.append("shadow.collusion_agreement_threshold must be in (0, 1]")
            if self.shadow.confidence_discount_floor >= self.shadow.confidence_discount_default:
                errors.append("shadow.confidence_discount_floor must be < confidence_discount_default")
            if self.shadow.virtual_slippage_atr_pct < 0:
                errors.append("shadow.virtual_slippage_atr_pct must be >= 0")
            pcts = self.shadow.achievement_percentiles
            if not (pcts["endangered"] < pcts["watch"] < pcts["excellent"] < pcts["elite"]):
                errors.append("achievement_percentiles must be strictly ordered: endangered < watch < excellent < elite")
        return errors
