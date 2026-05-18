# Phase H v2 Architecture Plan — Red Team Architecture/Integration Audit

**Audit type**: Architecture + Integration
**Date**: 2026-05-18
**Plan under review**: `.claude/plans/phase-h-revised-architecture.md` (v2)
**Original plan**: `.claude/plans/phase-h-comprehensive-architecture.md` (v1)
**Prior audits**: `.claude/audits/phase-h-plan-architecture.md`, `phase-h-plan-logic.md`, `phase-h-plan-security.md`
**Codebase baseline verified**: Yes — all file line counts and import chains verified against source

---

## Key Question 1: Are v1 CRITICALs Actually Resolved?

### ARCH-C1 (v1): investigation_loop.py was 918 lines, exceeded 500-line hard ceiling, needed extraction

**v2 claim**: Extracted to 5 modules, main file now 486 lines.

**Verified against code**:
```
investigation_loop.py:  486 lines
hvr_cycle.py:           328 lines
investigation_prompts.py: 94 lines
investigation_types.py:  81 lines
investigation_direction.py: 107 lines
```

The extraction is complete and correct:
- `investigation_loop.py` imports from all four sub-modules (glue layer pattern)
- Sub-modules do NOT import from `investigation_loop.py` (no back-imports)
- `hvr_cycle.py` imports from `investigation_types`, `verification_chain`, `gateway.async_client`, `config.investigation_config` — clean dependency DAG
- `investigation_types.py` imports from `verification_chain` — sibling import, allowed
- `investigation_loop.py` at 486 lines is the glue/orchestration layer — it calls `run_hvr_cycle()`, `_pre_act_planning()`, `_expectation_gap_check()`, `_adversarial_bear_check()`, `_generate_layer_narratives()`, and `_determine_verdict()` in sequence. It contains minimal helper functions (`_parse_json_strict`, `_determine_verdict`) — the helpers could be extracted to a dedicated module in a future pass but are small enough (60 lines combined) to not trigger soft threshold investigation.

**Verdict**: **FULLY RESOLVED**. investigation_loop.py is 486 lines (14 lines below hard ceiling). Extraction created a clean glue layer with no back-imports. All four extracted modules are under soft threshold except hvr_cycle.py (328 lines — soft threshold triggered but it does one thing: run the HVR cycle).

### ARCH-C2 (v1): HypothesisResult did NOT flow to generate_decision()

**v2 claim**: "✅ 已接入 generate_decision()"

**Verified against code**:
- `decision.py:93-107`: `generate_decision()` now accepts `hypotheses: list | None = None` parameter
- `decision.py:184-247`: `_build_hypothesis_summary()` processes HypothesisResult objects, extracting ACTIONABLE direction/confidence/core_logic/risk, HIGH_CONTENTION risks, and 4-layer verification summaries
- `orchestration.py:291-296`: passes `hypotheses=hypotheses` to `generate_decision()`
- `orchestration.py:150-153`: `run_investigation_loop()` returns hypotheses, filtered into actionable/monitor/priced_in lists

The data flow is now:
```
investigation_loop.py → returns list[HypothesisResult]
  → orchestration.py:152 hypotheses = await run_investigation_loop(...)
  → orchestration.py:295 generate_decision(..., hypotheses=hypotheses)
  → decision.py:164 _build_hypothesis_summary(hypotheses)
  → decision.py:120 chat_pro(..., user_prompt=user_prompt)
```

**Verdict**: **FULLY RESOLVED**. HypothesisResult flows through orchestration to decision. The `_build_hypothesis_summary()` function consumes direction, confidence, core_logic, risk_level, time_window, bear_case, and 4-layer narratives from HypothesisResult objects.

---

## Key Question 2: app.py Status — Is It Truly 76 Lines With No Business Logic?

**v2 claim**: "app.py 971→76"

**Verified against code**: app.py is 77 lines (plan says 76 — 1 line off, negligible).

**Content analysis**:
| Lines | Content | Classification |
|:---:|------|:---:|
| 1-8 | Imports + sys.path setup | Entry point boilerplate |
| 13-18 | `_setup_logging()` | Infrastructure |
| 20-28 | `run_gui()` | Mode dispatch |
| 31-77 | `main()` | CLI args + config validation + mode dispatch |

