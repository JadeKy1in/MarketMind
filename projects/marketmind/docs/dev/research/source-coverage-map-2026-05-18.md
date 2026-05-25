# Source Coverage Map — 2026-05-18

**Engineer**: Data Engineer
**Purpose**: Map all 25 sources against Robinhood asset universe, identify coverage gaps.
**Updated**: 2026-05-18 19:30 UTC

---

## 1. Source Inventory — All 25 Sources

### PRIMARY Tier (10 sources)

| # | Source | Type | Quality | Region | Focus | Asset Classes Covered |
|---|--------|------|---------|--------|-------|----------------------|
| 1 | **FRED** | RSS blog + API | FULL_CONTENT | US | Macro data (BDI via PPI proxy), research context. API in `macro_data.py`. | US macro, treasuries, all USD-denominated |
| 2 | **BLS** | API (bls_fetcher) | DATA_API | US | CPI, Core CPI, Unemployment (3/4 indicators). PPI no data. | Inflation, rates, USD, all US assets |
| 3 | **SEC EDGAR** | Atom feed | PARTIAL (127 chars) | US | Corporate filings, insider transactions | US equities (AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, JPM, XOM) |
| 4 | **Federal Reserve** | RSS | FULL_CONTENT | US | Monetary policy, FOMC, banking regulation | US treasuries (TLT), rates, USD, all US assets |
| 5 | **CFTC COT** | API (macro_data) | DATA_API | US | Futures positioning: ES, CL, GC, NG | Equities (SPY), Oil (USO), Gold (GLD), Nat Gas (UNG) |
| 6 | **ECB Press Releases** | RSS | **HEADLINES_ONLY** | EU | Monetary policy decisions, speeches. 15 entries, ZERO description fields. | EUR, EU bonds, European equities |
| 7 | **ECB Publications** | RSS | FULL_CONTENT (865c) | EU | Economic Bulletin, Financial Stability Review, research | EU macro context, EUR |
| 8 | **EC Press Corner** | RSS | FULL_CONTENT | EU | European Commission policy, press releases. NOT ECB (different institution). | EU equities, EUR (indirect) |
| 9 | **Brazil BCB Copom** | RSS | FULL_CONTENT (5128c) | Brazil | Copom monetary policy statements | EM (EEM), Brazilian assets |
| 10 | **India RBI Press Releases** | RSS | FULL_CONTENT (1697c) | India | MPC statements, monetary policy, regulatory | EM (EEM), Indian assets |

### RELIABLE Tier (9 sources)

| # | Source | Type | Quality | Region | Focus | Asset Classes Covered |
|---|--------|------|---------|--------|-------|----------------------|
| 11 | **NewsAPI** | Paid API | FULL_CONTENT | US/Global | Top business headlines (US, category=business) | All US equities, ETFs, crypto |
| 12 | **GNews** | Paid API | FULL_CONTENT | US/Global | Top business headlines (US, category=business) | All US equities, ETFs, crypto |
| 13 | **MarketWatch** | RSS | FULL_CONTENT | US | Financial markets, Dow Jones | US equities, bonds, commodities, crypto |
| 14 | **China Daily Bizchina** | RSS | FULL_CONTENT (315c) | China | Business, finance, economy | China equities, EM (EEM) |
| 15 | **CGTN Business** | RSS | FULL_CONTENT (264c) | China | Business news | China equities, EM (EEM) |
| 16 | **SCMP Business** | RSS | FULL_CONTENT (502c) | China/Asia | Business, finance, Asia markets | China/Asia equities, EM (EEM) |
| 17 | **Financial Times** | RSS | FULL_CONTENT (121c) | Global | World news (paywall may truncate) | All global assets |
| 18 | **Euronews Business** | RSS (MRSS) | FULL_CONTENT (214c) | EU | Business, economy, European markets | EU equities, EUR |
| 19 | **CoinTelegraph** | RSS | FULL_CONTENT (133c) | Global | Crypto, blockchain, regulation | BTC-USD, crypto |

### FRAGILE Tier (3 sources)

