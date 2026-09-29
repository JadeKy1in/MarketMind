"""Big-move alerts (docs/S8_DESIGN.md, owner decisions 2026-09-29): trend trunk, grouped
advisor votes and evidence as annotations, observe mode, owner live switch, one batched
priority push, weekend crypto run."""
import inspect
import json
from datetime import datetime, timezone

import httpx
import pytest

from marketmind.alerts import conditions as cond
from marketmind.alerts import config as C
from marketmind.alerts import notify, runner
from marketmind.alerts import trend_source as ts
from marketmind.alerts.asset_groups import ASSET_GROUPS, asset_group
from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.store import LedgerEntry, LedgerStore

NOW = datetime(2026, 9, 28, 16, tzinfo=timezone.utc)          # New York date 2026-09-28
DAY = "2026-09-28"
VOTERS = {"f1": "fundamental", "f2": "fundamental", "m1": "momentum", "c1": "contrarian",
          "playground:pg1": "playground"}


def _add(store, source_type, source_id, ticker, direction="long", hold=20,
         at="2026-09-27T10:00:00+00:00", **meta):
    return store.add(LedgerEntry(source_type, source_id, ticker, direction, hold, 0.6, 200, "x",
                                 meta=meta), created_at=at)


def _state(t, state, **kw):
    return {"ticker": t, "state": state, "as_of": "2026-09-25", "close": 100.0,
            "stop_level": 90.0, "entry_signal_date": "2026-09-25" if state == "TREND" else None,
            **kw}


def _trend_file(data_dir, day=DAY, lean=True, full_only=None):
    """lean: QQQ entry, GLD exit, IWM entry (made non-executable in tests), BTC-USD entry,
    SPY WATCH. full: adds NVDA entry (only visible with the full universe)."""
    lean_states = {"QQQ": _state("QQQ", "TREND"), "GLD": _state("GLD", "EXIT"),
                   "IWM": _state("IWM", "TREND"), "BTC-USD": _state("BTC-USD", "TREND"),
                   "SPY": _state("SPY", "WATCH"), "TLT": _state("TLT", "CASH")}
    full = dict(lean_states) | {"NVDA": _state("NVDA", "TREND")}
    doc = {"date": day, "mode": "daily", "full": full,
           "lean": {"states": lean_states} if lean else None,
           "changes": {"full": {"entries": ["BTC-USD", "IWM", "NVDA", "QQQ"], "exits": ["GLD"]},
                       "lean": {"entries": ["BTC-USD", "IWM", "QQQ"], "exits": ["GLD"]}}}
    folder = data_dir / "trend"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{day}.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(C.LIVE_ENV, raising=False)
    monkeypatch.delenv(C.TREND_SOURCE_ENV, raising=False)
    # these tests exercise the lean/auto file layout; the production default ("six")
    # is covered by test_six_source_and_default below
    monkeypatch.setattr(C, "TREND_SOURCE", "daily_state_machine")
    monkeypatch.setattr(runner, "load_voters", lambda entries=(): (runner.ADVISORS, dict(VOTERS)))
    _trend_file(tmp_path)
    return LedgerStore(tmp_path / "ledger.db"), tmp_path


def _bars():
    return [Bar(f"2026-08-{d:02d}", 100, 101, 99, 100, 1000) for d in range(1, 29)]


async def _run(store, tmp, env_vars=None, **kw):
    sent = []

    async def notifier(title, body, priority=False):
        sent.append((title, body, priority))
        return [{"channel": "fake", "ok": True, "status": 200}]
    report = await runner.run_alerts(
        store, now=NOW, tradable=lambda t: t != "IWM", notifier=notifier,
        price_source=StaticPriceSource({t: _bars() for t in ("QQQ", "BTC-USD", "NVDA")}),
        report_dir=tmp / "alerts", env=env_vars or {}, **kw)
    return report, sent


# ── asset groups (decision 3) ───────────────────────────────────────────────

