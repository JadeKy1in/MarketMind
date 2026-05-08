# Robinhood: Belief-Driven Algorithm Engine

Robinhood: Belief-Driven Quantitative Algorithm Engine -- Beta-Bernoulli State Estimation, Multi-Source Macro Data Ingestion, and Scheduled Belief Maintenance.

Robinhood：信念驱动的量化算法引擎——Beta-Bernoulli 状态估计、多源宏观数据摄入、定时信念维护。

---

## Overview

Robinhood is the headless algorithm engine of the SkillFoundry ecosystem. It contains no graphical user interface, no interactive terminal, and no network server. It is a pure computational kernel -- a collection of Python modules that can be imported, tested, and executed independently of any UI layer. It is the "backend brain" that the Command Center interactive terminal draws upon for belief state data and insight.

Robinhood 是 SkillFoundry 生态的无头算法引擎。它不含图形用户界面、交互终端或网络服务器。它是一个纯计算内核——一组 Python 模块集合，可独立于任何 UI 层导入、测试和执行。它是 Command Center 交互终端所依赖的"后端大脑"。

The engine operates as a four-layer architecture:

引擎运行在四层架构之上：

```
Layer 1: Perception (感知层)
  ScoutFetcher.fetch_all() -> RawEvent[]
    - Track A: FRED API (JSON) + Reuters RSS (XML)
    - Track B: Yahoo Finance HTML (regex extraction)
    - Track C: (reserved for Playwright MCP)

Layer 2: Distillation (蒸馏层)
  Distiller.distill() -> DistilledEvent[]
    - Headless LLM API call (OpenAI-compatible, no Agent context pollution)
    - JSON mode with strict schema enforcement
    - Retry-once on malformed output

Layer 3: Belief State (信念状态层)
  BeliefStateManager (Beta-distributed belief graph)
    - IngestObservation: beta_update with Phase 8.4 symmetric correction
    - ConflictDetection: expectation difference > threshold
    - Retirement: confidence_score < theta
    - GammaDecay: corrected decay toward uniform prior Beta(1,1)

Layer 4: Scheduled Maintenance (定时维护层)
  PatrolScheduler (daily timer-based ingestion)
  ReflectionOrchestrator (T = n x 50 belief decay)
  BeliefMemoryAdapter (Memory MCP persistence bridge)
```

---

## Core Modules and Their Source-Level Architecture

### BeliefStateManager (`src/belief_state_manager.py`)

The central orchestrator of the belief system. Maintains a registry of `BeliefNode` objects, each parameterized as Beta(alpha, beta). The manager operates in three layers:

信念系统的中央编排器。维护 `BeliefNode` 对象的注册表，每个节点参数化为 Beta(alpha, beta)。管理器在三个层次上运行：

- **Layer 1 (Ingestion)**: `register_node()` creates a new belief with a uniform prior Beta(1,1). `ingest_observation()` accepts a `BeliefObservation` (frozen dataclass with value [0,1], confidence [0,1], source, timestamp) and applies beta_update with Phase 8.4 symmetric correction: alpha' = alpha + value * confidence, beta' = beta + (1 - value) * confidence.
  Layer 1（摄入层）：`register_node()` 使用均匀先验 Beta(1,1) 创建新信念。`ingest_observation()` 接受 `BeliefObservation`（冻结数据类，包含 value [0,1], confidence [0,1], source, timestamp），应用 Phase 8.4 对称修正的 beta_update。

- **Layer 2 (Processing)**: `_apply_decay()` applies gamma-corrected decay toward Beta(1,1) proportional to elapsed time. `_detect_conflicts()` compares expectation values of sibling nodes for the same proposition; if |E[theta_left] - E[theta_right]| > conflict_threshold, both are marked CONFLICTED. `resolve_conflict()` applies three strategies (OVERRIDE_HIGHER_CONFIDENCE, MERGE, AMBIGUOUS_REJECT).
  Layer 2（处理层）：`_apply_decay()` 应用向 Beta(1,1) 的 gamma 修正衰减（与经过时间成比例）。`_detect_conflicts()` 比较同一命题的兄弟节点的期望值；如果 |E[theta_left] - E[theta_right]| > conflict_threshold，两者都被标记为 CONFLICTED。`resolve_conflict()` 应用三种策略（覆盖高置信、合并、模糊拒绝）。

- **Layer 3 (Querying)**: `get_snapshot()`, `list_active()`, `list_all()`, `search_nodes()` provide point-in-time views. `export_state()` produces a JSON-compatible dict for diagnostics and memory-bank serialization.
  Layer 3（查询层）：提供点状快照视图。`export_state()` 产生 JSON 兼容字典用于诊断和 memory-bank 序列化。

