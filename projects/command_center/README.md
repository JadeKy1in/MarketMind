# Cline OS Command Center V2.0

Cline OS Command Center V2.0: Local Quantitative Interactive Terminal -- Dual-Model Gateway, Multi-Source Intelligence Pipeline, and Monte Carlo Shadow Comparison Engine.

Cline OS Command Center V2.0：本地量化交互终端——双模型网关、多源情报管线、Monte Carlo 影子对比引擎。

---

## Overview

Command Center V2.0 is the user-facing interactive terminal of the SkillFoundry ecosystem. It is a locally running desktop application built on CustomTkinter that provides a complete multi-modal cognitive interface for quantitative decision support. Unlike Robinhood (the headless algorithm engine), Command Center manages the complete lifecycle of user interaction: message routing, model dispatching, intelligence ingestion, portfolio optimization, shadow comparison, report generation, and settings management.

Command Center V2.0 是 SkillFoundry 生态的面向用户的交互终端。它是一个基于 CustomTkinter 构建的本地运行桌面应用程序，提供完整的量化决策支持多模态认知界面。与 Robinhood（无头算法引擎）不同，Command Center 管理用户交互的完整生命周期：消息路由、模型调度、情报摄入、投资组合优化、影子对比、报告生成和设置管理。

---

## Architecture

The system is organized into four layered subsystems:

系统组织为四个层次化子系统：

```
UI Layer (Layer 4: Interaction / 交互层)
  MainWindow + DashboardPanel + ChatPanel + ShadowComparisonPanel
  + IntakeBar + SettingsModal + ReportViewer
  |
  | (thread-safe callback bridge)
  v
Gateway Layer (Layer 3: Cognition / 认知层)
  LLMRouter (priority-based task classification)
  -> TaskQueue (background asyncio event loop)
     -> ProAdapter (serial, DeepSeek Pro)
     -> FlashAdapter (concurrent, DeepSeek Flash)
  |
  v
Intelligence Layer (Layer 2: Perception / 感知层)
  Scraper (three-track A/B/C) -> FactChecker -> BeliefModifier
  AcademicScraper (Semantic Scholar, OpenAlex, arXiv)
  OCRReader (image/PDF/text extraction)
  |
  v
Engine Layer (Layer 1: Analysis / 分析层)
  ShadowComparator (Monte Carlo 10,000-path GBM simulation)
  Optimizer (belief-weighted drift detection + rebalance suggestions)
  SemanticTranslator (statistical-to-narrative translation)
  Reporter (Markdown + optional PDF export)

Cross-Cutting:
  SettingsManager (Singleton + Pub-Sub hot-reload, config.json persistence)
  TokenBudget (cross-model cost tracking and budget tripwire)
```

---

## Gateway Layer: Dual-Model Cognitive Architecture (双模型认知架构)

### LLMRouter (`gateway/router.py`)

The routing decision engine is a pure function with zero network I/O. It uses priority-based keyword matching to classify each user input into a `TaskProfile` containing:

路由判定引擎是纯函数，零网络 I/O。它使用基于优先级的关键词匹配将每个用户输入分类为包含以下内容的 `TaskProfile`：

- `target_model`: `TargetModel.PRO` (deep reasoning) or `TargetModel.FLASH` (high throughput)
- `task_type`: One of 14 `TaskType` enums (URL_FETCH, DOC_SUMMARIZE, STRATEGY_DEBATE, REBALANCE_ADVICE, etc.)
- `priority`: HIGH, NORMAL, LOW, or BACKGROUND
- `estimated_tokens`: Rough token count estimate
- `confidence`: Routing confidence score [0, 1]

Routing rules (defined in `ROUTING_RULES`) are evaluated in priority order -- first match wins. Flash handles mechanical tasks (URL fetch, summarization, fact-checking, formatting). Pro handles strategic tasks (strategy debate, rebalance advice, belief debate, deep analysis, report narration). The final fallback rule sends unclassifiable inputs to Flash for a cheap classification call.

