# Plan: Phase F — Shadow Ecology v1

## WHY + SCOPE

### WHY

The shadow system (Phase C+D, 20+ agents) has three fundamental ceilings:

1. **No learning loop**: Shadows produce analyses daily but never reflect on accuracy. Knowledge never crystallizes from ad-hoc insight into reusable methodology.
2. **Single-channel input**: Shadows only see structured pipeline data. No screenshots, PDFs, or audio.
3. **Synchronous-only**: Manual trigger only. No autonomous reflection or background processing.

### SCOPE — IN (6 work streams)

**F-1. Multi-modal input gateway**
Port `robinhood/src/multimodal_bridge.py` → `marketmind/gateway/multimodal_adapter.py`. Supports screenshots (Gemini Vision), PDFs (pdfplumber), images (OCR fallback). Adapts to marketmind's async gateway pattern. Produces `ExternalObservation` objects.
- **Key risk**: Sync→async conversion — robinhood uses `requests`/`PIL`; marketmind uses `httpx`/`asyncio`. PIL CPU-bound ops → `asyncio.to_thread()`. Gemini API → `httpx.AsyncClient`. Must validate `asyncio.to_thread()` behavior on Windows daemon-thread event loops.

**F-2. External observation evaluation**
Extend existing `marketmind/shadows/knowledge_filter.py` (has `KnowledgeItem`, `KnowledgeFilter` with PASS/DROP/ISOLATE rules + ACE risk scoring) with `evaluate_external()` method. External observations use same verification pipeline as challenger knowledge inheritance. ~40 line extension — no new module.

**F-3. Layered shadow memory (3-tier)**
Port robinhood's belief subsystem:
- `belief_types.py` + `belief_math.py` → copy verbatim to `marketmind/shadows/` (zero-dependency, pure functions/dataclasses)
- `belief_state_manager.py` → adapt as `marketmind/shadows/shadow_memory.py` (replace MCP/JSONL persistence with ShadowStateDB SQLite; ~70% logic reuse)
- Three tiers: Working (~24h), Episodic (~90d, per-shadow decision-outcome pairs), Semantic (indefinite, crystallized insights)
- Beta-Bernoulli decay: γ=0.95, half-life ~13.5 steps (Silent Scholar calibration)

**F-4. Knowledge crystallization**
Two-source design:
- **Methodology tracking**: Port `robinhood/src/methodology_evolver.py` → `marketmind/shadows/methodology_evolver.py`. Has `MethodRecord` (success/failure counters, decay factor), `MethodologyReport` (best/worst performing, recommended changes), `DEFAULT_METHODS` registry, JSON audit trail.
- **Crystallization orchestrator**: New `marketmind/shadows/crystallization.py`. Inner loop (insight → hypothesis → methodology tweak → backtest validate via shadow_votes), outer loop (performance tracking → statistical significance gate → promote to semantic memory or retire). Wire into `ShadowMother.orchestrate_daily_cycle()`.

**F-5. Async background scheduler**
New `marketmind/shadows/background_scheduler.py`. DAG task graph (DynTaskMAS-inspired), asyncio scheduling, event-driven wake-up (market close, high volatility, breaking news). Separate daemon thread + own event loop + queue.Queue (same pattern as existing `AsyncBridge`) to avoid blocking tkinter main thread.

**F-6. Red Team audit**
Adversarial security review: prompt injection via screenshot OCR text, memory poisoning via crafted PDFs, scheduler resource exhaustion, crystallization contamination. Severity-classified report; all HIGH/CRITICAL resolved before merge.

### SCOPE — OUT

- RAG/vector database (Phase G)
- New shadow types or shadow conversation participation (Phase G)
- Gemini Pro deep analysis (Flash only; Pro stays DeepSeek)
- UI changes
- Brokerage API connection (Law 2)

### Reuse Strategy

| Source | Action | Notes |
|--------|--------|-------|
| robinhood `multimodal_bridge.py` (334 lines) | **Port** | Sync→async conversion needed |
| robinhood `belief_types.py` (389 lines) | **Copy verbatim** | Pure dataclasses + enums, zero deps |
| robinhood `belief_math.py` (243 lines) | **Copy verbatim** | Pure functions, zero deps, γ=0.95 calibrated |
| robinhood `belief_state_manager.py` (1005 lines) | **Adapt** (~70% reuse) | Replace MCP/JSONL backend with ShadowStateDB SQLite |
| robinhood `methodology_evolver.py` (~350 lines) | **Port** | Update DEFAULT_METHODS to shadow domains |
| robinhood `reflection_orchestrator.py` (306 lines) | **Pattern reference** | Different trigger mechanism |
| marketmind `knowledge_filter.py` | **Extend** (+40 lines) | Add `evaluate_external()` |

