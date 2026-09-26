# MarketMind Phase H: 深度分析增强综合架构方案

**日期**: 2026-05-18 | **基于**: 5 份研究方法论文献 + 3 份红方审计 + 4 份 Agent 研究 | **状态**: 待红方审核 → 待用户审批

---

## 零、架构原则（不可违反）

1. **管道单向流动**：Stage N 的输出只流向 Stage N+1，不反向导入
2. **影子生态独立**：Shadows 不投票、不参与主决策，通过 `shadow_votes=None` 强制执行
3. **所有 LLM 调用通过 gateway**：`chat_flash` / `chat_pro`，不直接调 httpx
4. **模块契约**：每个新模块单一入口函数 + 明确 dataclass 输入/输出
5. **单源真理**：`pipeline-manifest.yaml` 为权威管道定义
6. **渐进增强**：新模块增强现有分析，不替代。旧代码路径保留为 fallback
7. **PICA 全协议**：每个新模块必须通过 PICA-Unit → Security → Integration → Regression

---

## 一、当前架构（基线）

### 管道流程
```
stage_0_shadow_init → stage_1_scout → stage_2_flash → stage_2b_investigation
                                                              │
                                                    [Gate 1: 用户确认方向]
                                                              │
stage_3_layer1 → stage_4_layer2_layer3 → stage_5_shadows → stage_6_red_team
                                                                      │
                                              stage_7_resonance ←─────┘
                                                      │
                                              stage_8_decision → stage_9_archive
```

### 现有模块能力边界
| 能力 | 现有模块 | 限制 |
|------|------|------|
| 信号提取 | `flash_preprocessor.py` | 从标题提取 FlashSignal，不做深层验证 |
| 假设生成 | `investigation_loop.py` | Pro 生成假设 + 4 层验证 + 对抗自检 |
| 叙事分析 | `layer1_narrative.py` | 事件分级、矩阵象限，描述"发生了什么" |
| 基本面 | `layer2_fundamental.py` | 5 层递进（宏观→资产→行业→因子→标的）|
| 技术面 | `layer3_technical.py` | 3 灯信号，独立于 L1/L2 |
| 统计验证 | `resonance.py` | DSR/CSCV/PBO，纯 Python |
| 对抗挑战 | `red_team.py` | 找逻辑漏洞、遗漏证据 |
| 决策合成 | `decision.py` | 标量置信度 + 单一方向 |

### 与参考方法论的差距（来自 4 份 Agent 研究）
参考分析师的 10 个能力中，现有管道**完全没有** 4 个，**部分覆盖** 6 个。详见 `pipeline-methodology-gap.md`。

---

## 二、增强模块设计

### 模块总览

```
                              ┌─────────────────────────────┐
                              │   pipeline/                 │
                              │   mechanism_glossary.py     │ ← 数据模块，零破坏半径
                              │   (机制术语库 ~80行)         │
                              └─────────────┬───────────────┘
                                            │ 被所有 prompt 引用
              ┌─────────────────────────────┼─────────────────────────────┐
              │                             │                             │
    ┌─────────▼──────────┐    ┌─────────────▼───────────┐    ┌───────────▼──────────┐
    │ causal_            │    │ flow_                   │    │ cross_border_        │
    │ decomposition.py   │    │ decomposition.py        │    │ analyzer.py          │
    │ (~250行)           │    │ (~250行)                │    │ (~250行)             │
    │                    │    │                         │    │                      │
    │ 资产/负债双视角     │    │ 5类实体资金流归属       │    │ TIC+BIS+CCB 集成     │
    │ 分解假设为对立力量  │    │ 谁在买/卖什么/为什么    │    │ 跨境流向异常检测     │
    └─────────┬──────────┘    └─────────────┬───────────┘    └───────────┬──────────┘
              │                             │                             │
              └─────────────────────────────┼─────────────────────────────┘
                                            │
    ┌───────────────────────────────────────┼───────────────────────────────┐
    │                                       │                               │
    ┌─────────▼──────────┐    ┌─────────────▼───────────┐    ┌───────────▼──────────┐
    │ regime_mapper.py    │    │ scenario_               │    │ fragility_           │
    │ (~300行)            │    │ forecaster.py           │    │ scanner.py           │
    │                    │    │ (~250行)                │    │ (~300行)             │
    │ 7变量欧氏距离搜索   │    │ 2-3条件变量分支树      │    │ ~15阈值库 + 级联链   │
    │ 历史类似期前向收益  │    │ 基/上/下行情景概率     │    │ 阈值突破预警        │
    └────────────────────┘    └─────────────────────────┘    └──────────────────────┘
```

