# 影子生态最终方案 — 核心架构

**版本**: 3.0 Final
**日期**: 2026-05-20
**状态**: 汇总中 → 待红方审核
**整合自**: 7 份设计文档 + 5 份研究报告 + brainstorming 全部决策

---

## 1. 设计原则

### 1.1 核心原则

| # | 原则 | 含义 |
|:--:|------|------|
| P1 | **策略原型分类** | 按 Fundamental/Momentum/Contrarian 组织，不按风险水平。风险是中央风控的正交约束。 |
| P2 | **独立基金经理** | 每个影子是独立虚拟基金经理，做投资决策（不是投票）。ShadowDecision 不是 ShadowVote。 |
| P3 | **每日必决策** | 所有影子每天必须产出投资决策。不确定 → $100 最小仓位。 |
| P4 | **全球无限制** | 影子标的全球可交易资产。只有主管道受 Robinhood 约束。 |
| P5 | **用户是唯一桥梁** | 影子与主管道不自动通信。用户在 Gate 2 是唯一信息交汇点。 |
| P6 | **自循环进化** | 排名、淘汰、结晶、变异——全自动，用户不参与日常管理。 |
| P7 | **质量优先成本** | 影子主分析全用 Pro。Flash 用于分类/格式化。纯 Python 替代一切可替代的 LLM 调用。 |

### 1.2 影子生态的定位

```
影子生态 = R&D 实验室（核心目的 A）
  → 通过第二意见机制影响用户（输出 B）
  → 毕业后才能参与 Gate 2（有门槛的 B）
  → 不替代主管道，不自动参与决策
```

---

## 2. 影子类型体系

### 2.1 三类型架构

```
Fundamental (16)     Momentum (4)        Contrarian "敢死队" (4)
领域专家              动量/趋势             逆向/均值回归

始终活跃              始终活跃              全球扫描条件触发
τ=0.30-0.40          τ=0.40-0.50          τ=0.45-0.60
90天评估              75天评估              252天评估
回撤≤25%              回撤≤30%              回撤≤35-40%
```

### 2.2 完整影子清单

#### Fundamental — 16 领域专家

| shadow_id | 中文名 | 领域 | 资本 | τ |
|------|------|------|------|:--:|
| `expert:gold:bullion_broker` | 黄金捕手 | 贵金属 | $50K | 0.30 |
| `expert:crypto:chain_oracle` | 链上先知 | 加密货币 | $45K | 0.35 |
| `expert:energy:oil_geologist` | 石油地质学家 | 能源 | $50K | 0.30 |
| `expert:bonds:yield_whisperer` | 收益率耳语者 | 债券 | $55K | 0.30 |
| `expert:vol:vega_trader` | 波动率交易员 | 波动率 | $40K | 0.40 |
| `expert:em:frontier_scout` | 新兴市场侦察兵 | 新兴市场 | $45K | 0.35 |
| `expert:tech:silicon_oracle` | 硅谷神谕 | 科技 | $50K | 0.30 |
| `expert:financials:bank_examiner` | 银行审计官 | 金融 | $48K | 0.30 |
| `expert:healthcare:trial_reviewer` | 临床审查员 | 医疗 | $48K | 0.30 |
| `expert:consumer:wallet_watcher` | 钱包观察员 | 消费 | $46K | 0.30 |
| `expert:industrials:factory_floor` | 车间主任 | 工业 | $48K | 0.30 |
| `expert:metals:steel_trader` | 钢铁交易员 | 工业金属 | $42K | 0.35 |
| `expert:agriculture:harvest_seer` | 丰收先知 | 农产品 | $42K | 0.35 |
| `expert:realestate:reit_analyst` | REIT 分析师 | 房地产 | $48K | 0.30 |
| `expert:fx:currency_dealer` | 外汇交易员 | 外汇 | $44K | 0.35 |
| `expert:macro:cycle_reader` | 周期之眼 | 宏观/跨资产 | $60K | 0.30 |

#### Momentum — 4 动量/趋势

