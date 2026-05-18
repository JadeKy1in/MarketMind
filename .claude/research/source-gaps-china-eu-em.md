# MarketMind Source Gap Research: China, EU, Emerging Markets

**Date**: 2026-05-17
**Purpose**: Fill three major coverage gaps with FREE, reliable, timely information sources.
**Methodology**: WebSearch verification of URLs, update frequency, and reliability.

---

## Gap 1: China -- Highest Priority

### 1.1 PBOC Official Announcements (English)

| Field | Value |
|---|---|
| **Name** | PBOC English Announcements -- Open Market Operations |
| **URL** | https://www.pbc.gov.cn/en/3688110/3688181/ |
| **Type** | Web (HTML index page, no RSS) |
| **Country** | CN |
| **Update Freq** | Daily (open market operations published each trading day) |
| **Reliability** | Official -- government source |
| **Language** | EN (English section of pbc.gov.cn) |
| **Notes** | No RSS feed available. Monitor via web scraper or change-detection tool. Covers: reverse repos, outright reverse repos, central bank bill issuances, MLF operations. |

| Field | Value |
|---|---|
| **Name** | PBOC English Announcements -- Policy & Press Releases |
| **URL** | https://www.pbc.gov.cn/en/3688110/3688172/ |
| **Type** | Web (HTML index page, no RSS) |
| **Country** | CN |
| **Update Freq** | Weekly to monthly (policy decisions, MPC statements, FX policy) |
| **Reliability** | Official -- government source |
| **Language** | EN |
| **Notes** | Covers: RRR changes, interest rate decisions, FX risk reserve ratio, RMB cross-border policy, MPC meeting summaries. Verified active as of May 2026 (Q1 2026 MPC statement, March 2026 FX reserve ratio cut). |

| Field | Value |
|---|---|
| **Name** | PBOC Monetary Policy Committee Statements |
| **URL** | https://www.pbc.gov.cn/en/3688229/3688311/3688329/ |
| **Type** | Web (HTML index page) |
| **Country** | CN |
| **Update Freq** | Quarterly (MPC meets ~once per quarter) |
| **Reliability** | Official -- government source |
| **Language** | EN |

### 1.2 Caixin / Caixin Global

| Field | Value |
|---|---|
| **Name** | Caixin Global -- Official RSS Feed |
| **URL** | https://gateway.caixin.com/api/data/global/feedlyRss.xml |
| **Type** | RSS |
| **Country** | CN |
| **Update Freq** | Daily (~20-25 original stories/day) |
| **Reliability** | High -- independent financial journalism, English edition of Caixin |
| **Language** | EN |
| **Notes** | Caveat: users report this official RSS contains fewer articles than the website. Use RSSHub as fallback (below). Covers: China macro, financial policy, PMI data, tech/TMT. |

| Field | Value |
|---|---|
| **Name** | RSSHub -- Caixin Global (community-maintained, more comprehensive) |
| **URL** | https://rsshub.app/caixinglobal/latest |
| **Type** | RSS (via RSSHub) |
| **Country** | CN |
| **Update Freq** | Daily |
| **Reliability** | Medium-High (community-maintained, generally more comprehensive than official feed) |
| **Language** | EN |
| **Notes** | Self-host or use public instance. Also offers Caixin Chinese routes: /caixin/latest, /caixin/finance/bank, /caixin/economy, etc. |

| Field | Value |
|---|---|
| **Name** | Caixin Global Website |
| **URL** | https://www.caixinglobal.com/ |
| **Type** | Web |
| **Country** | CN |
| **Update Freq** | Daily |
| **Reliability** | High |
| **Language** | EN |
| **Notes** | Some content behind paywall. Key source for Caixin PMI (manufacturing & services), independent financial coverage. |

### 1.3 A-Share Market Sentiment / Northbound Capital Flows

