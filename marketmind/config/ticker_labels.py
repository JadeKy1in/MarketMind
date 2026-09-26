"""Chinese labels for tickers, sectors, and domains (P4 bilingual display).

Primary lookup: TICKER_CN (manual Chinese translations for all Asset Universe tickers).
Fallback: ASSET_UNIVERSE[ticker].name (English name as label).
Unknown: ticker symbol only.
"""
from marketmind.config.asset_universe import ASSET_UNIVERSE

TICKER_CN: dict[str, str] = {
    # ── Asset Universe — ETFs ──────────────────────────────
    "SPY": "标普500指数ETF",
    "QQQ": "纳斯达克100ETF",
    "IWM": "罗素2000小盘股ETF",
    "DIA": "道琼斯工业ETF",
    "TLT": "20年以上长期国债ETF",
    "GLD": "黄金信托ETF",
    "SLV": "白银信托ETF",
    "USO": "美国原油基金ETF",
    "UNG": "美国天然气基金ETF",
    "DBA": "农产品基金ETF",
    "EEM": "新兴市场ETF",
    "XLF": "金融板块ETF",
    "XLK": "科技板块ETF",
    "XLE": "能源板块ETF",
    "XLV": "医疗板块ETF",
    # ── Asset Universe — Equities ───────────────────────────
    "AAPL": "苹果",
    "MSFT": "微软",
    "NVDA": "英伟达",
    "GOOGL": "谷歌",
    "AMZN": "亚马逊",
    "META": "Meta",
    "TSLA": "特斯拉",
    "JPM": "摩根大通",
    "XOM": "埃克森美孚",
    # ── Asset Universe — Crypto ─────────────────────────────
    "BTC-USD": "比特币",
    # ── Common L2 candidates beyond Asset Universe ──────────
    "AMD": "超微半导体(AMD)",
    "INTC": "英特尔",
    "SMH": "半导体ETF",
    "SOXX": "费城半导体指数ETF",
    "WMT": "沃尔玛",
    "PG": "宝洁",
    "KO": "可口可乐",
    "JNJ": "强生",
    "COST": "好市多",
    "GS": "高盛",
    "BAC": "美国银行",
    "PFE": "辉瑞",
    "UNH": "联合健康",
    "CVX": "雪佛龙",
    "CAT": "卡特彼勒",
    "GDX": "金矿股ETF",
    "FXI": "中国大盘ETF",
    "VNQ": "房地产ETF",
    "TIPS": "通胀保护国债ETF",
    "XLY": "非必需消费板块ETF",
    "XLI": "工业板块ETF",
}

DOMAIN_CN: dict[str, str] = {
    "energy": "能源", "tech": "科技", "crypto": "加密货币",
    "bonds": "债券", "gold": "黄金", "macro": "宏观",
    "metals": "金属", "financials": "金融", "healthcare": "医疗",
    "consumer": "消费", "industrials": "工业", "emerging": "新兴市场",
    "real_estate": "房地产", "volatility": "波动率", "fx": "外汇",
    "short": "做空",
}

SECTOR_CN: dict[str, str] = {
    "Information Technology": "信息技术", "Technology": "科技",
    "Financials": "金融", "Healthcare": "医疗保健",
    "Consumer Discretionary": "可选消费", "Consumer Staples": "必需消费品",
    "Energy": "能源", "Industrials": "工业", "Materials": "原材料",
    "Real Estate": "房地产", "Utilities": "公用事业",
    "Communication Services": "通信服务",
}


def ticker_cn(ticker: str) -> str:
    """Return ticker with label. Priority: TICKER_CN > ASSET_UNIVERSE > symbol only."""
    t = ticker.upper()
    cn = TICKER_CN.get(t, "")
    if cn:
        return f"{ticker}({cn})"
    asset = ASSET_UNIVERSE.get(t)
    if asset:
        return f"{ticker}({asset.name})"
    return ticker


def domain_cn(domain: str) -> str:
    """Return domain with Chinese label, e.g., 'energy(能源)'."""
    cn = DOMAIN_CN.get(domain.lower(), "")
    return f"{domain}({cn})" if cn else domain
