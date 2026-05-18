# Phase I Architecture Audit — Red Team (Architecture/Integration)

**Date**: 2026-05-18 | **Auditor**: Red Team (Architecture/Integration Agent)
**Source**: `E:\AI_Studio_Workspace\.claude\plans\phase-i-self-evolving-architecture.md`
**Codebase**: Worktree `agent-a0f3559a33f302bb0` (Phase H Gate 1, commit `5a5378b`)

---

## Executive Summary

**Verdict**: BLOCKED — 2 CRITICAL findings that must be resolved before implementation begins.

The Phase I plan is conceptually sound (6-layer learning architecture, self-improving system) but has two fatal integration gaps: (1) the proposed insertion point (`investigation_loop.py` HVR cycle) references a file that does not exist in the codebase, and (2) the plan references `HypothesisResult` as the data type to extend, but this type does not exist in the codebase either. The current pipeline produces `DecisionOutput` (a list of `DecisionCard` + optional `NoTradeCard`), not structured hypotheses. Phase I needs a concrete bridging mechanism from the existing pipeline outputs to the new `PredictableHypothesis` extraction pipeline.

Additionally, 3 HIGH-severity risks around storage growth, batch reliability, and import DAG compliance were found. These should be addressed in the implementation plan before coding begins.

---

## Q1: Pipeline Insertion (CRITICAL)

**Plan claim**: "批处理独立运行，不阻塞每日分析" — reflection_agent runs as batch, doesn't block daily analysis.

**Finding**: The plan does not specify WHEN reflection_agent runs, and the proposed insertion point does not exist.

The plan says predictions are extracted "在 `investigation_loop.py` 的 HVR 循环完成后" after Stage 2. However, `investigation_loop.py` does not exist in the codebase. A grep for `investigation_loop`, `hvr`, and `HVR` across all pipeline modules returned zero matches for a file by that name. The only mention of "investigation" is in `layer1_interactive.py` (line 170) as a section header describing tool availability — not a processing module.

**Current pipeline flow** (app.py lines 33-496):
```
Stage 0: Shadow Mother init
Stage 0.5: Economic calendar check
Stage 1: News fetch
Stage 2: Flash preprocessing
Stage 3: L1 Interactive (Socratic dialogue)
Stage 3.5A/B: Broadcast to shadows
Stage 3.6: Launch shadow ecosystem (background)
Stage 4: L2 Fundamental
Stage 4.5: ELITE shadow check
Stage 6: L3 Technical
Stage 7: Red Team
Stage 8: Resonance
Stage 8.5: Shadow consensus display
Stage 9: Decision
Stage 10: Archive
```

There is no HVR cycle. There is no investigation_loop. The pipeline produces `DecisionOutput` at Stage 9, not `HypothesisResult` objects.

**Timing impact**: If reflection_agent runs as a cron job at midnight, yesterday's lessons are not available for today's analysis — they would only feed into tomorrow's analysis. This means every daily analysis runs with lessons that are at least 1 day stale. The plan's claim that "复盘批处理独立运行，不阻塞每日分析" is a statement of non-interference, not a specification of timing.

**Recommendation**:
1. Specify exact timing: reflection_agent should run at session START (before Stage 0), checking for expired predictions from previous sessions. This ensures yesterday's lessons are available for today's analysis.
2. Define the prediction extraction point explicitly. Since `investigation_loop.py` does not exist, extraction should happen immediately after Stage 9 (Decision), using `DecisionOutput.decision_cards` as input. Each `DecisionCard` contains `thesis`, `target_price`, `max_hold_days`, `stop_loss` — these map cleanly to `PredictableHypothesis` fields.
3. Add a new Stage 9.5: "Prediction Extraction" that converts DecisionCards → PredictableHypotheses via Flash LLM call.

---

## Q2: SQLite Schema & Scale (HIGH)

**Plan claim**: 4+ new tables in learning_store.py, "与影子 SQLite 数据库并存".

