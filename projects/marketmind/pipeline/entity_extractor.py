"""Tier 1: Regex entity extraction from news headlines. 0 tokens, <100ms."""

from dataclasses import dataclass, field
import re

# ── Acronym blacklist (RT-12): financial acronyms that match [A-Z]{2,5} but are not tickers ──
# Non-alpha entries (e.g. M&A, P/E) can never match the \b[A-Z]{1,5}\b regex and are excluded.
ACRONYM_BLACKLIST: set[str] = {
    "FOMC", "ETF", "CEO", "CFO", "GDP", "CPI", "PPI", "IPO",
    "AI", "ML", "API", "ROI", "EPS", "YTD",
    "QOQ", "YOY", "PMI", "OPEC", "NFP", "ECB", "FED", "BOJ",
    "BOE", "SNB", "RBA", "RBNZ", "PBOC", "BIS", "IMF",
    "WTO", "WHO", "UN", "EU", "G7", "G20", "BRICS",
    "MACD", "RSI", "SMA", "EMA", "WTI", "LNG", "ESG",
    "HFT", "OTC", "CDS", "MBS", "ABS", "REIT", "SPAC", "LBO",
    "MBO", "JNK", "HYG", "LQD", "TLT", "TIPS", "SOFR", "ESTR",
    "SONIA", "TONA", "SARON", "CORRA", "AONIA",
}

# ── Country names (English + Chinese) ──
# Uses (?<![a-zA-Z]) instead of \b because \b does not work with CJK characters
# (Python treats CJK as \w, so \b won't fire between adjacent CJK chars).
COUNTRY_PATTERNS: list[tuple[str, str]] = [
    ("US", r"(?<![a-zA-Z])(?:US|U\.S\.|United States|America|美国)(?![a-zA-Z])"),
    ("China", r"(?<![a-zA-Z])(?:China|Chinese|中国)(?![a-zA-Z])"),
    ("Germany", r"(?<![a-zA-Z])(?:Germany|German|德国)(?![a-zA-Z])"),
    ("Japan", r"(?<![a-zA-Z])(?:Japan|Japanese|日本)(?![a-zA-Z])"),
    ("UK", r"(?<![a-zA-Z])(?:UK|U\.K\.|United Kingdom|Britain|British|英国)(?![a-zA-Z])"),
    ("France", r"(?<![a-zA-Z])(?:France|French|法国)(?![a-zA-Z])"),
    ("Italy", r"(?<![a-zA-Z])(?:Italy|Italian|意大利)(?![a-zA-Z])"),
    ("Canada", r"(?<![a-zA-Z])(?:Canada|Canadian|加拿大)(?![a-zA-Z])"),
    ("Australia", r"(?<![a-zA-Z])(?:Australia|Australian|澳洲|澳大利亚)(?![a-zA-Z])"),
    ("India", r"(?<![a-zA-Z])(?:India|Indian|印度)(?![a-zA-Z])"),
    ("Brazil", r"(?<![a-zA-Z])(?:Brazil|Brazilian|巴西)(?![a-zA-Z])"),
    ("Russia", r"(?<![a-zA-Z])(?:Russia|Russian|俄罗斯)(?![a-zA-Z])"),
    ("South_Korea", r"(?<![a-zA-Z])(?:South Korea|Korean|Korea|韩国)(?![a-zA-Z])"),
    ("Switzerland", r"(?<![a-zA-Z])(?:Switzerland|Swiss|瑞士)(?![a-zA-Z])"),
    ("Saudi_Arabia", r"(?<![a-zA-Z])(?:Saudi Arabia|Saudi|沙特)(?![a-zA-Z])"),
    ("Turkey", r"(?<![a-zA-Z])(?:Turkey|Turkish|土耳其)(?![a-zA-Z])"),
    ("Mexico", r"(?<![a-zA-Z])(?:Mexico|Mexican|墨西哥)(?![a-zA-Z])"),
    ("Indonesia", r"(?<![a-zA-Z])(?:Indonesia|Indonesian|印尼)(?![a-zA-Z])"),
    ("Taiwan", r"(?<![a-zA-Z])(?:Taiwan|Taiwanese|台湾)(?![a-zA-Z])"),
    ("Hong_Kong", r"(?<![a-zA-Z])(?:Hong Kong|HK|香港)(?![a-zA-Z])"),
    ("Singapore", r"(?<![a-zA-Z])(?:Singapore|新加坡)(?![a-zA-Z])"),
    ("South_Africa", r"(?<![a-zA-Z])(?:South Africa|南非)(?![a-zA-Z])"),
    ("UAE", r"(?<![a-zA-Z])(?:UAE|United Arab Emirates|Dubai|阿联酋)(?![a-zA-Z])"),
    ("EU", r"(?<![a-zA-Z])(?:EU|European Union|Eurozone|Euro area|欧元区)(?![a-zA-Z])"),
]

