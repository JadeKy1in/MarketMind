"""Offline tests: Indeed Hiring Lab and Apple App Store charts (macro_alt feed) (owner decision 2026-09-29).
Payload shapes copy the live responses checked 2026-09-29.
"""
import json

import httpx
import pytest

from marketmind.gateway import app_charts, hiring_lab
from marketmind.shadow_feeds import macro_alt


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    return tmp_path


def _transport(monkeypatch, module, handler, calls=None):
    def h(req):
        if calls is not None:
            calls.append(str(req.url))
        return handler(req)
    monkeypatch.setattr(module, "_TRANSPORT", httpx.MockTransport(h))


# ── Indeed Hiring Lab ───────────────────────────────────────────────────────

def _agg(cc):
    rows = ["date,jobcountry,indeed_job_postings_index_SA,indeed_job_postings_index_NSA,variable"]
    for d, v in (("2026-08-20", 101.0), ("2026-08-28", 102.0), ("2026-09-25", 103.8)):
        rows += [f"{d},{cc},{v},{v + 4},total postings", f"{d},{cc},{v - 3},{v},new postings"]
    return "\n".join(rows) + "\n"


SECTORS = "\n".join([
    "date,jobcountry,indeed_job_postings_index,variable,display_name",
    "2026-08-28,US,74.62,total postings,Software Development",
    "2026-08-28,US,70.00,new postings,Software Development",
    "2026-09-25,US,78.09,total postings,Software Development",
    "2026-09-25,US,99.0,total postings,Nursing",
]) + "\n"


def _hiring_handler(fail=()):
    def h(req):
        name = req.url.path.rsplit("/", 1)[-1]
        if any(f in name for f in fail):
            return httpx.Response(500)
        if name.startswith("aggregate_job_postings_"):
            return httpx.Response(200, text=_agg(name[-6:-4]))
        if name == "job_postings_by_sector_US.csv":
            return httpx.Response(200, text=SECTORS)
        return httpx.Response(404)
    return h


def test_hiring_parsers():
    s = hiring_lab.parse_aggregate(_agg("US"))
    assert s[-1] == ("2026-09-25", 103.8) and len(s) == 3        # total postings only
    c = hiring_lab.change(s)
    assert c["ref_date"] == "2026-08-28" and c["chg_pts"] == pytest.approx(1.8)
    assert hiring_lab.change(s[-1:]) == {"date": "2026-09-25", "value": 103.8}
    sec = hiring_lab.parse_sectors(SECTORS, ["Software Development"])
    assert sec == {"Software Development": [("2026-08-28", 74.62), ("2026-09-25", 78.09)]}


@pytest.mark.asyncio
async def test_hiring_feed_lines_attribution_and_cache(monkeypatch, _data_dir):
    _transport(monkeypatch, hiring_lab, _hiring_handler(fail=("_DE",)))
    doc = await hiring_lab.load_postings(countries=("US", "DE"),
                                         sectors=("Software Development", "Retail"))
    lines = macro_alt.hiring_lines(doc)
    text = "\n".join(lines)
    assert "United States total postings: 103.8 on 2026-09-25; 4-week change +1.8 pts, +1.8%" in text
    assert "Germany total postings: unavailable (HTTPStatusError)" in text
    assert "US sector Software Development: 78.1" in text
    assert "US sector Retail: unavailable (sector not in file)" in text
    assert "CC BY 4.0" in lines[-1] and "Indeed Hiring Lab" in lines[-1]
    # stale cache + failed download -> cached copy with an explicit note
    f = _data_dir / "altdata" / "hiring_lab" / "aggregate_job_postings_US.csv"
    import os
    os.utime(f, (1, 1))
    _transport(monkeypatch, hiring_lab, _hiring_handler(fail=("aggregate",)))
    doc = await hiring_lab.load_postings(countries=("US",), sectors=())
    assert doc["countries"]["US"]["value"] == 103.8
    assert "download failed" in doc["notes"][0] and "cached copy" in doc["notes"][0]


@pytest.mark.asyncio
async def test_hiring_all_failed_raises(monkeypatch):
    _transport(monkeypatch, hiring_lab, lambda req: httpx.Response(500))
    with pytest.raises(RuntimeError):
        await hiring_lab.load_postings(countries=("US",), sectors=("Retail",))


# ── Apple App Store charts ──────────────────────────────────────────────────

def _entry(i, name, artist):
    return {"im:name": {"label": name}, "im:artist": {"label": artist},
            "id": {"label": f"https://apps.apple.com/app/id{i}",
                   "attributes": {"im:id": str(i), "im:bundleId": f"b.{i}"}},
            "category": {"attributes": {"im:id": "6015", "label": "Finance"}}}


def _feed(apps):
    return {"feed": {"updated": {"label": "2026-09-29T13:26:06-07:00"},
                     "entry": [_entry(i, n, a) for i, n, a in apps]}}


