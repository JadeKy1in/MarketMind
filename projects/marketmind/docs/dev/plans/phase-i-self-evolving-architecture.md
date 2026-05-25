# MarketMind Phase I: 自我进化学习层 — 架构方案

**日期**: 2026-05-18 | **基于**: 3 份前瞻研究（自进化/知识图谱/多Agent学习）| **状态**: 待红方审核 → 待用户审批

---

## 零、核心命题

Phase H 让 AI **分析得更深**。Phase I 让 AI **从自己的分析中学习，越来越准**。

当前状态：主 AI 和 21 个影子 AI 每天产出分析 → 归档 → 结束。下一次分析重新开始，不参考之前的经验。这就像每天雇一个新的分析师。

目标状态：系统分析 EUR/USD 第 50 次时，比第 1 次更准。因为它记得自己之前 49 次分析的结论、置信度、以及实际结果。影子 AI 之间存在知识传递——擅长黄金的影子可以教其他影子黄金市场的规律，由实际业绩验证。

---

## 一、六层学习架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      Phase I 学习层                              │
│                                                                  │
│  Layer 6: 跨影子知识蒸馏 (Cross-Shadow Distillation)              │
│          阴影A擅长黄金 → 方法论提炼 → 注入阴影B的黄金分析prompt      │
│                                                                  │
│  Layer 5: 模型校准 (Calibration Layer)                           │
│          Brier分数追踪 → 系统化置信度调整 → Platt缩放               │
│                                                                  │
│  Layer 4: 实体记忆进化 (Entity Memory Evolution)                   │
│          EUR/USD记忆文件: 过去49次分析 + 验证结果 + 关键水平 + 教训   │
│                                                                  │
│  Layer 3: 结构化复盘 (Structured Post-Mortem)                     │
│          预测到期 → 对比实际 → 根因分类 → 结构化教训 → 存储          │
│                                                                  │
│  Layer 2: 预测评分 (Prediction Scoring)                           │
│          每条假设 → Brier分数 + 校准曲线 + 方向准确率                │
│                                                                  │
│  Layer 1: 时间锚定预测 (Time-Anchored Predictions)                │
│          每条假设必须产出: {预测内容, 置信度, 时间窗口, 验证指标}     │
└─────────────────────────────────────────────────────────────────┘
```

自下而上：没有 Layer 1 的可验证预测，Layer 2 无法评分，Layer 3-6 无法学习。

---

## 二、Layer 1: 时间锚定预测

**问题**：当前 HypothesisResult 有时间窗口字段（`time_window: "2-4周"`），但预测格式不足以支撑自动化验证。

### 新增：PredictableHypothesis

```python
@dataclass
class PredictableHypothesis:
    hypothesis: str                    # 假设文本
    prediction: str                    # 可验证的预测语句:"EUR/USD将在30天内升至1.10以上"
    confidence: float                  # 0-1
    
    # 时间锚定
    prediction_window_days: int        # 30
    expiry_date: str                   # "2026-06-17" (ISO)
    
    # 验证条件
    verification_metric: str           # "EUR/USD close price"
    verification_source: str           # "market_data:EUR/USD"
    success_condition: str             # "价格 >= 1.1000"
    success_value: float               # 1.1000
    direction: str                     # "above" | "below" | "within_range"
    
    # 状态追踪
    status: str = "PENDING"            # PENDING | VERIFIED_SUCCESS | VERIFIED_FAILURE | EXPIRED_UNVERIFIABLE
    actual_value: float | None = None
    verified_at: str | None = None
    brier_score: float | None = None
```

### 集成方式

在 `investigation_loop.py` 的 `run_investigation_loop()` 完成后（HypothesisResult 定义于 `investigation_types.py`），对每个 ACTIONABLE 假设调用 Flash 提取可验证预测。Flash 产出结构化预测语句，不增加 Pro 成本。

---

## 三、Layer 2: 预测评分

**问题**：没有评分就没有学习。需要量化"这个预测有多准"。

### Brier Score（二元事件）

```
BS = (predicted_prob - actual_outcome)²
完美预测 = 0.0，最差预测 = 1.0
```

系统追踪每个影子 AI 的累计 Brier 分数、方向准确率（涨/跌/持平判断的对错比）、校准曲线（预测 0.81 的事件实际发生频率是否真的 ~81%）。

### CalibrationTracker

```python
@dataclass
class CalibrationTracker:
    entity_id: str                     # "shadow_gold_expert" | "main_ai"
    total_predictions: int
    brier_score_cumulative: float
    direction_accuracy: float          # 涨/跌方向判断正确率
    calibration_bucket: dict[str, tuple[int, int]]  # {"0.7-0.8": (predicted, actual)}
    ece: float                         # Expected Calibration Error
    last_updated: str
