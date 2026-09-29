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


@pytest.mark.asyncio
async def test_trend_section_in_prompt_and_facts(env):
    store, briefs, tmp = env
    assert "趋势状态" not in daily.gather_facts(TODAY, store, briefs)     # no trend file yet
    (tmp / "trend").mkdir()
    (tmp / "trend" / f"{TODAY}.json").write_text(json.dumps({
        "date": TODAY, "mode": "daily",
        "full": {"SPY": {"state": "TREND", "stop_level": 640.5, "close": 670.0,
                         "entry_signal_date": TODAY, "as_of": TODAY},
                 "TLT": {"state": "CASH"}},
        "lean": {"strongest_sector": "XLK", "states": {}},
        "changes": {"full": {"entries": ["SPY"], "exits": ["QQQ"]},
                    "lean": {"entries": [], "exits": []}}}), encoding="utf-8")
    seen = {}

    async def call(system, user):
        seen.update(system=system, user=user)
        return "## 今日要闻\n- x"
    await daily.build_report(TODAY, store=store, call=call, brief_dir=briefs)
    section = next(line for line in seen["system"].splitlines() if "## 趋势状态" in line)
    assert "TREND" in section and "止损" in section and "不是警报" in section
    assert seen["system"].index("## 观察名单") < seen["system"].index("## 趋势状态")
    f = daily.gather_facts(TODAY, store, briefs)["趋势状态"]
    assert f["entries_today"] == ["SPY"] and f["exits_today"] == ["QQQ"]
    assert f["trend"] == [{"ticker": "SPY", "stop_level": 640.5, "close": 670.0,
                           "entry_signal_date": TODAY, "as_of": TODAY}]
    assert "640.5" in seen["user"]


@pytest.mark.asyncio
async def test_pending_retirement_proposals_in_prompt_and_facts(env):
    store, briefs, tmp = env
    assert daily.gather_facts(TODAY, store, briefs)["retirement_proposals"] == []
    sid = "momentum:weekly:trend_rider"
    (tmp / "promotion").mkdir()
    (tmp / "promotion" / "retirements.json").write_text(json.dumps({"proposals": [
        {"shadow_id": sid, "status": "pending", "proposed_at": TODAY, "stage": "formal",
         "reason": {"challengers": ["t1", "t2"], "excess_domain_mean": -0.003, "excess_n": 9,
                    "window": ["2026-08-01", "2026-09-26"], "domain_benchmark": "SPY"},
         "successor": {"shadow_id": f"{sid}@2", "donor_id": "momentum:event:news_hound",
                       "method": "donor_rewrite"}},
        {"shadow_id": "x", "status": "rejected", "successor": {}}]}), encoding="utf-8")
    seen = {}

    async def call(system, user):
        seen.update(system=system, user=user)
        return "## 今日要闻\n- x"
    await daily.build_report(TODAY, store=store, call=call, brief_dir=briefs)
    assert "## 待批准：影子退役提案" in seen["system"]
    assert seen["system"].index("## 大行情警报") < seen["system"].index("## 待批准：影子退役提案") \
        < seen["system"].index("## 值得关注")
    (p,) = daily.gather_facts(TODAY, store, briefs)["retirement_proposals"]
    assert (p["shadow_id"], p["successor"], p["donor"]) == (
        sid, f"{sid}@2", "momentum:event:news_hound")
    assert p["failed_challengers"] == ["t1", "t2"] and p["excess_vs_domain_mean"] == -0.003
    assert p["approve"].endswith(f"retire approve {sid}") and f"{sid}@2" in seen["user"]
    assert sid in daily.fallback_text(daily.gather_facts(TODAY, store, briefs))


def _eco(tmp, day, **doc):
    (tmp / "ecosystem").mkdir(exist_ok=True)
    (tmp / "ecosystem" / f"{day}.json").write_text(json.dumps({"date": day, **doc}), encoding="utf-8")


def test_ecosystem_facts_one_liner_and_flags(env):
    store, briefs, tmp = env
    assert "ecosystem" not in daily.gather_facts(TODAY, store, briefs)       # no report yet
    _eco(tmp, "2026-09-28", summary="[ecosystem] herding: none, N_eff 4.0/6")
    f = daily.gather_facts(TODAY, store, briefs)["ecosystem"]              # latest, dated
    assert f == {"date": "2026-09-28", "summary": "[ecosystem] herding: none, N_eff 4.0/6",
                 "herding_flags": [], "duplicate_clusters": []}
    _eco(tmp, TODAY, summary="[ecosystem] herding: us_equity_index long 3d behavioural",
         herding={"flags": [{"group": "us_equity_index", "direction": "long", "days": 3,
                             "verdict": "behavioural", "escalate": False, "daily": [1, 2, 3]}]},
         diversity={"pnl": {"clusters": [{"members": ["a", "b"], "expected": False},
                                         {"members": ["c", "trial:c1"], "expected": True}]},
                    "direction": {"clusters": []}})
    f = daily.gather_facts(TODAY, store, briefs)["ecosystem"]
    assert f["date"] == TODAY and f["herding_flags"] == [{"group": "us_equity_index", "direction": "long",
                                                          "days": 3, "verdict": "behavioural",
                                                          "escalate": False}]
    assert f["duplicate_clusters"] == [{"measure": "pnl", "members": ["a", "b"]}]
    assert "behavioural" in daily.fallback_text(daily.gather_facts(TODAY, store, briefs))


def test_playground_facts_today_only(env):
    store, briefs, _ = env
    assert daily.gather_facts(TODAY, store, briefs)["playground"] == {"calls": 0, "by_agent": {}}
    ids = [store.add(LedgerEntry("playground", "playground:memory_desk", t, "long", 5, 0.6, 200, "x",
                                 meta={"run_date": TODAY})) for t in ("SPY", "GLD")]
    store.add(LedgerEntry("playground", "playground:tsmom", "TLT", "short", 5, 0.6, 200, "x",
                          meta={"run_date": "2026-09-28"}))                     # not today
    f = daily.gather_facts(TODAY, store, briefs)["playground"]
    assert f["calls"] == 2 and list(f["by_agent"]) == ["memory_desk"]
    assert sorted(c["entry_id"] for c in f["by_agent"]["memory_desk"]) == sorted(ids)
    assert "Playground 调用：2" in daily.fallback_text(daily.gather_facts(TODAY, store, briefs))
    assert "playground" not in daily.gather_facts(TODAY, None, briefs)


@pytest.mark.asyncio
async def test_prompt_has_short_ecosystem_and_playground_sections(env):
    store, briefs, tmp = env
    _eco(tmp, TODAY, summary="[ecosystem] herding: none")
    seen = {}

    async def call(system, user):
        seen.update(system=system, user=user)
        return "## 今日要闻\n- x"
    await daily.build_report(TODAY, store=store, call=call, brief_dir=briefs)
    sp = seen["system"]
    assert sp.index("## 影子动向") < sp.index("## 生态健康") < sp.index("## Playground 实验") \
        < sp.index("## 实盘持仓")
    assert "market_driven" in sp and "behavioural" in sp and "简短" in sp
    assert "[ecosystem] herding: none" in seen["user"] and '"playground"' in seen["user"]
