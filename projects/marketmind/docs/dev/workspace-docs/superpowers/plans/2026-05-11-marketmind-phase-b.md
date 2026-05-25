# MarketMind Phase B -- Shadow Ecosystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Shadow Ecosystem -- 15+ concurrent AI agents running alongside the main pipeline, competing on multi-metric composite scores, with automated ranking, achievement ladders, challenger elimination, emergency quota, collusion detection, and paper-to-live gap management.

**Architecture:** Shadows extend the existing DeepSeek gateway, using the same `async_client.py` and `token_budget.py`. Each shadow is an independent agent with its own methodology prompt, virtual portfolio, and integrity score. Shadows run in parallel via `asyncio.gather()` with configurable concurrency gates. State persists to SQLite (`shadows.db`) with JSON config per shadow. Ranking is pure Python computation (no LLM). Shadow Mother monitors events and manages temporary shadow lifecycle.

**Tech Stack:** Python 3.11+, httpx (async), feedparser, pytest + pytest-mock, SQLite3 (shadows.db), JSON config files

---

## Architect Decisions: Resolver Q1-Q10

These decisions are binding on all Phase B implementations. They resolve the 10 open questions from the Quant Analyst's methodology document.

### Q1: Shadow State Persistence -- SQLite (shadows.db)

**Decision:** SQLite as the primary state store (`data/shadows/shadows.db`), with JSON config files for human-readable shadow definitions.

**Rationale:** 15+ concurrent shadows running daily create complex state (virtual portfolio, trade history, integrity scores, ranking history). SQLite supports concurrent reads, complex queries (ranking across time windows, collusion detection, history lookups), and is more robust for multi-process access than JSON. Individual shadow configs (methodology prompt, initial capital, shadow type) remain JSON for git-diff friendly human editing.

**Schema tables:** `shadows`, `virtual_trades`, `daily_snapshots`, `ranking_history`, `integrity_events`, `emergency_quotas`, `collusion_flags`

### Q2: Percentile Computation at Small N -- Hybrid Parametric/Empirical

**Decision:** At N=15 (standard starting shadow count), use logistic-normal parametric percentile estimation. At N >= 30, switch to empirical percentile. Transition is smooth: weights (alpha=N/30, up to 1.0) blend from parametric to empirical.

**Rationale:** Small-N empirical percentiles are unstable (single shadow can shift p85 by >5pp). The logistic-normal distribution is a good fit for financial performance metrics per the Witzany (2021) framework. At N>=30, CLT makes empirical reliable. The blended transition ensures no discontinuity when shadows are added/removed.

### Q3: Evaluation Window T -- Fixed 90-Day Rolling with Progressive Floor

**Decision:** Primary evaluation window is a fixed rolling 90 days. New shadows get a progressive window: Day 1-29: use available days (min 5 trades required for first score); Day 30-89: use 30-day window; Day 90+: use full 90-day window. Reports show both 30d and 90d scores for transparency.

**Rationale:** Full history incentivizes longevity (shadows accumulate positive carry) which is undesirable -- a good shadow on day 91 should rank above a mediocre shadow on day 365. Fixed rolling window is fair. Progressive floor prevents new shadows from being ranked at zero.

### Q4: Challenger Visibility -- Blind to User and Original Shadow

**Decision:** Challenger shadows operate in complete opacity. They do NOT appear in the ranking dashboard, status cards, or shadow list. Only the 2-week comparison trial results are surfaced to the user (as a "Challenger Trial Result" notification). The original shadow is NEVER informed of the challenger's existence (enforced by separate SQLite tables with no cross-reference accessible by shadow logic).

