# Playground 纯代码量化 agent

> 2026-09-29 所有人决定：把经典的纯代码策略作为 Playground 候选接入（零 LLM token），同时作为每个 AI 影子都必须跑赢的强基准。规格依据：`docs/SPEC_v3.md` §4 ④、§6.1、§7、§8；接入契约见 `docs/archive/project-docs/playground-agent-onboarding.md`。

## 1. 四个 agent

| agent（`source_id`） | 规则（参数取自文献，未在我们的数据上调参） | 标的 | 方向 | 调仓 / 持有 | 出处 |
|---|---|---|---|---|---|
| `tsmom`（`playground:tsmom`） | 过去 12 个月收益减 T-bill 门槛的符号：正做多、负做空；强度 = 超额收益 ÷ EWMA 年化波动（质心 60 天） | SPY QQQ IWM EFA EEM TLT IEF GLD DBC USO BTC-USD ETH-USD | 多 / 空 | 每月一次；21 根日线（加密 30 个 UTC 日） | Moskowitz, Ooi & Pedersen (2012) |
| `short_term_reversal` | 过去 5 根 K 线收益在 11 个行业 SPDR ETF 中排最后 2 名的买入 | XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY | 只做多 | 每周一次；5 根 | Jegadeesh (1990)；Lehmann (1990) |
| `trend_state` | 包装 `marketmind.trend` 状态机（不复制规则）：新的入场信号 → 做多 | `TREND_UNIVERSE`（28 个） | 只做多 | 事件驱动；60 根 | `docs/TREND_DESIGN.md` |
| `dual_momentum` | SPY / EFA / BTC-USD 中 12 个月收益最高者，且高于 T-bill 才持有；否则持有 IEF（无数据时 TLT） | 同左 | 只做多 | 每月一次；21 根（BTC 30 天） | Antonacci (2012) |

共同约定（`marketmind/playground/agents/_quant/`）：
- **数据**：`trend.state.fetch_inputs` → `gateway.price_history`，只用已收盘的完整日线；T-bill 门槛 = `^IRX` 过去 252 日均值（与趋势状态机相同）。缺数据、历史不足或最后一根完整 K 线超过 7 天 → 标记为 unavailable，不做判断。拿不到 `^IRX` 时 `tsmom`、`dual_momentum` 不出判断（超额收益算不出来）；`trend_state` 沿用状态机自己的做法（门槛记 0，并在 `hurdle_source` 中写明）。
- **可证伪条件**：以信号收盘价 ∓ 3×Wilder ATR(20) 为止损（与状态机的吊灯止损距离相同），写入账本 `falsifier_rule`（做多用 `close_below`，做空用 `close_above`），由结算按收盘价触发。`trend_state` 用信号当时生效的吊灯止损价；账本里的止损价不会像状态机那样随价格上移。原文策略本身没有止损，这里是为满足 L5 加的灾难止损。
- **确信度** = 0.5 + 0.15 × min(1, 强度 / 2)，范围 0.50-0.65（仓位 $100-$400）。这些策略文献记载的胜率不高，确信度的校准交给账本的 Brier 分。`trend_state` 用 12 个月超额收益在全体标的中的百分位排名；`dual_momentum` 在规则切换到债券时确信度取 0.50（这是规则，不代表看好）。
- **零 LLM**：adapter 不导入 `gateway.async_client`，由测试检查。`mock=True` 时不访问网络。

## 2. 为什么不每天出判断

§6.1 的"每日强制决策"只约束长期影子；`ledger_bridge` 明确规定 Playground 候选不强制每天交易。月度和周度策略如果每天都出判断，会让同一笔持仓在账本里叠出十几条互相重叠的记录，放大样本数，也扭曲 MinTRL 对有效样本的估计。所以：
- `tsmom` / `dual_momentum` 只在每月 1-7 日（UTC）的**第一次运行**记录（`signal_key` = 月份），其余时间 `directional_calls` 为空，`no_calls_reason` 写明原因，也不抓行情。7 天内都没有运行过的月份整月跳过，不在月末补记。
- `short_term_reversal` 在每个 ISO 周的第一次运行时记录（`signal_key` = 周，例如 `2026-W40`）。
- `trend_state` 只记录信号出现在该标的最近 3 根完整 K 线以内、且仍处于 TREND 的入场，每个（标的，信号日期）只记录一次。晚一两天记录时，入场价会比状态机的入场价晚。

## 3. 对 `ledger_bridge.py` 的改动（最小化）

原 bridge 无法把代码算出的止损价交给结算，也无法防止月度信号被重复记录，因此改了以下几处：
- `hold_bars` 与 `hold_days` 都可以用（原来只认 `hold_days`）。
- 可以传 `falsifier_rule`：类型必须是 `close_below` 或 `close_above`；价格与记录时的收盘价方向不符（多单止损价在收盘价之上等）时丢弃这条规则，保留文字形式的可证伪条件，并写日志。
- `signal_key`：同一个 agent 的同一个 key 已经在账本里（不论哪天记的）时，这笔判断跳过，计入 `dropped`。
- `signal`（代码算出的事实）和 `signal_key` 写入 `meta`，供白箱回溯。
不带这些字段的 agent（例如 `serenity_reply`）行为不变。

## 4. 已知局限

