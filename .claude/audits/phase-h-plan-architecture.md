# Phase H Architecture Plan — Red Team Architecture/Integration Audit

**Audit type**: Architecture + Integration
**Date**: 2026-05-18 10:13 UTC
**Plan under review**: `.claude/plans/phase-h-comprehensive-architecture.md`
**Codebase baseline**: `investigation_loop.py` (918 lines), `app.py` (464 lines), `verification_chain.py` (684 lines), `token_budget.py` (96 lines), `decision.py` (226 lines)

---

## Finding 1: Pipeline Insertion Points — Stage Numbering Mismatch and Missing Hook for cross_border_analyzer (MEDIUM)

**Plan claim**: Modules insert at stage_2b internal, stage_7b new, stage_4 replacement.

**Reality**: The plan uses a pipeline numbering scheme that does NOT match `app.py:run_daily()`. The actual stage mapping:

| Plan Stage | App.py Stage | What Runs |
|:---:|:---:|------|
| stage_2b | Stage 3 (line 146-168) | `run_investigation_loop()` |
| stage_3 | Stage 4 (line 171-195) | `analyze_layer1()` |
| stage_4 | Stage 5 (line 198-228) | L2+L3 parallel |
| stage_7 | Stage 8 (line 268-283) | `evaluate_resonance()` |
| stage_7b | **gap** (lines 283-286) | NEW — between resonance and decision |
| stage_8 | Stage 9 (line 286-307) | `generate_decision()` |

**Insertion point analysis**:

1. **stage_2b internal (causal + flow decomposition)**: EXISTS at `investigation_loop.py:846-901` (the per-hypothesis loop body). Feasible insertion point, but see Finding 4 for the asyncio.gather problem.

2. **stage_7b (fragility_scanner)**: EXISTS at `app.py:283-286` — the gap between resonance (line 283) and decision (line 286). The `hypotheses` variable is still in scope (defined line 142). The insertion is clean.

3. **stage_4 replacement (regime_mapper)**: FALSE PREMISE. The plan says "替换 verification_chain.py Layer 4" — this is NOT a pipeline stage replacement. It replaces the internal function `verify_claim_historical()` at `verification_chain.py:344-419`. This is a function-level replacement inside the HVR verification, not a pipeline stage insertion. The plan's diagram in section 3 confusingly labels this as happening at "stage_4", but stage_4 in the plan's numbering is L2+L3 (unchanged). The actual insertion is INSIDE stage_2b's verification chain. **Location is correct, naming is wrong.**

4. **cross_border_analyzer**: NO INSERTION POINT DEFINED. The plan says "optional enhancement, data unavailable → silent skip" but never specifies WHERE in the pipeline it runs. Is it during investigation? During decision synthesis? During archive? The plan mentions a `gateway/cross_border.py` data gateway but no pipeline hook.

**Mitigation**: 
- Adopt `app.py:run_daily()` line numbers as the canonical stage reference. Rename all plan stages to match the code.
- Define the cross_border_analyzer pipeline hook point explicitly. Recommend running it as an optional stage between resonance and fragility (stage 7.5), feeding enriched market context to both fragility_scanner and decision.

---

## Finding 2: Data Flow Integrity — HypothesisResult Does NOT Flow to Downstream Stages (CRITICAL)

**Plan claim (section 4)**: "New modules add fields to HypothesisResult. These flow through L1 → L2 → L3 → Red Team → Resonance → Decision."

**Reality**: HypothesisResult is NEVER passed to any downstream stage. Verified against actual function signatures:

| Stage | Function | Actual Parameters | Source (app.py) |
|-------|----------|-------------------|-----------------|
| L1 | `analyze_layer1()` | `signals: list[FlashSignal], news_items: list` | Line 176 |
| L2 | `analyze_layer2()` | `l1_result: Layer1Result` | Line 204 |
| L3 | `analyze_layer3()` | `tickers: list, config: dict` | Line 205 |
| Red Team | `run_red_team()` | `l1_raw, l2_raw, ticker_candidates` | Line 249-253 |
| Resonance | `evaluate_resonance()` | `signal_returns, dimensions, observed_sharpe` | Line 270-273 |
| Decision | `generate_decision()` | `l1, l2, l3, red_team, resonance, shadow_votes` | Line 288-292 |

