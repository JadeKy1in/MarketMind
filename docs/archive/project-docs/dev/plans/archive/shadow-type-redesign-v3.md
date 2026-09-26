# Shadow Ecosystem Type Redesign v3 — 策略原型分类

**Status**: PENDING USER APPROVAL
**Date**: 2026-05-20
**Previous**: v2 (deprecated — Red Team reviewed, 14 findings)
**Trigger**: Fade Master 敢死队重设计 + 外部研究结论
**Research Basis**: 2-agent parallel web research (Millennium/Citadel pod-shop architecture; Jegadeesh & Titman 1993; DeBondt & Thaler 1985; AlphaMix KDD 2023; ArchetypeTrader AAAI 2026; MARS AAAI 2026; Numerai MMC; Telescope BEAM)

---

## 1. 核心原则

**分类维度：策略原型。不是风险水平。**

风险是中央风控引擎统一施加的正交约束——每个影子独立拥有风险预算（回撤上限、仓位限制、止损规则），与它属于哪个策略类型无关。这直接对标 Millennium/Citadel 的 pod-shop 架构：pod 按 Equities/FI&Macro/Commodities/Quant/Credit 分桶，风险限额由中央风控统一管理。

---

## 2. 新影子类型体系

### 2.1 三类型架构

```
Fundamental (16)     Momentum (4)        Contrarian (4)
领域专家              动量/趋势             逆向/敢死队

始终活跃              始终活跃              全球扫描条件触发（大多数交易日活跃）
τ=0.30-0.40          τ=0.40-0.50          τ=0.45-0.60
90天评估窗口          75天评估窗口           252天评估窗口
回撤上限 25%          回撤上限 30%           回撤上限 35-40%
min 5笔交易           min 50笔交易           min 25-50笔交易
```

### 2.2 完整影子清单

#### Fundamental — 16 领域专家

| shadow_id | 显示名 | 领域 | 资本 | τ |
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

**策略原型**: 领域专业知识 + 基本面估值
**始终活跃**: 每个领域总有值得分析的东西
**评估**: 90天窗口，均衡权重（MPPM 0.35 / Calmar 0.25 / Omega 0.20 / WinRate 0.20）

#### Momentum — 4 动量/趋势

| shadow_id | 显示名 | 策略 | 持有期 | 资本 | τ |
|------|------|------|------|------|:--:|
| `momentum:intraday:scalper` | Intraday Scalper | 日内动量 | 1-3天 | $25K | 0.50 |
| `momentum:weekly:trend_rider` | Trend Rider | 周线趋势 | 5-15天 | $30K | 0.40 |
| `momentum:event:news_hound` | Event Hound | 事件追入 | 1-5天 | $25K | 0.45 |
| `momentum:sector:rotation_engine` | Rotation Engine | 板块轮动 | 5-20天 | $30K | 0.40 |

**策略原型**: 趋势延续（正反馈）/ 突破追入（stop-entry）
**始终活跃**: 每天寻找动量机会（每种市场都有动量——方向不同而已）
**评估**: 75天窗口，高 Calmar 权重（Momentum 回撤更重要）
**免疫**: 区间市场（RANGE_BOUND）下动量损失不触发淘汰

#### Contrarian "敢死队" — 4 逆向/均值回归

| shadow_id | 显示名 | 触发条件 | 激活频率 | 资本 | τ |
|------|------|------|:--:|------|:--:|
| `contrarian:consensus:fade_master` | Fade Master | 始终活跃（每日） | 高 | $20K | 0.55 |
| `contrarian:range_bound:sideways_scout` | Sideways Scout | 全球扫描：15+ 指数中寻找区间市场 | 高 | $25K | 0.45 |
| `contrarian:panic:vol_surfer` | Vol Surfer | 全球扫描：任一主要波动率指数飙升 | 中 | $30K | 0.60 |
| `contrarian:crash:hunter` | Crash Hunter | 全球扫描：任一地区 ≥2 bubble 信号 | 中 | $30K | 0.50 |

**策略原型**: 均值回归（负反馈）/ 极限位置逆向（limit-entry）
**全球扫描**: 每个 Contrarian 影子扫描全球市场寻找符合策略原型的极端状态——不局限于美国市场。全球总有某个市场处于区间/恐慌/泡沫状态，因此 Contrarian 影子大多数交易日都活跃，只是在不同的市场。
**评估**: 252天窗口，高 Omega 权重（尾部结果更重要）+ Brier Score
**免疫**: 趋势市场（TRENDING）下逆向损失不触发淘汰
**特殊规则**: 
- Fade Master 激活率 ≥ 50%（每日活跃，无环境锁，不能长期 abstain）
- Vol Surfer 和 Crash Hunter 通过全球扫描大幅提升激活频率，min 交易从 10-15 笔上调至 25-35 笔（252天窗口）
- "dormant" 状态极少发生（全球找不到机会时），不参与排名，不累积 Challenger 淘汰计数

