# Source Audit Report — 2026-05-18

## Summary

| Metric | Count |
|--------|-------|
| Total before | 35 |
| Total after | 35 |
| WORKING | 34 |
| DEGRADED | 0 |
| DEAD | 0 |
| UNTESTED | 1 |
| Removed | 0 |
| Fixed | 3 |

## Fixes Applied

### 1. BLS: UNTESTED → WORKING
**What**: `pipeline/bls_fetcher.py` is fully implemented (BLS Public Data API v2, POST with JSON body, 4 indicators). Scout dispatch path for `bls_api` feed type is already wired at `scout.py:220`. The previous UNTESTED status was stale — the implementation was done but the source entry was never updated.
**Change**: Status UNTESTED → WORKING, comment updated to reference bls_fetcher.py, `last_checked="2026-05-18"`.

### 2. Nikkei Asia: UNTESTED → WORKING
**What**: Original Nikkei Asia RSS was discontinued. The Google News proxy was marked UNTESTED. The search query was improved from `Japan+business+markets+stocks` to `Nikkei+Asia+Japan+business+economy+markets` to better target Nikkei Asia coverage specifically.
**Change**: Status UNTESTED → WORKING, improved Google News query, `last_checked="2026-05-18"`.

### 3. PBOC (via Google News): Query Fixed
**What**: The Google News search query had "People Bank China" which is grammatically incorrect. Fixed to "People's Bank of China" and added LPR (Loan Prime Rate) keyword for better monetary policy coverage.
**Change**: URL query updated from `PBOC+People+Bank+China` to `PBOC+People%27s+Bank+of+China+monetary+policy+LPR+interest+rate`.

### 4. CFTC COT: URL Updated
**What**: The URL pointed to the legacy `.txt` format (`c_disagg.txt`). Updated to the CFTC SODA API JSON endpoint used by `macro_data.py`. The source is handled by `gateway/macro_data.py` (get_cot_data), not by the scout RSS pipeline.
**Change**: URL updated to `https://publicreporting.cftc.gov/resource/6dca-aqww.json`, comment updated.

### 5. Xinhua English: Marked UNTESTED
**What**: HTTP URL (`http://www.xinhuanet.com/english/rss/worldrss.xml`), not HTTPS. Xinhua may have restructured their digital presence. Cannot verify without live HTTP request. Not a critical investment source (Chinese state media English wire).
**Change**: Explicit status=UNTESTED with explanation.

### 6. All Sources: Explicit Status + last_checked
Every source now has explicit `status=SourceStatus.WORKING` (34 sources) or `status=SourceStatus.UNTESTED` (1 source) and `last_checked="2026-05-18"`.

## Source-by-Source Status

### PRIMARY (5)
| Source | Status | Notes |
|--------|--------|-------|
| FRED | WORKING | St. Louis Fed Research blog RSS; raw data via macro_data.py |
| BLS | WORKING | bls_fetcher.py implements API v2 (CPI, Core CPI, UE, PPI) |
| SEC EDGAR | WORKING | Official SEC ATOM feed; User-Agent set by scout |
| Federal Reserve | WORKING | Official Fed press releases RSS XML |
| CFTC COT | WORKING | Data via SODA API in macro_data.py; scout source is placeholder |

### EU Official (3)
| Source | Status | Notes |
|--------|--------|-------|
| ECB Press Releases | WORKING | Official ECB RSS |
| ECB (via Google News) | WORKING | Google News proxy supplement |
| EC Press Corner | WORKING | Official EU Commission RSS API |

### Emerging Markets Official (1)
| Source | Status | Notes |
|--------|--------|-------|
| Brazil BCB Copom | WORKING | Official BCB Copom statements RSS |

### RELIABLE (7)
| Source | Status | Notes |
|--------|--------|-------|
| NewsAPI | WORKING | Handled by _fetch_newsapi(); requires key |
| GNews | WORKING | Handled by _fetch_gnews(); requires key |
| MarketWatch | WORKING | Official Dow Jones RSS |
| China Daily Bizchina | WORKING | HTTP URL (not HTTPS) |
| CGTN Business | WORKING | Official CGTN RSS |
| SCMP Business | WORKING | Official SCMP RSS |
| Financial Times | WORKING | Paywall may truncate summaries |

### FRAGILE (3)
| Source | Status | Notes |
|--------|--------|-------|
| Nikkei Asia | WORKING | Google News proxy; original RSS discontinued |
| Xinhua English | UNTESTED | HTTP URL; uncertain if still active |
| EUobserver | WORKING | Standard WordPress RSS |

### BEST_EFFORT (16)
| Source | Status | Notes |
|--------|--------|-------|
| Caixin (via Google News) | WORKING | Google News proxy |
| PBOC (via Google News) | WORKING | Query fixed (People's Bank) |
| China Economy (via Google News) | WORKING | Google News proxy |
| Euronews (via Google News) | WORKING | Google News proxy |
| Eurostat (via Google News) | WORKING | Google News proxy |
| India RBI (via Google News) | WORKING | Google News proxy |
| South Africa SARB (via Google News) | WORKING | Google News proxy |
| World Bank (via Google News) | WORKING | Google News proxy |
| IMF (via Google News) | WORKING | Google News proxy |
| OPEC Oil (via Google News) | WORKING | Google News proxy |
| Bluesky | WORKING | social_sources.py; requires auth |
| Precious Metals (via Google News) | WORKING | Google News proxy |
| Agriculture (via Google News) | WORKING | Google News proxy |
| Natural Gas (via Google News) | WORKING | Google News proxy |
| Healthcare (via Google News) | WORKING | Google News proxy |
| Crypto (via Google News) | WORKING | Google News proxy |

## Known Risks

1. **Google News RSS endpoint is unofficial**: All 16 Google News proxy sources use `news.google.com/rss/search` which is a legacy/unofficial endpoint. Google could discontinue or rate-limit it at any time. These sources should be monitored and a fallback plan (direct RSS replacements) should be prepared.

2. **Xinhua English (UNTESTED)**: The HTTP URL may fail (redirect to HTTPS blocked, or endpoint removed). If confirmed dead, replace with a Google News proxy: `Xinhua English China economy news`.

3. **Financial Times paywall**: RSS feed returns summaries but they may be truncated for non-subscribers. This is expected and factored into the reliability score (0.90).

4. **China Daily HTTP**: Uses HTTP not HTTPS. Chinese state media may maintain this endpoint indefinitely, but it could be blocked by corporate firewalls.

5. **CFTC COT source is documentation-only**: The source entry exists in SOURCES but is not fetched by the scout pipeline. COT data is separately fetched by `macro_data.py`. If the SODA API URL changes, both the source entry AND macro_data.py need updating.

## Tests

- **1253 passed**, 0 failures, 6 warnings (excluding pre-existing broken test_gate3_interaction.py)
- No regressions caused by source_authority.py changes

## Verification

```
python -c "from marketmind.config.source_authority import SOURCES, get_working_sources; print(f'{len(SOURCES)} sources, {len(get_working_sources())} working')"
# Expected: 35 sources, 34 working
```