| shadow_id | 中文名 | 策略 | 持有期 | 资本 | τ |
|------|------|------|------|------|:--:|
| `momentum:intraday:scalper` | 日内猎手 | 动量突破 | 1-3天 | $25K | 0.50 |
| `momentum:weekly:trend_rider` | 趋势骑士 | 趋势跟随 | 5-15天 | $30K | 0.40 |
| `momentum:event:news_hound` | 事件猎犬 | 事件追入 | 1-5天 | $25K | 0.45 |
| `momentum:sector:rotation_engine` | 轮动引擎 | 板块轮动 | 5-20天 | $30K | 0.40 |

#### Contrarian "敢死队" — 4 逆向/均值回归

| shadow_id | 中文名 | 触发 | 资本 | τ |
|------|------|------|------|:--:|
| `contrarian:consensus:fade_master` | 共识逆向者 | 每日 | $20K | 0.55 |
| `contrarian:range_bound:sideways_scout` | 区间猎手 | 全球扫描15+指数 | $25K | 0.45 |
| `contrarian:panic:vol_surfer` | 恐慌冲浪者 | 全球扫描7波动率指数 | $30K | 0.60 |
| `contrarian:crash:hunter` | 泡沫猎手 | 全球扫描5地区≥2信号 | $30K | 0.50 |

### 2.3 动态影子类型

| 类型 | 触发 | 生命周期 | 说明 |
|------|------|------|------|
| `temp_event` | EventDetector 检测到 cb_shock/geopolitical/vol_shock | ≤30天 | 事件驱动临时影子 |
| `challenger` | 目标影子连续2-3期排名底部20% | 直到对比试验结束 | 秘密竞争，不可见 |
| `missed_path` | Gate 1 方向确认后 | 直到退出信号 | 反事实追踪，只读 |
| `beta` | 手动创建 | 隔离期 | 实验性影子，不排名 |

### 2.4 类型定义

```python
_VALID_TYPES = {
    "expert", "momentum", "contrarian",
    "temp_event", "challenger", "missed_path", "beta"
}
# 移除: "daredevil" (拆分为 momentum+contrarian), "catfish" (已废弃)

_VALID_STATUSES = {
    "active", "beta", "retired", "paused",
    "watch", "endangered", "eliminated",
    "dormant"  # 全球零触发(极罕见)
}
```

---

## 3. 影子-主管道关系

### 3.1 架构隔离

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

### 3.2 通信规则

| 方向 | 内容 | 是否自动 | 说明 |
|------|------|:--:|------|
| 数据 → 影子 | 原始新闻 + 市场数据 | 是 | — |
| 数据 → 主管道 | 原始新闻 + 市场数据 | 是 | — |
| **R0** | ConsensusExtractor 聚合 Expert 方向 → Fade Master | 是 | **唯一跨影子例外**：仅传递方向标签+百分比（纯Python统计量），不传递任何影子个体分析内容 |
| 影子 → 主管道 | **无直接路径** | 否 | — |
| 影子 → 用户 | Shadow Research Feed (Gate 2) | 是（毕业后） | — |
| 主管道 → 影子 | **无直接路径** | 否 | — |
| 用户 → 影子 | 结构化 Q&A (Gate 2) | 手动（毕业后） | — |

### 3.3 为什么不自动通信

- **防止锚定**: 主管道看到影子结论 → 被锚定
- **防止污染**: 影子看到主管道结论 → 失去独立性
- **可审计**: 两边分析链条完全独立
- **用户是最终决策者**: 两边都是工具

---

## 4. ShadowVote 重命名

### 4.1 重命名映射

```
ShadowVote          → ShadowDecision
shadow_vote         → shadow_decision
votes (变量)         → decisions
VOTE_START/VOTE_END → DECISION_START/DECISION_END
_parse_votes()      → _parse_decisions()
shadow_analyses (DB表) → shadow_decisions
```
注意：当前 DB 中实际表名为 `shadow_analyses`（已于 2026-05-18 从 shadow_votes 改名）。本次迁移使用 ALTER TABLE RENAME 直接改名为 `shadow_decisions`。

### 4.2 CollusionDetector 重命名

"共谋检测"暗示影子串通 → 改名 **ConcentrationDetector (集中度检测器)**

逻辑不变：方向一致率 >80% 连续 3 天 → 警告"市场观点过度集中"

#### 4.3 体制感知阈值