def test_asset_groups_one_table_with_exact_ticker_fallback():
    assert asset_group("GC=F") == asset_group("GLD") == asset_group("slv") == "precious_metals"
    assert asset_group("ES=F") == asset_group("QQQ") == "us_equity_index"
    assert asset_group("ZN=F") == asset_group("TLT") == "long_rates"
    assert asset_group("CL=F") == asset_group("XLE") == "energy"
    assert asset_group("SOL-USD") == asset_group("BTC-USD") == "crypto"
    assert asset_group("SMH") == asset_group("XLK") == "sector_tech"
    assert asset_group("NVDA") == "NVDA" and asset_group(" aapl ") == "AAPL"
    members = [t for g in ASSET_GROUPS.values() for t in g]
    assert len(members) == len(set(members))


# ── votes: grouped, hold >= 10, playground counts (decisions 3, 4) ──────────

def test_group_votes_aggregate_by_group_and_skip_short_holds(env):
    store, _ = env
    _add(store, "shadow", "f1", "GC=F")                     # counts for GLD
    _add(store, "shadow", "m1", "SLV")
    _add(store, "playground", "playground:pg1", "GLD", "short")
    _add(store, "shadow", "c1", "GLD", hold=5)              # holding < 10 days: no vote
    _add(store, "shadow", "outsider", "GLD")                # not a voter
    _add(store, "shadow", "f2", "GLD", at="2026-09-10T10:00:00+00:00")   # outside window
    _add(store, "shadow", "f1", "IAU", "short", at="2026-09-26T10:00:00+00:00")  # older than GC=F
    v = cond.group_votes(store.list(), NOW, VOTERS)["precious_metals"]
    assert sorted(x["voter"] for x in v["long"]) == ["f1", "m1"]
    assert [x["voter"] for x in v["short"]] == ["playground:pg1"]
    assert {x["ticker"] for x in v["long"]} == {"GC=F", "SLV"}


def test_vote_status_rules():
    f = lambda sid, g: {"voter": sid, "group": g}       # noqa: E731
    assert cond.vote_status([], []) == cond.NO_VOTES
    assert cond.vote_status([f("a", "x")], [f("b", "y"), f("c", "z")]) == cond.VETOED
    assert cond.vote_status([f("a", "x")], [f("b", "y")]) == cond.WEAK     # tie: no veto
    assert cond.vote_status([f("a", "x"), f("b", "y")], [f("c", "z")]) == cond.SUPPORTED
    assert cond.vote_status([f("a", "x"), f("b", "x")], []) == cond.WEAK   # one group only
    assert cond.vote_status([f("a", "x")], []) == cond.WEAK                # one voter
    assert cond.vote_status([f("a", "x"), f("b", "y"), f("c", "z")],
                            [f("d", "x"), f("e", "y")]) == cond.WEAK       # 2 > half of 3


def test_load_voters_counts_playground_advisors(tmp_path, monkeypatch):
    from marketmind.shadows.v3 import roster
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    store = LedgerStore(tmp_path / "ledger.db")
    _add(store, "playground", "playground:alpha", "SPY")
    basis, v = runner.load_voters(store.list())             # no advisors.json: stand-ins
    assert basis == runner.STAND_IN and v["playground:alpha"] == "playground"
    assert len(v) == len(roster.active()) + 1
    shadow = roster.active()[0].shadow_id
    (tmp_path / "advisors.json").write_text(json.dumps(
        {"advisors": ["playground:beta", shadow, "nope"]}), encoding="utf-8")
    basis, v = runner.load_voters(store.list())
    assert basis == runner.ADVISORS
    assert v == {"playground:beta": "playground", shadow: roster.active()[0].group}
    (tmp_path / "advisors.json").write_text(json.dumps({"advisors": ["nope"]}), encoding="utf-8")
    assert runner.load_voters(store.list())[0] == runner.STAND_IN


# ── trend source (decision 2) ───────────────────────────────────────────────

