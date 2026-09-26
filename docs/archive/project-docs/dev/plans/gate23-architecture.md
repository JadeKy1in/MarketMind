# Gate 2 & Gate 3 Architecture Plan

**Status**: DESIGN (v2 — Red Team logic + security audit fixes applied)
**Date**: 2026-05-18
**Research base**: `.claude/research/gate23-decision-frameworks.md`
**Audits applied**: `.claude/audits/gate23-plan-logic.md` (3 CRITICAL), `.claude/audits/gate23-plan-security.md` (7 findings)

## Pipeline Insertion Point

```
Stage 0-3 (scout→flash→HVR) → Gate 1 (direction) → Stages 4-10 (L1-L3, shadows, Red Team, resonance, fragility, regime) → Gate 2 (signal confirmation) → Gate 3 (position decision) → Archive
```

Gate 2 and Gate 3 are the final two human touchpoints. Gate 2 is the "IC Presentation + Vote" moment. Gate 3 is the "Final Execution" gate. Both produce written, auditable outcomes.

## Gate 2: Signal Confirmation

### Purpose

After the full analysis pipeline (L1-L4, Red Team, resonance, fragility, regime mapping) completes, Gate 2 presents all findings to the user and asks: "Given what we've found, how strongly do you believe in this direction?" This is a conviction calibration gate -- no position sizing yet.

### Debiasing Mechanisms (Gate 2)

Gate 2 implements four specific debiasing mechanisms to mitigate AI anchoring effects:

1. **Conviction-before-evidence**: User states their independent conviction BEFORE seeing any AI analysis output. This prevents the AI's confidence score and evidence ordering from contaminating the user's judgment.
2. **Explicit overconfidence warning**: When AI analysis is shown, a calibration notice warns the user about known model biases: "AI模型在0.81置信度区间系统性过度自信约15%。请将此纳入你的判断。"
3. **Randomized evidence ordering**: Supporting and opposing evidence within each layer are presented in randomized order (not all bullish first). This prevents recency and primacy ordering effects.
4. **Devil's advocate**: Before final confirmation, the AI explicitly argues AGAINST the user's selected direction. This is structured intellectual conflict, not a prompt to change — it ensures the user has considered the counter-case.

### Step-by-Step Flow

**Step 2.1: Independent Conviction (BEFORE Evidence)**

The user states their independent conviction BEFORE seeing any AI analysis. The AI asks:

`在展示分析结果前，你对这个方向的信心是几成？`

The user provides their unaided conviction on a 1-10 scale (mapped to 0.1-1.0). This is recorded as `unaided_conviction` — the user's belief uncontaminated by AI output.

Options presented:
- **STRONG** (8-10): "我完全同意，愿意承担正常风险"
- **MODERATE** (5-7): "方向对，但需要谨慎"
- **WEAK** (1-4): "方向可能对，但信号不够强"

The AI records the raw number and level. Follow-up questions are deferred until after evidence review (Step 2.8).

**Step 2.2: Multi-Layer Evidence Summary (WITH Debiasing Notice)**

The AI presents a structured summary of all pipeline stages, organized by layer. Evidence within each layer is presented in RANDOMIZED order (supporting vs opposing shuffled, not all bullish first).

BEFORE the evidence table, the AI displays:
```
── 注意：AI置信度校准提醒 ──
AI模型在0.75-0.85置信度区间系统性过度自信约15%。
请将此偏差纳入你的独立判断。你的初始信心评估(Step 2.1)不受此数据影响。
── END ──
```

| Layer | Source | Summary (150 words max) |
|-------|--------|-------------------------|
| L1 | Narrative analysis | Event grade, matrix quadrant, sentiment, surprise level, cascade rank |
| L2 | Fundamental | Macro quadrant, ticker candidates, sector shortlist, preferred assets |
| L3 | Technical | Green/yellow/red counts, entry zones for green-lights |
| L4 (regime) | Historical analogue | Top 3 regime matches, similarity scores, forward return estimates |
| Red Team | Adversarial | Critical challenges (A-grade + critical), most important objection |
| Resonance | Statistical | DSR, PBO, verdict (passed/failed/flat) |
| Fragility | Systemic | Overall fragility score, crossed thresholds, staleness warnings |

