# MarketMind — Investment Analysis Platform

**Scope:** This file applies when working in `projects/marketmind/`. Load this FIRST for architecture, quick start, model routing, testing commands, and key file paths. For global conventions (Cognitive Loop, Three System Laws, Development Workflow, MRP format, Self-Correction Protocol), fall back to the root `CLAUDE.md` at the workspace level.

Multi-agent shadow ecosystem for investment signal validation and decision support. Built on DeepSeek Flash/Pro for production, developed with Claude (Cowork) for engineering.

## Development Order (LOCKED — do NOT reorder)

**CRITICAL: Main AI analysis pipeline comes FIRST. Shadow ecosystem SECOND. This order is written into this file to prevent development chaos. Every restart MUST follow this sequence.**

```
Phase 1: Main AI Analysis Pipeline (current)
  ├── Scout news collection ✅
  ├── Flash triage (Stage 2 replacement) ✅
  ├── Event clustering 🔄 Red Team audit
  ├── Pro HVR investigation loop ✅
  ├── Expectation gap analysis ✅
  ├── Adversarial self-check ✅
  ├── L2 + L3 (fundamental + technical) ✅
  ├── Red Team + Resonance ✅
  ├── Decision + Archive ✅
  └── End-to-end integration (NOT YET WIRED)

Phase 2: Shadow Ecosystem (build AFTER Phase 1 is complete)
  ├── Shadow initialization + parallel analysis
  ├── ELITE participation + domain-triggered awakening
  ├── Broadcast mechanism + 7-day isolation period
  ├── Ranking + Crystallization + Memory
  └── Cross-shadow interaction (collusion, challenger)
```

**Rule**: If you find yourself working on shadow code while the main AI pipeline is broken or incomplete, STOP. Fix the main pipeline first. Shadows are an ENHANCEMENT, not a replacement for the core analysis.

## Phase Status (2026-05-18 EOD)

### Pipeline: 10 stages + 3 gates
| Stage | Status |
|-------|--------|
| Stage 0 (Shadow Init) | COMPLETE |
| Stage 1 (Scout) | COMPLETE — 35 sources audited, statuses verified |
| Stage 2 (Flash Triage) | COMPLETE — event clustering integrated |
| Stage 2b (HVR Investigation) | COMPLETE — Phase H enhanced (causal+flow decomposition) |
| Gate 1 (Direction) | COMPLETE — cards, archiver, interaction loop, event clustering, CLI wiring |
| Stage 3 (L1 Narrative) | COMPLETE |
| Stage 4 (L2+L3) | COMPLETE |
| Stage 5 (Shadows) | COMPLETE |
| Stage 6 (Red Team) | COMPLETE |
| Stage 7 (Resonance) | COMPLETE |
| Stage 7b (Fragility) | COMPLETE — Phase H module |
| Stage 8 (Decision) | COMPLETE — signal conflict detection |
| Stage 9 (Archive) | COMPLETE |
| Gate 2 (Confirmation) | COMPLETE — gate2_interaction, position sizing, pre-trade checklist |
| Gate 3 (Position) | COMPLETE — gate3_interaction, final position validation |

### Phase H: Deep Analysis — COMPLETE
6 modules enhance existing stages with deeper analysis. All modules have full PICA audit coverage (75 artifacts).

### Phase I: Learning Layer — COMPLETE
6-layer self-evolving system observes pipeline output, scores predictions, runs post-mortems, accumulates entity memories. Operates as independent batch system — does not modify pipeline.

### Event Clustering: COMPLETE
3-tier pipeline (regex entity extraction → TF-IDF clustering → Flash topic synthesis). Reduces 587 headlines to 10-15 named themes with cross-cluster causal chains. Integrated into Gate 1 direction assessment.

### Shadow Phase 2: COMPLETE
Ranking enhancement (MPPM/Calmar/Omega composite), new shadow types (Temp/MissedPath/Challenger/Beta lifecycle), collusion detector upgrade (agreement stats → convergence vs herding), shadow_analyses table replaces shadow_votes. Shadow voting removed from main pipeline — shadows produce independent analyses for internal ranking only.

