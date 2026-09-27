"""Offline tests for pipeline/sources_alternative.py (Wikipedia, GDELT, PortWatch)."""
import io
import zipfile
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import marketmind.pipeline.sources_alternative as sa
from marketmind.pipeline.scout import NewsItem

SRC = SimpleNamespace(name="Alt Test", tier=3, reliability=0.6)


def _resp(status: int = 200, payload=None, text: str = "", content: bytes = b"") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = text
    resp.content = content
    if status == 200:
        resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            f"{status}", request=MagicMock(), response=MagicMock()))
    return resp


def _client(*responses) -> AsyncMock:
    client = AsyncMock()
    client.get.side_effect = list(responses)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# ── Wikipedia ───────────────────────────────────────────────────────────────

def _series(base: int, latest: int, n: int = 29) -> list[tuple[str, int]]:
    start = date(2026, 8, 29)
    days = [(start + timedelta(days=i)).strftime("%Y%m%d00") for i in range(n)]
    return [(d, base) for d in days[:-1]] + [(days[-1], latest)]


def test_spike_detected_at_threshold():
    spike = sa.detect_pageview_spike(_series(1000, 3000))
    assert spike and spike["ratio"] == pytest.approx(3.0) and spike["views"] == 3000


def test_no_spike_below_ratio_or_floor_or_short_history():
    assert sa.detect_pageview_spike(_series(1000, 2900)) is None       # 2.9x
    assert sa.detect_pageview_spike(_series(100, 900)) is None         # 9x but < 1000 views
    assert sa.detect_pageview_spike(_series(1000, 5000, n=10)) is None  # too little history


def test_spike_uses_median_not_mean():
    s = _series(1000, 3500)
    s[3] = (s[3][0], 100_000)  # one outlier day in the trailing window
    assert sa.detect_pageview_spike(s)["median"] == 1000


def test_wiki_articles_map_is_reasonable():
    assert 20 <= len(sa.WIKI_ARTICLES) <= 30
    assert all(" " not in t for t in sa.WIKI_ARTICLES.values())  # canonical underscore titles
    assert "@" in sa._UA  # Wikimedia wants contact info


def _wiki_payload(series):
    return {"items": [{"timestamp": d, "views": v} for d, v in series]}


@pytest.mark.asyncio
async def test_fetch_wikipedia_bounded_and_sorted(monkeypatch):
    monkeypatch.setattr(sa, "WIKI_REQUEST_DELAY", 0)
    monkeypatch.setattr(sa, "WIKI_ARTICLES", {f"T{i}": f"Art_{i}" for i in range(8)})
    # Every article spikes, with increasing ratio.
    resps = [_resp(payload=_wiki_payload(_series(1000, 3000 + 1000 * i))) for i in range(8)]
    with patch("httpx.AsyncClient", return_value=_client(*resps)):
        items = await sa.fetch_wikipedia_attention(SRC)
    assert len(items) == sa.WIKI_MAX_ITEMS
    assert all(isinstance(i, NewsItem) for i in items)
    assert "Art 7" in items[0].title and "(T7)" in items[0].title  # highest ratio first
    assert items[0].published_at == "2026-09-26"


@pytest.mark.asyncio
async def test_fetch_wikipedia_skips_404_but_raises_on_429(monkeypatch):
    monkeypatch.setattr(sa, "WIKI_REQUEST_DELAY", 0)
    monkeypatch.setattr(sa, "WIKI_ARTICLES", {"A": "Gone", "B": "Ok"})
    ok = _resp(payload=_wiki_payload(_series(1000, 1000)))
    with patch("httpx.AsyncClient", return_value=_client(_resp(404), ok)):
        assert await sa.fetch_wikipedia_attention(SRC) == []
    with patch("httpx.AsyncClient", return_value=_client(_resp(429), ok)):
        with pytest.raises(httpx.HTTPStatusError):
            await sa.fetch_wikipedia_attention(SRC)


@pytest.mark.asyncio
async def test_fetch_wikipedia_raises_when_all_404(monkeypatch):
    monkeypatch.setattr(sa, "WIKI_REQUEST_DELAY", 0)
    monkeypatch.setattr(sa, "WIKI_ARTICLES", {"A": "X", "B": "Y"})
    with patch("httpx.AsyncClient", return_value=_client(_resp(404), _resp(404))):
        with pytest.raises(httpx.HTTPStatusError):
            await sa.fetch_wikipedia_attention(SRC)


