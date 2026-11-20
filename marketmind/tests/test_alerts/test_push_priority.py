"""Push priority and daily budget (docs/S8_DESIGN.md 推送优先级, 2026-11-20): Server酱 sends
5 messages a day; with alerts live, watchlist triggers go out after the alerts and are
held when only the daily report's reserve is left. Dashboard alert page API."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from marketmind.alerts import config as C
from marketmind.alerts import notify, quota, runner
from marketmind.ledger.store import LedgerStore
from marketmind.tests.test_alerts.test_alerts import _add, _run, env  # noqa: F401  (fixture)
from marketmind.watchlist import runner as wl

NOW = datetime(2026, 11, 20, 14, tzinfo=timezone.utc)           # 22:00 in China


def _trigger_report():
    row = {"watch_id": "w1", "ticker": "NVDA", "direction": "long", "source": "main_pipeline",
           "fired": [{"label": "收盘价上破 105", "detail": "106"}], "thesis": "AI capex",
           "stop": 100, "target": 120, "levels_basis": "l3", "entry_id": "e1"}
    other = dict(row, watch_id="w2", ticker="TLT", source="anomaly")
    return {"triggered": [row, other]}


def _fill_quota(n, now=NOW):
    for _ in range(n):
        quota.record(now)


# ── budget counter ──────────────────────────────────────────────────────────

def test_quota_counts_per_china_day():
    assert quota.remaining(NOW) == quota.DAILY_LIMIT == 5
    _fill_quota(2)
    assert quota.sent_today(NOW) == 2 and quota.remaining(NOW) == 3
    assert quota.day_key(NOW) == "2026-11-20"
    late = datetime(2026, 11, 20, 16, 30, tzinfo=timezone.utc)   # 00:30 next day in China
    assert quota.day_key(late) == "2026-11-21" and quota.sent_today(late) == 0
    _fill_quota(7)
    assert quota.remaining(NOW) == 0


@pytest.mark.asyncio
async def test_send_counts_only_delivered_serverchan(monkeypatch):
    monkeypatch.setattr(notify, "RETRY_DELAYS_S", (0, 0))
    replies = {"sctapi.ftqq.com": (200, {"code": 0})}

    def handler(request):
        status, body = replies.get(request.url.host, (200, {"errcode": 0}))
        return httpx.Response(status, json=body)
    env_vars = {"SERVERCHAN_SENDKEY": "k", "WECOM_WEBHOOK_KEY": "w"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await notify.send("t", "b", env=env_vars, client=client)
        assert quota.sent_today() == 1
        replies["sctapi.ftqq.com"] = (400, {"code": 40001})       # Server酱 refused
        await notify.send("t", "b", env=env_vars, client=client)
        await notify.send("t", "b", env={"WECOM_WEBHOOK_KEY": "w"}, client=client)
    assert quota.sent_today() == 1


# ── watchlist push deferred behind live alerts ──────────────────────────────

@pytest.mark.asyncio
async def test_defer_keeps_message_until_after_alerts():
    async def must_not_send(title, body):
        raise AssertionError("deferred push must not send")
    out = await wl.notify_triggers(_trigger_report(), send=must_not_send, defer=True)
    assert out["deferred"] == ["w1"] and out["pushed"] == [] and out["skipped"] == ["w2"]
    sent = []

    async def fake_send(title, body):
        sent.append((title, body))
        return [{"channel": "serverchan", "ok": True, "status": 200}]
    out = await wl.push_deferred(send=fake_send, now=datetime.now(timezone.utc))
    assert out["pushed"] == ["w1"] and len(sent) == 1
    assert "NVDA 做多" in sent[0][0] and "TLT" not in sent[0][1]
    assert (await wl.push_deferred(send=fake_send))["pushed"] == []        # sent once only


@pytest.mark.asyncio
async def test_deferred_push_held_when_only_the_report_reserve_is_left():
    now = datetime.now(timezone.utc)
    await wl.notify_triggers(_trigger_report(), defer=True)
    _fill_quota(quota.DAILY_LIMIT - quota.REPORT_RESERVE, now)          # 4 sent: 1 left

    async def must_not_send(title, body):
        raise AssertionError("held push must not send")
    out = await wl.push_deferred(send=must_not_send, now=now)
    assert out == {"pushed": [], "held": ["w1"], "reason": "quota", "results": []}
    assert not wl._pending_path().exists()                     # dropped: the report has it


@pytest.mark.asyncio
async def test_stale_deferred_push_is_dropped():
    await wl.notify_triggers(_trigger_report(), defer=True)
    doc = json.loads(wl._pending_path().read_text(encoding="utf-8"))
    wl._pending_path().write_text(json.dumps(doc | {"day": "2026-01-01"}), encoding="utf-8")
    out = await wl.push_deferred(send=None)
    assert out["reason"] == "stale" and out["held"] == ["w1"]


@pytest.mark.asyncio
async def test_not_live_pushes_watchlist_immediately_as_before(monkeypatch):
    from marketmind import watchlist
    from marketmind.pipeline import orchestration as orch
    monkeypatch.delenv(C.LIVE_ENV, raising=False)
    seen = {}

    async def fake_check_all(src, ledger=None, crypto_only=False):
        return _trigger_report()

    async def fake_notify(rep, defer=False):
        seen["defer"] = defer
        return {"pushed": [], "deferred": []}
    monkeypatch.setattr(watchlist, "check_all", fake_check_all)
    monkeypatch.setattr(watchlist, "notify_triggers", fake_notify)
    monkeypatch.setattr(orch, "_ledger_store", lambda config: None)
    await orch.watchlist_step(object(), items=[])
    assert seen["defer"] is False
    monkeypatch.setenv(C.LIVE_ENV, "1")
    await orch.watchlist_step(object(), items=[])
    assert seen["defer"] is True


@pytest.mark.asyncio
async def test_live_run_sends_alerts_before_the_deferred_watchlist(monkeypatch, capsys):
    from marketmind.pipeline import orchestration as orch
    monkeypatch.setenv(C.LIVE_ENV, "1")
    order = []
    await wl.notify_triggers(_trigger_report(), defer=True)

    async def fake_alerts(store, notifier=None, crypto_only=False):
        await notifier("MarketMind 大行情警报", "body", priority=True)
        return {"mode": runner.LIVE, "fired": [], "near_misses": [],
                "trend_source": {"available": True}}

    async def fake_send(title, body, priority=False, **kw):
        order.append(title)
        return [{"channel": "serverchan", "ok": True, "status": 200}]
    monkeypatch.setattr(runner, "run_alerts", fake_alerts)
    monkeypatch.setattr(notify, "send", fake_send)
    monkeypatch.setattr(orch, "_ledger_store", lambda config: None)
    await orch.alerts_step(object())
    assert [t.split("：")[0].split(" ")[1] for t in order] == ["大行情警报", "观察触发"]
    assert "deferred push sent" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_failed_alert_step_still_releases_the_deferred_push(monkeypatch, capsys):
    from marketmind.pipeline import orchestration as orch
    await wl.notify_triggers(_trigger_report(), defer=True)
    sent = []

    async def boom(store, **kw):
        raise RuntimeError("x")

    async def fake_send(title, body, **kw):
        sent.append(title)
        return [{"channel": "serverchan", "ok": True, "status": 200}]
    monkeypatch.setattr(runner, "run_alerts", boom)
    monkeypatch.setattr(notify, "send", fake_send)
    monkeypatch.setattr(orch, "_ledger_store", lambda config: None)
    await orch.alerts_step(object())
    assert len(sent) == 1 and "观察触发" in sent[0]


# ── dashboard alert page API ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_instruments_outcomes_and_budget(env):  # noqa: F811
    from marketmind.api import whitebox
    store, tmp = env
    report, _ = await _run(store, tmp)
    _fill_quota(2, datetime.now(timezone.utc))
    d = whitebox.get_big_alerts()
    ins = d["instruments"]
    assert ins["available"] and ins["source"] == "daily_state_machine" and ins["universe"] == "lean"
    rows = {r["ticker"]: r for r in ins["rows"]}
    assert set(rows) == {"QQQ", "GLD", "IWM", "BTC-USD", "SPY", "TLT"}
    assert rows["QQQ"]["state"] == "TREND" and rows["QQQ"]["stop_level"] == 90.0
    qid = next(f["entry_id"] for f in report["fired"] if f["ticker"] == "QQQ")
    assert rows["QQQ"]["last_alert"]["entry_id"] == qid
    assert rows["GLD"]["last_alert"] is None                      # exits are not in the ledger
    assert d["outcomes"]["all"] == {"n": 2, "settled": 0, "wins": 0, "avg_net": None}
    assert d["outcomes"]["by_response"]["none"]["n"] == 2
    assert d["push_budget"]["sent_today"] == 2 and d["push_budget"]["limit"] == 5
    h = next(x for x in d["history"] if x["entry_id"] == qid)
    assert h["status_note"] == "no_votes" and h["exit_reason"] is None        # no voters here


def test_outcomes_split_by_response():
    from marketmind.api.whitebox import alert_outcomes
    rows = [{"status": "settled", "net_return": 0.04, "response": "accept"},
            {"status": "settled", "net_return": -0.02, "response": "reject"},
            {"status": "settled", "net_return": 0.06, "response": "reject"},
            {"status": "open", "net_return": None, "response": None}]
    o = alert_outcomes(rows)
    assert o["all"]["n"] == 4 and o["all"]["settled"] == 3 and o["all"]["wins"] == 2
    assert o["by_response"]["reject"]["avg_net"] == pytest.approx(0.02)
    assert o["by_response"]["none"] == {"n": 1, "settled": 0, "wins": 0, "avg_net": None}


def test_dashboard_without_trend_file(tmp_path, monkeypatch):
    from marketmind.api import whitebox
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    store = LedgerStore(tmp_path / "ledger.db")
    monkeypatch.setattr(whitebox, "_store", lambda: store)
    _add(store, "alert", "alert:observe", "SPY", status="supported")
    d = whitebox.get_big_alerts()
    assert d["available"] and d["instruments"]["available"] is False
