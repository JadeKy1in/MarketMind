"""Discovery runner with a fake registry and fake prices (fully offline)."""
import json
from datetime import date, timedelta

import pytest

from marketmind.discovery import runner as rn
from marketmind.discovery.series import Series
from marketmind.gateway.price_history import Bar

TODAY = "2026-09-28"
OBS_END = "2026-09-25"


def _daily(values, end=OBS_END):
    e = date.fromisoformat(end)
    n = len(values)
    return [((e - timedelta(days=n - 1 - i)).isoformat(), float(v)) for i, v in enumerate(values)]


def _zigzag(n):
    return [100.0 + (1 if i % 2 else -1) for i in range(n)]


def _const(obs):
    async def fetch(ctx):
        return obs
    return fetch


async def _boom(ctx):
    raise ConnectionError("host unreachable")


async def _empty(ctx):
    return []


def _registry():
    return [
        Series("test:SPIKE", "Spiking series", "daily", "idx", "fake", _const(_daily(_zigzag(300) + [110.0])),
               (("SPY", 1), ("TLT", -1)), ("spike",), "prior"),
        Series("test:DROP", "Dropping series", "daily", "idx", "fake", _const(_daily(_zigzag(300) + [85.0])),
               (("BTC-USD", 1),), ("drop",), "prior"),
        Series("test:QUIET", "Quiet series", "daily", "idx", "fake", _const(_daily(_zigzag(300))),
               (("SPY", 1),), ("quiet",)),
        Series("test:SHORT", "Short series", "daily", "idx", "fake", _const(_daily([1.0, 2.0, 99.0])),
               (("SPY", 1),), ("short",)),
        Series("test:DOWN", "Broken source", "weekly", "idx", "fake", _boom, (("SPY", 1),), ("x",)),
        Series("test:EMPTY", "Empty source", "weekly", "idx", "fake", _empty, (("SPY", 1),), ("x",)),
        Series("test:STALE", "Stale source", "daily", "idx", "fake",
               _const(_daily(_zigzag(300), end="2026-06-30")), (("SPY", 1),), ("x",)),
    ]


def _bars(after_close, n=40, end_base=OBS_END):
    """n flat bars at 100 ending on the observation date, then one bar at `after_close`."""
    e = date.fromisoformat(end_base)
    out = [Bar((e - timedelta(days=n - 1 - i)).isoformat(), 100.0, 100.5, 99.5, 100.0, 1000.0)
           for i in range(n)]
    out.append(Bar((e + timedelta(days=1)).isoformat(), after_close, after_close + 0.5,
                   after_close - 0.5, after_close, 2000.0))
    return out


PRICES = {"SPY": _bars(100.2), "TLT": _bars(97.0), "BTC-USD": None}


async def _loader(t):
    return PRICES.get(t)


NEWS = [{"title": "Big DROP in the data", "summary": "", "published_at": "2026-09-27T00:00:00Z"}] * 3


