# H1: Congress Trading Data Source — Replacement Research

**Date:** 2026-05-17
**Context:** `pipeline/insider_sources.py` — `fetch_congress_trades()` is a dead stub. House Stock Watcher S3 returns 403, Senate Stock Watcher API returns 503/TLS, CapitolTrades BFF returns 503 CloudFront. We need a replacement.

**Current architecture** (from `insider_sources.py`):
- Async Python, `httpx.AsyncClient`, `feedparser` for Atom feeds
- Returns `NewsItem` objects with `content_type="insider_signal"`
- Existing working sources: SEC Form 4 and 13F via EDGAR Atom feeds
- No API keys currently used

---

## Evaluated Sources

### 1. House Stock Watcher — S3 JSON Dump + API (FREE, House Only)

- **Website:** `https://housestockwatcher.com`
- **API:** `https://housestockwatcher.com/api` (returns CSV/JSON)
- **S3 Master JSON:** `https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json`
- **Maintainer:** Timothy Carambat (GitHub: `timothycarambat/house-stock-watcher-data`)
- **Status:** Uncertain. MarketMind code reports S3 403. However, the domain SSL certificates are valid through 2026 with no widespread reports of shutdown. The 403 may have been a transient CloudFront/WAF issue, a CORS policy change, or a regional block. **Worth re-testing** — simply `httpx.get()` the S3 URL.

**Data fields:** `disclosure_year`, `disclosure_date`, `transaction_date`, `owner` (Self/Spouse/Joint/Child), `ticker`, `asset_description`, `type` (Purchase/Sale/Exchange), `amount` (bracket range), `representative`, `district` (e.g. NY-12), `state`, `party`, `ptr_link`, `asset_type`, `cap_gains_over_200_usd`

**Pros:**
- Free, no API key
- Single JSON file — trivial integration
- Includes party affiliation
- Companion to the original source (same maintainer)

**Cons:**
- House only (no Senate). Senate Stock Watcher is confirmed dead (GitHub repo last updated >3 years ago, SSL likely expired)
- Unofficial, could disappear without notice
- The previous 403 may indicate a deliberate block or shutdown

**Integration effort:** Small (single httpx GET → parse JSON → map to NewsItem)

---

### 2. Official House Clerk — Disclosures ZIP + XML (FREE, House Only)

- **ZIP endpoint:** `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<YEAR>FD.zip` (e.g., `2026FD.zip`)
- **Contents:** `<YEAR>FD.xml` (index) + individual PTR PDFs
- **PDF fetch:** `https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/<YEAR>/<DocID>.pdf`
- **Status:** ✅ Working. Official government source, STOCK Act mandated. New ZIP published daily.

**Data extraction workflow:**
1. Download ZIP, extract XML index
2. Filter XML for `FilingType='P'` (Periodic Transaction Report)
3. Fetch each PTR PDF
4. Parse PDF text (machine-generated, structured)
5. ~5% of historical PTRs are scanned images requiring OCR

**Pros:**
- Authoritative source, guaranteed uptime
- Free, no API key, no rate limiting
- Complete House coverage

**Cons:**
- House only
- Requires PDF parsing + OCR fallback for scanned documents
- ZIP can be large (full year-to-date). Need to track which DocIDs have already been processed to avoid redundant fetches
- No ticker field in XML — ticker must be extracted from PDF text

**Integration effort:** Large (ZIP download + XML parse + PDF text extraction + OCR fallback + dedup)

---

### 3. Official Senate EFD — efdsearch.senate.gov (FREE, Senate Only)

- **Base URL:** `https://efdsearch.senate.gov/`
- **Status:** ✅ Working. Official government source, STOCK Act mandated.

**Challenges:**
- Akamai bot protection — direct requests get 403. Residential proxy or browser-like headers required
- Terms-acceptance gate — every session must POST `prohibition_agreement=1` to `/search/home/`
- Two-stage data flow — `/search/report/data/` returns filing list, each links to a detail page with actual transactions
- Session cookies expire quickly
- HTML scraping (DataTables-based)

**Pros:**
- Authoritative source for Senate

**Cons:**
- Senate only
- High scraping complexity (bot protection, session management, HTML parsing)
- No ticker in listing — must fetch detail pages