路由规则按优先级顺序评估——第一个匹配胜出。Flash 处理机械任务（URL 抓取、摘要、事实核查、格式化）。Pro 处理策略任务（策略复盘、调仓建议、信念辩论、深度分析、报告叙事）。最后一条 fallback 规则将不可分类的输入发送给 Flash 进行廉价分类调用。

### ProAdapter (`gateway/pro_adapter.py`)

DeepSeek V4 Pro adapter for serial, deep-reasoning tasks. Inherits from `LLMAdapter` ABC.

用于串行深度推理任务的 DeepSeek V4 Pro 适配器。继承自 `LLMAdapter` ABC。

- `chat()`: Non-streaming API call with `httpx.AsyncClient`, exponential backoff retry (up to `max_retries`), and Safe Timeout pattern (explicit `asyncio.sleep` between retries, not `Promise.race()`).
  非流式 API 调用，具有指数退避重试和安全超时模式。

- `chat_stream()`: SSE-based streaming via `async with client.stream()`.
  基于 SSE 的流式调用。

- **Mock mode**: Automatically activates when `api_key` is empty. Returns structured mock responses without network calls.
  当 `api_key` 为空时自动激活。返回结构化模拟响应，无需网络调用。

### FlashAdapter (`gateway/flash_adapter.py`)

DeepSeek Flash adapter for high-throughput, concurrent tasks. Shares `LLMAdapter` ABC with `ProAdapter` but uses distinct config (lower temperature 0.1, lower max_tokens 4096, higher max_retries 3).

用于高吞吐并发任务的 DeepSeek Flash 适配器。与 `ProAdapter` 共享 `LLMAdapter` ABC，但使用不同的配置。

### TaskQueue (`gateway/task_queue.py`)

Thread-safe dual-model dispatch queue. This is the PM engineering red-line implementation -- ensuring the UI thread is NEVER blocked.

线程安全的双模型调度队列。这是 PM 工程红线实现——确保 UI 线程永不阻塞。

- **Architecture**: Runs its own `asyncio` event loop in a background daemon thread. UI thread submits tasks via `submit()` which calls `asyncio.run_coroutine_threadsafe()`.
  架构：在后台守护线程中运行自己的 `asyncio` 事件循环。UI 线程通过 `submit()` 提交任务。

- **Pro serial queue**: Pro tasks are executed one at a time to guarantee reasoning order.
  Pro 串行队列：Pro 任务一次执行一个，保证推理顺序。

- **Flash concurrent pool**: Flash tasks run in parallel up to `flash_max_concurrent` (default 5).
  Flash 并发池：Flash 任务并行运行。

- **Callback bridge**: Results are delivered back to the UI thread via a `queue.Queue` + `drain_callbacks()` pattern.
  回调桥接：通过 `queue.Queue` + `drain_callbacks()` 模式将结果送回 UI 线程。

- **Token Budget**: `TokenBudget` tracks total input/output tokens, Pro/Flash call counts, and provides a budget tripwire (`is_exceeded`).
  Token 预算：追踪总输入/输出 token、Pro/Flash 调用次数，并提供预算熔断。

- **Safe Timeout compliance**: Uses explicit `asyncio.sleep` in retry loops with `clearTimeout` in both resolve and reject paths. No `Promise.race()`.
  安全超时合规：在重试循环中使用显式 `asyncio.sleep`。

- **Task lifecycle**: Every task transitions through PENDING -> RUNNING -> COMPLETED/FAILED/CANCELLED. Full traceability via `get_task(task_id)`.
  任务生命周期：每个任务经历 PENDING -> RUNNING -> COMPLETED/FAILED/CANCELLED 状态转换。

---

## Intelligence Layer: Multi-Source Intake Pipeline (多源情报摄入管线)

### Scraper (`intelligence/scraper.py`)

Three-track URL content extraction:

三通道 URL 内容提取：

- **Track A (HTTP)**: `httpx.AsyncClient` GET with redirect support. Extracts raw HTML from target URL.
  HTTP GET 获取原始 HTML。

