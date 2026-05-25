# H2: Bluesky Social Media Content Quality Assessment

**Date**: 2026-05-17
**Assessor**: Claude Agent
**Scope**: MarketMind pipeline/social_sources.py Bluesky integration

## 1. Current Bluesky Setup Summary

### Authentication
- AT Protocol via `com.atproto.server.createSession`
- Credentials from env vars: `BLUESKY_USERNAME` + `BLUESKY_APP_PASSWORD`
- Token cached at module level for process lifetime
- Credentials are configured (`.env` has `jadekylin.bsky.social`)

### Search Query (hardcoded in `fetch_bluesky_posts`)
```
finance OR stocks OR market OR $AAPL OR $MSFT OR $NVDA OR $TSLA
```
- Only 4 tickers (AAPL, MSFT, NVDA, TSLA) — no integration with `config/asset_universe.py`
- Generic terms ("finance", "stocks", "market") will return vast amounts of low-signal content
- Query is a single string constant with no dynamic construction

### Fetch Parameters
- Limit: 10 posts per call
- Endpoint: `app.bsky.feed.searchPosts`
- Timeout: 30 seconds
- No pagination, no cursor, no date range filtering

### Post Processing
- Takes raw Bluesky API response, extracts: `record.text`, `author.handle`, `post.indexedAt`
- Generates ID via `sha256(f"bluesky:{handle}:{text[:80]}").hexdigest()[:16]`
- Assigns reliability from `source.reliability` (typically 0.5 default)
- Content type: `"social_mention"`
- Summary: first 500 chars of post text

### What is NOT Done
- No follower count check
- No engagement metrics (likes, reposts, replies)
- No account age or verification status check
- No content quality scoring
- No spam/bot detection
- No language filtering
- No sentiment analysis
- No relevance ranking within results
- No deduplication against other news sources

## 2. Critical Issues Identified

### ISSUE 1 (BLOCKER): Bluesky is NOT in the SOURCES list

**File**: `config/source_authority.py`

The canonical `SOURCES` list contains 12 sources but does NOT include a "Bluesky Social" entry. This means:
- `scout.py`'s `fetch_all_sources()` iterates over `SOURCES` and will never call `fetch_bluesky_posts()`
- The `source_health_check.py` tests for `source.name == "Bluesky Social"` (line 52) but this source does not exist in the list
- **The entire `fetch_bluesky_posts()` function is dead code** — defined but never called by any pipeline module

**Verification**: `grep` for `fetch_bluesky` across the entire project returns only the definition in `social_sources.py` — zero call sites.

### ISSUE 2 (CRITICAL): Zero Content Quality Filtering

If Bluesky were wired into the pipeline, every post returned by the search API would be treated as a valid investment signal with no quality gates:

| Filter Type | Status |
|---|---|
| Spam detection | Not implemented |
| Bot account filtering | Not implemented |
| Follower threshold | Not implemented |
| Engagement quality (likes/reposts ratio) | Not implemented |
| Account age verification | Not implemented |
| Verified account preference | Not implemented |
| Language detection | Not implemented |
| Relevance scoring | Not implemented |

This means a Bluesky post saying "I love NVDA stock emoji emoji rocket" from a 3-follower account created yesterday would carry the same weight as any other source in the pipeline.

### ISSUE 3 (HIGH): Hardcoded Ticker List

The query only covers 4 tickers (`$AAPL`, `$MSFT`, `$NVDA`, `$TSLA`). MarketMind has a full `config/asset_universe.py` with a comprehensive tradable asset matrix. The query should be dynamically constructed from the asset universe, not hardcoded to 4 mega-caps.

### ISSUE 4 (HIGH): Generic Keywords Are Noise Magnets

Terms like "finance", "stocks", and "market" are extremely generic. On a social platform like Bluesky, these will return:
- Personal finance advice ("how I saved $100 on groceries")
- Crypto scams and pump-and-dump promotions
- Political commentary about "the market"
- Self-promotion and newsletter signups
- Memes and jokes

Without filtering, this is overwhelmingly noise.

### ISSUE 5 (MEDIUM): No Test Coverage

Zero tests reference Bluesky or `social_sources.py`. The test directory has no `test_social_sources.py` or any test mentioning `fetch_bluesky`.