def test_daily_source_prefers_lean_then_full(tmp_path):
    _trend_file(tmp_path)
    r = ts.DailyStateMachineSource(data_dir=tmp_path).read(DAY)
    assert r.available and r.universe == "lean" and "NVDA" not in r.entries
    assert r.entries == ["BTC-USD", "IWM", "QQQ"] and r.exits == ["GLD"]
    r = ts.DailyStateMachineSource("full", data_dir=tmp_path).read(DAY)
    assert r.universe == "full" and "NVDA" in r.entries
    _trend_file(tmp_path, day="2026-09-29", lean=False)
    r = ts.DailyStateMachineSource(data_dir=tmp_path).read("2026-09-29")
    assert r.universe == "full" and "NVDA" in r.entries
    r = ts.DailyStateMachineSource(data_dir=tmp_path).read("2026-09-30")   # no stale fallback
    assert not r.available and "missing" in r.reason


class _Monthly:
    name = "monthly_test"

    def read(self, day):
        return ts.TrendReading(self.name, day, True, universe="monthly",
                               states={"SPY": {"state": "TREND", "as_of": day}}, entries=["SPY"])


def make_monthly():
    return _Monthly()


def test_source_is_a_config_switch(monkeypatch):
    monkeypatch.delenv(C.TREND_SOURCE_ENV, raising=False)
    assert C.trend_source_name({}) == "daily_state_machine:six"      # owner decision 2026-09-29
    assert ts.get_source().name == "daily_state_machine:six"
    assert ts.get_source("daily_state_machine:full").universe == "full"
    monkeypatch.setenv(C.TREND_SOURCE_ENV, f"{__name__}:make_monthly")
    assert ts.get_source().name == "monthly_test"
    with pytest.raises(ValueError):
        ts.get_source("nonsense")


@pytest.mark.asyncio
async def test_plugged_source_feeds_the_trunk(env):
    store, tmp = env
    report, _ = await _run(store, tmp, source=_Monthly())
    assert [f["ticker"] for f in report["fired"]] == ["SPY"]
    assert report["trend_source"]["source"] == "monthly_test"


# ── the run (decisions 1, 2, 7) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trunk_alerts_with_annotations_in_observe_mode(env):
    store, tmp = env
    for sid in ("f1", "m1"):
        _add(store, "shadow", sid, "ES=F")                  # support QQQ entry via the group
    _add(store, "evidence", "evidence:v1:x", "SPY", claim="资金流背离")
    for sid in ("f1", "m1"):
        _add(store, "shadow", sid, "GC=F")                  # longs oppose the GLD exit
    report, sent = await _run(store, tmp)
    assert sent == [] and report["mode"] == runner.OBSERVE and not report["live_switch"]
    fired = {f["ticker"]: f for f in report["fired"]}
    assert set(fired) == {"QQQ", "GLD", "BTC-USD"}           # IWM not executable
    assert report["skipped"] == [{"ticker": "IWM", "kind": "entry", "reason": "所有人无法执行"}]
    q, g, b = fired["QQQ"], fired["GLD"], fired["BTC-USD"]
    assert (q["kind"], q["status"], q["a_ok"], q["b_ok"]) == ("entry", "supported", True, True)
    assert q["evidence"][0]["claim"] == "资金流背离" and q["asset_group"] == "us_equity_index"
    assert (g["kind"], g["direction"], g["status"], g["veto"]) == ("exit", "short", "vetoed", True)
    assert g["entry_id"] is None and len(g["advisors_long"]) == 2
    assert b["status"] == "no_votes"
    assert [n["ticker"] for n in report["near_misses"]] == ["SPY"]   # WATCH
    e = store.get(q["entry_id"])
    assert (e.source_type, e.source_id, e.direction, e.hold_bars) == ("alert", "alert:observe", "long", 20)
    assert e.falsifier_rule == {"type": "close_below", "price": 90.0} and e.snapshot_id
    assert e.meta["status"] == "supported" and e.meta["trend_source"] == "daily_state_machine"
    assert len(store.list(source_type="alert")) == 2           # entries only
    saved = json.loads((tmp / "alerts" / "2026-09-28.json").read_text("utf-8"))
    assert saved["trend_source"]["universe"] == "lean" and len(saved["fired"]) == 3