### Shadow Ecosystem Rules (PERMANENT)
1. Shadows produce independent ANALYSES for internal ranking — they NEVER vote on investment decisions.
2. Shadow analyses stored in `shadow_analyses` table (renamed from shadow_votes on 2026-05-18).
3. generate_decision() does NOT accept shadow data — no shadow output path exists to main decisions.
4. Beta shadows are ISOLATED — excluded from ranking, collusion, challenger.

### Source Audit: COMPLETE
35 sources audited, statuses verified. Source authority tiers updated in `config/source_authority.py`.

### Test count: 1272 (up from 689)
### PICA artifacts: 75
### Red Team audits: 13

## Quick Start

```bash
# GUI (Command Center dashboard)
cd projects/marketmind
python app.py

# CLI daily analysis
python app.py --mode daily --mock --verbose

# With custom shadow count
python app.py --mode daily --shadow-count 21 --verbose
```

## Architecture

```
marketmind/
├── app.py (entry point)
├── backtest_runner.py
├── gateway/                    # LLM gateway layer
│   ├── async_client.py         # Flash/Pro routing + M1 integrity injection
│   ├── token_budget.py         # Priority-based token budget
│   ├── response_parser.py      # Structured output parsing
│   ├── multimodal_adapter.py   # Image/PDF/screenshot ingestion
│   └── cross_border.py         # TIC/BIS/cross-currency basis data gateway
├── shadows/                    # Shadow ecosystem (Phase B-F)
│   ├── shadow_agent.py         # Base ShadowAgent class
│   ├── shadow_state.py         # SQLite persistence + ShadowConfig
│   ├── shadow_mother.py        # Daily orchestration + event detection + temp shadows
│   ├── shadow_memory.py        # Layered memory (working/episodic/semantic)
│   ├── expert_shadows.py       # 16 domain-specific analyst shadows
│   ├── daredevil_shadows.py    # 5 active + 2 env-locked + 1 short-biased = 8 daredevils
│   ├── ecosystem_auditor.py    # Ecosystem auditor mechanism (NOT a shadow — blind-spot scan)
│   ├── catfish_agent.py        # DEPRECATED — backward-compat wrapper for ecosystem_auditor
│   ├── ranking_engine.py       # MPPM/Calmar/Omega composite ranking
│   ├── challenger_engine.py    # 3-stage elimination buffer + paired t-test
│   ├── collusion_detector.py   # Agreement stats → convergence vs herding
│   ├── emergency_quota.py      # Confidence-based extra LLM calls + audit trail
│   ├── cash_reframing.py       # A/B test: treatment/control cohorts + Mann-Whitney
│   ├── paper_live_gap.py       # Virtual slippage + confidence discount
│   ├── knowledge_filter.py     # Learn-genes selective inheritance + ACE risk
│   ├── missed_path.py          # Counterfactual tracking + survivorship warning
│   ├── crystallization.py      # Insight → hypothesis → validate → promote/retire
│   ├── methodology_evolver.py  # Shadow methodology drift + evolution
│   ├── belief_types.py         # Belief state data types
│   ├── belief_math.py          # Belief update + decay math
│   └── background_scheduler.py # Periodic tasks (crystallization, cleanup)
├── pipeline/                   # Daily analysis pipeline
│   ├── scout.py                # News discovery
│   ├── flash_preprocessor.py   # Flash model data prep
│   ├── layer1_narrative.py     # Narrative layer
│   ├── layer2_fundamental.py   # Fundamental analysis
│   ├── layer3_technical.py     # Technical analysis
│   ├── decision.py             # Decision aggregation
│   ├── resonance.py            # Multi-dimensional resonance
│   ├── position_patrol.py      # Position monitoring
│   ├── red_team.py             # Red Team adversarial review
│   ├── hypothesis_card.py      # Gate 1 hypothesis card generation (3-card, frequency framing, progressive disclosure)
│   ├── kill_monitor.py         # Downstream kill-criteria monitoring
│   ├── gate1_interaction.py    # Gate 1 conversation loop + state machine
│   ├── gate2_interaction.py    # Gate 2 confirmation interaction loop
│   ├── gate3_interaction.py    # Gate 3 position sizing interaction loop
│   ├── position_sizing.py      # Position sizing engine (Kelly, risk parity)
│   ├── pre_trade_checklist.py  # Pre-trade validation checklist
│   ├── hvr_cycle.py            # HVR investigation cycle (extracted from investigation_loop)
│   ├── investigation_prompts.py  # HVR system prompt constants (data module)
│   ├── investigation_types.py    # HVR data types (data module)
│   ├── investigation_direction.py  # HVR direction extraction (data module)
│   ├── investigation_loop.py   # Investigation orchestration (glue layer)
│   ├── causal_decomposition.py # Asset-class-aware causal factor decomposition
│   ├── flow_decomposition.py   # Entity-level capital flow attribution
│   ├── regime_mapper.py        # Historical regime comparison (replaces Layer 4 heuristic)
│   ├── scenario_forecaster.py  # Branching scenario tree generation
│   ├── fragility_scanner.py    # Systemic fragility threshold monitoring
│   ├── cross_border_analyzer.py # Cross-border capital flow analysis
│   ├── entity_extractor.py      # Regex entity extraction from headlines
│   ├── event_clusterer.py       # TF-IDF clustering + theme naming
│   ├── flash_triage.py          # Stage 2 replacement — flash signal triage
│   ├── pre_gate1.py             # Pre-Gate 1 preparation
│   ├── post_gate1.py            # Post-Gate 1 processing
│   ├── entity_memory.py         # Phase I — per-entity memory accumulation
│   ├── expertise_discovery.py   # Phase I — cross-shadow methodology discovery
│   ├── platt_scaling.py         # Phase I — Platt scaling confidence calibration
│   ├── calibration_tracker.py   # Phase I — Brier score calibration tracking
│   ├── prediction_extractor.py  # Phase I — time-anchored prediction extraction
│   ├── reflection_agent.py      # Phase I — structured post-mortem reflection
│   ├── backtest_entry.py       # Backtest runner entry point (extracted from app.py)
│   ├── orchestration.py        # Pipeline orchestration (run_interactive extracted from app.py)
│   └── cache.py                # Response caching
├── ui/                         # Command Center GUI (customtkinter)
│   ├── main_window.py          # Main application window
│   ├── dashboard_panel.py      # Market overview dashboard
│   ├── shadow_panel.py         # Shadow ranking table (color-coded by tier)
│   ├── shadow_status_card.py   # Individual shadow detail card
│   ├── shadow_charts.py        # Ranking trend + discount rate charts
│   ├── decision_card.py        # Investment decision display
│   ├── position_card.py        # Position status display
│   ├── gate_panel.py           # Gate 1/2/3 decision panels
│   ├── pause_screen.py         # Pause/override screen
│   ├── async_bridge.py         # Async/sync bridge for UI
│   └── progress.py             # Progress indicators
├── storage/                    # Persistence
│   ├── session.py              # Session state management
│   ├── archivist.py            # Decision archive
│   └── gate_archiver.py        # Gate conversation JSONL+MD archiver
├── integrity/                  # Quality assurance
│   ├── watchdog.py             # Integrity monitoring
│   ├── fact_checker.py         # Claim verification
│   └── input_guard.py          # Shared input sanitization (prompt injection, Markdown escaping, Unicode normalization)
├── config/                     # Configuration
│   ├── settings.py             # MarketMindConfig + ShadowSettings
│   ├── asset_universe.py       # Tradable asset matrix
│   ├── source_authority.py     # Source authority tiers
│   ├── asset_class_routing.py  # 9-class asset taxonomy + router (data module)
│   ├── mechanism_glossary.py   # 25+ institutional mechanism definitions (data module)
│   ├── regime_library.py       # 8+ historical macro regimes (data module)
│   └── fragility_thresholds.py # 12 systemic fragility thresholds (data module)
└── tests/                      # Test suite (1044 tests)
    ├── test_gateway/           # Gateway + token budget tests
    │   ├── test_async_client.py
    │   ├── test_token_budget.py
    │   ├── test_response_parser.py
    │   ├── test_market_data.py
    │   ├── test_macro_data.py
    │   ├── test_options_flow.py
    │   └── test_cross_border.py
    ├── test_shadows/           # Shadow ecosystem tests (147+ tests)
    │   ├── test_shadow_agent.py
    │   ├── test_shadow_state.py
    │   ├── test_shadow_mother.py
    │   ├── test_expert_shadows.py
    │   ├── test_daredevil_shadows.py
    │   ├── test_catfish_agent.py       # Tests EcosystemAuditor + backward-compat CatfishAgent
    │   ├── test_ranking_engine.py
    │   ├── test_challenger_engine.py
    │   ├── test_collusion_detector.py
    │   ├── test_emergency_quota.py
    │   ├── test_cash_reframing.py
    │   ├── test_paper_live_gap.py
    │   ├── test_knowledge_filter.py
    │   ├── test_missed_path.py
    │   ├── test_llm_integration.py
    │   └── test_e2e_shadow_ecosystem.py
    ├── test_pipeline/          # Pipeline stage tests
    │   ├── test_scout.py
    │   ├── test_flash_preprocessor.py
    │   ├── test_layer1.py
    │   ├── test_layer2.py
    │   ├── test_layer3.py
    │   ├── test_decision.py
    │   ├── test_resonance.py
    │   ├── test_red_team.py
    │   ├── test_position_patrol.py
    │   ├── test_investigation_loop.py
    │   ├── test_causal_decomposition.py
    │   ├── test_flow_decomposition.py
    │   ├── test_regime_mapper.py
    │   ├── test_scenario_forecaster.py
    │   ├── test_fragility_scanner.py
    │   ├── test_cross_border_analyzer.py
    │   ├── test_hypothesis_card.py
    │   ├── test_kill_monitor.py
    │   ├── test_gate1_interaction.py
    │   ├── test_entity_extractor.py
    │   ├── test_event_clusterer.py
    │   ├── test_flash_triage.py
    │   ├── test_entity_memory.py
    │   ├── test_expertise_discovery.py
    │   ├── test_platt_scaling.py
    │   ├── test_calibration_tracker.py
    │   ├── test_prediction_extractor.py
    │   ├── test_reflection_agent.py
    │   ├── test_cache.py
    │   └── test_verification_chain.py
    ├── test_ui/                # UI component tests
    │   ├── test_async_bridge.py
    │   └── test_progress.py
    ├── test_integrity/         # Integrity watchdog tests
    │   ├── test_input_guard.py
    │   ├── test_watchdog.py
    │   └── test_fact_checker.py
    └── test_storage/           # Storage layer tests
        ├── test_session.py
        ├── test_archivist.py
        └── test_gate_archiver.py
```

