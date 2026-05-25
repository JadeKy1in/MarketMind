# Shadow Ecosystem Type Redesign v2 — 策略原型分类重构

**Status**: DRAFT — PENDING RED TEAM REVIEW
**Date**: 2026-05-20
**Trigger**: Fade Master 敢死队重设计 + 16E+8D 类型确认
**Research Basis**: 2-agent parallel web research (see §1)

---

## 1. Executive Summary

### 1.1 当前问题

当前影子分类按**风险水平**划分（Expert 低风险 vs Daredevil 高风险），这是一个结构性错误：

| 问题 | 详情 |
|------|------|
| **分类维度错误** | 行业标准（Millennium/Citadel）、学术共识（Jegadeesh & Titman 1993, DeBondt & Thaler 1985）均按**策略原型**分类，不按风险水平。风险是正交约束层，不是组织维度。 |
| **Fade Master 被误分类** | 逆向策略与动量策略相关性为 **-35%**（Balvers, Wu & Gilliland 2000）。放在同一排名桶中，趋势市场必然压制逆向影子，这不是公平竞争——是结构性压制。 |
| **路由器无信号** | "Daredevil" 标签告知风险偏好，对"何时激活、分配多少权重"的路由决策提供零信号。"Contrarian" 标签直接告知：共识极端时激活。 |
| **绩效基准混乱** | 逆向策略应参照均值回归基准、长周期评估（3-5年 DeBondt-Thaler）。动量策略应参照趋势跟踪基准、中短周期评估（1-12月）。同一桶下两者都用不对的基准。 |

### 1.2 解决方案

将当前的 **Expert / Daredevil 二元分类**（按风险）重构为 **策略原型四分类**（按策略类型）：

| 旧分类 | 新分类 | 数量 | 说明 |
|--------|--------|:---:|------|
| Expert (16) | **Fundamental** 基本面/领域 | 16 | 不变 |
| Daredevil (8) → | **Momentum** 动量/趋势 | 4 | Intraday, Trend, Event Hound, Rotation |
| | **Contrarian** 逆向/敢死队 | 4 | Fade Master, Sideways, Panic, Crash Hunter |
| — | **Event-Driven** 事件/尾部 | — | 暂空（Crash Hunter 已归入 Contrarian） |

**24个影子总数不变。只改分类体系。**

### 1.3 关键决策

1. **Contrarian"敢死队"** 4 成员：Fade Master (每日主动) + Sideways Scout (低波环境触发) + Vol Surfer (恐慌环境触发) + Crash Hunter (崩盘信号触发)
2. 四个 Contrarian 共享同一个策略 DNA：**均值回归假设 + 逆向入场 + 极限位置交易**。唯一差异是触发条件。
3. Crash Hunter 归入 Contrarian 而非单独 Event-Driven 类型——它逆向押注泡沫破裂，本质是极端版本的逆向策略。

---

## 2. Research Basis

### 2.1 行业实践

| 来源 | 关键发现 |
|------|------|
| Millennium 330-pod 架构 | 按 Equities/FI&Macro/Commodities/Quant/Credit 分桶，不按风险水平 |
| Citadel 5-bucket | Equities/FI&Macro/Credit/Commodities/Quant Strategies |
| HFR Hedge Fund Strategy Classification | Equity Hedge / Event-Driven / Macro / Relative Value 四类标准行业分类 |
| Pod-shop isolation model | 每个 pod 有独立 risk envelope（5%回撤→资本减半，7.5%→终止），风险限额由中央风控引擎统一施加 |
| QVR Advisors reverse dispersion trade | 逆向策略需要**结构性隔离**——独立风险预算、独立 P&L、独立基准 |

**结论**: 按策略类型组织是行业标准。风险是正交约束。

### 2.2 学术共识

| 来源 | 关键发现 |
|------|------|
| Jegadeesh & Titman (1993) | 动量策略利润来源于信息延迟扩散（反应不足） |
| DeBondt & Thaler (1985) | 逆向策略利润来源于过度反应修正 |
| Conrad & Kaul (1998) | 动量和逆向策略对不同的收益驱动因素做出反应——不应混合评估 |
| Balvers, Wu & Gilliland (2000) | 动量-逆向组合策略比纯策略每月超额收益 1.1-1.7%，两策略相关性 -35% |
| ArchetypeTrader (AAAI 2026) | VQ-VAE 学习的策略原型聚类为 momentum-like / mean-reversion-like / event-driven 三类，验证了人工分类法 |
| AlphaMix (KDD 2023) | "按需路由器"必须先知道每个专家的策略类型，才能决定何时激活。策略标签是路由决策的必需信号 |
| MARS (AAAI 2026) | 异构风险偏好 Agent + Safety-Critic 配对显著优于同质 Agent 池 |

