# MarketMind 信息源 × Robinhood 资产覆盖分析

**日期**: 2026-05-17 | **源总数**: 31 | **Robinhood 资产**: 25

---

## 一、最终信息源清单（31 个）

| # | 源 | 地区 | 等级 | 文章 | 摘要 | 覆盖领域 |
|:---:|------|:---:|:---:|:---:|:---:|------|
| 1 | FRED Research Blog | US | PRIMARY | 10 | 418 | 宏观经济研究 |
| 2 | BLS API | US | PRIMARY | API | — | CPI/就业/PPI/工资 |
| 3 | SEC EDGAR | US | PRIMARY | 20 | 56 | 公司监管文件 |
| 4 | Federal Reserve | US | PRIMARY | 20 | 115 | 货币政策/联储声明 |
| 5 | CFTC COT API | US | PRIMARY | API | — | 期货持仓 |
| 6 | ECB Press Releases | EU | PRIMARY | 15 | 0* | 欧央行政策（标题即信号） |
| 7 | EC Press Corner | EU | PRIMARY | 10 | 241 | 欧盟法规/贸易 |
| 8 | Brazil BCB Copom | EM | PRIMARY | 10 | 5103 | 巴西货币政策 |
| 9 | NewsAPI | US | RELIABLE | API | — | 全球综合新闻 |
| 10 | GNews | US | RELIABLE | API | — | 全球综合新闻 |
| 11 | MarketWatch | US | RELIABLE | 10 | 104 | 美股/市场数据 |
| 12 | China Daily Bizchina | CN | RELIABLE | 100 | 189 | 中国财经/产业政策 |
| 13 | CGTN Business | CN | RELIABLE | 50 | 158 | 中国视角全球商业 |
| 14 | Financial Times | EU | RELIABLE | 25 | 94 | 全球金融分析 |
| 15 | SCMP Business | CN | RELIABLE | 50 | 500 | 香港/中国商业 |
| 16 | Nikkei Asia (GN) | JP | FRAGILE | 69 | — | 亚洲商业/股市 |
| 17 | Xinhua English | CN | FRAGILE | 20 | 179 | 中国官媒 |
| 18 | EUobserver | EU | FRAGILE | 20 | 208 | 欧盟政治/政策 |
| 19 | xcancel (FT) | US | BEST_EFFORT | 1 | 397 | FT 头条 |
| 20 | Bluesky | US | BEST_EFFORT | API | — | 社交金融讨论 |
| 21 | Caixin (Google News) | CN | BEST_EFFORT | 59 | 89 | 中国财经 |
| 22 | PBOC (Google News) | CN | BEST_EFFORT | 100 | 99 | 中国货币政策 |
| 23 | China Economy (Google News) | CN | BEST_EFFORT | 55 | 97 | 中国宏观数据 |
| 24 | ECB (Google News) | EU | BEST_EFFORT | 100 | 87 | 欧央行政策讨论 |
| 25 | Euronews (Google News) | EU | BEST_EFFORT | 100 | 88 | 欧盟商业 |
| 26 | Eurostat (Google News) | EU | BEST_EFFORT | 42 | 78 | 欧盟经济数据 |
| 27 | India RBI (Google News) | EM | BEST_EFFORT | 100 | 107 | 印度货币政策 |
| 28 | S.Africa SARB (Google News) | EM | BEST_EFFORT | 100 | 93 | 南非货币政策 |
| 29 | World Bank (Google News) | EM | BEST_EFFORT | 100 | 98 | 全球发展 |
| 30 | IMF (Google News) | EM | BEST_EFFORT | 100 | 98 | 全球宏观 |
| 31 | OPEC Oil (Google News) | EM | BEST_EFFORT | 65 | 90 | 石油/能源 |

*ECB Press Releases: 标题包含完整政策信号（如 "ECB raises rates by 25bp"），不需要正文

---

## 二、Robinhood 资产覆盖矩阵

### ETF 指数/板块

