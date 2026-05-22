# MarketMind — Investment Analysis Platform

**Scope:** This file applies when working in `projects/marketmind/`. Load this FIRST for architecture, quick start, model routing, testing commands, and key file paths. For global conventions (Cognitive Loop, Three System Laws, Development Workflow, MRP format, Self-Correction Protocol), fall back to the root `CLAUDE.md` at the workspace level.

Multi-agent shadow ecosystem for investment signal validation and decision support. Built on DeepSeek Flash/Pro for production, developed with Claude (Cowork) for engineering.

## Development Order (LOCKED — do NOT reorder)

**CRITICAL: Main AI analysis pipeline comes FIRST. Shadow ecosystem SECOND. This order is written into this file to prevent development chaos. Every restart MUST follow this sequence.**

```
Phase 1: Main AI Analysis Pipeline (current)
  ├── Scout news collection ✅
  ├── Flash triage (Stage 2 replacement) ✅
  ├── Event clustering ✅
  ├── Pro HVR investigation loop ✅
  ├── Expectation gap analysis ✅
  ├── Adversarial self-check ✅
  ├── L2 + L3 (fundamental + technical) ✅
  ├── Red Team + Resonance ✅
  ├── Decision + Archive ✅
  └── End-to-end integration ✅

Phase 2: Shadow Ecosystem ✅
  ├── Shadow initialization + parallel analysis ✅
  ├── ELITE participation + domain-triggered awakening ✅
  ├── Broadcast mechanism + 7-day isolation period ✅
  ├── Ranking + Crystallization + Memory ✅
  └── Cross-shadow interaction (collusion, challenger) ✅
```

**Rule**: If you find yourself working on shadow code while the main AI pipeline is broken or incomplete, STOP. Fix the main pipeline first. Shadows are an ENHANCEMENT, not a replacement for the core analysis.

## Phase Status (2026-05-23)

**Test count: 1,749 pass, 11 fail, 44 skip** | **PICA artifacts: 79** | **Red Team audits: 17**

### Phase J: API + WebSocket + AEL + Upload — COMPLETE
### Phase K: Grandfather extraction + API tests + Regression fixes — COMPLETE

### Pipeline: 10 stages + 3 gates — COMPLETE
| Stage | Status |
|-------|--------|
| Stage 0 (Shadow Init) | COMPLETE |
| Stage 1 (Scout) | COMPLETE |
| Stage 2 (Flash Triage) | COMPLETE |
| Stage 2b (HVR Investigation) | COMPLETE |
| Gate 1 (Direction) | COMPLETE |
| Stage 3 (L1 Narrative) | COMPLETE |
| Stage 4 (L2+L3) | COMPLETE |
| Stage 5 (Shadows) | COMPLETE |
| Stage 6 (Red Team) | COMPLETE |
| Stage 7 (Resonance) | COMPLETE |
| Stage 7b (Fragility) | COMPLETE |
| Stage 8 (Decision) | COMPLETE |
| Stage 9 (Archive) | COMPLETE |
| Gate 2 (Confirmation) | COMPLETE |
| Gate 3 (Position) | COMPLETE |

## Quick Start

```bash
# GUI (Command Center dashboard)
cd projects/marketmind
python app.py

# CLI daily analysis
python app.py --mode daily --mock --verbose

# Dashboard
python api_server.py
# Open http://localhost:8520

# AEL experiment
python scripts/ael_experiment.py
```

## Model Routing (Flash vs Pro)

DeepSeek Flash: data collection, simple classification, auxiliary processing
DeepSeek Pro: deep analysis, adversarial reasoning, shadow analysis, final report writing

All LLM calls route through `gateway/async_client.py` — no module should call httpx directly.

## Testing

```bash
# All tests
cd projects/marketmind
python -m pytest tests/ -v --tb=short -p no:warnings

# Shadow ecosystem only
python -m pytest tests/test_shadows/ -v --tb=short

# API tests
python -m pytest tests/test_api/ -v --tb=short

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
