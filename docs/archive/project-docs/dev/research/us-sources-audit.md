# US-Centric Information Sources Audit — MarketMind

**Audit date**: 2026-05-17
**Auditor**: AI analysis of production code (pipeline/, gateway/, config/, tests/)
**Scope**: All 16 US-focused information sources across Layers 1, 3, 4, 5

---

## Methodology

Each source is evaluated against four criteria:
1. **Uniqueness** — Does it provide data no other source provides?
2. **Timeliness** — Is the data fresh enough for trading decisions?
3. **Signal value** — How actionable is the output for investment analysis?
4. **Redundancy** — Is there overlap with another active source?

Findings are grounded in the actual implementation code (not documentation or plans):
- `pipeline/scout.py` — RSS/API news fetching
- `pipeline/l1_tools.py` — L1 tool registry (8 tools, rate caps)
- `pipeline/l1_market_tools.py` — macro/CoT/EIA tool implementations
- `pipeline/l1_info_tools.py` — news search, economic calendar
- `pipeline/insider_sources.py` — Form 4, 13F, Congress trades
- `pipeline/economic_calendar.py` — FOMC + FRED release calendar
- `gateway/market_data.py` — yfinance + Finnhub + Binance
- `gateway/macro_data.py` — FRED API, CFTC SODA, EIA API
- `config/source_authority.py` — Source tier definitions and health states
- `config/settings.py` — API key configuration

---

## Per-Source Evaluation

### Layer 1 — News RSS/API (Sources 1-9)

