"""Offline tests for pipeline/house_ptr.py (House Clerk PTR index + PDF text parsing).

Text fixtures are excerpts of real electronic PTRs (pdfplumber output, 2026-09).
"""
import io
import zipfile
from datetime import date

import httpx
import pytest

from marketmind.pipeline import house_ptr as hp

_RealAsyncClient = httpx.AsyncClient

# Wrapped asset names, a wrapped amount split by the asset tag, options, and a
# page-break header in the middle of a record (20035455 / 20035492 excerpts).
PTR_TEXT = """Filing ID #20035455
Name: Hon. Josh Gottheimer
ID Owner Asset Transaction Date Notification Amount Cap.
Type Date Gains >
$200?
JT Applied Materials, Inc. - Common P 08/06/2026 09/14/2026 $1,001 - $15,000
Stock (AMAT) [ST]
F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New
S          O : Morgan Stanley - Select UMA Account # 1
JT Microsoft Corporation - Common P 08/14/2026 09/14/2026 $250,001 -
Stock (MSFT) [OP] $500,000
F      S     : New
D          : Call options; Strike price $340; Expires 10/16/2026
JT Microsoft Corporation - Common P 08/14/2026 09/14/2026 $500,001 -
Stock (MSFT) [OP] $1,000,000
F      S     : New
SP Rollins, Inc. Common Stock (ROL) S 08/12/2026 09/15/2026 $15,001 -
[ST] $50,000
F      S     : New
JT Republic Services, Inc. Common P 08/06/2026 09/14/2026 $1,001 - $15,000
ID Owner Asset Transaction Date Notification Amount Cap.
Type Date Gains >
$200?
Stock (RSG) [ST]
F      S     : New
Hon. Salazar Berkshire Hathaway Inc. New (BRK.B) [ST] S (partial) 08/07/2026 09/01/2026 $1,001 - $15,000
F      S     : New
SP Energy Northwest WA PWR UTIL S 08/13/2026 08/31/2026 $500,001 -
[GS] $1,000,000
F      S     : New
* For the complete list of asset type abbreviations, please visit https://fd.house.gov/reference/asset-type-codes.aspx.
"""

INDEX_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<FinancialDisclosure>
  <Member><Prefix>Hon.</Prefix><Last>Gottheimer</Last><First>Josh</First><Suffix />
    <FilingType>P</FilingType><StateDst>NJ05</StateDst><Year>2026</Year>
    <FilingDate>9/14/2026</FilingDate><DocID>20035455</DocID></Member>
  <Member><Prefix>Hon.</Prefix><Last>Old</Last><First>Filing</First><Suffix />
    <FilingType>P</FilingType><StateDst>TX01</StateDst><Year>2026</Year>
    <FilingDate>8/1/2026</FilingDate><DocID>20030001</DocID></Member>
  <Member><Prefix>Hon.</Prefix><Last>Paper</Last><First>Filer</First><Suffix />
    <FilingType>P</FilingType><StateDst>CA01</StateDst><Year>2026</Year>
    <FilingDate>9/20/2026</FilingDate><DocID>9116331</DocID></Member>
  <Member><Prefix /><Last>Annual</Last><First>Report</First><Suffix />
    <FilingType>O</FilingType><StateDst>NY01</StateDst><Year>2026</Year>
    <FilingDate>9/21/2026</FilingDate><DocID>10070001</DocID></Member>
  <Member><Prefix>Hon.</Prefix><Last>Broken</Last><First>Pdf</First><Suffix />
    <FilingType>P</FilingType><StateDst>FL01</StateDst><Year>2026</Year>
    <FilingDate>9/22/2026</FilingDate><DocID>20035499</DocID></Member>
