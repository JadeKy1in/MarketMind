# S9 自进化 — 第 0 步：数据基础

> 状态：所有人 2026-09-29 决定先做本步；校准、复盘（LLM）、认知库、知识继承仍按 SPEC §11 冻结到约 50–100 条已结算预测。
> 本步**不改变任何决策、仓位或结算结果**，只让账本多记录两类信息，供以后的自进化使用。

## 1. 目标

1. 每条由 LLM 产出的账本记录都能追溯到"哪个模型、哪一版方法论"。以后评估"成绩变化来自换模型还是换方法"、做模型之间的配对试验，都靠这两个字段。
2. 每条已结算记录都附带一份由代码计算的复盘事实。以后的 LLM 复盘只能引用这些事实，不能自己编过程。

## 2. 来源标注（`meta.llm`、`meta.prompt_version`）

- `meta.llm`：产出这条记录的 LLM 调用**实际**使用的模型名，取自网关返回结果（Claude CLI 的 `modelUsage`，或 DeepSeek 请求的模型名）。Claude 失败退回 DeepSeek 时记 DeepSeek。一次决策重试多次、用到多个模型时，按调用顺序去重后用 `+` 连接。
- `meta.prompt_version`：方法论 prompt 的内容指纹（`sha256` 前 12 位）。影子用该影子的系统 prompt；主管线用决策环节的系统 prompt。prompt 一改，指纹就变。
- 旧字段 `meta.model`（影子里是档位名 "flash"，Playground 里是"思维模型"）保持原样，不再作为模型依据。
- 覆盖范围：长期 / 临时 / 试验影子（`shadows/v3/runner.py`）、主管线交易卡与被迫交易（决策环节报错走兜底时没有 LLM 结果，不写）。纯代码来源（随机基准、missed_path）没有 LLM，不写这两个字段。
- 暂不覆盖：观察名单产生的记录（观察卡跨天触发，要改观察名单存储才能带上来源；需要时可按创建日期关联当天主管线记录的字段）。
- 实现：网关用 `contextvars` 记录当前任务内每次 LLM 调用的实际模型（`gateway/llm_trace.py`），影子在一次决策（含重试）的范围内收集；主管线只有一次决策调用，直接取该次返回的模型。DeepSeek 返回结果现在也带 `model` 字段（取响应里的模型名）。

## 3. 复盘事实（`review` 列，JSON）

结算为 `settled` 时由代码写入；已结算但缺 `review`、或 `review.v` 低于当前版本（`REVIEW_VERSION`）的记录，在之后的结算运行中自动补算，所以以后加字段只需把版本号加 1。字段：

| 字段 | 含义 |
|---|---|
| `v` | 复盘事实的版本号 |
| `direction_correct` | 毛收益方向与判断一致（毛收益 > 0） |
| `error_class` | 代码判定的结果类别：`win`（净赚且跑赢市场基准）/ `beta_carried`（净赚但没跑赢基准，靠大盘）/ `cost_flipped`（毛赚、扣成本后亏）/ `right_but_stopped`（止损或可证伪离场后，原持有期内又到了目标）/ `thesis_wrong`。以后的 LLM 复盘只能引用这个类别，不能自己定性 [R3][R1] |
| `mfe` / `mae` | 持有期内最大有利 / 不利波动，相对成交价的收益率（按方向取符号，`mae` ≤ 0） |
| `bars_held` | 实际持有的 K 线根数 |
| `touched_target` / `touched_stop` | 持有期内是否碰到目标 / 止损（与实际离场原因分开记，用于判断止损是否过紧、目标是否过远） |
| `ambiguous_bar` | 持有期内有一根日线同时碰到止损和目标，日线无法判断先后（结算按先止损处理）[R3] |
| `target_distance` / `stop_distance` | 成交时目标 / 止损离成交价的距离（收益率） |
| `r_multiple` | 毛收益 ÷ 初始风险（止损距离），即 R 倍数 [R3] |
| `atr_pct`、`mfe_atr` / `mae_atr` | 入场前 ATR14 占收盘价的比例；MFE / MAE 除以它，便于跨品种比较 [R3] |
| `target_hit_after_exit`、`post_exit_complete` | 提前离场后，原持有期内是否到了目标；原持有期还没走完时 `post_exit_complete` 为 false，之后的结算会重算 |
| `regime` | 入场前的市场状态：近 20 日涨跌、是否在 50 / 200 日均线之上。以后作为教训的检索与适用条件 [R1] |
| `beat_market` | 超额收益（相对市场基准）> 0；基准缺失时为 null；基准之后补上时整份复盘重算 |

