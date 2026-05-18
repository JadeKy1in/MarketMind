# Red Team Architecture Audit: Gate 2/3 Plan

**Auditor**: Red Team Architecture/Integration
**Date**: 2026-05-18
**Plan audited**: `.claude/plans/gate23-architecture.md`
**Status**: NEEDS REVISION — 3 blockers, 4 warnings

---

## Summary Verdict

The plan correctly identifies the pipeline insertion point and has well-designed data types. However, **3 blockers** prevent implementation as-written: (1) PipelineOutput cannot be built from the current state dict, (2) Gate 2 lacks a conversation state machine, and (3) module line estimates are wrong about soft-threshold compliance. The plan also omits EliteRegistry population and market data sourcing.

---

## Finding 1: Pipeline Insertion Point — PARTIALLY CORRECT

**Plan says**:
```
Stage 0-3 → Gate 1 → Stages 4-10 → Gate 2 → Gate 3 → Archive
```

**Actual code flow** (`orchestration.py:39-81`):
```python
run_full():
    state = run_pre_gate1(...)       # Stages 0-3
    gate1_session = run_gate1(...)    # Gate 1 interaction
    return run_post_gate1(...)        # Stages 4-10
```

The structural insertion point (after stages 4-10, before return) is **correct**. However:

### 1a. Function naming mismatch
The plan uses aspirational names that don't exist in the codebase:
| Plan name | Actual name |
|-----------|-------------|
| `_run_stages_0_3()` | `run_pre_gate1()` |
| `_run_stages_4_10()` | `run_post_gate1()` |
| `_bundle_pipeline_output(state)` | Does not exist |

**Severity**: Low. Names can change during implementation. But the plan should reference actual function names to avoid confusion.

### 1b. BLOCKER: PipelineOutput cannot be built from state dict

The plan calls `_bundle_pipeline_output(state)` to create a `PipelineOutput` for Gate 2. **This won't work.** Looking at `run_post_gate1()` (lines 14-196), the intermediate results (`l1_result`, `l2_result`, `l3_result`, `red_team_report`, `resonance`) are local variables that get archived to JSON but are **never stored in the state dict**. The state dict contains:
- `tracker`, `archivist`, `session_date`, `shadow_db`, `mother`
- `news_items`, `triage_results`, `hypotheses`, `actionable`

None of the pipeline stage outputs are in state. `_bundle_pipeline_output(state)` would return an empty PipelineOutput.

**Fix required**: Either (a) refactor `run_post_gate1()` to return a `PipelineOutput` instead of `int`, or (b) store all intermediate results in the state dict during execution. Option (a) is cleaner — change the return signature of `run_post_gate1()` from `-> int` to `-> tuple[int, PipelineOutput]`.

### 1c. PipelineOutput dataclass is missing a field

The plan's `PipelineOutput` lists: l1, l2, l3, red_team, resonance, fragility, regime, signal_conflicts, hypotheses. It's missing `decision: DecisionOutput` (produced by `generate_decision()` at stage 9). The decision output contains `DecisionCard` objects with ticker, entry zones, stop-loss, and target prices — all needed by Gate 3's decision ticket pre-fill (Step 3.1).

**Fix**: Add `decision: DecisionOutput` to PipelineOutput.

---

## Finding 2: SessionState gate2/gate3 Fields — CORRECT

**SessionState** (`storage/session.py:23-31`):
```python
class SessionState:
    gate1: GateCheckpoint | None = None
    gate2: GateCheckpoint | None = None
    gate3: GateCheckpoint | None = None
```

The fields exist and serialization (`_serialize_state`, `_deserialize_state`) already handles all three gates. The plan's usage in the session checkpoint flow (lines 519-533) is correct.

### 2a. WARNING: Complex datatypes in GateCheckpoint.data

`GateCheckpoint.data` is `dict[str, Any]` — values must be JSON-serializable. The plan stores:
- Gate 2: `ConvictionRecord` fields including `list[KillCriterion]` (nested dataclass)
- Gate 3: `DecisionTicket` fields including `PositionSizingDiagnostics` (nested dataclass)

These nested dataclasses need `asdict()` conversion or a custom `to_dict()` method before storage. The plan doesn't address this.

**Fix**: Add serialization note to implementation tasks, or use `dataclasses.asdict()` with a `default=str` fallback.

---

## Finding 3: run_full() Flow — MOSTLY CORRECT

The plan's proposed `run_full()` flow (lines 462-501) matches the actual `orchestration.py` structure. The plan correctly adds:
- Gate 2 after stages 4-10
- Gate 3 after Gate 2
- Branching on `gate2_outcome != "CONTINUE"`
- Archive at the end

