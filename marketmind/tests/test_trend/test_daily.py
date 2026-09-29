"""Daily / weekend trend step, report facts and dashboard view (synthetic bars, fake clock)."""
import asyncio
import json
from datetime import date, datetime, timezone

import pytest

from marketmind.trend import daily
from marketmind.trend.rules import TrendConfig
from marketmind.trend.state import simulate
from marketmind.tests.test_trend.test_rules_state import flat_then_up, make_bars

UNIVERSE = ["SPY", "GLD", "BTC-USD"]


def at(d: str, hour: int = 21) -> datetime:
    """A fake clock: `hour` UTC on date d (21:00 UTC is 17:00 in New York)."""
    y, m, dd = map(int, d.split("-"))
    return datetime(y, m, dd, hour, tzinfo=timezone.utc)


@pytest.fixture
def series():
    spy = flat_then_up(300, 60, 0.01)
    spy += [spy[-1] * (0.96 ** k) for k in range(1, 15)]          # then a crash -> exit
    bars = make_bars(spy)
    sim = simulate("SPY", bars, TrendConfig(), 0.0)
    tr = sim.trades[0]
    gld = make_bars([100.0 + (0.5 if i % 2 else -0.5) for i in range(len(spy))])
    btc = make_bars([100.0 + (0.5 if i % 2 else -0.5) for i in range(500)], start="2020-01-01",
                    crypto=True)
    return {"SPY": bars, "GLD": gld, "BTC-USD": btc, "entry": tr.signal_idx,
            "exit": tr.exit_signal_idx}


def fetcher(histories, seen=None):
    async def fetch(tickers):
        if seen is not None:
            seen.append(list(tickers))
        return ({t: histories.get(t) for t in tickers}, {t: "test" for t in tickers}, 0.0,
                "test hurdle")
    return fetch


def cut(series, i):
    """Histories as of SPY/GLD bar i (crypto aligned to the same calendar date)."""
    d = series["SPY"][i].date
    return {"SPY": series["SPY"][:i + 1], "GLD": series["GLD"][:i + 1],
            "BTC-USD": [b for b in series["BTC-USD"] if b.date <= d]}, d


def run(tmp_path, hist, d, mode="daily", seen=None):
    return asyncio.run(daily.run_trend_step(tmp_path, mode, now=at(d), fetch=fetcher(hist, seen),
                                            universe=UNIVERSE))


def test_ny_date_uses_new_york_calendar():
    assert daily.ny_date(datetime(2026, 9, 29, 2, tzinfo=timezone.utc)) == "2026-09-28"
    assert daily.ny_date(datetime(2026, 9, 29, 12, tzinfo=timezone.utc)) == "2026-09-29"


def test_entry_then_exit_across_days(tmp_path, series):
    i = series["entry"]
    hist, d0 = cut(series, i - 1)
    s0 = run(tmp_path, hist, d0)
    assert s0["changes"]["full"] == {"entries": [], "exits": []}
    assert (tmp_path / "trend" / f"{d0}.json").exists()
    assert not list((tmp_path / "trend").glob("*.tmp"))            # atomic write, no leftovers

    hist, d1 = cut(series, i)
    s1 = run(tmp_path, hist, d1)
    assert s1["full"]["SPY"]["state"] == "TREND" and s1["full"]["SPY"]["event"] == "ENTRY"
    assert s1["changes"]["full"]["entries"] == ["SPY"]
    assert s1["changes"]["lean"]["entries"] == ["SPY"]
    assert s1["counts"] == {"TREND": 1, "CASH": 2, "UNAVAILABLE": 0}
    line = daily.summary_line(s1)
    assert line == "[trend] 1 TREND, 2 CASH, 0 unavailable; entries: SPY (lean: SPY); exits: none"

    hist, d2 = cut(series, series["exit"])
    s2 = run(tmp_path, hist, d2)
    assert s2["full"]["SPY"]["state"] == "EXIT"
    assert s2["changes"]["full"] == {"entries": [], "exits": ["SPY"]}
    saved = json.loads((tmp_path / "trend" / f"{d2}.json").read_text(encoding="utf-8"))
    assert saved["date"] == d2 and saved["mode"] == "daily"
    assert saved["full"]["SPY"]["stop_level"] is None
    assert set(saved["lean"]["states"]) >= {"SPY", "GLD", "BTC-USD"}


def test_first_run_counts_only_todays_events(tmp_path, series):
    hist, d = cut(series, series["entry"] + 3)                     # already trending
    s = run(tmp_path, hist, d)
    assert s["full"]["SPY"]["state"] == "TREND"
    assert s["changes"]["full"]["entries"] == []                   # no previous file, no event


def test_unavailable_instrument(tmp_path, series):
    hist, d = cut(series, series["entry"])
    hist["GLD"] = None
    s = run(tmp_path, hist, d)
    assert s["full"]["GLD"]["state"] == "UNAVAILABLE"
    assert "1 unavailable" in daily.summary_line(s)


def test_weekend_covers_crypto_only_and_monday_compares_with_friday(tmp_path, series):
    i = series["entry"]
    hist, fri = cut(series, i - 1)
    run(tmp_path, hist, fri)
    seen = []
    sat = (date.fromisoformat(fri).toordinal() + 1)
    sat = date.fromordinal(sat).isoformat()
    s = run(tmp_path, hist, sat, mode="weekend", seen=seen)
    assert seen == [["BTC-USD"]]
    assert set(s["full"]) == {"BTC-USD"} and s["mode"] == "weekend"
    hist, mon = cut(series, i)
    s = run(tmp_path, hist, mon)
    assert s["changes"]["full"]["entries"] == ["SPY"]              # vs Friday's SPY record