- **Memory MCP Integration**: `set_memory_adapter()` injects a `BeliefMemoryAdapter`; `sync_to_memory()` pushes the full belief graph to the Memory MCP Server's knowledge graph (entities, relations, observations).
   Memory MCP 集成：`set_memory_adapter()` 注入 `BeliefMemoryAdapter`；`sync_to_memory()` 将完整信念图推送到 Memory MCP 服务器的知识图（实体、关系、观测）。

Key invariants enforced by `BeliefNode.__post_init__()`: alpha >= 1.0, beta >= 1.0 (corrected decay prevents U-shaped Beta degeneration); status must be a valid `BeliefStatus` enum (ACTIVE, RETIRED, CONFLICTED); proposition_id is unique.

`BeliefNode.__post_init__()` 强制执行的关键不变性：alpha >= 1.0, beta >= 1.0（修正衰减防止 Beta U 型退化）；status 必须是有效的 `BeliefStatus` 枚举；proposition_id 唯一。

---

### BeliefMath (`src/belief_math.py`)

Pure mathematical kernel with zero external dependencies (no NumPy, no SciPy). Implements the Beta-Bernoulli belief framework from Silent Scholar (arXiv 2504.18924).

零外部依赖的纯数学内核。实现了 Silent Scholar (arXiv 2504.18924) 的 Beta-Bernoulli 信念框架。

- `beta_update(alpha, beta, value, confidence)`: Phase 8.4 symmetric correction eliminates the noise asymmetry bug where low-confidence observations were systematically bearish. The formula: alpha' = alpha + clamp(value) * clamp(confidence), beta' = beta + (1 - clamp(value)) * clamp(confidence).
  Phase 8.4 对称修正，消除了低置信观测系统性熊市的噪音不对称 bug。公式：alpha' = alpha + clamp(value) * clamp(confidence), beta' = beta + (1 - clamp(value)) * clamp(confidence)。

- `gamma_decay(alpha, beta, gamma=0.95, steps=1)`: PM-approved corrected formula: alpha' = 1.0 + (alpha - 1.0) * gamma^steps. Prevents Beta distribution from degenerating into U-shaped extreme beliefs by always decaying toward the uniform prior Beta(1,1).
  PM 批准的修正公式：alpha' = 1.0 + (alpha - 1.0) * gamma^steps。通过始终向均匀先验 Beta(1,1) 衰减，防止 Beta 分布退化为 U 型极端信念。

- `beta_uncertainty(alpha, beta)`: Var[theta] = (alpha * beta) / ((alpha+beta)^2 * (alpha+beta+1)). Measures epistemic uncertainty -- how much we don't know.
  认知不确定性——衡量我们未知的程度。

- `beta_expectation(alpha, beta)`: E[theta] = alpha / (alpha + beta). The posterior mean.
  后验均值。

- `confidence_score(alpha, beta)`: E[theta] / (1 + Var[theta]). Combined score balancing expectation and uncertainty, used for conflict resolution arbitration.
  结合期望和不确定性的综合评分，用于冲突解决仲裁。

---

### ScoutFetcher (`src/scout_fetcher.py`)

Multi-source macro/market data fetcher with three-track degradation strategy. Zero heavy dependencies beyond `requests` (for HTTP) and `xml.etree` (for RSS).

具有三通道降级策略的多源宏观/市场数据抓取器。

- **Track A (API/JSON)**: `fetch_fred_observations(series_id, api_key)` -- FRED economic data via JSON API. `fetch_reuters_rss(feed_url)` -- Reuters headlines via RSS XML.
  通过 JSON API 获取 FRED 经济数据。通过 RSS XML 获取路透社头条。

- **Track B (HTML regex)**: `fetch_yahoo_finance_headlines(ticker)` -- Yahoo Finance headline extraction via regex patterns on raw HTML. No BeautifulSoup dependency.
  通过正则表达式从原始 HTML 提取 Yahoo Finance 头条。无 BeautifulSoup 依赖。

- **Track C (reserved)**: Playwright MCP bridge for SPA-rendered pages (future).
  为 SPA 渲染页面预留的 Playwright MCP 桥接。

- **Orchestrator**: `fetch_all(tickers, config)` aggregates all sources into a `FetchResult` with isolated try-except per source. A failure in FRED does not block Reuters or Yahoo Finance.
  将所有源聚合到 `FetchResult` 中，每个源有独立的 try-except。FRED 的故障不会阻塞路透社或 Yahoo Finance。