**HypothesisResult usage**: Only inside `investigation_loop.py` and in the archive serialization at `app.py:159-167` where it's manually accessed field-by-field:
```python
"hypotheses": [{"hypothesis": h.hypothesis, "confidence": h.confidence,
                "verdict": h.verdict, "bear_case": h.bear_case}
               for h in hypotheses[:50]]
```

**Implication**: Adding 11 fields to HypothesisResult has ZERO impact on L1/L2/L3/Red Team/Resonance/Decision because HypothesisResult doesn't flow to them. The plan's compatibility analysis in section 5 is analyzing a data flow that doesn't exist.

**Two sub-problems**:

2a. **The plan's integration claim is self-contradictory**: Section 5 says "Decision 接收增强后的 HypothesisResult" and claims `generate_decision()` will "just ignore" new fields. But `generate_decision()` at `decision.py:93-106` has signature:
```python
async def generate_decision(
    l1: Layer1Result, l2: Layer2Result, l3: Layer3BatchResult,
    red_team: RedTeamReport, resonance: ResonanceResult,
    shadow_votes: dict | None = None,
) -> DecisionOutput:
```
There is NO `HypothesisResult` parameter. To "receive enhanced HypothesisResult," the function signature must be changed — which the plan does NOT account for as integration work.

2b. **Serialization safety (LOW risk)**: The archive at `app.py:159-167` uses explicit field access, not `dataclasses.asdict()`. New fields with defaults won't break existing serialization. However, if the plan later adds `json.dumps(hypothesis_result)` anywhere, the `CausalDecomposition | None`, `FlowAttribution | None`, and `ScenarioTree | None` fields could cause issues since these are custom dataclasses — not JSON-serializable by default. Currently no such serialization exists.

