# Phase 6 — The Risk Engine: 智能风控与双轨决策引擎 架构蓝图

**文档版本**: v1.0  
**日期**: 2026-05-05  
**状态**: APPROVED  
**上层依赖**: Phase 5 (The Scout) ScoutReport + AssetBasket + CausalAudit  
**设计原则**: 零新增第三方依赖，继承 SPARC 认知循环，严格遵守物理隔离天条

---

## 目录

1. [形象定位：从 Scout 到 Fund Manager 的认知跃迁](#1-形象定位从-scout-到-fund-manager-的认知跃迁)
2. [双轨决策状态机 (Dual-Track Decision FSM)](#2-双轨决策状态机-dual-track-decision-fsm)
3. [轨道 A：战略观望 (Observe & Wait)](#3-轨道-a战略观望-observe--wait)
4. [轨道 B 卖出逻辑：铁证清仓协议 (Sell/Liquidate Protocol)](#4-轨道-b-卖出逻辑铁证清仓协议-sellliquidate-protocol)
5. [轨道 B 买入逻辑：风险收益画像与标的穿透 (Buy & Risk-Reward Profiling)](#5-轨道-b-买入逻辑风险收益画像与标的穿透-buy--risk-reward-profiling)
6. [核心数据结构定义 (Data Schema)](#6-核心数据结构定义-data-schema)
7. [数据流与模块交互图](#7-数据流与模块交互图)
8. [Phase 6 分步开发计划](#8-phase-6-分步开发计划)
9. [风险与降级预案](#9-风险与降级预案)

---

## 1. 形象定位：从 Scout 到 Fund Manager 的认知跃迁

```
Phase 5 (The Scout):               Phase 6 (The Fund Manager):

  "发现机会"         ────────▶      "权衡后下注或不注"
  雷达扫描 (Radar)                  双轨决策 (Dual-Track Decision)
  叙事提取 + 资产映射              风险收益画像 + 仓位建议
  因果检验标记                      铁证卖出 + 触发阈值
  信源三角形校验                    订单结构生成 (Order JSON)
```

**The Fund Manager 不替代 The Scout，而是在 Scout 的资产篮子 + 因果检验之上构建第三层：决策与执行建议层。** Scout 的输出（AssetBasket / Narrative / AuditCheckpoint）成为 Fund Manager 的 **结构化输入**，Fund Manager 在此之上执行定性判定、风险画像、订单生成。

### 与现有架构的整合点

| 上游模块 (Phase 1-5) | 提供给 Phase 6 的数据 | Phase 6 消费方式 |
|---|---|---|
| `scout_types.AssetBasket` | 三维配置篮子 (high_liquidity / low_expense_ratio / high_beta) | 买入逻辑的标的矩阵输入 |
| `scout_types.AuditorCheckpoint` | 因果检验状态 + 失效触发器列表 | 卖出逻辑的铁证交叉验证源 |
| `scout_types.MacroTag` | 宏观叙事标签 + 置信度 | 定性判定 (Track A/B) 的核心输入 |
| `config.asset_universe.ASSET_UNIVERSE` | 7 类叙事 × 3 维篮子 | 标的穿透分析的参考资产池 |
| `account_reader.py` | 当前持仓 + 现金 + buying_power | 订单建议的资金约束 |
| `market_fetcher.py` | 当前价格 | Limit Price / Stop Loss 计算基准 |

---

## 2. 双轨决策状态机 (Dual-Track Decision FSM)

### 2.1 状态转移图

```
                         ┌──────────────────────────┐
                         │  ScoutReport 输入         │
                         │  + AccountState           │
                         │  + AssetBasket            │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │  定性判定引擎              │
                         │  (QualitativeJudgment)    │
                         │                          │
                         │  检查三组条件:             │
                         │  ① 宏观信号一致性          │
                         │  ② 盈亏比 (Reward/Risk)   │
                         │  ③ 市场状态分类            │
                         └────────────┬─────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 │                 ▼
        ┌──────────────────┐         │     ┌──────────────────────┐
        │  轨道 A           │         │     │  轨道 B               │
        │  OBSERVE & WAIT   │         │     │  ACTION & ADJUST      │
        │                  │         │     │                      │
        │  - 矛盾信号       │         │     │  - 信号清晰           │
        │  - 盈亏比<2:1     │         │     │  - 因果检验通过        │
        │  - 无序震荡       │         │     │  - 四维共振 >=3/4     │
        │                  │         │     │                      │
        │  输出:            │         │     │  输出:                │
        │  MarketEvolution  │         │     │  分支判断:            │
        │  Report           │         │     │  ├─ SELL 子轨         │
        │                  │         │     │  └─ BUY 子轨          │
        └──────────────────┘         │     └──────────┬───────────┘
                                     │                │
                                     │       ┌────────┴────────┐
                                     │       ▼                 ▼
                                     │  ┌──────────────┐ ┌──────────────┐
                                     │  │ SELL PROTOCOL│ │ BUY PROTOCOL  │
                                     │  │              │ │              │
                                     │  │ 铁证交叉验证  │ │ 风险收益画像   │
                                     │  │ 清仓比例建议  │ │ 标的穿透分析   │
                                     │  │ 保护性止损    │ │ 三层标签分类   │
                                     │  └──────┬───────┘ └──────┬───────┘
                                     │         │               │
                                     │         └───────┬───────┘
                                     │                 │
                                     │                 ▼
                                     │     ┌──────────────────────┐
                                     │     │  订单结构生成器         │
                                     │     │  (OrderSuggestion)     │
                                     │     │                      │
                                     │     │  Limit Price          │
                                     │     │  Stop Loss            │
                                     │     │  Take Profit          │
                                     │     │  建议仓位占比           │
                                     │     └──────────┬───────────┘
                                     │                │
                                     │                ▼
                                     │     ┌──────────────────────┐
                                     │     │  物理隔离红线           │
                                     │     │  ===================  │
                                     │     │  仅输出 Order JSON    │
                                     │     │  禁止调用券商 API      │
                                     │     │  禁止操作真实账户      │
                                     │     └──────────┬───────────┘
                                     │                │
                                     └────────────────┼──────────────
                                                      │
                                                      ▼
                                          ┌──────────────────────┐
                                          │  output_formatter.py  │
                                          │  (Phase 6 扩展)        │
                                          │                      │
                                          │  最终 Markdown 研报    │
                                          └──────────────────────┘
```

### 2.2 定性判定引擎核心逻辑

定性判定引擎 (`qualitative_judgment.py`) 接收 ScoutReport 的全部上下文，执行三维打分，决定走哪条轨道：

```
判定输入:
  ├─ macro_tags: List[MacroTag]          (Phase 5 宏观叙事标签)
  ├─ asset_basket: AssetBasket           (Phase 5 三维篮子)
  ├─ sentiment_report: SentimentReport  (Phase 4 情绪汇总)
  ├─ account_state: dict                 (Phase 1 账户状态)
  └─ existing_audits: List[AuditorCheckpoint]  (Phase 5 因果检验)

判定逻辑 (三维评分):

维度 1: 宏观信号一致性 (0-100)
  ├─ >= 70: 多个独立信源共振，方向一致 → 信号清晰
  ├─ 40-69: 部分信号矛盾，但方向可辨 → 信号模糊
  └─ < 40: 信号严重矛盾，方向无法判定 → 信号矛盾

维度 2: 盈亏比评估 (Reward/Risk Ratio)
  ├─ >= 3:1: 高盈亏比 → 诱人机会
  ├─ 2:1 ~ 3:1: 适中 → 可接受
  └─ < 2:1: 低盈亏比 → 不值得下注

维度 3: 市场状态分类
  ├─ trending:    趋势明确 (单边上涨/下跌)
  ├─ mean_reverting: 均值回归区域
  ├─ choppy:      无序震荡 (低波动率 + 窄幅横盘)
  └─ crisis:      危机模式 (VIX 飙升, 流动性枯竭)

判定规则表:

| 信号一致性 | 盈亏比 | 市场状态 | 判定结果 | 轨道 |
|-----------|--------|---------|---------|------|
| >= 70 | >= 3:1 | trending/mean_reverting | STRONG_SIGNAL | B (BUY/SELL) |
| >= 70 | 2:1~3:1 | trending | MODERATE_SIGNAL | B (BUY/SELL) |
| >= 70 | < 2:1 | any | WEAK_OPPORTUNITY | A (OBSERVE) |
| 40-69 | >= 2:1 | trending | AMBIGUOUS | A (OBSERVE) |
| 40-69 | < 2:1 | any | AMBIGUOUS | A (OBSERVE) |
| < 40 | any | any | CONTRADICTION | A (OBSERVE) |
| any | any | choppy | SIDEWAYS | A (OBSERVE) |
| any | any | crisis | CRISIS_MODE | A (OBSERVE) |
```

---

## 3. 轨道 A: 战略观望 (Observe & Wait)

### 3.1 触发条件汇总

轨道 A 在以下任一条件满足时激活：

| 场景代号 | 条件 | 含义 |
|---------|------|------|
| CONTRADICTION | 宏观信号一致性 < 40 | 多空信号严重矛盾，无法判定方向 |
| WEAK_OPPORTUNITY | 盈亏比 < 2:1 | 即使方向正确，潜在收益不足以覆盖风险 |
| SIDEWAYS | 市场状态 = choppy | 低波动率窄幅震荡，无方向性机会 |
| CRISIS_MODE | 市场状态 = crisis | VIX 飙升/流动性枯竭，不适合新开仓 |
| AMBIGUOUS | 信号一致性 40-69 且盈亏比 < 2:1 | 模糊信号组合 |

### 3.2 输出: MarketEvolutionReport (市场演变推演)

轨道 A 不输出操作建议，但必须输出一份《市场演变推演》报告，内容包含：

```
MarketEvolutionReport:
  ├─ status: "OBSERVE"
  ├─ reason_for_observe: str                # 为何不行动 (引用具体触发条件)
  ├─ dark_currents: List[NarrativeThread]   # 当前市场暗流趋势
  │   └─ 每条暗流包含:
  │       ├─ narrative: str                 # 趋势描述
  │       ├─ evidence_chain: List[str]      # 支撑证据链
  │       └─ confidence: float              # 置信度
  ├─ watch_points: List[WatchPoint]         # 重点关注方向
  │   └─ 每个观察点包含:
  │       ├─ direction: str                 # 关注方向 (e.g. "rate_cut", "inflation")
  │       ├─ current_value: float           # 当前值
  │       ├─ activation_threshold: float    # 激活阈值
  │       ├─ activation_operator: str       # "gt" | "lt" | "cross_above" | "cross_below"
  │       └─ activated_action: str          # 阈值触发后的预设动作 (e.g. "激活做多美债逻辑")
  └─ review_timeline: str                   # 建议复审时间 (e.g. "2026-05-08 after CPI release")
```

### 3.3 WatchPoint 示例

```
若 CPI 跌破 2.8% → 激活做多美债逻辑 (TLT / VGLT)
若 VIX 回落至 18 以下 → 解除危机模式，重新评估风险资产
若非农 < 10万 → 激活衰退避险逻辑 (GLD / USFR)
若原油 WTI 突破 $85 → 激活大宗商品超级周期逻辑 (DBC / XLE)
```

---

## 4. 轨道 B 卖出逻辑：铁证清仓协议 (Sell/Liquidate Protocol)

### 4.1 设计哲学

> **"买入需要理由，卖出需要铁证。"**

卖出逻辑严格约束：每一条卖出建议必须附带交叉验证报告，明确指出触发源和证据链。

### 4.2 卖出触发条件分类

```
卖出触发源 (SellTriggerSource):

类型 A — 宏观逻辑失效 (Macro Invalidation):
  ├─ 原买入逻辑的因果检验被标记为 INVALIDATED
  ├─ 宏观数据反转 (e.g. 原本押注通胀下行，但 CPI 连续 2 个月超预期)
  └─ 政策路径突变 (e.g. 原本押注降息，但 Fed 暗示加息)

类型 B — 技术破位 (Technical Breakdown):
  ├─ 价格跌破关键移动均线 (60日均线 / 200日均线)
  ├─ 周线 MACD 顶背离确认
  ├─ 关键支撑位放量击穿
  └─ VIX 恐慌飙升触发仓位保护

类型 C — 仓位再平衡 (Portfolio Rebalancing):
  ├─ 单标的浮盈超过总仓位 30%，触发再平衡
  ├─ 相关性风险：两笔持仓高度正相关，需减持其一
  └─ 现金储备低于安全阈值 (e.g. < 20%)
```

### 4.3 输出: LiquidationReport (清仓报告)

```
LiquidationReport:
  ├─ action: "SELL"
  ├─ position_to_close: str               # 需要清仓/减仓的持仓 Ticker
  ├─ current_shares: int                  # 当前持有股数
  ├─ suggested_liquidation_ratio: float   # 建议清仓比例 (0.0 ~ 1.0)
  │                                       # 1.0 = 全部清仓, 0.5 = 减半
  ├─ trigger_source: SellTriggerSource    # 触发源类型
  ├─ trigger_detail:                      # 触发详情 (交叉验证)
  │   ├─ macro_trigger: Optional[str]     # 宏观触发事件 (e.g. "NFP: 320K vs expected 180K")
  │   ├─ technical_trigger: Optional[str] # 技术触发条件 (e.g. "周线收盘跌破 60MA @ $142.30")
  │   └─ evidence_chain: List[str]        # 支撑证据链 (至少 2 条独立证据)
  ├─ protective_stop: Optional[float]     # 保护性止损限价 (若不全部清仓)
  ├─ reason_narrative: str                # 人类可读的卖出理由 (100-300 字)
  └─ causal_audit_ref: str                # 引用的因果检验 checkpoint_id
```

### 4.4 交叉验证规则

- 卖出触发必须至少有 **2 条独立证据** 支撑
- 宏观逻辑失效 (类型 A) 至少需要 1 条宏观数据 + 1 条技术确认
- 技术破位 (类型 B) 至少需要 1 条价格信号 + 1 条成交量或动量确认
- 仓位再平衡 (类型 C) 至少需要资金管理模块的数值计算验证

---

## 5. 轨道 B 买入逻辑：风险收益画像与标的穿透 (Buy & Risk-Reward Profiling)

### 5.1 两层剖析架构

```
输入: ScoutReport.narrative + AssetBasket + AccountState
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  第一层: 机会整体方向画像                      │
│  (Opportunity Profiling)                     │
│                                              │
│  输出标签 (三选一):                           │
│  ├─ ASYMMETRIC:   低风险/高回报               │
│  ├─ SPECULATIVE:  高风险/高回报               │
│  └─ TREND_FOLLOW: 中等风险/中等回报           │
│                                              │
│  附加字段:                                    │
│  ├─ risk_reward_ratio: float                 │
│  ├─ expected_upside_pct: float               │
│  ├─ expected_downside_pct: float             │
│  ├─ safety_margin_assessment: str            │
│  └─ confidence_rating: "HIGH"|"MEDIUM"|"LOW" │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│  第二层: 配置标的穿透分析                      │
│  (Asset Class Penetration)                   │
│                                              │
│  针对选定方向，输出标的矩阵:                    │
│  ├─ 核心推荐 (直接挂钩现货/期货 ETF)            │
│  ├─ 上游杠杆 (产业链上游公司 - 运营杠杆)         │
│  └─ 下游/关联 (产业链下游或相关设备)             │
│                                              │
│  每个标的附带:                                │
│  ├─ 当前价格                                   │
│  ├─ 建议仓位占比 (% of buying_power)          │
│  ├─ Limit Price (建议限价)                     │
│  ├─ Stop Loss (止损价)                        │
│  └─ Take Profit (止盈价)                      │
└──────────────────────────────────────────────┘
```

### 5.2 第一层详细：机会画像 (RiskProfile)

#### ASYMMETRIC — 低风险/高回报 (非对称机会)

```
触发条件:
  ├─ 市场极度恐慌 (VIX > 35)
  ├─ 利空出尽 (负面消息已被完全定价)
  ├─ 安全边际 > 30% (当前价格低于内在价值估算 > 30%)
  └─ 盈亏比 > 5:1

标签特征:
  ├─ 下档有限 (有硬底支撑, 如资产净值/国家兜底)
  ├─ 上档巨大 (情绪修复/政策转向带来的弹性)
  └─ 典型场景: 2020.03 流动性危机后的反弹, 2022.10 加息恐慌见顶
```

#### SPECULATIVE — 高风险/高回报 (投机催化剂)

```
触发条件:
  ├─ 重大会议前夕单边押注 (FOMC / OPEC+)
  ├─ 短线逼空行情 (高 Short Interest)
  ├─ 新兴技术概念炒作 (AI/量子)
  └─ 盈亏比 > 3:1 但下档不明确

标签特征:
  ├─ 高波动率 (Beta > 2.0)
  ├─ 时间窗口有限 (事件驱动)
  └─ 典型场景: FOMC 前押注利率决议, 财报季超预期博弈
```

#### TREND_FOLLOWING — 中等风险/中等回报 (趋势跟随)

```
触发条件:
  ├─ 已有确定性的宏观趋势 (如降息周期已启动)
  ├─ 四维共振 >= 3/4
  ├─ 技术面处于上升趋势 (周线 MACD 金叉, > 60MA)
  └─ 盈亏比 > 2:1

标签特征:
  ├─ 顺应已形成的宏观趋势
  ├─ 持仓周期较长 (数月)
  └─ 典型场景: 降息周期中的稳健做多, 商品超级周期中的趋势跟踪
```

### 5.3 第二层详细：标的穿透分析 (Asset Penetration)

以"看多大宗商品"为例，系统生成以下标的矩阵：

```
方向: 大宗商品超级周期 (commodity_supercycle)
风险画像: TREND_FOLLOWING

标的矩阵:

┌──────────────────────────────────────────────────────────────┐
│ 层 1: 核心推荐 — 直接挂钩现货/期货 ETF (跟踪紧密)               │
├──────────┬──────────┬──────────┬──────────┬──────────────────┤
│ Ticker   │ 方向      │ 仓位占比  │ Limit    │ Stop / TP        │
├──────────┼──────────┼──────────┼──────────┼──────────────────┤
│ DBC      │ BUY      │ 15%      │ $23.50   │ SL: $21.15 / TP: $28.00 │
│ PDBC     │ BUY      │ 10%      │ $14.80   │ SL: $13.32 / TP: $17.76 │
│ GLD      │ BUY      │ 10%      │ $215.00  │ SL: $202.00 / TP: $238.00 │
└──────────┴──────────┴──────────┴──────────┴──────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ 层 2: 上游杠杆 — 产业链上游公司 (运营杠杆, 弹性更大)            │
├──────────┬──────────┬──────────┬──────────┬──────────────────┤
│ Ticker   │ 方向      │ 仓位占比  │ Limit    │ Stop / TP        │
├──────────┼──────────┼──────────┼──────────┼──────────────────┤
│ XLE      │ BUY      │ 8%       │ $92.00   │ SL: $85.50 / TP: $106.00 │
│ GDX      │ BUY      │ 5%       │ $38.00   │ SL: $34.50 / TP: $46.00  │
│ ERX      │ BUY      │ 3%       │ $62.00   │ SL: $53.00 / TP: $80.00  │(高 Beta 警告)
└──────────┴──────────┴──────────┴──────────┴──────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ 层 3: 下游/关联 — 相关设备或服务提供商                          │
├──────────┬──────────┬──────────┬──────────┬──────────────────┤
│ Ticker   │ 方向      │ 仓位占比  │ Limit    │ Stop / TP        │
├──────────┼──────────┼──────────┼──────────┼──────────────────┤
│ VDE      │ BUY      │ 5%       │ $135.00  │ SL: $124.00 / TP: $155.00 │
└──────────┴──────────┴──────────┴──────────┴──────────────────┘

总计建议仓位: 56% of buying_power
建议保留现金: 44% (高于 20% 安全阈值)
```

### 5.4 仓位计算公式

```
单标的建议仓位占比 = BaseWeight × ConfidenceAdjust × RiskProfileMultiplier × CorrelationPenalty

BaseWeight:
  - 核心推荐层: 10% ~ 15%
  - 上游杠杆层: 3% ~ 8%
  - 下游关联层: 3% ~ 5%

ConfidenceAdjust:
  - HIGH confidence:   × 1.0
  - MEDIUM confidence: × 0.7
  - LOW confidence:    × 0.4

RiskProfileMultiplier:
  - ASYMMETRIC:        × 1.2 (高确定性, 可适度加仓)
  - SPECULATIVE:       × 0.5 (高不确定性, 严格控仓)
  - TREND_FOLLOWING:   × 1.0 (标准仓位)

CorrelationPenalty:
  - 与现有持仓相关性 > 0.8: × 0.5
  - 与现有持仓相关性 > 0.6: × 0.75
  - 否则: × 1.0
```

---

## 6. 核心数据结构定义 (Data Schema)

### 6.1 RiskProfile (机会整体方向画像)

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class RiskProfileLabel(Enum):
    ASYMMETRIC = "asymmetric"           # 低风险/高回报
    SPECULATIVE = "speculative"         # 高风险/高回报
    TREND_FOLLOWING = "trend_following" # 中等风险/中等回报

@dataclass
class RiskProfile:
    """第一层剖析输出: 机会整体方向画像"""
    profile_id: str
    narrative_ref: str                  # 引用的 MacroTag.narrative
    label: RiskProfileLabel
    risk_reward_ratio: float            # 盈亏比 (e.g. 3.5 表示 3.5:1)
    expected_upside_pct: float          # 预期上涨百分比
    expected_downside_pct: float        # 预期下跌百分比
    safety_margin_pct: float            # 安全边际百分比
    confidence_rating: str              # "HIGH" | "MEDIUM" | "LOW"
    rationale: str                      # 人类可读的画像依据 (100-300 字)
    triggering_conditions: List[str]    # 触发此画像的具体条件列表
    risk_warnings: List[str]            # 风险警示列表
    time_horizon: str                   # 预期持仓周期 (e.g. "3-6 months")
```

### 6.2 AssetPenetrationItem (单个标的穿透分析)

```python
@dataclass
class AssetPenetrationItem:
    """单个标的的穿透分析条目"""
    ticker: str
    direction: str                      # "BUY" | "SELL"
    layer: str                          # "core" | "upstream_leverage" | "downstream_related"
    layer_rationale: str                # 为何归入此层 (e.g. "直接挂钩黄金现货 ETF, 跟踪紧密")
    suggested_weight_pct: float         # 建议仓位占比 (% of buying_power)
    current_price: Optional[float]      # 当前市价
    limit_price: Optional[float]        # 建议限价单价格
    stop_loss: Optional[float]          # 建议止损价
    take_profit: Optional[float]        # 建议止盈价
    expected_return_pct: Optional[float] # 预期回报率
    beta: Optional[float]               # Beta 系数
    correlation_warning: Optional[str]  # 相关性警告
    risk_note: Optional[str]            # 特殊风险提示
```

### 6.3 OrderSuggestion (完整订单建议)

```python
@dataclass
class OrderSuggestion:
    """轨道 B 的最终输出: 完整订单建议结构"""
    order_id: str
    created_at: str                     # ISO 时间戳
    decision_track: str                 # "ACTION_AND_ADJUST"
    action_type: str                    # "BUY" | "SELL" | "MIXED"

    # 风险画像 (第一层)
    risk_profile: RiskProfile

    # 标的穿透分析 (第二层)
    penetration_items: List[AssetPenetrationItem]

    # 资金管理汇总
    total_notional_commitment: float    # 建议总投入金额
    cash_reserve_after: float           # 操作后预估现金余额
    cash_reserve_pct: float             # 操作后现金占比
    account_state_ref: str              # 引用的账户状态快照 (e.g. "2026-05-05")

    # 因果审计引用
    causal_audit_refs: List[str]        # 引用的 AuditorCheckpoint ID 列表

    # 物理隔离标记 (系统级约束)
    execution_disclaimer: str           # 固定文案: "THEORETICAL ONLY - NO BROKERAGE API CONNECTED"
```

### 6.4 MarketEvolutionReport (轨道 A 输出)

```python
@dataclass
class WatchPoint:
    """一个观察点定义"""
    direction: str                      # 关注方向 (e.g. "cpi_trend")
    description: str                    # 人类可读描述
    current_value: float                # 当前指标值
    activation_threshold: float         # 激活阈值
    activation_operator: str            # "gt" | "lt" | "cross_above" | "cross_below"
    activated_action: str               # 触发后的预设动作描述
    data_source: str                    # 数据来源 (e.g. "BLS CPI release")

@dataclass
class NarrativeThread:
    """一条暗流趋势"""
    narrative: str                      # 趋势描述
    evidence_chain: List[str]           # 支撑证据链
    confidence: float                   # 置信度

@dataclass
class MarketEvolutionReport:
    """轨道 A 输出: 市场演变推演报告"""
    report_id: str
    created_at: str
    decision_track: str                 # "OBSERVE_AND_WAIT"
    trigger_scenario: str               # 触发场景代号 (CONTRADICTION/WEAK_OPPORTUNITY/...)
    reason_for_observe: str             # 不行动理由 (200 字)
    dark_currents: List[NarrativeThread] # 当前暗流趋势 (至少 1 条)
    watch_points: List[WatchPoint]       # 观察点列表 (至少 2 个)
    review_timeline: str                 # 建议复审时间
```

### 6.5 定性判定引擎的数据契约

```python
@dataclass
class QualitativeJudgment:
    """定性判定引擎的输出"""
    judgment_id: str
    timestamp: str

    # 三维打分明细
    signal_coherence_score: float       # 宏观信号一致性 (0-100)
    reward_risk_ratio: float            # 盈亏比
    market_regime: str                  # "trending" | "mean_reverting" | "choppy" | "crisis"

    # 判定结果
    decision_track: str                 # "OBSERVE_AND_WAIT" | "ACTION_AND_ADJUST"
    track_confidence: float             # 判定置信度
    decision_rationale: str             # 判定依据 (引用判定规则表)

    # 如果是 ACTION_AND_ADJUST, 分支建议
    suggested_subtrack: Optional[str]   # "BUY" | "SELL" | "MIXED"

    # 如果是 OBSERVE_AND_WAIT, 场景代号
    observe_scenario: Optional[str]     # "CONTRADICTION" | "WEAK_OPPORTUNITY" | ...
```

---

## 7. 数据流与模块交互图

```
                       Phase 5 ScoutReport
                       + AccountState
                            │
                            ▼
              ┌─────────────────────────┐
              │  dual_track_router.py    │  ← Phase 6 新模块: 双轨路由器
              │  (QualitativeJudgment)   │
              └───────────┬─────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               │               ▼
┌─────────────────┐       │    ┌─────────────────────┐
│ 轨道 A           │       │    │ 轨道 B               │
│ observe_wait.py  │       │    │ action_adjust.py     │
│                 │       │    │                     │
│ 输入:           │       │    │ 输入:               │
│ - Narratives    │       │    │ - AssetBasket       │
│ - 矛盾信号       │       │    │ - AuditCheckpoints │
│                 │       │    │ - AccountState      │
│ 输出:           │       │    │                     │
│ - MarketEvolut- │       │    │ 输出:               │
│   ionReport     │       │    │ - QualitativeJudg.  │
│                 │       │    │   (subtrack)        │
└────────┬────────┘       │    └──────────┬──────────┘
         │                │               │
         │                │    ┌──────────┴──────────┐
         │                │    │                     │
         │                │    ▼                     ▼
         │                │ ┌──────────────┐ ┌──────────────┐
         │                │ │ sell_proto-  │ │ buy_proto-   │
         │                │ │ col.py       │ │ col.py       │
         │                │ │              │ │              │
         │                │ │ 输出:        │ │ 输出:        │
         │                │ │ Liquidation- │ │ RiskProfile  │
         │                │ │ Report       │ │ + AssetPene- │
         │                │ │              │ │ trationItems │
         │                │ └──────┬───────┘ └──────┬───────┘
         │                │        │               │
         │                │        └───────┬───────┘
         │                │                │
         │                │                ▼
         │                │    ┌──────────────────────┐
         │                │    │ order_builder.py      │
         │                │    │                      │
         │                │    │ 输入:                │
         │                │    │ - RiskProfile        │
         │                │    │ - AssetPenetrationItems │
         │                │    │ - LiquidationReport  │
         │                │    │ - AccountState       │
         │                │    │                      │
         │                │    │ 输出:                │
         │                │    │ - OrderSuggestion    │
         │                │    │   (纯 JSON, 物理隔离) │
         │                │    └──────────┬───────────┘
         │                │               │
         │                │               │
         └────────────────┼───────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │  output_formatter.py     │  ← Phase 6 扩展
              │  (新增轨道 A/B 渲染逻辑) │
              │                         │
              │  轨道 A:                │
              │   - MarketEvolution      │
              │     Report 板块          │
              │                         │
              │  轨道 B:                │
              │   - RiskProfile 板块     │
              │   - AssetPenetration     │
              │     标的矩阵表           │
              │   - OrderSuggestion      │
              │     订单摘要             │
              │   - 物理隔离声明          │
              └───────────┬─────────────┘
                          │
                          ▼
                  Final Markdown 研报
                  (存入 memory-bank/ 存档)
```

###