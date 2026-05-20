# MarketMind 影子生态信息源映射文档

**日期**: 2026-05-20
**状态**: 规划文档 — 待实施
**范围**: 24 个影子 × 信息源需求 = 完整信息供给链条
**前置条件**: `config/source_authority.py` 现有 25 个来源（已审计），`gateway/macro_data.py` 现有 3 类结构化数据获取器

---

## 1. 现有信息源总览

### 1.1 现有已实施来源（25个）

| 层级 | 来源 | 类型 | 提供的内容 |
|:---:|------|------|------|
| **T1** | FRED (St. Louis Fed Research) | RSS | 美联储经济研究博客文章 |
| **T1** | BLS | API | CPI、Core CPI、失业率、PPI（免费，无需密钥） |
| **T1** | SEC EDGAR | RSS | 上市公司 SEC 文件（8-K, 10-K, 13F） |
| **T1** | Federal Reserve Press | RSS | 美联储官方新闻发布 XML |
| **T1** | CFTC COT | API | 期货持仓报告（ES/CL/GC/NG），SODA API 免费 |
| **T1** | ECB Press Releases | RSS | 欧洲央行新闻发布（标题级） |
| **T1** | ECB Publications | RSS | 欧洲央行经济公报/金融稳定报告（全文） |
| **T1** | EC Press Corner | RSS | 欧盟委员会新闻发布 |
| **T1** | Brazil BCB Copom | RSS | 巴西央行货币政策声明 |
| **T1** | India RBI Press Releases | RSS | 印度央行政发布 |
| **T2** | NewsAPI | API | 综合新闻聚合（需 NEWSAPI_KEY） |
| **T2** | GNews | API | 综合新闻聚合（需 GNEWS_API_KEY） |
| **T2** | MarketWatch | RSS | Dow Jones 顶级财经新闻 |
| **T2** | China Daily Bizchina | RSS | 中国经济商业新闻 |
| **T2** | CGTN Business | RSS | 中国国际商业新闻 |
| **T2** | SCMP Business | RSS | 香港/中国商业新闻 |
| **T2** | Financial Times | RSS | 全球金融深度报道（付费墙摘要） |
| **T2** | Euronews Business | RSS | 欧洲商业新闻（全文 MRSS） |
| **T2** | CoinTelegraph | RSS | 加密货币/区块链新闻（全文） |
| **T3** | Nikkei Asia (Google News proxy) | RSS | 日本经济新闻代理 |
| **T3** | Xinhua English | RSS | 中国官方英文新闻 |
| **T3** | EUobserver | RSS | 欧盟政策新闻 |
| **T4** | South Africa SARB (Google News proxy) | RSS | 南非储备银行新闻代理 |
| **T4** | OPEC Oil (Google News proxy) | RSS | OPEC 石油生产新闻代理 |
| **T4** | Bluesky | AT Protocol | 社交媒体金融讨论（需凭据） |

### 1.2 现有结构化数据获取器（gateway/macro_data.py）

| 获取器 | 数据点 | 来源 API | 密钥 | 现状 |
|------|------|------|------|------|
| `get_macro_indicator()` | BDI 运费指数 | FRED API | FRED_KEY | 已实施 |
| `get_macro_indicator("GSCPI")` | 全球供应链压力指数 | NY Fed（非 FRED） | 无 | 返回 `source_unavailable` |
| `get_cot_data()` | COT 期货持仓 (ES/CL/GC/NG) | CFTC SODA | 免费 | 已实施 |
| `get_eia_inventory()` | 美国原油/汽油/馏分油库存 | EIA API v2 | EIA_KEY | 已实施 |

### 1.3 核心诊断：当前信息供给的本质缺陷

**当前 25 个来源中，23 个是新闻来源。只有 2 个（BLS API + CFTC COT API）提供结构化数据。**

这意味着所有 24 个影子都在用**新闻文本**做决策（通过 LLM 理解），缺少可量化的结构化数据输入。影子必须依赖 LLM 从新闻中"推断" 数字——这造成三个严重问题：

1. **信息衰减**：新闻标题无法替代精确数据（如"黄金上涨" vs GLD 净流入 $237M + COT 投机净多 4.2 万手）
2. **反应滞后**：新闻滞后于数据发布（CPI 发布后 30 分钟才有新闻，BLS API 即时可得）
3. **无法独立交叉验证**：影子无法用硬数据检验新闻叙述是否属实

---

## 2. 按影子划分的信息需求映射

### 2.1 基本面专家（16位）

---

#### #1 Bullion Broker · 黄金捕手
**领域**: 贵金属 | **资本**: $50K | **温度**: 0.30

**分析逻辑**: 实际利率 → 美元 → 央行购金 → COT 持仓 → ETF 流量 → 实物溢价 → 矿业成本

**当前拥有**:
- [x] CFTC COT: GC (黄金期货) 投机/商业持仓 — `get_cot_data("GC")`
- [x] 新闻覆盖: MarketWatch + Financial Times + Bloomberg 代理新闻
- [x] FRED 数据: 实际利率可从 FRED 获取（但未接入）
- [x] Bluesky: 社交媒体黄金讨论情绪

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| GLD/SLV ETF 每日流量 | ETF 资金流向判断 | ETF.com API / ETFdb | **CRITICAL** |
| 央行购金月度数据 | 结构性需求判断 | WGC Gold Demand Trends CSV | **CRITICAL** |
| 上海/孟买黄金实物溢价 | 实物市场压力 | 上海金交所 SGE / MCX | HIGH |
| 全球金矿生产成本曲线 | 底部支撑判断 | S&P Global / Metals Focus | MEDIUM |
| COMEX 库存数据 | 交割压力 | CME Group Daily | MEDIUM |
| DXY 实时 (ice_dollar_index) | 汇率驱动 | ICE / Yahoo Finance 代理 | **CRITICAL** |
| TIPS 实际收益率 | 机会成本 | FRED (DFII10) | **CRITICAL** |

**数据源详情**:
- **FRED TIPS 收益率**: `https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key=YOUR_KEY&file_type=json` - 免费，需 FRED_KEY
- **WGC 黄金需求趋势**: `https://www.gold.org/goldhub/data/gold-demand-trends` - 免费下载 CSV，无 API
- **ETF 流量**: `https://www.etf.com/api/etf/GLD` — 收费；替代方案: `https://finnhub.io/api/v1/etf/holdings?symbol=GLD` (免费 tier)
- **COMEX 库存**: `https://www.cmegroup.com/markets/metals/precious/gold.volume.html` — 公开网页，需爬取

---

#### #2 Chain Oracle · 链上先知
**领域**: 加密货币 | **资本**: $45K | **温度**: 0.35

**分析逻辑**: 链上数据 → ETF 流量 → 监管进展 → 减半周期 → 稳定币市值 → DeFi TVL

**当前拥有**:
- [x] CoinTelegraph RSS: 加密货币行业新闻（全文 30 条）
- [x] Bluesky: 社交媒体加密讨论
- [x] NewsAPI/GNews: 综合新闻加密覆盖
- [x] 市场数据: BTC-USD 价格（asset_universe.py）

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 链上数据 (活跃地址, 交易所储备) | 网络健康度 | Glassnode API / CoinMetrics | **CRITICAL** |
| BTC ETF 每日流量 | 机构资金流向 | Farside Investors API | **CRITICAL** |
| 稳定币总市值 | 流动性储备 | DefiLlama API (免费) | **CRITICAL** |
| DeFi TVL 总额 + 分协议 | 生态系统健康 | DefiLlama API (免费) | HIGH |
| 哈希率 + 挖矿难度 | 网络安全 | Blockchain.com API (免费) | HIGH |
| 交易所 BTC/ETH 余额 | 持仓行为 | CryptoQuant (收费) / Glassnode | HIGH |
| 恐惧/贪婪指数 | 市场情绪 | `https://api.alternative.me/fng/` (免费) | HIGH |
| 比特币减半倒计时 | 周期位置 | `https://www.bitcoinblockhalf.com/` | MEDIUM |
| 监管跟踪 (SEC/CFTC 加密行动) | 监管风险 | SEC EDGAR (已有) + CFTC 公告 | MEDIUM |

**数据源详情**:
- **DefiLlama API**: `https://api.llama.fi/overview/dexs` (DEX 交易量), `https://api.llama.fi/protocols` (协议 TVL) — **完全免费，无密钥，速率限制 100/min**
- **Blockchain.com API**: `https://api.blockchain.info/charts/hash-rate?format=json` — 免费，无密钥
- **Farside Investors**: `https://farside.co.uk/btc/` — 网页数据，非官方 API（可爬取或使用社区代理）
- **Alternative.me 恐惧贪婪指数**: `https://api.alternative.me/fng/?limit=1` — 免费，无密钥，速率限制 60/min
- **Glassnode**: `https://api.glassnode.com/v1/metrics/...` — **收费** (Free tier 极其有限，Pro $49/月), 需 `GLASSNODE_API_KEY`
- **CoinMetrics**: `https://community-api.coinmetrics.io/v4/...` — 免费 tier 每日几百次调用

---

#### #3 Oil Geologist · 石油地质学家
**领域**: 能源 | **资本**: $50K | **温度**: 0.30

**分析逻辑**: OPEC+ 决策 → 原油库存 → 钻井平台数 → 需求预测 → 炼油价差 → VLCC 运价 → 天然气储备