This is display-only -- no LLM calls, pure formatting from existing pipeline output objects.

**Step 2.3: ELITE Shadow Integration**

The `EliteRegistry` (already implemented in `shadows/elite_participation.py`) checks the user's selected direction from Gate 1 against its `DOMAIN_KEYWORDS` map. Shadows whose domain keywords match the direction text are "awakened" and their pre-computed analysis is surfaced.

**Shadow awakening cap**: Maximum 5 ELITE shadows surfaced per Gate 2 session. If >5 match, show top 5 by domain-keyword-relevance score with a note: "7 of 15 ELITE shadows matched (showing top 5 by relevance)." If >50% of registered domains match, log a warning — this is anomalous and may indicate keyword-bombing.

**Shadow opinion sanitization**: All shadow opinion text MUST be passed through `_escape_markdown()` from `input_guard.py` before display. Shadow opinions are wrapped in `<!-- SHADOW_OPINION_START/END -->` markers in the Markdown archive, following the same pattern as user content.

Rules (already defined in CLAUDE.md and `elite_participation.py`):
- Each ELITE shadow contributes at most ONCE per session
- Contributions are clearly marked "SHADOW OPINION" -- advisory only
- ELITE shadows analyze news independently at the same time as the main AI (same daily cycle)
- They wait passively until their domain is triggered

Display format in Gate 2:
```
── SHADOW OPINION ──
[Gold Expert · ELITE] — the gold shadow's pre-computed view on the direction
[Crypto Analyst · ELITE] — the crypto shadow's pre-computed view
── END SHADOW OPINIONS ──
```

**Step 2.4: Shadow Consensus Tally**

The AI presents a consensus view across all relevant ELITE shadows:

```
Shadow Consensus: 7 of 12 relevant shadows agree with the selected direction
  3 dissent (Gold, Energy, Short)
  2 neutral (Volatility, Emerging)
```

This is informational, not dictating. The user can follow up: "Why does Gold shadow dissent?" and the AI surfaces that shadow's analysis.

**Step 2.5: Red Team Survivors**

The Red Team challenges that survived the adversarial process (i.e., were not refuted) are presented explicitly. The user must acknowledge them:

```
── SURVIVING RED TEAM CHALLENGES ──
1. [CRITICAL] The Fed's next dot plot could shift rate expectations by 50bp — 
   your L2 thesis assumes stable rates.
2. [HIGH] Liquidity in the chosen instrument is below the 90-day average — 
   slippage risk is elevated.
── END ──
```

The user can challenge any of these, triggering a re-review of that specific Red Team finding. Unchallenged items become "acknowledged risks" carried into Gate 3.

**Step 2.6: Signal Conflicts from Decision Layer**

Signal conflicts detected by `_detect_signal_conflicts()` in `decision.py` are presented:

```
── SIGNAL CONFLICTS ──
1. 因果分解(Directional Force: +0.65) 与 资金流(Imbalance: -0.10) 分歧度 0.75
   → Structural analysis is bullish, flow data is neutral-bearish. 
   Resolution needed before Gate 3.
── END ──
```

If conflicts exist, the user must annotate a resolution (e.g., "prioritize structural over flow" or "reduce conviction"). Unresolved conflicts block Gate 3.

**Step 2.7: Historical Regime Analogues**

Top 3 historical analogues from `regime_mapper.py` are displayed:

```
── HISTORICAL ANALOGUES ──
1. 1995 Soft Landing (similarity: 0.82) — forward 3M equity: +8.2%
2. 2007 Pre-Crisis Peak (similarity: 0.71) — forward 3M equity: -4.1%
3. 2018 Late-Cycle (similarity: 0.68) — forward 3M equity: -12.3%
Caution: These are historical analogues, not predictions.
── END ──
```