集中度检测的阈值按市场体制动态调整，防止真恐慌时误报：
- RANGE_BOUND 体制: 阈值 = 70%（安静市场更易发现拥挤）
- TRENDING 体制: 阈值 = 80%（默认）
- CHOPPY / VIX>35: 阈值 = 95%（真恐慌中高共识 = 理性行为）
- 交叉验证: 共识方向与当日 SPX > ±2% 同向 → 降低警告级别

---

## 5. 每日运营周期

```
每日启动
  │
  ├── Startup Protocol（记忆注入）
  │   ├── 加载市场上下文
  │   ├── 加载待确认信号 → 自动检查
  │   ├── 加载情景记忆 + 语义记忆
  │   └── 生成 Daily Briefing (per shadow)
  │
  ├── Phase 1: 并行分析（阶段1）
  │   ├── 16 Expert + 4 Momentum + 3 全球扫描 Contrarian
  │   └── 产出 ShadowDecision[]
  │
  ├── Phase 2: 共识提取（纯Python, 0 LLM）
  │   └── ConsensusExtractor 计算 Expert 方向一致率。有效性: ≥12 Expert→FULL; 8-11→DEGRADED; <8→SKIP
  │
  ├── Phase 3: Fade Master 分析（阶段2）
  │   └── 接收共识统计(FULL/DEGRADED/SKIP) → 独立逆向决策。SKIP 时仅使用外部情绪数据
  │
  ├── 虚拟交易执行
  │   └── ShadowDecision → VirtualTrade 记录
  │
  ├── 排名与评估
  │   ├── 类型感知复合评分
  │   ├── 多样性折扣 (DPP + EARCP)
  │   └── 成就阶梯更新
  │
  ├── 生态审计
  │   ├── 集中度检测 (原 CollusionDetector)
  │   ├── 生态系统盲点扫描 (EcosystemAuditor)
  │   └── 体制检测 + 免疫更新
  │
  ├── 进化机制
  │   ├── Challenger 淘汰检查
  │   ├── Crystallization 结晶
  │   └── 方法论变异
  │
  └── 每日快照归档
```

---

## 6. 毕业与评估（摘要）

详见 `final-plan-section-graduation.md`

- **Tier 1**: 胜率 + 收益率 + Brier Eagle/Bull + 最低交易 + 回撤
- **Tier 2**: Sortino/MAR/GPR/K-Ratio + 超越独立基准 + 跑赢主流水线
- **压力测试**: 2008/2020Q1/2022 三危机 + Carhart/Fung-Hsieh 因子纯度
- **毕业后**: CUSUM/CUSUMSQ/BOCPD 三层监控 + 8 降级条件

---

## 7. Gate 2 交互（摘要）

详见 `final-plan-section-interaction-memory.md`

- **四阶段**: 独立展示 → 结构化提问(12题) → 交叉验证(用户驱动) → 最终决策
- **Devil's Advocate**: Elite 影子是挑战者，不是确认者
- **污染控制**: 四级评级(LOW/MEDIUM/HIGH/CRITICAL)，系统不自动传递

---

## 8. 记忆持久化（摘要）

详见 `final-plan-section-interaction-memory.md`

- **三层**: Working(每日生成) → Episodic(90d,SQLite) → Semantic(永久)
- **待确认信号注册表**: 影子声明 WAITING_FOR → 系统检查触发
- **Daily Briefing**: 3200 token 预算，分层结构，Lost in the Middle 缓解

---

## 9. 自循环进化（摘要）

详见 `final-plan-section-evolution-data.md`

- **6 层进化**: 排名 → 挑战者 → 知识继承 → 多样性 → 结晶 → 生态模拟
- **DPP + EARCP**: 品质-多样性子集选择
- **Crystallization**: Ralph Loop (FactorMiner) = 我们的 Insight→Hypothesis→Tweak→Validate→Promote
- **4 级体制**: TRENDING/TRANSITIONAL/RANGE_BOUND/CHOPPY + 滞后规则
- **两级免疫**: 淘汰免疫(逐月递减) + 回撤执行(永不暂停)
- **LLM 语义变异**: 非随机参数扰动——LLM 提出金融上合理的策略修改

---

## 10. 信息源架构（摘要）

详见 `final-plan-section-evolution-data.md`