**当前拥有**:
- [x] EIA 原油/汽油/馏分油库存 — `get_eia_inventory()`
- [x] CFTC COT: CL (原油期货), NG (天然气期货) 持仓
- [x] OPEC Oil (Google News proxy): OPEC 政策新闻
- [x] 新闻覆盖: MarketWatch + Financial Times 能源板块

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| Baker Hughes 钻井平台数 | 上游活动 | Baker Hughes Rig Count PDF/API | **CRITICAL** |
| EIA 天然气存储 | 天然气供需 | EIA API v2 (补充 NG 存储) | **CRITICAL** |
| EIA 原油产量估算 | 供应趋势 | EIA API v2 / STEO | **CRITICAL** |
| 炼油价差 (3-2-1 Crack Spread) | 需求健康度 | CME / EIA 计算方法 | HIGH |
| VLCC 运价 (TD3C 航线) | 物流成本 | 波罗的海交易所 / Clarksons | MEDIUM |
| OPEC+ 实际产量数据 | 合规监测 | IEA Monthly / OPEC MOMR | HIGH |
| WTI-Brent 价差 | 套利窗口 | EIA / Yahoo Finance | HIGH |
| 原油期货期限结构 | 库存预期 | CME futures chain | MEDIUM |

**数据源详情**:
- **Baker Hughes Rig Count**: `https://rigcount.bakerhughes.com/static-files/...` — 公开 PDF/CSV，无 API；可脚本化下载
- **EIA API v2 补充数据**: `https://api.eia.gov/v2/natural-gas/stor/wkly/data/` — 免费，需 EIA_KEY
- **EIA STEO (短期能源展望)**: `https://www.eia.gov/outlooks/steo/data/browser/` — 公开 CSV，每月更新
- **IEA 月度报告**: `https://www.iea.org/reports/oil-market-report-december-2024` — 摘要免费，完整版收费
- **OPEC MOMR**: `https://www.opec.org/opec_web/en/publications/338.htm` — 免费 PDF，每月更新

---

#### #4 Yield Whisperer · 收益率耳语者
**领域**: 固定收益、利率 | **资本**: $55K | **温度**: 0.30

**分析逻辑**: 收益率曲线形态 (2s10s, 3m10y) → 盈亏平衡通胀 → 美联储措辞/期货定价 → 国债拍卖需求 → MOVE 指数 → 信用利差

**当前拥有**:
- [x] Federal Reserve Press RSS: 美联储官方新闻
- [x] FRED: 通过 Research blog 获取经济研究背景
- [x] 新闻覆盖: 所有主要金融媒体覆盖利率动态
- [x] SEC EDGAR: 查看金融机构文件

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 实时国债收益率 (2Y, 5Y, 10Y, 30Y) | 曲线形态 | FRED API / Treasury.gov API | **CRITICAL** |
| TIPS 盈亏平衡通胀率 (5Y, 10Y) | 通胀预期 | FRED (DFII5, DFII10) | **CRITICAL** |
| Fed Funds Futures 隐含概率 | 加息预期 | CME FedWatch Tool | **CRITICAL** |
| MOVE 指数 (债券波动率) | 波动风险 | Bloomberg / ICE BofA | HIGH |
| 投资级/高收益信用利差 | 信用风险 | FRED (BAMLC0A0CM, BAMLH0A0HYM2) | **CRITICAL** |
| 国债拍卖需求 (bid-to-cover, tail) | 需求健康度 | TreasuryDirect.gov | HIGH |
| SOFR 利率 + 远期曲线 | 融资成本 | NY Fed (公开) | HIGH |

**数据源详情**:
- **FRED 国债收益率**: `https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key=KEY` — 免费
- **FRED TIPS 收益率**: `https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key=KEY`
- **CME FedWatch**: `https://www.cmegroup.com/CmeWS/mvc/Tickertape/FedWatch/FedReportServlet` — 公开 JSON，无密钥
- **FRED 信用利差**: `BAMLC0A0CM` (IG OAS), `BAMLH0A0HYM2` (HY OAS) — 滞后 1 天
- **TreasuryDirect**: `https://www.treasurydirect.gov/TA_WS/securities/auctioned` — 拍卖结果 XML，公开

---

#### #5 Vega Trader · 波动率交易员
**领域**: 波动率、期权 | **资本**: $40K | **温度**: 0.40

**分析逻辑**: VIX 期限结构 → SKEW 指数 → VVIX → 实现波动率 vs 隐含波动率 → 波动率风险溢价

**当前拥有**:
- [x] 新闻覆盖: 仅间接通过金融新闻跟踪 VIX
- [x] 市场数据: VXX, UVXY（波动率 ETP）价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| VIX 期限结构 (期货曲线) | 远期预期 | CBOE Futures / Yahoo Finance | **CRITICAL** |
| SKEW 指数 (尾风险定价) | 黑天鹅概率 | CBOE SKEW Index | **CRITICAL** |
| VVIX (VIX 的波动率) | 波动率的波动 | CBOE VVIX Index | **CRITICAL** |
| 实现波动率 (10D/20D) | 历史对比 | 自行计算 (SPY 日收益标准差) | HIGH |
| 认购/认沽比率 (equity + ETF) | 市场情绪 | CBOE 公开数据 | **CRITICAL** |
| VSTOXX (欧洲波动率) | 跨市场比较 | STOXX / Eurex | HIGH |
| VNKY (日本波动率) | 亚太波动 | Nikkei VI | MEDIUM |
| 期权希腊字母预估值 | 做市商行为 | 自行计算 (需要期权链数据) | MEDIUM |

**数据源详情**:
- **CBOE VIX 期货**: `https://www.cboe.com/us/futures/market_statistics/vix_term_structure/data.csv` — 公开 CSV，无密钥。需要手动下载或脚本抓取
- **CBOE SKEW**: `https://www.cboe.com/us/indices/dashboard/skew/` — 网页数据，无公开 JSON API
- **CBOE VVIX**: `https://www.cboe.com/us/indices/dashboard/vvix/` — 网页数据
- **认沽/认购比率**: `https://www.cboe.com/us/options/market_statistics/symbol_data/csv/?mkt=cone` — 公开 CSV
- **VSTOXX**: `https://www.stoxx.com/discovery-values-snapshot` — 网页数据
- **替代方案 — Yahoo Finance 代理**: `https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX` — 免费但不稳定

---

#### #6 Frontier Scout · 新兴市场侦察兵
**领域**: 新兴市场 | **资本**: $45K | **温度**: 0.35

**分析逻辑**: DXY → EM 债券利差 (EMBI) → 资本流动数据 → 政治风险 → 经常账户 → 商品出口/进口结构

**当前拥有**:
- [x] Brazil BCB Copom RSS: 巴西央行声明
- [x] India RBI Press Releases RSS: 印度央行声明
- [x] South Africa SARB (Google News proxy): 南非储备银行新闻
- [x] China Daily/CGTN/SCMP/Xinhua: 中国 4 个直接来源
- [x] 市场数据: EEM, FXI 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| EMBI 利差 (新兴市场债券利差) | 风险溢价 | FRED (BAMLEMHBHYCRPIOAS) | **CRITICAL** |
| DXY 实时 | 美元强度 | ICE / Yahoo Finance | **CRITICAL** |
| IIF 资本流动月度报告 | 跨境资金流 | IIF (Institute of International Finance) | **CRITICAL** |
| 经常账户余额 (各国) | 外部脆弱性 | IMF IFS / World Bank WDI | HIGH |
| 外汇储备变化 | 干预能力 | 各国央行网站 / IMF IFS | HIGH |
| PMI (中国/印度/巴西) | 增长信号 | S&P Global PMI | **CRITICAL** |
| 政治风险指数 | 事件风险 | PRS Group ICRG / World Bank WGI | MEDIUM |
| 新兴市场 ETF 流量 | 资金趋势 | ETF.com / EPFR Global (收费) | HIGH |

**数据源详情**:
- **FRED EMBI 利差**: series_id `BAMLEMHBHYCRPIOAS` — 免费，需 FRED_KEY
- **IMF IFS (国际金融统计)**: `https://data.imf.org/ifs` — 免费 API，需注册获取密钥
- **S&P Global PMI**: `https://www.spglobal.com/spdji/en/` — 收费数据；替代方案：Markit Economics 新闻摘要
- **World Bank WDI**: `https://api.worldbank.org/v2/country/CN/indicator/BN.CAB.XOKA.CD?format=json` — 免费 REST API，无密钥
- **IIF Capital Flows Tracker**: `https://www.iif.com/Products/Capital-Flows-Tracker` — 收费，仅摘要免费。替代方案：BIS 国际银行统计

---

#### #7 Silicon Oracle · 硅谷神谕
**领域**: 科技、半导体、软件 | **资本**: $50K | **温度**: 0.30

**分析逻辑**: 盈利动量 → AI 资本开支 → 芯片供应链 → 监管/反垄断 → 云支出增长 → 广告市场

**当前拥有**:
- [x] SEC EDGAR: 科技公司 10-K/10-Q/8-K 文件
- [x] 新闻覆盖: 所有财经媒体覆盖科技板块
- [x] 市场数据: QQQ, SMH, AAPL, MSFT, NVDA, GOOGL, META 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 半导体出货/销售额 (WSTS/SIA) | 周期位置 | SIA Semiconductor Billings | **CRITICAL** |
| 台积电月度营收 | 全球芯片需求 | TSMC 投资者关系页 | **CRITICAL** |
| 云服务商资本开支追踪 | AI 投资强度 | 公司财报汇总 + CSP CAPEX tracker | HIGH |
| 全球芯片设备订单 (SEMI Billings) | 扩产周期 | SEMI | MEDIUM |
| 反垄断案件追踪 | 监管风险 | FTC/DOJ/EU 竞争总司公告 | HIGH |
| App Store/Google Play 收入估计 | 应用经济 | Sensor Tower (收费) / App Annie | MEDIUM |
| 网络安全攻击统计 | 安全支出 | CrowdStrike/Verizon DBIR | LOW |

