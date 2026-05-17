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
│   └── multimodal_adapter.py   # Image/PDF/screenshot ingestion
├── shadows/                    # Shadow ecosystem (Phase B-F)
│   ├── shadow_agent.py         # Base ShadowAgent class
│   ├── shadow_state.py         # SQLite persistence + ShadowConfig
│   ├── shadow_mother.py        # Daily orchestration + event detection + temp shadows
│   ├── shadow_memory.py        # Layered memory (working/episodic/semantic)
│   ├── expert_shadows.py       # 15 domain-specific analyst shadows
│   ├── daredevil_shadows.py    # 5 contrarian/high-risk shadows
│   ├── catfish_agent.py        # Minority-opinion enforcer (>=80% consensus trigger)
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
│   └── archivist.py            # Decision archive
├── integrity/                  # Quality assurance
│   ├── watchdog.py             # Integrity monitoring
│   └── fact_checker.py         # Claim verification
├── config/                     # Configuration
│   ├── settings.py             # MarketMindConfig + ShadowSettings
│   ├── asset_universe.py       # Tradable asset matrix
│   └── source_authority.py     # Source authority tiers
└── tests/                      # Test suite
    ├── test_gateway/           # Gateway + token budget tests
    ├── test_shadows/           # Shadow ecosystem tests (147+ tests)
    ├── test_pipeline/          # Pipeline stage tests
    ├── test_ui/                # UI component tests
    ├── test_integrity/         # Integrity watchdog tests
    └── test_storage/           # Storage layer tests
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

Step 3: L1 Narrative — analyze_layer1(signals[:15], news_items)
        Pro LLM produces Layer1Result: event_grade, matrix_quadrant, sentiment

Step 4: L2 + L3 (parallel)
        L2: analyze_layer2(l1_result) — 5-tier fundamental
        L3: analyze_layer3(tickers, {}) — 3-light technical (INDEPENDENT of L1-L2)

Step 5: Shadow Ecosystem (optional, runs in parallel with main AI)
        Shadows analyze raw news+market_data independently.
        Output: ranked shadows, memory updates, crystallization.
        shadow_votes is ALWAYS None — shadows do NOT vote on decisions.

Step 6: Red Team — run_red_team()
        Adversarial challenge on L1+L2 raw analysis

Step 7: Resonance — evaluate_resonance()
        Statistical validation (DSR/PBO), pure Python, no LLM

Step 8: Decision — generate_decision()
        shadow_votes=None (design decision: shadows don't vote)
        Produces decision_cards + no_trade_card

Step 9: Archive — archivist.index_document()
        FTS5 full-text search index
```

### CRITICAL: Shadows Do NOT Vote

`app.py:110`: `shadow_votes = None` — initialized to None, never assigned, passed as None to `generate_decision()`. This is INTENTIONAL. Shadows are an internal competition ecosystem for ranking/evolution/crystallization. They are NOT a voting mechanism for investment decisions. Any document claiming "shadows vote on decisions" is stale/wrong.

### Shadow Ecosystem (independent from main decision)

21+ shadows across 7 types compete internally:
- **Expert** (15): domain-specific analysts (gold, crypto, energy, bonds, etc.)
- **Daredevil** (5): contrarian strategies
- **Catfish** (1): minority-opinion enforcer at >=80% consensus
- **Temp/MissedPath/Challenger/Beta**: dynamic lifecycle

Internal cycle: event scan → temp shadow lifecycle → analysis → ranking → collusion → challenger → memory update → crystallization. Output feeds back into shadow ranking only.

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
