# 趋势状态机（大行情探测器）设计稿

> 日期：2026-09-29 ｜ 状态：**回测阶段，未接入警报**（所有人 2026-09-29 决定：先回测，结果交所有人审阅后再接入 §10 的"代码确认趋势"）
> 代码：`marketmind/trend/` ｜ 测试：`marketmind/tests/test_trend/` ｜ 回测报告：`docs/TREND_BACKTEST_2026-09-29.md`

## 1. 目标与范围

- **目标**：为所有人能在 Robinhood 执行的标的（只做多、不用期权、可买加密货币）提供一个纯代码的趋势状态机，回答"这个标的现在是否处在一段大行情的中段"，对应 SPEC §1 的"一年抓 3-4 波大行情，只吃中间一段，不被套"和 §10 警报三条件中的"代码确认趋势"。
- **本阶段做**：规则、状态机、每日状态函数、历史回测（单标的 + 组合层面）、参数稳健性检查、报告。
- **本阶段不做**：接入警报、账本；不调用 LLM。（2026-09-29 第二阶段：精简版回测 §8，并接入每日/周末运行只写状态文件、日报事实与仪表盘，§9。）
- **L3**：所有数字由代码从行情数据计算；历史不足或数据缺失时输出 `UNAVAILABLE` 与原因，不猜。

## 2. 标的池（`marketmind/trend/universe.py::TREND_UNIVERSE`）

美股宽基 SPY QQQ IWM DIA；行业 XLK XLF XLE XLV XLI XLY XLP XLU XLB SMH；
商品 GLD SLV USO UNG；债券 TLT IEF；加密 BTC-USD ETH-USD SOL-USD；
大型股 NVDA AAPL MSFT AMZN META。共 28 个，只放在一个常量里。

- UNG：Robinhood 可交易（NYSE Arca ETF），但天然气期货展期损耗极大，买入持有长期大幅亏损；保留在池中以便检验"只做多趋势规则能否避开它的长期下跌"，报告里单独提示。
- 大型股是**今天的**赢家（幸存者偏差，见回测报告注意事项）。

## 3. 规则（`marketmind/trend/rules.py::TrendConfig`，全部参数在一个 dataclass 里）

所有判断都在**最后一根完整日线**（`gateway.price_history.complete_bars`）上做，第 t 天的决定只用 ≤t 的数据，**第 t+1 天开盘成交**。

| 项 | 规则 | 默认参数 | 依据 |
|---|---|---|---|
| 12 个月动量 | 收盘价 12 个月收益 > 12 个月 T-bill 收益 | 美股 252 根日线；加密 365 根（日历日） | Moskowitz-Ooi-Pedersen 2012：过去 12 个月超额收益是 58 个品种未来收益的正向预测因子；Hurst-Ooi-Pedersen 2017：1880 年以来每个十年都为正 |
| T-bill 代理 | 13 周国债收益率 `^IRX` 过去 252 个交易日均值 ÷100 | 取不到时用 0，并在输出里标注 `hurdle_source` | 同上（超额收益）；0 是保守的下限 |
| 长期均线过滤 | 收盘 > 200 日简单均线 | 200 根 | Faber 2007（10 个月均线 ≈ 200 日）：显著降低回撤 |
| 突破触发 | 收盘 > 前 55 根日线的最高收盘（55 日收盘新高） | 55 | 海龟 System 2 的 55 日突破 |
| 离场（主规则） | 吊灯止损：入场以来最高收盘 − 3×ATR(20)；只上移不下移；收盘跌破 → 次日开盘卖出 | 3.0×ATR(20)，Wilder 平滑 | LeBeau 吊灯离场（原版 22 日最高价 − 3×ATR(22)）；海龟的 N = 20 日 ATR |
| 离场（对照） | 收盘跌破 100 日均线 | 100 | 只在稳健性表里对照，不作为主规则 |