**Mitigation**:
- Remove the false claim that HypothesisResult "flows through L1→L2→L3→Red Team→Resonance→Decision" from the plan.
- If the plan intends to connect HypothesisResult to Decision (which it should — that's the whole point of Phase H), add an explicit integration step to Phase H-3 or H-5:
  1. Add `hypotheses: list[HypothesisResult] | None = None` parameter to `generate_decision()`
  2. Pass `actionable` list from app.py line 150 to `generate_decision()`
  3. Add `_build_decision_prompt()` logic to consume causal/flow/scenario fields
  4. Update the archive serialization to include new fields
- Add a `to_dict()` method on HypothesisResult for safe JSON serialization if it ever needs to be serialized whole.

---

## Finding 3: Module Dependency DAG — flow_decomposition Has Hard Dependency on causal_decomposition (HIGH)

**Plan claim (section 3, rule 1)**: "因果分解 + 资金流分解在 HVR 循环内并行运行（asyncio.gather）"

**Plan claim (section 0, principle 4)**: "模块契约：每个新模块单一入口函数 + 明确 dataclass 输入/输出"

**Reality — dependency graph**:

```
mechanism_glossary.py  ─────────────────────────────────────┐
  (zero dependencies)                                        │ 注入到所有 prompt
                                                              ├──────────────────────
causal_decomposition.py                                      │
  inputs: HypothesisResult                                    │
  outputs: CausalDecomposition                                │
  dependencies: chat_pro (gateway)                            │
         │                                                    │
         │  HARD DEPENDENCY (plan section 2.2:                │
         │  "输入: HypothesisResult + CausalDecomposition")    │
         ▼                                                    │
flow_decomposition.py                                         │
  inputs: HypothesisResult + CausalDecomposition  ◄── CRITICAL
  outputs: FlowAttribution                                    │
  dependencies: chat_pro, causal_decomposition                │
                                                              │
regime_mapper.py                                              │
  inputs: claim text (via verify_claim_historical interface)   │
  outputs: float (via adapter) + RegimeMapping (internal)      │
  dependencies: RegimeLibrary (config data module)             │
         │                                                    │
         │  NO DEPENDENCY (different data paths)               │
         ▼                                                    │
scenario_forecaster.py                                        │
  inputs: HypothesisResult (verdict=ACTIONABLE only)           │
  outputs: ScenarioTree                                       │
  dependencies: chat_pro                                      │
                                                              │
fragility_scanner.py                                          │
  inputs: list[HypothesisResult] + market data                 │
  outputs: FragilityReport                                    │
  dependencies: fragility_thresholds.py (config data)          │
                                                              │
cross_border_analyzer.py                                      │
  inputs: TIC/BIS/FRED data                                   │
  outputs: CrossBorderFlowReport                              │
  dependencies: gateway/cross_border.py (data gateway)         │
```

**Key finding**: `flow_decomposition` explicitly requires `CausalDecomposition` as input (plan section 2.2: "输入: HypothesisResult + CausalDecomposition"). This is a **hard sequential dependency**. They CANNOT run in parallel via `asyncio.gather`. The correct execution order is:

```
causal_decomposition → flow_decomposition → HVR verification
```

**Secondary dependency concern**: `scenario_forecaster` is described as running "仅对 ACTIONABLE 判定" — but ACTIONABLE verdict is determined AFTER the HVR cycle + adversarial check + `_determine_verdict()`. So scenario_forecaster must run AFTER the full HVR loop completes, not before verdict determination. The plan's pipeline diagram in section 3 shows scenario_forecaster BEFORE Gate 1 (user confirmation) and AFTER the HVR loop — this ordering is consistent with the code. Confirmed: no issue here.

**Mitigation**:
- Remove the `asyncio.gather` claim from section 3 rule 1.
- Replace with explicit sequential ordering: `causal_result = await causal_decompose(h) → flow_result = await flow_decompose(h, causal_result) → verification = await verify_claim(...)`
- If parallel execution is desired for latency, refactor flow_decomposition to NOT depend on causal output. The plan's 5 entity classes (US_HOUSEHOLD, US_INSTITUTIONAL, etc.) and TIC/COT data sources are conceptually independent of the asset/liability decomposition.
- Document the dependency in the module specification (section 2.2).

---

## Finding 4: Async/Concurrency — asyncio.gather Conflicts with Sequential HVR Logic (HIGH)

**Plan claim (section 3, rule 1)**: "因果分解 + 资金流分解在 HVR 循环内并行运行（asyncio.gather）"

**Reality**: The HVR loop in `run_investigation_loop()` at `investigation_loop.py:846-901` is inherently sequential:

```python
for i, h in enumerate(hypotheses[:cfg.max_hypotheses]):
    gap = await _expectation_gap_check(h)        # Step 1: must complete before Step 2
    if gap < threshold: continue                  # Step 2: conditional skip
    hvr_result = await _hvr_cycle(h, ...)         # Step 3: HVR — ALSO sequential internally
    hvr_result = await _adversarial_bear_check()  # Step 4: depends on Step 3 output
    hvr_result.verdict = _determine_verdict()     # Step 5: depends on Steps 3-4
    hvr_result = await _generate_layer_narratives() # Step 6: depends on Step 5
```

Inside `_hvr_cycle()` (line 367-493), the flow is:
```python
verification = await verify_claim(claim)           # Initial verify (line 394)
# ... refinement loop with re-verification ...
```

**Where the gather fits — and where it breaks**:

The plan wants causal + flow to run "before HVR verification" inside `_hvr_cycle()`. The only available slot is before line 394 (`verify_claim`). But:

1. flow_decomposition needs CausalDecomposition output (Finding 3) → sequential, not parallel
2. `_hvr_cycle()` already has sequential logic: verify → refine → re-verify. Inserting 2 new async calls before line 394 adds latency (~2-4 seconds for 2 Pro calls) but doesn't break the sequential logic.
3. The entire per-hypothesis loop in `run_investigation_loop()` is already sequential (Steps 1-6 above). The asyncio.gather pattern could work for **different hypotheses** (parallelize across N hypotheses), but the plan proposes it INSIDE a single hypothesis's processing — which is where the dependency conflict arises.

**What WOULD work for parallelism**: After fixing the flow/causal dependency, parallelize per-hypothesis processing across hypotheses:
```python
# Process all non-priced-in hypotheses in parallel
tasks = [_process_single_hypothesis(h, gap, cfg) for h, gap in active_hypotheses]
results = await asyncio.gather(*tasks, return_exceptions=True)
```
This is NOT what the plan proposes, but it's a viable optimization for a future phase.

**Mitigation**:
- Accept that causal + flow are sequential within a single hypothesis's HVR cycle. The latency impact (~2 additional Pro calls per hypothesis at ~2s each = ~4s added to ~20s per hypothesis) is acceptable.
- Document the execution order explicitly: `causal_decomposition → flow_decomposition → verify_claim → [refine loop]`.
- For latency optimization, parallelize across HYPOTHESES (not within one hypothesis's decomposition). Each hypothesis's causal+flow+verify chain is independent of other hypotheses.
- If flash_triage identifies 5 hypotheses and 3 pass expectation_gap → process all 3 in parallel via `asyncio.gather`. Slot this into the per-hypothesis loop in `run_investigation_loop()`.

---

## Finding 5: Token Budget Integration — No Connection to TokenBudget (HIGH)

**Plan claim (section 7, risk matrix)**: "因果/资金流使用 Flash；条件预测仅对 ACTIONABLE 运行" — uses Flash for cost control.

**Reality**: The plan makes zero references to `gateway/token_budget.py`. The `TokenBudget` class at `token_budget.py:17-97` provides:
- `can_call_pro()` / `can_call_flash()` — pre-flight checks
- `reserve_pro(estimated_tokens)` / `reserve_flash(estimated_tokens)` — quota reservation
- `report()` — usage statistics
- Priority-based queueing (CRITICAL > HIGH > NORMAL > SHADOW > LOW)

**Current call budget per session** (from `investigation_loop.py`):

| Phase | LLM | Calls | Per |
|-------|:---:|:-----:|-----|
| Pre-Act planning | Pro | 1 | session |
| Expectation gap | Pro | 1 | per hypothesis |
| HVR initial verify | Pro | 1 | per hypothesis (inside _hvr_cycle → verify_claim) |
| HVR refine | Pro | 0-3 | per hypothesis (refinement loop) |
| Adversarial bear case | Pro | 1 | per hypothesis |
| Layer narratives | Flash | 1 | per hypothesis |
| **Total (5 hypotheses, 2 refines each)** | Pro + Flash | **~21 Pro + 5 Flash** | session |

**After Phase H — additional calls**:

| New Module | LLM | Calls | Per | Plan's Mitigation |
|------------|:---:|:-----:|-----|-------------------|
| causal_decomposition | **Pro** | 1 | per hypothesis | Plan §7 says "use Flash" but §2.1 says `chat_pro` |
| flow_decomposition | **Pro** | 1 | per hypothesis | Same contradiction |
| scenario_forecaster | **Pro** | 1 | per ACTIONABLE (~1-3) | Limited to ACTIONABLE only |
| fragility_scanner | **Pro** | 1 | session | Not specified |
| cross_border_analyzer | **Pro?** | 1 | session | Not specified |

**Total with Phase H (worst case: 5 hypotheses, 3 ACTIONABLE, 2 refines each)**:
- Existing: ~21 Pro + 5 Flash
- New causal: +5 Pro (or Flash if plan's Flash mitigation is adopted)
- New flow: +5 Pro (or Flash)
- New scenario: +3 Pro
- New fragility: +1 Pro
- New cross_border: +1 Pro
- **Total: ~36 Pro + 5 Flash (or 26 Pro + 15 Flash if Flash mitigation adopted)**

**Token budget concern**: The `TokenBudget` currently has `pro_call_limit` and `flash_call_limit` (defaults from `MarketMindConfig`). If `pro_call_limit` is set to e.g., 30, the Phase H additions would exceed it with no warning. The new modules have:
- No `can_call_pro()` pre-checks before calling
- No `reserve_pro()` quota reservation
- No Priority level assignment
- No integration with the budget reporting system

**The plan contradicts itself on LLM routing**: Section 2.1 (causal_decomposition) says "调用 chat_pro 进行分解（通过 gateway）" but Section 7 (risk matrix) says "因果/资金流使用 Flash". This MUST be resolved. If causal/flow use Flash, per-hypothesis token cost is lower but analysis quality may suffer (Flash is less capable at causal reasoning).

**Mitigation**:
- Add `can_call_pro()` / `can_call_flash()` checks before every new LLM call. If budget exhausted, skip the module (return None) — same pattern as existing error handling.
- Assign Priority levels: causal_decomposition=HIGH, flow_decomposition=HIGH, scenario_forecaster=NORMAL, fragility_scanner=NORMAL, cross_border_analyzer=LOW.
- Decide and document: do causal/flow use Pro or Flash? The plan says both. Pick one and update all references.
- Add a budget remaining check BEFORE the per-hypothesis loop in `run_investigation_loop()`. If budget is below N_hypotheses * (existing_cost + new_cost), skip Phase H modules for remaining hypotheses.
- Add `budget.report()` output in the pipeline tracker (app.py's `_StageTracker`) so the user sees token consumption.

---

## Finding 6: Error Propagation — Cumulative Silent Failure Mode (HIGH)

**Plan's error handling philosophy** (from each module's "不冲突证明"):

| Module | Failure Behavior |
|--------|-----------------|
| causal_decomposition | field = None → pipeline continues |
| flow_decomposition | 数据不可用标记 |
| scenario_forecaster | 仅对 ACTIONABLE, 可选字段 |
| fragility_scanner | NOT SPECIFIED |
| cross_border_analyzer | 静默跳过 |
| regime_mapper | 降级为旧版关键词启发式 |

**The cumulative failure mode**: If all 6 Phase H enhancements fail silently:

1. `causal = None` → no decomposition
2. `flow = None` → no flow attribution
3. `scenario_tree = None` → no forward scenarios
4. `regime_mapper` falls back to keyword heuristic → same as pre-Phase-H Layer 4
5. `fragility_scanner` fails → empty FragilityReport (no warnings)
6. `cross_border` silently skipped → no cross-border context

**Result**: The pipeline produces output IDENTICAL in quality to pre-Phase-H — but the user receives NO warning that all 6 Phase H enhancements silently failed. The user believes they're getting Phase H-enhanced analysis when they're actually getting pre-Phase-H baseline quality.

**This is a trust-shattering failure mode.** If the user makes an investment decision based on what they think is Phase-H-quality analysis but is actually pre-Phase-H-quality, and the trade goes wrong, the tool has silently misled them.

**No existing mechanism tracks this**: The `_StageTracker` in app.py only reports per-stage success/failure. There's no per-module health tracking within a stage. The archive serialization at `app.py:159-167` doesn't include enhancement status.

**Mitigation**:
- Add an `enhancement_health: dict[str, str]` field to some shared session context (or as a module-level accumulator) that records `{"causal_decomposition": "ok" | "parse_failed" | "api_error" | "skipped", ...}`.
- After the pipeline completes, if any Phase H module failed, emit a prominent warning through the tracker: `"[WARNING] Phase H enhancements degraded: causal=parse_failed, flow=data_unavailable. Analysis quality = pre-Phase-H baseline."`
- Add enhancement health to the archive output at `app.py:159-167` and the final decision summary.
- Adopt a "fail-loud" default for Phase H modules: unless the plan explicitly classifies a module as "optional enhancement" (cross_border_analyzer), failures should be logged at WARNING level, not silently swallowed.

---

## Finding 7: Module Size Compliance — fragility_scanner and regime_mapper Over Soft Threshold (MEDIUM)

**Plan estimates vs CLAUDE.md §3.1 limits**:

| Module | Estimated Lines | Soft (250) | Hard (500) | Status |
|--------|:---:|:---:|:---:|------|
| mechanism_glossary.py | ~80 | PASS | PASS | Data module, exempt from SRP |
| causal_decomposition.py | ~250 | AT LIMIT | PASS | Needs SRP check at review |
| flow_decomposition.py | ~250 | AT LIMIT | PASS | Needs SRP check at review |
| cross_border_analyzer.py | ~250 | AT LIMIT | PASS | Needs SRP check at review |
| regime_mapper.py | ~300 | **OVER** | PASS | Triggers SRP investigation |
| fragility_scanner.py | ~300 | **OVER** | PASS | Triggers SRP investigation |
| scenario_forecaster.py | ~250 | AT LIMIT | PASS | Needs SRP check at review |
| fragility_thresholds.py | ~80 | PASS | PASS | Data module, exempt from SRP |

**SRP investigation for fragility_scanner (300 lines)**: Per CLAUDE.md §3.1 Tier 1 rules, ask 4 questions:

1. **Does the module do more than one thing?** The plan describes it doing: (a) load 15-threshold library, (b) scan market data against each threshold, (c) compute distance_pct for each, (d) detect cascade chains, (e) compute overall_fragility_score (0-1), (f) classify into active_warnings vs monitored, (g) output FragilityReport. That's 7 distinct responsibilities. **Likely SRP violation.**

2. **Does it export more than 10 public functions?** Unknown — plan doesn't specify the API surface. At 300 lines with 7 responsibilities, 10+ functions is plausible.

3. **Do any functions have >4 parameters?** The `FragilityReport` dataclass already has `active_warnings`, `monitored`, `overall_fragility_score` — the main analysis function would likely take 4+ inputs.

4. **Cyclomatic complexity >10?** The cascade detection (traversing threshold chains) is inherently branching. Likely >10.

**Verdict**: fragility_scanner at 300 lines with 7 distinct responsibilities is an SRP violation. Split into:
- `fragility_thresholds.py` (already separate: ~80 lines data) — keep as is
- `fragility_scanner.py` (~150 lines): scan + distance computation only
- `fragility_cascade.py` (~100 lines): cascade chain detection + scoring

**SRP investigation for regime_mapper (300 lines)**: Responsibilities include (a) quadrant classification, (b) 7-variable Euclidean distance search, (c) top-5/anti-3 selection, (d) forward return computation, (e) key difference generation (LLM call?), (f) fallback to keyword heuristic. Likely SRP violation. Split candidate: `regime_library.py` (data), `regime_mapper.py` (distance search + matching), `regime_interpreter.py` (difference analysis + confidence extraction).

**Mitigation**:
- For fragility_scanner and regime_mapper, the soft threshold triggers a MANDATORY SRP investigation before coding begins. Document the 4-question answers in the module spec.
- If SRP violation is confirmed, split the module BEFORE writing code (design the split in the architecture plan, not during implementation).
- The 250-line soft threshold is NOT a hard limit — it's a trigger for investigation. If the investigation shows the module is genuinely single-responsibility despite the line count, document the justification and proceed.

---

## Finding 8: Grandfather Clause — investigation_loop.py is NOT Grandfathered and Needs Extraction (CRITICAL)

**Plan claim (section 5, "与 grandfather clause 不冲突")**: "investigation_loop.py 当前 704 行 → 超过硬上限 → 但仅做增强插入（~50 行胶水代码），属 grandfather 允许范围"

**Reality**:

1. **Line count is wrong**: The plan says 704 lines. The actual count is **918 lines** (confirmed by `wc -l`). This is a 30% error. At 918 lines, the file is 83.6% over the 500-line hard ceiling.

2. **investigation_loop.py is NOT in the grandfather clause**: CLAUDE.md §3.1 lists: `app.py: 971, layer1_interactive.py: 657, methodology_rules.py: 639, shadow_agent.py: 567, multimodal_adapter.py: 591`. investigation_loop.py is absent.

3. **The plan's proposed change IS "new feature work"**: The grandfather clause states: "may receive extraction-only changes and bug fixes. New feature work on these files requires extraction first." Adding 50 lines of glue code to wire in causal_decomposition and flow_decomposition is unambiguously "new feature work" — not extraction, not a bug fix.

4. **Even if investigation_loop.py were grandfathered**: The clause's permission is "extraction-only changes and bug fixes." Adding new feature code would still violate it. The file would need extraction FIRST.

5. **The file already needs extraction without Phase H**: At 918 lines, `investigation_loop.py` does at least 7 things:
   - Pre-Act planning (`_pre_act_planning`, line 267-317)
   - Expectation gap check (`_expectation_gap_check`, line 320-361)
   - HVR cycle with refinement loop (`_hvr_cycle`, line 367-493)
   - Hypothesis refinement via Pro (`_refine_hypothesis`, line 496-539)
   - Adversarial bear case (`_adversarial_bear_check`, line 544-602)
   - Layer narrative generation via Flash (`_generate_layer_narratives`, line 417-466)
   - Session orchestration (`run_investigation_loop`, line 606-712... wait, line 809-918)
   - Various helper functions (line 189-414)

**Required extraction BEFORE Phase H module integration**:

The file should be split into:
1. `pipeline/hvr_cycle.py` (~250 lines): `_hvr_cycle` + `_refine_hypothesis` 
2. `pipeline/investigation_pre_act.py` (~120 lines): `_pre_act_planning` + `_PRE_ACT_SYSTEM`
3. `pipeline/investigation_bear_case.py` (~100 lines): `_adversarial_bear_check` + `_BEAR_CASE_SYSTEM`
4. `pipeline/investigation_narratives.py` (~80 lines): `_generate_layer_narratives` + helpers + `_NARRATIVE_PROMPT`
5. `pipeline/investigation_helpers.py` (~60 lines): `_parse_json_strict`, `_classify_layer_interpretation`, `_determine_verdict`
6. `pipeline/investigation_loop.py` (~150 lines): `run_investigation_loop` glue + data types (HypothesisResult, InvestigationConfig)

This reduces the main file from 918 to ~150 lines and creates testable sub-modules.

**Mitigation**:
- **Phase H cannot proceed until investigation_loop.py is extracted.** This is a hard blocker per CLAUDE.md §3.1.
- Add "investigation_loop.py extraction" as Phase H-0 step 0.5a (before "app.py extraction" step 0.5).
- Each extracted module needs 3+ tests (PICA-Unit) before integration.
- Update the plan's line count to reflect reality (918, not 704).
- After extraction, the new 150-line glue layer can safely accept the 50 lines of Phase H enhancement calls — staying under the 200-line soft threshold for glue layers.

---

## Finding 9: Test Coverage — No Test Plan for 6 New Modules (HIGH)

**Plan claim (section 0, principle 7)**: "PICA 全协议：每个新模块必须通过 PICA-Unit → Security → Integration → Regression"

**Reality**: The plan mentions PICA as a principle but provides:
- NO test file specifications
- NO test strategy per module
- NO mock/fixture plan
- NO minimum test count per module
- NO mention of test-before-extract (CLAUDE.md §3.1, rule 4: "Write at least 3 tests for the new module BEFORE integrating it into the glue layer")

**Required tests per modular architecture rules (§3.1)**:

| Module | Minimum Tests | What to Test |
|--------|:---:|------|
| causal_decomposition.py | 3+ | Successful decomposition, parse failure fallback, empty hypothesis edge case |
| flow_decomposition.py | 3+ | Entity attribution completeness, data_unavailable degradation, TIC mock |
| regime_mapper.py | 3+ | Quadrant classification, distance search accuracy, keyword fallback |
| scenario_forecaster.py | 3+ | Tree generation, ACTIONABLE filter, parse failure |
| fragility_scanner.py | 3+ | Threshold detection, cascade chain, empty market data |
| cross_border_analyzer.py | 3+ | TIC parse, BIS fallback, data_unavailable |
| **Total minimum** | **18+** | Plus regression tests on integration points |

**Where tests go**: `tests/test_pipeline/test_causal_decomposition.py`, etc.

**Mock strategy needed**: All new modules call `chat_pro`/`chat_flash` via gateway. Tests need a mock LLM fixture (similar to existing `conftest.py` patterns for `test_investigation_loop.py`).

**Mitigation**:
- Add a "Test Plan" section to the plan specifying test files and per-module test scenarios.
- Write tests in TDD order: write tests first, then implement module (this is standard for the project's PICA protocol).
- Each Phase H sub-phase (H-3, H-4, H-5) should include a test-writing step BEFORE the implementation step.
- Existing `test_investigation_loop.py` (2 files found by grep) must be updated for the extracted sub-modules.
- Fragility thresholds need property-based tests: for any combination of current values, `overall_fragility_score` must be in [0,1] and threshold detection must be deterministic.

---

## Finding 10: Config vs Code Boundary — Data Modules Compliant but PICA Required on Changes (LOW)

**Plan classification**: `mechanism_glossary.py` and `fragility_thresholds.py` as "data modules" in `config/`.

**Compliance check against CLAUDE.md §3.1 exception**: "Constants, enums, label maps, and configuration modules may export multiple names. The single-entry-point rule applies to behavioral modules, not data containers."

Both files are pure data containers (dictionaries). They qualify for the multi-export exception. **Compliant.**

**PICA audit requirements**: The exception exempts data modules from the single-entry-point rule but does NOT exempt them from PICA audit. CLAUDE.md §4 says PICA applies to "Every code change." Changing a data module (adding/modifying entries) IS a code change.

**Specific concerns**:

1. **mechanism_glossary.py** (~40 entries planned): Adding a new mechanism entry is a data change. However, the mechanism names (eSLR, IORB, FIMA) are referenced in Pro prompts. A typo in a mechanism name could cause LLM confusion but won't crash the pipeline. Risk: LOW. PICA-Unit (verify the dict is valid Python) is the minimum bar.

2. **fragility_thresholds.py** (~15 thresholds): Significantly higher risk. Incorrect threshold values could cause:
   - False positive: warning triggered when market is fine → user anxiety
   - False negative: warning NOT triggered when market IS fragile → missed risk
   
   Threshold changes require:
   - Source citation in comments (e.g., `# Source: Pozsar (2023), "War Finance" §4, Table 2`)
   - PICA-Unit: verify thresholds are in valid ranges (e.g., VIX threshold < 100, not 350)
   - PICA-Security: verify thresholds don't contain injection vectors (they're all numeric, so LOW risk)

3. **File format choice**: The plan uses `.py` files. This is acceptable per the rules. YAML/JSON would be equally valid but the project already uses Python config modules (`investigation_config.py`, `source_authority.py`, `source_independence.py`, `asset_universe.py`). Consistency favors `.py`.

**Mitigation**:
- Add a header comment to `fragility_thresholds.py`: `# WARNING: Threshold changes require source citation + PICA review.`
- For each threshold entry, document: source paper, section, date of research, and rationale for the chosen value.
- Add a PICA-Unit check: `python -c "from marketmind.config.fragility_thresholds import FRAGILITY_THRESHOLDS; assert len(FRAGILITY_THRESHOLDS) >= 15"`
- mechanism_glossary.py: add a simple validation that all mechanism keys referenced in prompts exist in the glossary (to prevent prompt-key mismatch).

---

## Summary of Findings

| # | Finding | Severity | Blocker? |
|:---:|------|:---:|:---:|
| 1 | Pipeline insertion points — stage numbering mismatch + missing cross_border hook | MEDIUM | No |
| 2 | HypothesisResult does NOT flow to downstream stages — false data-flow premise | **CRITICAL** | **Yes** — plan claims about compatibility are based on non-existent data flow |
| 3 | flow_decomposition has hard dependency on causal_decomposition | HIGH | Yes — blocks asyncio.gather claim |
| 4 | asyncio.gather conflicts with sequential HVR logic | HIGH | Yes — requires redesign of concurrent execution strategy |
| 5 | No token budget integration — could silently exceed daily limit | HIGH | No — but MUST be addressed before Phase H ships |
| 6 | Cumulative silent failure mode — all 6 enhancements can fail without warning | HIGH | No — but erodes user trust |
| 7 | fragility_scanner and regime_mapper over soft line threshold | MEDIUM | No — SRP investigation required |
| 8 | investigation_loop.py NOT grandfathered, needs extraction before any new feature work | **CRITICAL** | **Yes** — violates CLAUDE.md §3.1 hard ceiling |
| 9 | No test plan for 6 new modules (18+ tests needed) | HIGH | No — but violates test-before-extract rule |
| 10 | Data modules compliant but PICA needed on threshold changes | LOW | No |

**Blockers that must be resolved before Phase H implementation can begin**:
1. **FINDING 8 (CRITICAL)**: Extract investigation_loop.py (918 lines) before adding any new code. The plan's claim that the file is grandfathered is incorrect.
2. **FINDING 2 (CRITICAL)**: Fix the false data-flow premise. The plan must explicitly define HOW HypothesisResult connects to Decision — it currently doesn't. Add an integration step.
3. **FINDING 3 + 4 (HIGH)**: Resolve the asyncio.gather contradiction. Either make flow_decomposition independent of causal_decomposition, or accept sequential execution and remove the parallel claim.

**Recommendations**:
- Phase H-0 step 0.5a: Extract investigation_loop.py into 6 sub-modules. This is higher priority than app.py extraction.
- Phase H-0 step 0.5b: Add HypothesisResult parameter to generate_decision() and wire the data flow.
- Phase H plan section 3: Rewrite the integration diagram with correct execution order (sequential causal→flow→verify, not parallel).
- Add a "Test Plan" section to the plan with per-module test specifications.
- Add a "Token Budget Integration" section documenting how new modules interact with TokenBudget.reserve_pro().

---

**Audit prepared for**: User review before Phase H-1 (Gate 1) implementation.
**Next step**: User reviews findings, resolves blockers, updated plan proceeds to Security and Logic Red Team audits.
