"""Offline tests for pipeline/sources_regulatory.py (SEC full-text flags, Fed calendar, BLS calendar)."""
import json
from datetime import date, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from marketmind.pipeline import sources_regulatory as sr
from marketmind.pipeline.scout import NewsItem, deduplicate

TODAY = date(2026, 9, 27)
_RealAsyncClient = httpx.AsyncClient


def _src(name="Test Source"):
    return SimpleNamespace(name=name, tier=1, reliability=0.95)


@pytest.fixture
def mock_http(monkeypatch):
    """Route every httpx.AsyncClient in the module through a MockTransport handler."""
    state = {"handler": None, "requests": [], "client_kwargs": []}

    def factory(**kwargs):
        state["client_kwargs"].append(dict(kwargs))
        kwargs.pop("proxy", None)

        def handler(request):
            state["requests"].append(request)
            return state["handler"](request)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(sr.httpx, "AsyncClient", factory)
    monkeypatch.setattr(sr, "EFTS_REQUEST_PAUSE_S", 0)
    return state


# ── SEC EDGAR full-text search ──────────────────────────────────────────────

def _hit(adsh, company="Acme Corp  (ACME)  (CIK 0000123456)", form="8-K", file_type=None,
         file_date="2026-09-25", filename="acme_8k.htm", cik="0000123456", items=None):
    return {
        "_id": f"{adsh}:{filename}",
        "_source": {
            "ciks": [cik], "display_names": [company], "root_forms": [form.split("/")[0]],
            "form": form, "file_type": file_type or form, "adsh": adsh, "file_date": file_date,
            "period_ending": "2026-06-30", "biz_locations": ["Austin, TX"], "sics": ["3674"],
            "items": items or [],
        },
    }


def _efts(*hits):
    return {"hits": {"total": {"value": len(hits)}, "hits": list(hits)}}


def test_efts_newsitem_fields():
    filing = {"adsh": "0001-26-000001", "phrases": ["going concern", "material weakness"],
              "hit": _hit("0001-26-000001", items=["4.02", "9.01"])}
    item = sr.efts_filing_to_newsitem(filing, _src("SEC Full-Text"))
    assert isinstance(item, NewsItem)
    assert item.title == 'Acme Corp (ACME) 8-K: "going concern" +1'
    assert item.url == "https://www.sec.gov/Archives/edgar/data/123456/000126000001/acme_8k.htm"
    assert item.published_at == "2026-09-25"
    assert item.source_name == "SEC Full-Text" and item.source_tier == 1
    assert '"going concern", "material weakness"' in item.summary
    assert "8-K items 4.02, 9.01" in item.summary and "accession 0001-26-000001" in item.summary
    assert item.id == sr._sid("efts:0001-26-000001")


def test_efts_dedupe_by_accession_and_merge_phrases():
    a = _hit("A-1", filename="a.htm")
    a_exhibit = _hit("A-1", file_type="EX-99.1", filename="a_ex99.htm")
    b = _hit("B-1", company="Beta Inc (BETA) (CIK 0000000002)", cik="2", filename="b.htm")
    out = sr.collect_efts_hits([("going concern", _efts(a, a_exhibit)), ("tariff", _efts(a, b))])
    assert [f["adsh"] for f in out] == ["A-1", "B-1"]
    assert out[0]["phrases"] == ["going concern", "tariff"]


def test_efts_drops_non_signal_exhibits():
    contract = _hit("C-1", file_type="EX-10.1", filename="credit.htm")
    clawback = _hit("C-2", form="10-K", file_type="EX-97.1", filename="ex97.htm")
    press = _hit("C-3", file_type="EX-99.1", filename="ex99.htm")
    amended = _hit("C-4", form="8-K/A", filename="8ka.htm")
    out = sr.collect_efts_hits([("restatement", _efts(contract, clawback, press, amended))])
    assert sorted(f["adsh"] for f in out) == ["C-3", "C-4"]


def test_efts_caps_per_phrase_and_total_and_prefers_newest():
    hits = [_hit(f"P-{i}", file_date=f"2026-09-2{i}", filename=f"{i}.htm") for i in range(1, 6)]
    out = sr.collect_efts_hits([("going concern", _efts(*hits))], max_per_phrase=2, max_total=30)
    assert [f["adsh"] for f in out] == ["P-5", "P-4"]
    many = [(f"phrase{p}", _efts(*[_hit(f"{p}-{i}", filename=f"{p}{i}.htm") for i in range(5)]))
            for p in range(10)]
    out = sr.collect_efts_hits(many, max_per_phrase=3, max_total=7)
    assert len(out) == 7
    assert {f["phrases"][0] for f in out} == {"phrase0", "phrase1", "phrase2"}  # priority order