Rate limiting: 2s inter-request delay per domain. Configurable via `ScoutConfig.rate_limit_seconds`.

速率限制：每个域名 2 秒的请求间隔。可通过 `ScoutConfig.rate_limit_seconds` 配置。

---

### IngestionPipeline (`src/ingestion_pipeline.py`)

Converts raw scraped events into belief observations. Three stages:

将原始抓取事件转换为信念观测。三个阶段：

1. **Extractor (implicit)**: `RawEvent` already has structured fields from `ScoutFetcher`.
   提取器（隐含）：`RawEvent` 已具有来自 `ScoutFetcher` 的结构化字段。

2. **Distiller**: `Distiller.distill()` makes a headless LLM API call (OpenAI-compatible, `requests` only, no Agent context pollution) to convert `RawEvent` to `DistilledEvent` with proposition_id, direction (bullish/bearish/neutral), confidence [0,1], and one-liner summary.
   `Distiller.distill()` 进行无头 LLM API 调用（OpenAI 兼容，仅使用 `requests`，无 Agent 上下文污染），将 `RawEvent` 转换为 `DistilledEvent`。

3. **Instantiator**: `Instantiator.instantiate_and_ingest()` maps direction+confidence to evidence_value, creates `BeliefObservation`, and calls `BeliefStateManager.ingest_observation()`.
   将方向+置信度映射到 evidence_value，创建 `BeliefObservation`，并调用 `BeliefStateManager.ingest_observation()`。

Preloaded proposition registry (`PRELOADED_PROPOSITIONS`): 8 macro-economic and sector propositions (recession risk, Fed rate path, inflation trend, US-China tension, market sentiment, tech outperformance, energy weakness, financial stress).

预加载命题注册表：8 个宏观经济和板块命题（衰退风险、美联储利率路径、通胀趋势、中美紧张、市场情绪、科技跑赢、能源走弱、金融压力）。

---

### PatrolScheduler (`src/patrol_scheduler.py`)

Lightweight daily timer-based ingestion scheduler. Zero external dependencies -- pure `threading.Timer` + `datetime`.

轻量级基于定时器的每日摄入调度器。零外部依赖——纯 `threading.Timer` + `datetime`。

- **Idempotency Guard**: Same slot cannot fire twice within 60 minutes (`IDEMPOTENCY_WINDOW_SECONDS = 3600`).
  同一插槽在 60 分钟内不能触发两次。

- **Slots**: Default morning (09:00) and evening (21:00) patrol slots. Configurable via `PatrolSlot` definitions.
  默认早间 (09:00) 和晚间 (21:00) 巡逻插槽。可通过 `PatrolSlot` 定义配置。

- **Callback dispatch**: `on_patrol` callback receives a `PatrolSlot` and returns a `PatrolResult`. Callback exceptions are caught and logged but do not break the scheduler loop.
  回调调度：`on_patrol` 回调接收 `PatrolSlot` 并返回 `PatrolResult`。回调异常被捕获并记录，但不破坏调度器循环。

- **Manual override**: `trigger_now()` bypasses the timer for testing or PM override (still respects the idempotency guard).
  手动覆盖：绕过定时器用于测试或 PM 覆盖（仍然遵守幂等守卫）。

---

### ReflectionOrchestrator (`src/reflection_orchestrator.py`)

Scheduled belief maintenance. Triggers global gamma-decay on all active beliefs at T = n x 50 trading steps (academic standard from TradingGroup arXiv:2505.04479).

定时信念维护。在 T = n x 50 交易步时触发对所有活跃信念的全局 gamma 衰减。

- **Idempotent**: `on_trading_step_completed()` tracks `_last_decay_step` to prevent double-fires.
  追踪 `_last_decay_step` 以防止重复触发。

- **Observability**: `_log_belief_state()` logs all active beliefs after each decay with proposition, expectation, uncertainty, score, and observation count.
  每次衰减后记录所有活跃信念，包含命题、期望、不确定性、评分和观测计数。

- **Simulation Mode**: `simulate_steps(count)` for testing without a real trading loop.
  无需真实交易循环即可测试。

---

### BeliefAwarePredictor (`src/belief_aware_predictor.py`)

Functional transformation layer. Injects belief-state weights into `ShadowPrediction` objects before they enter the ShadowPipeline.

函数式转换层。在 `ShadowPrediction` 对象进入 ShadowPipeline 之前注入信念状态权重。

