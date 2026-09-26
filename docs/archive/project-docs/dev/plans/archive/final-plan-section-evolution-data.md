# 影子自循环进化体系 & 信息源架构与数据分层

**文档类型**: 最终方案章节（合并入总体设计文档）
**最后更新**: 2026-05-20 07:07 UTC
**前置依赖**: 影子生态设计（types/roles/lifecycle）、Gate 评审体系、L1-L3 分析流水线

---

## Section A: 影子自循环进化体系

### A.1 总体架构

MarketMind 维护 24 个影子，按三种策略类型划分：

| 策略类型 | 数量 | 评估周期 | 核心特征 |
|----------|:---:|----------|----------|
| Fundamental/Expert | 16 | 90 日窗口 | 领域专长驱动，深度分析 |
| Momentum | 4 | 75 日窗口 | 趋势追随，快速适应 |
| Contrarian/敢死队 | 4 | 252 日窗口 | 逆向思维，长周期检验 |

影子在完全自主的生态系统中竞争。每日运营无需人工干预——用户仅在 Gate 2 评审环节与"毕业"的 Elite 影子交互。所有影子必须每日做出投资决策，即使不确定也必须至少投入 100 USD。每个影子管理一个虚拟投资组合，遵循其专属风险预算。

进化体系分为六层架构，每层解决一个独立问题：排序选择、挑战者生成、知识继承、多样性维护、结晶沉淀、生态模拟。

---

### A.2 Layer 1 — 排序与选择（Ranking & Selection）

#### A.2.0 选择管道顺序

三个选择机制的明确执行顺序：

**Step 1 — Lexicase 预选（保证体制覆盖）**: 从全池中各市场体制至少选出 1 个专精影子。输出 `regime_specialists`（不可被后续步骤淘汰）。

**Step 2 — DPP 品质-多样性选择（填充剩余）**: 从 `regime_specialists` + 剩余池中选出最终集合（8-12 影子）。目标: 最大化品质-多样性平衡。

**Step 3 — EARCP 权重调整（微调）**: 对最终集合内影子调整权重。Lexicase 选中的 regime_specialists 享有缩权豁免（权重 ≥ 2% 地板）。输出最终加权影子列表。

#### A.2.1 类型感知复合评分

不同类型影子使用不同的评估窗口，反映其策略特性的自然检验周期：

- **Expert (90日)**: 足够覆盖季度财报周期，既不过短（避免噪音）也不过长（避免策略漂移）
- **Momentum (75日)**: 略短于 Expert，因为动量信号衰减快、需要更敏捷的反馈
- **Contrarian (252日)**: 完整交易年，逆向策略需要更长时间才能证明其价值

每个窗口内计算复合评分，权重如下（可随 Gate 评审调整）：

Expert Score = 0.35 x Sharpe + 0.25 x Excess Return + 0.20 x Information Ratio + 0.10 x Max Drawdown Penalty + 0.10 x Regime Consistency

Momentum Score = 0.30 x Sharpe + 0.30 x Excess Return + 0.15 x Information Ratio + 0.15 x Turnover Efficiency + 0.10 x Max Drawdown Penalty

Contrarian Score = 0.25 x Sharpe + 0.20 x Excess Return + 0.20 x Max Drawdown Penalty + 0.20 x Tail Risk Alpha + 0.15 x Long-Term Stability

**关键差异说明**: Expert 侧重信息比率（领域知识转化效率），Momentum 侧重换手效率（成本控制），Contrarian 侧重尾部风险 Alpha（逆向策略真正的 alpha 来自危机时刻的逆势买入）。

#### A.2.2 DPP 品质-多样性子集选择（Determinantal Point Process）

使用 DPP 从评分池中选出质量与多样性兼顾的影子子集。DPP 的核心优势在于它天然平衡"选高分"和"选不相似的"两个目标，无需手动调权重。

**具体实现**:
1. 构造核矩阵 L：L_ij = score_i x score_j x similarity(i, j)，其中 similarity 由影子数据源指纹的 Jaccard 距离 + 决策树语义距离加权得到
2. 对 L 做特征分解，按概率采样子集
3. 输出入选影子列表及其 DPP 概率

**关键参数**:
- 每次选择 8-12 个影子进入活跃组合（具体数量由 Gate 2 动态调整）
- DPP 采样 1000 次，取出现频率最高的组合为最终入选集

#### A.2.3 EARCP 一致性感知加权

引入开源库 earcp（pip install earcp）实现 Ensemble-Aware Regularized Coherence Pruning。EARCP 在传统权重分配基础上增加"一致性正则项"：如果一个影子产生的信号与组合整体高度相关但贡献有限，它的权重会被适度收缩，释放预算给真正独立的信号源。