- **Track B (LLM extraction)**: Sends raw text to `FlashAdapter.chat()` with a structured extraction prompt. Returns JSON with summary, sentiment (bullish/bearish/neutral), confidence [0,1], and extracted entities.
  将原始文本发送给 `FlashAdapter.chat()`，返回带摘要、情绪、置信度和提取实体的 JSON。

- **Track C (Mock)**: Returns mock `ScrapedContent` when no FlashAdapter is configured (for testing/offline use).
  当未配置 FlashAdapter 时返回模拟的 `ScrapedContent`。

### AcademicScraper (`intelligence/scraper.py` -- AcademicScraper class)

Multi-source academic paper search matrix. Implements Matrix 8 (Anti-Scraping & Compliance Act) of .clinerules:

多源学术论文搜索矩阵。实现 .clinerules 的 Matrix 8（反爬虫与合规法案）：

- **Semantic Scholar API** (Track S2): `GET /graph/v1/paper/search` with fields=title,abstract,authors,year,citationCount.
- **OpenAlex API** (Track OA): `GET /works` with search query. Requires `User-Agent: mailto:<email>` header for polite pool access.
- **arXiv API** (Track AR): XML-based query interface as fallback when both S2 and OA fail.

Strategy: Concurrently query S2 and OA; merge and deduplicate (by normalized title); if both fail, fall back to arXiv. Each source is independently try-except guarded -- one source failure never blocks another.

策略：并发查询 S2 和 OA；合并并去重（按归一化标题）；如果两者都失败，回退到 arXiv。每个源有独立的 try-except 保护——一个源的故障不会阻塞另一个。

### FactChecker (`intelligence/fact_checker.py`)

Verifies `ScrapedContent` against known fact databases and LLM reasoning. Produces a `FactCheckReport` with score [0, 100], overall verdict (verified/contradicted/indeterminate/unverifiable), and source confidence.

对已知事实数据库和 LLM 推理验证 `ScrapedContent`。生成带有评分、整体裁决和来源置信度的 `FactCheckReport`。

### BeliefModifier (`intelligence/belief_modifier.py`)

Generates `BeliefModificationPlan` from `ScrapedContent` + `FactCheckReport`. The plan contains `BeliefModificationSuggestion` objects that align with Robinhood's `PRELOADED_PROPOSITIONS` schema -- ensuring that Command Center's belief modifications are consumable by Robinhood's `BeliefStateManager`.

从 `ScrapedContent` + `FactCheckReport` 生成 `BeliefModificationPlan`。该计划包含与 Robinhood 的 `PRELOADED_PROPOSITIONS` 模式一致的 `BeliefModificationSuggestion` 对象——确保 Command Center 的信念修改可被 Robinhood 的 `BeliefStateManager` 消费。

- `_match_propositions()`: Keyword-based proposition matching with relevance scoring (0.0 to 1.0).
  基于关键词的命题匹配和相关性评分。

- `_determine_urgency()`: Urgency derived from report score, relevance score, and direction.
  从报告评分、相关性评分和方向推导紧急程度。

- `_build_register_suggestion()`: When no existing proposition matches, generates a new proposition registration suggestion.
  当没有现有命题匹配时，生成新命题注册建议。

### IntakePipeline (`intelligence/intake_pipeline.py`)

Pipeline orchestrator chaining Scraper -> FactChecker -> BeliefModifier. Each stage is independently mockable, with inter-stage degradation (FactChecker can be skipped without blocking BeliefModifier). Full execution telemetry via `IntakePipelineResult` (latency_ms per stage, successes count, error dict).

管线编排器，串联 Scraper -> FactChecker -> BeliefModifier。每个阶段可独立模拟，具有级间降级能力。通过 `IntakePipelineResult` 提供完整执行遥测。

### OCRReader (`intelligence/ocr_reader.py`)

Multi-modal file parser for images, PDFs, Markdown, and plain text. Designed to run on background threads to avoid blocking the UI.