**Integration effort:** Large (bot bypass + session management + two-stage HTML scraping)

---

### 4. Financial Modeling Prep (FMP) API (FREEMIUM, Both Chambers)

- **Base URL:** `https://financialmodelingprep.com/api/`
- **Endpoints:**
  - Senate: `/stable/senate-trades?symbol=AAPL&apikey=KEY`
  - Senate latest: `/stable/senate-latest?apikey=KEY`
  - House latest: `/stable/house-latest?apikey=KEY`
  - Senate by name: `/stable/senate-trades-by-name?name=Jerry&apikey=KEY`
- **Free tier:** 250 requests/day
- **Status:** ✅ Working, actively maintained

**Data format (JSON):**
```json
{
  "symbol": "AAPL",
  "disclosureDate": "2026-02-15",
  "transactionDate": "2026-01-15",
  "firstName": "John",
  "lastName": "Boozman",
  "office": "John Boozman",
  "district": "AR",
  "owner": "Joint",
  "assetDescription": "Apple Inc",
  "assetType": "Stock",
  "type": "Purchase",
  "amount": "$1,001 - $15,000",
  "capitalGainsOver200USD": "False",
  "comment": "--",
  "link": "https://efdsearch.senate.gov/..."
}
```

**Key unknown:** FMP does not publish a definitive list of which endpoints are free vs. premium. The free plan page shows a "Free Plan Access" banner on the Senate/House docs, but also states "No Premium endpoints." The only way to know is to sign up for a free key and test.

**Pros:**
- Single API for both House and Senate
- Clean JSON, well-documented
- Easiest integration if free tier works
- Includes direct links to official filings

**Cons:**
- Requires API key (free registration, but still adds a dependency)
- Rate limited (250 req/day free tier)
- Uncertain if congressional endpoints are on free tier. If not: Starter $29/mo
- Adds a key-based dependency vs. the current key-less architecture

**Integration effort:** Small (httpx GET + API key header → parse JSON → map to NewsItem)

---

### 5. Apify Congressional Trading Actors (PAY-PER-USE, Both Chambers)

- **Senate actor:** `seralifatih/congress-trading-pipeline` — scrapes `efdsearch.senate.gov`
- **House actor:** `seralifatih/congress-trading-pipeline-1` — scrapes `disclosures-clerk.house.gov`
- **Cost:** ~$0.10 per 30-day pull, ~$0.72/day running every 6 hours
- **Output:** Clean, deduplicated JSON (SHA-256 idempotent)
- **Status:** ✅ Working

**Data fields:** `politician`, `ticker`, `asset_name`, `asset_type`, `type` (buy/sell), `amount_min`, `amount_max`, `transaction_date`, `filing_date`, `owner`

**Pros:**
- Both chambers covered
- Handles all scraping complexity (bot bypass, PDF parsing, dedup)
- Structured JSON output
- Very low cost

**Cons:**
- Costs money (though minimal: ~$22/month at 6-hour polling)
- Adds external dependency on Apify platform
- Latency (pull-based, not real-time)

**Integration effort:** Small (httpx POST to Apify API → parse JSON → map to NewsItem)

---

### 6. Quiver Quantitative (PAID, Both Chambers)

- **API base:** `https://api.quiverquant.com/beta/`
- **Congress endpoint:** `/beta/bulk/congress/politicians`
- **Cost:** Free tier = dashboard only (no API). Hobbyist $12.50/mo, Trader $25/mo
- **Python SDK:** `pip install quiverquant`
- **Coverage:** 2016–present, daily updates, ~1,800 tickers
- **Status:** ✅ Working

**Pros:** Well-documented, Python SDK, comprehensive
**Cons:** Requires paid subscription for API access
**Integration effort:** Small (Python SDK or REST API)

---

### 7. MCP Capitol Trades Server (FREE, npm Package)

- **Package:** `@anguslin/mcp-capitol-trades` (npm)
- **Tools:** `get_politician_trades`, `get_top_traded_assets`, `get_politician_stats`, `get_asset_stats`, `get_buy_momentum_assets`
- **Status:** Working but depends on CapitolTrades.com as backend data source