**结论**: 动量与逆向是本质不同的策略原型。按策略原型分类有坚实的学术基础。

### 2.3 本系统独特发现

| 来源 | 关键发现 |
|------|------|
| Telescope BEAM Benchmark (2025) | Frontier 模型在市场压力期间收敛到 1-12 度分离角——Collusion Detector 解决真实问题 |
| Numerai MMC metric | 独特信号比准确信号更有价值——多样性折扣是排名系统的必要组件 |
| TradeTrap (Dec 2025) | 管道组件的小扰动可传播并引发投资组合崩溃——需要优雅降级规范 |

---

## 3. New Shadow Type Architecture

### 3.1 类型定义

```python
# shadow_data_types.py — _VALID_TYPES 更新
_VALID_TYPES = {
    "expert",        # 领域专家（16），基本面/宏观分析
    "momentum",      # 动量/趋势（4），方向性追击
    "contrarian",    # 逆向/敢死队（4），共识反转 + 尾部对冲
    "temp_event",    # 事件驱动的临时影子（动态）
    "challenger",    # 挑战者影子（动态）
    "missed_path",   # 反事实追踪（动态）
    "beta",          # 实验性影子（隔离）
}
```

移除: `"daredevil"`（拆分入 momentum + contrarian）, `"catfish"`（已废弃）

### 3.2 影子分配

#### Fundamental (16) — 始终活跃

```
expert:gold:bullion_broker       贵金属       $50K   τ=0.30
expert:crypto:chain_oracle       加密货币     $45K   τ=0.35
expert:energy:oil_geologist      能源         $50K   τ=0.30
expert:bonds:yield_whisperer     债券/利率    $55K   τ=0.30
expert:vol:vega_trader           波动率       $40K   τ=0.40
expert:em:frontier_scout         新兴市场     $45K   τ=0.35
expert:tech:silicon_oracle       科技         $50K   τ=0.30
expert:financials:bank_examiner  金融         $48K   τ=0.30
expert:healthcare:trial_reviewer 医疗         $48K   τ=0.30
expert:consumer:wallet_watcher   消费         $46K   τ=0.30
expert:industrials:factory_floor 工业         $48K   τ=0.30
expert:metals:steel_trader       工业金属     $42K   τ=0.35
expert:agriculture:harvest_seer  农产品       $42K   τ=0.35
expert:realestate:reit_analyst   房地产       $48K   τ=0.30
expert:fx:currency_dealer        外汇         $44K   τ=0.35
expert:macro:cycle_reader        宏观/跨资产  $60K   τ=0.30
```

**特征**: 低温度 (0.30-0.40) / 领域关键词过滤 / 结构化投票 / 基线层

#### Momentum (4) — 趋势市场活跃

```
momentum:intraday:scalper        日内动量      $25K   τ=0.50   持有1-3天
momentum:weekly:trend_rider      周线趋势      $30K   τ=0.40   持有5-15天
momentum:event:news_hound        事件动量      $25K   τ=0.45   持有1-5天
momentum:sector:rotation_engine  板块轮动      $30K   τ=0.40   持有5-20天
```

**特征**: 中温度 / 突破追入 / 方向性押注 / 中短周期
**激活逻辑**: 始终活跃（每日寻找动量机会），无环境锁定
**评估窗口**: 60-90天（短周期）
**基准**: 趋势跟踪指数 / 相对强度基准

#### Contrarian "敢死队" (4) — 极限位置逆向

```
contrarian:consensus:fade_master       共识逆向      $20K   τ=0.55   每日激活
contrarian:range_bound:sideways_scout  区间逆向      $25K   τ=0.45   VIX<20 触发
contrarian:panic:vol_surfer            恐慌逆向      $30K   τ=0.60   VIX>30 触发
contrarian:crash:hunter                泡沫逆向      $30K   τ=0.50   2+崩盘信号触发
```

**特征**: 中高温度 / 极限位置逆向入场 / 均值回归假设 / 长周期
**激活逻辑**: 每个影子有独立触发条件（见 §4.2）
**评估窗口**: 180-365天（长周期，DeBondt-Thaler 框架）
**基准**: 均值回归指数 / 反转因子基准
**特殊保护**: 趋势市场中的损失不触发淘汰（见 §6.3）

### 3.3 类型对比