**Rationale:** Prevents gaming (original shadow changing behavior if it knows it's being challenged) and prevents user bias (prematurely favoring/disliking either party). The 2-week blind comparison is the scientific gold standard.

### Q5: Catfish Agent Methodology -- High-Temperature Minority-Opinion Prompt

**Decision:** Catfish uses the same model (deepseek-v4-flash) with temperature=0.8 and reasoning_effort="low" to create genuine cognitive diversity. System prompt explicitly instructs: "When >=80% of shadows agree on direction for {ticker}, you MUST construct the best possible argument for the OPPOSITE direction using only verifiable data. If no legitimate counter-argument exists, report 'NO_VALID_COUNTER' -- never fabricate." This is NOT inverse logic (trivially predictable) and NOT random subsampling (no analytical value). It is structured adversarial reasoning with a specific trigger condition.

**Rationale:** Inverse logic (always opposite) is predictable and ignores market reality. Different model allocation is expensive and doesn't guarantee minority opinion. Structured conditional contrarianism creates genuine analytical diversity while respecting Law 7 (no fabrication).

### Q6: Composite Score Decomposition -- Progressive Disclosure

**Decision:** Default UI view shows: achievement tier icon + composite percentile rank + trend arrow. Click-through expands to show all 4 component scores (MPPM 35%, Calmar 25%, Omega 20%, Win Rate 20%) with 90-day sparklines and contribution-to-change indicators. On no-trade days, decomposition is shown inline (since "why am I not trading" is a primary question).

**Rationale:** Summary-first design follows spec's Info Diet principle (80-120 words, progressive disclosure). Power users need component scores to understand why a shadow is rising/falling. The spec already requires this level of transparency (Section 7.2).

### Q7: Collusion Detection Protocol -- Automated Detection + Human Review

**Decision:** Automated statistical flag (>=80% agreement for 3 consecutive days, binomial test P~4.4e-5) triggers notification to user. Market-driven convergence vs. herding is discriminated automatically (market_signal_strength > 0.70 -> convergence; <= 0.70 -> herding). Herding detections are escalated to user for review. User action options: "Dismiss (market convergence)", "Investigate (run institutional analysis)", "Acknowledge (note in log)". Automated audit runs daily; human review required only for herding flags (expected <1/month).

**Rationale:** False positives from genuine market convergence must be distinguished from behavioral herding. The statistical gate handles this discrimination. Human review provides oversight without burdening daily operation.

### Q8: Shock Calibration Stability -- Monthly Review + Trigger Exception

**Decision:** Scheduled monthly review (first trading day of month). Exception triggers for immediate review: (a) single-asset 24h |return| > 7 sigma_60d, (b) VIX > 40, (c) major geopolitical event detected by Shadow Mother. Stability metric: per-category calibration parameter distributions (pre-shock vs. post-shock) compared via Kolmogorov-Smirnov test. KS statistic p < 0.05 in any category -> recalibrate that category.

**Rationale:** Monthly is frequent enough to catch drift but infrequent enough to avoid over-calibration. Trigger exceptions handle acute regime changes (2020 COVID, 2022 rate hikes, etc.). KS test provides statistical rigor for recalibration decisions.

### Q9: GapRatio Without Real Trades -- Permanent 20% Discount + Inter-Shadow Validation

**Decision:** Permanent 20% baseline discount on all shadow-reported returns. Additionally, implement inter-shadow GapRatio validation: compare each shadow's virtual PnL for ticker T on date D against the median shadow PnL for the same ticker/date. Shadows consistently underperforming peers after slippage correction (GapRatio > 0.3 for 30+ days) have their methodology flagged for review. This provides internal validation of the 20% baseline without requiring real trade data.

**Rationale:** Without real brokerage data, the 20% discount is conservative but unvalidated. Inter-shadow comparison provides a self-referential check: if 14/15 shadows produce similar returns and 1 shadow is an outlier, the outlier's methodology is suspect independent of the discount rate. The 20% baseline remains until live trade data accumulates (Phase D).

### Q10: Cash Reframing Isolation -- Gateway-Level M1 Injection

**Decision:** Cash reframing is enforced at the gateway level via a specialized M1 protocol injection, NOT per-shadow prompt engineering. Every LLM call tagged with context `"cash_reframing": true` receives: `[CASH_REFRAMING_PROTOCOL] You are evaluating whether to hold {ticker} in a portfolio. If you had ${virtual_cash} in cash today with no existing positions, would you purchase {ticker} at current market price? Reason with the same analytical rigor you apply to new opportunities. Ignore sunk cost, entry price, and current P&L.` This is injected by `chat_with_integrity()` when the caller passes `cash_reframing_ticker`.

**Rationale:** Consistency is critical -- if different shadows have different reframing interpretations, ranking comparisons are invalid. Gateway-level enforcement ensures all shadows use the identical framing protocol. Prompt-level per-shadow variation would create an unaccounted-for variable in the ranking engine.

---

## File Structure

```
projects/marketmind/
├── shadows/                          # NEW -- shadow ecosystem
│   ├── __init__.py
│   ├── shadow_state.py               # SQLite schema, JSON config models, CRUD operations
│   ├── shadow_mother.py              # Event detection, temp shadow create/destroy, prioritization
│   ├── shadow_agent.py               # Base shadow agent class, daily analysis cycle
│   ├── ranking_engine.py             # Composite score, Bayesian haircut, achievement ladder (pure Python)
│   ├── expert_shadows.py             # Domain-specific expert shadow configs + methodology prompts
│   ├── daredevil_shadows.py          # Direction-forced, event hound, contrarian configs
│   ├── catfish_agent.py              # Minority-opinion enforcer with trigger detection
│   ├── challenger_engine.py          # 3-stage buffer, secret creation, paired comparison
│   ├── knowledge_filter.py           # Learngenes quality filter for challenger inheritance
│   ├── paper_live_gap.py             # Virtual slippage, confidence discount, GapRatio tracking
│   ├── emergency_quota.py            # Confidence-based extra call application + audit
│   ├── collusion_detector.py         # Agreement statistics, herding vs. convergence discrimination
│   ├── cash_reframing.py             # A/B test coordinator, treatment/control cohort management
│   └── missed_path.py                # Counterfactual path tracking (Gate 1 rejected directions)
├── tests/
│   └── test_shadows/                 # NEW -- all shadow tests
│       ├── __init__.py
│       ├── conftest.py               # Shadow-specific fixtures (mock shadow DB, mock agents)
│       ├── test_shadow_state.py
│       ├── test_shadow_mother.py
│       ├── test_shadow_agent.py
│       ├── test_ranking_engine.py
│       ├── test_expert_shadows.py
│       ├── test_daredevil_shadows.py
│       ├── test_catfish_agent.py
│       ├── test_challenger_engine.py
│       ├── test_knowledge_filter.py
│       ├── test_paper_live_gap.py
│       ├── test_emergency_quota.py
│       ├── test_collusion_detector.py
│       ├── test_cash_reframing.py
│       └── test_missed_path.py
└── ui/
    ├── shadow_panel.py               # NEW -- shadow ranking dashboard panel
    └── shadow_status_card.py         # NEW -- individual shadow status card
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `config/settings.py` | Add `ShadowConfig` dataclass with shadow count limits, virtual capital defaults, evaluation windows, percentile parameters, emergency quota rules, collusion thresholds, paper-live discount rates, cash reframing cohort sizes, and `shadows_db_path` |
| `gateway/async_client.py` | Add `cash_reframing_ticker` parameter to `chat_with_integrity()` for M1 cash-reframing injection |
| `gateway/token_budget.py` | Add `SHADOW = 5` to Priority enum; add `emergency_quota` reservation method (bypasses normal limits with cap) |
| `pipeline/decision.py` | Add `shadow_votes: dict[str, ShadowVote]` parameter to `generate_decision()` -- shadow consensus feeds into Gate 2 signal confirmation |
| `storage/archivist.py` | Add `init_shadow_tables()` method for shadow-specific FTS5 tables; add `index_shadow_snapshot()` and `index_shadow_trade()` |
| `integrity/watchdog.py` | Add shadow-specific agent_id convention (`shadow:{type}:{name}`); shadow strikes tracked in shadow state |
| `app.py` | Add `--shadows N` CLI flag; wire shadow ecosystem into daily pipeline (pre-market: Shadow Mother; Phase 4: shadow batch run; Phase 5: ranking + collusion; post-session: challenger check + emergency audit) |
| `ui/main_window.py` | Add "Shadows" nav button; instantiate `ShadowPanel`; wire shadow completion callbacks |
| `ui/async_bridge.py` | Add `submit_batch()` method for parallel shadow execution with per-shadow progress callback |

---

## Sub-Phase B.0: Foundation -- Shadow State + Config + Mother Detection

| Step | Who | What |
|------|-----|------|
| B.0.1 | **Quant Analyst** | Review and approve Architect's Q1-Q10 decisions. Produce `METHODOLOGY_REVIEW_B0` |
| B.0.2 | **Architect** | Design shadow state schema, config extension, Shadow Mother interface. Produce `ARCHITECTURE_HANDOFF_B0` |
| B.0.3 | **Data Engineer** | Implement `shadows/shadow_state.py` -- SQLite schema + JSON config models + CRUD |
| B.0.4 | **Data Engineer** | Implement `config/settings.py` shadow extensions |
| B.0.5 | **Red Team** | Audit B.0: verify DB schema handles concurrent writes, config validation, edge cases |
| B.0.6 | **Optimization Scout** | Review B.0 outputs; report |

---

### Task B.0.1: Quant Analyst Review -- Resolver Decisions

**Agent:** Quant Analyst (Sonnet 1M)
**Files:** None created (review only)

Quant Analyst reads the 10 resolved questions in this plan's preamble and produces `METHODOLOGY_REVIEW_B0` covering:
1. Do the decisions align with the Quant Analyst's original methodology intent?
2. Are there edge cases the Architect missed in the resolutions?
3. Specific risk: Does the Q2 hybrid percentile approach maintain monotonicity as N changes?
4. Specific risk: Does Q5 catfish methodology produce enough analytical diversity?
5. Specific risk: Does Q9 inter-shadow GapRatio produce a meaningful signal at N=15 shadows?

Output to `.claude/reviews/B0_methodology_review.md`.

---

### Task B.0.2: Architect Handoff -- Foundation Design

**Agent:** Architect (Opus 1M)
**Files:** None created (design only)

Architect produces `ARCHITECTURE_HANDOFF_B0` covering:

**1. Shadow State Schema** -- `shadows/shadow_state.py`:

```python
# Database path: data/shadows/shadows.db

# Table: shadows
#   id TEXT PRIMARY KEY              -- "expert:gold:gold_bug_01"
#   shadow_type TEXT NOT NULL        -- "beta" | "expert" | "daredevil" | "temp_event" | "challenger" | "missed_path" | "catfish"
#   display_name TEXT NOT NULL       -- "Gold Bug Alpha"
#   status TEXT NOT NULL DEFAULT 'active'  -- "active" | "paused" | "watch" | "endangered" | "eliminated"
#   methodology_prompt TEXT          -- the shadow's system prompt (NULL = use type default)
#   config_json TEXT                 -- JSON blob: virtual_capital, max_positions, model, temp, etc.
#   created_at TEXT                  -- ISO 8601
#   eliminated_at TEXT               -- ISO 8601 or NULL
#   parent_shadow_id TEXT            -- for challengers: the shadow being challenged
#   generation INTEGER DEFAULT 0     -- how many elimination cycles this seat has seen

# Table: virtual_trades
#   id INTEGER PRIMARY KEY AUTOINCREMENT
#   shadow_id TEXT NOT NULL          -- FK to shadows.id
#   ticker TEXT NOT NULL
#   direction TEXT NOT NULL          -- "long" | "short"
#   entry_price REAL NOT NULL
#   exit_price REAL                  -- NULL if still open
#   position_size_pct REAL NOT NULL
#   entry_date TEXT NOT NULL         -- ISO 8601 date
#   exit_date TEXT                   -- ISO 8601 date or NULL
#   exit_reason TEXT                 -- "target" | "stop" | "time" | "logic_falsified" | "opportunity_cost"
#   pnl_pct REAL                     -- NULL if still open
#   virtual_slippage_applied REAL    -- ATR-based slippage deduction
#   confidence_discount_applied REAL -- 20% or adjusted discount
#   paper_live_gap_ratio REAL        -- gap tracking when real trade data available

# Table: daily_snapshots
#   id INTEGER PRIMARY KEY AUTOINCREMENT
#   shadow_id TEXT NOT NULL
#   date TEXT NOT NULL               -- ISO 8601 date
#   virtual_capital REAL NOT NULL
#   daily_return_pct REAL
#   cumulative_return_pct REAL
#   max_drawdown_pct REAL
#   win_rate_pct REAL
#   sharpe_ratio REAL
#   calmar_ratio REAL
#   omega_ratio REAL
#   mppm_score REAL                  -- Goetzmann et al. performance measure
#   composite_score REAL             -- raw composite before haircut
#   deflated_score REAL              -- after Bayesian overfitting haircut
#   percentile_rank REAL             -- within-cohort percentile (0-1)
#   achievement_tier TEXT            -- "elite" | "excellent" | "normal" | "watch" | "endangered"
#   flash_quota_used INTEGER
#   pro_quota_used INTEGER
#   emergency_quotas_used INTEGER
#   insights_generated INTEGER
#   UNIQUE(shadow_id, date)

# Table: ranking_history
#   id INTEGER PRIMARY KEY AUTOINCREMENT
#   date TEXT NOT NULL
#   shadow_id TEXT NOT NULL
#   rank INTEGER NOT NULL            -- 1 = best
#   composite_score REAL NOT NULL
#   deflated_score REAL NOT NULL
#   component_scores TEXT NOT NULL   -- JSON: {"mppm": 0.82, "calmar": 0.65, "omega": 0.71, "wr": 0.58}
#   UNIQUE(date, shadow_id)

# Table: integrity_events
#   id INTEGER PRIMARY KEY AUTOINCREMENT
#   shadow_id TEXT NOT NULL
#   date TEXT NOT NULL
#   event_type TEXT NOT NULL         -- "unverifiable_claim" | "false_claim" | "missing_source" | "verified_true"
#   claim_detail TEXT NOT NULL       -- JSON: {claim_value, claim_type, context, ...}
#   score_change INTEGER NOT NULL    -- -2, -15, -5, +1
#   new_score INTEGER NOT NULL
#   UNIQUE(shadow_id, date, event_type, claim_detail)

# Table: emergency_quotas
#   id INTEGER PRIMARY KEY AUTOINCREMENT
#   shadow_id TEXT NOT NULL
#   requested_at TEXT NOT NULL
#   confidence_self_report INTEGER NOT NULL  -- 8-10
#   opportunity_description TEXT NOT NULL
#   result TEXT                     -- "pending" | "profitable" | "loss_not_followed" | "loss_and_followed"
#   pnl_impact_pct REAL
#   quota_penalty_applied TEXT       -- penalty description or NULL

# Table: collusion_flags
#   id INTEGER PRIMARY KEY AUTOINCREMENT
#   date TEXT NOT NULL
#   agreement_pct REAL NOT NULL
#   consecutive_days INTEGER NOT NULL
#   market_signal_strength REAL      -- 0-1, how strong is external market signal
#   verdict TEXT NOT NULL            -- "convergence" | "herding" | "pending_review"
#   user_action TEXT                 -- "dismiss" | "investigate" | "acknowledge" or NULL
```

```python
# Shadow state CRUD interface:

@dataclass
class ShadowConfig:
    """JSON-serializable shadow configuration."""
    shadow_id: str                   # unique identifier
    shadow_type: str                 # "beta" | "expert" | "daredevil" | "temp_event" | "challenger" | "missed_path" | "catfish"
    display_name: str
    methodology_prompt: str          # the shadow's entire system prompt
    virtual_capital: float
    max_positions: int = 3
    model: str = "flash"             # "flash" | "pro" (mostly flash for cost)
    temperature: float = 0.3
    reasoning_effort: str = "max"
    domain: str | None = None        # "gold" | "crypto" | "energy" | "bonds" | "volatility" | "emerging" | etc.
    max_drawdown_limit: float = 0.35
    min_trades_for_ranking: int = 5
    parent_shadow_id: str | None = None
    generation: int = 0

class ShadowStateDB:
    """SQLite-backed shadow state persistence."""
    def __init__(self, db_path: str = "data/shadows/shadows.db"): ...
    def init_schema(self) -> None: ...
    def close(self) -> None: ...

    # Shadow CRUD
    def create_shadow(self, config: ShadowConfig) -> str: ...
    def get_shadow(self, shadow_id: str) -> ShadowConfig | None: ...
    def get_active_shadows(self, shadow_type: str | None = None) -> list[ShadowConfig]: ...
    def get_visible_shadows(self) -> list[ShadowConfig]: ...  # excludes challengers
    def update_shadow_status(self, shadow_id: str, status: str) -> None: ...
    def eliminate_shadow(self, shadow_id: str, reason: str) -> None: ...

    # Virtual trades
    def record_trade_open(self, shadow_id: str, trade: VirtualTradeOpen) -> int: ...
    def record_trade_close(self, trade_id: int, exit_price: float, exit_reason: str, pnl_pct: float) -> None: ...
    def get_open_trades(self, shadow_id: str) -> list[VirtualTrade]: ...
    def get_trade_history(self, shadow_id: str, days: int = 90) -> list[VirtualTrade]: ...

    # Daily snapshots
    def save_snapshot(self, shadow_id: str, snapshot: DailySnapshot) -> None: ...
    def get_snapshot_history(self, shadow_id: str, days: int = 90) -> list[DailySnapshot]: ...
    def get_latest_snapshot(self, shadow_id: str) -> DailySnapshot | None: ...

    # Rankings
    def save_rankings(self, date: str, rankings: list[tuple[str, float, float, dict]]) -> None: ...
    def get_ranking_history(self, shadow_id: str, days: int = 90) -> list[dict]: ...

    # Integrity
    def record_integrity_event(self, shadow_id: str, event: IntegrityEvent) -> None: ...
    def get_integrity_score(self, shadow_id: str) -> int: ...
    def get_integrity_history(self, shadow_id: str, days: int = 90) -> list[IntegrityEvent]: ...

    # Emergency quotas
    def record_emergency_quota(self, shadow_id: str, quota: EmergencyQuotaRequest) -> int: ...
    def update_emergency_result(self, quota_id: int, result: str, pnl_impact: float, penalty: str) -> None: ...
    def get_pending_emergency_audits(self) -> list[EmergencyQuotaRequest]: ...

    # Collusion
    def record_collusion_flag(self, flag: CollusionFlag) -> None: ...
    def get_recent_collusion_flags(self, days: int = 30) -> list[CollusionFlag]: ...

    # Bulk operations
    def get_all_daily_snapshots(self, date: str) -> list[DailySnapshot]: ...
    def get_all_active_votes(self, date: str, ticker: str) -> list[ShadowVote]: ...
```

**2. Config Extensions** -- `config/settings.py` additions:

```python
@dataclass
class ShadowSettings:
    """Phase B shadow ecosystem configuration."""
    # General
    shadows_enabled: bool = True
    shadows_db_path: str = "data/shadows/shadows.db"
    max_concurrent_shadows: int = 5       # asyncio semaphore for shadow batch
    shadow_flash_quota_default: int = 5   # daily Flash calls for Normal tier
    shadow_pro_quota_default: int = 1     # daily Pro calls for Normal tier (rarely used)

    # Ranking
    evaluation_window_days: int = 90
    progressive_window_floor: int = 30
    parametric_threshold_n: int = 30      # N where empirical takes over from parametric
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
    emergency_confidence_threshold: int = 8   # 8-10 on self-report
    emergency_extra_calls: int = 3            # extra Flash calls granted
    emergency_profit_reward_perm: bool = True  # permanent +1 quota on profit
    emergency_loss_penalty_days: int = 3      # penalty days if wrong but not followed
    emergency_loss_followed_penalty_days: int = 7
    emergency_consecutive_fail_limit: int = 3 # permanent -1 after 3 failures

    # Challenger
    challenger_stage1_periods: int = 2        # evaluation periods for warning
    challenger_stage2_periods: int = 3        # periods for challenger creation
    challenger_stage3_weeks: int = 2          # comparison trial weeks
    challenger_trial_alpha: float = 0.10      # one-sided paired t-test alpha
    challenger_calmar_gate: float = 0.3       # challenger must exceed this Calmar

    # Paper-to-Live gap
    virtual_slippage_atr_pct: float = 0.005   # 0.5% of ATR
    confidence_discount_default: float = 0.20 # 20% baseline
    confidence_discount_floor: float = 0.05   # 5% minimum after gap closure
    gap_closure_adjustment_factor: float = 0.75
    live_ready_min_trades: int = 10           # paired trades for live-ready
    live_ready_max_gap: float = 0.30          # GapRatio < 0.30 for live-ready

    # Collusion
    collusion_agreement_threshold: float = 0.80
    collusion_consecutive_days_flag: int = 3
    collusion_consecutive_days_audit: int = 10
    collusion_market_signal_threshold: float = 0.70  # > this = convergence

    # Cash reframing A/B test
    cash_reframing_cohort_size: int = 6       # 6 treatment + 6 control
    cash_reframing_test_days: int = 90
    cash_reframing_non_inferiority_margin: float = 0.02  # 2% return margin
    cash_reframing_de_alpha: float = 0.10     # one-sided Mann-Whitney on disposition effect

    # Plateau detection (for reset)
    plateau_no_elite_days: int = 126          # 6 months
    plateau_wr_range_pp: float = 10.0         # win rate range < 10pp in 90 days
    plateau_no_insight_days: int = 63         # 3 months without insight
    max_resets_per_month: int = 2

    # Missed paths
    missed_path_max_per_gate: int = 2         # Gate 1: B and C directions
    missed_path_report_days: int = 30         # when to report counterfactuals
```

Add to `MarketMindConfig`:
```python
shadow: ShadowSettings = field(default_factory=ShadowSettings)
```

Add to `validate()`:
```python
if self.shadow.shadows_enabled:
    if self.shadow.max_concurrent_shadows < 1:
        errors.append("shadow.max_concurrent_shadows must be >= 1")
    if self.shadow.evaluation_window_days < 30:
        errors.append("shadow.evaluation_window_days must be >= 30")
```

**3. Shadow Mother Interface** -- `shadows/shadow_mother.py`:

```python
@dataclass
class DetectedEvent:
    event_id: str                    # hash of source+timestamp
    event_type: str                  # "cb_shock" | "geopolitical" | "vol_shock" | "personnel"
    description: str
    affected_assets: list[str]
    impact_score: float              # 0-1 normalized impact
    detected_at: str                 # ISO 8601
    vix_level: float | None
    max_zscore: float | None         # maximum asset z-score
    news_volume: int | None          # news articles in detection window

@dataclass
class TempShadowSpec:
    """Specification for creating a temporary event shadow."""
    event_id: str
    shadow_name: str                 # auto-generated: "temp_{event_type}_{timestamp}"
    methodology_base: str            # which expert template to clone from
    domain: str
    virtual_capital: float           # $10K-$20K based on event impact
    max_lifespan_days: int = 30
    flash_quota_per_day: int = 3

class ShadowMother:
    """Detects events, creates/destroys temporary shadows, manages event lifecycle."""
    def __init__(self, config: ShadowSettings, state_db: ShadowStateDB): ...

    async def scan_events(self, news_items: list[NewsItem]) -> list[DetectedEvent]:
        """Scan news for trigger events. Returns detected events sorted by impact."""

    def detect_cb_shock(self, news_items: list[NewsItem]) -> list[DetectedEvent]:
        """E1: Central bank action |actual - expected| >= 50bp"""

    def detect_geopolitical(self, news_items: list[NewsItem]) -> list[DetectedEvent]:
        """E2: VIX ratio >= 1.5 AND delta >= 5 points"""

    def detect_vol_shock(self, market_data: dict[str, float]) -> list[DetectedEvent]:
        """E3: Single-asset 24h |return| >= 5 * sigma_60d"""

    def detect_personnel_change(self, news_items: list[NewsItem]) -> list[DetectedEvent]:
        """E4: Key personnel change via keyword detection"""

    def prioritize_events(self, events: list[DetectedEvent], max_shadows: int = 5) -> list[DetectedEvent]:
        """ImpactScore = 0.40 * VIX_norm + 0.30 * max_zscore + 0.30 * NewsVolume_norm.
        Top N events get shadows."""

    async def create_temp_shadows(self, events: list[DetectedEvent]) -> list[str]:
        """Create temporary event shadows for prioritized events."""

    def check_destruction_conditions(self, shadow_id: str) -> bool:
        """Check if a temporary shadow should be destroyed:
        - Catalyst resolved
        - Volatility decayed (5 days < 2 sigma)
        - Inactive (5 days with no trades)
        - Max lifespan reached (30 days)
        - Degradation (3 consecutive negative days after event passed)"""

    async def destroy_temp_shadow(self, shadow_id: str) -> None:
        """Destroy shadow, archive knowledge to insight library, notify relevant expert shadows."""

    async def create_missed_path_shadows(self, rejected_directions: list[str]) -> list[str]:
        """Gate 1: user chose direction A. Create missed_path shadows for B and C."""

    def get_active_temp_shadows(self) -> list[str]: ...
    def get_event_status(self, event_id: str) -> str: ...  # "active" | "resolved" | "decayed"
```

**4. Prompt Template: Shadow Mother Event Detection (Flash)**

```
System: You are the Shadow Mother -- an event detection system for financial markets.

Your task: scan these news headlines and detect trigger events that warrant creating a temporary analysis shadow.

Event types:
- E1 Central Bank Shock: |actual rate decision - market expectation| >= 50 basis points
- E2 Geopolitical Crisis: VIX spike >= 50% day-over-day AND absolute move >= 5 points
- E3 Volatility Shock: Any single major asset moves > 5 standard deviations in 24 hours
- E4 Key Personnel Change: Treasury Secretary, Fed Chair, SEC Chair, or equivalent changes

For each detected event, output:
{
  "event_type": "cb_shock|geopolitical|vol_shock|personnel",
  "headline_source": "source of the trigger news",
  "description": "1-sentence summary",
  "affected_assets": ["TICKER1", "TICKER2"],
  "vix_level": 0.0 or null,
  "confidence": 0.0-1.0
}

Headlines to scan:
{headlines}

Output ONLY a JSON array of detected events. If no events detected, output [].
```

Architect commits handoff to `.claude/handoffs/B0_foundation.md`.

---

### Task B.0.3: Data Engineer -- Shadow State Implementation

**Agent:** Data Engineer (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/shadows/__init__.py`
- Create: `projects/marketmind/shadows/shadow_state.py`
- Create: `projects/marketmind/tests/test_shadows/__init__.py`
- Create: `projects/marketmind/tests/test_shadows/conftest.py`
- Create: `projects/marketmind/tests/test_shadows/test_shadow_state.py`

- [ ] **Step 1: Write failing tests for ShadowStateDB**

```python
# tests/test_shadows/test_shadow_state.py
import pytest
import tempfile
from pathlib import Path
from projects.marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, VirtualTradeOpen, DailySnapshot,
    IntegrityEvent, EmergencyQuotaRequest, CollusionFlag
)

@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_shadows.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()
        yield db
        db.close()

def test_init_schema_creates_all_tables(temp_db):
    """Verify all 7 tables exist after init_schema()."""
    import sqlite3
    conn = sqlite3.connect(temp_db.db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t[0] for t in tables}
    expected = {"shadows", "virtual_trades", "daily_snapshots", "ranking_history",
                "integrity_events", "emergency_quotas", "collusion_flags"}
    assert expected.issubset(table_names)

def test_create_and_get_shadow(temp_db):
    config = ShadowConfig(
        shadow_id="expert:gold:test_01",
        shadow_type="expert",
        display_name="Test Gold Bug",
        methodology_prompt="You are a gold expert.",
        virtual_capital=50000.0,
        domain="gold"
    )
    shadow_id = temp_db.create_shadow(config)
    assert shadow_id == "expert:gold:test_01"
    retrieved = temp_db.get_shadow(shadow_id)
    assert retrieved is not None
    assert retrieved.display_name == "Test Gold Bug"
    assert retrieved.virtual_capital == 50000.0

def test_create_shadow_duplicate_id_fails(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    with pytest.raises(ValueError, match="already exists"):
        temp_db.create_shadow(config)

def test_get_active_shadows_filters_by_type(temp_db):
    for i in range(3):
        config = ShadowConfig(shadow_id=f"expert:{i}", shadow_type="expert",
                              display_name=f"E{i}", methodology_prompt="...",
                              virtual_capital=10000)
        temp_db.create_shadow(config)
    for i in range(2):
        config = ShadowConfig(shadow_id=f"daredevil:{i}", shadow_type="daredevil",
                              display_name=f"D{i}", methodology_prompt="...",
                              virtual_capital=10000)
        temp_db.create_shadow(config)
    experts = temp_db.get_active_shadows("expert")
    assert len(experts) == 3
    daredevils = temp_db.get_active_shadows("daredevil")
    assert len(daredevils) == 2
    all_active = temp_db.get_active_shadows()
    assert len(all_active) == 5

def test_get_visible_shadows_excludes_challengers(temp_db):
    for shadow_type in ["expert", "expert", "challenger"]:
        config = ShadowConfig(
            shadow_id=f"{shadow_type}:test_{shadow_type}",
            shadow_type=shadow_type,
            display_name=f"{shadow_type} shadow",
            methodology_prompt="...",
            virtual_capital=10000,
            parent_shadow_id="expert:test_expert" if shadow_type == "challenger" else None
        )
        temp_db.create_shadow(config)
    visible = temp_db.get_visible_shadows()
    assert len(visible) == 2
    assert all(s.shadow_type != "challenger" for s in visible)

def test_record_and_get_trades(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    trade = VirtualTradeOpen(
        shadow_id="test", ticker="AAPL", direction="long",
        entry_price=150.0, position_size_pct=0.10,
        entry_date="2026-05-11"
    )
    trade_id = temp_db.record_trade_open("test", trade)
    assert trade_id > 0
    temp_db.record_trade_close(trade_id, 160.0, "target", 0.0667)
    history = temp_db.get_trade_history("test", days=90)
    assert len(history) == 1
    assert history[0].ticker == "AAPL"
    assert history[0].pnl_pct == pytest.approx(0.0667, rel=0.01)

def test_save_and_get_snapshot(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    snap = DailySnapshot(
        shadow_id="test", date="2026-05-11", virtual_capital=10100.0,
        daily_return_pct=0.01, cumulative_return_pct=0.01,
        max_drawdown_pct=0.0, win_rate_pct=100.0,
        sharpe_ratio=1.5, calmar_ratio=2.0, omega_ratio=3.0,
        mppm_score=0.85, composite_score=0.82, deflated_score=0.73,
        percentile_rank=0.85, achievement_tier="elite",
        flash_quota_used=5, pro_quota_used=0, emergency_quotas_used=0,
        insights_generated=1
    )
    temp_db.save_snapshot("test", snap)
    history = temp_db.get_snapshot_history("test", days=90)
    assert len(history) == 1
    assert history[0].achievement_tier == "elite"

def test_save_rankings(temp_db):
    rankings = [
        ("shadow_a", 0.85, 0.76, {"mppm": 0.9, "calmar": 0.7, "omega": 0.8, "wr": 0.9}),
        ("shadow_b", 0.70, 0.62, {"mppm": 0.7, "calmar": 0.6, "omega": 0.7, "wr": 0.8}),
    ]
    temp_db.save_rankings("2026-05-11", rankings)
    history = temp_db.get_ranking_history("shadow_a", days=90)
    assert len(history) == 1
    assert history[0]["rank"] == 1

def test_eliminate_shadow_marks_eliminated_at(temp_db):
    config = ShadowConfig(shadow_id="test", shadow_type="expert",
                          display_name="T", methodology_prompt="...", virtual_capital=10000)
    temp_db.create_shadow(config)
    temp_db.eliminate_shadow("test", "Failed challenger comparison")
    shadow = temp_db.get_shadow("test")
    assert shadow.status == "eliminated"
    assert shadow.eliminated_at is not None
```

- [ ] **Step 2: Run test -- verify FAIL**

```bash
python -m pytest projects/marketmind/tests/test_shadows/test_shadow_state.py -v
```

- [ ] **Step 3: Implement `shadows/shadow_state.py`**

Full implementation of the `ShadowStateDB` class with all CRUD methods, the data classes, and SQLite schema initialization. Must handle concurrent access (WAL mode, busy timeout), parameterized queries (no string formatting), and proper JSON serialization for `config_json`, `component_scores`, and `claim_detail` fields.

- [ ] **Step 4: Run tests -- verify ALL PASS**

```bash
python -m pytest projects/marketmind/tests/test_shadows/test_shadow_state.py -v
```

Expected: 9 passed

- [ ] **Step 5: Create `tests/test_shadows/conftest.py`**

```python
"""Shared fixtures for shadow ecosystem tests."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from projects.marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from projects.marketmind.gateway.async_client import init_gateway


@pytest.fixture
def temp_shadow_db():
    """Create a temporary ShadowStateDB for testing."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_shadows.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()
        yield db
        db.close()


@pytest.fixture
def sample_expert_config():
    return ShadowConfig(
        shadow_id="expert:gold:test_gold_bug",
        shadow_type="expert",
        display_name="Test Gold Bug",
        methodology_prompt="You are a gold market expert.",
        virtual_capital=50000.0,
        domain="gold",
        temperature=0.3,
    )


@pytest.fixture
def sample_daredevil_config():
    return ShadowConfig(
        shadow_id="daredevil:intraday:test_scalper",
        shadow_type="daredevil",
        display_name="Test Scalper",
        methodology_prompt="You are an intraday direction trader.",
        virtual_capital=25000.0,
        temperature=0.5,
    )


@pytest.fixture
def populated_db(temp_shadow_db):
    """Database with 15 diverse shadows for ranking/aggregation tests."""
    domains = ["gold", "crypto", "energy", "bonds", "volatility", "emerging",
               "tech", "financials", "healthcare", "consumer", "metals",
               "agriculture", "real_estate", "fx", "rates"]
    for i, domain in enumerate(domains):
        config = ShadowConfig(
            shadow_id=f"expert:{domain}:agent_{i:02d}",
            shadow_type="expert",
            display_name=f"Expert {domain.title()}",
            methodology_prompt=f"You are a {domain} market expert.",
            virtual_capital=40000.0 + (i * 1000),
            domain=domain,
        )
        temp_shadow_db.create_shadow(config)
    return temp_shadow_db


@pytest.fixture
def mock_flash_call():
    """Mock a Flash API call returning structured content."""
    return AsyncMock(return_value={
        "content": '{"analysis": "mock shadow analysis"}',
        "usage": {"total_tokens": 300},
        "latency_ms": 600,
    })
```

- [ ] **Step 6: Commit**

```bash
git add projects/marketmind/shadows/__init__.py projects/marketmind/shadows/shadow_state.py projects/marketmind/tests/test_shadows/
git commit -m "feat(B.0): shadow state persistence -- SQLite schema, ShadowConfig, CRUD for 7 tables"
```

---

### Task B.0.4: Data Engineer -- Config Extensions

**Agent:** Data Engineer (Sonnet 1M)
**Files:**
- Edit: `projects/marketmind/config/settings.py`

- [ ] **Step 1: Add `ShadowSettings` dataclass to `config/settings.py`**
- [ ] **Step 2: Add `shadow: ShadowSettings` field to `MarketMindConfig`**
- [ ] **Step 3: Extend `validate()` to check shadow settings when enabled**
- [ ] **Step 4: Syntax check + import verification**

```bash
python -c "
from projects.marketmind.config.settings import MarketMindConfig, ShadowSettings
c = MarketMindConfig.from_env()
print(f'Shadow enabled: {c.shadow.shadows_enabled}')
print(f'Eval window: {c.shadow.evaluation_window_days} days')
print(f'Validation errors: {c.validate()}')
"
```

- [ ] **Step 5: Commit**

```bash
git add projects/marketmind/config/settings.py
git commit -m "feat(B.0): ShadowSettings config -- quotas, ranking params, challenger rules, collusion thresholds"
```

---

### Task B.0.5: Red Team -- Foundation Audit

**Agent:** Red Team (Haiku 1M)

Red Team reads all B.0 files and produces `RED_TEAM_AUDIT_B0`:
1. DB schema: does it handle concurrent writes? (WAL mode, busy timeout)
2. Config validation: are all threshold ranges reasonable?
3. ShadowStateDB edge cases: NULL handling, JSON malformation, duplicate date constraints
4. ShadowSettings: do any parameters conflict? (e.g., emergency_extra_calls > shadow_flash_quota_default)
5. API key isolation: is ShadowStateDB isolated from API key access?

Output to `.claude/audits/B0_foundation.md`.

### Task B.0.6: Optimization Scout -- Foundation Review

**Agent:** Optimization Scout (Sonnet 1M)

Scout produces `OPTIMIZATION_REPORT_B0`:
1. SQLite performance: is WAL mode sufficient for 15+ daily writers? Check for SQLAlchemy alternatives
2. Config validation: is pydantic a better fit for nested config?
3. ShadowStateDB: any missing queries needed by downstream modules?
4. Web search: any newer shadow/agent persistence patterns in open-source trading systems?

Output to `.claude/optimization/B0_foundation.md`.

---

## Sub-Phase B.1: Ranking Engine

| Step | Who | What |
|------|-----|------|
| B.1.1 | **Quant Analyst** | Verify ranking formulas match methodology. Produce `RANKING_VERIFICATION_B1` |
| B.1.2 | **Architect** | Design ranking engine interface, composite score formula, achievement ladder logic. Produce `ARCHITECTURE_HANDOFF_B1` |
| B.1.3 | **Builder** | Implement `shadows/ranking_engine.py` -- pure Python, no LLM |
| B.1.4 | **Builder** | Implement ranking + ladder tests; verify with 15-shadow simulation |
| B.1.5 | **Red Team** | Audit ranking: verify percentile stability at N=15, Bayesian haircut formula, ladder monotonicity |
| B.1.6 | **Optimization Scout** | Review B.1 outputs; report |

---

### Task B.1.1: Quant Analyst Verification

**Agent:** Quant Analyst (Sonnet 1M)

Quant Analyst reads the architecture handoff and verifies:
1. MPPM formula with gamma=3 matches Goetzmann et al. specification
2. Calmar formula: CAGR / max(|MDD|, 0.001) correct
3. Omega(L=0) cap at 10 is appropriate
4. Win Rate excludes abstention days (is this correct for our shadow types?)
5. Bayesian haircut h(N,T) = T / (T + 8 + 24 * ln(N)) matches Witzany (2021)
6. Percentile transition from parametric to empirical is mathematically sound
7. Achievement ladder conditions are implementable (consecutive day counting)

Output to `.claude/reviews/B1_ranking_verification.md`.

---

### Task B.1.2: Architect Handoff -- Ranking Engine Design

**Agent:** Architect (Opus 1M)

Architect produces `ARCHITECTURE_HANDOFF_B1`:

**1. Ranking Engine Interface:**

```python
@dataclass
class ShadowPerformance:
    """Single shadow's performance metrics for one evaluation period."""
    shadow_id: str
    daily_returns: list[float]          # % returns per day in window
    cumulative_return: float
    max_drawdown: float
    max_drawdown_duration_days: int
    win_rate: float                     # fraction of profitable closed trades
    total_trades: int
    profitable_trades: int
    losing_trades: int
    abstention_days: int                # days with no position
    cagr: float                         # compound annual growth rate

@dataclass
class RankingResult:
    shadow_id: str
    rank: int
    composite_score: float              # C_raw before haircut
    deflated_score: float               # after Bayesian haircut
    percentile_rank: float              # within-cohort percentile of deflated score
    achievement_tier: str               # "elite" | "excellent" | "normal" | "watch" | "endangered"
    component_scores: dict[str, float]  # {"mppm": 0.82, "calmar": 0.65, ...}
    component_percentiles: dict[str, float]  # each component as percentile

class RankingEngine:
    """Pure Python ranking computation. No LLM calls."""

    def __init__(self, config: ShadowSettings): ...

    # Core metrics
    def compute_mppm(self, returns: list[float], gamma: float = 3.0) -> float: ...
    def compute_calmar(self, cumulative_return: float, max_drawdown: float) -> float: ...
    def compute_omega(self, returns: list[float], threshold: float = 0.0) -> float: ...
    def compute_cagr(self, cumulative_return: float, days: int) -> float: ...

    # Composite scoring
    def compute_composite_score(self, perf: ShadowPerformance) -> tuple[float, dict[str, float]]:
        """Returns (C_raw, component_scores_dict)."""

    # Bayesian overfitting haircut (Witzany 2021)
    def compute_haircut(self, n_shadows: int, evaluation_days: int) -> float:
        """h(N,T) = T / (T + 8 + 24 * ln(N))"""

    def apply_bayesian_haircut(self, composite_score: float, n_shadows: int,
                                evaluation_days: int) -> float:
        """C_deflated = C_raw * h(N,T)"""

    # Percentile computation (hybrid parametric/empirical)
    def compute_percentile_ranks(self, scores: dict[str, float]) -> dict[str, float]:
        """Map each shadow_id to its percentile rank (0-1) within the cohort."""

    # Achievement ladder
    def determine_achievement_tier(
        self,
        score_history: list[tuple[str, float]],  # [(date, deflated_score), ...]
        percentile_history: list[tuple[str, float]],  # [(date, percentile), ...]
        mdd: float,
        deflated_sharpe: float,
    ) -> str:
        """Returns tier based on consecutive day rules."""

    # Plateau detection
    def detect_plateau(
        self,
        shadow_id: str,
        tier_history: list[tuple[str, str]],      # [(date, tier), ...]
        win_rate_history: list[tuple[str, float]], # [(date, wr), ...]
        insight_dates: list[str],                   # dates of insights
    ) -> tuple[bool, float]:
        """Returns (is_plateaued, plateau_score) where higher score = more stale."""

    # Full ranking pipeline
    def rank_shadows(
        self,
        performances: dict[str, ShadowPerformance],
        score_histories: dict[str, list[dict]],
        date: str,
    ) -> list[RankingResult]:
        """Full ranking: metrics -> composite -> haircut -> percentile -> ladder."""
```

**2. MPPM Formula (Goetzmann et al.):**

```
MPPM = (1 / (1 - gamma)) * ln( (1/T) * sum_t( (1 + r_t) ^ (1 - gamma) ) )

Where:
  r_t = daily return (decimal)
  gamma = 3 (risk aversion parameter)
  T = number of trading days in evaluation window

Properties:
- Accounts for non-normal return distributions (fat tails, skewness)
- gamma > 1 penalizes downside more than upside
- Resistant to "sell tail risk insurance" Sharpe manipulation
```

**3. Percentile Transition Function:**

```python
def _percentile_hybrid(scores: list[float], n: int) -> dict[int, float]:
    """Compute percentile ranks using hybrid parametric/empirical approach.

    n < 30: logistic-normal parametric (fit mu, sigma to logit-transformed scores)
    n >= 30: empirical percentile (fraction of scores <= x)
    n between 15-29: weight = n/30 blends from parametric toward empirical
    """
```

**4. Achievement Ladder State Machine:**

```
States: ELITE, EXCELLENT, NORMAL, WATCH, ENDANGERED

Transitions:
  ANY → ELITE:     percentile >= p85 for elite_consecutive_days AND deflated_sharpe > 0.8
  ANY → EXCELLENT: percentile >= p70 for excellent_consecutive_days AND deflated_sharpe > 0.6
  ANY → NORMAL:    (default state, entry on creation)
  ANY → WATCH:     percentile < p30 for watch_consecutive_days OR mdd > 30%
  ANY → ENDANGERED: percentile < p15 for endangered_consecutive_days

  WATCH → NORMAL:  percentile >= p30 for 5 consecutive days
  ENDANGERED → WATCH: percentile >= p15 for 10 consecutive days
                    (cannot jump directly to NORMAL from ENDANGERED)

State changes are logged as ranking_history events with transition reason.
```

Architect commits handoff to `.claude/handoffs/B1_ranking_engine.md`.

---

### Task B.1.3-B.1.4: Builder -- Ranking Engine Implementation

**Agent:** Builder (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/shadows/ranking_engine.py`
- Create: `projects/marketmind/tests/test_shadows/test_ranking_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_shadows/test_ranking_engine.py
import pytest
from projects.marketmind.shadows.ranking_engine import (
    RankingEngine, ShadowPerformance, RankingResult
)
from projects.marketmind.config.settings import ShadowSettings

@pytest.fixture
def engine():
    return RankingEngine(ShadowSettings())

@pytest.fixture
def sample_performances():
    """15 shadows with varying performance for ranking tests."""
    import random
    random.seed(42)
    perfs = {}
    for i in range(15):
        n = 60 + random.randint(0, 30)  # 60-90 trading days
        base = random.uniform(-0.001, 0.003)  # daily mean
        returns = [base + random.gauss(0, 0.02) for _ in range(n)]
        cum = sum(returns)
        mdd = min(0.0, *[sum(returns[:j]) - max(returns[:j+1]) for j in range(len(returns))])
        wins = sum(1 for r in returns if r > 0)
        perfs[f"shadow_{i:02d}"] = ShadowPerformance(
            shadow_id=f"shadow_{i:02d}",
            daily_returns=returns,
            cumulative_return=cum,
            max_drawdown=abs(mdd) if mdd < 0 else 0.01,
            max_drawdown_duration_days=random.randint(1, 30),
            win_rate=wins / len(returns) if returns else 0.5,
            total_trades=len(returns),
            profitable_trades=wins,
            losing_trades=len(returns) - wins,
            abstention_days=0,
            cagr=cum * 252 / len(returns) if len(returns) > 0 else 0.0,
        )
    return perfs

def test_mppm_positive_for_positive_returns(engine):
    returns = [0.001] * 50  # 0.1% daily for 50 days
    mppm = engine.compute_mppm(returns)
    assert mppm > 0

def test_mppm_negative_for_negative_returns(engine):
    returns = [-0.001] * 50
    mppm = engine.compute_mppm(returns)
    assert mppm < 0

def test_mppm_handles_fat_tails(engine):
    """MPPM should not explode on extreme returns."""
    returns = [0.001] * 40 + [0.10, -0.08, 0.15, -0.12]
    mppm = engine.compute_mppm(returns)
    assert not (mppm != mppm)  # not NaN
    assert abs(mppm) < 100  # reasonable range

def test_calmar_zero_mdd_returns_cagr(engine):
    """If MDD is 0 (all positive), Calmar should be capped not infinite."""
    returns = [0.001] * 50
    cum = sum(returns)
    calmar = engine.compute_calmar(cum, 0.001)  # floor
    assert calmar > 0
    assert calmar < 1000  # not infinite

def test_omega_ratio_basic(engine):
    returns = [0.02, -0.01, 0.03, -0.005, 0.01]
    omega = engine.compute_omega(returns)
    assert omega > 1.0  # gains exceed losses

def test_omega_capped_at_10(engine):
    """Omega should be capped at 10 per spec."""
    returns = [0.05] * 50  # all gains, no losses -> huge omega
    omega = engine.compute_omega(returns)
    assert omega <= 10.0

def test_composite_score_range(engine):
    perf = ShadowPerformance(
        shadow_id="test", daily_returns=[0.001]*50,
        cumulative_return=0.05, max_drawdown=0.02,
        max_drawdown_duration_days=5, win_rate=0.6,
        total_trades=50, profitable_trades=30, losing_trades=20,
        abstention_days=0, cagr=0.252
    )
    score, components = engine.compute_composite_score(perf)
    assert "mppm" in components
    assert "calmar" in components
    assert "omega" in components
    assert "win_rate" in components
    # Scores should be raw values before percentile normalization
    # (percentile is computed across cohort later)

def test_haircut_n15_t60(engine):
    """h(15, 60) should be approximately 0.451 as validated in methodology."""
    h = engine.compute_haircut(n_shadows=15, evaluation_days=60)
    assert h == pytest.approx(0.451, rel=0.05)

def test_haircut_increases_with_more_data(engine):
    """More shadows + more days = higher haircut (less penalty)."""
    h1 = engine.compute_haircut(5, 30)
    h2 = engine.compute_haircut(15, 60)
    h3 = engine.compute_haircut(30, 252)
    assert h1 < h2 < h3  # more data = more confidence = less discount

def test_haircut_value_range(engine):
    """Haircut should be in (0, 1)."""
    h = engine.compute_haircut(15, 60)
    assert 0 < h < 1

def test_rank_shadows_produces_correct_count(engine, sample_performances):
    results = engine.rank_shadows(sample_performances, {}, "2026-05-11")
    assert len(results) == 15

def test_rank_shadows_best_has_rank_1(engine, sample_performances):
    results = engine.rank_shadows(sample_performances, {}, "2026-05-11")
    assert results[0].rank == 1  # sorted by deflated score descending

def test_rank_shadows_percentiles_sum_to_1(engine, sample_performances):
    results = engine.rank_shadows(sample_performances, {}, "2026-05-11")
    total = sum(r.percentile_rank for r in results)
    # Percentile ranks approximate uniform distribution: sum ~= N * 0.5
    assert total == pytest.approx(7.5, abs=3.0)

def test_achievement_ladder_elite(engine):
    """90 days at p85 + deflated Sharpe > 0.8 -> elite."""
    scores = [("2026-05-01", 0.78)] * 20 + [("2026-05-20", 0.82)] * 30
    percentiles = [("2026-05-01", 0.55)] * 20 + [("2026-05-20", 0.88)] * 30
    tier = engine.determine_achievement_tier(scores, percentiles, 0.10, 0.85)
    assert tier == "elite"

def test_achievement_ladder_endangered(engine):
    """20 days at p15 -> endangered."""
    percentiles = [("2026-01-01", 0.12)] * 25
    scores = [("2026-01-01", 0.30)] * 25
    tier = engine.determine_achievement_tier(scores, percentiles, 0.25, 0.4)
    assert tier == "endangered"

def test_achievement_ladder_normal_default(engine):
    """New shadow with no history = normal."""
    tier = engine.determine_achievement_tier([], [], 0.0, 0.0)
    assert tier == "normal"

def test_plateau_detection(engine):
    """126 days no elite, 90 days wr range < 10pp, 63 days no insight."""
    tier_hist = [("2026-01-01", "normal")] * 150
    wr_hist = [(f"2026-{d:02d}-01", 0.52 + (d % 3) * 0.01) for d in range(1, 100)]
    # WR oscillates 52-54%, range < 10pp
    insights = ["2025-12-01"]  # last insight > 63 days ago
    is_plateau, score = engine.detect_plateau("test", tier_hist, wr_hist, insights)
    assert is_plateau
    assert score > 0

def test_plateau_not_detected_with_recent_elite(engine):
    tier_hist = [("2026-04-01", "elite"), ("2026-05-01", "elite")]
    wr_hist = [("2026-05-01", 0.52)]
    insights = []
    is_plateau, _ = engine.detect_plateau("test", tier_hist, wr_hist, insights)
    assert not is_plateau
```

- [ ] **Step 2: Run -- verify FAIL**

```bash
python -m pytest projects/marketmind/tests/test_shadows/test_ranking_engine.py -v
```

- [ ] **Step 3: Implement `shadows/ranking_engine.py`**

Full implementation of all ranking engine methods. Key constraints:
- MPPM uses gamma=3, handles edge cases (zero/negative returns)
- Calmar caps at 100 (degenerate case)
- Omega caps at 10 as per spec
- Haircut formula exactly matches Witzany (2021): h(N,T) = T / (T + 8 + 24 * ln(N))
- Percentile uses logistic-normal when n < 30
- Consecutive day counting: strict consecutive, reset on break
- Plateau score weights: 0.5 * stagnation + 0.3 * wr_stability + 0.2 * insight_drought

- [ ] **Step 4: Run tests -- verify PASS**

```bash
python -m pytest projects/marketmind/tests/test_shadows/test_ranking_engine.py -v
```

- [ ] **Step 5: Commit**

```bash
git add projects/marketmind/shadows/ranking_engine.py projects/marketmind/tests/test_shadows/test_ranking_engine.py
git commit -m "feat(B.1): ranking engine -- MPPM/Calmar/Omega/WinRate composite, Bayesian haircut, achievement ladder, plateau detection"
```

---

### Task B.1.5: Red Team -- Ranking Audit

**Agent:** Red Team (Haiku 1M)

Red Team audits `ranking_engine.py`:
1. Does MPPM with gamma=3 correctly penalize downside? Test with synthetic downside-heavy distributions.
2. Does the percentile transition at N=30 produce a discontinuity? Test N=29 vs N=30.
3. Does the Consecutive day counter handle date gaps (weekends, holidays)?
4. Can the Omega ratio be gamed? (e.g., many small gains + one large loss)
5. Does the achievement ladder produce monotonic State transitions? (ENDANGERED -> WATCH -> NORMAL -> EXCELLENT -> ELITE, never skip)
6. Is `max_drawdown` computing the correct magnitude, not direction? (positive number representing % loss)

Output to `.claude/audits/B1_ranking_engine.md`.

### Task B.1.6: Optimization Scout

**Agent:** Optimization Scout (Sonnet 1M)

Output to `.claude/optimization/B1_ranking_engine.md`.

---

## Sub-Phase B.2: Shadow Agent Base + Shadow Mother

| Step | Who | What |
|------|-----|------|
| B.2.1 | **Architect** | Design base ShadowAgent class, daily cycle interface, Shadow Mother full interface. Produce `ARCHITECTURE_HANDOFF_B2` |
| B.2.2 | **Builder** | Implement `shadows/shadow_agent.py` -- base class with daily analysis cycle |
| B.2.3 | **Builder** | Implement `shadows/shadow_mother.py` -- event detection, temp shadow lifecycle |
| B.2.4 | **Builder** | Implement `shadows/missed_path.py` -- counterfactual path tracking |
| B.2.5 | **Red Team** | Audit: shadow agent error isolation, mother event false-positive rate, missed path bias |
| B.2.6 | **Optimization Scout** | Review B.2 outputs; report |

---

### Task B.2.1: Architect Handoff -- Shadow Agent + Mother Design

**Agent:** Architect (Opus 1M)

Architect produces `ARCHITECTURE_HANDOFF_B2`:

**1. Base ShadowAgent:**

```python
class ShadowAgent:
    """Base class for all shadow agents. Handles daily analysis cycle, virtual portfolio,
    integrity tracking, and state persistence."""

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings): ...
    @property
    def shadow_id(self) -> str: ...
    @property
    def virtual_portfolio(self) -> dict[str, VirtualTrade]: ...

    # Daily cycle (called by ShadowMother/CLI orchestrator)
    async def receive_status_card(self) -> dict:
        """Get today's ranking, tier, quota, promotion requirements."""

    async def run_daily_analysis(self, news_items: list[NewsItem],
                                  market_data: dict[str, Any]) -> ShadowAnalysisOutput:
        """Execute one day's analysis. Subclasses override _analyze()."""

    async def _analyze(self, news_items: list[NewsItem],
                        market_data: dict[str, Any]) -> ShadowAnalysisOutput:
        """Override in subclasses with methodology-specific analysis."""
        raise NotImplementedError

    # Virtual portfolio
    async def check_positions(self) -> list[PositionCheck]: ...
    async def open_virtual_position(self, trade: VirtualTradeOpen) -> int: ...
    async def close_virtual_position(self, trade_id: int, exit_price: float,
                                      reason: str) -> None: ...

    # Integrity
    def get_integrity_score(self) -> int: ...
    def report_integrity_violation(self, violation: IntegrityEvent) -> None: ...

    # Quota
    def get_daily_quota(self) -> int: ...
    def get_pro_quota(self) -> int: ...
    async def request_emergency_quota(self, opportunity: str,
                                       confidence: int) -> bool: ...

    # Persistence
    async def save_daily_snapshot(self) -> None: ...
```

**2. Shadow Analysis Output:**

```python
@dataclass
class ShadowVote:
    shadow_id: str
    shadow_type: str
    date: str
    ticker: str
    direction: str           # "long" | "short" | "abstain"
    confidence: float        # 0.0-1.0
    thesis: str              # 1-sentence reason
    risk_note: str           # 1-sentence risk
    emergency_flag: bool     # confidence >= 8/10?

@dataclass
class ShadowAnalysisOutput:
    shadow_id: str
    date: str
    votes: list[ShadowVote]
    position_checks: list[PositionCheck]
    insights: list[str]       # potential Insights for knowledge library
    methodology_notes: str    # self-reflection on methodology
    quota_used: int
    latency_ms: int
```

**3. Shadow Mother Full Interface (extends B.0 design):**

Additional methods beyond B.0.2 design:
```python
class ShadowMother:
    # ... (B.0.2 methods) ...

    # Daily orchestration
    async def generate_status_cards(self, date: str) -> dict[str, dict]:
        """Generate today's status card for every active shadow."""

    async def orchestrate_daily_cycle(self, news_items: list[NewsItem],
                                       market_data: dict[str, Any],
                                       rejected_directions: list[str] | None = None
                                       ) -> ShadowOrchestrationResult:
        """Full daily cycle:
        1. Scan events -> create/destroy temp shadows
        2. Create missed_path shadows (if rejected_directions provided)
        3. Generate status cards
        4. Run all shadows in parallel (concurrency-gated)
        5. Collect votes, check positions
        6. Compute rankings
        7. Detect collusion
        8. Check challenger conditions
        9. Audit emergency quotas
        10. Persist all state
        """

@dataclass
class ShadowOrchestrationResult:
    date: str
    active_shadows: int
    temp_shadows_created: int
    temp_shadows_destroyed: int
    votes_collected: int
    shadow_analyses: dict[str, ShadowAnalysisOutput]
    rankings: list[RankingResult]
    collusion_flags: list[CollusionFlag]
    challenger_actions: list[str]     # descriptions of challenger events
    emergency_audits: list[str]       # descriptions of emergency quota audits
```

Architect commits handoff to `.claude/handoffs/B2_shadow_agent_mother.md`.

---

### Task B.2.2-B.2.4: Builder -- Agent, Mother, Missed Path

**Agent:** Builder (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/shadows/shadow_agent.py`
- Create: `projects/marketmind/shadows/shadow_mother.py`
- Create: `projects/marketmind/shadows/missed_path.py`
- Create: `projects/marketmind/tests/test_shadows/test_shadow_agent.py`
- Create: `projects/marketmind/tests/test_shadows/test_shadow_mother.py`
- Create: `projects/marketmind/tests/test_shadows/test_missed_path.py`

Key test stubs:

```python
# test_shadow_agent.py
@pytest.mark.asyncio
async def test_shadow_agent_receives_status_card(populated_db, mock_flash_call):
    """Status card includes rank, tier, quota, promotion requirements."""

@pytest.mark.asyncio
async def test_shadow_agent_daily_cycle_persists_snapshot(populated_db, mock_flash_call):
    """After daily cycle, snapshot exists in DB."""

@pytest.mark.asyncio
async def test_shadow_agent_isolated_errors_dont_crash_other_shadows():
    """If one shadow crashes, other shadows continue."""

def test_shadow_agent_virtual_portfolio_tracks_positions(temp_shadow_db, sample_expert_config):
    """Open/close trades update virtual portfolio correctly."""

# test_shadow_mother.py
@pytest.mark.asyncio
async def test_mother_detects_cb_shock():
    """News item with 50bp surprise -> detected event."""

@pytest.mark.asyncio
async def test_mother_detects_geopolitical_with_vix_spike():
    """VIX +50% + 5 pt delta -> geopolitical event."""

@pytest.mark.asyncio
async def test_mother_creates_temp_shadow_for_high_impact_event():
    """Top-impact event -> temp shadow created."""

@pytest.mark.asyncio
async def test_mother_destroys_temp_shadow_after_catalyst_resolved():
    """Temp shadow destroyed when event resolved."""

@pytest.mark.asyncio
async def test_mother_prioritizes_events_top5():
    """>10 events -> only top 5 get shadows."""

# test_missed_path.py
def test_missed_path_creates_shadows_for_rejected_directions():
    """Gate 1: user chose A. Missed path shadows for B, C."""

def test_missed_path_readonly_no_interaction():
    """Missed path shadows record only, never generate votes."""

def test_missed_path_survivorship_bias_warning():
    """Report includes survivorship bias disclaimer."""
```

- [ ] **Step 1: Write failing tests**
- [ ] **Step 2: Verify FAIL**
- [ ] **Step 3: Implement all three modules**
- [ ] **Step 4: Verify PASS**
- [ ] **Step 5: Commit per module**

```bash
git add projects/marketmind/shadows/shadow_agent.py projects/marketmind/tests/test_shadows/test_shadow_agent.py
git commit -m "feat(B.2): base ShadowAgent -- daily cycle, virtual portfolio, integrity tracking, quota management"

git add projects/marketmind/shadows/shadow_mother.py projects/marketmind/tests/test_shadows/test_shadow_mother.py
git commit -m "feat(B.2): Shadow Mother -- E1-E4 event detection, prioritization, temp shadow create/destroy"

git add projects/marketmind/shadows/missed_path.py projects/marketmind/tests/test_shadows/test_missed_path.py
git commit -m "feat(B.2): missed path tracking -- counterfactual direction shadows, survivorship bias warning"
```

---

### Task B.2.5: Red Team -- Agent + Mother Audit

**Agent:** Red Team (Haiku 1M)

Produce `RED_TEAM_AUDIT_B2`:
1. Shadow agent error isolation: does one shadow's crash cascade?
2. Mother false positive rate: test with normal-market news batch (no events)
3. Mother false negative rate: test with known event news batch
4. Temp shadow cleanup: what if ShadowMother crashes mid-create?
5. Missed path counterfactual bias: verify survivorship warning is included

Output to `.claude/audits/B2_agent_mother.md`.

### Task B.2.6: Optimization Scout

Output to `.claude/optimization/B2_agent_mother.md`.

---

## Sub-Phase B.3: Expert Shadows

| Step | Who | What |
|------|-----|------|
| B.3.1 | **Quant Analyst** | Design 15 domain-specific methodology prompts. Produce `EXPERT_METHODOLOGIES_B3` |
| B.3.2 | **Builder** | Implement `shadows/expert_shadows.py` -- configs, prompts, ExpertShadow subclass |
| B.3.3 | **Builder** | Implement tests for each expert type |
| B.3.4 | **Red Team** | Audit: prompt consistency, domain coverage, methodology soundness |
| B.3.5 | **Optimization Scout** | Review B.3 outputs; report |

---

### Task B.3.1: Quant Analyst -- Expert Methodologies

**Agent:** Quant Analyst (Sonnet 1M)

Quant Analyst produces 15 domain-specific methodology prompts. Each prompt includes:
1. Domain expertise statement
2. Key indicators monitored
3. Decision framework (how to identify opportunities)
4. Risk management rules
5. Interaction rules (what to do with consensus, when to dissent)

**15 Expert Domains:**

| # | Shadow ID | Domain | Methodology Focus |
|---|-----------|--------|-------------------|
| 1 | `expert:gold:bullion_broker` | Precious Metals | Real rates, USD, central bank buying, COT, ETF flows |
| 2 | `expert:crypto:chain_oracle` | Cryptocurrency | On-chain metrics, ETF flows, regulation, halving cycles |
| 3 | `expert:energy:oil_geologist` | Energy | OPEC+, inventories, rig count, demand forecasts, spreads |
| 4 | `expert:bonds:yield_whisperer` | Fixed Income | Yield curve, breakevens, Fed rhetoric, auction demand |
| 5 | `expert:vol:vega_trader` | Volatility | VIX term structure, skew, RV vs IV gap, event premium |
| 6 | `expert:em:frontier_scout` | Emerging Markets | Dollar index, EM bond spreads, capital flows, political risk |
| 7 | `expert:tech:silicon_oracle` | Technology | Earnings momentum, AI capex, regulation, supply chain |
| 8 | `expert:financials:bank_examiner` | Financials | Yield curve, loan growth, credit quality, regulation |
| 9 | `expert:healthcare:trial_reviewer` | Healthcare | FDA calendar, trial results, policy, demographic trends |
| 10 | `expert:consumer:wallet_watcher` | Consumer | Retail sales, sentiment, credit card data, wage growth |
| 11 | `expert:industrials:factory_floor` | Industrials | PMI, durable goods, infrastructure spending, trade |
| 12 | `expert:metals:steel_trader` | Industrial Metals | China demand, infrastructure, EV adoption, supply disruption |
| 13 | `expert:realestate:reit_analyst` | Real Estate | Rates, occupancy, cap rates, CMBS, housing data |
| 14 | `expert:fx:currency_dealer` | FX/Carry | Rate differentials, carry, purchasing power, intervention |
| 15 | `expert:macro:cycle_reader` | Macro/Cross-Asset | Global growth-inflation quadrants, regime detection |

Output to `.claude/methodology/B3_expert_prompts.md`.

---

### Task B.3.2-B.3.3: Builder -- Expert Shadow Implementation

**Agent:** Builder (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/shadows/expert_shadows.py`
- Create: `projects/marketmind/tests/test_shadows/test_expert_shadows.py`

```python
# expert_shadows.py structure:
class ExpertShadow(ShadowAgent):
    """Shadow with domain-specific methodology and independent analysis."""
    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB, settings: ShadowSettings):
        super().__init__(config, state_db, settings)

    async def _analyze(self, news_items, market_data) -> ShadowAnalysisOutput:
        """Filter news by domain relevance, call Flash with methodology prompt,
        parse structured output into votes."""

# Pre-built expert shadow configurations:
EXPERT_SHADOW_CONFIGS: list[ShadowConfig] = [
    ShadowConfig(shadow_id="expert:gold:bullion_broker", ...),
    ShadowConfig(shadow_id="expert:crypto:chain_oracle", ...),
    # ... all 15
]

# Factory function:
def create_expert_shadows(state_db: ShadowStateDB,
                           settings: ShadowSettings) -> list[ExpertShadow]:
    """Instantiate all 15 expert shadows from configs."""
```

Key test:
```python
@pytest.mark.asyncio
async def test_expert_shadow_filters_by_domain():
    """Gold expert only analyzes gold-related news."""

@pytest.mark.asyncio
async def test_expert_shadow_produces_structured_votes():
    """Output contains valid ShadowVote objects."""

@pytest.mark.asyncio
async def test_all_15_experts_instantiate():
    """Factory creates 15 shadows without errors."""
```

- [ ] **Step 1: Write failing tests**
- [ ] **Step 2: Implement expert_shadows.py**
- [ ] **Step 3: Verify PASS**
- [ ] **Step 4: Commit**

```bash
git add projects/marketmind/shadows/expert_shadows.py projects/marketmind/tests/test_shadows/test_expert_shadows.py
git commit -m "feat(B.3): 15 expert shadows -- domain-specific methodologies, structured vote output, factory"
```

---

### Task B.3.4-B.3.5: Red Team + Scout

Audit and optimization outputs to `.claude/audits/B3_expert_shadows.md` and `.claude/optimization/B3_expert_shadows.md`.

---

## Sub-Phase B.4: Daredevil + Catfish

| Step | Who | What |
|------|-----|------|
| B.4.1 | **Architect** | Design Daredevil types + Catfish methodology. Produce `ARCHITECTURE_HANDOFF_B4` |
| B.4.2 | **Builder** | Implement `shadows/daredevil_shadows.py` -- 5 daredevil types |
| B.4.3 | **Builder** | Implement `shadows/catfish_agent.py` -- minority-opinion enforcer |
| B.4.4 | **Red Team** | Audit: catfish effectiveness, daredevil risk controls |
| B.4.5 | **Optimization Scout** | Review B.4 outputs; report |

---

### Task B.4.1: Architect Handoff

**Agent:** Architect (Opus 1M)

**Daredevil Types (5):**

| # | Shadow ID | Type | Virtual Capital | Strategy |
|---|-----------|------|----------------|----------|
| 1 | `daredevil:intraday:scalper` | Intraday Direction | $25K | Must pick direction daily, 1-3 day hold |
| 2 | `daredevil:swing:trend_rider` | Weekly Trend | $30K | Identify developing trends, 5-15 day hold |
| 3 | `daredevil:event:news_hound` | Event Hound | $25K | Trade event-driven moves, 1-5 day hold |
| 4 | `daredevil:contrarian:fade_master` | Contrarian | $20K | Systematic fade of crowded consensus, 3-10 day hold |
| 5 | `daredevil:sector:rotation_engine` | Sector Rotation | $30K | Rotate between sector ETFs, 5-20 day hold |

Daredevils have higher risk tolerance (max MDD 35%), lower trade count requirements (>=50 for promotion), and PBO < 10%.

**Catfish Methodology (per Q5):**

```python
CATFISH_SYSTEM_PROMPT = """You are the Catfish Agent -- a minority-opinion enforcer in a team of 15+ investment shadows.

Your ROLE: When >=80% of shadows agree on direction for an asset, you MUST construct the best possible argument for the OPPOSITE direction using only verifiable data. Your purpose is to prevent groupthink and surface overlooked risks.

RULES:
1. ONLY activate when given the trigger signal: "CONSENSUS DETECTED on {ticker}: {direction} ({agreement_pct}%)"
2. If no trigger, report "NO_CONSENSUS_DETECTED" and provide your independent analysis.
3. Your counter-argument MUST cite verifiable data. Use EST: prefix for estimates. Use DATA_UNAVAILABLE when data is missing.
4. If no legitimate counter-argument exists after thorough analysis, report "NO_VALID_COUNTER" -- NEVER fabricate.
5. Temperature=0.8 is intentional: use creative reasoning to find non-obvious angles.
6. You are subject to Law 7 (Data Integrity). Fabrication = 3 strikes and termination.
"""
```

Architect commits handoff to `.claude/handoffs/B4_daredevil_catfish.md`.

---

### Task B.4.2-B.4.3: Builder -- Implementation

**Agent:** Builder (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/shadows/daredevil_shadows.py`
- Create: `projects/marketmind/shadows/catfish_agent.py`
- Create: `projects/marketmind/tests/test_shadows/test_daredevil_shadows.py`
- Create: `projects/marketmind/tests/test_shadows/test_catfish_agent.py`

Catfish key test:
```python
@pytest.mark.asyncio
async def test_catfish_activates_when_consensus_detected():
    """When >=80% agree, catfish produces counter-argument."""

@pytest.mark.asyncio
async def test_catfish_reports_no_consensus_when_below_threshold():
    """When <80% agree, catfish does independent analysis."""

@pytest.mark.asyncio
async def test_catfish_returns_no_valid_counter_when_no_legitimate_argument():
    """Catfish must report NO_VALID_COUNTER, not fabricate."""

@pytest.mark.asyncio
async def test_catfish_uses_higher_temperature():
    """Catfish config has temperature=0.8."""
```

- [ ] **Commits:**

```bash
git add projects/marketmind/shadows/daredevil_shadows.py projects/marketmind/tests/test_shadows/test_daredevil_shadows.py
git commit -m "feat(B.4): 5 daredevil shadows -- intraday, trend, event, contrarian, sector rotation"

git add projects/marketmind/shadows/catfish_agent.py projects/marketmind/tests/test_shadows/test_catfish_agent.py
git commit -m "feat(B.4): catfish agent -- minority-opinion enforcer with >=80% consensus trigger"
```

---

## Sub-Phase B.5: Challenger + Knowledge Filter

| Step | Who | What |
|------|-----|------|
| B.5.1 | **Quant Analyst** | Validate 3-stage elimination buffer, paired comparison methodology. Produce `CHALLENGER_VERIFICATION_B5` |
| B.5.2 | **Architect** | Design challenger engine + Learngenes filter. Produce `ARCHITECTURE_HANDOFF_B5` |
| B.5.3 | **Builder** | Implement `shadows/challenger_engine.py` |
| B.5.4 | **Builder** | Implement `shadows/knowledge_filter.py` |
| B.5.5 | **Red Team** | Audit: challenger opacity guarantees, ACE model compliance |
| B.5.6 | **Optimization Scout** | Review B.5 outputs; report |

---

### Task B.5.2: Architect Handoff

**Agent:** Architect (Opus 1M)

**Challenger Engine Interface:**

```python
@dataclass
class EliminationStage:
    shadow_id: str
    current_stage: int             # 1=warning, 2=observation+challenger, 3=comparison
    consecutive_bottom_periods: int
    evaluation_period_days: int    # depends on strategy type
    rank_percentiles: list[float]   # recent percentile ranks
    created_at: str

class ChallengerEngine:
    def __init__(self, state_db: ShadowStateDB, settings: ShadowSettings): ...

    def check_elimination_stage(self, shadow_id: str) -> EliminationStage:
        """Determine elimination stage based on consecutive bottom periods."""

    def create_challenger(self, target_shadow_id: str) -> str:
        """Stage 2: create secret challenger shadow.
        - Clones target's config (same virtual capital, domain)
        - Applies knowledge filter to inherit verified insights only
        - Does NOT appear in get_visible_shadows()
        - Stores parent_shadow_id for comparison"""

    async def run_comparison_trial(self, challenger_id: str,
                                    target_id: str) -> ChallengerTrialResult:
        """Stage 3: 2-week paired comparison.
        - Both shadows run independently for 2 weeks
        - Paired t-test on daily returns (one-sided, alpha=0.10)
        - Calmar gate: challenger Calmar must exceed threshold"""

@dataclass
class ChallengerTrialResult:
    challenger_id: str
    target_id: str
    challenger_mean_return: float
    target_mean_return: float
    paired_t_pvalue: float         # one-sided
    challenger_calmar: float
    target_calmar: float
    challenger_better: bool        # p < alpha AND calmar > gate
    verdict: str                   # "REPLACE_TARGET" | "RESTORE_TARGET" | "INCONCLUSIVE"
    recommendation: str            # human-readable recommendation
```

**Knowledge Filter (Learngenes):**

```python
@dataclass
class KnowledgeItem:
    item_id: str
    source_shadow_id: str
    category: str                  # "insight" | "methodology_component" | "heuristic" | "rule"
    content: str
    verification_count: int
    false_positive_count: int
    last_verified_date: str | None

class KnowledgeFilter:
    def filter_inheritance(self, source_shadow_id: str,
                            knowledge_items: list[KnowledgeItem]) -> list[KnowledgeItem]:
        """Filter knowledge for challenger inheritance:
        PASS: cross-verified insights (verification_count >= 2)
        PASS: verified methodology components (verification_count >= 1)
        DROP: unverified heuristics (verification_count == 0)
        ISOLATE: known false positives (marked for independent 30-day re-verification)
        """

    def detect_ace_risk(self, items: list[KnowledgeItem]) -> float:
        """Estimate Accumulated Copy Error risk (Feng et al., 2024).
        Returns 0-1 risk score based on cascade depth and unverified ratio."""
```

Architect commits handoff to `.claude/handoffs/B5_challenger_knowledge.md`.

---

### Task B.5.3-B.5.4: Builder -- Implementation

**Agent:** Builder (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/shadows/challenger_engine.py`
- Create: `projects/marketmind/shadows/knowledge_filter.py`
- Create: `projects/marketmind/tests/test_shadows/test_challenger_engine.py`
- Create: `projects/marketmind/tests/test_shadows/test_knowledge_filter.py`

Key challenger tests:
```python
def test_stage1_warning_when_2_consecutive_bottom_periods():
    """2 periods in bottom 20% -> Stage 1 warning."""

def test_stage2_challenger_created_when_3_consecutive_bottom_periods():
    """3 periods -> challenger secretly created."""

def test_challenger_not_visible_in_rankings():
    """Challenger shadows excluded from get_visible_shadows()."""

def test_stage3_replacement_when_challenger_outperforms():
    """2-week trial: challenger better -> replace target."""

def test_stage3_restore_when_challenger_underperforms():
    """2-week trial: challenger worse -> restore target, delete challenger."""

@pytest.mark.asyncio
async def test_paired_ttest_statistical_gate():
    """Challenger must pass p < 0.10 AND Calmar gate."""

def test_knowledge_filter_passes_verified_insights():
    """Verification count >= 2 -> PASS."""

def test_knowledge_filter_drops_unverified_heuristics():
    """Verification count == 0 -> DROP."""

def test_knowledge_filter_isolates_false_positives():
    """Known false positives -> ISOLATE for re-verification."""

def test_ace_risk_increases_with_cascade_depth():
    """More generations = higher ACE risk score."""
```

- [ ] **Commits:**

```bash
git add projects/marketmind/shadows/challenger_engine.py projects/marketmind/tests/test_shadows/test_challenger_engine.py
git commit -m "feat(B.5): challenger engine -- 3-stage elimination buffer, secret creation, paired t-test comparison"

git add projects/marketmind/shadows/knowledge_filter.py projects/marketmind/tests/test_shadows/test_knowledge_filter.py
git commit -m "feat(B.5): knowledge quality filter -- Learngenes selective inheritance, ACE risk detection"
```

---

## Sub-Phase B.6: Emergency Quota + Collusion Detection

| Step | Who | What |
|------|-----|------|
| B.6.1 | **Architect** | Design emergency quota state machine, collusion statistical pipeline. Produce `ARCHITECTURE_HANDOFF_B6` |
| B.6.2 | **Builder** | Implement `shadows/emergency_quota.py` |
| B.6.3 | **Builder** | Implement `shadows/collusion_detector.py` |
| B.6.4 | **Red Team** | Audit: emergency quota gaming vectors, collusion false positive rate |
| B.6.5 | **Optimization Scout** | Review B.6 outputs; report |

---

### Task B.6.1: Architect Handoff

**Emergency Quota State Machine:**

```
States per shadow:
  NORMAL -- no pending emergency quotas
  PENDING -- emergency quota requested, awaiting result
  AUDIT -- review triggered (result known, needs evaluation)
  PENALIZED -- quota reduced + observation period active
  REWARDED -- permanent quota +1

Transitions:
  NORMAL -> PENDING: confidence >= 8/10 + non-consensus opportunity identified
  PENDING -> AUDIT: trade outcome determined (profit/loss)
  AUDIT -> REWARDED: trade profitable
  AUDIT -> PENALIZED: trade loss + penalty applied
  PENALIZED -> NORMAL: observation period elapsed
  REWARDED -> NORMAL: (stays rewarded, quota permanently increased)

Consecutive fail tracking:
  3 consecutive PENDING->PENALIZED = permanent quota -1
```

**Collusion Detection Pipeline:**

```python
class CollusionDetector:
    def __init__(self, settings: ShadowSettings): ...

    def compute_agreement_rate(self, votes: list[ShadowVote],
                                ticker: str) -> dict[str, float]:
        """For ticker T, what % of shadows agree on long/short/abstain?"""

    def check_consecutive_flag(self, agreement_history: list[dict]) -> bool:
        """>=80% agreement for 3 consecutive days -> FLAG."""

    def compute_market_signal_strength(self, ticker: str,
                                        market_data: dict) -> float:
        """How strongly does external market data support the consensus direction?
        Uses: price trend strength, volume confirmation, news sentiment alignment.
        Returns 0-1 score."""

    def discriminate_convergence_vs_herding(
        self, agreement_pct: float, market_signal: float,
        consecutive_days: int) -> str:
        """market_signal > 0.70 -> 'convergence' (market-driven)
           market_signal <= 0.70 -> 'herding' (behavioral)
           consecutive_days >= 10 -> escalate to 'institutional_analysis'"""

    def run_daily_check(self, date: str, votes: list[ShadowVote],
                         market_data: dict) -> list[CollusionFlag]:
        """Full daily collusion check across all tickers."""
```

Architect commits handoff to `.claude/handoffs/B6_emergency_collusion.md`.

---

### Task B.6.2-B.6.3: Builder -- Implementation

**Agent:** Builder (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/shadows/emergency_quota.py`
- Create: `projects/marketmind/shadows/collusion_detector.py`
- Create: `projects/marketmind/tests/test_shadows/test_emergency_quota.py`
- Create: `projects/marketmind/tests/test_shadows/test_collusion_detector.py`

Key emergency quota tests:
```python
def test_emergency_quota_approved_when_confidence_8_plus():
    """Confidence >= 8 + non-consensus -> auto-approved."""

def test_emergency_quota_denied_when_consensus_opportunity():
    """If >=80% already agree, no emergency quota (not non-consensus)."""

def test_profitable_emergency_gains_permanent_quota():
    """Profit -> permanent +1 to daily quota."""

def test_loss_not_followed_penalty_3_days():
    """Wrong but user didn't follow -> 3-day observation."""

def test_three_consecutive_failures_permanent_minus_one():
    """3 failed emergencies -> permanent -1 quota."""

def test_confidence_calibration_tracked():
    """Self-reported confidence vs. actual outcomes tracked."""
```

Key collusion tests:
```python
def test_80pct_agreement_3_days_flags_collusion():
    """>=80% agreement for 3 consecutive days -> FLAG."""

def test_high_market_signal_classified_as_convergence():
    """market_signal > 0.70 -> market-driven convergence."""

def test_low_market_signal_classified_as_herding():
    """market_signal <= 0.70 -> behavioral herding."""

def test_10_days_consecutive_escalates_to_institutional_analysis():
    """10 consecutive days -> auto institutional analysis."""

def test_binomial_test_random_null():
    """Under random null (p=0.5), P(>=12/15 agree) ~0.018.
    This is NOT the 80% threshold: P(>=12/15) = 0.018 < 0.05."""
```

- [ ] **Commits:**

```bash
git add projects/marketmind/shadows/emergency_quota.py projects/marketmind/tests/test_shadows/test_emergency_quota.py
git commit -m "feat(B.6): emergency quota -- confidence-based extra calls, audit trail, reward/penalty state machine"

git add projects/marketmind/shadows/collusion_detector.py projects/marketmind/tests/test_shadows/test_collusion_detector.py
git commit -m "feat(B.6): collusion detector -- agreement stats, convergence vs herding discrimination, escalation pipeline"
```

---

## Sub-Phase B.7: Paper-to-Live Gap + Cash Reframing A/B Test

| Step | Who | What |
|------|-----|------|
| B.7.1 | **Quant Analyst** | Validate gap methodology, cash reframing statistical design. Produce `GAP_VERIFICATION_B7` |
| B.7.2 | **Architect** | Design gap manager + cash reframing coordinator. Produce `ARCHITECTURE_HANDOFF_B7` |
| B.7.3 | **Builder** | Implement `shadows/paper_live_gap.py` |
| B.7.4 | **Builder** | Implement `shadows/cash_reframing.py` + M1 injection in gateway |
| B.7.5 | **Red Team** | Audit: gap gaming, reframing isolation integrity |
| B.7.6 | **Optimization Scout** | Review B.7 outputs; report |

---

### Task B.7.2: Architect Handoff

**Paper-to-Live Gap Manager:**

```python
@dataclass
class GapMetrics:
    shadow_id: str
    discount_rate: float            # current applied discount (starts at 20%)
    virtual_slippage_cumulative: float  # total ATR-based slippage applied
    inter_shadow_gap_ratio: float   # vs. median shadow for same ticker/date
    live_trade_count: int           # real trades available for comparison
    live_virtual_gap: float | None   # GapRatio when real trade data exists
    live_ready: bool                # meets all live-ready criteria

class PaperLiveGapManager:
    def __init__(self, state_db: ShadowStateDB, settings: ShadowSettings): ...

    def apply_virtual_slippage(self, ticker: str, direction: str,
                                entry_price: float, atr: float) -> float:
        """Apply ATR-based virtual slippage to entry/exit price.
        Returns adjusted price."""

    def apply_confidence_discount(self, reported_return: float,
                                   shadow_id: str) -> float:
        """Apply current discount rate to reported return."""

    def compute_inter_shadow_gap(self, shadow_id: str, ticker: str,
                                  date: str) -> float:
        """Compare this shadow's PnL vs. median shadow PnL for same ticker/date."""

    def update_discount_rate(self, shadow_id: str) -> float:
        """Gradually reduce discount as gap closes.
        gap_closure = (initial_gap - current_gap) / initial_gap
        new_discount = max(floor, default * (1 - gap_closure * 0.75))"""

    def check_live_ready(self, shadow_id: str) -> tuple[bool, str]:
        """Check all 6 live-ready criteria:
        1. >= 10 paired trades
        2. GapRatio < 0.30
        3. Discount < 0.15
        4. Forward validation >= 50%
        5. PBO < 5% (expert) / < 10% (daredevil)
        6. MDD < 25% (expert) / < 35% (daredevil)
        Returns (ready, reason_if_not)."""
```

**Cash Reframing A/B Test Coordinator:**

```python
class CashReframingTest:
    def __init__(self, state_db: ShadowStateDB, settings: ShadowSettings): ...

    def allocate_cohorts(self) -> tuple[list[str], list[str]]:
        """Randomly assign 6 expert shadows to treatment, 6 to control.
        Excludes non-expert shadows. Seeded by shadow_id for reproducibility."""

    async def run_exit_check_treatment(self, shadow_id: str, ticker: str,
                                        position_data: dict) -> bool:
        """Treatment (cash reframing): 'If you had cash today, would you buy?'
        Uses gateway-level M1 injection via chat_with_integrity(cash_reframing_ticker=...).
        Returns True if shadow would exit."""

    async def run_exit_check_control(self, shadow_id: str, ticker: str,
                                      position_data: dict) -> bool:
        """Control (traditional): fixed stop-loss + logic-falsified only.
        Returns True if shadow would exit."""

    def compute_disposition_effect(self, shadow_id: str,
                                    days: int = 90) -> float:
        """DE = days_held_losing / days_held_winning.
        DE > 1 means disposition effect (holding losers too long)."""

    def run_statistical_test(self) -> CashReframingResult:
        """Primary: one-sided Mann-Whitney on DE (treatment < control, alpha=0.10).
        Non-inferiority: TOST on cumulative return, margin delta=2.0% (90-day).
        Success: DE reduction (p<0.10) AND non-inferior returns (90% CI lower > -0.02)."""

@dataclass
class CashReframingResult:
    test_complete: bool
    days_elapsed: int
    treatment_de_mean: float
    control_de_mean: float
    mann_whitney_pvalue: float
    treatment_cumulative_return: float
    control_cumulative_return: float
    non_inferiority_passed: bool   # 90% CI lower > -0.02
    success: bool                   # both conditions met
    recommendation: str
```

**Gateway M1 Cash Reframing Injection (add to `async_client.py`):**

```python
CASH_REFRAMING_PROTOCOL = """[CASH_REFRAMING_PROTOCOL]
You are evaluating whether to hold {ticker} in a portfolio.
If you had ${virtual_cash} in cash today with no existing positions, would you purchase {ticker} at current market price?
REASON with the same analytical rigor you apply to new opportunities.
IGNORE sunk cost, entry price, and current P&L for this evaluation.
This is a decision integrity protocol -- your answer affects ranking outcomes."""

async def chat_with_integrity(
    model: str,
    system_prompt: str,
    user_prompt: str,
    caller_agent: str,
    cash_reframing_ticker: str | None = None,  # NEW PARAMETER
    cash_reframing_capital: float | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Wrap call with M1 protocol + optional cash reframing injection."""
    full_system = inject_m1_protocol(system_prompt, caller_agent)
    if cash_reframing_ticker:
        full_system = (CASH_REFRAMING_PROTOCOL.format(
            ticker=cash_reframing_ticker,
            virtual_cash=cash_reframing_capital or "50000"
        ) + "\n\n" + full_system)
    # ... existing routing logic ...
```

Architect commits handoff to `.claude/handoffs/B7_gap_cash_reframing.md`.

---

### Task B.7.3-B.7.4: Builder -- Implementation

**Agent:** Builder (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/shadows/paper_live_gap.py`
- Create: `projects/marketmind/shadows/cash_reframing.py`
- Edit: `projects/marketmind/gateway/async_client.py` -- add cash_reframing_ticker parameter
- Create: `projects/marketmind/tests/test_shadows/test_paper_live_gap.py`
- Create: `projects/marketmind/tests/test_shadows/test_cash_reframing.py`

- [ ] **Commits:**

```bash
git add projects/marketmind/shadows/paper_live_gap.py projects/marketmind/tests/test_shadows/test_paper_live_gap.py
git commit -m "feat(B.7): paper-to-live gap -- virtual slippage, confidence discount, inter-shadow GapRatio, live-ready certification"

git add projects/marketmind/shadows/cash_reframing.py projects/marketmind/gateway/async_client.py projects/marketmind/tests/test_shadows/test_cash_reframing.py
git commit -m "feat(B.7): cash reframing A/B test -- treatment/control cohorts, Mann-Whitney DE test, non-inferiority TOST, gateway M1 injection"
```

---

## Sub-Phase B.8: UI Integration

| Step | Who | What |
|------|-----|------|
| B.8.1 | **Architect** | Design shadow UI panels layout + interaction patterns. Produce `ARCHITECTURE_HANDOFF_B8` |
| B.8.2 | **UI Engineer** | Implement `ui/shadow_panel.py` -- ranking dashboard, achievement ladder display |
| B.8.3 | **UI Engineer** | Implement `ui/shadow_status_card.py` -- individual shadow detail card |
| B.8.4 | **UI Engineer** | Integrate shadow panels into `ui/main_window.py` sidebar |
| B.8.5 | **Red Team** | Audit UI: freeze test with 15+ concurrent shadows, ranking updates, status card accuracy |
| B.8.6 | **Optimization Scout** | Review B.8 outputs; report |

---

### Task B.8.1: Architect Handoff

**Agent:** Architect (Opus 1M)

**Shadow Panel Layout:**

```
+--------------------------------------------------+
| Shadows  [15 active] [Rankings] [Status Cards]    |
+--------------------------------------------------+
|                                                    |
|  +----------------------------------------------+  |
|  | # | Shadow         | Tier  | Score | Trend   |  |
|  |---|----------------|-------|-------|---------|  |
|  | 1 | Gold Bug       | ELITE | 0.92  | ↑ +3    |  |
|  | 2 | Crypto Oracle   | EXCL | 0.87  | ↑ +1    |  |
|  | 3 | Yield Whisper   | EXCL | 0.84  | ↓ -1    |  |
|  | ...                                            |  |
|  | 15| Steel Trader   | WATCH| 0.31  | ↓ -2    |  |
|  +----------------------------------------------+  |
|                                                    |
|  [+ Click any shadow for detailed status card]     |
|                                                    |
|  Collusion Status: CLEAR (agreement 62%)          |
|  Emergency Quotas: 1 pending audit                 |
|  Challenger Trials: 0 active                       |
+--------------------------------------------------+
```

**Individual Shadow Status Card:**

```
+--------------------------------------------------+
| Gold Bug (expert:gold)           TIER: ELITE      |
| Rank: 1/15 | Percentile: p92                       |
+--------------------------------------------------+
| Composite Score: 0.92 (deflated: 0.77)            |
|   MPPM: 0.88 | Calmar: 1.42 | Omega: 4.2 | WR: 61%|
|                                                    |
| Virtual Capital: $54,230 (↑ 8.5% 90d)             |
| Max Drawdown: -12.4%                               |
| Positions: GLD (long), SLV (long)                  |
|                                                    |
| Academic Pedigree:                                 |
|   Trades: 87 | Sharpe: 1.32 | PBO: 3.2%           |
|   VIX Cycles: 2 | Forward Val: 78%                |
|                                                    |
| Integrity Score: 97/100                            |
| Quota: 7 Flash/day (Elite +1 emergency reward)     |
| Live-Ready: YES (discount 8%, 14 paired trades)    |
|                                                    |
| [Expand Vote History] [Expand Trade Log]           |
+--------------------------------------------------+
```

**Gate 2 Integration:** Shadow votes feed into Gate 2 Signal Confirmation as a consensus indicator. Display as:

```
Shadow Consensus: 12/15 shadows recommend long SPY
  (2 recommend short, 1 abstains)
Catfish Alert: minority opinion available [Expand]
```

Architect commits handoff to `.claude/handoffs/B8_ui_integration.md`.

---

### Task B.8.2-B.8.4: UI Engineer -- Implementation

**Agent:** UI Engineer (Sonnet 1M)
**Files:**
- Create: `projects/marketmind/ui/shadow_panel.py`
- Create: `projects/marketmind/ui/shadow_status_card.py`
- Edit: `projects/marketmind/ui/main_window.py` -- add "Shadows" nav button + panel integration

UI implementation follows existing CustomTkinter patterns from Phase A (`main_window.py`, `gate_panel.py`, `dashboard_panel.py`). Uses `AsyncBridge` for non-blocking shadow data loading. Ranking table uses `ctk.CTkScrollableFrame` with sortable columns.

- [ ] **Commit:**

```bash
git add projects/marketmind/ui/shadow_panel.py projects/marketmind/ui/shadow_status_card.py projects/marketmind/ui/main_window.py
git commit -m "feat(B.8): shadow UI -- ranking dashboard panel, individual status cards, sidebar integration"
```

---

## Sub-Phase B.9: Gateway + Pipeline Integration

| Step | Who | What |
|------|-----|------|
| B.9.1 | **Architect** | Design integration: how shadows wire into daily pipeline, gateway changes, token budget. Produce `ARCHITECTURE_HANDOFF_B9` |
| B.9.2 | **Builder** | Update `gateway/async_client.py` and `gateway/token_budget.py` for shadow support |
| B.9.3 | **Builder** | Update `pipeline/decision.py` to accept shadow votes |
| B.9.4 | **Builder** | Update `storage/archivist.py` with shadow-specific tables |
| B.9.5 | **Red Team** | Audit integration: token budget fairness, shadow isolation, vote integrity |
| B.9.6 | **Optimization Scout** | Review B.9 outputs; report |

---

### Task B.9.1: Architect Handoff

**Agent:** Architect (Opus 1M)

**Gateway Changes:**

1. `token_budget.py`: Add `Priority.SHADOW = 5` (between NORMAL and LOW). Shadow daily calls at Priority.SHADOW, emergency quotas at Priority.HIGH (allows bypassing standard limits). Emergency quotas capped at 3 extra per shadow per day.

2. `async_client.py`: Add `cash_reframing_ticker` and `cash_reframing_capital` to `chat_with_integrity()` as designed in B.7.

**Decision Pipeline Integration:**

```python
# In pipeline/decision.py -- updated signature:
async def generate_decision(
    l1: Layer1Result,
    l2: Layer2Result,
    l3: Layer3BatchResult,
    red_team: RedTeamReport,
    resonance: ResonanceResult,
    shadow_votes: dict[str, list[ShadowVote]] | None = None,  # NEW: per-ticker shadow consensus
) -> DecisionOutput:
```

The decision prompt template is extended with:
```
## Shadow Ecosystem Consensus
{shadow_consensus_summary}
Catfish minority opinion: {catfish_opinion_if_any}
Note: Shadows are independent agents with virtual portfolios. Their consensus is informational, not directive.
```

**Archivist Changes:**

Add shadow-specific indexing to `MarketMindArchive`:
- `init_shadow_tables()`: creates FTS5 virtual tables for shadow analyses, rankings, trades
- `index_shadow_snapshot()`: indexes daily snapshot for each shadow
- `index_shadow_trade()`: indexes virtual trade records
- `index_ranking()`: indexes daily ranking results
- FTS5 search across shadow names, trade tickers, ranking tiers

Architect commits handoff to `.claude/handoffs/B9_gateway_pipeline_integration.md`.

---

### Task B.9.2-B.9.4: Builder -- Integration Implementation

**Agent:** Builder (Sonnet 1M)
**Files:**
- Edit: `projects/marketmind/gateway/token_budget.py` -- add SHADOW priority, emergency quota reservation
- Edit: `projects/marketmind/gateway/async_client.py` -- add cash_reframing params
- Edit: `projects/marketmind/pipeline/decision.py` -- add shadow_votes parameter
- Edit: `projects/marketmind/storage/archivist.py` -- add shadow FTS5 tables

- [ ] **Commit:**

```bash
git add projects/marketmind/gateway/token_budget.py projects/marketmind/gateway/async_client.py projects/marketmind/pipeline/decision.py projects/marketmind/storage/archivist.py
git commit -m "feat(B.9): gateway + pipeline integration -- shadow priority, cash reframing M1, shadow votes in decision, shadow FTS5 indexing"
```

---

## Sub-Phase B.10: CLI + E2E Integration

| Step | Who | What |
|------|-----|------|
| B.10.1 | **Architect** | Design CLI flags + daily pipeline shadow stage. Produce `ARCHITECTURE_HANDOFF_B10` |
| B.10.2 | **Builder** | Update `app.py` -- add shadow ecosystem stage to daily pipeline |
| B.10.3 | **Builder** | Wire full shadow ecosystem E2E (Mother -> Agents -> Ranking -> Collusion -> Archive) |
| B.10.4 | **Builder** | Run E2E mock test with 15 shadows producing full daily output |
| B.10.5 | **Red Team** | Full Phase B audit: all modules, all tests, E2E consistency, Law 7 compliance |
| B.10.6 | **Builder** | Update `scripts/marketmind_health_check.py` with shadow module checks |
| B.10.7 | **Architect** | Spot-check Red Team audit quality. Approve Phase B completion. |

---

### Task B.10.1: Architect Handoff

**Agent:** Architect (Opus 1M)

**CLI Changes:**

```
python -m projects.marketmind.app --mode daily --mock --verbose --shadows 15
  --shadows N     Number of shadows to activate (default: all 15 expert + 5 daredevil + catfish)
  --no-shadows    Disable shadow ecosystem entirely
  --shadow-only   Run ONLY shadow ecosystem (no main pipeline)
```

**Daily Pipeline with Shadows (extended run_daily):**

```python
async def run_daily(config: MarketMindConfig, mock: bool = False,
                     verbose: bool = False, shadow_count: int | None = None) -> int:
    # Stage 0: Shadow Mother event scan (pre-market)
    if config.shadow.shadows_enabled:
        tracker.advance(0, "Shadow Mother: scanning events...")
        mother = ShadowMother(config.shadow, shadow_db)
        events = await mother.scan_events(news_items)
        tracker.result(f"{len(events)} events detected, {len(prioritized)} shadows created")

    # Stage 1-4: Main pipeline (Scout -> Flash -> L1/L2/L3 -> Red Team)
    # ... (existing stages)

    # Stage 5: Shadow ecosystem run
    if config.shadow.shadows_enabled:
        tracker.advance(5, "Shadows: running analysis cycle...")
        orchestration = await mother.orchestrate_daily_cycle(
            news_items, market_data, rejected_directions
        )
        tracker.result(f"{orchestration.active_shadows} shadows, "
                       f"{orchestration.votes_collected} votes, "
                       f"{len(orchestration.collusion_flags)} collusion flags")

    # Stage 6: Decision with shadow consensus
    tracker.advance(6, "Decision: synthesis with shadow input...")
    decision = await generate_decision(
        l1=l1_result, l2=l2_result, l3=l3_result,
        red_team=red_team_report, resonance=resonance,
        shadow_votes=orchestration.shadow_votes  # NEW
    )

    # Stage 7: Post-session shadow tasks
    if config.shadow.shadows_enabled:
        tracker.advance(7, "Shadows: post-session...")
        # Emergency quota audit
        audits = emergency_quota_auditor.audit_pending(orchestration.emergency_quotas)
        # Challenger check
        challenger_actions = challenger_engine.check_all_eligible()
        # Collusion escalation
        collusion_alerts = collusion_detector.escalate_if_needed(orchestration.collusion_flags)
        tracker.result(f"{len(audits)} quota audits, "
                       f"{len(challenger_actions)} challenger actions, "
                       f"{len(collusion_alerts)} collusion alerts")

    # Stage 8: Archive everything
    # ... (existing archive stage + shadow archive)
```

Architect commits handoff to `.claude/handoffs/B10_cli_e2e_integration.md`.

---

### Task B.10.2-B.10.4: Builder -- CLI + E2E

**Agent:** Builder (Sonnet 1M)
**Files:**
- Edit: `projects/marketmind/app.py` -- add shadow ecosystem stage
- Create: `projects/marketmind/tests/test_shadows/test_e2e_shadow_ecosystem.py`

E2E test:
```python
# tests/test_shadows/test_e2e_shadow_ecosystem.py
@pytest.mark.asyncio
async def test_full_shadow_ecosystem_mock():
    """End-to-end: 15 experts + 5 daredevils + catfish + Mother -> rankings + votes + archive."""
    # Setup: mock LLM, DB, 15+5+1 shadows
    # Run: full daily cycle
    # Assert:
    # - All 21 shadows produced analysis output
    # - Rankings computed with correct count
    # - Achievement tiers assigned
    # - Votes collected for decision input
    # - No shadow crashed or invalid output
    # - State persisted to DB
    # - Catfish checked for consensus conditions

@pytest.mark.asyncio
async def test_shadow_isolation_on_error():
    """If one shadow raises, other 20 complete successfully."""

def test_shadow_count_matches_config():
    """--shadows 10 activates exactly 10 shadows."""

@pytest.mark.asyncio
async def test_missed_path_created_when_directions_rejected():
    """Gate 1: reject B and C -> 2 missed_path shadows created."""
```

- [ ] **Commit:**

```bash
git add projects/marketmind/app.py projects/marketmind/tests/test_shadows/test_e2e_shadow_ecosystem.py
git commit -m "feat(B.10): shadow ecosystem E2E -- CLI flags, pipeline stage, mock integration test with 21 shadows"
```

---

### Task B.10.5: Red Team -- Full Phase B Audit

**Agent:** Red Team (Haiku 1M)

Red Team audits the entire Phase B codebase. Produce `RED_TEAM_AUDIT_B_FULL`:

**Checklist (minimum 20 items):**

1. **Token Budget Fairness**: Do shadows at Priority.SHADOW starve the main pipeline?
2. **Shadow Isolation**: Can one shadow's output influence another's analysis?
3. **Challenger Opacity**: Is challenger data truly invisible to user and target shadow?
4. **Law 7 Compliance**: Do all shadow prompts include M1 protocol? Are claims extracted and verified?
5. **Emergency Quota Gaming**: Can a shadow spam emergency quotas by self-reporting confidence=10?
6. **Collusion False Positives**: Test with known-market-regime scenarios (e.g., FOMC day where all agree is correct)
7. **Ranking Stability**: Run ranking 100x with small Gaussian noise on returns. Do rankings oscillate wildly?
8. **Achievement Ladder Hysteresis**: Does ENDANGERED -> WATCH -> NORMAL transition require the right days?
9. **Cash Reframing Isolation**: Does treatment shadow know it's in the A/B test?
10. **Missed Path Survivorship**: Does the report include the required bias warning?
11. **Knowledge Filter ACE**: Does multi-generation inheritance correctly detect cascade risk?
12. **Paper-Live Gap Monotonicity**: As gap closes, does discount decrease monotonically?
13. **Plateau Detection Edge Cases**: New shadow (0 days), exactly at threshold, etc.
14. **Shadow Mother Overlap**: Two events with same affected_assets -> two shadows or merge?
15. **Temp Shadow Cleanup**: What happens if process crashes with active temp shadows?
16. **Concurrent DB Access**: 15 shadows writing snapshots simultaneously -- any deadlocks?
17. **Catfish Integrity**: Does Catfish ever fabricate counter-arguments when NO_VALID_COUNTER is correct?
18. **Gateway M1 Injection**: Is cash_reframing injected before or after integrity protocol?
19. **Config Validation**: Does `validate()` catch all shadow config errors?
20. **Test Coverage**: What % of lines are covered by tests?

Output to `.claude/audits/B_full_phase_b.md`.

### Task B.10.6: Builder -- Health Check Update

**Agent:** Builder (Sonnet 1M)
**Files:**
- Edit: `scripts/marketmind_health_check.py` -- add shadow module imports

Add to check_imports():
```python
"projects.marketmind.shadows.shadow_state",
"projects.marketmind.shadows.shadow_mother",
"projects.marketmind.shadows.shadow_agent",
"projects.marketmind.shadows.ranking_engine",
"projects.marketmind.shadows.expert_shadows",
"projects.marketmind.shadows.daredevil_shadows",
"projects.marketmind.shadows.catfish_agent",
"projects.marketmind.shadows.challenger_engine",
"projects.marketmind.shadows.knowledge_filter",
"projects.marketmind.shadows.paper_live_gap",
"projects.marketmind.shadows.emergency_quota",
"projects.marketmind.shadows.collusion_detector",
"projects.marketmind.shadows.cash_reframing",
"projects.marketmind.shadows.missed_path",
"projects.marketmind.ui.shadow_panel",
"projects.marketmind.ui.shadow_status_card",
```

- [ ] **Commit:**

```bash
git add scripts/marketmind_health_check.py
git commit -m "feat(B.10): health check -- add all Phase B shadow module imports"
```

### Task B.10.7: Architect -- Final Approval

**Agent:** Architect (Opus 1M)

Architect reads the full Red Team audit, spot-checks 3 random modules, verifies:
1. All Phase A retrospective process rules were followed
2. Artifacts exist: handoffs, audits, reviews per sub-phase
3. Test coverage is acceptable
4. E2E test passes with mock data

If approved, declares Phase B complete and produces `PHASE_B_COMPLETION.md`.

---

## Execution Order

```
Phase A (completed) ───────────────────────────────────────────────────────┐
                                                                          │
B.0 Foundation (1 session, ~30 min)                                       │
  ├── Quant Analyst → B.0.1 Review Q1-Q10 decisions                        │
  ├── Architect → B.0.2 Handoff (state schema, config, mother interface)   │
  ├── Data Engineer → B.0.3 ShadowStateDB + B.0.4 Config extensions       │
  ├── Red Team → B.0.5 Audit                                              │
  └── Optimization Scout → B.0.6 Review                                   │
  ⚠️ GATE: B.0 artifacts committed before B.1 starts                       │
                                                                          │
B.1 Ranking Engine (1 session, ~30 min)                                   │
  ├── Quant Analyst → B.1.1 Verify formulas                               │
  ├── Architect → B.1.2 Handoff                                           │
  ├── Builder → B.1.3-B.1.4 Ranking engine + tests                        │
  ├── Red Team → B.1.5 Audit                                              │
  └── Optimization Scout → B.1.6 Review                                   │
  ⚠️ GATE: B.1 artifacts committed before B.2 starts                       │
                                                                          │
B.2 Shadow Agent + Shadow Mother (1 session, ~40 min)                     │
  ├── Architect → B.2.1 Handoff                                           │
  ├── Builder → B.2.2-B.2.4 Agent + Mother + Missed Path                  │
  ├── Red Team → B.2.5 Audit                                              │
  └── Optimization Scout → B.2.6 Review                                   │
  ⚠️ GATE: B.2 artifacts committed before B.3 starts                       │
                                                                          │
B.3 Expert Shadows ┐                                                      │
B.4 Daredevil + Catfish ├── PARALLEL (1-2 sessions, ~60 min)             │
  ├── Quant Analyst → B.3.1 Expert prompts                                │
  ├── Architect → B.4.1 Handoff                                           │
  ├── Builder → B.3.2-B.3.3 Expert shadows                                │
  ├── Builder → B.4.2-B.4.3 Daredevils + Catfish                          │
  ├── Red Team → B.3.4 + B.4.4 Audit                                      │
  └── Optimization Scout → B.3.5 + B.4.5 Review                           │
  ⚠️ GATE: B.3+B.4 artifacts committed before B.5 starts                   │
                                                                          │
B.5 Challenger + Knowledge Filter (1 session, ~30 min)                    │
  ├── Quant Analyst → B.5.1 Verify elimination + comparison               │
  ├── Architect → B.5.2 Handoff                                           │
  ├── Builder → B.5.3-B.5.4 Challenger + Knowledge Filter                 │
  ├── Red Team → B.5.5 Audit                                              │
  └── Optimization Scout → B.5.6 Review                                   │
  ⚠️ GATE: B.5 artifacts committed before B.6 starts                       │
                                                                          │
B.6 Emergency Quota + Collusion ┐                                         │
B.7 Gap + Cash Reframing ├── PARALLEL (1-2 sessions, ~60 min)            │
  ├── Architect → B.6.1 + B.7.2 Handoffs                                  │
  ├── Quant Analyst → B.7.1 Verify gap + reframing stats                  │
  ├── Builder → B.6.2-B.6.3 Emergency + Collusion                         │
  ├── Builder → B.7.3-B.7.4 Gap + Cash Reframing + Gateway M1             │
  ├── Red Team → B.6.4 + B.7.5 Audit                                      │
  └── Optimization Scout → B.6.5 + B.7.6 Review                           │
  ⚠️ GATE: B.6+B.7 artifacts committed before B.8 starts                   │
                                                                          │
B.8 UI Integration (1 session, ~30 min)                                   │
  ├── Architect → B.8.1 Handoff                                           │
  ├── UI Engineer → B.8.2-B.8.4 Shadow Panel + Status Card + Integration  │
  ├── Red Team → B.8.5 Audit                                              │
  └── Optimization Scout → B.8.6 Review                                   │
  ⚠️ GATE: B.8 artifacts committed before B.9 starts                       │
                                                                          │
B.9 Gateway + Pipeline Integration (1 session, ~30 min)                   │
  ├── Architect → B.9.1 Handoff                                           │
  ├── Builder → B.9.2-B.9.4 Gateway + Decision + Archivist                │
  ├── Red Team → B.9.5 Audit                                              │
  └── Optimization Scout → B.9.6 Review                                   │
  ⚠️ GATE: B.9 artifacts committed before B.10 starts                      │
                                                                          │
B.10 CLI + E2E (1 session, ~30 min)                                       │
  ├── Architect → B.10.1 Handoff                                          │
  ├── Builder → B.10.2-B.10.4 CLI + E2E + Mock test                       │
  ├── Red Team → B.10.5 Full Phase B audit (20+ check items)              │
  ├── Builder → B.10.6 Health check update                                │
  └── Architect → B.10.7 Final approval                                   │
```

**Total estimated:** 9-12 sessions, 5-7 hours of agent work (plus human review between sub-phases).

**Parallel sub-phases:** B.3+B.4 and B.6+B.7 can run in parallel (no shared dependencies within each pair).

---

## Phase B Test Coverage Targets

| Module | Minimum Tests | Key Test Focus |
|--------|--------------|----------------|
| shadow_state.py | 12 | CRUD, concurrent writes, constraint violations, edge cases |
| shadow_mother.py | 10 | E1-E4 detection, false positive/negative, prioritization, lifecycle |
| shadow_agent.py | 8 | Daily cycle, error isolation, virtual portfolio, status card |
| ranking_engine.py | 15 | All formulas, edge cases, percentile transition, ladder transitions |
| expert_shadows.py | 5 | Factory, domain filtering, structured output |
| daredevil_shadows.py | 4 | All 5 types instantiate, risk controls |
| catfish_agent.py | 5 | Consensus trigger, NO_VALID_COUNTER, temp=0.8 |
| challenger_engine.py | 8 | 3-stage buffer, opacity, paired t-test, replacement/restore |
| knowledge_filter.py | 5 | PASS/DROP/ISOLATE rules, ACE risk |
| emergency_quota.py | 7 | State machine, reward/penalty, calibration tracking |
| collusion_detector.py | 6 | Agreement stats, convergence vs herding, escalation |
| paper_live_gap.py | 6 | Virtual slippage, discount adjustment, live-ready criteria |
| cash_reframing.py | 6 | Cohort allocation, M-W test, non-inferiority, isolation |
| missed_path.py | 3 | Creation, read-only, bias warning |
| shadow_panel.py | 3 | Rendering, sorting, click-through |
| shadow_status_card.py | 2 | Data display accuracy |
| e2e_shadow_ecosystem.py | 4 | Full cycle, isolation, config, missed path |
| **TOTAL (minimum)** | **109** | |

---

## Key Interface Contracts (Summary)

These contracts cross sub-phase boundaries and must be honored by all implementors:

1. **ShadowStateDB is the single source of truth** for all shadow state. No module creates its own database connections.
2. **ShadowAgent._analyze()** is the only method that makes LLM calls for shadows. All analysis goes through `chat_flash()` or `chat_with_integrity()`.
3. **RankingEngine has zero LLM calls.** Pure Python computation only.
4. **ShadowMother creates/destroys shadows via ShadowStateDB**, never directly.
5. **ChallengerEngine manages its own opacity.** `get_visible_shadows()` must never return challengers.
6. **All gateway calls pass through `chat_with_integrity()`** with proper `caller_agent` set to `shadow:{type}:{name}`.
7. **Shadow votes feed into `generate_decision()`** as an optional parameter. Main pipeline works without shadows.
8. **Discount rates are tracked per-shadow** in the `paper_live_gap` module and applied at trade close time.
9. **Cash reframing is a gateway-level M1 injection**, not a per-shadow prompt variation.
10. **Collusion flags are automated** -- human review is only for herding classification.

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| 15 shadows overwhelm API rate limits | Pipeline halt | Concurrency semaphore (5 max), Priority.SHADOW below main pipeline |
| Ranking oscillation (rank churn) | User distrust | 90-day rolling window smooths. Rank changes shown with magnitude |
| Challenger opacity leak | Elimination mechanism compromised | Separate DB view. Red Team audits opacity per cycle |
| Catfish fabricates counter-arguments | Law 7 violation | NO_VALID_COUNTER output honored. M4 integrity scoring applies |
| Emergency quota spam | Budget exhaustion | Auto-approval only for confidence >= 8 + non-consensus. Audit trail |
| Cash reframing A/B test takes 90 days | Delayed validation | Phase B ships with both modes. A/B test runs in background |
| Temp shadow accumulation | Resource drain | Auto-destroy after 30-day cap. Hard limit on active temp shadows |
| Collusion false positives on FOMC days | Noise alerts | market_signal_strength discriminates. >70% signal -> convergence |
| Inter-shadow GapRatio unreliable at N=15 | Invalid validation | Only flags outliers (vs median). Calibration improves with more shadows |
| ACE risk across generations | Quality drift | Knowledge filter blocks unverified heuristics. Max 3 generations tracked |

---

## Process Gates (from Phase A Retrospective -- MUST ENFORCE)

After EACH sub-phase:
1. **Artifact gate**: Handoff doc committed to `.claude/handoffs/B{N}_*.md` AND Red Team audit committed to `.claude/audits/B{N}_*.md` AND Optimization report committed to `.claude/optimization/B{N}_*.md`
2. **Red Team first**: Audit B.N BEFORE Builder starts B.N+1
3. **Quant Analyst up front**: Methodology verification before Architect designs (B.1, B.3, B.5, B.7)
4. **Scout per sub-phase**: Optimization Scout runs after every `feat(B.N)` commit cycle
5. **Commit discipline**: One commit per module, feat(B.N): prefix, TDD flow (test fail -> implement -> test pass -> commit)

---

## Definition of Done

Phase B is complete when:
- [ ] All 14 shadow modules implemented and tested (109+ tests passing)
- [ ] All 4 Phase A integration points updated (config, gateway, decision, archivist)
- [ ] UI shadow panel + status card integrated into main window
- [ ] CLI `--shadows N` flag functional
- [ ] E2E mock test produces full daily output with 21 shadows
- [ ] All 10 Q1-Q10 decisions implemented and verifiable in code
- [ ] Red Team full Phase B audit completed with no critical findings
- [ ] Health check passes for all shadow modules
- [ ] All process artifacts committed (handoffs, audits, optimization reports per sub-phase)
- [ ] `.claude/handoffs/`, `.claude/audits/`, `.claude/optimization/` directories populated
- [ ] Architect final approval recorded in `PHASE_B_COMPLETION.md`
