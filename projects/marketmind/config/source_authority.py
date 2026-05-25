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
    # ── US / Americas ──────────────────────────────────────────────
    Source("CNBC Top News", SourceTier.PRIMARY, "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "rss", 0.88, 2.0),
    Source("Yahoo Finance", SourceTier.PRIMARY, "https://finance.yahoo.com/news/rssindex", "rss", 0.85, 2.0, status=SourceStatus.DEGRADED),
    Source("Bloomberg Markets", SourceTier.PRIMARY, "https://feeds.bloomberg.com/markets/news.rss", "rss", 0.90, 2.0),
    Source("MarketWatch", SourceTier.RELIABLE, "https://feeds.content.dowjones.io/public/rss/mw_topstories", "rss", 0.80, 2.0),
    Source("NYT Business", SourceTier.PRIMARY, "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "rss", 0.90, 2.0),
    Source("NYT Economy", SourceTier.PRIMARY, "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml", "rss", 0.90, 2.0),
    Source("Seeking Alpha", SourceTier.RELIABLE, "https://seekingalpha.com/market-news.xml", "rss", 0.78, 2.0),
    Source("Reuters (via Google News)", SourceTier.PRIMARY, "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB", "rss", 0.85, 2.0),

    # ── China / Greater China ──────────────────────────────────────
    Source("SCMP Business", SourceTier.RELIABLE, "https://www.scmp.com/rss/4/feed/", "rss", 0.80, 2.0),
    Source("China Money Network", SourceTier.RELIABLE, "https://www.chinamoneynetwork.com/feed/", "rss", 0.72, 1.0),  # Replaces Caixin — free English China finance/VC news RSS
    Source("Xinhua Finance", SourceTier.RELIABLE, "http://www.xinhuanet.com/english/rss/worldrss.xml", "rss", 0.72, 2.0),

    # ── Japan / Asia Pacific ───────────────────────────────────────
    Source("Nikkei Asia", SourceTier.RELIABLE, "https://asia.nikkei.com/rss/feed/nar", "rss", 0.80, 2.0),

    # ── India ───────────────────────────────────────────────────────
    Source("Economic Times Markets", SourceTier.RELIABLE, "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "rss", 0.75, 2.0),

    # ── Europe ─────────────────────────────────────────────────────
    Source("FT World News", SourceTier.PRIMARY, "https://www.ft.com/world?format=rss", "rss", 0.90, 2.0),
    Source("ECB Press", SourceTier.PRIMARY, "https://www.ecb.europa.eu/rss/press.html", "rss", 0.95, 2.0),
    Source("DW Business", SourceTier.RELIABLE, "http://rss.dw.de/rdf/rss-en-bus", "rss", 0.80, 2.0),
    Source("Euronews Economy", SourceTier.RELIABLE, "https://www.euronews.com/rss?format=mrss&level=theme&name=business", "rss", 0.75, 1.0),

    # ── Middle East / Energy ───────────────────────────────────────
    Source("Al Jazeera Economy", SourceTier.RELIABLE, "https://www.aljazeera.com/xml/rss/all.xml", "rss", 0.72, 1.0),
    Source("OilPrice.com", SourceTier.RELIABLE, "https://oilprice.com/rss/main", "rss", 0.82, 2.0),

    # ── Russia / Eastern Europe ────────────────────────────────────
    Source("RT Business", SourceTier.FRAGILE, "https://www.rt.com/rss/business/", "rss", 0.55, 1.0),

    # ── Latin America ──────────────────────────────────────────────
    Source("MercoPress", SourceTier.BEST_EFFORT, "https://en.mercopress.com/rss/", "rss", 0.45, 1.0),

    # ── Crypto / Digital Assets ────────────────────────────────────
    Source("CoinDesk", SourceTier.RELIABLE, "https://www.coindesk.com/arc/outboundfeeds/rss", "rss", 0.82, 2.0),
    Source("CoinTelegraph", SourceTier.RELIABLE, "https://cointelegraph.com/rss", "rss", 0.78, 2.0),

    # ── Global / Multi-region ─────────────────────────────────────
    Source("BBC Business", SourceTier.PRIMARY, "https://feeds.bbci.co.uk/news/business/rss.xml", "rss", 0.88, 2.0),

    # ── Commodities / Futures ─────────────────────────────────────
    Source("Investing.com", SourceTier.BEST_EFFORT, "https://www.investing.com/rss/news_1063.rss", "rss", 0.40, 1.0),

    # ── Social Media (BEST_EFFORT) ────────────────────────────────
    # Reliability weights are domain-reasoned, not backtest-optimized (Law 3 compliance).
    # Swiss Finance Institute (2026): finfluencer picks = -2.3% returns; fading them = +6.8% alpha.
    # Social sentiment captures positioning/crowding — structurally independent from news flow.
    # ApeWisdom: 0.15 — anonymous, unverifiable, prone to manipulation. ApeWisdom is a hobby
    #   project with no SLA, no versioned API, and no per-account data for manipulation detection.
    # Bluesky: 0.20 — identified accounts, smaller sample, demographic selection bias (users who
    #   migrated from X due to content moderation concerns). AT Protocol is open and free.
    # Truth Social (Trump): 0.15 — single-person source, ~90% noise ratio, dependent on
    #   third-party RSS aggregator (trumpstruth.org by Defending Democracy Together).
    #   BUT: when it fires on investment-relevant content, it is a LEADING indicator of
    #   market-moving policy — a unique capability no other source provides.
    # Reddit WSB: Reddit's own RSS feed — free, no auth, returns 200
    Source("Reddit WSB", SourceTier.BEST_EFFORT,
           "https://www.reddit.com/r/wallstreetbets/.rss", "rss", 0.15, 1.0),
    # Bluesky: requires BLUESKY_USERNAME + BLUESKY_APP_PASSWORD in .env
    Source("Bluesky Social", SourceTier.BEST_EFFORT,
           "https://bsky.social/xrpc/com.atproto.repo.searchPosts?q={QUERY}", "api", 0.20, 1.0),
    Source("Truth Social (Trump)", SourceTier.BEST_EFFORT,
           "https://trumpstruth.org/feed", "rss", 0.15, 1.0),

    # ── Insider / Smart Money (Phase G Layer 4) ─────────────────────
    # Congress trades revived 2026-05-25 via @anguslin/mcp-capitol-trades
    # (real-time HTML scraping of capitoltrades.com via Node.js MCP subprocess).
    Source("Congress Trades", SourceTier.BEST_EFFORT,
           "https://www.capitoltrades.com/trades",
           "congress_api", 0.20, 1.0, status=SourceStatus.WORKING),
    Source("SEC Form 4", SourceTier.BEST_EFFORT,
           "", "sec_form4", 0.20, 1.0),
    Source("SEC 13F", SourceTier.BEST_EFFORT,
           "", "sec_13f", 0.15, 1.0),


    # ── API-based (require keys) ──────────────────────────────────
    Source("NewsAPI", SourceTier.RELIABLE, "https://newsapi.org/v2/top-headlines?country=us&category=business&apiKey={API_KEY}", "api", 0.90, 10.0, True),
    Source("GNews", SourceTier.RELIABLE, "https://gnews.io/api/v4/top-headlines?category=business&lang=en&country=us&apikey={API_KEY}", "api", 0.85, 10.0, True),
]


def get_working_sources() -> list[Source]:
    return [s for s in SOURCES if s.is_available]


def get_sources_by_tier(tier: SourceTier) -> list[Source]:
    return [s for s in SOURCES if s.tier == tier]