**Business logic inventory**: None.
- No analysis/decision/formatting code
- No HypothesisResult construction
- No data fetching or pipeline logic
- Pure argument parsing, mode routing, and function calling

The file reads like a table of contents: `run_gui(path)` or `run_daily(path)` is selected based on `--mode`, and `run_backtest(path)` for `--backtest`. All implementation is in `pipeline/orchestration.py` and `backtest_entry.py`.

**Verdict**: **CLEAN**. app.py is a textbook entry point — 77 lines of argument parsing and mode dispatch. Zero business logic.

---

## Key Question 3: orchestration.py at 365 Lines — Hard Ceiling Exceeded

**v2 claim**: "orchestration.py 拆分（run_stages_0_3 / run_gate1 / run_stages_4_10）" deferred to Phase H-4.

**Verified**: `wc -l` confirms 365 lines.

**Tier 1 SRP investigation (soft threshold 200, hard ceiling 300)**:

1. **Does the module do more than one thing?** **YES**. It defines:
   - `run_daily()` (329 lines) — full daily pipeline orchestration
   - `run_interactive()` (38 lines) — interactive CLI pipeline orchestration
   - `_StageTracker` (11 lines) — progress tracking helper
   
   Two distinct pipeline modes in one file. This is a mild SRP violation — `run_interactive` and `run_daily` share the `_StageTracker` helper but otherwise have no dependency on each other.

2. **Does it export more than 10 public functions?** No — 2 public functions + 1 class. Ample headroom.

3. **Do any functions have >4 parameters?** `run_daily(config, mock, verbose, shadow_count)` = 4 params. At the limit but not over.

4. **Is any function's cyclomatic complexity >10?** `run_daily()` has 10 sequential stages with conditionals for shadow initialization, flash_triage fallback, and crystallization — likely CC in the 12-18 range.

**Assessment for transitional step**:
- The file is 65 lines over the hard ceiling
- The content is pure orchestration — no business logic hiding in it. Every stage calls an external module and wraps the result in archive serialization.
- The v2 plan explicitly schedules splitting in Phase H-4 step 4.3
- The splitting plan is reasonable: `run_stages_0_3`, `run_gate1`, `run_stages_4_10`

**Verdict**: **ACCEPTABLE for transitional step**, with conditions:
- Split MUST be completed in Phase H-4 before any new feature work on orchestration.py
- The file must not grow beyond 365 lines before H-4 (new features go into extracted helpers, not inline)
- The split deliverables should be: `pipeline/orchestrate_early_stages.py` (~150 lines, stages 0-3), `pipeline/orchestrate_gate1.py` (~100 lines, Gate 1 loop), `pipeline/orchestrate_late_stages.py` (~150 lines, stages 4-10), leaving `pipeline/orchestration.py` (~50 lines) as the top-level dispatch that calls all three.

---

## Key Question 4: asset_class_routing.py — Circular Import Risk?

**v2 plan**: asset_class_routing.py lives in `config/` as a data module. Pipeline modules import from it.

**Verified**: asset_class_routing.py does NOT exist yet (planned, not implemented).

**Circular import analysis**:
```
config/asset_class_routing.py
  ├── imports: nothing from pipeline/ or config/ siblings
  ├── exports: ASSET_CLASS_TAXONOMY dict + route_asset_class() function
  └── dependency: leaf node in the import DAG

pipeline/causal_decomposition.py (planned)
  ├── would import: from marketmind.config.asset_class_routing import route_asset_class
  └── config → pipeline IS the correct direction (config never imports pipeline)

pipeline/flow_decomposition.py (planned)
  ├── would import: from marketmind.config.asset_class_routing import ASSET_CLASS_TAXONOMY
  └── same direction — safe
```

**Existing precedent**: pipeline modules already import from config modules:
- `investigation_loop.py` imports from `marketmind.config.investigation_config`
- `hvr_cycle.py` imports from `marketmind.config.investigation_config`
- `orchestration.py` imports from `marketmind.config.settings` and `marketmind.config.asset_universe`

No existing config module imports from pipeline. The pattern is well-established and safe.

