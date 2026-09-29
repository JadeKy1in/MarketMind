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

## References（访问日期 2026-09-29）

1. Moskowitz, T. J., Ooi, Y. H., Pedersen, L. H. (2012). *Time Series Momentum*. Journal of Financial Economics 104(2), 228-250. https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf
2. Jegadeesh, N. (1990). *Evidence of Predictable Behavior of Security Returns*. Journal of Finance 45(3), 881-898.
3. Lehmann, B. N. (1990). *Fads, Martingales, and Market Efficiency*. Quarterly Journal of Economics 105(1), 1-28.
4. Moskowitz, T. J., Grinblatt, M. (1999). *Do Industries Explain Momentum?* Journal of Finance 54(4), 1249-1290.
5. Antonacci, G. (2012/2017). *Risk Premia Harvesting Through Dual Momentum*. SSRN 2042750; Journal of Management & Entrepreneurship 2(1), 27-55. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750
6. `docs/TREND_DESIGN.md`（趋势状态机的规则与出处：Moskowitz-Ooi-Pedersen 2012、Faber 2007、海龟交易法则）。

期刊卷期页码为作者凭记忆填写，未在线核对；参考 1、5 的链接与趋势设计文档所引用的一致。