**Step 2.8: Devil's Advocate (Counter-Case)**

Before the final confirmation, the AI explicitly argues AGAINST the user's selected direction. This is mandatory and cannot be skipped:

```
── DEVIL'S ADVOCATE: Case Against This Direction ──
[AI constructs the strongest possible argument against the selected direction,
drawing from Red Team findings, opposing signal components, worst historical
analogue, and fragility warnings. Maximum 200 words.]
── END ──
```

The AI asks: "Having seen the counter-case, do you want to adjust your initial conviction of [X]/10?"

The user may adjust up or down. The FINAL conviction is the `conviction_score` (0.0-1.0) recorded in `ConvictionRecord`.

**Step 2.9: Kill Criteria Confirmation**

The kill criteria extracted by `kill_monitor.py` during the analysis are presented. The user reviews, adds, or removes criteria:

```
── KILL CRITERIA ──
1. [KC-001] EUR/USD 跌破 1.05 → KILL
2. [KC-002] 德国CPI < 2.2% → REDUCE_50
3. [ADD] (user-defined)
── END ──
```

**Step 2.10: Gate 2 Outcome**

Three possible outcomes:
1. **Continue to Gate 3**: User confirms conviction, acknowledges risks, confirms kill criteria.
2. **Modify direction**: User pivots -- return to Gate 1 with modifications.
3. **Pause (parking lot)**: User defers -- session archived as PARKED with notes.

### Gate 2 Output: ConvictionRecord

```python
@dataclass
class ConvictionRecord:
    session_id: str
    selected_direction: str          # from Gate 1
    unaided_conviction: float        # user's conviction BEFORE seeing AI evidence (Step 2.1)
    conviction_level: str            # "STRONG" | "MODERATE" | "WEAK"
    conviction_score: float          # 0.0-1.0 (final, after devil's advocate review)
    acknowledged_risks: list[str]    # Red Team challenges user acknowledged
    disputed_risks: list[str]        # Red Team challenges user disputed
    signal_conflicts_resolved: list[dict]  # {"conflict": description, "resolution": text}
    shadow_consensus: dict           # {"agree": N, "dissent": N, "neutral": N}
    shadow_opinions_surfaced: int    # how many ELITE contributions were shown
    kill_criteria: list[KillCriterion]
    regime_analogues_top3: list[str] # regime IDs
    gate2_outcome: str               # "CONTINUE" | "MODIFY" | "PAUSE"
    modification_notes: str          # if MODIFY
    pause_reason: str                # if PAUSE
    turn_count: int
    completed_at: str                # ISO timestamp
```

### Gate 2 Module Interface

```python
# pipeline/gate2_interaction.py

async def run_gate2(
    gate1_session: Gate1Session,        # direction selection from Gate 1
    pipeline_output: PipelineOutput,     # stages 4-10 results (see below)
    elite_registry: EliteRegistry,       # pre-computed shadow analyses
    session_id: str,
    io_handler: callable,                # async (prompt) -> str
    status_handler: callable,            # async (message) -> None
) -> ConvictionRecord:
    """Run the Gate 2 signal confirmation conversation loop."""
    ...
```

`PipelineOutput` is a new dataclass that bundles all Stage 4-10 results for Gate 2 consumption:

```python
@dataclass
class PipelineOutput:
    l1: Layer1Result
    l2: Layer2Result
    l3: Layer3BatchResult
    red_team: RedTeamReport
    resonance: ResonanceResult
    fragility: FragilityReport
    regime: RegimeMapping
    signal_conflicts: list[SignalConflict]
    hypotheses: list[HypothesisResult]
```

---

## Gate 3: Position Decision

### Purpose

Gate 3 is the final execution gate. The user has confirmed conviction at Gate 2. Now they commit to specific position parameters via a structured decision ticket. The system validates against risk limits and archives the canonical record.

### Step-by-Step Flow

**Step 3.1: Decision Ticket Presentation**

The AI presents a structured decision ticket template pre-filled from the analysis pipeline where available:

