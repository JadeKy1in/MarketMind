"""Daily report (docs/DAILY_REPORT.md): facts from the day's files, LLM text, fallback, push."""
import json
from dataclasses import dataclass

import pytest

from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.reports import daily

TODAY = "2026-09-29"


@dataclass
class _News:
    title: str
    source_name: str
    priority_score: float
    url: str = ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    briefs = tmp_path / "briefs"
    briefs.mkdir()
    (briefs / f"{TODAY}.json").write_text(json.dumps({
        "decision_summary": "不交易：风险回报不足", "has_no_trade": True,
        "paper_trade": {"ticker": "GDX"}, "red_team_challenges": [{"severity": "critical", "challenge": "c"}]}),
        encoding="utf-8")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / f"{TODAY}.json").write_text(json.dumps(
        {"divergences": 1, "items": [{"claim": "SOFR 上行", "verdict_cn": "支持"}]}), encoding="utf-8")
    store = LedgerStore(tmp_path / "ledger.db")
    for t, d in (("SPY", "long"), ("SPY", "long"), ("TLT", "short")):
        store.add(LedgerEntry("shadow", f"s:{t}{d}", t, d, 3, 0.6, 200, "x", meta={"run_date": TODAY}))
    daily.save_headlines([_News("Fed hikes", "Reuters", 0.9), _News("Oil jumps", "Bloomberg", 0.5)], TODAY)
    return store, briefs, tmp_path


def test_gather_facts_reads_the_day(env):
    store, briefs, _ = env
    f = daily.gather_facts(TODAY, store, briefs)
    assert [h["title"] for h in f["headlines"]] == ["Fed hikes", "Oil jumps"]
    assert f["main_pipeline"]["paper_trade"] == {"ticker": "GDX"}
    assert f["evidence"]["divergences"] == 1
    assert f["shadows"]["long"] == 2 and f["shadows"]["most_long"][0] == ("SPY", 2)


@pytest.mark.asyncio
async def test_build_report_uses_llm_and_saves(env):
    store, briefs, tmp = env
    seen = {}

    async def call(system, user):
        seen["user"] = user
        return "## 今日要闻\n- Fed hikes"
    r = await daily.build_report(TODAY, store=store, call=call, brief_dir=briefs)
    assert r["source"] == "llm" and "<facts>" in seen["user"] and "GDX" in seen["user"]
    assert json.loads((tmp / "reports" / f"{TODAY}.json").read_text("utf-8"))["markdown"].startswith("## 今日要闻")
    from marketmind.api import whitebox
    assert whitebox.get_daily_report()["date"] == TODAY


@pytest.mark.asyncio
async def test_llm_failure_still_reports_raw_facts(env):
    store, briefs, _ = env

    async def boom(system, user):
        raise RuntimeError("limit")
    r = await daily.build_report(TODAY, store=store, call=boom, brief_dir=briefs)
    assert r["source"] == "fallback" and "不交易" in r["markdown"] and "Fed hikes" in r["markdown"]


@pytest.mark.asyncio
async def test_push_truncates_long_reports(monkeypatch):
    sent = {}

    async def fake_send(title, body):
        sent.update(title=title, body=body)
        return [{"channel": "serverchan", "ok": True, "status": 200}]
    monkeypatch.setattr("marketmind.alerts.notify.send", fake_send)
    res = await daily.push({"date": TODAY, "markdown": "字" * 10000})
    assert res[0]["ok"] and TODAY in sent["title"]
    assert len(sent["body"]) < daily.PUSH_MAX_CHARS + 100 and "仪表盘" in sent["body"]


def test_gather_facts_includes_discovery_and_watchlist(env):
    store, briefs, tmp = env
    (tmp / "discovery").mkdir()
    (tmp / "discovery" / f"{TODAY}.json").write_text(json.dumps({
        "counts": {"anomalies": 1, "cold": 1},
        "anomalies": [{"series": "fred:WRESBAL", "title": "Reserves", "z": -2.4, "coverage": 0,
                       "cold": True, "proxies": [{"ticker": "SPY", "direction": "short",
                                                  "bucket": "not_priced", "move_atr": 0.1}]}],
        "unavailable": [{"series": "eia:WCESTUS1", "reason": "timeout"}]}), encoding="utf-8")
    from marketmind.watchlist.store import WatchlistStore
    WatchlistStore(tmp / "watchlist.db")
    f = daily.gather_facts(TODAY, store, briefs)
    a = f["discovery"]["anomalies"][0]
    assert a["series"] == "fred:WRESBAL" and a["news_coverage"] == 0 and a["proxies"][0]["bucket"] == "not_priced"
    assert f["discovery"]["unavailable"] == ["eia:WCESTUS1"]
    assert f["watchlist"]["watching"] == 0 and f["watchlist"]["new"] == []
    assert "冷门数据异常：1" in daily.fallback_text(f)
