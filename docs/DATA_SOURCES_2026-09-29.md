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

## References（访问日期 2026-09-29）

- https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data
- https://www.sec.gov/os/accessing-edgar-data （SEC 公平访问与 User-Agent 要求）
- https://github.com/hiring-lab/job_postings_tracker （README：方法与 CC BY 4.0）
- https://itunes.apple.com/us/rss/topfreeapplications/limit=100/genre=6015/json ; https://rss.marketingtools.apple.com/
- https://github.com/akfamily/akshare ; https://akshare.akfamily.xyz/
