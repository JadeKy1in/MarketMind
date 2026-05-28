# Playground Agent 入驻指南 / Playground Agent Onboarding Guide

**语言 / Language**: 中英双语 / Bilingual CN-EN

---

## 目录 / TOC

1. [概述 / Overview](#1-概述--overview)
2. [架构 / Architecture](#2-架构--architecture)
3. [快速开始 / Quick Start](#3-快速开始--quick-start)
4. [manifest.json 规范 / manifest.json Specification](#4-manifestjson-规范--manifestjson-specification)
5. [adapter.py 接口 / adapter.py Interface](#5-adapterpy-接口--adapterpy-interface)
6. [数据源注册 / Registering Data Sources](#6-数据源注册--registering-data-sources)
7. [测试 / Testing](#7-测试--testing)
8. [审计与升级 / Audit & Upgrade Path](#8-审计与升级--audit--upgrade-path)
9. [参考实现 / Reference Implementation](#9-参考实现--reference-implementation)
10. [清单 / Checklist](#10-清单--checklist)

---

## 1. 概述 / Overview

Playground 是 MarketMind 的实验层——独立 agent 在不接触主管道分析数据的前提下，基于公开市场数据产出方向性判断。通过的 agent 可升级接入主管道成为决策信号源。

Playground is MarketMind's experimental layer — independent agents produce directional calls using only public market data, never touching main pipeline analysis. Agents that pass audit can upgrade into the main pipeline as decision signal sources.

| 概念 / Concept | 说明 / Description |
|:--|:--|
| **Agent** | 一个独立分析模块，有独特的分析框架和视角 |
| **manifest.json** | Agent 自声明文件——声明"我是谁、做什么、如何评估" |
| **adapter.py** | Agent 的入口函数 `analyze(context, mock)` —— runner 只调用这一个接口 |
| **信息防火墙** | Playground agent 只收到公开数据（新闻+行情），收不到主管道的 L1/L2/L3/Red Team/Resonance/Decision |
| **升级门控** | 6 个关卡全部通过 → 进入集成评估 |

---

## 2. 架构 / Architecture

```
主管道: Scout → Flash → L1 → L2+L3 → Shadows → RedTeam → Resonance → Decision
                              ⬆ 信息防火墙 (主管道数据不传入 Playground)
                              
Playground: WP API(6) + RSS(2) → fetcher → [agent].adapter.py → analyze()
                │                                              │
           playground_sources.py                         daily report
           (agent→source mapping)                        + audit log
```

**数据通道 / Data Channels:**

| 通道 | 说明 | 示例 |
|:--|:--|:--|
| `SourceChannel.WP_API` | WordPress REST API — 完整文章 JSON | EE Times, EDN, Semiconductor Engineering |
| `SourceChannel.RSS` | 传统 RSS 2.0 / Atom feed | EE Times Asia, Photonics Spectra |

**数据层级 / Usage Tiers:**

| 层级 | 触发条件 | 说明 |
|:--|:--|:--|
| `CORE` | 每次运行 | agent 声明的主数据源 |
| `SUPPLEMENTAL` | CORE < 15 篇时触发 | 补充来源 |
| `RETIRED` | 永不抓取 | 保留为审计记录 |

**生命周期 / Lifecycle:**

```
安装 → 观察期(≥60天) → 积累 ≥20 次结算 → 审计 → 通过 → 升级评估 → 接入主管道
                                                  ↓ 未通过
                                               继续观察 / 标记 stagnant
```

---

## 3. 快速开始 / Quick Start

### 步骤 1：创建 agent 目录

```bash
cd playground/agents
mkdir my_agent
```

### 步骤 2：编写 manifest.json

```json
{
  "agent_id": "my_agent",
  "display_name": "My Agent Display Name",
  "description": "1-3 sentences describing what this agent analyzes and how.",
  "output_character": "directional call on individual stocks — bullish/bearish with confidence and thesis",
  "public_data_sources": ["RSS news", "public market price data"],
  "requires_proprietary_data": false,
  "primary_metric": "direction_accuracy",
  "secondary_metrics": ["sharpe_ratio", "max_drawdown"],
  "min_sample_size": 20,
  "min_observation_days": 60,
  "target_pipeline_node": "decision_signal_source",
  "version": "1.0.0",
  "author": "your-name",
  "tags": ["domain-tag-1", "domain-tag-2"]
}
```

### 步骤 3：编写 adapter.py

```python
"""My agent adapter."""

MOCK_OUTPUT = {
    "directional_calls": [],
    "no_calls_reason": "Mock mode — no live analysis performed.",
    "supply_chain_observations": [],
}

async def analyze(context: dict, *, mock: bool = False) -> dict:
    """Entry point called by playground_runner.
    
    Args:
        context: Public-data-only context with keys:
            - news: list[dict] — news items (title, url, summary, full_content, source_name, ...)
            - market_data: dict | None — public market data (may be absent)
            - timestamp: str — UTC ISO timestamp
            - source: "public_market_data"
        mock: If True, return mock output (no API cost).
    
    Returns:
        dict with keys:
            - directional_calls: list[dict] — each with ticker, direction, confidence, thesis
            - no_calls_reason: str — reason if no calls made
            - supply_chain_observations: list[str] — optional
    """
    if mock:
        return dict(MOCK_OUTPUT)
    
    news = context.get("news", [])
    if not news:
        return {"directional_calls": [], "no_calls_reason": "No news data."}
    
    # Your analysis logic here
    # Call LLM via gateway/async_client.py (chat_flash for light, chat_pro for deep)
    
    return {
        "directional_calls": [
            {
                "ticker": "SYMBOL",
                "direction": "bullish",  # or "bearish"
                "confidence": 0.75,
                "thesis": "One-sentence thesis.",
            }
        ],
        "supply_chain_observations": [],
    }
```

### 步骤 4：创建 `__init__.py`

```python
# playground.agents.my_agent
```

### 步骤 5：测试运行

```bash
# Mock 模式验证 agent 能被正确加载和执行
python app.py --mode daily --mock --playground -v

# 查看 Dashboard 的 Playground 卡片
python api_server.py
# → http://localhost:8520/playground
```

---

## 4. manifest.json 规范 / manifest.json Specification

所有字段均为 agent 作者的自声明。审计器将其视为**待验证假设**，而非既定事实。

All fields are claims by the agent author. The auditor treats them as **hypotheses to be verified**, not ground truth.

### 必填字段 / Required Fields

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `agent_id` | `string` | 唯一标识，snake_case，如 `"serenity_reply"`。与目录名一致。 |
| `display_name` | `string` | 人类可读名称，如 `"Serenity Semiconductor Analyst"` |
| `description` | `string` | 1-3 句话描述 agent 的分析内容和方法 |
| `output_character` | `string` | 自由文本描述输出类型。**不设 enum**——分类从累积的 manifest 中涌现。例如：`"directional call on individual stocks"`, `"market regime label"`, `"risk binary flag"` |
| `primary_metric` | `string` | 主要成功指标，自由文本。审计器映射到可计算指标。 |
| `min_sample_size` | `number` | 最小决策数，评估生效前 |
| `min_observation_days` | `number` | 最小日历天数，首次审计前 |

### 可选字段 / Optional Fields

| 字段 | 类型 | 默认值 | 说明 |
|:--|:--|:--|:--|
| `public_data_sources` | `list[string]` | `[]` | Agent 使用的公开数据源描述 |
| `requires_proprietary_data` | `bool` | `false` | 是否需要主管道 Scout 以外的数据。`true` 时，所有性能记录标记 `[enhanced_data]` |
| `secondary_metrics` | `list[string]` | `[]` | 辅助指标，如 `["sharpe_ratio", "max_drawdown", "profit_factor"]` |
| `target_pipeline_node` | `string` | `""` | 升级后的目标节点。如 `"decision_signal_source"`, `"l1_narrative_input"`, `"red_team_input"`。空 = 尚未确定或 agent 是 meta/utility 类型 |
| `version` | `string` | `"1.0.0"` | 语义化版本 |
| `author` | `string` | `""` | 作者署名 |
| `tags` | `list[string]` | `[]` | 自由标签，用于 Dashboard 分组显示 |

### 设计原则 / Design Principles

1. **无硬编码分类 / No Hardcoded Taxonomy** — 不强制 agent 选择预定义类型。分类从 manifest 累积中涌现。
2. **自声明 / Self-Declaration** — manifest 是 agent 对自身的声明。审计器独立验证。
3. **无预设升级路径 / No Preset Upgrade Path** — 每个 agent 的集成方案个案分析。

---

## 5. adapter.py 接口 / adapter.py Interface

### 唯一入口 / Single Entry Point

```python
async def analyze(context: dict, *, mock: bool = False) -> dict:
```

Runner 通过 `importlib` 动态加载 adapter.py，只调用这一个函数。

### context 参数 / context Parameter

`context` 是一个 dict，包含以下键：

```python
context = {
    "source": "public_market_data",       # 固定值
    "timestamp": "2026-05-28T02:34:00Z",  # UTC ISO 时间戳
    "news": [                              # 新闻列表，每项为一个 dict
        {
            "title": "Article Title",
            "url": "https://...",
            "summary": "First 400 chars of cleaned text",
            "full_content": "Up to 8000 chars of full article",
            "published_at": "2026-05-28T...",
            "source_name": "EE Times",     # 来源名称
            "source_tier": 1,              # SourceTier 枚举值 (1=PRIMARY, 2=RELIABLE, ...)
            "source_reliability": 0.88,    # 可靠性评分 0-1
        },
        # ...
    ],
    "market_data": {  # 可选，可能不存在
        # 公开行情数据
    },
    "enhanced_data": True,  # 仅当有 Playground 专属数据时存在
}
```

**信息防火墙保证 / Firewall Guarantee**: context 中**永远不会**包含以下字段：
- `flash_signal`, `flash_scores`, `triage_result` (Flash 输出)
- `l1_tag`, `l2_candidate` (主管道分析)
- 任何 Shadow 分析结果
- Red Team / Resonance / Decision 数据

### 返回值 / Return Value

```python
{
    "directional_calls": [  # 方向性判断列表
        {
            "ticker": "AXTI",         # 股票代码，大写
            "direction": "bullish",   # "bullish" 或 "bearish"
            "confidence": 0.75,       # 0.0-1.0
            "thesis": "一句话简述逻辑",  # 最多 300 字符
            "mental_model_used": "chokepoint_theory",  # 可选，使用的分析框架
            "research_backed": True,  # 可选，是否有深度研究支持
        }
    ],
    "no_calls_reason": "如果没有 calls，解释原因",
    "supply_chain_observations": ["观察1", "观察2"],  # 可选，最多 5 条
    "research_summary": "一句话研究摘要",             # 可选
}
```

**规则 / Rules:**
- `directional_calls` 最多 3 个，质量优先
- 每个 call 的 `thesis` 长度 ≤ 300 字符
- `confidence` 建议 ≥ 0.6 再作为 call 输出
- `_research_log` 等私有字段 runner 不会消费，仅展示在日报中

### 扩展字段 / Extension Fields

以下 `_` 前缀字段 runner 识别并用于日报展示，但不会影响决策逻辑：

| 字段 | 说明 |
|:--|:--|
| `_passes` | 分析轮数 (1 或 2) |
| `_research_log` | 研究日志列表，每项含 `label`, `response`, `error` |
| `_research_leads_identified` | 识别的研究线索数 |
| `_research_rounds_completed` | 完成的研究轮数 |

### LLM 调用规范 / LLM Call Conventions

```python
# 轻量分类/初筛 → Flash
from marketmind.gateway.async_client import chat_flash

result = await chat_flash(
    system_prompt="Your system instructions",
    user_prompt="Your analysis prompt",
    temperature=0.2,
    max_tokens=8192,
)

# 深度分析 → Pro
from marketmind.gateway.async_client import chat_pro

result = await chat_pro(
    system_prompt="Your system instructions", 
    user_prompt="Your deep analysis prompt",
    temperature=0.4,
    max_tokens=16384,
)
```

**禁止直接使用 httpx 调用 LLM API**——所有调用必须通过 gateway。

### Mock 模式 / Mock Mode

```python
MOCK_OUTPUT = {
    "directional_calls": [],
    "no_calls_reason": "Mock mode — no live analysis performed.",
    "supply_chain_observations": [],
}

async def analyze(context: dict, *, mock: bool = False) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    # ... real analysis
```

Mock 模式下不调用 API，快速返回占位结果。用于 `--mock` 管线和测试。

---

## 6. 数据源注册 / Registering Data Sources

### Agent 使用现有数据源

大多数 agent 使用的是 playground 已注册的公开数据源。无需注册新源——只需在 `manifest.json` 的 `public_data_sources` 中声明即可。

### Agent 需要专属数据源

如果 agent 需要新的 RSS/WP API 数据源，两步完成：

**步骤 1**: 在 `playground/playground_sources.py` 中添加源：

```python
# 在 PLAYGROUND_SOURCES 列表中添加
PlaygroundSource(
    name="Your Source Name",
    url="https://example.com/feed/",           # RSS URL
    channel=SourceChannel.RSS,                  # 或 SourceChannel.WP_API
    tier=SourceTier.RELIABLE,                   # PRIMARY/RELIABLE/FRAGILE/BEST_EFFORT
    reliability=0.75,                           # 0-1 可靠性评分
    usage_tier=UsageTier.CORE,                  # CORE/SUPPLEMENTAL/RETIRED
    description="What this source covers.",
    coverage=["domain1", "domain2"],
),
```

对于 WP API 源，额外设置 `wp_api_url`:

```python
PlaygroundSource(
    name="Your WP Source",
    url="https://example.com",
    wp_api_url=wp_posts_url("https://example.com"),  # 自动生成 WP REST API endpoint
    channel=SourceChannel.WP_API,
    # ... 其余字段
),
```

**步骤 2**: 在 `AGENT_SOURCE_MAP` 中将源绑定到 agent：

```python
AGENT_SOURCE_MAP: dict[str, list[str]] = {
    "serenity_reply": [...],
    "my_agent": ["Your Source Name", "Another Source"],
}
```

### 源分层决策 / Tier Decision Guide

| 条件 | 推荐层级 |
|:--|:--|
| 每次运行都需要 | `CORE` |
| 仅在 CORE 不足时补充 | `SUPPLEMENTAL` |
| 历史源，不再抓取 | `RETIRED`（需填写 `retire_reason`） |

---

## 7. 测试 / Testing

### 单元测试

在 `tests/test_playground/` 下创建 agent 测试文件，如 `test_my_agent.py`:

```python
import pytest
from marketmind.playground.agent_manifest import load_manifest


class TestMyAgent:
    def test_manifest_loads(self):
        manifest = load_manifest(Path("playground/agents/my_agent"))
        assert manifest is not None
        assert manifest.agent_id == "my_agent"
        assert manifest.min_sample_size >= 20

    @pytest.mark.asyncio
    async def test_adapter_mock_mode(self):
        from importlib import util
        spec = util.spec_from_file_location(
            "test_adapter", "playground/agents/my_agent/adapter.py"
        )
        mod = util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        
        result = await mod.analyze({"news": []}, mock=True)
        assert "directional_calls" in result
        assert result["directional_calls"] == []
```

### 集成测试

```bash
# Playground 专属测试
python -m pytest tests/test_playground/ -v --tb=short

# 全量测试
python -m pytest tests/ -q -p no:warnings
```

---

## 8. 审计与升级 / Audit & Upgrade Path

### 升级门控 / Upgrade Gates

Agent 必须同时通过 6 个关卡才能升级：

| # | 门控 | 阈值 | 说明 |
|:--|:--|:--|:--|
| 1 | 观察期 / Observation | ≥ 60 天 | `perf.observation_days >= MIN_OBSERVATION_DAYS` |
| 2 | 样本量 / Sample Size | ≥ 20 次结算 | `perf.settled_calls >= MIN_SETTLED_CALLS` |
| 3 | 方向准确率 / Accuracy | ≥ 55% 且 p<0.05 | 二项检验，零假设 = 随机猜测 |
| 4 | 夏普比率 / Sharpe | ≥ 0.5 | `perf.sharpe_ratio >= MIN_SHARPE` |
| 5 | 最大回撤 / Drawdown | ≤ 25% (2500 bps) | `perf.max_drawdown_bps <= MAX_DRAWDOWN_BPS` |
| 6 | 主管道相关性 / Correlation | ≤ 0.7 | 与主管道决策的相关性。过高 = 信息冗余，无增量 |

### 审计建议 / Audit Recommendations

| 状态 | 含义 |
|:--|:--|
| `KEEP_OBSERVING` | 继续观察，数据不足或部分门控未通过 |
| `CANDIDATE_FOR_UPGRADE` | 全部门控通过，进入集成评估 |
| `MARK_STAGNANT` | 连续 3 次审计准确率 < 55%，无改善趋势 |

### 升级后 / After Upgrade

升级后的 agent 不再走 Playground 路径——输出直接接入主管道。初始权重保守（≤ 0.05），根据后续表现动态调整。

升级路径是**个案分析**而非模板化——`target_pipeline_node` 只是一个建议，最终位置取决于 agent 的实际输出特征和主管道的当前需求。

---

## 9. 参考实现 / Reference Implementation

`playground/agents/serenity_reply/` 是 Playground 的首个入驻 agent，也是最佳参考实现：

| 文件 | 要点 |
|:--|:--|
| [`manifest.json`](../playground/agents/serenity_reply/manifest.json) | 完整的自声明示例——5 个思维模型、8 条决策启发式、半导体瓶颈分析 |
| [`adapter.py`](../playground/agents/serenity_reply/adapter.py) | 双轮分析 + 研究循环：Pass 1 初筛 → 深度研究 borderline leads → Pass 2 综合。展示完整的研究日志记录、LLM 调用、输出验证模式 |
| `__init__.py` | 空文件，标记 Python 包 |

**关键设计点 / Key Design Decisions:**
- 两轮分析（Pass 1 → Research → Pass 2）而非单轮，提升 borderline 信号质量
- 研究日志 `_research_log` 记录每次 Flash 交互，用于审计
- `_validate_output()` 做硬过滤：移除大市值、confidence < 0.6 的无效 calls
- 最大化 3 个 calls，按 confidence 降序

---

## 10. 清单 / Checklist

新 agent 入驻时逐项确认：

- [ ] `playground/agents/<agent_id>/` 目录已创建
- [ ] `manifest.json` 所有必填字段完整
- [ ] `adapter.py` 实现了 `async def analyze(context, mock=False) -> dict`
- [ ] `__init__.py` 存在（可为空）
- [ ] `analyze()` 在 `mock=True` 时返回占位结果，不调用 API
- [ ] `analyze()` 从 `context["news"]` 获取数据，不访问主管道内部
- [ ] 所有 LLM 调用通过 `gateway/async_client.py`
- [ ] 返回值包含 `directional_calls` 和/或 `no_calls_reason`
- [ ] 如需专属数据源，已在 `playground_sources.py` 注册并加入 `AGENT_SOURCE_MAP`
- [ ] Mock 管线验证通过: `python app.py --mode daily --mock --playground -v`
- [ ] 单元测试已添加至 `tests/test_playground/`
- [ ] Agent 已出现在 Dashboard `/playground` 页面

---

## References

| # | Source | Date | Type |
|---|--------|------|------|
| 1 | [agent_manifest.py](../playground/agent_manifest.py) | 2026-05 | `[V]` primary |
| 2 | [playground_runner.py](../playground/playground_runner.py) | 2026-05 | `[V]` primary |
| 3 | [playground_auditor.py](../playground/playground_auditor.py) | 2026-05 | `[V]` primary |
| 4 | [playground_sources.py](../playground/playground_sources.py) | 2026-05 | `[V]` primary |
| 5 | [serenity_reply adapter](../playground/agents/serenity_reply/adapter.py) | 2026-05 | `[V]` primary |
| 6 | [serenity_reply manifest](../playground/agents/serenity_reply/manifest.json) | 2026-05 | `[V]` primary |
