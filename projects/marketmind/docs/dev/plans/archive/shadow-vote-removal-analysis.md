# ShadowVote 重命名 + 投票机制清理 + 架构修正分析

**Date**: 2026-05-20
**Trigger**: 用户发现 "投票" 概念错误 + "决策融合" 不应存在

---

## 1. ShadowVote → ShadowDecision 重命名清单

### 1.1 为什么必须改

影子不是"投票者"——他们是独立的基金经理。每个影子基于自己的方法论分析数据、做出投资决定、管理虚拟投资组合。"投票"暗示集体决策，与当前架构完全矛盾。

### 1.2 重命名映射

```
ShadowVote          → ShadowDecision
shadow_vote         → shadow_decision
votes (变量名)       → decisions
_votes (私有变量)     → _decisions
VOTE_START          → DECISION_START
VOTE_END            → DECISION_END
_parse_votes()      → _parse_decisions()
all_votes           → all_decisions
votes_collected     → decisions_collected
shadow_votes (DB表) → shadow_decisions
```

### 1.3 影响文件（17个）

| 文件 | 影响内容 |
|------|------|
| `shadow_agent.py` | ShadowVote 类定义, _parse_votes(), ShadowAnalysisOutput.votes, _build_user_prompt() 中的 VOTE_START/VOTE_END |
| `shadow_state.py` | DB 表操作, save_votes(), get_votes_by_date_range() 等 |
| `shadow_schema.py` | shadow_votes 表 DDL, 索引, 迁移 |
| `shadow_mother.py` | _step_collect_votes(), all_votes 变量, result.votes_collected |
| `ecosystem_auditor.py` | run_audit(votes), _check_*() 方法参数, ShadowVote import |
| `collusion_detector.py` | compute_agreement_rate(votes), run_daily_check(votes), ShadowVote import |
| `daredevil_shadows.py` | _build_user_prompt() 中的 VOTE_START/VOTE_END 引用 |
| `expert_shadows.py` | _build_user_prompt() 中的 VOTE_START/VOTE_END 引用 |
| `missed_path.py` | ShadowAnalysisOutput 中的 votes=[] |
| `catfish_agent.py` | 废弃文件，可能需要删除 |
| `shadow_data_types.py` | 类型引用 |
| `ecosystem_health.py` | votes 引用 |
| `knowledge_manager.py` | votes 引用 |
| `background_scheduler.py` | votes 引用 |
| `shadow_snapshot_repo.py` | votes 引用 |
| `orchestrator.py` | votes 引用 |
| `__init__.py` | 导出 ShadowVote |

---

## 2. 投票机制是否应该存在？

### 2.1 结论：不应该。需要彻底改写。

**当前影子流程中残留的投票逻辑**:

```
ShadowAnalysisOutput:
  votes: list[ShadowVote]   ← 这里！影子产出的是一个"投票列表"

EcosystemAuditor:
  run_audit(votes)          ← 读"投票"找盲点

CollusionDetector:
  compute_agreement_rate(votes) ← 计算"投票"一致率

ShadowMother:
  _step_collect_votes()     ← "收集投票"
  all_votes.extend()        ← 聚合"投票"
```

**问题**: 这不是语言问题——是架构残留。影子产出 `ShadowAnalysisOutput`，其中 `votes` 字段是一个"投票列表"。但影子不是在投票——它是在做投资决定。

### 2.2 应该改成什么

```
ShadowAnalysisOutput:
  decisions: list[ShadowDecision]   ← 投资决定列表

每个 ShadowDecision:
  - ticker: 交易标的
  - direction: long/short
  - confidence: 0-1
  - position_size_pct: 仓位百分比
  - thesis: 投资逻辑（一句话）
  - risk_note: 风险提示（一句话）
  - entry_price_target: 入场目标价
  - exit_price_target: 退出目标价
  - holding_period_days: 预期持有天数
```

这才是"独立投资决策"的数据结构。不是"投票给某个方向"——是"我要以 X% 仓位做多/做空 Y 标的，入场价 Z，止损位 W"。

### 2.3 Collusion Detector 改名

"共谋检测"（Collusion Detector）的名字暗示影子们在串通。但实际上它检测的是：是不是所有影子都在同一个方向做交易（= 拥挤交易风险）。

改名为：**Concentration Detector（集中度检测器）**

逻辑不变：方向一致率 >80% 连续 3 天 → 警告"市场观点过度集中，可能存在拥挤交易风险"。这是有用的风险管理功能——只是名字不对。

