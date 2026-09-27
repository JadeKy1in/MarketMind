"""US House Periodic Transaction Reports (STOCK Act) from the House Clerk.

Replaces the capitoltrades.com scraper, which since 2026-09 answers every
request with a Vercel Security Checkpoint (JS challenge, HTTP 429). The Senate
eFD site (efdsearch.senate.gov) is blocked from the current network (Akamai
403), so only the House is covered.

Flow: the yearly filing index (`{year}FD.zip` → XML) lists every PTR with
member, district, filing date and DocID; electronic PTRs (DocID starting
with "2") are text PDFs parsed with pdfplumber. Paper filings are scanned
images and are skipped. Trades are disclosed up to 45 days after the fact,
so these items are context, not real-time signals.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger("marketmind.pipeline.house_ptr")

INDEX_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
PDF_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MarketMind/0.1"}
TIMEOUT_S = 30.0
LOOKBACK_DAYS = 14
MAX_FILINGS = 25
MAX_ITEMS = 40
PDF_CONCURRENCY = 4

_TX_LINE = re.compile(
    r"^(?P<pre>.*?)\s(?P<tx>P|S|E|S \(partial\))\s(?P<trade>\d\d/\d\d/\d{4})"
    r"\s(?P<notified>\d\d/\d\d/\d{4})\b\s*(?P<rest>.*)$")
# Repeated table header at page breaks: skip, the record continues after it.
_HEADER = re.compile(r"^(ID Owner Asset|Type Date Gains|\$200\?)")
# Per-record detail rows ("F  S  : New", "S  O : account", "D  : description"; label
# letters are partly lost in extraction) and the footnote end the record's asset text.
_DETAIL = re.compile(r"^[A-Z][\s\x00]{2,}.*:|^\* For the complete")
_TICKER = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,6})\)\s*\[[A-Z]{2}\]|\(([A-Z][A-Z0-9.\-]{0,6})\)")
_ASSET_TYPE = re.compile(r"\[([A-Z]{2})\]")
_AMOUNT = re.compile(r"\$[\d,]+\s*-\s*[^$]*?\$[\d,]+|Over \$[\d,]+")
_OWNER = re.compile(r"^(SP|JT|DC)\s+")

_DIRECTION = {"P": "Buy", "S": "Sell", "S (partial)": "Sell (partial)", "E": "Exchange"}
_ASSET_TYPE_NOTE = {"OP": "options", "EF": "ETF", "ST": "stock"}


@dataclass
class Filing:
    doc_id: str
    name: str
    district: str
    filed: date


@dataclass
class Transaction:
    owner: str | None
    ticker: str | None
    asset_type: str | None
    tx: str
    trade_date: str
    notified_date: str
    amount: str | None


def parse_index(xml_bytes: bytes) -> list[Filing]:
    """Electronic PTR filings from the yearly index XML."""
    filings = []
    for m in ET.fromstring(xml_bytes):
        if m.findtext("FilingType") != "P":
            continue
        doc_id = (m.findtext("DocID") or "").strip()
        raw_date = (m.findtext("FilingDate") or "").strip()
        if not doc_id.startswith("2") or not raw_date:
            continue  # paper filing (scanned image) or undated
        try:
            filed = datetime.strptime(raw_date, "%m/%d/%Y").date()
        except ValueError:
            logger.warning("House PTR index: bad FilingDate %r for DocID %s", raw_date, doc_id)
            continue
        name = " ".join(p for p in (m.findtext("First"), m.findtext("Last")) if p)
        filings.append(Filing(doc_id, name, (m.findtext("StateDst") or "").strip(), filed))
    return filings


def parse_ptr_text(text: str) -> list[Transaction]:
    """Transactions from the text of one electronic PTR PDF."""
    records: list[dict] = []
    current = None
    for line in (l.replace("\x00", " ").rstrip() for l in text.splitlines()):
        m = _TX_LINE.match(line)
        if m:
            current = {"m": m, "extra": [], "closed": False}
            records.append(current)
        elif current is None or _HEADER.match(line):
            continue
        elif _DETAIL.match(line):
            current["closed"] = True
        elif not current["closed"]:
            current["extra"].append(line)

    out = []
    for r in records:
        m = r["m"]
        asset_text = " ".join([m["pre"], *r["extra"]])
        tail = " ".join([m["rest"], *r["extra"]])
        tk = _TICKER.search(asset_text)
        at = _ASSET_TYPE.search(asset_text)
        amt = _AMOUNT.search(tail)
        owner = _OWNER.match(m["pre"])
        out.append(Transaction(
            owner=owner.group(1) if owner else None,
            ticker=(tk.group(1) or tk.group(2)) if tk else None,
            asset_type=at.group(1) if at else None,
            tx=m["tx"],
            trade_date=m["trade"],
            notified_date=m["notified"],
            # a wrapped range has the asset's continuation text between its two halves
            amount=re.sub(r"\s*-\s*[^$]*?\$", " - $", amt.group(0)) if amt else None,
        ))
    return out


def _pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def to_newsitems(filing: Filing, transactions: list[Transaction]) -> list[Any]:
    """One NewsItem per (ticker, direction) in a filing; untickered assets are dropped."""
    from marketmind.config.source_authority import SourceTier
    from marketmind.pipeline.scout import NewsItem

    grouped: dict[tuple[str, str], list[Transaction]] = {}
    for t in transactions:
        if t.ticker:
            grouped.setdefault((t.ticker, _DIRECTION.get(t.tx, t.tx)), []).append(t)

    url = PDF_URL.format(year=filing.filed.year, doc_id=filing.doc_id)
    items = []
    for (ticker, direction), txs in grouped.items():
        who = f"Rep. {filing.name}" + (f" ({filing.district})" if filing.district else "")
        kinds = sorted({_ASSET_TYPE_NOTE.get(t.asset_type or "", t.asset_type or "?") for t in txs})
        amounts = ", ".join(sorted({t.amount for t in txs if t.amount})) or "amount unparsed"
        trade_dates = ", ".join(sorted({t.trade_date for t in txs}))
        summary = (
            f"{who} disclosed {len(txs)} {direction.lower()} transaction(s) of ${ticker} "
            f"({'/'.join(kinds)}); amount {amounts}; traded {trade_dates}; "
            f"filed {filing.filed.isoformat()}. House PTR (STOCK Act), disclosed up to 45 days late."
        )
        items.append(NewsItem(
            id=hashlib.sha256(f"house_ptr:{filing.doc_id}:{ticker}:{direction}".encode()).hexdigest()[:16],
            title=f"[Congress] {who} ({direction} ${ticker})",
            url=url,
            source_name="Congress Trades",
            source_tier=int(SourceTier.BEST_EFFORT),
            published_at=datetime(filing.filed.year, filing.filed.month, filing.filed.day,
                                  tzinfo=timezone.utc).isoformat(),
            summary=summary[:500],
            source_reliability=0.20,
            content_type="insider_signal",
        ))
    return items


async def fetch_house_ptr_items(today: date | None = None, days: int = LOOKBACK_DAYS,
                                max_filings: int = MAX_FILINGS,
                                max_items: int = MAX_ITEMS) -> list[Any]:
    """NewsItems for House PTRs filed in the last `days` days, newest filings first."""
    today = today or datetime.now(timezone.utc).date()
    since = today - timedelta(days=days)
    async with httpx.AsyncClient(timeout=TIMEOUT_S, headers=HEADERS,
                                 follow_redirects=True) as client:
        filings: list[Filing] = []
        for year in sorted({since.year, today.year}):
            resp = await client.get(INDEX_URL.format(year=year))
            if resp.status_code != 200:
                logger.warning("House PTR index %d returned HTTP %d", year, resp.status_code)
                continue
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                xml_name = next((n for n in z.namelist() if n.lower().endswith(".xml")), None)
                if xml_name is None:
                    logger.warning("House PTR index %d: no XML in archive", year)
                    continue
                filings.extend(parse_index(z.read(xml_name)))

        recent = sorted((f for f in filings if since <= f.filed <= today),
                        key=lambda f: (f.filed, f.doc_id), reverse=True)[:max_filings]
        sem = asyncio.Semaphore(PDF_CONCURRENCY)

        async def one(f: Filing) -> list[Any]:
            async with sem:
                try:
                    resp = await client.get(PDF_URL.format(year=f.filed.year, doc_id=f.doc_id))
                    if resp.status_code != 200:
                        logger.warning("House PTR %s returned HTTP %d", f.doc_id, resp.status_code)
                        return []
                    text = await asyncio.to_thread(_pdf_text, resp.content)
                except Exception as e:  # one bad PDF must not drop the rest
                    logger.warning("House PTR %s failed: %s", f.doc_id, e)
                    return []
            txs = parse_ptr_text(text)
            if not txs:
                logger.warning("House PTR %s: no transactions parsed", f.doc_id)
            return to_newsitems(f, txs)

        batches = await asyncio.gather(*(one(f) for f in recent))

    items = [i for batch in batches for i in batch][:max_items]
    logger.info("House PTR: %d filings since %s → %d items", len(recent), since, len(items))
    return items
