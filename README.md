# SignalFoundry

Automated macro investment research platform. Multi-region news aggregation (57 sources, 8 regions) → DeepSeek Pro adversarial analysis → multi-horizon investment recommendations with shadow simulation.

自动化宏观投资研究平台。多区域新闻聚合（57个信源、8个区域）→ DeepSeek Pro 红蓝对抗深度分析 → 多期限投资建议 + 影子模拟。

## Projects

| Project | Purpose | Stack |
|---------|---------|-------|
| [SignalFoundry](projects/robinhood/) | Daily macro analysis pipeline | Python, DeepSeek V4, yfinance |
| [Command Center](projects/command_center/) | Interactive investment UI | Python, CustomTkinter |
| [Browser Automation](infrastructure/skills/browser-automation/) | Multi-track content extraction | TypeScript, VLM |

## Quick Start

```bash
# Command Center GUI
python -m projects.command_center.app

# Daily analysis (CLI)
cd projects/robinhood
python src/main.py --mode daily --mock --verbose

# Health check
python scripts/health_check.py
```

## Architecture

```
Scout (57 sources, 8 regions)
  → Four-Dimensional Analysis (Fundamental / Technical / Event / Sentiment)
  → Blue/Red Adversarial Review
  → Resonance Aggregation
  → Multi-Profile Investment Recommendations
  → Shadow Simulation (6 personalities × 4 horizons × 3 daily cycles)
  → Cognitive Review & Methodology Evolution
```

## Model Routing

| Model | Role |
|-------|------|
| DeepSeek Flash | Data collection, sentiment classification |
| DeepSeek Pro | Deep analysis, adversarial reasoning, report writing |
| Claude (Cowork) | Development & architecture |

## Development

Uses Cowork with `/tri` three-model collaboration (Opus architecture → Sonnet planning → Haiku execution). See [CLAUDE.md](CLAUDE.md) for full rules.