用于图片、PDF、Markdown 和纯文本的多模态文件解析器。设计在后台线程上运行，避免阻塞 UI。

- **Images**: Base64-encoded data URIs for Flash Vision API.
  图片：Base64 编码的数据 URI，用于 Flash Vision API。

- **PDF**: `pdfplumber` text extraction with try-except graceful degradation to plain text reading on failure.
  PDF：`pdfplumber` 文本提取，失败时优雅降级为纯文本读取。

- **Text files**: Direct UTF-8 reading with errors='replace'.
  文本文件：直接 UTF-8 读取。

- `build_vision_messages()`: Constructs OpenAI-compatible vision messages from OCR output, merging image data URIs with textual context.
  从 OCR 输出构建 OpenAI 兼容的视觉消息，合并图片数据 URI 和文本上下文。

---

## Engine Layer: Analysis and Decision Support (分析与决策支持)

### ShadowComparator (`engine/shadow_comparator.py`)

Monte Carlo simulation engine that compares current portfolio vs. suggested rebalance across 10,000 Geometric Brownian Motion paths.

Monte Carlo 模拟引擎，对当前仓位与调仓建议在 10,000 条几何布朗运动路径上进行比较。

- `_simulate_gbm(days)`: Single-asset GBM with drift `(daily_return - 0.5 * vol^2) * dt` and diffusion `vol * sqrt(dt) * Z`.
  单资产 GBM，含漂移和扩散项。

- `_simulate_portfolio_returns(weights)`: Portfolio-weighted aggregation across all assets.
  跨所有资产的投资组合加权聚合。

- `compare(positions, suggestions)`: Full `ComparisonResult` with `DistributionStats` for both strategies (mean, median, std, VaR, CVaR, Sharpe, max drawdown, win rate), `improvement`, `risk_reduction`, `convergence_score`, and `suggested_is_preferred` boolean.

- **Transaction cost modeling**: `_compute_transaction_cost()` applies `transaction_cost_pct` (default 0.1%) to total portfolio turnover.
  交易成本建模：将交易成本百分比应用于总投资组合换手率。

- **Deterministic result**: `suggested_is_preferred` is True when improvement > 0.1% OR (risk_reduction > 0.1% AND win rate does not significantly drop).
  确定性结果：当收益改善 > 0.1% 或（风险降低 > 0.1% 且胜率不显著下降）时为 True。

### Optimizer (`engine/optimizer.py`)

Portfolio rebalancing engine with belief-weighted scoring and drift detection.

具有信念加权评分和漂移检测的投资组合再平衡引擎。

- `compute_belief_scores(belief_snapshots)`: Maps `BeliefSnapshot` objects to per-ticker scores using `DEFAULT_TICKER_BELIEF_MAP` (ticker -> proposition_id mapping).
  使用 `DEFAULT_TICKER_BELIEF_MAP` 将 `BeliefSnapshot` 对象映射到每个 ticker 的评分。

- `_detect_drifts(positions, target_weights, total_value)`: Compares current vs. target weights. Returns `DriftRecord` list sorted by absolute drift magnitude. Drifts exceeding `drift_threshold` (default 3%) generate suggestions.
  比较当前 vs 目标权重。返回按绝对漂移幅度排序的 `DriftRecord` 列表。超过漂移阈值的漂移生成建议。

- `_generate_suggestions()`: Creates `RebalanceSuggestion` with delta_shares, urgency (HIGH at >10% drift, MEDIUM at >5%, LOW below), and belief-weighted narrative.
  创建带有股数变动、紧急度等级和信念加权叙事的 `RebalanceSuggestion`。

### SemanticTranslator (`engine/semantic_translator.py`)

LLM-based statistical-to-narrative translation. Converts `ComparisonResult` (arrays of floats) into human-readable action narratives.

基于 LLM 的统计到叙事翻译。将 `ComparisonResult`（浮点数数组）转换为人类可读的行动叙事。

