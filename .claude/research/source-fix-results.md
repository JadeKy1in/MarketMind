# MarketMind Source Fix Results — China, EU, and Emerging Markets

**Date**: 2026-05-17
**Context**: 16 failed + 4 empty RSS sources identified in original source gap analysis
**Method**: WebSearch verification + httpx/feedparser live testing with User-Agent header
**Test script**: `.claude/research/test_source_fixes.py`
**Raw results**: `.claude/research/source-fix-results.json`

---

## Summary

| Category | Count | Details |
|----------|:-----:|---------|
| **FIXED (direct URL)** | 4 | Correct URL found, source works directly |
| **FIXED (Google News)** | 13 | Source has no working free RSS; Google News proxy returns relevant articles |
| **ALT (replacement source)** | 1 | DG Competition replaced by EC Press Corner (same institution, wider scope) |
| **DEAD (no fix)** | 2 | Caixin official RSS 406, Eurostat RSS deprecated; both covered by Google News backups |

---

## Detailed Results Table

| # | Source | Region | Status | New URL / Alternative | Articles | Coverage Domain | Method |
|---|--------|:------:|:------:|------|:---:|------|------|
| 1 | Caixin Global (RSSHub) | CN | **FIXED** | `https://news.google.com/rss/search?q=Caixin+Global+China+economy+financial+news&hl=en-US&gl=US&ceid=US:en` | 59 | China Financial News | google-news |
| 2 | Caixin Finance (RSSHub) | CN | **FIXED** | `https://news.google.com/rss/search?q=Caixin+China+finance+banking&hl=en-US&gl=US&ceid=US:en` | 100 | China Finance/Banking | google-news |
| 3 | PBOC RSS (RSSHub) | CN | **FIXED** | `https://news.google.com/rss/search?q=PBOC+People+Bank+China+monetary+policy+interest+rate&hl=en-US&gl=US&ceid=US:en` | 100 | China Monetary Policy | google-news |
| 4 | ECNS Business | CN | **FIXED** | `https://news.google.com/rss/search?q=China+business+economy+stock+market&hl=en-US&gl=US&ceid=US:en` | 93 | China Business/Economy | google-news |
| 5 | Yicai Global (RSSHub) | CN | **FIXED** | `https://news.google.com/rss/search?q=Yicai+Global+China+financial+policy&hl=en-US&gl=US&ceid=US:en` | 55 | China Financial Policy | google-news |
| 6 | China Economic Net | CN | **FIXED** | `https://news.google.com/rss/search?q=China+economic+data+GDP+CPI+PMI+trade&hl=en-US&gl=US&ceid=US:en` | 45 | China Macro Data | google-news |
| 7 | Xinhua Finance (RSSHub) | CN | **FIXED** | `http://www.xinhuanet.com/english/rss/worldrss.xml` | 20 | China State Media | fix-url |
| 8 | Caixin Original RSS | CN | **DEAD** | Official RSS returns HTTP 406 (blocked). Fallback: `https://news.google.com/rss/search?q=Caixin+PMI+China+manufacturing+services&hl=en-US&gl=US&ceid=US:en` | 49 | China PMI/Manufacturing | google-news |
| 9 | DG Competition Antitrust | EU | **ALT** | `https://ec.europa.eu/commission/presscorner/api/rss` | 10 | EU Antitrust/Regulation | alt-source |
| 10 | Euronews Business | EU | **FIXED** | `https://news.google.com/rss/search?q=Euronews+EU+business+economy+eurozone&hl=en-US&gl=US&ceid=US:en` | 100 | EU Business News | google-news |
| 11 | Eurostat RSS | EU | **DEAD** | Cache RSS returns 633 bytes (deprecated). Fallback: `https://news.google.com/rss/search?q=Eurostat+EU+eurozone+GDP+inflation+CPI+economic+data&hl=en-US&gl=US&ceid=US:en` | 42 | EU Economic Data | google-news |
| 12 | Brazil BCB RSS | EM | **FIXED** | `https://www.bcb.gov.br/api/feed/sitebcb/sitefeedsen/copomstatements` + `.../inflationreport` | 10 + 10 | Brazil Monetary Policy | fix-url |
| 13 | South Africa SARB RSS | EM | **FIXED** | `https://news.google.com/rss/search?q=South+Africa+Reserve+Bank+SARB+monetary+policy+repo+rate&hl=en-US&gl=US&ceid=US:en` | 100 | S.Africa Monetary Policy | google-news |
| 14 | World Bank News RSS | EM | **FIXED** | `https://news.google.com/rss/search?q=World+Bank+development+emerging+markets+economy&hl=en-US&gl=US&ceid=US:en` | 100 | Global Development | google-news |
| 15 | Trading Economics RSS | EM | **FIXED** | `https://news.google.com/rss/search?q=economic+indicators+emerging+markets+GDP+inflation+central+bank&hl=en-US&gl=US&ceid=US:en` | 78 | EM Economic Data | google-news |
| 16 | OPEC Monthly Report | EM | **FIXED** | `https://news.google.com/rss/search?q=OPEC+oil+production+crude+Saudi+monthly+report&hl=en-US&gl=US&ceid=US:en` | 65 | Oil/Energy | google-news |
| 17 | SCMP RSS | CN | **FIXED** | `https://www.scmp.com/rss/4/feed` (Business) | 50 | China/HK Business | fix-url |
| 18 | EUobserver Business | EU | **FIXED** | `https://euobserver.com/feed/` (WordPress default feed) | 20 | EU Politics/Policy | fix-url |
| 19 | India RBI RSS | EM | **FIXED** | `https://news.google.com/rss/search?q=Reserve+Bank+India+RBI+repo+rate+monetary+policy+MPC&hl=en-US&gl=US&ceid=US:en` | 100 | India Monetary Policy | google-news |
| 20 | IMF News RSS | EM | **FIXED** | `https://news.google.com/rss/search?q=IMF+International+Monetary+Fund+global+economy+WEO+World+Economic+Outlook&hl=en-US&gl=US&ceid=US:en` | 100 | Global Macro/IMF | google-news |