```

**关键设计**：评分不用于惩罚，用于调整。一个系统性在 0.81 置信度上过度自信的影子 AI，其未来置信度自动下调（Platt 缩放）。

**存储**：SQLite 表 `prediction_scores`，与影子 SQLite 数据库并存。

---

## 四、Layer 3: 结构化复盘

**问题**：知道"我预测错了"不够，需要知道"为什么错"。

### ReflectionAgent

独立的复盘 Agent（Pro 调用，非实时，批处理），在预测过期后运行：

```
输入: PredictableHypothesis + 实际结果 + 原始分析文本
输出: StructuredLesson:
  - prediction_id
  - outcome: SUCCESS | FAILURE
  - root_cause: 根因分类
  - updated_belief: 修正后的认知
  - relevance_score: 对未来分析的参考价值 (0-1)
  - entity: 关联的资产/行业
  - decay_factor: 随时间衰减权重
```

### 根因分类体系

| 类别 | 示例 | 触发条件 |
|------|------|------|
| MISSING_DATA | "没有考虑中国PMI数据" | 事后出现新数据推翻了预测 |
| FLAWED_CHAIN | "ECB鹰派→EUR上涨 这条链断了" | 因果推理错误 |
| REGIME_CHANGE | "9月出现新的政策框架" | 环境变化 |
| OVERCONFIDENCE | "预测0.81置信度但实际正确率仅60%" | 校准问题 |
| CORRECT_REASONING | "推理正确但幅度低估" | 方向对、幅度错 |
| BLACK_SWAN | "不可预测的外部冲击" | 低概率高影响事件 |

每条教训按实体（EUR/USD、AAPL）、行业（科技、能源）、根因类别三维索引。

---

## 五、Layer 4: 实体记忆进化

**问题**：每次分析对特定资产的理解从零开始。缺少"积累"。

### EntityMemory

```python
@dataclass
class EntityMemory:
    entity_id: str           # "EUR/USD" | "AAPL" | "gold" | "ECB" | "tech_sector"
    entity_type: str         # "asset" | "central_bank" | "sector" | "macro_indicator"
    
    # 累积知识
    analysis_count: int      # 分析过多少次
    lessons: list[dict]      # 历史教训（最近N条）
    
    # 统计特征
    avg_prediction_accuracy: float
    recurring_patterns: list[str]  # "ECB 12月会议通常偏鸽"、"黄金在3月季节性走强"
    key_levels: list[dict]         # [{"level": 1.05, "significance": "强支撑", "tested": 8}]
    
    # 行为特征
    best_performing_shadows: list[str]  # 谁最擅长分析这个实体
    common_blind_spots: list[str]       # 系统在这个实体上常犯什么错
    
    last_analyzed: str
    memory_freshness: float  # 0-1，根据最近分析时间衰减
```

### 检索机制

每次管道启动分析前，为每个待分析的资产查询 EntityMemory：
1. 加载最近 5 条教训
2. 注入到分析 Agent 的 system prompt："你过去分析 EUR/USD 时，以下教训值得注意：..."
3. 加载关键水平和重复模式作为分析基线

**存储**：SQLite — 实体记忆增长速度慢（每次分析产 1-2 条教训），不需要向量数据库。

---

## 六、Layer 5: 模型校准

**问题**：研究显示所有 LLM 在 90%+ 置信度区间系统性过度自信。

### 校准流水线

```
预测产出 → 收集验证结果(N≥50后启动) → 计算ECE → Platt缩放 → 调整后的置信度
```

**实现**：纯统计，不调用 LLM。当某个影子 AI 积累 ≥50 个已验证预测后，运行 Platt 缩放拟合，产出校准系数。此后该影子的置信度输出自动通过校准系数调整。

**KalshiBench 教训**：推理增强反而加剧过度自信。所以 Pro 的 CoT 推理输出需要单独校准，不能与 Flash 共享校准系数。

---

## 七、Layer 6: 跨影子知识蒸馏

**问题**：21 个影子各自独立分析，互不学习。擅长黄金的影子每天看黄金，积累了洞察但无法传递给其他影子。

### 专长发现

```python
def discover_expertise(calibration_trackers: dict[str, CalibrationTracker]) -> dict[str, list[str]]:
    """Find which shadows outperform baseline on which entities.
    
    Returns: {"shadow_gold_expert": ["gold", "XAU/USD", "GLD"],
              "shadow_tech_analyst": ["AAPL", "NVDA", "tech_sector"], ...}
    """