```
── DECISION TICKET ──
Direction:    [from Gate 1/Gate 2]
Instrument:   [from L3 green-lights or user selection]
Entry Level:  [from L3 entry zone / user specified]
Stop-Loss:    [from L3 entry zone / ATR-based calculation]
Take-Profit:  [from L3 target or user specified]
Position Size: [to be determined via Kelly formula]
Risk Budget:   [% of total risk capital this consumes]
Conviction:    [from Gate 2]
Correlation:   [to existing positions — check needed]
Catalyst:      [from HVR investigation or user specified]
Max Hold:      [default 90 days unless catalyst has known date]
```

The user fills in missing fields or overrides pre-filled values.

**Step 3.2: Position Sizing**

The system computes position size using Half-Kelly with a single calibrated probability input:

```python
def compute_position_size(
    calibrated_win_probability: float,   # SINGLE input: model confidence → Platt-scaled → conviction-discounted
    avg_gain_pct: float,                 # from L3 target vs entry
    avg_loss_pct: float,                 # from L3 stop-loss vs entry
    volatility_percentile: float,        # from market data
    correlation_to_portfolio: float,     # 0-1, from external check
    portfolio_value: float,
    existing_heat_pct: float,            # total % of portfolio already at risk
) -> tuple[float, dict]:                 # (position_size_pct, diagnostics)
    """
    Single-input Kelly with conviction as discount.

    Input validation (all parameters range-checked before formula):
        - 0.0 <= calibrated_win_probability <= 1.0
        - avg_loss_pct > 0.0 (prevents division by zero)
        - avg_gain_pct > 0.0
        - -1.0 <= correlation_to_portfolio <= 1.0
        - 0.0 <= volatility_percentile <= 1.0
        - 0.0 <= existing_heat_pct <= 1.0
        - portfolio_value > 0

    Kelly formula (SINGLE probability input):
        K% = W - (1 - W) / R
        where W = calibrated_win_probability, R = avg_gain / avg_loss

    Half-Kelly: f* = K% / 2

    Adjustments:
        volatility_adj = 1.0 - (volatility_percentile - 0.5)  # center around 1.0
        correlation_adj = 1.0 - correlation_to_portfolio * 0.5
        heat_adj = max(0.0, min(1.0, (0.25 - existing_heat_pct) / 0.25))  # clamped, never negative

    final_pct = f* * volatility_adj * correlation_adj * heat_adj

    Hard caps applied after:
        single_position_max = 0.25   # 25% of portfolio
        sector_max = 0.40             # 40% sector concentration
        direction_max = 0.80          # 80% total long or short
    """
```

**Calibrated Win Probability (single input)**:

The Kelly formula uses exactly ONE probability input: `calibrated_win_probability`. This is computed as:

```
calibrated_win_probability = raw_model_confidence → Platt-scaled → conviction-discounted
```

Where:
1. `raw_model_confidence` = the model's statistical win probability (from resonance DSR or ensemble)
2. Platt scaling calibrates this against historical outcomes (corrects known overconfidence at 0.75-0.85 range)
3. User conviction acts as a **DISCOUNT only**: `calibrated = platt_scaled * min(1.0, user_conviction / platt_scaled)`

The user's conviction **cannot increase** the probability above the Platt-scaled model estimate — it can only reduce it. If the user says "I'm only 60% confident" but the model says 0.81, the calibrated probability = 0.81 * (0.6 / 0.81) = 0.60. If the user says "I'm 95% confident," the min(1.0, 0.95/0.81) = 1.0, so calibrated stays at 0.81.

**Why not two separate inputs?** Feeding both `conviction_score` and `win_probability` into the formula double-counts the same thing (belief in the direction) from two angles. The single-input approach treats conviction as a calibration adjustment on the statistical estimate, not as a separate betting factor.

The AI presents the computation transparently:

```
── POSITION SIZE COMPUTATION ──
Model win probability:   0.81 (raw)
Platt-scaled:            0.77 (historical calibration)
Conviction discount:     ×0.78 (user 0.60 / platt 0.77)
Calibrated probability:  0.60 (single Kelly input)
Kelly fraction (full):   K% = 0.60 - (1 - 0.60) / 2.0 = 0.400 → 40.0%
Kelly fraction (half):   f* = 20.0%
Volatility adjustment:   ×0.72 (VVIX at 85th percentile)
Correlation adjustment:  ×0.85 (correlation to SPY: 0.30)
Remaining heat budget:   ×1.00 (0% existing heat)
────────────────────────────────────
Adjusted position size: 12.2% of portfolio
Hard cap check:          12.2% < 25% max → OK

Recommended range:       8% - 15% (user adjusts within this band)
```

**Step 3.3: Stop-Loss Validation**

The system validates the stop-loss using technical-level criteria (NOT fragility scanner — fragility_scanner.py monitors macro thresholds like bank_reserves and 10Y yield, which do not produce instrument-level price zones):

```
── STOP-LOSS VALIDATION ──
Proposed: $182.50 (3.2% below entry)
Current Price: $188.60
20-day ATR: $4.15

CHECK 1 (not too tight): Stop distance ($6.10) > ATR × 2 ($8.30)? → FAIL
  → Stop is too close to current price. Min distance: $8.30.
  → Suggestion: $180.30 or lower.

CHECK 2 (not too loose): Max loss ($6.10 × position_size) < risk_budget? → OK
  → Max loss: $1,220 vs risk budget: $2,500

CHECK 3 (meaningful level): Is stop at a recent support/resistance?
  → $182.50 is near the 20-day low support at $182.00. Acceptable.
  → WARNING: Arbitrary round numbers (e.g., $180.00) without technical basis
    should be rejected. Justify the level.
── END ──
```

**Three validation criteria**:

| Criterion | Check | Rationale |
|-----------|-------|-----------|
| Not too tight | Stop distance > ATR(20) × 2 from current price | Prevents stop-losses that get triggered by normal noise. ATR × 2 is a standard volatility-based minimum distance. |
| Not too loose | (Entry - Stop) × PositionSize ≤ RiskBudget | Prevents stops so far away that a hit would exceed the max acceptable loss. Risk budget is defined as position size × max loss tolerance (default 2% of portfolio). |
| Meaningful level | Stop is at a recent support/resistance (S/R) level identified by L3 technical analysis | Prevents arbitrary round-number stops. If L3 identifies support at $182.00 and resistance at $195.00, the stop must be near one of these levels, not a random number. |

If any check fails, the AI flags it and suggests an alternative level. The user can override with a written justification, which is recorded in `stop_loss_rationale`.

**Step 3.4: Correlation Overlay**

For users with existing positions (from portfolio data), the AI checks correlation:

```
── POSITION CORRELATION ──
New position:          EUR/USD long
Existing positions:    (none / or list with correlation coefficients)
Net directional exposure after: Long 14.5% portfolio
── END ──
```

If the new position is highly correlated (>0.7) with an existing position, the AI flags it: "This position is 0.82 correlated with your existing SPY long. Combined exposure to US equity factor = 24.5%. Consider if this is intentional."

**Step 3.5: Pre-Trade Checklist**

Automated checklist run before Gate 3 completes:

| Check | Source | Pass Condition |
|-------|--------|----------------|
| Kill criteria have monitoring hooks | `kill_monitor.py` | All criteria have `data_source` set |
| Stop-loss not too tight | ATR(20) calculation | stop_distance > ATR × 2 from current price |
| Stop-loss not too loose | risk budget check | (entry - stop) × position_size ≤ risk_budget |
| Stop-loss at meaningful level | L3 technical analysis | stop is near identified support/resistance, not arbitrary round number |
| Position size within limits | internal check | ≤25% single, ≤40% sector, ≤80% direction |
| No conflicting open positions | portfolio check | No opposite-direction position on same instrument |
| Entry level within current market range | market data check | market data timestamp < 300s stale AND \|entry - current_price\| / current_price < 5% |
| Decision ticket fields complete | schema validation | All mandatory fields non-null |

