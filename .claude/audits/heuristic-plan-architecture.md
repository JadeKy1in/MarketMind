# Red Team Architecture Audit: Heuristic News Workflow Plan

**Audit Date**: 2026-05-17
**Auditor Role**: Architecture Auditor
**Plan Under Review**: `docs/superpowers/plans/2026-05-17-heuristic-news-workflow.md`
**Supporting Docs**: Root CLAUDE.md, MarketMind CLAUDE.md, heuristic-workflow-2, heuristic-workflow-4

---

## Finding 1: L1-L3 Pipeline Fate Is Unspecified (What Replaces What)

**Rating**: CRITICAL

The plan states it will "replace Step 2 (Flash preprocessing)" with the new 4-module architecture. However, the new flow (`Flash triage -> Heuristic browse -> Deep verify -> Logic chain`) fundamentally replaces not just Step 2, but the ENTIRE analysis pipeline through Step 4 at minimum.

Current flow:
```
Step 1: Scout (587 articles)
Step 2: Flash -> FlashSignal (50 articles)
Step 3: L1 -> Layer1Result (15 signals)
Step 4: L2 + L3 -> Layer2Result + Layer3BatchResult
Step 5: Shadow ecosystem
Step 6-9: Red Team, Resonance, Decision, Archive
```

Proposed flow:
```
Step 1: Scout (587 articles)
Step 2: Flash triage -> FlashScore (587 articles, scoring only)
Step 2.5: Pro heuristic browse -> selected threads
Step 2.6: Verification chain -> validated evidence
Step 2.7: Logic chain -> structured conclusions
Step 3: ??? (L1 still needed? L2? L3?)
```

**Specific breakage points:**

1. `layer1_narrative.py:analyze_layer1()` takes `signals: list[FlashSignal]` as input. With the new flow, there are no FlashSignals -- only FlashScores (5-axis, no event_grade/direction/confidence). L1 would need a complete rewrite to accept `list[FlashScore]` instead, OR L1 is removed entirely.

2. `layer2_fundamental.py:analyze_layer2()` takes `l1_result: Layer1Result`. If L1 is removed/replaced, L2 has no input.

3. `layer3_technical.py:analyze_layer3()` takes `tickers` and operates independently of L1-L2, so it survives. But its ticker list origin becomes unclear.

4. `decision.py:generate_decision()` takes `l1, l2, l3, red_team, resonance, shadow_votes`. If L1/L2 are removed, the decision stage must be rewritten to accept the new logic chain output.

**Recommended resolution**: The plan must explicitly declare the fate of each existing Step 3-8 module:
- KEPT (unchanged): scout.py, resonance.py, red_team.py, archivist.py
- MODIFIED (adapt to new input): layer1_narrative.py, layer2_fundamental.py, decision.py
- DELETED: flash_preprocessor.py (partially or fully)
- Or: the new heuristic workflow is an *alternative mode* (e.g., `--mode heuristic`) that runs in parallel, leaving existing pipeline intact.

---

## Finding 2: Token Budget Is Off by 10-15x

**Rating**: CRITICAL

The plan claims ~9,500 tokens total per session. Analysis of the same research documents the plan cites (heuristic-workflow-4) shows actual estimates of ~121,700 input + 35,500 output = ~157,000 tokens.

**Breakdown of discrepancy:**

| Phase | Plan Claim | Research Doc Estimate | Reality Check |
|-------|:----------:|:---------------------:|---------------|
| Flash triage (587 articles) | ~500 tokens | 58,700 in / 5,000 out | 587 articles x 50 chars/headline = 29,350 chars = ~7,300 tokens input MINIMUM. Structured JSON output for 587 articles at 50-100 tokens each = 29K-58K output. **Realistic: 80K-120K tokens** |
| Main AI browse (20 selected) | ~2,000 tokens | 5,000 in / 2,000 out | Acceptable for just browsing/skimming 20 summaries |
| HVR loop (5 hypotheses x 3 rounds) | ~5,000 tokens | 30,000 in / 15,000 out | Each HVR round: hypothesis (~200) + tool call desc (~300) + tool output (~500) + refinement (~300) = ~1,300/round. 5 threads x 3 rounds x 1,300 = 19,500. With context overhead: 25K-35K. **5,000 is 5-7x too low** |
| Logic chain synthesis | ~2,000 tokens | 8,000 in / 4,000 out | Acceptable |
| Flash verification pass | Not budgeted | 5,000 in / 2,000 out | Missing from plan entirely |
| **TOTAL** | **~9,500** | **~121,700 in / 35,500 out** | **~157,000 total** |