**数据源详情**:
- **SIA 半导体销售**: `https://www.semiconductors.org/data-resources/` — 免费月度报告 WSTS 数据，网页 + PDF
- **台积电月度营收**: `https://investor.tsmc.com/english/monthly-revenue` — 公开网页表格
- **SEMI 设备 Billings**: `https://www.semi.org/en/news-resources/market-data` — 摘要免费，详细数据收费
- **FTC/DOJ 反垄断**: 通过新闻源覆盖（已有 MarketWatch/FT）

---

#### #8 Bank Examiner · 银行审计官
**领域**: 金融 | **资本**: $48K | **温度**: 0.30

**分析逻辑**: 收益率曲线陡度 → 贷款增长 → 信用质量 (坏账率, 拨备) → 监管资本 → 并购

**当前拥有**:
- [x] Federal Reserve Press RSS: Fed 监管变化
- [x] SEC EDGAR: 银行 10-K/10-Q
- [x] 新闻覆盖: 所有财经媒体覆盖金融板块
- [x] 市场数据: XLF, KRE, JPM 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 美联储 H.8 报告 (银行资产/负债) | 贷款趋势 | FRED / Federal Reserve H.8 | **CRITICAL** |
| 商业银行贷款增长率 | 信用周期 | FRED (LOANINV, BUSLOANS) | **CRITICAL** |
| 净坏账率 (NCO Ratio) | 信用质量 | FRED / FDIC Quarterly Banking Profile | **CRITICAL** |
| 银行拨备覆盖率 | 风险缓冲 | 10-K 汇总 / FRED | HIGH |
| 联邦基金利率期货 | 利率路径 | CME FedWatch | HIGH |
| 并购交易公告日历 | 交易流 | SEC EDGAR (已有) + Bloomberg 终端 | MEDIUM |
| 区域银行健康指标 (CRE 暴露) | 系统性风险 | FDIC / FRED | HIGH |

**数据源详情**:
- **FRED H.8**: series_id `TLAACBM027SBOG` (银行总资产), `LOANINV` (贷款和租赁) — 免费
- **FRED NCO**: series_id `NCOALLACB` — 免费
- **FDIC QBP**: `https://www.fdic.gov/bank/statistical/statistics/` — 免费 PDF/CSV，季度更新
- **CME FedWatch**: 同上 — 公开 JSON

---

#### #9 Trial Reviewer · 临床审查员
**领域**: 医疗健康 | **资本**: $48K | **温度**: 0.30

**分析逻辑**: FDA 审批日历 → 临床数据 → 药价政策 → 人口结构趋势 → 医疗利用率

**当前拥有**:
- [x] SEC EDGAR: 药企 10-K/8-K (药物审批/临床结果)
- [x] 新闻覆盖: 财经新闻覆盖 FDA/药企
- [x] 市场数据: XLV, IBB 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| FDA 审批日历 (PDUFA dates) | 催化事件 | FDA Drugs@FDA / BioPharmCatalyst | **CRITICAL** |
| 临床结果数据库 (ClinicalTrials.gov) | 管线进展 | `https://clinicaltrials.gov/api/v2/studies` | **CRITICAL** |
| CMS 药品价格谈判日历 | 定价风险 | CMS.gov / 新闻监控 | HIGH |
| 处方药销量 (IQVIA/IMS 数据) | 商业化进展 | IQVIA (收费) — 替代：财报电话会议 | MEDIUM |
| 医疗保险利用率数据 | 需求趋势 | CMS National Health Expenditure Data | MEDIUM |
| 流行病学数据 (CDC/WHO) | 疾病负担 | CDC WONDER / WHO GHO | LOW |
| FDA 警告信/483 表格 | 制造风险 | FDA Inspections Database | MEDIUM |

**数据源详情**:
- **FDA Drugs@FDA**: `https://api.fda.gov/drug/drugsfda.json?search=...` — 免费 API `https://open.fda.gov/apis/` — 无密钥，速率限制 240/min
- **ClinicalTrials.gov API**: `https://clinicaltrials.gov/api/v2/studies?query.term=cancer&pageSize=20` — 免费，无密钥，现代 REST API
- **CMS NHE**: `https://www.cms.gov/data-research/statistics-trends-and-reports/national-health-expenditure-data` — 免费
- **BioPharmCatalyst**: `https://www.biopharmcatalyst.com/fda-calendar/` — 网页数据，有免费日历

---

#### #10 Wallet Watcher · 钱包观察员
**领域**: 消费 | **资本**: $46K | **温度**: 0.30

**分析逻辑**: 零售销售趋势 → 消费者信心/情绪 → 信用卡支出数据 → 工资增长 → 储蓄率 → 住房可负担性

**当前拥有**:
- [x] BLS API: 就业/失业率/工资增长 (CPI, PPI)
- [x] SEC EDGAR: 零售/消费公司文件
- [x] 新闻覆盖: 零售新闻
- [x] 市场数据: XLY, XRT, AMZN, TSLA 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 密歇根大学消费者信心指数 | 消费者情绪 | UMich Survey / FRED (UMCSENT) | **CRITICAL** |
| 零售销售月度数据 (Census Bureau) | 消费趋势 | FRED (RSXFS, RETAIL) | **CRITICAL** |
| 个人储蓄率 | 财务缓冲 | FRED (PSAVERT) | **CRITICAL** |
| 信用卡支出数据 (实时) | 高频消费 | Visa/Mastercard SpendingPulse (收费) | HIGH |
| 红皮书零售指数 | 周度零售 | Redbook Research (收费/有限公开) | HIGH |
| AAII 投资者情绪 | 散户情绪 | AAII Sentiment Survey | **CRITICAL** |
| Conference Board 消费者信心 | 企业视角 | Conference Board (收费) / FRED 摘要 | HIGH |
| 美国人口普查局零售销售 | 官方统计 | `https://api.census.gov/data/timeseries/eits/marts` | HIGH |

**数据源详情**:
- **FRED UMCSENT**: `UMCSENT` (密歇根消费者情绪) — 免费，半月更新
- **FRED 零售销售**: `RSXFS` (零售销售 ex 食品), `RETAIL` — 免费，月度
- **FRED PSAVERT**: 个人储蓄率 — 免费，月度
- **Census Bureau EITS API**: `https://api.census.gov/data/timeseries/eits/marts?get=cell_value&time=2026&NAICS=44` — 免费，无需密钥
- **AAII Sentiment**: `https://www.aaii.com/sentimentsurvey` — 网页免费，无 API（可爬取或手动输入）。替代方案：Barchart 有代理数据

---

#### #11 Factory Floor · 工厂车间主任
**领域**: 工业 | **资本**: $48K | **温度**: 0.30

**分析逻辑**: PMI (ISM/全球) → 耐用品订单 → 基建支出 → 贸易政策/关税 → 运输指数 → 货运指数

**当前拥有**:
- [x] FRED: BDI 运费指数 — `get_macro_indicator("BDI")`
- [x] 新闻覆盖: 工业/制造业新闻
- [x] 市场数据: XLI, ITA, CAT 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| ISM 制造业 PMI | 美国制造业 | ISM 报告 (收费) / FRED 摘要 | **CRITICAL** |
| ISM 服务业 PMI | 美国服务业 | ISM 报告 / FRED 摘要 | **CRITICAL** |
| 全球 PMI (JP Morgan Global) | 全球同步 | S&P Global / JP Morgan | **CRITICAL** |
| 耐用品订单 | 投资周期 | FRED (DGORDER, NEWORDER) | **CRITICAL** |
| Cass 货运指数 | 物流量 | Cass Information Systems (收费/摘要公开) | HIGH |
| Dow Jones 运输指数 | 市场信号 | 已有 (DIA/SPY 已有) | LOW |
| 基建支出趋势 | 政策驱动 | Census Bureau Construction Spending | MEDIUM |
| 全球集装箱运费 (SCFI/WCI) | 贸易成本 | Drewry WCI / Shanghai SCFI | HIGH |
| 德国 Ifo 商业景气指数 | 欧洲制造业 | Ifo Institute | HIGH |

**数据源详情**:
- **FRED ISM PMI**: Note — ISM PMI 不在 FRED 上；替代方案：通过 BLS API 或 FRED `NAPM`（芝加哥 PMI = 预测），S&P Global PMI 通过 Markit/新闻代理
- **FRED 耐用品订单**: `DGORDER` / `NEWORDER` — 免费
- **Drewry World Container Index**: `https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index` — 免费摘要，完整数据收费
- **SCFI (上海集装箱运费)**: `https://www.sse.net.cn/index/singleIndex?indexType=scfi` — 公开网页
- **Ifo 指数**: `https://www.ifo.de/en/survey/ifo-business-climate-index` — 免费发布，月度

---

#### #12 Steel Trader · 钢铁交易员
**领域**: 工业金属 | **资本**: $42K | **温度**: 0.35

**分析逻辑**: 中国需求指标 → 基建支出 → EV 普及率 → 供应中断 → LME 库存 → 铁矿石价格

