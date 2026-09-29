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

期刊卷期页码为作者凭记忆填写，未在线核对；参考 1、5 的链接与趋势设计文档所引用的一致。参考 9 的出处也是凭记忆填写，未在线核对。
