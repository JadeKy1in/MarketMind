# MarketMind 信息源全景目录

**生成日期**: 2026-05-17 | **源总数**: 24 | **可用**: 18 | **需人工**: 3 | **已死**: 3

---

## 一、按层级分布

### Layer 1 — 新闻采集 (12 源)

| # | 源名称 | 等级 | 可靠性 | 类型 | 国籍/视角 | 领域 | 状态 |
|:---:|------|:---:|:---:|------|:---:|------|:---:|
| 1 | **FRED** (St. Louis Fed) | PRIMARY | 0.99 | RSS | 🇺🇸 美国 | 宏观经济研究 | ✅ |
| 2 | **BLS** (劳工统计局) | PRIMARY | 0.99 | API | 🇺🇸 美国 | 就业/通胀/PPI/工资 | ⏸ 待实现 |
| 3 | **SEC EDGAR** | PRIMARY | 0.99 | RSS | 🇺🇸 美国 | 上市公司监管文件 | ✅ |
| 4 | **Federal Reserve** | PRIMARY | 0.99 | RSS | 🇺🇸 美国 | 货币政策/联储声明 | ✅ |
| 5 | **CFTC COT** | PRIMARY | 0.99 | API | 🇺🇸 美国 | 期货持仓报告 | ✅ |
| 6 | **NewsAPI** | RELIABLE | 0.90 | API | 🌐 全球 | 综合商业新闻（80K+ 源） | 🔄 实现中 |
| 7 | **GNews** | RELIABLE | 0.85 | API | 🌐 全球 | 综合商业新闻 | 🔄 实现中 |
| 8 | **MarketWatch** | RELIABLE | 0.80 | RSS | 🇺🇸 美国 | 美股/市场数据 | ✅ |
| 9 | **Investing.com** | RELIABLE | 0.75 | RSS | 🌐 全球 | 外汇/商品/加密货币 | ✅ |
| 10 | **Nikkei Asia** (Google News) | FRAGILE | 0.70 | RSS | 🇯🇵 日本 | 亚洲商业/股市 | ⏸ 待验证 |
| 11 | **xcancel** (Financial Times) | BEST_EFFORT | 0.60 | RSS | 🇬🇧 英国 | FT 头条转发 | ✅ |
| 12 | **Bluesky** | BEST_EFFORT | 0.60 | API | 🌐 全球 | 社交金融讨论 | ✅ |

### Layer 2 — 社交情绪 (3 源)

| # | 源名称 | 类型 | 国籍/视角 | 领域 | 状态 |
|:---:|------|------|:---:|------|:---:|
| 13 | **Reddit WSB** | RSS | 🌐 全球散户 | 散户情绪（反指） | ✅ |
| 14 | **Bluesky Social** | OAuth API | 🌐 全球 | 社交金融提及 | ✅ |
| 15 | ~~ApeWisdom~~ | API 已死 | 🇺🇸 美国 | 散户热门股 | ❌ |

### Layer 3 — 市场数据 (3 源)

| # | 源名称 | 类型 | 国籍/视角 | 领域 | 状态 |
|:---:|------|------|:---:|------|:---:|
| 16 | **yfinance** (Yahoo Finance) | API | 🇺🇸 美国 | OHLCV/基本面/指标 | ✅ |
| 17 | **Finnhub** | API | 🇫🇮 芬兰 | 美股实时/财报/蜡烛图 | ✅ |
| 18 | **Binance** | API | 🌐 全球 | 加密货币现货 | ✅ |

### Layer 4 — 内部人/聪明钱 (3 源)

| # | 源名称 | 类型 | 国籍/视角 | 领域 | 状态 |
|:---:|------|------|:---:|------|:---:|
| 19 | **SEC Form 4** | EDGAR Atom | 🇺🇸 美国 | 公司内部人交易 | ✅ |
| 20 | **SEC 13F** | EDGAR Atom | 🇺🇸 美国 | 机构持仓（季度） | ✅ |
| 21 | **Congress Trades** | 手动工具 | 🇺🇸 美国 | 国会议员交易 | 📋 手动 |

### Layer 5 — 宏观经济 API (3 源)

| # | 源名称 | 类型 | 国籍/视角 | 领域 | 状态 |
|:---:|------|------|:---:|------|:---:|
| 22 | **FRED API** | REST API | 🇺🇸 美国 | 利率/GDP/通胀/就业 | ✅ |
| 23 | **EIA API** | REST API | 🇺🇸 美国 | 原油/汽油/馏分油库存 | ✅ |
| 24 | **CFTC COT API** | SODA API | 🇺🇸 美国 | 期货投机/商业持仓 | ✅ |