| # | Source | Type | Quality | Region | Focus | Asset Classes Covered |
|---|--------|------|---------|--------|-------|----------------------|
| 20 | **Nikkei Asia** | GNews proxy | **HEADLINES_ONLY** | Japan | Japan business, markets, economy. 84 entries. | Japan equities (no direct ETF in universe) |
| 21 | **Xinhua English** | RSS | FULL_CONTENT (202c) | China/Global | World news from Chinese state media | China equities, EM (EEM), global macro |
| 22 | **EUobserver** | RSS | FULL_CONTENT (325c) | EU | EU politics, policy, institutional news | EU equities, EUR (indirect) |

### BEST_EFFORT Tier (3 sources)

| # | Source | Type | Quality | Region | Focus | Asset Classes Covered |
|---|--------|------|---------|--------|-------|----------------------|
| 23 | **South Africa SARB** | GNews proxy | **HEADLINES_ONLY** | South Africa | SARB monetary policy, repo rate | EM (EEM), ZAR |
| 24 | **OPEC Oil** | GNews proxy | **HEADLINES_ONLY** | Global | OPEC production quotas, oil policy | Oil (USO), Energy (XLE), Crude (CL) |
| 25 | **Bluesky** | AT Protocol API | FULL_CONTENT | Global | Social media, keyword-driven, varied topics | Any (keyword-configured) |

---

## 2. Content Quality Summary

| Quality | Count | Sources |
|---------|:---:|------|
| FULL_CONTENT (real article text) | 19 | FRED, Fed, ECB Publications, EC Press Corner, Brazil BCB, RBI, NewsAPI, GNews, MarketWatch, China Daily, CGTN, SCMP, FT, Euronews Business, CoinTelegraph, Xinhua, EUobserver, Bluesky |
| DATA_API (numeric data, not articles) | 2 | BLS, CFTC COT |
| PARTIAL (brief but usable) | 1 | SEC EDGAR |
| HEADLINES_ONLY (titles only, zero content) | 3 | **ECB Press Releases**, Nikkei Asia, SARB, OPEC Oil |

---

## 3. Coverage Map — By Region

| Region | Sources | Strength | Gap? |
|--------|---------|----------|:---:|
| **United States** | FRED, BLS, SEC EDGAR, Federal Reserve, CFTC COT, MarketWatch, NewsAPI, GNews | Strong — 8 sources, 2 data APIs, full institutional + market coverage | None |
| **European Union** | ECB Press Releases (HEADLINES), ECB Publications, EC Press Corner, Euronews Business, EUobserver, FT | Moderate — ECB decisions are HEADLINES_ONLY. Euronews had 0 ECB articles in last 50. | **ECB monetary policy content gap** |
| **China** | China Daily, CGTN, SCMP, Xinhua | Strong — 4 direct RSS with FULL_CONTENT | None |
| **Japan** | Nikkei Asia (HEADLINES_ONLY) | Weak — single source, titles only | **No FULL_CONTENT Japan source** |
| **India** | India RBI Press Releases | Strong — official central bank RSS with 1700+ char content | None |
| **Brazil** | Brazil BCB Copom | Strong — official central bank RSS with rich content | None |
| **South Africa / Africa** | South Africa SARB (HEADLINES_ONLY) | Weak — single source, titles only | **No dedicated Africa EM source** |
| **Global / Multi-region** | FT, CoinTelegraph, Bluesky, OPEC Oil (HEADLINES) | Moderate — general coverage, crypto has dedicated source | None |

---

## 4. Coverage Map — By Asset Class (Robinhood Tradable)