### 2.3 类型定义

```python
_VALID_TYPES = {
    "expert",        # Fundamental: 领域专家，基本面分析
    "momentum",      # Momentum: 趋势延续，正反馈
    "contrarian",    # Contrarian: 均值回归，负反馈
    "temp_event",    # 临时事件影子（动态）
    "challenger",    # 挑战者（动态，不可见）
    "missed_path",   # 反事实追踪（动态，只读）
    "beta",          # 实验性影子（隔离，不排名）
}
# 移除: "daredevil"（拆分）, "catfish"（已废弃）

_VALID_STATUSES = {
    "active", "beta", "retired", "paused",
    "watch", "endangered", "eliminated",
    "dormant",  # 全球扫描后零市场触发（罕见，非正常状态）
}
```

---

## 3. 每个 Contrarian 成员的详细定义

### 3.1 共同 DNA

1. **均值回归假设**: 极端状态不可持续，最终回归均衡
2. **逆向入场**: 在最拥挤/最恐慌/最泡沫时入场
3. **全球扫描**: 全球总有符合策略原型的市场——不局限于美国。每个影子扫描全球多个市场/地区，在符合条件的市场中激活。只在全球零市场触发时才报告 "NO_*_GLOBALLY"
4. **极限位置触发**: 各自定义"极端"的具体标准（跨市场适用）
5. **长周期评估**: 252天窗口（DeBondt-Thaler 框架）
6. **高波动容忍**: 逆向入场 = 浮亏常态
7. **免疫保护**: 趋势市场中损失不触发淘汰（结构性预期）
8. **回撤强制**: 即使免疫期间，回撤上限**永不暂停**

### 3.2 C1: Fade Master — 共识逆向

**shadow_id**: `contrarian:consensus:fade_master`
**触发**: 始终活跃（每日）
**信号源**:
- AAII 散户情绪（牛熊比 >2.0 或 <0.5）
- Put/Call 比率极端（<0.6 或 >1.5）
- COT 投机净仓位处于 2 年极端
- 社交媒体情绪峰值

**共识信号** (从 Expert 输出中提取——第二遍运行):
- Fade Master **在 Expert 全部完成后**运行（第二遍）
- ConsensusExtractor 计算 Expert 方向一致率
- 一致率 >75% → 逆向信号触发
- 一致率 <75% → 正常分析，可 ABSTAIN

```
决策逻辑:
  IF Expert 一致率 >75% AND 方向 = long:
      → SHORT 共识最强的 ticker(s)
  IF Expert 一致率 >75% AND 方向 = short:
      → LONG 最被讨厌的 ticker(s)
  IF Expert 一致率 <75%:
      → 正常分析，可 ABSTAIN
```

**参数**: 资本 $20K / 最多 4 仓位 / 回撤 35% / 单笔 10%
**约束**: 激活率 ≥ 50%（月均至少 10 个交易日有产出）——低于此门槛标记 "insufficient_data" 零权重

### 3.3 C2: Sideways Scout — 区间逆向（全球扫描）

**shadow_id**: `contrarian:range_bound:sideways_scout`
**策略**: 在全球15+主要指数中寻找区间震荡市场，在区间边界逆向交易

**全球扫描清单**:
```
美洲: S&P 500, Nasdaq 100, Russell 2000, Bovespa
欧洲: FTSE 100, Euro Stoxx 50, DAX, CAC 40, IBEX 35
亚太: Nikkei 225, Hang Seng, Shanghai Composite, Nifty 50, ASX 200, KOSPI
```

**触发条件** (对每个指数独立判断):
```
该指数 VIX-equivalent < 20
AND 5日日均振幅 < 1.5%
AND |20日均线斜率| < 0.1%/日  ← 趋势过滤器（解决红方 M3）
```

**扫描逻辑**:
```
每日扫描所有15+指数
→ 找到满足条件的指数 → 在该市场激活，区间顶部做空 / 区间底部做多
→ 多个市场同时满足 → 选择振幅最窄的3-4个（最优区间信号）
→ 零市场满足 → 输出 NO_RANGE_GLOBALLY（极少发生）
```

