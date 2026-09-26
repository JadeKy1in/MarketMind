# MarketMind v2.0

> AI-Powered Investment Analysis Workstation · Multi-Agent Shadow Ecosystem
> AI 驱动的投资分析工作站 · 多智能体影子生态系统

MarketMind is a personal AI investment analysis platform. Every morning, it collects global financial news from 37 sources, runs deep analysis through a 10-stage LLM pipeline, and presents structured investment decisions. 24 independent AI "shadows" — each a virtual fund manager with their own domain, strategy, and methodology — operate in a tiered ecosystem with self-evolution and graduation. A Playground sandbox allows experimental agents (like serenity-reply, a distilled semiconductor analyst persona) to run in isolation, be tracked for performance, and graduate into the main pipeline as validated signal sources.

MarketMind 是一个个人 AI 投资分析平台。每天从 37 个全球信息源采集新闻，通过 10 阶段 LLM 管道进行深度分析，输出结构化投资决策。24 个独立 AI「影子」在分层生态中运行并自进化。Playground 实验沙箱让外部 skills（如 serenity-reply 半导体分析师）在隔离环境中接受绩效追踪，通过验证后升级为主管道信号源。

**MarketMind does not trade for you. You remain the final decision maker.**
**MarketMind 不替你交易。你始终是最终决策者。**

---

## Quick Start · 快速开始

```bash
# Web Dashboard (recommended)
cd projects/marketmind
python api_server.py
# Open http://localhost:8520
# Playground: http://localhost:8520/playground
# Evolution:  http://localhost:8520/evolution

# CLI daily analysis
python app.py --mode daily --mock --verbose

# Mock pipeline + Playground experimental agents
python app.py --mode daily --mock --playground -v

# Live pipeline (real API, ~7min)
python app.py --mode daily --playground -v

# Run tests
python -m pytest tests/ -q -p no:warnings
```

## Architecture · 架构

```
10-stage Main Pipeline · 主管道
  Scout (37 sources) → Flash Triage → HVR → L1 Narrative →
  L2 Fundamental + L3 Technical → Red Team → Resonance → Decision
  Self-Evolution: Daily Calibration → Weekly Tactical Audit → Cross-Stage Attribution

24-Shadow Ecosystem · 影子生态
  16 Experts + 8 Daredevils · Tier: ELITE/EXCELLENT/NORMAL/ENDANGERED
  3-stage Elimination Pipeline · Zombie Detector at startup
  Graduation → Gate 2 discussion rights

Playground · 实验沙箱
  Isolated agent sandbox with information firewall
  serenity-reply (semiconductor bottleneck analyst) — first入驻 agent
  60-day observation → upgrade gate → pipeline signal source
```

## Key Numbers · 关键数据

| Metric · 指标 | Value · 值 |
|------|:--:|
| Information sources · 信息源 | 37 (main Scout) + 8 (Playground CORE) |
| Shadow agents · 影子 | 24 (16 Experts + 8 Daredevils) |
| Playground agents · 实验 | 1 (serenity-reply) |
| Self-evolution layers · 进化层 | 3 (main pipeline) + 3 (shadow AEL) |
| Tests · 测试 | all passing |
| PICA audit · 审计 | 全链通过 |

## Tech Stack · 技术栈

Python · FastAPI · asyncio · httpx · DeepSeek · SQLite · yfinance · scipy · numpy · CustomTkinter · pytest

## Development · 开发指南

- **[CLAUDE.md](CLAUDE.md)** — Workspace conventions · 工作区规范
- **[projects/marketmind/CLAUDE.md](projects/marketmind/CLAUDE.md)** — Architecture guide · 架构指南
- **[.claude/RESTART_GUIDE.md](.claude/RESTART_GUIDE.md)** — Session restart · 会话重启
- **[docs/playground-agent-onboarding.md](docs/playground-agent-onboarding.md)** — Playground agent 入驻指南（中英双语）
