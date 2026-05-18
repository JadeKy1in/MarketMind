"""Source authority tiers and health tracking."""
from dataclasses import dataclass
from enum import IntEnum


class SourceTier(IntEnum):
    PRIMARY = 1
    RELIABLE = 2
    FRAGILE = 3
    BEST_EFFORT = 4


class SourceStatus(IntEnum):
    WORKING = 1
    DEGRADED = 2
    DEAD = 3
    UNTESTED = 0


@dataclass
class Source:
    name: str
    tier: SourceTier
    url: str | None = None
    feed_type: str = "rss"
    reliability: float = 0.5
    rate_limit_rps: float = 1.0
    requires_auth: bool = False
    status: SourceStatus = SourceStatus.UNTESTED
    last_checked: str | None = None
    consecutive_failures: int = 0

    @property
    def is_available(self) -> bool:
        return self.status in (SourceStatus.WORKING, SourceStatus.DEGRADED)


SOURCES: list[Source] = [
    # === PRIMARY tier — institutional economic/financial data sources ===
    Source("FRED", SourceTier.PRIMARY,
           "https://news.research.stlouisfed.org/feed/", "rss", 0.99, 2.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ FRED economic-data RSS was discontinued; replaced with St. Louis Fed Research blog.
    #   Raw FRED data is available via macro_data.py (FRED API). RSS provides research
    #   context articles, not raw data series.

    Source("BLS", SourceTier.PRIMARY,
           "https://api.bls.gov/publicAPI/v2/timeseries/data/", "bls_api", 0.99, 2.0,
           requires_auth=False,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ BLS Public Data API v2 implemented in pipeline/bls_fetcher.py.
    #   Fetches CPI, Core CPI, Unemployment Rate, PPI. Free API, no key required
    #   (registration increases daily quota from 25 to 500). Scout dispatch path
    #   wired at scout.py:220 (feed_type="bls_api").

    Source("SEC EDGAR", SourceTier.PRIMARY,
           "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom&count=20",
           "rss", 0.99, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Now requires User-Agent: "OrgName/version (email)" per SEC developer policy.
    #   Scout sets User-Agent header on all RSS requests.

    Source("Federal Reserve", SourceTier.PRIMARY,
           "https://www.federalreserve.gov/feeds/press_all.xml", "rss", 0.99, 2.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Official Fed press releases RSS XML (was directory listing; now correct endpoint).

    Source("CFTC COT", SourceTier.PRIMARY,
           "https://publicreporting.cftc.gov/resource/6dca-aqww.json", "api", 0.99, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ CFTC COT data fetched via SODA API by gateway/macro_data.py (get_cot_data).
    #   Not fetched through scout RSS pipeline — feed_type="api" is a documentation
    #   marker. URL updated from legacy .txt to SODA JSON endpoint.

    # === EU official sources ===
    Source("ECB Press Releases", SourceTier.PRIMARY,
           "https://www.ecb.europa.eu/rss/press.html", "rss", 0.99, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ HEADLINES_ONLY — RSS returns 15 entries with empty <description> tags.
    #   Titles still provide topic awareness for ECB activity. Supplemented by
    #   ECB Publications below for full-text coverage.

    Source("ECB Publications", SourceTier.PRIMARY,
           "https://www.ecb.europa.eu/rss/pub.html", "rss", 0.99, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ FULL_CONTENT — Economic Bulletin, Financial Stability Review, research
    #   papers. Supplements HEADLINES_ONLY ECB Press Releases above.
    # ECB (via Google News) removed 2026-05-18 — redundant with Press Releases +
    #   Publications + EC Press Corner coverage.

    Source("EC Press Corner", SourceTier.PRIMARY,
           "https://ec.europa.eu/commission/presscorner/api/rss", "rss", 0.95, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),

    # === Emerging Markets official ===
    Source("Brazil BCB Copom", SourceTier.PRIMARY,
           "https://www.bcb.gov.br/api/feed/sitebcb/sitefeedsen/copomstatements",
           "rss", 0.99, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Official Banco Central do Brasil Copom statements RSS feed.

    # === RELIABLE tier — commercial news aggregators ===
    Source("NewsAPI", SourceTier.RELIABLE, None, "api", 0.90, 10.0, True,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Handled by _fetch_newsapi() in scout.py. Requires NEWSAPI_KEY env var.
    #   Gracefully degrades (empty results) if key not configured.

    Source("GNews", SourceTier.RELIABLE, None, "api", 0.85, 10.0, True,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Handled by _fetch_gnews() in scout.py. Requires GNEWS_API_KEY env var.

    Source("MarketWatch", SourceTier.RELIABLE,
           "https://feeds.content.dowjones.io/public/rss/mw_topstories", "rss", 0.80, 2.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Official Dow Jones MarketWatch RSS feed.
    # Investing.com removed — RSS returns headlines only (0 summaries), GNews covers same ground

    # === China sources ===
    Source("China Daily Bizchina", SourceTier.RELIABLE,
           "http://www.chinadaily.com.cn/rss/bizchina_rss.xml", "rss", 0.75, 2.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ HTTP (not HTTPS) — Chinese state media RSS; may not redirect to HTTPS.

    Source("CGTN Business", SourceTier.RELIABLE,
           "https://www.cgtn.com/subscribe/rss/section/business.xml", "rss", 0.70, 2.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),

    Source("SCMP Business", SourceTier.RELIABLE,
           "https://www.scmp.com/rss/4/feed/", "rss", 0.80, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),

    # === EU / Global ===
    Source("Financial Times", SourceTier.RELIABLE,
           "https://www.ft.com/world?format=rss", "rss", 0.90, 2.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ FT has a paywall — RSS summaries may be truncated for non-subscribers.

    # === FRAGILE tier — regional / specialised feeds ===
    Source("Nikkei Asia", SourceTier.FRAGILE,
           "https://news.google.com/rss/search?q=Nikkei+Asia+Japan+business+economy+markets&hl=en-US&gl=US&ceid=US:en",
           "rss", 0.70, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Original Nikkei Asia RSS discontinued (newsletter-only).
    #   Replaced with Google News proxy targeting Nikkei Asia Japan business coverage.

    # === China / Asia FRAGILE ===
    Source("Xinhua English", SourceTier.FRAGILE,
           "http://www.xinhuanet.com/english/rss/worldrss.xml",
           "rss", 0.65, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ HTTP (not HTTPS) — confirmed working 2026-05-18 (20 entries, FULL_CONTENT).

    # === EU FRAGILE ===
    Source("EUobserver", SourceTier.FRAGILE,
           "https://euobserver.com/feed/", "rss", 0.65, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Standard WordPress RSS feed.

    # === Emerging Markets ===
    # Turkey TCMB removed — RSS returns headlines only. Google News proxies cover EM.

    # === BEST_EFFORT tier — Google News proxies (aggregated, not first-party) ===
    # All Google News RSS proxies use an UNOFFICIAL legacy endpoint
    # (news.google.com/rss/search). Google could discontinue at any time.
    # All return title + snippet per entry. Search queries are tuned for
    # English-language financial/economic news.

    # 🇨🇳 China — Google News proxies removed 2026-05-18 (redundant with 4 direct
    # China RSS sources: China Daily, CGTN, SCMP, Xinhua)
    # - Caixin (via Google News): Caixin official RSS returns 406; direct China
    #   sources cover same ground
    # - PBOC (via Google News): PBOC news appears in all China direct sources
    # - China Economy (via Google News): redundant with macro data + China sources

    # 🇪🇺 EU
    Source("Euronews Business", SourceTier.RELIABLE,
           "https://www.euronews.com/rss?format=mrss&level=theme&name=business", "rss", 0.80, 2.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Official Euronews MRSS feed — FULL_CONTENT, 50 entries. Replaced Google News
    #   proxy (2026-05-18). MRSS format includes media:content tags for images.
    #   Also available: general news feed (level=theme&name=news).
    # Eurostat (via Google News) removed 2026-05-18 — redundant with ECB Press
    #   Releases + ECB Publications + EC Press Corner coverage of EU data.

    # 🌍 Emerging Markets
    Source("India RBI Press Releases", SourceTier.PRIMARY,
           "https://www.rbi.org.in/pressreleases_rss.xml", "rss", 0.99, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Official Reserve Bank of India RSS — FULL_CONTENT, 10 entries, 1700+ chars
    #   per description. Covers monetary policy, MPC statements, regulatory actions.
    #   Replaced Google News proxy (2026-05-18).

    Source("South Africa SARB (via Google News)", SourceTier.BEST_EFFORT,
           "https://news.google.com/rss/search?q=South+Africa+Reserve+Bank+SARB+monetary+policy+repo+rate&hl=en-US&gl=US&ceid=US:en",
           "rss", 0.55, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ KEPT 2026-05-18 — only Africa EM central bank source. SARB has RSS feeds
    #   page but uses JS-based subscribe (no direct XML URL). Google News proxy
    #   provides the only programmatic access to SARB coverage.

    # World Bank (via Google News) removed 2026-05-18 — development economics,
    #   not market-moving. Covered by general financial news.
    # IMF (via Google News) removed 2026-05-18 — IMF RSS URLs serve HTML pages
    #   (React SPA), not actual RSS feeds. IMF news covered by Financial Times +
    #   general financial sources.

    Source("OPEC Oil (via Google News)", SourceTier.BEST_EFFORT,
           "https://news.google.com/rss/search?q=OPEC+oil+production+crude+Saudi+monthly+report&hl=en-US&gl=US&ceid=US:en",
           "rss", 0.55, 1.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ KEPT 2026-05-18 — OPEC has NO official RSS feed. Production quota decisions
    #   are market-critical. Google News proxy is the only programmatic source for
    #   OPEC policy news. Supplemented by EIA inventory data + CFTC COT positioning.

    # === BEST_EFFORT tier — social / community ===
    # xcancel removed — only 1 article, FT direct RSS already covers (Financial Times #24).
    # CapitolTrades removed — HTML scraping not implemented per design spec Track B,
    #   BFF API (bff.capitoltrades.com) returned 503. Fallback: tools/manual_congress.py.

    Source("Bluesky", SourceTier.BEST_EFFORT, None, "bluesky", 0.60, 0.5, True,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ Handled by pipeline/social_sources.py (fetch_bluesky_posts).
    #   Requires BLUESKY_USERNAME + BLUESKY_APP_PASSWORD env vars.
    #   AT Protocol endpoint, not RSS.

    # === BEST_EFFORT tier — asset-specific Google News proxies ===
    # Precious Metals, Agriculture, Natural Gas, Healthcare, Crypto (all via Google
    # News) removed 2026-05-18:
    # - Precious Metals: covered by MarketWatch + general financial RSS
    # - Agriculture: not in primary asset universe
    # - Natural Gas: covered by EIA API data + CFTC COT NG futures
    # - Healthcare: sector news, not macro-focused
    # - Crypto: replaced by CoinTelegraph direct RSS (RELIABLE tier)

    Source("CoinTelegraph", SourceTier.RELIABLE,
           "https://cointelegraph.com/rss", "rss", 0.75, 2.0,
           status=SourceStatus.WORKING, last_checked="2026-05-18"),
    # ^ CoinTelegraph official RSS — FULL_CONTENT, 30 entries, 130+ chars per
    #   description. Replaced Crypto (via Google News) proxy (2026-05-18).
    #   Covers Bitcoin, crypto regulation, ETFs, blockchain industry news.
]


def get_working_sources() -> list[Source]:
    return [s for s in SOURCES if s.is_available]


def get_sources_by_tier(tier: SourceTier) -> list[Source]:
    return [s for s in SOURCES if s.tier == tier]