**权重地板**: 每个影子 >= 2% 最低权重。这是 Abe et al. (2023) 的关键发现——强制输出多样性反而可能损害整体表现。地板权重的存在不是为了多样性本身，而是确保即使"看似无用"的影子也保留观察窗口，因为它在特定市场体制下可能成为关键信号——只是那个体制尚未到来。

#### A.2.4 Lexicase 选择

Lexicase 选择按多个市场体制（如 TRENDING-UP、TRENDING-DOWN、RANGE_BOUND-LOW-VOL、CRISIS 等）分别评估每个影子，优先选择在所有体制中至少有一个表现优异的影子。

此方法天然防止"在所有体制中都中等但无突出表现"的影子垄断名额，确保每种市场环境都有"专家"被选中。

#### A.2.5 成就阶梯

成就阶梯的权威定义见 `final-plan-section-graduation.md` §9.2。基于类型内百分位 + 连续天数（非绝对阈值）。本模块（排名引擎）产生评分和百分位；成就阶梯由毕业引擎独立判定。


---

### A.3 Layer 2 — 挑战者生成（Challenger Generation）

#### A.3.1 三级淘汰流程

WARNING -> CHALLENGER -> COMPARISON -> REPLACE or RECOVER

| 阶段 | 条件 | 持续 | 动作 |
|------|------|------|------|
| WARNING | 连续 2 个评估周期处于同类后 20% | 2 个周期 | 记录表现日志，生成诊断报告，标记为"观察" |
| CHALLENGER | WARNING 后仍未改善（连续 3 个周期后 20%） | 3 个周期 | 基于诊断结果生成 3-5 个挑战者影子（变异体），开始在隔离沙箱中并行运行 |
| COMPARISON | CHALLENGER 生成完毕 | 2 周 | 原影子 vs. 挑战者进行配对 t 检验（p<0.05），胜者替换败者 |

**配对 t 检验细节**:
- 样本量: 至少 10 个交易日（2 周）
- 零假设 H0: 挑战者日收益 - 原影子日收益 = 0
- 备择假设 H1: 挑战者 > 原影子（单尾检验）
- 若 p < 0.05 -> 挑战者替换原影子; 若 p >= 0.05 -> 保留原影子，挑战者存档
- 若原影子在 COMPARISON 期间连续创新低（连续 5 日负超额收益），可触发紧急替换（无需等 t 检验完成）

#### A.3.2 LLM 驱动的语义变异（CogAlpha 启发）

CogAlpha 框架的核心思想：大语言模型理解金融语义，可以用自然语言描述策略变更。MarketMind 的 LLM 变异流程：

1. **诊断输入**: 将濒危影子的完整方法论文档（中文）、近期决策日志、表现数据打包为 prompt
2. **变异指令**: 要求 LLM 生成 3 个"保留原有优势、修复明显缺陷"的语义级方法论变更
3. **约束**: 变异必须在财务上有意义——不能是随机的参数调整。例如："将入场条件从 RSI<30 改为 RSI<30 + 成交量放大20%，因为原策略在缩量超卖时频繁误判"是有效变异；"将 RSI 阈值从 30 改为 26.37"是无效变异（无财务语义）
4. **输出格式**: 每个变异包含 (a) 变更描述 (b) 财务理由 (c) 预期改善方向 (d) 潜在副作用

**实施注意事项**:
- 使用 Claude API（已在 MarketMind 架构中）作为变异引擎
- 每次变异会话消耗约 8K input tokens + 2K output tokens
- 变异结果需经 Security Agent 审核（防幻觉、防无意义变更）

#### A.3.3 几何编译变异（Continuous Program Search）

沿着历史上成功变异构成的"有利方向"进行安全突变。维护一个成功变异向量库，记录每次成功变异的参数空间方向向量和 Sharpe 改善量。当需要为新濒危影子生成挑战者时，检索历史上成功改善类似影子的变异方向，沿这些方向做小幅安全探索。核心原则：不随机变异，而是从已验证有益的方向出发。

#### A.3.4 树形结构交叉（TreEvo）

TreEvo 的洞见：投资决策可表示为决策树，决策树天然支持子树交叉。在 MarketMind 中，将每个影子的决策逻辑分解为：入场逻辑子树（什么条件下开仓）、仓位管理子树（如何确定仓位大小）、退出逻辑子树（什么条件下平仓）、风控逻辑子树（什么条件下减仓/对冲）。

交叉操作: 取影子 A 的入场逻辑子树 + 影子 B 的退出逻辑子树 = 新挑战者 C。这种交叉在财务上有语义：A 擅长发现机会，B 擅长及时退出，组合后的 C 有望继承两者的优势。

**约束**: 交叉对象必须在同一市场类型内；交叉后必须通过 alpha-CFG 策略语法验证；每次交叉生成的挑战者必须经过 5 日沙箱观察才能进入 CHALLENGER 阶段。

#### A.3.5 诊断挑战者（免疫期特供）