**自检** (解决红方 Finding 2，按市场独立追踪):
```
IF 某市场连续 8 次在"区间边界"止损:
    → 该市场标记为 FALSE_RANGE，暂停 20 天
    → 其他市场继续正常扫描
    → 20 天后该市场重新评估
```

**参数**: 资本 $25K / 最多 4 仓位（可跨市场分配） / 回撤 30% / 单笔 12%

### 3.4 C3: Vol Surfer — 恐慌逆向（全球扫描）

**shadow_id**: `contrarian:panic:vol_surfer`
**策略**: 监控全球主要波动率指数，在任一市场出现恐慌时逆向入场

**全球波动率指数清单**:
```
VIX (美国)          VSTOXX (欧洲)         VNKY (日本)
NIFTY50 VIX (印度)  KOSPI VIX (韩国)      HSI Vol (香港)
VXEFA (发达市场ex-US)
```

**触发条件** (任一市场满足即可):
```
该市场波动率指数 > 30（或其历史90%分位，取较低值）
```

**扫描逻辑**:
```
每日扫描所有全球波动率指数
→ 任一 > 触发阈值 → 在该市场激活
→ 多个市场同时恐慌 → 选择波动率偏离历史均值最大的2-3个市场
→ 所有波动率指数正常 → 输出 NO_PANIC_GLOBALLY（极少发生）
```

**入场/退出** (按市场独立):
- 入场: 该市场波动率从峰值回落时入场（右侧，不是接飞刀）
- 退出: 该市场波动率回归至中位数以下时分批退出
- 信号: VIX 期限倒挂 / Put/Call >1.5 / 广度冲刷 / 信用利差爆破（各市场独立评估）

**参数**: 资本 $30K / 最多 3 仓位（可跨市场分配） / 回撤 40% / 单笔 15%
**min_trades_for_ranking**: 30（全球扫描大幅提升激活频率——修正此前15笔的低频假设）

### 3.5 C4: Crash Hunter — 泡沫逆向（全球扫描）

**shadow_id**: `contrarian:crash:hunter`
**策略**: 全球扫描泡沫信号，在信号聚集的市场做空泡沫。全球总有某个市场估值偏高——不局限于美国。

**全球扫描地区**:
```
美国 / 欧洲（EU aggregate） / 日本 / 中国 / 新兴市场（EM aggregate）
```

**信号清单** (每地区独立评分，需 ≥2 触发):
1. CAPE / 可比周期性调整市盈率 > 30（或该地区历史90%分位）
2. 市值/GDP 比率 > 150%（或该地区历史90%分位）
3. Hindenburg Omen 触发（仅适用于有足够成分股的市场）
4. 广度分化（指数新高但 >50% 成分股 < 50MA）
5. 内幕抛售比 >5:1（4周窗口，有数据可得的市场）
6. 信用利差扩大（IG OAS >150bp 或 HY >500bp，按地区企业债）
7. 跨资产相关性上升（股债相关性从负转正）

**扫描逻辑**:
```
每日对每个地区独立评分
→ 任一地区 ≥2 信号 → 在该市场激活，SHORT-BIASED
→ 多个地区触发 → 选择信号数量最多的2-3个地区
→ 零地区 ≥2 信号 → 输出 NO_BUBBLE_GLOBALLY（极少发生）
```

**仓位缩放** (按地区，基于该地区的信号数):
```
2 信号 = 半仓
3 信号 = ¾ 仓
4+ 信号 = 满仓
```

**参数**: 资本 $30K / 最多 3 仓位（可跨地区分配） / 回撤 40% / 单笔 15%
**min_trades_for_ranking**: 25（全球扫描大幅提升激活频率——修正此前10笔的极低频假设）

---

## 4. 类型感知配置

### 4.1 评估参数

```python
TYPE_RANKING_CONFIGS = {
    "expert": {
        "eval_window_days": 90,
        "min_trades_for_ranking": 5,
        "immunity_regimes": [],
        "composite_weights": {"mppm": 0.35, "calmar": 0.25, "omega": 0.20, "win_rate": 0.20},
    },
    "momentum": {
        "eval_window_days": 75,
        "min_trades_for_ranking": 50,
        "immunity_regimes": ["RANGE_BOUND"],
        "composite_weights": {"mppm": 0.25, "calmar": 0.30, "omega": 0.20, "win_rate": 0.25},
    },
    "contrarian": {
        "eval_window_days": 252,
        "min_trades_for_ranking": {  # 按激活频率分层（全球扫描后上调）
            "fade_master": 50,
            "sideways_scout": 40,
            "vol_surfer": 30,
            "crash_hunter": 25,
        },
        "immunity_regimes": ["TRENDING"],
        "composite_weights": {"mppm": 0.20, "calmar": 0.25, "omega": 0.30,
                              "win_rate": 0.15, "brier": 0.10},
    },
}
```