</FinancialDisclosure>"""


def _zip(xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2026FD.txt", "ignored")
        z.writestr("2026FD.xml", xml)
    return buf.getvalue()


def test_parse_ptr_text_records():
    txs = hp.parse_ptr_text(PTR_TEXT)
    assert len(txs) == 7
    by = [(t.ticker, t.asset_type, t.tx, t.amount, t.owner) for t in txs]
    assert by[0] == ("AMAT", "ST", "P", "$1,001 - $15,000", "JT")
    assert by[1] == ("MSFT", "OP", "P", "$250,001 - $500,000", "JT")
    assert by[3] == ("ROL", "ST", "S", "$15,001 - $50,000", "SP")
    # page-break header inside the record does not cut it off
    assert by[4][:2] == ("RSG", "ST")
    assert by[5][:3] == ("BRK.B", "ST", "S (partial)")
    # municipal bond: no ticker, still a parsed record
    assert by[6] == (None, "GS", "S", "$500,001 - $1,000,000", "SP")
    assert txs[0].trade_date == "08/06/2026" and txs[0].notified_date == "09/14/2026"


def test_parse_ptr_text_without_records():
    assert hp.parse_ptr_text("Filing ID #1\nNothing here\n") == []


def test_parse_index_keeps_dated_electronic_ptrs_only():
    filings = hp.parse_index(INDEX_XML)
    assert [f.doc_id for f in filings] == ["20035455", "20030001", "20035499"]
    f = filings[0]
    assert (f.name, f.district, f.filed) == ("Josh Gottheimer", "NJ05", date(2026, 9, 14))


def test_to_newsitems_groups_by_ticker_and_direction():
    filing = hp.Filing("20035455", "Josh Gottheimer", "NJ05", date(2026, 9, 14))
    items = hp.to_newsitems(filing, hp.parse_ptr_text(PTR_TEXT))
    titles = [i.title for i in items]
    assert "[Congress] Rep. Josh Gottheimer (NJ05) (Buy $MSFT)" in titles
    assert "[Congress] Rep. Josh Gottheimer (NJ05) (Sell (partial) $BRK.B)" in titles
    assert len(items) == 5  # AMAT, MSFT (2 rows merged), ROL, RSG, BRK.B; bond dropped
    msft = next(i for i in items if "$MSFT" in i.title)
    assert "2 buy transaction(s)" in msft.summary and "options" in msft.summary
    assert "$250,001 - $500,000" in msft.summary and "$500,001 - $1,000,000" in msft.summary
    assert msft.url.endswith("/ptr-pdfs/2026/20035455.pdf")
    assert msft.source_name == "Congress Trades"
    assert msft.content_type == "insider_signal"
    assert msft.published_at.startswith("2026-09-14")
    assert len({i.id for i in items}) == len(items)


@pytest.fixture
def mock_http(monkeypatch):
    state = {"requests": [], "pdf_status": {}}

    def handler(request):
        state["requests"].append(str(request.url))
        path = request.url.path
        if path.endswith("2026FD.zip"):
            return httpx.Response(200, content=_zip(INDEX_XML))
        if path.endswith(".pdf"):
            doc = path.rsplit("/", 1)[-1][:-4]
            status = state["pdf_status"].get(doc, 200)
            return httpx.Response(status, content=doc.encode())
        return httpx.Response(404)

    def factory(**kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(hp.httpx, "AsyncClient", factory)
    monkeypatch.setattr(hp, "_pdf_text", lambda b: PTR_TEXT if b == b"20035455" else "garbage")
    return state


@pytest.mark.asyncio
async def test_fetch_uses_lookback_window_and_survives_bad_pdf(mock_http):
    mock_http["pdf_status"]["20035499"] = 500
    items = await hp.fetch_house_ptr_items(today=date(2026, 9, 27), days=14)
    pdfs = [u for u in mock_http["requests"] if u.endswith(".pdf")]
    # 8/1 filing is outside the window; paper filing never requested
    assert sorted(p.rsplit("/", 1)[-1] for p in pdfs) == ["20035455.pdf", "20035499.pdf"]
    assert len(items) == 5
    assert all(i.title.startswith("[Congress] Rep. Josh Gottheimer") for i in items)


@pytest.mark.asyncio
async def test_fetch_caps_items(mock_http):
    items = await hp.fetch_house_ptr_items(today=date(2026, 9, 27), max_items=2)
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_spans_year_boundary(mock_http):
    await hp.fetch_house_ptr_items(today=date(2027, 1, 5), days=14)
    zips = [u for u in mock_http["requests"] if u.endswith(".zip")]
    assert [z.rsplit("/", 1)[-1] for z in zips] == ["2026FD.zip", "2027FD.zip"]
