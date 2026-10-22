"""S9 step 1: automatic beta trials on the weekend run, pass -> approval push.
Offline: the LLM rewrite and the push are fakes."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.shadows.v3 import auto_beta, roster, trials

SAT, SUN, NEXT_SAT = "2026-10-24", "2026-10-25", "2026-10-31"
WORST = "momentum:weekly:trend_rider"
SECOND = "momentum:sector:rotation_engine"
THIRD = "expert:gold:bullion_broker"
GOOD = "expert:tech:silicon_oracle"
FEW_ROWS = "expert:bonds:yield_whisperer"
FEW_DAYS = "expert:energy:oil_geologist"


def _rows(sid, excess, n, days, brier=0.3):
    out = []
    for i in range(n):
        day = f"2026-10-{1 + i % days:02d}"
        e = LedgerEntry("shadow", sid, "SPY", "long", 5, 0.55, 100, "x",
                        meta={"run_date": day}, created_at=f"{day}T10:00:00+00:00")
        e.status, e.net_return, e.excess_domain, e.brier = "settled", excess, excess, brier
        e.review = {"v": 2, "error_class": "thesis_wrong"}
        out.append(e)
    return out


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(auto_beta.ENV_SWITCH, raising=False)
    store = LedgerStore(tmp_path / "ledger.db")
    for e in (_rows(WORST, -0.03, 12, 6) + _rows(SECOND, -0.01, 10, 5) + _rows(THIRD, -0.005, 10, 5)
              + _rows(GOOD, 0.02, 20, 8) + _rows(FEW_ROWS, -0.09, 9, 9) + _rows(FEW_DAYS, -0.09, 20, 4)):
        store.add(e, created_at=e.created_at)
    return SimpleNamespace(tmp=tmp_path, store=store, folder=tmp_path / "trials")


class FakeLLM:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def __call__(self, system, user):
        self.calls.append(user)
        if self.fail:
            raise RuntimeError("LLM down")
        original = user.split("## 原方法论\n\n", 1)[1].split("\n\n## 改动说明", 1)[0]
        return original                      # passes the heading / length check


def test_candidates_rank_and_filters(env):
    c = auto_beta.candidates(env.store, today=SAT, folder=env.folder)
    assert [x["shadow_id"] for x in c] == [WORST, SECOND, THIRD]   # good / few rows / few days out
    assert c[0]["settled"] == 12 and c[0]["days"] == 6 and c[0]["mean_excess"] == pytest.approx(-0.03)
    note = auto_beta.change_note({**c[0], "week": "2026-W43"})
    assert "12 条已结算、6 个决策日" in note and "-3.00%" in note and "thesis_wrong" in note


def test_brier_breaks_ties(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    store = LedgerStore(tmp_path / "ledger.db")
    for e in _rows(WORST, -0.01, 10, 5, brier=0.2) + _rows(SECOND, -0.01, 10, 5, brier=0.4):
        store.add(e, created_at=e.created_at)
    c = auto_beta.candidates(store, today=SAT, folder=tmp_path / "trials")
    assert [x["shadow_id"] for x in c] == [SECOND, WORST]


def test_running_retired_and_recent_parents_are_skipped(env):
    trials.save([trials.Trial("t1", "challenger", WORST, "x", "2026-10-20", "2026-12-15")], env.folder)
    (env.tmp / "promotion").mkdir()
    (env.tmp / "promotion" / "retirements.json").write_text(json.dumps(
        {"proposals": [{"shadow_id": SECOND, "status": "approved"}]}), encoding="utf-8")
    assert SECOND not in {r.shadow_id for r in roster.active()}
    c = auto_beta.candidates(env.store, today=SAT, folder=env.folder)
    assert [x["shadow_id"] for x in c] == [THIRD]
    # a failed trial 30 trading days ago still blocks (REPROPOSE_GAP_DAYS = 60)
    trials.save([trials.Trial("t2", "beta", THIRD, "x", "2026-09-14", "2026-11-09", status="failed")],
                env.folder)
    (env.tmp / "promotion" / "retirements.json").unlink()
    assert [x["shadow_id"] for x in auto_beta.candidates(env.store, today=SAT, folder=env.folder)] \
        == [WORST, SECOND]


def test_propose_cap_per_run_and_idempotent_week(env):
    llm = FakeLLM()
    res = asyncio.run(auto_beta.run(env.store, today=SAT, folder=env.folder, call=llm))
    assert res["status"] == "done" and len(llm.calls) == auto_beta.PER_RUN == 2
    started = trials.load(env.folder)
    assert [(t.kind, t.parent_id, t.status) for t in started] == [("beta", WORST, "running"),
                                                                 ("beta", SECOND, "running")]
    assert started[0].note.startswith("[auto beta 2026-W43]")
    assert "## 该影子复盘事实" in llm.calls[0]                  # existing rewrite prompt + facts
    # same day retry, Sunday run: nothing new, no LLM call
    for day in (SAT, SUN):
        again = asyncio.run(auto_beta.run(env.store, today=day, folder=env.folder, call=llm))
        assert again["status"] == "already_done" and len(llm.calls) == 2
    assert len(trials.load(env.folder)) == 2
    # next weekend: the two parents are busy, the third one starts
    nxt = asyncio.run(auto_beta.run(env.store, today=NEXT_SAT, folder=env.folder, call=llm))
    assert [p["parent_id"] for p in nxt["proposed"]] == [THIRD]


def test_max_running_cap(env):
    trials.save([trials.Trial(f"r{i}", "challenger", f"other:{i}", "x", "2026-10-01", "2026-12-01")
                 for i in range(trials.MAX_RUNNING - 1)], env.folder)
    llm = FakeLLM()
    res = asyncio.run(auto_beta.run(env.store, today=SAT, folder=env.folder, call=llm))
    assert res["slots"] == 1 and [p["parent_id"] for p in res["proposed"]] == [WORST]
    assert sum(t.status == "running" for t in trials.load(env.folder)) == trials.MAX_RUNNING
    full = asyncio.run(auto_beta.run(env.store, today=NEXT_SAT, folder=env.folder, call=llm))
    assert full["slots"] == 0 and full["proposed"] == [] and len(llm.calls) == 1


def test_llm_failure_leaves_the_week_open(env):
    res = asyncio.run(auto_beta.run(env.store, today=SAT, folder=env.folder, call=FakeLLM(fail=True)))
    assert res["status"] == "retry" and trials.load(env.folder) == []
    assert not (env.folder / "auto_beta.json").exists()
    ok = asyncio.run(auto_beta.run(env.store, today=SUN, folder=env.folder, call=FakeLLM()))
    assert ok["status"] == "done" and len(ok["proposed"]) == 2


def test_switch_and_dry_run(env, monkeypatch):
    llm = FakeLLM()
    dry = asyncio.run(auto_beta.run(env.store, today=SAT, folder=env.folder, call=llm, dry_run=True))
    assert dry["would_propose"] == [WORST, SECOND] and llm.calls == []
    assert not env.folder.exists() or trials.load(env.folder) == []
    monkeypatch.setenv(auto_beta.ENV_SWITCH, "0")
    off = asyncio.run(auto_beta.run(env.store, today=SAT, folder=env.folder, call=llm))
    assert off["status"] == "disabled" and llm.calls == []


def _passed(tid="abc12345", status="passed"):
    return trials.Trial(tid, "beta", WORST, "[auto beta] note", "2026-08-01", "2026-09-26",
                        status=status, result={"pairs": 40, "mean_diff": 0.001, "p_holm": 0.01})


def test_pass_pushes_an_approval_request_never_adopts():
    sent, queued = [], []

    async def send(title, body):
        sent.append((title, body))
        return [{"channel": "serverchan", "ok": True}]
    ids = asyncio.run(auto_beta.notify_passed([_passed(), _passed("f1", "failed"),
                                               _passed("i1", "insufficient")],
                                              send=send, enqueue=lambda *a: queued.append(a)))
    assert ids == ["abc12345"] and len(sent) == 1 and queued == []
    title, body = sent[0]
    assert "abc12345" in title and "python -m marketmind.shadows.v3.trials approve abc12345" in body
    assert "reject abc12345" in body and "不会自动采用" in body


def test_undelivered_approval_push_is_queued():
    queued = []

    async def fails(title, body):
        return [{"channel": "serverchan", "ok": False}]

    async def boom(title, body):
        raise OSError("net")

    async def none_configured(title, body):
        return []
    for send in (fails, boom):
        asyncio.run(auto_beta.notify_passed([_passed()], send=send, enqueue=lambda *a: queued.append(a)))
    asyncio.run(auto_beta.notify_passed([_passed()], send=none_configured,
                                        enqueue=lambda *a: queued.append(a)))
    assert len(queued) == 2 and "approve abc12345" in queued[0][1]


def test_promotion_step_notifies_passed_trials(tmp_path, monkeypatch):
    from marketmind.pipeline import orchestration as orch
    from marketmind.promotion import runner
    sent = []

    async def send(title, body, **k):
        sent.append(title)
        return [{"channel": "x", "ok": True}]
    monkeypatch.setattr("marketmind.alerts.notify.send", send)
    monkeypatch.setattr(runner, "run_promotion", lambda *a, **k: {"events": []})
    monkeypatch.setattr(orch, "playground_candidates", lambda: [])
    monkeypatch.setattr(orch, "_ledger_store", lambda c: None)
    monkeypatch.setattr(trials, "evaluate", lambda store: [_passed(), _passed("f1", "failed")])
    orch._reset_step_failures()
    asyncio.run(orch.promotion_step(SimpleNamespace(data_dir=str(tmp_path))))
    assert sent == ["MarketMind 试验通过，待批准 abc12345"] and not orch._step_failures


def test_weekend_step_marks_retry_as_degraded(tmp_path, monkeypatch):
    from marketmind.pipeline import orchestration as orch

    async def fake_run(store, folder=None, **k):
        return {"status": "retry", "week": "2026-W43", "proposed": [], "errors": [{"transient": True}]}
    monkeypatch.setattr(auto_beta, "run", fake_run)
    monkeypatch.setattr(orch, "_ledger_store", lambda c: None)
    orch._reset_step_failures()
    asyncio.run(orch.auto_beta_step(SimpleNamespace(data_dir=str(tmp_path))))
    assert orch._step_failures == ["auto beta"]
    orch._reset_step_failures()