@pytest.mark.asyncio
async def test_veto_is_a_flag_not_a_block(env):
    store, tmp = env
    for sid in ("f1", "m1", "c1"):
        _add(store, "shadow", sid, "NQ=F", "short")
    report, _ = await _run(store, tmp)
    q = next(f for f in report["fired"] if f["ticker"] == "QQQ")
    assert q["status"] == "vetoed" and q["entry_id"]


@pytest.mark.asyncio
async def test_same_trend_event_is_not_alerted_twice(env):
    store, tmp = env
    first, _ = await _run(store, tmp)
    second, _ = await _run(store, tmp)
    assert len(first["fired"]) == 3 and second["fired"] == []
    assert {d["ticker"] for d in second["duplicates"]} == {"QQQ", "GLD", "BTC-USD"}
    assert len(store.list(source_type="alert")) == 2


@pytest.mark.asyncio
async def test_missing_trend_file_gives_no_alerts(env):
    store, tmp = env
    (tmp / "trend" / f"{DAY}.json").unlink()
    report, _ = await _run(store, tmp)
    assert report["fired"] == [] and not report["trend_source"]["available"]


@pytest.mark.asyncio
async def test_live_only_by_owner_switch_one_batched_priority_message(env, tmp_path):
    store, tmp = env
    # full advisor roster does not switch to live on its own
    report, sent = await _run(store, tmp)
    assert report["mode"] == runner.OBSERVE and sent == []
    (tmp / "alerts" / "2026-09-28.json").unlink()            # fresh day: no earlier alerts
    store2 = LedgerStore(tmp_path / "ledger2.db")
    report, sent = await _run(store2, tmp, env_vars={C.LIVE_ENV: "1"})
    assert report["mode"] == runner.LIVE and report["live_switch"]
    assert len(sent) == 1 and sent[0][2] is True                 # ONE message, priority
    title, body, _ = sent[0]
    for t in ("QQQ", "GLD", "BTC-USD"):
        assert t in title
    assert "【离场】GLD" in body and "【入场】QQQ" in body and "系统不下单" in body
    assert body.index("【离场】") < body.index("【入场】")     # exits first
    q = next(f for f in report["fired"] if f["ticker"] == "QQQ")
    assert q["entry_id"] in body and q["notified"][0]["ok"]
    assert store2.get(q["entry_id"]).source_id == "alert:live"


def test_live_switch_default_off():
    assert C.LIVE is False and runner.current_mode({}) == runner.OBSERVE
    assert runner.current_mode({C.LIVE_ENV: "true"}) == runner.LIVE
    assert runner.current_mode({C.LIVE_ENV: "0"}) == runner.OBSERVE


@pytest.mark.asyncio
async def test_weekend_crypto_only(env):
    store, tmp = env
    report, _ = await _run(store, tmp, crypto_only=True)
    assert [f["ticker"] for f in report["fired"]] == ["BTC-USD"] and report["crypto_only"]
    assert report["near_misses"] == [] and report["skipped"] == []


def test_orchestration_runs_alerts_after_trend_daily_and_weekend():
    from marketmind.pipeline import orchestration as orch
    daily = inspect.getsource(orch._run_daily_with_shadows)
    assert daily.index("await trend_step(config)") < daily.index("await alerts_step(config)") \
        < daily.index("await daily_report_step(config)")
    weekend = inspect.getsource(orch.run_weekend)
    assert weekend.index("await trend_step(config, crypto_only=True)") \
        < weekend.index("await alerts_step(config, crypto_only=True)")