作废（void）和未结算记录没有 `review`。

## 4. 验收

- 离线测试覆盖：模型追踪（含 Claude 失败退回 DeepSeek）、prompt 指纹、影子 / 主管线记录带上两个字段、复盘事实计算与旧记录补算、旧库自动加列。
- 真实账本运行一次结算：已结算记录全部带上 `review`，其他字段不变。
- 全量测试通过后推送。

## 5. 以后（冻结中，不在本步）：外部调研结论

2026-09-29 做了三项只读调研（LLM 交易智能体的记忆与反思、小样本概率校准、交易复盘与模型对比）。以下是对后续步骤的约束，启用前再由所有人确认。标 [推断] 的是综合判断，没有直接来源。

**校准**
- LLM 自报的确信度普遍偏自信，只能当作信号，要按实际胜率修正 [R2]。
- 方法：每个来源拟合 logit(实际) = α + β·logit(确信度)，并向全体来源的均值收缩（分层模型，加交易日随机效应，吸收同一天的相关结果）[R2]。样本少时 Platt / logistic 优于 isotonic（约 200–1000 条以下）[R2]。
- 用有效样本数（按日期聚类、考虑持有期重叠），不用记录条数；置信区间用按日期的块自助法 [R2]。门槛（[推断]）：有效样本约 50 以下只用全体均值或不修正；约 50–200 用收缩后的分来源参数，且置信区间须排除"无需修正"。
- 不用固定分箱的 ECE 排名；奖励区分度（resolution），校准可以修，区分度才是本事 [R2]。
- 仓位：确信度只说明"赚钱的概率"，不足以定仓位，要结合盈亏比；用区间下限、至多 1/4–1/2 Kelly，并设单笔上限 [R2]。

**复盘与认知库**
- 已发表的 LLM 交易智能体（FinMem、FinAgent、FinCon、TradingAgents、CryptoTrade）几乎都只有回测，且测试区间多在模型训练数据之内，记忆效应会虚增成绩；知识截止日之后成绩明显缩水 [R1]。本系统只用前向账本，天然避开这一点。
- 没有外部信号的 LLM 自我批评常常变差；教训只能来自代码结算的结果 [R1]。
- 复盘时先给 LLM 看原始论点、确信度、可证伪条件，再给结果；先按 `error_class` 归类；可遮蔽代码与日期以减少"记忆故事" [R1]。
- 教训的存储：条件规则 + 可证伪的预期效果 + 来源记录编号 + 作者模型与 prompt 版本 + 入场状态标签 + 状态（候选 / 试用 / 生效 / 退役）+ 样本外统计 + 有效期 [R1]。
- 检索：结构化键（标的、板块、持有期、状态标签）优先，文本相似度其次；每次最多约 5 条，状态不符不取 [R1]。
- 验证：每条教训都当作方法论变更，走 beta 配对试验（有 / 无该教训，只用前向交易日），不在产生它的样本上验证；至少几次独立事件，不因一次亏损生成教训 [R1]。
- 衰减：教训有有效期（如 60 个交易日），只有新的样本外证据能续期；失效的降权或删除；小步增量合并，不整篇重写（整篇重写会"语境坍塌"）[R1]。
- 跨模型：直接把一个模型的记忆搬给另一个模型可能变差；教训以模型无关的结构化规则保存，标注作者模型，**每个模型单独试用**后才对它生效 [R1]。

**模型 / prompt 对比**
- 同一交易日、同一输入、同一问题上比较；主指标用 Brier（正确评分规则），盈亏为辅 [R3]。
- 配对差按日聚合，Diebold–Mariano + Newey–West（滞后 ≥ 持有期 − 1）+ HLN 小样本修正；多于两个版本用 Model Confidence Set 或 SPA，并按试过的版本数校正 [R3]。
- 只用模型知识截止日之后的交易日 [R3][R1]。
- 本步记录的 `meta.llm`、`meta.prompt_version` 就是为此准备的。

## 参考文献（访问日期均为 2026-09-29）

