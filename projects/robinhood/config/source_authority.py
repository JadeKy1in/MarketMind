"""
source_authority.py - 信源权重系统 (Source Authority Rating, SAR) (Phase 5: The Scout)

定义全局信源的权威权重等级，供 source_governor.py 在三角形校验时使用。

等级规则：
- TIER_1 (权威官方)：政府机构、央行、国际组织。单源即可作为"硬证据"
- TIER_2 (准官方)：行业报告、交易所数据。需至少 2 个不同源交叉验证
- TIER_3 (新闻媒体)：主流财经媒体。需至少 2 个 TIER_2+ 信源佐证
- TIER_4 (社交/博客)：非官方言论、推特。需至少 3 个 TIER_3+ 信源佐证
"""

from typing import Dict, List, Optional, Set
from enum import IntEnum


class AuthorityTier(IntEnum):
    """信源权威等级 (数值越低越权威)"""
    TIER_1 = 1    # 政府/央行/国际组织 - 最高权威
    TIER_2 = 2    # 行业报告/交易所数据
    TIER_3 = 3    # 主流财经媒体
    TIER_4 = 4    # 社交/博客/非官方


# ─── 信源注册表 ──────────────────────────────────────────────────────
# 每个信源的唯一 key -> { name, tier, category, description }

SourceRegistry = Dict[str, dict]

SOURCE_REGISTRY: SourceRegistry = {
    # ═══ TIER 1: 政府/央行/国际组织 ═══
    "fed": {
        "name": "Federal Reserve",
        "tier": AuthorityTier.TIER_1,
        "category": "central_bank",
        "feed_type": "rss",
        "url": "https://www.federalreserve.gov/feeds/latest-news.xml",
        "description": "美联储 - 货币政策声明、会议纪要、讲话",
    },
    "eia": {
        "name": "U.S. Energy Information Administration",
        "tier": AuthorityTier.TIER_1,
        "category": "government_agency",
        "feed_type": "api",
        "url": "https://www.eia.gov/opendata/",
        "description": "美国能源信息署 - 原油库存、天然气储存、能源预测",
    },
    "bls": {
        "name": "Bureau of Labor Statistics",
        "tier": AuthorityTier.TIER_1,
        "category": "government_agency",
        "feed_type": "rss",
        "url": "https://www.bls.gov/feed/",
        "description": "美国劳工统计局 - 非农就业(NFP)、CPI、PPI",
    },
    "bea": {
        "name": "Bureau of Economic Analysis",
        "tier": AuthorityTier.TIER_1,
        "category": "government_agency",
        "feed_type": "rss",
        "url": "https://www.bea.gov/rss/news-releases",
        "description": "美国经济分析局 - GDP、个人消费支出",
    },
    "opec": {
        "name": "OPEC",
        "tier": AuthorityTier.TIER_1,
        "category": "international_org",
        "feed_type": "rss",
        "url": "https://www.opec.org/opec_web/en/rss/24.xml",
        "description": "石油输出国组织 - 月度石油市场报告、产量数据",
    },
    "imf": {
        "name": "International Monetary Fund",
        "tier": AuthorityTier.TIER_1,
        "category": "international_org",
        "feed_type": "rss",
        "url": "https://www.imf.org/en/News/RSS",
        "description": "国际货币基金组织 - 全球经济展望、金融稳定报告",
    },
    "worldbank": {
        "name": "World Bank",
        "tier": AuthorityTier.TIER_1,
        "category": "international_org",
        "feed_type": "rss",
        "url": "https://www.worldbank.org/en/news/rss",
        "description": "世界银行 - 全球经济数据、发展报告",
    },
    # ═══ TIER 2: 行业报告/交易所数据 ═══
    "cftc": {
        "name": "Commodity Futures Trading Commission",
        "tier": AuthorityTier.TIER_2,
        "category": "regulator",
        "feed_type": "api",
        "url": "https://www.cftc.gov/cftc/cftc-news-releases",
        "description": "美国商品期货交易委员会 - COT 持仓报告",
    },
    "cme": {
        "name": "CME Group",
        "tier": AuthorityTier.TIER_2,
        "category": "exchange",
        "feed_type": "api",
        "url": "https://www.cmegroup.com/content/dam/cmegroup/notices/",
        "description": "芝加哥商品交易所 - FedWatch、期货持仓、波动率数据",
    },
    "wsj_market": {
        "name": "WSJ Markets Data",
        "tier": AuthorityTier.TIER_2,
        "category": "financial_data",
        "feed_type": "rss",
        "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "description": "华尔街日报市场数据 - 实时市场指数、汇率、商品",
    },
    # ═══ TIER 3: 主流财经媒体 ═══
    "reuters": {
        "name": "Reuters",
        "tier": AuthorityTier.TIER_3,
        "category": "news_agency",
        "feed_type": "rss",
        "url": "https://www.reutersagency.com/feed/",
        "description": "路透社 - 全球财经与地缘新闻",
    },
    "bloomberg": {
        "name": "Bloomberg",
        "tier": AuthorityTier.TIER_3,
        "category": "news_agency",
        "feed_type": "rss",
        "url": "https://www.bloomberg.com/feed/",
        "description": "彭博 - 金融新闻、市场分析",
    },
    "cnbc": {
        "name": "CNBC",
        "tier": AuthorityTier.TIER_3,
        "category": "news_agency",
        "feed_type": "rss",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "description": "CNBC - 商业与财经新闻",
    },
    "ft": {
        "name": "Financial Times",
        "tier": AuthorityTier.TIER_3,
        "category": "news_agency",
        "feed_type": "rss",
        "url": "https://www.ft.com/rss/home",
        "description": "金融时报 - 全球金融新闻",
    },
    # ═══ TIER 4: 社交/博客/非官方 ═══
    "twitter_finance": {
        "name": "Twitter Finance Community",
        "tier": AuthorityTier.TIER_4,
        "category": "social_media",
        "feed_type": "api",
        "url": "N/A (requires Twitter API)",
        "description": "推特金融 KOL 讨论（非结构化数据源）",
    },
    "seeking_alpha": {
        "name": "Seeking Alpha",
        "tier": AuthorityTier.TIER_4,
        "category": "blog",
        "feed_type": "rss",
        "url": "https://seekingalpha.com/feed.xml",
        "description": "投资社区博客 - 散户情绪分析",
    },
    "reddit_wallstreetbets": {
        "name": "Reddit r/wallstreetbets",
        "tier": AuthorityTier.TIER_4,
        "category": "social_media",
        "feed_type": "api",
        "url": "https://www.reddit.com/r/wallstreetbets/.rss",
        "description": "WSB 子版块 - 散户投机情绪",
    },
}