**主离场规则选吊灯止损的理由**：(1) 它直接给出止损价，组合层面"每笔风险 1%"的仓位计算需要止损距离；(2) 它随波动率自适应，同一套参数可用于债券 ETF 与加密货币；(3) 100 日均线离场在急跌时反应慢，与"不被套"相冲突。主规则在看回测结果之前确定，稳健性表同时列出 100 日均线离场的结果，避免事后挑参数。

**实现细节**
- ATR：Wilder ATR(20)，前 20 个 TR 取简单平均作为起点。
- 止损在第 t 天收盘后计算（`stop_t = max(stop_{t-1}, 入场以来最高收盘 − k×ATR_t)`），作用于第 t+1 天的收盘判断；入场信号当天的初始止损 = 信号日收盘 − k×ATR。
- 只用收盘价判断离场（不用盘中最低价），成交在下一根开盘，跳空损失如实计入。
- 加密货币的 SMA/突破/ATR 用日线根数（加密日线是自然日），12 个月动量用 365 根。

## 4. 状态

| 状态 | 含义 |
|---|---|
| `CASH` | 空仓，趋势条件不满足 |
| `WATCH` | 空仓，12 个月动量和 200 日均线两条过滤都满足，只差 55 日突破（附到突破价的距离） |
| `TREND` | 持有中。`event = "ENTRY"` 表示今天刚发出入场信号（下一开盘买入） |
| `EXIT` | 今天发出离场信号（下一开盘卖出），下一交易日回到 CASH/WATCH |
| `UNAVAILABLE` | 历史不足（美股 < 260 根、加密 < 366 根完整日线）、取数失败或最后一根完整日线过旧（> 7 个自然日），附原因 |

状态有路径依赖（是否持有取决于过去的入场与止损），所以每日状态函数与回测**用同一个模拟器**从头重放完整日线历史，保证"今天的状态"与回测完全一致。

## 5. 每日函数（供以后接警报用）

- 纯函数 `trend.state.compute_states(histories, hurdle, config)`：输入每个标的的日线（已剔除未完成的 bar），返回每个标的的 `TrendState`：`state`、`event`、`as_of`（最后一根完整日线日期）、`close`、`ret_12m`、`hurdle`、`sma200`、`high_55`（前 55 日最高收盘）、`atr`、`stop_level`、`entry_date`、`entry_signal_close`、`reason`。
- 异步包装 `trend.state.today_states()`：用 `get_price_history(years=5)` + `complete_bars` 取数，用 `^IRX` 计算门槛（取不到则 0 并标注）。
- 5 年重放窗口的局限：持有超过约 4 年仍未离场的仓位会被识别为较晚的入场；输出带 `replay_start`。

## 6. 回测方法（`marketmind/trend/backtest.py`）

- **数据**：每个标的取一次，缓存到工作区 `cache/trend/`（已被 `.gitignore` 忽略，不入库）。非加密用 yfinance 复权日线（历史最长，可到 2005 年；Alpaca 只到 2016 年）；加密在 Coinbase（真 USD）与 Binance（USDT 当作 USD）中取历史更长的一个。T-bill 用 yfinance `^IRX`。
- **单标的**：只做多，一次一个仓位，满仓进出；成本取 `ledger.settlement.cost_bps`（美股/ETF 单边 5bp；BTC/ETH 100bp；其他币 125bp），每笔来回扣两次。空仓收益为 0。
- **大行情定义**（客观）：收盘价从低点到高点涨幅 ≥20%，且低点到高点 ≤120 个交易日（加密按日历时间折算为 174 根日线）。贪心、不重叠地识别：从左往右扫，若某天之后 120 根内的最高收盘 ≥ 当天 ×1.2，则取该区间最低点为谷、谷后 120 根内最高点为峰，记一段，再从峰后继续。
  - 参与率：持仓期与这段行情有重叠的比例；
  - 中段命中率：行情价格（对数）走到一半的那一天系统是否持仓；
  - 捕获比例：行情期间持仓日的对数收益之和 ÷ 整段对数涨幅。
