"""
Asset Mapper - 资产映射引擎 (Phase 5: The Scout)
将宏观叙事标签路由到三维配置篮子 (AssetBasket)

职责:
  1. 接收 MacroTag 集合
  2. 将 narrative/category 映射到 ASSET_UNIVERSE 中的类别
  3. 构建包含高流动性 / 低费率 / 高弹性三维度的 AssetBasket
  4. 记录完整的路由链路 (MacroTagResolution)
"""

import logging
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum

from src.scout_types import AssetBasket, MacroTag
from config.asset_universe import ASSET_UNIVERSE, get_universe_categories

logger = logging.getLogger(__name__)


class TagMatchMode(Enum):
    """标签匹配模式 - 决定篮子的构造精度"""
    EXACT = "exact"          # narrative 精确映射到 ASSET_UNIVERSE 类别
    INFLECTED = "inflected"  # 通过同义推理/路由表匹配
    FALLBACK = "fallback"    # 无匹配，使用通用篮子


class MacroTagResolution:
    """
    宏观标签解析结果 - 记录从 MacroTag 到 AssetBasket 的完整路由链路。
    所有字段均为公开属性，支持序列化。
    """

    def __init__(
        self,
        source_tags: List[MacroTag],
        matched_categories: List[str],
        match_mode: TagMatchMode,
        resolved_basket: AssetBasket,
        unmapped_tags: Optional[List[str]] = None,
        confidence_score: float = 0.0,
    ):
        self.source_tags = source_tags
        self.matched_categories = matched_categories
        self.match_mode = match_mode
        self.resolved_basket = resolved_basket
        self.unmapped_tags = unmapped_tags or []
        self.confidence_score = confidence_score

    def to_dict(self) -> Dict:
        """序列化为字典，供审计和输出格式化使用"""
        return {
            "source_tags": [
                {
                    "narrative": t.narrative,
                    "category": t.category,
                    "confidence": round(t.confidence, 2),
                }
                for t in self.source_tags
            ],
            "matched_categories": self.matched_categories,
            "match_mode": self.match_mode.value,
            "resolved_basket": {
                "high_liquidity": self.resolved_basket.high_liquidity,
                "low_expense_ratio": self.resolved_basket.low_expense_ratio,
                "high_beta": self.resolved_basket.high_beta,
            },
            "unmapped_tags": self.unmapped_tags,
            "confidence_score": round(self.confidence_score, 2),
        }


# =========================================================================
# 叙事→类别路由表
# =========================================================================