**当前拥有**:
- [x] 中国新闻: China Daily/CGTN/SCMP/Xinhua 4 个来源
- [x] 新闻覆盖: 商品相关新闻
- [x] 市场数据: DBB, XME, FCX 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| LME 金属库存 (铝/铜/锌/镍/铅) | 供需平衡 | LME Daily Stocks Report | **CRITICAL** |
| LME 铜/铝/锌 3M 期货价格 | 基准价格 | LME Official Prices | **CRITICAL** |
| 上海期货交易所 (SHFE) 金属库存 | 中国库存 | SHFE Weekly | **CRITICAL** |
| 中国工业产出数据 | 需求信号 | NBS China Monthly | **CRITICAL** |
| 铁矿石价格 (62% Fe CFR) | 钢铁成本 | Platts / Mysteel / Fastmarkets | HIGH |
| 中国 PMI 建筑/制造业分项 | 下游需求 | NBS / Caixin PMI | HIGH |
| EV 销售月度数据 | 电池金属需求 | EV-volumes.com / 各汽车制造商 | MEDIUM |
| 智利/秘鲁铜矿产量 | 供应中断 | Cochilco / MINEM Peru | MEDIUM |

**数据源详情**:
- **LME 每日库存**: `https://www.lme.com/en/market-data/reports-and-data/warehouse-and-stocks-reports/` — 公开网页/PDF，免费。可脚本化下载每日 PDF
- **LME 价格**: `https://www.lme.com/api/price-month?metal=METAL&month=YYYY-MM` — 公开内部 API JSON
- **SHFE 库存**: `https://www.shfe.com.cn/en/market/market-datastorage/` — 公开网页/CSV
- **铁矿石 (Platts)**: `https://www.spglobal.com/commodityinsights/en/our-methodology/price-assessments/metals/iron-ore` — 收费，摘要免费
- **Mysteel**: `https://www.mysteel.com/` — 中国钢铁数据，部分免费

---

#### #13 Harvest Seer · 收获先知
**领域**: 农产品 | **资本**: $42K | **温度**: 0.35

**分析逻辑**: 谷物库存 (USDA WASDE) → 天气模式 (ENSO, 干旱指数) → 肥料价格 → 食物 CPI → 运费 → 产量预测

**当前拥有**:
- [x] 新闻覆盖: 部分农产品新闻（但来源极少）
- [x] FRED BDI: 运费背景 — `get_macro_indicator("BDI")`
- [x] 市场数据: DBA, CORN, WEAT, SOYB 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| USDA WASDE 报告 (月度) | 供需平衡表 | USDA WASDE PDF/数据表 | **CRITICAL** |
| USDA 作物进展周报 | 播种/收获进度 | USDA Crop Progress | **CRITICAL** |
| ENSO (厄尔尼诺/拉尼娜) 预报 | 天气模式 | NOAA CPC / IRI | **CRITICAL** |
| 全球干旱监测 | 产量威胁 | NOAA / USDA Drought Monitor | HIGH |
| CFTC COT 农产品 (玉米/小麦/豆) | 定位数据 | CFTC SODA API (扩展) | **CRITICAL** |
| 肥料价格指数 (DAP/尿素/钾肥) | 投入成本 | World Bank Commodity Price Data (Pink Sheet) | HIGH |
| 联合国粮农组织食品价格指数 (FAO FPI) | 全球食品通胀 | FAO Food Price Index | HIGH |
| 咖啡/糖/可可 ICE 期货数据 | 软商品 | ICE Futures | MEDIUM |

**数据源详情**:
- **USDA WASDE**: `https://www.usda.gov/oce/commodity/wasde` — 免费 PDF/Excel，每月发布。可脚本化下载
- **USDA Crop Progress**: `https://usda.library.cornell.edu/concern/publications/8336h188j` — 免费 CSV，每周更新
- **NOAA CPC ENSO**: `https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/` — 免费
- **CFTC COT 扩展**: 在现有 `get_cot_data()` 基础上添加 CORN, WHEAT, SOYBEAN, COFFEE — 当前仅支持 ES/CL/GC/NG 四种
- **World Bank Pink Sheet**: `https://www.worldbank.org/en/research/commodity-markets` — 免费 Excel/CSV，月度更新
- **FAO FPI**: `https://www.fao.org/worldfoodsituation/foodpricesindex/en/` — 免费数据

---

#### #14 REIT Analyst · 地产分析师
**领域**: 房地产 | **资本**: $48K | **温度**: 0.30

**分析逻辑**: 利率趋势 → 入住率 → 资本化率利差 → CMBS 发行 → 房屋开工/二手房销售 → 抵押贷款利率

**当前拥有**:
- [x] SEC EDGAR: REIT 文件
- [x] 新闻覆盖: 财经新闻地产板块
- [x] 市场数据: VNQ 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 美国房屋开工/营建许可 | 供应趋势 | FRED (HOUST, PERMIT) / Census Bureau | **CRITICAL** |
| 二手房销售 (NAR) | 需求趋势 | FRED / NAR | **CRITICAL** |
| 30年固定抵押贷款利率 | 融资条件 | FRED (MORTGAGE30US) / Freddie Mac | **CRITICAL** |
| Case-Shiller 房价指数 | 估值趋势 | FRED (SPCS20RSA) / S&P | **CRITICAL** |
| CMBS 发行量 | 商业地产信贷 | Commercial Mortgage Alert / CREFC | HIGH |
| 各物业类型入住率 (办公/零售/工业/住宅) | 基本面 | CoStar / CBRE (收费) | HIGH |
| 房屋可负担性指数 | 需求能力 | NAR Housing Affordability Index | MEDIUM |
| 在建多户住宅数据 | 供给管道 | Census Bureau / FRED | MEDIUM |

**数据源详情**:
- **FRED 房屋开工**: `HOUST`, `PERMIT` — 免费，月度
- **FRED 抵押利率**: `MORTGAGE30US` — 免费，每周
- **FRED Case-Shiller**: `SPCS20RSA` (20城市季调) — 免费，月度
- **NAR 二手房销售**: `https://www.nar.realtor/research-and-statistics/housing-statistics/existing-home-sales` — 免费摘要
- **Freddie Mac PMMS**: `https://www.freddiemac.com/pmms` — 免费，每周

---

#### #15 Currency Dealer · 外汇交易员
**领域**: 外汇 | **资本**: $44K | **温度**: 0.35

**分析逻辑**: 利差 → Carry-to-Risk 比率 → 购买力平价偏离 → 央行干预风险 → 经常账户余额

**当前拥有**:
- [x] ECB Press Releases + Publications + EC Press Corner: 欧元区
- [x] Brazil BCB Copom: 巴西雷亚尔
- [x] India RBI: 印度卢比
- [x] Federal Reserve Press: 美元
- [x] China 4 来源: 人民币
- [x] 市场数据: UUP, FXE 价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 各国政策利率 (G10 + 主要 EM) | 利差计算 | 各国央行网站 / BIS 统计 | **CRITICAL** |
| 远期汇率/远期点数 | 对冲成本 | Bloomberg / OANDA API (收费) | HIGH |
| 经常账户余额 (各国) | 结构低估/高估 | IMF IFS / World Bank WDI | HIGH |
| BIS 跨境银行债权 | 资本流动 | BIS International Banking Statistics | **CRITICAL** |
| BIS 实际有效汇率 (REER) | 竞争力 | BIS Effective Exchange Rates | **CRITICAL** |
| TIC 数据 (美国国债外国持有量) | 美元需求 | Treasury TIC | HIGH |
| 央行外汇干预数据 | 尾部风险 | 各国央行 / BIS | MEDIUM |
| 人民币中间价 (PBOC Fixing) | 政策信号 | CFETS / PBOC | MEDIUM |

**数据源详情**:
- **BIS 有效汇率**: `https://data.bis.org/topics/EER/BIS%2CWS_EER_D%2C1.0/BIS%2CEERD%2C1.0/D..B.USD?format=csv` — 免费，公开 CSV/API
- **BIS 国际银行统计**: `https://data.bis.org/topics/IBS` — 免费 REST API，季度更新
- **Treasury TIC**: `https://ticdata.treasury.gov/resource-center/data-chart-center/tic-data/` — 免费，月度
- **IMF IFS**: 同上 — 免费，需注册
- **World Bank WDI**: 同上 — 免费 REST API

---

#### #16 Cycle Reader · 周期读者
**领域**: 宏观/跨资产 | **资本**: $60K | **温度**: 0.30

**分析逻辑**: 增长-通胀象限 → 体制识别 → 风险偏好指标 → 全球 PMI 动量 → 金融条件指数 → 央行政策分歧

**当前拥有**:
- [x] 几乎全部 25 个新闻来源（domain=macro，无过滤）
- [x] FRED: BDI 运费指数
- [x] BLS: CPI, PPI, 失业率
- [x] Federal Reserve Press: 美联储声明
- [x] 全部央行 RSS (ECB, BCB, RBI)
- [x] CFTC COT: 4 个期货市场

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| FRED 全面宏观系列 (GDP, IP, PCE, etc.) | 宏观仪表盘 | FRED API (扩展) | **CRITICAL** |
| 全球 PMI 综合 (JPM Global Composite) | 全球增长 | S&P Global / Markit | **CRITICAL** |
| 金融条件指数 (Chicago Fed NFCI) | 金融环境 | FRED (NFCI) / Chicago Fed | **CRITICAL** |
| 美联储 GDPNow 实时预测 | 增长追迹 | Atlanta Fed GDPNow | HIGH |
| 地缘政治风险指数 | 尾部事件 | Caldara & Iacoviello GPR Index | HIGH |
| BIS 跨境资本流 | 全球流动性 | BIS International Banking Stats | HIGH |
| 经济政策不确定性指数 (EPU) | 政策风险 | `https://www.policyuncertainty.com/` | MEDIUM |
| Shiller CAPE (周期性调整市盈率) | 长期估值 | `http://www.econ.yale.edu/~shiller/data.htm` | **CRITICAL** |
| 美国国债外国持有量 (TIC) | 资金安全 | Treasury TIC Data | MEDIUM |