**Finding**: The existing SQLite schema is already very large. `shadow_db.py` defines 20 tables spanning 540 lines (over the 500-line hard ceiling per CLAUDE.md §3.1). Adding 4+ new tables (predictions, lessons, entity_memories, calibration_data, expertise) to the same database means either:
- (a) Adding to `shadow_db.py` → further bloating an already-over-ceiling file
- (b) Creating a separate `learning.db` → cleaner but requires managing two SQLite connections

**Scale analysis** (6 months, 21 shadows, daily analysis):
| Table | Est. rows/day | Est. rows/6mo | Row size (est.) | Total size |
|-------|:---:|:---:|:---:|---:|
| predictions | 21-63 (1-3 per shadow) | 3,800-11,300 | ~500 bytes | ~5.5 MB |
| lessons | 0-21 (only for expired) | 0-3,800 | ~1 KB | ~3.8 MB |
| entity_memories | ~50 entities | static-ish | ~2 KB | ~100 KB |
| calibration_data | 1 per entity/shadow | ~1,000 | ~200 bytes | ~200 KB |
| expertise | 1 per shadow per entity | ~200 | ~300 bytes | ~60 KB |

Total estimated 6-month growth: ~10 MB. This is well within SQLite's capabilities (140 TB max). **Scale is not a concern for the database engine itself.**

**Missing indices**: The plan specifies no indices for the new tables. At minimum:
- `predictions`: index on `(status, expiry_date)` — needed for finding expired PENDING predictions
- `predictions`: index on `(entity_id, created_at)` — needed for entity memory queries
- `lessons`: index on `(entity_id, root_cause)` — needed for three-dimensional lookup
- `calibration_data`: index on `(entity_id)` — needed for expertise discovery

**Recommendation**:
1. Use a SEPARATE `learning.db` database file (not the shadows.db). This avoids further bloating `shadow_db.py` and keeps the learning system's schema independent. The `learning_store.py` module manages its own schema, migrations, and connections.
2. Add the four indices above to the `learning_store.py` schema specification.
3. The plan's claim that entity memories "不需要向量数据库" is correct — the scale is small enough for SQLite + JSON fields.

---

## Q3: Module Size Compliance (MEDIUM)

**Plan**: Lists 6 new modules with complexity labels (低/中) but no estimated line counts.

**Estimated line counts vs CLAUDE.md §3.1 limits** (soft: 250, hard: 500 for Python modules):

| Module | Complexity | Est. Lines | Risk |
|--------|:---:|:---:|------|
| `prediction_extractor.py` | 低 | 80-150 | Within limits |
| `calibration_tracker.py` | 中 | 200-350 | May exceed soft threshold; verify SRP |
| `reflection_agent.py` | 中 | 250-400 | May exceed soft threshold; likely SRP-clean (one concern) |
| `entity_memory.py` | 低 | 100-200 | Within limits |
| `expertise_discovery.py` | 中 | 200-350 | May exceed soft threshold; verify SRP |
| `learning_store.py` | 中 | 300-500 | HIGH RISK — storage modules tend to bloat (see shadow_state.py at 1,309 lines) |

**Key concern**: `learning_store.py` at "中" complexity. The existing `shadow_db.py` (schema + migrations) is 540 lines and `shadow_state.py` (CRUD + access control) is 1,309 lines. If `learning_store.py` follows the same pattern of combining schema, migrations, AND CRUD operations into one file, it will easily exceed 500 lines. The plan should split this into `learning_db.py` (schema + migrations) and `learning_store.py` (CRUD operations) from the start.

**Recommendation**:
1. Pre-split `learning_store.py` into `learning_db.py` (schema, migrations, table creation) and `learning_store.py` (CRUD operations). Follow the existing `shadow_db.py` + `shadow_state.py` split pattern.
2. Add a line-count budget to each module in the implementation plan. Target: all 6 modules under 400 lines (leaving headroom below the 500-line hard ceiling).
3. `calibration_tracker.py` should be two files if it combines statistical computation (Brier, ECE, Platt scaling) with tracker state management — split into `calibration_math.py` (pure functions) and `calibration_tracker.py` (state + storage).

---

## Q4: Import DAG (HIGH)

**Plan**: 6 new modules. The import relationships are underspecified.