| Field | Value |
|---|---|
| **Name** | AKShare -- Northbound Capital Flows (Stock Connect) |
| **URL** | https://github.com/akfamily/akshare |
| **Type** | Python API (free, no key required) |
| **Country** | CN |
| **Update Freq** | Daily (T+1 for official exchange data) |
| **Reliability** | Medium-High (aggregates from East Money/Sina Finance official sources) |
| **Language** | ZH (data), EN (docs) |
| **Notes** | CRITICAL: Since Aug 19 2024, China exchanges stopped publishing real-time buy/sell breakdowns. Only daily turnover totals + top-10 active stocks are available post-close. `ak.stock_hsgt_hist_em()` function. Also provides A-share market sentiment via money flow indicators. |

| Field | Value |
|---|---|
| **Name** | stocks-rss -- A-Share Northbound Flow RSS Generator |
| **URL** | https://github.com/cwjcw/stocks-rss |
| **Type** | RSS (generated via GitHub Actions + AKShare) |
| **Country** | CN |
| **Update Freq** | Daily (configurable) |
| **Reliability** | Medium (community project, depends on AKShare upstream) |
| **Language** | ZH |
| **Notes** | Generates RSS XML for northbound flows (Shanghai/Shenzhen connect), major/retail fund flows. Deployable to Cloudflare Pages. |

| Field | Value |
|---|---|
| **Name** | SAFE -- Cross-Border Capital Flow Data |
| **URL** | https://www.safe.gov.cn/en/SAFENews/index_5.html |
| **Type** | Web (monthly releases) |
| **Country** | CN |
| **Update Freq** | Monthly (~15th-22nd of each month) |
| **Reliability** | Official -- government source |
| **Language** | EN |
| **Notes** | Covers: bank FX settlement/sales, cross-border receipts/payments, foreign holdings of domestic stocks/bonds. Q3 2025: net cross-border capital inflow USD 119.7B. No RSS; requires scraping or manual monitoring. |

### 1.4 Major Chinese Economic Data (CPI, PMI, GDP, Trade Balance)

| Field | Value |
|---|---|
| **Name** | AKShare -- China Macroeconomic Data |
| **URL** | https://github.com/akfamily/akshare |
| **Type** | Python API (free, no key required) |
| **Country** | CN |
| **Update Freq** | Monthly (CPI, PMI, PPI, trade), Quarterly (GDP) |
| **Reliability** | High (direct from NBS/China Customs/Golden Ten Data sources) |
| **Language** | ZH/EN |
| **Notes** | Functions: `macro_china_cpi_yearly()`, `macro_china_pmi_yearly()`, `macro_china_cx_pmi_yearly()` (Caixin PMI), `macro_china_gdp_yearly()`, `macro_china_trade_balance()`, `macro_china_money_supply()`, `macro_china_lpr()`, `macro_china_social_financing()`. All verified active 2025. |

| Field | Value |
|---|---|
| **Name** | China Daily -- Bizchina (Business) RSS |
| **URL** | http://www.chinadaily.com.cn/rss/bizchina_rss.xml |
| **Type** | RSS |
| **Country** | CN |
| **Update Freq** | Daily |
| **Reliability** | Medium-High (state-owned English media, covers official data releases) |
| **Language** | EN |
| **Notes** | Free for non-commercial use. Covers economic data releases, policy announcements, market reports. Other useful feeds: china_rss.xml, world_rss.xml, opinion_rss.xml. |

| Field | Value |
|---|---|
| **Name** | SCMP RSS Feeds |
| **URL** | https://www.scmp.com/rss |
| **Type** | RSS (multiple topic feeds) |
| **Country** | HK |
| **Update Freq** | Daily |
| **Reliability** | High -- major English-language HK newspaper |
| **Language** | EN |
| **Notes** | RSS feeds provide headlines + summaries only. Full articles behind paywall (HK$399/year). Business section RSS available from the /rss directory. Alternative: RSSHub route /scmp/:category_id. |