**数据源详情**:
- **FRED GDP**: `GDP`, `GDPC1` — 免费
- **FRED NFCI**: `NFCI` — 免费，每周
- **FRED PCE**: `PCE`, `PCEPILFE` (Core PCE) — 免费，月度
- **Atlanta Fed GDPNow**: `https://www.atlantafed.org/cqer/research/gdpnow` — 免费，实时更新
- **GPR 指数**: `https://www.matteoiacoviello.com/gpr.htm` — 免费 Excel
- **Shiller CAPE**: `http://www.econ.yale.edu/~shiller/data/ie_data.xls` — 免费 Excel，Robert Shiller 主页
- **EPU 指数**: `https://www.policyuncertainty.com/us_monthly.html` — 免费 CSV

---

### 2.2 动量/趋势（4位）

---

#### #17 Intraday Scalper · 日内动量
**策略**: 日内动量 | **持有**: 1-3天 | **资本**: $25K | **温度**: 0.50

**分析逻辑**: 开盘区间突破 → 成交量形态异常 → 订单流失衡 → 跳空模式

**当前拥有**:
- [x] 全部新闻源（间接）
- [x] 市场数据: 资产价格 (Yahoo Finance 代理)

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 日内价格数据 (OHLCV) | 突破检测 | Polygon.io / Alpaca / Alpha Vantage | **CRITICAL** |
| 实时成交量数据 | 成交量确认 | 同上 | **CRITICAL** |
| 盘前/盘后跳空数据 | 跳空交易 | Yahoo Finance extended hours | HIGH |
| VWAP (成交量加权均价) | 机构订单检测 | 自行计算 (需要 OHLCV) | HIGH |
| 当日资金流数据 | 板块轮动 | FINRA 数据 / ETF 日内流量 | MEDIUM |

**数据源详情**:
- **Polygon.io**: `https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/minute/2024-01-09/2024-01-09?apiKey=KEY` — 免费 tier 5 调用/分钟，历史数据丰富
- **Alpaca Markets**: `https://docs.alpaca.markets/docs/market-data-api` — 免费（paper account），实时 websocket
- **Alpha Vantage**: `https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol=IBM&interval=5min&apikey=KEY` — 免费 tier 25 调用/天

---

#### #18 Trend Rider · 趋势骑士
**策略**: 周线趋势 | **持有**: 5-15天 | **资本**: $30K | **温度**: 0.40

**分析逻辑**: ADX > 20 → 均线交叉 → 相对强弱排名 → 成交量确认

**当前拥有**:
- [x] 全部新闻源
- [x] 市场数据: 资产价格

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 日线 OHLCV (完整价格历史) | 趋势指标计算 | Polygon.io / Yahoo Finance | **CRITICAL** |
| 相对强弱排名 (RSI, ROC) | 动量比较 | 自行计算（需要 OHLCV） | HIGH |
| 板块 ETF 相对表现 | 板块轮动 | 已有 XLF/XLK/XLE/XLV/XLI | LOW |
| ETF 资金流量 (周度) | 资金趋势 | ETF.com / EPFR (收费) | HIGH |

---

#### #19 Event Hound · 事件猎犬
**策略**: 事件驱动 | **持有**: 1-5天 | **资本**: $25K | **温度**: 0.45

**分析逻辑**: 盈利超预期 → FDA 决策 → 并购公告 → 监管变化 → 地缘政治发展

**当前拥有**:
- [x] SEC EDGAR RSS: 8-K 文件（公告事件）
- [x] 全部 25 个新闻源：事件新闻覆盖
- [x] Bluesky: 社交媒体事件讨论

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 盈利超预期/不及预期数据库 | 盈利动量 | EarningsWhispers / Refinitiv (收费) | **CRITICAL** |
| 并购公告日历/谣言追踪 | 事件机会 | Dealogic / Bloomberg (收费) — 新闻代理覆盖大部分 | MEDIUM |
| 经济数据发布日历 | 数据事件 | `https://www.econoday.com/` / ForexFactory 日历 | HIGH |
| FDA 决策日历 | 医疗催化 | 同上 (Trial Reviewer 所在) | MEDIUM |
| 地缘政治仪表盘 | 政治风险 | CFR Global Conflict Tracker / ACLED | MEDIUM |

**数据源详情**:
- **Econoday 日历**: `https://www.econoday.com/economic-calendar.aspx` — 网页免费
- **ForexFactory 日历**: `https://www.forexfactory.com/calendar` — 网页免费
- **EarningsWhispers**: `https://www.earningswhispers.com/calendar` — 网页免费，API 收费
- **CFR Global Conflict Tracker**: `https://www.cfr.org/global-conflict-tracker/` — 免费网页

---

#### #20 Rotation Engine · 板块轮动引擎
**策略**: 板块 ETF 轮动 | **持有**: 5-20天 | **资本**: $30K | **温度**: 0.40

**分析逻辑**: 11 GICS 板块相对强弱 → 收益率曲线信号 → 领先指标 → 资金流数据

**当前拥有**:
- [x] 全部新闻源
- [x] 市场数据: SPY, QQQ, XLF, XLK, XLE, XLV, XLI, IWM

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| 11 个 GICS 板块 ETF 日线数据 | 相对强度计算 | 已有 7 个，缺 XLB, XLC, XLP, XLU, XLRE | HIGH |
| 收益率曲线实时数据 (2s10s) | 周期/防御信号 | FRED (T10Y2Y) | **CRITICAL** |
| 板块 ETF 资金流量 (周度) | 资金轮动 | ETF.com / State Street SPDR 数据 | **CRITICAL** |
| 因子轮动 (价值/动量/质量/低波) | 风格偏好 | MSCI 因子指数 / AQR 论文 | MEDIUM |

---

### 2.3 逆向/敢死队（4位）

---

#### #21 Fade Master · 共识逆行者
**策略**: 系统性逆向 | **持有**: 3-10天 | **资本**: $20K | **温度**: 0.55

**分析逻辑**: 当 >75% 专家影子同意时反向 → 情绪极端 → COT 持仓极端 → 认沽/认购比率极端 → AAII

**当前拥有**:
- [x] CFTC COT: ES/CL/GC/NG 持仓数据
- [x] 其他影子意见 (通过 ranking_engine 聚合)
- [x] Bluesky: 社交媒体情绪

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| **AAII 投资者情绪调查 (牛/熊/中性)** | 散户情绪极端 | `https://www.aaii.com/sentimentsurvey` | **CRITICAL** |
| 认沽/认购比率 (总市场 + 个股 + ETF) | 期权情绪 | CBOE P/C Ratio CSV | **CRITICAL** |
| CNN 恐惧/贪婪指数 | 复合情绪 | `https://www.cnn.com/markets/fear-and-greed` | **CRITICAL** |
| 分析师共识评级 (一致性强弱) | 卖方情绪 | FactSet / Refinitiv — 新闻代理 | HIGH |
| 社交媒体情绪量化 (Twitter/Reddit) | 散户狂热 | ApeWisdom (收费) / BullScore | MEDIUM |
| 基金持仓集中度 | 拥挤度 | Goldman Sachs Hedge Fund VIP | MEDIUM |

**数据源详情**:
- **AAII 情绪**: `https://www.aaii.com/sentimentsurvey/sent_results` — 网页免费，每周更新。可爬取或手动输入
- **CBOE 认沽/认购比率**: `https://www.cboe.com/us/options/market_statistics/symbol_data/csv/?mkt=cone` — 公开每日 CSV
- **CNN 恐惧/贪婪**: `https://production.dataviz.cnn.io/index/fearandgreed/graphdata/` — 内部公开 JSON API (非官方但多年稳定)
- **Goldman Hedge Fund VIP**: `https://www.goldmansachs.com/insights/pages/hedge-fund-vip-list` — 收费；替代方案：13F 汇总

---

#### #22 Sideways Scout · 区间侦察兵
**策略**: 区间市场均值回归 | **触发**: VIX < 20 + 日波幅 < 1.5% | **资本**: $25K | **温度**: 0.45

**分析逻辑**: 区间边界反弹 → 成交量收缩 → RSI 背离 → Bollinger Band 挤压

**当前拥有**:
- [x] 市场数据: 资产价格
- [x] 新闻覆盖: 间接

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| VIX 每日数据 (精确值) | 环境触发判断 | CBOE / Yahoo Finance | **CRITICAL** |
| 日波幅数据 (15+ 市场) | 区间识别 | Yahoo Finance / Polygon.io | **CRITICAL** |
| Bollinger Band / RSI 计算基础数据 | 技术信号 | 自行计算 (OHLCV) | HIGH |
| 历史波动率 (20D) | 平静确认 | 自行计算 | HIGH |

---

#### #23 Vol Surfer · 波动冲浪者
**策略**: 恐慌买入 | **触发**: VIX > 30 | **资本**: $30K | **温度**: 0.60

**分析逻辑**: VIX 期限结构倒挂 → 认沽/认购极端 → 广度崩溃 → 信用利差爆裂 → 市场广度