### Layer 6 — 期权/日历 (3 源)

| # | 源名称 | 类型 | 国籍/视角 | 领域 | 状态 |
|:---:|------|------|:---:|------|:---:|
| — | **Options Flow** | 数据流 | 🇺🇸 美国 | 异常期权活动 | ✅ |
| — | **Economic Calendar** | 数据 | 🌐 全球 | 经济数据发布日期 | ✅ |
| — | **Earnings Dates** | 数据 | 🇺🇸 美国 | 财报发布日期 | ✅ |

---

## 二、按国家/视角分布

| 视角 | 源数量 | 主要贡献 |
|:---:|:---:|------|
| 🇺🇸 **美国** | 16 | 政策、监管、市场、宏观——压倒性多数 |
| 🌐 **全球** | 5 | 商业新闻聚合、加密货币、社交 |
| 🇬🇧 **英国** | 1 | Financial Times 头条（xcancel 转发） |
| 🇯🇵 **日本** | 1 | 亚洲商业新闻（Google News 聚合） |
| 🇫🇮 **芬兰** | 1 | Finnhub 美股数据 API |

**视角偏差**: 严重偏向美国。无中国大陆、欧盟政策、新兴市场一手源。

---

## 三、按领域分布

| 领域 | 源 |
|------|------|
| **宏观经济** | FRED, BLS, Federal Reserve, FRED API, EIA API |
| **货币政策** | Federal Reserve, FRED |
| **监管/合规** | SEC EDGAR, SEC Form 4, SEC 13F, Congress |
| **期货/商品** | CFTC COT, CFTC API, EIA API, Investing.com |
| **股票市场** | MarketWatch, NewsAPI, GNews, yfinance, Finnhub |
| **加密货币** | Binance, Investing.com |
| **外汇** | Investing.com |
| **亚洲市场** | Nikkei Asia (Google News) |
| **社交情绪** | Reddit WSB, Bluesky, xcancel |
| **衍生品** | Options Flow, Economic Calendar, Earnings Dates |

---

## 四、按可靠性分级

### PRIMARY (0.99) — 官方机构一手数据，不可伪造
FRED, BLS, SEC EDGAR, Federal Reserve, CFTC COT

### RELIABLE (0.75-0.90) — 商业新闻聚合，有编辑审查
NewsAPI, GNews, MarketWatch, Investing.com

### FRAGILE (0.70) — 第三方转发或聚合，可能中断
Nikkei Asia (Google News 代理)

### BEST_EFFORT (0.50-0.65) — 社交/社区源，高噪声，可能随时不可用
xcancel, Bluesky, Reddit WSB

---

## 五、已死/已删除源

| 源 | 原因 | 替代方案 |
|------|------|------|
| Google News RSS | 2023 年关闭 | NewsAPI / GNews |
| Bloomberg RSS | 不存在 | 无可替代 |
| Reuters RSS | 持续 HTTP 429 | NewsAPI 部分覆盖 |
| ApeWisdom | API 返回 HTML | Reddit WSB RSS |
| CapitolTrades | HTML 爬虫未实现 | 手动工具 manual_congress.py |
| Nikkei Asia 原版 RSS | 仅限 Newsletter | Google News 代理 |
| BLS RSS | Cloudflare 403 | BLS Public API v2 |
| Trump Truth Social RSS | 志愿项目不稳定 | 已移除 |
| House Stock Watcher S3 | HTTP 403 | 手动工具 |

---

## 六、关键缺口

| 缺口 | 影响 | 优先级 |
|------|------|:---:|
| 🇨🇳 **中国大陆政策/市场** | 无法感知 PBOC/FX干预/A股情绪 | HIGH |
| 🇪🇺 **欧盟 ECB/监管** | 无法感知欧央行政策/欧盟反垄断 | MEDIUM |
| 🌏 **新兴市场** | 无法感知 EM 资金流向/政治风险 | MEDIUM |
| 📊 **VIX/期权期限结构** | 波动率曲面数据缺失 | LOW |
| 🏛️ **国会交易（自动）** | 政治情报交易盲区 | LOW (手动工具) |

---

**文档版本**: 1.0 | **下次复查**: Phase H 启动前