### ISSUE 6 (MEDIUM): Health Check is Content-Blind

`source_health_check.py` (line 52-82) only verifies that the Bluesky API returns posts (count > 0). It does not assess:
- Whether returned posts are relevant to investing
- Whether posts contain actual ticker mentions vs. generic terms
- Post quality or account credibility

### ISSUE 7 (LOW): Manual Input as Implicit Fallback

`tools/manual_input.py` has a `input_bluesky()` function that accepts copy-pasted posts — suggesting the developers knew the automated pipeline was insufficient and built a manual workaround.

## 3. Signal-to-Noise Analysis

Bluesky is fundamentally a general-purpose social network, not a financial data platform. Compared to MarketMind's other sources:

| Source | Signal Type | Reliability |
|---|---|---|
| SEC EDGAR (Tier 1) | Regulatory filings, insider trades | 0.99 |
| FRED/BLS (Tier 1) | Official economic data | 0.99 |
| MarketWatch (Tier 2) | Curated financial news | 0.80 |
| NewsAPI/GNews (Tier 2) | Aggregated news with keyword filtering | 0.85-0.90 |
| **Bluesky (not listed)** | **Unfiltered social media** | **0.50 (default)** |

Bluesky's raw search API returns whatever matches the query string — no editorial curation, no fact-checking, no source vetting. At best, it could serve as a **retail sentiment indicator** (and MarketMind already notes in the ApeWisdom docstring that retail sentiment is a **contrarian indicator** — fading finfluencer picks yields +6.8% alpha).

## 4. Suggested Improvements

### Priority 1: Decide Whether to Keep Bluesky

Before investing in improvements, answer the strategic question: **Does Bluesky provide unique signal that MarketMind's other sources don't?**

Arguments against:
- Reddit WSB RSS already covers retail sentiment
- SEC EDGAR and CapitolTrades cover actual insider/ institutional activity
- NewsAPI and GNews cover curated financial news
- Bluesky has no unique financial data advantage

Arguments for:
- Real-time sentiment pulse (faster than RSS feeds)
- Emerging narratives before they hit mainstream news
- Crypto and alternative asset discussion not covered by traditional sources

### Priority 2: If Keeping — Wire Into Pipeline

1. Add `Source("Bluesky Social", SourceTier.BEST_EFFORT, feed_type="api", reliability=0.35, requires_auth=True)` to the `SOURCES` list in `source_authority.py`
2. Add a Bluesky case to `fetch_source()` in `scout.py` that calls `fetch_bluesky_posts()`

### Priority 3: Add Content Quality Filters

Minimum viable filtering before any post enters the pipeline:
```
1. MINIMUM_FOLLOWERS: 100 (require accounts with some credibility)
2. MINIMUM_LIKES: 3 (filter pure noise)
3. TICKER_REQUIRED: true (must mention $TICKER from asset universe)
4. MIN_POST_LENGTH: 50 chars (filter one-word posts)
5. BLOCKED_KEYWORDS: ["moon", "pump", "dump", "1000x", "airdrop", "giveaway", "presale"]
```

### Priority 4: Dynamic Query Construction

Build the Bluesky query from `config/asset_universe.py`:
- Rotate through asset universe tickers in batches
- Use `$TICKER` format with OR operators
- Cap at Bluesky's query length limit (likely ~512 chars)
- Cycle through different ticker batches on each run

### Priority 5: Add Tests

Create `tests/test_pipeline/test_social_sources.py` with:
- Mock Bluesky API responses
- Test that spam posts are filtered
- Test that posts without ticker mentions are filtered
- Test authentication failure handling
- Test empty response handling

### Priority 6: Health Check Enhancement

Extend `source_health_check.py` to report:
- Average post length
- Number of posts containing actual ticker mentions
- Account follower distribution (min, max, median)
- Percentage of posts with URLs (likely spam indicator)

## 5. Summary

Bluesky integration is currently **dead code** — the function exists but is never called because the source is not in the canonical `SOURCES` list. Even if wired in, the content quality filtering is nonexistent, the hardcoded query is too narrow and too generic simultaneously, and there are zero tests. The integration needs a strategic decision on whether Bluesky provides unique value before investing in the pipeline wiring and quality filters described above.