### 2.4 Ecosystem Auditor 的输入改名

不是 "run_audit(votes)"，而是 "run_audit(decisions)"。它扫描的是所有影子的投资决定，找盲点：
- 方向集中度（所有人在做多？）
- 资产类别忽略（没人看能源？）
- 标的覆盖缺失

逻辑不变，名字改。

---

## 3. "决策融合" 为什么不应该存在

### 3.1 当前代码状态

**好消息**: `shadows/` 目录中没有任何文件包含 `fusion` 或 `融合`。这个概念从未被实现——只存在于设计文档中。

**坏消息**: 4 个设计文档提到了它:
- `shadow-type-redesign-v3.md` §8.2
- `shadow-lifecycle-framework.md` §12
- `shadow-type-redesign-v2.md`
- `phase-d-shadow-completion.md`

### 3.2 为什么应该删除

"决策融合"的前提是：**影子们在投票，需要把投票结果融合成一个集体决定。** 但我们已经确认影子不是投票者——他们是独立基金经理。

正确的模型：
```
24 个独立基金经理           主管道（投资委员会）
─────────────────         ─────────────────
各自分析、各自决策           阅读所有影子的分析报告
各自管理虚拟账户            独立做出最终投资决策
被排名系统评估              （仅限 Robinhood 可交易标的）
                          不受影子"投票"约束
```

不存在"融合"——存在的是"参考"。主管道可以看影子们的分析作为参考，就像基金经理读卖方报告一样。但决定是自己做的。

### 3.3 替代方案：Shadow Research Feed

取代"决策融合"的是 **Shadow Research Feed**：

```
每天影子分析完成后:
  1. 每个影子产出 ShadowAnalysisOutput（投资决定 + 分析报告）
  2. 这些报告被整理成 ShadowResearchFeed
  3. 主管道 Gate 2 阶段，用户/系统可以:
     - 查看"今天 24 个分析师的观点摘要"
     - 筛选按资产类别/方向的分布
     - 关注排名靠前影子的观点
     - 关注与共识方向相反的影子观点（Contrarian 信号）
  4. 但这些报告是参考信息——不决定主管道的输出
```

---

## 4. 影子与主管道的信息交流

### 4.1 正确的关系

```
              ┌──────────────────────────┐
              │     新闻 + 市场数据        │
              └──────────┬───────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
         ▼                               ▼
   ┌───────────┐                 ┌───────────────┐
   │  主管道    │                 │  影子生态      │
   │  (决策者)  │                 │  (研究者)      │
   │           │                 │               │
   │ Scout     │                 │ 24个独立分析师  │
   │ Flash     │                 │ 各自做投资决定  │
   │ HVR       │                 │ 管理虚拟账户    │
   │ L1/L2/L3  │                 │ 被排名系统评估  │
   │ Red Team  │                 │               │
   │ Resonance │                 │               │
   │ Decision  │                 │               │
   └─────┬─────┘                 └───────┬───────┘
         │                               │
         │  最终投资决策                   │  研究输出
         │  (Robinhood可交易)             │  (作为参考)
         │                               │
         └───────────┬───────────────────┘
                     │
                     ▼
            ┌────────────────┐
            │  Gate 2 确认    │
            │  用户可以看到:   │
            │  - 主管道结论    │
            │  - 影子观点摘要  │
            │  - 方向分布     │
            │  - 精英影子观点  │
            │  用户做最终决策  │
            └────────────────┘
```

### 4.2 交流规则

| 方向 | 内容 | 时机 |
|------|------|------|
| 数据 → 影子 | 原始新闻 + 市场数据 | 每日分析前 |
| 数据 → 主管道 | 原始新闻 + 市场数据 | 每日分析前 |
| 影子 → 主管道 | ❌ 无直接路径 | — |
| 影子 → 用户 | ShadowResearchFeed（Gate 2 展示） | Gate 2 阶段 |
| 主管道 → 影子 | ❌ 无直接路径 | — |
| 用户 → 影子 | ❌ 无（影子独立运作） | — |

**关键**: 影子和主管道之间没有自动的信息流。用户是唯一的交汇点——用户在 Gate 2 看到两边各自独立的分析，自己做判断。

### 4.3 为什么这样设计

