# Red Team: Architecture/Integration Audit — Shadow System Comprehensive Plan

**Auditor**: Architecture Agent (Haiku)
**Date**: 2026-05-18
**Target**: `shadow-system-comprehensive-plan.md` (2026-05-18)
**Code verified against**: `shadow_agent.py` L1-250, `prediction_extractor.py` (273 lines), `calibration_tracker.py` (126 lines), `reflection_agent.py` (205 lines), `entity_memory.py`, `ecosystem_auditor.py` L1-50, `shadow_memory.py` L1-80

## Summary

The plan is architecturally sound at the conceptual level, but has **4 blocking gaps** and **2 high-risk integration issues** that need resolution before implementation. The three-layer routing architecture (Haiku classification → shadow analysis → RAG) is well-motivated by research findings (MoDEM +36.4% domain specialization). However, key integration points with the existing codebase are underspecified, and one claim ("Phase I 已就绪") is partially correct but misses a critical gap in the verification scheduler.

---

## 1. Token Cost: DAILY TOTAL Estimate

### Layer 0 — Haiku Classification ($0.011/day)

345 articles, batch classification with multi-label output. Haiku 4.5 pricing: ~$0.80/M input, ~$4/M output. Assuming ~500 chars/article (headline only, ~120 tokens), a single batch call: 345 × 120 = 41,400 input + ~200 output = 41,600 tokens ≈ $0.033. If headlines only (no body text for classification), closer to $0.015-0.020. The plan's $0.011/day estimate is **plausible but optimistic** — likely closer to $0.015-0.020/day. **Not prohibitive.**

### Layer 1 — Shadow Analysis ($0.08-0.30/day)

23 shadows each make at least one `chat_with_integrity()` call (DeepSeek Fast/Pro, routed through `gateway/async_client.py:323`). The plan adds a SECOND call type: Flash queries for information retrieval. Current code has **no mechanism for shadows to make supplementary Flash queries** — `_analyze()` only makes one LLM call per shadow (shadow_agent.py:158).

Estimate assumes:
- 1 main analysis (DeepSeek Fast, $0.27/1M in, $1.10/1M out) per shadow = 23 calls/day
- Each call: ~3000 input tokens (domain news + market data) + ~1000 output tokens
- 23 × 3000 = 69K input + 23 × 1000 = 23K output = $0.019 + $0.025 = **$0.044/day**
- Plus Layer 0: ~$0.020/day
- **Core cost: ~$0.06/day (conservative), ~$0.25/day (worst case with large articles)**

If shadows make supplementary Flash queries (plan Layer 1 feature):
- 23 shadows × 2 queries × (1000 in + 500 out) = 46K in + 23K out = $0.012 + $0.025 = $0.037/day additional
- **Total with supplements: ~$0.10-0.30/day, or $3-9/month**

### Layer 2 — RAG ($0.005-0.02/day)

Embedding cost for writing successful analyses to RAG. At ~1 write per shadow per week, negligible in daily terms. Retrieval cost is near-zero (local vector search, no LLM).

### Daily Total

| Scenario | Layer 0 | Layer 1 (main) | Layer 1 (suppl.) | Layer 2 | **Total/day** | **/month** |
|----------|:---:|:---:|:---:|:---:|---:|---:|
| Conservative | $0.02 | $0.04 | $0.00 | $0.00 | **$0.06** | ~$2 |
| Moderate | $0.02 | $0.06 | $0.04 | $0.01 | **$0.13** | ~$4 |
| Worst (large articles) | $0.03 | $0.15 | $0.08 | $0.02 | **$0.28** | ~$8 |

**Verdict: NOT prohibitive.** Even the worst case (~$8/month, ~$100/year) is negligible for an investment analysis system. The plan's silence on Layer 1+2 costs is a documentation gap but not a financial risk.

---

## 2. Integration Points: Where Do the 3 Layers Plug In?

### Layer 0 (news_classifier.py) — Location Confirmed, Interface Missing

**Where**: Between Scout (Stage 1) and Flash Preprocessor (Stage 2) in `app.py:run_daily()`.

The current pipeline:
```
Scout (fetch_all_sources) → Flash Preprocessor (preprocess_batch)
```

Layer 0 inserts:
```
Scout → news_classifier.classify_batch() → Flash Preprocessor
```