# ─── 三角形校验阈值 ──────────────────────────────────────────────────


def get_min_corroboration(tier: AuthorityTier) -> int:
    """
    返回指定权威等级所需的最小佐证信源数 (三角校验规则)：
    - TIER_1: 1 (单源可独立)
    - TIER_2: 2 (需至少 2 个不同 TIER_2+)
    - TIER_3: 2 (需至少 2 个 TIER_2+)
    - TIER_4: 3 (需至少 3 个 TIER_3+)
    """
    thresholds = {
        AuthorityTier.TIER_1: 1,
        AuthorityTier.TIER_2: 2,
        AuthorityTier.TIER_3: 2,
        AuthorityTier.TIER_4: 3,
    }
    return thresholds.get(tier, 3)


def get_required_authority_tier(tier: AuthorityTier) -> AuthorityTier:
    """
    返回佐证源必须至少达到的权威等级：
    - TIER_1: 不需要佐证 (返回同等级)
    - TIER_2: 需要 TIER_2+ (即 TIER_1 或 TIER_2)
    - TIER_3: 需要 TIER_2+
    - TIER_4: 需要 TIER_3+
    """
    required = {
        AuthorityTier.TIER_1: AuthorityTier.TIER_1,
        AuthorityTier.TIER_2: AuthorityTier.TIER_2,
        AuthorityTier.TIER_3: AuthorityTier.TIER_2,
        AuthorityTier.TIER_4: AuthorityTier.TIER_3,
    }
    return required.get(tier, AuthorityTier.TIER_3)


def get_sources_by_tier(tier: AuthorityTier) -> List[str]:
    """获取指定等级的所有信源 key"""
    return [
        key for key, s in SOURCE_REGISTRY.items()
        if s["tier"] == tier
    ]


def get_sources_by_category(category: str) -> List[str]:
    """获取指定类别的所有信源 key"""
    return [
        key for key, s in SOURCE_REGISTRY.items()
        if s["category"] == category
    ]


def get_tier_for_source(source_key: str) -> Optional[AuthorityTier]:
    """获取指定信源的权威等级"""
    entry = SOURCE_REGISTRY.get(source_key)
    return entry["tier"] if entry else None


def is_authoritative_enough(
    narrative_sources: List[str],
    target_tier: AuthorityTier,
) -> bool:
    """
    三角形校验：判断一个宏观叙事的信源集合是否足够权威。
    
    逻辑：
    1. 统计每个信源的 TIER
    2. 检查最高等级信源是否可以独立验证 (TIER_1)
    3. 否则统计达到 required_tier 的信源数是否 >= min_corroboration
    
    返回 True 表示该叙事的信源满足三角形校验，可以进入后续的 AI 推理。
    """
    if not narrative_sources:
        return False

    tiers: Set[AuthorityTier] = set()
    for key in narrative_sources:
        t = get_tier_for_source(key)
        if t is not None:
            tiers.add(t)

    if not tiers:
        return False

    # TIER_1 单源即可独立验证
    if AuthorityTier.TIER_1 in tiers:
        return True

    min_corroboration = get_min_corroboration(target_tier)
    required_tier = get_required_authority_tier(target_tier)

    # 统计达到 required_tier 的信源数
    qualifying_count = sum(
        1 for key in narrative_sources
        if (t := get_tier_for_source(key)) is not None
        and t <= required_tier  # 数值越小越权威
    )

    return qualifying_count >= min_corroboration