[R1] LLM 交易智能体的记忆与反思：Reflexion https://arxiv.org/abs/2303.11366 ；ExpeL https://arxiv.org/abs/2308.10144 ；FinMem https://arxiv.org/html/2311.13743 ；FinAgent https://arxiv.org/html/2402.18485v3 ；FinCon https://arxiv.org/html/2407.06567 ；TradingAgents https://arxiv.org/html/2412.20138 、https://github.com/TauricResearch/TradingAgents ；CryptoTrade https://aclanthology.org/2024.emnlp-main.63/ ；FinBen https://arxiv.org/abs/2402.12659 ；InvestorBench https://arxiv.org/abs/2412.18174 ；StockBench https://arxiv.org/abs/2510.02209 ；LiveTradeBench https://arxiv.org/abs/2511.03628 ；Agent Market Arena https://arxiv.org/abs/2510.11695 ；KTD-Fin https://arxiv.org/html/2605.28359v1 ；知识截止后的成绩 https://arxiv.org/abs/2510.07920 、https://arxiv.org/html/2512.23847v2 ；LLM 回测的前视偏差 https://arxiv.org/abs/2309.17322 、https://www.sciencedirect.com/science/article/pii/S0165176525004392 ；LLM 自我修正 https://arxiv.org/abs/2310.01798 ；记忆衰减 https://arxiv.org/abs/2605.12978 ；语境坍塌 https://arxiv.org/abs/2510.04618 ；交易方案稳健性 https://arxiv.org/abs/2609.19705 ；指标向量检索 https://arxiv.org/html/2609.28771v1 ；跨模型记忆迁移 https://arxiv.org/pdf/2603.23234
[R2] 概率校准：Xiong et al. https://openreview.net/forum?id=gjeQKFxFpZ ；Schoenegger et al. https://www.science.org/doi/10.1126/sciadv.adp1528 ；Halawi et al. https://arxiv.org/abs/2402.18563 ；Metaculus AI 基准 https://www.lesswrong.com/posts/P8YwCvHoF2FHQoHjF/metaculus-q4-ai-benchmarking-bots-are-closing-the-gap ；ForecastBench 对比 https://goodjudgment.com/human-vs-ai-forecasts/ ；Niculescu-Mizil & Caruana https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf ；Beta calibration https://proceedings.mlr.press/v54/kull17a.html ；Turner et al. https://link.springer.com/article/10.1007/s10994-013-5401-4 ；Baron et al. https://pubsonline.informs.org/doi/10.1287/deca.2014.0293 ；ECE 偏差 https://proceedings.mlr.press/v151/roelofs22a/roelofs22a.pdf ；CORP 可靠性图 https://www.pnas.org/doi/10.1073/pnas.2016191118 ；一致性区间 https://journals.ametsoc.org/view/journals/wefo/22/3/waf993_1.xml ；分解偏差 https://link.springer.com/article/10.1007/s00382-011-1191-1 ；相关预测的检验 https://www.nber.org/system/files/working_papers/w18391/w18391.pdf ；Kelly 收缩 https://pubsonline.informs.org/doi/10.1287/deca.2013.0271
[R3] 交易复盘与模型对比：Edge ratio https://www.buildalpha.com/what-is-e-ratio/ ；R 倍数与期望 https://www.pnlledger.com/expectancy-r-multiples-the-plain-english-guide/ ；SQN https://www.tradesviz.com/glossary/system-quality-number/ ；MFE / MAE https://spreadsheetshub.com/blogs/articles/how-to-track-mfe-and-mae-to-improve-your-exit-analysis ；K 线内顺序歧义 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6240638 、https://greyhoundanalytics.com/blog/stop-losses-in-backtestingpy/ ；Brier 分解 https://rmets.onlinelibrary.wiley.com/doi/abs/10.1002/qj.2985 ；聚类标准误 https://arxiv.org/abs/2411.00640 ；DM 检验 https://pkg.robjhyndman.com/forecast/reference/dm.test.html ；MCS https://onlinelibrary.wiley.com/doi/abs/10.3982/ECTA5771 ；SPA https://papers.ssrn.com/sol3/papers.cfm?abstract_id=264569 ；Deflated Sharpe https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 ；幸存者偏差 https://www.quantrocket.com/blog/survivorship-bias/ ；重叠收益的标准误 https://warwick.ac.uk/fac/soc/wbs/subjects/finance/faculty1/anthony_neuberger/improved.pdf

说明：部分来源调研 Agent 只读到摘要或检索摘要（[R1] 中 2510.07920、ScienceDirect 那篇与 2603.23234；[R2] 中 Metaculus 那篇），结论按"待核实"看待。