- **4 层**: 免费优先(10源,$0) → 免费适配(7源) → Freemium(4源) → 付费(3源)
- **每需求双源**: 主+备份，防止单点故障
- **信息指纹**: 每影子独特数据源组合 → DiversityController 监控同质化

---

## 11. 关键设计决策汇总

| # | 决策 | 结论 |
|:--:|------|------|
| 1 | 分类维度 | 策略原型(Fundamental/Momentum/Contrarian) |
| 2 | 影子标的 | 全球无限制 |
| 3 | 输出类型 | ShadowDecision（不是投票） |
| 4 | 决策融合 | **删除**——不存在 |
| 5 | 主管道关系 | 不直接通信，用户是唯一桥梁 |
| 6 | 每日要求 | 所有影子每天必须决策，min $100 |
| 7 | 全球扫描 | 无休眠——全球找机会 |
| 8 | LLM 选择 | 影子分析全部 Pro；Flash 仅分类/格式化 |
| 9 | 独立性 | 同一 DeepSeek 内通过 Persona+温度+数据切片+推理框架区分 |
| 10 | 毕业标准 | 基础能力(Tier1) + 类型卓越(Tier2) + 压力测试 + 持续监控 |
| 11 | 毕业后 | 无任期——CUSUM 触发即降级 |
| 12 | CollusionDetector | 重命名为 ConcentrationDetector |
| 13 | 反博弈 | Tier 2 年化收益必须 > 无风险利率 + 2%（绝对值）——防 min-bet 策略操纵 Sortino/MAR |
| 14 | 孤儿信号 | 影子淘汰时不取消 pending_signals——转移至 system owner 继续检查 |
| 15 | 成本治理 | 日预算 30 Pro 调用，月预算 750。紧急配额上限 3/天。周度成本报告 |

---

## 12. ShadowDecision 数据结构

```python
@dataclass
class ShadowDecision:
    """影子独立投资决策——不是投票。"""
    shadow_id: str
    shadow_type: str          # "expert" | "momentum" | "contrarian"
    date: str
    ticker: str               # 交易标的（全球，无限制）
    direction: str            # "long" | "short"
    confidence: float         # 0.0-1.0
    position_size_pct: float  # 仓位百分比（min = 虚拟资本 * 0.2% 或 $100/资本）
    entry_price_target: float | None
    exit_price_target: float | None
    holding_period_days: int | None
    thesis: str               # 投资逻辑（一句话）
    risk_note: str            # 风险提示（一句话）
    is_min_position: bool     # 是否最低仓位（不确定时）
```

### 12.1 输出解析安全

影子 LLM 输出中的结构化块（DECISION_START/DECISION_END、WAITING_FOR/END_WAITING_FOR、TRACKING）由解析器提取。防止自由文本中的伪块注入：

1. **块计数**: 每影子每天最多 1 个 DECISION_START 块，最多 10 个 WAITING_FOR 条目。超出 → 拒绝整份输出
2. **顶层匹配**: 块标记必须出现在行首（零缩进、无前缀）
3. **嵌套禁止**: 块内不允许出现同类块标记。解析器只提取第一个 DECISION_START...DECISION_END 对
4. **Prompt 规范**: 影子 prompt 明确要求"不要在 thesis/risk_note 中输出 DECISION_START/WAITING_FOR 字面量"
5. **审计日志**: 拒绝的输出写入审计日志，记录拒绝原因

---

## 13. 待实现模块清单

| 模块 | 文件 | 预估行数 | LLM? |
|------|------|:--:|:--:|
| ShadowDecision 重命名 | 17 文件 | 机械替换 | — |
| ConsensusExtractor | `shadows/consensus_extractor.py` | ~80 | 0 |
| ConcentrationDetector | `shadows/concentration_detector.py` | 重命名 | 0 |
| DiversityController | `shadows/diversity_controller.py` | ~150 | 0 |
| DPP Selector | `shadows/dpp_selector.py` | ~100 | 0 |
| PendingSignalRegistry | `shadows/pending_signals.py` | ~150 | 0 |
| EventTracker | `shadows/event_tracker.py` | ~120 | 0 |
| DailyBriefingGenerator | `shadows/daily_briefing.py` | ~250 | Flash |
| VennAbersCalibrator | `pipeline/venn_abers.py` | ~200 | 0 |
| BrierDecomposition | `pipeline/brier_decomposition.py` | ~150 | 0 |
| GraduationEngine | `shadows/graduation_engine.py` | ~300 | 0 |
| PostGraduationMonitor | `shadows/post_graduation_monitor.py` | ~400 | 0 |
| FactorAnalyzer | `shadows/factor_analyzer.py` | ~300 | 0 |
| ContrarianShadows | `shadows/contrarian_shadows.py` | 新建 | — |
| MomentumShadows | `shadows/momentum_shadows.py` | 重构 | — |
| DB 迁移 | `shadows/shadow_schema.py` | +迁移 | 0 |