### 4.2 成就阶梯

| 阶梯 | Expert | Momentum | Contrarian |
|------|:--:|:--:|:--:|
| Elite | 85%ile + 30天 | 85%ile + 20天 | 85%ile + **60天** |
| Excellent | 70%ile + 10天 | 70%ile + 7天 | 70%ile + **20天** |
| Watch | 30%ile + 10天 | 30%ile + 7天 | 30%ile + **30天** |
| Endangered | 15%ile + 20天 | 15%ile + 14天 | 15%ile + **40天** |

### 4.3 ShadowSettings

```python
@dataclass
class ShadowSettings:
    # ... existing fields ...

    # ── Type-specific ──
    eval_window_expert: int = 90
    eval_window_momentum: int = 75
    eval_window_contrarian: int = 252

    # ── Contrarian ──
    contrarian_total_exposure_cap: float = 100_000.0
    contrarian_exposure_expansion_max: float = 130_000.0  # 4个独立激活时允许扩展
    contrarian_trend_immunity_taper: list[float] = (1.0, 0.66, 0.33, 0.0)  # 逐月递减
    contrarian_fade_master_min_activation: float = 0.50  # Fade Master 激活率 ≥50%
    contrarian_global_scan_min_trades: dict = {"vol_surfer": 30, "crash_hunter": 25}  # 全球扫描大幅提升激活频率

    # ── Momentum ──
    momentum_max_consecutive_losses: int = 10

    # ── Diversity ──
    diversity_similarity_threshold: float = 0.75
    diversity_beta: float = 0.3
    diversity_min_factor: float = 0.85   # 下限（不跌破 0.85）
    diversity_max_factor: float = 1.15   # 上限（不超过 1.15，明确标识为 "diversity bonus"）
    diversity_min_weight_floor: float = 0.02

    # ── System safety ──
    system_safe_mode_weight_threshold: float = 0.40  # 有效权重 <40% → SAFE_MODE
```

### 4.4 Contrarian Prompts

```json
{
  "contrarian": {
    "fade_master": "你是 Fade Master，敢死队共识逆向者。系统性地 fading 拥挤共识。关键信号：AAII 极端、Put/Call 极端、COT 极端、Expert 一致率。当共识最拥挤时押注反转。共识极端几乎总错——未必立刻，但最终必错。风险：趋势存活比逆向者更长。使用紧止损。输出 VOTE_START/VOTE_END，必须声明：正在 fading 什么共识、为什么极端、逆向押注方向。Floor confidence: 0.45。激活率要求：月均 ≥50%（不能长期静默）。",
    "sideways_scout": "你是 Sideways Scout，敢死队区间猎手。全球扫描模式：每日扫描15+主要指数（S&P 500, Nasdaq, FTSE 100, Euro Stoxx 50, DAX, CAC 40, Nikkei 225, Hang Seng, Shanghai Composite, Nifty 50, ASX 200, KOSPI, Bovespa等）。对每个指数独立判断：VIX-equivalent<20 + 5日振幅<1.5% + 20日均线平坦。在满足条件的市场中，于区间边界 fade 突破——区间中大多数突破是假的。关键：边界成交量收缩、RSI 背离、布林带收缩。多个市场满足时选振幅最窄的3-4个。某市场连续8次在区间边界止损 → 该市场标记 FALSE_RANGE 暂停20天。风险：真突破致命。激活时输出找到的市场和方向。全球零市场满足时输出 NO_RANGE_GLOBALLY（极罕见）。",
    "vol_surfer": "你是 Vol Surfer，敢死队恐慌冲浪者。全球扫描模式：每日监控全球波动率指数（VIX, VSTOXX, VNKY, NIFTY50 VIX, KOSPI VIX, HSI Vol, VXEFA）。任一市场的波动率指数 >30 或超过其历史90%分位 → 在该市场激活。买在恐惧峰值，fade 恐慌。恐慌总是过度的——问题只是何时消退。关键：VIX 期限倒挂、Put/Call 极端、广度冲刷、信用利差爆破。波动率从峰值回落时入场（右侧）。波动率回归中位数以下时退出。风险：接飞刀。多个市场恐慌时选偏离最大的2-3个。激活时输出所在市场和入场理由。全球所有波动率正常时输出 NO_PANIC_GLOBALLY（极罕见）。",
    "crash_hunter": "你是 Crash Hunter，敢死队泡沫猎手。全球扫描模式：对每个地区（美国/欧洲/日本/中国/新兴市场）独立评分 bubble 信号。需要该地区 ≥2 个 pre-crash 信号触发。扫描每地区：CAPE/可比PE>30或历史90%分位、市值/GDP>150%、Hindenburg Omen、广度分化、内幕抛售激增、信用利差扩大、跨资产相关性上升。信号越多仓位越大。默认方向：做空。多个地区触发时选信号最多的2-3个。激活时输出做空地区和信号清单。全球零地区 ≥2 信号时输出 NO_BUBBLE_GLOBALLY（极罕见）。"
  }
}
```

