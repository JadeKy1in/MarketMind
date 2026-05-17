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
           "https://news.research.stlouisfed.org/feed/", "rss", 0.99, 2.0),
    # ^ FRED economic-data RSS was discontinued; replaced with St. Louis Fed Research blog.
    #   Raw FRED data is available via macro_data.py (FRED API).
    Source("BLS", SourceTier.PRIMARY,
           "https://api.bls.gov/publicAPI/v2/timeseries/data/", "bls_api", 0.99, 2.0,
           requires_auth=False, status=SourceStatus.UNTESTED),
    # ^ Switched from RSS (blocked by Cloudflare 403) to BLS Public Data API v2.
    #   Free registration key at https://data.bls.gov/registrationEngine/ (optional,
    #   increases daily quota from 25 to 500). Provides CPI, employment, PPI, wages.
    #   Implementation TBD — macro_data.py or dedicated pipeline/bls_fetcher.py.
    Source("SEC EDGAR", SourceTier.PRIMARY,
           "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom&count=20",
           "rss", 0.99, 1.0),
    # ^ Now requires User-Agent: "OrgName/version (email)" per SEC developer policy.
    Source("Federal Reserve", SourceTier.PRIMARY,
           "https://www.federalreserve.gov/feeds/press_all.xml", "rss", 0.99, 2.0),
    # ^ Fixed: was directory listing (feeds/); now points to actual press releases RSS XML.
    Source("CFTC COT", SourceTier.PRIMARY,
           "https://www.cftc.gov/dea/newcot/c_disagg.txt", "api", 0.99, 1.0),
    # ^ feed_type="api" is correct — handled by macro_data.py, not RSS parser.

    # === RELIABLE tier — commercial news aggregators ===
    Source("NewsAPI", SourceTier.RELIABLE, None, "api", 0.90, 10.0, True),
    Source("GNews", SourceTier.RELIABLE, None, "api", 0.85, 10.0, True),
    Source("MarketWatch", SourceTier.RELIABLE,
           "https://feeds.marketwatch.com/marketwatch/topstories", "rss", 0.80, 2.0),
    Source("Investing.com", SourceTier.RELIABLE,
           "https://www.investing.com/rss/news.rss", "rss", 0.75, 1.0),

    # === FRAGILE tier — regional / specialised feeds ===
    Source("Nikkei Asia", SourceTier.FRAGILE,
           "https://news.google.com/rss/search?q=Japan+business+markets+stocks&hl=en-US&gl=US&ceid=US:en",
           "rss", 0.70, 1.0, status=SourceStatus.UNTESTED),
    # ^ Original Nikkei Asia RSS discontinued (newsletter-only).
    #   Replaced with Google News RSS search for "Japan business markets stocks".

    # === BEST_EFFORT tier — community / social / scrape-based ===
    Source("xcancel", SourceTier.BEST_EFFORT,
           "https://xcancel.com/FinancialTimes/rss", "rss", 0.60, 0.5),
    # ^ Fixed URL format: was generic rss.xcancel.com/ (wrong domain).
    #   Nitter RSS works via xcancel.com/{username}/rss.
    # CapitolTrades removed — HTML scraping not implemented per design spec Track B,
    #   BFF API (bff.capitoltrades.com) returned 503. Fallback: tools/manual_congress.py.
    Source("Bluesky", SourceTier.BEST_EFFORT, None, "bluesky", 0.60, 0.5, True),
]


def get_working_sources() -> list[Source]:
    return [s for s in SOURCES if s.is_available]


def get_sources_by_tier(tier: SourceTier) -> list[Source]:
    return [s for s in SOURCES if s.tier == tier]