| 资产 | 类型 | 因子 | 覆盖源 | 状态 |
|------|------|------|------|:---:|
| **SPY** | 美股大盘 | beta=1.0 | Fed, MarketWatch, NewsAPI, GNews, SEC EDGAR | ✅ |
| **QQQ** | 科技 | beta=1.2 | XLK 同 (Fed, GNews 科技关键词) | ✅ |
| **IWM** | 小盘股 | beta=1.1 | MarketWatch, GNews | ✅ |
| **DIA** | 道指 | beta=0.9 | MarketWatch, GNews | ✅ |
| **TLT** | 长期国债 | rate=1.0 | FRED, Federal Reserve, ECB, PBOC GN | ✅ |
| **GLD** | 黄金 | gold=1.0 | ⚠️ **无专门贵金属源** | ❌ |
| **SLV** | 白银 | gold=0.8 | ⚠️ **GLD 同样的缺口** | ❌ |
| **USO** | 原油 | oil=1.0 | OPEC GN, EIA API | ✅ |
| **UNG** | 天然气 | oil=0.6 | ⚠️ OPEC 主油，天然气弱覆盖 | ❌ |
| **DBA** | 农产品 | agri=1.0 | ⚠️ **无农产品源** | ❌ |
| **EEM** | 新兴市场 | beta=1.1 | India GN, SARB GN, World Bank GN, IMF GN | ✅ |
| **XLF** | 金融 | rate=0.5 | Fed, ECB, FRED | ✅ |
| **XLK** | 科技 | beta=1.2 | GNews, MarketWatch, NewsAPI | ✅ |
| **XLE** | 能源 | oil=0.9 | OPEC GN, EIA API | ✅ |
| **XLV** | 医疗 | beta=0.7 | ⚠️ **无医疗行业源** | ❌ |

### 个股

| 资产 | 行业 | 覆盖源 | 状态 |
|------|------|------|:---:|
| **AAPL** | 科技 | GNews, MarketWatch, SEC EDGAR (10-K/10-Q) | ✅ |
| **MSFT** | 科技 | 同上 | ✅ |
| **NVDA** | 科技 | 同上 | ✅ |
| **GOOGL** | 科技 | 同上 | ✅ |
| **AMZN** | 消费 | GNews, SEC EDGAR | ✅ |
| **META** | 科技 | GNews, SEC EDGAR | ✅ |
| **TSLA** | 消费 | GNews, SEC EDGAR, MarketWatch | ✅ |
| **JPM** | 金融 | Fed, FRED, SEC EDGAR | ✅ |
| **XOM** | 能源 | OPEC GN, EIA API, SEC EDGAR | ✅ |

### 加密货币

| 资产 | 覆盖源 | 状态 |
|------|------|:---:|
| **BTC-USD** | Binance API (market data only), GNews/NewsAPI (news) | ⚠️ 无专门加密新闻 |

---

## 三、覆盖缺口总结

| # | 缺口 | 受影响资产 | 严重度 |
|:---:|------|------|:---:|
| 1 | **贵金属新闻** | GLD, SLV | 🔴 |
| 2 | **天然气专门报道** | UNG | 🟡 |
| 3 | **农产品期货新闻** | DBA | 🔴 |
| 4 | **医疗健康行业** | XLV | 🟡 |
| 5 | **加密货币专门新闻** | BTC-USD | 🟡 |

---

## 四、覆盖统计

| 维度 | 覆盖 | 总资产 | 覆盖率 |
|------|:---:|:---:|:---:|
| ETF 指数 | 11/15 | 15 | 73% |
| 个股 | 9/9 | 9 | 100% |
| 加密货币 | 0/1 | 1 | 0% |
| **全部** | **20/25** | **25** | **80%** |

## 五、缺口修复方案

| 缺口 | 方案 |
|------|------|
| 🔴 贵金属 (GLD/SLV) | Google News: `gold+silver+precious+metals+price` |
| 🔴 农产品 (DBA) | Google News: `agriculture+commodities+wheat+corn+soybean` |
| 🟡 天然气 (UNG) | Google News: `natural+gas+price+EIA+storage` |
| 🟡 医疗 (XLV) | Google News: `healthcare+biotech+pharma+FDA` |
| 🟡 加密货币 (BTC) | Google News: `Bitcoin+crypto+regulation+ETF` |