#### 1. FRED (St. Louis Fed Research blog) — PRIMARY, 0.99

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | Moderate. The blog provides narrative context around FRED economic data, but all underlying data is available via the FRED API (#15). |
| **Timeliness** | Low. Research blog posts are published on the St. Louis Fed's editorial schedule (irregular, often weeks apart). Not a real-time or daily feed. |
| **Signal value** | Low-Medium. Academic/analytical in nature. Rarely contains time-sensitive market-moving insight. |
| **Redundancy** | **Partial overlap with FRED API (#15).** The RSS is the narrative wrapper; the API is the raw data. Different content types but same institution. |

**Verdict**: KEEP, but demote to RELIABLE tier. The blog provides interpretative commentary that raw FRED data lacks. However, at 0.99 reliability with PRIMARY tier, it is overrated — research blogs are not institutional data feeds.

---

#### 2. BLS (Bureau of Labor Statistics API) — PRIMARY, 0.99

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | High in theory. BLS provides CPI, employment, PPI, wages — data no other free source offers with this authority. |
| **Timeliness** | N/A. |
| **Signal value** | High (CPI, NFP are market-moving releases). |
| **Redundancy** | No overlap. |
| **Implementation status** | **NOT IMPLEMENTED.** The source is listed as UNTESTED with `feed_type="bls_api"`. The source health check tool explicitly skips it: `"SKIPPED (BLS API — implementation TBD)"` (source_health_check.py:193). The `source_authority.py` comment on line 48 says: "Implementation TBD — macro_data.py or dedicated pipeline/bls_fetcher.py." Zero code fetches BLS data. |

**Verdict**: BOOST priority. This is the single highest-value unimplemented source in the entire system. CPI, NFP, PPI, and wage data are market-moving releases. The BLS Public Data API v2 is free and requires only optional registration to increase daily quota from 25 to 500 calls. This should be implemented as a dedicated `pipeline/bls_fetcher.py` module OR added to `gateway/macro_data.py`.

---

#### 3. SEC EDGAR (SEC filings feed) — PRIMARY, 0.99

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | High. Official SEC filings are the authoritative source for corporate disclosures (8-K, 10-K, 10-Q, 8-K). |
| **Timeliness** | Medium. Filings appear within minutes of submission to EDGAR. |
| **Signal value** | High. 8-K filings contain material events, 10-K/Q contain financial statements. |
| **Redundancy** | **Overlaps with Form 4 (#12) and 13F (#13)** — both also use EDGAR Atom feeds but hit different endpoints (type=4 and type=13F-HR instead of the default feed). These are NOT redundant; they provide distinct data. |

**Verdict**: KEEP at PRIMARY. The EDGAR feed is the authoritative pipeline for all SEC filings. The Form 4 and 13F implementations in `insider_sources.py` are specialized consumers of the same EDGAR infrastructure, not duplicates.

---

#### 4. Federal Reserve (Press releases) — PRIMARY, 0.99

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | High. Federal Reserve press releases are the authoritative source for FOMC statements, monetary policy decisions, and regulatory changes. |
| **Timeliness** | High on release days. FOMC statements are released at 2:00 PM ET on meeting days. |
| **Signal value** | Very High. FOMC statements are the single most market-moving regular event. |
| **Redundancy** | **Low overlap with FRED API (#15) and FRED RSS (#1).** FRED is economic data; Fed RSS is policy narrative. FRED API provides data series; Fed press releases provide the *interpretation* (forward guidance, dot plots, statement language). These are complementary, not redundant. However, there is **mild overlap with FOMC hardcoded dates in economic_calendar.py** — that module already tracks FOMC dates mechanically. |

**Verdict**: KEEP at PRIMARY. The Fed press release feed is irreplaceable for monetary policy coverage. The RSS URL (`press_all.xml`) is confirmed working in VCR fixtures.

---

#### 5. CFTC COT (Commitments of Traders) — PRIMARY, 0.99

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | Very High. No other free source provides institutional/speculative futures positioning data. |
| **Timeliness** | Weekly (released Friday 3:30 PM ET, data through Tuesday). Sufficient for medium-term positioning analysis. |
| **Signal value** | Medium-High. COT data reveals structural positioning shifts that news cannot capture. Contrarian signals at extremes (speculator crowding). |
| **Redundancy** | None. Unique data source. |

**Verdict**: KEEP at PRIMARY. The COT data is unique, free, and provides a dimension of analysis (positioning) that no other source offers. Well-implemented in `gateway/macro_data.py` via the SODA API with contrarian signal logic.

**Note**: The source_authority.py entry for CFTC COT uses `feed_type="api"` and the old text-file URL, but the actual implementation uses the SODA JSON API. The health check tool correctly delegates it: `"SKIPPED (handled by macro_data.py)"`. The source_authority entry should be updated to reflect the SODA API URL.

---

#### 6. NewsAPI (80K+ source aggregator) — RELIABLE, 0.90

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | Low. Aggregates 80K+ sources globally. GNews (#7) covers ~60K sources with significant overlap. |
| **Timeliness** | Good. Top-headlines endpoint refreshed in near-real-time. |
| **Signal value** | Medium. Broad coverage dilutes signal. The `top-headlines?country=us&category=business` query is generic — no topic filtering. |
| **Redundancy** | **High overlap with GNews (#7).** Both are global news aggregators covering US business headlines. GNews provides the same signal at lower cost. |
| **Cost** | $450/mo for Business tier (necessary for >100 requests/day). Developer tier is only 100 req/day. |

**Verdict**: **REMOVE.** This is the highest-cost source with the lowest marginal value. GNews (#7) provides equivalent coverage at a fraction of the cost. The `_fetch_newsapi()` and `_fetch_gnews()` implementations in scout.py are nearly identical in structure — both fetch top business headlines, parse JSON, and return NewsItem lists. The deduplication logic in `deduplicate()` already handles overlap. Removing NewsAPI saves $450/mo with zero loss of unique information.

**Migration path**: Remove `_fetch_newsapi()` from scout.py, remove `newsapi_key` from MarketMindConfig, and remove the NewsAPI entry from SOURCES list. No other code depends on NewsAPI — it is only fetched as one source among many in `fetch_all_sources()`.

---

#### 7. GNews (News aggregator) — RELIABLE, 0.85

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | Moderate. Covers ~60K sources globally. Overlaps with NewsAPI but has different source mix (stronger international coverage). |
| **Timeliness** | Good. Top-headlines endpoint refreshed near-real-time. |
| **Signal value** | Medium. Same generic `category=business&country=us` query as NewsAPI. |
| **Redundancy** | **High overlap with NewsAPI (#6).** But GNews is cheaper and has additional utility: it is also used as the `search_news` tool in l1_tools.py for topic-specific queries. |
| **Dual purpose** | GNews serves TWO roles: (1) top-headlines in scout.py, (2) topic-specific search via `_tool_search_news()` in l1_info_tools.py. The search tool is capped at 10 calls/session to stay within the 100/day free quota. |

**Verdict**: KEEP as the SOLE news aggregator. After removing NewsAPI, GNews becomes the only general news source. Consider upgrading to a paid GNews plan to increase the daily quota if 100/day becomes constraining.

---

#### 8. MarketWatch (Dow Jones) — RELIABLE, 0.80

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | Low. MarketWatch republishes Dow Jones content that also appears on WSJ, Barron's, and other Dow Jones properties. Much of this content is paywalled at the destination URL. |
| **Timeliness** | Good. RSS feed updated throughout the trading day. |
| **Signal value** | Low-Medium. MarketWatch content is largely consumer-oriented financial journalism — personal finance advice, market summaries, trending stories. VCR fixture analysis shows the feed contains articles like "think robocalls are annoying?", "all-you-can-eat deals at restaurants", "can't afford to buy a new fridge?" — these are NOT investment signals. |
| **Redundancy** | **High overlap with GNews (#7).** GNews aggregates MarketWatch content among its 60K sources. Any MarketWatch article of genuine market significance appears in GNews results. |
| **Cost** | Free (RSS). |

**Verdict**: **REMOVE.** The RSS feed has extremely low signal-to-noise ratio for investment analysis. VCR fixture confirms the feed is predominantly lifestyle/personal-finance content, not market-moving news. Any MarketWatch article of analytic value will appear through GNews aggregation. The RSS is free, so there is no cost savings, but removing it reduces noise in the deduplication pipeline.

---

#### 9. Investing.com — RELIABLE, 0.75

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | Low. Global financial news with heavy forex/crypto/commodities focus. |
| **Timeliness** | Moderate. RSS feed lags real-time by minutes to hours. |
| **Signal value** | Low. VCR fixture analysis shows the feed is dominated by earnings call transcripts, not original analysis. The RSS URL (`news.rss`) returned earnings transcripts in the VCR recording — summaries of calls, not market-moving data. |
| **Redundancy** | **High overlap with GNews (#7).** GNews aggregates Investing.com among its sources. Earnings call content is also available through SEC EDGAR (#3) for the US market. |
| **Cost** | Free (RSS). |

**Verdict**: **REMOVE.** This is the lowest-reliability RELIABLE-tier source (0.75), and its actual content (earnings transcripts) is of marginal investment signal value. Transcripts are better sourced from SEC EDGAR directly. Removing it reduces noise.

---

### Layer 3 — Market Data (Sources 10-11)

#### 10. yfinance (Yahoo Finance) — free, no key

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | Moderate. Yahoo Finance provides comprehensive US equity data (fundamentals + OHLCV) for free. |
| **Timeliness** | Good. Yahoo data is refreshed throughout the trading day. |
| **Signal value** | High. Fundamental data (P/E, market cap, ratios) is essential for Layer 2 analysis. OHLCV data feeds Layer 3 technical analysis. |
| **Redundancy** | **Partial overlap with Finnhub (#11).** Finnhub provides the same data types (profile + metrics + candles). But Finnhub is the FALLBACK — yfinance is the primary. |

**Verdict**: KEEP as PRIMARY market data source. yfinance is the best free option for US equity data. The implementation in `gateway/market_data.py` includes proper throttling (semaphore(5) + 200ms delay).

**Risk**: yfinance has no SLA and breaks periodically when Yahoo changes their API. The Finnhub fallback (#11) exists precisely for this reason.

---

#### 11. Finnhub — free tier, 60 calls/min

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | Low. Provides the same OHLCV + fundamentals as yfinance (#10). |
| **Timeliness** | Good. Finnhub provides real-time data within free tier constraints. |
| **Signal value** | Same as yfinance. But only used as FALLBACK — when `_fetch_yfinance()` returns empty, `_fetch_finnhub()` is called. |
| **Redundancy** | **Functionally identical to yfinance (#10).** Same data types, same coverage (US equities). Finnhub's only role is redundancy — it is NOT additive. |
| **Cost** | Free tier, 60 API calls/min. |

**Verdict**: KEEP as fallback only. The free tier makes this a zero-cost insurance policy. However, monitor actual fallback usage — if Finnhub is never invoked in production (yfinance is reliable enough), the code overhead is minimal but unnecessary. The implementation is ~50 lines in `market_data.py`, well within acceptable limits.

**Recommendation**: Keep for now. Re-evaluate after 90 days of production usage. If Finnhub fallback is triggered <1% of the time, the code path could be simplified to a direct error message instead of a full Finnhub integration.

---

### Layer 4 — Insider (Sources 12-14)

#### 12. SEC Form 4 (insider trades) — BEST_EFFORT, 0.20

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | High. Form 4 filings reveal corporate insider buying/selling — a signal category no other source provides. |
| **Timeliness** | Moderate. Filings are due within 2 business days. Data is 0-2 days delayed. |
| **Signal value** | Medium. Insider clusters (3+ unique members, same ticker, 14-day window) are a well-documented contrarian signal. The `detect_insider_clusters()` function boosts these items 1.5x. |
| **Redundancy** | None. Unique data type. |
| **Cost** | Free (SEC EDGAR Atom feed). |

**Verdict**: BOOST priority. The current implementation works but has low reliability (0.20) and BEST_EFFORT tier. Insider trading data is one of the few genuinely unique signals in the system. The clustering logic is well-designed. Consider upgrading to RELIABLE tier after monitoring cluster detection hit rate for 30 days. The implementation could also be enhanced to parse the actual transaction amounts (shares, price, value) from the EDGAR filing summary rather than just the title.

---

#### 13. SEC 13F (institutional holdings) — BEST_EFFORT, 0.15

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | Moderate. 13F reveals institutional portfolio shifts that are invisible to news feeds. |
| **Timeliness** | VERT LOW. 13F filings are quarterly with a 45-day filing deadline. Data is 45-135 days stale. |
| **Signal value** | Low for timing, Medium for thesis. Stale institutional data cannot inform short-term entries but can validate structural theses. |
| **Redundancy** | None directly. However, institutional positioning is partially captured by COT data (#5) for futures. |
| **Cost** | Free (SEC EDGAR Atom feed). |

**Verdict**: KEEP at BEST_EFFORT. The 45-135 day staleness makes this useless for entry/exit timing. Its value is limited to structural thesis validation for long-term holdings. Do not invest engineering effort in improving 13F parsing — the staleness is fundamental. Current implementation (fetch filing titles from Atom feed) is appropriate for the value it provides.

---

#### 14. Congress Trades (manual) — SOURCE DEAD

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | High in theory. Congressional stock trading data is a high-profile signal. |
| **Timeliness** | N/A. All three endpoints are DEAD. |
| **Signal value** | High in theory, ZERO in practice (no data). |
| **Redundancy** | None. |
| **Status** | CONFIRMED DEAD. House Stock Watcher S3 (403, all regions), Senate Stock Watcher API (503/TLS), CapitolTrades BFF (503 CloudFront). Function returns empty list with one-time warning. Manual entry fallback exists in `manual_congress.py`. |

**Verdict**: **REMOVE from active pipeline.** The `fetch_congress_trades()` function is dead code — it always returns `[]`. Keep `manual_congress.py` as a human-operated fallback for manual entry, but stop including `fetch_congress_trades()` in the automated pipeline cycle. The function should be called `check_congress_trades()` and return a one-time warning, then be excluded from `fetch_source()` dispatch.

---

### Layer 5 — Macro API (Sources 15-16)

#### 15. FRED API (economic data series) — fed_key required

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | High. FRED provides 800K+ US economic data series from 100+ sources. |
| **Timeliness** | Good. Data is published on release schedule (monthly/weekly). No real-time streaming. |
| **Signal value** | Medium-High. Currently only BDI and GSCPI are supported. The FRED release calendar provides CPI/NFP/GDP release dates for confidence discounting. |
| **Redundancy** | **Partial overlap with FRED RSS (#1).** FRED RSS is narrative; FRED API is raw data. Different content types — NOT redundant. |
| **Cost** | Free (API key from stlouisfed.org). |

**Verdict**: KEEP. The FRED API currently supports only BDI and GSCPI directly, but also powers the economic calendar (release dates). **Expansion opportunity**: Add the actual CPI, NFP, GDP series to `_FRED_SERIES` — these are the most market-moving indicators and are already requested by the calendar module. Adding 4-5 high-impact series (CPI, NFP, GDP, PCE, Initial Claims) would dramatically increase the API's value at zero additional cost.

---

#### 16. EIA API (petroleum inventory) — eia_key required

| Criterion | Assessment |
|-----------|-----------|
| **Uniqueness** | High. EIA Weekly Petroleum Status Report is the authoritative source for US crude/gasoline/distillate inventory. |
| **Timeliness** | Weekly (Wednesday 10:30 AM ET). Sufficient for energy sector positioning. |
| **Signal value** | Medium. Crude inventory data moves oil markets, but Cushing inventory is the most-watched metric (not currently retrieved). Currently returns total crude (excl. SPR), gasoline, and distillate. |
| **Redundancy** | None. No other source provides US petroleum inventory data. |
| **Cost** | Free (API key from eia.gov). |

**Verdict**: KEEP. The implementation is solid. Consider adding Cushing-specific inventory (the delivery point for WTI futures — more market-sensitive than total crude) as an additional product option.

---

## Specific Question Answers

### 1. NewsAPI vs GNews
**GNews alone is sufficient.** Both are global news aggregators with significant overlap. GNews costs less, provides equivalent coverage, AND serves double duty as the L1 `search_news` tool (topic-specific queries). NewsAPI at $450/mo for the Business tier is not justified when GNews provides the same signal. REMOVE NewsAPI.

### 2. MarketWatch vs Investing.com
**Both should be removed.** MarketWatch RSS is dominated by consumer lifestyle content, not investment signals. Investing.com RSS is dominated by earnings call transcripts (available via EDGAR). Both feeds are aggregated by GNews, so removing them loses no unique information. REMOVE both.

### 3. FRED RSS vs FRED API
**Keep both.** The FRED RSS (St. Louis Fed Research blog) provides narrative/interpretive content. The FRED API provides raw economic data series. They serve different purposes and come from the same institution via different mechanisms. The RSS is correctly valued as contextual commentary, not as a data source. However, **demote the RSS from PRIMARY (0.99) to RELIABLE (0.85)** — a research blog is not an institutional data feed.

### 4. yfinance vs Finnhub
**Keep both in their current roles.** yfinance is the primary source; Finnhub is the zero-cost fallback. This is correct architecture. Monitor fallback usage rate and re-evaluate in 90 days.

### 5. Federal Reserve vs FRED
**Keep both.** Federal Reserve press releases provide policy narrative (FOMC statements, forward guidance). FRED provides economic data series. These serve different purposes — the Fed RSS is the "what does it mean," FRED is the "what is the data." The economic_calendar.py module integrates both: hardcoded FOMC dates from the Fed + FRED release calendar for CPI/NFP dates.

---

## Source Triage Summary

| # | Source | Current Tier | Verdict | Rationale |
|:--:|--------|:------------:|---------|-----------|
| 1 | FRED RSS | PRIMARY 0.99 | **KEEP, demote to RELIABLE 0.85** | Research blog, not institutional data |
| 2 | BLS API | PRIMARY 0.99 | **BOOST — NOT YET IMPLEMENTED** | Highest-value gap; CPI/NFP/PPI data is essential |
| 3 | SEC EDGAR | PRIMARY 0.99 | KEEP | Authoritative filings source |
| 4 | Federal Reserve | PRIMARY 0.99 | KEEP | Irreplaceable monetary policy coverage |
| 5 | CFTC COT | PRIMARY 0.99 | KEEP | Unique positioning data |
| 6 | NewsAPI | RELIABLE 0.90 | **REMOVE** | $450/mo, redundant with GNews |
| 7 | GNews | RELIABLE 0.85 | KEEP as sole aggregator | Cheaper, dual-purpose (headlines + search) |
| 8 | MarketWatch | RELIABLE 0.80 | **REMOVE** | Low signal (lifestyle content), GNews covers it |
| 9 | Investing.com | RELIABLE 0.75 | **REMOVE** | Low signal (earnings transcripts), GNews covers it |
| 10 | yfinance | (Layer 3) | KEEP | Primary market data, free, comprehensive |
| 11 | Finnhub | (Layer 3) | KEEP as fallback | Zero-cost insurance, re-evaluate in 90 days |
| 12 | SEC Form 4 | BEST_EFFORT 0.20 | **BOOST to RELIABLE** | Unique insider signal with cluster detection |
| 13 | SEC 13F | BEST_EFFORT 0.15 | KEEP at BEST_EFFORT | Structurally stale (45-135 day lag) |
| 14 | Congress Trades | (DEAD) | **REMOVE from pipeline** | All endpoints dead; keep manual fallback only |
| 15 | FRED API | (Layer 5) | KEEP + EXPAND | Add CPI/NFP/GDP series expansion |
| 16 | EIA API | (Layer 5) | KEEP | Add Cushing-specific inventory |

---

## Recommended Minimal Set

### Tier 1 — Essential (must have, irreplaceable)
| Source | Layer | What it provides |
|--------|:-----:|------------------|
| SEC EDGAR | L1 | Authoritative corporate filings |
| Federal Reserve | L1 | FOMC statements, monetary policy |
| CFTC COT | L1 | Institutional positioning |
| yfinance | L3 | Market data (fundamentals + OHLCV) |
| FRED API | L5 | Economic data series + release calendar |
| BLS API | L1 | **NEW** — CPI, NFP, PPI, employment data |
| SEC Form 4 | L4 | Insider trading signals |

### Tier 2 — High value (keep, low cost)
| Source | Layer | What it provides |
|--------|:-----:|------------------|
| GNews | L1 | General news aggregation + topic search |
| EIA API | L5 | Petroleum inventory |
| FRED RSS | L1 | Economic research commentary |
| Finnhub | L3 | yfinance fallback |
| SEC 13F | L4 | Institutional holdings (stale but unique) |

### Tier 3 — Remove
| Source | Reason |
|--------|--------|
| NewsAPI | $450/mo, redundant with GNews |
| MarketWatch | Lifestyle content, GNews covers it |
| Investing.com | Earnings transcripts, GNews covers it |
| Congress Trades | All endpoints dead |

---

## Estimated Impact

| Metric | Current | Target | Delta |
|--------|:-------:|:------:|:-----:|
| Total sources | 16 | 11 (after adding BLS) | **-5 removed, +1 new** |
| Active sources (not dead/TBD) | 14 | 12 | **-2 net** |
| "PRIMARY"-tier sources | 5 | 5 (swap FRED RSS for BLS) | parity |
| Monthly API cost | $450+ (NewsAPI) | ~$0 (all free or free-tier) | **-$450/mo** |
| Source count reduction | — | 5 removed | **-31%** |
| Unimplemented sources | 1 (BLS) | 0 | **100% implemented** |

### Priority Action Items (ordered by impact/cost)

1. **[HIGH]** Implement BLS API — fills the biggest data gap (CPI/NFP/PPI) at zero cost
2. **[HIGH]** Remove NewsAPI — saves $450/mo immediately, no data loss
3. **[MEDIUM]** Remove MarketWatch and Investing.com RSS — reduce noise in dedup pipeline
4. **[MEDIUM]** Remove Congress Trades from active pipeline — dead code elimination
5. **[LOW]** Demote FRED RSS from PRIMARY to RELIABLE — accuracy correction
6. **[LOW]** Expand FRED API series (CPI, NFP, GDP, PCE, Claims) — zero-cost upgrade
7. **[LOW]** Add Cushing inventory to EIA API — more market-sensitive than total crude