- 短期反转的文献研究的是个股。行业层面的短期收益更常见的是延续而不是反转（Moskowitz & Grinblatt 1999），所以 `short_term_reversal` 可能是一个负基准，这一点在上线前就已记录。只做多意味着它只检验"输家"这一腿。
- `tsmom` 的原文在期货上做多空并按 40%/σ 定仓位；这里用 ETF 和现货加密代替，仓位用账本统一的"确信度 → 金额"标尺。
- `dual_momentum` 把 Antonacci 的两资产 GEM 扩展到三种风险资产，绝对动量用胜出者自己的收益判断（2012 论文的写法）；债券用 IEF，原文用综合债券指数。
- 持有期受 bridge 上限约束（最长 60 根），`trend_state` 以 60 根作为"持有到趋势离场"的替代。
- 晋升阶梯要求 ≥20 次结算、≥60 个交易日。`dual_momentum` 每月只有 1 条记录，至少要约 20 个月才能被评估。

## 5. 多空辩论台 `debate_desk`（LLM，多 agent）

> 2026-09-29 所有人决定。代码：`marketmind/playground/agents/debate_desk/`（`adapter.py`、`prompts.py`、`manifest.json`）；测试：`marketmind/tests/test_playground/test_debate_desk.py`（LLM 全部用 mock）。`source_id` = `playground:debate_desk`。

结构借鉴 TradingAgents（参考 7、8）：多头、空头研究员基于同一份分析材料辩论，再由风险经理 / 主持人给出一条结构化决定。只借鉴设计，没有复制代码或提示词；为了控制成本，这里做了大幅裁剪（原文每次预测约 11 次 LLM 调用、20 多次工具调用）。

| 步骤 | 谁来做 | 内容 |
|---|---|---|
| 标的池 | 代码 | SPY QQQ GLD TLT BTC-USD ETH-USD，加上当天 20 根 K 线收益最高的 3 个行业 SPDR ETF（11 选 3） |
| 预选 | 代码 | 按 \|20 根收益\| ÷（20 根日收益标准差 × √20）取前 `DEFAULT_TICKERS` = 3 个。不直接用 \|20 根收益\|，否则波动大的加密货币几乎每天都会入选 |
| 事实表 | 代码 | 收盘价，5 / 20 / 60 根与 12 个月收益，SMA50 / SMA200 及收盘相对它们的位置，Wilder ATR20，波动调整后动量及排名，`data/trend/<date>.json` 中的趋势状态（3 天内的文件，否则写 DATA_UNAVAILABLE），最多 3 条提到该市场的新闻标题 |
| 开场 | 多头、空头（各 1 次调用） | 只看事实表 |
| 反驳 | 多头、空头（各 1 次调用） | 各自看到对方的开场论点 |
| 裁决 | 风险经理（1 次调用） | 看事实表和四段论点，只返回严格 JSON：`{ticker, action: enter_long\|enter_short\|no_trade, confidence 0-1, hold_days 5-30, thesis, key_risk}` |
| 止损、仓位、记录 | 代码 | 止损 = 最后一根完整 K 线收盘 ∓ 3×ATR20（沿用 `_quant`），写入 `falsifier_rule`；仓位由账本统一的"确信度 → 金额"标尺决定 |

所有调用都走 `gateway.async_client.chat_with_integrity(model="flash")`（带数据诚信头和时间锚，用 `usage_tracker` 记在 `playground:debate_desk` 名下，超时 300 秒）。每个标的的五次调用包在 `llm_trace.trace()` 里。

**成本**（`adapter.token_estimate()`：按真实提示词长度 ÷ 4 估算，事实表按最长情形计（3 条 200 字符的标题），回复按字数上限计（开场 180 词、反驳 150 词），外加 gateway 的完整性头；不含模型的隐藏思考 token）：

| 每天标的数 | 调用次数 | 估算 token |
|---|---|---|
| 3（默认） | 15 | 约 23.6k |
| 4 | 20 | 约 31.4k |
| 5（`MAX_TICKERS`，硬上限 `MAX_CALLS_PER_RUN` = 25） | 25 | 约 39.3k |

目标是每天不超过约 40k token。5 个标的时已经贴近上限、没有余量，所以默认取 3 个。另外，gateway 的 `chat_flash` 会按 max(max_tokens, 16384) 预留预算、事后按实际用量结算；每天 15 次调用也会占用 Flash 每日调用次数上限（默认 100 次）。