### Reporter (`engine/reporter.py`)

Structured Markdown report generator with optional PDF export via weasyprint.

结构化 Markdown 报告生成器，通过 weasyprint 可选 PDF 导出。

- `build_markdown(data)`: Assembles report header, executive summary, positions table, belief summary table, rebalance suggestions table, Monte Carlo comparison section, and detailed translation section.
  组装报告页眉、执行摘要、仓位表、信念摘要表、调仓建议表、Monte Carlo 对比部分和详细翻译部分。

- `build_pdf(data, output_dir)`: Try-except wrapped PDF generation. If weasyprint is not installed, silently returns None (graceful degradation).
  Try-except 包装的 PDF 生成。如果未安装 weasyprint，静默返回 None（优雅降级）。

---

## SettingsManager: Singleton with Pub-Sub Hot-Reload (发布-订阅设置中心)

### `config/settings_manager.py`

Global settings manager implementing the Singleton pattern with Observer-based hot-reload.

实现单例模式及基于观察者的热重载的全局设置管理器。

- **Persistence**: Reads/writes `config.json` (located at `config/config.json`). File not found falls back to `DEFAULT_SETTINGS` from `config/defaults.py`.
  持久化：读写 `config.json`。文件不存在时回退到 `DEFAULT_SETTINGS`。

- **Nested access**: `get("appearance.font_family")` and `set("appearance.font_family", "SimHei")` via dot-path notation.
  嵌套访问：通过点号路径表示法。

- **API Key obfuscation**: `set_api_key(key)` XOR-encrypts + base64-encodes the key using a machine fingerprint (`uuid.uuid1() + platform.node() + uuid.getnode()` hashed with SHA256). `get_api_key()` decrypts or falls back to `DEEPSEEK_API_KEY` environment variable.
  API Key 混淆：使用机器指纹对密钥进行 XOR 加密 + base64 编码。`get_api_key()` 解密或回退到环境变量。

- **Pub-Sub**: `subscribe(callback)` registers a callback that receives the full settings dict on `notify()`. `save_and_notify()` persists to disk and broadcasts to all subscribers for hot-reload.
  发布-订阅：`subscribe(callback)` 注册一个回调，该回调在 `notify()` 时接收完整设置字典。`save_and_notify()` 持久化到磁盘并广播给所有订阅者进行热重载。

- **Default merge**: `_merge_defaults()` ensures newly added config keys in `DEFAULT_SETTINGS` are automatically added to existing `config.json`, preventing key errors after updates.
  默认值合并：确保 `DEFAULT_SETTINGS` 中新添加的配置键自动添加到现有 `config.json` 中。

---

## Environment Configuration (.env)

Command Center optionally reads a `.env` file from `projects/command_center/.env`:

Command Center 可选地从 `.env` 文件读取配置：

```ini
# DeepSeek API Key (required for real model calls; optional -- Mock mode without it)
# DeepSeek API Key（真实模型调用需要；可选——无 Key 时进入 Mock 模式）
DEEPSEEK_API_KEY=sk-your-key-here

# Optional: Custom API endpoint overrides
# 可选：自定义 API 端点覆盖
# DEEPSEEK_PRO_ENDPOINT=https://api.deepseek.com/v1/chat/completions
# DEEPSEEK_FLASH_ENDPOINT=https://api.deepseek.com/v1/chat/completions

# Optional: Custom model names
# 可选：自定义模型名称
# DEEPSEEK_PRO_MODEL=deepseek-chat
# DEEPSEEK_FLASH_MODEL=deepseek-chat

# Optional: LLM_API_KEY for Robinhood's IngestionPipeline Distiller
# When set, Robinhood's PatrolPipeline uses real LLM distillation instead of MockDistiller
# 设置后，Robinhood 的 PatrolPipeline 使用真实 LLM 蒸馏而非 MockDistiller
# LLM_API_KEY=sk-your-llm-key
# LLM_API_URL=https://api.openai.com/v1/chat/completions
```