| 维度 | Fundamental | Momentum | Contrarian |
|------|:---:|:---:|:---:|
| 核心假设 | 领域专业知识 | 趋势延续（正反馈） | 均值回归（负反馈） |
| 入场风格 | 基本面估值 | 突破追入（stop-entry） | 极限逆向（limit-entry） |
| 典型持有期 | 可变 | 1-20天 | 3-10天（可更长） |
| 温度范围 | 0.30-0.40 | 0.40-0.50 | 0.45-0.60 |
| 评估窗口 | 90天 | 60-90天 | 180-365天 |
| 风险管理 | 回撤上限 25% | 回撤上限 30% | 回撤上限 35-40% |
| 最低交易数 | 5 | 50 | 50 |
| 与 Momentum 相关性 | ~0.0-0.2 | 1.0 (self) | **-0.35** |
| 决策影响 | 无直接参与 | 无直接参与 | 无直接参与 |

---

## 4. Contrarian "敢死队" Detailed Design

### 4.1 共同 DNA

四个 Contrarian 影子共享以下核心特征：

1. **均值回归假设**: 价格最终回归均衡，极端状态不可持续
2. **逆向入场**: 在共识最拥挤/恐慌最极端时入场，与主流方向相反
3. **极限位置触发**: 每个影子定义了"市场处于极端状态"的具体条件
4. **长周期评估**: 逆向策略需要更长时间验证（180-365天），短期表现不佳是结构性预期
5. **高波动容忍**: 逆向入场意味着浮亏是常态，35-40%回撤上限

### 4.2 四个成员的精确定义

#### C1: Fade Master — 共识逆向（每日激活）

**shadow_id**: `contrarian:consensus:fade_master`
**触发条件**: 无环境限制，每日激活
**信号源**:
- AAII 散户情绪调查（牛熊比 >2.0 或 <0.5）
- 16 Expert 影子方向一致率 >75%（同向共识极端）
- Put/Call 比率极端值（<0.6 或 >1.5）
- COT 报告投机净多/空仓处于 2 年极端
- 社交媒体情绪峰值（检测到 ≥3 个 Expert 影子在同一方向）

**决策逻辑**:
```
IF consensus_direction = "long" AND consensus_agreement > 75%:
    → SHORT strongest consensus ticker(s)
IF consensus_direction = "short" AND consensus_agreement > 75%:
    → LONG most hated ticker(s)
IF consensus_agreement < 75%:
    → 正常分析，可能 ABSTAIN（不强制每日交易——与动量影子不同）
```

**风险参数**:
- Virtual capital: $20,000
- Max positions: 4 (可以分散逆向押注)
- Max drawdown limit: 35%
- 单笔最大仓位: 10%
- 止损: 共识方向被价格确认（而非被情绪确认）→ 退出

**方法论 Prompt 关键要素**:
```
你是 Fade Master，敢死队核心成员。你的任务：在共识最拥挤时押注反转。
当 >75% 的 Expert 影子同意一个方向时，你站在对面。
你的优势：共识极端几乎总是错误的——不是立刻错，但最终错。
关键信号：AAII 极端、Put/Call 极端、COT 极端、Expert 影子一致率。
风险：趋势比逆向交易者生存得更久。使用紧止损。
必须输出：被 fade 的共识是什么、为什么认为它极端、你的逆向押注。
```

#### C2: Sideways Scout — 区间逆向（环境触发）

**shadow_id**: `contrarian:range_bound:sideways_scout`
**触发条件**: VIX < 20 AND 过去5日 SPX 日均振幅 < 1.5%
**信号源**:
- VIX 处于低位（<20，市场自满）
- 日振幅压缩（<1.5%——区间确认）
- RSI 背离于区间边界
- 布林带收缩（挤压模式）
- 成交量在区间边界收缩

**决策逻辑**:
```
IF VIX < 20 AND daily_range_5d_avg < 1.5%:
    → 激活：寻找处于区间顶部的标的，做空
    → 寻找处于区间底部的标的，做多
    → 在区间边界突破时止损（大多数突破是假的，但真的会致命）
ELSE:
    → 休眠：输出 NO_RANGE_SETUP，不交易
```

**风险参数**: Virtual capital $25,000, Max 4 positions, 回撤限制 30%, 单笔 12%

#### C3: Vol Surfer — 恐慌逆向（环境触发）

**shadow_id**: `contrarian:panic:vol_surfer`
**触发条件**: VIX > 30
**信号源**:
- VIX 期限结构倒挂（现货 > 期货——恐慌峰值信号）
- Put/Call 比率极值 > 1.5
- 广度冲刷读数（<20% 股票高于 20日 MA）
- 信用利差爆破（HY OAS 扩张 >200bp）
- VIX 开始从峰值下降（恐慌消退的领先指标）