| Asset Class | Examples in Universe | Sources Covering | Gap? |
|-------------|---------------------|------------------|:---:|
| **US Equities (Broad)** | SPY, QQQ, IWM, DIA | Fed, SEC EDGAR, CFTC COT, MarketWatch, NewsAPI, GNews, FT | None |
| **US Technology** | XLK, AAPL, MSFT, NVDA, GOOGL, META | SEC EDGAR, MarketWatch, NewsAPI, GNews, FT | None |
| **US Financials** | XLF, JPM | Fed, SEC EDGAR, CFTC COT, MarketWatch, NewsAPI, GNews, FT | None |
| **US Energy** | XLE, XOM, USO, UNG | CFTC COT (CL, NG positioning), OPEC Oil (HEADLINES), EIA (data, not in source list), MarketWatch, general news | **Weak** — no dedicated energy news with FULL_CONTENT. OPEC is headlines-only. |
| **US Healthcare** | XLV | SEC EDGAR, MarketWatch, general news | **Weak** — no dedicated healthcare source |
| **US Consumer** | AMZN, TSLA | SEC EDGAR, MarketWatch, general news | **Weak** — no dedicated consumer/retail source |
| **US Treasuries** | TLT | Fed, FRED (data), CFTC COT, MarketWatch, FT | None |
| **Precious Metals** | GLD, SLV | CFTC COT (GC), MarketWatch, general news | **Moderate** — CFTC gives positioning data, but no dedicated metals news source |
| **Agriculture** | DBA | General news only (MarketWatch, NewsAPI, GNews) | **Weak** — no dedicated ag commodity source. CFTC COT doesn't cover ag. |
| **Emerging Markets** | EEM | Brazil BCB, India RBI, SARB (HEADLINES), China sources (4), SCMP | **Moderate** — BRICS covered, but no Korea/Mexico/Indonesia/Turkey/Vietnam |
| **Crypto** | BTC-USD | CoinTelegraph, Bluesky | None — dedicated crypto source with FULL_CONTENT |
| **EU Equities** | (no direct ETF but macro-critical) | ECB (HEADLINES), ECB Publications, EC Press Corner, Euronews Business, EUobserver | **Moderate** — ECB monetary policy is HEADLINES_ONLY |

---

## 5. ECB Coverage Gap — Detailed Analysis

### Problem

ECB Press Releases (`rss/press.html`) is a PRIMARY-tier source that returns **zero content**. The RSS XML has no `<description>` field at all — structurally absent, not just empty. Entry keys are only: `title`, `link`, `published`.

### What's Not Covered

ECB Press Releases RSS is the ONLY source that directly reports ECB monetary policy decisions (rate changes, QE/PEPP/APP announcements, forward guidance changes). Neither of our two EU news sources currently fills this gap:

- **Euronews Business**: 0 of 50 recent entries mention ECB, central banks, or interest rates. It's a general EU business feed (companies, trade, sector news).
- **Financial Times**: 0 of 25 current RSS entries mention ECB. FT's world feed has rotating coverage.
- **EC Press Corner**: Covers European **Commission** (EU executive), NOT the ECB. Different institution.
- **ECB Publications**: Covers research (Economic Bulletin, Financial Stability Review), NOT rate decisions.

### What Does Work

1. **ECB Press Releases titles** still tell us WHEN a decision is announced. Example: "Monetary policy decisions" title + link to full HTML page.
2. **Each ECB entry has a direct link** to the full HTML press release at `ecb.europa.eu/press/...`. E.g., `https://www.ecb.europa.eu/press/key/date/2026/html/ecb.sp260513_1~ab5ae9e754.en.html`
3. **NewsAPI / GNews** aggregate third-party coverage of ECB decisions from Reuters, Bloomberg, AP, etc. (in the 24-hour window after a decision).

### Recommendation

**Option A (Accept + supplement)**: Keep ECB Press Releases as-is for topic detection (titles + links). Recognize that third-party coverage (NewsAPI, GNews) fills the content gap within 24 hours of ECB decisions. ECB decisions happen every 6 weeks — the gap is during the window between ECB publication and third-party pickup (~hours).

**Option B (Lightweight HTML scraper)**: Add a small function in `pipeline/scout.py` that, when processing ECB Press Releases entries, fetches the linked HTML page and extracts the first 3-5 paragraphs as summary text. ECB press release pages follow a predictable structure (headline + dateline + body paragraphs in `<main>` or `<article>` tags). This is ~30 lines of code.

**Option C (Google News ECB proxy — re-add)**: Re-add a Google News proxy specifically for ECB: `"ECB+monetary+policy+rate+decision+Lagarde"`. We removed the ECB GNews proxy in the cleanup, but this one search query has unique value.

**Recommendation**: Option B (HTML scraper) for primary coverage + keep NewsAPI/GNews as fallback. The ECB publishes predictably (~8 times/year) so scraping load is negligible.

---

## 6. Coverage Gaps — Full List

### Critical Gaps (PRIMARY sources with zero content)

| Gap | Impact | Recommendation |
|-----|--------|---------------|
| **ECB monetary policy decisions** | PRIMARY source returns zero content. No dedicated EU rate-decision news. | Build lightweight HTML scraper for ECB press release pages (Option B above) |