# ── Sector patterns (English + Chinese) ──
SECTOR_PATTERNS: list[tuple[str, str]] = [
    ("tech", r"(?<![a-zA-Z])(?:tech|technology|software|AI|semiconductor|chip|cloud|cyber|科技|芯片|半导体|人工智能)(?![a-zA-Z])"),
    ("energy", r"(?<![a-zA-Z])(?:energy|oil|gas|crude|petroleum|能源|石油|天然气|OPEC)(?![a-zA-Z])"),
    ("financial", r"(?<![a-zA-Z])(?:financial|bank|banking|fintech|insurance|金融|银行)(?![a-zA-Z])"),
    ("healthcare", r"(?<![a-zA-Z])(?:healthcare|health|pharma|biotech|medical|制药|医疗|生物技术)(?![a-zA-Z])"),
    ("consumer", r"(?<![a-zA-Z])(?:consumer|retail|ecommerce|shopping|消费|零售|电商)(?![a-zA-Z])"),
    ("industrial", r"(?<![a-zA-Z])(?:industrial|manufacturing|factory|工业|制造)(?![a-zA-Z])"),
    ("real_estate", r"(?<![a-zA-Z])(?:real estate|property|housing|房地产|楼市|房价)(?![a-zA-Z])"),
    ("crypto", r"(?<![a-zA-Z])(?:crypto|bitcoin|blockchain|DeFi|NFT|加密|数字货币|比特币)(?![a-zA-Z])"),
    ("auto", r"(?<![a-zA-Z])(?:auto|automotive|EV|electric vehicle|汽车|电动车|新能源车)(?![a-zA-Z])"),
    ("defense", r"(?<![a-zA-Z])(?:defense|military|aerospace|weapons|国防|军事|航空)(?![a-zA-Z])"),
    ("telecom", r"(?<![a-zA-Z])(?:telecom|5G|6G|broadband|通信|电信|5G|宽带)(?![a-zA-Z])"),
    ("metals_mining", r"(?<![a-zA-Z])(?:mining|metal|steel|copper|gold mining|矿业|钢铁|铜矿)(?![a-zA-Z])"),
]

# ── Currency patterns ──
CURRENCY_PATTERNS: dict[str, str] = {
    "USD": r"(?<![a-zA-Z])(?:USD|US\$|U\.S\. dollar|dollar)(?![a-zA-Z])",
    "EUR": r"(?<![a-zA-Z€])(?:EUR|€|euro)(?![a-zA-Z])",
    "JPY": r"(?<![a-zA-Z¥])(?:JPY|¥|yen|Japanese yen)(?![a-zA-Z])",
    "GBP": r"(?<![a-zA-Z£])(?:GBP|£|sterling|pound)(?![a-zA-Z])",
    "CHF": r"(?<![a-zA-Z])(?:CHF|Swiss franc)(?![a-zA-Z])",
    "AUD": r"(?<![a-zA-Z])(?:AUD|Australian dollar|Aussie)(?![a-zA-Z])",
    "CAD": r"(?<![a-zA-Z])(?:CAD|Canadian dollar|loonie)(?![a-zA-Z])",
    "CNY": r"(?<![a-zA-Z])(?:CNY|RMB|renminbi|yuan|人民币|元)(?![a-zA-Z])",
    "BTC": r"(?<![a-zA-Z])(?:BTC|Bitcoin|比特币)(?![a-zA-Z])",
    "ETH": r"(?<![a-zA-Z])(?:ETH|Ether|Ethereum|以太币)(?![a-zA-Z])",
    "Gold": r"(?<![a-zA-Z])(?:gold|XAU|黄金)(?![a-zA-Z])",
    "Silver": r"(?<![a-zA-Z])(?:silver|XAG|白银)(?![a-zA-Z])",
    "Oil": r"(?<![a-zA-Z])(?:crude oil|WTI|Brent|原油)(?![a-zA-Z])",
}

