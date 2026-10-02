# 新增公开数据源（2026-09-29）

> 所有人 2026-09-29 决定接入 4 个公开数据源（并批准新依赖 akshare）。全部免密钥；可达性均于 2026-09-29 在所有人本机（利雅得网络）实测。规则 L3：取不到就标注"unavailable"，不猜、不补。

## 1. 一览

| 数据源 | 代码 | 影子分区（feed） | Playground 注册名 | 滞后 / 许可 |
|---|---|---|---|---|
| SEC 交割失败（半月文件） | `gateway/sec_ftd.py` | `shadow_feeds/equity_stress.py` → squeeze_watch、bear_tracker | SEC Fails-to-Deliver | 结算后约 2–4 周发布，每条输出都注明；美国政府公开数据，按 SEC 规则声明 User-Agent |
| Indeed Hiring Lab 招聘指数 | `gateway/hiring_lab.py` | `shadow_feeds/macro_alt.py`（indeed_postings）→ cycle_reader、wallet_watcher | Indeed Hiring Lab Job Postings | 日度数据、每周更新；CC BY 4.0，每段输出带署名 |
| Apple App Store 榜单 | `gateway/app_charts.py` | `shadow_feeds/macro_alt.py`（app_store_charts）→ wallet_watcher、silicon_oracle | Apple App Store Charts | 只有当前排名；历史靠每日存档，≥ 2 天才有排名变化；Apple 未写明数据许可（个人研究用） |
| akshare 中国市场 | `gateway/china_akshare.py` | `shadow_feeds/china_market.py` → dragon_watch | akshare China Market Data | 代码 MIT；akshare 声明数据"仅用于学术研究"；上游易变 |

Playground：`playground_sources.py` 新增 `SourceChannel.DATA`，4 个源各带 `loaders`（`模块:函数`）、`licence`、`lag`。新闻抓取器不会抓 DATA 源；manifest 在 `public_data_sources` 里写注册名即可声明，agent 用 `resolve_loader` 调用。

缓存 / 存档都在数据目录 `altdata/` 下：`sec_ftd/`（ZIP 永久缓存，发布后不变）、`hiring_lab/`（CSV 缓存 20 小时；下载失败时用旧缓存并注明日期）、`app_charts/<日期>.json`（每日存档，原子写入）。

## 2. 细节

- **SEC FTD**：从索引页取最新两个半月 ZIP（`cnsfailsYYYYMM{a,b}.zip`）。数量是当日的交割失败余额（不是新增）；价格是 SEC 给的前一日收盘价，缺价时写"value n/a"。每个标的输出：有记录的天数、最新余额与金额、有记录日的平均值、最大值、与上一半月平均值的变化；另列全市场平均失败金额前 5。
- **Hiring Lab**：美、英、德、法、加、澳总量 + 美国 9 个行业（软件开发、银行金融、建筑、制造、装卸、驾驶、零售、餐饮、酒店旅游）。输出最新值与 4 周变化（点数和百分比）。
- **App Store**：用旧版 iTunes RSS JSON（`itunes.apple.com/<国家>/rss/<榜单>/limit=100/genre=<id>/json`），因为新版 `rss.marketingtools.apple.com` v2 不支持分类和畅销榜。国家 us / gb / jp / cn × 分类 全部 / 财务 / 购物 / 游戏 × 免费 / 畅销 = 32 个榜。开发者名 → 股票代码是手写前缀表（`DEVELOPER_TICKERS`），匹配不上就不归属。
- **akshare**：只封装实测可用的函数：新浪指数日线（沪深 300、上证、创业板、科创 50、恒指）、东方财富南向资金历史、东方财富两融账户统计（全市场，亿元）。
  - 从利雅得访问**被拦截**：东方财富行情接口 push2his（`index_zh_a_hist`、`stock_zh_index_daily_em`）、深交所（`stock_margin_szse`）。
  - **北向资金**：2024-08-19 起源数据的净买额为空；`stock_hsgt_fund_flow_summary_em` 把北向显示成 0.0，这个 0 表示"未公布"，不是真实的零，代码不用它，输出里标注"unavailable"并给出最后公布值。
  - **线程**：akshare 是同步库，全部调用放在**唯一一个**工作线程里执行。新浪接口用到 py_mini_racer（V8），2026-09-29 实测多线程同时初始化时整个 Python 进程直接崩溃（V8 fatal check）。每次调用都有超时；feed 超出时间预算就跳过剩余调用并标注。

