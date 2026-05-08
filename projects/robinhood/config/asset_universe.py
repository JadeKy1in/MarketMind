"""
asset_universe.py - 资产映射矩阵配置 (Phase 5: The Scout)

定义全球可交易资产的三维映射表：
- HIGH_LIQUIDITY: 大资金进出优选 (高日均成交量)
- LOW_EXPENSE_RATIO: 低成本中期持有 (低管理费)
- HIGH_BETA: 高弹性/杠杆 (高风险回报比)

每个资产按"宏观类别"分组，供 asset_mapper.py 在发现宏观叙事时动态路由。
"""

from typing import Dict, List

# ─── 资产维度分类 ────────────────────────────────────────────────────
# 每个键是宏观类别 (macro_category)，值是一个三维配置篮子

AssetUniverse = Dict[str, Dict[str, List[str]]]

# 宏类别 -> { dimension -> [ticker, ...] }
ASSET_UNIVERSE: AssetUniverse = {
    # ═══ 黄金/避险 ═══
    "gold_safe_haven": {
        "high_liquidity": ["GLD", "IAU"],
        "low_expense_ratio": ["IAU"],  # IAU 费率 0.03% < GLD 0.40%
        "high_beta": ["GDX", "GDXJ", "NUGT"],  # 金矿股 + 3x 杠杆
    },
    # ═══ 利率/债券 ═══
    "interest_rate": {
        "high_liquidity": ["TLT", "AGG", "BND"],
        "low_expense_ratio": ["AGG", "BND"],  # 综合债券 ETF
        "high_beta": ["TMF", "EDV"],          # 3x 杠杆长期国债 / 零息长债
    },
    # ═══ 股票指数 ═══
    "equity_index": {
        "high_liquidity": ["SPY", "QQQ", "VTI"],
        "low_expense_ratio": ["VOO", "VTI", "SCHX"],
        "high_beta": ["TQQQ", "SOXL", "FNGU"],  # 3x 杠杆
    },
    # ═══ 大宗商品 ═══
    "commodity": {
        "high_liquidity": ["USO", "DBC", "GSG"],
        "low_expense_ratio": ["DBC", "PDBC"],
        "high_beta": ["UCO", "BOIL"],  # 2x 杠杆原油/天然气
    },
    # ═══ 原油/能源 ═══
    "crude_oil": {
        "high_liquidity": ["USO", "XLE"],
        "low_expense_ratio": ["XLE"],
        "high_beta": ["UCO", "XLE"],  # UCO = 2x 原油
    },
    # ═══ 加密货币 ═══
    "crypto": {
        "high_liquidity": ["IBIT", "FBTC", "ETHA"],  # BTC/ETH 现货 ETF
        "low_expense_ratio": ["IBIT"],               # 费率最低
        "high_beta": ["BITX", "MSTY"],               # 2x BTC / 微策略杠杆
    },
    # ═══ 外汇/美元 ═══
    "forex_dollar": {
        "high_liquidity": ["UUP", "FXE"],
        "low_expense_ratio": ["UUP"],
        "high_beta": ["YCS", "EUO"],  # 2x 做空日元/欧元
    },
    # ═══ 波动率 ═══
    "volatility": {
        "high_liquidity": ["VXX", "UVXY"],
        "low_expense_ratio": [],                     # 波动率产品都不适合长期持有
        "high_beta": ["UVXY"],                       # 1.5x VIX 期货
    },
    # ═══ 防御性 (Utilities / Healthcare / Consumer Staples) ═══
    "defensive": {
        "high_liquidity": ["XLU", "XLV", "XLP"],
        "low_expense_ratio": ["XLU", "XLP"],
        "high_beta": ["XLU"],  # 防御性质，高 beta 无合适标的
    },
    # ═══ 新兴市场 ═══
    "emerging_market": {
        "high_liquidity": ["EEM", "VWO"],
        "low_expense_ratio": ["VWO", "IEMG"],
        "high_beta": ["EEM", "EDC"],  # EDC = 3x 新兴市场
    },
}


def get_universe_categories() -> List[str]:
    """返回所有支持的宏观类别列表"""
    return list(ASSET_UNIVERSE.keys())


def get_basket(category: str) -> Dict[str, List[str]]:
    """获取指定类别的三维配置篮子，不存在时返回空字典"""
    return ASSET_UNIVERSE.get(category, {})


def resolve_tickers(category: str, dimension: str) -> List[str]:
    """
    从类别+维度解析出 Ticker 列表。
    例如: resolve_tickers("gold_safe_haven", "high_beta") -> ["GDX", "GDXJ", "NUGT"]
    """
    basket = ASSET_UNIVERSE.get(category, {})
    return basket.get(dimension, [])