**决策逻辑**:
```
IF VIX > 30:
    → 激活：买入最受打击的资产（VIX 从峰值下降时入场——不是最低点，是右侧）
    → 做多波动率敏感资产，做空波动率本身（做空 VXX/UVXY）
    → 当 VIX 回落至 <25 时分批退出
ELSE:
    → 休眠
```

**风险参数**: Virtual capital $30,000, Max 3 positions, 回撤限制 40%, 单笔 15%

#### C4: Crash Hunter — 泡沫逆向（信号触发）

**shadow_id**: `contrarian:crash:hunter`
**触发条件**: ≥2 个 pre-crash 信号同时出现
**信号清单**（需 ≥2 个）:
1. Shiller CAPE > 30
2. Buffett Indicator（总市值/GDP） > 150%
3. Hindenburg Omen 触发（纽交所新高+新低同时 >2.2%）
4. 广度分化：指数创新高但 >50% 成分股低于 50日 MA
5. 内幕抛售激增（过去4周 insider sell/buy ratio > 5:1）
6. 信用利差扩大（IG OAS >150bp 或 HY OAS >500bp）
7. 跨资产相关性上升（股债相关性从负转正——系统性风险信号）

**决策逻辑**:
```
IF pre_crash_signals >= 2:
    → 激活：默认方向 SHORT
    → 做空最脆弱的资产（高估值、高Beta、低质量）
    → 信号越多，仓位越大（2个信号=半仓, 4+信号=满仓）
ELSE:
    → 休眠：输出 NO_CRASH_SETUP
```

**风险参数**: Virtual capital $30,000, Max 3 positions, 回撤限制 40%, 单笔 15%

### 4.3 敢死队内部协调

四个 Contrarian 影子不直接通信（保持影子间隔离规则），但共享以下风险约束：

1. **总 Contrarian 风险暴露上限**: 所有 4 个 Contrarian 的总名义敞口不超过 $100K（防止逆向押注过度集中）
2. **相关性监控**: Ecosystem Auditor 监控 4 个 Contrarian 是否同时激活——如果 3+ 同时活跃，触发"逆向拥挤"警告
3. **各自独立触发**: 每个影子独立决定是否激活——不存在"敢死队队长"协调激活

---

## 5. Type-Specific Configuration

### 5.1 ShadowConfig Changes

```python
# shadow_data_types.py

# 新 shadow_type 值
_VALID_TYPES = {
    "expert",        # was: expert
    "momentum",      # NEW — was: subset of daredevil
    "contrarian",    # NEW — was: subset of daredevil
    "temp_event",
    "challenger",
    "missed_path",
    "beta",
}
# REMOVED: "daredevil", "catfish"

# 新 status 值（Contrarian 专用）
_VALID_STATUSES = {
    "active", "beta", "retired", "paused",
    "watch", "endangered", "eliminated",
    "dormant",  # NEW — Contrarian 未触发时的正常状态（不是惩罚）
}
```

### 5.2 ShadowSettings Additions

```python
# config/settings.py — ShadowSettings additions

# ── Type-specific evaluation windows ──
evaluation_window_expert: int = 90       # days
evaluation_window_momentum: int = 75     # days (shorter)
evaluation_window_contrarian: int = 252  # days (1 trading year, longer)

# ── Contrarian-specific ──
contrarian_total_exposure_cap: float = 100_000.0   # max total contrarian notional
contrarian_trend_immunity: bool = True              # suppress elimination during trends
contrarian_trend_immunity_months: int = 3           # max consecutive months of immunity
contrarian_min_activation_pct: float = 0.15         # must be active ≥15% of days for ranking
contrarian_correlation_warning_threshold: int = 3   # ≥3 contrarians active = crowding warning

# ── Momentum-specific ──
momentum_trend_min_adx: float = 20.0    # ADX threshold for "trending" regime
momentum_max_consecutive_losses: int = 10  # trigger review after 10 consecutive losses

# ── Diversity controller ──
diversity_similarity_threshold: float = 0.75  # pairwise agreement above this = discount
diversity_min_weight_floor: float = 0.02      # every shadow gets ≥2% weight
diversity_mmc_enabled: bool = True            # Numerai-style MMC scoring
```

### 5.3 Shadow Prompts — New Contrarian Section