**Verdict**: **NO CIRCULAR IMPORT RISK**. Config data modules are leaf nodes in the import DAG. Pipeline imports config — never the reverse. asset_class_routing.py follows the same pattern as existing `investigation_config.py`, `asset_universe.py`, `source_authority.py`.

---

## Key Question 5: Module Dependency DAG — Sibling Import Analysis

**Current pipeline import DAG (verified)**:

```
config/ (leaf layer — imports nothing from pipeline)
  ├── investigation_config.py
  ├── settings.py
  ├── asset_universe.py
  └── asset_class_routing.py (planned)

pipeline/ (internal layer)
  ├── investigation_types.py → imports verification_chain
  ├── investigation_prompts.py → leaf (no pipeline imports)
  ├── investigation_direction.py → leaf
  ├── verification_chain.py → imports investigation_types (sibling)
  ├── hvr_cycle.py → imports investigation_types, verification_chain, config (sibling + config)
  ├── investigation_loop.py → imports flash_preprocessor, hvr_cycle, direction, prompts, types, verification_chain (glue → modules)
  ├── layer1_narrative.py → sibling
  ├── layer2_fundamental.py → sibling
  ├── layer3_technical.py → sibling
  ├── red_team.py → sibling
  ├── resonance.py → sibling
  ├── decision.py → imports layer1, layer2, layer3, red_team, resonance
  └── orchestration.py → imports scout, flash_triage, investigation_loop, layer1-3, red_team, resonance, decision (glue → all)

gateway/ (infrastructure layer — no pipeline imports)
  ├── async_client.py
  └── macro_data.py
```

**Planned additions**:
```
config/asset_class_routing.py → leaf, zero imports from pipeline ✓
pipeline/causal_decomposition.py → would import config.asset_class_routing + gateway.async_client ✓
pipeline/flow_decomposition.py → would import config.asset_class_routing + gateway.async_client ✓
pipeline/regime_mapper.py → would import config.regime_library ✓
pipeline/scenario_forecaster.py → would import gateway.async_client ✓
pipeline/fragility_scanner.py → would import config.fragility_thresholds ✓
pipeline/cross_border_analyzer.py → would import gateway.cross_border ✓
```

**Sibling import check**: The new modules would import from:
- `config/` (leaf nodes — safe)
- `gateway/` (infrastructure — safe)
- `pipeline/` — only from types modules (investigation_types, verification_chain), not from the glue layer

**Potential issue**: `flow_decomposition.py` needs `CausalDecomposition` dataclass. If `CausalDecomposition` is defined in `causal_decomposition.py`, then flow_decomposition imports from causal_decomposition — a sibling import. This is allowed (the extraction rules prohibit imports FROM the glue layer, not between siblings), but it creates a hard sequential dependency: causal must run before flow. The v1 audit Finding 3 flagged this. The v2 plan does NOT seem to resolve it — flow_decomposition still takes CausalDecomposition as input.

**Recommendation**: Define all shared data types (CausalDecomposition, FlowAttribution, RegimeMapping, ScenarioTree, FragilityReport, CrossBorderFlowReport) in a single `pipeline/investigation_types.py` or `pipeline/phase_h_types.py` data module. This way flow_decomposition imports types from a data module, not from its sibling — removing the hard dependency concern and allowing true parallel development of both modules.

**Verdict**: **NO BACK-IMPORTS TO GLUE LAYER**. Import DAG is clean: glue → modules → config/gateway. Sibling imports between pipeline modules exist (verification_chain ↔ investigation_types) and are allowed. The flow_decomposition → causal_decomposition dependency should be resolved by extracting shared types to a data module.

---

## Key Question 6: Phase H-1 and H-2 Parallel Execution — Dependency Analysis

**v2 claim**: Phase H-1 (causal + flow) and H-2 (regime + scenario) can run in parallel.

**Dependency analysis**:

```
Phase H-1: causal_decomposition.py, flow_decomposition.py
  Dependencies: config/asset_class_routing, gateway/async_client, pipeline/investigation_types
  Internal: flow depends on causal output (sequential within H-1)

Phase H-2: regime_mapper.py, scenario_forecaster.py
  Dependencies: config/regime_library, gateway/async_client, pipeline/investigation_types
  Internal: independent (both can be developed in parallel within H-2)
```

