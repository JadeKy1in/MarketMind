"""Direction extraction and risk/time estimation helpers for hypothesis results."""

# Common asset names to look for (ordered by specificity — longer first)
_ASSET_PATTERNS: list[tuple[str, str]] = [
    # Forex pairs (most specific first)
    ("EUR/USD", "EUR/USD"), ("GBP/USD", "GBP/USD"), ("USD/JPY", "USD/JPY"),
    ("AUD/USD", "AUD/USD"), ("NZD/USD", "NZD/USD"), ("USD/CAD", "USD/CAD"),
    ("USD/CHF", "USD/CHF"), ("EUR/GBP", "EUR/GBP"), ("EUR/JPY", "EUR/JPY"),
    ("GBP/JPY", "GBP/JPY"),
    # US equity ETFs
    ("SPY", "标普500"), ("QQQ", "纳斯达克"), ("IWM", "罗素2000"),
    ("DIA", "道琼斯"), ("TLT", "长期国债"), ("IEF", "中期国债"),
    ("SHY", "短期国债"), ("HYG", "高收益债"), ("LQD", "投资级债"),
    # Commodities / Crypto
    ("GLD", "黄金"), ("SLV", "白银"), ("USO", "原油"), ("UNG", "天然气"),
    ("BTC", "比特币"), ("ETH", "以太坊"),
    # Chinese asset names
    ("黄金", "黄金"), ("白银", "白银"), ("原油", "原油"),
    ("天然气", "天然气"), ("铜", "铜"),
    ("美元指数", "美元指数"), ("美元", "美元"),
    ("欧元", "欧元"), ("日元", "日元"), ("英镑", "英镑"), ("人民币", "人民币"),
    ("美联储", "美联储"), ("央行", "央行"),
    ("美股", "美股"), ("标普", "标普"), ("纳指", "纳指"), ("道指", "道指"),
    ("A股", "A股"), ("港股", "港股"), ("日股", "日股"),
    ("美债", "美债"), ("国债", "国债"), ("利率", "利率"),
    ("通胀", "通胀"), ("CPI", "CPI"), ("PPI", "PPI"), ("GDP", "GDP"),
    ("科技股", "科技股"), ("银行股", "银行股"), ("能源股", "能源股"),
]

# Directional keywords
_BULLISH_KW = ["看涨", "多头", "long", "bullish", "上涨", "上升", "走强",
                "利好", "加息", "raise", "increase", "higher", "growth",
                "expand", "outperform", "rally", "surge", "反弹", "突破"]
_BEARISH_KW = ["看跌", "空头", "short", "bearish", "下跌", "下降", "走弱",
                "利空", "降息", "cut", "decrease", "lower", "decline",
                "contract", "recession", "underperform", "crash", "暴跌", "回调"]


def extract_direction(hypothesis_text: str) -> str:
    """Extract structured direction label from hypothesis text using keyword heuristics.

    Returns a string like "EUR/USD 看涨" or "TLT 看跌", or empty string if
    no clear asset+direction can be identified.
    """
    text_lower = hypothesis_text.lower()

    # 1. Find asset — first match wins
    asset_label = ""
    for pattern, label in _ASSET_PATTERNS:
        if pattern.lower() in text_lower:
            asset_label = label
            break

    # 2. Find direction — prefer Chinese keywords
    is_bullish = any(kw.lower() in text_lower for kw in _BULLISH_KW)
    is_bearish = any(kw.lower() in text_lower for kw in _BEARISH_KW)

    if is_bullish and not is_bearish:
        dir_word = "看涨"
    elif is_bearish and not is_bullish:
        dir_word = "看跌"
    elif is_bullish and is_bearish:
        dir_word = ""  # mixed signals, can't determine
    else:
        dir_word = ""  # no directional signal

    if asset_label and dir_word:
        return f"{asset_label} {dir_word}"
    elif asset_label:
        return asset_label
    elif dir_word:
        return dir_word
    return ""


def estimate_risk_level(confidence: float, bear_case_confidence: float) -> str:
    """Estimate risk level from confidence and bear case confidence.

    低 (Low):    conf > 0.7 AND bear < 0.3
    高 (High):   conf < 0.5 OR bear > 0.6
    中等 (Med):  everything else
    """
    if confidence > 0.7 and bear_case_confidence < 0.3:
        return "低"
    if confidence < 0.5 or bear_case_confidence > 0.6:
        return "高"
    return "中等"


def estimate_time_window(verdict: str) -> str:
    """Estimate time window from verdict tier.

    ACTIONABLE      → "1-4周"
    MONITOR         → "1-3个月"
    HIGH_CONTENTION → "2-6周"
    DISCARD         → "N/A"
    PRICED_IN       → "已过期"
    (default)       → "N/A"
    """
    _map = {
        "ACTIONABLE": "1-4周",
        "MONITOR": "1-3个月",
        "HIGH_CONTENTION": "2-6周",
        "DISCARD": "N/A",
        "PRICED_IN": "已过期",
    }
    return _map.get(verdict, "N/A")
