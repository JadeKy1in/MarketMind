# SignalFoundry — Automated Macro Investment Research

Daily pipeline: news aggregation → deep analysis → adversarial review → multi-profile recommendations.

## Quick Start

```bash
# Daily full pipeline
python src/main.py --mode daily --verbose

# Mock mode (no API calls)
python src/main.py --mode daily --mock --verbose

# Single ticker
python src/main.py --mode strict --ticker NVDA --verbose

# Shadow simulation (21 scenarios)
python src/main.py --simulate --verbose

# Cognitive review
python src/main.py --review 2026-05-08
```

## Architecture

```
S1: Scout — 57 sources across 8 regions (crypto, equities, commodities, macro)
S2: Deep Dive — Fundamental (Soros reflexivity) + Technical (SMA/MACD) + Event (Blue/Red) + Sentiment
S2.5: Cognitive Review — Yesterday's predictions vs today's reality
S3: Resonance — Weighted 4D aggregation (F20/T25/E30/S25)
S4: Portfolio — Multi risk-reward profiles (conservative/balanced/aggressive)
S5: Pro Model — DeepSeek Pro deep analysis with asset chain penetration
S6: Output — Structured Markdown report with specific price triggers
```

## Key Modules

| Module | Layer | Purpose |
|--------|-------|---------|
| `src/main.py` | All | Unified entry point |
| `src/deepseek_client.py` | L1 | LLM gateway (Flash/Pro routing) |
| `src/scout_fetcher.py` | S1 | Multi-region news aggregation |
| `src/fundamental_engine.py` | S2 | Reflexivity analysis |
| `src/technical_engine.py` | S2 | Weekly SMA/MACD |
| `src/event_engine.py` | S2 | Blue/Red adversarial arbitration |
| `src/sentiment_engine.py` | S2 | Sentiment classification |
| `src/resonance_aggregator.py` | S3 | 4D weighted resonance |
| `src/capital_manager.py` | S4 | Position sizing |
| `src/pro_model_deep_dive.py` | S5 | Pro prompt builder |
| `src/shadow_personalities.py` | C | 6-personality shadow trading |
| `src/lateral_proxy.py` | Verification | Indirect data verification |
| `src/news_authenticity_scorer.py` | Verification | Source credibility scoring |
| `src/methodology_evolver.py` | Evolution | White-box method improvement |
| `config/asset_universe.py` | - | Robinhood-tradable assets |
| `config/source_authority.py` | - | 35+ global news sources |

## Investment Philosophy

1. Low risk, high reward priority — cash is a weapon
2. Multi-horizon flexibility (intraday to monthly)
3. Every trade has a timeline and specific price trigger
4. Never chase the last copper — we lag institutions
5. Maintain 10%+ cash reserve

## Requirements

```
pip install httpx pandas yfinance
```

Set `DEEPSEEK_API_KEY` in `.env`.
