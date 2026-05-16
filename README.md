# MarketMind

> AI-Powered Investment Analysis Workstation · AI 驱动的投资分析工作站

MarketMind is an AI-native investment analysis workstation that processes daily market signals through an adversarial pipeline. It ingests multi-source news, runs layered narrative/fundamental/technical analysis, cross-validates findings via an independent Red Team challenger, and surfaces high-conviction investment decisions — all orchestrated through an autonomous shadow agent ecosystem that hunts for bias, collusion, and missed counterfactuals.

MarketMind 是一个 AI 原生的投资分析工作站，通过对抗性管道处理每日市场信号。系统采集多源新闻，运行分层分析，由独立 Red Team 对抗审查交叉验证，最终输出高置信度投资决策——整个过程由自主运行的影子代理生态编排，持续追猎偏见、合谋与错失的反事实路径。

---

## Quick Start

```bash
# GUI dashboard
cd projects/marketmind
python app.py

# CLI daily analysis (mock mode)
python app.py --mode daily --mock --verbose

# Run tests
python -m pytest projects/marketmind/tests/ -v --tb=short
```

## Key Capabilities

- **Adversarial Pipeline** — Scout → Flash Preprocess → Narrative → Fundamental + Technical → Shadow Ecosystem → Red Team → Resonance → Decision → Archive
- **Shadow Agent Ecosystem** — 21+ independent analyst shadows (expert, daredevil, catfish, temp event, missed path) with virtual capital, composite ranking, collusion detection, and emergency quota audits
- **Red Team Auditor** — Structurally independent adversary hunting for confirmation bias, survivorship bias, and unsupported claims
- **Counterfactual Tracking** — Missed-path shadows quantify what would have happened if rejected directions were chosen
- **Resonance Validation** — Statistical cross-check of signal alignment across narrative, fundamental, technical, and sentiment dimensions
- **Dual Interface** — CLI for batch runs + CustomTkinter GUI with live dashboard, decision cards, and shadow status panels

## Tech Stack

Python · asyncio · httpx · yfinance · feedparser · CustomTkinter · SQLite · pytest

## Development

For architecture details, model routing, testing commands, and full project structure:

- **[CLAUDE.md](CLAUDE.md)** — Global workspace conventions and workflow
- **[projects/marketmind/CLAUDE.md](projects/marketmind/CLAUDE.md)** — MarketMind-specific architecture and development guide