### 模块 0：机制术语库（优先级 1，零破坏）

**文件**: `config/mechanism_glossary.py`（数据模块，允许多导出）

```python
# 映射：机制名 → {描述, 数据源, 方向含义, 相关机制}
MECHANISM_GLOSSARY = {
    "eSLR": {
        "description": "补充杠杆率豁免 — 下调大型银行额外杠杆缓冲，释放购债能力",
        "data_source": "FRED: TLAADFWATR",  # 或 Fed 监管公告
        "directional": "宽松 → 利多风险资产（银行购债能力上升）",
        "related": ["SLR", "GSIB_surcharge", "CCAR"]
    },
    "IORB": { ... },
    "FIMA_repo": { ... },
    # ... ~40 条
}
```

**集成方式**：所有 Pro 级 prompt 的 system prompt 追加：
> "当分析涉及机构机制时，使用标准术语（如 eSLR、IORB、FIMA、TGA）。将每个机制映射到其数据源和资产价格含义。"

**零新代码** — 只改 3 个文件中的 prompt 字符串 + 新建一个数据文件。

---

### 模块 1：因果分解 `causal_decomposition.py`（优先级 2）

**插入点**：`stage_2b_investigation` 内部，HVR 验证之前

**输入**: `HypothesisResult`（初始假设 + 4 层 float 分数）
**输出**: `CausalDecomposition` dataclass

```python
@dataclass
class CausalDecomposition:
    hypothesis: str
    asset_side_factors: list[tuple[str, float]]   # [(因子, 影响力 0-1)]
    liability_side_factors: list[tuple[str, float]]
    net_liquidity_impact: float                    # -1 (抽水) to +1 (放水)
    asset_liability_tension: float                 # 0 (一致) to 1 (对立)
    mechanism_chain: list[str]                     # e.g., ["TGA↓ → 准备金↑ → 银行购债能力↑"]
```

**与现有模块的关系**：
- 调用 `chat_pro` 进行分解（通过 gateway）
- 不修改 `VerificationResult` 结构
- 分解结果作为 `HypothesisResult` 的新可选字段 `causal: CausalDecomposition | None`
- 如果分解失败（Pro 返回无法解析），字段为 None → 管道继续正常运行

**不冲突证明**：
- 在 `investigation_loop.py` 的 HVR 循环中，验证之前插入分解步骤
- 分解结果不影响 verdict 分类逻辑（`_determine_verdict` 不变）
- 分解仅丰富输出，不改变控制流

---

### 模块 2：资金流分解 `flow_decomposition.py`（优先级 3）

**插入点**：`stage_2b_investigation` 内部，因果分解之后

**输入**: `HypothesisResult` + `CausalDecomposition`
**输出**: `FlowAttribution` dataclass

```python
@dataclass
class FlowAttribution:
    entities: dict[str, FlowEntity]  # key = entity enum
    # FlowEntity: {direction: BUY|SELL, asset_class: str, size_estimate: str, rationale: str}
    dominant_buyer: str
    dominant_seller: str
    flow_imbalance: float       # -1 (卖压倒性) to +1 (买压倒性)
    change_trend: str           # "加速流入" | "流入放缓" | "转向流出"
```

**5 类实体**：`US_HOUSEHOLD | US_INSTITUTIONAL | FOREIGN_OFFICIAL | FOREIGN_PRIVATE | FED`

**数据源**：
- TIC 月度数据（Treasury.gov — 免费 CSV，~6 周滞后）
- Fed H.4.1 周度（FRED API）
- COT 期货持仓（已有 `macro_data.py`）
- 滞后数据用于结构理解，不用于时机选择

**不冲突证明**：
- 完全独立于 L2/L3 基本面/技术面分析
- 不改变现有的 `layer2_fundamental.py` 逻辑
- 若数据源不可用 → 优雅降级为 "数据不可用" 标记

---

### 模块 3：历史体制映射 `regime_mapper.py`（优先级 4）

**插入点**：替换 `verification_chain.py` Layer 4（`verify_claim_historical`）

