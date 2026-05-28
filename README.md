# MarketMind · 市场心智

> AI 驱动的投资信号验证与决策支持 · 多智能体影子生态 · Playground 实验沙箱  
> AI-Powered Investment Signal Validation & Decision Support · Multi-Agent Shadow Ecosystem · Playground Sandbox

MarketMind 每天早上从 37 个全球信息源采集新闻，通过 10 阶段 LLM 管道进行深度分析，输出结构化投资决策。24 个独立 AI「影子」在分层生态中并行分析、投票、进化。Playground 实验沙箱让外部 agent 在信息防火墙隔离下运行，通过 6 关审计后升级为主管道信号源。三层自进化体系持续优化管线质量。

MarketMind collects news from 37 global sources daily, runs deep analysis through a 10-stage LLM pipeline, and delivers structured investment decisions. 24 independent AI shadows analyze, vote, rank, and evolve in a tiered ecosystem. The Playground sandbox lets external agents run behind an information firewall, tracked for performance, graduating through 6 audit gates into the main pipeline. A 3-layer self-evolution system continuously optimizes the pipeline.

**[→ 项目代码 / Source](projects/marketmind/)** | **1,998 tests · 0 fail · 0 skip**

**MarketMind does not trade for you. You remain the final decision maker.**
**MarketMind 不替你交易。你始终是最终决策者。**

---

## 快速开始 / Quick Start

```bash
cd projects/marketmind

# Dashboard → http://localhost:8520
python api_server.py
# Playground: http://localhost:8520/playground
# Evolution:  http://localhost:8520/evolution

# Mock 管线（不消耗 API, ~1min）
python app.py --mode daily --mock -v

# Mock + Playground agent
python app.py --mode daily --mock --playground -v

# 实盘管线（真实 API, ~7min）
python app.py --mode daily --playground -v

# 交互模式（Socratic 对话 + 决策确认）
python app.py --mode interactive -v

# 全量测试
python -m pytest tests/ -q -p no:warnings
```

---

## 架构 / Architecture

```
主管线 / Main Pipeline (10 stages + 3 gates)
  Scout (37 sources) → Flash Triage → HVR Investigation → L1 Narrative
  → L2 Fundamental + L3 Technical (parallel) → Shadows → Red Team
  → Resonance → Fragility → Decision → Archive
  
  Self-Evolution: Daily Calibration → Weekly Tactical Audit → Cross-Stage Attribution

Playground / 实验沙箱 (isolated, information firewall)
  WP API (6) + RSS (2) → agent.adapter.analyze() → daily report + audit log
  serenity-reply (semiconductor analyst) — first入驻 agent
  60-day observation → 6-gate audit → pipeline signal source

影子生态 / Shadow Ecosystem (non-blocking background)
  24 shadows (16 Experts + 8 Daredevils)
  Tier: ELITE / EXCELLENT / NORMAL / ENDANGERED
  3-stage elimination: Warning → Challenger → 21-day paired t-test
  Zombie Detector: startup code-vs-DB consistency check
```

---

## 关键数据 / Key Numbers

| 指标 / Metric | 值 / Value |
|------|:--:|
| 信息源 / Sources | 37 (主 Scout) + 8 (Playground CORE) + 1 Supplement + 6 Retired |
| 管线阶段 / Pipeline Stages | 10 + 3 gates |
| 影子 / Shadows | 24 (16 Experts + 8 Daredevils) |
| Playground Agent | 1 (serenity-reply) |
| 自进化层 / Self-Evolution | 3 (calibration → weekly audit → cross-stage attribution) |
| 测试 / Tests | 1,998 pass · 0 fail · 0 skip |

---

## 影子生态 / Shadow Ecosystem

24 个 AI agent，各自拥有独立方法论、风险偏好和领域专长。
24 AI agents, each with independent methodology, risk profile, and domain expertise.

| 类型 / Type | 数量 | 特点 |
|:--|:--:|:--|
| **Experts / 专家** | 16 | 领域专精：黄金、加密货币、能源、债券、波动率、期权等 |
| **Daredevils / 冒险者** | 8 | 高风险策略：动量、均值回归、突破、反转 |

**评分 / Ranking**: 复合评分（MPPM + Sharpe + Calmar + Omega + Win Rate），Walk-Forward Efficiency 防过拟合。Tier 分布面板代替跨域排名——不同波动率体质的影子不可直接比较序数。

**淘汰 / Elimination**: 3 阶段管道——警告 → 挑战者 → 21 天配对检验（t-test + Calmar 门控）。

**ELITE 资格**: 顶级表现者获得 Gate 2 讨论权和更高投票权重。

**僵尸检测 / Zombie Detection**: 每次启动对比代码 vs 数据库，发现不存在的影子立即标记。

---

## Playground / 实验沙箱

独立 agent 实验层——外部分析框架在信息防火墙隔离下运行，通过审计后升级接入主管道。

Isolated agent sandbox — external analytical frameworks run behind an information firewall, graduate into the main pipeline after passing audit.

