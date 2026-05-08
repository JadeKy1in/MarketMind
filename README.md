# SkillFoundry

SkillFoundry: Open AI-Agent Infrastructure Forge -- Contextual Event Sourcing, Belief-Driven Decision Systems, and Dual-Model Cognitive Architecture.

SkillFoundry（技能熔炉）：开放的 AI 智能体基础设施熔炉——基于情境化事件溯源的信念驱动决策系统与双模型认知架构。

---

## Vision

SkillFoundry is not a single product. It is a collection of independently deployable, hot-pluggable sub-projects -- each a complete technical-validation prototype developed under the Skill Foundry Standard (Section 4 of .clinerules). The ecosystem validates the following architectural patterns through real, compilable, tested code:

SkillFoundry 并非单一产品。它是一系列可独立部署、可热插拔的子项目集合——每个子项目都是一个完整的技术验证原型，遵循 Skill Foundry Standard（.clinerules 第 4 节）开发流程。生态系统通过真实的可编译、可测试的代码验证以下架构模式：

- **Dual-Model Cognitive Architecture**: A Pro model (deep reasoning, serial execution) and a Flash model (high-throughput, concurrent execution) routed by an intelligent `LLMRouter` that classifies each task by type, priority, and estimated token budget.
  双模型认知架构：Pro 模型（深度推理、串行执行）与 Flash 模型（高吞吐、并发执行），由智能 `LLMRouter` 按任务类型、优先级和预估 Token 预算分类路由。

- **Belief-Driven Decision**: External intelligence is ingested through a three-stage pipeline (Scraper, FactChecker, BeliefModifier) into a `BeliefStateManager` that maintains a Beta-distributed belief knowledge graph -- a falsifiable, confidence-weighted representation of the system's worldview.
  信念驱动决策：外部情报经由三级管线（Scraper, FactChecker, BeliefModifier）摄入 `BeliefStateManager`，该系统维护一个 Beta 分布信念知识图谱——系统世界观的、可证伪的、置信加权的表达。

- **Contextual Event Sourcing (情境化事件溯源)**: This is the core architectural principle of the SkillFoundry ecosystem. It is not a rigid, globally enforced pattern but a contextually applied discipline. Within `BeliefStateManager`, observations are append-only immutable events and `BeliefNode` is atomically replaced on each update (frozen dataclass replacement). Within `ShadowComparator`, Monte Carlo paths are pure functional simulations with no System.Random state leakage. This principle is applied where it provides maximum value -- auditability, testability, and state recovery -- without imposing unnecessary ceremony on latency-sensitive or ephemeral operations.
  情境化事件溯源：这是 SkillFoundry 生态的核心架构原则。它不是僵化的全局死板规则，而是因地制宜应用的纪律。在 `BeliefStateManager` 中，观测是仅追加的不可变事件，`BeliefNode` 在每次更新时原子替换（冻结数据类替换）。在 `ShadowComparator` 中，Monte Carlo 路径是纯函数式模拟，无 System.Random 状态泄漏。该原则在能提供最大价值的地方应用——可审计性、可测试性和状态恢复——而不对延迟敏感或临时操作施加不必要的形式主义。

- **Monte Carlo Shadow Comparison**: A `ShadowComparator` executes 10,000 Geometric Brownian Motion paths against both the current portfolio and a suggested rebalance, comparing full return distributions (mean, median, standard deviation, VaR, CVaR, Sharpe ratio, win rate, max drawdown) to determine, with statistical significance, whether a rebalance is warranted.
  Monte Carlo 影子对比：`ShadowComparator` 对当前仓位和调仓建议各执行 10,000 条几何布朗运动路径模拟，比较完整收益分布（均值、中位数、标准差、VaR、CVaR、夏普比率、胜率、最大回撤），以统计显著性判断调仓是否合理。

