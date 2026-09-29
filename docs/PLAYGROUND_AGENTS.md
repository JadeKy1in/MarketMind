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

## 5. `memory_desk`：带记忆与反思的 LLM agent，及其无记忆对照组

> 2026-09-29 所有人决定。设计约束来自 `docs/S9_DESIGN.md` §3（复盘事实）与 §5（记忆与反思的调研结论）。代码：`marketmind/playground/agents/memory_desk/`（`adapter.py`、`memory.py`、`prompts.py`）与 `agents/memory_desk_control/`。

**做什么**：固定小标的池 SPY、QQQ、GLD、TLT、BTC-USD、ETH-USD，每天一次 LLM 调用，给出 1–3 个多 / 空判断，持有 5 根 K 线。
- **事实表（代码）**：只用已收盘的完整日线，算 5 / 20 / 60 日收益、相对 MA50 / MA200 的位置、ATR20，以及与结算复盘相同定义的状态标签（`ret20_up/down`、`above/below_ma50`、`above/below_ma200`）；另附最多 8 条公开新闻标题。每天只算一次，缓存在 `<data_dir>/playground/memory_desk/facts/<日期>.json`，两个孪生 agent 读同一份。
- **止损、确信度、持有期（代码）**：止损 = 信号收盘 ∓ 3×ATR20，写成账本 `falsifier_rule`（与 `_quant` 相同）；LLM 给的确信度截到 0.50–0.70，原值记在 `signal.raw_confidence`；已有未结算记录的标的当天不再开仓；每个（日期，标的）只记一次（`signal_key`）。
- **信息防火墙**：输入只有公开行情、公开标题和**本 agent 自己**的账本记录；不读主管线、影子或其他 Playground agent 的输出（测试检查）。

**三层记忆**（参照 FinMem 的分层记忆 [7] 与旧版影子记忆的三层 + 90 天情景期限），存于 `<data_dir>/playground/memory_desk/memory.json`（原子写入）：
| 层 | 内容 | 衰减 |
|---|---|---|
| working | 自己最近 5 天的判断及其状态 / 结果 | 每次从账本重建 |
| episodic | 自己已结算的记录 + 结算代码写入的复盘事实（`error_class`、MFE/MAE、入场状态标签、净收益） | 离场 90 天后过期，过期后不再作为教训证据 |
| semantic | 教训（见下） | 60 个交易日有效期，只有新的样本外支持证据能续期 |

**教训**（参照 ExpeL 从自身成败经验中提炼规则 [8]，按 S9 §5 限定为只来自代码结算的结果、不来自自我批评）：
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

## References（访问日期 2026-09-29）

1. Moskowitz, T. J., Ooi, Y. H., Pedersen, L. H. (2012). *Time Series Momentum*. Journal of Financial Economics 104(2), 228-250. https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf
2. Jegadeesh, N. (1990). *Evidence of Predictable Behavior of Security Returns*. Journal of Finance 45(3), 881-898.
3. Lehmann, B. N. (1990). *Fads, Martingales, and Market Efficiency*. Quarterly Journal of Economics 105(1), 1-28.
4. Moskowitz, T. J., Grinblatt, M. (1999). *Do Industries Explain Momentum?* Journal of Finance 54(4), 1249-1290.
5. Antonacci, G. (2012/2017). *Risk Premia Harvesting Through Dual Momentum*. SSRN 2042750; Journal of Management & Entrepreneurship 2(1), 27-55. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750
6. `docs/TREND_DESIGN.md`（趋势状态机的规则与出处：Moskowitz-Ooi-Pedersen 2012、Faber 2007、海龟交易法则）。
7. Yu, Y. et al. (2023). *FinMem: A Performance-Enhanced LLM Trading Agent with Layered Memory and Character Design*. https://arxiv.org/html/2311.13743
8. Zhao, A. et al. (2023). *ExpeL: LLM Agents Are Experiential Learners*. https://arxiv.org/abs/2308.10144

期刊卷期页码为作者凭记忆填写，未在线核对；参考 1、5 的链接与趋势设计文档所引用的一致；参考 7、8 的链接与 `docs/S9_DESIGN.md` [R1] 相同，标题与作者未在线核对。