当一个影子处于免疫期，原则上免受淘汰。但机制设计上不能"盲目容忍"。在免疫期内生成一个"影子副本"（诊断用挑战者），该副本不受免疫保护，与影子并行运行。不参与实际投票，仅用于验证问题根源：若诊断挑战者表现显著优于原影子，说明问题来自方法论；若表现相似，说明问题来自市场体制，免疫保护合理。诊断挑战者的方法论文档会标注【诊断用·不投票】，结果仅对系统内部可见。


---

### A.4 Layer 3 — 知识继承（Knowledge Inheritance）

当一个影子被淘汰时，它积累了数月甚至数年的市场经验。直接删除它等于丢弃这些知识。Layer 3 设计了一套完整的知识蒸馏与继承机制。

#### A.4.0 知识继承前置验证（样本外）

结晶知识进入可继承池前必须通过 OOS 验证：
1. **观察期**: 30 个交易日只读观察
2. **样本外验证**: 将洞察预测与实际市场数据对比（数据不在结晶数据集内）
3. **准入标准**: 方向准确率 ≥ 50% 且与随机猜测差异显著（二项检验 p < 0.10）
4. **验证失败**: 标记 "unvalidated"，仍存储但不进入 PKT 可继承池
5. **继承追踪**: 所有 PKT 转移记录来源洞察 ID，支持追溯和回滚

#### A.4.1 PKT 概率知识迁移蒸馏

Probabilistic Knowledge Transfer (PKT) 的核心思想：不复制退休影子的输出（那是行为克隆），而是让新挑战者学习退休影子隐含的概率分布——即"影子认为什么场景重要，什么场景不重要"。

实现步骤：收集退休影子在最后 90 个交易日的所有输入-输出对作为教师数据集；通过退休影子的决策树做前向传播记录激活分布；用 KL 散度损失训练挑战者（lambda=0.3）；同时最小化自身投资任务损失。这样新影子继承了"经验直觉"而非"机械复刻"。

#### A.4.2 TIES-Merging 多源融合

当多个 Expert 影子同时退休（如宏观环境剧变导致一批老影子集体失效），TIES-Merging 提供了融合方案：

1. **Trim (修剪)**: 每个退休影子只保留其权重中"对预测贡献 > 噪声贡献"的参数（通过 Fisher 信息量判断）
2. **Elect Sign (选举)**: 对每个保留的参数，取多影子中多数方向作为融合方向
3. **Disjoint Merge (合并)**: 只在参数方向一致的维度上保留融合值，方向冲突的维度清零

TIES-Merging 保证融合结果不会退化为"平均化噪声"。

#### A.4.3 EWC 弹性权重固结

Elastic Weight Consolidation 在影子适应新市场体制时保护其核心能力。当影子需要适应新的 regime 时（如从 RANGE_BOUND 转到 TRENDING），对原有的关键参数施加"弹性约束"——学习率按 Fisher 信息量反比缩放。Fisher 信息量高的参数（对原任务重要）学习率极低，Fisher 信息量低的参数（不重要/冗余）学习率正常。总损失 = L_new_task + (lambda/2) x Sum(F_i x (theta_i - theta*_i)^2)，lambda 建议 0.1。

#### A.4.4 经验链（Chain of Experience）

每个影子维护一条结构化的进化轨迹，以 JSON 格式记录版本序列、死亡原因、累积洞察和继承遗产。经验链的引用场景：新影子初始化时读取同类影子的经验链避免重蹈覆辙；LLM 语义变异时作为 prompt 的一部分提供历史上下文；Gate 评审时审计员检查经验链判断影子是"真进步"还是"换了个方式犯同样的错"。


---

### A.5 Layer 4 — 多样性维护（Multi-Layer Diversity）

Abe et al. (2023) 的核心警告：强制输出多样性（让影子故意做出不同预测）会损害组合表现。MarketMind 的多样性维护目标不是"预测不相关"，而是**信号来源多样**。

#### A.5.1 五层多样性监控

| 层级 | 监控维度 | 方法 | 阈值 |
|------|----------|------|:---:|
| 数据源层 | 信息指纹差异 | DPP 基于 Jaccard 距离选择互补数据源组合 | 同源重叠率 < 50% |
| 策略结构层 | 决策树语义距离 | TreEvo 树编辑距离（插入/删除/修改节点的最小操作数） | 同类影子间最小距离 > 3 |
| 行为层 | 因子暴露、体制偏好、换手率 | MAP-Elites 行为描述符映射到 6D 行为网格 | 每个网格单元最多 2 个影子 |
| 输出层 | 信号共线性 | EARCP 一致性正则化惩罚高共线性低贡献影子 | 贡献/共线性比 < 0.3 触发审查 |
| 贡献层 | 边际贡献 (MMC) / True Contribution | 逐一移除影子，测量组合 Sharpe 变化 | 负贡献连续 10 日触发审查 |

#### A.5.2 多样性控制流程