### Success Criteria

- [x] Screenshot → Gemini Flash → structured data → `ExternalObservation` in shadow memory
- [x] PDF submission → `knowledge_filter.evaluate_external()` → pass/fail → if passed, enters layered memory
- [x] Three-tier memory with TTL decay; queries return age-weighted, belief-strength-ranked results
- [x] Crystallization inner loop: insight → hypothesis → methodology tweak → backtest validate → promote/retire
- [x] Methodology evolver tracks per-method performance with audit trails
- [x] Background scheduler runs reflection + crystallization daily (configurable interval)
- [x] Red Team audit: all HIGH/CRITICAL resolved before merge
- [x] All 339 existing tests pass; ~480 new test lines

## Phase F Completion (2026-05-12)

All 6 work streams are complete:

| Stream | Description | Files | Tests |
|--------|-------------|-------|-------|
| F-0 | Shared interfaces (ExternalObservation, MemoryQuery, CrystallizationResult) | `shadow_agent.py` | 5 tests |
| F-1 | Multi-modal input gateway (Gemini Flash + OCR + pdfplumber) | `multimodal_adapter.py` | 6 tests |
| F-2 | Knowledge filter extension (evaluate_external + suspicious content detection) | `knowledge_filter.py` | 11 + 5 new tests |
| F-3 | Layered shadow memory (3-tier Beta-Bernoulli belief system) | `belief_types.py`, `belief_math.py`, `shadow_memory.py`, `shadow_state.py` | 14 tests |
| F-4 | Knowledge crystallization + methodology evolver | `crystallization.py`, `methodology_evolver.py`, `shadow_mother.py` | 15 tests |
| F-5 | Async background scheduler (DAG task graph, daemon thread) | `background_scheduler.py` | 18 tests |
| F-6 | Red Team audit + integration wiring | `app.py`, `tests/test_red_team_phase_f.py`, `tests/test_phase_f_integration.py` | 20 tests |

### F-6 Red Team Audit Findings

| # | Attack Surface | Severity | Mitigation | Test |
|---|---------------|----------|------------|------|
| RT-1 | Prompt injection via screenshot OCR | MEDIUM | Statistical crystallization gate (>=10 votes required for promotion). Single injection cannot crystallize. | `test_injected_prompt_is_ingested_but_wont_crystallize` |
| RT-2 | Memory poisoning via crafted PDF | HIGH | SUSPICIOUS_CONTENT_PATTERNS in knowledge_filter ISOLATE insider/confidential/leaked content. | `test_insider_information_is_isolated` (4 tests) |
| RT-3 | Scheduler resource exhaustion | LOW | per_shadow_task_budget + max_concurrent_tasks via Semaphore. | `test_task_budget_limits_enforced` (2 tests) |
| RT-4 | Crystallization contamination | LOW | Cold-start guard (min_samples) + backtest validation against shadow_votes PnL. | `test_false_signal_rejected_by_cold_start` |
| RT-5 | Gemini API key leakage | LOW | Private `_api_key` attribute, no custom repr/str, error messages use env var name not value. | `test_repr_does_not_expose_key` (4 tests) |
| RT-6 | Cross-shadow memory isolation | LOW | Parameterized queries filter by shadow_id. Proposition naming convention enforces scoping. | `test_get_observations_respects_shadow_id_boundary` (2 tests) |
| RT-7 | SQL injection in belief queries | LOW | All queries use parameterized SQLite (?, ?, ?), no f-string interpolation. | `test_query_beliefs_handles_sql_injection_in_ticker` (4 tests) |

### Integration Wiring

- `app.py`: BackgroundScheduler + MultimodalAdapter initialization gated behind config flags (disabled by default)
- `app.py`: Memory update + crystallization status report after Stage 5
- All new features are DISABLED by default (config flags default to False)
- Existing pipeline stages (0-9) unchanged

## Existing Solutions

### Robinhood implementations (port sources) — CONFIRMED