Without `.env`, the system operates in full Mock mode -- all model calls return simulated responses, and the UI is fully functional for demonstration and evaluation.

没有 `.env`，系统在完整 Mock 模式下运行——所有模型调用返回模拟响应，UI 完全可用于演示和评估。

---

## Launch Instructions (.bat Startup)

### Windows (One-Click Launch)

```batch
launch_command_center.bat
```

This batch file (located at the repository root) performs:

该批处理文件执行以下操作：

1. Change to the SkillFoundry root directory.
   切换到 SkillFoundry 根目录。

2. Detect Python 3.10+. Exit with error message if not found.
   检测 Python 3.10+。未找到时退出并显示错误消息。

3. Create a virtual environment at `projects/command_center/venv` if it does not exist.
   如果不存在，在 `projects/command_center/venv` 创建虚拟环境。

4. Install core dependencies from `projects/command_center/requirements.txt` (httpx, customtkinter, pytest, pytest-asyncio).
   从 `projects/command_center/requirements.txt` 安装核心依赖。

5. Attempt to install optional dependencies (python-dotenv for .env loading, pdfplumber for PDF extraction). Failures are silent.
   尝试安装可选依赖（.env 加载的 python-dotenv，PDF 提取的 pdfplumber）。失败时静默。

6. Activate the venv and launch: `python -m projects.command_center.app`
   激活 venv 并启动。

7. On application crash, pause with error message before terminal closes.
   应用程序崩溃时，在终端关闭前暂停并显示错误消息。

### Linux / macOS (Manual Launch)

```bash
cd projects/command_center
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install python-dotenv pdfplumber  # optional
python -m projects.command_center.app
```

---

## UI Suite (CustomTkinter)

The UI is built on CustomTkinter and organized into independent panels, each managing its own layout and event bindings:

UI 基于 CustomTkinter 构建，组织为独立面板，每个面板管理自己的布局和事件绑定：

| Panel | File | Responsibility |
|---|---|---|
| MainWindow | `ui/main_window.py` | Root window, tab navigation, menu bar |
| DashboardPanel | `ui/dashboard_panel.py` | Portfolio overview, belief summary cards, key metrics |
| ChatPanel | `ui/chat_panel.py` | Message history (user + assistant), input box, submit button |
| ShadowComparisonPanel | `ui/shadow_comparison_panel.py` | Monte Carlo results visualization, distribution comparison table, verdict display |
| IntakeBar | `ui/intake_bar.py` | URL input field, file attachment button, intake pipeline status indicator |
| SettingsModal | `ui/settings_modal.py` | Form-based API key input, theme selection, font picker, save/cancel |
| ReportViewer | `ui/report_viewer.py` | Scrollable Markdown-rendered report with PDF export button |

---

## Directory Structure