## 3. 待接线（本次未改 orchestration.py）

App Store 每日存档需要编排层每天调用一次：

```python
from marketmind.gateway.app_charts import archive_daily
await archive_daily(today: str | None = None, data_dir: Path | None = None, force: bool = False) -> dict
# 返回 {"path", "day", "written", "skipped", "charts_ok", "charts_failed"}；全部榜单失败时抛 RuntimeError（不写文件）
```

同一天重复调用幂等（当天已完整就跳过）。存档没跑时，影子 feed 会现场抓一次榜单（不写盘），并标注"today's archive has not run yet"。

## 4. 免费行情源（2026-10-02 新增）

> 所有人 2026-10-02 批准接入 Stooq、EODHD、baostock、FinMind（并批准新依赖 baostock）。代码 `gateway/free_quotes.py`，接线在 `gateway/price_history.get_price_history`。缺环境变量的源直接跳过（每次运行一条 debug 日志）；任何失败返回 None，换下一个源，不估算。

### 4.1 本机实测（2026-10-02，利雅得网络）

| 源 | 可达 | 实测结果 |
|---|---|---|
| Stooq `stooq.com/q/d/l/` | TCP/TLS 可达 | 不带密钥（以及带无效 `apikey`）一律 HTTP 200 + HTML 浏览器 JS 验证页（SHA-256 工作量证明），不是 CSV。带有效密钥是否放行**未验证**（没有密钥）。代码不破解验证，遇到即本次运行停用 Stooq 并记一条警告。curl 需 `--ssl-no-revoke`（Windows 吊销检查服务器不可达），Python httpx 不受影响。 |
| EODHD `eodhd.com/api/eod/` | 可达 | 不带 / 无效密钥：HTTP 401，正文 `Unauthenticated`。成功格式（文档）：JSON 数组 `date, open, high, low, close, adjusted_close, volume`。 |
| baostock 0.9.4（pip 安装） | 可达 | 登录约 1 秒；`sh.600519` 前复权日线正常（2026-09-30 收 1258.62）；不存在的代码返回空结果、error_code 0。 |
| FinMind `api.finmindtrade.com/api/v4/data` | 可达 | 无 token 可用：`TaiwanStockPrice` 返回 `{"msg":"success","status":200,"data":[{date, open, max, min, close, Trading_Volume, ...}]}`；复权数据集 `TaiwanStockPriceAdj` 回 "Your level is free"（需付费档）；无效 token 回 `{"msg":"Token is illegal.","status":400,"token_tail":"..."}`。 |

### 4.2 接线顺序

- A 股：Yahoo → 腾讯 → **baostock** → 东方财富 → Twelve Data → **EODHD**。
- 港股：Yahoo → 腾讯 → 东方财富 → **Stooq** → EODHD。
- 日股（.T）、德国（.DE Xetra）、英国（.L）：Yahoo → **Stooq** → Twelve Data → EODHD。其他欧洲交易所 Stooq 没有，只走 Twelve Data / EODHD。
- 期货（CL、NG、GC、SI、HG、PL、PA）、外汇、主要指数（^N225、^GDAXI、^FTSE、^HSI、^GSPC、^FCHI）：Yahoo → 东方财富 → **Stooq**。ZF / ZN 等利率期货 Stooq 代码未核实，不映射。
- 台股（.TW / .TWO）：Yahoo → **FinMind** → EODHD。FinMind 价格**未做除息调整**（与 Nasdaq 备选相同）。
- 美股不变（Alpaca → Yahoo → Nasdaq → Twelve Data），最后加 **EODHD**。

### 4.3 各源要点