### 3a. WARNING: session_mode parameter

The plan adds `session_mode: str = "full"` to `run_full()`. This parameter **already exists** in the current signature (`orchestration.py:40`). No change needed — the plan is accidentally correct here.

### 3b. WARNING: Checkpoint saving responsibility

The plan introduces `save_gate1_checkpoint()`, `save_gate2_checkpoint()`, `save_gate3_checkpoint()` as standalone functions in `run_full()`. Currently, checkpoint saving happens inside `run_full()` and `run_gate1_mode()` with inline `SessionManager().save(...)` calls. The plan should clarify:
- Does `run_gate2()` save its own checkpoint (like `run_gate1()` does), or does the caller save it?
- Gate 1 currently saves its checkpoint inside the gate function (lines 384-407 of gate1_interaction.py) AND the caller (lines 67-76 of orchestration.py) — this double-save pattern should NOT be replicated.

**Recommendation**: Gate modules should own their checkpointing (like Gate 1 does). Remove the duplicate save from orchestration.py.

### 3c. WARNING: ELITE registry not populated

The plan passes `elite_registry` to `run_gate2()` but never shows how it gets populated. Looking at the actual code:
- `run_post_gate1()` calls `mother.orchestrate_daily_cycle()` which runs all shadows
- But `mother.orchestrate_daily_cycle()` does NOT call `elite_registry.register_shadow_analysis()`
- The `EliteRegistry` has 6 files referencing it, but the main pipeline orchestration never populates it

**Fix**: After shadow orchestration completes, iterate ELITE-tier shadows and call `elite_registry.register_shadow_analysis()` for each one. This is a missing integration step between the shadow ecosystem and Gate 2.

---

## Finding 4: Module Size — SOFT THRESHOLD EXCEEDED

The plan claims (line 437): *"All are at or below soft thresholds."* **This is false.**

Per root `CLAUDE.md` §3.1, the soft threshold for Python modules is **250 lines**.

| Module | Plan Estimate | vs Soft (250) | vs Hard (500) |
|--------|:---:|:---:|:---:|
| `gate2_interaction.py` | ~350 | **+100 (40% over)** | Under |
| `gate3_interaction.py` | ~350 | **+100 (40% over)** | Under |
| `position_sizing.py` | ~120 | Under | Under |
| `pre_trade_checklist.py` | ~100 | Under | Under |
| `pipeline_output.py` | ~40 | Under | Under |

### 4a. BLOCKER: Gate 2 SRP investigation

At 350 lines, the soft threshold is triggered — the 4 questions from §3.1 must be answered:

1. **Does the module do more than one thing?** YES. Gate 2 has 7+ concerns in one module:
   - Multi-layer evidence formatting (Step 2.1)
   - ELITE shadow integration (Step 2.2)
   - Shadow consensus tally (Step 2.3)
   - Red Team survivors display (Step 2.4)
   - Signal conflict resolution (Step 2.5)
   - Historical regime display (Step 2.6)
   - Conviction calibration conversation (Step 2.7)
   - Kill criteria review (Step 2.8)
   - Outcome routing (Step 2.9)

2. **Does it export more than 10 public functions?** Likely, given 9 sub-steps each needing display + logic functions.

3. **Do any functions have >4 parameters?** `run_gate2()` already has 7 parameters.

4. **Cyclomatic complexity?** Unknown until written, but the conversation branching (CONTINUE/MODIFY/PAUSE + user interrupts) suggests >10.

**SRP violation is confirmed.** The plan must either:
- Split into `gate2_display.py` (~180 lines, formatting/display only) + `gate2_conviction.py` (~200 lines, conversation loop), OR
- Provide a written justification for keeping 350 lines (e.g., "conversation state machine is a single responsibility — display sub-steps are sequential function calls, not distinct concerns").

### 4b. BLOCKER: Gate 3 SRP investigation

Similarly, Gate 3 has 6+ concerns:
- Decision ticket pre-fill (Step 3.1)
- Position sizing computation (Step 3.2)
- Stop-loss validation (Step 3.3)
- Correlation overlay (Step 3.4)
- Pre-trade checklist (Step 3.5)
- Final archival (Step 3.6)

**Recommendation**: `position_sizing.py` and `pre_trade_checklist.py` are already correctly extracted. But `gate3_interaction.py` still bundles display, conversation, and validation orchestration. Consider extracting `gate3_display.py` from the conversation logic.

---

## Finding 5: Gate 2 vs Gate 1 Pattern Compliance — BLOCKER

