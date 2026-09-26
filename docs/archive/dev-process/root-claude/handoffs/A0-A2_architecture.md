# ARCHITECTURE_HANDOFF — MarketMind Phase A (A.0-A.2)

**Date:** 2026-05-11
**Architect:** Design embedded in implementation plan (`docs/superpowers/plans/2026-05-11-marketmind-phase-a.md`)
**Status:** IMPLEMENTED (commits 7d054c5, 82465ae, 0154264)

## A.0 Foundation

### Modules
- `gateway/async_client.py` — Singleton DeepSeekGateway, chat_flash/chat_pro/chat_batch_flash/chat_with_integrity
- `gateway/token_budget.py` — TokenBudget with Priority enum, 429 backoff, reserve/release
- `config/settings.py` — MarketMindConfig dataclass, env-var loading, validate()
- `config/asset_universe.py` — 25 Robinhood-tradable assets (equity/ETF/crypto)
- `config/source_authority.py` — 4-tier source authority (Tier 1-4), SourceStatus tracking

### Key Decisions
- All LLM calls route through `async_client.py` — no module calls httpx directly
- TokenBudget uses Priority queue with CRITICAL/HIGH/NORMAL/LOW levels
- Config loaded from env vars with validation on startup

## A.1 Data Pipeline

### Modules
- `pipeline/scout.py` — Multi-source RSS fetch, 3-tier degradation (RSS→HTML→paid→human), NewsItem dedup
- `pipeline/cache.py` — Async DataCache with TTL, hit/miss stats, thread-safe
- `pipeline/flash_preprocessor.py` — Batch Flash preprocessing, JSON signal extraction, denoising

### Key Decisions
- Scout must never fabricate data — empty list on total failure
- Cache TTL default 300s, per-entry overrides accepted (Note: TTL storage bug fixed post-audit)
- Flash batches capped at 15 items per call

## A.2 Analysis Engines

### Modules
- `pipeline/layer1_narrative.py` — Event A-E grading, 2x2 matrix, price-in, cascade, sentiment
- `pipeline/layer2_fundamental.py` — 5-tier progressive: macro→asset→sector→factor→ticker
- `pipeline/layer3_technical.py` — 3-light review, entry/exit zone calculation (INDEPENDENT from L1/L2)
- `pipeline/red_team.py` — Adversarial challenge engine, structural independence
- `pipeline/resonance.py` — Pure-Python DSR/CSCV/PBO, no LLM dependency
- `pipeline/decision.py` — DecisionCard + NoTradeCard synthesis

### Key Decisions
- Layer 3 receives ONLY ticker list + raw market data — NOT L1/L2 conclusions
- Resonance: PBO > 10% → "no signal", requires >=3/4 dimensions for strong signal
- Red Team: structural independence, must produce >=1 A-grade objection per cycle
- Decision: parallel trade + no-trade cards with equal analytical depth