| Field | Value |
|---|---|
| **Name** | Yicai Global |
| **URL** | https://www.yicaiglobal.com/ |
| **Type** | Web (no confirmed RSS endpoint; try /rss, /feed, /rss.xml) |
| **Country** | CN |
| **Update Freq** | Daily (~20-25 stories/day) |
| **Reliability** | High -- Shanghai Media Group-backed, English financial news |
| **Language** | EN |
| **Notes** | Free. Covers: China macro, financial policy, TMT, fintech. Content also on Bloomberg terminals. No confirmed RSS URL -- if needed, generate via RSS-Bridge or FetchRSS. |

### 1.5 RMB/CNY Exchange Rate Intervention Signals

| Field | Value |
|---|---|
| **Name** | PBOC -- FX Policy Announcements |
| **URL** | https://www.pbc.gov.cn/en/3688110/3688172/ |
| **Type** | Web (same policy page as above) |
| **Country** | CN |
| **Update Freq** | Ad hoc (intervention signals, reserve ratio changes, fixing mechanism adjustments) |
| **Reliability** | Official |
| **Language** | EN |
| **Notes** | Key events: March 2026: FX risk reserve ratio cut from 20% to zero for forward FX sales. Also: RMB central parity rate (daily fixing) signals. |

| Field | Value |
|---|---|
| **Name** | SAFE -- Foreign Exchange Data |
| **URL** | https://www.safe.gov.cn/en/ |
| **Type** | Web |
| **Country** | CN |
| **Update Freq** | Monthly (forex reserves, bank settlement data) |
| **Reliability** | Official |
| **Language** | EN |
| **Notes** | Monthly forex reserve figures, bank FX settlement/sales data, Q&A with SAFE spokespersons on RMB trends. |

---

## Gap 2: European Union -- Medium Priority

### 2.1 ECB Monetary Policy

| Field | Value |
|---|---|
| **Name** | ECB -- RSS News Feeds (Main Hub) |
| **URL** | https://www.ecb.europa.eu/home/html/rss.en.html |
| **Type** | RSS |
| **Country** | EU |
| **Update Freq** | Daily (press releases), every 6 weeks (policy decisions) |
| **Reliability** | Official -- central bank source |
| **Language** | EN |
| **Notes** | Central hub for ALL ECB RSS feeds. Feeds available for: press releases, speeches, publications, statistical releases, exchange rates. |

| Field | Value |
|---|---|
| **Name** | ECB -- Press Releases RSS |
| **URL** | https://www.ecb.europa.eu/rss/press.html |
| **Type** | RSS |
| **Country** | EU |
| **Update Freq** | Daily |
| **Reliability** | Official |
| **Language** | EN |
| **Notes** | Covers: monetary policy decisions, Governing Council non-rate decisions, banking supervision, statistical releases, institutional announcements. |

| Field | Value |
|---|---|
| **Name** | ECB -- Market Information Dissemination (MID) RSS |
| **URL** | https://www.ecb.europa.eu/press/html/mid.en.html |
| **Type** | RSS (structured, machine-readable RSS 2.0) |
| **Country** | EU |
| **Update Freq** | Daily (EUR FX reference rates ~14:15 CET), ad hoc (policy decisions) |
| **Reliability** | Official -- designed for automated consumption |
| **Language** | EN |
| **Notes** | Covers: policy decisions, EUR FX reference rates (daily), tender operation announcements, EURSTR rates, eligible assets lists. Best choice for programmatic use. |

| Field | Value |
|---|---|
| **Name** | ECB -- Statistical Press Releases |
| **URL** | https://www.ecb.europa.eu/stats/ecb_statistics/accessing-our-data/html/index.en.html |
| **Type** | Web + RSS |
| **Country** | EU |
| **Update Freq** | Monthly/quarterly |
| **Reliability** | Official |
| **Language** | EN |
| **Notes** | Balance of payments, monetary developments (M3), HICP, bank interest rates. Statistical calendar with release dates available. |

### 2.2 EU Commission Antitrust/Regulation

| Field | Value |
|---|---|
| **Name** | European Commission -- Press Corner RSS |
| **URL** | https://ec.europa.eu/commission/presscorner/api/rss |
| **Type** | RSS (API-based) |
| **Country** | EU |
| **Update Freq** | Daily |
| **Reliability** | Official |
| **Language** | EN (multilingual available) |
| **Notes** | Filter by topic: COMPET for competition/antitrust. Competition topic page: https://ec.europa.eu/commission/presscorner/home/en?topics=COMPET |