- **Multimodal Perception**: Via OCR (image/PDF text extraction), web scraping (three-track A/B/C degradation), and an academic multi-source API matrix (Semantic Scholar, OpenAlex, arXiv fallback) -- the `IntakePipeline` and `AcademicScraper` classes embody this capability.
  多模态感知：通过 OCR（图片/PDF 文本提取）、网页抓取（三通道 A/B/C 降级）和学术多源 API 矩阵（Semantic Scholar, OpenAlex, arXiv 兜底）——由 `IntakePipeline` 和 `AcademicScraper` 类实现。

- **Introspective Risk Management**: Token budget tripwires, safe timeout patterns (explicit Promise<T> with clearTimeout in BOTH resolve and reject), and graceful degradation strategies are embedded at every layer. The `ReflectionOrchestrator` triggers scheduled belief decay at T = n x 50 trading steps (academic standard per arXiv:2505.04479).
  自省式风险管理：Token 预算熔断、安全超时模式（显式 Promise<T> 模式，clearTimeout 在 resolve 和 reject 双路调用）和优雅降级策略嵌入每一层。`ReflectionOrchestrator` 在 T = n x 50 交易步时触发定时信念衰减（学术标准，引自 arXiv:2505.04479）。

---

## Ecosystem Overview

```
                  SkillFoundry Meta Layer
  .clinerules -- SPARC Cognition Loop + PM Governance + Self-Evolution Matrices
  memory-bank/ -- The Archivist Persistent State Machine
  infrastructure/ -- MCP Skill Factory & SKILLS_MANIFEST.json
  docs/ -- Cline OS Blueprint & Architecture Whitepaper

  +----------------------------+    +-----------------------------+
  | Command Center V2.0        |    | Robinhood                   |
  | (Interactive Terminal)     |    | (Algorithm Engine)          |
  |                            |    |                             |
  |  Dual-Model Gateway        |    |  BeliefStateManager         |
  |  (ProAdapter+FlashAdapter) |    |  (Beta Belief Net)          |
  |  TaskQueue (async dispatch)|    |  Monte Carlo Simulator      |
  |  SettingsManager (Pub-Sub) |    |  ScoutFetcher (Multi-API)   |
  |  IntakePipeline (3-stage)  |    |  IngestionPipeline          |
  |  ShadowComparator (MC)     |    |  PatrolScheduler            |
  |  CustomTkinter UI          |    |  ReflectionOrchestrator     |
  +----------------------------+    +-----------------------------+

  +------------------------------------------+
  | MCP Servers (Tool Adapter Factory)       |
  |  Filesystem Server | Memory Server       |
  |  Playwright Server | (more in infra/)    |
  +------------------------------------------+
```

### Sub-Project Boundary Delineation

The ecosystem divides cleanly into two computational layers:

生态系统的计算分工明确划分为两层：

- **Robinhood (Algorithm Engine / 算法引擎)**: The headless backend -- pure computational logic with no user interface. It contains the `BeliefStateManager` (Beta-distributed belief network with gamma-decay and conflict resolution), `ScoutFetcher` (multi-source macro/market data scraping with Track A/B/C degradation), `IngestionPipeline` (RawEvent to DistilledEvent to BeliefObservation via headless LLM API), `PatrolScheduler` (daily timer-based ingestion with idempotency guards), `ReflectionOrchestrator` (scheduled belief decay at T=nx50), `BeliefMath` (pure mathematical kernel for Beta-Bernoulli conjugate updates and gamma-decay), `BeliefAwarePredictor` (belief-weight injection into `ShadowPrediction` objects), and `BeliefMemoryAdapter` (persistence bridge to the Memory MCP Server). Robinhood operates as a standalone module -- it can be imported, tested, and run independently of the Command Center UI.
  Robinhood（算法引擎）：无头后端——纯计算逻辑，无用户界面。包含 `BeliefStateManager`（具有 gamma 衰减和冲突解决的 Beta 分布信念网络）、`ScoutFetcher`（具有 Track A/B/C 降级的多源宏观/市场数据抓取）、`IngestionPipeline`（通过无头 LLM API 从 RawEvent 到 DistilledEvent 再到 BeliefObservation）、`PatrolScheduler`（具有幂等守卫的基于定时器的每日摄入）、`ReflectionOrchestrator`（T=nx50 的定时信念衰减）、`BeliefMath`（Beta-Bernoulli 共轭更新和 gamma 衰减的纯数学内核）、`BeliefAwarePredictor`（信念权重注入 `ShadowPrediction` 对象）、以及 `BeliefMemoryAdapter`（到 Memory MCP 服务器的持久化桥接）。Robinhood 作为独立模块运行——可独立于 Command Center UI 导入、测试和运行。