---

## 5. 体制检测与免疫机制

### 5.1 四级体制（解决红方 H3 + Finding A）

体制检测基于 **SPX（基准市场）** 的 ADX 和振幅。免疫机制以主市场体制为准——即使 Contrarian 影子在全球其他市场交易，体制免疫仍按 SPX 体制计算。

```
ADX ≥ 30 → TRENDING (强趋势)
  → 持续 10 天才激活（滞后进入，防止抖动）
  → Contrarian: 完全免疫
  → Momentum: 正常评估

ADX 20-30 → TRANSITIONAL (过渡)
  → Contrarian: 50% 免疫（损失权重减半计入 Challenger 评分）
  → Momentum: 50% 免疫
  → 两个方向都不清楚——两边都保护

ADX < 20 AND 日振幅均 < 1.5% → RANGE_BOUND (区间)
  → 持续 10 天才激活
  → Contrarian: 正常评估（区间是逆向的主场）
  → Momentum: 完全免疫

ADX < 20 BUT 日振幅 > 1.5% → CHOPPY (震荡)
  → Contrarian: 50% 免疫
  → Momentum: 50% 免疫
  → 两边都可能被来回打脸

体制切换滞后规则:
  → 进入免疫: 条件连续满足 10 个交易日
  → 退出免疫: 条件连续不满足 10 个交易日
  → 目的: 防止体制边界抖动引发的免疫翻转

全球市场维度:
  → Contrarian 影子在各目标市场独立判断是否满足策略触发条件
  → 每个被交易的市场追踪独立的 "FALSE_RANGE" / "FALSE_PANIC" / "FALSE_BUBBLE" 标记
  → 体制免疫仍按 SPX 基准执行——全球市场交易不影响免疫判定
```

### 5.2 免疫规则（解决红方 C1）

```
两层级免疫:

TIER 1 — 淘汰免疫:
  趋势市场下 Contrarian 损失不触发 Challenger 淘汰
  区间市场下 Momentum 损失不触发 Challenger 淘汰
  免疫逐月递减: 月1=100% / 月2=66% / 月3=33% / 月4+=0%
  → 没有悬崖效应——自然衰竭，不是突然切断

TIER 2 — 回撤执行 (永不暂停):
  无论免疫状态，任何影子超过其回撤上限立即 PAUSE:
  - 资本冻结，不产生新信号
  - 触发诊断审查（方法论文档自动生成）
  - PAUSE 持续到: 方法论更新 + 3 测试通过 + 手动恢复
  → 免疫保护"不被淘汰"，不保护"无限亏钱"
```

### 5.3 免疫期间的诊断挑战者（解决红方 H4）

```
趋势免疫激活时，Challenger 创建 "诊断挑战者":
  → 使用与原始 Contrarian 相同的策略类型
  → 但修改参数（不同信号阈值、不同回溯窗口）
  → 运行于 BETA 隔离（不影响排名）
  → 30-60 天后比较原始 vs 诊断:
      - 诊断挑战者表现更好 → 方法论有问题 → 替换
      - 两者表现类似 → 体制问题 → 免疫继续
```

---

## 6. 多样性控制器

### 6.1 MMC 公式（解决红方 H1）

```python
def compute_diversity_factor(shadow_id: str,
                             all_directions: dict[str, list[int]],
                             beta: float = 0.3,
                             min_factor: float = 0.85,
                             max_factor: float = 1.15,
                             threshold: float = 0.75) -> float:
    """
    成对方向一致率 → diversity_factor。
    
    avg_agreement > 0.75 → factor < 1.0 (折扣：太像别人)
    avg_agreement < 0.50 → factor > 1.0 (奖金：独特信号)
    区间: [min_factor, max_factor] = [0.85, 1.15]
    """
    if shadow_id not in all_directions:
        return 1.0
    
    my_dirs = all_directions[shadow_id]
    pairwise = []
    for other_id, other_dirs in all_directions.items():
        if other_id == shadow_id:
            continue
        common = sum(1 for d1, d2 in zip(my_dirs, other_dirs) if d1 == d2)
        pairwise.append(common / max(len(my_dirs), 1))
    
    if not pairwise:
        return 1.0
    
    avg_agreement = sum(pairwise) / len(pairwise)
    if avg_agreement < threshold:
        return 1.0  # 不够相似，无需折扣
    
    raw = 1.0 - beta * (avg_agreement - 0.5)
    return max(min_factor, min(max_factor, raw))
```

