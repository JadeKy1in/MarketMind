# MarketMind

> AI-Powered Investment Analysis Workstation · AI 驱动的投资分析工作站

MarketMind is an AI-native investment analysis platform that processes daily market signals through a multi-layer adversarial verification pipeline. The system collects news from 25 global sources, classifies → clusters → verifies hypotheses → decomposes causality → challenges adversarially → validates statistically → scans fragility, culminating in three user-interaction Gates for direction selection, signal confirmation, and position sizing. 23 independent shadow AI analysts run in parallel, competing internally without voting on main decisions.

MarketMind 是一个 AI 原生的投资分析平台，通过多层对抗验证管道处理每日市场信号。系统从 25 个全球信息源采集新闻，经过分类→聚类→假设验证→因果分解→对抗挑战→统计验证→脆弱性扫描，最终在三个用户交互 Gate 中完成方向确认、信号确认和仓位决策。23 个独立影子 AI 分析师并行运行，内部竞争排名，不参与主决策投票。

---

## Quick Start · 快速开始

```bash
cd E:\AI_Studio_Workspace\projects\marketmind

# Full pipeline with Gate 1/2/3 interaction · 完整管线（含 Gate 1/2/3 交互）
python app.py --mode full --mock --verbose

# Batch mode, no interaction · 后台批处理（无交互）
python app.py --mode daily --mock

# Gate 1 only · 单独跑 Gate 1
python app.py --mode gate1 --mock

# GUI dashboard · GUI 仪表盘
python app.py

# Full test suite · 全量测试
python -m pytest tests/ -q
```

## Pipeline Architecture · 管道架构

```
Stage 0 ──→ 1 ──→ 2 ──→ 2b ──→ [Gate 1] ──→ 3 ──→ 4 ──→ 5 ──→ 6 ──→ 7 ──→ 7b ──→ 8 ──→ 9
Shadow    Scout Flash  HVR     Direction    L1   L2+L3 Shadows Red  Res  Frag  Dec  Archive
 Init            +Clust  Loop   Confirm      Narr Fund+  (23)  Team onance ility  ision
                                                              ·Resonance
```

| Gate | User Decision · 用户决策 |
|------|------|
| Gate 1 | Select direction — AI presents 3 hypothesis cards with frequency framing, no ranking · 选择投资方向 |
| Gate 2 | Confirm conviction — interrogate AI analysis from multiple angles · 确认信号信心 |
| Gate 3 | Position sizing — Kelly formula, ATR stop-loss validation, pre-trade checklist · 仓位决策 |

## Depth of Analysis · 分析深度

- **10-Stage Pipeline · 10 阶段管道** — Scout (25 sources) → Flash signal extraction + event clustering → HVR investigation loop (hypothesis → 4-layer verification → adversarial self-check) · 新闻收集→信号提取+事件聚类→调查循环→4层验证→对抗自检
- **3 Interactive Gates · 3 个交互 Gate** — Direction → Signal → Position. AI provides analysis, user retains decision authority · AI 提供分析，用户保持决策权
- **Phase H Enhancement · Phase H 增强** — 9 asset-class causal decomposition, entity-level flow tracking, historical regime mapping, conditional scenario forecasting, systemic fragility scanning, cross-border capital flow analysis · 9资产类别因果分解/资金流追踪/体制映射/情景预测/脆弱性扫描/跨境分析
- **Phase I Learning Layer · Phase I 学习层** — 6-layer self-evolving system: prediction extraction → Brier calibration → structured post-mortem → entity memory → Platt scaling → cross-shadow knowledge distillation · 预测提取→Brier校准→结构化复盘→实体记忆→Platt缩放→知识蒸馏
- **23 Shadow AI Analysts · 23 影子分析师** — 15 domain experts + 8 strategy daredevils, internal ranking competition, no voting on main decisions · 内部竞争排名，不参与主决策投票
- **input_guard** — Shared input sanitization: prompt injection detection, Markdown escaping, Unicode normalization · 共享输入清洗：Prompt注入检测/Markdown转义/Unicode规范化

## Quality · 测试与质量

- **1,285 tests passed** · 75+ PICA audit artifacts · 13 Red Team audits · 1285 测试通过
- Enforced modular architecture: pipeline modules ≤500 lines · CLI entry points ≤150 lines · glue layers ≤300 lines · 模块架构强制

## Tech Stack · 技术栈

Python · asyncio · httpx · SQLite · CustomTkinter · pytest · DeepSeek Flash/Pro

## Development · 开发

- **[CLAUDE.md](../CLAUDE.md)** — Global workspace rules · 全局工作区规则
- **[CLAUDE.md](CLAUDE.md)** — MarketMind architecture & development guide · 架构和开发指南