NARRATIVE_CATEGORY_MAP: Dict[str, List[str]] = {
    # --- 利率/货币政策 ---
    "rate_cut": ["interest_rate", "equity_index"],
    "rate_hike": ["interest_rate", "forex_dollar"],
    "dovish_fed": ["interest_rate", "equity_index", "crypto"],
    "hawkish_fed": ["interest_rate", "forex_dollar"],
    "yield_curve_inversion": ["interest_rate", "defensive"],

    # --- 通胀/通缩 ---
    "inflation_surge": ["gold_safe_haven", "commodity", "crude_oil"],
    "deflation_risk": ["interest_rate", "defensive"],
    "cpi_beat": ["gold_safe_haven", "interest_rate"],
    "cpi_miss": ["equity_index", "crypto"],

    # --- 地缘政治 ---
    "geopolitical_conflict": ["gold_safe_haven", "crude_oil", "defensive"],
    "geopolitical": ["gold_safe_haven", "crude_oil"],
    "trade_war": ["gold_safe_haven", "emerging_market", "commodity"],
    "sanctions_escalation": ["crude_oil", "gold_safe_haven", "commodity"],

    # --- 能源/大宗商品 ---
    "oil_shortage": ["crude_oil", "commodity"],
    "energy_crisis": ["crude_oil", "commodity", "defensive"],
    "supply_chain_crisis": ["commodity", "inflation_surge", "equity_index"],

    # --- 风险偏好 ---
    "risk_on": ["equity_index", "crypto", "commodity"],
    "risk_off": ["gold_safe_haven", "interest_rate", "defensive"],
    "crypto_surge": ["crypto", "equity_index"],
    "crypto_crash": ["gold_safe_haven", "forex_dollar"],

    # --- 外汇 ---
    "usd_weakness": ["gold_safe_haven", "commodity", "emerging_market", "crypto"],
    "usd_strength": ["forex_dollar", "defensive"],
    "dxy_breakout": ["forex_dollar", "gold_safe_haven"],

    # --- 就业/经济 ---
    "nfp_beat": ["equity_index", "interest_rate"],
    "nfp_miss": ["gold_safe_haven", "interest_rate"],
    "recession_fear": ["gold_safe_haven", "interest_rate", "defensive"],
    "gdp_surprise": ["equity_index", "commodity"],

    # --- 新兴市场 ---
    "emerging_market_crisis": ["gold_safe_haven", "forex_dollar", "emerging_market"],
    "china_slowdown": ["commodity", "emerging_market", "equity_index"],

    # --- 波动率 ---
    "volatility_spike": ["volatility", "gold_safe_haven", "defensive"],
    "vix_surge": ["volatility", "gold_safe_haven"],

    # --- 技术/监管 ---
    "tech_regulation": ["defensive", "gold_safe_haven"],
    "tech_rally": ["equity_index", "crypto"],
}

# 同义路由表
SYNONYM_ROUTING: Dict[str, str] = {
    "fed_dovish": "dovish_fed",
    "fed_hawkish": "hawkish_fed",
    "stimulus_hope": "risk_on",
    "consumer_confidence_drop": "risk_off",
    "housing_market_slowdown": "deflation_risk",
    "labor_market_tight": "nfp_beat",
    "labor_market_weak": "nfp_miss",
    "oil_price_surge": "oil_shortage",
    "gold_rush": "risk_off",
    "btc_rally": "crypto_surge",
    "btc_dump": "crypto_crash",
    "market_panic": "volatility_spike",
    "bear_steepener": "yield_curve_inversion",
    "bull_flattener": "rate_hike",
    "china_economic_slowdown": "china_slowdown",
    "dollar_index_up": "usd_strength",
    "dollar_index_down": "usd_weakness",
}


# =========================================================================
# 默认通用篮子
# =========================================================================
DEFAULT_BASKET = AssetBasket(
    high_liquidity=["SPY", "GLD", "BND"],
    low_expense_ratio=["VOO", "IAU", "AGG"],
    high_beta=["TQQQ", "GDX", "BTC"],
)

_UNIVERSE_CATEGORIES: Set[str] = set(get_universe_categories())


# =========================================================================
# AssetMapper
# =========================================================================