---

## 14. 迁移计划

| Phase | 内容 | 风险 |
|:--:|------|:--:|
| 0 | DB 备份 + 审计基线 | LOW |
| 1 | 类型定义更新 (shadow_data_types.py) | LOW |
| 2 | 配置更新 (prompts + settings) | LOW |
| 3 | 影子模块重构 (contrarian + momentum) | MEDIUM |
| 4 | 运行时适配 (shadow_mother, ranking, challenger) | MEDIUM |
| 5 | 新模块实现 (diversity, consensus, graduation, monitor) | HIGH |
| 6 | DB 迁移 (shadow_id + shadow_type, 显式映射表) | HIGH |
| 7 | ShadowVote → ShadowDecision 全量替换 (17 文件) | MEDIUM |
| 8 | 测试 (~100 新测试, 1272 现有回归) | — |
| 9 | Red Team 审计 | — |
| 10 | 用户审批 | — |

---

## 15. 成本治理

### 15.1 API 调用预算

- 全局日预算: 30 Pro 调用/天（默认，可配置）
- 全局月预算: 750 Pro 调用/月（默认，可配置）
- 每影子紧急配额上限: 3 次/天, 15 次/月
- 预算耗尽 → 硬停止（需管理员手动恢复）
- 集成: `gateway/token_budget.py`

### 15.2 Token 消耗估算（每日）

| 组件 | 每影子 | ×24 | 合计 |
|------|------|------|------|
| Daily Briefing | 3,200 | — | 76,800 |
| 影子分析 (prompt + 数据 + 输出) | ~8,000 | — | 192,000 |
| 主管道 (全阶段) | — | — | ~60,000 |
| **总计** | — | — | **~330,000 tokens/天** |

月度估算: ~7,000,000 tokens（不含 Gate 2 交互）

### 15.3 监控

- 周度成本报告 → `.claude/audits/cost-{week}.json`
- 与 `gateway/token_budget.py` 集成实时追踪
- 季度对照实际 API 账单校准估算

### 15.4 审计日志完整性

- **追加写**: 仅支持 append，无 modify/delete API
- **哈希链**: 每条日志含 `prev_hash = SHA-256(上一条)` + `entry_hash = SHA-256(本条)`
- **完整性表**: 哈希链头存储于独立的 `audit_integrity` 表（只写一次）
- **启动验证**: 每次会话重算哈希链，对比存储链头。不匹配 → "INTEGRITY_BREACH"

---

## 附录: 完整文档清单

| # | 文档 | 内容 |
|:--:|------|------|
| 1 | `final-plan-core-architecture.md` | 本文件 — 架构总纲 |
| 2 | `final-plan-section-graduation.md` | 毕业考试与评估体系 |
| 3 | `final-plan-section-interaction-memory.md` | Gate 2 交互 + 记忆持久化 |
| 4 | `final-plan-section-evolution-data.md` | 自循环进化 + 信息源架构 |
| 5 | `shadow-type-redesign-v3.md` | 类型体系详细设计 |
| 6 | `shadow-introductions-zh.md` | 24 影子中文介绍 |
| 7 | `shadow-lifecycle-framework.md` | 完整运营生命周期 |
| 8 | `shadow-information-sources.md` | 信息源逐影子映射 |
| 9 | `shadow-vote-removal-analysis.md` | ShadowVote 清理分析 |
| 10 | `shadow-memory-persistence.md` | 记忆持久化详细设计 |
| 11 | `shadow-user-interaction-framework.md` | Gate 2 交互框架 |
