# MarketMind

> AI-Powered Investment Analysis Workstation · AI 驱动的投资分析工作站

---

## English

MarketMind is an AI-native investment analysis workstation that processes daily market signals through a 9-stage adversarial pipeline. It ingests multi-source news, runs layered narrative/fundamental/technical analysis, cross-validates findings via an independent Red Team challenger, and surfaces high-conviction investment decisions — all orchestrated through an autonomous shadow agent ecosystem that hunts for bias, collusion, and missed counterfactuals.

**Key Capabilities**

- **9-Stage Daily Pipeline** — Scout → Flash Preprocess → L1 Narrative → L2 Fundamental + L3 Technical (parallel) → Shadow Ecosystem → Red Team → Resonance → Decision → Archive
- **Adversarial Quality Control** — Structurally independent Red Team auditor hunts for confirmation bias, survivorship bias, and unsupported claims with hard A-grade thresholds
- **Shadow Agent Ecosystem** — Expert, daredevil, and catfish agents with independent virtual capital, ranked by composite performance metrics (MPPM, Calmar, Omega, win rate), with collusion detection and emergency quota audits
- **Counterfactual Tracking** — Missed-path shadows record what would have happened if rejected directions were chosen, quantifying survivorship bias
- **Resonance Validation** — Statistical cross-check of signal alignment across narrative, fundamental, technical, and sentiment dimensions
- **Dual Interface** — CLI for daily batch runs + CustomTkinter GUI with live dashboard, decision cards, position cards, and shadow status panels

**Tech Stack**

Python · asyncio · httpx · yfinance · feedparser · CustomTkinter · SQLite · pytest (38 test suites)

---

## 中文

MarketMind 是一个 AI 原生的投资分析工作站，通过 9 阶段对抗性管道处理每日市场信号。系统采集多源新闻，运行分层叙事/基本面/技术面分析，由独立 Red Team 对抗审查交叉验证，最终输出高置信度投资决策——整个过程由自主运行的影子代理生态编排，持续追猎偏见、合谋与错失的反事实路径。

**核心能力**

- **9 阶段日度管道** — Scout 新闻采集 → Flash 信号预处理 → L1 叙事分析 → L2 基本面 + L3 技术面（并行）→ Shadow 影子生态 → Red Team 对抗审查 → Resonance 共振验证 → Decision 决策合成 → Archive 归档
- **对抗性质控** — 结构独立的 Red Team 审计者追猎确认偏差、幸存者偏差和无据论断，设有硬性 A 级质疑门槛
- **影子代理生态** — 专家型、冒险型、鲶鱼型三类影子代理，各有独立虚拟资本，按复合绩效指标（MPPM、Calmar、Omega、胜率）排名，内置合谋检测与紧急配额审计
- **反事实追踪** — Missed-path 影子记录被拒绝方向"本来会发生什么"，量化幸存者偏差
- **共振验证** — 统计交叉检验叙事、基本面、技术面、情绪面多维度信号一致性
- **双界面** — CLI 日度批处理 + CustomTkinter GUI 实时仪表盘，含决策卡片、持仓卡片、影子状态面板

**技术栈**

Python · asyncio · httpx · yfinance · feedparser · CustomTkinter · SQLite · pytest（38 套测试）
