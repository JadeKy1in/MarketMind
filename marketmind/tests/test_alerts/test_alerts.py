"""Big-move alerts (docs/S8_DESIGN.md): conditions, observation mode, ledger, push."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from marketmind.alerts import conditions as cond
from marketmind.alerts import notify
from marketmind.alerts import runner
from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.pipeline.l3_indicators import TechnicalSnapshot

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
ADVISORS = {"a1": "fundamental", "a2": "fundamental", "a3": "momentum", "a4": "contrarian",
            "a5": "fundamental"}


def _add(store, source_type, source_id, ticker, direction="long", at="2026-09-27T10:00:00+00:00",
         **meta):
    return store.add(LedgerEntry(source_type, source_id, ticker, direction, 5, 0.6, 200, "x",
                                 meta=meta), created_at=at)


def _snap(light="green"):
    return TechnicalSnapshot(
        ticker="X", close=100.0, daily_return_pct=0.0, wma200=80.0, weekly_bars=260,
        above_200wma=True, structure_intact=True, key_resistance=None,
        resistance_distance_pct=None, near_key_resistance=False, atr14=2.0, support_low=95.0,
        support_high=96.0, entry_low=98.0, entry_high=100.5, stop_loss=96.0, target_price=110.0,
        reward_risk_ratio=2.5, light=light, recommendation="enter", as_of="2026-09-25", notes=[])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "load_advisors", lambda: (runner.OBSERVE, dict(ADVISORS)))
    return LedgerStore(tmp_path / "ledger.db"), tmp_path


# ── condition A ─────────────────────────────────────────────────────────────

def test_condition_a_needs_three_advisors_two_groups_few_shorts(env):
    store, _ = env
    for sid in ("a1", "a2", "a3"):
        _add(store, "shadow", sid, "NVDA")
    for sid in ("a1", "a2", "a5"):                  # one group only
        _add(store, "shadow", sid, "XLE")
    for sid in ("a1", "a3", "a4"):
        _add(store, "shadow", sid, "GLD")
    _add(store, "shadow", "a2", "GLD", "short")
    _add(store, "shadow", "a5", "GLD", "short")      # 2 shorts > half of 3 longs
    _add(store, "shadow", "outsider", "NVDA")        # not an advisor
    _add(store, "shadow", "a4", "NVDA", at="2026-09-10T10:00:00+00:00")   # outside window
    votes = cond.advisor_votes(store.list(), NOW, ADVISORS, lambda t: True)
    assert cond.check_a(votes["NVDA"]) == (True, ["fundamental", "momentum"])
    assert cond.check_a(votes["XLE"])[0] is False
    assert cond.check_a(votes["GLD"])[0] is False


def test_latest_vote_per_advisor_counts_once(env):
    store, _ = env
    _add(store, "shadow", "a1", "NVDA", "short", at="2026-09-25T10:00:00+00:00")
    _add(store, "shadow", "a1", "NVDA", "long", at="2026-09-27T10:00:00+00:00")
    votes = cond.advisor_votes(store.list(), NOW, ADVISORS, lambda t: True)
    assert len(votes["NVDA"]["long"]) == 1 and votes["NVDA"]["short"] == []


# ── full evaluation ─────────────────────────────────────────────────────────

def _bars():
    return [Bar(f"2026-08-{d:02d}", 100, 101, 99, 100, 1000) for d in range(1, 29)]


async def _run(store, tmp, snap_light="green", tradable=lambda t: t != "600519.SS", **kw):
    async def snap(t):
        return _snap(snap_light)
    sent = []

    async def notifier(title, body):
        sent.append((title, body))
        return [{"channel": "fake", "ok": True, "status": 200}]
    report = await runner.run_alerts(store, now=NOW, snapshot_fn=snap, tradable=tradable,
                                     notifier=notifier,
                                     price_source=StaticPriceSource({"NVDA": _bars()}),
                                     report_dir=tmp / "alerts", **kw)
    return report, sent


@pytest.mark.asyncio
async def test_fires_only_when_all_three_hold_and_observe_does_not_push(env):
    store, tmp = env
    for sid in ("a1", "a2", "a3"):
        _add(store, "shadow", sid, "NVDA")
    _add(store, "evidence", "evidence:v1:revenue_growth", "NVDA", claim="营收下滑？数据说增长")
    for sid in ("a1", "a3", "a4"):
        _add(store, "shadow", sid, "600519.SS")      # not owner-executable
    report, sent = await _run(store, tmp)
    assert [f["ticker"] for f in report["fired"]] == ["NVDA"] and sent == []
    e = store.get(report["fired"][0]["entry_id"])
    assert (e.source_type, e.source_id, e.direction, e.hold_bars) == ("alert", "alert:observe", "long", 20)
    assert e.falsifier_rule == {"type": "close_below", "price": 96.0} and e.snapshot_id
    assert len(e.meta["advisors_long"]) == 3 and e.meta["evidence"][0]["claim"]
    saved = json.loads((tmp / "alerts" / "2026-09-28.json").read_text("utf-8"))
    assert saved["mode"] == "observe" and len(saved["fired"]) == 1


@pytest.mark.asyncio
async def test_near_miss_and_dedupe(env):
    store, tmp = env
    for sid in ("a1", "a2", "a3"):
        _add(store, "shadow", sid, "NVDA")
    report, _ = await _run(store, tmp)                 # A + C, no evidence
    assert report["fired"] == [] and report["near_misses"][0]["met"] == 2
    _add(store, "evidence", "evidence:v1:x", "NVDA", claim="c")
    first, _ = await _run(store, tmp)
    assert len(first["fired"]) == 1
    second, _ = await _run(store, tmp)                 # same day again -> deduped
    assert second["fired"] == [] and "已警报过" in second["near_misses"][0]["note"]
    assert len(store.list(source_type="alert")) == 1


@pytest.mark.asyncio
async def test_yellow_light_blocks(env):
    store, tmp = env
    for sid in ("a1", "a2", "a3"):
        _add(store, "shadow", sid, "NVDA")
    _add(store, "evidence", "evidence:v1:x", "NVDA", claim="c")
    report, _ = await _run(store, tmp, snap_light="yellow")
    assert report["fired"] == [] and report["near_misses"][0]["c_ok"] is False


@pytest.mark.asyncio
async def test_live_mode_pushes(env, monkeypatch):
    store, tmp = env
    monkeypatch.setattr(runner, "load_advisors", lambda: (runner.LIVE, dict(ADVISORS)))
    for sid in ("a1", "a2", "a3"):
        _add(store, "shadow", sid, "NVDA")
    _add(store, "evidence", "evidence:v1:x", "NVDA", claim="c")
    report, sent = await _run(store, tmp)
    assert len(sent) == 1 and "NVDA" in sent[0][0] and report["fired"][0]["entry_id"] in sent[0][1]
    assert report["fired"][0]["notified"][0]["ok"]


def test_load_advisors_observe_until_s7_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    mode, adv = runner.load_advisors()
    assert mode == runner.OBSERVE and len(adv) >= 20
    (tmp_path / "advisors.json").write_text(json.dumps(
        {"advisors": ["expert:gold:bullion_broker", "nope"]}), encoding="utf-8")
    mode, adv = runner.load_advisors()
    assert mode == runner.OBSERVE and len(adv) >= 20


def _write_advisors(tmp_path, ids):
    (tmp_path / "advisors.json").write_text(json.dumps({"advisors": ids}), encoding="utf-8")


def test_live_mode_only_once_advisors_can_meet_condition_a(tmp_path, monkeypatch):
    """1-2 advisors, or 3 from one group, can never satisfy A: stay in observation."""
    from marketmind.shadows.v3 import roster
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    by_group: dict[str, list[str]] = {}
    for r in roster.active():
        by_group.setdefault(r.group, []).append(r.shadow_id)
    fund, other = by_group["fundamental"], by_group["momentum"]
    for ids in ([fund[0]], [fund[0], other[0]], fund[:3], fund[:5]):
        _write_advisors(tmp_path, ids)
        mode, adv = runner.load_advisors()
        assert mode == runner.OBSERVE and len(adv) == len(roster.active()), ids
    _write_advisors(tmp_path, fund[:2] + other[:1])
    mode, adv = runner.load_advisors()
    assert mode == runner.LIVE and sorted(adv) == sorted(fund[:2] + other[:1])
    assert runner.can_satisfy_a(adv) and not runner.can_satisfy_a({"a": "g", "b": "h"})


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
    f = reqs["feishu"].json
    assert f["msg_type"] == "text" and f["timestamp"] and f["sign"]
    assert notify.build_requests("t", "b", {}) == {}
    long = notify.build_requests("t", "字" * 2000, {"WECOM_WEBHOOK_KEY": "k"})["wecom"]
    assert len(long.json["text"]["content"].encode()) <= notify.WECOM_MAX_BYTES


@pytest.mark.asyncio
async def test_send_success_and_failure_without_leaking_keys(caplog):
    replies = {"sctapi.ftqq.com": (200, {"code": 0}), "www.pushplus.plus": (200, {"code": 905}),
               "qyapi.weixin.qq.com": (200, {"errcode": 0}), "open.feishu.cn": (500, {})}

    def handler(request):
        status, body = replies[request.url.host]
        return httpx.Response(status, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await notify.send("t", "b", env=ENV, client=client)
    assert {r["channel"]: r["ok"] for r in results} == {
        "serverchan": True, "pushplus": False, "wecom": True, "feishu": False}
    assert "SCTkey" not in caplog.text and "wk" not in caplog.text.replace("wecom", "")


def test_redaction_covers_path_keys():
    from marketmind.notification.log_redaction import redact
    assert "SCTkey" not in redact("POST https://sctapi.ftqq.com/SCTkey.send")
    assert "abc" not in redact("https://open.feishu.cn/open-apis/bot/v2/hook/abc")
