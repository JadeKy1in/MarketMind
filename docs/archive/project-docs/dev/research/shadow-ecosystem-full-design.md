# Shadow Ecosystem — Full Design Document

**来源**: Phase B 审查/审计周期文档 | **编译日期**: 2026-05-17

---

## 1. 影子类型总览

7 种类型，各有独立的方法论、行为逻辑、配额等级。

### 1.1 Expert 影子（15 个）

领域专家。每个 Expert 有独特的方法论 prompt、决策框架、风险管理规则。

| # | Shadow ID | 名称 | 决策逻辑要点 | 最大仓位 |
|:---:|------|------|------|:---:|
| 1 | expert:gold:bullion_broker | 黄金经纪人 | 4+/8 指标确认（实际收益率、DXY、央行购金、COT、ETF、SGE）| 15% |
| 2 | expert:crypto:chain_oracle | 链上预言机 | 4+/6 指标确认（交易所流出、MVRV、算力、稳定币、ETF、恐惧贪婪）| 12% |
| 3 | expert:energy:oil_geologist | 石油地质师 | 4+/6 指标确认（EIA库存、钻井数、OPEC合规、PMI、裂解价差、贴水）| 15% |
| 4 | expert:bonds:yield_whisperer | 收益率耳语者 | 4+/5 指标确认（2s10s、Fed定价、盈亏平衡、IG OAS、MOVE）| 20% |
| 5 | expert:vol:vega_trader | 波动率交易员 | 3+/5 指标确认（VIX、SKEW、VVIX、事件日历、跨资产相关性）| 8% |
| 6 | expert:em:frontier_scout | 前沿侦察兵 | 4+/6 指标确认（DXY、EMB OAS、IIF流向、信贷脉冲、EM FX vol、商品）| 12% |
| 7 | expert:tech:silicon_oracle | 硅谷先知 | 4+/6 指标确认（SIA、AI capex、云计算增长、TSMC、SOX、P/E）| 18% |
| 8 | expert:financials:bank_examiner | 银行检查官 | 4+/5 指标确认（2s10s、NIM、坏账拨备、存款流失、CET1、坏账率）| 15% |
| 9 | expert:healthcare:trial_reviewer | 临床试验审查员 | 大型药企需满足多项条件（专利悬崖、Phase 3、IRA暴露、GLP-1）| 14% |
| 10 | expert:consumer:wallet_watcher | 钱包观察者 | 4+/6 指标确认（PCE、可支配收入、信心、储蓄率、工资、汽油占比）| 14% |
| 11 | expert:industrials:factory_floor | 工厂车间 | 4+/6 指标确认（ISM新订单、客户库存、耐用品、Cass、铁路、基建）| 15% |
| 12 | expert:metals:steel_trader | 钢铁交易员 | 4+/5 指标确认（PMI、铜库存、地产竣工、电网投资、TC/RC）| 12% |
| 13 | expert:realestate:reit_analyst | REIT分析师 | 4+/5 指标确认（资本化率利差、FFO、同店NOI、供应、10Y）| 14% |
| 14 | expert:fx:currency_dealer | 外汇交易员 | 4+/6 确认（2Y利差、REER、经常账户、COT、贸易条件、波动率）| 10% |
| 15 | expert:macro:cycle_reader | 周期阅读者 | 四象限体制检测，综合+矛盾发现 | 20% |

### 1.2 Daredevil 影子（7+1 个）

高风险策略，更高的回撤容忍度（35% vs 25%）。

| # | 策略 | 类型 | 说明 |
|:---:|------|------|------|
| 1 | Intraday Direction | 日内方向 | 必须每日选方向，1-3天持仓 |
| 2 | Weekly Trend | 周度趋势 | 识别发展中趋势，5-15天持仓 |
| 3 | Event Hound | 事件猎犬 | 事件驱动交易，1-5天持仓 |
| 4 | Fade Master | 共识逆行者 | 系统化逆拥挤共识 |
| 5 | Rotation Engine | 板块轮动 | 板块ETF轮动，5-20天 |
| 6 | Range-Bound | 震荡市专精 | 环境锁定 |
| 7 | Panic (VIX>30) | 恐慌市专精 | 恐慌环境专家 |
| 8 | Crash Hunter | 崩溃猎人 | 做空偏见，寻找高估/泡沫 |

### 1.3 Catfish（反群体思维→生态审计员）

- **原始设计**: 当>80%影子同向时，强制构造反向论证（温度=0.8）
- **重新设计（Phase B+）**: 生态审计员——交叉影子多样性监控（方向集中度、资产类别忽视、方法论收敛、未覆盖标的），输出≤5个盲点警报

### 1.4 Temp Event（Form C——里程碑触发记录器）

- **不是完整影子**，是轻量级事件记录器
- 30天内仅 3-5 次 Pro 调用
- 检测事件: E1（央行冲击≥50bp）、E2（地缘VIX≥1.5x）、E3（波动率冲击>5σ）、E4（关键人事变动）
- 价值: 为主AI原始分析提供因果链验证证据

### 1.5 MissedPath（反事实追踪）

- 只读，不生成投票，不开仓
- 追踪Gate 1被拒绝的方向B和C
- 30天反事实报告 + 生存偏差警告

### 1.6 Challenger（秘密竞争者）

- 对用户和目标影子完全不可见
- 3阶段淘汰缓冲: 警告→观察+秘密培养→对比裁决
- 2周配对t检验（单侧α=0.10）+ Calmar门槛>0.3

### 1.7 Beta（假设测试）

- **量化版**: 纯Python参数层，零LLM调用，无限并发
- **定性版**: 1-2个完整Pro影子，60天+红方审查

---

## 2. 排名系统

**C_raw = 0.35×P_MPPM + 0.25×P_Calmar + 0.20×P_Omega + 0.20×P_WR**

贝叶斯过拟合剃刀: `h(N,T) = T/(T+8+24×ln(N))`

最终得分: **C_deflated = C_raw × h(N,T)**

百分位计算: n<15参数化 → 15≤n<30混合 → n≥30经验化

---

## 3. 等级系统

| 等级 | 条件 | 连续天数 | Flash配额/日 |
|------|------|:---:|:---:|
| ELITE | >p85 + 缩减夏普>0.8 | 30天 | 7 |
| EXCELLENT | >p70 + 缩减夏普>0.6 | 10天 | 6 |
| NORMAL | 默认起点 | — | 5 |
| WATCH | <p30 或 MDD>30% | 10天 | 3 |
| ENDANGERED | <p15 | 20天 | 1 |

---

## 4. 等级进退规则

- WATCH→NORMAL: p≥p30 连续5天
- ENDANGERED→WATCH: p≥p15 连续10天（不能跳级到NORMAL）
- 单日改善重置ENDANGERED计数器（需20个新连续日才能重新进入）
- 单日下跌重置ELITE计数器（需30个新连续日）
- **滞后效应已正确实现**（Phase B审计确认）

---

## 5. ELITE 影子参与 Gate 2

- ELITE影子与主AI**同时**分析每日新闻（并行，非事后）
- 预计算分析存储在 EliteRegistry 中
- 用户讨论匹配领域关键词或提到影子名字时**唤醒**
- 每影子每Gate 2最多**一次**
- 标记为"影子意见"，**无决策权**

---

## 6. 信息广播规则

**影子接收**: 原始新闻/事实 + 用户原始意见 + 市场数据
**影子不接收**: 主AI的分析/报告（防止锚定偏差）
**影子不能用**: 其他影子的分析输出（分析阶段内）

来源: `phase_b_ideation_notes.md` §1, §4