Gate 1 is a mature, proven conversation pattern. The plan's Gate 2 design does not follow it.

### What Gate 1 has that Gate 2 plan lacks:

| Feature | Gate 1 | Gate 2 Plan |
|---------|--------|-------------|
| **State machine** | 10 states: START → USER_AGENDA_OPENING → PRESENTING_CARDS → AWAITING_USER_CHOICE → EXPLORING_DIRECTION / COMPARING_DIRECTIONS / SCOPE_DISAMBIGUATION / ANALYZING_NEW_DIRECTION / CONFIRMING | Describes sequential display, no state machine |
| **Intent parsing** | Regex patterns for 8 user intents (select, compare, confirm, detail, pivot, parking_lot, new_direction, unknown) | No intent parsing described |
| **GateArchiver** | Full turn-by-turn archival via `GateArchiver.log_turn()` and `archiver.log_decision()` | Not mentioned |
| **Input guard** | `sanitize_for_llm_prompt()` on every user input | Not mentioned |
| **Turn limit** | 50 turns, warning at 40 | Not mentioned |
| **KeyboardInterrupt** | Saves partial checkpoint on Ctrl+C | Not mentioned |
| **Parking lot** | User can defer topics for next session | Not mentioned (though Gate 2 has PAUSE outcome) |
| **No LLM calls** | Display-only, human interaction | Same — correct |

### Why this matters

The plan describes Gate 2 as a linear presentation ("show evidence → show shadows → show Red Team → show conflicts → ask conviction"). But real human conversation is non-linear. The user will:
- Ask "why does Gold shadow dissent?" (mid-presentation jump to shadow detail)
- Challenge a Red Team finding (re-triggers review before conviction question)
- Change their mind about conviction after seeing kill criteria (backtracking)
- Say "wait, compare these two Red Team items" (comparison intent)

A sequential presentation breaks on the first user deviation. The Gate 1 state machine handles this gracefully — the user can type anything at any prompt and the intent parser routes correctly.

**Fix required**: Model Gate 2 as a state machine with at minimum:
- `PRESENTING_EVIDENCE` → `PRESENTING_SHADOWS` → `PRESENTING_RED_TEAM` → `PRESENTING_CONFLICTS` → `AWAITING_CONVICTION`
- Transitions: user can jump to `DETAIL_QUERY` (on any layer), `CHALLENGE_RED_TEAM`, `SHADOW_DETAIL`, `MODIFY_DIRECTION` from any state
- Add intent regex patterns for Gate 2-specific actions: "why does X", "challenge Y", "explain Z", "modify", "pause"

---

## Finding 6: Import DAG — MOSTLY CORRECT

### Forward dependencies (correct):
```
pipeline_output.py          (data, no imports from pipeline)
position_sizing.py          (pure math, no imports from pipeline)
pre_trade_checklist.py      (imports fragility_scanner, decision — data modules)
gate2_interaction.py        → pipeline_output, gate1_interaction (Gate1Session), elite_participation
gate3_interaction.py        → pipeline_output, position_sizing, pre_trade_checklist
orchestration.py            → gate2_interaction, gate3_interaction
```

### 6a. WARNING: Sibling import for ConvictionRecord

The plan defines `ConvictionRecord` inside `gate2_interaction.py` but `gate3_interaction.py` needs to import it. This creates a sibling import (`gate3_interaction` → `gate2_interaction`).

Per root CLAUDE.md extraction rules: sibling imports are restricted. While this is a forward-direction dependency (gate2 runs before gate3), the data type should live in a shared location.

**Fix**: Move `ConvictionRecord` into `pipeline/pipeline_output.py` alongside `PipelineOutput`. Both gate2 and gate3 import from the data module, not from each other. Same consideration for `DecisionTicket` — it could also live in `pipeline_output.py` since the data module is the natural home for cross-gate types.

### 6b. No back-imports detected

No module imports from the glue layer (`orchestration.py`, `app.py`). Dependency flow is correct: glue → gates → data/utilities.

---

## Finding 7: Additional Gaps

### 7a. Market data sourcing for Gate 3

Gate 3's pre-trade checklist requires:
- "Entry level within current market range" → needs live price data
- "No conflicting open positions" → needs portfolio data
- Stop-loss validation against fragility zone → needs fragility scanner output for the specific instrument

The current pipeline has no live market data feed. Market price references come from news analysis text, not structured price feeds. `PortfolioSnapshot` is defined but no `_load_portfolio_snapshot()` function exists.

**Recommendation**: Gate 3 MVP can use hardcoded market data in mock mode and flag missing data in production. Defer live market data to Phase I/II.