### Significant Gaps (no dedicated source, asset in universe)

| Asset Class | Current Coverage | Recommendation |
|-------------|-----------------|---------------|
| **Japan equities/markets** | Nikkei Asia is HEADLINES_ONLY only | Research Nikkei Asia direct RSS (their RSS page exists at `info.asia.nikkei.com/rss` but exact feed URL not found). Alternatively add a Japan-specific Google News proxy. |
| **Energy/Oil news** | OPEC Oil is HEADLINES_ONLY. EIA data is API, not news. CFTC COT is positioning data, not news. | No OPEC RSS exists. Accept headlines from Google News proxy. EIA + CFTC provide strong data foundation. |
| **Precious Metals news** | CFTC COT (GC) gives positioning data. MarketWatch covers broadly. | Accept — CFTC data + MarketWatch provides sufficient coverage. Gold is widely covered in general financial news. |
| **Agriculture commodities** | No dedicated source. DBA is in asset universe. | Low priority — agriculture is a small part of the universe (1 ETF). General news covers major crop reports. |

### Minor Gaps (sector-specific, not macro-critical)

| Gap | Impact | Recommendation |
|-----|--------|---------------|
| **Healthcare sector** | No dedicated source for XLV | Low priority — sector ETF coverage from general financial news is sufficient |
| **Consumer/Retail** | No dedicated source for AMZN/TSLA news | Not needed — individual stock news covered by SEC EDGAR + general financial sources |
| **Emerging Markets (non-BRICS)** | No Korea, Mexico, Indonesia, Turkey sources | Low priority — EEM is broad EM, BRICS coverage from RBI + BCB + China sources provides good signal |

### Structural Gaps (HEADLINES_ONLY sources in the list)

| Source | Tier | Impact |
|--------|------|--------|
| **ECB Press Releases** | PRIMARY | ECB rate decisions have no direct content. Covered by third-party (NewsAPI/GNews) within hours. |
| **Nikkei Asia** | FRAGILE | Only Japan source, titles only. Japan is the 3rd largest economy. |
| **South Africa SARB** | BEST_EFFORT | Only Africa EM source, titles only. SARB has no direct RSS. |
| **OPEC Oil** | BEST_EFFORT | Oil is market-critical. OPEC has no RSS. Google News proxy is the only programmatic source. |

---

## 7. Overall Assessment

| Metric | Value |
|--------|:---:|
| **Total sources** | 25 |
| **FULL_CONTENT** | 19 |
| **DATA_API** (numeric data) | 2 |
| **PARTIAL** (usable) | 1 |
| **HEADLINES_ONLY** (zero content) | 3 |
| **Robinhood asset classes with STRONG coverage** | 7 (US equities, US tech, US financials, US treasuries, crypto, China equities, EM-BRICS) |
| **Robinhood asset classes with MODERATE coverage** | 4 (US energy, precious metals, emerging markets, EU macro) |
| **Robinhood asset classes with WEAK coverage** | 4 (US healthcare, US consumer, agriculture, Japan) |
| **Critical gaps requiring action** | 1 (ECB monetary policy decisions) |
| **Significant gaps** | 2 (Japan equities, energy/oil news) |
| **Regions with zero dedicated sources** | 5 (Japan, Africa ex-SA, Middle East, Southeast Asia, Latin America ex-Brazil) |

---

## 8. Regional Coverage Heatmap

```
Region          | Dedicated Sources | Quality
----------------|-------------------|--------
United States   | ████████ (8)      | STRONG
China           | ████ (4)          | STRONG
European Union  | █████ (5)         | MODERATE (ECB gap)
India           | █ (1)             | STRONG (official RBI)
Brazil          | █ (1)             | STRONG (official BCB)
Japan           | ░ (1)             | WEAK (headlines only)
South Africa    | ░ (1)             | WEAK (headlines only)
Global/Other    | ███ (3)           | MODERATE
Korea           |                   | NONE
Mexico          |                   | NONE
Indonesia       |                   | NONE
Turkey          |                   | NONE
Southeast Asia  |                   | NONE
Middle East     |                   | NONE
```

---

**Updated**: 2026-05-18 19:30 UTC