@pytest.fixture
def report(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    return asyncio.run(rn.run_discovery(NEWS, TODAY, registry=_registry(), price_loader=_loader))


def test_report_file_written_under_data_dir(report, tmp_path):
    f = tmp_path / "discovery" / f"{TODAY}.json"
    assert report["file"] == str(f) and f.exists()
    on_disk = json.loads(f.read_text(encoding="utf-8"))
    assert on_disk["date"] == TODAY and len(on_disk["anomalies"]) == 2
    assert rn.load_report(TODAY)["counts"] == on_disk["counts"]


def test_unavailable_series_are_listed_with_reasons(report):
    un = {u["series"]: u["reason"] for u in report["unavailable"]}
    assert set(un) == {"test:DOWN", "test:EMPTY", "test:STALE"}
    assert "ConnectionError" in un["test:DOWN"] and "host unreachable" in un["test:DOWN"]
    assert un["test:EMPTY"] == "no observations returned"
    assert un["test:STALE"].startswith("stale")
    c = report["counts"]
    assert (c["series"], c["ok"], c["unavailable"], c["anomalies"]) == (7, 4, 3, 2)
    statuses = {s["series"]: s["status"] for s in report["series"]}
    assert statuses["test:DOWN"] == "unavailable" and statuses["test:QUIET"] == "ok"
    short = next(s for s in report["series"] if s["series"] == "test:SHORT")
    assert short["latest"] == 99.0 and short["z"] is None and not short["is_anomaly"]


def test_anomalies_ids_origin_coverage_and_order(report):
    a_spike, a_drop = report["anomalies"]           # cold first
    assert a_spike["series"] == "test:SPIKE" and a_spike["cold"] and a_spike["coverage"] == 0
    assert a_drop["series"] == "test:DROP" and not a_drop["cold"] and a_drop["coverage"] == 3
    assert a_spike["anomaly_id"] == f"{TODAY}:test:SPIKE"
    assert a_spike["obs_date"] == OBS_END and a_spike["latest"] == 110.0
    assert a_spike["move"] == 1 and a_drop["move"] == -1
    assert a_spike["origin"] == {"kind": "anomaly", "series": ["test:SPIKE"],
                                 "anomaly_id": f"{TODAY}:test:SPIKE",
                                 "priced_in": "not_priced", "coverage": 0}


def test_priced_in_rows_per_proxy(report):
    spike = report["anomalies"][0]
    rows = {p["ticker"]: p for p in spike["proxies"]}
    assert rows["SPY"]["direction"] == "long" and rows["SPY"]["bucket"] == "not_priced"
    # TLT prior -1 x move +1 -> short; it fell 3 ATR -> priced in
    assert rows["TLT"]["direction"] == "short" and rows["TLT"]["bucket"] == "priced_in"
    assert rows["TLT"]["volume_ratio"] == pytest.approx(2.0)
    assert rows["TLT"]["origin"]["priced_in"] == "priced_in"
    drop = report["anomalies"][1]
    btc = drop["proxies"][0]
    assert btc["direction"] == "short" and btc["bucket"] == "unavailable" and btc["reason"]
    assert drop["priced_in"] == "unavailable"


def test_candidates_and_origin_for(report):
    cands = rn.candidates(report)
    assert [c["ticker"] for c in cands] == ["SPY"]        # TLT priced in, BTC unavailable
    assert cands[0]["direction"] == "long" and cands[0]["anomaly_id"] == f"{TODAY}:test:SPIKE"
    assert rn.candidate_tickers(report) == ["SPY"]
    assert rn.origin_for(report, "SPY")["series"] == ["test:SPIKE"]
    assert rn.origin_for(report, "TLT") is None


def test_candidate_ranking_cold_first_then_abs_z():
    def a(aid, cold, z, ticker, bucket="not_priced"):
        return {"anomaly_id": aid, "series": aid, "title": aid, "cold": cold, "coverage": 0 if cold else 5,
                "z": z, "proxies": [{"ticker": ticker, "bucket": bucket, "direction": "long",
                                     "move_atr": 0.1, "origin": {"anomaly_id": aid}}]}
    rep = {"anomalies": [a("hot_big", False, 9.0, "AAA"), a("cold_small", True, 2.1, "BBB"),
                         a("cold_big", True, -4.0, "CCC"), a("cold_none", True, None, "DDD"),
                         a("cold_priced", True, 8.0, "EEE", "priced_in"),
                         a("cold_dup", True, 1.0, "CCC", "partial")]}
    assert rn.candidate_tickers(rep) == ["CCC", "BBB", "DDD", "AAA"]
    assert rn.candidate_tickers(rep, max_n=2) == ["CCC", "BBB"]


def test_prompt_block_is_compact_and_lists_unavailable(report):
    text = rn.prompt_block(report)
    lines = text.splitlines()
    assert lines[0].startswith("Cold-data anomalies 2026-09-28")
    assert "[cold, news 0] Spiking series (test:SPIKE) 2026-09-25: 110.00 idx" in lines[1]
    assert "SPY long not_priced" in lines[1] and "TLT short priced_in (-3.0 ATR)" in lines[1]
    assert lines[-1].startswith("- Unavailable series today (3): test:DOWN")
    assert "none today" in rn.prompt_block({"date": TODAY, "anomalies": []})


def test_write_false_and_timeout(tmp_path):
    import asyncio

    async def slow(ctx):
        await asyncio.sleep(5)
        return []
    reg = [Series("test:SLOW", "Slow", "daily", "idx", "fake", slow, (("SPY", 1),))]
    rep = asyncio.run(rn.run_discovery([], TODAY, registry=reg, price_loader=_loader,
                                       write=False, fetch_timeout_s=0.05, out_dir=tmp_path))
    assert "file" not in rep and not list(tmp_path.iterdir())
    assert rep["unavailable"][0]["reason"].startswith("timeout")


def test_price_loader_failure_is_reported_not_raised(tmp_path):
    import asyncio

    async def bad_loader(t):
        raise RuntimeError("feed down")
    reg = _registry()[:1]
    rep = asyncio.run(rn.run_discovery([], TODAY, registry=reg, price_loader=bad_loader, out_dir=tmp_path))
    rows = rep["anomalies"][0]["proxies"]
    assert all(r["bucket"] == "unavailable" and "RuntimeError" in r["reason"] for r in rows)
    assert rn.candidates(rep) == []