```

### 知识蒸馏

当影子 A 在实体 E 上 Brier 分数持续优于中位数 20%+ 时：
1. 提取影子 A 分析实体 E 时的推理模式（不是原始数据，是分析框架）
2. 将模式转化为方法论提示："分析黄金时，以下框架被证明有效：..."
3. 注入到其他阴影分析同一实体时的 system prompt
4. 知识传递后在下一周期验证：接收方的 Brier 分数是否改善
5. 如果改善 → 保留方法论；如果恶化 → 回滚

**不共享**：原始分析内容、投资结论、具体价格预测 — 只共享分析方法论框架。

---

## 八、基础设施需求

### 新增模块

| 模块 | 功能 | 复杂度 |
|------|------|:---:|
| `pipeline/prediction_extractor.py` | 从假设提取可验证预测 | 低 |
| `pipeline/calibration_tracker.py` | Brier分数 + ECE计算 + Platt缩放 | 中 |
| `pipeline/reflection_agent.py` | 结构化复盘 + 根因分类 | 中 |
| `pipeline/entity_memory.py` | 实体记忆读写 + 检索 | 低 |
| `pipeline/expertise_discovery.py` | 影子专长发现 + 知识蒸馏 | 中 |
| `storage/learning_store.py` | SQLite: 预测历史+教训+实体记忆+校准数据 | 中 |

### 新增 LLM 调用（非实时，批处理）

| 调用 | 频率 | 模型 | 预估 token |
|------|:---:|------|:---:|
| 预测提取 | 每次分析 | Flash | ~500 |
| 复盘分析 | 每日批处理 | Pro | ~2000/过期预测 |
| 根因分类 | 每日批处理 | Flash | ~500/条 |
| 方法论提炼 | 每周 | Pro | ~3000/专长影子 |

---

## 九、实施阶段

| 阶段 | 内容 | 依赖 |
|:---:|------|------|
| I-1 | PredictableHypothesis + prediction_extractor + SQLite存储 | 无 |
| I-2 | CalibrationTracker + Brier评分 + 方向准确率 | I-1 |
| I-3 | ReflectionAgent + 根因分类 + 结构化教训 | I-1 |
| I-4 | EntityMemory + 检索 + prompt注入 | I-3 |
| I-5 | Platt缩放 + 置信度自动调整 | I-2 |
| I-6 | 跨影子专长发现 + 知识蒸馏 | I-2 + I-4 |

---

## 十、与现有架构兼容性

- 不修改主管道阶段编号
- 不修改影子分析流程（只增加评分层）
- 复盘批处理独立运行，不阻塞每日分析
- EntityMemory 作为分析前的 context 注入，不影响 L1/L2/L3 逻辑
- 知识蒸馏只传递方法论框架，不共享原始分析（保持影子独立性）

## 十一、风险

| 风险 | 缓解 |
|------|------|
| 过度拟合历史模式 | 根因分类区分 REGIME_CHANGE — 环境变化时标记旧教训为过期 |
| 知识蒸馏导致群体思维 | 只蒸馏方法论框架，不蒸馏结论；猫鱼 Agent 继续强制执行异议 |
| 复盘 Pro 调用成本高 | 优先 Flash 评分 + 仅对高价值预测（Brier >0.5）运行 Pro 复盘 |
| 校准数据不足 | N≥50 预测后才启动校准；前期使用保守默认系数 |
| 实体记忆膨胀 | SQLite 每实体保留最近 20 条教训 + 摘要压缩旧教训 |

---

**方案状态**: 待红方审核