- **组合层面**（所有人账户视角）：初始 $30,000；每个 TREND 信号都接（有空位时），风险 = 当前权益 1% ÷ 止损距离，单仓上限 25%，最多 6 个仓位，不加杠杆（现金不足按可用现金，低于 $100 视为无现金跳过）；同一天多个信号按 12 个月超额收益从高到低排序；满仓时跳过的信号记为"跳过"。现金收益默认 0，另报一版现金按 T-bill 计息。基准：SPY 买入持有（同一区间）。
- **报告生成**：`python -m marketmind.trend.report --fetch --out docs/TREND_BACKTEST_<日期>.md`（`--fetch` 只补缺失的缓存，`--refresh` 全部重取）。报告里的每个数字都由代码计算。
- **稳健性**：突破 40/55/80 × ATR 倍数 2.5/3/4 共 9 组，外加 100 日均线离场对照；另把样本分成前后两半，检查规则在两段是否都成立（规则未经优化，前后两半都是样本外）。

## 7. 回测结论与未决事项

结论见 `docs/TREND_BACKTEST_2026-09-29.md`（摘要在顶部，第 9 节是接入警报的建议）。待所有人决定：
- 接入方式：作为 §10 "代码确认趋势"条件，还是单独推送；
- 信号数量：全池原始信号每年约 66 个，远多于"一年 3-4 波"，是否需要按相关组或动量排名再筛（需另行回测）；
- 单笔风险：每笔 1% 风险下组合平均投入约 69%，与"大部分时间持币"的画像不符。

## 8. 精简版（LEAN）回测：预先登记（2026-09-29，在看任何精简版结果之前写定）

所有人 2026-09-29 决定：接入警报之前，先回测一个贴近画像的精简版（大部分时间持币、一年约 3-4 波大行情，目标每年 4-8 次入场警报）。以下规则、参数、评价口径在运行回测之前写定并单独提交；结果写在 `docs/TREND_BACKTEST_LEAN_2026-09-29.md`，不回头改这里的规则。代码：`marketmind/trend/lean.py`。

**标的**：资产类别代表 SPY、QQQ、GLD、TLT、USO、BTC-USD、ETH-USD，外加"最强行业"一个名额：在每个交易日，XLK XLF XLE XLV XLI XLY XLP XLU XLB SMH 中 12 个月超额收益最高的那一个；只有它可以发入场信号（行业相对强度轮动，参考 Faber 2010 的"持有排名第一的行业"）。已持有的行业不因后来不再最强而卖出，仍只按自己的吊灯止损离场。

**相关组**：{SPY, QQQ, 最强行业}、{BTC-USD, ETH-USD}；GLD、TLT、USO 各自一组。每组最多持有一个仓位（参考海龟规则对"高度相关市场"的合计头寸上限）；同一天组内多个信号时取 12 个月超额收益最高的一个；组内已有持仓（尚未发出离场信号）时，组内其他标的的信号不接。

**入场/离场**：与主设计完全相同（§3：55 日收盘突破、收盘 > SMA200、12 个月收益 > T-bill、吊灯 3×ATR20、信号次日开盘成交、同样的成本）。

**被挡掉的信号**（非最强行业、组已占用、下面的更严过滤不满足）：该标的**不**进入"假想持仓"，状态记为 WATCH，之后只要再出现新的 55 日收盘突破且条件满足就可以入场。所以精简版需要一个联合模拟器（`lean.simulate_lean`），它与主设计的 `state.simulate` 共用同一个单标的步进器；不加任何门槛时两者逐笔一致（有单元测试）。