**当前 Layer 4 问题**：固定关键词 → 固定概率（`rate_cut=0.65`），不是真正的历史对比

**新实现**：
```python
@dataclass
class RegimeMatch:
    regime_id: str           # "volcker_1979_1982"
    regime_name: str         # "沃尔克时代"
    similarity: float        # 欧氏距离归一化 [0,1]
    forward_3m_equity: float
    forward_6m_equity: float
    forward_12m_equity: float
    key_differences: list[str]  # "这次不同"的理由

@dataclass
class RegimeMapping:
    current_quadrant: str    # 增长↑通胀↑ / 增长↑通胀↓ / 增长↓通胀↑ / 增长↓通胀↓
    top_analogues: list[RegimeMatch]   # 最相似 5 个时期
    anti_analogues: list[RegimeMatch]  # 最不相似 3 个时期
    regime_consensus: str    # 基于类似时期的一致预测
```

**方法**：Bridgewater 四象限（GDP 增速 × CPI 方向）+ Man Group 7 变量欧氏距离搜索

**7 变量**：S&P 500 同比、10Y-2Y 利差、WTI 同比、铜同比、T-bill 收益率、VIX 水平、股债相关性

**数据**：1985-2025 月度，全部来自 FRED（免费）

**不冲突证明**：
- 替换 `verify_claim_historical()` 的实现，但保持相同函数签名
- 返回的 float 仍可参与加权置信度计算
- 如果 regime 数据未加载 → 降级为旧版关键词启发式（fallback）

---

### 模块 4：条件预测 `scenario_forecaster.py`（优先级 5）

**插入点**：`stage_2b_investigation` 完成后，仅对 ACTIONABLE 判定运行

**输入**: `HypothesisResult`（verdict=ACTIONABLE）
**输出**: `ScenarioTree` dataclass

```python
@dataclass
class ScenarioBranch:
    conditions: dict[str, str]  # {"10Y收益率": "保持在4.5%以下", "国会": "通过监管改革"}
    probability: float
    outcome: str
    confidence: float
    timeline: str               # "3-6个月"

@dataclass
class ScenarioTree:
    base_case: ScenarioBranch
    upside_case: ScenarioBranch
    downside_case: ScenarioBranch
    key_condition_variables: list[str]  # 决定走哪条路的 2-3 个变量
```

**不冲突证明**：
- 仅对 ACTIONABLE 运行（~1-3 个假设/会话），控制 token 成本
- 不影响 `_determine_verdict()` 判决逻辑
- 作为 `HypothesisResult` 的可选字段，决策阶段可选择消费

---

### 模块 5：脆弱性扫描 `fragility_scanner.py`（优先级 7）

**插入点**：`stage_7_resonance` 之后、`stage_8_decision` 之前（新 stage_7b）

**输入**: 所有 ACTIONABLE 假设 + 当前市场数据
**输出**: `FragilityReport`

```python
@dataclass
class FragilityThreshold:
    metric: str              # "银行准备金"
    current_value: float
    threshold_value: float
    direction: str           # "below" | "above"
    distance_pct: float      # 距阈值还有多远
    crossed: bool
    cascade: list[str]       # 突破后的级联效应

@dataclass
class FragilityReport:
    active_warnings: list[FragilityThreshold]  # 已突破或接近(<5%)的阈值
    monitored: list[FragilityThreshold]        # 远离阈值(>10%)的指标
    overall_fragility_score: float             # 0 (稳固) to 1 (极端脆弱)
```

**阈值库** (`config/fragility_thresholds.py`)：初始 ~15 条，来自专业文献：

| 指标 | 阈值 | 方向 | 突破后果 |
|------|------|:---:|------|
| 银行准备金 | $2.7T | 跌破 | SOFR 飙升 → 回购市场冻结 |
| 10Y 美债收益率 | 4.5% | 突破 | 政治痛觉 → 政策急转弯 |
| ON RRP | $50B | 跌破 | 最后流动性缓冲耗尽 |
| SOFR-IORB 利差 | +25bp | 突破 | 2019年9月式回购危机 |
| HYG-LQD 利差 | +200bp | 突破 | 信用市场压力 |
| VIX | 35 | 突破 | 恐慌性抛售 |
| ... | ... | ... | ... |