@pytest.mark.asyncio
async def test_alerts_step_passes_crypto_flag(monkeypatch, capsys):
    from marketmind.pipeline import orchestration as orch
    seen = {}

    async def fake(store, **kw):
        seen.update(kw)
        return {"mode": runner.OBSERVE, "fired": [], "near_misses": [],
                "trend_source": {"available": True}}
    monkeypatch.setattr(runner, "run_alerts", fake)
    monkeypatch.setattr(orch, "_ledger_store", lambda config: None)
    await orch.alerts_step(object(), crypto_only=True)
    assert seen["crypto_only"] is True and seen["notifier"] is notify.send
    assert "[alerts] observe: fired none" in capsys.readouterr().out


# ── owner responses ─────────────────────────────────────────────────────────

def test_responses(env):
    store, _ = env
    aid = _add(store, "alert", "alert:observe", "NVDA")
    sid = _add(store, "shadow", "a1", "NVDA")
    runner.record_response(aid, "reject", "太贵")
    runner.record_response(aid, "accept")
    assert runner.load_responses()[aid]["decision"] == "accept"
    with pytest.raises(ValueError):
        runner.record_response(sid, "accept", store=store)
    with pytest.raises(ValueError):
        runner.record_response(aid, "maybe")
    from marketmind.api import whitebox
    d = whitebox.get_big_alerts()
    assert d["available"] and d["history"][0]["response"] == "accept"


# ── push ────────────────────────────────────────────────────────────────────

ENV = {"SERVERCHAN_SENDKEY": "SCTkey", "PUSHPLUS_TOKEN": "pp", "WECOM_WEBHOOK_KEY": "wk",
       "FEISHU_WEBHOOK_TOKEN": "ft", "FEISHU_WEBHOOK_SECRET": "sec"}


def test_build_requests_formats():
    reqs = notify.build_requests("标题\n换行", "正文\n第二行", ENV)
    assert set(reqs) == {"serverchan", "pushplus", "wecom", "feishu"}
    assert reqs["serverchan"].url == "https://sctapi.ftqq.com/SCTkey.send"
    assert reqs["serverchan"].data == {"title": "标题 换行", "desp": "正文\n\n第二行"}
    assert reqs["pushplus"].json["token"] == "pp" and reqs["pushplus"].json["template"] == "txt"
    assert reqs["wecom"].url.endswith("?key=wk") and reqs["wecom"].json["msgtype"] == "text"
    assert "mentioned_list" not in reqs["wecom"].json["text"]
    f = reqs["feishu"].json
    assert f["msg_type"] == "text" and f["timestamp"] and f["sign"]
    assert notify.build_requests("t", "b", {}) == {}
    long = notify.build_requests("t", "字" * 2000, {"WECOM_WEBHOOK_KEY": "k"})["wecom"]
    assert len(long.json["text"]["content"].encode()) <= notify.WECOM_MAX_BYTES


def test_priority_mentions_all_on_wecom_only():
    plain = notify.build_requests("t", "b", ENV)
    prio = notify.build_requests("t", "b", ENV, priority=True)
    assert prio["wecom"].json["text"]["mentioned_list"] == ["@all"]
    assert prio["serverchan"].data == plain["serverchan"].data
    assert prio["pushplus"].json == plain["pushplus"].json
    assert prio["feishu"].json["content"] == plain["feishu"].json["content"]


