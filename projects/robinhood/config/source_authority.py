"""
source_authority.py — Multi-Region Source Authority Rating (SAR v2.0)

Global financial information source registry organized by:
  - TIER (1-4): Authority level
  - REGION: Geographic/jurisdictional coverage
  - LANGUAGE: Primary language of the source

TIER rules (triangle validation):
  TIER_1: Official government/central bank — single source can stand alone
  TIER_2: Semi-official, industry, exchange data — needs 2+ corroboration
  TIER_3: Mainstream financial media — needs 2+ TIER_2+ corroboration
  TIER_4: Social media, blogs — needs 3+ TIER_3+ corroboration
"""

from typing import Dict, List, Optional, Set
from enum import IntEnum


class AuthorityTier(IntEnum):
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3
    TIER_4 = 4


class Region(str):
    US = "US"
    EU = "EU"
    UK = "UK"
    JP = "JP"
    CN = "CN"
    KR = "KR"
    ME = "ME"       # Middle East
    RU = "RU"       # Russia
    GLOBAL = "GLOBAL"


# =========================================================================
# Multi-Region Source Registry
# =========================================================================

SOURCE_REGISTRY: Dict[str, dict] = {

    # ═══ TIER 1: Central Banks & Official Agencies ═══

    # --- US ---
    "fed": {
        "name": "Federal Reserve", "tier": AuthorityTier.TIER_1,
        "region": "US", "language": "en",
        "feed_type": "rss", "url": "https://www.federalreserve.gov/feeds/latest-news.xml",
        "category": "central_bank",
    },
    "fred": {
        "name": "FRED (St. Louis Fed)", "tier": AuthorityTier.TIER_1,
        "region": "US", "language": "en",
        "feed_type": "api", "url": "https://api.stlouisfed.org/fred/",
        "category": "economic_data",
    },
    "bls": {
        "name": "Bureau of Labor Statistics", "tier": AuthorityTier.TIER_1,
        "region": "US", "language": "en",
        "feed_type": "rss", "url": "https://www.bls.gov/feed/",
        "category": "government_agency",
    },
    "bea": {
        "name": "Bureau of Economic Analysis", "tier": AuthorityTier.TIER_1,
        "region": "US", "language": "en",
        "feed_type": "rss", "url": "https://www.bea.gov/rss/news-releases",
        "category": "government_agency",
    },

    # --- EU / Eurozone ---
    "ecb": {
        "name": "European Central Bank", "tier": AuthorityTier.TIER_1,
        "region": "EU", "language": "en",
        "feed_type": "rss", "url": "https://www.ecb.europa.eu/rss/press.html",
        "category": "central_bank",
    },
    "ecb_stats": {
        "name": "ECB Statistical Data Warehouse", "tier": AuthorityTier.TIER_1,
        "region": "EU", "language": "en",
        "feed_type": "api", "url": "https://data.ecb.europa.eu/",
        "category": "economic_data",
    },
    "eurostat": {
        "name": "Eurostat", "tier": AuthorityTier.TIER_1,
        "region": "EU", "language": "en",
        "feed_type": "api", "url": "https://ec.europa.eu/eurostat/data/",
        "category": "economic_data",
    },

    # --- UK ---
    "boe": {
        "name": "Bank of England", "tier": AuthorityTier.TIER_1,
        "region": "UK", "language": "en",
        "feed_type": "rss", "url": "https://www.bankofengland.co.uk/rss",
        "category": "central_bank",
    },
    "ons": {
        "name": "Office for National Statistics", "tier": AuthorityTier.TIER_1,
        "region": "UK", "language": "en",
        "feed_type": "api", "url": "https://www.ons.gov.uk/",
        "category": "government_agency",
    },

    # --- Japan ---
    "boj": {
        "name": "Bank of Japan", "tier": AuthorityTier.TIER_1,
        "region": "JP", "language": "ja",
        "feed_type": "rss", "url": "https://www.boj.or.jp/en/",
        "category": "central_bank",
    },

    # --- China ---
    "pboc": {
        "name": "People's Bank of China", "tier": AuthorityTier.TIER_1,
        "region": "CN", "language": "zh",
        "feed_type": "rss", "url": "http://www.pbc.gov.cn/",
        "category": "central_bank",
    },

    # --- Middle East ---
    "sama": {
        "name": "Saudi Central Bank (SAMA)", "tier": AuthorityTier.TIER_1,
        "region": "ME", "language": "ar",
        "feed_type": "rss", "url": "https://www.sama.gov.sa/en-US/",
        "category": "central_bank",
    },
    "cbuae": {
        "name": "Central Bank of UAE", "tier": AuthorityTier.TIER_1,
        "region": "ME", "language": "en",
        "feed_type": "api", "url": "https://www.centralbank.ae/en/",
        "category": "central_bank",
    },

    # --- Russia ---
    "cbr": {
        "name": "Bank of Russia", "tier": AuthorityTier.TIER_1,
        "region": "RU", "language": "ru",
        "feed_type": "rss", "url": "https://www.cbr.ru/eng/",
        "category": "central_bank",
    },

    # --- Global ---
    "imf": {
        "name": "IMF", "tier": AuthorityTier.TIER_1,
        "region": "GLOBAL", "language": "en",
        "feed_type": "rss", "url": "https://www.imf.org/en/News/RSS",
        "category": "international_org",
    },
    "worldbank": {
        "name": "World Bank", "tier": AuthorityTier.TIER_1,
        "region": "GLOBAL", "language": "en",
        "feed_type": "rss", "url": "https://www.worldbank.org/en/news/rss",
        "category": "international_org",
    },
    "bis": {
        "name": "Bank for International Settlements", "tier": AuthorityTier.TIER_1,
        "region": "GLOBAL", "language": "en",
        "feed_type": "rss", "url": "https://www.bis.org/",
        "category": "international_org",
    },

    # ═══ TIER 2: Semi-Official, Exchanges, Industry ═══

    "cftc": {
        "name": "CFTC", "tier": AuthorityTier.TIER_2,
        "region": "US", "language": "en",
        "feed_type": "api", "url": "https://www.cftc.gov/",
        "category": "regulator",
    },
    "cme": {
        "name": "CME Group", "tier": AuthorityTier.TIER_2,
        "region": "US", "language": "en",
        "feed_type": "api", "url": "https://www.cmegroup.com/",
        "category": "exchange",
    },
    "opec": {
        "name": "OPEC", "tier": AuthorityTier.TIER_2,
        "region": "ME", "language": "en",
        "feed_type": "rss", "url": "https://www.opec.org/opec_web/en/rss/24.xml",
        "category": "international_org",
    },
    "spa_saudi": {
        "name": "Saudi Press Agency", "tier": AuthorityTier.TIER_2,
        "region": "ME", "language": "en",
        "feed_type": "rss", "url": "https://www.spa.gov.sa/en/",
        "category": "government_agency",
    },
    "saudi_gazette": {
        "name": "Saudi Gazette", "tier": AuthorityTier.TIER_2,
        "region": "ME", "language": "en",
        "feed_type": "rss", "url": "https://saudigazette.com.sa/",
        "category": "financial_media",
    },
    "argaam": {
        "name": "Argaam", "tier": AuthorityTier.TIER_2,
        "region": "ME", "language": "en",
        "feed_type": "api", "url": "https://www.argaam.com/en",
        "category": "financial_data",
    },
    "zawya": {
        "name": "Zawya (MENA Markets)", "tier": AuthorityTier.TIER_2,
        "region": "ME", "language": "en",
        "feed_type": "rss", "url": "https://www.zawya.com/en/",
        "category": "financial_media",
    },

    # ═══ TIER 3: Mainstream Financial Media ═══

    "reuters": {
        "name": "Reuters", "tier": AuthorityTier.TIER_3,
        "region": "GLOBAL", "language": "en",
        "feed_type": "rss", "url": "https://www.reutersagency.com/feed/",
        "category": "news_agency",
    },
    "bloomberg": {
        "name": "Bloomberg", "tier": AuthorityTier.TIER_3,
        "region": "GLOBAL", "language": "en",
        "feed_type": "rss", "url": "https://feeds.bloomberg.com/markets/news.rss",
        "category": "news_agency",
    },
    "ft": {
        "name": "Financial Times", "tier": AuthorityTier.TIER_3,
        "region": "UK", "language": "en",
        "feed_type": "rss", "url": "https://www.ft.com/rss/home",
        "category": "news_agency",
    },
    "cnbc": {
        "name": "CNBC", "tier": AuthorityTier.TIER_3,
        "region": "US", "language": "en",
        "feed_type": "rss", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "category": "news_agency",
    },
    "nikkei_asia": {
        "name": "Nikkei Asia", "tier": AuthorityTier.TIER_3,
        "region": "JP", "language": "en",
        "feed_type": "rss", "url": "https://asia.nikkei.com/rss/feed.xml",
        "category": "news_agency",
    },
    "nikkei_jp": {
        "name": "Nihon Keizai Shimbun", "tier": AuthorityTier.TIER_3,
        "region": "JP", "language": "ja",
        "feed_type": "rss", "url": "https://www.nikkei.com/rss/",
        "category": "news_agency",
    },
    "investing_com": {
        "name": "Investing.com", "tier": AuthorityTier.TIER_3,
        "region": "GLOBAL", "language": "en",
        "feed_type": "rss", "url": "https://www.investing.com/rss/news_14.rss",
        "category": "financial_media",
    },
    "arabian_business": {
        "name": "Arabian Business", "tier": AuthorityTier.TIER_3,
        "region": "ME", "language": "en",
        "feed_type": "rss", "url": "https://www.arabianbusiness.com/",
        "category": "financial_media",
    },
    "thenational_uae": {
        "name": "The National (UAE)", "tier": AuthorityTier.TIER_3,
        "region": "ME", "language": "en",
        "feed_type": "rss", "url": "https://www.thenationalnews.com/",
        "category": "news_agency",
    },
    "yonhap": {
        "name": "Yonhap News", "tier": AuthorityTier.TIER_3,
        "region": "KR", "language": "en",
        "feed_type": "rss", "url": "https://en.yna.co.kr/",
        "category": "news_agency",
    },
    "korea_herald": {
        "name": "Korea Herald", "tier": AuthorityTier.TIER_3,
        "region": "KR", "language": "en",
        "feed_type": "rss", "url": "https://www.koreaherald.com/",
        "category": "news_agency",
    },
    "tass": {
        "name": "TASS (Russian News Agency)", "tier": AuthorityTier.TIER_3,
        "region": "RU", "language": "en",
        "feed_type": "rss", "url": "https://tass.com/",
        "category": "news_agency",
    },
    "interfax": {
        "name": "Interfax", "tier": AuthorityTier.TIER_3,
        "region": "RU", "language": "en",
        "feed_type": "rss", "url": "https://interfax.com/",
        "category": "news_agency",
    },

    # ═══ TIER 4: Social / Alternative ═══

    "twitter_finance": {
        "name": "Twitter Finance", "tier": AuthorityTier.TIER_4,
        "region": "GLOBAL", "language": "en",
        "feed_type": "api", "url": "N/A",
        "category": "social_media",
    },
    "reddit_wsb": {
        "name": "r/wallstreetbets", "tier": AuthorityTier.TIER_4,
        "region": "GLOBAL", "language": "en",
        "feed_type": "api", "url": "https://www.reddit.com/r/wallstreetbets/.rss",
        "category": "social_media",
    },
    "seeking_alpha": {
        "name": "Seeking Alpha", "tier": AuthorityTier.TIER_4,
        "region": "US", "language": "en",
        "feed_type": "rss", "url": "https://seekingalpha.com/feed.xml",
        "category": "blog",
    },
}


