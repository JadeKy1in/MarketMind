"""Primary-data fetchers for the evidence layer (docs/S5_DESIGN.md).

All keyless, all verified reachable 2026-09-28. Parsers are pure functions over
the raw payloads; `LiveEvidenceData` wires them to the network. Every fetch
returns None on failure (logged) so the claim is judged "unverifiable", never
guessed.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger("marketmind.evidence.sources")

TIMEOUT_S = 30.0
SEC_HEADERS = {"User-Agent": "MarketMind/0.1 (contact@marketmind.dev)",
               "Accept": "application/json"}
SEC_PAUSE_S = 0.15
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day}.txt"
SOFR_URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/30.json"
AUCTIONS_URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/"
                "accounting/od/auctions_query")
STABLE_URL = "https://stablecoins.llama.fi/stablecoincharts/all"

REVENUE_MAX_AGE_DAYS = 200     # older quarter = the filer stopped using the concept
REVENUE_CONCEPTS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                    "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax",
                    "RevenuesNetOfInterestExpense")   # banks
# (phrase, forms). "restatement" is in every 10-K's Exhibit 97 clawback policy, so
# it and the other event phrases only count in 8-Ks (review 2026-09-28, MSFT).
RED_FLAG_PHRASES = (("going concern", "8-K,10-Q,10-K"), ("material weakness", "8-K,10-Q,10-K"),
                    ("should no longer be relied upon", "8-K"), ("restatement", "8-K"),
                    ("delisting", "8-K"), ("chapter 11", "8-K"))


# ── parsers (pure) ──────────────────────────────────────────────────────────

@dataclass
class RevenueYoY:
    concept: str
    period_end: str
    value: float
    prior_end: str
    prior_value: float
    filed: str | None = None          # first filing that reported the latest quarter

    @property
    def yoy(self) -> float:
        return self.value / self.prior_value - 1


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def parse_revenue_yoy(facts: dict) -> RevenueYoY | None:
    """Latest ~3-month revenue vs the same quarter a year earlier."""
    gaap = ((facts or {}).get("facts") or {}).get("us-gaap") or {}
    best: RevenueYoY | None = None
    for concept in REVENUE_CONCEPTS:
        rows = (((gaap.get(concept) or {}).get("units") or {}).get("USD")) or []
        quarters: dict[str, float] = {}
        filed: dict[str, str] = {}
        for r in rows:
            s, e, v = r.get("start"), r.get("end"), r.get("val")
            if not (s and e and isinstance(v, (int, float))) or v <= 0:
                continue
            if 80 <= _days(s, e) <= 100:
                quarters[e] = float(v)      # later filings overwrite earlier ones
                if r.get("filed") and (e not in filed or r["filed"] < filed[e]):
                    filed[e] = r["filed"]
        if not quarters:
            continue
        last = max(quarters)
        prior = [e for e in quarters if 345 <= _days(e, last) <= 385]
        if not prior:
            continue
        p = min(prior, key=lambda e: abs(_days(e, last) - 365))
        cand = RevenueYoY(concept, last, quarters[last], p, quarters[p], filed.get(last))
        if best is None or cand.period_end > best.period_end or (
                cand.period_end == best.period_end and cand.value > best.value):
            best = cand
    return best


def parse_cik_map(payload: dict) -> dict[str, int]:
    return {str(v.get("ticker", "")).upper(): int(v["cik_str"])
            for v in (payload or {}).values() if v.get("ticker") and v.get("cik_str")}


def parse_efts_hits(payload: dict) -> list[dict]:
    hits = (((payload or {}).get("hits") or {}).get("hits")) or []
    out = []
    for h in hits:
        src = h.get("_source") or {}
        out.append({"form": src.get("form") or src.get("root_form"),
                    "filed": src.get("file_date"), "name": (src.get("display_names") or [""])[0],
                    "adsh": src.get("adsh") or str(h.get("_id", "")).split(":")[0]})
    return out


def parse_finra_day(text: str) -> dict[str, float]:
    """Symbol -> short volume / total volume for one RegSHO daily file."""
    out: dict[str, float] = {}
    for line in (text or "").splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 5:
            continue
        try:
            short, total = float(parts[2]), float(parts[4])
        except ValueError:
            continue
        if total > 0:
            out[parts[1].upper()] = short / total
    return out


def parse_sofr(payload: dict) -> list[tuple[str, float]]:
    """(date, rate %) oldest first."""
    rows = [(r.get("effectiveDate"), r.get("percentRate"))
            for r in (payload or {}).get("refRates") or []]
    return sorted((d, float(v)) for d, v in rows if d and v is not None)


def parse_auctions(payload: dict) -> list[dict]:
    """Completed auctions with a bid-to-cover ratio, newest first."""
    out = []
    for r in (payload or {}).get("data") or []:
        btc = r.get("bid_to_cover_ratio")
        if btc in (None, "", "null"):
            continue
        # Note/bond reopenings ("9-Year 10-Month") compare with their original term;
        # bills are reopened across terms, so their current term is the comparable one.
        term = r.get("security_term")
        if r.get("security_type") in ("Note", "Bond") and r.get("original_security_term")                 not in (None, "", "null"):
            term = r.get("original_security_term")
        kind = r.get("security_type")
        if r.get("inflation_index_security") == "Yes":
            kind = "TIPS"
        elif r.get("floating_rate") == "Yes":
            kind = "FRN"
        try:
            out.append({"date": r["auction_date"], "type": kind,
                        "term": term, "bid_to_cover": float(btc)})
        except (KeyError, ValueError):
            continue
    out.sort(key=lambda a: a["date"], reverse=True)
    return out


def parse_stablecoin_supply(payload: list) -> list[tuple[str, float]]:
    """(date, total USD-pegged supply) oldest first."""
    out = []
    for r in payload or []:
        try:
            d = datetime.fromtimestamp(int(r["date"]), tz=timezone.utc).strftime("%Y-%m-%d")
            v = float((r.get("totalCirculatingUSD") or {}).get("peggedUSD"))
        except (KeyError, TypeError, ValueError):
            continue
        out.append((d, v))
    return sorted(out)


# ── live wiring ─────────────────────────────────────────────────────────────

class LiveEvidenceData:
    """Network access for the checks; one instance per run (caches inside)."""

    def __init__(self, client: httpx.AsyncClient | None = None, today: date | None = None):
        self._client = client
        self.today = today or datetime.now(timezone.utc).date()
        self._cik: dict[str, int] | None = None
        self._finra: dict[str, dict[str, float] | None] = {}
        self._sec_lock = asyncio.Lock()
        self._cache: dict[str, object] = {}

    async def _get(self, url: str, params: dict | None = None, headers: dict | None = None,
                   sec: bool = False) -> httpx.Response | None:
        try:
            if sec:
                async with self._sec_lock:
                    await asyncio.sleep(SEC_PAUSE_S)
                    return await self._do_get(url, params, headers or SEC_HEADERS)
            return await self._do_get(url, params, headers)
        except Exception as e:
            logger.warning("evidence fetch failed %s: %s", url, e)
            return None

    async def _do_get(self, url, params, headers):
        if self._client is not None:
            return await self._client.get(url, params=params, headers=headers)
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as c:
            return await c.get(url, params=params, headers=headers)

    async def _json(self, url, params=None, headers=None, sec=False):
        resp = await self._get(url, params, headers, sec)
        if resp is None or resp.status_code != 200:
            if resp is not None:
                logger.warning("evidence HTTP %d for %s", resp.status_code, url)
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    async def cik(self, ticker: str) -> int | None:
        if self._cik is None:
            self._cik = parse_cik_map(await self._json(SEC_TICKERS_URL, sec=True) or {})
        t = ticker.upper()
        return next((self._cik[k] for k in (t, t.replace(".", "-"), t.replace("-", "."))
                     if k in self._cik), None)

    async def revenue_yoy(self, ticker: str) -> RevenueYoY | None:
        cik = await self.cik(ticker)
        if cik is None:
            return None
        r = parse_revenue_yoy(await self._json(SEC_FACTS_URL.format(cik=cik), sec=True) or {})
        if r is not None and (self.today - date.fromisoformat(r.period_end)).days > REVENUE_MAX_AGE_DAYS:
            logger.info("SEC XBRL revenue for %s is stale (%s); treated as unavailable",
                        ticker, r.period_end)
            return None
        return r

    async def red_flag_filings(self, ticker: str, days: int = 90) -> list[dict] | None:
        cik = await self.cik(ticker)
        if cik is None:
            return None
        start = (self.today - timedelta(days=days)).isoformat()
        hits: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for phrase, forms in RED_FLAG_PHRASES:
            payload = await self._json(EFTS_URL, params={
                "q": f'"{phrase}"', "ciks": f"{cik:010d}", "forms": forms,
                "dateRange": "custom", "startdt": start, "enddt": self.today.isoformat()},
                sec=True)
            if payload is None:
                return None
            for h in parse_efts_hits(payload):
                key = (h["adsh"], phrase)      # one filing's exhibits count once
                if key not in seen:
                    seen.add(key)
                    hits.append(dict(h, phrase=phrase))
        return hits

    async def short_interest(self, ticker: str):
        from marketmind.gateway.nasdaq_derivs import get_short_interest
        return await get_short_interest(ticker, client=self._client)

    async def _finra_day(self, day: date) -> dict[str, float] | None:
        key = day.strftime("%Y%m%d")
        if key not in self._finra:
            resp = await self._get(FINRA_URL.format(day=key))
            self._finra[key] = (parse_finra_day(resp.text)
                                if resp is not None and resp.status_code == 200 else None)
        return self._finra[key]

    async def short_volume_ratios(self, ticker: str, n: int = 5) -> list[tuple[str, float]]:
        """Last n trading days' short-volume ratio, oldest first (holidays skipped)."""
        out: list[tuple[str, float]] = []
        day = self.today - timedelta(days=1)
        for _ in range(14):
            if len(out) >= n:
                break
            if day.weekday() < 5:
                data = await self._finra_day(day)
                sym = ticker.upper().replace("-", "/").replace(".", "/")
                if data and sym in data:
                    out.append((day.isoformat(), data[sym]))
            day -= timedelta(days=1)
        return sorted(out)

    async def sofr(self) -> list[tuple[str, float]]:
        if "sofr" not in self._cache:
            self._cache["sofr"] = parse_sofr(await self._json(SOFR_URL) or {})
        return self._cache["sofr"]

    async def auctions(self) -> list[dict]:
        if "auctions" not in self._cache:
            payload = await self._json(AUCTIONS_URL, params={
                "sort": "-auction_date", "page[size]": "300",
                "filter": f"auction_date:lte:{self.today.isoformat()}"})
            self._cache["auctions"] = parse_auctions(payload or {})
        return self._cache["auctions"]

    async def stablecoin_supply(self) -> list[tuple[str, float]]:
        if "stable" not in self._cache:
            self._cache["stable"] = parse_stablecoin_supply(await self._json(STABLE_URL) or [])
        return self._cache["stable"]