**当前拥有**:
- [x] 市场数据: VXX, UVXY, SPY
- [x] 新闻覆盖: 危机新闻通过全部新闻源

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| VIX 期限结构 (期货曲线) | 恐慌结构 | CBOE VIX Futures | **CRITICAL** |
| 市场广度 (涨跌比, 新高低比) | 广度崩溃 | Barchart / WSJ 市场数据 | **CRITICAL** |
| 信用利差 (IG OAS + HY OAS) | 信用压力 | FRED BAMLC0A0CM / BAMLH0A0HYM2 | **CRITICAL** |
| VSTOXX + VNKY (欧日波动率) | 全球恐慌同步 | STOXX / Nikkei | HIGH |
| TED 利差 | 银行间信任 | FRED (TEDRATE) | HIGH |
| FRA-OIS 利差 | 美元融资压力 | Bloomberg / FRED | HIGH |

**数据源详情**:
- **FRED TEDRATE**: `TEDRATE` — 免费
- **FRED FRA-OIS**: `FEDFUNDS`, `SOFR` + 自行计算 — 免费
- **市场广度**: `https://www.wsj.com/market-data/stocks/marketsdiary` — WSJ 网页免费

---

#### #24 Crash Hunter · 崩盘猎人
**策略**: 做空泡沫 | **触发**: 全球 ≥2 个崩盘信号 | **资本**: $30K | **温度**: 0.50

**分析逻辑**: Shiller CAPE > 30 → Buffett 指标 > 150% → 跨资产相关性上升 → VIX 倒挂 → Hindenburg Omen → 广度背离 → 内部人卖出激增 → 信用利差扩大

**当前拥有**:
- [x] 市场数据: SPY, QQQ, IWM, DIA
- [x] SEC EDGAR: 内部人交易文件 (Form 4)
- [x] 新闻覆盖: 全部

**缺失的关键数据**:
| 缺失数据 | 用途 | 推荐来源 | 优先级 |
|------|------|------|:---:|
| **Shiller CAPE (周期性调整市盈率)** | 长期估值 | `http://www.econ.yale.edu/~shiller/data.htm` (免费 Excel) | **CRITICAL** |
| **Buffett Indicator (总市值/GDP)** | 市场高估 | 自行计算: Wilshire 5000 / FRED GDP | **CRITICAL** |
| **Hindenburg Omen 信号组件** | 技术崩溃 | NYSE 数据 / WSJ 市场数据 | **CRITICAL** |
| 市场广度每日数据 (涨跌 + 新高新低) | 广度背离 | WSJ Markets Diary / Barchart | **CRITICAL** |
| 内部人卖出/买入比率 | 内部人行为 | SEC Form 4 (已有) + OpenInsider (聚合) | **CRITICAL** |
| 信用利差 (IG + HY) | 信用压力 | FRED BAMLC0A0CM + BAMLH0A0HYM2 | HIGH |
| VIX 期限结构 | 波动率信号 | CBOE VIX Futures | HIGH |
| 跨资产相关性 (60D rolling) | 相关性 1.0 信号 | 自行计算 (SPY/GLD/TLT/IWM) | MEDIUM |