每日收盘后的六步检查流程：
1. 计算所有影子间的成对相似度矩阵（5 层 x 各层权重）
2. 聚合为综合相似度矩阵
3. 检查：是否有半数以上影子共享同一主导数据源？是 -> 发出"BlackRock 拥挤警告"，触发数据源重分配
4. 检查：是否有同类影子间语义距离过近？是 -> 对距离最近的一对触发变异
5. 检查：是否有 MAP-Elites 网格单元超过 2 个影子？是 -> 将该单元评分为中等的影子重新分配行为目标
6. 检查：是否有影子连续 10 日边际贡献为负？是 -> 触发诊断审查

#### A.5.3 MAP-Elites 行为分区

使用 6 维行为描述符将影子映射到行为网格：

| 维度 | 说明 | 离散化 |
|------|------|--------|
| Factor_Exposure | 主要因子暴露 | 价值/动量/质量/低波/规模 各 3 级 |
| Regime_Preference | 擅长体制 | TRENDING_UP / TRENDING_DOWN / RANGE / CHOPPY / TRANSITIONAL |
| Turnover | 日均换手率 | LOW(<5%) / MED(5-20%) / HIGH(>20%) |
| Drawdown_Tolerance | 可承受最大回撤 | CONSERVATIVE(10%) / MODERATE(20%) / AGGRESSIVE(35%) |
| Prediction_Horizon | 预测周期 | SHORT(1-5d) / MEDIUM(5-20d) / LONG(20-60d) |
| Signal_Frequency | 信号频率 | RARE(<1/wk) / REGULAR(1-3/wk) / FREQUENT(>3/wk) |

行为网格共 3x5x3x3x3x3 = 1215 个单元格。当某一单元格超过 2 个影子时，对评分最接近中位数的影子施加行为扰动，引导其探索相邻单元格。


---

### A.6 Layer 5 — 结晶（Crystallization，FactorMiner Ralph Loop 对齐）

#### A.6.1 Ralph Loop 对齐

FactorMiner 的 Ralph Loop（Retrieve -> Evaluate -> Distill）与 MarketMind 现有的 Insight -> Hypothesis -> Tweak -> Validate -> Promote/Retire 流水线自然对齐。当影子进入 Elite 状态或其方法论通过 Gate 3 评审后，触发结晶流程。

#### A.6.2 VQ-VAE 蒸馏（ArchetypeTrader）

借鉴 ArchetypeTrader 的方法，使用 Vector Quantized Variational Autoencoder 将退休/结晶的 Elite 影子策略压缩到离散原型库：编码（策略描述 + 决策边界 + 参数空间 -> 连续潜在向量）、量化（映射到 codebook 中的最近离散原型）、解码（从离散原型重构策略）、入库（存入 Knowledge Forest 的策略原型节点）。

**统计准入标准**: 至少 10 笔已完成交易（不是 10 条预测信号）；平均 Sharpe >= 1.0 或超额收益 >= 年化 5%；夏普比率的 bootstrap 检验 p < 0.05（非零）；最大回撤 < 同类影子中位数。

#### A.6.3 alpha-CFG 策略语法

引入形式语法（alpha Context-Free Grammar）确保所有策略描述合法且可验证。策略定义包含 EntryRule（入场条件）、PositionRule（仓位规则+修饰符）、ExitRule（止损+止盈+时间退出）、RiskRule（最大仓位+最大回撤+最大相关性+体制覆盖）。

alpha-CFG 的两个核心用途：(1) 变异验证 — 任何 LLM 生成的变异必须能被 alpha-CFG 解析通过，否则退回重生成；(2) 交叉验证 — TreEvo 交叉后的策略必须能被 alpha-CFG 解析通过，否则宣告交叉失败。

#### A.6.4 Knowledge Forest（知识森林）

图数据库结构存储 MarketMind 的累积策略知识。节点类型包括：STRATEGY_ARCHETYPE（VQ-VAE 离散原型）、SHADOW_INSTANCE（具体影子实例）、MARKET_REGIME（市场体制快照）、DECISION_RECORD（关键决策记录）。边类型包括：EVOLVED_FROM（版本演化）、CONFLICTS_WITH（策略矛盾）、SYNERGIZES_WITH（策略互补）、PERFORMED_IN（体制-表现关联）、DISTILLED_TO（实例->原型蒸馏）。

Knowledge Forest 的查询场景：检索与当前体制相似的历史体制及当时最佳影子；追踪影子版本间方法论节点变更；检测 Elite 影子间的策略重叠。


---

### A.7 Layer 6 — 生态系统模拟（FinEvo SDE）

#### A.7.1 FinEvo SDE 统一框架

FinEvo 将影子种群的演化建模为随机微分方程：dP(t) = S(P,t)dt + I(P,t)dW + J(P,t)dN。其中 S(P,t) 为 Selection（评分驱动的自然选择），I(P,t)dW 为 Innovation（变异/交叉带来的随机探索），J(P,t)dN 为 Perturbation（市场体制突变带来的外部冲击）。