- `inject_belief_weights(predictions, manager)`: Queries `BeliefStateManager.search_nodes()` for each prediction's `target_ticker`, computes mean `confidence_score` of matching ACTIVE nodes, and creates a new frozen `ShadowPrediction` with `belief_weights` injected.
  为每个预测的 `target_ticker` 查询 `BeliefStateManager.search_nodes()`，计算匹配的活跃节点的平均 `confidence_score`，并创建带有注入 `belief_weights` 的新冻结 `ShadowPrediction`。

- `get_ticker_belief_profile(ticker, manager)`: Diagnostic method returning full active belief profile for a ticker.
  诊断方法，返回某个 ticker 的完整活跃信念画像。

---

### BeliefMemoryAdapter (`src/belief_memory_adapter.py`)

Persistence bridge between `BeliefStateManager` and the Memory MCP Server's JSON knowledge graph file.

`BeliefStateManager` 与 Memory MCP 服务器的 JSON 知识图文件之间的持久化桥接。

- `export_to_memory(snapshots, conflicts, retirements)`: Reads the current graph, clears existing belief entities, upserts new entities (BELIEF_NODE, CONFLICT_RECORD, RETIREMENT_RECORD), and writes relations. Returns entity count.
  读取当前图，清除现有信念实体，更新插入新实体，写入关系。返回实体计数。

- `import_from_memory()`: Reads the graph and deserializes back to domain objects (BeliefSnapshot, ConflictRecord, BeliefRetirement).
  读取图并反序列化回域对象。

---

## Data Flow: End-to-End Patrol Cycle

完整的端到端 Patrol 周期数据流：

```
PatrolScheduler fires (09:00 or 21:00)
  |
  v
PatrolPipeline.run()
  |
  +--> 1. register_default_propositions() (idempotent)
  |
  +--> 2. ScoutFetcher.fetch_all()
  |       +--> FRED API (Track A)
  |       +--> Reuters RSS (Track A)
  |       +--> Yahoo Finance (Track B)
  |       +--> FetchResult.events[] (RawEvent)
  |
  +--> 3. Distiller.distill(events)
  |       +--> Headless LLM API call (or MockDistiller fallback)
  |       +--> DistilledEvent[] with proposition_id, direction, confidence
  |
  +--> 4. Instantiator.instantiate_and_ingest(distilled)
  |       +--> direction -> evidence_value mapping
  |       +--> BeliefObservation creation
  |       +--> BeliefStateManager.ingest_observation()
  |       +--> Beta posterior update
  |       +--> Conflict detection
  |       +--> Retirement check
  |
  +--> 5. IngestionResult (stats + proposition_updates)

ReflectionOrchestrator (on trading step completion)
  |
  +--> if step % 50 == 0:
  |       +--> BeliefStateManager.apply_global_decay()
  |       +--> Log active belief state
  |       +--> (optional) Memory export
```

---

## Directory Structure

```
projects/robinhood/
├── src/
│   ├── belief_state_manager.py      # Central orchestrator (3-layer)
│   ├── belief_types.py              # Frozen dataclass domain models
│   ├── belief_math.py               # Pure math kernel (Beta updates, decay)
│   ├── belief_aware_predictor.py    # Belief-weight injection into predictions
│   ├── belief_memory_adapter.py     # Memory MCP persistence bridge
│   ├── scout_fetcher.py             # Multi-source data fetcher (3 tracks)
│   ├── ingestion_pipeline.py        # RawEvent -> DistilledEvent -> BeliefObservation
│   ├── patrol_scheduler.py          # Daily timer-based ingestion
│   ├── reflection_orchestrator.py   # T=nx50 belief decay scheduler
│   ├── shadow_types.py              # ShadowPrediction, BatchShadowRun domain models
│   └── event_store.py               # (reserved) Immutable event log
├── tests/
│   ├── test_belief_state_manager.py
│   ├── test_belief_math.py
│   ├── test_belief_types.py
│   ├── test_belief_integration_8_3_2.py
│   ├── test_scout_fetcher.py
│   ├── test_ingestion_pipeline.py
│   ├── test_patrol_scheduler.py
│   └── conftest.py
├── .env.example                     # Environment variable template
└── README.md                        # <- You are here
```

---

## Running Tests

```bash
cd projects/robinhood
python -m pytest tests/ -v --tb=short

# Run a specific test file:
python -m pytest tests/test_belief_math.py -v --tb=short

# Run with coverage (requires pytest-cov):
python -m pytest tests/ -v --tb=short --cov=src
```

---

## Standalone Dry Run