# ── GDELT ───────────────────────────────────────────────────────────────────

def _grow(code="190", goldstein="-10", mentions="10", cc="UP", geo="Kyiv, Kyiv, Ukraine",
          url="https://ex.com/a", a1="RUSSIA", a2="UKRAINE", a1cc="RUS", a2cc="UKR",
          a1type="", a2type="", sources="3", tone="-5") -> list[str]:
    row = [""] * 61
    row[6], row[16], row[7], row[17], row[12], row[22] = a1, a2, a1cc, a2cc, a1type, a2type
    row[26], row[27], row[28] = code, code[:3], code[:2]
    row[30], row[31], row[32], row[34] = goldstein, mentions, sources, tone
    row[52], row[53], row[60] = geo, cc, url
    return row


def test_gdelt_filter_keeps_high_impact_geopolitics_only():
    rows = [
        _grow(url="u1"),                                                   # kept: intl, -10
        _grow(code="042", goldstein="1.9", mentions="99", url="u2"),       # root 04 dropped
        _grow(code="190", goldstein="-3", mentions="2", url="u3"),         # weak + few mentions
        _grow(a1cc="USA", a2cc="USA", a1type="COP", a2type="", url="u4"),  # domestic police
        _grow(a1cc="", a2cc="", a1type="MIL", url="u5"),                   # state actor: kept
        _grow(code="163", goldstein="-8", mentions="1", a1cc="USA", a2cc="USA", url="u6"),  # sanctions
        _grow()[:40],                                                      # truncated row
    ]
    clusters = sa.aggregate_gdelt_rows(rows)
    assert clusters[("UP", "19")].events == 2
    assert clusters[("UP", "16")].events == 1
    assert sum(c.events for c in clusters.values()) == 3


def test_gdelt_same_url_counted_once_per_cluster():
    clusters = sa.aggregate_gdelt_rows([_grow(url="same"), _grow(url="same"), _grow(url="other")])
    assert clusters[("UP", "19")].events == 2


def test_gdelt_top_clusters_bounded_and_ranked():
    rows = [_grow(cc=f"C{i}", mentions=str(10 + i), url=f"u{i}") for i in range(12)]
    rows.append(_grow(cc="LOW", mentions="3", goldstein="-9", url="low"))  # below cluster floor
    top = sa.top_gdelt_clusters(sa.aggregate_gdelt_rows(rows))
    assert len(top) == sa.GDELT_MAX_ITEMS
    assert top[0].country_code == "C11"
    assert all(c.country_code != "LOW" for c in top)
    item = sa.gdelt_cluster_to_newsitem(top[0], "w", SRC)
    assert "Armed fighting in Ukraine" in item.title and item.url == "u11"


def test_parse_lastupdate():
    text = ("35196 abc http://data.gdeltproject.org/gdeltv2/20260927080000.export.CSV.zip\n"
            "47356 def http://data.gdeltproject.org/gdeltv2/20260927080000.mentions.CSV.zip\n")
    assert sa.parse_lastupdate(text) == "20260927080000"
    with pytest.raises(ValueError):
        sa.parse_lastupdate("garbage")
    assert sa._previous_stamps("20260927080000", 3) == [
        "20260927080000", "20260927074500", "20260927073000"]


def _zip_rows(rows) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.export.CSV", "\n".join("\t".join(r) for r in rows) + "\n")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_gdelt_end_to_end(monkeypatch):
    monkeypatch.setattr(sa, "GDELT_FILES", 2)
    last = _resp(text="1 a http://data.gdeltproject.org/gdeltv2/20260927080000.export.CSV.zip\n")
    z1 = _resp(content=_zip_rows([_grow(url="u1", mentions="30")]))
    z2 = _resp(404)  # older slot missing -> skipped
    client = _client(last, z1, z2)
    with patch("httpx.AsyncClient", return_value=client):
        items = await sa.fetch_gdelt_events(SRC)
    assert len(items) == 1 and items[0].url == "u1"
    assert "07:45-08:15 UTC" in items[0].summary
    assert client.get.call_args_list[2].args[0].endswith("20260927074500.export.CSV.zip")