**唯一一个更严的入场过滤（预先登记）**：**12 个月超额收益排名前 3**——入场信号当天，该标的的 12 个月超额收益必须在精简候选（7 个代表 + 当天最强行业，共 8 个，按当天有数据的计）中排前 3。依据：Antonacci 的"双动量"（绝对动量 = 跑赢 T-bill，相对动量 = 在候选中更强；只做多时两者都为正才持有）；Faber 2010 的相对强度系统持有排名前 1/2/3 的行业。选它而不选"6 个月动量确认"的理由（推论）：6 个月动量与 55 日新高、200 日均线高度重叠，增加的信息少；排名则引入主设计没有的横截面维度，直接减少信号数量。

**仓位（两种都报，事先定好）**：(a) 与全池版相同的 `PortfolioConfig`（每笔风险 1%、单仓 ≤25%、最多 6 仓）便于对比；(b) 每个仓位固定 20% 权益（5 个组最多 100%，不加杠杆）——更贴近"少而大"的画像。现金收益按 0。

**报告口径**：入场次数/年（= 警报数）、在场时间（有任一仓位的天数占比）与平均投入、CAGR、最大回撤、最差年份；对比 SPY 买入持有与全池 28 标的版（同一区间、同两种仓位）；大行情捕获（7 个代表逐个 + 10 个行业合并，与全池版在同样行情上的捕获对比）；稳健性用 §6 的同一组 10 个相邻参数；前后两半 2006-2015 / 2016-至今。

**是否采用更严过滤的判定（事先定）**：只有同时满足才建议采用——(1) 前后两半的 CAGR 都不低于不加过滤的精简版；(2) 前后两半的最大回撤都不比精简版深超过 2 个百分点；(3) 每年入场次数更接近 4-8 的目标区间（或都在区间内）。否则保留不加过滤的精简版。

**结果**（2026-09-29，见 `docs/TREND_BACKTEST_LEAN_2026-09-29.md`；以上规则未因结果修改）：精简版每年约 12.5 次入场，未达到 4-8 的目标；排名前 3 过滤按事先标准未通过，不采用。

## 9. 每日 / 周末运行（只写状态，不记账本、不推送）

- **位置**：`pipeline/orchestration.py::trend_step`，每日运行在晋升评审之后、大行情警报与日报之前；周末运行在观察名单之后，**只算加密标的**。
- **做什么**：`trend.daily.run_trend_step` 一次取数（`state.fetch_inputs`：5 年完整日线 + `^IRX` 门槛），算全池 28 个标的的 `compute_states` 与精简版的 `lean.lean_states`（与回测同一个联合模拟器、默认不加排名过滤），写 `<数据目录>/trend/<纽约日期>.json`（`MARKETMIND_DATA_DIR`，默认 `data/`；先写临时文件再 `os.replace`）。
- **文件内容**：`date`、`mode`（daily / weekend）、`written_at`、`hurdle`、`hurdle_source`、`counts`、`full`（每个标的的 `TrendState`）、`lean`（`strongest_sector`、`groups`、`states`）、`changes`（full / lean 各自的 `entries`、`exits`）。
- **入场 / 离场的判定**：与每个标的**最近一份更早文件**里的状态比较（周末文件只有加密，周一的股票与周五比较）：现在 TREND 而之前是 CASH/WATCH/EXIT（或同一 TREND 但入场信号日变了）= 入场；之前 TREND 而现在 CASH/WATCH/EXIT = 离场；没有更早记录时只认当天的 ENTRY / EXIT 事件；UNAVAILABLE 两者都不算。
- **输出一行**：`[trend] n TREND, m CASH, k unavailable; entries: A, B (lean: A); exits: none`（计数是全池；CASH 含 WATCH 与 EXIT；精简版的变化放在括号里）。
- **失败**：取数或计算出错时记录日志、打印 `[trend] failed (see log)`，加入本次运行的降级步骤列表（退出码 3），不影响其他步骤。
- **日报**：`reports/daily.py::gather_facts` 增加 `趋势状态` 事实（今天的入场 / 离场、TREND 列表与止损位、不可用列表、精简版视图）。
- **仪表盘**：白箱"趋势状态"页（`/api/wb/trend`）：每个标的的状态、数据日期、收盘、12 个月超额收益、SMA200、55 日高、止损位；周末文件缺的股票沿用上一份并标注。