**不冲突证明**：
- 新 stage_7b，插在 Resonance 和 Decision 之间
- 不修改任何现有 stage
- 输出作为 Decision 的风险叠加层，不替代决策逻辑

---

### 模块 6：跨境资本流 `cross_border_analyzer.py`（优先级 8）

**插入点**：新 `gateway/cross_border.py`（数据网关）+ `pipeline/cross_border_analyzer.py`（分析模块）

**数据源**：
- TIC 月度报告（Treasury.gov — CSV）
- BIS 地域银行统计（BIS API — JSON）
- FRED 交叉货币基差系列（`EXJPUS`, `EXUSEU`）

**输出**: `CrossBorderFlowReport`

```python
@dataclass
class CrossBorderFlowReport:
    country_flows: dict[str, float]      # 国家 → 净流入/流出(美元)
    ccb_alerts: list[str]                # 交叉货币基差异常
    fima_usage: dict[str, float]         # FIMA 回购使用情况
    unusual_patterns: list[str]          # 异常模式描述
```

**不冲突证明**：
- 作为可选增强层，若数据不可用则静默跳过
- 不影响主管道决策，仅丰富最终报告

---

## 三、管道集成（完整增强后）

```
stage_1_scout → stage_2_flash → stage_2b_investigation
                                      │
                    ┌─────────────────┼──────────────────┐
                    │                 │                  │
              [因果分解]        [资金流分解]        [HVR验证+对抗]
                    │                 │                  │
                    └─────────────────┼──────────────────┘
                                      │
                              [条件预测树]  ← 仅对 ACTIONABLE
                                      │
                              [Gate 1: 用户确认]
                                      │
stage_3_layer1 → stage_4_layer2_layer3 → stage_5_shadows → stage_6_red_team
                                                                  │
                                          stage_7_resonance ←─────┘
                                                  │
                                          stage_7b_fragility  ← NEW
                                                  │
                                          stage_8_decision → stage_9_archive
```

**关键集成规则**：
1. 因果分解 + 资金流分解在 HVR 循环内并行运行（`asyncio.gather`）
2. 条件预测仅对 ACTIONABLE 判定运行（~1-3 个/会话）
3. 脆弱性扫描在 Resonance 验证后运行，为 Decision 提供风险叠加
4. 历史体制映射替换 Layer 4，保持接口兼容
5. 机制术语库被所有 prompt 引用，零运行时成本
6. 跨境资本流为可选增强层，数据不可用时静默降级

---

## 四、数据模型变更

### HypothesisResult 扩展

新增 11 个字段（8 个基础 + 3 个可选复杂类型）：

```python
@dataclass
class HypothesisResult:
    # ── 现有字段（不变）──
    hypothesis: str
    expectation_gap: float
    verification: VerificationResult
    refined_hypothesis: str
    confidence: float
    bear_case: str
    bear_case_confidence: float
    verdict: str
    logic_chain: list[str]

    # ── 新增基础字段（带默认值，向后兼容）──
    direction: str = ""              # "EUR/USD 看涨"
    core_logic: str = ""             # 一句逻辑摘要
    risk_level: str = "中等"         # 低/中等/高
    time_window: str = ""            # "2-4周"
    layer_1_narrative: str = ""      # L1 叙事
    layer_2_narrative: str = ""
    layer_3_narrative: str = ""
    layer_4_narrative: str = ""

    # ── 新增复杂字段（可选，增强模块填充）──
    causal: CausalDecomposition | None = None
    flow: FlowAttribution | None = None
    scenario_tree: ScenarioTree | None = None
```

**向后兼容**：所有新字段有默认值，现有测试不破坏。

---

## 五、与现有模块的兼容性证明

### 与 shadow_ecosystem 不冲突
- 所有新模块在 **主 AI 管道** 内运行
- Shadows 仍收到原始新闻 + 用户意见（广播规则不变）
- 因果分解/资金流/体制映射的输出**不作为影子输入** — 避免锚定
- `shadow_votes = None` 不变

### 与 L1/L2/L3 不冲突
- 因果分解在 HVR 阶段（Stage 2b）运行，在 L1 之前
- L1 的叙事分析仍描述"发生了什么"；因果分解回答"为什么"
- L2 的 5 层基本面递进不变
- L3 仍只接收原始市场数据（DD-004 不变）