**数据源详情**:
- **Shiller CAPE**: 同上 — 免费 Excel，Robert Shiller 学术主页维护
- **Buffett Indicator 计算**: FRED `GDP` (季度) + Wilshire 5000 (FRED `WILL5000PR`) — 免费
- **Hindenburg Omen**: NYSE 涨跌数据 (WSJ/Barron's) + NYSE 52周新高新低
- **内部人交易聚合**: `http://openinsider.com/screener?s=&o=&pl=&ph=&ll=&lh=&fd=365&td=0&fdlyl=&fdlyh=&daysago=&xp=1&xs=1&vl=&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=100&page=1` — 免费网页，可爬取每日更新

---

## 3. 跨所有影子的通用信息缺口

### 3.1 缺失的数据类型（优先级排序）

| 优先级 | 数据类型 | 影响影子数量 | 缺失程度 | 可替代性 |
|:---:|------|:---:|------|------|
| **P0** | **结构化宏观经济数据** (GDP, PCE, ISM PMI, IP, etc.) | 14/24 | 严重缺失 — BLS 覆盖 4 指标，FRED 仅 BDI | FRED 免费 API 可直接覆盖 |
| **P0** | **估值/情绪数据** (CAPE, Buffett Ind., AAII, P/C, Fear/Greed) | 8/24 | 完全缺失 — 无任何来源 | 多个免费公开来源可获取 |
| **P0** | **持仓/资金流数据** (COT 扩展, ETF flows, insider trading) | 10/24 | 部分覆盖 — COT 仅 4 品种 | CFTC API 免费扩展; ETF.com |
| **P0** | **收益率曲线/利差/利率数据** (2s10s, IG/HY OAS, SOFR, TIPS) | 6/24 | 严重缺失 — 无实时数据 | FRED 全覆盖，免费 |
| **P1** | **大宗商品基本面数据** (LME 库存, USDA, EIA 扩展, Baker Hughes) | 5/24 | 部分覆盖 — EIA 仅 3 产品 | 多个免费来源可获取 |
| **P1** | **链上加密货币数据** (活跃地址, TVL, 稳定币, 哈希率) | 1/24 | 完全缺失 — 仅 CoinTelegraph 新闻 | DefiLlama 免费, Glassnode 收费 |
| **P1** | **波动率曲面数据** (VIX 期货曲线, SKEW, VVIX, VSTOXX) | 3/24 | 完全缺失 — 仅市场新闻提及 | CBOE 公有 CSV; 多个免费指数 |
| **P1** | **新兴市场数据** (EMBI 利差, IIF 资金流, PMI 各国) | 2/24 | 最小覆盖 — 仅 3 央行 RSS | FRED + IMF IFS 免费 |
| **P2** | **行业特定数据** (半导体出货, FDA 日历, 航运指数) | 5/24 | 完全缺失 — 仅新闻 | 多来源; 部分免费/部分收费 |
| **P2** | **房地产数据** (房屋开工, Case-Shiller, 抵押利率) | 1/24 | 完全缺失 — 仅新闻 + VNQ 价格 | FRED 全覆盖，免费 |
| **P2** | **日内/实时市场数据** (OHLCV, minute data, VWAP) | 2/24 | 完全缺失 — 仅收盘价 | Polygon/Alpaca 免费 tier |

### 3.2 缺失数据的结构性原因

当前 MarketMind 信息架构有两个根本性缺口：

1. **FRED API 利用不足**：`gateway/macro_data.py` 当前仅获取 BDI 和 GSCPI（后者还无法获取）。FRED 拥有 80 万+ 宏观/金融时间序列，且完全免费。我们正在使用的是一个相当于 0.01% 利用率的 API。

2. **没有"结构化数据管道"概念**：所有 23 个新闻来源通过 scout.py 的 RSS 管道统一处理，适用于文本。但结构化数据完全不同——需要专用的获取器、缓存、标准化的 JSON 响应格式。`macro_data.py` 的模式（session-cached async fetch）是正确的，但范围太小。

---

## 4. 推荐实施路线图

### Phase 1: 基础设施 — FRED API 全面接入 (P0, 预计工作量: 3-5天)

**目标**: 将 FRED 从 2 个指标扩展到 ~30 个核心宏观/金融系列，覆盖 14 个影子。

**新 FRED 系列清单**:
```
# 收益率/利率 (Yield Whisperer, Cycle Reader, Bank Examiner)
DGS2, DGS5, DGS10, DGS30          # 国债收益率
DFII5, DFII10                       # TIPS 实际收益率
T10Y2Y, T10Y3M                      # 收益率曲线利差
BAMLC0A0CM, BAMLH0A0HYM2            # IG/HY OAS 信用利差
MORTGAGE30US                        # 30年抵押利率

# 宏观/经济增长 (Cycle Reader, Factory Floor)
GDP, GDPC1                          # GDP
INDPRO                              # 工业生产
PAYEMS                              # 非农就业
UMCSENT                             # 密歇根消费者情绪
PSAVERT                             # 个人储蓄率

# 通胀 (全部影子基础数据)
PCE, PCEPILFE                       # PCE, Core PCE
T5YIFR                              # 5Y5Y 通胀互换远期

# 房地产 (REIT Analyst)
HOUST, PERMIT                       # 房屋开工/营建许可
SPCS20RSA                           # Case-Shiller 20 城市

# 消费/零售 (Wallet Watcher)
RSXFS, RETAIL                       # 零售销售

# 金融条件 (Cycle Reader, Fade Master)
NFCI                                # Chicago Fed 金融条件指数

# 工业 (Factory Floor)
DGORDER, NEWORDER                   # 耐用品订单
TEDRATE                             # TED 利差

# 市场估值 (Crash Hunter, Cycle Reader)
WILL5000PR                          # Wilshire 5000 (Buffett Ind. 组件)

# 外汇/EM (Currency Dealer, Frontier Scout)
DTWEXBGS                            # 贸易加权美元指数
```

**实施文件**: `gateway/fred_client.py`（从 `macro_data.py` 中提取 FRED 逻辑并扩展）
**密钥**: FRED_KEY（已有获取逻辑 `_get_fred_key()`）
**速率限制**: FRED API 免费 tier 120 调用/分钟
**响应格式**: 标准化 JSON `{"series_id": "...", "label": "...", "value": ..., "date": "...", "source": "fred"}`

### Phase 2: 情绪与持仓数据 (P0, 预计工作量: 3-4天)

**2a. 情绪数据获取器** `gateway/sentiment_fetcher.py`:
- **CBOE 认沽/认购比率**: 公开 CSV 下载 → JSON 缓存
- **CNN 恐惧/贪婪指数**: 内部 JSON API 代理
- **AAII 情绪调查**: 网页爬取或手动输入（周度）
- 受益影子: Fade Master, Vol Surfer, Crash Hunter, Wallet Watcher (消费者情绪 via UMCSENT 已在 FRED)

**2b. CFTC COT 扩展**: 在现有 `get_cot_data()` 中添加农产品品种:
- CORN (玉米), WHEAT (芝加哥小麦), SOYBEAN (大豆), COFFEE (咖啡)
- 可选: COPPER (铜), SILVER (银), COTTON (棉花)
- 受益影子: Harvest Seer, Steel Trader, Bullion Broker

**2c. Shiller CAPE + Buffett Indicator** `gateway/valuation_fetcher.py`:
- CAPE: 直接读取 Robert Shiller 学术主页 Excel 文件
- Buffett Indicator: 计算 `WILL5000PR / GDP`
- 受益影子: Crash Hunter, Cycle Reader, Fade Master

### Phase 3: 大宗商品基本面 (P1, 预计工作量: 4-5天)

**3a. LME 金属数据** `gateway/lme_fetcher.py`:
- LME 每日库存报告 (铜/铝/锌/镍/铅)
- LME 每日官方价格
- 受益影子: Steel Trader

**3b. USDA 农业数据** `gateway/usda_fetcher.py`:
- WASDE 月度供需报告 — PDF 解析或手动数据
- 作物进展周报 (CSV)
- 受益影子: Harvest Seer

**3c. EIA 数据扩展** `gateway/eia_fetcher.py`:
- 天然气存储 (补充原油库存)
- 原油产量估算
- Baker Hughes 钻井平台数
- 受益影子: Oil Geologist

**3d. ENSO/天气数据** `gateway/weather_fetcher.py`:
- NOAA CPC ENSO 预报
- 全球干旱监测
- 受益影子: Harvest Seer

### Phase 4: 加密货币与跨资产 (P1, 预计工作量: 2-3天)

**4a. 链上数据** `gateway/crypto_onchain.py`:
- DefiLlama API (免费 — TVL, DEX 量, 稳定币)
- Blockchain.com API (免费 — 哈希率, 活跃地址)
- Alternative.me 恐惧贪婪指数 (免费)
- 受益影子: Chain Oracle

**4b. 跨资产资本流** `gateway/cross_border.py` (已有基础框架):
- BIS 国际银行统计 (免费 API)
- IIF 资本流 (收费摘要, 免费新闻替代)
- TIC 数据 (免费)
- 受益影子: Currency Dealer, Frontier Scout, Cycle Reader

### Phase 5: 波动率曲面与行业数据 (P2, 预计工作量: 3-4天)

**5a. 波动率数据** `gateway/vol_surface_fetcher.py`:
- CBOE VIX 期货期限结构 (公开 CSV)
- CBOE SKEW 指数
- CBOE VVIX 指数
- VSTOXX, VNKY (跨市场)
- 受益影子: Vega Trader, Vol Surfer, Crash Hunter

**5b. 行业特定数据**:
- FDA 审批日历 (OpenFDA API) → Trial Reviewer
- SIA 半导体出货 → Silicon Oracle
- 台积电月度营收 → Silicon Oracle
- 受益影子: Trial Reviewer, Silicon Oracle

---

## 5. API 密钥采集指南

### 5.1 必需密钥 (启动前获取)

| 密钥 | 用途 | 获取方式 | 成本 | 速率限制 |
|------|------|------|------|------|
| `FRED_KEY` | FRED 宏观经济数据 | `https://fred.stlouisfed.org/docs/api/api-key.html` | **免费** | 120 次/分钟 |
| `EIA_KEY` | EIA 能源数据 | `https://www.eia.gov/opendata/register.php` | **免费** | 2000 次/天 |
| `NEWSAPI_KEY` | NewsAPI 新闻聚合 | `https://newsapi.org/register` | **免费** Developer tier | 100 次/天 |
| `GNEWS_API_KEY` | GNews 新闻聚合 | `https://gnews.io/register` | **免费** tier: 100 次/天 | 100 次/天 |
| `BLUESKY_USERNAME` + `BLUESKY_APP_PASSWORD` | Bluesky 社交数据 | Bluesky 设置 → App Passwords | **免费** | 50 次/5 分钟 |

### 5.2 推荐密钥 (可选但有重大价值)

| 密钥 | 用途 | 获取方式 | 成本 | 价值评估 |
|------|------|------|------|------|
| `GLASSNODE_API_KEY` | 链上加密数据 | `https://studio.glassnode.com/` | Free tier 有限; Pro $49/月 | 高 — 链上分析核心 |
| `POLYGON_API_KEY` | 日内价格/成交量 | `https://polygon.io/` | Free tier 5 调用/分钟 | 高 — 日内影子必需 |
| `ALPHA_VANTAGE_KEY` | 日内OHLCV 替代 | `https://www.alphavantage.co/support/#api-key` | **免费** 25 次/天 | 中 |
| `IMF_DATA_API_KEY` | IMF IFS 国际金融统计 | `https://data.imf.org/` | **免费** (需注册) | 高 — EM 数据核心 |
| `CLINICALTRIALS_GOV` | 无密钥 | `https://clinicaltrials.gov/api/v2/` | **免费, 无密钥** | 高 — FDA 影子必需 |
| `DEFILLAMA` | 无密钥 | `https://defillama.com/docs/api` | **免费, 无密钥** | 最高 — 最好的免费加密数据 |

### 5.3 免费且无需密钥的来源

这些来源可以在零成本、零注册的情况下立即集成：

| 来源 | 数据类型 | URL |
|------|------|------|
| CFTC SODA (已实施) | COT 期货持仓 | `publicreporting.cftc.gov/resource/6dca-aqww.json` |
| BLS API (已实施) | CPI, 失业率, PPI | `api.bls.gov/publicAPI/v2/timeseries/data/` |
| CBOE 每日 CSVs | 期权统计, 认沽/认购比率 | `cboe.com/us/options/market_statistics/` |
| FRED API (实施中) | 宏观经济数据 | `api.stlouisfed.org/fred/` (需免费密钥) |
| DefiLlama API | 加密 DeFi 数据 | `api.llama.fi/` |
| Blockchain.com API | 加密网络数据 | `api.blockchain.info/charts/` |
| Alternative.me | 加密恐惧/贪婪 | `api.alternative.me/fng/` |
| World Bank API | 全球发展指标 | `api.worldbank.org/v2/` |
| LME 价格 API | 金属价格/库存 | `lme.com/api/` (内部 API, 未记录但公开) |
| BIS 统计数据 | 跨境银行/汇率 | `data.bis.org/` |
| CME FedWatch JSON | Fed 加息概率 | `cmegroup.com/CmeWS/` (公开 JSON) |
| FDA OpenFDA | 药品/设备数据 | `api.fda.gov/` |
| TreasuryDirect API | 国债拍卖 | `treasurydirect.gov/TA_WS/` |
| ClinicalTrials.gov API | 临床研究数据 | `clinicaltrials.gov/api/v2/` |
| NOAA CPC | ENSO 天气预报 | `cpc.ncep.noaa.gov/` |
| Census Bureau API | 零售销售/房屋数据 | `api.census.gov/` |
| IMF IFS (免费密钥) | 国际金融统计 | `data.imf.org/` |
| World Bank GEM Commodities (Pink Sheet) | 商品价格 | `worldbank.org/en/research/commodity-markets` |

---

## 6. 影子-数据源矩阵总结

### 6.1 现状覆盖度

| 影子 | 现有可用数据 | 数据充足度 | 最紧急缺口 |
|------|------|:---:|------|
| Bullion Broker | COT GC + 新闻 + Bluesky | **40%** | FRED 实际利率, WGC 央行购金, GLD ETF 流量 |
| Chain Oracle | CoinTelegraph + 新闻 + Bluesky | **25%** | 链上数据 (DefiLlama), BTC ETF 流量, 稳定币 |
| Oil Geologist | EIA 库存 + COT CL/NG + OPEC 新闻 | **45%** | Baker Hughes 钻井数, EIA 天然气存储, 裂解价差 |
| Yield Whisperer | Fed Press + FRED blog | **25%** | FRED TIPS 收益率, FRED 信用利差, CME FedWatch |
| Vega Trader | VXX/UVXY 价格 | **15%** | VIX 期限结构, SKEW, VVIX, P/C 比率 |
| Frontier Scout | 央行 RSS ×3 + 中国 ×4 | **35%** | EMBI 利差 (FRED), IIF 资本流, DXY |
| Silicon Oracle | SEC EDGAR + 新闻 | **30%** | SIA 半导体出货, TSMC 营收, 云服务商 CAPEX |
| Bank Examiner | Fed Press + SEC EDGAR + 新闻 | **35%** | FRED H.8 银行资产, FRED 贷款增长, NCO 坏账率 |
| Trial Reviewer | SEC EDGAR + 新闻 | **25%** | FDA 审批日历, ClinicalTrials.gov, CMS 定价 |
| Wallet Watcher | BLS CPI/就业 + 新闻 | **30%** | 密歇根情绪 (FRED UMCSENT), 零售销售 (FRED), AAII |
| Factory Floor | FRED BDI + 新闻 | **30%** | ISM PMI, FRED 耐用品订单, SCFI 运费 |
| Steel Trader | 中国新闻 ×4 | **20%** | LME 库存/价格, SHFE 库存, FRED 中国 PMI 代理 |
| Harvest Seer | FRED BDI + 新闻 | **15%** | USDA WASDE, CFTC 农产品 COT, ENSO 预报 |
| REIT Analyst | SEC EDGAR + 新闻 | **20%** | FRED 房屋开工, Case-Shiller, 抵押利率 |
| Currency Dealer | 央行 RSS ×6 + 新闻 | **40%** | BIS 有效汇率, 利差计算, TIC 数据 |
| Cycle Reader | 25 新闻源 + BLS + COT | **50%** | FRED GDP/PCE/NFCI, 全球 PMI, Shiller CAPE |
| Intraday Scalper | 价格数据 | **10%** | 日内 OHLCV, VWAP, 成交量 |
| Trend Rider | 价格数据 | **20%** | 日线 OHLCV, ETF 资金流 |
| Event Hound | SEC EDGAR + 全新闻源 | **45%** | 盈利数据/Econoday 日历 |
| Rotation Engine | 7 板块 ETF 价格 | **35%** | FRED 2s10s 曲线, ETF 资金流, 板块 ETF 补全 |
| Fade Master | COT ×4 + 影子共识 | **35%** | AAII 情绪, P/C 比率, CNN 恐惧贪婪 |
| Sideways Scout | 价格数据 | **15%** | VIX 数据, 波动率计算基础 |
| Vol Surfer | VXX/UVXY/SPY 价格 + 全新闻 | **25%** | VIX 期货结构, 市场广度, FRED 信用利差 |
| Crash Hunter | SPY/QQQ + SEC EDGAR + 全新闻 | **30%** | Shiller CAPE, Buffett Ind., Hindenburg Omen, 广度, 内部人交易 |

### 6.2 实施后预期覆盖度 (Phase 1-5 完成)

| 影子 | 实施后覆盖度 | 新增来源数 |
|------|:---:|:---:|
| Bullion Broker | **85%** | +4 (FRED TIPS + WGC + ETF flow + ICE DXY) |
| Chain Oracle | **80%** | +5 (DefiLlama + Blockchain.com + Farside + Glassnode + Fear/Greed) |
| Oil Geologist | **85%** | +3 (Baker Hughes + EIA扩展 + Crack Spread) |
| Yield Whisperer | **90%** | +5 (FRED 系列 + CME FedWatch + SOFR + MOVE + TIPS) |
| Vega Trader | **75%** | +5 (VIX Futures + SKEW + VVIX + P/C + VSTOXX) |
| Frontier Scout | **80%** | +4 (FRED EMBI + IIF + DXY + IMF IFS) |
| Silicon Oracle | **70%** | +3 (SIA + TSMC + CAPEX tracker) |
| Bank Examiner | **85%** | +4 (FRED H.8 + NCO + CME FedWatch + FDIC) |
| Trial Reviewer | **75%** | +3 (FDA API + ClinicalTrials + CMS) |
| Wallet Watcher | **85%** | +4 (FRED UMCSENT + FRED 零售 + AAII + Census API) |
| Factory Floor | **80%** | +5 (FRED ISM代理 + FRED 耐用品 + SCFI + Ifo + Cass) |
| Steel Trader | **75%** | +4 (LME + SHFE + FRED 工业 + 铁矿石价格) |
| Harvest Seer | **80%** | +6 (USDA WASDE + USDA Crop + NOAA ENSO + CFTC COT扩展 + WB Pink Sheet + FAO) |
| REIT Analyst | **85%** | +5 (FRED 房屋开工 + Case-Shiller + 抵押利率 + NAR + Freddie Mac) |
| Currency Dealer | **85%** | +4 (BIS EER + BIS IBS + TIC + IMF IFS) |
| Cycle Reader | **95%** | +6 (FRED 全面 + 全球 PMI + NFCI + GDPNow + GPR + Shiller CAPE) |
| Intraday Scalper | **60%** | +2 (Polygon/Alpaca OHLCV + VWAP) |
| Trend Rider | **65%** | +2 (日线OHLCV + ETF资金流) |
| Event Hound | **75%** | +3 (盈利DB + Econoday + CFR Geopolitical) |
| Rotation Engine | **75%** | +3 (FRED 2s10s + ETF资金流 + 板块ETF补全) |
| Fade Master | **85%** | +4 (AAII + P/C比率 + Fear/Greed + Insider OI) |
| Sideways Scout | **60%** | +2 (VIX + OHLCV 技术计算) |
| Vol Surfer | **85%** | +5 (VIX期货 + 广度 + FRED信用利差 + TED + FRA-OIS) |
| Crash Hunter | **90%** | +7 (Shiller CAPE + Buffett Ind. + Hindenburg + 广度 + Insider + FRED信用 + VIX期货) |

---

## 7. 实施注意事项

### 7.1 文件组织

新获取器应遵循 `gateway/macro_data.py` 的模式：
- 每个数据源类型一个模块（非一个来源一个文件）
- 模块级 session cache（与 `macro_data.py` 相同的 `_cache` + `_cache_locks` 模式）
- 所有字符串字段通过 `input_guard.sanitize_for_llm_prompt()` 消毒
- 返回值标准化 JSON dict，失败时返回 `{"error": "source_unavailable"}`
- API 密钥从 `MarketMindConfig` 获取，后备到环境变量
- 每个新获取器 ≥3 个测试

### 7.2 速率限制策略

| API | 免费限制 | 获取策略 |
|------|------|------|
| FRED | 120/分钟 | 批处理 — 单次请求获取全部 30 系列 |
| EIA | 2000/天 | 每日一次获取所有产品 |
| DefiLlama | 100/分钟 | 单次 TVL + 稳定币获取 |
| Blockchain.com | 未说明 | 单次获取哈希率 |
| CBOE CSVs | 未说明 | 每日一次下载 |
| Polygon.io | 5/分钟 | 仅在日内影子活跃时获取 |

### 7.3 影子数据分发

当前影子通过 `_analyze()` 方法接收 `news_items` (文本) 和 `market_data` (价格 dict)。新增的结构化数据应通过 `market_data` dict 传递——作为额外的 key：

```python
# 示例: Oil Geologist 收到的 market_data
{
    "prices": {...},           # 现有
    "eia_inventory": {...},    # 新 — EIA 原油库存
    "cot_cl": {...},           # 已有 — CFTC COT
    "baker_hughes_rigs": {...}, # 新 — 钻井平台数
}
```

这避免了修改 `_analyze()` 函数签名，同时让每个影子能访问其专属的结构化数据。

### 7.4 测试策略

每个新获取器编写 3 类测试：
1. **Mock 测试**: 用 `unittest.mock.patch` 模拟 HTTP 响应 → 验证解析逻辑
2. **真实 API 测试** (可选标记 `@pytest.mark.integration`): 验证 API 格式未变
3. **LLM 消费测试**: 验证 JSON 输出可被影子 prompt 直接引用

### 7.5 PICA 审计要求

所有新 `.py` 文件触发完整 PICA 协议:
- PICA-Unit: pytest 0 失败
- PICA-Security: 密钥泄漏检查, URL 参数注入, 输入消毒验证
- PICA-Integration: 与 `scout.py` / `shadow_agent.py` 的集成点检查
- PICA-Regression: 现有 1272 测试继续通过

---

## 8. 附录

### 8.1 被评估但排除的来源及原因

| 来源 | 数据类型 | 排除原因 |
|------|------|------|
| Bloomberg API | 全面金融数据 | **$24,000/年** — 超出个人项目预算 |
| Refinitiv Eikon | 全面金融数据 | **$20,000+/年** — 同上 |
| IQVIA (医疗) | 处方药销量 | **$50,000+/年** — 仅 Phase 5 考虑替代方案 |
| CoStar (房地产) | 入住率/租金 | **$10,000+/年** — FRED 覆盖大部分需求 |
| EPFR Global | ETF/基金资金流 | **$30,000+/年** — FRED + ETF.com 免费替代 |
| Glassnode Advanced | 链上数据 | Pro $49/月 — Free tier 可接受作为起点 |
| CryptoQuant | 交易所余额 | Pro $29/月 — 可后续升级 |
| Fastmarkets / Platts | 金属价格 | **$5,000+/年** — LME 免费替代 |

### 8.2 应急后备方案

如果某个关键 API 不可用，以下是备选方案：

| 数据需求 | 主来源 | 后备来源 | 后备方法 |
|------|------|------|------|
| 宏观经济 | FRED API | World Bank API + IMF IFS | 更粗粒度但免费 |
| 股指估值 | Shiller Excel | FRED SP500 + CPI (手动计算 CAPE) | 精确度略低 |
| ETF 资金流 | ETF.com API | 13F 汇总 (季度) + 新闻 | 延迟更大 |
| 链上数据 | DefiLlama | Blockchain.com + CoinGecko | 少几个指标 |
| 农产品数据 | USDA WASDE | World Bank Pink Sheet | 更粗粒度 |
| 波动率曲面 | CBOE CSV | Yahoo Finance VIX + VIX 期货 | 无 SKEW/VVIX |
| AAII 情绪 | AAII 网站 | CNN 恐惧/贪婪 (复合替代) | 单一指标 vs 直接调查 |

### 8.3 文档历史

- **2026-05-20**: 初始文档 — 完整 24 影子 × 信息源映射，5 Phase 实施路线图，API 密钥获取指南
- **待定**: Phase 1 完成后更新实施覆盖率
- **待定**: 每次新增数据源后更新此文档

---

**下次操作**: 启动 Phase 1 — 扩展 FRED API 接入到 ~30 个核心宏观系列。见 `E:/AI_Studio_Workspace/projects/marketmind/.claude/plans/phase-1-fred-expansion.md`（待创建）。