| Field | Value |
|---|---|
| **Name** | DG Competition -- Antitrust RSS |
| **URL** | https://competition-policy.ec.europa.eu/antitrust/rss_en |
| **Type** | RSS |
| **Country** | EU |
| **Update Freq** | Weekly to monthly (case-specific) |
| **Reliability** | Official -- DG COMP |
| **Language** | EN |
| **Notes** | Covers: antitrust decisions, merger control, state aid, cartel fines, policy consultations. Key 2025 cases: Microsoft Teams unbundling, Delivery Hero/Glovo no-poach cartel fine, Intel fine reduction. |

### 2.3 Eurozone Economic Data (PMI, CPI, GDP)

| Field | Value |
|---|---|
| **Name** | Eurostat -- Main Site (RSS available) |
| **URL** | https://ec.europa.eu/eurostat/web/main/home |
| **Type** | Web + RSS |
| **Country** | EU |
| **Update Freq** | Daily to monthly |
| **Reliability** | Official -- EU statistical office |
| **Language** | EN/DE/FR (multilingual) |
| **Notes** | RSS feeds available from homepage. Covers: GDP, employment, CPI/HICP, industrial production, retail trade, public debt. Publications: "Key Figures on Europe" and "Regional Yearbook" annual editions. |

| Field | Value |
|---|---|
| **Name** | Euronews Business RSS |
| **URL** | https://www.euronews.com/business/feed |
| **Type** | RSS |
| **Country** | EU |
| **Update Freq** | Daily |
| **Reliability** | Medium (news media, not primary data) |
| **Language** | EN |
| **Notes** | Free. Covers EU business/economy news. Additional feeds: /feeds/business, /tag/economy/feed. Useful for narrative context around official data releases. |

### 2.4 European Market Indices

| Field | Value |
|---|---|
| **Name** | Financial Times -- Custom myFT RSS |
| **URL** | https://www.ft.com/ (free registration required for RSS) |
| **Type** | RSS (custom topic feeds via myFT) |
| **Country** | UK/EU |
| **Update Freq** | Daily |
| **Reliability** | High -- premier financial newspaper |
| **Language** | EN |
| **Notes** | Free tier: 20 articles/month after registration. myFT allows building custom RSS feeds on EU/business topics. FT Alphaville (markets blog) is ENTIRELY FREE with registration -- unlimited articles, no paywall. |

| Field | Value |
|---|---|
| **Name** | Reuters -- Legacy RSS Feeds (may be discontinued) |
| **URL** | http://feeds.reuters.com/reuters/businessNews |
| **Type** | RSS (legacy, status unknown) |
| **Country** | UK/Global |
| **Update Freq** | Daily |
| **Reliability** | High (but feed may be non-functional -- test first) |
| **Language** | EN |
| **Notes** | Reuters discontinued public RSS. These URLs from the archived 2018 catalog may or may not work. No dedicated Europe/EU feed ever existed. Test before relying on it. |
| **Status** | VERIFY BEFORE USE |

---

## Gap 3: Emerging Markets -- Medium Priority

### 3.1 Major EM Central Bank Decisions

#### Brazil -- Banco Central do Brasil (BCB)

| Field | Value |
|---|---|
| **Name** | BCB -- English RSS Feeds |
| **URL** | https://www.bcb.gov.br/api/feed/sitebcb/sitefeedsen/ |
| **Type** | RSS (structured API endpoint) |
| **Country** | BR |
| **Update Freq** | Every 6 weeks (COPOM rate decisions), weekly (other releases) |
| **Reliability** | Official -- central bank |
| **Language** | EN |
| **Notes** | Base URL for all English RSS feeds. Known feed: /financialstabilityreport. Likely also feeds for: press releases, COPOM minutes, inflation reports. Visit main site https://www.bcb.gov.br/en for full feed directory. Key: Selic rate currently 15.00% (tightening cycle paused 2025). |

