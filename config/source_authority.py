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
    Source("FRED", SourceTier.PRIMARY, "https://fred.stlouisfed.org/rss/", "rss", 0.99, 2.0),
    Source("BLS", SourceTier.PRIMARY, "https://www.bls.gov/feed/", "rss", 0.99, 2.0),
    Source("SEC EDGAR", SourceTier.PRIMARY, "https://www.sec.gov/cgi-bin/browse-edgar", "rss", 0.99, 1.0),
    Source("Federal Reserve", SourceTier.PRIMARY, "https://www.federalreserve.gov/feeds/", "rss", 0.99, 2.0),
    Source("CFTC COT", SourceTier.PRIMARY, "https://www.cftc.gov/dea/newcot/c_disagg.txt", "api", 0.99, 1.0),
    Source("NewsAPI", SourceTier.RELIABLE, None, "api", 0.90, 10.0, True),
    Source("GNews", SourceTier.RELIABLE, None, "api", 0.85, 10.0, True),
    Source("MarketWatch", SourceTier.RELIABLE, "https://feeds.marketwatch.com/marketwatch/topstories", "rss", 0.80, 2.0),
    Source("Investing.com", SourceTier.RELIABLE, "https://www.investing.com/rss/news.rss", "rss", 0.75, 1.0),
    Source("Nikkei Asia", SourceTier.FRAGILE, "https://asia.nikkei.com/rss/feed/nikkei-asia-news", "rss", 0.70, 1.0),
    Source("xcancel", SourceTier.BEST_EFFORT, "https://rss.xcancel.com/", "rss", 0.60, 0.5),
    Source("CapitolTrades", SourceTier.BEST_EFFORT, "https://www.capitoltrades.com/", "html", 0.65, 0.5),
]


def get_working_sources() -> list[Source]:
    return [s for s in SOURCES if s.is_available]


def get_sources_by_tier(tier: SourceTier) -> list[Source]:
    return [s for s in SOURCES if s.tier == tier]