### 6.2 应用

```
排名前对每个影子计算 diversity_factor
  deflated_score = composite_score * diversity_factor

最终权重:
  base_weight = percentile_rank_to_weight(percentile)
  diversity_weight = base_weight * diversity_factor
  final_weight = max(diversity_min_weight_floor, diversity_weight)

权重地板: 每个影子 ≥ 2%（防止赢家通吃、保留探索）
```

---

## 7. 信息流与交互规则

### 7.1 分析时序（解决红方 C3）

```
阶段 1 — PARALLEL（并行）:
  16 Expert + 4 Momentum + 3 全球扫描 Contrarian (Sideways/Vol/Crash 若触发)
  → 独立分析，不互读

阶段 2 — CONSENSUS EXTRACTION（共识提取）:
  ConsensusExtractor 读取 16 Expert 的输出
  → 提取方向信号（regex 匹配 thesis 文本中的 long/short/bullish/bearish）
  → 计算: consensus_direction, agreement_pct
  → 纯 Python 计算，0 LLM 调用，~30行代码

阶段 3 — FADE MASTER（第二遍）:
  Fade Master 接收 consensus_direction + agreement_pct
  → IF agreement_pct > 75%: 逆向信号触发
  → 不读取任何影子内部的完整分析文本
  → 仅接收聚合统计量（方向和一致率）
```

**为什么这样可以**: ConsensusExtractor 输出的是统计量（一个方向 + 一个百分比），不是影子分析内容。保持了分析隔离原则——Fade Master 不知道其他影子为什么这么想，只知道它们往哪边站。

### 7.2 交互规则

| 规则 | 内容 |
|------|------|
| R1 | 阶段1中所有影子独立分析，不互读 |
| R2 | Fade Master 在阶段3运行，仅接收 ConsensusExtractor 的聚合统计量 |
| R3 | 所有影子（含 Contrarian）不参与 `generate_decision()` |
| R4 | 类型内排名 + 跨类型总排名——两个视图 |
| R5 | 免疫仅抑制淘汰，不暂停回撤限额 |
| R6 | Momentum↔Contrarian 使用负相关调整 (-35%) |
| R7 | Contrarian 影子在 dormant（全球零触发）期间不参与排名，不累积淘汰计数。dormant 极为罕见——全球扫描确保大多数交易日有至少一个市场激活 |

---

## 8. 决策融合规范

### 8.1 数学公式

```
Step 1 — 信号提取:
  对每个活跃影子 s: d_s ∈ {-1, 0, +1}, c_s ∈ [0, 1]

Step 2 — 一致性评分:
  consistency = 1 - σ(d_signals) / σ_max

Step 3 — 动态加权:
  w_s = base_weight_s * confidence_s * diversity_factor_s
  base_weight_s 来自排名百分位

Step 4 — 聚合:
  aggregate_signal = Σ(w_s * d_s) / Σ(w_s)

Step 5 — 阈值:
  IF |aggregate_signal| < 0.15 → DISCARD
  ELIF aggregate_signal > 0 → LONG
  ELSE → SHORT

Step 6 — LLM 解释 + 自动验证（解决红方 C4）:
  a. LLM 基于 {signals, weights, aggregate, decision} 生成可读解释
  b. VerificationEngine 从 LLM 解释中提取所有量化声明（正则匹配）
  c. 交叉比对量化声明 vs 数学输出（Steps 1-5）
  d. 发现矛盾 → 重新生成解释 + 修正指令
  e. 重试 3 次仍矛盾 → 输出纯数学结果（无 LLM 解释）+ flag human review
  f. 所有版本（原始 + 修正）写入审计日志

Step 7 — 审计追踪:
  {date, shadow_signals[], weights[], aggregate, decision, 
   explanation_generation_count, flagged_claims[], overrides}
```

### 8.2 激活条件

此融合规范不立即实现。Gate 3 条件:
- [ ] 所有影子类型 ≥252 天跟踪记录
- [ ] Contrarian 类型 Calmar ≥ 0.3
- [ ] Diversity Controller 折扣因子有效（不全部 = 1.0）
- [ ] 至少一次完整的市场周期（趋势 + 区间 + 恐慌）