**Impact**: At 9,500 tokens, the system would exhaust its budget before completing a single HVR round on a single hypothesis. The 587-article triage alone would consume 30-60x the budgeted amount.

**Root cause**: The plan's token estimate appears to count only the *prompt template* overhead (the instructions + schema), not the actual *data payload* (587 headlines, structured JSON outputs, tool invocation descriptions, tool outputs).

**Recommended resolution**:
1. Adopt the research doc's budget model: Flash 100K input / 10K output limit, Pro 50K input / 15K output limit per session
2. Build the `investigation_config.yaml` with explicit budget caps BEFORE implementation
3. Gate the number of articles processed by Flash based on actual token measurements: start with 200 articles and scale up
4. Implement per-step token tracking using `gateway/token_budget.py`

---

## Finding 3: Implementation Sequence Violates PICA Protocol and §3.1 Rule 4

**Rating**: HIGH

The plan's 8-step sequence:

```
1. Red Team audit
2. flash_triage.py
3. verification_chain.py
4. investigation_loop.py (depends on 2+3)
5. logic_chain_builder.py (depends on 4)
6. Integration to app.py
7. Test + PICA audit  <-- WRONG POSITION
8. Real data verification
```

**Violation 1 — PICA run too late (Root CLAUDE.md §4)**:
PICA-Unit must run BEFORE integration (before Step 6), not after. Every new module requires:
- PICA-Unit (pytest): before integration into app.py
- PICA-Security: for new modules touching API calls and data, before integration
- PICA-Regression: full suite after integration

Step 7 conflates all 4 PICA levels + all testing into one step after integration. This means security issues, API vulnerabilities, and cross-module bugs are found AFTER code is integrated, requiring rework.

**Violation 2 — §3.1 Rule 4 (test-before-extract)**:
"Write at least 3 tests for the new module BEFORE integrating it into the glue layer." Tests must exist before Step 6, but the plan runs tests at Step 7.

Notably missing: tests for `verify()` that the new scoring schema doesn't break downstream consumers, `confirm()` that the old `FlashSignal` dataclass consumers are handled.

**Corrected sequence**:
```
1. Red Team audit
2. flash_triage.py + PICA-Unit + PICA-Security -> commit
3. verification_chain.py + PICA-Unit + PICA-Security -> commit
4. investigation_loop.py + PICA-Unit + PICA-Security -> commit
5. logic_chain_builder.py + PICA-Unit + PICA-Security -> commit
6. Integration to app.py + PICA-Integration + PICA-Regression -> commit
7. Real data verification
```

Each module gets its own PICA pass and its own commit (§3.1 Rule 6: "Commit after each extraction").

---

## Finding 4: Missing Dependency -- investigation_config.yaml Not in Implementation Steps

**Rating**: HIGH

The module table lists `config/investigation_config.yaml` (~50 lines) as a new file, but it does NOT appear in the 8 implementation steps. This config is a prerequisite for:

1. **verification_chain.py** -- needs tool-to-category mapping (TRIGGER_MAP from research doc §3)
2. **investigation_loop.py** -- needs budget limits: `max_threads_per_session`, `max_depth_per_thread`, `max_api_calls_per_thread`, `max_flash_tokens_per_session`, `max_pro_tokens_per_session`
3. **logic_chain_builder.py** -- needs confidence thresholds and layer weights

Without this config, every module hardcodes magic numbers, creating a maintenance nightmare. With it, the config becomes a tunable control surface.