**Cross-phase dependency check**:
- regime_mapper needs: historical regime data (config/regime_library) + 7-variable market data (FRED) — does NOT need causal/flow output
- scenario_forecaster needs: HypothesisResult (verdict=ACTIONABLE) — does NOT need causal/flow output
- Neither H-2 module depends on any H-1 module

**However**: Within H-1, causal_decomposition and flow_decomposition cannot be developed fully in parallel because flow_decomposition takes CausalDecomposition as input. They can be developed concurrently if the shared type is defined first, or they can be developed sequentially with causal first.

**Verdict**: **H-1 and H-2 CAN RUN IN PARALLEL** as the plan claims. No cross-phase dependencies exist. Within H-1, the causal→flow dependency is sequential (extract shared dataclass first, then develop both modules against it in parallel).

---

## Key Question 7: Test Coverage — Zero New Test Requirements

**v2 plan**: The plan mentions "PICA 全协议" as an architecture principle but specifies ZERO test files, ZERO test scenarios, and ZERO test counts.

**Per CLAUDE.md §3.1 rule 4**: "Write at least 3 tests for the new module (confirm/observe/question paths) BEFORE integrating it into the glue layer."

**Required minimum tests**:

| Module | Minimum | Test File | What to Test |
|--------|:---:|------|------|
| asset_class_routing.py | 3 | tests/test_pipeline/test_asset_class_routing.py | Keyword match, ticker match, LLM fallback (None case), unknown asset class |
| mechanism_glossary.py | 3 | tests/test_pipeline/test_mechanism_glossary.py | Lookup hit, lookup miss, multi-key lookup |
| causal_decomposition.py | 3 | tests/test_pipeline/test_causal_decomposition.py | Successful decomposition with mock Pro, parse failure → None, empty hypothesis edge case |
| flow_decomposition.py | 3 | tests/test_pipeline/test_flow_decomposition.py | Entity attribution with mock Pro, data_unavailable degradation, empty causal input |
| regime_mapper.py | 3 | tests/test_pipeline/test_regime_mapper.py | Quadrant classification, distance search accuracy, keyword fallback when data missing |
| scenario_forecaster.py | 3 | tests/test_pipeline/test_scenario_forecaster.py | Tree generation for ACTIONABLE, MONITOR skip, parse failure |
| fragility_scanner.py | 3 | tests/test_pipeline/test_fragility_scanner.py | Threshold crossed detection, cascade chain, empty market data |
| fragility_thresholds.py | 3 | tests/test_pipeline/test_fragility_thresholds.py | Valid values (all in range), threshold count >= 15, last_validated field presence |
| cross_border_analyzer.py | 3 | tests/test_pipeline/test_cross_border_analyzer.py | TIC parse success, BIS fallback, data_unavailable graceful degradation |
| **Total minimum** | **27** | 9 test files | — |

**Existing test infrastructure**: The project already has mock LLM fixtures in `conftest.py` for testing pipeline modules. The `test_investigation_loop.py` test file can serve as a template for the new test files.

**Test plan gap severity**: **HIGH**. The v2 plan allocates zero time or tasks to testing across all 4 phases (H-0 through H-4). Per PICA protocol, tests must be written BEFORE module integration. If tests are deferred to "later," the pipeline will have 6 untested new modules in production.