1. **防止锚定**: 如果主管道看到影子结论，会被锚定影响
2. **防止污染**: 如果影子看到主管道结论，会失去独立性
3. **用户是最终决策者**: 两边都是工具，用户做判断
4. **可审计**: 两边的分析链条完全独立，事后可以对比谁的逻辑更正确

---

## 5. 影子投资标的范围

### 5.1 当前约束

CLAUDE.md: "All tickers must be Robinhood-tradable (from config/asset_universe.py)"

### 5.2 修正

**这个约束只适用于主管道。不适用于影子。**

理由：
- 影子管理的是**虚拟资本**，目标是**积累交易经验和方法论**
- Contrarian 影子需要全球扫描（日本、欧洲、新兴市场）——这些市场很多标的不在 Robinhood
- Expert 影子覆盖外汇、农产品、工业金属——Robinhood 不支持这些
- 限制影子标的 = 限制学习范围 = 影子生态的价值大打折扣

### 5.3 新规则

| 组件 | 标的限制 | 原因 |
|------|:--:|------|
| **主管道** | Robinhood 可交易 | 主管道产生**实际投资决策** |
| **影子生态** | **无限制**（全球所有可交易资产） | 影子是**虚拟学习系统** |
| **Momentum 影子** | 全球流动性足够的标的 | 趋势跟踪需要流动性 |
| **Contrarian 影子** | 全球扫描范围内所有标的 | 全球逆向需要全球市场 |
| **Expert 影子** | 各自领域的全球标的 | 外汇/FX, 商品/LME, 农产品/CBOT |

**影子资产来源**: 
- Yahoo Finance (全球股票/ETF)
- FRED (宏观数据)
- CFTC (期货)
- 各类商品交易所 (LME, CBOT, COMEX)
- Crypto 交易所 (Binance, Coinbase)
- 外汇 (OANDA/FXCM 数据)

---

## 6. 研究 Agent 发现中需要调整的部分

### 6.1 仍然有效的发现

| 发现 | 状态 | 说明 |
|------|:--:|------|
| 按策略原型分类（非风险） | ✅ 已采纳 | v3 核心设计 |
| Diversity Controller (MMC) | ✅ 保留 | 信号独特性仍然有价值 |
| Graceful Degradation | ✅ 保留 | 系统健壮性需要 |
| Contrarian 趋势免疫 | ✅ 保留 | 已修改为两级免疫 |
| 全球扫描替代休眠 | ✅ 已采纳 | v3 全球化修改 |
| 决策融合规范 | ❌ **删除** | 基于投票范式，不适用 |
| Safety-Critic 配对 (MARS) | ✅ 保留 | 激进影子需要约束 |

### 6.2 需要删除的

**"Decision Fusion Specification"** — 从所有文档中删除。它基于一个已经被推翻的前提（影子在投票）。

替代方案：**Shadow Research Feed**（§4.3 描述）。不要融合——参考。

---

## 7. 执行计划

### Phase 1: 重命名（代码层）
1. `shadow_agent.py`: ShadowVote → ShadowDecision, _parse_votes → _parse_decisions, VOTE_START/END → DECISION_START/END
2. 传播到 17 个文件
3. `shadow_schema.py`: shadow_votes 表重命名 + 迁移
4. `shadow_state.py`: 方法重命名
5. 所有 prompt 中的 VOTE_START/VOTE_END → DECISION_START/DECISION_END

### Phase 2: 删除（文档层）
1. v3 文档: 删除 §8.2 (Decision Fusion)
2. lifecycle-framework.md: 删除 §12 (Decision Fusion)
3. v2 文档: 已废弃，保留不修改

### Phase 3: 新增（文档层）
1. v3 文档: 添加 §8.2 Shadow Research Feed
2. lifecycle-framework.md: 添加影子-主管道交流章节
3. 更新 CLAUDE.md 中影子标的限制

### Phase 4: 概念清理
1. CollusionDetector → ConcentrationDetector（集中度检测器）
2. 更新 ecosystem_auditor.py 中的注释

---

## 8. 预计影响

| 组件 | 改动类型 | 风险 |
|------|:--:|:--:|
| 17 个文件重命名 | 机械替换 | LOW |
| shadow_votes 表迁移 | DB 迁移 | MEDIUM |
| 设计文档删除 Decision Fusion | 文档编辑 | LOW |
| Shadow Research Feed 新规范 | 文档新增 | LOW |
| CollusionDetector 重命名 | 概念澄清 | LOW |
| 投资标的限制放宽 | 配置+文档 | MEDIUM |