**Pro:** Free, no API key, MCP-compatible
**Con:** Backend data source (CapitolTrades.com) is the same BFF that returns 503 for MarketMind. If CapitolTrades blocks direct requests, the MCP server would fail too. Not suitable as a primary source.

---

## Sources Confirmed Dead / Not Viable

| Source | Failure Mode | Evidence |
|--------|-------------|----------|
| **Senate Stock Watcher** (`senatestockwatcher.com/api`) | 503 / TLS failure | GitHub data repo (`timothycarambat/senate-stock-watcher-data`) last pushed >3 years ago. No recent activity. |
| **CapitolTrades BFF** (`bff.capitoltrades.com/trades`) | 503 CloudFront | Confirmed by MarketMind. Uptime checkers show inconsistent results (down April 6, redirected April 14). No SLA, no docs, internal endpoint. |
| **House Stock Watcher S3** (`house-stock-watcher-data.s3-us-west-2.amazonaws.com`) | 403 (all regions) | Confirmed by MarketMind. Domain SSL valid through 2026 suggests it may be alive but blocking. |

---

## Recommendation: Two-Tier Approach

### Tier 1 — Try First (Easiest, May Just Work)

**A. Re-test House Stock Watcher S3**

The 403 may have been transient. Try with:
- Different User-Agent (browser-mimicking)
- Direct S3 URL: `https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json`
- API endpoint: `https://housestockwatcher.com/api`
- Alternative S3 regions: `us-east-1`, `us-west-1`

If it works → instant win for House data. Single JSON download, map to NewsItem.

**B. FMP free tier test**

Register a free API key at `financialmodelingprep.com` and test:
```
GET https://financialmodelingprep.com/stable/senate-latest?apikey=YOUR_KEY
GET https://financialmodelingprep.com/stable/house-latest?apikey=YOUR_KEY
```

If both return 200 with data → single API covers both chambers. 250 req/day is ample for daily pipeline use.

### Tier 2 — Fallback (More Work, Guaranteed to Work)

**Official House Clerk ZIP + PDF parsing (House) + Apify Senate actor (Senate)**

If Tier 1 options fail:
- House: Direct from `disclosures-clerk.house.gov` — ZIP → XML filter → PDF text extraction → NewsItem
- Senate: Apify actor `seralifatih/congress-trading-pipeline` (~$0.10/pull) — avoids the Akamai/session/cookie nightmare of direct EFD scraping

This combination is the most reliable because the House Clerk is an official government endpoint that cannot be shut down, and the Apify actor handles all Senate scraping complexity.

---

## Summary Comparison

| Source | Chambers | Cost | API Key? | Reliability | Integration Effort |
|--------|:--------:|:----:|:--------:|:-----------:|:------------------:|
| House Stock Watcher S3 | House | Free | No | Unknown (was 403) | **Small** |
| House Stock Watcher API | House | Free | No | Unknown (was 403) | **Small** |
| Official House Clerk | House | Free | No | Guaranteed | **Large** |
| Official Senate EFD | Senate | Free | No | Guaranteed | **Large** |
| FMP API | Both | Free (TBD) | Yes | High | **Small** |
| Apify Actors | Both | ~$0.10/pull | Yes | High | **Small** |
| QuiverQuant | Both | $12.50+/mo | Yes | High | Small |

**Final recommendation:** First verify whether House Stock Watcher S3 is truly dead (the 403 may be recoverable). Simultaneously test FMP free tier for congressional endpoints. If neither works, fall back to Official House Clerk + Apify Senate actor.

---

## Integration Notes

When implementing, the new `fetch_congress_trades()` should:
1. Follow the same pattern as `fetch_form4_insider()` — async, `httpx.AsyncClient`, return `list[NewsItem]`
2. Set `source_name="Congress Trades"`, `source_tier=int(SourceTier.BEST_EFFORT)`, `content_type="insider_signal"`
3. Set `source_reliability` to 0.15–0.20 (similar to Form 4/13F) due to the 30-45 day reporting lag
4. Include politician name and party in the `title` field for downstream cluster detection
5. Fire a one-time warning if the source returns empty (preserve the existing dead-source warning pattern)
6. The `detect_insider_clusters()` function already scans `insider_signal` content_type items, so Congress trades will automatically participate in cluster detection