def test_no_data_at_all_raises(tmp_path):
    with pytest.raises(RuntimeError):
        run(tmp_path, {}, "2026-09-29")


def test_changes_rules():
    prev = {"A": {"state": "TREND", "entry_signal_date": "d1"}, "B": {"state": "CASH"},
            "C": {"state": "TREND", "entry_signal_date": "d1"}, "D": {"state": "UNAVAILABLE"}}
    cur = {"A": {"state": "TREND", "entry_signal_date": "d1"}, "B": {"state": "TREND"},
           "C": {"state": "UNAVAILABLE"}, "D": {"state": "TREND", "event": None},
           "E": {"state": "EXIT", "event": "EXIT"}}
    assert daily.changes(prev, cur) == {"entries": ["B"], "exits": ["E"]}
    moved = {"A": {"state": "TREND", "entry_signal_date": "d2"}}
    assert daily.changes(prev, moved) == {"entries": ["A"], "exits": ["A"]}


# ── orchestration step ──────────────────────────────────────────────────────

def test_orchestration_step_prints_one_line(tmp_path, series, monkeypatch, capsys):
    from types import SimpleNamespace
    from marketmind.pipeline import orchestration as orch
    hist, d = cut(series, series["entry"])
    orig = daily.run_trend_step

    async def fake(data_dir, mode="daily"):
        assert data_dir == tmp_path and mode == "weekend"
        return await orig(data_dir, mode, now=at(d), fetch=fetcher(hist), universe=UNIVERSE)
    monkeypatch.setattr(daily, "run_trend_step", fake)
    orch._reset_step_failures()
    asyncio.run(orch.trend_step(SimpleNamespace(data_dir=tmp_path), crypto_only=True))
    out = capsys.readouterr().out
    assert out.strip().startswith("[trend] 0 TREND, 1 CASH, 0 unavailable; entries: none")
    assert orch._step_failures == []


def test_orchestration_step_failure_is_degraded(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from marketmind.pipeline import orchestration as orch

    async def boom(*a, **k):
        raise RuntimeError("price source down")
    monkeypatch.setattr(daily, "run_trend_step", boom)
    orch._reset_step_failures()
    try:
        asyncio.run(orch.trend_step(SimpleNamespace(data_dir=tmp_path)))
        assert orch._step_failures == ["trend"]
        assert "[trend] failed" in capsys.readouterr().out
        assert orch._finish_exit_code(0) == orch.DEGRADED_EXIT
    finally:
        orch._reset_step_failures()


def test_trend_step_runs_before_alerts_in_daily_and_in_weekend():
    import inspect
    from marketmind.pipeline import orchestration as orch
    src = inspect.getsource(orch._run_daily_with_shadows)
    assert src.index("await trend_step(config)") < src.index("await daily_report_step(config)")
    assert "await trend_step(config, crypto_only=True)" in inspect.getsource(orch.run_weekend)


# ── report facts and dashboard ──────────────────────────────────────────────

def test_report_facts_and_dashboard(tmp_path, series, monkeypatch):
    i = series["entry"]
    run(tmp_path, *cut(series, i - 1))
    hist, d = cut(series, i)
    run(tmp_path, hist, d)
    f = daily.report_facts(tmp_path, d)
    assert f["entries_today"] == ["SPY"] and f["exits_today"] == []
    assert f["trend"][0]["ticker"] == "SPY" and f["trend"][0]["stop_level"] is not None
    assert f["unavailable"] == [] and f["lean"]["trend"] == ["SPY"]

    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    from marketmind.reports import daily as report
    assert report.gather_facts(d)["趋势状态"]["entries_today"] == ["SPY"]

    # a later weekend file holds crypto only; the view carries the rest forward
    sat = date.fromordinal(date.fromisoformat(d).toordinal() + 1).isoformat()
    run(tmp_path, hist, sat, mode="weekend")
    from marketmind.api import whitebox
    v = whitebox.get_trend()
    assert v["available"] and v["date"] == sat and v["mode"] == "weekend"
    rows = {r["ticker"]: r for r in v["rows"]}
    assert rows["SPY"]["state"] == "TREND" and rows["SPY"]["carried"] is True
    assert rows["BTC-USD"]["carried"] is False
    assert rows["SPY"]["excess_12m"] == pytest.approx(rows["SPY"]["ret_12m"])
    assert v["rows"][0]["ticker"] == "SPY"                         # TREND first
    assert whitebox.get_trend("bad")["available"] is False
    assert whitebox.get_trend("1999-01-01")["available"] is False


def test_dashboard_route_and_tab(tmp_path, monkeypatch):
    from pathlib import Path
    from fastapi.testclient import TestClient
    from marketmind.api.routes import app
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    c = TestClient(app, base_url="http://127.0.0.1:8520")
    r = c.get("/api/wb/trend")
    assert r.status_code == 200 and r.json()["available"] is False
    html = (Path(__file__).resolve().parents[2] / "whitebox.html").read_text(encoding="utf-8")
    assert '["trend","趋势状态"]' in html and "trend:loadTrend" in html and 'id="s-trend"' in html