```json
{
  "contrarian": {
    "fade_master": "You are the Fade Master, 敢死队核心. Systematically fade consensus extremes. When >75% of Expert shadows agree on direction, bet against it. Your edge: consensus extremes are almost always wrong — not immediately, but ultimately. Key: AAII extremes, put/call extremes, COT extremes, Expert agreement rate. Risk: trends persist longer than contrarians stay solvent. Use tight stops. Floor confidence: 0.45. Output VOTE_START/VOTE_END. Must declare: what consensus you're fading, why it's extreme, your contrarian bet.",
    "sideways_scout": "You are the Sideways Scout, 敢死队区间猎手. ENVIRONMENT LOCKED: VIX<20 AND 5-day avg range<1.5%. In sideways markets, fade breakouts at range boundaries. Buy support, short resistance. Your edge: most breakouts in ranges are fake. Key: volume contraction at boundaries, RSI divergence, Bollinger squeezes. Risk: real breakouts break you. Output VOTE_START/VOTE_END when active, NO_RANGE_SETUP when dormant.",
    "vol_surfer": "You are the Vol Surfer, 敢死队恐慌冲浪者. ENVIRONMENT LOCKED: VIX>30. Buy fear peaks, fade panics. Your edge: panic is always overdone — the question is when, not if. Key: VIX term structure inversion, put/call extremes, breadth washout, credit spread blowout. Enter when VIX starts declining from peak. Risk: catching a falling knife. Output VOTE_START/VOTE_END when active, NO_PANIC_SETUP when dormant.",
    "crash_hunter": "You are the Crash Hunter, 敢死队泡沫猎手. SIGNAL LOCKED: ≥2 pre-crash signals required. SHORT-BIASED. Scan for: Shiller CAPE>30, Buffett Indicator>150%, Hindenburg Omen, breadth divergence, insider selling surges, credit spread widening, rising cross-asset correlation. More signals = bigger position. Default direction: SHORT. Output VOTE_START/VOTE_END when active (≥2 signals), NO_CRASH_SETUP when dormant."
  }
}
```

---

## 6. Cross-Type Interaction Model

### 6.1 信息流

```
                    ┌──────────────────────────────┐
                    │     Daily News + Market Data   │
                    └──────────────┬───────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            ▼                      ▼                      ▼
    ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
    │ 16 Experts    │    │ 4 Momentum    │    │ 4 Contrarian  │
    │ (Fundamental) │    │ (Trend Chase) │    │ (Mean Rev.)   │
    │ 始终活跃       │    │ 始终活跃       │    │ 条件触发       │
    └───────┬───────┘    └───────┬───────┘    └───────┬───────┘
            │                    │                    │
            │   共识方向          │                    │
            ├───────────────────┬┼────────────────────┤
            ▼                   ▼▼                    ▼
    ┌─────────────────────────────────────────────────────┐
    │              Ranking Engine (type-aware)             │
    │  - Expert: 90-day window, standard composite         │
    │  - Momentum: 75-day window, trend-following benchmark│
    │  - Contrarian: 252-day window, reversal benchmark    │
    │  - Diversity discount applied across all types       │
    └─────────────────────┬───────────────────────────────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
    ┌──────────┐  ┌──────────┐  ┌──────────────┐
    │Collusion │  │Challenger│  │  Ecosystem   │
    │Detector  │  │Engine    │  │  Auditor     │
    └──────────┘  └──────────┘  └──────────────┘
```

### 6.2 关键交互规则

| 规则 | 描述 |
|------|------|
| **R1: 分析隔离** | 影子分析期间不互读输出。排名/共谋检测仅在事后聚合。 |
| **R2: Expert → Contrarian 信号** | Expert 共识率 >75% → Fade Master 获得逆向信号（唯一合法的跨类型信息流——方向性使用） |
| **R3: 无投票权** | 所有影子（包括 Contrarian）不参与 `generate_decision()`——仅内部排名 |
| **R4: 类型内排名** | 每种类型内排名 + 跨类型总排名——两个视图都可见 |
| **R5: Contrarian 隔离** | 趋势市场中 Contrarian 损失不触发 Challenger 淘汰（见 §6.3） |
| **R6: 相关性分层** | Momentum↔Momentum 协同排名，Contrarian↔Momentum 使用负相关调整 |

### 6.3 Contrarian 趋势免疫机制

逆向策略在强趋势市场中必然亏损——这是结构性预期，不是方法论失败。Challenger 引擎必须区分"策略失效"和"策略与环境不匹配"。