The Patrol pipeline can be executed as a standalone script from the repository root:

Patrol 管线可以从仓库根目录作为独立脚本执行：

```bash
python run_patrol_dryrun.py
```

This script executes the full Scout -> Distill -> Ingest cycle against real external data sources (FRED, Reuters RSS, Yahoo Finance) and prints a formatted battle report with belief state deltas. If no LLM API key is set, it automatically degrades to a `MockDistiller`.

该脚本对真实外部数据源执行完整的 Scout -> Distill -> Ingest 周期，并打印格式化的执行战报和信念状态变化。如果未设置 LLM API Key，它自动降级为 `MockDistiller`。

---

## Configuration

Robinhood is configured programmatically via its dataclass configs:

Robinhood 通过其数据类配置进行程序化配置：

- `BeliefManagerConfig`: gamma (decay factor, default 0.95), theta (retirement threshold, default 0.1), conflict_threshold (default 0.3), auto_decay_interval_seconds (default 86400), max_observations_per_node (default 10000).
- `DistillerConfig`: api_url (default OpenAI-compatible), model (default gpt-4o-mini), max_raw_per_batch (default 20), temperature (default 0.1), timeout_seconds (default 30).
- `MemoryAdapterConfig`: server_path, memory_file path, timeout_seconds (default 10.0), max_retries (default 2).
- `ReflectionSchedulerConfig`: decay_interval (default 50), decay_steps_per_interval (default 1).
- `ScoutConfig`: rate_limit_seconds (default 2.0), max_body_chars (default 500), request_timeout (default 15), fred_api_key, newsapi_key (with env fallback).

---

## Design Principles Enforced at the Source Level

| Principle | Enforcement |
|---|---|
| Append-Only Observations | `BeliefObservation` is a frozen dataclass; observations are never modified after creation. `BeliefStateManager._nodes` appends to `_InternalNode.observations` but never deletes. |
| Immutable Node Replacement | `BeliefNode` is a frozen dataclass. Every update creates a new instance atomically replacing the old one in `_InternalNode.node`. No in-place mutation. |
| Zero Heavy Dependencies | `belief_math.py` contains zero imports beyond typing. `scout_fetcher.py` depends only on `requests` and `xml.etree`. No NumPy, no SciPy, no pandas. |
| Phase 8.4 Symmetric Correction | `beta_update` applies confidence symmetrically to both alpha and beta, eliminating the systematic bearish bias from low-confidence observations. |
| Corrected Decay Baseline | `gamma_decay` uses alpha' = 1.0 + (alpha - 1.0) * gamma^steps, preventing U-shaped Beta distribution degeneration. |
| Conflict Resolution Audit Trail | Every conflict is recorded as a `ConflictRecord` with resolution strategy, confidence scores at conflict time, and resolution outcome. |
| Idempotent Patrol Guards | `PatrolScheduler.IDEMPOTENCY_WINDOW_SECONDS = 3600` prevents duplicate slot fires within 60 minutes. |
| Academia-Grounded Intervals | Belief decay interval of 50 trading steps (TradingGroup arXiv:2505.04479). Gamma factor of 0.95 (Silent Scholar arXiv:2504.18924). |

---

## Relationship to Command Center

Robinhood is the computational backend; Command Center is the interactive frontend. The boundary is strictly maintained:

Robinhood 是计算后端；Command Center 是交互前端。边界被严格维护：

- Robinhood has zero knowledge of CustomTkinter, task queues, or dual-model gateways.
  Robinhood 对 CustomTkinter、任务队列或双模型网关零感知。

- Command Center delegates belief modifications to Robinhood through the `IntakePipeline` and `BeliefModifier`, which produce `BeliefModificationSuggestion` objects aligned with Robinhood's `PRELOADED_PROPOSITIONS` schema.
  Command Center 通过 `IntakePipeline` 和 `BeliefModifier` 将信念修改委托给 Robinhood，这些组件生成与 Robinhood 的 `PRELOADED_PROPOSITIONS` 模式一致的 `BeliefModificationSuggestion` 对象。

- Command Center's `Optimizer` reads belief snapshots (via `SemanticTranslator`'s `BeliefStateManager`) but never directly writes to the belief graph -- all writes go through Robinhood's `ingestion_pipeline.py`.
  Command Center 的 `Optimizer` 读取信念快照（通过 `SemanticTranslator` 的 `BeliefStateManager`），但从不直接写入信念图——所有写操作都通过 Robinhood 的 `ingestion_pipeline.py`。

---

## License

MIT -- part of the SkillFoundry ecosystem.