```
projects/command_center/
├── app.py                            # Application entry point (.env -> SettingsManager -> TaskQueue -> UI)
├── requirements.txt                  # Minimal dependencies: httpx, customtkinter, pytest, pytest-asyncio
├── launch_command_center.bat         # (at repo root) One-click Windows launcher
├── config/
│   ├── __init__.py
│   ├── defaults.py                   # DEFAULT_SETTINGS dictionary
│   └── settings_manager.py           # Singleton + Pub-Sub hot-reload
├── gateway/
│   ├── __init__.py
│   ├── router.py                     # LLMRouter (priority-based routing)
│   ├── task_queue.py                 # TaskQueue (thread-safe async dispatch)
│   ├── pro_adapter.py                # ProAdapter (LLMAdapter ABC, DeepSeek Pro)
│   └── flash_adapter.py             # FlashAdapter (LLMAdapter ABC, DeepSeek Flash)
├── intelligence/
│   ├── __init__.py
│   ├── scraper.py                    # Scraper (3-track) + AcademicScraper (multi-API matrix)
│   ├── fact_checker.py               # FactChecker (verification engine)
│   ├── belief_modifier.py            # BeliefModifier (modification plan generator)
│   ├── intake_pipeline.py            # IntakePipeline (3-stage orchestrator)
│   └── ocr_reader.py                 # OCRReader (image/PDF/text parser)
├── engine/
│   ├── __init__.py
│   ├── shadow_comparator.py          # ShadowComparator (MC 10,000-path GBM)
│   ├── optimizer.py                  # Optimizer (belief-weighted rebalance)
│   ├── reporter.py                   # Reporter (Markdown + optional PDF)
│   └── semantic_translator.py        # SemanticTranslator (LLM narrative)
├── ui/
│   ├── __init__.py
│   ├── main_window.py                # Root window
│   ├── dashboard_panel.py            # Portfolio overview
│   ├── chat_panel.py                 # Message history + input
│   ├── shadow_comparison_panel.py    # MC results display
│   ├── intake_bar.py                 # URL/file intake
│   ├── settings_modal.py             # Settings form
│   └── report_viewer.py              # Report renderer
├── models/
│   ├── __init__.py
│   └── position.py                   # Position, RebalanceSuggestion data models
├── tests/
│   ├── conftest.py
│   ├── test_task_queue.py
│   ├── test_router.py
│   ├── test_engine.py
│   ├── test_intelligence.py
│   ├── test_settings_manager.py
│   ├── test_chat_panel.py
│   └── test_integration.py
└── .gitignore
```

---

## Running Tests

```bash
cd projects/command_center
python -m pytest tests/ -v --tb=short

# Run specific test file:
python -m pytest tests/test_router.py -v --tb=short
```

---

## Design Principles Enforced at the Source Level

| Principle | Enforcement |
|---|---|
| UI Thread Never Blocked | `TaskQueue` runs a background asyncio event loop. All LLM calls execute off the UI thread. Results delivered via callback queue. |
| Safe Timeout (SS3.7.d) | Explicit `asyncio.sleep` in retry loops with clearTimeout in both resolve and reject. No `Promise.race()`. |
| Anti-Scraping Compliance (Matrix 8) | `AcademicScraper` uses multi-API matrix (Semantic Scholar + OpenAlex + arXiv). No DOM scraping of Google Scholar. OpenAlex includes `mailto:` User-Agent. 0.5s sleep between requests. |
| Graceful Degradation | No API key -> Mock mode. pdfplumber not installed -> text fallback. weasyprint not installed -> Markdown only. |
| XOR API Key Obfuscation | API keys stored as `XOR(machine_fingerprint) + base64`. Not encryption, but prevents accidental screenshot exposure. |
| Pub-Sub Hot-Reload | `SettingsManager.subscribe()` enables real-time UI updates when settings change. `save_and_notify()` triggers all subscribers. |
| Observation Isolation | `IntakePipeline` wraps each stage in try-except. Scraper failure does not block BeliefModifier. FactChecker skip does not block pipeline completion. |
| Stateless Routing | `LLMRouter.classify()` is a pure function with zero I/O. No side effects, no external state, thread-safe. |

---

## Relationship to Robinhood

- Command Center reads belief state from Robinhood's `BeliefStateManager` through the `SemanticTranslator`.
  Command Center 通过 `SemanticTranslator` 从 Robinhood 的 `BeliefStateManager` 读取信念状态。

- Command Center writes belief modifications through the `IntakePipeline`'s `BeliefModifier`, which produces suggestions aligned with Robinhood's `PRELOADED_PROPOSITIONS` schema.
  Command Center 通过 `IntakePipeline` 的 `BeliefModifier` 写入信念修改，该修改器生成与 Robinhood 的 `PRELOADED_PROPOSITIONS` 模式一致的建议。

- Command Center does NOT duplicate Robinhood's belief math (no `BeliefMath`, no `BeliefStateManager`). All belief computation is delegated to the Robinhood module.
  Command Center 不重复 Robinhood 的信念数学。所有信念计算委托给 Robinhood 模块。

---

## License

MIT -- part of the SkillFoundry ecosystem.