```
市场体制检测（每日）:
  IF ADX > 25 AND trending_days > 20:
      regime = "TRENDING"
  ELIF ADX < 20 AND daily_range_avg < 1.5%:
      regime = "RANGE_BOUND"
  ELSE:
      regime = "TRANSITIONAL"

Contrarian 淘汰门控:
  IF regime = "TRENDING" AND contrarian_underperforming:
      → 抑制淘汰（趋势免疫激活）
      → 记录: "Immunity: trending regime, contrarian drawdown expected"
      → 最大免疫期: 3 连续月（之后强制进入观察——如果趋势结束后仍未恢复）
  ELIF regime = "RANGE_BOUND" AND contrarian_underperforming:
      → 不抑制淘汰（逆向策略应在区间市场表现好——如果仍亏损，方法论可能有问题）
```

### 6.4 多样性折扣

基于 Numerai MMC (Meta Model Contribution) 指标：

```
对每对影子 (i, j) 计算过去 90 天方向一致率:
  agreement_ij = P(direction_i = direction_j)

如果 agreement_ij > diversity_similarity_threshold (0.75):
  对每个影子应用折扣因子:
    discount_i = 1.0 - β * (avg_agreement_i - 0.5)
    其中 β = 0.3, 确保最大折扣不超过 15%
    
    deflated_score_i = composite_score_i * discount_i

权重地板: 每个影子权重 ≥ diversity_min_weight_floor (0.02)
```

---

## 7. Ranking & Evaluation Changes

### 7.1 类型感知评估

```python
@dataclass
class TypeAwareRankingConfig:
    """Evaluation parameters per shadow type."""
    shadow_type: str
    eval_window_days: int
    min_trades_for_ranking: int
    benchmark: str             # "trend_following" | "mean_reversion" | "fundamental"
    immunity_regimes: list[str] # regimes where underperformance is excused
    
TYPE_RANKING_CONFIGS = {
    "expert": TypeAwareRankingConfig(
        shadow_type="expert",
        eval_window_days=90,
        min_trades_for_ranking=5,
        benchmark="fundamental",
        immunity_regimes=[],
    ),
    "momentum": TypeAwareRankingConfig(
        shadow_type="momentum",
        eval_window_days=75,
        min_trades_for_ranking=50,
        benchmark="trend_following",
        immunity_regimes=["RANGE_BOUND"],  # 区间市场动量策略预期不佳
    ),
    "contrarian": TypeAwareRankingConfig(
        shadow_type="contrarian",
        eval_window_days=252,  # 1 trading year
        min_trades_for_ranking=50,
        benchmark="mean_reversion",
        immunity_regimes=["TRENDING"],  # 趋势市场逆向策略预期不佳
    ),
}
```

### 7.2 排名组件权重调整

```python
# Type-specific composite weights
COMPOSITE_WEIGHTS = {
    "expert":     {"mppm": 0.35, "calmar": 0.25, "omega": 0.20, "win_rate": 0.20},
    "momentum":   {"mppm": 0.25, "calmar": 0.30, "omega": 0.20, "win_rate": 0.25},
    "contrarian": {"mppm": 0.20, "calmar": 0.25, "omega": 0.30, "win_rate": 0.15,
                   "brier": 0.10},  # +Brier Score for calibration
}
# Momentum: higher weight on Calmar (trend drawdowns matter more) + Win Rate
# Contrarian: higher weight on Omega (tail outcomes matter more) + Brier calibration
# Expert: balanced weights (current default)
```

### 7.3 成就阶梯更新

| 阶梯 | Expert 门槛 | Momentum 门槛 | Contrarian 门槛 |
|------|:---:|:---:|:---:|
| Elite | 85%ile + 30天 | 85%ile + 20天 | 85%ile + 60天（更长验证） |
| Excellent | 70%ile + 10天 | 70%ile + 7天 | 70%ile + 20天 |
| Watch | 30%ile + 10天 | 30%ile + 7天 | 30%ile + 30天（更长容忍） |
| Endangered | 15%ile + 20天 | 15%ile + 14天 | 15%ile + 40天 |

---

## 8. New Components (from Research Gaps)

### 8.1 Diversity Controller（新模块）

**文件**: `shadows/diversity_controller.py`
**职责**: 主动多样性工程——计算影子间相似度、应用 MMC 折扣、强制权重地板
**输入**: 所有影子的投票方向历史（过去 90 天）
**输出**: 每个影子的多样性折扣因子
**LLM调用**: 0（纯 Python 计算）
**关键公式**:
- 成对方向一致率: `agreement_ij = count(d_i == d_j) / count(total)`
- MMC 折扣: `discount_i = 1.0 - 0.3 * (mean_agreement_i - 0.5)`，封顶 0.85-1.0
- 权重地板: `floor_weight = 0.02`（每个影子最低 2% 权重）

### 8.2 Decision Fusion Specification（规范定义）