class AssetMapper:
    """
    资产映射引擎 - 宏观叙事到交易标的的转化器。

    用法:
        mapper = AssetMapper()
        tags = [MacroTag("rate_cut", "monetary_policy", 0.85)]
        resolution = mapper.map_macro_tags(tags)
        basket = resolution.resolved_basket
    """

    def __init__(self, enable_synonym_fallback: bool = True):
        self._enable_synonym = enable_synonym_fallback
        self._categories = _UNIVERSE_CATEGORIES
        self._resolution_cache: Dict[str, MacroTagResolution] = {}

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def map_macro_tags(
        self,
        tags: List[MacroTag],
        min_confidence: float = 0.3,
    ) -> Optional[MacroTagResolution]:
        """
        主入口: 将一组 MacroTag 映射为 AssetBasket。

        Args:
            tags:  宏观标签列表。
            min_confidence: 最低置信度阈值 (0.0 ~ 1.0)。

        Returns:
            MacroTagResolution 或 None (全部无效)。
        """
        if not tags:
            logger.warning("Empty macro tag list, returning default")
            return self._fallback_resolution([], "No tags provided")

        # 过滤低置信度
        valid = [t for t in tags if t.confidence >= min_confidence]
        if not valid:
            logger.warning("All tags below min_confidence, using default")
            return self._fallback_resolution(tags, "All tags below confidence threshold")

        # Phase 1: 精确匹配
        exact_categories = self._exact_match(valid)
        if exact_categories:
            basket = self._build_basket(exact_categories)
            return MacroTagResolution(
                source_tags=valid,
                matched_categories=exact_categories,
                match_mode=TagMatchMode.EXACT,
                resolved_basket=basket,
                confidence_score=round(max(t.confidence for t in valid), 2),
            )

        # Phase 2: 同义推理
        if self._enable_synonym:
            inflected_categories = self._inflect_match(valid)
            if inflected_categories:
                basket = self._build_basket(inflected_categories)
                unmapped = [
                    t.narrative for t in valid
                    if t.narrative not in NARRATIVE_CATEGORY_MAP
                    and t.narrative not in SYNONYM_ROUTING
                ]
                return MacroTagResolution(
                    source_tags=valid,
                    matched_categories=inflected_categories,
                    match_mode=TagMatchMode.INFLECTED,
                    resolved_basket=basket,
                    unmapped_tags=unmapped,
                    confidence_score=round(
                        max(t.confidence for t in valid) * 0.8, 2
                    ),
                )

        # Phase 3: fallback
        unmapped_all = [t.narrative for t in valid]
        logger.info("No category mapping found, using default basket")
        return self._fallback_resolution(
            valid, f"No mapping found for: {unmapped_all}"
        )

    def map_single_narrative(
        self, narrative: str, fallback: bool = True
    ) -> Optional[AssetBasket]:
        """单个叙事关键词 -> AssetBasket。"""
        n = narrative.lower().strip()

        if n in NARRATIVE_CATEGORY_MAP:
            cats = NARRATIVE_CATEGORY_MAP[n]
            return self._build_basket(cats)

        if n in SYNONYM_ROUTING:
            target = SYNONYM_ROUTING[n]
            if target in NARRATIVE_CATEGORY_MAP:
                cats = NARRATIVE_CATEGORY_MAP[target]
                return self._build_basket(cats)

        return DEFAULT_BASKET if fallback else None

    def map_by_category(
        self, category: str, dimension: Optional[str] = None
    ) -> Optional[AssetBasket]:
        """按 ASSET_UNIVERSE 类别直接构建篮子 (绕过 narrative 路由)。"""
        if category not in self._categories:
            return None

        basket_data = ASSET_UNIVERSE.get(category, {})

        if dimension:
            return AssetBasket(
                high_liquidity=basket_data.get("high_liquidity", [])
                if dimension == "high_liquidity" else [],
                low_expense_ratio=basket_data.get("low_expense_ratio", [])
                if dimension == "low_expense_ratio" else [],
                high_beta=basket_data.get("high_beta", [])
                if dimension == "high_beta" else [],
            )

        return AssetBasket(
            high_liquidity=list(basket_data.get("high_liquidity", [])),
            low_expense_ratio=list(basket_data.get("low_expense_ratio", [])),
            high_beta=list(basket_data.get("high_beta", [])),
        )

    def get_all_tickers(self) -> List[str]:
        """返回资产宇宙中所有唯一的 Ticker。"""
        seen: Set[str] = set()
        result: List[str] = []
        for cat_data in ASSET_UNIVERSE.values():
            for dim_key in ("high_liquidity", "low_expense_ratio", "high_beta"):
                for ticker in cat_data.get(dim_key, []):
                    if ticker not in seen:
                        seen.add(ticker)
                        result.append(ticker)
        return result

    def clear_cache(self) -> None:
        """清空内部解析缓存。"""
        self._resolution_cache.clear()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _exact_match(self, tags: List[MacroTag]) -> List[str]:
        """精确匹配: narrative 在 NARRATIVE_CATEGORY_MAP 中定义。"""
        seen_cats: Set[str] = set()
        result: List[str] = []

        for tag in tags:
            cats = NARRATIVE_CATEGORY_MAP.get(tag.narrative)
            if cats:
                for c in cats:
                    if c not in seen_cats and c in self._categories:
                        seen_cats.add(c)
                        result.append(c)
        return result

    def _inflect_match(self, tags: List[MacroTag]) -> List[str]:
        """同义推理: 通过 SYNONYM_ROUTING 或 tag.category 猜测。"""
        seen_cats: Set[str] = set()
        result: List[str] = []

        for tag in tags:
            n = tag.narrative

            # 1. 检查 SYNONYM_ROUTING
            if n in SYNONYM_ROUTING:
                target = SYNONYM_ROUTING[n]
                cats = NARRATIVE_CATEGORY_MAP.get(target)
                if cats:
                    for c in cats:
                        if c not in seen_cats and c in self._categories:
                            seen_cats.add(c)
                            result.append(c)
                continue

            # 2. 模糊匹配: 从 tag.category 推断
            if tag.category:
                inferred = self._category_to_universe_category(tag.category)
                if inferred and inferred not in seen_cats and inferred in self._categories:
                    seen_cats.add(inferred)
                    result.append(inferred)

        return result

    @staticmethod
    def _category_to_universe_category(category: str) -> Optional[str]:
        """将 MacroTag.category 映射到 ASSET_UNIVERSE 类别。"""
        guess_map: Dict[str, str] = {
            "monetary_policy": "interest_rate",
            "central_bank": "interest_rate",
            "inflation": "commodity",
            "geopolitical": "gold_safe_haven",
            "energy": "crude_oil",
            "commodities": "commodity",
            "equity": "equity_index",
            "crypto": "crypto",
            "forex": "forex_dollar",
            "volatility": "volatility",
            "defensive": "defensive",
            "emerging_markets": "emerging_market",
            "economic_growth": "equity_index",
            "recession": "defensive",
            "trade": "commodity",
        }
        return guess_map.get(category.lower().strip())

    @staticmethod
    def _build_basket(categories: List[str]) -> AssetBasket:
        """
        从匹配到的 ASSET_UNIVERSE 类别列表构建 AssetBasket。
        同一维度的 Ticker 取并集并去重。
        """
        all_hl: List[str] = []
        all_le: List[str] = []
        all_hb: List[str] = []

        for cat in categories:
            data = ASSET_UNIVERSE.get(cat, {})
            all_hl.extend(data.get("high_liquidity", []))
            all_le.extend(data.get("low_expense_ratio", []))
            all_hb.extend(data.get("high_beta", []))

        def dedup(items: List[str]) -> List[str]:
            seen: Set[str] = set()
            out: List[str] = []
            for item in items:
                if item not in seen:
                    seen.add(item)
                    out.append(item)
            return out

        basket = AssetBasket(
            high_liquidity=dedup(all_hl) or list(DEFAULT_BASKET.high_liquidity),
            low_expense_ratio=dedup(all_le) or list(DEFAULT_BASKET.low_expense_ratio),
            high_beta=dedup(all_hb) or list(DEFAULT_BASKET.high_beta),
        )

        return basket

    def _fallback_resolution(
        self, tags: List[MacroTag], reason: str
    ) -> MacroTagResolution:
        """生成回退决议, 使用 DEFAULT_BASKET。"""
        return MacroTagResolution(
            source_tags=tags,
            matched_categories=[],
            match_mode=TagMatchMode.FALLBACK,
            resolved_basket=AssetBasket(
                high_liquidity=list(DEFAULT_BASKET.high_liquidity),
                low_expense_ratio=list(DEFAULT_BASKET.low_expense_ratio),
                high_beta=list(DEFAULT_BASKET.high_beta),
            ),
            unmapped_tags=[t.narrative for t in tags] if tags else [],
            confidence_score=0.0,
        )