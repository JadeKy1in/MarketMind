# 影子生态系统运行框架 (Shadow Ecosystem Operational Framework)

**版本**: 1.0
**日期**: 2026-05-20
**状态**: 权威参考文档
**适用范围**: MarketMind 影子生态系统（24 个常驻影子，3 种策略原型）
**前置阅读**: `shadow-type-redesign-v3.md`（影子分类体系）、`shadow-introductions-zh.md`（影子成员介绍）

---

## 目录

1. [系统总览](#1-系统总览)
2. [信息获取](#2-信息获取)
3. [独立分析](#3-独立分析)
4. [虚拟交易执行](#4-虚拟交易执行)
5. [绩效追踪](#5-绩效追踪)
6. [事后复盘](#6-事后复盘)
7. [知识结晶](#7-知识结晶)
8. [排名与权重](#8-排名与权重)
9. [奖惩机制](#9-奖惩机制)
10. [进化与选择](#10-进化与选择)
11. [生态治理](#11-生态治理)
12. [决策融合（未来/Gate 3 受限）](#12-决策融合未来gate-3-受限)
13. [生命周期流程图](#13-生命周期流程图)
14. [奖惩机制汇总表](#14-奖惩机制汇总表)
15. [关键约束与隔离规则](#15-关键约束与隔离规则)
16. [时间维度：日/周/月/事件触发](#16-时间维度日周月事件触发)

---

## 1. 系统总览

### 1.1 什么是影子？

影子（Shadow）是 MarketMind 平台内的独立 AI 分析代理。每个影子拥有自己的策略方法论、虚拟资金组合、记忆系统和排名历史。24 个常驻影子按策略原型分为三类，在一个受控的竞争生态中运行——它们独立分析市场、做出虚拟投资决策、接受绩效排名，但**绝不直接影响主流水线的真实投资决策**。

### 1.2 三类型架构

```
Fundamental (16)     Momentum (4)        Contrarian (4)
领域专家              动量/趋势             逆向/敢死队

始终活跃              始终活跃              条件触发
τ=0.30-0.40          τ=0.40-0.50          τ=0.45-0.60
90天评估窗口          75天评估窗口           252天评估窗口
回撤上限 25%          回撤上限 30%           回撤上限 35-40%
min 5笔交易           min 50笔交易           min 25-35笔交易
```

### 1.3 核心设计原则

1. **物理隔离**: 影子只接收原始新闻+市场数据，**永远不接触**主 AI 的分析结果或内部讨论——防止锚定偏差。
2. **独立分析**: 影子之间不互相读取对方的当日分析结果，各自独立完成决策。
3. **内部竞争**: 影子产出的是**独立的投资分析**（不是投票），仅用于内部排名比较。影子分析结果存储在 `shadow_analyses` 表中，**没有路径进入主决策**。
4. **追加状态**: 影子状态只追加不修改。早期上下文永不覆盖，新信息作为新消息追加到尾端。
5. **精英限制**: ELITE 精英影子在 Gate 2 中最多贡献一次，标记为"影子意见"，无决策权。

### 1.4 完整影子清单

#### Fundamental — 16 领域专家（策略原型：基本面估值 + 领域专业知识）

| shadow_id | 显示名 | 领域 | 虚拟资本 | 温度(τ) |
|------|------|------|------|:--:|
| `expert:gold:bullion_broker` | Bullion Broker | 贵金属 | $50K | 0.30 |
| `expert:crypto:chain_oracle` | Chain Oracle | 加密货币 | $45K | 0.35 |
| `expert:energy:oil_geologist` | Oil Geologist | 能源 | $50K | 0.30 |
| `expert:bonds:yield_whisperer` | Yield Whisperer | 债券 | $55K | 0.30 |
| `expert:vol:vega_trader` | Vega Trader | 波动率 | $40K | 0.40 |
| `expert:em:frontier_scout` | Frontier Scout | 新兴市场 | $45K | 0.35 |
| `expert:tech:silicon_oracle` | Silicon Oracle | 科技 | $50K | 0.30 |
| `expert:financials:bank_examiner` | Bank Examiner | 金融 | $48K | 0.30 |
| `expert:healthcare:trial_reviewer` | Trial Reviewer | 医疗 | $48K | 0.30 |
| `expert:consumer:wallet_watcher` | Wallet Watcher | 消费 | $46K | 0.30 |
| `expert:industrials:factory_floor` | Factory Floor | 工业 | $48K | 0.30 |
| `expert:metals:steel_trader` | Steel Trader | 工业金属 | $42K | 0.35 |
| `expert:agriculture:harvest_seer` | Harvest Seer | 农产品 | $42K | 0.35 |
| `expert:realestate:reit_analyst` | REIT Analyst | 房地产 | $48K | 0.30 |
| `expert:fx:currency_dealer` | Currency Dealer | 外汇 | $44K | 0.35 |
| `expert:macro:cycle_reader` | Cycle Reader | 宏观 | $60K | 0.30 |

**评估**: 90天窗口，均衡权重（MPPM 0.35 / Calmar 0.25 / Omega 0.20 / WinRate 0.20）

#### Momentum — 4 动量/趋势（策略原型：趋势延续、正反馈）

| shadow_id | 显示名 | 策略 | 持有期 | 虚拟资本 | τ |
|------|------|------|------|------|:--:|
| `momentum:intraday:scalper` | Intraday Scalper | 日内动量 | 1-3天 | $25K | 0.50 |
| `momentum:weekly:trend_rider` | Trend Rider | 周线趋势 | 5-15天 | $30K | 0.40 |
| `momentum:event:news_hound` | Event Hound | 事件追入 | 1-5天 | $25K | 0.45 |
| `momentum:sector:rotation_engine` | Rotation Engine | 板块轮动 | 5-20天 | $30K | 0.40 |

**评估**: 75天窗口，高 Calmar 权重（回撤控制对动量策略更关键）
**免疫**: 区间市场（RANGE_BOUND）下动量损失不触发淘汰

#### Contrarian — 4 逆向/敢死队（策略原型：均值回归、负反馈）

| shadow_id | 显示名 | 触发条件 | 激活频率 | 虚拟资本 | τ |
|------|------|------|:--:|------|:--:|
| `contrarian:consensus:fade_master` | Fade Master | 始终活跃（每日） | 高 | $20K | 0.55 |
| `contrarian:range_bound:sideways_scout` | Sideways Scout | 全球扫描：15+指数找区间市场 | 高 | $25K | 0.45 |
| `contrarian:panic:vol_surfer` | Vol Surfer | 全球扫描：任一波动率指数飙升 | 中 | $30K | 0.60 |
| `contrarian:crash:hunter` | Crash Hunter | 全球扫描：任一地区 ≥2 bubble信号 | 中 | $30K | 0.50 |

**评估**: 252天窗口，高 Omega 权重（尾部结果更重要）+ Brier Score
**免疫**: 趋势市场（TRENDING）下逆向损失不触发淘汰
**全球扫描**: 每个 Contrarian 影子扫描全球市场寻找符合策略原型的极端状态

#### 动态影子类型（临时创建，有生命周期）

| 类型 | 用途 | 生命周期 |
|------|------|------|
| `temp_event` | 突发事件追踪（央行冲击、地缘事件、波动率冲击、人事变动） | 最长30天 |
| `missed_path` | 追踪 Gate 1 中被拒绝的方向（反事实路径） | 30天报告期 |
| `challenger` | 挑战者影子（替代表现不佳的影子） | 直至2周对比试验结束 |
| `beta` | 实验性新策略测试 | 隔离期，不参与排名 |

---

## 2. 信息获取

### 2.1 数据管道总览

影子生态系统接收两类数据：

```
外部世界
  │
  ├─ Scout 新闻采集 (35 sources, ~587 articles/day)
  │   └─ 原始标题+摘要 → 所有影子
  │
  └─ 市场数据 API
      └─ 价格、成交量、技术指标 → 影子根据策略类型获取
```

### 2.2 新闻数据：Scout 管道

- **来源**: 35 个经过审计的新闻来源，每日产生约 587 篇文章
- **原始形式**: 影子接收**原始新闻标题和摘要**，而非主 AI 的分析结果——这确保独立性
- **传递方式**: `ShadowMother.analyze_all_shadows()` 将新闻列表作为原始数组传入每个影子

### 2.3 市场数据

- **内容**: 价格数据、成交量、波动率指标（VIX、ATR）、技术指标（RSI、MACD、布林带）
- **来源**: 通过 `gateway/async_client.py` 统一网关访问（所有 LLM 调用都经过此网关）
- **M1 数据完整性协议**: 在网关层注入，对所有影子 LLM 调用生效

### 2.4 领域过滤

每个影子类型根据自己的策略过滤数据——它们不接收相同的输入子集：

**Expert（基本面专家）**:
- 过滤方式：领域关键词匹配（每个领域有专属关键词集）
- 示例：`expert:gold:bullion_broker` 只接收包含 "gold"、"silver"、"precious"、"GLD"、"COMEX" 等的新闻
- Macro（宏观专家）: 接收所有新闻，不做过滤
- 过滤上限：最多 20 条相关新闻。如无相关新闻，回退取 5 条

**Momentum（动量）**:
- 接收：全量市场数据 + 技术指标（RSI、MACD、Volume Profile）
- 关注：价格动量、成交量异动、趋势强度、突破信号
- 持有期意识：Scalper 偏好 1-3 天视角，Trend Rider 偏好 5-15 天

**Contrarian（逆向/敢死队）**:
- 接收：全量市场数据 + 情绪指标（VIX 期限结构、Put/Call 比率、AAII 情绪调查）
- 估值指标：Shiller CAPE、信用利差、股债收益差
- **全球扫描**: Contrarian 影子不局限于美国市场——它们扫描 15+ 全球指数寻找符合策略原型的极端状态
- 这使得它们在大多数交易日都活跃（全球总有某市场处于区间/恐慌/泡沫状态）

### 2.5 信息隔离规则

影子**永远不接收**以下信息：
- 主 AI 流水线的分析结果（L1 叙事、L2 基本面、L3 技术面）
- 主 AI 的讨论记录（Gate 1/2/3 交互对话）
- 其他影子的当日分析结果
- 人类用户的交易决策或偏好
- 实际的经纪账户状态（虚拟账户独立运行）

这确保了**锚定偏差零传染**——每个影子从同一原始事实出发，走独立的分析路径。

---

## 3. 独立分析

### 3.1 分析执行流程

```
影子接收数据 → 构建 System Prompt → 调用 LLM → 解析结构化输出
```

**每一步的细节**:

1. **System Prompt**: 每个影子有唯一的 `methodology_prompt`（定义在 `ShadowConfig` 中），定义其投资哲学、分析框架、约束条件。Expert 影子额外加载领域专业知识（如 `expert:gold:bullion_broker` 的贵金属分析方法论）。

2. **User Prompt**: 包含领域过滤后的新闻标题列表 + 市场数据 JSON + 策略特定约束。Expert 影子将领域上下文注入 prompt；Daredevil 影子注入约束条件（如环境锁定、方向要求）。

3. **LLM 调用**: 所有分析通过 `gateway/async_client.py` 路由至 DeepSeek Pro 模型。调用方式：`chat_pro(system_prompt, user_prompt)`。

4. **结构化解析**: LLM 返回的文本通过 `VOTE_START`/`VOTE_END` 块标记解析，提取为 `ShadowVote` 数据对象。

### 3.2 ShadowAnalysisOutput 结构

```python
@dataclass
class ShadowAnalysisOutput:
    shadow_id: str                    # 影子唯一标识
    date: str                         # 分析日期
    votes: list[ShadowVote]           # 投资决策列表
    position_checks: list[PositionCheck]  # 现有持仓检查
    insights: list[str]               # 洞察列表
    methodology_notes: str            # 方法论备注
    quota_used: int                   # 已用配额
    latency_ms: int                   # 调用延迟（毫秒）

@dataclass
class ShadowVote:
    shadow_id: str
    shadow_type: str                  # "expert"|"momentum"|"contrarian"
    date: str
    ticker: str                       # 标的代码
    direction: str                    # "long"|"short"|"abstain"
    confidence: float                 # 0.0-1.0
    thesis: str                       # 一句话投资逻辑
    risk_note: str                    # 一句话风险提示
    emergency_flag: bool              # 置信度 >= 8/10?
```

**关键语义**: 这不是一个"投票"——这是一个**投资决策**。每个 ShadowVote 代表该影子判断该标的应该做多/做空/观望，并附有完整的论点和风险说明。

### 3.3 配额管理

每个影子每日有明确的 LLM 调用配额：

| 配额类型 | 默认值 | 说明 |
|------|:---:|------|
| `flash_quota` | 3 次/日 | DeepSeek Flash（轻量级数据任务） |
| `pro_quota` | 5 次/日 | DeepSeek Pro（深度分析，主调用） |

配额消耗后记录在 `daily_snapshots.flash_quota_used` 和 `daily_snapshots.pro_quota_used` 中。

### 3.4 紧急配额机制

当影子基础配额耗尽但仍有高价值机会时，可以申请紧急配额：

**触发条件**: 基础 pro 配额已耗尽 (`used >= total`)
**前提约束**: 影子必须处于 "normal" 状态（不在处罚期中）
**审批流程**: 自动审批（基于状态机），记录在 `emergency_quotas` 表中
**奖惩状态机**:

```
NORMAL → PENDING → AUDIT → REWARDED/PENALIZED → NORMAL

- 盈利 → 永久 +1 每日配额
- 亏损（未执行）→ 3 天观察期处罚
- 亏损（已执行）→ 7 天处罚
- 连续 3 次亏损 → 永久 -1 配额
```

### 3.5 并行执行

所有 24 个影子的分析**并发执行**——使用 `asyncio.gather()` 同时启动所有 LLM 调用。唯一的例外是：

**Fade Master 二次通行**: 在所有其他影子完成分析后，Fade Master 获取共识方向信息作为额外输入，进行第二遍分析以生成逆向信号。这是一项结构性优势——Fade Master 知道群体在做什么，可以有针对性地逆向。

### 3.6 温度参数

每个影子类型的 LLM 温度（τ）控制创造性与稳定性的平衡：

| 类型 | τ 范围 | 含义 |
|------|:--:|------|
| Expert | 0.30-0.40 | 高纪律、低幻觉——严格执行领域方法论 |
| Momentum | 0.40-0.50 | 中等创造空间——需要灵活识别动量模式 |
| Contrarian | 0.45-0.60 | 最高创造性——逆向思维需要跳出框架 |

---

## 4. 虚拟交易执行

### 4.1 从决策到交易记录

影子分析输出中的每个 `ShadowVote` 被解析为 `VirtualTrade` 记录并写入 SQLite：

```sql
CREATE TABLE virtual_trades (
    id INTEGER PRIMARY KEY,
    shadow_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,          -- "long"|"short"
    entry_price REAL NOT NULL,        -- 入场价格
    exit_price REAL,                  -- 出场价格（持仓中为 NULL）
    position_size_pct REAL NOT NULL,  -- 仓位占虚拟资本百分比
    entry_date TEXT NOT NULL,
    exit_date TEXT,
    exit_reason TEXT,                 -- stop_loss|take_profit|time_expiry|shadow_exit
    pnl_pct REAL,                     -- 盈亏百分比
    virtual_slippage_applied REAL,    -- 已应用的虚拟滑点
    confidence_discount_applied REAL, -- 已应用的置信度折扣
    paper_live_gap_ratio REAL         -- 纸面对实盘差距比率
);
```

### 4.2 虚拟滑点

一笔交易入场和出场时自动应用虚拟滑点：

- **公式**: `slippage = ATR * 0.5%`（默认为 ATR 的 0.5%）
- **多头入场**: `adjusted_price = entry_price + slippage`（以略差价格买入）
- **多头出场**: `adjusted_price = exit_price - slippage`（以略差价格卖出）
- **空头方向相反**

### 4.3 置信度折扣

影子报告的收益自动应用折扣映射到"纸面到实盘差距"：

- **基准折扣率**: 20%——所有影子报告的收益默认打八折
- **折扣下限**: 5%（通过改进 GapRatio 可降低至最低 5%）
- **GapRatio 闭合**: `gap_closure_adjustment_factor`——影子实际的实盘表现改善 → 折扣率逐步降低
- 折扣率存储在 `daily_snapshots.discount_rate` 中，初始值 0.20

### 4.4 纸面到实盘差距追踪

`PaperLiveGapManager` 管理完整的 gap 追踪：

1. **跨影子 GapRatio**: 比较每个影子的 PnL 与同一标的、同一日期的中位数影子表现
2. **折扣闭合**: GapRatio 改善 → 降低折扣率（最低 5%）
3. **实盘认证**: 影子必须满足 6 项标准才能被认证为 "live-ready"（表示其虚拟表现可信）

### 4.5 持仓追踪

活跃持仓记录在 `virtual_trades` 表中（`exit_date IS NULL`）。`ShadowAgent.get_open_positions()` 查询活跃持仓并生成 `PositionCheck` 列表。

### 4.6 退出条件

虚拟持仓可以在以下条件触发时退出：

| 退出条件 | 触发机制 | 记录方式 |
|------|------|------|
| **止损** | 价格触及止损价 | `exit_reason = "stop_loss"` |
| **止盈** | 价格触及目标价 | `exit_reason = "take_profit"` |
| **时间到期** | 超过最大持仓天数 | `exit_reason = "time_expiry"` |
| **影子主动退出** | 影子自身分析决定退出 | `exit_reason = "shadow_exit"` |

---

## 5. 绩效追踪

### 5.1 每日快照

每个交易日的每个活跃影子生成一条 `DailySnapshot` 记录：

```sql
CREATE TABLE daily_snapshots (
    shadow_id TEXT,
    date TEXT,
    virtual_capital REAL,        -- 当日虚拟资本
    daily_return_pct REAL,       -- 日收益率
    cumulative_return_pct REAL,  -- 累计收益率
    max_drawdown_pct REAL,       -- 最大回撤
    win_rate_pct REAL,           -- 胜率
    sharpe_ratio REAL,           -- Sharpe 比率
    calmar_ratio REAL,           -- Calmar 比率
    omega_ratio REAL,            -- Omega 比率
    mppm_score REAL,             -- MPPM 评分
    composite_score REAL,        -- 综合评分
    deflated_score REAL,         -- 贝叶斯折扣后评分
    percentile_rank REAL,        -- 百分位排名
    achievement_tier TEXT,       -- 成就等级
    flash_quota_used INTEGER,
    pro_quota_used INTEGER,
    emergency_quotas_used INTEGER,
    insights_generated INTEGER,
    votes_produced INTEGER,
    discount_rate REAL           -- 当前折扣率
);
```

### 5.2 核心绩效指标

#### MPPM (Manipulation-Proof Performance Measure)

Goetzmann et al. 提出的操纵证明绩效指标：

```
MPPM = (1/(1-γ)) * ln((1/T) * Σ(1+r_t)^(1-γ))
```

其中 γ = 3.0（风险厌恶参数）。该指标对收益序列操纵具有理论抗性。

#### Calmar 比率

```
Calmar = CAGR / max(|MDD|, 0.001)，上限 100
```

衡量单位回撤的收益效率。对 Momentum 影子权重更高（回撤控制对动量策略更关键）。

#### Omega 比率

```
Omega(L=0) = Σ(gains) / Σ(|losses|)，上限 10
```

衡量收益-损失不对称性。高 Omega 意味着收益尾部大于损失尾部。对 Contrarian 影子权重更高（尾部结果更重要）。

#### Brier Score（概率校准）

用于验证影子置信度是否与最终结果匹配。高置信度+错误预测 = 高 Brier 惩罚。Contrarian 影子评估中包含 Brier Score。

### 5.3 综合评分（Composite Score）

V2 公式（Phase 2b）：

```
C_v2 = 0.30*MPPM(normalized) + 0.20*Calmar(normalized)
     + 0.15*Omega(normalized) + 0.15*WinRate(normalized)
     + 0.20*Calibration_Score
```

动态调整：
- **职业生涯早期 (< 60天)**: WinRate 权重被提升（额外+0.10），鼓励方向准确性
- **职业生涯成熟 (≥ 180天)**: 如累计收益 > 10%，WinRate 权重可下调（最低 0.12），为盈利能力腾出权重
- **Abstention 惩罚**: 影子 > 30% 天数不交易 → 综合评分扣除
- **亏损惩罚**: 累计收益 < 0 → 综合评分乘以 (1 - penalty)，最低到 0.02
- **无校准数据回退**: 如无 Brier/校准数据，V2 权重均匀重分配到 V1 四分量

### 5.4 贝叶斯过拟合折扣

使用 Witzany (2021) 方法 + Effective-N 修正：

```
haircut = 1 - sqrt((ln(N_eff) + ln(T)) / T)
N_eff = N / (1 + (N-1) * mean_abs_corr)
```

- 小样本（少影子、短历史）→ 更大折扣
- 影子高度相关 → 更小 Effective-N → 更大折扣
- 这防止了"短期随机胜出者被过早奖励"的问题

### 5.5 排名历史

每次排名计算都会写入 `ranking_history` 表：

```sql
CREATE TABLE ranking_history (
    date TEXT,
    shadow_id TEXT,
    rank INTEGER,           -- 当前排名
    composite_score REAL,   -- 综合评分
    deflated_score REAL,    -- 折扣后评分
    component_scores TEXT   -- JSON: 各分项得分
);
```

### 5.6 成就等级（Achievement Tier）

基于**连续天数规则**的五级体系（非单日百分位）：

| 等级 | 条件 | 含义 |
|------|------|------|
| **Elite** | 连续 N 天百分位 ≥ 90th + Deflated Sharpe > 阈值 | 顶级表现，享有最高权重和影响力 |
| **Excellent** | 连续 N 天百分位 ≥ 75th + Deflated Sharpe > 阈值 | 优秀表现，权重有加成 |
| **Normal** | 默认 | 正常表现 |
| **Watch** | 连续 N 天百分位 < 25th 或 最大回撤 > 阈值 | 观察名单——需要改进 |
| **Endangered** | 连续 N 天百分位 < 10th | 濒危——进入淘汰流程 |

等级存储在每日快照和当前影子状态中。

---

## 6. 事后复盘

### 6.1 Reflection Agent

当预测结果被验证后（价格达到到期日），触发 `reflection_agent.py` 进行结构化事后分析。

**触发事件**:
- 大额亏损（亏损超过 $1,000 或 10%）
- 止损触发
- 连续亏损（连续 3 笔交易亏损）
- 大额盈利（盈利超过 $2,000 或 20%）

**模型路由**:
- 成功案例 → DeepSeek Flash（快速、低成本确认"为什么对了"）
- 失败案例 → DeepSeek Pro（深度分析"为什么错了"）

### 6.2 结构化复盘输出

```python
@dataclass
class StructuredLesson:
    lesson_id: str
    prediction_id: str
    outcome: str              # "SUCCESS" | "FAILURE"
    root_cause: str           # 根本原因分类
    updated_belief: str       # 系统应更新的信念
    entity: str               # 受影响资产/板块
    relevance_score: float    # 对未来分析的有用程度 (0-1)
    decay_factor: float       # 知识衰减因子 (初始 1.0)
```

### 6.3 根本原因分类体系

| 原因代码 | 中文说明 |
|------|------|
| `CORRECT_REASONING` | 推理正确但幅度估计不足 |
| `FLAWED_CHAIN` | 因果推理链条断裂——A→B 的逻辑不成立 |
| `MISSING_DATA` | 事后出现新数据推翻了预测——分析时缺少关键信息 |
| `OVERCONFIDENCE` | 预测方向正确但置信度过高——校准问题 |
| `DATA_SOURCE_ERROR` | 数据源本身有误——并非分析错误 |
| `REGIME_CHANGE` | 环境发生结构性变化——旧框架不再适用 |
| `BLACK_SWAN` | 不可预测的外部冲击 |

相关性评分按原因类型递减: CORRECT_REASONING (0.8) > FLAWED_CHAIN (0.7) > OVERCONFIDENCE (0.6) > MISSING_DATA (0.5) > DATA_SOURCE_ERROR (0.4) > REGIME_CHANGE (0.3) > BLACK_SWAN (0.2)

### 6.4 复盘结果存储

复盘产生的 `StructuredLesson` 存入影子分层记忆的**情节层（Episodic Memory）**，关联到具体的 Entity Memory。跨影子的模式识别会在知识结晶循环中运行。

---

## 7. 知识结晶

### 7.1 双层循环架构

```
内循环（Inner Loop）: 单影子内
  洞察 → 形式化假设 → 方法论微调 → 回测验证 → 升级/淘汰

外循环（Outer Loop）: 跨影子
  绩效追踪 → 统计显著性门 → 升级到语义记忆或淘汰
```

### 7.2 内循环：从洞察到方法论

1. **采集**: `CrystallizationEngine` 从情节记忆（Episodic Memory）查询高信念但不稳定的洞察
2. **形式化**: 将洞察转化为可测试的假设（如"黄金在美元走弱时做多胜率 > 60%"）
3. **微调**: `MethodologyEvolver` 生成方法论变更建议（如增加美元先行条件过滤）
4. **回测验证**: 对历史 `shadow_analyses` 数据进行回测，计算命中率
5. **判决**: `validation_score >= threshold` → promote（升级）/ `< threshold` → retire（淘汰）

### 7.3 外循环：统计显著性门

- **最小样本**: ≥ 10 笔交易/投票 才能进入结晶流程
- **显著性阈值**: 0.60（默认值）
- **升级**: 通过显著性门的洞察被提升到**语义记忆层（Semantic Memory）**——永久存储，跨影子可访问
- **淘汰**: 未通过门的洞察保持在情节记忆层，继续衰减

### 7.4 方法论进化器（Methodology Evolver）

`methodology_evolver.py` 维持所有分析方法的正式追踪：

```python
@dataclass
class MethodRecord:
    method_id: str              # 方法唯一标识
    description: str
    total_predictions: int      # 使用总量
    correct_predictions: int    # 成功量
    last_used: str
    last_correct: str
    decay_factor: float         # 1.0 = 全强度，趋向 0
    active: bool
    category: str               # "expert"|"daredevil"|"cross"
```

**预注册方法清单**（14 个基准方法）:

- Expert: gold, crypto, tech, energy, healthcare, realestate（6 个领域方法）
- Daredevil: scalper, trend-rider, news-hound, fade-master, rotation（5 个策略方法）
- Cross: catfish-contrarian, fundamental-analysis, technical-analysis, narrative-analysis（4 个跨领域方法）

**进化机制**:
- 方法成功 → decay_factor 重置为 1.0
- 方法连续失败 → decay_factor 按 γ=0.95 衰减
- decay_factor < 0.3 → 方法标记为 inactive
- 所有变更记录在 JSONL 审计追踪中（`evolution_audit.jsonl`）

### 7.5 方法论报告

每日生成 `MethodologyReport`：

```
- 总方法数 / 活跃方法数 / 已淘汰方法数
- 最优表现方法 TOP 5
- 最差表现方法 BOTTOM 5
- 已衰减方法列表
- 建议变更清单（基于统计显著差异）
```

---

## 8. 排名与权重

### 8.1 类型感知的评估窗口

不同类型的影子使用不同的历史窗口进行排名评估，因为它们的策略在时间尺度上有本质差异：

| 类型 | 评估窗口 | 原因 |
|------|:--:|------|
| **Expert** | 90 天 | 基本面分析的中期验证周期 |
| **Momentum** | 75 天 | 动量策略需要较短窗口以保持信号时效性 |
| **Contrarian** | 252 天（1年） | 逆向策略需要足够长的时间让均值回归发生 |

### 8.2 类型感知的权重配置

| 类型 | MPPM | Calmar | Omega | WinRate | Calibration |
|------|:--:|:--:|:--:|:--:|:--:|
| **Expert** | 0.35 | 0.25 | 0.20 | 0.20 | — |
| **Momentum** | 0.30 | 0.30 | 0.15 | 0.25 | — |
| **Contrarian** | 0.25 | 0.20 | 0.35 | 0.20 | +Brier |

- **Momentum 高 Calmar 权重**: 动量策略的致命弱点是回撤（动量崩溃），所以回撤效率权重最高
- **Contrarian 高 Omega 权重**: 逆向策略靠少数大胜弥补多数小亏，尾部不对称性最重要
- **Contrarian Brier Score**: 逆向影子需要额外验证其置信度校准——"看对的次数少但要敢重仓"

### 8.3 多样性控制器（MMC 风格折扣）

为防止影子生态退化到"所有人都说同样的话"：

**多样性折扣**: 当多个影子在同一标的上方向一致时，对同类影子应用逐步的权重折扣。原理类似于 Numerai MMC（Meta Model Contribution）——影子要证明自己的**独特信息贡献**而非共识跟随。

**唯一信号加成**: 产生真正独特信号（与所有其他影子不同的方向判断）的影子获得最高 **1.15x 权重乘数**。

**权重下限**: 每个影子无论表现多差，权重不低于 **2%**。这确保了生态的多样性底线——即使表现不佳的影子也能贡献不同的声音。

### 8.4 成就阶梯（类型特定阈值）

每种影子类型有独立的成就等级百分位阈值——这防止了"某一类型的影子总是占据 Elite 层"的不公平。

Expert 影子在 Expert 池内排名，Momentum 影子在 Momentum 池内排名，Contrarian 在 Contrarian 池内排名。跨类型排名仅用于生态全局视图（UI 展示），不影响各自池内的淘汰/晋升。

### 8.5 平稳期检测

`RankingEngine.detect_plateau()` 检测影子是否陷入"中等但停滞"的状态：

```
plateau_score = 0.5*stagnation + 0.3*wr_stability + 0.2*insight_drought

stagnation: 最近 plateau_no_elite_days 天内未达到 elite（0 或 0.5）
wr_stability: 近期胜率波动范围（窄 = 停滞，加 0-0.3）
insight_drought: 距离上次产生新洞察的天数（越长越高，加 0-0.2）
```

`plateau_score >= 0.5` → 标记为 plateaued（停滞）。停滞影子不会自动淘汰，但：
- 不享受 Elite 特权
- 可能触发方法论重置建议
- 在结晶循环中增加探索权重（降低 exploitation 倾向）

---

## 9. 奖惩机制

### 9.1 奖励体系

#### 1. 虚拟资本分配

高排名影子获得更大的虚拟资本额度——这模拟了 real-world pod-shop 中最佳 PM 获得更多资本的机制：

- 初始虚拟资本: 按影子类型设置（$20K-$60K）
- 动态调整: 每月的排名表现可触发虚拟资本再分配
- 从未直接增减——资本调整完全由排名驱动（即被证明了能力的影子管理更多钱）

#### 2. 紧急配额授予

高置信度信号（原始设计: confidence ≥ 8/10；Phase 2: 基础配额耗尽触发）→ 额外 LLM 调用机会：
- 盈利: 永久 +1 每日配额
- 奖励不可撤销

#### 3. 多样性加成

产生唯一信号（没有其他影子同方向同标的）的影子获得 **1.15x 权重乘数**——其分析在影子生态中的可见度更高。

#### 4. Elite 特权

- 在 Gate 2 中对人类用户可见（ELITE 影子参与）
- 更高的影响力权重
- 方法论进化优先（其洞察被结晶系统优先选为候选）

### 9.2 惩罚体系

#### 1. 回撤暂停

**最高优先级惩罚——无豁免**。

| 影子类型 | 回撤上限 | 触发动作 |
|------|:--:|------|
| Expert | 25% | 立即暂停交易（虚拟） |
| Momentum | 30% | 立即暂停交易 |
| Contrarian | 35-40% | 立即暂停交易 |

不同于其他惩罚，回撤暂停**不可被免疫机制覆盖**。暂停影子仍可产生分析但不执行交易，暂停期间不参与排名。

暂停解除条件：回撤恢复到上限的 50% 以下，或经过至少 5 个交易日。

#### 2. Brier Score 惩罚

高置信度 + 错误预测 = 更大的综合评分惩罚。这特别惩罚"自信但错误"的影子——比"不确定但错误"更严重。

惩罚内置于 V2 综合评分公式中：`Calibration_Score = 0.5*(1-Brier) + 0.5*Resolution`。低 Brier Score → 低 Calibration_Score → 综合评分下降 0.20 权重块的贡献。

#### 3. 多样性折扣（MMC 风格）

与群体过于相似的影子面临权重缩减——它们贡献的边际信息太少。折扣在排名计算时应用。

#### 4. Fade Master 激活率惩罚

Fade Master 是唯一要求强制激活的 Contrarian 影子：

- **激活率 < 50%**: 权重降为 **0**（完全不参与排名）
- 因为 Fade Master 是唯一始终活跃的逆向影子——如果它大部分时间弃权，整个逆向维度就缺失了

#### 5. 配额缩减

连续错误（综合评分在底部 10% 且连续 ≥ 5 天）→ 永久减少每日配额。

#### 6. 紧急配额滥用惩罚

- 1 次亏损 → 3 天观察期
- 亏损（已执行）→ 7 天处罚
- 连续 3 次亏损 → 永久 -1 配额

---

## 10. 进化与选择

### 10.1 Challenger Engine：三阶段淘汰

`challenger_engine.py` 实现了从警告到淘汰的完整管道：

```
Stage 0 (NORMAL) → Stage 1 (WARNING) → Stage 2 (CHALLENGER) → Stage 3 (COMPARISON)
```

#### Stage 1: WARNING（警告）

- **条件**: 连续 **2 个**评估周期处于同类影子池底部 20%
- **动作**: 标记为 WARNING，在生态 UI 中显示警告状态
- **无额外惩罚**——这是一个早期预警信号

#### Stage 2: CHALLENGER（挑战者创建）

- **条件**: 连续 **3 个**评估周期处于底部 20%
- **动作**: 创建一个**秘密挑战者影子**（`shadow_type = "challenger"`）
  - 挑战者对目标影子不可见（不在排名中显示）
  - 挑战者基于目标影子的改良方法论运行（由 Methodology Evolver 生成变体）
  - 挑战者的数据对目标影子完全屏蔽

#### Stage 3: COMPARISON（对比试验）

- **条件**: Stage 2 触发后自动进入
- **试验设计**: **2 周（最少 21 个交易日）**的成对对比
- **统计检验**: 
  - 配对 t 检验（单侧，α = 0.10）
  - Calmar 门: 挑战者 Calmar > 0.3（门值可配置）
- **判决**:
  - `REPLACE_TARGET`: 挑战者日平均收益 > 目标，t 检验显著，Calmar 通过门 → 挑战者替换目标
  - `RESTORE_TARGET`: 目标表现优于挑战者 → 目标恢复 NORMAL 状态
  - `INCONCLUSIVE`: 统计不显著 → 维持 WARNING，延长观察

### 10.2 知识继承

当挑战者替换目标影子时，`knowledge_filter.py` 管理知识转移：

**Learngenes 继承规则**:

| 知识类别 | 传递条件 | 最低验证数 | 说明 |
|------|------|:--:|------|
| **insight** | 跨验证通过 | ≥ 2 | 需要多个独立来源交叉验证 |
| **methodology_component** | 已验证 | ≥ 1 | 方法论组件至少一次确认 |
| **heuristic** | 跨验证通过 | ≥ 2 | 启发规则需要双重验证 |
| **rule** | 已验证 | ≥ 1 | 规则至少一次确认 |
| **verification_count == 0** | **DROP**（丢弃） | — | 未验证的知识不传递 |
| **false_positive_count > 0** | **ISOLATE**（隔离） | — | 已知误报 → 30天独立重验证 |

### 10.3 ACE 风险评分

`KnowledgeFilter` 计算 Adversarial Cascade Effect（对抗级联效应）风险：

```
ACE = 0.50 * unverified_ratio
    + 0.30 * false_positive_ratio
    + 0.20 * (unverified_ratio * cascade_depth / max_depth)
```

- 高 ACE 风险 → 知识继承链应被打断（该影子的知识不值得继承）
- 低 ACE 风险 → 知识可安全传递给新影子

### 10.4 诊断挑战者

在**免疫期**（参见 §11.4），不执行正常的 Challenger 淘汰。而是创建**诊断挑战者**——使用修改后的参数运行，纯粹用于分析目标影子方法论缺陷的数据收集目的。诊断挑战者不会替换目标影子。

### 10.5 Missed Path 机制

`missed_path.py` 追踪被 Gate 1 拒绝的方向的反事实路径：

- **创建**: 当用户在 Gate 1 选择了方向 A，为 B 和 C 方向各创建一个 MissedPath 影子
- **行为**: 只读——跟踪被拒方向的假设表现，不产生交易投票
- **报告**: 30 天后生成 `MissedPathReport`
- **幸存者偏差警告**: 当被拒路径实际上更优 → 生成幸存者偏差警告

### 10.6 Temp Shadow 生命周期

临时影子由 `ShadowMother` 通过事件检测创建和管理：

**事件类型** (E1-E4):
- E1: 央行冲击（实际 vs 预期 ≥ 50bp）
- E2: 地缘事件（VIX 比率 ≥ 1.5 且 delta ≥ 5）
- E3: 波动率冲击（单一资产 24h |收益| ≥ 5σ）
- E4: 关键人事变动（关键词检测）

**生命周期**:
- 创建: 事件检测触发 → `TempShadowLifecycle.create_temp_shadows()`
- 最长寿命: 30 天
- 销毁条件: 事件解决/衰减 → 知识归档 → 通知相关 Expert 影子
- 虚拟资本: $10K-$20K（根据事件影响评分）

---

## 11. 生态治理

### 11.1 生态系统审计师（Ecosystem Auditor）

**关键概念**: `EcosystemAuditor` **不是一个影子**——它是一个生态级别的监控机制，读取所有影子输出但不产生投资分析。

**扫描类别**:

| 扫描类别 | 阈值 | 触发动作 |
|------|:--:|------|
| **方向集中** | 80%+ 的非弃权投票倾向同一方向 | 生成盲点警报 |
| **资产类别忽视** | 任一主要资产类别零覆盖 | 生成覆盖面警报 |
| **方法论收敛** | 多影子在同一标的上 ticker 重复率高 | 判定为趋同 vs 羊群 |
| **未覆盖标的** | 前 20 大市值公司中有未被任何影子分析的 | 补充覆盖面建议 |

**双轨处理**:
- Python 纯计算: 所有指标计算不调用 LLM（零延迟，零成本）
- Pro 解释: 仅当阈值被触发时才调用 DeepSeek Pro 生成可读解释

**输出**: 每日最多 5 条 `EcosystemAlert` 记录，浮动在 Gate 2 界面中供人类审阅。

### 11.2 串通检测器（Collusion Detector）

检测影子是否在无明文协调的情况下一致行动：

**检测规则**:

| 检测条件 | 判定 | 说明 |
|------|------|------|
| ≥ 60% 一致性持续 3 天 + 市场信号强度 > 0.70 | **convergence**（市场驱动） | 是市场特征导致的——无问题 |
| ≥ 60% 一致性持续 3 天 + 市场信号强度 ≤ 0.70 | **herding**（行为羊群） | 是行为偏差——标记并报告 |
| ≥ 10 天连续高一致性 | 升级到制度分析 | 自动触发深度调查 |

**二项检验**: 一致性检验使用二项分布计算 P 值 ~ 4.4e-5（对于纯随机的 ≥ 80% 一致性），确保统计严谨。

一致性阈值从 80% 下调至 60%（Phase I 决策），原因是 Phase I 知识蒸馏可能导致影子方法论自然收敛——更早干预可保护生态多样性。

### 11.3 市场状态检测

四种市场状态的实时分类，每个评估周期自动检测：

| 状态 | 特征 | 受影响影子类型 |
|------|------|------|
| **TRENDING** | 趋势清晰、波动率适中 | Momentum 受益 |
| **TRANSITIONAL** | 趋势转换期、方向不明确 | 所有类型不确定性升高 |
| **RANGE_BOUND** | 区间震荡、VIX < 20、日波幅 < 1.5% | Contrarian 受益，Momentum 免疫 |
| **CHOPPY** | 高波动、无方向、反复假突破 | 所有类型受损 |

### 11.4 免疫机制

**策略-市场错配免疫**: 当市场处于与影子策略原型根本不相容的状态时，该期间的损失不计入淘汰统计：

| 影子类型 | 免疫条件 | 原理 |
|------|------|------|
| **Momentum** | RANGE_BOUND 市场 | 动量策略在无趋势市场中注定失败——不应因此被淘汰 |
| **Contrarian** | TRENDING 市场 | 逆向策略在强趋势中注定失败——不应因此被淘汰 |

免疫机制保护了策略多样性——它防止在市场周期中系统性地淘汰某类策略，从而保留了"当市场转向时最优影子已经存在"的能力。

**免疫期间**: 不启动 Challenger 淘汰流程。改为创建诊断挑战者收集方法论数据。

### 11.5 优雅降级

**组件级降级**: 单个组件故障不影响整个生态。

| 组件 | 故障表现 | 降级模式 |
|------|------|------|
| LLM 网关 | API 不可用 | 影子使用缓存的最新方法论提示，输出标记为 degraded |
| 市场数据 | 数据源失败 | 影子跳过价格依赖分析，使用最后已知快照 |
| 排名引擎 | 计算失败 | 跳过当日排名，延用上次排名 |
| 结晶引擎 | 知识存储失败 | 跳过结晶周期，洞察保留在情节记忆中 |

**系统级 SAFE_MODE**: 当 3 个以上关键组件同时故障 → 触发 SAFE_MODE：
- 影子继续分析但不执行虚拟交易
- 所有输出标记为 `safe_mode: true`
- 系统每小时自动尝试恢复正常模式

### 11.6 Contrarian 敞口上限

为防止逆向影子在极端市场中被集体歼灭：

- **基线敞口**: $100K 总虚拟风险敞口（所有 Contrarian 影子合计）
- **独立激活上限**: 当 4 个 Contrarian 影子独立触发时，上限提升至 $130K
- 每个 Contrarian 单笔最大仓位: 不超过其虚拟资本的 25%

---

## 12. 决策融合（未来/Gate 3 受限）

### 12.1 当前状态：完全隔离

**Gate 3 未通过**。影子分析当前**不参与主流水线的投资决策**。

- `generate_decision()` 函数**不接受影子数据**作为参数
- 影子分析存储在 `shadow_analyses` 表中，仅供生态内部排名
- 没有代码路径连接影子输出到 Decision Card 生成

### 12.2 设计蓝图：7 步数学融合

当 Gate 3 条件满足后，将通过以下 7 步实现影子到主决策的融合（定义在 v3 设计文档中）：

```
Step 1: 归一化 — 所有影子的置信度和方向量化为标准向量
Step 2: 权重加权 — 按类型感知权重进行加权
Step 3: 多样性折扣 — 唯一信号保持高权重，重复信号打折
Step 4: 置信度校准 — Platt Scaling 统一校准不同影子的置信度测量
Step 5: 贝叶斯聚合 — 多源信息贝叶斯融合（Beta-Bernoulli 框架）
Step 6: 冲突检测 — 高分歧自动标记为需要人类裁决
Step 7: 风险预算合成 — 加权后的信号映射到风险预算约束
```

### 12.3 Gate 3 条件

在激活决策融合之前必须满足：
1. 主 AI 流水线端到端完成（10 stages + 3 gates 全部通过）
2. 影子生态稳定运行 ≥ 90 个交易日
3. 挑战者淘汰管道至少完成 3 个完整周期（WARNING → CHALLENGER → COMPARISON）
4. 所有 24 个影子都有 ≥ 60 天职业生涯数据
5. 生态系统审计连续 30 天无 CRITICAL 警报

---

## 13. 生命周期流程图

```
                        ┌─────────────────────┐
                        │   影子被创建/初始化    │
                        │   (ShadowConfig + DB) │
                        └──────────┬──────────┘
                                   │
               ┌───────────────────┼───────────────────┐
               │                   │                   │
          Expert (16)        Momentum (4)        Contrarian (4)
          始终活跃             始终活跃             条件触发
               │                   │                   │
               └───────────────────┼───────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    每日运行周期 (Daily)       │
                    └──────────────┬──────────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           │                       │                       │
    ┌──────▼──────┐        ┌──────▼──────┐        ┌──────▼──────┐
    │  1. 信息获取  │        │  2. 独立分析  │        │ 3. 虚拟交易  │
    │ Scout+市场数据│───────▶│ LLM DeepSeek │───────▶│ VirtualTrade │
    │ 领域过滤     │        │ Pro 调用     │        │ 滑点+折扣    │
    └─────────────┘        └─────────────┘        └──────┬──────┘
                                                         │
                    ┌────────────────────────────────────┘
                    │
           ┌────────▼────────┐
           │  4. 绩效追踪      │
           │  DailySnapshot   │
           │  MPPM/Calmar/Ω   │
           └────────┬────────┘
                    │
    ┌───────────────┼───────────────┐
    │               │               │
┌───▼──────┐  ┌─────▼─────┐  ┌─────▼──────┐
│ 5. 复盘   │  │ 7. 知识结晶│  │ 8. 排名权重 │
│Reflection │  │Crystalize │  │RankingEngine│
│ LLM回顾   │  │双层循环    │  │Composite+HC │
└───┬──────┘  └─────┬─────┘  └─────┬──────┘
    │               │               │
    └───────────────┼───────────────┘
                    │
           ┌────────▼────────┐
           │  9. 奖惩评估      │
           │  Reward/Punish   │
           └────────┬────────┘
                    │
    ┌───────────────┼───────────────┐
    │               │               │
┌───▼────────┐  ┌──▼──────────┐  ┌──▼─────────┐
│ 分级评估     │  │ 10. 进化选择 │  │ 11. 生态审计│
│Elite/Exc/   │  │Challenger   │  │Collusion+  │
│Watch/Endgr  │  │3-Stage      │  │BlindSpot   │
└───┬────────┘  └──┬──────────┘  └──┬─────────┘
    │               │               │
    └───────────────┼───────────────┘
                    │
           ┌────────▼────────┐
           │ 达到淘汰条件?     │
           └───┬─────────┬───┘
               │YES      │NO
               │         │
    ┌──────────▼──┐      │
    │ Challenger  │      │
    │ 2周对比试验  │      │
    └──┬──────┬──┘      │
       │      │         │
   REPLACE  RESTORE    │
       │      │         │
  ┌────▼──┐   │         │
  │影子淘汰│   │         │
  │知识继承│   │         │
  └───────┘   │         │
              │         │
              └────┬────┘
                   │
                   ▼
            ┌─────────────┐
            │ 进入下个周期  │
            │ (次日/下周)   │
            └─────────────┘


特殊路径:
  ┌──────────────┐        ┌──────────────┐
  │ 免疫机制      │        │ 回撤暂停      │
  │ 市场-策略错配  │        │ 回撤 > 上限   │
  │ 暂停淘汰计数  │        │ 立即暂停交易  │
  └──────────────┘        └──────────────┘
```

---

## 14. 奖惩机制汇总表

| 机制 | 类型 | 触发条件 | 效果 | 可豁免? |
|------|:--:|------|------|:--:|
| 虚拟资本分配 | 奖励 | 排名提升 | 更高虚拟资本管理权 | — |
| 紧急配额授予 | 奖励 | 高置信度 / 配额耗尽 + 盈利 | 永久 +1 每日配额 | — |
| 多样性加成 | 奖励 | 唯一信号（无其他影子同向） | 权重 x1.15 | — |
| Elite 特权 | 奖励 | 连续 N 天 ≥ 90th 百分位 | Gate 2 可见 + 影响力加权 | — |
| 回撤暂停 | 惩罚 | 回撤 > 类型上限 | 立即暂停虚拟交易 | **否** |
| Brier 惩罚 | 惩罚 | 高置信度 + 错误预测 | 综合评分下降 | 否 |
| 多样性折扣 | 惩罚 | 与群体高度相似 | 权重缩减 | 否 |
| 激活率惩罚 | 惩罚 | Fade Master 激活率 < 50% | 权重降为 0 | 否 |
| 配额缩减 | 惩罚 | 连续错误 ≥ 5 天 + 底部 10% | 永久减少每日配额 | 否 |
| 紧急配额滥用 | 惩罚 | 紧急调用亏损 | 3-7 天处罚 / 永久 -1 配额 | 否 |
| Stage 1: 警告 | 制度 | 2 周期底部 20% | 警告标记 | 是（免疫期） |
| Stage 2: 挑战者 | 制度 | 3 周期底部 20% | 秘密挑战者创建 | 是（免疫期） |
| Stage 3: 替换 | 制度 | 2 周对比试验失败 | 挑战者替换目标 | 是（免疫期） |
| 免疫保护 | 豁免 | 策略-市场错配 | 该期间损失不计入淘汰 | — |

---

## 15. 关键约束与隔离规则

### 15.1 永久规则（不可覆盖）

1. **影子隔离**: 影子从不读其他影子的当日分析——分析是完全独立的。
2. **决策隔离**: `generate_decision()` 不接受影子数据——没有影子输出路径通向主决策。
3. **数据隔离**: 影子只接收原始新闻+市场数据，从不接触主 AI 分析或 Gate 对话。
4. **Beta 隔离**: Beta 影子排除在排名、串通检测、挑战者流程之外——它们在自己的沙盒中。
5. **挑战者不透明**: 挑战者数据对目标影子不可见，直到试验结束。
6. **回撤暂停无条件**: 任何免疫机制都不能覆盖回撤暂停。
7. **温度锁定**: 每个影子的 LLM 温度由类型决定，运行时不可更改。
8. **配额上限**: 紧急配额不能将每日总配额翻倍以上。

### 15.2 运行规则（可覆盖）

1. **M1 数据完整性**: 所有影子 LLM 调用在网关层注入 M1 协议。
2. **追加状态**: 影子记忆只追加不修改。
3. **并行执行**: 所有影子并发分析（Fade Master 二次通行除外）。
4. **领域过滤**: Expert 影子只分析其领域相关的数据。
5. **全球扫描**: Contrarian 影子扫描全球 15+ 指数。

---

## 16. 时间维度：日/周/月/事件触发

### 16.1 每日

- Scout 新闻采集（~587 篇文章）
- ShadowMother 扫描事件（检测 E1-E4 触发器）
- 所有活跃影子执行独立分析
- 虚拟交易执行 + 持仓更新
- 排名计算 + 成就等级更新
- 每日快照写入 `daily_snapshots`
- 串通检测运行
- 生态系统审计扫描
- 后台调度器触发（结晶周期、反思复盘）

### 16.2 每周

- 挑战者阶段检查（评估连续底部周期计数）
- 方法论衰减检查（decay_factor 更新）
- 平稳期检测（所有影子全面扫描）
- MissedPath 报告生成（30 天期满时）
- Temp Shadow 销毁条件检查

### 16.3 每月

- 方法论报告生成（全影子汇总）
- 知识结晶外循环（显著性门检查）
- 虚拟资本再分配评估
- 配额调整评估（永久增减）
- 免疫状态审查（市场状态重分类）

### 16.4 事件触发（异步）

| 事件 | 触发条件 | 动作 |
|------|------|------|
| E1: 央行冲击 | 利率预期偏离 ≥ 50bp | 创建 Temp Shadow |
| E2: 地缘风险 | VIX 比率 ≥ 1.5 | 创建 Temp Shadow |
| E3: 波动率冲击 | 单一资产 24h \|return\| ≥ 5σ | 创建 Temp Shadow |
| E4: 人事变动 | 关键词命中 | 创建 Temp Shadow |
| 大额盈亏 | 盈亏 > $1,000 或 10% | 触发 Reflection Agent |
| 止损触发 | 止损条件满足 | 虚拟交易退出 + 复盘 |
| 连续亏损 | 连续 3 笔亏损 | 触发深度复盘 |
| CC3+: 阶段升级 | 影子进入 Stage 3 | 启动 2 周对比试验 |
| CC3 结束 | 试验期满 | 判决: 替换/恢复 |
| SAFE_MODE | 3+ 组件故障 | 全系统暂停交易 |

---

## 附录 A: 关键数据表一览

| 表名 | 用途 |
|------|------|
| `shadows` | 影子注册信息（id, type, status, config） |
| `shadow_analyses` | 历史分析记录（ticker, direction, confidence, thesis） |
| `virtual_trades` | 虚拟交易记录（入场/出场/盈亏/滑点） |
| `daily_snapshots` | 每日绩效快照（各指标+排名） |
| `ranking_history` | 排名历史趋势 |
| `integrity_events` | 完整性事件日志 |
| `emergency_quotas` | 紧急配额申请/审批记录 |
| `emergency_quota_state` | 紧急配额状态机持久化 |
| `collusion_flags` | 串通检测标记 |
| `paper_live_gap_state` | 纸面-实盘差距状态 |
| `belief_nodes` | 信念节点（分层记忆） |
| `belief_observations` | 信念观察记录 |
| `belief_retirements` | 已淘汰信念 |
| `methodology_changes` | 方法论变更审计追踪 |
| `shadow_outputs` | 影子原始 LLM 输出 |

## 附录 B: 关键代码路径

| 功能 | 模块 |
|------|------|
| 影子基类 | `shadows/shadow_agent.py` |
| 状态持久化 | `shadows/shadow_state.py` + `shadows/shadow_schema.py` |
| 每日编排 | `shadows/shadow_mother.py` |
| 分层记忆 | `shadows/shadow_memory.py` |
| Expert 影子 | `shadows/expert_shadows.py` |
| Momentum/Contrarian 影子 | `shadows/daredevil_shadows.py` |
| 排名引擎 | `shadows/ranking_engine.py` |
| 挑战者引擎 | `shadows/challenger_engine.py` |
| 串通检测 | `shadows/collusion_detector.py` |
| 生态审计 | `shadows/ecosystem_auditor.py` |
| 知识结晶 | `shadows/crystallization.py` |
| 方法论进化 | `shadows/methodology_evolver.py` |
| 知识过滤 | `shadows/knowledge_filter.py` |
| 紧急配额 | `shadows/emergency_quota.py` |
| 纸面实盘差距 | `shadows/paper_live_gap.py` |
| 反思复盘 | `pipeline/reflection_agent.py` |
| 反事实追踪 | `shadows/missed_path.py` |
| 后台调度 | `shadows/background_scheduler.py` |
| LLM 网关 | `gateway/async_client.py` |
| 配置 | `config/settings.py` |

---

**此文档为影子生态系统的权威参考。所有影子相关设计、开发和调试应以本文档为基准。如与代码实现有出入，以代码实际实现为准（代码为最终真相来源）。**