**Recommended**: Add `investigation_config.yaml` as Step 2.5 (after flash_triage, before verification_chain). Or, better: define it alongside Step 2 since the flash triage scoring dimensions and thresholds need to be configurable.

---

## Finding 5: investigation_loop.py -- High SRP Violation Risk at 300 Lines

**Rating**: HIGH

The plan estimates `investigation_loop.py` at ~300 lines. Per §3.1, 250 lines is the soft threshold for investigation. At 300 lines, this module is at the HARD threshold. Examining its responsibilities:

1. **HVR loop engine**: Hypothesis generation, verification orchestration, refinement
2. **Thread management**: Create/update/prune parallel investigation threads
3. **Context management**: Tier 1-4 context folding, compression checkpoints
4. **Budget tracking**: Remaining token/tool-call budget at each step
5. **Diminishing returns detection**: Confidence delta calculation, stop conditions
6. **LLM interaction**: Prompt construction for Pro model calls, response parsing

That is 6 distinct responsibilities. Even at a very dense 50 lines per responsibility, it's at the hard ceiling. Realistically, a clean implementation of these 6 concerns would be 400-600 lines.

**Recommended**: Pre-split investigation_loop.py into 3 modules:
- `pipeline/investigation_loop.py` (~150 lines): HVR loop orchestrator (H -> V -> R cycle)
- `pipeline/thread_manager.py` (~100 lines): Thread CRUD, hypothesis state, pruning
- `pipeline/budget_guard.py` (~80 lines): Token tracking, diminishing returns, stop conditions

This keeps each module under soft threshold and maps to single responsibilities.

---

## Finding 6: Investigation Loop Has No Circuit Breaker

**Rating**: HIGH

The research documents (heuristic-workflow-2 §1.1, heuristic-workflow-4 §4) explicitly warn about ReAct loop failures: infinite loops, exploration-order sensitivity, and context bloat. The plan's HVR loop (Phase 2) has:

- Diminishing returns detection (`confidence gain < 5% -> stop`)
- Confidence thresholds (`>= 0.7 -> decide, < 0.4 -> abandon`)

But it LACKS:
1. **Hard iteration cap per thread**: No `max_iterations` mentioned for HVR rounds (the research doc recommends 3, but this should be configurable and enforced at the code level, not just a prompt instruction)
2. **Total wall-clock timeout**: 587 articles + investigation could run for minutes. What stops it?
3. **API call failure cascade**: If `fred_api` is down, does the loop retry forever? What about partial failures?
4. **Graceful degradation**: If budget exhausted mid-loop, does it crash or summarize partial results?

The current `app.py` is strictly linear (9 steps, each completes or fails). The proposed investigation loop is non-linear (conditional branching, loops). This requires defensive coding that the current codebase has no precedent for.

**Recommended**: Add to `investigation_config.yaml`:
```yaml
safety:
  max_iterations_per_thread: 3
  max_wall_clock_seconds: 300
  api_call_timeout_seconds: 30
  max_consecutive_api_failures: 3
  graceful_degradation: true  # summarize partial results on timeout
```

And implement a `CircuitBreaker` pattern (the project already has `gateway/circuit_breaker.py` -- reuse it).

---

## Finding 7: Model Provider Mismatch -- DeepSeek vs Anthropic Token/Pricing Model

**Rating**: MEDIUM

The research documents benchmark patterns on Anthropic models (Haiku/Sonnet/Opus). The plan's token estimates derive from Anthropic pricing. However:

1. **MarketMind uses DeepSeek** (DeepSeek Flash / DeepSeek Pro), routed through `gateway/async_client.py`
2. DeepSeek Flash has different context windows and pricing than Anthropic Haiku
3. DeepSeek's Flash model may not support the same structured JSON output reliability as Claude Haiku

The research doc (heuristic-workflow-4 §2) recommends Haiku for Flash tier, but MarketMind's `gateway/async_client.py` uses DeepSeek. The plan is silent on whether a model migration is needed or whether DeepSeek Flash can handle 587 headlines in a single call.