#### India -- Reserve Bank of India (RBI)

| Field | Value |
|---|---|
| **Name** | RBI -- Press Releases RSS |
| **URL** | https://www.rbi.org.in/Scripts/Rss.aspx?Id=200 |
| **Type** | RSS |
| **Country** | IN |
| **Update Freq** | Daily to bi-monthly (MPC decisions: Feb, Apr, Jun, Aug, Oct, Dec) |
| **Reliability** | Official -- central bank |
| **Language** | EN |
| **Notes** | RSS info page: https://www.rbi.org.in/Scripts/Rss.aspx. Covers: MPC resolutions, liquidity measures, data releases (forex reserves, money supply, BoP), regulatory actions. Legacy ASP.NET site. New Liferay site also exists at website.rbi.org.in. |

#### Turkey -- TCMB (Central Bank of Republic of Turkey)

| Field | Value |
|---|---|
| **Name** | TCMB -- Press Releases RSS (English) |
| **URL** | https://tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Bottom+Menu/Other/RSS/Press+Releases |
| **Type** | RSS |
| **Country** | TR |
| **Update Freq** | Every 6 weeks (MPC decisions: 8 meetings/year), ad hoc |
| **Reliability** | Official -- central bank |
| **Language** | EN |
| **Notes** | Also: MPC-only decisions RSS at .../RSS/MPC+Decisions. Publications RSS at .../RSS/Publications. 2025 press releases index page: https://www.tcmb.gov.tr/wps/wcm/connect/en/tcmb+en/main+menu/announcements/press+releases/2025/. |

#### Chile -- Banco Central de Chile

| Field | Value |
|---|---|
| **Name** | Banco Central de Chile -- Monetary Policy Press Releases |
| **URL** | https://www.bcentral.cl/en/web/banco-central/areas/monetary-politics/monetary-policy-meeting-rpm |
| **Type** | Web (no confirmed RSS; Liferay platform may offer hidden RSS) |
| **Country** | CL |
| **Update Freq** | 8 meetings/year (Jan, Mar, Apr, Jun, Jul, Sep, Oct, Dec) |
| **Reliability** | Official -- central bank |
| **Language** | EN |
| **Notes** | English RPM press releases consistently published. Minutes follow ~6 working days after each decision. No confirmed RSS URL -- try appending /rss to news listing page. Current rate: 4.50% (held steady as of Apr 2026). |

#### South Africa -- SARB

| Field | Value |
|---|---|
| **Name** | SARB -- RSS Feeds |
| **URL** | https://www.resbank.co.za/en/home/quick-links/rss-feeds |
| **Type** | RSS |
| **Country** | ZA |
| **Update Freq** | Bi-monthly (MPC: Jan, Mar, May, Jul, Sep, Nov) |
| **Reliability** | Official -- central bank |
| **Language** | EN |
| **Notes** | RSS feeds available; click "Subscribe" to reveal feed URLs. MPC statements also published at https://www.resbank.co.za/en/home/what-we-do/monetary-policy/monetary-policy-committee. Newsroom: resbank.co.za/en/home/newsroom. |

#### Saudi Arabia -- SAMA