### 7b. kill_monitor.py integration gap

The plan references `kill_monitor.py` for kill criteria display (Step 2.8) but doesn't show how kill criteria flow from the analysis pipeline into Gate 2. Currently:
- `KillMonitor` class exists in `kill_monitor.py`
- `KillCriterion` dataclass has `criterion_id`, `description`, `observable`, `data_source`, `threshold_value`, `trigger_condition`
- But the main pipeline never instantiates or runs `KillMonitor`

**Fix**: Add kill criteria extraction to `run_post_gate1()` or run it as a separate step before Gate 2. The criteria become part of `PipelineOutput`.

### 7c. Decision cards are an input, not just archive

The plan's `PipelineOutput` omits `DecisionOutput` (the decision cards from stage 9). These contain pre-computed entry zones, stop-losses, targets, and ticker suggestions — exactly what Gate 3's decision ticket pre-fills. Without this, Gate 3 starts from scratch.

**Fix**: Add `decision: DecisionOutput` to `PipelineOutput`.

### 7d. No test count verification

The plan estimates 12+15+15+8 = 50 tests. For comparison:
- Gate 1 has 38 tests (`test_gate1_interaction.py` + `test_hypothesis_card.py`)
- Gate 2/3 are more complex (more states, more data types, position sizing math)
- 50 tests for ~960 lines of code = ~1 test per 19 lines — reasonable but verify during implementation

---

## Recommendations

### Blockers (must fix before implementation):

1. **PipelineOutput construction**: `run_post_gate1()` must return pipeline results, not just exit code. Change return to `tuple[int, PipelineOutput]`.

2. **Gate 2 state machine**: Model Gate 2 as a state machine with intent parsing, archiver, input guard, and turn limits — following Gate 1's proven pattern. The plan's sequential-presentation model won't survive real conversation.

3. **Module size soft threshold**: Acknowledge that gate2 and gate3 both exceed the 250-line soft threshold. Either split (display module + conversation module) or provide SRP justification per root CLAUDE.md §3.1.

### Warnings (should fix before implementation):

4. **ConvictionRecord location**: Move to `pipeline_output.py` to avoid sibling import from gate3 → gate2.

5. **PipelineOutput missing DecisionOutput**: Add `decision: DecisionOutput` field.

6. **EliteRegistry population**: Specify where `register_shadow_analysis()` is called (in shadow orchestration step, post `mother.orchestrate_daily_cycle()`).

7. **Gate 2/Gate 3 resumption modes**: `--mode gate2` and `--mode gate3` CLI flags are listed in app.py changes but the resumption logic (loading state, restoring session, continuing from checkpoint) is not described.

### Suggestions (non-blocking improvements):

8. Move `DecisionTicket` and `PortfolioSnapshot` into `pipeline_output.py` as well — keeps all shared data types in one place.

9. Add a `Gate2State` enum paralleling Gate 1's state strings: `PRESENTING_EVIDENCE`, `PRESENTING_SHADOWS`, `PRESENTING_RED_TEAM`, `PRESENTING_CONFLICTS`, `AWAITING_CONVICTION`, `KILL_CRITERIA_REVIEW`, `OUTCOME`.

10. Rename plan's `_run_stages_0_3()` → `run_pre_gate1()` and `_run_stages_4_10()` → `run_post_gate1()` to match actual code.

---

## Verification Checklist

- [x] Read `app.py` — confirmed CLI mode dispatch, no gate2/gate3 modes exist
- [x] Read `orchestration.py` — confirmed `run_full()` flow, pre_gate1/post_gate1 split
- [x] Read `session.py` — confirmed gate2/gate3 fields, serialization, atomic writes
- [x] Read `gate1_interaction.py` (full) — confirmed state machine, archiver, input_guard, turn_limit pattern
- [x] Read `post_gate1.py` (full) — confirmed intermediate results are NOT stored in state dict
- [x] Read `elite_participation.py` (full) — confirmed EliteRegistry API, DOMAIN_KEYWORDS, session reset
- [x] Read `fragility_scanner.py` (header) — confirmed FragilityReport dataclass
- [x] Read `regime_mapper.py` (header) — confirmed RegimeMatch dataclass
- [x] Read `decision.py` (header) — confirmed DecisionCard, SignalConflict, DecisionOutput, `_detect_signal_conflicts()`
- [x] Read `kill_monitor.py` — confirmed KillCriterion and KillMonitorReport exist
- [x] Checked EliteRegistry usage across codebase — confirmed never populated in main pipeline