## Model Routing (Flash vs Pro)

DeepSeek Flash: data collection, simple classification, auxiliary processing
DeepSeek Pro: deep analysis, adversarial reasoning, shadow analysis, final report writing

All LLM calls route through `gateway/async_client.py` — no module should call httpx directly.

M1 Data Integrity Protocol is injected at the gateway level for all shadow calls.

## Pipeline (AUTHORITATIVE — do NOT modify without user approval)

The pipeline defined here is the SINGLE SOURCE OF TRUTH. `app.py:run_daily()` is the reference implementation. All other documents that describe a different pipeline are WRONG.

### Main Pipeline (runs every session)

```
Step 0: Shadow Mother event scan (optional, shadows_enabled=1)
        Initialize expert/daredevil/catfish shadows, background scheduler

Step 1: Scout — fetch_all_sources()
        33 sources → news_items (587 articles avg)

Step 2: Flash Preprocessor — preprocess_batch(news_items[:50])
        Flash LLM extracts FlashSignal per batch of 15 headlines

Step 2b: HVR Investigation — investigate(top_signals, news_items)
        Pro LLM deep-dive on flash signals: hypothesis formation, causal decomposition,
        entity-level flow tracking, evidence collection. Produces HypothesisResult.

Step 3: L1 Narrative — analyze_layer1(signals[:15], news_items)
        Pro LLM produces Layer1Result: event_grade, matrix_quadrant, sentiment

Step 4: L2 + L3 (parallel)
        L2: analyze_layer2(l1_result) — 5-tier fundamental
        L3: analyze_layer3(tickers, {}) — 3-light technical (INDEPENDENT of L1-L2)

Step 5: Shadow Ecosystem (optional, runs in parallel with main AI)
        Shadows analyze raw news+market_data independently.
        Output: ranked shadows, memory updates, crystallization.

Step 6: Red Team — run_red_team()
        Adversarial challenge on L1+L2 raw analysis

Step 7: Resonance — evaluate_resonance()
        Statistical validation (DSR/PBO), pure Python, no LLM

Step 8: Decision — generate_decision()
        Produces decision_cards + no_trade_card

Step 9: Archive — archivist.index_document()
        FTS5 full-text search index
```