## References（访问日期 2026-09-29）

1. Moskowitz, T. J., Ooi, Y. H., Pedersen, L. H. (2012). *Time Series Momentum*. Journal of Financial Economics 104, 228–250. https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf — 摘要："We find persistence in returns for one to 12 months that partially reverses over longer horizons"；正文："the past 12-month excess return of each instrument is a positive predictor of its future return"。
2. Faber, M. T. (2007). *A Quantitative Approach to Tactical Asset Allocation*. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461 （SSRN 页面对抓取返回 403；内容据作者公开 PDF https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf 及检索摘要：月末价格高于 10 个月均线持有，否则持现金；报告中回撤从 46% 降到 10% 以下）。
3. Hurst, B., Ooi, Y. H., Pedersen, L. H. (2017). *A Century of Evidence on Trend-Following Investing*. Journal of Portfolio Management 44(1), 15–29. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026 （SSRN 403；摘要据 https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing 与 https://research.cbs.dk/en/publications/a-century-of-evidence-on-trend-following-investing/ ：1880 年以来每个十年平均收益为正，在 60/40 组合最大的 10 次危机中 8 次表现良好）。
4. Rozario, E., Holt, S., West, J., Ng, S. (2020). *A Decade of Evidence of Trend Following Investing in Cryptocurrencies*. https://arxiv.org/pdf/2009.12155 — BTCUSD 2011-2019 均线趋势跟踪；作者也指出按年滚动优化的参数"no predictable and attractive Sharpe ratios"，且回测假设零成本。**推论**：加密趋势跟踪有效，但参数不稳定、成本敏感，所以这里不为加密单独调参，并计入 100/125bp 单边成本。
5. 海龟交易法则（Curtis Faith 公开的原始规则）：System 2 = 55 日突破入场，N = 20 日 ATR（Wilder），2N 初始止损。https://oxfordstrat.com/coasdfASD32/uploads/2016/01/turtle-rules.pdf ；https://www.theturtletrader.com/turtle-trading-rules/
6. Chandelier Exit（Chuck LeBeau）：多头离场 = 22 日最高价 − 3×ATR(22)。StockCharts ChartSchool：https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit
7. 成本：`marketmind/ledger/settlement.py` 中的 Robinhood 加密路由价差（robinhood.com/us/en/support/articles/crypto-order-routing，该文件记录的核对日期 2026-09-28）。
8. Faber, M. T. (2010). *Relative Strength Strategies for Investing*. SSRN 1585517. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1585517 （全文 https://mebfaber.com/wp-content/uploads/2018/12/SSRN-id1585517-Relative-Strength-Strategies-for-Investing.pdf ）— "Each month the ten sectors are ranked on trailing total return"；"The system invests in the top X sectors. For Top 1, the system is 100% invested in the top ranked sector … For Top 3, the system is 33% invested in each of the top three sectors."；摘要：加入趋势跟踪参数后波动与回撤都下降。
9. Antonacci, G. (2012/2017). *Risk Premia Harvesting Through Dual Momentum*. SSRN 2042750；Journal of Management & Entrepreneurship 2(1), 27–55. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750 （2012 版全文 https://www.trendfollowing.com/whitepaper/SSRN-id2042750.pdf ）— "When looking only at long side momentum, however, it is desirable to be long only when both absolute and relative momentum is positive"；"To determine absolute momentum, we see if an asset has outperformed Treasury bills over the past year."
10. 海龟规则的相关市场头寸上限（同第 5 条来源）：单一市场 4 个单位、高度相关市场合计 6 个、松散相关市场合计 10 个、同一方向合计 12 个。精简版把"高度相关"收紧为每组 1 个仓位（本项目的取舍，不是海龟原规则）。