Any failing check blocks completion. The user must resolve each before the ticket is accepted.

**Step 3.6: Gate 3 Output -- DecisionTicket**

### DecisionTicket Dataclass

```python
@dataclass
class PositionSizingDiagnostics:
    raw_model_confidence: float      # from resonance DSR or ensemble
    platt_scaled_probability: float  # after historical calibration
    conviction_discount: float       # user conviction / platt_scaled, capped at 1.0
    calibrated_win_probability: float  # SINGLE Kelly input
    kelly_full: float               # raw Kelly fraction
    kelly_half: float               # half-Kelly
    volatility_adjustment: float     # multiplier from vol percentile
    correlation_adjustment: float    # multiplier from portfolio correlation
    heat_adjustment: float           # multiplier from existing risk budget
    final_pct: float                 # after all adjustments
    hard_cap_applied: bool           # whether a cap was binding
    cap_type: str                    # "single" | "sector" | "direction" | "none"


@dataclass
class ChecklistResult:
    item: str
    passed: bool
    detail: str


@dataclass
class DecisionTicket:
    # Mandatory fields
    ticket_id: str
    session_id: str
    direction: str                  # "long" | "short"
    instrument: str                 # ticker or forex pair
    position_size_pct: float        # % of portfolio
    position_size_absolute: float   # in account currency
    entry_level: float              # limit price or current market
    entry_type: str                 # "limit" | "market" | "stop_limit"
    stop_loss: float
    stop_loss_rationale: str        # "technical" | "volatility" | "time" | "structure"
    take_profit_1: float | None     # partial exit (optional)
    take_profit_1_pct: float        # % of position to sell at TP1
    take_profit_2: float | None     # full exit
    risk_budget_consumed_bp: float  # basis points of portfolio at risk

    # Conviction & sizing
    conviction_score: float         # from Gate 2
    sizing_diagnostics: PositionSizingDiagnostics

    # Risk
    correlation_to_portfolio: float
    existing_heat_pct: float        # existing % of portfolio at risk
    kill_criteria: list[str]        # criteria IDs from kill_monitor
    acknowledged_risks: list[str]

    # Timing
    catalyst_description: str       # what event makes this thesis play out?
    catalyst_date_estimate: str | None  # ISO date or None
    max_hold_days: int              # exit if catalyst doesn't materialize by then

    # Approval
    pre_trade_checks: list[ChecklistResult]
    override_reason: str            # if any check was overridden

    # Archive
    created_at: str                 # ISO timestamp
    archived: bool = False
```

### Gate 3 Module Interface

```python
# pipeline/gate3_interaction.py

async def run_gate3(
    conviction: ConvictionRecord,       # from Gate 2
    pipeline_output: PipelineOutput,     # stages 4-10 results
    portfolio_snapshot: PortfolioSnapshot,  # existing positions
    market_data: dict,                   # current price data for validation
    session_id: str,
    io_handler: callable,
    status_handler: callable,
) -> DecisionTicket:
    """Run the Gate 3 position decision conversation loop."""
    ...


@dataclass
class PortfolioSnapshot:
    positions: list[dict]           # {"ticker": str, "direction": str, "size_pct": float}
    total_equity: float
    existing_heat_pct: float        # total % at risk across all positions
    sector_exposures: dict[str, float]
    directional_exposure: dict[str, float]  # {"long": 0.45, "short": 0.10}
```

---

## Security Hardening (from `.claude/audits/gate23-plan-security.md`)

### SH-1: Input Validation in `compute_position_size()`

All 7 parameters are range-checked BEFORE the Kelly formula executes. See Step 3.2 for the validation block. Key protections:
- `avg_loss_pct > 0.0` prevents division by zero
- `existing_heat_pct` clamped to `[0.0, 1.0]` with `max(0.0, min(...))` to prevent negative position sizes
- All probability inputs bounded to `[0.0, 1.0]`
- Validation failures raise `ValueError` with actionable messages — Gate 3 presents these to the user, does not silently clamp