**Proposed DAG** (inferred from plan descriptions):

```
Phase I modules:
  storage/learning_store.py       → sqlite3 only (no project imports)
  pipeline/prediction_extractor.py → gateway/async_client (Flash), pipeline/decision (DecisionCard)
  pipeline/calibration_tracker.py  → storage/learning_store.py, pure math (numpy?)
  pipeline/reflection_agent.py     → gateway/async_client (Pro), storage/learning_store.py
  pipeline/entity_memory.py        → storage/learning_store.py
  pipeline/expertise_discovery.py  → storage/learning_store.py, pipeline/calibration_tracker.py
```

**Compliance check against CLAUDE.md §3.1 extraction rules**:

1. **No back-imports**: Phase I modules import from `storage/learning_store.py` and `gateway/async_client.py` — both are lower in the DAG (infrastructure). No imports from `app.py` (glue) or sibling pipeline stages. **PASSES**.

2. **No import from shadows/**: The plan explicitly says "知识蒸馏只传递方法论框架，不共享原始分析（保持影子独立性）". This means expertise_discovery reads calibration data from learning_store, not from shadow_agent or shadow_state. **PASSES** — but requires that shadow calibration data gets written TO learning_store. See Q5.

3. **Import from Phase H modules**: The plan references `investigation_loop.py` which does not exist. If the plan is updated to extract predictions from `DecisionOutput.decision_cards`, Phase I imports from `pipeline/decision.py` (existing, stable). **PASSES** after plan correction.

4. **Potential circular dependency**: `expertise_discovery.py` imports from `calibration_tracker.py` to read per-shadow Brier scores. This is a DAG (expertise_discovery reads calibration_tracker's output), not circular. **PASSES**.

**Recommendation**:
1. Formalize the import DAG in the implementation plan. Add a diagram.
2. Ensure `learning_store.py` is the ONLY module that touches SQLite. All other Phase I modules go through it. This is the existing pattern (shadow_state.py wraps shadow_db.py).

---

## Q5: Shadow Ecosystem Integration (HIGH)

**Plan claim**: "shadow expertise is tracked" and "不修改影子分析流程（只增加评分层）".

**Finding**: Expertise tracking REQUIRES per-shadow calibration data, but the plan is ambiguous about HOW this data flows from shadows → calibration_tracker.

**Current shadow ecosystem**:
- `shadow_agent.py` (494 lines) — produces `ShadowAnalysisOutput` (insights, votes, methodology_notes)
- `shadow_state.py` (1,309 lines) — all CRUD + access control
- `shadow_memory.py` (572 lines) — belief nodes, observations, retirements
- `shadow_types.py` (81 lines) — ShadowVote, PositionCheck, ShadowAnalysisOutput

**Integration gap**: For Phase I to track shadow expertise, each shadow's predictions must be scored. This means:
- Each shadow's analysis must produce `PredictableHypothesis` objects (or a Flash call must extract them from shadow outputs)
- These predictions must be stored in `learning_store`
- When predictions expire, they must be verified against market data
- Brier scores must be computed per shadow per entity

**Does this require changes to shadow_agent.py?** YES — indirectly. Shadows produce `ShadowAnalysisOutput` which has `insights: list[str]` and `methodology_notes: str`. These would need to be run through prediction_extractor to produce structured predictions. This could be done:
- (a) In shadow_agent.py itself (adds code to a grandfathered file nearing hard ceiling)
- (b) In shadow_mother.py orchestrate_daily_cycle (adds a post-processing step)
- (c) As a standalone batch process that reads shadow_outputs from the DB

**Recommendation**: Option (c) — standalone batch. This keeps shadow_agent.py unchanged (per the plan's promise) and treats the learning layer as a consumer of shadow outputs, not a modifier of the shadow pipeline.

**Does this require changes to shadow_state.py?** NO — if learning data lives in a separate `learning.db`, shadow_state.py is untouched. The learning system reads shadow outputs from the existing `shadows.db` (using `get_raw_output()` with system-level access) and writes learning data to its own `learning.db`.

---

## Q6: Backward Compatibility — PredictableHypothesis (CRITICAL)

**Plan claim**: "当前 HypothesisResult 有时间窗口字段（`time_window: "2-4周"`）".

**Finding**: `HypothesisResult` DOES NOT EXIST in the codebase. A grep for `HypothesisResult` across all Python files returned zero matches.

**Existing data types in the analysis pipeline**:
```
Layer1Result → Layer2Result → Layer3BatchResult → DecisionOutput
                                                    ├── DecisionCard (ticker, direction, thesis, target_price, stop_loss, max_hold_days, ...)
                                                    └── NoTradeCard (thesis, supporting_evidence, ...)
```

`DecisionCard` is the closest existing type to what `PredictableHypothesis` needs. It has:
- `ticker` → maps to entity
- `direction` (long/short) → maps to direction
- `target_price` → maps to success_value
- `stop_loss` → maps to a failure condition
- `max_hold_days` → maps to prediction_window_days
- `thesis` → maps to hypothesis text

**What this means**: `PredictableHypothesis` is a NEW dataclass, not an extension of an existing one. **There is no backward compatibility issue** because there is nothing to be backward-compatible with. The plan's reference to `HypothesisResult` is a phantom — it describes what the plan authors *thought* existed.

**The real question**: Since Phase I adds NO new fields to existing dataclasses, the backward compatibility claim is vacuously true. But the integration question becomes: where do `PredictableHypothesis` objects get created?

**Recommendation**:
1. Define `PredictableHypothesis` as a standalone dataclass in a new `pipeline/predictable_hypothesis.py` (or add it to `session_context.py` alongside the other pipeline types).
2. Create `prediction_extractor.py` that takes `DecisionOutput` (or individual `DecisionCard` objects) as input and uses Flash to extract structured `PredictableHypothesis` objects.
3. Remove the reference to `HypothesisResult` from the plan — it's misleading.

---

## Q7: Phase I vs Phase H Integration (HIGH)

**Plan claim**: Phase I "从假设提取可验证预测" from Phase H outputs.

**Finding**: Phase H modules at root level produce enriched analysis but the final pipeline output is still `DecisionOutput` (from `pipeline/decision.py`). There is no Phase H module that produces `HypothesisResult` objects.

**Phase H modules that exist** (at root level of worktree):
- `pipeline/causal_review.py` (118 lines) — 3-step PMV post-mortem, not integrated into daily pipeline
- `pipeline/flash_preprocessor.py` (144 lines) — news → signals, feeds Stage 2
- `pipeline/forecast_tracker.py` (159 lines) — scenario predictions (A→B), uses forecast_scenarios table
- `pipeline/layer1_interactive.py` (967 lines) — L1 Socratic dialogue
- Various tools modules (l1_tools, l1_info_tools, l1_market_tools)

None of these produce structured hypothesis results. The `forecast_scenarios` table has `prediction_label` and `predicted_probability` fields but is designed for scenario forecasting (trigger_event → prediction_scenarios), not for the type of time-anchored single predictions that Phase I needs.

**Data flow analysis**:
```
Current: DecisionOutput → archive → done
Phase I needs: DecisionOutput → prediction_extractor → PredictableHypothesis → learning_store
                                                         ↓
                              (prediction expires) → reflection_agent → StructuredLesson → entity_memory
```

**The data flow IS clean** — Phase I reads from `DecisionOutput` which is a well-defined, stable output type. It does NOT need to import from Phase H modules. The plan's reference to `investigation_loop.py` is the only problem.

**Recommendation**:
1. Phase I only needs to import from `pipeline/decision.py` (for `DecisionOutput`, `DecisionCard`), `gateway/async_client.py` (for Flash/Pro calls), and `storage/learning_store.py`.
2. No imports from any Phase H module are required. The data flow is cleaner than the plan implies.
3. Remove all references to `investigation_loop.py` from the plan.

---

## Q8: Batch Processing Reliability (HIGH)

**Plan claim**: Reflection agent uses Pro (2000 tokens/expired prediction). Flash for root cause classification (500 tokens/prediction).

**Finding**: No retry mechanism, no dead letter queue, no timeout handling specified.

**API failure scenarios**:
1. Pro call fails (network error, API rate limit, token budget exhausted) → `PredictableHypothesis.status` stays "PENDING" forever
2. Flash root cause classification fails after Pro succeeds → StructuredLesson is partially created (missing root_cause)
3. Market data for verification is unavailable → prediction cannot be scored, stays PENDING

**The plan's cost optimization exacerbates this**: "仅对高价值预测（Brier >0.5）运行 Pro 复盘". But Brier score requires knowing the ACTUAL outcome. You cannot compute Brier until the prediction expires AND market data is available. This means the filtering logic is:
```
prediction expires → check actual outcome → compute Brier → if Brier > 0.5, run Pro reflection
```
The Pro call happens AFTER Brier computation, not before. This is correct for cost optimization but means the planning text is unclear — it should say "only run Pro reflection on predictions where the actual outcome significantly differs from the predicted probability (Brier > 0.25, not > 0.5; BS > 0.5 means the prediction was catastrophically wrong, which might justify the Pro cost)".

**Recommendation**:
1. Add a `retry_count` field to `PredictableHypothesis` (default 0, max 3). After 3 failures, mark status as `VERIFICATION_FAILED` with error note.
2. Add exponential backoff to reflection_agent Pro calls (1s, 4s, 16s).
3. Add a `last_error` text field to `PredictableHypothesis` to capture API error details for debugging.
4. Clarify the cost optimization logic: Flash scoring (cheap) runs first → compute Brier → only run Pro reflection (expensive) on predictions where Brier > 0.25 (i.e., the prediction was meaningfully wrong).
5. Add a daily batch process that scans for `status = 'PENDING' AND expiry_date < TODAY` and attempts verification. This is the "cron job" that the plan alludes to but doesn't specify.

---

## Q9: Storage Growth & Pruning (MEDIUM)

**Plan claim**: "SQLite 每实体保留最近 20 条教训 + 摘要压缩旧教训".

**Finding**: Pruning is only specified for lessons, not for predictions, calibration data, or expertise records.

**Growth model** (unbounded):
| Table | Growth rate | 1 year | 3 years | Pruning specified? |
|-------|:---:|:---:|:---:|:---:|
| predictions | ~21/day (1/shadow) | 7,665 | 22,995 | No (status-based archival possible) |
| lessons | ~5/day (subset of predictions) | 1,825 | 5,475 | Yes — 20 per entity |
| entity_memories | static (~50 entities) | 50 | 50 | N/A (fixed set) |
| calibration_data | 1/entity/shadow/day | ~1,050 | ~3,150 | No |
| expertise | ~50-200 rows | 50-200 | 50-200 | N/A (overwritten) |

At 3 years, ~30,000 prediction rows is trivially small for SQLite. **Storage growth is not a real problem** for the SQLite engine itself.

**The real problem is relevance decay**: 6-month-old predictions with PENDING status (API failures) are zombie data. 2-year-old entity memories about market regimes that no longer exist ("ECB negative rates era") should be marked as stale.

**Recommendation**:
1. Add a cleanup query for zombie predictions: `DELETE FROM predictions WHERE status = 'PENDING' AND expiry_date < date('now', '-90 days')` — if a prediction can't be verified within 90 days of expiry, it's never going to be verified.
2. Add `memory_freshness` decay to entity memories: set to 0.0 when `last_analyzed > 365 days ago`. Don't delete — just exclude from prompt injection.
3. Add a VACUUM call to the monthly maintenance routine (or rely on SQLite auto-vacuum).
4. Archive verified predictions older than 6 months to a JSON summary (keeps the raw data for backtesting but removes it from the active DB). This is optional — 30K rows is not a performance problem.
5. The "20 lessons per entity" limit is reasonable for prompt injection (fits in context window). But old lessons should be compressed into entity-level summary statistics rather than simply deleted.

---

## Additional Findings

### A1. Missing dependency: investigation_loop.py

Covered in Q1 and Q7. This is the single largest gap in the plan. The plan should be updated to reference the actual integration point: Stage 9.5, after Decision output, using `DecisionCard` objects as input to `prediction_extractor.py`.

### A2. No session_context.py changes specified

The plan adds `PredictableHypothesis` but does not specify where it lives. It should either be:
- (a) A new dataclass in `pipeline/session_context.py` (alongside other pipeline types)
- (b) A new file `pipeline/predictable_hypothesis.py`
- (c) Defined inside `prediction_extractor.py` and re-exported

Option (a) is preferred — `session_context.py` is only 78 lines and is explicitly designed as the shared data type module.

### A3. CalibrationTracker requires NumPy dependency

Brier score computation, ECE (Expected Calibration Error), and Platt scaling all require numerical computation. The plan says "纯统计，不调用 LLM" — correct, but doesn't mention whether NumPy/SciPy is needed. Check if the project already has these dependencies.

### A4. No CLI entry point for learning system

The plan describes batch processing but doesn't specify how it's invoked. Options:
- (a) New `--mode learning` CLI argument in app.py
- (b) Separate `python -m marketmind.pipeline.reflection_agent` script
- (c) Cron job calling a new entry point

Option (a) is preferred — consistent with the existing `--mode daily/interactive/gui/shadows` pattern.

### A5. Phase I timeline vs existing batch process

The plan lists 6 implementation stages (I-1 through I-6). At the project's established pace of ~1 stage per session, Phase I is a 6-12 session effort. This should be factored into the roadmap — Phase I is not a "quick addition" but a major new subsystem.

---

## Verdict Summary

| Finding | Severity | Status |
|---------|:---:|:---:|
| Q1: Pipeline insertion point undefined, investigation_loop.py missing | **CRITICAL** | BLOCKS implementation |
| Q6: HypothesisResult phantom type, PredictableHypothesis integration undefined | **CRITICAL** | BLOCKS implementation |
| Q2: SQLite schema — no indices, DB split decision | HIGH | Resolve before I-1 |
| Q4: Import DAG underspecified (but likely clean) | HIGH | Resolve before I-1 |
| Q5: Shadow calibration data flow unspecified | HIGH | Resolve before I-5 |
| Q7: Phase H dependency on nonexistent module | HIGH | Resolve before I-1 |
| Q8: No retry/dead-letter mechanism for batch API calls | HIGH | Resolve before I-3 |
| Q3: Module size — learning_store.py at risk of exceeding 500 lines | MEDIUM | Monitor during I-1 |
| Q9: Storage pruning only specified for lessons | MEDIUM | Resolve before I-4 |
| A1-A5: Additional concerns | LOW-MEDIUM | Address in implementation plan |

---

## Required Plan Amendments (Checklist)

Before Phase I implementation begins:

- [ ] **Q1**: Replace `investigation_loop.py` reference with actual integration point (Stage 9.5, after Decision). Specify that reflection_agent runs at session START (before Stage 0) to check for expired predictions.
- [ ] **Q6**: Remove all references to `HypothesisResult`. Define `PredictableHypothesis` as a NEW dataclass in `pipeline/session_context.py`. Specify that `prediction_extractor.py` takes `DecisionCard` objects as input.
- [ ] **Q4**: Add explicit import DAG diagram to the plan.
- [ ] **Q2**: Decide: separate `learning.db` or extend `shadows.db` (recommendation: separate). Add index specifications for all new tables.
- [ ] **Q5**: Specify that shadow predictions are extracted from `shadow_outputs` table (DB read, no code changes to shadow_agent.py).
- [ ] **Q8**: Add retry_count, last_error fields to PredictableHypothesis. Specify exponential backoff for reflection_agent Pro calls.
- [ ] **Q3**: Add estimated line counts to each module in the plan. Pre-split `learning_store.py` into `learning_db.py` + `learning_store.py`.
- [ ] **Q9**: Add zombie prediction cleanup query (90-day threshold for PENDING predictions past expiry).

**Updated**: 2026-05-18 — Red Team Architecture audit of Phase I plan complete. 2 CRITICAL, 5 HIGH, 1 MEDIUM findings.
