# MarketMind — Multi-Agent Investment Analysis Platform

AI 驱动的投资信号验证与决策支持系统。25 个独立分析影子并行评估市场信号，通过投票、排名、挑战者淘汰机制形成投资决策。

**[→ 项目代码](projects/marketmind/)** | **1,998 tests · 0 fail · 0 skip**

---

## 架构

```
28 News Sources → Scout → Flash Triage → L1 Narrative (A-E Grade)
    ↓
L2 Fundamentals + L3 Technicals (parallel)
    ↓
25-Shadow Ecosystem (16 Experts + 8 Daredevils + 1 Catfish)
    ├── Independent analysis → Voting → Ranking → Crystallization
    ├── 3-stage Challenger elimination (stats + Calmar gate)
    └── Collusion detection + Emergency quota audit
    ↓
Red Team + Resonance → Decision → Archive
```

**Real-time**: WebSocket → Dashboard (status lights, shadow rankings, stage progress)

---

## Quick Start

```bash
cd projects/marketmind

# Dashboard → http://localhost:8520
python api_server.py

# Mock analysis (no API cost)
python app.py --mode daily --mock -v

# Real API
python app.py --mode daily -v

# Run tests
python -m pytest tests/ -v -m "not slow" -p no:warnings
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI | DeepSeek Flash (light) + DeepSeek Pro (deep analysis) |
| Backend | Python 3.11+, FastAPI + Uvicorn, WebSocket |
| Frontend | Vanilla HTML/CSS/JS Dashboard |
| Data | SQLite (WAL), RSS/JSON API feeds (28 sources) |
| Stats | SciPy, NumPy, scikit-learn |
| CI/CD | GitHub Actions (auto-test on push) |

---

## Shadow Ecosystem

25 AI agents, each with independent methodology, risk profile, and domain:

- **16 Experts**: Domain specialists (gold, crypto, energy, bonds, volatility, etc.)
- **8 Daredevils**: High-risk strategies (momentum, mean-reversion, breakout)
- **1 Catfish**: Anti-consensus — warns when everyone agrees

**Ranking**: Daily composite score (MPPM + Sharpe + Calmar + Omega + Win Rate). Walk-Forward Efficiency validation prevents overfitting.

**Elimination**: 3-stage pipeline — warning → secret challenger → paired comparison (t-test + Calmar gate).

**ELITE**: Top performers get extra quota + higher vote weight.

---

## Tests

```
1,998 passed, 0 failed, 0 skipped
├── Pipeline:    1,019  (Scout, Flash, L1-L3, Red Team, Resonance, Decision)
├── Shadows:       492  (Agent, Ranking, Challenger, Crystallization, Memory)
├── API:            16  (Routes, WebSocket, Data Providers)
├── Real-API:        5  (9-stage full pipeline with live LLM, skipped in CI)
└── Other:         466  (Storage, Config, Gateway, UI, Tools)
```

---

## Development Gates

| Gate | When | What |
|------|------|------|
| **PreToolUse** | Before any Edit/Write | Task declaration required (`current_task.json`) |
| **Pre-commit** | Before commit | 500-line ceiling per `.py` file |
| **Stop Gate** | Session end | 7 PICA audits (unit, security, integration, regression, architecture, plan, review) |
| **CI** | On push | Full test suite via GitHub Actions |

---

## Project Structure

```
projects/marketmind/
├── pipeline/          # 10-stage analysis pipeline
│   ├── scout.py               # 28-source news collection
│   ├── layer1_narrative.py    # L1 event grading + matrix
│   ├── layer2_fundamental.py  # L2 fundamental analysis
│   ├── layer3_technical.py    # L3 technical analysis
│   ├── red_team.py            # adversarial challenge
│   ├── resonance.py           # statistical validation
│   └── decision.py            # final synthesis
├── shadows/          # 25-shadow ecosystem
│   ├── shadow_mother.py       # daily orchestration
│   ├── ranking_engine.py      # composite scoring
│   └── challenger_engine.py   # 3-stage elimination
├── api/              # FastAPI server
│   ├── routes.py              # REST endpoints
│   └── websocket.py           # real-time push
├── gateway/          # LLM routing
│   └── async_client.py        # DeepSeek Flash/Pro
├── config/           # configuration
├── storage/          # archiving (JSON + SQLite FTS5)
├── tests/            # 1,998 tests
└── data/             # runtime data (organized by date)
```

---

## Setup

Copy `.env.example`:
```bash
DEEPSEEK_API_KEY=your_key
NEWSAPI_KEY=your_key       # optional
GNEWS_API_KEY=your_key     # optional
```