### SH-2: File Permissions (Sensitive Financial Data)

All files under `data/archive/` and `data/sessions/` must be written with `0o600` permissions (owner read/write only):
```python
tmp.write_text(json_data)
os.chmod(tmp, 0o600)  # before atomic rename
tmp.replace(filepath)
```
Applies to `archivist.py`, `session.py`, and `gate_archiver.py`.

### SH-3: FTS5 Index Exclusion

Do NOT index `position_size_absolute`, `stop_loss`, or `entry_level` in FTS5. These are quantitative values, not searchable text. Index only: `ticket_id`, `session_id`, `direction`, `instrument`, `catalyst_description`.

### SH-4: Market Data Staleness Check

The `market_data` dict passed to `run_gate3()` must include a `timestamp` field. The pre-trade checklist verifies `now - timestamp < 300` (5 minutes) before using prices. Stale data fails the entry-level check with a clear message.

### SH-5: ELITE Shadow Content Sanitization

All shadow opinion text must pass through `_escape_markdown()` from `input_guard.py` before display. Shadow opinions are wrapped in `<!-- SHADOW_OPINION_START/END -->` markers in the Markdown archive.

### SH-6: ELITE Shadow Awakening Cap

Maximum 5 ELITE shadows surfaced per Gate 2 session. If >50% of registered domains match, log a warning (anomalous keyword-bombing). Applied in Step 2.3.

### SH-7: Session Resume Integrity

On checkpoint resume (`--mode gate2`/`--mode gate3`), display the loaded checkpoint data to the user and require confirmation before proceeding: "Resuming Gate 2 with direction: X. Proceed? (y/n)"

---

## New Modules Required

| Module | Lines (est.) | Purpose |
|--------|:---:|---------|
| `pipeline/gate2_interaction.py` | ~350 | Conversation loop, conviction-before-evidence flow, debiasing mechanisms, devil's advocate, ELITE shadow integration (cap=5, sanitized), kill criteria review |
| `pipeline/gate3_interaction.py` | ~350 | Decision ticket creation, position sizing (single-input Kelly), ATR-based stop-loss validation, correlation check, pre-trade checklist, archival |
| `pipeline/position_sizing.py` | ~120 | Kelly computation (single probability input, input validation, Platt scaling, conviction discount), volatility/correlation/heat adjustments, hard cap enforcement |
| `pipeline/pre_trade_checklist.py` | ~100 | Automated checklist runner (ATR-based stop validation, market data staleness check, schema validation) |
| `pipeline/pipeline_output.py` | ~40 | PipelineOutput dataclass (bundle all Stage 4-10 results) |

Total new code: ~960 lines across 5 modules. All are at or below soft thresholds.

Existing modules that need modification:
| Module | Change | Why |
|--------|--------|-----|
| `pipeline/orchestration.py` | Add `_run_gates_2_3()` and wire into `run_full()` | Insert gates after stages 4-10 |
| `app.py` | Add `--mode gate2` and `--mode gate3` CLI modes | Resume from gate checkpoints |
| `storage/session.py` | Already has `gate2`/`gate3` fields -- update serialization for new data types | Minimal change |

---

## Integration with Existing Pipeline

### `app.py` Changes

```python
# New CLI mode
if args.mode == "full":
    return asyncio.run(run_full(config, ...))
elif args.mode == "gate2":
    return asyncio.run(run_gate2_resume(config, args.session_id, ...))
elif args.mode == "gate3":
    return asyncio.run(run_gate3_resume(config, args.session_id, ...))
```

### `orchestration.py` -- Updated `run_full()`