# ── Index patterns ──
INDEX_PATTERNS: list[tuple[str, str]] = [
    ("S&P_500", r"(?<![a-zA-Z])(?:S&P\s*500|SPX|SP500|标普500|标普)(?![a-zA-Z])"),
    ("Nasdaq", r"(?<![a-zA-Z])(?:Nasdaq|NASDAQ|NDX|纳指|纳斯达克)(?![a-zA-Z])"),
    ("Dow", r"(?<![a-zA-Z])(?:Dow|DJIA|道指|道琼斯)(?![a-zA-Z])"),
    ("FTSE", r"(?<![a-zA-Z])(?:FTSE\s*100|FTSE100|富时100|英国富时)(?![a-zA-Z])"),
    ("DAX", r"(?<![a-zA-Z])(?:DAX|德国DAX|法兰克福DAX)(?![a-zA-Z])"),
    ("Nikkei", r"(?<![a-zA-Z])(?:Nikkei\s*225|日经225|日经)(?![a-zA-Z])"),
    ("SSE", r"(?<![a-zA-Z])(?:Shanghai Composite|SSE|上证综指|上证|沪指)(?![a-zA-Z])"),
    ("SZSE", r"(?<![a-zA-Z])(?:Shenzhen Composite|SZSE|深证成指|深证|深指)(?![a-zA-Z])"),
    ("HSI", r"(?<![a-zA-Z])(?:Hang Seng|HSI|恒生指数|恒指|恒生)(?![a-zA-Z])"),
    ("VIX", r"(?<![a-zA-Z])(?:VIX|volatility index|恐慌指数|波动率指数)(?![a-zA-Z])"),
    ("CSI300", r"(?<![a-zA-Z])(?:CSI\s*300|沪深300)(?![a-zA-Z])"),
]

# ── Central bank patterns ──
CENTRAL_BANK_PATTERNS: dict[str, str] = {
    "Fed": r"(?<![a-zA-Z])(?:Fed|Federal Reserve|FOMC|美联储)(?![a-zA-Z])",
    "ECB": r"(?<![a-zA-Z])(?:ECB|European Central Bank|欧央行|欧洲央行)(?![a-zA-Z])",
    "BOJ": r"(?<![a-zA-Z])(?:BOJ|Bank of Japan|日本央行|日银)(?![a-zA-Z])",
    "BOE": r"(?<![a-zA-Z])(?:BOE|Bank of England|英国央行|英央行)(?![a-zA-Z])",
    "PBoC": r"(?<![a-zA-Z])(?:PBoC|PBOC|People's Bank of China|中国央行|人民银行|央行)(?![a-zA-Z])",
    "SNB": r"(?<![a-zA-Z])(?:SNB|Swiss National Bank|瑞士央行)(?![a-zA-Z])",
    "RBA": r"(?<![a-zA-Z])(?:RBA|Reserve Bank of Australia|澳洲央行|澳联储)(?![a-zA-Z])",
    "RBNZ": r"(?<![a-zA-Z])(?:RBNZ|Reserve Bank of New Zealand|新西兰央行)(?![a-zA-Z])",
    "RBI": r"(?<![a-zA-Z])(?:RBI|Reserve Bank of India|印度央行)(?![a-zA-Z])",
    "BCB": r"(?<![a-zA-Z])(?:BCB|Banco Central do Brasil|巴西央行)(?![a-zA-Z])",
    "CBRT": r"(?<![a-zA-Z])(?:CBRT|TCMB|Turkish Central Bank|土耳其央行)(?![a-zA-Z])",
    "BOK": r"(?<![a-zA-Z])(?:BOK|Bank of Korea|韩国央行)(?![a-zA-Z])",
}