当影子生态足够成熟（Gate 3 通过后），决策融合使用以下**确定性数学公式**：

```
Step 1 — 影子信号提取:
  对每个活跃影子 s，提取其方向投票 d_s ∈ {-1, 0, +1} 和置信度 c_s ∈ [0, 1]

Step 2 — 一致性评分:
  consistency = 1 - σ(d_signals) / σ_max
  其中 σ(d_signals) 是方向信号的标准差
  当所有影子同意 → consistency = 1.0
  当影子各半 → consistency = 0.0

Step 3 — 动态加权:
  w_s = base_weight_s * confidence_s * diversity_discount_s
  base_weight_s 来自排名百分位

Step 4 — 聚合:
  aggregate_signal = Σ(w_s * d_s) / Σ(w_s)
  区间: [-1, +1]

Step 5 — 阈值分类:
  IF |aggregate_signal| < consistency_threshold (0.15):
      → DISCARD (信号太弱/太分散)
  ELIF aggregate_signal > 0:
      → LONG signal, strength = |aggregate_signal|
  ELSE:
      → SHORT signal, strength = |aggregate_signal|

Step 6 — 审计追踪:
  记录: {date, shadow_signals[], weights[], aggregate, decision, overrides}
  LLM 仅用于生成人类可读解释——禁止修改数学输出
```

**Gate**: 此融合逻辑不立即实现——这是规范定义。影子必须通过 Gate 3（≥252天跟踪记录，Contrarian ≥0.3 Calmar，多样性折扣有效）后，此规范才被激活。

### 8.3 Graceful Degradation（优雅降级）

```
┌─────────────────┬────────────────────┬──────────────────────┐
│ Component       │ Degradation Mode   │ Fallback             │
├─────────────────┼────────────────────┼──────────────────────┤
│ 16 Experts      │ ≥12 active = FULL  │ 8-11 = x0.8 weight   │
│                 │ 4-7 = x0.5 weight  │ <4 = Expert DISABLED │
├─────────────────┼────────────────────┼──────────────────────┤
│ 4 Momentum      │ 3-4 active = FULL  │ 2 = x0.8 weight      │
│                 │ 1 = WARNING only   │ 0 = Momentum DISABLED│
├─────────────────┼────────────────────┼──────────────────────┤
│ 4 Contrarian    │ ≥2 active = FULL   │ 1 = x0.7 weight      │
│                 │ 0 = Contrarian DISABLED (no contrarian)   │
├─────────────────┼────────────────────┼──────────────────────┤
│ Red Team        │ Normal = critique  │ Failed = flag human   │
│                 │                   │ NO auto-proceed       │
├─────────────────┼────────────────────┼──────────────────────┤
│ Collusion Det.  │ Normal = monitor   │ Failed = warn only    │
│                 │                   │ (non-blocking)        │
├─────────────────┼────────────────────┼──────────────────────┤
│ Diversity Ctrl  │ Normal = discount  │ Failed = uniform wt   │
│                 │                   │ (conservative fallback)│
└─────────────────┴────────────────────┴──────────────────────┘
```

---

## 9. Migration Plan

### 9.1 Phase 1: 数据层（无破坏性变更）

**文件**: `shadow_data_types.py`
1. 添加 `"momentum"` 和 `"contrarian"` 到 `_VALID_TYPES`
2. 添加 `"dormant"` 到 `_VALID_STATUSES`
3. 保留 `"daredevil"` 在 `_VALID_TYPES` 中（向后兼容——现有 DB 中的 8 个 daredevil 不会立即改名）
4. 添加新 dataclass: `TypeAwareRankingConfig`

### 9.2 Phase 2: 配置层

**文件**: `shadow_prompts.json`, `settings.py`
1. `shadow_prompts.json`: 添加 `"contrarian"` section + 重命名 `"daredevil"` → `"momentum"`
2. `settings.py`: 添加 §5.2 中的新设置项

### 9.3 Phase 3: 拆分影子配置

**文件**: `daredevil_shadows.py` → `daredevil_shadows.py` + `contrarian_shadows.py`
- 新建 `contrarian_shadows.py` — 4 个 Contrarian 影子 + `CONTRARIAN_SHADOW_CONFIGS` + `create_contrarian_shadows()`
- 修改 `daredevil_shadows.py` — 8 → 4 个 Momentum 影子, `DAREDEVIL_SHADOW_CONFIGS` → `MOMENTUM_SHADOW_CONFIGS`

### 9.4 Phase 4: 运行时适配

