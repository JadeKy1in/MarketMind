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
    # True when 0 items is a normal outcome (anomaly-only or quiet-day sources), so the
    # scout report does not flag an empty result as "URL may be broken".
    zero_is_normal: bool = False
    # Reason of the most recent failed fetch (None after a successful one).
    last_error: str | None = None

    @property
    def is_available(self) -> bool:
        return self.status in (SourceStatus.WORKING, SourceStatus.DEGRADED)


# Public RSSHub mirrors, tried in this order when a source URL is on one of them
# (all returned 200 with 50 items on 2026-09-28; rssforever times out intermittently).
RSSHUB_MIRRORS: tuple[str, ...] = (
    "https://rsshub.rssforever.com",
    "https://rss.owo.nz",
    "https://rsshub.ktachibana.party",
    "https://hub.slarker.me",
)


def rss_candidate_urls(source: Source) -> list[str]:
    """URLs to try for `source`: the configured one, then the same route on other RSSHub mirrors."""
    url = source.url or ""
    for base in RSSHUB_MIRRORS:
        if url.startswith(base + "/"):
            route = url[len(base):]
            return [url] + [m + route for m in RSSHUB_MIRRORS if m != base]
    return [url]


SOURCES: list[Source] = [
    # ── US / Americas ──────────────────────────────────────────────
    Source("CNBC Top News", SourceTier.PRIMARY, "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "rss", 0.88, 2.0),
    # finance.yahoo.com/news/rssindex went stale (newest item 5 days old, 2026-09-28);
    # the S&P 500 headline feed is fresh.
    Source("Yahoo Finance", SourceTier.PRIMARY,
           "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US", "rss", 0.85, 2.0),
    Source("Bloomberg Markets", SourceTier.PRIMARY, "https://feeds.bloomberg.com/markets/news.rss", "rss", 0.90, 2.0),
    Source("MarketWatch", SourceTier.RELIABLE, "https://feeds.content.dowjones.io/public/rss/mw_topstories", "rss", 0.80, 2.0),
    Source("NYT Business", SourceTier.PRIMARY, "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "rss", 0.90, 2.0),
    Source("NYT Economy", SourceTier.PRIMARY, "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml", "rss", 0.90, 2.0),
    Source("Seeking Alpha", SourceTier.RELIABLE, "https://seekingalpha.com/market-news.xml", "rss", 0.78, 2.0),
    # Google News "Business" topic: an aggregator (Yahoo, CNBC, Reuters, Fox, WSJ, Bloomberg,
    # NYT ...), not Reuters; renamed 2026-09-28.
    Source("Google News Business", SourceTier.PRIMARY, "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB", "rss", 0.85, 2.0),

    # ── US official / first-hand (added 2026-09-27, all verified live, key-free) ──
    Source("Federal Reserve Press", SourceTier.PRIMARY, "https://www.federalreserve.gov/feeds/press_all.xml", "rss", 0.97, 2.0),
    Source("Federal Reserve Speeches", SourceTier.PRIMARY, "https://www.federalreserve.gov/feeds/speeches.xml", "rss", 0.93, 2.0),
    # Treasury's own press-release RSS paths 404/time out; its official GovDelivery topic feeds work.
    Source("US Treasury Press", SourceTier.PRIMARY, "https://public.govdelivery.com/topics/USTREAS_49/feed.rss", "rss", 0.95, 2.0),
    Source("OFAC Recent Actions", SourceTier.PRIMARY, "https://public.govdelivery.com/topics/USTREAS_61/feed.rss", "rss", 0.95, 2.0),
    Source("USTR Press", SourceTier.PRIMARY, "https://ustr.gov/rss.xml", "rss", 0.93, 2.0),
    # Federal Register documents from Commerce/BIS (export controls), USTR and Treasury/OFAC.
    Source("Federal Register (Trade & Sanctions)", SourceTier.PRIMARY,
           "https://www.federalregister.gov/api/v1/documents.rss?conditions[agencies][]=industry-and-security-bureau"
           "&conditions[agencies][]=trade-representative-office-of-united-states"
           "&conditions[agencies][]=foreign-assets-control-office&order=newest",
           "rss", 0.95, 2.0),
    # SEC 8-K current filings (Atom). URL is informational: scout._fetch_sec_edgar builds the
    # request itself and sends the SEC-required "Org contact@email" User-Agent.
    Source("SEC EDGAR 8-K", SourceTier.PRIMARY,
           "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom",
           "sec_api", 0.90, 1.0),
    # Structured data APIs → pipeline/official_data_sources.py
    Source("US Treasury Auctions", SourceTier.PRIMARY,
           "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query",
           "fiscaldata_auctions", 0.95, 1.0),
    Source("NY Fed Reference Rates", SourceTier.PRIMARY,
           "https://markets.newyorkfed.org/api/rates/all/latest.json", "nyfed_rates", 0.95, 1.0),
    # SEC full-text red-flag phrases / Fed + BLS calendars → pipeline/sources_regulatory.py
    Source("SEC EDGAR Full-Text Flags", SourceTier.PRIMARY,
           "https://efts.sec.gov/LATEST/search-index", "sec_fulltext", 0.90, 1.0),
    Source("Federal Reserve Calendar", SourceTier.PRIMARY,
           "https://www.federalreserve.gov/json/calendar.json", "fed_calendar", 0.97, 1.0),
    Source("BLS Release Calendar", SourceTier.PRIMARY,
           "https://www.bls.gov/schedule/news_release/bls.ics", "bls_calendar", 0.97, 1.0),
    # Positioning / inventory / volatility → pipeline/sources_positioning.py
    # Cboe data: 15-min delayed, personal non-commercial use only.
    Source("CFTC Commitments of Traders", SourceTier.PRIMARY, "https://publicreporting.cftc.gov/resource/6dca-aqww.json", "cftc_cot", 0.95, 1.0, zero_is_normal=True),
    Source("EIA Weekly Petroleum Status", SourceTier.PRIMARY, "https://ir.eia.gov/wpsr/table1.csv", "eia_petroleum", 0.97, 1.0, zero_is_normal=True),
    Source("EIA Natural Gas Storage", SourceTier.PRIMARY, "https://ir.eia.gov/ngs/wngsr.json", "eia_natgas", 0.97, 1.0, zero_is_normal=True),
    Source("Cboe VIX History", SourceTier.PRIMARY, "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", "cboe_vix", 0.95, 1.0, zero_is_normal=True),
    Source("Cboe SPX Options (delayed)", SourceTier.RELIABLE, "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json", "cboe_spx_options", 0.90, 0.5, zero_is_normal=True),
    Source("Deribit DVOL", SourceTier.RELIABLE, "https://www.deribit.com/api/v2/public/get_volatility_index_data", "deribit_dvol", 0.85, 1.0, zero_is_normal=True),
    Source("Bybit Perp Funding/OI", SourceTier.RELIABLE, "https://api.bybit.com/v5/market/tickers", "bybit_derivs", 0.80, 1.0, zero_is_normal=True),
    Source("Hyperliquid Perp Funding/OI", SourceTier.FRAGILE, "https://api.hyperliquid.xyz/info", "hyperliquid_derivs", 0.75, 1.0, zero_is_normal=True),
    # Attention / alternative data → pipeline/sources_alternative.py (anomalies only)
    Source("Wikipedia Attention Spikes", SourceTier.BEST_EFFORT,
           "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/",
           "wiki_pageviews", 0.60, 1.0, zero_is_normal=True),
    Source("GDELT Events (15-min)", SourceTier.BEST_EFFORT,
           "http://data.gdeltproject.org/gdeltv2/lastupdate.txt", "gdelt_events", 0.50, 1.0, zero_is_normal=True),
    Source("IMF PortWatch Chokepoints", SourceTier.PRIMARY,
           "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query",
           "portwatch_chokepoints", 0.85, 1.0, zero_is_normal=True),
    # FDA approvals, recalls, enforcement: first-hand biotech/pharma catalysts.
    Source("FDA Press", SourceTier.PRIMARY,
           "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
           "rss", 0.93, 1.0),

    # ── Global central banks (added 2026-09-27, verified live) ─────
    # BIS aggregates speeches from ~60 central banks (incl. PBOC, RBI, BCB) in one feed.
    Source("BIS Central Bank Speeches", SourceTier.PRIMARY, "https://www.bis.org/doclist/cbspeeches.rss", "rss", 0.93, 1.0),
    Source("Bank of Japan", SourceTier.PRIMARY, "https://www.boj.or.jp/en/rss/whatsnew.xml", "rss", 0.95, 1.0),
    Source("Bank of England", SourceTier.PRIMARY, "https://www.bankofengland.co.uk/rss/news", "rss", 0.95, 1.0),
    Source("Swiss National Bank", SourceTier.PRIMARY, "https://www.snb.ch/public/en/rss/pressrel", "rss", 0.95, 1.0),
    Source("Reserve Bank of Australia", SourceTier.PRIMARY, "https://www.rba.gov.au/rss/rss-cb-media-releases.xml", "rss", 0.95, 1.0),
    Source("Bank of Canada", SourceTier.PRIMARY, "https://www.bankofcanada.ca/content_type/press-releases/feed/", "rss", 0.95, 1.0),

    # ── China / Greater China ──────────────────────────────────────
    Source("SCMP Business", SourceTier.RELIABLE, "https://www.scmp.com/rss/4/feed/", "rss", 0.80, 2.0),
    Source("China Money Network", SourceTier.RELIABLE, "https://www.chinamoneynetwork.com/feed/", "rss", 0.72, 1.0),  # Replaces Caixin — free English China finance/VC news RSS
    # Via public RSSHub mirror (rsshub.app itself is Cloudflare-blocked). Content is first-hand
    # Chinese-language financial news; FRAGILE because the mirror is volunteer-run with no SLA.
    # On failure scout retries the same route on the other RSSHUB_MIRRORS.
    Source("Caixin Latest (via RSSHub)", SourceTier.FRAGILE, "https://rsshub.rssforever.com/caixin/latest", "rss", 0.70, 1.0),
    Source("Yicai Brief (via RSSHub)", SourceTier.FRAGILE, "https://rsshub.rssforever.com/yicai/brief", "rss", 0.65, 1.0),
    # Primary company disclosures (unofficial JSON backends of the public sites; one request
    # per run, no retries) → pipeline/sources_cn_hk.py. HKEXnews: English; CNINFO: Chinese.
    Source("HKEXnews Announcements", SourceTier.RELIABLE,
           "https://www1.hkexnews.hk/ncms/json/eds/lcisehk7relsde_1.json", "hkex_announcements", 0.92, 1.0),
    Source("CNINFO A-share Risk Announcements", SourceTier.RELIABLE,
           "https://www.cninfo.com.cn/new/hisAnnouncement/query", "cninfo_risk", 0.92, 1.0),
    Source("CNINFO A-share Restructuring", SourceTier.RELIABLE,
           "https://www.cninfo.com.cn/new/hisAnnouncement/query", "cninfo_restructuring", 0.90, 1.0),

    # ── Japan / Asia Pacific ───────────────────────────────────────
    Source("Nikkei Asia", SourceTier.RELIABLE, "https://asia.nikkei.com/rss/feed/nar", "rss", 0.80, 2.0),

    # ── India ───────────────────────────────────────────────────────
    Source("Economic Times Markets", SourceTier.RELIABLE, "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "rss", 0.75, 2.0),

    # ── Europe ─────────────────────────────────────────────────────
    Source("FT World News", SourceTier.PRIMARY, "https://www.ft.com/world?format=rss", "rss", 0.90, 2.0),
    Source("ECB Press", SourceTier.PRIMARY, "https://www.ecb.europa.eu/rss/press.html", "rss", 0.95, 2.0),
    Source("DW Business", SourceTier.RELIABLE, "http://rss.dw.de/rdf/rss-en-bus", "rss", 0.80, 2.0),
    # DEGRADED 2026-09-27: Fastly edge returns 406 in some windows; on 2026-09-28 it alternated
    # 200/406 by User-Agent. Scout retries a 406 once with browser-style headers; the failure
    # counter handles windows where both header sets are refused.
    Source("Euronews Economy", SourceTier.RELIABLE, "https://www.euronews.com/rss?format=mrss&level=theme&name=business", "rss", 0.75, 1.0,
           status=SourceStatus.DEGRADED),

    # ── Middle East / Energy ───────────────────────────────────────
    Source("Al Jazeera Economy", SourceTier.RELIABLE, "https://www.aljazeera.com/xml/rss/all.xml", "rss", 0.72, 1.0),
    Source("OilPrice.com", SourceTier.RELIABLE, "https://oilprice.com/rss/main", "rss", 0.82, 2.0),

    # ── Russia / Eastern Europe ────────────────────────────────────
    Source("RT Business", SourceTier.FRAGILE, "https://www.rt.com/rss/business/", "rss", 0.55, 1.0),

    # ── Latin America ──────────────────────────────────────────────
    Source("MercoPress", SourceTier.BEST_EFFORT, "https://en.mercopress.com/rss/", "rss", 0.45, 1.0),

    # ── Crypto / Digital Assets ────────────────────────────────────
    Source("CoinDesk", SourceTier.RELIABLE, "https://www.coindesk.com/arc/outboundfeeds/rss", "rss", 0.82, 2.0),
    # Note 2026-09-27: ConnectError on the current (restricted) network; left as-is.
    Source("CoinTelegraph", SourceTier.RELIABLE, "https://cointelegraph.com/rss", "rss", 0.78, 2.0),
    Source("Decrypt", SourceTier.RELIABLE, "https://decrypt.co/feed", "rss", 0.75, 2.0),

    # ── Global / Multi-region ─────────────────────────────────────
    Source("BBC Business", SourceTier.PRIMARY, "https://feeds.bbci.co.uk/news/business/rss.xml", "rss", 0.88, 2.0),

    # ── Commodities / Futures ─────────────────────────────────────
    Source("Investing.com", SourceTier.BEST_EFFORT, "https://www.investing.com/rss/news_1063.rss", "rss", 0.40, 1.0),

    # ── Semiconductor / Technology (Phase J: Playground→Main pipeline merge) ──
    # EE Times: Global electronics industry — AI chips, processors, TSMC, Huawei.
    # Semiconductor Engineering: Deep chip engineering — GPU inference, technical papers, EDA.
    # EDN: Component-level electronics design — circuit protection, SoC, medical electronics.
    # EE Times Asia: Asian supply chain — Indonesia smartphone, ASE packaging, EUV lithography.
    Source("EE Times", SourceTier.PRIMARY, "https://www.eetimes.com/feed/", "rss", 0.88, 2.0),
    Source("Semiconductor Engineering", SourceTier.PRIMARY, "https://semiengineering.com/feed/", "rss", 0.90, 2.0),
    Source("EDN", SourceTier.RELIABLE, "https://www.edn.com/feed/", "rss", 0.80, 2.0),
    Source("EE Times Asia", SourceTier.RELIABLE, "https://www.eetasia.com/feed/", "rss", 0.78, 2.0),

    # ── Social Media (BEST_EFFORT) ────────────────────────────────
    # Reliability weights are domain-reasoned, not backtest-optimized (Law 3 compliance).
    # Swiss Finance Institute (2026): finfluencer picks = -2.3% returns; fading them = +6.8% alpha.
    # Social sentiment captures positioning/crowding — structurally independent from news flow.
    # ApeWisdom: 0.15 — anonymous, unverifiable, prone to manipulation. ApeWisdom is a hobby
    #   project with no SLA, no versioned API, and no per-account data for manipulation detection.
    # Truth Social (Trump): 0.15 — single-person source, ~90% noise ratio, dependent on
    #   third-party RSS aggregator (trumpstruth.org by Defending Democracy Together).
    #   BUT: when it fires on investment-relevant content, it is a LEADING indicator of
    #   market-moving policy — a unique capability no other source provides.
    # Reddit WSB: Reddit's own RSS feed — free, no auth, returns 200
    Source("Reddit WSB", SourceTier.BEST_EFFORT,
           "https://www.reddit.com/r/wallstreetbets/.rss", "rss", 0.15, 1.0),
    Source("Truth Social (Trump)", SourceTier.BEST_EFFORT,
           "https://trumpstruth.org/feed", "rss", 0.15, 1.0),
    # Google daily trending searches (US, 10 items): mass-attention signal, not a news source.
    Source("Google Trends US", SourceTier.BEST_EFFORT,
           "https://trends.google.com/trending/rss?geo=US", "rss", 0.20, 1.0),

    # ── Insider / Smart Money (Phase G Layer 4) ─────────────────────
    # Congress trades: House Clerk PTR filings (pipeline/house_ptr.py), 2026-09-27.
    # capitoltrades.com is behind a Vercel bot checkpoint (429 for any UA) and the
    # Senate eFD site is Akamai-blocked from the current network, so House only.
    Source("Congress Trades", SourceTier.BEST_EFFORT,
           "https://disclosures-clerk.house.gov/FinancialDisclosure",
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
