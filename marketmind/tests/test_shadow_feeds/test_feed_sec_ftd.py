"""Offline tests: SEC fails-to-deliver gateway and the equity_stress feed (owner decision 2026-09-29).
Payload shapes copy the live responses checked 2026-09-29.
"""
import io
import zipfile

import httpx
import pytest

from marketmind.gateway import sec_ftd
from marketmind.shadow_feeds import equity_stress


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


# ── SEC fails-to-deliver ────────────────────────────────────────────────────

HEADER = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE"


def _fails_zip(name, rows) -> bytes:
    text = "\n".join([HEADER, *rows, f"Trailer record count {len(rows)}",
                      "Trailer total quantity of shares 1"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{name}.txt", text.encode("latin-1"))
    return buf.getvalue()


LATEST = _fails_zip("cnsfails202609a", [
    "20260901|46090E103|QQQ|1000|INVESCO QQQ TR|500.00",
    "20260902|46090E103|QQQ|3000|INVESCO QQQ TR|510.00",
    "20260901|88160R101|TSLA|200|TESLA INC|.",
    "20260902|999999999|ZZZZ|50000000|BIG FAILS INC|10.00",
    "20260902|999999998|UPST|400|UPSTART HLDGS|30.00",
])
PRIOR = _fails_zip("cnsfails202608b", [
    "20260817|46090E103|QQQ|1000|INVESCO QQQ TR|490.00",
    "20260818|46090E103|QQQ|1000|INVESCO QQQ TR|495.00",
])
PAGE = ('<a href="/files/data/fails-deliver-data/cnsfails202609a.zip">Sep a</a>'
        '<a href="/files/data/fails-deliver-data/cnsfails202608b.zip">Aug b</a>'
        '<a href="/files/data/other/fails-deliver-data/cnsfails202505b.zip">old</a>')


def _sec_handler(page_status=200):
    def h(req):
        assert "MarketMind" in req.headers["User-Agent"] and "@" in req.headers["User-Agent"]
        if req.url.path.endswith("fails-deliver-data"):
            return httpx.Response(page_status, text=PAGE)
        if req.url.path.endswith("202609a.zip"):
            return httpx.Response(200, content=LATEST)
        if req.url.path.endswith("202608b.zip"):
            return httpx.Response(200, content=PRIOR)
        return httpx.Response(404)
    return h


def test_ftd_parsers():
    assert sec_ftd.parse_index(PAGE)["202505b"].startswith("/files/data/other/")
    p = sec_ftd.parse_fails(sec_ftd.zip_text(LATEST), "202609a")
    assert p.dates == ["2026-09-01", "2026-09-02"]
    q = p.tickers["QQQ"]
    assert (q.days, q.last_date, q.last_shares, q.max_shares) == (2, "2026-09-02", 3000, 3000)
    assert q.avg_shares == 2000 and q.avg_value == (1000 * 500 + 3000 * 510) / 2
    assert p.tickers["TSLA"].last_value is None           # SEC printed '.' for price
    with pytest.raises(ValueError):
        sec_ftd.parse_fails("not|a|header")


@pytest.mark.asyncio
async def test_ftd_feed_lines_and_cache(monkeypatch, _data_dir):
    calls = []
    _transport(monkeypatch, sec_ftd, _sec_handler(), calls)
    doc = await sec_ftd.load_ftd(["QQQ", "TSLA", "UPST", "SPY"])
    assert doc["latest"]["period"] == "202609a" and doc["prior"]["period"] == "202608b"
    assert doc["tickers"]["QQQ"]["chg_avg_shares_pct"] == pytest.approx(100.0)
    assert doc["top"] == []                                  # top list needs >= 3 dates
    lines = equity_stress.build_lines(doc, ["QQQ", "TSLA", "UPST", "SPY"])
    text = "\n".join(lines)
    assert "2-4 weeks after settlement" in lines[0]
    assert "2026-09-01..2026-09-02" in text and "compared with 202608b" in text
    assert "QQQ: fails on 2/2 dates; latest 2026-09-02 3,000 sh ($1.53M)" in text
    assert "avg +100% vs prior period" in text
    assert "TSLA:" in text and "value n/a (no SEC price)" in text
    assert "UPST:" in text and "not in the prior period file" in text
    assert "No fails reported in 202609a for: SPY" in text
    # ZIPs are cached; a second run downloads only the index page
    assert (_data_dir / "altdata" / "sec_ftd" / "cnsfails202609a.zip").exists()
    calls.clear()
    await sec_ftd.load_ftd(["QQQ"])
    assert len(calls) == 1 and calls[0].endswith("fails-deliver-data")


@pytest.mark.asyncio
async def test_ftd_page_down_uses_cache_or_fails_loudly(monkeypatch):
    _transport(monkeypatch, sec_ftd, _sec_handler(page_status=503))
    with pytest.raises(httpx.HTTPStatusError):               # nothing cached yet
        await sec_ftd.load_ftd(["QQQ"])
    _transport(monkeypatch, sec_ftd, _sec_handler())
    await sec_ftd.load_ftd(["QQQ"])
    _transport(monkeypatch, sec_ftd, _sec_handler(page_status=503))
    doc = await sec_ftd.load_ftd(["QQQ"])
    assert doc["latest"]["period"] == "202609a" and "newest cached files" in doc["note"]


def test_ftd_watched_symbols_are_us_listed():
    w = equity_stress.watched()
    assert "UPST" in w and "TSLA" in w and "IWM" in w
    assert all("." not in t and "-" not in t for t in w)