| File | Lines | Status | Key exports |
|------|-------|--------|-------------|
| `multimodal_bridge.py` | 334 | Isolated (zero production callers) | `MultimodalResult`, `extract_text_from_image()`, `extract_text_from_pdf()`, `extract_text_from_screenshot()` |
| `belief_types.py` | 389 | Production (imported by all belief modules) | `BeliefNode`, `BeliefObservation`, `ConflictRecord`, `BeliefRetirement`, `BeliefSnapshot`, 3 enums |
| `belief_math.py` | 243 | Production (imported by manager + predictor) | `beta_update()`, `gamma_decay()`, `beta_uncertainty()`, `beta_expectation()`, `confidence_score()` |
| `belief_state_manager.py` | 1005 | Production (imported by predictor, ingestion, reflection) | `BeliefStateManager` (3-layer: Ingestion→Processing→Querying), 4 custom exceptions |
| `methodology_evolver.py` | ~350 | Production | `MethodRecord`, `MethodologyReport`, `load_tracker()`, `record_prediction()`, `apply_decay()` |
| `reflection_orchestrator.py` | 306 | Test-only (no production wiring) | `ReflectionOrchestrator`, `ReflectionSchedulerConfig`, step-based decay |

### MarketMind existing — integrate with

| File | Purpose | Phase F use |
|------|---------|-------------|
| `shadows/knowledge_filter.py` | KnowledgeItem, PASS/DROP/ISOLATE, ACE risk | Extend with `evaluate_external()` |
| `shadows/shadow_state.py` | 9 SQLite tables, version-tracked schema | Add 3 memory tables |
| `shadows/shadow_agent.py` | ShadowVote, ShadowAnalysisOutput dataclasses | Add ExternalObservation, MemoryQuery, CrystallizationResult |
| `shadows/shadow_mother.py` | 8-step daily orchestration | Wire memory update (step 6.5) + crystallization (step 6.6) |
| `gateway/async_client.py` | KeyRotator, DeepSeekGateway | Pattern reference for GeminiFlashGateway |
| `gateway/token_budget.py` | TokenBudget with priority queue | Extend for Gemini quota tracking |

### Command Center — existing multi-modal infrastructure

| Component | Status | Phase F use |
|-----------|--------|-------------|
| `intelligence/ocr_reader.py` | Vision messages built but NOT consumed by adapters | Basis for multimodal message routing to Gemini |
| `gateway/flash_adapter.py` | Flash adapter, temperature=0.1 | Pattern reference for Gemini Flash adapter |

### External references (user-provided, no re-search)

- **FinMem** (AAAI 2024): Layered memory + character self-evolution
- **FinCon CVRF** (NeurIPS 2024): Verbal belief propagation between agents
- **QuantAgent** (2024): Two-layer knowledge refinement loop
- **Nurture-First Development** (2026): Conversational Knowledge Crystallization
- **DynTaskMAS** (AAAI 2025): DAG task graph + async parallel engine
- **AHCE** (2026): Learned expert intervention policy
- **Silent Scholar** (arXiv:2504.18924): β-Bernoulli calibration (γ=0.95) — implemented in robinhood belief_math.py

## Minimal Path

### Files to Create/Modify (18 files)

| # | File | Action | Est. Lines | Stream | Depends On |
|---|------|--------|-----------|--------|------------|
| 0 | `marketmind/shadows/shadow_agent.py` | MODIFY (+ExternalObservation etc.) | +30 | Shared | None |
| 1 | `marketmind/gateway/multimodal_adapter.py` | PORT (from robinhood) | ~200 | F-1 | #0 |
| 2 | `marketmind/gateway/__init__.py` | MODIFY | +5 | F-1 | #1 |
| 3 | `marketmind/shadows/knowledge_filter.py` | MODIFY (+evaluate_external) | +40 | F-2 | #0 |
| 4 | `marketmind/shadows/belief_types.py` | COPY (from robinhood) | ~389 | F-3 | None |
| 5 | `marketmind/shadows/belief_math.py` | COPY (from robinhood) | ~243 | F-3 | None |
| 6 | `marketmind/shadows/shadow_memory.py` | CREATE (adapt belief_state_manager) | ~350 | F-3 | #4, #5, #0 |
| 7 | `marketmind/shadows/shadow_state.py` | MODIFY (+3 memory tables) | +50 | F-3 | #0 |
| 8 | `marketmind/shadows/methodology_evolver.py` | PORT (from robinhood) | ~300 | F-4 | #6 |
| 9 | `marketmind/shadows/crystallization.py` | CREATE | ~200 | F-4 | #6, #8 |
| 10 | `marketmind/shadows/shadow_mother.py` | MODIFY (+memory+crystal wiring) | +40 | F-4 | #6, #9 |
| 11 | `marketmind/shadows/background_scheduler.py` | CREATE | ~200 | F-5 | #6 |
| 12 | `marketmind/config/settings.py` | MODIFY (+scheduler, +Gemini key) | +20 | All | None |
| 13 | `marketmind/app.py` | MODIFY (+scheduler launch) | +20 | F-5 | #11, #1 |
| 14 | `tests/test_multimodal_adapter.py` | CREATE | ~80 | F-1 | #1 |
| 15 | `tests/test_shadow_memory.py` | CREATE | ~120 | F-3 | #6 |
| 16 | `tests/test_crystallization.py` | CREATE | ~100 | F-4 | #9 |
| 17 | `tests/test_background_scheduler.py` | CREATE | ~100 | F-5 | #11 |
| 18 | `tests/test_phase_f_integration.py` | CREATE | ~80 | F-6 | All |