- **Command Center V2.0 (Interactive Terminal / 交互终端)**: The user-facing layer -- an interactive desktop application with a CustomTkinter GUI. It provides the `DualModelGateway` (`ProAdapter` + `FlashAdapter` + `LLMRouter` + `TaskQueue` with serial Pro queue and concurrent Flash pool), `SettingsManager` (singleton with Pub-Sub hot-reload and XOR-obfuscated API key storage), `IntakePipeline` (Scraper to FactChecker to BeliefModifier orchestration), `ShadowComparator` (10,000-path Monte Carlo GBM simulation), `Optimizer` (belief-weighted portfolio rebalancing with drift detection), `Reporter` (structured Markdown report generation with optional PDF export), `SemanticTranslator` (LLM-based statistical-to-narrative translation), and the complete `CustomTkinter UI` suite (MainWindow, DashboardPanel, ChatPanel, ShadowComparisonPanel, IntakeBar, SettingsModal, ReportViewer). Command Center does NOT duplicate Robinhood's belief math -- it delegates to Robinhood via the `IntakePipeline`'s `BeliefModifier` which produces `BeliefModificationSuggestion` objects that align with Robinhood's `PRELOADED_PROPOSITIONS` schema.
  Command Center V2.0（交互终端）：面向用户层——具有 CustomTkinter GUI 的交互式桌面应用程序。提供 `DualModelGateway`（`ProAdapter` + `FlashAdapter` + `LLMRouter` + 具有串行 Pro 队列和并发 Flash 池的 `TaskQueue`）、`SettingsManager`（具有 Pub-Sub 热重载和 XOR 混淆 API Key 存储的单例）、`IntakePipeline`（Scraper 到 FactChecker 到 BeliefModifier 的编排）、`ShadowComparator`（10,000 路径 Monte Carlo GBM 模拟）、`Optimizer`（具有漂移检测的信念加权投资组合再平衡）、`Reporter`（具有可选 PDF 导出的结构化 Markdown 报告生成）、`SemanticTranslator`（基于 LLM 的统计到叙事翻译）、以及完整的 `CustomTkinter UI` 套件（MainWindow, DashboardPanel, ChatPanel, ShadowComparisonPanel, IntakeBar, SettingsModal, ReportViewer）。Command Center 不重复 Robinhood 的信念数学——它通过 `IntakePipeline` 的 `BeliefModifier` 委托给 Robinhood，该修改器生成与 Robinhood 的 `PRELOADED_PROPOSITIONS` 模式一致的 `BeliefModificationSuggestion` 对象。

---

## One-Command Ecosystem Launch

The entire ecosystem can be brought up from the repository root with a single command:

从仓库根目录使用单条命令即可启动整个生态系统：

```batch
launch_command_center.bat
```

This batch script automates:
1. Python 3.10+ detection
2. Virtual environment creation (projects/command_center/venv)
3. Dependency installation (httpx, customtkinter, pytest, optional python-dotenv and pdfplumber)
4. `.env` reading for `DEEPSEEK_API_KEY` (optional -- Mock mode without it)
5. UI launch via `python -m projects.command_center.app`

该批处理脚本自动执行：
1. Python 3.10+ 检测
2. 虚拟环境创建
3. 依赖安装
4. `.env` 中的 `DEEPSEEK_API_KEY` 读取（可选——无 Key 时进入 Mock 模式）
5. 通过 `python -m projects.command_center.app` 启动 UI

Robinhood's Patrol dry-run can be executed independently:

Robinhood 的 Patrol 试车可独立执行：

```bash
python run_patrol_dryrun.py
```

---

## Architectural Principles: Contextual Event Sourcing (情境化事件溯源)