# =========================================================================
# Region-Based Source Queries
# =========================================================================

REGION_MAP: Dict[str, str] = {
    "US": "United States",
    "EU": "European Union / Eurozone",
    "UK": "United Kingdom",
    "JP": "Japan",
    "CN": "China",
    "KR": "South Korea",
    "ME": "Middle East (GCC)",
    "RU": "Russia",
    "GLOBAL": "Global / International",
}


def get_sources_by_region(region: str) -> List[str]:
    """Return source keys for a specific region."""
    return [k for k, v in SOURCE_REGISTRY.items() if v.get("region") == region]


def get_sources_by_tier(tier: AuthorityTier) -> List[str]:
    return [k for k, v in SOURCE_REGISTRY.items() if v.get("tier") == tier]


def get_sources_by_tier_and_region(tier: AuthorityTier, region: str) -> List[str]:
    return [k for k, v in SOURCE_REGISTRY.items()
            if v.get("tier") == tier and v.get("region") == region]


def get_tier_for_source(source_key: str) -> Optional[AuthorityTier]:
    entry = SOURCE_REGISTRY.get(source_key)
    return entry["tier"] if entry else None


def get_min_corroboration(tier: AuthorityTier) -> int:
    thresholds = {
        AuthorityTier.TIER_1: 1,
        AuthorityTier.TIER_2: 2,
        AuthorityTier.TIER_3: 2,
        AuthorityTier.TIER_4: 3,
    }
    return thresholds.get(tier, 3)