**Total: ~2567 lines (1267 production + 560 test + 632 copied verbatim, 108 adapted/ported)**

### Dependency Graph

```
Phase F-0: Shared Interface — shadow_agent.py (+30 lines) [BLOCKS ALL]
    │
    ├── F-1: Multimodal Adapter ── 2 files, ~285 lines ── Agent A
    ├── F-2: Knowledge Filter Ext ── 1 file, ~40 lines ── Agent B
    └── F-3: Layered Memory ────── 5 files, ~1082 lines ─ Agent C
            │
            ├── F-4: Crystallization ── 3 files, ~540 lines ── Agent A (after F-3)
            └── F-5: Background Scheduler ─ 2 files, ~220 lines ─ Agent B (after F-3)
                    │
                    └── F-6: Integration + Red Team ─ 2 files, ~100 lines ─ Agent C
```

**Critical path**: F-0 → F-3 → F-4 → F-6

**Parallel opportunities (Agent Team compatible)**:
- F-0: Single agent, 1 file (~30 min)
- F-1 + F-2 + F-3: Three agents in parallel after F-0 interface lock (~2-3h each)
- F-4 + F-5: Two agents in parallel after F-3 (~1-2h each)
- F-6: Single agent after F-4 + F-5 (~1h + Red Team)

**Estimated total time with 3 parallel agents**: ~6-8 hours (vs ~14-18 hours serial)

## Risks and Unknowns

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **Sync→async conversion** (multimodal_bridge) | F-1 blocked | PIL → `asyncio.to_thread()`, Gemini API → `httpx.AsyncClient`, validate on Windows daemon-thread loops |
| **MCP→SQLite persistence swap** (belief_state_manager) | F-3 blocked | Write `ShadowMemoryStore` wrapping ShadowStateDB with same interface |
| **Gemini Flash quota** (free tier 1,500/day) | Low (1-10/day target) | Key rotation follows existing KeyRotator pattern |
| **Scheduler ↔ GUI thread isolation** | GUI freeze | Separate daemon thread + own event loop + queue.Queue (same as AsyncBridge) |
| **Crystallization cold start** (<10 votes) | Skip for new shadows | Same 10-trade threshold from Phase E Bayesian cold start |
| **knowledge_filter scope creep** | Method mismatch | Separate `evaluate_external()` method, same KnowledgeItem dataclass |
| **Red Team: prompt injection via OCR** | HIGH | Dedicated Red Team pass before merge |
| **Red Team: memory poisoning via PDF** | MEDIUM | `evaluate_external()` gate before memory insertion |
| **Red Team: scheduler resource exhaustion** | LOW | Max concurrent tasks config, per-shadow task budget |
| **pdfplumber dependency** | Missing in marketmind requirements | Add to `requirements.txt` during F-1 |
| **`asyncio.to_thread()` on Windows** | Python 3.9+ required | MarketMind already uses Python 3.11+ — verified compatible |

### Implementation Notes (from plan-critic Round 3)

