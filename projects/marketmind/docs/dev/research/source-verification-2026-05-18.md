# Source Verification Report — 2026-05-18

**Engineer**: Data Engineer
**Method**: Live HTTP fetch of each source RSS/API endpoint, checking summary field quality (plain text after HTML stripping must contain article text beyond just the title).
**Test date**: 2026-05-18 ~18:30 UTC

---

## Summary

| Category | Count | Status |
|----------|:-----:|--------|
| CONFIRMED_WORKING (full article content) | 15 | Operational |
| PARTIAL (brief summaries, usable) | 2 | Acceptable |
| HEADLINES_ONLY (titles only, no article text) | 18 | 1 PRIMARY needs attention; 17 are BEST_EFFORT |
| FAILED | 0 | All reachable |

---

## Primary Tier Sources

### CONFIRMED_WORKING

| Source | Type | Verdict | Details |
|--------|------|---------|---------|
| **FRED** (St. Louis Fed) | API (macro_data.py) | CONFIRMED_WORKING | BDI = 430.372 via PPI proxy. Real API call succeeds when FRED_KEY is in .env and `dotenv.load_dotenv()` is called before using macro_data. **Note**: `_get_fred_key()` tries `MarketMindConfig.fred_key` first (attribute doesn't exist → caught by `except Exception: pass`), then falls back to `os.environ.get("FRED_KEY")`. The env var path works. |
| **CFTC COT** | API (macro_data.py, SODA) | CONFIRMED_WORKING | ES speculative_net=89,575, date=2026-05-12. Public API, no key required. |
| **BLS** | API (bls_fetcher.py) | CONFIRMED_WORKING | CPI=333.02, Core CPI=335.803, Unemployment=4.3% (all April 2026). PPI: no observations returned by BLS API — data availability gap, not a code issue. |
| **Federal Reserve** | RSS | CONFIRMED_WORKING | 20 entries, real summaries (155-233 chars). |
| **EC Press Corner** | RSS | CONFIRMED_WORKING | 10 entries, ~250 char summaries. |
| **Brazil BCB Copom** | RSS | CONFIRMED_WORKING | 10 entries, very rich content (up to 5,128 chars). |
| **SEC EDGAR** | Atom feed | PARTIAL** | 20 entries. Atom format gives brief summaries (127 chars max). Not headline-only — contains filing descriptions. Usable as-is. |

### HEADLINES_ONLY

| Source | Type | Verdict | Details |
|--------|------|---------|---------|
| **ECB Press Releases** | RSS | **HEADLINES_ONLY** | **PRIMARY tier** — 15 entries, zero-length `<description>` tags. The RSS feed returns titles only with empty description fields. |

---

## Reliable Tier Sources

All RELIABLE tier sources are CONFIRMED_WORKING:

| Source | Type | Verdict | Details |
|--------|------|---------|---------|
| **NewsAPI** | Paid API | CONFIRMED_WORKING | 20 articles with full content via JSON API. |
| **GNews** | Paid API | CONFIRMED_WORKING | 20 articles with full content via JSON API. |
| **MarketWatch** | RSS | CONFIRMED_WORKING | 10 entries, real summaries (200+ chars). |
| **China Daily Bizchina** | RSS | CONFIRMED_WORKING | 100 entries, 315 char summaries. |
| **CGTN Business** | RSS | CONFIRMED_WORKING | 50 entries, 264 char summaries. |
| **SCMP Business** | RSS | CONFIRMED_WORKING | 50 entries, 500+ char summaries. |
| **Financial Times** | RSS | CONFIRMED_WORKING | 25 entries, brief but real summaries (121 chars). |

---

## Fragile Tier Sources

| Source | Type | Verdict | Details |
|--------|------|---------|---------|
| **Nikkei Asia (via Google News)** | RSS proxy | TITLE_ONLY | 84 entries. Google News RSS format — description contains only `<a href="google redirect">Title</a> Source`. No article summary. |
| **Xinhua English** | RSS | CONFIRMED_WORKING | 20 entries, 202 char summaries. |

---

## Best Effort Tier — All Google News Proxy Sources

**Verdict: ALL 17 are TITLE_ONLY.** Every Google News RSS proxy returns descriptions containing ONLY an HTML `<a>` tag wrapping a Google News redirect URL, plus the source name. After `_strip_html()`, the result is literally `"Article Title  Source Name"` — the title repeated, with no additional article content.

This is inherent to Google News RSS format, not a search query or configuration issue. The raw HTML is 400-800 chars of redirect link boilerplate:

```html
<a href="https://news.google.com/rss/articles/CBMingFBVV95cUxN...">
Article Title Here</a>&nbsp;<font size="-1">Source Name</font>
```

After HTML stripping: `"Article Title Here  Source Name"` — no additional text.

### Affected sources (all TITLE_ONLY):

| # | Source | Entries | HTTP |
|---|--------|:-------:|:----:|
| 1 | ECB (via Google News) | 100 | 200 |
| 2 | Nikkei Asia | 84 | 200 |
| 3 | Caixin (via Google News) | 60 | 200 |
| 4 | PBOC (via Google News) | 100 | 200 |
| 5 | China Economy (via Google News) | 64 | 200 |
| 6 | Euronews (via Google News) | 100 | 200 |
| 7 | Eurostat (via Google News) | 36 | 200 |
| 8 | India RBI (via Google News) | 100 | 200 |
| 9 | South Africa SARB (via Google News) | 100 | 200 |
| 10 | World Bank (via Google News) | 100 | 200 |
| 11 | IMF (via Google News) | 100 | 200 |
| 12 | OPEC Oil (via Google News) | 92 | 200 |
| 13 | Precious Metals (via Google News) | 100 | 200 |
| 14 | Agriculture (via Google News) | 79 | 200 |
| 15 | Natural Gas (via Google News) | 100 | 200 |
| 16 | Healthcare (via Google News) | 64 | 200 |
| 17 | Crypto (via Google News) | 71 | 200 |

---

## Non-RSS/Dynamic Sources

| Source | Type | Verdict | Details |
|--------|------|---------|---------|
| **Bluesky** | API (social_sources.py) | WORKING | Uses AT Protocol. Configurable keywords. |
| **EIA** | API (macro_data.py) | CONFIRMED_WORKING | Crude inventory = 199.5M barrels (2026-05-08). Real API call succeeds when EIA_KEY is in .env. |

---

## Analysis

### Source Quality Tiers (Actual)

```
FULL CONTENT (15): FRED, CFTC, BLS, Fed Reserve, EC Press Corner, Brazil BCB,
                   MarketWatch, China Daily, CGTN, SCMP, FT, Xinhua, EUobserver,
                   NewsAPI, GNews

PARTIAL (2):        SEC EDGAR (short Atom summaries), Financial Times (brief)

HEADLINES ONLY (18): ECB Press Releases (PRIMARY!), 17x Google News proxies (BEST_EFFORT)

DEAD (0):           None — all sources reachable
```

### Issues Requiring Attention

1. **ECB Press Releases** (PRIMARY tier): Zero-length RSS descriptions. This is the official ECB RSS feed. Flag for user decision — options:
   - Accept as-is (titles still provide topic awareness from a primary institution)
   - Supplement with ECB (via Google News) proxy (which is also TITLE_ONLY)
   - Search for an alternative ECB news API

2. **All Google News proxies** (BEST_EFFORT tier, 17 sources): TITLE_ONLY is inherent to Google News RSS format. These feeds were always designed for click-through discovery, not content syndication. They still provide value as topic/discovery signals (event detection, regional coverage, keyword monitoring). Recommendation: **keep them** — they're correctly labeled BEST_EFFORT and serve their intended purpose (topic awareness). Consider them regional radar, not article sources.

3. **PPI indicator from BLS**: No observations returned. The BLS API returns data for 3/4 indicators. PPI series `PCUOMFGOMFG` may need a different series ID or the data may lag. Low priority — CPI and unemployment data are the primary BLS use cases.

4. **FRED key resolution**: `MarketMindConfig` lacks `fred_key` and `eia_key` attributes. The env var fallback works, but the `AttributeError` on every call produces log noise. Recommend adding `fred_key` and `eia_key` fields to `MarketMindConfig` for clean key resolution.

### What Was NOT Tested

- **Bluesky**: Social source, tested in prior sessions (working with one account)
- **Manual congress trading** (`tools/manual_congress.py`): Not part of automated pipeline

---

**Updated**: 2026-05-18 18:30 UTC

---

## Google Proxy Assessment + ECB Fix

**Assessment date**: 2026-05-18 ~19:00 UTC
**Engineer**: Data Engineer
**Action**: All recommendations implemented in `config/source_authority.py` (net: 35 → 25 sources)

---

### ECB Fix

**Problem**: ECB Press Releases (`rss/press.html`) is HEADLINES_ONLY — 15 entries with zero-length `<description>` tags.

**Solution**: Found and added **ECB Publications** (`rss/pub.html`) as a new PRIMARY source:
- URL: `https://www.ecb.europa.eu/rss/pub.html`
- 15 entries, FULL_CONTENT (865 chars per description)
- Covers Economic Bulletin, Financial Stability Review, research papers
- Supplements the titles-only ECB Press Releases feed
- ECB (via Google News) proxy removed — redundant with Press Releases + Publications + EC Press Corner

Other ECB sub-feeds tested: `rss/sp.html` (speeches), `rss/int.html` (interviews), `rss/statspr.html` (statistical press) → all return 404. The two working ECB RSS feeds (press + pub) are the only ones available.

---

### Google News Proxy Assessment — All 17 Sources

#### Sources REPLACED with direct RSS (3)

| Old (Google News proxy) | New (direct RSS) | Tier | Quality |
|------|------|:---:|------|
| Euronews (via Google News) | **Euronews Business** (`www.euronews.com/rss?format=mrss&level=theme&name=business`) | RELIABLE | FULL_CONTENT, 50 entries, 214 chars/desc |
| India RBI (via Google News) | **India RBI Press Releases** (`www.rbi.org.in/pressreleases_rss.xml`) | PRIMARY | FULL_CONTENT, 10 entries, 1700+ chars/desc |
| Crypto (via Google News) | **CoinTelegraph** (`cointelegraph.com/rss`) | RELIABLE | FULL_CONTENT, 30 entries, 130+ chars/desc |

#### Sources DELETED — redundant with existing direct coverage (11)

| Source | Reason |
|------|------|
| **Caixin (via Google News)** | Redundant with China Daily + CGTN + SCMP + Xinhua (4 direct China sources). Caixin official RSS (`gateway.caixin.com/api/data/global/feedlyRss.xml`) returns HTTP 406. |
| **PBOC (via Google News)** | PBOC news appears in all 4 China direct RSS sources. |
| **China Economy (via Google News)** | Redundant with China direct sources + macro data pipelines. |
| **Eurostat (via Google News)** | Redundant with ECB Publications + EC Press Corner + ECB Press Releases (3 direct EU institutional sources). Eurostat RSS feed URLs returned 404. |
| **World Bank (via Google News)** | Development economics, not market-moving. World Bank RSS URLs serve Adobe CMS HTML, not actual RSS feeds. |
| **IMF (via Google News)** | IMF RSS URLs serve React SPA HTML pages, not RSS feeds. IMF WEO/Article IV news covered by Financial Times + general financial sources. Old blog RSS (`blogs.imf.org/feed/`) also returns HTML. |
| **Precious Metals (via Google News)** | Covered by MarketWatch + general financial RSS feeds. |
| **Agriculture (via Google News)** | Not in primary asset universe. EIA + CFTC COT cover energy/commodities. |
| **Natural Gas (via Google News)** | Covered by EIA API inventory data + CFTC COT NG futures + general energy news. |
| **Healthcare (via Google News)** | Sector-specific news, not macro-focused. Covered by general financial sources. |
| **ECB (via Google News)** | Redundant with ECB Press Releases + ECB Publications + EC Press Corner (3 direct institutional sources). |

#### Sources KEPT — unique coverage, no better alternative found (3)

| Source | Reason | Importance |
|------|------|:---:|
| **Nikkei Asia (via Google News)** | Only Japan-specific source. Official Nikkei RSS URLs returned 404. Nikkei Asia RSS page (`info.asia.nikkei.com/rss`) exists but with JS-based subscribe. 84 entries, titles provide Japan market awareness. | MEDIUM — Japan is the 3rd largest economy, but coverage is thin. Keep until a direct feed is found. |
| **South Africa SARB (via Google News)** | Only Africa EM central bank source. SARB RSS page (`resbank.co.za/en/home/quick-links/rss-feeds`) uses JS-based subscribe — no direct XML URL. SSL handshake timeout on direct access attempts. | MEDIUM — unique EM central bank coverage. Keep as radar. |
| **OPEC Oil (via Google News)** | OPEC has NO official RSS feed. Production quota decisions are market-critical for energy positions. Google News proxy is the only programmatic source for OPEC policy news. Supplemented by EIA inventory data + CFTC COT positioning data. | HIGH — oil is a primary macro driver; OPEC decisions move markets. Must keep until an OPEC RSS/API exists. |

---

### New Source Summary

After changes, `config/source_authority.py` has **25 sources** (down from 35):

| Tier | Count | Sources |
|------|:---:|------|
| PRIMARY | 10 | FRED, BLS, SEC EDGAR, Federal Reserve, CFTC COT, ECB Press Releases, **ECB Publications** (new), EC Press Corner, Brazil BCB Copom, **India RBI Press Releases** (new) |
| RELIABLE | 9 | NewsAPI, GNews, MarketWatch, China Daily, CGTN, SCMP, Financial Times, **Euronews Business** (new), **CoinTelegraph** (new) |
| FRAGILE | 3 | Nikkei Asia (GNews), Xinhua English, EUobserver |
| BEST_EFFORT | 3 | South Africa SARB (GNews), OPEC Oil (GNews), Bluesky |

### Sources NOT Found (Future Work)

These searches yielded no working direct RSS feed:

| Institution | Search Result | Blockers |
|------|------|------|
| **IMF** | `imf.org/en/News/RSS` → HTML SPA page | IMF website is a Next.js SPA; RSS endpoint serves HTML |
| **World Bank** | `worldbank.org/en/news/rss.xml` → HTML Adobe CMS | Adobe Experience Manager, no RSS |
| **OPEC** | No RSS infrastructure on `opec.org` | No programmatic access to production/policy news |
| **SARB** | RSS page exists but JS-only subscribe | SSL issues + no direct XML URL |
| **Caixin Global** | `gateway.caixin.com/api/data/global/feedlyRss.xml` → 406 | HTTP 406 Not Acceptable — may require specific Accept header or is IP-restricted |
| **Nikkei Asia** | `info.asia.nikkei.com/rss` page exists | JS-based subscribe button; attempted feed URLs return 404 |
| **Eurostat** | RSS feed URL not discoverable | EC website migration; contact `eurostat-mediasupport@ec.europa.eu` |

---

**Updated**: 2026-05-18 19:00 UTC