---

## 9. 优雅降级

### 9.1 组件降级矩阵

```
Component        Degradation                    Fallback
──────────────────────────────────────────────────────────
16 Experts        ≥12 active = FULL
                  8-11 = x0.8 weight
                  4-7 = x0.5 weight
                  <4 = DISABLED

4 Momentum        3-4 active = FULL
                  2 = x0.8 weight
                  1 = WARNING
                  0 = DISABLED

4 Contrarian       ≥2 active = FULL
                  1 = x0.7 weight
                  0 = DISABLED

Red Team          Normal = critique              Failed = flag human
                                                NO auto-proceed

Collusion         Normal = monitor              Failed = warn (non-blocking)

Diversity         Normal = discount             Failed = uniform weights
```

### 9.2 系统级断路器（解决红方 M1）

```
IF 总有效权重 < system_safe_mode_weight_threshold (0.40):
    → SAFE_MODE
    → 无自动决策
    → 仅输出诊断信息
    → 标记人类审查

总有效权重 = Σ(每种类型的 active_shadows / total_shadows * degradation_multiplier)
```

### 9.3 Dormant 与 Challenger 交互（解决红方 M2）

Dormant 定义为"全球扫描后零市场满足触发条件"——极为罕见，因为全球总有某市场处于区间/恐慌/泡沫状态。

```
Dormant 影子:
  → 不参与排名计算
  → Challenger 的 consecutive_bottom_periods 计数器暂停（而非累积）
  → dormancy 期间消耗 0 配额
  → 重新激活时: 计数器从休眠前的值恢复（不归零，不累加）
  → 连续 dormant > 20 个交易日 → 标记审查（全球找不到机会 = 策略定义可能过窄）

Active 但激活率不足的 Contrarian (Fade Master < 50% 或 全球扫描影子 < min_trades):
  → 参与排名（标记 "insufficient_data"）
  → 排名中给予 floor 权重（不高于 2%）
  → 但在决策融合中 weight = 0（无足够数据 = 不参与聚合）
```

---

## 10. Contrarian 敞口管理（解决红方 H5 + H7）

### 10.1 敞口定义

**敞口 = 所有 Contrarian 当前已部署的虚拟头寸名义价值之和**（不是分配的资本规模，不是最大可部署）

### 10.2 常规上限

```
总敞口 ≤ $100K（基线）

如果 4 个 Contrarian 同时激活 AND Ecosystem Auditor 确认每个激活条件独立满足:
    → 上限扩展到 $130K
    → Auditor 验证: 不是同向 cascading（一个事件触发另一个）
    → 扩展记录在审计日志中
```

### 10.3 违规处理

```
IF 总敞口 > 适用上限:
    → 按比例裁减: 每个影子 position_size *= cap / total_exposure
    → 裁减后重新计算（裁减发生说明配置有问题——审计标记）
```

---

## 11. 迁移计划

### 11.1 Phase 0: 审计基线

- 备份 `data/shadows/shadows.db`
- 记录迁移前影子状态（数量、类型、状态）

### 11.2 Phase 1: 类型定义

**文件**: `shadow_data_types.py`
- 添加 `"momentum"`, `"contrarian"` 到 `_VALID_TYPES`
- 添加 `"dormant"` 到 `_VALID_STATUSES`
- 暂保留 `"daredevil"` 向后兼容
- 添加 `TypeAwareRankingConfig` dataclass

### 11.3 Phase 2: 配置

**文件**: `shadow_prompts.json`, `settings.py`
- prompts: 添加 `"contrarian"` section, 重命名 `"daredevil"` → `"momentum"`
- settings: 添加 §4.3 新字段

### 11.4 Phase 3: 影子模块

**文件**: 新建 `contrarian_shadows.py`, 修改 `daredevil_shadows.py`
- `contrarian_shadows.py`: 4 Contrarian 配置 + `CONTRARIAN_SHADOW_CONFIGS` + `create_contrarian_shadows()`
- `daredevil_shadows.py`: 重命名为 `momentum_shadows.py`（或保留文件名但改内容为 4 Momentum）

### 11.5 Phase 4: 运行时

**文件**: `shadow_mother.py`, `ranking_engine.py`, `challenger_engine.py`
- shadow_mother: 添加阶段1/2/3 时序 + `ConsensusExtractor` 调用
- ranking: 类型感知评估窗口 + 组件权重 + dormant 跳过
- challenger: 体制检测 + 两层级免疫 + 诊断挑战者

### 11.6 Phase 5: 新模块

