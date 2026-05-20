# 影子生态系统最终方案

**版本**: 4.0 Final
**日期**: 2026-05-20
**状态**: 权威参考文档 —— 取代所有此前碎片化文档
**整合来源**: 7份设计文档 + 5份研究Batch 1报告 + 3份研究Batch 2报告 + 外部GitHub探索 + 日内研究
**语言**: 中文（本文件为影子生态系统的唯一权威定义）

---

## 目录

1. [执行摘要与设计原则](#1-执行摘要与设计原则)
2. [影子类型体系](#2-影子类型体系)
3. [完整影子名册](#3-完整影子名册)
4. [影子-主管道关系](#4-影子-主管道关系)
5. [每日运营周期](#5-每日运营周期)
6. [信息架构](#6-信息架构)
7. [记忆与持久化](#7-记忆与持久化)
8. [毕业体系](#8-毕业体系)
9. [渐进式评估窗口](#9-渐进式评估窗口)
10. [毕业后监控](#10-毕业后监控)
11. [Gate 2 交互机制](#11-gate-2-交互机制)
12. [自循环进化生态](#12-自循环进化生态)
13. [敢死队详细设计](#13-敢死队详细设计)
14. [ShadowDecision 数据结构](#14-shadowdecision-数据结构)
15. [体制检测与免疫机制](#15-体制检测与免疫机制)
16. [毕业体系补充](#16-毕业体系补充)
17. [成本治理与API预算](#17-成本治理与api预算)
18. [迁移计划](#18-迁移计划)
19. [实施构建顺序](#19-实施构建顺序)

---

## 1. 执行摘要与设计原则

### 1.1 影子生态的定位

影子生态是MarketMind平台的**独立R&D实验室**。24个AI影子作为虚拟基金经理，各自管理虚拟投资组合，在完全自主的竞争生态中运行。影子产出独立投资决策（ShadowDecision），参与内部排名竞争，通过毕业考试获得与用户在Gate 2对话的资格——但永远不直接影响主管道的真实投资决策。

```
影子生态 = R&D 实验室（核心目的 A：策略研究与方法论进化）
  → 通过第二意见机制影响用户（输出 B：Gate 2 研究参考）
  → 毕业后才能参与 Gate 2（有门槛的 B）
  → 不替代主管道，不自动参与决策
```

### 1.2 核心设计原则

| # | 原则 | 含义 |
|:--:|------|------|
| P1 | **策略原型分类** | 按 Fundamental/Momentum/Contrarian 组织，不按风险水平。风险是中央风控的正交约束。对标 Millennium/Citadel 的 pod-shop 架构。 |
| P2 | **独立基金经理** | 每个影子是独立虚拟基金经理，做投资决策（不是投票）。ShadowDecision 不是 ShadowVote。 |
| P3 | **每日必决策** | 所有影子每天必须产出投资决策。不确定时以 $100 最小仓位表达方向，thesis 注明 "MIN_POSITION:UNCERTAIN"。 |
| P4 | **全球无限制** | 影子标的全球可交易资产。只有主管道受 Robinhood 约束。Contrarian 影子全球扫描 15+ 指数寻找机会。 |
| P5 | **用户是唯一桥梁** | 影子与主管道不自动通信。用户在 Gate 2 是唯一信息交汇点。系统架构层强制隔离——对标 Millennium "中国墙"。 |
| P6 | **自循环进化** | 排名、挑战者淘汰、知识结晶、方法论变异——全自动，用户不参与日常管理。6层进化体系确保生态持续优化。 |
| P7 | **质量优先成本** | 影子主分析全用 DeepSeek Pro。Flash 仅用于分类/格式化。纯 Python 替代一切可替代的 LLM 调用。 |
| P8 | **独立性多层保障** | 同一 DeepSeek 模型内通过 Persona + 温度 + 数据切片 + 推理框架实现有意义分歧。东京大学研究(arXiv 2411.19515)证明同模型内不同Persona可产生有意义预测分歧。 |
| P9 | **无任期原则** | 对标 Millennium/Citadel——即使 Elite 300 天，今天触发降级条件今天暂停。毕业不是终身成就。 |
| P10 | **审计完整性** | 审计日志 SHA-256 哈希链保护。仅追加写，无修改/删除 API。每次启动验证链完整性。 |

### 1.3 关键设计决策（不可更改）

| # | 决策 | 结论 |
|:--:|------|------|
| 1 | 分类维度 | 策略原型 (Fundamental/Momentum/Contrarian) |
| 2 | 影子标的 | 全球无限制 |
| 3 | 输出类型 | ShadowDecision（不是投票） |
| 4 | 决策融合 | **删除**——不存在。generate_decision() 不接受影子数据 |
| 5 | 主管道关系 | 不直接通信，用户是唯一桥梁 |
| 6 | 每日要求 | 所有影子每天必须决策，min $100 |
| 7 | 全球扫描 | 无休眠——全球找机会。Contrarian 影子扫描 15+ 全球指数 |
| 8 | LLM 选择 | 影子分析全部 Pro；Flash 仅分类/格式化 |
| 9 | 独立性 | 同一 DeepSeek 内通过 Persona+温度+数据切片+推理框架区分 |
| 10 | ConsensusExtractor | 唯一跨影子例外（R0规则）——仅传递方向标签+百分比（纯Python统计量），不传递任何影子个体分析内容 |
| 11 | CollusionDetector | 重命名为 ConcentrationDetector（集中度检测器） |
| 12 | 成就阶梯 | 百分位+连续天数制（非绝对指标） |
| 13 | 体制免疫 | 按影子实际交易市场独立判定（非全局SPX基准） |
| 14 | 孤儿信号 | 影子淘汰时 pending_signals 转移至 system owner 继续检查 |
| 15 | API预算 | 测试后校准（非预先固定数字） |

---

## 2. 影子类型体系

### 2.1 三类型架构

```
Fundamental (16)     Momentum (4)        Contrarian "敢死队" (4)
领域专家              动量/趋势             逆向/均值回归

始终活跃              始终活跃              全球扫描条件触发（大多数交易日活跃）
τ=0.30-0.40          τ=0.40-0.50          τ=0.45-0.60
90天评估窗口          75天评估窗口           252天评估窗口
回撤上限 ≤25%         回撤上限 ≤30%          回撤上限 ≤35-40%
min 5笔交易           min 50笔交易           min 25-50笔交易（按类型分层）
```

### 2.2 固定影子类型（7种形态）

```python
_VALID_TYPES = {
    "expert",        # Fundamental: 领域专家，基本面分析
    "momentum",      # Momentum: 趋势延续，正反馈
    "contrarian",    # Contrarian: 均值回归，负反馈
    "temp_event",    # 临时事件影子（动态，≤30天）
    "challenger",    # 挑战者（动态，不可见）
    "missed_path",   # 反事实追踪（动态，只读）
    "beta",          # 实验性影子（隔离，不排名）
}
# 移除: "daredevil"（拆分为 momentum + contrarian）, "catfish"（已废弃）

_VALID_STATUSES = {
    "active", "beta", "retired", "paused",
    "watch", "endangered", "eliminated",
    "dormant",  # 全球扫描后零市场触发（极罕见，非正常状态）
}
```

### 2.3 动态影子类型

| 类型 | 触发条件 | 生命周期 | 说明 |
|------|------|------|------|
| `temp_event` | EventDetector 检测到 E1(央行冲击)/E2(地缘)/E3(波动率冲击)/E4(人事变动) | ≤30天 | 事件驱动临时影子，资本$10K-$20K |
| `challenger` | 目标影子连续2-3期排名底部20% | 直到2周对比试验结束 | 秘密竞争，对目标不可见 |
| `missed_path` | Gate 1 方向确认后 | 30天报告期 | 反事实追踪，只读，不产生交易 |
| `beta` | 手动创建 | 隔离期 | 实验性影子，不排名，不参与集中度检测 |

---

## 3. 完整影子名册

### 3.1 Fundamental — 16 领域专家（策略原型：基本面估值 + 领域专业知识）

| shadow_id | 中文名 | 领域 | 虚拟资本 | τ | 性格 |
|------|------|------|------|:--:|------|
| `expert:gold:bullion_broker` | 黄金捕手 | 贵金属（金、银、铂） | $50K | 0.30 | 稳重保守——黄金是千年货币，不值得为几个点去赌方向 |
| `expert:crypto:chain_oracle` | 链上先知 | 加密货币（BTC、ETH、DeFi） | $45K | 0.35 | 新锐敏锐——链上不会说谎，但人会 |
| `expert:energy:oil_geologist` | 石油地质学家 | 能源（原油、天然气、成品油） | $50K | 0.30 | 务实粗犷——地底下的事情，别想当然 |
| `expert:bonds:yield_whisperer` | 收益率耳语者 | 固定收益（国债、企业债、利率） | $55K | 0.30 | 宏观敏感——收益率曲线比任何经济学家都诚实 |
| `expert:vol:vega_trader` | 波动率交易员 | 波动率（VIX、期权、波动率曲面） | $40K | 0.40 | 冷静精准——别人恐慌他算数，别人贪婪他也算数 |
| `expert:em:frontier_scout` | 新兴市场侦察兵 | 新兴市场（中国、印度、巴西等） | $45K | 0.35 | 胆大心细——敢去别人不敢去的地方，但带好地图 |
| `expert:tech:silicon_oracle` | 硅谷神谕 | 科技（半导体、AI、云计算、软件） | $50K | 0.30 | 前瞻激进——技术革命不容错过，但泡沫也同样危险 |
| `expert:financials:bank_examiner` | 银行审计官 | 金融（银行、保险、券商） | $48K | 0.30 | 审慎周密——银行的资产负债表他比行长还清楚 |
| `expert:healthcare:trial_reviewer` | 临床审查员 | 医疗健康（制药、生物科技、医疗器械） | $48K | 0.30 | 证据导向——三期数据没出来之前，什么都是猜测 |
| `expert:consumer:wallet_watcher` | 钱包观察员 | 消费（零售、电商、奢侈品） | $46K | 0.30 | 接地气——消费者口袋里的钱才是真正的宏观指标 |
| `expert:industrials:factory_floor` | 车间主任 | 工业（制造业、航空航天、运输） | $48K | 0.30 | 务实沉稳——工厂不会骗人，开工率就是真相 |
| `expert:metals:steel_trader` | 钢铁交易员 | 工业金属（铜、铁矿石、铝、锌） | $42K | 0.35 | 周期敏感——工业金属是经济的晴雨表 |
| `expert:agriculture:harvest_seer` | 丰收先知 | 农产品（谷物、油籽、牲畜、软商品） | $42K | 0.35 | 耐心等待——天气急不得，庄稼有它的节奏 |
| `expert:realestate:reit_analyst` | REIT 分析师 | 房地产（REITs、住宅、商业地产） | $48K | 0.30 | 扎实稳重——不动产的核心就在"不动"两个字 |
| `expert:fx:currency_dealer` | 外汇交易员 | 外汇（主要货币对、利差交易） | $44K | 0.35 | 全球视野——汇率的背后是国家之间的博弈 |
| `expert:macro:cycle_reader` | 周期之眼 | 宏观/跨资产 | $60K | 0.30 | 大局观——别人看树，他看森林。资本最雄厚，风险最分散 |

**评估配置**: 90天窗口，MPPM 0.35 / Calmar 0.25 / Omega 0.20 / WinRate 0.20

### 3.2 Momentum — 4 动量/趋势（策略原型：趋势延续、正反馈）

| shadow_id | 中文名 | 策略 | 持有期 | 虚拟资本 | τ | 性格 |
|------|------|------|------|------|:--:|------|
| `momentum:intraday:scalper` | 日内猎手 | 日内动量突破 | 1-3天 | $25K | 0.50 | 快进快出——手速是他的Alpha。所有影子中换手率最高 |
| `momentum:weekly:trend_rider` | 趋势骑士 | 周线趋势跟随 | 5-15天 | $30K | 0.40 | 耐心果断——不预测趋势何时开始，只判断现在是什么方向 |
| `momentum:event:news_hound` | 事件猎犬 | 事件驱动追入 | 1-5天 | $25K | 0.45 | 嗅觉敏锐——闻到血腥味就出发，不犹豫 |
| `momentum:sector:rotation_engine` | 轮动引擎 | 行业板块轮动 | 5-20天 | $30K | 0.40 | 策略至上——不赌个股，赌资金流向哪个行业 |

**评估配置**: 75天窗口，MPPM 0.30 / Calmar 0.30 / Omega 0.15 / WinRate 0.25
**免疫**: 区间市场（RANGE_BOUND）下动量损失不触发淘汰

### 3.3 Contrarian "敢死队" — 4 逆向/均值回归（策略原型：均值回归、负反馈）

| shadow_id | 中文名 | 触发条件 | 激活频率 | 虚拟资本 | τ | 回撤上限 |
|------|------|------|:--:|------|:--:|:--:|
| `contrarian:consensus:fade_master` | 共识逆向者 | 始终活跃（每日） | 高 | $20K | 0.55 | 35% |
| `contrarian:range_bound:sideways_scout` | 区间猎手 | 全球扫描：15+指数中寻找区间市场 | 高 | $25K | 0.45 | 30% |
| `contrarian:panic:vol_surfer` | 恐慌冲浪者 | 全球扫描：任一主要波动率指数飙升 | 中 | $30K | 0.60 | 40% |
| `contrarian:crash:hunter` | 泡沫猎手 | 全球扫描：任一地区 ≥2 bubble信号 | 中 | $30K | 0.50 | 40% |

**敢死队共同DNA**:
- 均值回归假设——极端状态不可持续，最终回归均衡
- 逆向入场——在最拥挤/最恐慌/最泡沫时入场
- 全球扫描——全球总有符合策略原型的市场，不局限于美国
- 极限位置触发——各自定义"极端"的具体标准（跨市场适用）
- 长周期评估——252天窗口（DeBondt-Thaler 框架）
- 高波动容忍——逆向入场 = 浮亏常态
- 免疫保护——趋势市场中损失不触发淘汰（结构性预期）
- 回撤强制——即使免疫期间，回撤上限**永不暂停**

**评估配置**: 252天窗口，MPPM 0.20 / Calmar 0.25 / Omega 0.35 / WinRate 0.20（含 Brier Score 额外惩罚）
**免疫**: 趋势市场（TRENDING）下逆向损失不触发淘汰

**最低交易数（按激活频率分层）**:
- Fade Master: 50笔（始终活跃，激活率要求 ≥50%）
- Sideways Scout: 40笔（全球扫描大幅提升激活频率）
- Vol Surfer: 30笔（全球扫描大幅提升激活频率）
- Crash Hunter: 25笔（全球扫描大幅提升激活频率）

### 3.4 四种触发模式的对比

| 成员 | 触发模式 | 激活频率 | 寻找的"极端" |
|------|:--:|:--:|------|
| Fade Master | 每日主动 | 高 | **情绪极端**——共识过于拥挤 |
| Sideways Scout | 全球扫描 | 高 | **波动极端**——市场过于安静 |
| Vol Surfer | 全球扫描 | 中 | **恐慌极端**——市场过于恐惧 |
| Crash Hunter | 全球扫描 | 中 | **估值极端**——市场过于昂贵 |

四种极端状态分别探测：**过度一致、过度安静、过度恐慌、过度昂贵**。当四个同时激活时，是最强的逆向信号。

### 3.5 影子之间的天然对冲

- **基本面专家** → 提供领域深度和共识基准。16人各有专长，他们的一致/分歧本身就是信号
- **动量影子** → 在趋势市场中赚钱，在区间市场中亏钱。和敢死队天然对冲（相关性 -35%）
- **敢死队** → 在极端位置逆向入场，在趋势市场中亏钱。是动量影子的天然对冲

---

## 4. 影子-主管道关系

### 4.1 架构隔离

```
                  新闻 + 市场数据
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
    ┌──────────┐            ┌──────────────┐
    │  主管道   │            │   影子生态     │
    │ (决策者)  │            │   (研究者)     │
    │          │            │               │
    │ Scout    │            │ 24个独立分析师  │
    │ Flash    │            │ 各自做投资决定   │
    │ HVR      │            │ 管理虚拟账户    │
    │ L1/L2/L3 │            │ 排名系统评估    │
    │ Red Team │            │               │
    │ Decision │            │               │
    └────┬─────┘            └───────┬───────┘
         │                          │
         │  最终决策                 │  研究输出
         │  (Robinhood)             │  (参考)
         │                          │
         └──────────┬───────────────┘
                    ▼
              Gate 2 (用户)
              用户看到两边独立分析
              用户做最终判断
```

### 4.2 通信规则

| 方向 | 内容 | 是否自动 | 说明 |
|------|------|:--:|------|
| 数据 → 影子 | 原始新闻 + 市场数据 | 是 | — |
| 数据 → 主管道 | 原始新闻 + 市场数据 | 是 | — |
| **R0** | ConsensusExtractor 聚合 Expert 方向 → Fade Master | 是 | **唯一跨影子例外**: 仅传递方向标签+百分比(纯Python统计量)，不传递任何影子个体分析内容 |
| 影子 → 主管道 | **无直接路径** | 否 | generate_decision() 不接受影子数据 |
| 影子 → 用户 | Shadow Research Feed (Gate 2) | 是(毕业后) | — |
| 主管道 → 影子 | **无直接路径** | 否 | — |
| 用户 → 影子 | 结构化 Q&A (Gate 2) | 手动(毕业后) | — |

### 4.3 为什么不自动通信

- **防止锚定**: 主管道看到影子结论 → 被锚定
- **防止污染**: 影子看到主管道结论 → 失去独立性
- **可审计**: 两边分析链条完全独立
- **用户是最终决策者**: 两边都是工具，用户做最终判断

### 4.4 信息隔离设计（对标 Millennium "中国墙"）

```
系统架构层强制隔离:
  - 影子之间: 0 通信路径（无消息传递、无共享输出可见性）
  - 影子 ↔ 主管道: 0 自动通信（只有用户手动桥接）
  - 用户可见: 两边各自的独立输出

BlackRock 拥挤警告应用:
  - ConcentrationDetector 监控影子输入同质化
  - 当 ≥ 50% 影子依赖相同主数据源 → 警告
  - 每影子必须有独特的信息源指纹
```

---

## 5. 每日运营周期

### 5.1 完整日循环

```
每日启动
  │
  ├── Startup Protocol（记忆注入，6步）
  │   ├── Step 1: 加载市场上下文（经济日历、隔夜变动、突发新闻）
  │   ├── Step 2: 加载待确认信号注册表 → 自动检查触发/过期
  │   ├── Step 3: 加载情景记忆（90天，Ebbinghaus衰减加权）
  │   ├── Step 4: 加载语义记忆（结晶知识、方法论统计）
  │   ├── Step 5: 生成个性化 Daily Briefing（per shadow，3200 token预算）
  │   └── Step 6: 开始正常分析流程
  │
  ├── Phase 1: 并行分析（阶段1）
  │   ├── 16 Expert + 4 Momentum + 3 全球扫描 Contrarian
  │   ├── 所有影子独立分析，不互读
  │   └── 产出 ShadowDecision[]
  │
  ├── Phase 2: 共识提取（纯Python, 0 LLM 调用）
  │   ├── ConsensusExtractor 计算 Expert 方向一致率
  │   ├── 有效性: ≥12 Expert→FULL; 8-11→DEGRADED; <8→SKIP
  │   └── 输出: consensus_direction + agreement_pct
  │
  ├── Phase 3: Fade Master 分析（阶段2）
  │   ├── 接收共识统计(FULL/DEGRADED/SKIP) → 独立逆向决策
  │   └── SKIP 时仅使用外部情绪数据
  │
  ├── 虚拟交易执行
  │   ├── ShadowDecision → VirtualTrade 记录
  │   ├── 虚拟滑点应用（ATR * 0.5%）
  │   └── 置信度折扣应用（基准20%，下限5%）
  │
  ├── 排名与评估
  │   ├── 类型感知复合评分（不同类型不同权重）
  │   ├── 多样性折扣 (DPP + EARCP + MMC)
  │   ├── Lexicase 体制覆盖预选
  │   └── 成就阶梯更新
  │
  ├── 生态审计
  │   ├── 集中度检测 (ConcentrationDetector)
  │   │   ├── 方向一致率 >80% 连续3天 → 警告
  │   │   └── 体制感知阈值: RANGE_BOUND=70%, TRENDING=80%, CHOPPY/VIX>35=95%
  │   ├── 生态系统盲点扫描 (EcosystemAuditor)
  │   │   └── 方向集中/资产类别忽视/方法论收敛/未覆盖标的
  │   └── 体制检测 + 免疫更新
  │
  ├── 进化机制
  │   ├── Challenger 淘汰检查（WARNING→CHALLENGER→COMPARISON→REPLACE/RESTORE）
  │   ├── Crystallization 结晶（Insight→Hypothesis→Tweak→Validate→Promote）
  │   ├── 方法论变异（LLM语义变异 + 几何编译变异 + TreEvo树形交叉）
  │   └── 知识继承（PKT蒸馏 + TIES-Merging + EWC弹性固结）
  │
  └── 每日快照归档
      ├── DailySnapshot 写入 SQLite
      ├── 排名历史追加
      └── 审计日志 SHA-256 哈希链追加
```

### 5.2 时间维度：日/周/月/事件触发

**每日**:
- Scout 新闻采集（~587 篇文章）
- ShadowMother 扫描事件（检测 E1-E4 触发器）
- 所有活跃影子执行独立分析
- 虚拟交易执行 + 持仓更新
- 排名计算 + 成就等级更新
- 集中度检测 + 生态系统审计
- 每日快照写入
- 数据预取清单 P01-P13 自动拉取（启动时）

**每周**:
- 挑战者阶段检查（评估连续底部周期计数）
- 方法论衰减检查（decay_factor 更新）
- 平稳期检测（全影子扫描）
- MissedPath 报告生成（30天期满时）
- Temp Shadow 销毁条件检查
- 成本报告生成 → `.claude/audits/cost-{week}.json`

**每月**:
- 方法论报告生成（全影子汇总）
- 知识结晶外循环（显著性门检查）
- 虚拟资本再分配评估
- 配额调整评估（永久增减）
- 免疫状态审查（市场状态重分类）
- 对抗性体制冲击测试（或极端事件触发）

**事件触发（异步）**:
| 事件 | 触发条件 | 动作 |
|------|------|------|
| E1: 央行冲击 | 利率预期偏离 ≥ 50bp | 创建 Temp Shadow |
| E2: 地缘风险 | VIX 比率 ≥ 1.5 | 创建 Temp Shadow |
| E3: 波动率冲击 | 单一资产 24h return ≥ 5σ | 创建 Temp Shadow |
| E4: 人事变动 | 关键词命中 | 创建 Temp Shadow |
| 大额盈亏 | 盈亏 > $1,000 或 10% | 触发 Reflection Agent |
| 止损触发 | 止损条件满足 | 虚拟交易退出 + 复盘 |
| CC3+: 阶段升级 | 影子进入 Stage 3 | 启动 2 周对比试验 |
| SAFE_MODE | 3+ 组件故障 | 全系统暂停交易 |

---

## 6. 信息架构

### 6.1 四层数据架构

#### Layer 1 — 免费优先（零成本，即刻接入）

| 数据源 | 提供内容 | 服务影子 | 接入方式 |
|--------|----------|----------|----------|
| **yfinance** | 全球 15+ 主要指数 OHLCV、波动率指数、ETF | 全部 24 个影子 | Python 库，无需 API Key |
| **FRED API** | 800K+ 美国宏观序列（GDP、CPI、失业率、利率、CAPE） | 大部分 Expert | 免费 API Key，120 req/min |
| **EIA API** | 原油/天然气库存、产量、价格 | Oil Geologist | 免费 API Key |
| **USDA FAS PSD API** | 全球农产品供需月度数据 | Harvest Seer | 免费，无需 Key |
| **DeFiLlama API** | 加密 TVL、稳定币供应、DEX 交易量 | Chain Oracle | 免费，无需 Key |
| **CFTC COT** | 期货持仓报告（商业/非商业/散户） | Fade Master、Steel Trader | 免费 CSV 下载 |
| **NOAA NCEI API** | ENSO 指数、全球气候模式 | Harvest Seer | 免费 API Key |
| **openFDA API** | 药品审批历史、召回、不良事件 | Trial Reviewer | 免费，240 req/min |
| **Ken French Data Library** | Fama-French 五因子 + 动量因子 + 行业组合 | 所有 Contrarian 基准、Expert 基准 | 免费 CSV 下载 |
| **Nasdaq Data Link / MULTPL** | Shiller CAPE、Buffett Indicator、Tobin Q | Crash Hunter | 免费（有限配额） |

#### Layer 2 — 免费适配（零成本，需开发工时）

| 数据源 | 提供内容 | 接入工作 | 影子受众 |
|--------|----------|----------|----------|
| **AAII Sentiment** | 散户多空情绪调查（周度） | 网页爬虫 | Contrarian、Crash Hunter |
| **Research Affiliates** | 各国 CAPE 数据 | headless browser 爬虫 | Macro Watcher、Contrarian |
| **siblisresearch** | 多国 CAPE 快照 | 网页爬虫 | Macro Watcher |
| **LME（通过 iTick API）** | 金属库存数据 | API 集成（免费层） | Steel Trader |
| **CoinMetrics Community** | 链上数据（30日历史） | API 集成 | Chain Oracle |
| **AKShare** | A 股行情、融资融券、龙虎榜 | pip install | 关注中国市场的 Expert |
| **nsepy** | India VIX、NSE 数据 | pip install | Frontier Scout |

#### Layer 3 — Freemium（免费配额→按需付费）

| 数据源 | 免费额度 | 升级费用 | 用途 |
|--------|----------|:---:|------|
| **Twelve Data** | 800 req/day | $49.99/mo | 全球价格数据专业备源 |
| **Databento** | $125 免费额度 | 按量计费 | 高频历史 Tick 数据（未来入口） |
| **ShareSeer MCP** | 10-50 req/day | 不定 | 社交媒体情绪、另类数据 |
| **FinancialReports.eu** | 有限免费 | 付费层 | 欧洲公司财报 |

#### Layer 4 — 付费数据（仅在 ROI 验证后启用）

| 数据源 | 费用 | 用途 | 启用条件 |
|--------|:---:|------|------|
| **Glassnode Professional** | ~$999/mo | 深度链上数据 | Chain Oracle Elite + 连续3月正边际收益 + 预估 Sharpe 提升 ≥ 0.15 |
| **WSTS Semiconductor** | ~EUR 11,500/yr | 全球芯片销量月度数据 | Silicon Oracle Elite + 半导体赛道持续超额 |
| **siblisresearch Pro** | 订阅费 | 全球 CAPE 历史序列 | Research Affiliates 爬虫不可用时的备选 |

**付费决策流程**: 影子达到 Elite → 连续 3 月正边际收益 → 数据缺口诊断 → 预估 Sharpe 提升 ≥ 0.15 → Gate 评审批准。

### 6.2 数据质量验证层

在数据传输到影子之前执行（优先于可靠性层）:

1. **日收益率异常**: |日收益率| > 5σ → 标记可疑，启用备用源交叉验证
2. **零量检测**: volume = 0 在交易日 → 标记
3. **OHLC 一致性**: High < max(Open,Close) 或 Low > min(Open,Close) → 标记无效
4. **备用源交叉验证**: 主/备偏差 > 2σ → 两源均标记
5. **异常操作**: 标记 → 自动切换备用源 → 审计事件记录

实现: `pipeline/data_quality_validator.py` (~150行, 纯Python, 0 LLM)

### 6.3 API 调用可靠性架构

所有外部 API 调用统一通过 ReliableAPIClient 包装:
- **超时保护**: 默认 30s，可按源自定义
- **指数退避重试**: 最多 3 次，间隔 1s → 2s → 4s（仅对 TimeoutError、ConnectionError、HTTP 429/503 重试）
- **熔断器**: CLOSED → [连续失败3次] → OPEN (5分钟) → HALF_OPEN → [成功] → CLOSED
- **主/备源自动切换**: 主源重试耗尽后自动切换到备源

### 6.4 数据预取清单（启动时自动拉取）

#### Momentum/Contrarian 数据预取清单（P01-P13）

| # | 数据项 | 频率 | 用途 |
|:--:|------|:--:|------|
| P01 | 全球 15+ 主要指数 OHLCV | 每日 | 全部影子基础数据 |
| P02 | VIX + VIX 期货期限结构 | 每日 | Vega Trader、Vol Surfer、Crash Hunter |
| P03 | SKEW 指数 + VVIX | 每日 | Vega Trader、Crash Hunter |
| P04 | Put/Call 比率（总市场+个股+ETF） | 每日 | Fade Master、Vol Surfer |
| P05 | CFTC COT 持仓（ES/CL/GC/NG + 农产品扩展） | 每周 | Fade Master、Steel Trader、Harvest Seer |
| P06 | AAII 散户情绪（牛熊比） | 每周 | Fade Master、Crash Hunter |
| P07 | CNN 恐惧/贪婪指数 | 每日 | Fade Master |
| P08 | Shiller CAPE + Buffett Indicator | 每日 | Crash Hunter、Cycle Reader |
| P09 | FRED 信用利差（IG OAS + HY OAS） | 每日 | Vol Surfer、Crash Hunter |
| P10 | 市场广度（涨跌比、新高新低比） | 每日 | Vol Surfer、Crash Hunter |
| P11 | 内幕交易聚合（OpenInsider scrape） | 每日 | Crash Hunter |
| P12 | 全球波动率指数（VSTOXX、VNKY、NIFTY50 VIX、KOSPI VIX、HSI Vol） | 每日 | Vol Surfer、Sideways Scout |
| P13 | 全球指数 20 日均线斜率 | 每日 | Sideways Scout（趋势过滤器） |

### 6.5 新闻推送三级分类

| 级别 | 定义 | 推送时机 | 影响影子 |
|:--:|------|------|------|
| **Critical** | 市场移动型人物（6类分类法）发言触发 Ability×Willingness×Acknowledgment 高分 | 即时推送 | 全部相关影子 |
| **High** | 重大数据发布、突发事件 | 15分钟批次 | 领域相关影子 |
| **Low** | 常规新闻、背景分析 | 每日摘要 | 全部影子（领域过滤） |

#### 市场移动型人物 6 类分类法

| 类别 | 示例 | 评分维度 |
|------|------|------|
| **Policymakers** | 央行行长、财政部长 | Ability×Willingness×Acknowledgment 框架 |
| **Political** | 国家元首、贸易谈判代表 | 同上 |
| **Executives** | 上市公司 CEO/CFO | 同上 |
| **Activists** | 激进投资者 | 同上 |
| **Fund Managers** | 大型基金首席投资官 | 同上 |
| **Celebrities** | 影响力巨大的公众人物 | 同上 |

评分框架学术基础: Spence 信号理论、Kartik 昂贵谈话模型、事件研究方法论。

### 6.6 数据菜单与配额系统

每个影子拥有基于数据菜单的配额:
- **基础配额**: 每个影子每日获取领域的核心数据（自动）
- **扩展配额**: 影子可申请额外数据（消耗 Pro 配额）
- **贪婪/恐惧检测**: 影子频繁申请同一方向数据 → 标记"确认偏误风险"
- **数据指纹**: 每影子维护唯一的数据源权重向量 → DiversityController 监控同质化

### 6.7 信息源逐影子覆盖度

| 影子 | 当前覆盖度 | Phase 1-5 后 | 最紧急缺口 |
|------|:---:|:---:|------|
| Bullion Broker | 40% | 85% | FRED 实际利率、WGC 央行购金、GLD ETF 流量 |
| Chain Oracle | 25% | 80% | 链上数据 (DeFiLlama)、BTC ETF 流量、稳定币 |
| Oil Geologist | 45% | 85% | Baker Hughes 钻井数、EIA 天然气存储、裂解价差 |
| Yield Whisperer | 25% | 90% | FRED TIPS 收益率、信用利差、CME FedWatch |
| Vega Trader | 15% | 75% | VIX 期限结构、SKEW、VVIX、P/C 比率 |
| Frontier Scout | 35% | 80% | EMBI 利差、IIF 资本流、DXY |
| Silicon Oracle | 30% | 70% | SIA 半导体出货、TSMC 营收、云服务商 CAPEX |
| Bank Examiner | 35% | 85% | FRED H.8 银行资产、贷款增长、NCO 坏账率 |
| Trial Reviewer | 25% | 75% | FDA 审批日历、ClinicalTrials.gov、CMS 定价 |
| Wallet Watcher | 30% | 85% | 密歇根情绪、零售销售、AAII |
| Factory Floor | 30% | 80% | ISM PMI、耐用品订单、SCFI 运费 |
| Steel Trader | 20% | 75% | LME 库存/价格、SHFE 库存、中国 PMI |
| Harvest Seer | 15% | 80% | USDA WASDE、CFTC 农产品 COT、ENSO 预报 |
| REIT Analyst | 20% | 85% | 房屋开工、Case-Shiller、抵押利率 |
| Currency Dealer | 40% | 85% | BIS 有效汇率、利差计算、TIC 数据 |
| Cycle Reader | 50% | 95% | FRED GDP/PCE/NFCI、全球 PMI、Shiller CAPE |
| Intraday Scalper | 10% | 60% | 日内 OHLCV (Polygon/Alpaca)、VWAP |
| Trend Rider | 20% | 65% | 日线 OHLCV、ETF 资金流 |
| Event Hound | 45% | 75% | 盈利数据库、Econoday 日历 |
| Rotation Engine | 35% | 75% | FRED 2s10s 曲线、ETF 资金流 |
| Fade Master | 35% | 85% | AAII 情绪、P/C 比率、CNN 恐惧贪婪 |
| Sideways Scout | 15% | 60% | VIX 数据、波动率计算基础 |
| Vol Surfer | 25% | 85% | VIX 期货结构、市场广度、信用利差 |
| Crash Hunter | 30% | 90% | Shiller CAPE、Buffett Ind.、Hindenburg Omen、内幕交易 |

---

## 7. 记忆与持久化

### 7.1 三层记忆架构

```
Working Memory (~24h)
  - Daily Briefing（每次启动生成）
  - ≤ 3200 tokens（结构化分层）
  - 会话结束后丢弃
        │ 每天沉淀
        ▼
Episodic Memory (~90d)
  - SQLite: 交易决策 + 结果 + 复盘记录
  - Ebbinghaus 衰减加权检索
  - RecMem 启发: 延迟固化——仅相似模式重现时触发 LLM 总结
        │ 统计显著性检验 + OOS 验证
        ▼
Semantic Memory (永久)
  - Crystallization 通过的洞察
  - 方法论有效性统计
  - 可继承知识（PKT 蒸馏传递）— 需 OOS 验证（30天观察期 + 方向准确率 ≥ 50% + 二项检验 p<0.10）
  - ACE 风险评分
  - 验证失败 → "unvalidated"（仍存储，不进入 PKT 可继承池）
```

### 7.2 每日启动协议（6步）

```
Step 1: 加载市场上下文 —— 今日经济日历、隔夜变动、突发新闻

Step 2: 加载待确认信号注册表
  - 查询 status='awaiting' 的信号
  - 自动检查: 信号已触发？→ 标记 'triggered'，通知影子
  - 过期信号 (> 预期日期 7 天) → 标记 'expired'

Step 3: 加载情景记忆（90 天，Ebbinghaus 加权）

Step 4: 加载语义记忆（结晶知识）

Step 5: 生成个性化 Daily Briefing（per shadow）
  结构化分层格式:
    [1] PERSONA & STRATEGY (~150 tokens, 固定)
    [2] CUMULATIVE EXPERIENCE (~600 tokens, 衰减加权)
    [3] PENDING SIGNALS (~400 tokens, 结构化表格)
    [4] TODAY'S MARKET (~800 tokens, 领域过滤)
    [5] INSTRUCTION (~200 tokens, 关键要求重复)

Step 6: 开始正常分析流程
```

**Lost in the Middle 缓解**: 最重要信息放开头（Persona + Experience）和结尾（Instruction）。中间放数据密集但优先级低的内容（Market）。

### 7.3 待确认信号注册表

```sql
CREATE TABLE pending_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_description TEXT NOT NULL,
    trigger_condition TEXT,
    related_ticker TEXT,
    related_decision_id INTEGER,
    created_date TEXT NOT NULL,
    expected_date TEXT,
    check_frequency TEXT DEFAULT 'daily',
    status TEXT DEFAULT 'awaiting',   -- awaiting/triggered/expired/cancelled
    resolved_date TEXT,
    resolution_notes TEXT,
    impact_on_decision TEXT
);
```

影子在 LLM 输出中声明:
```
WAITING_FOR:
- signal: AAPL Q2 财报; expected: 2026-05-25
  condition: 营收 > $90B → 确认做多逻辑
END_WAITING_FOR
```

### 7.4 Pending Signal 截断规则

待确认信号可能膨胀至 200+ 条目。400 token 预算的截断规则:
1. **预过滤**: 排除 expired 和 cancelled 状态
2. **优先级排序**: priority_score = signal_importance_weight / (days_until_expected_date + 1)，影子声明时的 1-5 评分（默认 3）
3. **截断**: 按 priority_score 降序取前 N 条
4. **关键保护**: expected_date ≤ 3 天的信号被截断 → 系统警告
5. **自动过期**: expected_date 超过 7 天未触发 → 自动标记 expired

### 7.5 持续跟踪事件注册表

```sql
CREATE TABLE event_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    track_topic TEXT NOT NULL,
    track_category TEXT NOT NULL,
    started_date TEXT NOT NULL,
    last_updated_date TEXT NOT NULL,
    check_cadence TEXT DEFAULT 'daily',
    key_metric TEXT,
    current_status TEXT,
    status TEXT DEFAULT 'active'
);
```

### 7.6 边界条件

- **30 天关机**: 批量信号过期，显式"离线通知"。情景记忆可能部分超过 90 天 → 修剪
- **影子淘汰 — 孤儿信号处理**: pending_signals 不取消。所有权转移至 `system`（orphaned 状态），系统继续检查。孤儿信号触发时记录 `retroactive_hit` 事件。月度"过早淘汰审计"聚合 retroactive_hit，识别被淘汰但方向正确的影子（若某策略类型过早淘汰率 > 30%，Challenger 对比期自动延长）
- **记忆溢出**: 按新近度 + 重要性截断
- **首次启动**: 无情景记忆 → 仅加载 Persona + 今日数据 + 空信号列表

---

## 8. 毕业体系

### 8.1 核心理念

影子不是选民，是独立基金经理。毕业不是"投票权"的授予，而是**"与用户对话的资格"**。毕业标准衡量影子作为独立决策者的综合投资能力，而非与群体的吻合度。

```
未毕业影子:
  - 生态内部分析 → 仅用于排名、结晶、方法论进化
  - 对用户完全不可见

已毕业影子:
  - 保留生态内部分析职责
  - 获得 Gate 2 中被用户看到和召唤的权限
  - 每次 Gate 2 会话最多贡献一次，标记为"影子意见"，无决策权
  - 持续接受毕业后监控（CUSUM/CUSUMSQ/BOCPD）——表现下滑可被降级
```

### 8.2 成就阶梯与毕业的关系

成就阶梯是**生态内部**的相对排名（Elite/Excellent/Watch/Endangered），毕业是**绝对门槛**:

| 成就阶梯（内部） | 毕业体系（外部） |
|------|------|
| Elite | 可以参加毕业考试 → Gate 2 资格 |
| Excellent | 可以参加毕业考试 → 基础能力认证 |
| Watch | 不能参加毕业考试 |
| Endangered | 不能参加毕业考试 |

**前置条件**: 影子必须先达到 Elite 或 Excellent 才能参加毕业考试。**不是自动毕业**: 等级达标 ≠ 毕业。毕业 = Tier 1 + Tier 2 + 压力测试全部通过。

### 8.3 成就阶梯定义（类型特定百分位 + 连续天数）

| 阶梯 | Expert | Momentum | Contrarian |
|------|:--:|:--:|:--:|
| **Elite** | 85%ile + 30天 | 85%ile + 20天 | 85%ile + 60天 |
| **Excellent** | 70%ile + 10天 | 70%ile + 7天 | 70%ile + 20天 |
| **Watch** | <30%ile + 10天 | <30%ile + 7天 | <30%ile + 30天 |
| **Endangered** | <15%ile + 20天 | <15%ile + 14天 | <15%ile + 40天 |

### 8.4 毕业框架总览

```
新影子入职
    │
    ▼
观察期（Expert 90天 / Momentum 75天 / Contrarian 252天）
    │
    ▼
Tier 1: 基础能力认证（所有影子相同）
  - 胜率 ≥ 类型阈值 AND 收益率 > 0
  - Brier 分解：Eagle 或 Bull
  - 最低交易数达标 AND 最大回撤未触及上限
    │ 通过
    ▼
Tier 2: 类型专项卓越
  - 类型特定 Sortino/MAR/GPR/K-Ratio 阈值
  - 超越独立基准（配对 t 检验 α=0.10）
  - 跑赢主流水线（仅当主管道在影子领域有实际交易时对比）
    │ 通过
    ▼
压力测试: 2008 GFC / 2020Q1 COVID / 2022 加息冲击
    │ 通过
    ▼
Gate 2 资格激活 → 毕业后监控启动
```

### 8.5 Tier 1：基础能力认证

| 指标 | Expert | Momentum | Contrarian |
|------|:--:|:--:|:--:|
| **胜率** | ≥ 52% | ≥ 48% | ≥ 45% |
| **总收益率** | > 0% | > 0% | > 0% |
| **Brier Score 分解** | Eagle/Bull | Eagle/Bull | Eagle/Bull |
| **最低交易数** | ≥ 5 | ≥ 50 | ≥ 25-50（按类型分层） |
| **最大回撤** | < 25% | < 30% | < 35-40% |
| **Abstention 率** | ≤ 20% | ≤ 15% | ≤ 25% |

**Contrarian 最低交易数分层**: Fade Master 50, Sideways Scout 40, Vol Surfer 30, Crash Hunter 25。

### 8.6 Tier 2：类型专项卓越

| 指标 | Expert | Momentum | Contrarian | 公式 |
|------|:--:|:--:|:--:|------|
| **Sortino** | ≥ 0.5 | ≥ 0.3 | ≥ 0.25 | (Rp-Rf)/DownsideDev |
| **MAR** | ≥ 0.8 | ≥ 0.5 | ≥ 0.4 | CAGR/|MaxDD| |
| **GPR** | ≥ 1.5 | ≥ 1.2 | ≥ 1.0 | Σ收益/Σ|亏损| |
| **K-Ratio** | ≥ 0.4 | ≥ 0.3 | ≥ 0.25 | Slope(VAMI)/SE(Slope) |
| **超越基准** | 领域ETF | SG Trend Index | Fama-French LT Rev |
| **跑赢主流水线** | 必须 | 必须 | 必须 |

**反博弈规则**: 
- Tier 2 的年化收益率必须 > 无风险利率 + 2%（绝对值，非比率）。
- 单笔最大盈利占总收益 > 50% → 审查标记（SINGLE_TRADE_DEPENDENT）
- Min-bet（≤$100）交易占比 > 60% → 降权处理（Sortino/MAR 打 0.7 折）
- 防止小额高胜率策略系统性压低风险指标分母。

### 8.7 概率校准管道

```
原始置信度 → Venn-Abers 校准器 → Brier 三元分解 (MCB/DSC/UNC) → Manokhin 概率矩阵
```

#### Brier 分解公式
BS = MCB + DSC - UNC（Dimitriadis "The Triptych", arXiv:2301.10803）

#### Manokhin 概率矩阵

| 原型 | 校准 | 区分力 | 毕业资格 |
|------|:--:|:--:|:--:|
| **Eagle（鹰）** | 好 | 强 | 直接通过 |
| **Bull（牛）** | 差 | 强 | 后校准修复后通过 |
| **Sloth（树懒）** | 好 | 弱 | 需改进区分力 |
| **Mole（鼹鼠）** | 差 | 弱 | 需全面改进 |

### 8.8 领域基准映射（16 Expert）

| # | 影子 | 主基准 | 辅助基准 |
|:--:|------|------|------|
| 1 | Bullion Broker | **GLD** | SLV, GDX |
| 2 | Chain Oracle | **BTC+ETH** 等权 | BITW |
| 3 | Oil Geologist | **XLE** | USO, UNG |
| 4 | Yield Whisperer | **AGG+TLT** 等权 | LQD |
| 5 | Vega Trader | **VIX Index + VXX** | VXZ |
| 6 | Frontier Scout | **EEM** | EMB, FXI |
| 7 | Silicon Oracle | **QQQ+SMH** 等权 | XLK |
| 8 | Bank Examiner | **XLF** | KRE |
| 9 | Trial Reviewer | **XLV+IBB** 等权 | PJP |
| 10 | Wallet Watcher | **XLY+XLP** 等权 | RTH |
| 11 | Factory Floor | **XLI** | ITA |
| 12 | Steel Trader | **DBB+CPER** 等权 | XME |
| 13 | Harvest Seer | **DBA** | CORN,WEAT,SOYB |
| 14 | REIT Analyst | **VNQ+IYR** 等权 | XLRE |
| 15 | Currency Dealer | **UUP+FXE** 等权 | FXY |
| 16 | Cycle Reader | **SPY/AGG/GLD** (60/30/10) | ACWI |

### 8.9 Contrarian 特定基准

| Contrarian 影子 | 主基准 | 说明 |
|------|------|------|
| **Fade Master** | Fama-French LT Rev + AAII 极端模拟 | 长期反转因子 + 散户情绪极端表现 |
| **Sideways Scout** | Fama-French LT Rev + 区间模拟 | 反转因子 + 区间市场模拟 |
| **Vol Surfer** | CBOE PUT Index | 保护性看跌策略基准 |
| **Crash Hunter** | CBOE SKEW Index + 保护性看跌 | 尾部风险定价 + 对冲策略基准 |

### 8.10 压力测试

| # | 情景 | 回测区间 | Expert/Momentum | Contrarian 高频(Fade/Scout) | Contrarian 低频(Vol/Crash) |
|:--:|------|------|------|------|------|
| 1 | GFC | 2008-09 ~ 2009-03 | 回撤 ≤ 上限*1.5 | **必须正收益** | **条件正收益**（激活条件触发→必须正收益；未触发→免除） |
| 2 | COVID | 2020-02 ~ 2020-03 | 回撤 ≤ 上限*1.5 | **必须正收益** | **必须正收益** |
| 3 | 加息冲击 | 2022-01 ~ 2022-10 | 回撤 ≤ 上限 | 回撤 ≤ 上限 | 回撤 ≤ 上限 |

**Alpha 纯度**: Carhart 4因子（所有影子）+ Fung-Hsieh 7因子（Momentum/Contrarian）。α年化 > 0, t > 1.65。**风格漂移**: 月度因子暴露变化 ≤ 2σ。连续3月超标 → 降级。

---

## 9. 渐进式评估窗口

### 9.1 核心问题

固定 252 天评估窗口的问题:
- **低 SR 策略**: SR=0.5 需要 2,728 天才能达到统计显著性——固定窗口永远无法证明其有效性
- **高 SR 策略**: SR=1.5 仅需 303 天——固定窗口对它是浪费
- **低频策略**: 交易数不足时评估不可靠

### 9.2 解决方案：渐进式权重解锁

```
50 笔交易门 → 渐进权重解锁（50→384笔交易）→ PSR 显著性标记
```

**交易数 vs 权重解锁表**:

| 交易数 | 窗口权重 | 评估置信度 | 说明 |
|:--:|:--:|:--:|------|
| < 50 | 0 | — | 数据不足，不参与排名 |
| 50-99 | 0.25 | LOW | 初步评估，标记 "insufficient_data" |
| 100-199 | 0.50 | MEDIUM | 有参考价值，权重地板适用 |
| 200-383 | 0.75 | HIGH | 可参与正常排名 |
| ≥ 384 | 1.00 | PSR | 统计显著，完全权重 |

### 9.3 类型特定评估窗口

| 影子类型 | 评估窗口 | 交易数门槛 | 原因 |
|------|:--:|:--:|------|
| **Expert** | 90天 | 5 | 基本面分析的中期验证周期 |
| **Momentum** | 75天 | 50 | 动量策略需要较短窗口 + 高交易频率 |
| **Contrarian: Fade Master** | 252天 | 50 | 始终活跃，交易充足 |
| **Contrarian: Sideways Scout** | 252天（但126天即可初步排名） | 40 | 全球扫描提升频率 |
| **Contrarian: Vol Surfer** | 252天 | 30 | 全球扫描提升频率 |
| **Contrarian: Crash Hunter** | 252天 | 25 | 全球扫描提升频率 |

### 9.4 多频率排名统一

所有指标年化到日频后再比较:
- 使用 Calmar + MaxDD 作为频率无关指标
- 换手率按年化换手 = 日均换手 * 252 标准化
- Contrarian 低频影子通过 Omega 比率（尾部不对称性）获得公平比较

### 9.5 日内动量特殊规则

- **双时间点检查**: 开盘 30 分钟后 + 收盘 30 分钟前（日内动量影子 Intraday Scalper）
- **数据拉取间隔**: 30 分钟最优（Gao et al. 2018 对美国市场的研究结论）
- **成本优化**: yfinance 拉取 → 免费指标计算 → Pro 调用仅在有信号触发时
- **增量成本**: ~$1-2/月额外

---

## 10. 毕业后监控

### 10.1 三层监控体系

| 层级 | 方法 | 频率 | 触发动作 |
|------|------|:--:|------|
| Layer 1 | **CUSUM** on P&L | 每日 | 3月5次警报 → 重评估 |
| Layer 2 | **CUSUMSQ** on 残差 | 每日 | 触发 → **立即暂停 Gate 2** |
| Layer 3 | **Score-Driven BOCPD** | 每周 | L3+L1 联合 → 策略重优化 |

**关键参考文献**:
- Hadjiliadis & Vecer (2006): CUSUM 回撤检测
- Brown, Durbin & Evans (1975): CUSUMSQ 方法论断裂
- Tsaknaki et al. (2025): Score-Driven BOCPD 体制检测

### 10.2 降级触发条件（8条）

| # | 条件 | 严重度 | 降级到 | 恢复条件 |
|:--:|------|:--:|:--:|------|
| D1 | CUSUMSQ 触发 | **严重** | SUSPENDED | 方法论修正+30天回测 |
| D2 | CUSUM 3月5次警报 | 高 | DISPLAY_ONLY | 20天无警报+α>0 |
| D3 | BOCPD+CUSUM 联合 | 高 | SUSPENDED | 新策略优于旧 |
| D4 | 降至 Endangered | 高 | SUSPENDED | Challenger 胜出 |
| D5 | 连续3周期 Watch | 中 | DISPLAY_ONLY | Tier 2 重检 |
| D6 | 风格漂移 3月>2σ | 中 | DISPLAY_ONLY | 方法论说明+回归 |
| D7 | 回撤触及上限 | **严重** | SUSPENDED | 全部流程重来 |
| D8 | 因子α<0 (t<-1.65) | 高 | DISPLAY_ONLY | α转正2月 |

### 10.3 降级优先级

当多个条件同时触发时: D7 > D1 > D3 > D4 > D2 > D8 > D5 > D6

**竞态规则**: Challenger 对比试验进行中触发 D1/D3/D7 → 试验暂停，影子 SUSPENDED。解除后试验从暂停处继续（保留累积天数）。

**无任期原则**: 对标 Millennium/Citadel——即使 Elite 300 天，今天触发 D1 今天暂停。

---

## 11. Gate 2 交互机制

### 11.1 核心约束

1. 影子是独立决策者，不是投票者——从不参与主管道最终决策
2. 用户是唯一桥梁——系统不自动传递影子/主管道之间的任何结论
3. 只有 Elite + 毕业的影子可以对话
4. 毕业后仍接受每日考核，可被降级

### 11.2 四阶段交互流程

```
Gate 2 开启
    │
    ▼
Phase 1: 独立展示
  ├── 左面板: 主管道结论（推理链、置信度、风险警告）
  ├── 右面板: Shadow Research Feed
  │   ├── 领域覆盖图: 各领域分析师覆盖情况
  │   ├── 按领域/标的聚合的方向视图（如"贵金属: 2看多, 1弃权"）
  │   ├── Elite 影子个体观点（thesis + 置信度）
  │   └── 跨策略分歧高亮（同一领域内方向不一致时标注）
  └── 系统不自动交叉引用
    │
    ▼
Phase 2: 结构化提问
  ├── 12 个预设问题，分 4 类
  │   ├── 基础验证 Q1-Q3: 最脆弱环节、什么改变判断、校准历史
  │   ├── 风险探查 Q4-Q6: 5%不利怎么办、尾部风险、缺失数据
  │   ├── 时机 Q7-Q9: 时间窗口、催化事件、入场时机
  │   └── 替代场景 Q10-Q12: 反方辩护、第二可能、无法量化因素
  ├── 用户选择: 一键全部 / 按类发送 / 单选 / 手动
  └── AI 回答格式: 结构化（非自由对话），强制引用来源上下文ID
    │
    ▼
Phase 3: 交叉验证（用户驱动）
  ├── 污染评级:
  │   ├── LOW:    "如果有人持相反观点，你怎么回应？"（不透露来源）
  │   ├── MEDIUM: "另一位分析师认为 X。你的回应？"（透露来源，记入审计日志）
  │   ├── HIGH:   直接分享完整结论 → 系统温和提醒
  │   └── CRITICAL: 系统自动传递 → 禁止
  ├── 用户是唯一完成交叉引用的人
  └── 所有交叉引用写入审计日志
    │
    ▼
Phase 4: 最终决策
  ├── 用户操作: CONFIRM / MODIFY / OVERRIDE / PAUSE
  ├── 影响因子清单（用户记录哪些输入影响了决策）
  └── 完整审计日志
```

### 11.3 Elite 影子交互规则

- **领域限制**: 只讨论自己领域（Bullion Broker 不谈科技股）
- **Devil's Advocate 角色**: 被设计为挑战者，不是确认者（Ma et al. 2023, arXiv 2403.01791）
- **干净状态**: 每轮 Q&A 从干净状态开始（BEAM 教训——不累积对话状态）
- **引用强制**: 每个回答必须引用来源上下文 ID
- **无决策权**: 标记为"影子意见"，仅供参考

### 11.4 独立性保持的多层架构

| 层 | 方法 | 防止 |
|------|------|------|
| 模型层 | DeepSeek 内 Persona+温度+推理框架差异化 | 行为纠缠（arXiv 2411.19515） |
| 数据层 | 不同信息源指纹 | 输入同质化（BlackRock 警告） |
| Persona 层 | 不同分析人格 | 输出趋同 |
| 交互层 | 无状态 Q&A | 上下文污染（BEAM） |

### 11.5 审计日志完整性保护

- **追加写**: 审计日志仅支持 append，不提供 modify/delete API
- **哈希链**: 每条日志含 prev_hash = SHA-256(上一条) 和 entry_hash = SHA-256(本条)
- **完整性表**: 哈希链头存储于独立的 audit_integrity 表中（只写一次）
- **启动验证**: 每次 Gate 2 会话启动时重算哈希链，与存储的链头对比
- **篡改检测**: 任何不匹配 → 标记 "INTEGRITY_BREACH"，Gate 2 进入只读模式

---

## 12. 自循环进化生态

### 12.1 六层进化架构

```
Layer 1: 排序与选择（Ranking & Selection）
  → Lexicase 预选（保证体制覆盖）
  → DPP 品质-多样性选择（填充剩余 8-12 影子）
  → EARCP 一致性感知权重调整（微调）

Layer 2: 挑战者生成（Challenger Generation）
  → LLM 语义变异 + 几何编译变异 + TreEvo 树形交叉
  → 诊断挑战者（免疫期特供）

Layer 3: 知识继承（Knowledge Inheritance）
  → PKT 概率知识迁移蒸馏 + TIES-Merging 多源融合
  → EWC 弹性权重固结 + 经验链（Chain of Experience）

Layer 4: 多样性维护（Multi-Layer Diversity）
  → 五层监控（数据源/策略结构/行为/输出/贡献）
  → MAP-Elites 行为分区（1215 单元格，每格 ≤2 影子）

Layer 5: 结晶（Crystallization = FactorMiner Ralph Loop）
  → Insight → Hypothesis → Tweak → Validate → Promote/Retire
  → VQ-VAE 蒸馏到 Knowledge Forest
  → alpha-CFG 策略语法验证

Layer 6: 生态系统模拟（FinEvo SDE）
  → 随机微分方程框架（Selection + Innovation + Perturbation）
  → 对抗性体制冲击测试
  → 主导周期与联盟形成检测
```

### 12.2 选择管道顺序（Lexicase → DPP → EARCP）

**Step 1 — Lexicase 预选（保证体制覆盖）**: 从全池中各市场体制至少选出 1 个专精影子。输出 regime_specialists（不可被后续步骤淘汰）。

**Step 2 — DPP 品质-多样性选择（填充剩余）**: 从 regime_specialists + 剩余池中选出最终集合（8-12 影子）。核矩阵 L_ij = score_i × score_j × similarity(i,j)，DPP 采样 1000 次，取最高频组合。

**Step 3 — EARCP 权重调整（微调）**: 对最终集合内影子调整权重。Lexicase 选中的 regime_specialists 享有缩权豁免（权重 ≥ 2% 地板）。一致性正则项惩罚高共线性低贡献影子。

### 12.3 类型感知复合评分

**Expert Score** = 0.35 × Sharpe + 0.25 × Excess Return + 0.20 × Information Ratio + 0.10 × Max Drawdown Penalty + 0.10 × Regime Consistency

**Momentum Score** = 0.30 × Sharpe + 0.30 × Excess Return + 0.15 × Information Ratio + 0.15 × Turnover Efficiency + 0.10 × Max Drawdown Penalty

**Contrarian Score** = 0.25 × Sharpe + 0.20 × Excess Return + 0.20 × Max Drawdown Penalty + 0.20 × Tail Risk Alpha + 0.15 × Long-Term Stability

**关键差异**: Expert 侧重信息比率（领域知识转化效率），Momentum 侧重换手效率（成本控制），Contrarian 侧重尾部风险 Alpha（逆向策略真正的 alpha 来自危机时刻的逆势买入）。

### 12.4 挑战者三级淘汰流程

```
WARNING → CHALLENGER → COMPARISON → REPLACE or RECOVER
```

| 阶段 | 条件 | 持续 | 动作 |
|------|------|------|------|
| WARNING | 连续 2 个评估周期处于同类后 20% | 2 个周期 | 记录表现日志，生成诊断报告 |
| CHALLENGER | WARNING 后仍未改善（连续 3 个周期后 20%） | 3 个周期 | 生成 3-5 个挑战者（变异体），隔离沙箱并行 |
| COMPARISON | CHALLENGER 生成完毕 | 2 周（≥10 交易日） | 配对 t 检验（p<0.05），胜者替换败者 |

**紧急替换**: 原影子在 COMPARISON 期间连续 5 日负超额收益，可触发紧急替换（无需等 t 检验完成）。

### 12.5 LLM 驱动的语义变异

基于 CogAlpha 框架:
1. 将濒危影子的完整方法论文档 + 近期决策日志 + 表现数据打包为 prompt
2. LLM 生成 3 个"保留原有优势、修复明显缺陷"的语义级方法论变更
3. 变异必须在财务上有意义——不能是随机的参数调整
4. 使用 Claude API 作为变异引擎，每次 ~8K input + 2K output tokens
5. 变异结果需经 Security Agent 审核

### 12.6 MAP-Elites 行为分区

使用 6 维行为描述符映射到 1215 个单元格:

| 维度 | 说明 | 离散化 |
|------|------|--------|
| Factor_Exposure | 主要因子暴露 | 价值/动量/质量/低波/规模 各 3 级 |
| Regime_Preference | 擅长体制 | 5 种体制 |
| Turnover | 日均换手率 | LOW(<5%) / MED(5-20%) / HIGH(>20%) |
| Drawdown_Tolerance | 可承受最大回撤 | CONSERVATIVE / MODERATE / AGGRESSIVE |
| Prediction_Horizon | 预测周期 | SHORT / MEDIUM / LONG |
| Signal_Frequency | 信号频率 | RARE / REGULAR / FREQUENT |

每单元格最多 2 个影子。超出 → 评分中位数影子被引导探索相邻单元格。

### 12.7 多样性控制流程（每日收盘后六步）

1. 计算所有影子间的成对相似度矩阵（5 层 × 各层权重）
2. 聚合为综合相似度矩阵
3. 检查：半数以上影子共享同一主导数据源？→ 发出"BlackRock 拥挤警告"
4. 检查：同类影子间语义距离过近？→ 触发变异
5. 检查：MAP-Elites 网格单元超过 2 个影子？→ 重新分配行为目标
6. 检查：连续 10 日边际贡献为负？→ 触发诊断审查

### 12.8 Crystallization 结晶（Ralph Loop）

```
Insight（采集高信念但不稳定的洞察）
  → Hypothesis（形式化为可测试假设）
    → Tweak（方法论微调）
      → Validate（回测验证，validation_score ≥ 0.60）
        → Promote（升级到语义记忆） 或 Retire（淘汰）
```

**统计准入标准**: 至少 10 笔已完成交易；平均 Sharpe ≥ 1.0 或超额收益 ≥ 年化 5%；夏普比率 bootstrap 检验 p < 0.05。

### 12.9 PKT 知识蒸馏（OOS 验证门）

结晶知识进入可继承池前必须通过样本外验证:
1. **观察期**: 60 个交易日（~3个月）只读观察（覆盖完整财报周期）
2. **样本外验证**: 方向准确率 ≥ 55% 且二项检验 p < 0.05
3. **FDR 控制**: 日度多重检验应用 Benjamini-Hochberg 控制（q=0.10），防止 24 影子并行检验产生假阳性
4. **重复验证**: 须通过 2 个独立 30 天 OOS 窗口
5. **验证失败**: 标记 "unvalidated"，仍存储但不进入 PKT 可继承池
6. **继承追踪**: 所有 PKT 转移记录来源洞察 ID，支持追溯和回滚
7. **硬要求**: 在 DiversityController 和 DPP Selector 实现后，才启用 PKT 知识继承——无多样性控制的知识共享会加速模型崩塌

### 12.10 实施优先级

| 阶段 | 组件 | 时间窗口 | 成本 |
|:---:|------|:---:|:---:|
| **Phase 1** 立即 | DPP 选择 + EARCP 加权 + 复合评分 | 2-3 周 | 零成本 |
| **Phase 2** 短期 | MAP-Elites 行为分区 + PKT 蒸馏 | 4-6 周 | 零成本 |
| **Phase 3** 中期 | 经验链 + LLM 语义变异 + 几何变异 | 6-8 周 | ~$0.03/变异 |
| **Phase 4** 长期 | VQ-VAE 蒸馏 + Knowledge Forest + FinEvo SDE | 8-12 周 | ~$15/mo 图数据库 |

Phase 1 和 Phase 2 完全零成本，可立即开始。Phase 1-3 足以构成完整的进化闭环。

---

## 13. 敢死队详细设计

### 13.1 C1: Fade Master — 共识逆向者（敢死队核心）

**shadow_id**: `contrarian:consensus:fade_master`
**触发**: 始终活跃（每日）
**虚拟资本**: $20K | **温度**: 0.55 | **最大仓位**: 4 | **回撤上限**: 35%
**激活率要求**: ≥ 50%（月均至少 10 天有产出）——低于此门槛标记 "insufficient_data" 零权重

**信号源**:
- AAII 散户情绪（牛熊比 >2.0 或 <0.5）
- Put/Call 比率极端（<0.6 或 >1.5）
- COT 投机净仓位处于 2 年极端
- 社交媒体情绪峰值
- Expert 共识一致率 >75%（通过 ConsensusExtractor 聚合——仅接收方向和百分比统计量）

**决策逻辑**:
```
IF Expert 一致率 >75% AND 方向 = long:
    → SHORT 共识最强的 ticker(s)
IF Expert 一致率 >75% AND 方向 = short:
    → LONG 最被讨厌的 ticker(s)
IF Expert 一致率 <75%:
    → 正常分析，可 ABSTAIN
```

**性格**: 天生反骨——"所有人都在买"对他来说是卖出信号。

### 13.2 C2: Sideways Scout — 区间猎手（全球扫描）

**shadow_id**: `contrarian:range_bound:sideways_scout`
**虚拟资本**: $25K | **温度**: 0.45 | **最大仓位**: 4 | **回撤上限**: 30%

**全球扫描清单**（15+ 指数）:
```
美洲: S&P 500, Nasdaq 100, Russell 2000, Bovespa
欧洲: FTSE 100, Euro Stoxx 50, DAX, CAC 40, IBEX 35
亚太: Nikkei 225, Hang Seng, Shanghai Composite, Nifty 50, ASX 200, KOSPI
```

**触发条件**（对每个指数独立判断）:
```
该指数 VIX-equivalent < 20
AND 5日日均振幅 < 1.5%
AND |20日均线斜率| < 0.1%/日  ← 趋势过滤器（防低波动慢涨误判）
```

**扫描逻辑**: 每日扫描所有 15+ 指数 → 找到满足条件的指数 → 区间顶部做空/底部做多 → 多个市场满足时选振幅最窄的 3-4 个 → 零市场满足时输出 NO_RANGE_GLOBALLY（极少发生）

**自检**（按市场独立追踪）: 某市场连续 8 次在"区间边界"止损 → 该市场标记为 FALSE_RANGE 暂停 20 天 → 其他市场继续 → 20 天后重新评估

### 13.3 C3: Vol Surfer — 恐慌冲浪者（全球扫描）

**shadow_id**: `contrarian:panic:vol_surfer`
**虚拟资本**: $30K | **温度**: 0.60 | **最大仓位**: 3 | **回撤上限**: 40%

**全球波动率指数清单**: VIX (美国), VSTOXX (欧洲), VNKY (日本), NIFTY50 VIX (印度), KOSPI VIX (韩国), HSI Vol (香港), VXEFA (发达市场ex-US)

**触发条件**（任一市场满足即可）: 该市场波动率指数 > 30（或其历史90%分位，取较低值）

**入场/退出**（按市场独立）: 波动率从峰值回落时入场（右侧，不是接飞刀）；波动率回归至中位数以下时分批退出；信号: VIX 期限倒挂 / Put/Call >1.5 / 广度冲刷 / 信用利差爆破

**性格**: 逆行者中的极限运动员——在别人最恐惧的时候最贪婪，但知道等 VIX 拐头再下水。

### 13.4 C4: Crash Hunter — 泡沫猎手（全球扫描）

**shadow_id**: `contrarian:crash:hunter`
**虚拟资本**: $30K | **温度**: 0.50 | **最大仓位**: 3 | **回撤上限**: 40%
**默认方向**: 做空

**全球扫描地区**: 美国 / 欧洲（EU aggregate） / 日本 / 中国 / 新兴市场（EM aggregate）

**信号清单**（每地区独立评分，需 ≥2 触发）:
1. CAPE / 可比周期性调整市盈率 > 30（或该地区历史90%分位）
2. 市值/GDP 比率 > 150%（或该地区历史90%分位）
3. Hindenburg Omen 触发
4. 广度分化（指数新高但 >50% 成分股 < 50MA）
5. 内幕抛售比 >5:1（4周窗口）
6. 信用利差扩大（IG OAS >150bp 或 HY >500bp）
7. 跨资产相关性上升（股债相关性从负转正）

**仓位缩放**（按地区）: 2 信号 = 半仓 / 3 信号 = ¾ 仓 / 4+ 信号 = 满仓

**性格**: 孤独的守望者——可能在牛市中休眠数年，但当信号灯亮起时，是整个生态中唯一坚定做空的人。

### 13.5 Contrarian 敞口管理

- **基线敞口**: ≤ $100K（所有 Contrarian 虚拟头寸名义价值之和）
- **独立激活上限**: 4 个 Contrarian 同时激活 AND Ecosystem Auditor 确认独立 → 扩展到 $130K
- **违规处理**: IF 总敞口 > 适用上限 → 按比例裁减

---

## 14. ShadowDecision 数据结构（非投票）

```python
@dataclass
class ShadowDecision:
    """影子独立投资决策——不是投票。"""
    shadow_id: str
    shadow_type: str          # "expert" | "momentum" | "contrarian"
    date: str
    ticker: str               # 全球，无限制
    direction: str            # "long" | "short"
    confidence: float         # 0.0-1.0
    position_size_pct: float  # min = max($100/资本, 0.2%)
    entry_price_target: float | None
    exit_price_target: float | None
    holding_period_days: int | None
    thesis: str
    risk_note: str
    is_min_position: bool
```

**重命名映射**: `ShadowVote→ShadowDecision`, `shadow_votes→shadow_decisions`, `VOTE_START→DECISION_START`
**DB迁移**: `shadow_analyses→shadow_decisions` (ALTER TABLE RENAME)
**输出安全**: 每影子每天≤1个DECISION_START块，行首匹配，嵌套禁止

---

## 15. 体制检测与免疫机制

### 14.1 四級体制（带滞后）

| 体制 | 条件 | Contrarian 免疫 | Momentum 免疫 |
|------|------|:--:|:--:|
| TRENDING | ADX≥30 + 持续10日 | 淘汰豁免（逐月递减） | 无 |
| TRANSITIONAL | ADX 20-30 | 50% | 50% |
| RANGE_BOUND | ADX<20 + 振幅<1.5% + 持续10日 | 无 | 淘汰豁免 |
| CHOPPY | ADX<20 + 振幅≥1.5% | 50% | 50% |

滞后：进入/退出免疫需条件连续满足 10 日。ConcentrationDetector 按体制调整阈值：RANGE_BOUND=70%, TRENDING=80%, TRANSITIONAL=75%, CHOPPY=90%, VIX>35=95%。

### 14.2 按交易市场判定

非全局 SPX 基准。影子仓位在 Nikkei → 用 Nikkei 的 ADX 判定。跨市场仓位 → 各仓位独立判定，加权汇总。

### 14.3 两级免疫

**Tier 1 — 淘汰免疫**：逐月递减（月1=100%, 月2=66%, 月3=33%, 月4+=0%）。计数器累计活跃天数，体制退出时暂停，重新进入时恢复。

**Tier 2 — 回撤执行（永不暂停）**：无论免疫状态，任何影子超过回撤上限 → 立即 PAUSE。

---

## 15. 毕业体系补充

### 15.1 Tier 2 基准说明

**Contrarian 特定基准**：
- 共识逆向者：Fama-French LT Rev + AAII 极端反向模拟（AAII 极值时反向交易的历史模拟，构造规范见附录）
- 区间猎手：Fama-French LT Rev + 区间均值回归模拟（振幅<1.5%时在区间边界交易）
- 恐慌冲浪者：CBOE Put/Call Ratio + VIX 期货期限结构策略（yfinance `^VIX` / `^VIX3M` 验证可用）
- 泡沫猎手：CBOE SKEW Index（需验证 yfinance `^SKEW` 可用性，添加 fallback）+ 保护性看跌模拟（每月 5%OTM SPY Put，构造规范见附录）

### 15.2 Challenger 评估周期

评估周期 = **月度**（约 20 个交易日），非类型评估窗口。Stage 1: 连续 2 个评估周期底部 20% → WARNING。Stage 2: 连续 3 个评估周期 → CHALLENGER。Stage 3: 2 周配对 t 检验。
对于 Contrarian，月度短期底部不触发（月度仅用于 WARNING 触发），排名评分仍用渐进式窗口。

---

## 16. 成本治理与 API 预算

- **预算原则**：测试后校准，不预先固定数字
- **基线预估**：影子分析 24-48 Pro 调用/天 + 主管道 ~7 + Fade Master 第二遍 1 = ~32-56 调用/天
- **实现**：`telemetry/api_counter.py` 拦截所有 async_client 调用，记录（调用方、模型、token数、时间），周度报告 `.claude/audits/api-usage-{date}.json`
- **硬停止**：预算耗尽 → `QuotaExhaustedError`（不可被静默吞噬）。网关层强制检查 `reserve_pro()` 返回值
- **每日预算**：50 Pro 调用（32基线 + 安全边际 + Gate 2 交互预留）
- **紧急配额**：5 次/天/影子，25 次/月/影子。恐慌市场自动收紧：VIX>35 时全局预算下调 20%
- **Token 预估**：~350,000 tokens/天，月度 ~10.5M

---

## 17. 迁移计划

| Phase | 内容 | 风险 | 注意 |
|:--:|------|:--:|------|
| 0 | DB 备份（`PRAGMA integrity_check` 验证后备份） | LOW | — |
| 1 | 类型定义更新 (`shadow_data_types.py`，暂时保留 daredevil) | LOW | 添加 `normalize_shadow_type()` 向后兼容适配器 |
| 2 | 配置更新 (`shadow_prompts.json` + `settings.py`) | LOW | — |
| 3 | 影子模块重构（新建 contrarian_shadows.py + momentum_shadows.py） | MEDIUM | 保留 daredevil_shadows.py 作为过渡兼容 |
| 4 | 运行时适配 (shadow_mother, ranking, challenger) | MEDIUM | 查询按 type IN ('momentum','daredevil') 保持兼容 |
| 5 | 新模块实现 | HIGH | 见 §18 构建顺序 |
| 6 | DB 迁移（显式映射表 + 11 表级联更新 + shadow_analyses→shadow_decisions） | **CRITICAL** | 禁用外键 → 11 表逐表更新 → 启用外键 → 验证完整性。**11 表含外键指向 shadows(id)**：shadow_outputs, virtual_trades, daily_snapshots, ranking_history, integrity_events, emergency_quotas, collusion_flags, emergency_quota_state, paper_live_gap_state, shadow_analyses, beta_analyses |
| 7 | ShadowVote → ShadowDecision（14 文件，人工审查后逐文件替换） | MEDIUM | 非影子上下文的 "vote" 不替换（如 verification_chain.py:148 的 "market vote"） |
| 8 | 投票残留清理（EcosystemAuditor 按领域聚合，ConcentrationDetector 重写） | MEDIUM | — |
| 9 | 测试（新增 150-170 测试 + 1,272 回归） | — | GraduationEngine 和 PostGraduationMonitor 各 ≥20 测试 |
| 10 | Red Team 审计 | — | 实施完成后最终审计 |

---

## 18. 实施构建顺序

**Phase A（数据基础）**：DataFingerprint → ReliableAPIClient → DataQualityValidator
**Phase B（类型基础）**：contrarian_shadows.py + momentum_shadows.py → shadow_data_types.py
**Phase C（独立工具）**：ConsensusExtractor → PendingSignalRegistry → EventTracker → PSR 数学工具
**Phase D（分析中间件）**：DiversityController → DPP Selector → VennAbersCalibrator → BrierDecomposition
**Phase E（集成模块）**：FactorAnalyzer → DailyBriefingGenerator → ConcentrationDetector
**Phase F（毕业管道）**：GraduationEngine → PostGraduationMonitor（最后构建，依赖最多）

每阶段独立测试。GraduationEngine 在所有依赖就绪后构建。

### Venn-Abers 说明
非即插即用——属于归纳共形预测研究级代码。先验证 `pip install venn-abers`（PyPI，最后更新 2022）。不可用则基于 `sklearn.isotonic` 自实现。预计 250-350 行。

### PSR 说明
`scipy.stats` 提供所需数学函数（skew, kurtosis, nct, norm.cdf）。约 80-120 行。n<4 时优雅降级至标准 Sharpe。分母趋近零时数值防护。

---

## 附录 A：已弃用的旧文档

以下文档被本文件取代，不再维护。其中可能存在过时信息（daredevil 类型、决策融合、ShadowVote 等），以本文件为准：
- `shadow-type-redesign-v2.md`、`shadow-type-redesign-v3.md`
- `shadow-lifecycle-framework.md`
- `shadow-vote-removal-analysis.md`
- `final-plan-core-architecture.md`、`final-plan-section-graduation.md`、`final-plan-section-interaction-memory.md`、`final-plan-section-evolution-data.md`
- `shadow-user-interaction-framework.md`、`shadow-memory-persistence.md`
- `projects/marketmind/CLAUDE.md`（影子生态章节）

---

## 附录 B：关键参考来源

**学术文献**：Jegadeesh & Titman (1993), DeBondt & Thaler (1985), Conrad & Kaul (1998), Balvers, Wu & Gilliland (2000), AlphaMix (KDD 2023), ArchetypeTrader (AAAI 2026), MARS (AAAI 2026), FactorMiner (2026), FinMem (AAAI 2024), Lo (2002), Bailey & Lopez de Prado (2012), Dimitriadis "The Triptych" (2023), Manokhin "Probability Matrix" (2026), Hadjiliadis & Vecer (2006), Tsaknaki et al. (2025)

**行业实践**：Millennium/Citadel pod-shop, Bloomberg ANR, Ken French Data Library, SG Trend Index, Numerai MMC, Telescope BEAM

**开源工具**：TradingAgents (71.1k★), easy-event-study, VectorBT v1.0.0, DeepTrust, Magents, FinRL-X, edgartools

---

**本文件是影子生态的权威设计文档。所有此前碎片化文档以此为准。**

---