**文件**: `shadow_mother.py`, `ranking_engine.py`, `challenger_engine.py`, `ecosystem_auditor.py`
- `shadow_mother.py`: 添加 Contrarian 影子的独立创建逻辑
- `ranking_engine.py`: 类型感知评估窗口 + 组件权重
- `challenger_engine.py`: Contrarian 趋势免疫逻辑
- `ecosystem_auditor.py`: Contrarian 拥挤检测（≥3 同时激活 → 警告）

### 9.5 Phase 5: 新模块

**文件**: `diversity_controller.py` (新建)
- 纯 Python 计算模块
- MMC 折扣 + 权重地板
- ~150 行

### 9.6 Phase 6: DB 迁移

**文件**: `shadow_schema.py`
- Migration 添加 `shadow_type` 值迁移: `UPDATE shadows SET shadow_type='momentum' WHERE shadow_id LIKE 'daredevil:%' AND shadow_id NOT LIKE '%fade_master%' AND shadow_id NOT LIKE '%sideways%' AND shadow_id NOT LIKE '%vol_surfer%' AND shadow_id NOT LIKE '%crash%'`
- `UPDATE shadows SET shadow_type='contrarian' WHERE shadow_id LIKE '%fade_master%' OR shadow_id LIKE '%sideways%' OR shadow_id LIKE '%vol_surfer%' OR shadow_id LIKE '%crash%'`

### 9.7 测试

每个 Phase 有对应测试。总计预估新增 ~80 tests。

---

## 10. Risk Assessment

| # | 风险 | 严重度 | 缓解 |
|:--:|------|:---:|------|
| R1 | DB 迁移破坏现有影子数据 | HIGH | 迁移前完整 DB 备份 + dry-run 模式 + 回滚脚本 |
| R2 | Contrarian 类型只有 4 个成员，样本过小 | MEDIUM | 未来可通过 Temp Shadow 机制创建更多 Contrarian；4 个足够建立基准 |
| R3 | 趋势免疫被滥用——Contrarian 永远不被淘汰 | MEDIUM | 最大免疫 3 连续月；趋势结束后若仍亏损则强制进入观察期 |
| R4 | 多样性折扣抑制了真正好的影子 | LOW | 折扣上限 15% + 权重地板 2% 保证最小参与 |
| R5 | 决策融合规范过早实现 | LOW | 明确 Gate 3 条件（≥252天跟踪 + Contrarian Calmar≥0.3）前不激活 |
| R6 | Momentum 类型失去了 Fade Master 的负相关对冲 | LOW | Contrarian 类型提供相同的对冲，且现在有更清晰的基准和隔离 |
| R7 | Crash Hunter 在牛市中长期休眠 | LOW | Dormant 状态下不消耗配额，不参与排名——无惩罚；激活时按完整 Contrarian 基准评估 |

---

## 11. Open Questions for Red Team Review

1. **Contrarian 4 成员是否够？** 是否需要额外添加分行业的 Fade Master（如 Fade Master:Tech, Fade Master:Energy）？
2. **Crash Hunter 归入 Contrarian 合理吗？** 还是应该单独作为 Event-Driven/Tail 类型？
3. **趋势免疫 3 个月上限是否合适？** 历史上最长的趋势可以持续数年（如 2009-2020 牛市）。
4. **多样性折扣 β=0.3 是否合适？** 需要敏感性分析——β 过高会过度惩罚共识，过低则无效果。
5. **决策融合中的 consistency_threshold=0.15 是否合理？** 需要基于历史影子投票数据的回测校准。
6. **Expert 类型是否需要进一步细化？** 16 个 Expert 中，macro:cycle_reader 是跨资产视角——是否可以作为一个独立的"Router"角色而不是普通 Expert？
7. **Dormant 状态的影子如何在 UI 中显示？** 休眠影子占 UI 空间但无输出——用户体验是否会被影响？

---

## 12. Success Criteria

- [ ] 所有 24 个影子按策略原型重新分类（无遗失）
- [ ] Contrarian "敢死队" 4 成员：独立配置、独立基准、趋势免疫
- [ ] 类型感知排名：Momentum 75天 / Expert 90天 / Contrarian 252天评估窗口
- [ ] Diversity Controller：MMC 折扣 + 权重地板（≤150行纯Python）
- [ ] Decision Fusion 规范已定义（不实现——仅规范）
- [ ] Graceful Degradation 矩阵已定义
- [ ] DB 迁移脚本 + 回滚脚本
- [ ] 所有 1272 现有测试通过（无回归）
- [ ] ~80 新测试覆盖新逻辑
- [ ] Red Team audit: 所有 HIGH/CRITICAL 已解决