@pytest.mark.asyncio
async def test_fetch_gdelt_raises_on_non_200():
    with patch("httpx.AsyncClient", return_value=_client(_resp(503))):
        with pytest.raises(httpx.HTTPStatusError):
            await sa.fetch_gdelt_events(SRC)
    last = _resp(text="1 a http://x/20260927080000.export.CSV.zip\n")
    with patch("httpx.AsyncClient", return_value=_client(last, _resp(404))):  # newest file 404
        with pytest.raises(httpx.HTTPStatusError):
            await sa.fetch_gdelt_events(SRC)


# ── PortWatch ───────────────────────────────────────────────────────────────

def _pw(port: str, latest: date, recent: float, base: float, days: int = 97) -> list[dict]:
    out = []
    for i in range(days):
        d = latest - timedelta(days=i)
        out.append({"portid": port, "date": d.isoformat(), "n_total": recent if i < 7 else base})
    return out


def test_chokepoint_deviation_flags_at_20pct():
    L = date(2026, 9, 20)
    recs = _pw("chokepoint6", L, 8, 10) + _pw("chokepoint1", L, 8.5, 10) + _pw("chokepoint2", L, 13, 10)
    devs = {d["portid"]: d for d in sa.chokepoint_deviations(recs)}
    assert devs["chokepoint6"]["flag"] and devs["chokepoint6"]["deviation"] == pytest.approx(-0.2)
    assert not devs["chokepoint1"]["flag"]
    assert devs["chokepoint2"]["flag"] and devs["chokepoint2"]["deviation"] == pytest.approx(0.3)


def test_chokepoint_requires_history_and_min_volume():
    L = date(2026, 9, 20)
    assert sa.chokepoint_deviations(_pw("chokepoint6", L, 1, 10, days=30)) == []  # short baseline
    assert sa.chokepoint_deviations(_pw("chokepoint6", L, 0, 2)) == []            # tiny volume


def test_chokepoint_yoy_is_context_only():
    L = date(2026, 9, 20)
    prior = [{"portid": "chokepoint6", "date": (L - timedelta(days=364 + i)).isoformat(), "n_total": 20}
             for i in range(7)]
    (d,) = sa.chokepoint_deviations(_pw("chokepoint6", L, 10, 10), prior)
    assert d["yoy"] == pytest.approx(-0.5) and not d["flag"]
    item = sa.chokepoint_to_newsitem(dict(d, deviation=-0.3), SRC)
    assert "Strait of Hormuz transits down 30%" in item.title and "-50%" in item.summary


@pytest.mark.asyncio
async def test_fetch_portwatch_only_flagged():
    L = date(2026, 9, 20)
    recs = _pw("chokepoint6", L, 3, 10) + _pw("chokepoint1", L, 10, 10)
    page = {"features": [{"attributes": r} for r in recs]}
    client = _client(_resp(payload=page), _resp(payload={"features": []}))
    with patch("httpx.AsyncClient", return_value=client):
        items = await sa.fetch_portwatch_chokepoints(SRC)
    assert len(items) == 1 and "Hormuz" in items[0].title
    assert "'chokepoint6'" in client.get.call_args_list[0].kwargs["params"]["where"]


@pytest.mark.asyncio
async def test_fetch_portwatch_errors_raise():
    with patch("httpx.AsyncClient", return_value=_client(_resp(500))):
        with pytest.raises(httpx.HTTPStatusError):
            await sa.fetch_portwatch_chokepoints(SRC)
    err = _resp(payload={"error": {"code": 400, "message": "bad where"}})
    with patch("httpx.AsyncClient", return_value=_client(err)):
        with pytest.raises(ValueError):
            await sa.fetch_portwatch_chokepoints(SRC)


def test_proxy_passed_through():
    kw = sa._client_kwargs(SimpleNamespace(proxy_url="http://127.0.0.1:7890"))
    assert kw["proxy"] == "http://127.0.0.1:7890" and kw["timeout"] == sa.HTTP_TIMEOUT
    assert "proxy" not in sa._client_kwargs(None)