FinEvo SDE 的价值不在于数值求解（在 24 个影子的小规模种群中不必要），而在于它提供了理论完备的框架来回答三个策略性问题：
1. 在当前的 Selection 速率下，一个 Watch 级的影子平均需要多少周期才能进化到 Elite？（预期进化时间）
2. 如果在 3 个月内连续施加多次 Perturbation（熊市 + 高波动），种群多样性是否会崩溃？（压力测试）
3. 目前的 Innovation 速率是否足以抵御自然趋同？（种群熵监测）

#### A.7.2 对抗性体制冲击测试

每月（或在市场出现极端事件时触发）运行一次对抗性体制冲击测试：构造多个极端体制场景，将 24 个影子的虚拟组合暴露于这些场景，测量组合损失和影子间相关性变化，输出灾难性损失预期的影子列表及应对建议。具体实现：使用历史极值事件的协方差矩阵（如 2008、2020-03、2022）替换当前协方差矩阵，重新计算组合风险。

#### A.7.3 主导周期与联盟形成检测

监控影子种群中是否出现权力集中现象：
- **主导检测**: 任何单个影子权重 > 25% -> 触发权力集中警告
- **联盟检测**: 对影子投票向量做层次聚类，若某联盟总权重 > 40% 且簇内影子决策一致性 > 80% -> 触发"隐性联盟"警告
- **应对**: 对主导影子的权重施加临时上限（20%），将释放的权重按 DPP 多样性优先分配给其他影子

---

### A.8 体制检测与免疫机制

#### A.8.1 四层体制检测（带滞后效应）

| 体制 | 判定条件 | 免疫策略 |
|------|----------|----------|
| TRENDING | ADX >= 30 + 持续 10 日 | Contrarian 淘汰豁免 |
| TRANSITIONAL | ADX 20-30 | 双方各 50% 免疫 |
| RANGE_BOUND | ADX < 20 + 振幅 < 1.5% + 持续 10 日 | Momentum 淘汰豁免 |
| CHOPPY | ADX < 20 + 振幅 >= 1.5% | 双方各 50% 免疫 |

#### A.8.2 滞后机制（10 日持续条件）

为防止体制在边界间高频切换导致影子频繁进入/退出免疫：进入免疫需条件连续满足 10 个交易日（第 11 日生效），退出免疫需条件连续不满足 10 个交易日（第 11 日退出），中途中断则计数器归零。在 TRANSITIONAL 和 CHOPPY 体制下，所有影子享 50% 淘汰免疫——评分的淘汰阈值比平时降低 50%。

#### A.8.3 免疫机制（两层）

**Tier 1 — 淘汰免疫**: Contrarian 在 TRENDING 体制和 Momentum 在 RANGE_BOUND 体制豁免淘汰。衰减机制：第 1 个月 100%，第 2 个月 66%，第 3 个月 33%，第 4 个月起 0%。

**Tier 2 — 回撤强制执行（永不暂停）**: 此层级取代 Tier 1 的所有豁免。任何影子一旦触发回撤限制，立即暂停操作：Contrarian 最大回撤 > 35% -> 立即暂停；Momentum > 25% -> 立即暂停；Expert > 同类历史中位数 2 倍 -> 立即暂停。暂停后影子进入 5 日隔离观察，由 Gate 评审决定恢复或退役。

#### A.8.4 按交易市场判定免疫

体制免疫按**影子实际交易市场**独立判定，非全局 SPX 基准：
- 影子仓位在 Nikkei → 用 Nikkei 的 ADX/振幅判定其免疫
- 跨市场仓位 → 各仓位按各自市场独立判定；影子整体免疫 = 各仓位免疫的加权（按仓位大小）
- 这防止了"SPX 趋势但影子在日本区间市场赚钱却享免疫"的错位


---

### A.9 实施优先级与路线图

| 阶段 | 组件 | 时间窗口 | 依赖 | 成本 |
|:---:|------|:---:|------|:---:|
| **Phase 1** 立即 | DPP 选择 + EARCP 加权 + 复合评分 | 2-3 周 | 开源库 earcp（pip install） | 零成本 |
| **Phase 2** 短期 | MAP-Elites 行为分区 + PKT 蒸馏 | 4-6 周 | Phase 1 完成 + 行为描述符定义 | 零成本 |
| **Phase 3** 中期 | 经验链 (CoE) + LLM 语义变异 + 几何变异 | 6-8 周 | Claude API（已有）+ 向量数据库 | API 费用: ~0.03 USD/变异 |
| **Phase 4** 长期 | VQ-VAE 蒸馏 + Knowledge Forest + FinEvo SDE | 8-12 周 | Phase 2-3 完成 + 图数据库 | 图数据库宿主 ~15 USD/mo |