**文件**: `diversity_controller.py`, `consensus_extractor.py` (新建)
- diversity_controller: MMC 折扣 + 权重地板 (~150行, 0 LLM)
- consensus_extractor: Expert 方向提取 + 一致率计算 (~80行, 0 LLM)

### 11.7 Phase 6: DB 迁移（解决红方 C2 + M4）

使用**显式映射表**，不用 LIKE 模糊匹配：

```python
SHADOW_ID_MIGRATION = {
    # Momentum (原 daredevil 中的顺势 4 个)
    "daredevil:intraday:scalper":       ("momentum:intraday:scalper",       "momentum"),
    "daredevil:weekly:trend_rider":     ("momentum:weekly:trend_rider",     "momentum"),
    "daredevil:event:news_hound":       ("momentum:event:news_hound",       "momentum"),
    "daredevil:sector:rotation_engine": ("momentum:sector:rotation_engine", "momentum"),
    # Contrarian (原 daredevil 中的逆向 4 个)
    "daredevil:contrarian:fade_master":   ("contrarian:consensus:fade_master",    "contrarian"),
    "daredevil:range_bound:sideways_scout": ("contrarian:range_bound:sideways_scout", "contrarian"),
    "daredevil:panic:vol_surfer":         ("contrarian:panic:vol_surfer",          "contrarian"),
    "daredevil:crash:hunter":             ("contrarian:crash:hunter",              "contrarian"),
}
```

迁移步骤:
1. **Dry-run**: `SELECT old_shadow_id, new_shadow_id, new_shadow_type FROM migration_map`——操作员审查
2. **Backup**: 复制 `shadows.db` → `shadows.db.pre_migration`
3. **Execute**: `UPDATE shadows SET shadow_id = ?, shadow_type = ? WHERE shadow_id = ?`
4. **Verify**: 断言 0 个 `daredevil:` shadow_id 残留
5. **Clean**: 从 `_VALID_TYPES` 移除 `"daredevil"`
6. **Rollback** (如有必要): `UPDATE shadows SET shadow_id = ?, shadow_type = 'daredevil' WHERE shadow_id = ?`（逆映射）

### 11.8 测试

预估新增 ~100 tests:
- `test_contrarian_shadows.py`: 4 Contrarian 创建 + 触发逻辑 + dormant
- `test_momentum_shadows.py`: 4 Momentum 更新
- `test_diversity_controller.py`: MMC 公式 + 边界
- `test_consensus_extractor.py`: 方向提取 + 一致率
- `test_regime_detection.py`: 四级体制 + 滞后
- `test_immunity_logic.py`: 两级免疫 + 递减 + 诊断挑战者
- `test_degradation.py`: 降级矩阵 + 断路器

---

## 12. 风险评估（更新）

| # | 风险 | 严重度 | 缓解 |
|:--:|------|:---:|------|
| R1 | DB 迁移破坏数据 | HIGH | 显式映射表 + dry-run + backup + rollback |
| R2 | Contrarian 只有 4 成员，样本小 | MEDIUM | 可通过 Temp 扩展；4 足够建立基准 |
| R3 | 免疫被滥用（逐月递减后仍有 4 个月窗口） | LOW | 回撤上限永不暂停 → 激进冒险会触发 PAUSE |
| R4 | 多样性折扣压制好影子 | LOW | 折扣区间 [0.85, 1.15] + 权重地板 2% |
| R5 | 决策融合过早实现 | LOW | Gate 3 多条件门控 |
| R6 | 全球扫描 Contrarian 数据稀疏（新兴市场数据可得性参差不齐） | LOW | 按信号质量而非交易频率评估；数据不可得的市场从扫描清单中剔除 |
| R7 | Fade Master 第二遍运行增加延迟 | LOW | 仅在 Expert 全部完成后运行；ConsensusExtractor 是纯 Python |

---

## 13. 成功标准

- [ ] 24 影子按策略原型重新分类：16 Expert + 4 Momentum + 4 Contrarian
- [ ] shadow_id 完全迁移（0 个 `daredevil:` 前缀残留）
- [ ] Contrarian "敢死队" 4 成员：独立配置、独立基准、两级免疫
- [ ] 四级体制检测 + 滞后规则
- [ ] Diversity Controller（≤150行纯Python）
- [ ] ConsensusExtractor（≤80行纯Python + 时序协调）
- [ ] Decision Fusion 规范 + 自动验证步骤
- [ ] Graceful Degradation 矩阵 + 系统级断路器
- [ ] DB 迁移脚本 + dry-run + rollback
- [ ] 所有 1272 现有测试通过（无回归）
- [ ] ~100 新测试