### Shadow Ecosystem (independent from main decision)

23+ shadows across 7 types compete internally (canonical design: shadow-ecosystem-full-design.md §1):
- **Expert** (16): domain-specific analysts with indicator confirmation thresholds
- **Daredevil** (8): 5 active (must decide daily) + 2 env-locked + 1 short-biased (Crash Hunter)
- **Ecosystem Auditor**: post-analysis mechanism — NOT a shadow. Reads shadow output, produces <=5 blind-spot alerts
- **Temp/MissedPath/Challenger/Beta**: dynamic lifecycle
- **Catfish**: DEPRECATED — replaced by EcosystemAuditor (backward-compat wrapper only)

Internal cycle: event scan → temp shadow lifecycle → analysis → ranking → collusion → challenger → ecosystem audit → memory update → crystallization. Output feeds back into shadow ranking only.

### ELITE Shadow Participation (Gate 2)

Documented in `shadows/elite_participation.py` and `.claude/phase_b_ideation_notes.md` §4:

1. ELITE shadows analyze news at the SAME TIME as main AI (same daily cycle)
2. They wait passively — pre-computed analysis stored in EliteRegistry
3. During Gate 2 (信号确认), when user discusses a topic matching a shadow's domain keyword → shadow awakens
4. User can also mention a shadow by name to summon it
5. Each ELITE shadow contributes at most ONCE per session
6. Contributions are clearly marked "SHADOW OPINION"
7. ELITE shadows have NO decision authority — advisory only
8. Domain keywords defined in `EliteRegistry.DOMAIN_KEYWORDS`

### Information Broadcast Rules

From `.claude/phase_b_ideation_notes.md` §1:

- Shadows receive: raw news/facts + user's raw opinions + submitted materials
- Shadows do NOT receive: main AI's pre-discussion analysis/report
- This prevents anchoring bias — shadows must think independently
- Shadows can use their Flash quota to request additional data (iterative)

## Testing

```bash
# All tests
cd projects/marketmind
python -m pytest tests/ -v --tb=short -p no:warnings

# Shadow ecosystem only
python -m pytest tests/test_shadows/ -v --tb=short

# Specific module
python -m pytest tests/test_shadows/test_ranking_engine.py -v --tb=short
```

Mock mode available for all pipeline stages via `--mock` flag.

## Design Constraints

1. All tickers must be Robinhood-tradable (from `config/asset_universe.py`)
2. DeepSeek Flash for data tasks, Pro for analysis tasks
3. All LLM calls through `gateway/async_client.py` gateway
4. Account state from `input/account_state.json` — no brokerage API
5. Final report in Chinese, ASCII-only, narrative essay style
6. Include specific price levels, not ranges
7. Shadow analysis is independent — no shadow reads another's output during analysis
8. Challenger data is opaque — invisible to target shadow until trial completes
9. Append-only state — never modify early context
