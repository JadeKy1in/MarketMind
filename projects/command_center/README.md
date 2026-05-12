# Command Center — Interactive Investment UI

Four-quadrant desktop GUI for the SignalFoundry investment pipeline. One-click daily report generation, shadow mode comparison, and deep macro research with Blue/Red adversarial review.

## Quick Start

```bash
python -m projects.command_center.app
```

## Architecture

```
app.py (CustomTkinter GUI)
├── ui/dashboard_panel.py — One-click buttons, status display
├── ui/chat_panel.py — Report display, multi-model chat
├── ui/main_window.py — Pipeline orchestration
├── engine/optimizer.py — Monte Carlo simulation
├── engine/shadow_comparator.py — Shadow mode comparison
├── engine/reporter.py — Report generation
├── gateway/router.py — Flash/Pro model routing
├── gateway/flash_adapter.py — DeepSeek Flash API
├── intelligence/scraper.py — DuckDuckGo search
├── intelligence/research_agent.py — Multi-source research
├── intelligence/fact_checker.py — Fact verification
└── config/settings_manager.py — Hot-reload settings
```

## Pipeline Integration

The "One-Click Daily" button automatically:
1. Detects SignalFoundry Phase B availability
2. Routes to SignalFoundry pipeline (preferred) or native pipeline (fallback)
3. Displays report in chat panel
4. Saves to `output/reports/`

## Features

- **Daily Report**: One-click full analysis with Pro model deep research
- **Shadow Comparison**: Monte Carlo simulation with 10,000 paths
- **Macro Research**: 6-agent concurrent research with CoT reasoning
- **Settings Hub**: Hot-reload fonts, themes, API keys without restart
- **Multi-Attachment**: Image (OCR), PDF, Markdown support
