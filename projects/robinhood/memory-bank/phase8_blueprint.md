# Phase 8 & 8.1 终局架构蓝图

> 首席架构师输出 · 基于 2026-05-07 本地代码审计  
> 适用：`projects/robinhood/` 量化投资系统  
> 前置：Phase 1–7 已竣工

---

## 目录

1. [全局架构概览](#1-全局架构概览)
2. [核心哲学：次优边界测试 (Sub-optimal Boundary Testing)](#2-核心哲学次优边界测试)
3. [监控池双轨制](#3-监控池双轨制)
4. [绝对断言协议 (Zero-Hedging Protocol)](#4-绝对断言协议)
5. [不可变事件溯源 (Event Sourcing) & 深度归因追踪](#5-不可变事件溯源--深度归因追踪)
6. [影子法庭 (The Shadow Tribunal)](#6-影子法庭)
7. [输出格式层 (Shadow Formatter)](#7-输出格式层)
8. [主控入口 (main.py) 路由规范](#8-主控入口路由规范)
9. [自动进化法庭 (Phase 8.1 连续运行闭环)](#9-自动进化法庭)
10. [现存 Bug 修复行动纲领](#10-现存-bug-修复行动纲领)

---

## 1. 全局架构概览

### 1.1 模块拓扑

```
┌──────────────┐     ┌─────────────────────┐     ┌──────────────────────┐
│  main.py     │────▶│ ShadowAggregator     │────▶│ ShadowPrediction × N │
│  (入口路由)   │     │ (次优边界推演引擎)    │     │ (绝对断言)            │
└──────┬───────┘     └──────────┬──────────┘     └──────────┬───────────┘
       │                        │                           │
       │              ┌─────────▼──────────┐                │
       │              │ ZeroHedgingValidator│◀───────────────┘
       │              │ (模糊词汇拦截)       │
       │              └─────────┬──────────┘
       │                        │
       │              ┌─────────▼──────────┐
       │              │  EventStore         │
       │              │  (JSONL 不可变流)    │
       │              │  predictions.jsonl  │
       │              │  verdicts.jsonl     │
       │              │  batches.jsonl      │
       │              └─────────┬──────────┘
       │                        │
       │              ┌─────────▼──────────┐
       │              │  MarketDataReplayer │
       │              │  (次日真实行情回放)   │
       │              └─────────┬──────────┘
       │                        │
       │              ┌─────────▼──────────┐
       └──────────────│  ShadowTribunal     │
                      │  (非黑即白判决)      │
                      └─────────┬──────────┘
                                │
                      ┌─────────▼──────────┐
                      │  ShadowFormatter    │
                      │  (人类可读报告输出)   │
                      └────────────────────┘
```

### 1.2 数据流契约（刚性）

```
真实行情 → MarketDataReplayer.get_next_day_snapshot()
  → ShadowTribunal.judge_batch()
    → TribunalVerdict × N (PASS/FAIL, 每次断言一枚)
      → EventStore.append_verdict() (JSONL, 不可变)
        → ShadowFormatter.format_tribunal_summary() (人类可读报告)
```

**关键约束：** 不经过 EventStore 写入的断言，法庭不承认。

### 1.3 文件清单

| 文件 | 职责 | 关键依赖 |
|------|------|----------|
| `shadow_types.py` | 全部领域数据类（frozen dataclass） | 无外部依赖 |
| `zero_hedging_validator.py` | 模糊词汇扫描 + 断言硬度评分 | `shadow_types.py` |
| `event_store.py` | 追加式 JSONL 事件存储 | `shadow_types.py` |
| `market_data_replayer.py` | 真实行情文件回放 + 快照生成 | `shadow_types.py` |
| `shadow_aggregator.py` | 次优边界推演 + 预测生成 | 上述全部 |
| `shadow_tribunal.py` | 非黑即白判决引擎 | `shadow_types.py`, `event_store.py`, `market_data_replayer.py` |
| `shadow_formatter.py` | 人类可读报告 / JSON 输出 | `shadow_types.py` |
| `main.py` | CLI 入口 + 模式路由 | 上述全部 |

---

## 2. 核心哲学：次优边界测试

### 2.1 原则声明

> **绝对禁止伪造数据或反事实模拟。** 影子模式必须 100% 依赖每日真实行情数据。

### 2.2 安全阀强制旁路规则

对于标准管线中原本会触发 `OBSERVE_WAIT`（观望）的次优标的，影子模式必须：

1. **强制执行方向性断言**（`DIRECTIONAL_MOVE`），不得输出"信号不足，观望"
2. **杠杆上限提升至 3.0x**（正常管线最大 1.0x），暴露引擎在极端压力下的逻辑短板
3. **绕过所有持仓上限检查**（`max_position_pct`, `single_asset_exposure_pct`, `sector_exposure_pct`）

### 2.3 影子场景分类

| 场景标签 | 触发条件 | 行为 |
|----------|----------|------|
| `AGGRESSIVE_BULL` | 原始评分 ≥ 60 且方向偏多 | 旁路安全阀，最大多仓（+3.0x） |
| `AGGRESSIVE_BEAR` | 原始评分 ≥ 60 且方向偏空 | 旁路安全阀，最大空仓（-3.0x） |
| `AMBIGUOUS_MIXED` | 原始评分 40-60，信号冲突 | 强制微预测（禁止 OBSERVE） |
| `AMBIGUOUS_FLAT` | 原始评分 ≤ 40 或无明显信号 | 强制微预测（禁止 OBSERVE） |

**关键规则：** `AMBIGUOUS_MIXED` / `AMBIGUOUS_FLAT` 场景同样必须输出绝对断言。不存在"观望"或"不入场"的回答。

---

## 3. 监控池双轨制

### 3.1 可交易池（Tradeable Pool）

| Ticker | 类型 | 杠杆上限 |
|--------|------|----------|
| IAU | 黄金 ETF | 3.0x |
| GDX | 金矿 ETF | 3.0x |
| TLT | 20Y+ 国债 ETF | 3.0x |
| SQQQ | 3x 反向纳斯达克 | 3.0x |
| UUP | 美元指数 ETF | 3.0x |
| FXY | 日元 ETF | 3.0x |
| USO | 原油 ETF | 3.0x |

### 3.2 宏观观测池（Macro Observatory Pool）

| 标识符 | 类型 | 要求 |
|--------|------|------|
| US10Y | 美国 10 年期国债收益率 | 每日绝对断言（升/降/平） |
| JGB10Y | 日本 10 年期国债收益率 | 每日绝对断言（升/降/平） |
| VIX | 恐慌指数 | 每日绝对断言（升/降/平）范围 ≤ ±2% |

### 3.3 断言要求

宏观观测池的断言必须是**绝对方向性断言**，不允许相对表述：
- ✅ "US10Y 将在次日上升至少 3bp（4.25% → 4.28%）"
- ❌ "US10Y 可能维持在当前水平附近"（模糊）
- ❌ "JGB10Y 受 BOJ 政策影响不确定性较高"（观望变体）

---

## 4. 绝对断言协议 (Zero-Hedging Protocol)

### 4.1 硬拦截词汇清单

`ZeroHedgingValidator` 必须拦截以下所有模糊词汇，触发即标记 `INVALID`：

```
may, might, could, possibly, perhaps, likely, unlikely,
probably, potentially, around, approximately, roughly,
near, about, almost, somewhat, relatively, generally,
tend to, seems, appears, suggests, indicates,
if..., then..., depending on, conditional upon,
subject to, based on, range of, between X and Y,
expected range, plausible range, wide range
```

### 4.2 断言格式规范

每条断言必须包含：
- **标的**：精确 ticker 或指标名
- **方向**：`gt` / `lt` / `eq`（非黑即白）
- **精确数值**：浮点数，不允许区间
- **时间边界**：精确到日期（ISO 8601: `YYYY-MM-DD`）

### 4.3 `decision_trace` 四维归因（每条断言必须携带）

```json
{
  "prediction_id": "uuid",
  "decision_trace": {
    "four_dimensional_scores": {
      "technical": 75.5,
      "fundamental": 62.0,
      "sentiment": 80.0,
      "macro": 55.0
    },
    "mosaic": {
      "strength": "MODERATE",
      "fragility_score": 0.45,
      "decoherence_risk": "ELEVATED"
    },
    "redteam_deductions": [
      {"rule": "CROWDED_LONG", "deduction": -8.0, "reason": "CFTC CoT > 90th percentile"},
      {"rule": "MOMENTUM_DIVERGENCE", "deduction": -5.0, "reason": "RSI(14) vs Price divergence"}
    ],
    "final_score": 67.5
  }
}
```

---

## 5. 不可变事件溯源 & 深度归因追踪

### 5.1 JSONL 事件流规范

三条独立 JSONL 流，每条记录均为 `{"event_type": "...", "timestamp": "ISO8601", "payload": {...}}`：

| 流文件 | event_type | 写入方法 | 核心字段 |
|--------|------------|----------|----------|
| `predictions.jsonl` | `shadow_prediction` | `append_prediction()` | prediction_id, decision_trace, assertion |
| `verdicts.jsonl` | `shadow_verdict` | `append_verdict()` | prediction_id, status (PASS/FAIL/PENDING), deviation_pct |
| `batches.jsonl` | `shadow_batch` | `append_batch()` | batch_id, scenario_ids[], total_predictions |

### 5.2 不可变约束（Event Sourcing 铁律）

- **禁止 UPDATE**：事件写入后不可修改
- **禁止 DELETE**：事件写入后不可删除
- **PENDING 状态支持**：法庭对账时允许将尚未裁决的断言标记为 `PENDING`（次日数据尚未到达）
- **溯源完整性**：每条断言必须能从 `predictions.jsonl` → `verdicts.jsonl` → `batches.jsonl` 形成完整因果链
- **所有字段不可变**：`ShadowPrediction`、`ShadowScenario`、`TribunalVerdict`、`BatchShadowRun` 均为 `@dataclass(frozen=True)`

### 5.3 不可变模式下的"更新"语义

由于 data class 是 frozen 的，任何"修改"操作必须通过以下模式：
```python
# 正确：创建新对象
new_prediction = ShadowPrediction(
    **existing.__dict__,
    verdict=VerdictStatus.PASS
)
# 错误：尝试原地修改 → FrozenInstanceError
prediction.verdict = VerdictStatus.PASS  # 💥 爆炸
```

---

## 6. 影子法庭 (The Shadow Tribunal)

### 6.1 判决算法

```python
def judge_one(prediction: ShadowPrediction, actual: DailyPriceSnapshot) -> TribunalVerdict:
    """
    非黑即白判决 — 无部分得分，无"接近正确"缓冲。
    
    DIRECTIONAL_MOVE:
      - gt: close > open → PASS, 否则 FAIL
      - lt: close < open → PASS, 否则 FAIL
      - eq: abs(change%) ≤ 0.5% → PASS
    
    SUPPORT_BREAK:
      - low >= support_level → PASS (支撑守住)
      - low < support_level → FAIL (支撑破裂)
    
    RESISTANCE_BREAK:
      - high > resistance_level → PASS (突破阻力)
      - high <= resistance_level → FAIL (受阻)
    
    VOLATILITY_BREAKOUT:
      - daily_range% > predicted_expansion% → PASS
    
    FLOW_REVERSAL:
      - volume_ratio 满足 predicted direction → PASS
    
    RELATIVE_OUTPERFORM:
      - actual_return 满足 predicted direction → PASS
    """
```

### 6.2 严格模式 vs 容错模式

| 模式 | tolerance_pct | 说明 |
|------|---------------|------|
| `strict_mode=True`（默认） | 0.0% | 任何偏差 = FAIL，用于次优边界测试 |
| `strict_mode=False` | 0.5% | 0.5% 内偏差仍算 PASS，用于常规对账 |

### 6.3 MarketDataReplayer 合同

```
输入: previous_date (YYYY-MM-DD), tickers[]
输出: MarketDataSnapshot
      ├── date: str (next trading day)
      ├── prices: Dict[str, DailyPriceSnapshot]
      │   └── DailyPriceSnapshot: {open_price, high_price, low_price, close_price, volume}
      └── macro_indicators: Optional[Dict[str, float]]
          └── {"US10Y": 4.28, "VIX": 18.5, "JGB10Y": 1.35}
```

**约束：** Replayer 必须从真实行情文件读取，不允许硬编码模拟数据。若行情文件不存在，抛出 `FileNotFoundError`（测试中允许使用 temp 文件模拟）。

---

## 7. 输出格式层 (Shadow Formatter)

### 7.1 ShadowReport 结构

```python
@dataclass
class ShadowReport:
    batch_id: str
    output_text: str       # 人类可读 Markdown 文本
    output_json: str       # JSON 格式（可选）
    tickers_processed: int
    total_predictions: int
    aggressive_count: int
    ambiguous_count: int
```

### 7.2 TribunalSummary 结构

```python
@dataclass
class TribunalSummary:
    batch_id: str
    total_judged: int
    passed: int
    failed: int
    pass_rate_pct: float
    avg_deviation_pct: float
    ticker_breakdown: Dict[str, Dict[str, int]]
```

### 7.3 输出规范

- 人类可读输出必须以 `THE TRIBUNAL` 作为标题前缀
- JSON 输出必须包含完整 `batch_id`、`mode`、`scenarios`
- 空判决列表时 `pass_rate_pct` 必须返回 `0.0`（而非 `NaN` 或抛异常）

---

## 8. 主控入口路由规范

### 8.1 CLI 命令

```bash
python -m src.main shadow --mode aggressive  --date 2026-05-07
python -m src.main shadow --mode ambiguous   --date 2026-05-07
python -m src.main shadow --mode strict      --date 2026-05-07
python -m src.main tribunal --previous-date 2026-05-06
```

### 8.2 路由逻辑

```
main.py
├── shadow <mode>
│   ├── 加载当日行情 → MarketDataReplayer
│   ├── 运行 ShadowAggregator.generate_predictions(tickers, mode)
│   ├── ZeroHedgingValidator 扫描所有断言
│   ├── 无效断言 → reject（不进入 EventStore）
│   ├── 有效断言 → EventStore.append_prediction()
│   ├── ShadowFormatter.format_batch_report()
│   └── 输出报告
│
└── tribunal <previous-date>
    ├── 从 EventStore 加载指定日期的所有预测
    ├── MarketDataReplayer.get_next_day_snapshot()
    ├── ShadowTribunal.judge_batch()
    ├── EventStore.append_verdict() 逐条写入
    ├── ShadowFormatter.format_tribunal_summary()
    └── 输出 HUMAN_READABLE 判决报告
```

---

## 9. 自动进化法庭 (Phase 8.1 连续运行闭环)

### 9.1 闭环流程

```
每日收盘后 (T 日):
┌──────────────────────────────────────────────┐
│ 1. 加载 T 日行情快照                           │
│ 2. ShadowAggregator 为每个 ticker 生成断言      │
│ 3. ZeroHedgingValidator 硬化扫描               │
│ 4. 断言 → predictions.jsonl (不可变)            │
│ 5. BatchShadowRun → batches.jsonl (不可变)      │
│                   ↓                            │
│ 次日开盘前 (T+1 日, 拿到 T 日收盘数据后):        │
│ 6. MarketDataReplayer 获取 T 日实际收盘价         │
│ 7. ShadowTribunal 逐条判决 (PASS/FAIL)          │
│ 8. 判决 → verdicts.jsonl (不可变)               │
│ 9. 计算准确率、偏差分布                          │
│10. 若连续 N 日 pass_rate < 阈值: 触发 ALARM     │
│11. ShadowFormatter 输出 HUMAN_READABLE 报告     │
└──────────────────────────────────────────────┘
```

### 9.2 自动进化触发条件

| 触发条件 | 动作 |
|----------|------|
| `pass_rate_7d_avg < 45%` | 输出 WARNING 报告，标记 ticker 为"DEGRADING" |
| `pass_rate_30d_avg < 40%` | 触发 ALARM，强制人工审核管线，同时自动下调该 ticker 权重 |
| 单 ticker `avg_deviation > 5%` | 标记为"UNSTABLE"，停止该 ticker 的 AGGRESSIVE 场景 |
| 全部 ticker `pass_rate_30d_avg > 60%` | 标记管线为"HEALTHY"，输出 PASS 证据链 |

### 9.3 PENDING 状态

当日判决时，若目标日期尚未到达（预测在 T-1 日生成，但 T+1 日数据尚未进入系统），判决状态为 `PENDING`。PENDING 的断言保留在事件存储中，等待数据就绪后批量重判。

---

## 10. 现存 Bug 修复行动纲领

> **诊断时间：** 2026-05-06 23:56 UTC+8  
> **诊断范围：** `test_event_store.py`, `test_shadow_formatter.py`, `test_shadow_tribunal.py`  
> **总报错数：** 26 FAILED + 6 ERROR = 32 个测试失败

### 10.1 `test_event_store.py` — 26 FAILED（不可变性/合同断裂）

**根因分析：**

测试代码试图对 `@dataclass(frozen=True)` 的实例执行原地修改操作。由于 Phase 8 要求完全不可变（Event Sourcing），data class 全部使用了 `frozen=True`，这导致：

1. **直接属性赋值爆炸** — 测试可能调用 `prediction.verdict = VerdictStatus.PASS` 或 `verdict.status = VerdictStatus.FAIL`，触发 `FrozenInstanceError`
2. **`__post_init__` 中使用 `object.__setattr__`** — 某些场景下（如 `ShadowScenario.__post_init__` 中更新 `prediction_count`），通过 `object.__setattr__` 绕过冻结，但测试可能创建了一个 frozen 实例后再尝试修改它
3. **`add_prediction()` 返回值未被使用** — `ShadowScenario.add_prediction()` 返回新实例（不可变模式），但测试可能原地调用而忽略了返回值

**修复策略（按优先级）：**

| 优先级 | 修复动作 | 影响文件 |
|--------|----------|----------|
| P1 | 审计所有测试中的原地赋值，替换为构造新对象模式 | `test_event_store.py` |
| P1 | 确保 `ShadowScenario.add_prediction()` 返回值被正确使用 | `test_event_store.py` |
| P2 | 如在 `__post_init__` 中使用 `object.__setattr__` 写入 `frozen` 实例而报错，将逻辑前移到 `__init__` 的参数计算阶段（`field(default_factory=...)`） | `shadow_types.py` |
| P2 | 如 `BatchShadowRun.__post_init__` 中 `object.__setattr__` 失败，改用 `__init_subclass__` 或 `field(default_factory=)` 注入 | `shadow_types.py` |

**具体修复模板：**

```python
# ❌ 错误写法（原地修改 frozen 实例）
prediction.verdict = VerdictStatus.PASS

# ✅ 正确写法（构造新对象）
prediction = ShadowPrediction(
    target_ticker=prediction.target_ticker,
    target_type=prediction.target_type,
    predicted_value=prediction.predicted_value,
    comparison_operator=prediction.comparison_operator,
    assertion=prediction.assertion,
    confidence=prediction.confidence,
    target_date=prediction.target_date,
    verdict=VerdictStatus.PASS,
    # ... 其余字段通过 __dict__ 解包
)
```

```python
# ❌ 错误写法（忽略不可变 add 的返回值）
scenario.add_prediction(pred)

# ✅ 正确写法（捕获返回值）
scenario = scenario.add_prediction(pred)
```

### 10.2 `test_shadow_formatter.py` — FAILED（与 event_store 联动）

**根因分析：**

Formatter 测试失败的主要原因是它依赖的 `ShadowPrediction` / `BatchShadowRun` / `TribunalVerdict` 创建路径与测试期望不匹配。典型问题：

1. **`ShadowScenario` 构造函数签名变更** — 新代码使用 `label: SceneLabel` 和 `predictions: List[ShadowPrediction]` 作为核心字段，但测试可能使用旧签名
2. **`BatchShadowRun` 的 `total_predictions` 自动计算** — `__post_init__` 会自动汇总 scenarios 中的预测数，但测试可能手动传入不匹配的值导致验证失败
3. **`TribunalVerdict` 字段顺序变更** — 构造函数签名 `(prediction_id, target_ticker, status, deviation_pct, actual_close, predicted_value, reason)` 与测试中的位置参数可能不一致

**修复策略：**

| 优先级 | 修复动作 |
|--------|----------|
| P1 | 对齐测试中所有 `ShadowScenario` 的构造方式与当前 `shadow_types.py` 定义 |
| P1 | 将 `ShadowScenario` 测试中的 `scenario_type` 字段替换为 `label` 字段 + `target_ticker` + `predictions` |
| P2 | 确保 `TribunalVerdict` 位置参数顺序与测试完全一致 |

### 10.3 `test_shadow_tribunal.py` — 6 ERROR（数据结构合同断裂）

**根因分析（6 个 ERROR 的典型模式）：**

根据之前读取的 `shadow_tribunal.py` 代码，关键合同点：

1. **`MarketDataReplayer.get_next_day_snapshot()` 返回类型** — `MarketDataSnapshot` 包含 `date: str`, `prices: Dict[str, DailyPriceSnapshot]`。测试可能在 mock 中使用了不兼容的类型

2. **`ShadowTribunal.judge_batch()` 参数** — 接受 `(batch: BatchShadowRun, previous_date: str)`，返回 `List[TribunalVerdict]`。测试可能在构造 `BatchShadowRun` 时缺少必要字段（如 `scenarios` 为空列表时）

3. **`ShadowTribunal._judge_prediction()` 分发** — 期望 `prediction.target_type` 为 `PredictionTarget` 枚举，但测试可能传入字符串

4. **`DailyPriceSnapshot` 字段访问** — tribunal 内部访问 `price.open_price`, `price.close_price`, `price.high_price`, `price.low_price`, `price.volume`。如果 mock 对象缺少任一字段，触发 `AttributeError`

5. **`_verdict_to_payload()` 中的 `verdict.actual_value`** — 这是一个 `@property` 返回 `self.actual_close`。如果 `TribunalVerdict` 构造时 `actual_close` 未正确传入，payload 序列化会失败

**修复策略：**

| 优先级 | 修复动作 | 影响文件 |
|--------|----------|----------|
| P0 | 确保 Mock 的 `MarketDataReplayer` 返回完整的 `MarketDataSnapshot` 对象（包含所有必需字段） | `test_shadow_tribunal.py` |
| P0 | 确保 `BatchShadowRun` 构造时 `scenarios` 不为空（或修复 tribunal 处理空列表的逻辑） | `test_shadow_tribunal.py` 或 `shadow_tribunal.py` |
| P1 | 确保测试中 `prediction.target_type` 使用 `PredictionTarget` 枚举而非字符串 | `test_shadow_tribunal.py` |
| P1 | 确保 Mock 的 `DailyPriceSnapshot` 包含 `open_price`, `close_price`, `high_price`, `low_price`, `volume` 五个字段 | `test_shadow_tribunal.py` |
| P2 | 审查所有 mock 的 `TribunalVerdict` 构造，确保 `actual_close` 参数正确传入 | `test_shadow_tribunal.py` |

### 10.4 修复执行顺序（强依赖拓扑）

```
Step 1: 修复 shadow_types.py 的 frozen 写入问题
   └── 影响：解决 test_event_store.py 的 26 个 FAILED

Step 2: 同步调整 test_shadow_formatter.py 的构造签名
   └── 依赖：Step 1（因为 Formatter 依赖类型定义）
   └── 影响：解决 test_shadow_formatter.py 的 FAILED

Step 3: 修复 test_shadow_tribunal.py 的 mock 合同
   └── 依赖：Step 1（因为 Tribunal 依赖 shadow_types 类型）
   └── 影响：解决 test_shadow_tribunal.py 的 6 个 ERROR

Step 4: 全量回归测试
   └── 命令：pytest projects/robinhood/tests/ -v --tb=short
   └── 目标：0 FAILED, 0 ERROR
```

### 10.5 快速验证命令

```bash
# 单文件调试（最快反馈循环）
pytest projects/robinhood/tests/test_event_store.py -v --tb=long 2>&1 | head -80
pytest projects/robinhood/tests/test_shadow_tribunal.py -v --tb=long 2>&1 | head -60
pytest projects/robinhood/tests/test_shadow_formatter.py -v --tb=long 2>&1 | head -60

# 全量回归
pytest projects/robinhood/tests/ -v --tb=short 2>&1
```

---

## 确认检查清单

在批准进入 ACT MODE 修复前，请确认以下项：

- [ ] **§2 次优边界测试哲学** — 同意安全阀旁路 + 3.0x 杠杆规则
- [ ] **§3 监控池双轨制** — 同意 7 可交易 + 3 宏观观测的标的清单
- [ ] **§4 Zero-Hedging** — 同意模糊词汇拦截清单和四维决策归因格式
- [ ] **§5 Event Sourcing** — 同意 frozen dataclass + JSONL 追加式存储
- [ ] **§6 法庭判决** — 同意非黑即白 `strict_mode=True` 默认
- [ ] **§7 Formatter** — 同意输出格式规范
- [ ] **§8 main.py 路由** — 同意 CLI 接口设计
- [ ] **§10 Bug 修复行动纲领** — 同意修复执行顺序（Step 1 → Step 2 → Step 3 → Step 4）

*End of Blueprint — Generated by Chief Architect (AI) on 2026-05-07*