### 与 decision.py 不冲突
- Decision 接收增强后的 HypothesisResult
- 新增字段为可选 — decision 如果不需要因果/资金流/情景树，直接忽略
- 脆弱性报告作为新输入传给 decision，作为风险叠加层

### 与 grandfather clause 不冲突
- `app.py` 的提取在 Phase H 开始前完成（前置步骤 1）
- 新增模块 ≤ 300 行（硬上限内）
- `investigation_loop.py` 当前 704 行 → 超过硬上限 → 但仅做增强插入（~50 行胶水代码），属 grandfather 允许范围

---

## 六、实施阶段

### Phase H-0: 前置修复（当前进行中 🔄）
| 步骤 | 内容 | 文件 | 状态 |
|:---:|------|------|:---:|
| 0.1 | 原子写入 + 安全反序列化 | `session.py`, `archivist.py` | ✅ |
| 0.2 | 管道 manifest 更新 | `pipeline-manifest.yaml` | ✅ |
| 0.3 | HypothesisResult 字段扩展 | `investigation_loop.py` | 🔄 Agent |
| 0.4 | session.py 损坏日志 | `session.py` | 🔄 Agent |
| 0.5 | app.py 提取 | `app.py` → `pipeline/orchestration.py` | ⬜ |
| 0.6 | `ensure_dirs()` + `"gates"` | `archivist.py` | ✅ |

### Phase H-1: Gate 1 实施（待用户审批方案）
| 步骤 | 内容 | 新模块 |
|:---:|------|------|
| 1.1 | `integrity/input_guard.py` | `integrity/` |
| 1.2 | 8 个安全测试（TDD） | `tests/test_integrity/` |
| 1.3 | `hypothesis_card.py` | `pipeline/` |
| 1.4 | `gate1_interaction.py` | `pipeline/` |
| 1.5 | `gate_archiver.py` | `storage/` |
| 1.6 | `pipeline/orchestration.py` | `pipeline/` |
| 1.7 | `app.py` 接入 | root |
| 1.8 | `kill_monitor.py` | `pipeline/` |

### Phase H-2: 机制命名（零破坏）
| 步骤 | 内容 | 文件 |
|:---:|------|------|
| 2.1 | `mechanism_glossary.py` | `config/` |
| 2.2 | Prompt 更新 | `investigation_loop.py`, `layer2_fundamental.py`, `verification_chain.py` |

### Phase H-3: 因果分解 + 资金流
| 步骤 | 内容 |
|:---:|------|
| 3.1 | `causal_decomposition.py` |
| 3.2 | `flow_decomposition.py` |
| 3.3 | 集成进 `investigation_loop.py` |

### Phase H-4: 历史体制 + 条件预测
| 步骤 | 内容 |
|:---:|------|
| 4.1 | `regime_library.py` (config) |
| 4.2 | `regime_mapper.py` → 替换 Layer 4 |
| 4.3 | `scenario_forecaster.py` |

### Phase H-5: 脆弱性 + 跨境
| 步骤 | 内容 |
|:---:|------|
| 5.1 | `fragility_thresholds.py` (config) |
| 5.2 | `fragility_scanner.py` → stage_7b |
| 5.3 | `cross_border.py` (gateway) |
| 5.4 | `cross_border_analyzer.py` |

---

## 七、风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|:---:|:---:|------|
| 新模块导致 HVR 循环 token 成本过高 | 中 | 高 | 因果/资金流使用 Flash；条件预测仅对 ACTIONABLE 运行 |
| 体制映射数据不足（FRED 无 1985 年前部分序列）| 低 | 中 | 使用较短历史窗口 + 降级到关键词 fallback |
| TIC 数据 6 周滞后导致跨境流分析过时 | 高 | 低 | 明确标注"结构性参考，非时机信号"|
| app.py 提取过程中引入回归 | 中 | 高 | 每步提取后全量测试；提取一步 → 测试 → 提交 |
| 影子生态与增强分析产生干扰 | 极低 | 高 | 信息广播规则不变；增强输出不传给影子 |

---

## 八、下一步

1. **红方审核**本方案（安全 + 逻辑 + 架构，3 并行 Agent）
2. **用户审批**
3. Phase H-0 前置修复完成
4. Phase H-1 Gate 1 实施
5. Phase H-2 至 H-5 按顺序推进

---

**方案状态**: 待红方审核