**关键决策**: Phase 1 和 Phase 2 完全零成本，可立即开始。Phase 3 的 LLM 语义变异是最有价值的进化驱动力（能产生人类可理解的方法论改进），应优先推进——即使 Phase 4 延后，Phase 1-3 足以构成完整的进化闭环。

#### A.9.5 成本治理（Phase 0 — 所有实现前）

- 全局日预算: 30 Pro 调用/天；月预算: 750 Pro 调用/月
- 每影子紧急配额: 3 次/天, 15 次/月
- 周度成本报告自动生成 → `.claude/audits/cost-{week}.json`
- 与 `gateway/token_budget.py` 集成实时追踪

---

## Section B: 信息源架构与数据分层

### B.1 设计原则

1. **双重冗余**: 每个数据需求至少配置一个主源 + 一个备源，防止单点故障
2. **免费优先**: 先使用免费层，只有在免费不足时才升级付费——确保研究阶段成本可控
3. **可靠调用**: 所有外部 API 调用统一包装 timeout + retry + circuit breaker（见 B.5 节）
4. **区域适配**: 全球主要市场通过 yfinance（主）+ Twelve Data（备），亚洲市场补充 AKShare（中国）/ nsepy（印度）/ iTick（金属）
5. **学术优先**: 凡是学术界有免费高质量替代的（如 Ken French Data Library），绝不使用付费替代

### B.2 四层数据架构

#### B.2.1 Layer 1 — 立即免费（零成本，即刻接入）

| 数据源 | 提供内容 | 服务影子 | 接入方式 |
|--------|----------|----------|----------|
| **yfinance** | 全球 15+ 主要指数 OHLCV、波动率指数、ETF | 全部 24 个影子 | Python 库，无需 API Key |
| **FRED API** | 800K+ 美国宏观序列（GDP、CPI、失业率、利率、CAPE） | Macro Watcher、Bond Guardian、大部分 Expert | 免费 API Key（注册即得），限 120 req/min |
| **EIA API** | 原油/天然气库存、产量、价格 | Oil Geologist | 免费 API Key（注册即得） |
| **USDA FAS PSD API** | 全球农产品供需月度数据（产量、消费、库存、贸易） | Harvest Seer | 免费 API，无需 Key |
| **DeFiLlama API** | 加密 TVL、稳定币供应、DEX 交易量 | Chain Oracle | 免费，无需 Key，rate limit 友好 |
| **CFTC COT** | 期货持仓报告（商业/非商业/散户） | Fade Master、Steel Trader | 免费 CSV 下载（每周五更新） |
| **NOAA NCEI API** | ENSO 指数、全球气候模式、极端天气 | Harvest Seer | 免费 API Key（注册即得） |
| **openFDA API** | 药品审批历史、召回、不良事件 | Trial Reviewer | 免费，无需 Key，rate limit 240 req/min |
| **Ken French Data Library** | Fama-French 五因子 + 动量因子 + 行业组合 | Contrarian 基准、所有 Expert 基准 | 免费 CSV 下载，学术黄金标准 |
| **Nasdaq Data Link / MULTPL** | Shiller CAPE、Buffett Indicator、Tobin Q | Crash Hunter | 免费（有限配额） |

**Layer 1 接入检查清单**:
- 注册 5 个免费 API Key（FRED、EIA、NOAA NCEI、Nasdaq Data Link、Twelve Data）
- 所有 Key 存入环境变量（禁止硬编码），通过 .env 加载
- 每个数据源编写对应的 adapter 模块（统一接口）
- 编写 rate limit 配置（存入 config/data_sources.yaml）
- 为每个 adapter 编写 3+ 单元测试（正常数据、空数据、超时）


#### B.2.2 Layer 2 — 需开发适配器（零成本，需投入开发工时）

| 数据源 | 提供内容 | 接入工作 | 影子受众 |
|--------|----------|----------|----------|
| **AAII Sentiment** | 散户多空情绪调查（周度） | 网页爬虫（静态 HTML），每周抓取一次 | Contrarian、Crash Hunter |
| **Research Affiliates** | 各国 CAPE 数据（EU、Japan、EM） | 网页爬虫（需 headless browser） | Macro Watcher、Contrarian |
| **siblisresearch** | 多国 CAPE 快照 | 网页爬虫 | Macro Watcher |
| **LME（通过 iTick API）** | 金属库存数据 | API 集成（iTick 免费层） | Steel Trader、Metals Watcher |
| **CoinMetrics Community** | 链上数据（30 日历史） | API 集成，需注册 Community Tier | Chain Oracle |
| **AKShare** | A 股行情、融资融券、股东增减持、龙虎榜 | Python 库 pip install akshare | 所有关注中国市场的 Expert |
| **nsepy** | India VIX、NSE 数据 | Python 库 pip install nsepy | Emerging Market Watcher |

