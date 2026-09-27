"""First-hand official data APIs (free, no API key) turned into NewsItems.

- US Treasury auction results via FiscalData (api.fiscaldata.treasury.gov)
- New York Fed reference rates (SOFR / EFFR / OBFR / TGCR / BGCR)

Both fetchers raise on non-200 responses (resp.raise_for_status) so that
scout.fetch_source() applies its usual failure tracking (DEGRADED -> DEAD).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx

logger = logging.getLogger("marketmind.pipeline.official_data_sources")

FISCALDATA_AUCTIONS_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
)
FISCALDATA_AUCTIONS_PAGE = "https://fiscaldata.treasury.gov/datasets/treasury-securities-auctions-data/"
NYFED_RATES_URL = "https://markets.newyorkfed.org/api/rates/all/latest.json"
NYFED_RATES_PAGE = "https://www.newyorkfed.org/markets/reference-rates"

HTTP_TIMEOUT = 30.0
MAX_AUCTIONS = 10
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketMind/0.1; Financial Research Bot)",
            "Accept": "application/json"}
# NY Fed rate types shown in the summary item, in display order (SOFRAI is an index, skipped).
_NYFED_RATE_ORDER = ("SOFR", "EFFR", "OBFR", "TGCR", "BGCR")


def _val(record: dict, key: str) -> str | None:
    """FiscalData encodes missing values as the string 'null'."""
    v = record.get(key)
    if v is None or v == "null" or v == "":
        return None
    return str(v)


def _num(text: str) -> str:
    """'5.0850' -> '5.085', '2.420000' -> '2.42'; non-numeric text passes through."""
    try:
        return f"{float(text):g}"
    except ValueError:
        return text


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


def auction_to_newsitem(record: dict, source: Any) -> Any | None:
    """Convert one completed FiscalData auction record into a NewsItem (None if no result yet)."""
    from marketmind.pipeline.scout import NewsItem

    btc = _val(record, "bid_to_cover_ratio")
    if btc is None:  # announced but not yet auctioned
        return None
    term = _val(record, "security_term") or "?"
    sec_type = _val(record, "security_type") or "Security"
    auction_date = _val(record, "auction_date") or ""
    cusip = _val(record, "cusip") or ""
    # Bills price on discount / investment rate; coupons, TIPS and FRNs on yield / margin.
    rate_label, rate = "high yield", _val(record, "high_yield")
    if rate is None:
        rate_label, rate = "high investment rate", _val(record, "high_investment_rate")
    if rate is None:
        rate_label, rate = "high discount margin", _val(record, "high_discnt_margin")
    rate_txt = f"{rate_label} {_num(rate)}%" if rate is not None else "rate n/a"
    offering = _val(record, "offering_amt")
    try:
        offering_txt = f"${float(offering) / 1e9:,.0f}B offered" if offering else "offering n/a"
    except ValueError:
        offering_txt = "offering n/a"
    reopening = " (reopening)" if _val(record, "reopening") == "Yes" else ""

    title = f"US Treasury {term} {sec_type} auction{reopening}: {rate_txt}, bid-to-cover {_num(btc)} ({auction_date})"
    parts = [offering_txt, f"CUSIP {cusip}"]
    for key, label in (("indirect_bidder_accepted", "indirect accepted"),
                       ("direct_bidder_accepted", "direct accepted"),
                       ("primary_dealer_accepted", "primary dealers accepted"),
                       ("comp_accepted", "competitive accepted")):
        amt = _val(record, key)
        if amt is not None:
            try:
                parts.append(f"{label} ${float(amt) / 1e9:,.1f}B")
            except ValueError:
                continue
    url = f"{FISCALDATA_AUCTIONS_PAGE}?cusip={cusip}&auction_date={auction_date}"
    return NewsItem(
        id=hashlib.sha256(f"auction:{cusip}:{auction_date}".encode()).hexdigest()[:16],
        title=title,
        url=url,
        source_name=source.name,
        source_tier=int(source.tier),
        published_at=auction_date,
        summary=("; ".join(parts))[:500],
        source_reliability=_reliability(source, 0.95),
    )


async def fetch_treasury_auctions(source: Any, config: Any = None) -> list[Any]:
    """Most recent completed US Treasury auctions (results only, newest first)."""
    params = {"sort": "-auction_date", "page[size]": "30"}
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        resp = await client.get(FISCALDATA_AUCTIONS_URL, params=params, headers=_HEADERS)
        resp.raise_for_status()
        data = resp.json()
    items = []
    for record in data.get("data", []):
        item = auction_to_newsitem(record, source)
        if item is not None:
            items.append(item)
        if len(items) >= MAX_AUCTIONS:
            break
    return items


def nyfed_rates_to_newsitem(ref_rates: list[dict], source: Any) -> Any | None:
    """Summarise the NY Fed latest reference rates into a single NewsItem."""
    from marketmind.pipeline.scout import NewsItem

    by_type = {r.get("type"): r for r in ref_rates if isinstance(r, dict)}
    shown = [by_type[t] for t in _NYFED_RATE_ORDER if t in by_type and by_type[t].get("percentRate") is not None]
    if not shown:
        return None
    date = max(str(r.get("effectiveDate", "")) for r in shown)
    title = f"NY Fed reference rates {date}: " + ", ".join(f"{r['type']} {r['percentRate']}%" for r in shown)
    parts = []
    for r in shown:
        p = f"{r['type']} {r['percentRate']}% (1st-99th pct {r.get('percentPercentile1')}-{r.get('percentPercentile99')}"
        if r.get("volumeInBillions") is not None:
            p += f", volume ${r['volumeInBillions']}B"
        p += f", {r.get('effectiveDate')})"
        parts.append(p)
    effr = by_type.get("EFFR", {})
    if effr.get("targetRateFrom") is not None and effr.get("targetRateTo") is not None:
        parts.append(f"FOMC target range {effr['targetRateFrom']}-{effr['targetRateTo']}%")
    return NewsItem(
        id=hashlib.sha256(f"nyfed_rates:{date}:{title}".encode()).hexdigest()[:16],
        title=title,
        url=f"{NYFED_RATES_PAGE}?date={date}",
        source_name=source.name,
        source_tier=int(source.tier),
        published_at=date,
        summary=("; ".join(parts))[:500],
        source_reliability=_reliability(source, 0.95),
    )


async def fetch_nyfed_reference_rates(source: Any, config: Any = None) -> list[Any]:
    """Latest NY Fed reference rates as one summary NewsItem."""
    async with httpx.AsyncClient(**_client_kwargs(config)) as client:
        resp = await client.get(NYFED_RATES_URL, headers=_HEADERS)
        resp.raise_for_status()
        data = resp.json()
    item = nyfed_rates_to_newsitem(data.get("refRates", []), source)
    return [item] if item is not None else []