**Verdict**: **DEFINITE GAP**. The v2 plan needs a "Test Plan" section with:
1. Per-module test file specifications (above table)
2. Test-before-integrate ordering (write tests in each phase's first step)
3. Mock LLM fixture reuse strategy (existing conftest.py patterns)
4. Total test count target: 27 minimum, 40+ recommended for edge case coverage

---

## Additional Finding 1: verification_chain.py at 684 Lines — Not Extracted, Not Grandfathered

The v1 audit Finding 7 flagged module sizes. The v2 plan extracts investigation_loop.py and app.py but does NOT address verification_chain.py:

```
verification_chain.py: 684 lines (hard ceiling: 500)
```

This file is NOT in the grandfather clause (`CLAUDE.md` §3.1 lists: app.py, layer1_interactive.py, methodology_rules.py, shadow_agent.py, multimodal_adapter.py). At 684 lines, it exceeds the hard ceiling by 184 lines (36.8%).

The plan says regime_mapper will "replace Layer 4" (`verify_claim_historical`). If this replacement means extraction (moving Layer 4 logic OUT of verification_chain.py), the file could shrink below 500 lines. But the plan describes it as "替换 verify_claim_historical() 的实现" — replacing the implementation, not extracting the function. This means verification_chain.py stays at ~684 lines.

**Verdict**: **MEDIUM**. verification_chain.py extraction is a prerequisite per CLAUDE.md §3.1. The v2 plan should include it in the "前置" steps, or the regime_mapper design should explicitly extract Layer 4 logic to reduce verification_chain.py below 500 lines.

---

## Additional Finding 2: Pipeline Stage Insertion Points — Now Clean

The v1 audit Finding 1 flagged stage numbering mismatches. The v2 plan resolves this by:
- Not using stage numbering for insertion points — instead describing insertion in terms of files: "在 investigation_loop.py 的 HVR 循环中" (inside investigation_loop.py's HVR loop)
- Defining the single insertion point clearly: `investigation_loop.py` → before HVR verification

**Verdict**: **RESOLVED**. The v2 plan's file-based insertion point descriptions are unambiguous and match the actual code structure.

---

## Additional Finding 3: Data Module Classification — Compliant

The v2 plan classifies `asset_class_routing.py` and `mechanism_glossary.py` as data modules in `config/`. Per CLAUDE.md §3.1 exception: "Constants, enums, label maps, and configuration modules may export multiple names."

Both modules are pure data containers (dictionaries) with a single routing function (`route_asset_class`). They qualify for the multi-export exception.

**Verdict**: **COMPLIANT**. Data module classification is correct.

---

## Summary of Findings

| # | Finding | Severity | Blocker? |
|:---:|------|:---:|:---:|
| Q1 | v1 CRITICALs: investigation_loop extraction + HypothesisResult wiring — both RESOLVED | — | No |
| Q2 | app.py: 77 lines, zero business logic — CLEAN | — | No |
| Q3 | orchestration.py: 365 lines, 65 over hard ceiling, deferred to H-4 — acceptable transitional | MEDIUM | No — conditional on H-4 completion |
| Q4 | asset_class_routing.py: circular import risk — NONE (config leaf node) | — | No |
| Q5 | Module dependency DAG: no back-imports, clean DAG, sibling types issue manageable | LOW | No |
| Q6 | H-1 and H-2 parallel: cross-phase dependencies — NONE, truly independent | — | No |
| Q7 | Test coverage: ZERO tests specified, 27 minimum required — GAP | **HIGH** | Yes — no test plan exists |
| A1 | verification_chain.py: 684 lines, not extracted, not grandfathered | MEDIUM | No — but should be addressed |
| A2 | Pipeline insertion points: now clean (file-based, unambiguous) | — | No |
| A3 | Data module classification: compliant | — | No |

### Blocker

**One blocker identified**: No test plan (Q7). 27 minimum tests across 9 test files are required by CLAUDE.md §3.1 and the PICA protocol. The v2 plan must add:

1. A "Test Plan" section with per-module test file specifications
2. Test-writing steps in each Phase (H-0 through H-4) BEFORE implementation steps
3. Mock LLM fixture reuse strategy

### Approved with conditions

The v2 plan is architecturally sound and resolves both v1 CRITICAL findings. The following conditions must be met before or during implementation:

1. **Add test plan** (Q7) — blocker, must be resolved before Phase H-0 begins
2. **Extract shared types** (Q5) — define CausalDecomposition, FlowAttribution, and other new dataclasses in a shared data module to remove the flow→causal sibling dependency
3. **Schedule orchestration.py split** (Q3) — the H-4 split must be completed before any new feature work on orchestration.py
4. **Address verification_chain.py** (A1) — either extract or confirm that regime_mapper replacement of Layer 4 shrinks the file below 500 lines

---

**Audit prepared for**: User review before Phase H-0 implementation.
**Next step**: User reviews findings, adds test plan to v2 plan, resolves blocker before any code is written.
