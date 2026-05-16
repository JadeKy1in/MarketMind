# MarketMind — Investment Analysis Platform

**Scope:** This file applies when working in `projects/marketmind/`. Load this FIRST for architecture, quick start, model routing, testing commands, and key file paths. For global conventions (Cognitive Loop, Project Boundaries, Development Workflow, PICA Protocol, Modular Architecture, MRP format), fall back to the root `CLAUDE.md` at the workspace level.

Multi-agent shadow ecosystem for investment signal validation and decision support. Built on DeepSeek Flash/Pro for production, developed with Claude (Cowork) for engineering.

## Project Constraints (Three System Laws)

These constraints are specific to MarketMind and are verified on every restart.

**Law 1 (Output Discipline):** Final Markdown reports must be ASCII-only, no emoji. Code comments and console output are exempt.

**Law 2 (Operational Boundary):** MarketMind is an analysis tool — it may READ public market data but must NEVER execute, modify, or cancel trades. Account state is maintained manually, never automated. Market data feeds must not be used for screening, ranking, or systematic parameter optimization (per Law 3).

- **PROHIBITED**: Any API call that places/modifies/cancels orders; any call accessing account balances, positions, or trading history; any authenticated connection to a brokerage account with trading permissions.
- **ALLOWED**: Read-only market data APIs (yfinance, Alpha Vantage, FMP, CoinGecko); exchange public endpoints (Binance `/api/v3/ticker/price`, `/api/v3/klines` — unauthenticated only; no Binance API keys, even read-only); APIs requiring read-only keys with zero trading permissions.
- **Boundary test**: If an API key grants trading capability, it must not be configured. If a platform's only key type grants trading, the platform is off-limits.

Verify: `grep -r "brokerage\|api\.trade\|place_order\|binance.*key\|Binance.*Key" --include="*.py" .` must return empty; `grep -r "yfinance\|finnhub\|alpha_vantage\|fmp\|coingecko" --include="*.py" .` confirms allowed sources.

**Law 3 (Anti-Overfitting):** Price data is a timing filter, not a signal source. Market data (fundamentals, OHLCV, technical indicators) may enrich analysis context but must NOT be fed into screening, ranking, or systematic parameter optimization pipelines. No parameter brute-forcing (no GridSearchCV, no brute_force loops over strategy params). Empty positions are valid outcomes. Verify: `grep -r "grid_search\|brute_force\|GridSearchCV\|Optuna\|hyperopt" --include="*.py" .` must return empty.

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
│   ├── broadcast.py            # User→shadow JSON broadcast
│   ├── elite_participation.py  # ELITE shadow interaction registry
│   └── background_scheduler.py # Periodic tasks (crystallization, cleanup)
├── pipeline/                   # Daily analysis pipeline
│   ├── scout.py                # News discovery
│   ├── flash_preprocessor.py   # Flash model data prep
│   ├── layer1_narrative.py     # Narrative layer
│   ├── layer1_interactive.py   # L1 Socratic dialogue (interactive)
│   ├── layer2_fundamental.py   # Fundamental analysis
│   ├── l2_interactive.py       # L2 ticker selection (interactive)
│   ├── layer3_technical.py     # Technical analysis
│   ├── l3_interactive.py       # L3 technical review (interactive)
│   ├── decision.py             # Decision aggregation
│   ├── decision_interactive.py # Decision confirmation (interactive)
│   ├── session_context.py      # Shared pipeline state
│   ├── resonance.py            # Multi-dimensional resonance
│   ├── position_patrol.py      # Position monitoring
│   ├── red_team.py             # Red Team adversarial review
│   ├── cache.py                # Response caching
│   ├── methodology_rules.py    # Methodology rule engine
│   ├── output_filter.py        # Hallucination guard
│   └── causal_review.py        # Causal post-mortem analysis
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

## Shadow Ecosystem

21+ independent shadow analysts across 7 types:
- **Expert** (15): gold, crypto, energy, bonds, volatility, emerging, tech, financials, healthcare, consumer, industrials, metals, real_estate, macro
- **Daredevil** (5): scalper, trend_rider, news_hound, fade_master, rotation_engine
- **Catfish** (1): minority-opinion enforcer, activates at >=80% consensus
- **Temp events** (dynamic): created/destroyed based on market events
- **Missed path** (dynamic): counterfactual tracking for rejected directions
- **Challenger** (dynamic): 3-stage elimination trials
- **Beta** (configurable): experimental shadows

Daily cycle: event scan → temp shadow lifecycle → parallel vote collection → ranking → collusion detection → challenger checks → emergency quota audit → memory update → crystallization.

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
