"""China / Hong Kong primary company announcements ("Group D") turned into NewsItems.

- HKEXnews latest listed-company announcements (English JSON used by the HKEXnews site)
- CNINFO (巨潮资讯, CSRC-designated A-share disclosure site) announcement search

Both are UNOFFICIAL web backends (the JSON the public websites call, not a documented API):
one request per fetcher per run, a polite UA, explicit timeouts, no retries. Fetchers raise
on non-200 / non-JSON responses so scout.fetch_source() applies its usual failure tracking.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger("marketmind.pipeline.sources_cn_hk")

HTTP_TIMEOUT = 30.0
_UA = "Mozilla/5.0 (compatible; MarketMind/0.1; Financial Research Bot)"
_TZ_CN = timezone(timedelta(hours=8))  # HKT and Beijing time are both UTC+8, no DST

# ── HKEXnews ────────────────────────────────────────────────────────────────
# lcisehk7relsde_1.json = newest 500 SEHK announcements (English, ~1 trading day).
# 'relsdc' is the Traditional Chinese variant; 'lcisehk1' is the latest release batch only.
HKEX_BASE = "https://www1.hkexnews.hk"
HKEX_LATEST_URL = f"{HKEX_BASE}/ncms/json/eds/lcisehk7relsde_1.json"
MAX_HKEX = 20

# Large caps: any non-boilerplate announcement from these is kept, incl. share buybacks.
HKEX_WATCHLIST: dict[str, str] = {
    "00700": "Tencent", "09988": "Alibaba", "03690": "Meituan", "01810": "Xiaomi",
    "01211": "BYD", "09618": "JD.com", "09888": "Baidu", "00981": "SMIC",
    "00005": "HSBC", "00883": "CNOOC", "00941": "China Mobile", "01299": "AIA",
    "00388": "HKEX", "02318": "Ping An", "01398": "ICBC", "00939": "CCB",
    "03988": "Bank of China", "00857": "PetroChina", "01024": "Kuaishou",
    "09999": "NetEase", "02015": "Li Auto", "09868": "XPeng", "09866": "NIO",
    "02269": "WuXi Biologics", "00020": "SenseTime", "06618": "JD Health",
    "01088": "China Shenhua", "00386": "Sinopec", "02020": "ANTA", "00016": "SHK Properties",
}

# (priority, substring of the HKEX headline-category text `lTxt`). Lower = more important.
# Any market-wide match is kept; share buybacks / discloseable deals only for the watchlist.
_HKEX_HIGH_SIGNAL: tuple[tuple[int, str], ...] = (
    (0, "Profit Warning"),
    (0, "Inside Information"),
    (0, "Suspension"),
    (0, "Resumption"),
    (0, "Trading Halt"),
    (0, "Winding-up"),
    (0, "Very Substantial"),
    (1, "Major Transaction"),
    (1, "Takeovers Code"),
    (1, "Final Results"),
    (1, "Interim Results"),
    (1, "Quarterly Results"),
    (1, "Placing"),
    (1, "Rights Issue"),
    (1, "Privatisation"),
    (1, "Change in Auditors"),
)
_HKEX_WATCHLIST_ONLY: tuple[tuple[int, str], ...] = (
    (2, "Share Buyback"),
    (2, "Discloseable Transaction"),
    (2, "Connected Transaction"),
    (2, "Dividend"),
)
# Boilerplate never worth an item, even for the watchlist.
_HKEX_NOISE = ("Proxy Forms", "Documents on Display", "List of Directors", "Monthly Returns",
               "Constitutional Documents", "Closure of Books", "Results of AGM", "Notice of AGM",
               "Takeovers Code - dealing disclosures")

# ── CNINFO ──────────────────────────────────────────────────────────────────
CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC = "https://static.cninfo.com.cn/"
CNINFO_PAGE_SIZE = 30  # server caps pageSize at 30
MAX_CNINFO = 20
CNINFO_LOOKBACK_DAYS = 4  # covers a weekend when run on Monday
# Verified codes (2026-09-27). Unknown codes are silently IGNORED by the server (it returns all
# ~1,000 announcements/day), so only add codes that were checked to narrow the result.
CNINFO_RISK_CATEGORIES = (
    "category_yjygjxz_szsh",  # 业绩预告 (earnings pre-announcements, incl. revisions)
    "category_tbclts_szsh",   # 特别处理和退市 (ST / delisting)
    "category_tszlq_szsh",    # 退市整理期
    "category_fxts_szsh",     # 风险提示 (risk warnings, abnormal-move notices)
    "category_cqdq_szsh",     # 澄清致歉 (clarifications of media reports)
)
CNINFO_RESTRUCTURING_KEY = "重大资产重组"
# (priority, keyword in title). Lower = more important; unmatched titles get priority 9.
_CNINFO_PRIORITY: tuple[tuple[int, str], ...] = (
    (0, "立案"), (0, "行政处罚"), (0, "处罚"), (0, "强制退市"), (0, "终止上市"),
    (0, "退市风险"), (0, "重大违法"), (1, "业绩预告"), (1, "业绩快报"), (1, "预亏"),
    (1, "预增"), (1, "重大资产重组"), (1, "停牌"), (1, "复牌"), (1, "澄清"),
    (2, "风险警示"), (2, "风险提示"), (3, "异常波动"),
)

# Intermediary attachments filed alongside a deal (audit / legal / adviser reports) - not news.
_CNINFO_NOISE = ("审计报告", "审阅报告", "备考", "法律意见书", "核查意见", "独立财务顾问", "评估报告")

_EM_RE = re.compile(r"</?em>", re.I)
_WS_RE = re.compile(r"\s+")


def _clean(text: Any) -> str:
    """Strip CNINFO <em> highlight tags and collapse whitespace/newlines."""
    return _WS_RE.sub(" ", _EM_RE.sub("", str(text or ""))).strip()


def _client_kwargs(config: Any) -> dict:
    kwargs: dict = {"timeout": HTTP_TIMEOUT, "follow_redirects": True}
    proxy = getattr(config, "proxy_url", "") if config is not None else ""
    if isinstance(proxy, str) and proxy:
        kwargs["proxy"] = proxy
    return kwargs


def _reliability(source: Any, default: float) -> float:
    try:
        return float(source.reliability)
    except (TypeError, ValueError, AttributeError):
        return default


def _json(resp: httpx.Response) -> dict:
    """raise_for_status, then require a JSON object (a 200 HTML error page counts as failure)."""
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"unexpected JSON payload type {type(data).__name__}")
    return data


# ── HKEXnews ────────────────────────────────────────────────────────────────

def _hkex_priority(record: dict) -> int | None:
    """Priority of an HKEX record, or None if it should be dropped."""
    cat = str(record.get("lTxt") or "")
    if any(n in cat for n in _HKEX_NOISE) and not any(k in cat for _, k in _HKEX_HIGH_SIGNAL):
        return None
    codes = {str(s.get("sc", "")) for s in record.get("stock") or [] if isinstance(s, dict)}
    watch = bool(codes & HKEX_WATCHLIST.keys())
    for prio, key in _HKEX_HIGH_SIGNAL:
        if key in cat:
            return prio - 1 if watch else prio  # watchlist hits sort first within a tier
    if watch:
        for prio, key in _HKEX_WATCHLIST_ONLY:
            if key in cat:
                return prio
        return 3  # any other non-boilerplate watchlist announcement
    return None


def _hkex_time(rel_time: str) -> str:
    """'25/09/2026 22:55' (HKT) -> ISO-8601 with +08:00; unparseable text passes through."""
    try:
        return datetime.strptime(rel_time, "%d/%m/%Y %H:%M").replace(tzinfo=_TZ_CN).isoformat()
    except (ValueError, TypeError):
        return str(rel_time or "")


def hkex_record_to_newsitem(record: dict, source: Any) -> Any | None:
    from marketmind.pipeline.scout import NewsItem

    web_path = record.get("webPath")
    if not web_path:
        return None
    stocks = [s for s in record.get("stock") or [] if isinstance(s, dict)]
    who = ", ".join(f"{s.get('sn', '?')} ({s.get('sc', '?')}.HK)" for s in stocks[:3]) or "HKEX issuer"
    watch_names = [HKEX_WATCHLIST[s.get("sc")] for s in stocks if s.get("sc") in HKEX_WATCHLIST]
    headline = _clean(record.get("title"))
    cat = _clean(record.get("lTxt"))
    title = f"HKEX: {who} - {headline or cat}"
    parts = [f"Category: {cat}"] if cat else []
    if watch_names:
        parts.append(f"Watchlist: {', '.join(watch_names)}")
    parts.append(f"Released {record.get('relTime', '')} HKT; {str(record.get('ext', '')).upper()} {record.get('size', '')}")
    return NewsItem(
        id=hashlib.sha256(f"hkex:{record.get('newsId')}:{web_path}".encode()).hexdigest()[:16],
        title=title[:300],
        url=f"{HKEX_BASE}{web_path}",
        source_name=source.name,
        source_tier=int(source.tier),
        published_at=_hkex_time(str(record.get("relTime", ""))),
        summary="; ".join(parts)[:500],
        source_reliability=_reliability(source, 0.90),
    )


def select_hkex_records(records: list[dict], cap: int = MAX_HKEX) -> list[dict]:
    """Filter to high-signal / watchlist announcements, most important first, newest first within a tier."""
    ranked = []
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        prio = _hkex_priority(rec)
        if prio is not None:
            ranked.append((prio, idx, rec))  # feed is already newest-first, so idx keeps recency
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [rec for _, _, rec in ranked[:cap]]


async def fetch_hkex_announcements(source: Any, config: Any = None) -> list[Any]:
    """Latest HKEX listed-company announcements (high-signal categories + large-cap watchlist)."""
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        resp = await client.get(HKEX_LATEST_URL, headers={"User-Agent": _UA, "Accept": "application/json"})
        data = _json(resp)
    records = data.get("newsInfoLst")
    if not isinstance(records, list):
        raise ValueError("HKEXnews payload missing newsInfoLst")
    items = [hkex_record_to_newsitem(r, source) for r in select_hkex_records(records)]
    return [i for i in items if i is not None]


# ── CNINFO ──────────────────────────────────────────────────────────────────

def _cninfo_priority(title: str) -> int:
    for prio, key in _CNINFO_PRIORITY:
        if key in title:
            return prio
    return 9


def _cninfo_time(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=_TZ_CN).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def cninfo_record_to_newsitem(record: dict, source: Any) -> Any | None:
    from marketmind.pipeline.scout import NewsItem

    adjunct = record.get("adjunctUrl")
    raw_title = _clean(record.get("announcementTitle"))
    if not adjunct or not raw_title:
        return None
    code = str(record.get("secCode") or "")
    name = _clean(record.get("secName"))
    title = f"CNINFO {name}({code}): {raw_title}" if code else f"CNINFO: {raw_title}"
    published = _cninfo_time(record.get("announcementTime"))
    summary = f"A股公告 {name} {code}; {published[:10]}; PDF {record.get('adjunctSize', '?')}KB"
    return NewsItem(
        id=hashlib.sha256(f"cninfo:{record.get('announcementId')}:{adjunct}".encode()).hexdigest()[:16],
        title=title[:300],
        url=f"{CNINFO_STATIC}{str(adjunct).lstrip('/')}",
        source_name=source.name,
        source_tier=int(source.tier),
        published_at=published,
        summary=summary[:500],
        source_reliability=_reliability(source, 0.90),
    )


def select_cninfo_records(records: list[dict], cap: int = MAX_CNINFO) -> list[dict]:
    """Drop intermediary attachments, de-duplicate by announcementId, rank by title keywords, newest first within a tier."""
    seen: set = set()
    ranked = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        key = rec.get("announcementId") or rec.get("adjunctUrl")
        if key in seen:
            continue
        seen.add(key)
        title = _clean(rec.get("announcementTitle"))
        if any(n in title for n in _CNINFO_NOISE):
            continue
        try:
            ts = -int(rec.get("announcementTime") or 0)
        except (TypeError, ValueError):
            ts = 0
        ranked.append((_cninfo_priority(title), ts, rec))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [rec for _, _, rec in ranked[:cap]]


def build_cninfo_form(*, categories: tuple[str, ...] = (), searchkey: str = "",
                      today: datetime | None = None) -> dict[str, str]:
    now = today or datetime.now(_TZ_CN)
    start = (now - timedelta(days=CNINFO_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    return {
        "pageNum": "1", "pageSize": str(CNINFO_PAGE_SIZE),
        "column": "szse",  # 'szse' column covers SZSE + SSE + BSE A-shares on this endpoint
        "tabName": "fulltext", "plate": "", "stock": "", "secid": "", "trade": "",
        "searchkey": searchkey,
        "category": "".join(f"{c};" for c in categories),
        "seDate": f"{start}~{now.strftime('%Y-%m-%d')}",
        "sortName": "", "sortType": "", "isHLtitle": "false",
    }


async def _cninfo_query(form: dict[str, str], source: Any, config: Any) -> list[Any]:
    headers = {"User-Agent": _UA, "Accept": "application/json, text/javascript, */*; q=0.01",
               "X-Requested-With": "XMLHttpRequest"}
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        resp = await client.post(CNINFO_QUERY_URL, data=form, headers=headers)
        data = _json(resp)
    records = data.get("announcements")
    if records is None:  # the server returns null for an empty window
        return []
    if not isinstance(records, list):
        raise ValueError("CNINFO payload 'announcements' is not a list")
    items = [cninfo_record_to_newsitem(r, source) for r in select_cninfo_records(records)]
    return [i for i in items if i is not None]


async def fetch_cninfo_risk_announcements(source: Any, config: Any = None) -> list[Any]:
    """A-share 业绩预告 / ST-退市 / 风险提示 / 澄清 announcements from the last few days."""
    return await _cninfo_query(build_cninfo_form(categories=CNINFO_RISK_CATEGORIES), source, config)


async def fetch_cninfo_restructuring(source: Any, config: Any = None) -> list[Any]:
    """A-share announcements whose title matches 重大资产重组 (no category code exists for it)."""
    return await _cninfo_query(build_cninfo_form(searchkey=CNINFO_RESTRUCTURING_KEY), source, config)