```python
async def run_full(config, mock, verbose, shadow_count, session_mode) -> int:
    state = await _run_stages_0_3(config, mock, verbose, shadow_count)

    # Gate 1: direction
    gate1_session = await run_gate1(...)
    save_gate1_checkpoint(gate1_session)

    # Stages 4-10: full analysis
    exit_code = await _run_stages_4_10(config, state, mock, verbose)

    # Bundle pipeline output
    pipeline_output = _bundle_pipeline_output(state)

    # Gate 2: signal confirmation
    gate2_record = await run_gate2(
        gate1_session, pipeline_output, elite_registry,
        session_id, io_handler, status_handler,
    )
    save_gate2_checkpoint(gate2_record)

    if gate2_record.gate2_outcome != "CONTINUE":
        archive_parked_session(...)
        return 0

    # Gate 3: position decision
    portfolio = _load_portfolio_snapshot(config)
    decision_ticket = await run_gate3(
        gate2_record, pipeline_output, portfolio, market_data,
        session_id, io_handler, status_handler,
    )
    save_gate3_checkpoint(decision_ticket)

    # Archive decision ticket to FTS5 + JSON
    archive_decision_ticket(decision_ticket)

    return 0
```

### Data Flow Between Gates

```
Gate 1 → Gate 2:
  Gate1Session.selected_direction → ConvictionRecord.selected_direction

Gate 2 → Gate 3:
  ConvictionRecord.conviction_level → DecisionTicket.conviction_score
  ConvictionRecord.kill_criteria   → DecisionTicket.kill_criteria
  ConvictionRecord.acknowledged_risks → DecisionTicket.acknowledged_risks

Gate 3 → Archive:
  DecisionTicket → decision.json (atomic write)
  DecisionTicket → FTS5 index (archivist.index_document)
```

### Session Checkpoint Flow

The existing `SessionManager`/`SessionState`/`GateCheckpoint` classes already support 3 gates. Gate 2 and 3 populate the `gate2` and `gate3` fields:

```
SessionState(
    session_id="gate1-20260518-0930",
    mode="full",
    current_gate=3,
    gate1=GateCheckpoint(1, True, data={selected_direction: "...", ...}),
    gate2=GateCheckpoint(2, True, data={conviction_level: "STRONG", ...}),
    gate3=GateCheckpoint(3, True, data={ticket_id: "...", position_size_pct: 14.5, ...}),
)
```

This enables resumption: `--mode gate2 --session-id gate1-20260518-0930` loads the Gate 1 checkpoint and continues from Gate 2.

---

## Implementation Phases

### Phase 1: Data Structures + Math (no interaction)
1. Create `pipeline/pipeline_output.py` — PipelineOutput dataclass
2. Create `pipeline/position_sizing.py` — Kelly formula (single probability input, Platt scaling, conviction discount, full input validation)
3. Create `pipeline/pre_trade_checklist.py` — validation checks (ATR-based, market data staleness)
4. Apply `os.chmod(0o600)` to `archivist.py` and `session.py` file writes (SH-2)
5. Tests: 12+ (unit tests for Kelly math, checklist validation, input validation edge cases)

### Phase 2: Gate 2 Conversation Loop
1. Create `pipeline/gate2_interaction.py`
2. Wire ELITE registry integration
3. Implement evidence display (formatting from existing objects)
4. Implement conviction calibration conversation
5. Implement kill criteria review
6. Tests: 15+ (mock IO handler, all 3 outcomes, turn limit, shadow surfacing)

### Phase 3: Gate 3 Decision Ticket
1. Create `pipeline/gate3_interaction.py`
2. Implement ticket template pre-fill
3. Implement ATR-based stop-loss validation (not tight / not loose / meaningful level)
4. Implement correlation overlay
5. Implement pre-trade checklist execution (with market data staleness check)
6. Tests: 15+ (ticket validation, checklist, sizing integration)

### Phase 4: Integration
1. Add `_run_gates_2_3()` to `orchestration.py`
2. Wire into `run_full()` flow
3. Add `--mode gate2` and `--mode gate3` resume modes to `app.py`
4. End-to-end tests: 8+ (full pipeline: gate1 → stages 4-10 → gate2 → gate3 → archive)
5. PICA audit on all new modules
6. Update CLAUDE.md pipeline diagram