@pytest.mark.asyncio
async def test_send_success_and_failure_without_leaking_keys(caplog):
    replies = {"sctapi.ftqq.com": (200, {"code": 0}), "www.pushplus.plus": (200, {"code": 905}),
               "qyapi.weixin.qq.com": (200, {"errcode": 0}), "open.feishu.cn": (500, {})}
    bodies = {}

    def handler(request):
        bodies[request.url.host] = request.content
        status, body = replies[request.url.host]
        return httpx.Response(status, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await notify.send("t", "b", env=ENV, client=client, priority=True)
    assert {r["channel"]: r["ok"] for r in results} == {
        "serverchan": True, "pushplus": False, "wecom": True, "feishu": False}
    assert b"@all" in bodies["qyapi.weixin.qq.com"]
    assert "SCTkey" not in caplog.text and "wk" not in caplog.text.replace("wecom", "")


def test_redaction_covers_path_keys():
    from marketmind.notification.log_redaction import redact
    assert "SCTkey" not in redact("POST https://sctapi.ftqq.com/SCTkey.send")
    assert "abc" not in redact("https://open.feishu.cn/open-apis/bot/v2/hook/abc")


# ── dashboard view of the alert report ──────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_view_reads_trunk_annotation_evidence(env):
    from marketmind.api import whitebox
    store, tmp = env
    _add(store, "shadow", "f1", "SPY")                      # us_equity_index, long
    _add(store, "shadow", "m1", "ES=F")
    _add(store, "playground", "playground:pg1", "GC=F")     # long gold: against the GLD exit
    _add(store, "evidence", "div", "QQQ", claim="breadth diverges up", claim_type="breadth")
    _add(store, "evidence", "div", "NQ=F", "short", claim="rates headwind")
    await _run(store, tmp)
    d = whitebox.get_big_alerts()
    v = d["view"]
    assert d["available"] and d["report"]["fired"]               # raw report still served
    assert v["mode"] == "observe" and v["live_switch"] is False and v["pushed"] == 0
    assert v["trend_source"]["name"] == "daily_state_machine"
    assert v["trend_source"]["universe"] == "lean"
    rows = {r["ticker"]: r for r in v["alerts"]}
    assert set(rows) == {"QQQ", "GLD", "BTC-USD"}
    q = rows["QQQ"]
    assert q["kind"] == "entry" and q["trunk"]["move"] == "→TREND"
    assert q["trunk"]["stop_level"] == 90.0 and q["trunk"]["close"] == 100.0
    assert q["annotation"] == {"status": "supported", "status_cn": "顾问支持", "veto": False,
                               "votes_for": 2, "votes_against": 0,
                               "groups_for": ["fundamental", "momentum"], "groups_against": []}
    assert [e["claim"] for e in q["evidence"]["for"]] == ["breadth diverges up"]
    assert [e["claim"] for e in q["evidence"]["against"]] == ["rates headwind"]
    assert q["entry_id"]
    g = rows["GLD"]
    assert g["kind"] == "exit" and g["trunk"]["move"] == "TREND→EXIT" and g["entry_id"] is None
    assert g["annotation"]["status"] == "vetoed" and g["annotation"]["veto"] is True
    assert g["annotation"]["votes_against"] == 1 and g["annotation"]["groups_against"] == ["playground"]
    assert rows["BTC-USD"]["annotation"]["status"] == "no_votes"
    assert [(r["ticker"], r["kind"]) for r in v["near_misses"]] == [("SPY", "watch")]
    assert v["near_misses"][0]["note"].startswith("WATCH")
    assert v["near_misses"][0]["annotation"]["status"] == "supported"
    assert [s["ticker"] for s in v["skipped"]] == ["IWM"]


def test_dashboard_view_tolerates_missing_fields():
    from marketmind.api import whitebox
    assert whitebox.alert_report_view(None) is None
    v = whitebox.alert_report_view({"mode": "live", "fired": [{"ticker": "X", "kind": "entry"}]})
    assert v["mode"] == "live" and v["near_misses"] == [] and v["trend_source"]["name"] is None
    r = v["alerts"][0]
    assert r["trunk"]["move"] == "→TREND" and r["trunk"]["stop_level"] is None
    assert r["annotation"]["status"] == "no_votes" and r["annotation"]["votes_for"] == 0
    assert r["evidence"] == {"for": [], "against": []}


def test_six_source_and_default(tmp_path):
    _trend_file(tmp_path)
    r = ts.DailyStateMachineSource("six", data_dir=tmp_path).read(DAY)
    assert r.available and r.universe == "six"
    assert set(r.states) == {"QQQ", "GLD", "BTC-USD", "SPY", "TLT"}      # IWM, NVDA not in SIX
    assert r.entries == ["BTC-USD", "QQQ"] and r.exits == ["GLD"]
    assert set(C.SIX) == {"SPY", "QQQ", "GLD", "TLT", "BTC-USD", "ETH-USD"}