- **Stooq**（`STOOQ_API_KEY`）：密钥只能放在 URL（`apikey=`），所以不记录任何请求 URL；httpx 的 INFO 请求日志加了过滤器，把 `apikey=` / `api_token=` / `token=` 的值换成 `***`。错误都以 HTTP 200 + 文本返回，只解析表头以 `Date,Open,High,Low,Close` 开头的 CSV；验证页、额度用完、密钥无效 → 本次运行停用；"No data" → 只跳过这个标的。请求串行、间隔 1 秒。
- **EODHD**（`EODHD_API_KEY`）：免费档每天 20 次、历史 1 年。每次请求前在 `altdata/eodhd/budget/` 用 O_EXCL 建一个 `<UTC 日期>.<序号>` 文件占位，最多 20 个，多进程也不会超；目录不可用时不请求（宁可少用）。旧日期的占位文件自动删除。401/402/403/429 → 本次运行停用。价格按 `adjusted_close / close` 缩放（拆股 + 分红调整，与 Yahoo 一致）。只在其他源都失败时用，不用于修补。
- **EODHD 实测（2026-10-02，所有人已设密钥）**：SAP.DE 取到 253 根完整日线（近 1 年）；7203.T 回 404。交易所列表接口（exchanges-list）共 70 个代码，**没有东京、香港、米兰、印度 NSE 和 INDX 指数**，因此 .T / .HK / .MI / .NS 与 ^指数不再向 EODHD 请求（404 也算一次日额度）。日股、港股的第二来源仍缺（Stooq 拿不到密钥）。
- **baostock**：同步库、全局 socket，所有调用在唯一工作线程里执行，超时 60 秒；超时后本次运行停用（线程可能卡住）。前复权（adjustflag=2）；停牌日（tradestatus=0）丢弃。
- **FinMind**（可选 `FINMIND_TOKEN`，放 HTTP 头）：错误信息里的 `token_tail` 不写日志；"upper limit" → 本次运行停用。

### 4.4 收盘价修补（close-only bars）

- 触发：最终序列最近 260 根日线（`REPAIR_LOOKBACK_BARS`）里有 close-only bar（O=H=L=C 且无成交量）。更早的不修，不发请求。
- 参照源：Stooq → baostock（A 股）→ FinMind（台股）→ 腾讯（港股 / A 股），跳过与主序列相同的源；不用 EODHD。
- 规则（`price_history.repair_close_only`）：同一日期、参照 bar 自身不是 close-only 且 low ≤ min(open, close)、high ≥ max(open, close)，并且两边收盘价相对差 ≤ **0.5%**（`REPAIR_CLOSE_TOLERANCE`）才修。参照的 O/H/L 乘以 本源收盘 / 参照收盘，保留本源收盘价和复权口径；成交量取参照值。
- 修补后来源记为 `yfinance+stooq` 这类组合（账本 price_source 可见），INFO 日志列出修补日期；没修上的仍按原规则标记、告警。
- 2026-10-02 抽查：Yahoo 2330.TW 的 close-only bar 2026-07-10 在 FinMind 中不存在（非交易日），不修补 —— 符合规则；港股 2022-01-31 等节前半日同理。

## References（访问日期 2026-09-29）

- https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data
- https://www.sec.gov/os/accessing-edgar-data （SEC 公平访问与 User-Agent 要求）
- https://github.com/hiring-lab/job_postings_tracker （README：方法与 CC BY 4.0）
- https://itunes.apple.com/us/rss/topfreeapplications/limit=100/genre=6015/json ; https://rss.marketingtools.apple.com/
- https://github.com/akfamily/akshare ; https://akshare.akfamily.xyz/
- （2026-10-02）Stooq 密钥要求：https://github.com/pydata/pandas-datareader/issues/1012 ；https://stooq.com/q/d/?s=9434.jp&get_apikey
- （2026-10-02）EODHD 交易所代码：https://eodhd.com/list-of-stock-markets
- （2026-10-02）baostock：http://baostock.com/ ；FinMind：https://finmind.github.io/