@pytest.mark.asyncio
async def test_fetch_sec_fulltext_flags_requests(mock_http):
    def handler(request):
        q = parse_qs(urlparse(str(request.url)).query)["q"][0]
        if q == '"going concern"':
            return httpx.Response(200, json=_efts(_hit("G-1"), _hit("G-2", filename="g2.htm")))
        return httpx.Response(200, json=_efts())
    mock_http["handler"] = handler
    items = await sr.fetch_sec_fulltext_flags(_src(), SimpleNamespace(proxy_url="http://p:1"), today=TODAY)
    assert len(items) == 2
    reqs = mock_http["requests"]
    assert len(reqs) == len(sr.EFTS_PHRASES)
    q0 = parse_qs(urlparse(str(reqs[0].url)).query)
    assert q0["startdt"] == ["2026-09-24"] and q0["enddt"] == ["2026-09-27"]
    assert q0["dateRange"] == ["custom"] and q0["forms"] == ["8-K,10-Q,10-K"]
    assert all("@" in r.headers["user-agent"] for r in reqs)  # SEC "Org contact@email" UA
    assert mock_http["client_kwargs"][0]["proxy"] == "http://p:1"
    assert mock_http["client_kwargs"][0]["timeout"] == 30.0


@pytest.mark.asyncio
async def test_fetch_sec_fulltext_flags_raises_on_error(mock_http):
    mock_http["handler"] = lambda request: httpx.Response(429, text="slow down")
    with pytest.raises(httpx.HTTPStatusError):
        await sr.fetch_sec_fulltext_flags(_src(), None, today=TODAY)


def test_efts_titles_survive_scout_dedup():
    filings = [{"adsh": f"X-{i}", "phrases": ["going concern"],
                "hit": _hit(f"X-{i}", company=f"Co{i} (CIK 000{i})", cik=str(i + 1), filename="10k.htm")}
               for i in range(5)]
    items = [sr.efts_filing_to_newsitem(f, _src()) for f in filings]
    assert len(deduplicate(items)) == 5


# ── Federal Reserve calendar ────────────────────────────────────────────────

FED_EVENTS = [
    {"title": "Speech - Governor Lisa D. Cook ", "description": "AI and Emerging Tech", "time": "1:25 p.m.",
     "month": "2026-09", "days": "28", "type": "Speeches", "location": "At the X Forum, Washington, D.C."},
    {"title": "FOMC Meeting", "description": "&lt;p&gt;Two-day meeting, October 27 - 28&lt;/p&gt;",
     "time": "2:00 p.m.", "month": "2026-10", "days": "28", "type": "FOMC"},  # outside window
    {"title": "G.5 - Foreign Exchange Rates", "time": "4:15 p.m.", "month": "2026-09", "days": "28",
     "type": "Stat"},  # skipped type
    {"title": "Holiday - Columbus Day", "time": "", "month": "2026-10", "days": "12", "type": "Other"},
    {"title": "Testimony - Chair", "description": "Semiannual Monetary Policy Report", "time": "10:00 a.m.",
     "month": "2026-10", "days": "1, 2", "type": "Testimony",
     "link": "https://www.federalreserve.gov/testimony.htm"},
    {"title": "Beige Book", "time": "2:00 p.m.", "month": "2026-09", "days": "26", "type": "Beige"},  # past
    {"title": "Board Meeting", "time": "", "month": "2026-10", "days": "4", "type": "Board"},  # all-day
    {"month": None},
]


def test_fed_events_window_types_and_multiday():
    selected = sr.fed_events_in_window(FED_EVENTS, TODAY)
    titles = [(w.isoformat(), ev["title"]) for w, ev in selected]
    assert titles == [
        ("2026-09-28T13:25:00-04:00", "Speech - Governor Lisa D. Cook "),
        ("2026-10-01T10:00:00-04:00", "Testimony - Chair"),  # multi-day entry -> one item
        ("2026-10-04", "Board Meeting"),
    ]
    assert selected[1][1]["_also_days"] == ["2026-10-02"]


def test_parse_fed_time():
    assert sr._parse_fed_time("3:30 p.m.") == (15, 30)
    assert sr._parse_fed_time("12:00 p.m.") == (12, 0)
    assert sr._parse_fed_time("12:15 a.m.") == (0, 15)
    assert sr._parse_fed_time("") is None