# ── Keyword patterns (event types and significant terms) ──
KEYWORD_PATTERNS: dict[str, str] = {
    "rate_hike": r"(?<![a-zA-Z])(?:rate hike|rates? hike|hiked rates?|加息|上调利率)(?![a-zA-Z])",
    "rate_cut": r"(?<![a-zA-Z])(?:rate cut|rates? cut|cut rates?|降息|下调利率)(?![a-zA-Z])",
    "rate_hold": r"(?<![a-zA-Z])(?:hold rates?|rates? hold|kept rates?|维持利率|不变利率)(?![a-zA-Z])",
    "inflation": r"(?<![a-zA-Z])(?:inflation|CPI|价格指数|通胀|通货膨胀)(?![a-zA-Z])",
    "recession": r"(?<![a-zA-Z])(?:recession|downturn|contraction|衰退|萧条)(?![a-zA-Z])",
    "earnings": r"(?<![a-zA-Z])(?:earnings|revenue|profit|quarterly|earnings report|财报|盈利|营收)(?![a-zA-Z])",
    "GDP": r"(?<![a-zA-Z])(?:GDP|economic growth|经济增长|国内生产总值)(?![a-zA-Z])",
    "employment": r"(?<![a-zA-Z])(?:employment|jobs?|unemployment|payroll|NFP|就业|失业|非农)(?![a-zA-Z])",
    "trade_war": r"(?<![a-zA-Z])(?:trade war|tariffs?|sanctions?|关税|贸易战|制裁)(?![a-zA-Z])",
    "supply_chain": r"(?<![a-zA-Z])(?:supply chain|shortage|bottleneck|供应链|短缺)(?![a-zA-Z])",
    "geopolitical": r"(?<![a-zA-Z])(?:war|conflict|tension|sanctions?|military|战争|冲突|地缘)(?![a-zA-Z])",
    "merger_acquisition": r"(?<![a-zA-Z])(?:M&A|merger|acquisition|takeover|buyout|收购|并购|合并)(?![a-zA-Z])",
    "regulation": r"(?<![a-zA-Z])(?:regulation|regulatory|crackdown|compliance|监管|合规|整顿)(?![a-zA-Z])",
    "monetary_policy": r"(?<![a-zA-Z])(?:monetary policy|QE|quantitative easing|tapering|货币政策|量化宽松|缩表)(?![a-zA-Z])",
    "fiscal_policy": r"(?<![a-zA-Z])(?:fiscal policy|stimulus|bailout|subsidy|财政政策|刺激|救助)(?![a-zA-Z])",
    "commodity": r"(?<![a-zA-Z])(?:commodity|copper|iron ore|wheat|corn|soybean|大宗商品|铁矿石|铜)(?![a-zA-Z])",
    "bond_market": r"(?<![a-zA-Z])(?:bond|yield|treasury|sovereign debt|债券|收益率|国债)(?![a-zA-Z])",
    "forex": r"(?<![a-zA-Z])(?:forex|FX|exchange rate|currency|外汇|汇率)(?![a-zA-Z])",
    "real_estate_market": r"(?<![a-zA-Z])(?:real estate|housing market|mortgage|房地产|楼市|按揭)(?![a-zA-Z])",
}