**Layer 2 优先级**: (1) AKShare — 中国市场数据缺口最大，优先接入；(2) AAII Sentiment — 爬虫最简单，逆向策略核心输入；(3) Research Affiliates CAPE — 需 headless browser 但数据无可替代；(4) nsepy — 印度市场数据空白；(5) CoinMetrics Community — 链上数据补充；(6) LME via iTick — 金属库存关键缺口。

#### B.2.3 Layer 3 — Freemium（免费配额->按需付费）

| 数据源 | 免费额度 | 升级费用 | 用途 |
|--------|----------|:---:|------|
| **Twelve Data** | 800 req/day | USD 49.99/mo | 全球价格数据专业备源 |
| **Databento** | USD 125 免费额度 | 按量计费 | 高频历史 Tick 数据（未来 Phase 保留入口） |
| **ShareSeer MCP** | 10-50 req/day | 不定 | 社交媒体情绪、另类数据 |
| **FinancialReports.eu** | 有限免费 | 付费层 | 欧洲公司财报 |

**升级触发条件**: Twelve Data — 当 yfinance 连续 3 日无法获取关键数据且日均调用超过 800 次时升级；Databento — 当需要 sub-1min 级别数据做微观结构分析时充值体验；ShareSeer — 当社交媒体情绪被证明对 Contrarian 有显著增量价值时评估升级。

#### B.2.4 Layer 4 — 必需的付费数据

| 数据源 | 费用 | 用途 | 必要性评估 |
|--------|:---:|------|------------|
| **Glassnode Professional** | ~USD 999/mo | 深度链上数据（MVRV、SOPR、交易所流） | 仅 Chain Oracle 成为 Elite 且有明确 ROI 时评估 |
| **WSTS Semiconductor** | ~EUR 11,500/yr | 全球芯片销量月度数据 | 仅 Tech Scout 成为 Elite 且在半导体赛道有持续超额时评估 |
| **siblisresearch Pro** | 订阅费 | 全球 CAPE 历史时间序列 | 仅 Research Affiliates 爬虫无法稳定获取时作为备选 |

**付费决策流程**: 影子达到 Elite 级别 -> 连续 3 个月贡献正边际收益 -> 数据缺口诊断报告显示填充该缺口预估可提升 Sharpe >= 0.15 -> 经 Gate 评审批准后支出。


### B.3 已知数据缺口

| 缺口 | 影响影子 | 当前状态 | 缓解方案 |
|------|----------|----------|----------|
| 日本/中国/EM 内幕交易数据 | Insider Tracker、EM Watcher | 中国：AKShare 部分覆盖；日本/EM：无可用方案 | 短期用股东增减持替代；长期关注监管开放动态 |
| KOSPI VIX 完整历史 | Korea Watcher | yfinance 数据不全，需 KRX 官方 API | 联系 KRX 或使用 iTick 韩国数据补充 |
| WGC 黄金需求数据 | Gold Bug | WGC 无公开 API | 联系 info@gold.org；替代：GLD 持仓变化 + COMEX 持仓 |
| 全球内幕交易 | Insider Tracker | 仅美国有 2 周延迟的 Form 4 数据 | 用机构 13F 持仓作为弱替代 |
| 新兴市场企业级基本面 | EM Watcher | yfinance 对 EM 小盘股覆盖不全 | Twelve Data 备用 + AKShare / nsepy 补充 |

### B.4 数据源指纹与多样性控制

#### B.4.1 数据指纹定义

每个影子的"数据指纹"是一个向量，描述它对每种数据源的依赖程度。数据结构包含：shadow_id、source_weights（数据源到权重的映射，和为1）、primary_source（权重最高的源）、fingerprint_diversity（1 - max(source_weights)，衡量指纹是否过于单一）、last_updated。

#### B.4.2 多样性监控器

DiversityController 提供两个核心方法：
- check_homogenization_risk(all_shadows): 检查是否半数以上影子共享同一主导数据源。这是 BlackRock 风格的内部警告——当太多策略依赖同一数据源时，该数据源的质量问题会导致系统性风险。触发条件：dominant_count / total >= 0.5
- compute_overlap(shadow_a, shadow_b): 计算两个影子数据指纹的 Jaccard 重叠度，用于量化数据源层面的策略相似性

#### B.4.3 同质化应对措施

当检测到数据源同质化时：(1) 按评分从低到高排序，优先为低评分影子更换数据源；(2) 按 DPP 原则最大化整体数据指纹多样性进行重分配；(3) 新旧数据源并行 5 日过渡期；(4) 过渡期后对比数据分布一致性，若偏差 < 2sigma 则切换完成。


### B.5 数据质量验证层（优先于可靠性层执行）

在数据传输到影子之前验证数据质量：