The system explicitly rejects the "one-size-fits-all" application of Event Sourcing. Instead, it applies the principle contextually where it provides concrete, measurable benefits:

系统明确拒绝"一刀切"式应用事件溯源。相反，它在能提供具体、可量化收益的地方因地制宜地应用该原则：

| Domain (领域) | Application (应用方式) | Why (理由) |
|---|---|---|
| Belief Observation Log | Append-only immutable event stream. `BeliefObservation` is a frozen dataclass; `BeliefNode` is atomically replaced on update. | Audit trail for every belief change; full conflict resolution traceability; deterministic replay for backtesting. |
| Shadow Predictions | Immutable `ShadowPrediction` with `verdict` field set by `TribunalVerdict`. The `BatchShadowRun` envelope commits all predictions atomically. | Complete record of what was predicted, when, by which scenario, and whether it passed or failed. |
| Monte Carlo Simulations | Pure functional -- no System.Random state leakage. Each simulation is input -> output with explicit seed for reproducibility. | Every comparison run is independently verifiable; exactly the same inputs always produce exactly the same outputs. |
| Settings Storage | NOT event-sourced. `SettingsManager` uses a single `config.json` file with Pub-Sub for hot-reload. | The overhead of an event log for user preferences would be counterproductive. Snapshot consistency is sufficient. |

---

## Repository Structure

```
SkillFoundry/
├── .clinerules                    # Cognitive Matrices (Matrix 1-8)
├── README.md                      # <- You are here
├── LICENSE                        # MIT
├── launch_command_center.bat      # One-command ecosystem launcher
├── run_patrol_dryrun.py           # Robinhood Patrol standalone dry-run
├── memory-bank/                   # The Archivist Persistent State Machine
│   ├── activeContext.md
│   ├── progress.md
│   ├── decision_log.md
│   ├── transcript_ledger.md
│   └── projectBrief.md
├── infrastructure/                # MCP Skill Factory
│   ├── SKILLS_MANIFEST.json       # Skill Registration Registry
│   ├── skills/                    # MCP Server Implementations
│   └── README.md
├── projects/
│   ├── command_center/            # Interactive Terminal (UI Layer)
│   │   ├── gateway/               #   Dual-model adapter + router
│   │   ├── intelligence/          #   Scraper/FactChecker/BeliefModifier
│   │   ├── engine/                #   ShadowComparator/Optimizer/Reporter
│   │   ├── config/                #   SettingsManager + Pub-Sub
│   │   ├── ui/                    #   CustomTkinter Panels
│   │   └── tests/                 #   Test suite
│   └── robinhood/                 # Algorithm Engine (Backend Logic)
│       ├── src/                   #   Belief state math & management
│       ├── tests/                 #   Test suite
│       └── .env.example
├── docs/
│   └── cline_os_blueprint_v1.0.md # Architecture Whitepaper
└── scripts/                       # Utility scripts
```

---

## Design Principles

| Principle | Description |
|---|---|
| DRY First | No duplication. Infrastructure layer and Memory Bank are the single source of truth for all sub-projects. |
| The Archivist | Every session must update activeContext.md and progress.md before declaring completion. |
| Safe Timeout | Explicit `Promise<T>` pattern; `clearTimeout` in BOTH resolve and reject handlers. No `Promise.race()`. |
| Token Budget Tripwire | Tiered response strategy across the 1M Token window (Level 1: 50%, Level 2: 80%, Level 3: 95%). |
| PM Governance (Step 0) | Cross-file modifications require Scout/Challenger/Handoff four-step SOP before any code changes. |
| Skill Foundry Standard | New skills proceed through Discovery -> Interface -> Adapter -> Test -> Register (5 phases). |
| Contextual Event Sourcing | Event sourcing applied where it provides measurable auditability value; not applied where it would be overhead without benefit. |
| Academia-Grounded Decay | Belief decay interval of 50 trading steps calibrated from TradingGroup arXiv:2505.04479. Gamma factor gamma=0.95 from Silent Scholar arXiv:2504.18924. |

---

## License

MIT License -- see [LICENSE](LICENSE)