# ── Common English words that match [A-Z]{1,5} but are NOT tickers ──
NON_TICKER_WORDS: set[str] = {
    "A", "I", "THE", "AN", "BE", "TO", "OF", "IN", "AT", "ON", "IS",
    "IT", "BY", "AS", "WE", "HE", "NO", "SO", "DO", "UP", "OR", "IF",
    "MY", "GO", "ME", "AM", "HI", "OH", "OK", "US", "ALL", "ARE",
    "BUT", "CAN", "DID", "END", "FEW", "FOR", "GOT", "HAS", "NEW",
    "HER", "HOW", "ITS", "HAD", "HIM", "HIS", "LET", "MAY", "NOT",
    "NOW", "OFF", "ONE", "OUR", "OUT", "OLD", "OWN", "PUT", "SAID",
    "SET", "SHE", "SEE", "TWO", "TOP", "VIA", "WAS", "WHO", "WILL",
    "AND", "BIG", "CUT", "DAY", "DUE", "HUGE", "JUST", "KEY", "LOW",
    "MANY", "MORE", "MUCH", "OVER", "PER", "SAYS", "THAN", "THAT",
    "THEM", "THEN", "THIS", "VERY", "WITH", "YEAR", "BACK", "INTO",
    "FROM", "DOWN", "LIKE", "RISE", "FALL", "HIT", "ALSO", "NEXT",
    "LAST", "WEEK", "DATA", "HIGH", "PLAN", "BANK", "RISK", "MARKET",
    "FIRST", "STILL", "AFTER", "COULD", "WOULD", "ABOUT", "THEIR",
    "THERE", "WHICH", "SINCE", "MONTH", "POWER", "SHOWS", "SURGE",
    "PLANS", "PRICE", "RATES", "GLOBAL", "MAJOR", "GROWTH",
    "ALERT", "AGAIN", "DAILY", "TRADE", "STOCK",
}


@dataclass
class ExtractedEntities:
    tickers: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    indices: list[str] = field(default_factory=list)
    central_banks: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


def _extract_tickers(headline: str) -> list[str]:
    """Extract uppercase ticker symbols, filtering blacklist and common words."""
    candidates = re.findall(r'\b[A-Z]{1,5}\b', headline)
    tickers: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c in NON_TICKER_WORDS:
            continue
        if c in ACRONYM_BLACKLIST:
            continue
        # Whichever-ticker symbols like C, V, W, etc. are valid but rare in news
        # We keep 3+ char tickers by default; 1-2 char tickers only if in asset_universe
        if len(c) <= 2:
            from marketmind.config.asset_universe import ASSET_UNIVERSE
            if c not in ASSET_UNIVERSE:
                continue
        if c not in seen:
            seen.add(c)
            tickers.append(c)
            if len(tickers) >= 5:  # RT-8: max 5 tickers per headline
                break
    return tickers


def _extract_countries(headline: str) -> list[str]:
    countries: list[str] = []
    for name, pattern in COUNTRY_PATTERNS:
        if re.search(pattern, headline, re.IGNORECASE):
            countries.append(name)
    return countries


def _extract_sectors(headline: str) -> list[str]:
    sectors: list[str] = []
    for name, pattern in SECTOR_PATTERNS:
        if re.search(pattern, headline, re.IGNORECASE):
            sectors.append(name)
    return sectors


def _extract_currencies(headline: str) -> list[str]:
    currencies: list[str] = []
    for name, pattern in CURRENCY_PATTERNS.items():
        if re.search(pattern, headline, re.IGNORECASE):
            currencies.append(name)
    return currencies


def _extract_indices(headline: str) -> list[str]:
    indices: list[str] = []
    for name, pattern in INDEX_PATTERNS:
        if re.search(pattern, headline, re.IGNORECASE):
            indices.append(name)
    return indices


def _extract_central_banks(headline: str) -> list[str]:
    banks: list[str] = []
    for name, pattern in CENTRAL_BANK_PATTERNS.items():
        if re.search(pattern, headline, re.IGNORECASE):
            banks.append(name)
    return banks


def _extract_keywords(headline: str) -> list[str]:
    keywords: list[str] = []
    for name, pattern in KEYWORD_PATTERNS.items():
        if re.search(pattern, headline, re.IGNORECASE):
            keywords.append(name)
    return keywords


def extract_entities(headline: str) -> ExtractedEntities:
    """Extract all entity types from a single headline.

    Args:
        headline: Raw news headline text (English or mixed English/Chinese).

    Returns:
        ExtractedEntities dataclass with categorized entity lists.
    """
    if not headline or not headline.strip():
        return ExtractedEntities()
    return ExtractedEntities(
        tickers=_extract_tickers(headline),
        countries=_extract_countries(headline),
        sectors=_extract_sectors(headline),
        currencies=_extract_currencies(headline),
        indices=_extract_indices(headline),
        central_banks=_extract_central_banks(headline),
        keywords=_extract_keywords(headline),
    )