| Field | Value |
|---|---|
| **Name** | SAMA -- Official News Page |
| **URL** | https://www.sama.gov.sa/en-US/News/ |
| **Type** | Web (no RSS confirmed) |
| **Country** | SA |
| **Update Freq** | Ad hoc (rate decisions follow US Fed, ~8 times/year) |
| **Reliability** | Official -- central bank |
| **Language** | EN |
| **Notes** | No RSS feed found. SAMA announcements also published via Saudi Press Agency (https://www.spa.gov.sa/en/) and Saudi Gazette (https://saudigazette.com.sa/tags/SAMA). Rate decisions typically mirror Fed moves due to USD peg. |

### 3.2 EM Capital Flow Indicators

| Field | Value |
|---|---|
| **Name** | IIF Capital Flows Tracker (free headlines only) |
| **URL** | https://www.iif.com/Products/Capital-Flows-Tracker |
| **Type** | Web (headline data free; full data requires institutional membership) |
| **Country** | Global |
| **Update Freq** | Monthly (end of each month) |
| **Reliability** | High -- industry standard for EM flows |
| **Language** | EN |
| **Notes** | PUBLIC: monthly headline EM portfolio flow numbers (equity + debt). PRIVATE: full Excel data, daily/weekly breakdowns. Free alternative: IMF Balance of Payments data (lags ~3-6 months). |

| Field | Value |
|---|---|
| **Name** | World Bank Open Data API -- Development Indicators |
| **URL** | https://api.worldbank.org/v2/ |
| **Type** | REST API (free, no key, JSON/XML) |
| **Country** | Global |
| **Update Freq** | Annual (some quarterly; data lags 1-2 years behind) |
| **Reliability** | Official -- multilateral institution |
| **Language** | EN |
| **Notes** | 200+ countries, 7,000-17,000+ indicators. Key EM indicators: GDP growth (NY.GDP.MKTP.KD.ZG), FDI (BX.KLT.DINV.WD.GD.ZS), external debt (DT.DOD.DECT.CD), current account (BN.CAB.XOKA.GD.ZS). No real-time data. Best for structural EM analysis, not tactical trading. |

| Field | Value |
|---|---|
| **Name** | IMF -- Press Releases & WEO RSS |
| **URL** | https://www.imf.org/en/News/RSS |
| **Type** | RSS |
| **Country** | Global |
| **Update Freq** | Weekly (press releases), semi-annual (WEO: Apr + Oct) |
| **Reliability** | Official -- multilateral institution |
| **Language** | EN |
| **Notes** | WEO database: https://www.imf.org/en/Publications/WEO. IMF Data portal: https://data.imf.org/. RSS available for: press releases, country reports, working papers, WEO updates. WEO Oct 2025: global growth 3.2% (2025), 3.1% (2026). |

| Field | Value |
|---|---|
| **Name** | SAFE -- China Cross-Border Capital Flows |
| **URL** | https://www.safe.gov.cn/en/SAFENews/index_5.html |
| **Type** | Web (monthly data releases) |
| **Country** | CN |
| **Update Freq** | Monthly |
| **Reliability** | Official |
| **Language** | EN |
| **Notes** | Key data: monthly bank FX settlement/sales, cross-border receipts/payments by non-bank sectors, net capital flows (inflow/outflow). Includes foreign holdings of domestic stocks/bonds. Q3 2025: net cross-border capital inflow USD 119.7B. |

### 3.3 Commodity-Exporting Country Data

#### Chile -- Copper

| Field | Value |
|---|---|
| **Name** | Cochilco -- Chilean Copper Commission |
| **URL** | https://www.cochilco.cl/ |
| **Type** | Web (monthly bulletin, annual yearbook; no RSS) |
| **Country** | CL |
| **Update Freq** | Monthly (production/export data, ~10th-15th of each month) |
| **Reliability** | Official -- government copper commission |
| **Language** | ES (some EN) |
| **Notes** | Monthly bulletin: https://boletin.cochilco.cl/. Covers: copper production by mine/company (Codelco, Escondida, Collahuasi), copper exports (refined, concentrate, by-products), price forecasts, supply/demand balance. All data free. Annual yearbook covers 20 years. |
| **Alt** | FINDIC API (https://findic.cl/) -- Chile copper price (USD/lb), exchange rate, IPSA index. RESTful, free tier available. |

#### Saudi Arabia -- Oil / OPEC

| Field | Value |
|---|---|
| **Name** | OPEC -- Monthly Oil Market Report (MOMR) |
| **URL** | https://publications.opec.org/ |
| **Type** | Web + iOS/Android App (free; no RSS feed) |
| **Country** | Global (Saudi Arabia as key member) |
| **Update Freq** | Monthly (2nd week of each month) |
| **Reliability** | Official -- OPEC Secretariat |
| **Language** | EN |
| **Notes** | MOMR contains: Saudi crude production (primary + secondary sources), OPEC+ quota compliance, global supply/demand balance, oil price analysis. Free mobile apps available. No RSS. Oct 2025: Saudi production 10.003 mbpd (breached 10 mbpd). |

| Field | Value |
|---|---|
| **Name** | Argaam -- Saudi Financial News (English) |
| **URL** | https://www.argaam.com/en/ |
| **Type** | Web |
| **Country** | SA |
| **Update Freq** | Daily |
| **Reliability** | Medium-High -- major Saudi financial portal |
| **Language** | EN |
| **Notes** | Covers: SAMA rate decisions, Saudi fiscal policy, Tadawul market, oil policy signals. Useful supplement when SAMA official page lacks RSS. |

---

## Summary: Quick Reference Table

| Gap | Best Free Source | Type | Key Strength |
|-----|-----------------|------|-------------|
| China PBOC | pbc.gov.cn/en/ (web) | Web | Official, daily ops + policy |
| China Caixin | gateway.caixin.com/.../feedlyRss.xml | RSS | Independent financial journalism |
| China A-shares/Northbound | AKShare (ak.stock_hsgt_hist_em) | Python API | Free, comprehensive, but post-Aug-2024 data limited |
| China Macro Data | AKShare (CPI/PMI/GDP functions) | Python API | Free, reliable, NBS-sourced |
| China Business News | China Daily Bizchina RSS | RSS | Daily, free, EN |
| EU ECB | ecb.europa.eu/rss/press.html | RSS | Official, multiple feeds |
| EU Antitrust | competition-policy.ec.europa.eu/antitrust/rss_en | RSS | Official DG COMP |
| EU Economic Data | ec.europa.eu/eurostat (RSS available) | RSS | Official EU statistics |
| EU Markets | Euronews Business RSS | RSS | Free, daily narrative |
| EM Brazil | bcb.gov.br/api/feed/sitebcb/sitefeedsen/ | RSS | Official, EN |
| EM India | rbi.org.in/Scripts/Rss.aspx?Id=200 | RSS | Official, reliable |
| EM Turkey | tcmb.gov.tr/.../RSS/Press+Releases | RSS | Official, EN |
| EM Chile (Copper) | cochilco.cl / boletin.cochilco.cl | Web | Official, free monthly data |
| EM Saudi (Oil) | publications.opec.org (MOMR) | Web | Official OPEC, monthly |
| EM Capital Flows | IIF Tracker (headlines free) | Web | Industry standard, monthly |
| EM Development | World Bank API (api.worldbank.org/v2/) | REST API | Free, no key, 7,000+ indicators |

---

## Important Caveats

1. **No RSS = Still Usable**: Several official sources (PBOC, SAFE, Cochilco, SAMA, OPEC) do NOT provide RSS feeds. They are still valuable but require web scraping, change-detection tools (changedetection.io, Visualping), or manual monitoring.

2. **Verified vs Unverified**: URLs marked "VERIFY BEFORE USE" (Reuters legacy feeds) should be tested before integration.

3. **Language**: Sources marked EN are available in English. ES sources (Cochilco) may require translation. AKShare function names/parameters are in English but data labels are often Chinese.

4. **Northbound Flow Data Limitation**: China's Aug 2024 disclosure reform makes real-time northbound flow data unavailable. Only post-close daily totals are available. This is a structural limitation, not a source gap.

5. **Trading Economics**: No free API tier. Free developer account limited to World Bank/UN/EUROSTAT public datasets only. Not recommended as a free source for MarketMind.

6. **RSSHub**: The community-maintained RSSHub project (https://github.com/DIYgod/RSSHub) can generate RSS feeds for many sources that lack official ones. Key routes: /caixinglobal/latest, /scmp/:category_id, /caixin/latest, /caixin/:column/:category. Self-host or use public instances (e.g., rsshub.app).

---

**Research completed**: 2026-05-17
**Next step**: Integrate verified sources into MarketMind scout.py / archivist.py ingestion pipeline.