1. **File reference fix**: Use `shadow_agent.py` (not `shadow_types.py` which doesn't exist). ShadowVote and ShadowAnalysisOutput are in `shadow_agent.py`.
2. **belief_math.py location**: Place in `marketmind/shadows/belief_math.py` (not `config/`). It's a core shadow subsystem dependency, not config.
3. **pdfplumber**: Add to `marketmind/requirements.txt` — currently not a dependency.
4. **`asyncio.to_thread()` validation**: Must verify behavior on Windows with daemon-thread event loops during F-1 implementation. MarketMind's AsyncBridge pattern already proven.
5. **ShadowStateDB memory tables**: Add 3 tables (`belief_nodes`, `belief_observations`, `belief_retirements`) following existing schema patterns (CREATE IF NOT EXISTS, migration registry entry).
6. **knowledge_filter extension**: Keep `evaluate_external()` as separate method within KnowledgeFilter class to avoid scope creep. External observations use same KnowledgeItem dataclass for consistency.
7. **DEFAULT_METHODS update**: When porting methodology_evolver.py, replace robinhood's 12 DEFAULT_METHODS with marketmind's shadow domain methods (expert domains, technical strategies, etc.).

## Critique History

| Round | Verdict | Composite | Assumption | Scope | Existing | Minimalism | Uncertainty |
|-------|---------|-----------|------------|-------|----------|------------|-------------|
| 1 | REVISE | 2.0 | 2 | 2 | 1 | 2 | 3 |
| 2 | REVISE | 2.8 | 3 | 3 | 3 | 3 | 2 |
| 3 | PROCEED | 3.2 | 3 | 4 | 3 | 3 | 3 |

**Key issues resolved across rounds:**

- **Round 1 → 2**: Discovered robinhood/ already has 6 production implementations (multimodal_bridge, belief_types, belief_math, belief_state_manager, methodology_evolver, reflection_orchestrator). Revised from "build from scratch" to "port, adapt, and integrate." File count dropped from 14-16 to 18 (more files but ~632 lines copied verbatim, ~108 adapted — net ~740 lines of "free" code).

- **Round 2 → 3**: (a) Replaced new `critical_evaluator.py` with extension of existing `knowledge_filter.py` (+40 lines). (b) Integrated `methodology_evolver.py` port into crystallization design. (c) Flagged sync→async conversion as explicit risk with three-pronged mitigation (PIL→asyncio.to_thread, requests→httpx.AsyncClient, subprocess→async subprocess). (d) Fixed `shadow_types.py` → `shadow_agent.py` reference. (e) Moved `belief_math.py` from `config/` to `shadows/`.

- **Round 3**: All axes at or above 3. No blocking issues. 7 implementation notes for code phase.

## Linked Issues

All issues created in `JadeKy1in/MarketMind` (SignalFoundry repo is archived):

- [#1](https://github.com/JadeKy1in/MarketMind/issues/1) — feat(Phase F-0): shared interface dataclasses — ExternalObservation, MemoryQuery, CrystallizationResult
- [#2](https://github.com/JadeKy1in/MarketMind/issues/2) — feat(Phase F-1): multi-modal input gateway — port multimodal_bridge.py, Gemini Flash adapter
- [#3](https://github.com/JadeKy1in/MarketMind/issues/3) — feat(Phase F-2): extend knowledge_filter for external observation evaluation
- [#4](https://github.com/JadeKy1in/MarketMind/issues/4) — feat(Phase F-3): layered shadow memory — 3-tier belief system (port from robinhood)
- [#5](https://github.com/JadeKy1in/MarketMind/issues/5) — feat(Phase F-4): knowledge crystallization + methodology evolver
- [#6](https://github.com/JadeKy1in/MarketMind/issues/6) — feat(Phase F-5/6): async background scheduler + integration + Red Team audit

**Issue decomposition (6 independent work items):**

| # | Title | Files | Stream | Depends on |
|---|-------|-------|--------|------------|
| 1 | Shared interfaces: ExternalObservation, MemoryQuery, CrystallizationResult | `shadow_agent.py` | F-0 | Nothing |
| 2 | Multi-modal input gateway (port multimodal_bridge.py) | `multimodal_adapter.py`, `gateway/__init__.py`, `requirements.txt` | F-1 | #1 |
| 3 | Extend knowledge_filter for external observation evaluation | `knowledge_filter.py` | F-2 | #1 |
| 4 | Layered shadow memory (3-tier belief system) | `belief_types.py`, `belief_math.py`, `shadow_memory.py`, `shadow_state.py` | F-3 | #1 |
| 5 | Knowledge crystallization + methodology evolver | `methodology_evolver.py`, `crystallization.py`, `shadow_mother.py` | F-4 | #4 |
| 6 | Background scheduler + integration + Red Team | `background_scheduler.py`, `settings.py`, `app.py`, integration test | F-5, F-6 | #4, #5 |