**判定规则**
- **严格 schema**：裁决必须是一个 JSON 对象（允许包在一层 ``` 代码块里），不从周围文字中提取，也不做修补。缺字段、ticker 与请求不一致、action 不在枚举内、confidence 不在 0-1（或不是数字）、hold_days 不是 5-30 的整数、thesis 或 key_risk 为空，任何一项不满足 → 该标的当天不出判断，原因记在输出的 `debates[ticker].outcome`。多出来的键（例如 LLM 自己给的 `stop_loss`）一律忽略，只在 `ignored_keys` 中留档（L3）。
- 任何一次开场或反驳没有拿到回复 → 该标的停止，不再调用裁判。不重试，避免成本失控。
- `no_trade`，或者选择入场但 confidence < 0.5（裁判自己都不看好）→ 不出判断。
- **确信度**：账本记录值 = 0.5 + 0.2 ×（裁判 confidence − 0.5）/ 0.5，范围 0.50-0.70，对应仓位 $100-$460；裁判的原始值记在 `meta.signal.judge.confidence`。之所以压缩，是因为 LLM 口头给出的置信度普遍偏高（参考 9）。采用线性映射而不是直接截断，是为了保留裁判给出的相对强弱；上限略高于纯代码基准的 0.65。最终的校准交给账本的 Brier 分。
- **去重**：`signal_key` = `标的:方向:ISO 周`，同一标的、同一方向每周最多记录一条。持有期最长 30 天，所以不同周的记录仍可能重叠，这一点在评估时需要注意。bridge 本身也保证每个 agent 每天只记录一次。

**账本 meta**：bridge 只把 `signal` 写进 `meta`，所以这些字段都放在 `meta.signal` 下：`judge`（action / confidence / hold_days / thesis / key_risk）、`reasoning_summary`、`llm`（`llm_trace.label`，即实际回答的模型）、`llm_tier`、`prompt_version`（`debate_desk/v1`）、`prompt_fingerprint`（全部系统提示词的 sha256 前 12 位）、止损价及依据、事实表数字。`meta.model` = `bull_bear_debate_v1`。没有为了把 `llm` / `prompt_version` 放到顶层而修改 `ledger_bridge.py`。

**信息防火墙与注入防护**
- 从 Playground context 中只取新闻的 `title` 和 `source_name`，按每个标的的关键词匹配。context 里的其他字段（`summary`、`market_data`，以及任何残留的主管线或影子字段）都不会进入提示词，测试对此有检查。
- 读取的数据只有：公开日线（`gateway.price_history`，只用完整 K 线）和纯代码趋势状态机写出的 `data/trend/` 文件。不读账本、影子、主管线或其他 Playground agent 的输出。
- 新闻标题先删掉 `<<<` / `>>>`，再经 `pipeline.defang.defang_text` 处理，然后放进 `<<<UNTRUSTED_HEADLINES … UNTRUSTED_HEADLINES>>>` 之间。LLM 的论点在交给下一个角色之前会再次删掉 `<<<` / `>>>` 并 defang，然后放进 `<<<DEBATE_ARGUMENT … >>>` 之间。系统提示词明确说明这些内容只是待衡量的说法，不是指令。

**已知局限**
- 调用预算按单次运行计，不按自然日。bridge 每天只记录一次，但同一天重复运行仍会重复消耗 token。
- TradingAgents 原文只做了 3 个月回测、没有实盘，不能作为这套结构有优势的证据；本 agent 同样要通过晋升阶梯（≥20 次结算、≥60 个交易日）来检验。
- 原文在分析和决策环节用深度思考模型；这里所有角色都用 Flash（与影子一致，也是为了控制成本）。
- 持有期由裁判在 5-30 天内自选，这是 LLM 给出的决策参数，不是价格。它会影响每笔记录的可比性。

## 6. `memory_desk`：带记忆与反思的 LLM agent，及其无记忆对照组

> 2026-09-29 所有人决定。设计约束来自 `docs/S9_DESIGN.md` §3（复盘事实）与 §5（记忆与反思的调研结论）。代码：`marketmind/playground/agents/memory_desk/`（`adapter.py`、`memory.py`、`prompts.py`）与 `agents/memory_desk_control/`。

**做什么**：固定小标的池 SPY、QQQ、GLD、TLT、BTC-USD、ETH-USD，每天一次 LLM 调用，给出 1–3 个多 / 空判断，持有 5 根 K 线。
- **事实表（代码）**：只用已收盘的完整日线，算 5 / 20 / 60 日收益、相对 MA50 / MA200 的位置、ATR20，以及与结算复盘相同定义的状态标签（`ret20_up/down`、`above/below_ma50`、`above/below_ma200`）；另附最多 8 条公开新闻标题。每天只算一次，缓存在 `<data_dir>/playground/memory_desk/facts/<日期>.json`，两个孪生 agent 读同一份。
- **止损、确信度、持有期（代码）**：止损 = 信号收盘 ∓ 3×ATR20，写成账本 `falsifier_rule`（与 `_quant` 相同）；LLM 给的确信度截到 0.50–0.70，原值记在 `signal.raw_confidence`；已有未结算记录的标的当天不再开仓；每个（日期，标的）只记一次（`signal_key`）。
- **信息防火墙**：输入只有公开行情、公开标题和**本 agent 自己**的账本记录；不读主管线、影子或其他 Playground agent 的输出（测试检查）。

**三层记忆**（参照 FinMem 的分层记忆 [10] 与旧版影子记忆的三层 + 90 天情景期限），存于 `<data_dir>/playground/memory_desk/memory.json`（原子写入）：
| 层 | 内容 | 衰减 |
|---|---|---|
| working | 自己最近 5 天的判断及其状态 / 结果 | 每次从账本重建 |
| episodic | 自己已结算的记录 + 结算代码写入的复盘事实（`error_class`、MFE/MAE、入场状态标签、净收益） | 离场 90 天后过期，过期后不再作为教训证据 |
| semantic | 教训（见下） | 60 个交易日有效期，只有新的样本外支持证据能续期 |

**教训**（参照 ExpeL 从自身成败经验中提炼规则 [11]，按 S9 §5 限定为只来自代码结算的结果、不来自自我批评）：
- 结构：条件（方向 × 状态标签，或 标的 × 方向，两种固定模板）+ 主张（净赚比例高于 / 低于基准）+ 证据编号 + 独立样本数 + 净赚比例 + 基准 + 样本外统计 + 创建 / 到期日期 + 状态（candidate / active / retired）+ 创建时的 prompt 版本。所有数字与状态都由 `memory.py` 计算。
- "净赚" = 复盘 `error_class` 为 `win` 或 `beta_carried`；基准 = 条件之外的自己的独立交易的净赚比例（不足 5 笔时取 0.5）。独立：同一入场日只算一笔；同一标的持有期重叠（入场相隔不到 7 天）只算第一笔。
- candidate：独立样本 ≥ 3 且 |净赚比例 − 基准| ≥ 0.10。创建时已看到的交易记为样本内证据。
- active：支持主张的独立交易 ≥ 5，全样本在主张一侧超出基准 ≥ 0.10，且**创建之后才结算**的样本外交易 ≥ 2、其净赚比例也在主张一侧（先验证后使用，不在产生它的样本上验证）。条件不再满足时降回 candidate。
- retired：全样本净赚比例不再在主张一侧（反证）；或样本外交易 ≥ 3 笔且落在另一侧；或到期未续。
- LLM 只在教训刚转为 active 时给它写一句措辞（`WORDING_SYSTEM_PROMPT`，最多 120 字，不许加原因、条件和数字）；失败时用代码模板。措辞不影响任何计数与状态。
- 检索：只取 active、且条件与今天事实表的状态标签相符的教训（标的类教训只要该标的今天有数据即相符），按 |差值| × √n 排序，最多 5 条；放在用户 prompt 的 `<<<MEMORY>>> … <<<END MEMORY>>>` 段落内，一并给出工作记忆与最近 5 笔已结算交易的事实。
- 防后见之明：教训只由结算代码的事实计算；样本外验证；至少 3 笔才建候选、5 笔才启用；LLM 看到的是带样本数与基准的统计，不是它自己写的复盘故事。

**对照组 `memory_desk_control`**（旧版 AEL 实验的"复制体对照组"要求）：同一份事实表、同一个系统 prompt（`prompt_version` 相同）、同一套代码规则，唯一的区别是用户 prompt 里没有记忆段落，也不维护记忆库（测试检查两者 prompt 去掉记忆段落后逐字相同）。它记为独立来源 `playground:memory_desk_control`。以后在晋升阶梯上按同一交易日做配对比较（Brier 为主，按日聚合的配对差，S9 §5 的方法），用来检验记忆是否真的有帮助；两者各自也要跑赢同域随机基准。

**可追溯性**：每笔判断的 `meta.model` 为 agent 名；`meta.signal` 内记录 `prompt_version`（系统 prompt 指纹）、`llm`（网关实际应答的模型，经 `llm_trace`）、`memory`（是否带记忆）、`lessons_used`（LLM 声称用到且确实被检索到的教训编号）和当天的事实。注意：`ledger_bridge` 目前只把 `signal` 写进 `meta`，所以这两个字段在 `meta.signal` 下，而不是影子那样的顶层 `meta.llm` / `meta.prompt_version`；如需顶层，要在 bridge 里加两行（不在本次范围）。

**Token 成本（估算）**：系统 prompt 约 1.3k 字符，带满记忆段落（10 条工作记忆、5 笔交易、5 条教训）的用户 prompt 约 4.3k 字符，输出约 1k 字符：`memory_desk` 约 2–2.5k token / 天，教训转为 active 的那天多一次约 0.6k 的措辞调用；对照组约 1.3–1.5k token / 天。两者都远低于每天 15k 的上限。走 Claude CLI 时 CLI 自身的系统开销不在此估算内。

**已知局限**：条件模板共 24 个（方向 × 6 个标签、标的 × 方向），存在多重检验；样本外验证是主要防线，门槛 0.10 与 5 / 2 / 3 的计数是先验设定、未在数据上调参 [推断]。交易日按工作日计（不计交易所假日）。每天约 1–3 笔、持有 5 根，最快也要约一个多月才可能出现第一条 active 教训。

## 7. `ml_gbm`：经典机器学习 agent（梯度提升树，纯代码）

> 2026-09-29 所有人决定。代码：`marketmind/playground/agents/ml_gbm/`（`features.py` 特征与标签、`model.py` 训练与缓存、`adapter.py` 每日判断、`backtest.py` 样本外验证）；测试：`marketmind/tests/test_playground/test_ml_gbm.py`（合成数据，离线）。`source_id` = `playground:ml_gbm`。样本外结果见 `docs/ML_GBM_BACKTEST_2026-09-29.md`。只用已声明的依赖（scikit-learn、numpy；缓存用 sklearn 自带依赖 joblib），零 LLM。

**思路**：Gu、Kelly、Xiu（参考 12）的结论是树模型和神经网络能利用预测变量之间的非线性交互，在收益预测上优于线性模型。这里用同类模型（sklearn `HistGradientBoostingClassifier`）在一组流动性好、所有人可直接交易的标的上预测短期方向。它是一个"经典 ML 能否跑赢简单基准"的检验，不预设它有效。

| 项目 | 规定 |
|---|---|
| 标的 | 11 个行业 SPDR ETF + SPY QQQ IWM GLD TLT BTC-USD ETH-USD（18 个） |
| 数据 | `gateway.price_history`，只用完整日线（`complete_bars`），取 10 年；`^VIX` 取不到时该特征记为缺失（模型原生支持缺失值） |
| 特征（19 个） | 自身：5/20/60/120/252 根收益，20/60 根年化波动，相对 SMA50/SMA200 的距离，相对 55 根最高价的距离，ATR20/收盘，20 根对数成交量 z 分数，往返成本；截面：20/60/120/252 根收益在当日全体标的中的百分位；市场：SPY 20 根收益、VIX 收盘。某日的行只用该日及以前的 K 线；其他标的与 SPY / VIX 取"该日或之前最近一根"（超过 7 天视为缺失）。测试检查：把所有序列截断到某日后重算，该日的特征逐位相同 |
| 标签 | 未来 10 根 K 线（收盘到收盘）收益 > 账本往返成本（`2 × ledger.settlement.cost_bps`：ETF 0.10%，BTC/ETH 2.00%）。选"扣成本后的绝对收益"而不是"相对 SPY 的超额"，因为账本对这笔判断的结算就是扣成本后的净收益 |
| 模型 | 固定超参数，事先设定、未在数据上调：学习率 0.05，150 轮，深度 ≤ 3，≤ 8 个叶子，每叶 ≥ 200 样本，L2 = 1.0，64 个分箱，不用早停，`random_state` 固定（结果可复现，测试检查） |
| 防泄漏 | 用于日期 T 的模型只用：行日期 ≤ SPY 日历上 T 往前 15 根（清除 = 标签期 10 根，再加禁入期 5 根），且标签结束日 ≤ T 往前 5 根的样本（参考 13 的 purging / embargo）。测试检查训练窗口的最后一行和最晚标签结束日 |
| 校准 | 训练样本按日期分两段：前 80% 训练树（只用标签在校准段开始前已结束的行），后 20% 拟合 Platt 缩放。给出的是 Platt 校准后的概率 |
| 重训与缓存 | 每个 ISO 周最多重训一次（扩展窗口）；模型连同训练截止日、特征列表、版本号存到 `<data_dir>/playground/ml_gbm/model.joblib`（另有可读的 `model_meta.json`）。版本、特征列表或所在周不一致时重训 |
| 每日判断 | 在有新鲜完整 K 线的标的中，取校准概率 ≥ 0.55 的最高 2 个做多；持有 10 根；止损 = 信号收盘 − 3×ATR20（沿用 `_quant`，写入 `falsifier_rule`）；确信度 = 校准概率截到 0.50–0.70；`signal_key` = `标的:ISO 周`，每个标的每周最多记一次 |
| 白箱事实 | `meta.signal`：原始与校准概率、阈值、排名、止损与 ATR、模型的训练截止日 / 标签截止日 / 训练行数 / 训练期正例率，以及置换重要性前 5 的特征（校准段上 AUC 的平均下降）和该标的当天的特征值，全部是数字 |

**样本外结果（2018-10 至 2026-09，402 次每周重训）**：AUC 0.513，命中率 52.8%（正例率 55.4%），Brier 0.254，比"训练期正例率"这一常数预测还差（技能分 −0.025）。只看 ETF 时 AUC 0.492；汇总 AUC 略高于 0.5，主要来自模型区分了加密与 ETF 的正例率（最重要的特征是往返成本，即资产类别）。线上规则的 top-2 策略扣成本后年化 1.7%、最大回撤 −61%，同期全体等权年化 15.6%。**结论：没有证据表明这个模型有预测力。** 它照常接入，作为"经典 ML"这一类方法的基准，由晋升阶梯在实盘记录上判定；不会因为回测结果去调参数（那会把样本外变成样本内）。

**已知局限**
- 回测不含止损、按收盘价成交；账本按次日开盘入场，两者不完全一致。
- 训练样本的标签期相互重叠（相邻日的 10 根窗口共享 9 根），有效样本远少于行数；没有按唯一性加权（参考 13 第 4 章）[推断：对固定超参数、不做模型选择的做法影响有限]。
- 加密货币的"根"是 UTC 日（10 根 = 10 天），ETF 是交易日（10 根 ≈ 14 天）；`ret_252` 对加密约是 8 个月。
- 因为长期正例率约 55%，0.55 的阈值选择性不强：回测中约 60% 的预测在 0.55 以上，线上几乎每天都会有 1–2 笔。
- 各标的的持有期（10 根）重叠，每周每个标的最多一条，评估时要注意相关性。

## 8. `minervini_sepa`：趋势模板 + VCP 突破（代码为主）

> 2026-09-29 所有人决定（候选理由见 `docs/PLAYGROUND_CANDIDATES_2026-09-29.md` 第 1 节）。代码：`marketmind/playground/agents/minervini_sepa/`（`rules.py` 规则、`universe.py` 标的池、`adapter.py`、`prompts.py`）；测试：`marketmind/tests/test_playground/test_frameworks.py`。`source_id` = `playground:minervini_sepa`。规则出处：Minervini (2013) 第 5 章（趋势模板）与第 10 章（VCP）[15-18]；参数都是书中或通行的取值，没有在我们的数据上调参。

**标的池（有界）**：`universe.py` 里约 150 只美国大盘股（覆盖 11 个 GICS 行业，按 2026-09 的市值选）+ 11 个行业 SPDR ETF。仓库里没有指数成分股来源，而对 `universe.equities` 的约 1 万个代码逐个取行情每天要上万次请求，所以用固定种子列表。运行时：先用 NASDAQ Trader 目录（`universe.equities`，取不到时原样使用种子列表并注明）去掉已退市的代码，再按拉到的 K 线计算最近 50 根的"收盘 × 成交量"中位数，低于 5000 万美元的剔除。已知偏差：今天的大盘股是过去的赢家（幸存者偏差）；相对强度只在这个池内排名，不是 IBD 的全市场排名。

**趋势模板（8 项，全部由代码判断，在信号那根 K 线上）**：收盘 > SMA150 且 > SMA200；SMA150 > SMA200；SMA200 至少上升一个月（SMA200[t] > SMA200[t−21]）；SMA50 > SMA150 且 > SMA200；收盘 > SMA50；收盘 ≥ 52 周最低 × 1.30（书中为 30%，后来一些转述用 25%，这里取书中的 30%）；收盘 ≥ 52 周最高 × 0.75；相对强度排名 ≥ 70。52 周 = 最近 252 根 K 线的日内最高 / 最低。
**相对强度**：IBD 的 RS 评级算法不公开。这里用常见的公开近似 [推断：通行做法，没有官方出处]：得分 = 0.4×63 根收益 + 0.2×126 根 + 0.2×189 根 + 0.2×252 根，在池内排成 1–99 的百分位。

**VCP（我们对书中文字描述的精确化）**，对候选突破 K 线 t，只用 t 之前的 K 线：
| 项目 | 定义 |
|---|---|
| 底部起点 | 最近 130 根中最高价所在的 K 线；到 t 至少 15 根（3 周） |
| 波段高点 | 最高价高于前 3 根、不低于后 3 根（右侧 3 根确认） |
| 回调 | 从每个波段高点到下一个波段高点之间的最低价；若某段低点不高于上一次回调的低点（更低的高点 + 更低的低点），视为同一次回调仍在继续，并入上一次，从两者中较高的高点起算。所以回调低点逐次抬高 |
| 形态 | 2–6 次回调，幅度逐次严格变小；第一次 ≤ 35%，最后一次 ≤ 10%；最后一次回调的平均成交量低于第一次，也低于 t 之前 50 根均量（量能枯竭） |
| 枢轴 | 最后一次回调的高点 |
| 突破 | t 的收盘首次站上枢轴（t−1 收盘不高于枢轴），且 t 的成交量 ≥ 前 50 根均量 × 1.4（通行说法是"比均量高 40–50%"） |

**判断（全部代码）**：最近 3 根完整 K 线内出现 VCP 突破、突破当天趋势模板 8 项全满足、最新收盘仍在枢轴之上 → 做多。止损 = 最后一次回调的低点，但离突破收盘不超过 8%（Minervini 要求亏损远小于 10%，7–8% 是他和 O'Neil 常用的上限）；写入账本 `falsifier_rule`（`close_below`）。持有 30 根（要求 20–40 根，取中间）。确信度 = 0.5 + 0.2 ×（RS − 70）/ 29，范围 0.50–0.70。每天最多 3 条（RS 高者优先，其次突破量比）。`signal_key` = `标的:枢轴日期`，同一枢轴只记一次。

**可选的 LLM 调用**：只有当天有判断、且新闻标题提到这些公司（公司简称，或 2 个字母以上的大写代码）时，才调用一次 Flash（`chat_with_integrity`，记在 `playground:minervini_sepa` 名下），让它根据标题给每个标的写一句催化剂说明（≤ 160 字符，不许写数字和建议）。标题只取 `title` 和 `source_name`，删掉 `<<<` / `>>>` 后经 `defang_text` 处理，放在 `<<<UNTRUSTED_HEADLINES … UNTRUSTED_HEADLINES>>>` 之间。回复必须是 `{"notes": {...}}` 这个 JSON 对象，不合格就不写说明。说明存在 `meta.signal.catalyst_note`；只有写出了说明，才在 `meta.signal` 记 `llm` / `prompt_version`（bridge 会把它们提到顶层 `meta`）。判断本身、所有数字与仓位都不依赖这次调用（测试检查：LLM 返回垃圾时，判断逐字相同）。每个 UTC 日最多一次（`<data_dir>/playground/minervini_sepa/llm_days.json`）。

**成本**：`adapter.token_estimate()` ≈ 1.1k token / 次（3 个标的 × 3 条最长标题）；只有出现突破且有相关标题的日子才调用。

**2026-09-29 真实数据（只读，临时目录）**：155 个代码全部仍在上市目录中、全部通过流动性门槛；28 个通过趋势模板（如 AAPL、AMD、LLY、NVDA、TSM、XLK），但最近 3 根内没有合格的 VCP 突破 → 当天 0 条判断，不调用 LLM。未通过 VCP 的主要原因：底部不到 15 根（刚创新高）、只有 1 次回调、回调没有逐次变小（例如 NVDA 15.6% → 11.3% → 11.4% …）。
频率估算（同一套规则逐日回放，2025-10-02 至 2026-09-29，拉到的 2 年日线只够回放最近 12 个月）：共 10 次信号（AMD、GE、GILD、PLTR、VLO、GS、SBUX、PLD、SLB、LLY），约每月 0.8 次，从未达到每天 3 条的上限。这只是次数估算，不是回测（没有计算收益）。

**已知局限**
- "回调逐次严格变小"很严格：只要中间有一次比上一次略深（NVDA 的 11.3% → 11.4%）就不算。这是对书中描述的直译，没有放宽，以免事后调参。
- 趋势模板与 VCP 用日线的最高 / 最低价；个别来源只有收盘价的 K 线（`close_only`）会让回调幅度偏小。
- 账本按次日开盘入场，止损按收盘价触发，而 Minervini 用盘中止损单；跳空低开时实际亏损可能超过 8%。
- 持有期固定 30 根；原方法是按走势逐步卖出。

## 9. `druckenmiller_liquidity`：流动性面板 + 规则闸门 + 稀疏 LLM

> 2026-09-29 所有人决定。代码：`marketmind/playground/agents/druckenmiller_liquidity/`（`dashboard.py` 面板与闸门、`adapter.py`、`prompts.py`）；测试同上。`source_id` = `playground:druckenmiller_liquidity`。

**框架（用我们自己的话概括，出处为 Druckenmiller 2015 年 1 月在 Lost Tree Club 的讲话，第三方文字稿 [19]）**：推动大类资产大行情的主要是央行流动性，而不是企业盈利；平时少动，等到流动性背景和价格趋势指向同一方向时才下重注；两者不再一致时要尽快认错。这里没有复制讲话原文。

**面板（全部代码，FRED）**：
| 项目 | 定义 |
|---|---|
| 净流动性 | WALCL / 1000 − WTREGEN / 1000 − RRPONTSYD，单位十亿美元。WALCL（美联储总资产）是周三时点值、百万美元；WTREGEN（财政部一般账户 TGA）是截至周三的周平均、百万美元；RRPONTSYD（隔夜逆回购）是日度、十亿美元 [20]。每个 WALCL 周三取同一周的 TGA、当天（否则 5 天内最近一天）的逆回购。周三时点值与周平均混用是这个公式的通行简化，误差相对 13 周变化很小 |
| 流动性冲量 | 4 周变化 d4、13 周变化 d13（按周度点）。rising：d13 > 净流动性的 0.5% 且 d4 > 0；falling：d13 < −0.5% 且 d4 < 0；否则 mixed。0.5%（目前约 290 亿美元）是先验取值 |
| 其他 | 2 年、10 年美债收益率及 4 / 13 周变化（百分点）；广义美元指数 DTWEXBGS 及 13 周涨跌幅；高收益债利差 BAMLH0A0HYM2 及 13 周变化 |
| 趋势 | SPY QQQ TLT GLD BTC-USD 的趋势状态，用 `marketmind.trend.state` 在完整日线上重算（与 `data/trend/<date>.json` 同一套代码），这样也能得到过去各周的状态 |

时点：某日的评估只用该日之前日期的 FRED 观测、该日及之前的 K 线；没有处理 FRED 的事后修订。WALCL 超过 14 天未更新 → 冲量记为不可用，不开闸。

**闸门（代码）**：流动性冲量与该资产自己的趋势必须一致。
- 做多候选：冲量 rising 且趋势状态为 TREND（五个资产都适用）。
- 做空候选：只限 TLT——冲量 falling、TLT 为 CASH 或 EXIT、收盘 < SMA200、10 年期收益率 13 周上升 ≥ 0.25 个百分点。理由：利率是这个框架里明确双向操作的地方（讲话中他最大的几次盈利都来自债券头寸，多空都有）；股票、黄金、比特币在流动性收缩时只是回避，不做空。
- 其余一律回避，并写明原因（例如"流动性下降、趋势 CASH"）。
- **新鲜度与冷却期**：候选只有在此前 13 个周度评估点（D−7、D−14 … D−91，即冲量的时间窗）都不在闸门里时才算"新"，只有新候选才交给 LLM。这是成本设定：只比较上一周时，2023-01 至 2026-09 的数据上闸门每年约有 8.8 周打开（闸门来回闪烁）；13 周冷却后约 4.4 周 / 年，落在所有人要求的每年 2–6 次内。选这个值时只看了次数，没有看收益。

**LLM 调用**：每个 ISO 周第一次运行时评估（结果存在 `<data_dir>/playground/druckenmiller_liquidity/weeks.json`，同一周后续运行直接返回存档，不再取数、不再调用）；有新候选才调用一次 Flash（`chat_with_integrity`，`caller_agent` = `druckenmiller_liquidity:decision`）。提示词只有代码算出的面板、趋势状态和候选清单，不读 Playground context 里的新闻或其他字段。回复必须是严格 JSON：`{ticker, action: enter_long|enter_short|no_trade, confidence 0-1, hold_days 20-60, thesis}`；ticker 必须是候选之一、action 必须与该候选的闸门方向一致（no_trade 除外）。不合格、没有回复、no_trade 或 confidence < 0.5 → 不出判断，原因写在 `no_calls_reason`。多出来的键只在 `ignored_keys` 留档。FRED 或行情取不到时不存档，下次运行重试。

**判断（代码）**：止损 = 最后完整收盘 ∓ 3×ATR20（沿用 `_quant`），写入 `falsifier_rule`；文字条件另加"净流动性 13 周变化反向"（不自动结算）。确信度 = 0.5 + 0.2 ×（模型 confidence − 0.5）/ 0.5，范围 0.50–0.70，原值记在 `meta.signal.decision`。持有期取模型给的 20–60 天。`signal_key` = `标的:ISO 周`。`meta.signal` 含完整面板、该资产趋势、闸门与新候选、模型决定、`llm`、`prompt_version`（`druckenmiller_liquidity/v1`）与 `prompt_fingerprint`（bridge 提到顶层 `meta.llm` / `meta.prompt_version`）。

**成本**：`adapter.token_estimate()` ≈ 1.2k token / 次（五个资产都是新候选的最长情形）；按约 4 次 / 年计，一年约 5k token。

**2026-09-29 真实数据（只读，临时目录）**：净流动性约 5.77 万亿美元（资产 6.75 万亿、TGA 0.98 万亿、逆回购 5 亿，数据周 2026-09-23），13 周 −423 亿（−0.73%）、4 周 −93 亿 → falling；10 年期 5.24%（13 周 +0.86 个百分点）、2 年期 4.92%（+0.82）；美元 13 周 −0.46%；高收益利差 3.02%（+0.22）。趋势：QQQ TREND、SPY WATCH、TLT / GLD / BTC CASH。闸门里只有 TLT 做空，但它在 2026-09-01 已作为新候选出现过，处于 13 周冷却期 → 当天不调用 LLM、0 条判断。过去约 3.7 年的新候选周（估算，用今天的 T-bill 门槛）：17 周，包括 TLT 做空 6 次、SPY / QQQ / GLD / BTC 做多若干次。

**已知局限**
- 净流动性公式是市场通行的经验指标，本身没有经过同行评审的预测力证据；这里检验的是"流动性 + 趋势 + LLM 判断"这一组合，由晋升阶梯裁决。
- 每年约 4 条记录，满足晋升阶梯的 ≥20 次结算要五年左右；它主要是一个低频的框架样本。
- 只做五个资产；TLT 做空要承担票息（账本结算未计入持有成本）。
- 冷却期意味着闸门在 13 周内第二次打开时不会再问（即使上次模型选了 no_trade）。

## References（访问日期 2026-09-29）

1. Moskowitz, T. J., Ooi, Y. H., Pedersen, L. H. (2012). *Time Series Momentum*. Journal of Financial Economics 104(2), 228-250. https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf
2. Jegadeesh, N. (1990). *Evidence of Predictable Behavior of Security Returns*. Journal of Finance 45(3), 881-898.
3. Lehmann, B. N. (1990). *Fads, Martingales, and Market Efficiency*. Quarterly Journal of Economics 105(1), 1-28.
4. Moskowitz, T. J., Grinblatt, M. (1999). *Do Industries Explain Momentum?* Journal of Finance 54(4), 1249-1290.
5. Antonacci, G. (2012/2017). *Risk Premia Harvesting Through Dual Momentum*. SSRN 2042750; Journal of Management & Entrepreneurship 2(1), 27-55. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750
6. `docs/TREND_DESIGN.md`（趋势状态机的规则与出处：Moskowitz-Ooi-Pedersen 2012、Faber 2007、海龟交易法则）。

7. Xiao, Y., Sun, E., Luo, D., Wang, W. (2024). *TradingAgents: Multi-Agents LLM Financial Trading Framework*. arXiv:2412.20138（查阅的是 v7 HTML 版，§3.2 研究员团队、§3.4 风险管理、§4.2 辩论主持人与结构化通信、§4.3 快 / 慢思考模型、§6.2 成本局限）。https://arxiv.org/html/2412.20138
8. TauricResearch/TradingAgents（Apache-2.0），可配置的辩论轮数（`max_debate_rounds`）和风险讨论轮数。只参考了设计，没有复制代码。https://github.com/TauricResearch/TradingAgents
9. Xiong, M. et al. (2024). *Can LLMs Express Their Uncertainty? An Empirical Evaluation of Confidence Elicitation in LLMs*. ICLR 2024. arXiv:2306.13063
10. Yu, Y. et al. (2023). *FinMem: A Performance-Enhanced LLM Trading Agent with Layered Memory and Character Design*. https://arxiv.org/html/2311.13743
11. Zhao, A. et al. (2023). *ExpeL: LLM Agents Are Experiential Learners*. https://arxiv.org/abs/2308.10144

12. Gu, S., Kelly, B., Xiu, D. (2020). *Empirical Asset Pricing via Machine Learning*. Review of Financial Studies 33(5), 2223-2273. doi:10.1093/rfs/hhaa009. https://academic.oup.com/rfs/article/33/5/2223/5758276
13. López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. 第 7 章 Cross-Validation in Finance（purging、embargo），第 4 章 Sample Weights（标签重叠与唯一性）。目录：https://toc.library.ethz.ch/objects/pdf03/e01_978-1-119-48208-6_01.pdf
14. scikit-learn 1.8 `HistGradientBoostingClassifier` 与 `permutation_importance` 文档。https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html

期刊卷期页码为作者凭记忆填写，未在线核对；参考 1、5 的链接与趋势设计文档所引用的一致。参考 9 的出处也是凭记忆填写，未在线核对；参考 10、11 的链接与 `docs/S9_DESIGN.md` [R1] 相同，标题与作者未在线核对。参考 12 的卷期页码与 DOI、参考 13 的第 4、7 章标题已于 2026-09-29 在线核对（出版社页面与 ETH 图书馆目录）。

15. Minervini, M. (2013). *Trade Like a Stock Market Wizard: How to Achieve Super Performance in Stocks in Any Market*. McGraw-Hill.（趋势模板、VCP、止损上限；章节号凭记忆填写，未在线核对）
16. Deepvue, *Minervini Trend Template* 筛选说明（核对了：SMA150 / SMA200 条件、SMA200 至少上升一个月、距 52 周高点 25% 以内、RS ≥ 70）。https://deepvue.com/screener/minervini-trend-template/
17. 趋势模板第 6、7 条原文转述（"至少高于 52 周低点 30%""距 52 周高点 25% 以内"），见第三方整理稿与讨论：https://pdfcoffee.com/the-trend-template-mark-minervini-pdf-free.html ; https://scan.stockcharts.com/discussion/1378/minervini-scan
18. VCP 的第三方说明（回调逐次变小、通常 2–4 次、量能枯竭、突破量比均量高 40–50%、止损在最后一次收缩的低点之下）：https://traderlion.com/technical-analysis/volatility-contraction-pattern/ ; https://tradingmomentum.substack.com/p/the-volatility-contraction-pattern-b57
19. Druckenmiller, S. (2015-01). Lost Tree Club 讲话，第三方文字稿：https://www.danielscrivner.com/stanley-druckenmiller-rare-lost-tree-club-lecture/
20. FRED 序列说明：WALCL（Wednesday Level，百万美元，周度）https://fred.stlouisfed.org/series/WALCL ; WTREGEN（Week Average，截至周三，百万美元）https://fred.stlouisfed.org/series/WTREGEN ; RRPONTSYD（十亿美元，日度，单位取自 `gateway/fred_client.py` 目录，未在线核对）。

参考 16–20 于 2026-09-29 访问；17、18 是第三方整理，不是作者原文。IBD RS 近似公式没有官方出处，是通行做法 [推断]。