**What to verify before implementation**:
1. DeepSeek Flash max context window size (needs to fit ~30K input tokens for 587 headlines)
2. DeepSeek Flash structured JSON output reliability (F1 score on scoring task)
3. Token cost comparison: DeepSeek Flash x 587 articles vs Anthropic Haiku

---

## Finding 8: Flash Triage 100 Lines Estimate Is Optimistic

**Rating**: MEDIUM

The plan estimates `flash_triage.py` at ~100 lines. The current `flash_preprocessor.py` is 148 lines and handles a SIMPLER task (batch signal extraction for 50 articles). The new module must handle:

1. 587 articles instead of 50 (~12x data volume)
2. 5-axis scoring (more complex output schema)
3. New output format (FlashScore dataclass vs FlashSignal dataclass)
4. Batch management: 587 articles in ~40 batches of 15 (vs current ~4 batches of 15)
5. Source tier weighting, cross-source flags
6. Category classification (macro/company/geopolitical/sentiment/technical)
7. API trigger mapping per article
8. Output deduplication (cross-source clusters)

Even a minimalist implementation with these features would be 180-250 lines. At 250, it hits the soft threshold and needs SRP investigation.

**Recommended**: Budget 150-200 lines and accept it may hit soft threshold. The module's single clear responsibility ("score and classify headlines") justifies the size.

---

## Finding 9: Shadow Ecosystem Timing Shift Is Unaddressed

**Rating**: MEDIUM

Current pipeline runs shadows at Step 5 (after L1-L3 analysis). The new flow introduces a non-deterministic investigation loop between Steps 2 and 5. If the investigation loop takes 60-120 seconds (multiple LLM calls + API queries), the shadows are delayed.

The plan states shadows still receive "原始新闻+市场数据" -- this is correct. But there is an unstated dependency:

**Temporal ordering**: The investigation loop's output (logic chain) arrives AFTER shadow analysis completes. This means:
- Shadows cannot respond to the main AI's logic chain findings (by design -- this is the independence guarantee)
- But the ELITE shadow awakening in Gate 2 depends on USER discussion of findings, not system timing. If the user discusses the logic chain in Gate 2 AFTER shadows have analyzed, ELITE awakening works correctly.
- However, if the shadows' event scan detects something the main AI misses, and the main AI is still in its HVR loop, there's no mechanism for the shadow to alert the main AI. This is by design (independence), but the plan should acknowledge this trade-off.

**Recommended**: No code change needed, but the plan should document that the investigation loop is intentionally blind to shadow findings, and vice versa -- consistent with existing information broadcast rules.

---

## Finding 10: Decision Stage Input Transformation Is Undefined

**Rating**: MEDIUM

Currently `decision.py:generate_decision()` accepts structured inputs from L1, L2, L3. The new logic chain output is a fundamentally different shape:

Old input to decision:
```
Layer1Result (structured: event_grade, quadrant, sentiment, etc.)
Layer2Result (structured: macro_quadrant, ticker_candidates, etc.)
Layer3BatchResult (structured: green_lights, results)
```

New potential input to decision:
```
LogicChain (narrative flow: hypothesis -> evidence -> refinement -> conclusion)
```

The decision stage's system prompt (`DECISION_SYSTEM_PROMPT`) is designed for structured layer outputs. Feeding it a narrative logic chain would require a prompt rewrite and may produce lower-quality decision cards because:
1. The structured format enables the decision prompt to extract specific fields (quadrant, green lights, resonance verdict)
2. A narrative logic chain requires the decision model to parse unstructured text for the same information
3. This adds latency, token cost, and potential parsing errors

**Recommended**: Design a `DecisionInput` dataclass that the logic chain builder outputs directly, preserving structured fields the decision stage needs. The logic chain narrative is retained as supplementary context, not the primary input.

---

## Finding 11: No Backward Compatibility or Feature Flag Strategy

**Rating**: LOW

The plan proposes a complete replacement of Step 2 with no fallback. If the investigation loop encounters a bug, fails on a particular news day, or exceeds budget, there is no path to revert to the old pipeline.