def get_required_authority_tier(tier: AuthorityTier) -> AuthorityTier:
    required = {
        AuthorityTier.TIER_1: AuthorityTier.TIER_1,
        AuthorityTier.TIER_2: AuthorityTier.TIER_2,
        AuthorityTier.TIER_3: AuthorityTier.TIER_2,
        AuthorityTier.TIER_4: AuthorityTier.TIER_3,
    }
    return required.get(tier, AuthorityTier.TIER_3)


def is_authoritative_enough(narrative_sources: List[str], target_tier: AuthorityTier) -> bool:
    if not narrative_sources:
        return False
    tiers: Set[AuthorityTier] = set()
    for key in narrative_sources:
        t = get_tier_for_source(key)
        if t is not None:
            tiers.add(t)
    if not tiers:
        return False
    if AuthorityTier.TIER_1 in tiers:
        return True
    min_corroboration = get_min_corroboration(target_tier)
    required_tier = get_required_authority_tier(target_tier)
    qualifying = sum(
        1 for key in narrative_sources
        if (t := get_tier_for_source(key)) is not None and t <= required_tier
    )
    return qualifying >= min_corroboration


def get_cross_region_score(source_keys: List[str]) -> float:
    """Score how many distinct regions are covered by the given sources.

    Returns a ratio 0.0-1.0. Higher = more regions covered = better cross-region
    triangulation for detecting global vs regional narratives.
    """
    regions = set()
    for key in source_keys:
        region = SOURCE_REGISTRY.get(key, {}).get("region")
        if region and region != "GLOBAL":
            regions.add(region)
    return len(regions) / 8.0  # 8 non-GLOBAL regions


def get_source_feeds() -> List[dict]:
    """Return all sources that have a feed URL (RSS or API) for Scout fetching."""
    feeds = []
    for key, src in SOURCE_REGISTRY.items():
        url = src.get("url", "")
        if url and url != "N/A":
            feeds.append({
                "key": key,
                "name": src["name"],
                "tier": src["tier"],
                "region": src.get("region", "GLOBAL"),
                "language": src.get("language", "en"),
                "feed_type": src.get("feed_type", "rss"),
                "url": url,
                "category": src.get("category", ""),
            })
    return sorted(feeds, key=lambda f: (f["tier"], f["region"]))