1. **日收益率异常**: |日收益率| > 5σ → 标记可疑，启用备用源交叉验证
2. **零量检测**: volume = 0 在交易日 → 标记
3. **OHLC 一致性**: High < max(Open,Close) 或 Low > min(Open,Close) → 标记无效
4. **备用源交叉验证**: 主/备偏差 > 2σ → 两源均标记
5. **异常操作**: 标记 → 自动切换备用源 → 审计事件记录

实现: `pipeline/data_quality_validator.py` (~150行, 纯Python, 0 LLM)

### B.6 API 调用可靠性架构

所有外部 API 调用统一通过 ReliableAPIClient 包装，提供四项保障：
- **超时保护**: 默认 30s，可在 DataSourceConfig 中按源自定义
- **指数退避重试**: 最多 3 次，间隔 1s -> 2s -> 4s，仅对 TimeoutError、ConnectionError、HTTP 429、HTTP 503 重试
- **熔断器**: 状态机 CLOSED -> [连续失败 3 次] -> OPEN (5分钟) -> HALF_OPEN -> [成功] -> CLOSED；HALF_OPEN 下失败则重新计时
- **主/备源自动切换**: 主源重试耗尽后自动切换到备源（如 yfinance -> Twelve Data）

### B.6 16 个 Expert 影子基准资产映射

每个 Expert 影子需要一个可交易的基准资产用于绩效对比和虚拟组合构建：

| Expert 影子 | 基准资产 | 备选基准 | 说明 |
|-------------|----------|----------|------|
| Gold Bug | GLD / GLDM | IAU | GLDM 费用率更低 (0.10%) |
| Chain Oracle | 50% BTC + 50% ETH | BITW | 按市值权重，季度再平衡 |
| Oil Geologist | XLE | USO + XOP | XLE 覆盖综合能源链 |
| Steel Trader | DBB / XME | SLX | DBB=工业金属期货，XME=矿业股 |
| Bond Guardian | TLT | IEF + LQD | TLT=长期国债，对利率最敏感 |
| Volatility Whisperer | VIX 指数 | VXX | VIX 不可直接投资，用 VXX 模拟 |
| EM Watcher | EEM / VWO | IEMG | VWO 费用率更低 |
| Tech Scout | QQQ | XLK + SOXX | QQQ 含部分非科技股 |
| Financials Eye | XLF | KBE + KIE | XLF 是综合金融指数 |
| Healthcare Pulse | XLV | IBB + XBI | Trial Reviewer 事件 + 基准对比 |
| Consumer Pulse | XLY | XLP + XRT | 可选 vs 必需消费分化是重要信号 |
| Industrial Monitor | XLI | ITA + PAVE | 工业的细分行业轮动 |
| Agriculture Seer | DBA | CORN + SOYB + WEAT | DBA=综合农产品 |
| Real Estate Monitor | VNQ | IYR | VNQ 覆盖面更广 |
| FX Strategist | DXY 篮子: 60% UUP + 20% FXE + 20% FXY | CEW | DXY 篮子近似美元指数 |
| Macro Watcher | 混合: 40% 权益 + 30% 债券 + 15% 商品 + 15% 外汇 | AOR | 通过 VT+TLT+DBC+UUP 四 ETF 合成 |

**基准构建实现要求**: 每日收盘后自动计算每个影子的超额收益；使用对数收益率（log return）避免算术收益率的时间可加性问题；基准本身也可进化——Gate 3 评审认为当前基准不够挑战性时可升级为更细粒度基准。


---

### B.7 实施检查清单

**Layer 1 接入（3-5 工作日）**:
- [ ] 注册并配置 5 个免费 API Key
- [ ] 编写 6 个 Layer 1 adapter 模块（yfinance、FRED、EIA、DeFiLlama、CFTC COT、Ken French）
- [ ] 编写 ReliableAPIClient 基类及熔断器
- [ ] 编写数据源配置文件 config/data_sources.yaml
- [ ] 运行 3 日数据完整性检查（确保所有源正常返回数据）
- [ ] 编写 adapter 单元测试（每个 adapter >= 3 个测试）

**Layer 2 接入（每源 1-3 工作日）**:
- [ ] AKShare adapter + 单元测试
- [ ] AAII Sentiment 爬虫 + 解析器 + 单元测试
- [ ] Research Affiliates CAPE 爬虫 (headless browser) + 解析器
- [ ] nsepy adapter + 单元测试
- [ ] CoinMetrics Community adapter
- [ ] iTick/LME adapter

**数据指纹与多样性控制器（5 工作日）**:
- [ ] DataFingerprint 数据结构实现
- [ ] DiversityController 实现（含同质化检测 + 应对）
- [ ] 指纹更新 schedule（每日收盘后自动更新）
- [ ] 集成测试：模拟 50% 同质化场景，验证警报触发

---

**文档版本**: v1.0
**作者**: MarketMind Architecture Team
**最后更新**: 2026-05-20 07:07 UTC
**下一节预期**: Gate 评审体系 & 用户交互层