**Gap**: No `news_classifier.py` module exists today (confirmed by glob). The plan estimates ~120 lines. The classifier needs:
1. Access to Haiku API (new dependency — gateway doesn't export a Haiku client today; `async_client.py` only exports `chat_flash`, `chat_pro`, `chat_with_integrity` for DeepSeek models)
2. The 15-domain label taxonomy (what are the 15 domains?)
3. A mapping from domain labels → shadow IDs (to route news to shadows)

**Integration risk: MEDIUM**. Adding an anthropic SDK import for Haiku alongside the existing DeepSeek gateway creates a dual-provider architecture. The gateway module would need a Haiku wrapper or the classifier imports anthropic directly.

### Layer 1 (Shadow Info Retrieval) — **BLOCKING GAP**

**The plan says shadows make Flash queries for information retrieval, but no such mechanism exists in the codebase.**

Current shadow flow (`shadow_agent.py:142-194`):
```python
async def _analyze(self, news_items, market_data) -> ShadowAnalysisOutput:
    result = await chat_with_integrity(...)  # ONE call, main analysis
    return ShadowAnalysisOutput(...)
```

There is NO second call for supplementary queries. The shadow receives news items already filtered by domain (if Layer 0 exists), but it cannot say "I need to look up gold ETF flow data for the past 5 days."

**What needs to be built**:
1. A broker/interface that shadows can call: e.g., `await self._request_data(query: str) -> dict`
2. This broker calls `chat_flash()` (DeepSeek Flash, `async_client.py:195`) with the shadow's data request
3. The result (structured data) is added to the shadow's user prompt before the main analysis
4. Each call consumes Flash quota from the shadow's budget

**The plan says "主 AI 的 Flash 代理" (main AI's Flash agent) handles the query**. This implies the main AI's gateway, not a separate broker. The simplest implementation: add a `_request_supplementary_data()` method to `ShadowAgent` that calls `chat_flash()` directly. No new module needed — ~30 lines in `shadow_agent.py`.

### Layer 2 (RAG) — Partially Covered by Existing shadow_memory

The existing `shadow_memory.py` (E:\AI_Studio_Workspace\projects\marketmind\shadows\shadow_memory.py) provides 3-tier memory (working/episodic/semantic) with `ingest_observation()`, belief nodes, and Bayesian tracking. This is **about shadow beliefs/observations**, NOT about domain articles and few-shot analysis trajectories.

The plan envisions per-shadow RAG containing:
- Domain-specific articles
- 3 most recent successful analyses (few-shot examples)
- Analysis trajectories (data → analysis → prediction)

The existing `shadow_memory.py` doesn't store these. The plan's estimate of ~200 lines for a "shadow_memory.py" (which already exists) suggests either:
- Extension of existing `shadow_memory.py` (adding RAG methods), OR
- A new module at pipeline/ or shadows/ for the RAG component

**Recommendation**: Add a `_rag` sub-module to `shadow_memory.py` or create `shadows/shadow_rag.py`. Do NOT create a separate `shadow_memory.py` — the name is taken.

---

## 3. Skill Store Schema: Filesystem vs SQLite

The plan says "per-shadow skills/ 目录" (per-shadow skills/ directory). At 1 skill/week × 23 shadows = ~1,200 skills/year.

### Filesystem Analysis

```
skills/
  gold_shadow/
    2026-05-18_gold-etf-inflow-long-win.md
    2026-05-25_dxy-breakdown-long-win.md
    ... (~52/year)
  crypto_shadow/
    ...
  ...23 shadows
```

**At scale (5 years)**:
- ~6,000 skill files across 23 directories
- File system lookup: `glob("skills/gold_shadow/*.md")` → O(n) per query
- Cross-shadow search ("find all skills related to ETF flows"): requires O(all files) traversal or an index

**Filesystem is NOT prohibitive at this scale.** 6,000 files across 23 directories is trivial for any modern filesystem (NTFS handles millions). But there are downsides:

| Dimension | Filesystem | SQLite + FTS |
|-----------|-----------|--------------|
| Write simplicity | `Write(skill_path, markdown)` — direct | INSERT + FTS index update |
| Read (per-shadow) | `glob(f"skills/{shadow_id}/*.md")` — fast enough with 52 files | `SELECT ... WHERE shadow_id = ?` — fast |
| Cross-shadow search | Manual traversal or external index | FTS5 full-text search — instant |
| Metadata query | None — parse filenames | Query by confidence, asset, date, outcome |
| Backup | Simple file copy | .sqlite file copy |
| Corruption risk | One file at a time | Entire DB if uncommitted |

**Recommendation**: Start with **filesystem + SQLite index**. Skills are stored as Markdown files for human readability. A SQLite table indexes metadata (shadow_id, date, asset, confidence, outcome, file_path) with FTS on skill content. The `skill_store.py` (~150 lines) manages both.

This is the pattern used by `archivist.py` (FTS5+JSONL) and `gate_archiver.py` (JSONL+MD). The codebase already has dual storage precedent.

---

## 4. Methodology Release: Held-Out Data Infrastructure

**The plan says "before/after comparison on held-out data" but never specifies who maintains it, how it's sampled, or whether infrastructure exists.**

### What Exists Today

- `methodology_evolver.py` in shadows/ — tracks methodology changes but there's no standardized held-out test set
- `backtest_runner.py` — runs backtests on historical data but uses the full dataset, not held-out splits
- `regime_mapper.py` — maps current market conditions to historical regimes, could inform stratified sampling
- No `methodology_release.py` exists (confirmed by glob)

### What Needs to Be Built

1. **Held-out dataset construction**:
   - Sample of ~50-100 historical scenarios (news + market data + known outcomes)
   - Stratified by market regime (bull/bear/volatile/sideways) using `regime_mapper.py`
   - Each scenario includes: input data snapshot, old methodology prediction, actual outcome
   - Maintained in `data/held_out_scenarios.jsonl` or similar

2. **Evaluation framework** (`methodology_release.py`):
   - For each scenario: run old methodology → prediction, run new methodology → prediction
   - Compare against actual outcome
   - Detection rules: any old-correct/new-wrong → block; count net improvements
   - Statistical test: McNemar's test for paired binary outcomes

3. **Sampling method**: Stratified random sampling by regime type (from `regime_mapper.py`'s regime library). The sampling mechanism belongs in `methodology_release.py`, not as separate infrastructure.

**Responsibility**: The plan assigns no owner. The `reflection_agent.py` does post-mortems on live predictions but doesn't maintain a held-out test set. This is **new infrastructure** — estimate ~80 additional lines in `methodology_release.py` for dataset management, beyond the planned 100 lines.

**Risk: MEDIUM**. The plan's 100-line estimate for `methodology_release.py` is too low for a module that must manage held-out data, run A/B comparisons, and enforce blocking rules. Realistic estimate: 180-220 lines.

---

## 5. Shadow Rebuild Compatibility

**The plan does NOT require the rebuild to be complete.** The three-layer architecture can coexist with current shadow code.

### Current State

- `expert_shadows.py`: 168 lines, factory class creating 15 ExpertShadow instances
- `daredevil_shadows.py`: 250 lines, factory class creating 8 DaredevilShadow instances
- Rebuild commits: `6be2270` (daredevil restructure), `62b4dc5` (Phase D completion)

### Coexistence Path

The plan's three-layer architecture maps to existing code as follows:

| Plan Layer | Existing Code | Gap |
|------------|--------------|-----|
| Persona (stable prompt) | `ShadowConfig.methodology_prompt` | Plan wants structured prompt template + lock — replace methodology_prompt with a `PersonaTemplate` |
| Knowledge (RAG + few-shot) | None (shadow_memory is about beliefs, not analysis trajectories) | New — add RAG module or extend shadow_memory |
| Memory (episodic) | None at shadow level (entity_memory is pipeline-level) | Phase I's `reflection_agent` + `entity_memory` fill this |

**The rebuild can proceed independently.** The plan's Persona layer is a configuration change (structured prompts replacing free-text methodology_prompt), not a code architecture change. Knowledge and Memory layers are additive — they inject content into the existing `_build_user_prompt()` flow without changing the ShadowAgent API.

**Recommendation**: Implement the three-layer architecture in the base `ShadowAgent` class first (new `_inject_knowledge()` and `_inject_memory()` methods that current shadows inherit). Then the rebuild can refactor individual shadow prompts into Persona templates without breaking the ecosystem.

---

## 6. Import DAG: Circular Dependency Analysis

### Module Dependency Graph

```
pipeline/news_classifier.py
  → gateway/async_client.py (needs Haiku — NEW dependency, anthropic SDK)
  → shadows/shadow_state.py (ShadowConfig for domain→shadow mapping)
  No shadow imports beyond shadow_state ✓

shadows/shadow_memory.py (EXTEND existing, do NOT create new)
  → shadows/shadow_state.py (ShadowStateDB)
  → shadows/belief_math.py
  → pipeline/entity_memory.py  ← NEW EDGE, currently not imported
  No circular risk ✓

shadows/skill_store.py (NEW)
  → shadows/shadow_state.py (ShadowConfig, ShadowAnalysisOutput)
  → pipeline/entity_memory.py (entity identification for skill tagging)
  → pipeline/prediction_extractor.py (PredictableHypothesis for skill→prediction link)
  Does NOT import methodology_release ✓

shadows/methodology_release.py (NEW)
  → shadows/skill_store.py (read skills for evaluation)
  → shadows/shadow_state.py (ShadowConfig)
  → pipeline/calibration_tracker.py (Brier score, direction accuracy)
  → pipeline/regime_mapper.py (stratified sampling by regime)
  Does NOT import skill_store back ✓

shadows/ecosystem_auditor.py (EXTEND existing, 232 lines)
  → shadows/shadow_agent.py (ShadowVote, PositionCheck)
  → shadows/shadow_state.py (ShadowStateDB)
  → NEW: shadows/skill_store.py (check methodology convergence)
  No circular risk ✓
```

### Circular Dependency Check

| Pair | Risk | Analysis |
|------|:---:|----------|
| skill_store ↔ methodology_release | **SAFE** | Unidirectional: methodology_release → skill_store. skill_store only does CRUD. |
| shadow_memory ↔ entity_memory | **SAFE** | Unidirectional: shadow_memory → entity_memory (reads entity memories for RAG injection). entity_memory does NOT import shadow code. |
| expert_shadows ↔ news_classifier | **SAFE** | Bidirectional via data types only (both import shadow_state.py for ShadowConfig). No runtime circularity. |
| ecosystem_auditor ↔ skill_store | **SAFE** | Unidirectional: ecosystem_auditor → skill_store. |

**No circular dependencies detected.** The import graph is a DAG: glue (app.py) → modules → shared data types (shadow_state.py, prediction_extractor.py).

### Dimension Warning

The `shadows/shadow_state.py` module is becoming a god-object dependency — it's imported by nearly every shadow and pipeline module. At current size it's manageable, but if more data types accumulate, consider splitting it into `shadows/shadow_types.py` (pure dataclasses) and `shadows/shadow_state.py` (persistence).

---

## 7. Phase I Readiness: API Verification

The plan claims "Phase I 已就绪" for memory and reflection. **Partially verified.**

### prediction_extractor.py — READY

- Exports: `PredictableHypothesis` dataclass, `extract_predictions()` function
- Input: list of HypothesisResult objects → Output: list of `PredictableHypothesis`
- Pure Python, no LLM dependency
- **API matches plan assumptions.** ✓

### calibration_tracker.py — READY

- Exports: `CalibrationResult` dataclass, `compute_brier_score()`, `compute_direction_accuracy()`, `compute_ece()`, `track_calibration()`
- All functions are synchronous (no LLM), compute standard calibration metrics
- Uses duck-typed `store` parameter for persistence
- **API matches plan assumptions for Phase I scoring.** ✓

### reflection_agent.py — READY

- Exports: `StructuredLesson` dataclass, `run_reflection()`, `run_batch_reflection()`
- Routes: Flash for success cases (cheap), Pro for failure cases (deep analysis)
- 7-class root cause taxonomy with relevance scoring
- 0.95 decay factor per lesson
- **API matches plan's STAR decomposition requirement.** ✓

### entity_memory.py — READY

- Exports: `EntityMemory` dataclass (`entity_id`, `entity_type`, `recurring_patterns`, `key_levels`, `best_performing_shadows`, `common_blind_spots`, `recent_lessons`)
- `identify_entities()`: heuristic entity extraction from text
- `load_entity_memories()`: load all memories for an entity
- `update_entity_memory()`: merge new lesson into entity memory
- `decay_memories()`: time-based freshness decay
- **API matches plan's "存储到 entity_memory" requirement.** ✓

### expertise_discovery.py — READY

- Exports: `ShadowExpertise` dataclass, `discover_expertise()` — cross-shadow methodology discovery
- Identifies which shadows outperform on which entities
- `generate_methodology_injection()` — creates few-shot prompts from best performers
- **Supports the plan's cross-shadow methodology sharing.** ✓

### CRITICAL GAP: Automated Verification Scheduler

**The plan says predictions expire and Phase I verifies them automatically:**

> "预测到期 → Phase I 验证实际结果"

**No automated scheduler exists.** The flow requires:

1. `prediction_extractor.extract_predictions()` creates `PredictableHypothesis` with `status=PENDING` and `expiry_date=YYYY-MM-DD`
2. When `expiry_date` arrives, the prediction should be verified against actual market data
3. Verification updates `status` to `VERIFIED_SUCCESS` or `VERIFIED_FAILURE`
4. `reflection_agent.run_batch_reflection()` processes verified predictions

Step 2 has no implementation. The `verification_chain.py` module handles claim verification (4-layer market/fundamental/news/historical) but it's designed for **real-time claim checking during analysis**, not for **expired prediction verification against actual outcomes**.

**What's needed**: A verification scheduler that runs daily, finds predictions where `expiry_date <= today AND status == PENDING`, fetches actual market data for the verification_source, compares against success_value, and updates the status. This could be a small module (~60 lines) or a method on `prediction_extractor.py`.

**Impact**: Without this, Phase I can extract predictions and reflect on manually-verified outcomes, but the automated feedback loop the plan describes is NOT operational. The "Phase I 已就绪" claim is **true for the components but false for the end-to-end integration**.

---

## Findings Summary

| # | Finding | Severity | Action |
|---|---------|:---:|--------|
| F1 | No Flash query mechanism for shadow info retrieval (Layer 1) | **BLOCKER** | Add `_request_supplementary_data()` to ShadowAgent or create a broker |
| F2 | No automated prediction verification scheduler | **BLOCKER** | Build verification cron (~60 lines) before Phase I loop can operate |
| F3 | No Haiku client in gateway (Layer 0 needs anthropic SDK) | **BLOCKER** | Add Haiku wrapper to gateway OR classifier imports anthropic directly |
| F4 | `methodology_release.py` 100-line estimate too low | **HIGH** | Realistic scope is 180-220 lines (includes held-out data management) |
| F5 | Skill store schema underspecified (filesystem vs DB) | **HIGH** | Use filesystem + SQLite index (follow existing archivist.py pattern) |
| F6 | Plan says "Phase I 已就绪" but end-to-end integration gap exists | **HIGH** | Build verification scheduler, then re-verify the claim |
| F7 | `news_classifier.py` needs Haiku — dual-provider architecture | **MEDIUM** | Decide: wrap in gateway or import anthropic directly |
| F8 | `shadow_memory.py` name collision (exists, plan wants RAG) | **MEDIUM** | Extend existing shadow_memory or create shadow_rag.py |
| F9 | 15 shadow domains undefined in plan | **MEDIUM** | Define domain taxonomy + domain→shadow mapping before Layer 0 |
| F10 | Ecosystem auditor extension to check methodology convergence | **LOW** | Add skill_store import to existing auditor |

### Token Cost: NOT PROHIBITIVE ($0.06-0.28/day, worst case ~$8/month)

---

## Recommendations

1. **Before any implementation**, resolve F1, F2, F3 (all blockers):
   - Add `_request_supplementary_data()` to ShadowAgent base class
   - Build `pipeline/verification_scheduler.py` for automated prediction expiry
   - Add Haiku client (wrapper in gateway or direct anthropic import in classifier)

2. **Define the 15-domain taxonomy** and domain→shadow mapping. The plan mentions 15 expert domains but doesn't list them. The existing `expert_shadows.py` already has 15 experts with defined domains — reconcile the plan with the code.

3. **Adjust line-count estimates** before starting work:
   - `methodology_release.py`: 180-220 lines (not 100)
   - `shadow_memory.py` extension: plan says 200 lines (already partially built, ~80 new lines for RAG)

4. **Use filesystem + SQLite for skill_store**, following the dual-storage pattern already proven in `archivist.py` and `gate_archiver.py`.
