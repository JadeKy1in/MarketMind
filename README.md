# MarketMind v2.0

> AI-Powered Investment Analysis Workstation · Multi-Agent Shadow Ecosystem
> AI 驱动的投资分析工作站 · 多智能体影子生态系统

MarketMind is a personal AI investment analysis platform. Every morning, it collects global financial news from 35 sources, runs deep analysis through a 10-stage LLM pipeline, and presents structured investment decisions. Meanwhile, 24 independent AI "shadows" — each a virtual fund manager with their own personality, strategy, and data sources — compete in an internal ranking system, evolve their methodologies through 6 layers of self-evolution, and graduate to earn discussion rights at Gate 2.

MarketMind 是一个个人 AI 投资分析平台。每天从 35 个全球信息源采集新闻，通过 10 阶段 LLM 管道进行深度分析，输出结构化投资决策。同时，24 个独立 AI「影子」在内部排名系统中竞争，通过 6 层自进化持续优化方法论，并毕业获得 Gate 2 对话资格。

**MarketMind does not trade for you. You remain the final decision maker.**
**MarketMind 不替你交易。你始终是最终决策者。**

---

## Quick Start · 快速开始

```bash
# Web Dashboard (recommended)
cd projects/marketmind
python api_server.py
# Open http://localhost:8520

# CLI daily analysis
python app.py --mode daily --mock --verbose

# Inject external information
python app.py --mode daily --inject "Your info here" --inject-files report.pdf

# Run tests (1,744 tests)
python -m pytest projects/marketmind/tests/ -v --tb=short
```

## Architecture · 架构

```
10-stage Main Pipeline · 主管道
  Scout (35 sources) → Flash Triage → HVR Deep-dive → L1 Narrative →
  L2 Fundamental + L3 Technical → Red Team → Decision → Gate 1/2/3

24-Shadow Ecosystem · 影子生态
  16 Experts + 4 Momentum + 4 Contrarian · 16 专家 + 4 动量 + 4 逆向
  6-layer Self-Evolution · 6 层自进化
  Ranking → Challenger → Knowledge → Diversity → Crystallization → Simulation
```

## Key Numbers · 关键数据

| Metric · 指标 | Value · 值 |
|------|:--:|
| Python files · 文件 | 329 |
| Lines of code · 代码行 | ~79,000 |
| Tests · 测试 | 1,744 |
| Information sources · 信息源 | 17 |
| Shadow agents · 影子 | 24 |
| PICA audit · 审计 | 全链通过 |

## Tech Stack · 技术栈

Python · FastAPI · asyncio · httpx · DeepSeek · SQLite · yfinance · scipy · numpy · CustomTkinter · pytest

## Development · 开发指南

- **[CLAUDE.md](CLAUDE.md)** — Workspace conventions · 工作区规范
- **[projects/marketmind/CLAUDE.md](projects/marketmind/CLAUDE.md)** — Architecture guide · 架构指南
- **[.claude/RESTART_GUIDE.md](.claude/RESTART_GUIDE.md)** — Session restart · 会话重启
