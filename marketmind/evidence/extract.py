"""News -> checkable claims (one Flash call), validated by code (docs/S5_DESIGN.md)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from marketmind.evidence.checks import CLAIM_TYPES, DOWN, UP
from marketmind.shadows.v3.decision import extract_json

MAX_NEWS = 60
MAX_CLAIMS = 15

SYSTEM_PROMPT = f"""你是证据层的说法抽取员。从新闻里找出**能用一手数据核对**的具体说法。
只抽下面这些类型（type 字段必须是其中之一）：
- revenue_growth：某上市公司营收在增长(up)或下滑(down)。必须给美股代码 ticker。
- short_interest：某公司的空头持仓在增加(up)或减少(down)。必须给 ticker。
- short_selling_pressure：某公司近期卖空交易在加剧(up)或减弱(down)。必须给 ticker。
- filing_red_flag：某公司存在持续经营疑虑、内控重大缺陷、财报重述、退市、破产等财务红旗(up)。必须给 ticker。
- funding_rates：美国短端资金利率/回购利率在上行(up)或下行(down)。
- treasury_demand：美国国债拍卖需求强劲(up)或疲弱(down)。
- stablecoin_supply：稳定币供应/流入在增加(up)或减少(down)。
- fed_liquidity：美联储在投放流动性/资产负债表扩张(up)，或在回收流动性/缩表(QT)(down)。
- etf_flows：ETF 资金在流入(up)或流出(down)。
规则：
1. 只抽新闻明确写出的说法，不要自己推断；一条新闻可以没有说法。
2. claim 用一句中文复述新闻的说法；news_ids 填支持这条说法的新闻编号（可多条，必须来自输入）。
3. asserted 只能是 up 或 down。
4. 同一说法被多条新闻报道时合并成一条，news_ids 列出全部。
5. 最多 {MAX_CLAIMS} 条。没有可核对的说法就返回空列表。
只输出 JSON：{{"claims": [{{"claim": "...", "type": "...", "ticker": "AAPL 或 null", "asserted": "up", "news_ids": ["..."]}}]}}"""


@dataclass
class Claim:
    claim: str
    type: str
    ticker: str | None
    asserted: str
    news_ids: list[str] = field(default_factory=list)


def render_news(items: list) -> str:
    lines = []
    for n in items[:MAX_NEWS]:
        summary = (getattr(n, "summary", "") or "")[:300].replace("\n", " ")
        lines.append(f"[{n.id}] ({getattr(n, 'source_name', '')}) {n.title}\n    {summary}")
    return "\n".join(lines)


# Words that point at a claim one of the checks can test (first live run,
# 2026-09-28: the 40 highest-priority articles held only one checkable claim).
CHECKABLE_WORDS = re.compile(
    r"revenue|sales|quarterly results|earnings|short interest|short seller|short sell|"
    r"shorts|short squeeze|repo|sofr|funding market|money market|liquidity|treasury auction|"
    r"auction|bid-to-cover|bond sale|stablecoin|tether|usdt|usdc|etf (?:in|out)flow|inflow|"
    r"fed(?:'s)? balance sheet|balance[- ]sheet runoff|"
    r"quantitative (?:tightening|easing)|\bqt\b|reserve management|"
    r"outflow|going concern|material weakness|restat|delist|chapter 11|bankrupt|营收|收入|"
    r"做空|空头|回购利率|拍卖|稳定币|资金流|缩表|扩表|资产负债表", re.I)


# Items that come from the primary sources the checks use are data, not narrative
# (full daily run 2026-09-28: all 7 claims were SEC items checked against SEC).
PRIMARY_HOSTS = ("sec.gov", "fiscaldata.treasury.gov", "treasurydirect.gov", "newyorkfed.org",
                 "finra.org", "llama.fi", "nasdaq.com")


def is_primary_item(n) -> bool:
    if getattr(n, "content_type", "news_article") in ("sec_filing", "insider_signal"):
        return True
    if str(getattr(n, "source_name", "") or "").upper().startswith("SEC "):
        return True
    host = urlparse(str(getattr(n, "url", "") or "")).hostname or ""
    return any(host == h or host.endswith("." + h) for h in PRIMARY_HOSTS)


def pick_news(items: list) -> list:
    """Articles that mention something checkable first, then by priority.
    Only media narrative is checked: social mentions carry no checkable facts, and
    SEC filings are primary data themselves (checking them against SEC data is
    circular; first full daily run 2026-09-28 produced only such claims)."""
    usable = [n for n in items if getattr(n, "content_type", "news_article") != "social_mention"
              and not is_primary_item(n)]

    def key(n):
        text = f"{n.title} {getattr(n, 'summary', '') or ''}"
        return (0 if CHECKABLE_WORDS.search(text) else 1, -(getattr(n, "priority_score", 0) or 0))
    return sorted(usable, key=key)[:MAX_NEWS]


def parse_claims(text: str, news_ids: set[str]) -> tuple[list[Claim], list[str]]:
    """Validated claims plus the reasons for anything dropped."""
    try:
        payload = extract_json(text)
    except ValueError as e:
        return [], [f"no JSON: {e}"]
    rows = payload.get("claims") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return [], ["claims is not a list"]
    claims, dropped = [], []
    for i, r in enumerate(rows[:MAX_CLAIMS]):
        if not isinstance(r, dict):
            dropped.append(f"#{i}: not an object")
            continue
        ctype = str(r.get("type") or "").strip()
        asserted = str(r.get("asserted") or "").strip().lower()
        ticker = r.get("ticker")
        ticker = str(ticker).strip().upper() if ticker not in (None, "", "null") else None
        ids = [str(x) for x in (r.get("news_ids") or []) if str(x) in news_ids]
        text_ = str(r.get("claim") or "").strip()
        if ctype not in CLAIM_TYPES:
            dropped.append(f"#{i}: unknown type {ctype!r}")
        elif asserted not in (UP, DOWN):
            dropped.append(f"#{i}: asserted must be up/down")
        elif CLAIM_TYPES[ctype][0] and not ticker:
            dropped.append(f"#{i}: {ctype} needs a ticker")
        elif not ids:
            dropped.append(f"#{i}: no valid news id")
        elif not text_:
            dropped.append(f"#{i}: empty claim")
        else:
            claims.append(Claim(text_[:300], ctype, ticker if CLAIM_TYPES[ctype][0] else None,
                                asserted, ids))
    return claims, dropped