| 概念 | 说明 |
|:--|:--|
| **Agent** | 独立分析模块，有独特框架和视角 |
| **信息防火墙** | Agent 只收到公开数据，收不到主管道 L1/L2/L3/Red Team/Decision |
| **升级门控** | 6 关（观察期 ≥60天、样本 ≥20、准确率 ≥55% p<0.05、Sharpe ≥0.5、回撤 ≤25%、相关性 ≤0.7） |
| **数据通道** | WP REST API（完整文章 JSON）+ RSS/Atom feed |

**入驻 Agent**: 新建 `playground/agents/<id>/` 目录，编写 `manifest.json` + `adapter.py`，详见 **[入驻指南](projects/marketmind/docs/playground-agent-onboarding.md)**。

**已入驻**: serenity-reply（半导体瓶颈分析师）——基于 5 个思维模型、8 条决策启发式，双轮 Flash 分析 + 研究循环。

---

## 技术栈 / Tech Stack

| 层 / Layer | 技术 / Technology |
|-----------|-------------------|
| AI 推理 | DeepSeek Flash (轻量) + DeepSeek Pro (深度) |
| 后端 | Python 3.11+, FastAPI + Uvicorn, WebSocket |
| 前端 | 原生 HTML/CSS/JS Dashboard + Playground 卡片 UI |
| 数据 | SQLite (WAL), 37 RSS/JSON API 新闻源 + 8 Playground WP/RSS |
| 统计 | SciPy, NumPy, scikit-learn |
| CI/CD | GitHub Actions（push 自动全量测试） |

---

## 测试 / Tests

```
1,998 passed, 0 failed, 0 skipped
├── Pipeline:    1,019  (Scout, Flash, L1-L3, Red Team, Resonance, Decision)
├── Shadows:       492  (Agent, Ranking, Challenger, Crystallization, Memory)
├── API:            16  (Routes, WebSocket, Data Providers)
├── 实盘:            5  (全管线真实 LLM，CI 跳过)
└── 其他:          466  (Storage, Config, Gateway, UI, Tools)
```

---

## 项目结构 / Project Structure

```
projects/marketmind/
├── pipeline/          # 10 阶段分析管线 + 3 层自进化
│   ├── scout.py                   # 37 源新闻采集
│   ├── flash_triage.py            # Stage 2 快速分流
│   ├── hvr/                       # Stage 2b 高价值研究
│   ├── layer1_narrative.py        # L1 事件评级
│   ├── layer2_fundamental.py      # L2 基本面
│   ├── layer3_technical.py        # L3 技术面
│   ├── red_team.py                # 对抗挑战
│   ├── resonance.py               # 统计验证
│   ├── decision.py                # 决策合成
│   ├── daily_calibration.py       # 自进化 L1: 日校准
│   ├── weekly_tactical_audit.py   # 自进化 L2: 周审计
│   └── methodology_evolution.py   # 自进化 L3: 跨阶段归因
├── playground/        # 实验沙箱
│   ├── agent_manifest.py          # Agent 自声明格式
│   ├── playground_runner.py       # 每日运行 + 信息防火墙
│   ├── playground_fetcher.py      # WP API + RSS 双通道
│   ├── playground_sources.py      # 16 源注册表（8 CORE + 1 SUP + 6 RETIRED）
│   ├── playground_auditor.py      # 月度审计 + 6 关升级门控
│   ├── playground_tracker.py      # 结算跟踪
│   └── agents/serenity_reply/     # 首个入驻 agent
├── shadows/           # 24 影子生态
│   ├── shadow_mother.py           # 每日编排
│   ├── ranking_engine.py          # 复合评分
│   ├── challenger_engine.py       # 3 阶段淘汰
│   └── zombie_detector.py         # 启动时代码 vs DB 一致性检查
├── api/               # FastAPI 服务
│   ├── routes.py                  # REST 端点
│   ├── websocket.py               # 实时推送
│   └── dashboard_server.py        # Playground 卡片 UI
├── gateway/           # LLM 路由
│   └── async_client.py            # DeepSeek Flash/Pro
├── config/            # 配置
├── storage/           # 归档（JSON + SQLite FTS5）
├── tests/             # 1,998 项测试
├── docs/              # 文档
│   └── playground-agent-onboarding.md  # 入驻指南（中英双语）
└── data/              # 运行时数据（按日期组织）
```

---

## 开发门禁 / Development Gates

| 门禁 / Gate | 何时 / When | 作用 / What |
|------------|------------|------------|
| **PreToolUse** | 编辑 .py 前 | 需声明任务 (`current_task.json`) |
| **Pre-commit** | 提交前 | 每文件 500 行上限 |
| **Stop Gate** | 会话结束 | 7 项 PICA 审计 |
| **CI** | Push 时 | GitHub Actions 自动全量测试 |

---

## 设置 / Setup

复制 `projects/marketmind/.env.example` 为 `.env`：
```bash
DEEPSEEK_API_KEY=your_key
NEWSAPI_KEY=your_key       # 可选
GNEWS_API_KEY=your_key     # 可选
```