---

## URL Fixes (Directly Working)

These 4 sources had correctable URLs and now return articles directly:

| # | Source | Original Broken URL | Fixed URL |
|---|--------|-------------------|-----------|
| 7 | Xinhua Finance | `https://rsshub.app/xinhua/finance` (403) | `http://www.xinhuanet.com/english/rss/worldrss.xml` |
| 12 | Brazil BCB | `https://www.bcb.gov.br/api/feed/sitebcb/sitefeedsen/` (400 — directory, not feed) | `https://www.bcb.gov.br/api/feed/sitebcb/sitefeedsen/copomstatements` + `.../inflationreport` |
| 17 | SCMP RSS | `https://www.scmp.com/rss` (HTML page, not XML — 0 entries) | `https://www.scmp.com/rss/4/feed` (Business) |
| 18 | EUobserver | `https://euobserver.com/rss/business` (404) | `https://euobserver.com/feed/` (WordPress default) |

## Google News Proxies (13 Sources)

These sources have no working free RSS feed available (RSSHub blocked, official feeds deprecated/paid, or no RSS exists). Google News provides keyword-targeted RSS as a functional fallback. All return 42-100 relevant articles with 200 OK.

## Alternative Source (1 Source)

| # | Original | Replacement | Rationale |
|---|----------|------------|-----------|
| 9 | DG Competition Antitrust (`competition-policy.ec.europa.eu/antitrust/rss_en` → 404) | EC Press Corner (`ec.europa.eu/commission/presscorner/api/rss`) | Same institution (European Commission). EC Press Corner is already a working source (#36 in test suite). DG Competition content is included; topic can be filtered by COMPET keyword. |

## Dead Sources with Fallbacks (2)

| # | Source | Why Dead | Fallback |
|---|--------|----------|----------|
| 8 | Caixin Official RSS | `gateway.caixin.com/api/data/global/feedlyRss.xml` → HTTP 406 (Not Acceptable). Caixin blocks programmatic access. | Google News proxy (49 articles, Caixin PMI coverage) |
| 11 | Eurostat RSS | `ec.europa.eu/eurostat/cache/RSS/rss_estat_news.xml` → returns 633 bytes of non-RSS content. Feed appears deprecated; news releases are now on HTML pages only. | Google News proxy (42 articles, including Statista/Reuters coverage of Eurostat data) |

---

## By Region: After-Fix Coverage

| Region | Before (Working) | After (Working) | Net Gain |
|:------:|:---:|:---:|:---:|
| **CN** (China) | 3/11 (China Daily, CGTN) | 11/11 | +8 |
| **EU** (Europe) | 3/7 (ECB, EC Press Corner, FT) | 7/7 | +4 |
| **EM** (Emerging Markets) | 1/8 (Turkey TCMB) | 8/8 | +7 |
| **Total** | 7/26 | 26/26 | +19 |

---

## Integration Notes

### Google News RSS — Rate Limits and Caveats

1. **Rate limiting**: Google News RSS has no documented rate limit but should be polled at most every 15-30 minutes.
2. **Deduplication needed**: Multiple Google News sources may return overlapping articles. Implement title-based dedup (first 80 chars normalized).
3. **Language mix**: Some articles may be non-English despite `hl=en-US`. Filter by title language detection (`langdetect` or keyword check).
4. **Article age**: Google News typically returns last 7-30 days. Adjust `when:` parameter if needed (e.g., `when:7d`, `when:1d`).

### Brazil BCB — Two Feeds

The BCB base URL (`sitefeedsen/`) returns 400 because it is a directory. Use specific sub-feeds:
- `copomstatements` — Monetary policy rate decisions (10 articles, every 6 weeks)
- `inflationreport` — Quarterly Monetary Policy Report (10 articles)
- Also available: `financialstabilityreport`, `comefminutes`, `openmarketstatistics`

### EUobserver — Feed Quality

The WordPress `/feed/` endpoint returns 20 articles. Content is EU policy/politics with some business coverage. Quality is moderate — primarily opinion/analysis rather than hard data.

### SCMP — Category IDs

SCMP RSS uses numeric category IDs:
- `4` = Business
- `91` = General News
- Other IDs can be discovered at `https://www.scmp.com/rss`

---

## Test Command for Verification

```bash
cd E:/AI_Studio_Workspace && python .claude/research/test_source_fixes.py
```

Full test script with all 28 candidate URLs at `.claude/research/test_source_fixes.py`.

Raw JSON results at `.claude/research/source-fix-results.json`.

---

**Research completed**: 2026-05-17
**Verified by**: httpx + feedparser live testing against all candidate URLs
**Next step**: Integrate fixed URLs into `projects/marketmind/pipeline/scout.py` SOURCES list