DAY1 = [(1, "Kalshi", "KalshiEX LLC"), (2, "Capital One Mobile", "Capital One"),
        (3, "Cash App", "Block, Inc."), (4, "Robinhood", "Robinhood Markets, Inc.")]
DAY2 = [(3, "Cash App", "Block, Inc."), (1, "Kalshi", "KalshiEX LLC"),
        (9, "New Thing", "Someone LLC"), (2, "Capital One Mobile", "Capital One")]


def _apple_handler(apps, fail_cc=()):
    def h(req):
        cc = req.url.path.split("/")[1]
        if cc in fail_cc:
            return httpx.Response(503)
        assert "/rss/top" in req.url.path and req.url.path.endswith("/json")
        return httpx.Response(200, json=_feed(apps))
    return h


def test_app_parsers_and_tickers():
    p = app_charts.parse_feed(_feed(DAY1))
    assert p["apps"][1] == {"rank": 2, "id": "2", "name": "Capital One Mobile",
                            "artist": "Capital One", "bundle": "b.2", "category": "Finance"}
    one = {"feed": {"entry": _entry(7, "Solo", "Nobody")}}        # single entry is a dict
    assert app_charts.parse_feed(one)["apps"][0]["rank"] == 1
    with pytest.raises(ValueError):
        app_charts.parse_feed({"nope": 1})
    assert app_charts.ticker_for("Block, Inc.") == "XYZ"
    assert app_charts.ticker_for("AMZN Mobile LLC") == "AMZN"
    assert app_charts.ticker_for("Blockchain Games Ltd") is None
    assert app_charts.chart_url("us", "finance", "grossing").endswith(
        "/us/rss/topgrossingapplications/limit=100/genre=6015/json")
    assert "/genre=" not in app_charts.chart_url("cn", "all", "free")
    a = app_charts.parse_feed(_feed(DAY1))["apps"]
    b = app_charts.parse_feed(_feed(DAY2))["apps"]
    rc = app_charts.rank_changes(a, b, top=3)
    assert [x["name"] for x in rc["entrants"]] == ["New Thing"]
    assert rc["risers"][0]["name"] == "Cash App" and rc["risers"][0]["move"] == 2
    assert rc["dropped"] == []
    assert [x["name"] for x in app_charts.rank_changes(b, a, top=3)["dropped"]] == ["New Thing"]


@pytest.mark.asyncio
async def test_archive_daily_is_idempotent_and_atomic(monkeypatch, _data_dir):
    calls = []
    _transport(monkeypatch, app_charts, _apple_handler(DAY1, fail_cc=("cn",)), calls)
    r = await app_charts.archive_daily("2026-09-29")
    total = len(app_charts.COUNTRIES) * len(app_charts.GENRES) * len(app_charts.CHARTS)
    assert r["written"] and r["charts_failed"] == 8 and r["charts_ok"] == total - 8
    doc = json.loads((_data_dir / "altdata" / "app_charts" / "2026-09-29.json").read_text("utf-8"))
    assert doc["charts"]["cn/all/free"] == {"error": "HTTPStatusError"}
    assert doc["charts"]["us/finance/free"]["apps"][0]["name"] == "Kalshi"
    assert not list((_data_dir / "altdata" / "app_charts").glob(".*.tmp"))
    # incomplete day -> refetch; complete day -> skipped without requests
    _transport(monkeypatch, app_charts, _apple_handler(DAY1), calls)
    assert (await app_charts.archive_daily("2026-09-29"))["charts_ok"] == total
    calls.clear()
    r = await app_charts.archive_daily("2026-09-29")
    assert r["skipped"] and calls == []
    _transport(monkeypatch, app_charts, lambda req: httpx.Response(500))
    with pytest.raises(RuntimeError):
        await app_charts.archive_daily("2026-09-30")
    assert app_charts.archived_days() == ["2026-09-29"]


@pytest.mark.asyncio
async def test_app_feed_one_day_then_changes(monkeypatch):
    _transport(monkeypatch, app_charts, _apple_handler(DAY1))
    lines = await macro_alt.fetch_apps("2026-09-29")            # nothing archived: live
    assert "live fetch, today's archive has not run yet" in lines[0]
    assert "need >= 2 archived days (archive has 0)" in lines[0]
    await app_charts.archive_daily("2026-09-29")
    _transport(monkeypatch, app_charts, _apple_handler(DAY2))
    await app_charts.archive_daily("2026-09-30")
    lines = await macro_alt.fetch_apps("2026-09-30")
    text = "\n".join(lines)
    assert "archived); rank changes vs archived 2026-09-29" in lines[0]
    assert "us/finance/free top 5: #1 Cash App [XYZ], #2 Kalshi" in text
    assert "up: Cash App [XYZ] #1 (+2)" in text
    assert "XYZ us/all/free #1 (was #3)" in text
    assert "HOOD" not in lines[-1]                            # dropped out of the charts