**Impact**: A single bug in the investigation loop could break the entire daily pipeline with no degraded mode.

**Recommended**: 
1. Implement as a feature flag: `config.heuristic_browsing_enabled` (default: False initially)
2. In `app.py`, branch at Step 2:
```python
if config.heuristic_browsing_enabled:
    scores = await triage_batch(news_items)
    logic_chains = await run_investigation_loop(scores, config)
    # feed logic chains to decision
else:
    signals = await preprocess_batch(news_items[:50])  # old path preserved
    l1_result = await analyze_layer1(signals[:15], news_items)
    ...
```
3. This preserves the old pipeline as a fallback and allows A/B comparison of output quality

---

## Finding 12: Config/investigation_config.yaml Location Mismatch

**Rating**: LOW

The plan places the config at `config/investigation_config.yaml`. The existing project only has Python config modules in `config/` (settings.py, asset_universe.py, source_authority.py). Adding a YAML file introduces a second config format. Either:

1. Keep as YAML (familiar, human-readable, easy to tune) -- but requires a YAML parser dependency not currently in the project
2. Move to Python dataclass (e.g., `config/investigation_config.py`) consistent with existing pattern -- but less tunable without code changes

**Recommended**: Use Python dataclass for consistency with existing `config/settings.py` pattern, but expose budget limits as class attributes that can be overridden by environment variables (consistent with `MarketMindConfig.from_env()`).

---

## Summary Matrix

| # | Finding | Rating | Effort to Fix | Blocks Implementation? |
|:--:|---------|:------:|:-------------:|:----------------------:|
| 1 | L1-L3 pipeline fate unspecified | CRITICAL | Medium | YES -- must decide before any code written |
| 2 | Token budget off by 10-15x | CRITICAL | Low (fix config) | YES -- investigation_config.yaml needed first |
| 3 | Implementation sequence violates PICA | HIGH | Low (reorder steps) | YES -- test-before-integrate is mandatory |
| 4 | investigation_config.yaml missing from steps | HIGH | Low (add step) | YES -- prerequisite for modules 3-5 |
| 5 | investigation_loop.py SRP violation risk | HIGH | Medium (pre-split) | No -- can be fixed during implementation |
| 6 | No circuit breaker in investigation loop | HIGH | Medium | No -- but risks runtime failures |
| 7 | Model provider mismatch (DeepSeek vs Anthropic) | MEDIUM | Low (verification) | No -- but token estimates change |
| 8 | flash_triage.py line estimate optimistic | MEDIUM | Low (re-estimate) | No |
| 9 | Shadow timing shift unaddressed | MEDIUM | Low (document) | No |
| 10 | Decision stage input transformation undefined | MEDIUM | Medium | Partially -- needed before Step 6 |
| 11 | No feature flag / backward compat | LOW | Low | No -- nice to have |
| 12 | Config file format inconsistency | LOW | Low | No -- nice to have |

## Bottom Line

The plan is architecturally sound in concept: the 3-tier progressive disclosure pattern (Flash gate -> Pro browse -> Deep verify) is well-supported by the research and maps cleanly to MarketMind's existing module structure. The shadow independence guarantees are preserved.

However, the plan has **two blocking issues** that must be resolved before implementation:

1. **Token budget is wrong by an order of magnitude** (Finding 2). The actual 157K token estimate must be reflected in the budget, and `investigation_config.yaml` must be created with explicit caps before any module is written. Otherwise the system will exhaust its budget mid-session.

2. **The fate of L1-L3 is unspecified** (Finding 1). The plan says "replace Step 2" but the new workflow replaces Step 2 AND Step 3 AND Step 4 partially. You cannot write `flash_triage.py` without knowing what its output consumers will be (existing L1? new investigation_loop? both?).

**Recommended next action**: Resolve Findings 1 and 2 before writing any code. The remaining findings can be addressed during implementation.

---

**Updated**: 2026-05-17 -- Architecture audit complete. 12 findings, 2 CRITICAL, 4 HIGH, 4 MEDIUM, 2 LOW.