@pytest.mark.asyncio
async def test_fetch_fed_calendar(mock_http, monkeypatch):
    body = "﻿" + json.dumps({"events": FED_EVENTS, "announcement": []})
    mock_http["handler"] = lambda request: httpx.Response(200, content=body.encode("utf-8"))
    items = await sr.fetch_fed_calendar(_src("Fed Calendar"), None, today=TODAY)
    assert len(items) == 3
    first = items[0]
    assert first.title == "Fed 2026-09-28 13:25 ET: Speech - Governor Lisa D. Cook - AI and Emerging Tech"
    assert first.published_at == "2026-09-28T13:25:00-04:00"
    assert "At the X Forum" in first.summary and first.source_name == "Fed Calendar"
    assert items[1].url.startswith("https://www.federalreserve.gov/testimony.htm#")
    assert items[1].title.startswith("Fed 2026-10-01 10:00 ET (also 2026-10-02): Testimony - Chair")
    assert len({i.url for i in items}) == 3 and len({i.id for i in items}) == 3
    assert len(deduplicate(list(items))) == 3
    monkeypatch.setattr(sr, "FED_MAX_EVENTS", 2)
    assert len(await sr.fetch_fed_calendar(_src(), None, today=TODAY)) == 2


def test_fed_clean_text_double_escaped():
    assert sr._clean_text("&lt;p&gt;Meeting of Sept&amp;#8217;s&lt;/p&gt;&#10;") == "Meeting of Sept’s"


@pytest.mark.asyncio
async def test_fetch_fed_calendar_raises_on_error(mock_http):
    mock_http["handler"] = lambda request: httpx.Response(503)
    with pytest.raises(httpx.HTTPStatusError):
        await sr.fetch_fed_calendar(_src(), None, today=TODAY)


# ── BLS calendar ────────────────────────────────────────────────────────────

BLS_ICS = """BEGIN:VCALENDAR\r
PRODID:-//Department of Labor//Bureau of Labor Statistics//EN\r
X-WR-TIMEZONE:US-Eastern\r
BEGIN:VTIMEZONE\r
TZID:US-Eastern\r
BEGIN:DAYLIGHT\r
DTSTART:20070311T020000\r
END:DAYLIGHT\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
UID:uid-jolts\r
DTSTART;TZID=US-Eastern:20260929T100000\r
SUMMARY:Job Openings and Labor Turnover Survey\r
LOCATION:Washington\\, DC\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:uid-state-jolts\r
DTSTART;TZID=US-Eastern:20260930T100000\r
SUMMARY:State Job Openings and Labor Turnover\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:uid-nfp\r
DTSTART;TZID=US-Eastern:20261002T083000\r
SUMMARY:Employment\r
  Situation\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:uid-cpi\r
DTSTART;TZID=US-Eastern:20261014T083000\r
SUMMARY:Consumer Price Index\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:uid-ppi-past\r
DTSTART;TZID=US-Eastern:20260925T083000\r
SUMMARY:Producer Price Index\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:uid-eci\r
DTSTART;VALUE=DATE:20261003\r
SUMMARY:Employment Cost Index\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_parse_ics_events_unfolds_and_types():
    events = sr.parse_ics_events(BLS_ICS)
    assert len(events) == 6
    by_uid = {e["UID"]: e for e in events}
    assert by_uid["uid-nfp"]["SUMMARY"] == "Employment Situation"  # folded line
    assert by_uid["uid-jolts"]["LOCATION"] == "Washington, DC"
    assert by_uid["uid-jolts"]["DTSTART"] == datetime(2026, 9, 29, 10, 0, tzinfo=sr._ET)
    assert by_uid["uid-eci"]["DTSTART"] == date(2026, 10, 3)


def test_bls_window_and_allowlist():
    evs = sr.bls_releases_in_window(sr.parse_ics_events(BLS_ICS), TODAY)
    assert [e["UID"] for e in evs] == ["uid-jolts", "uid-nfp", "uid-eci"]


@pytest.mark.asyncio
async def test_fetch_bls_calendar(mock_http):
    mock_http["handler"] = lambda request: httpx.Response(200, content=BLS_ICS.encode("utf-8"))
    items = await sr.fetch_bls_calendar(_src("BLS"), None, today=TODAY)
    assert [i.title for i in items] == [
        "BLS 2026-09-29 10:00 ET: Job Openings and Labor Turnover Survey",
        "BLS 2026-10-02 08:30 ET: Employment Situation",
        "BLS 2026-10-03: Employment Cost Index",
    ]
    assert items[1].published_at == "2026-10-02T08:30:00-04:00"
    assert len({i.id for i in items}) == 3 and len(deduplicate(list(items))) == 3
    assert str(mock_http["requests"][0].url) == sr.BLS_ICS_URL


@pytest.mark.asyncio
async def test_fetch_bls_calendar_raises_on_error(mock_http):
    mock_http["handler"] = lambda request: httpx.Response(403)
    with pytest.raises(httpx.HTTPStatusError):
        await sr.fetch_bls_calendar(_src(), None, today=TODAY)
