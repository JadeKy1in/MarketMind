"""memory_desk and its no-memory control twin (docs/PLAYGROUND_AGENTS.md §5).

Mocked LLM and synthetic settled ledger records only: no network, no real LLM call."""
import importlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from marketmind.gateway import llm_trace
from marketmind.gateway.price_history import Bar, PriceHistory
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.playground import ledger_bridge as lb
from marketmind.playground.agent_manifest import load_manifest
from marketmind.playground.agents.memory_desk import memory as M
from marketmind.playground.agents.memory_desk import prompts as P

desk = importlib.import_module("marketmind.playground.agents.memory_desk.adapter")
control = importlib.import_module("marketmind.playground.agents.memory_desk_control.adapter")
AGENTS_DIR = Path(lb.__file__).resolve().parent / "agents"

DOWN = {"ret_20d": -0.03, "above_ma50": False, "above_ma200": True}   # ret20_down/below_ma50
UP = {"ret_20d": 0.03, "above_ma50": True, "above_ma200": True}
D0 = date(2026, 6, 1)


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("real LLM gateway called in a test")
    import marketmind.gateway.async_client as ac
    monkeypatch.setattr(ac, "chat_flash", boom)
    monkeypatch.setattr(ac, "chat_pro", boom)


_seq = iter(range(10_000))


def rec(day: date, win: bool, regime=DOWN, ticker=None, direction="long",
        source="playground:memory_desk", hold=5, status="settled") -> LedgerEntry:
    """A settled record entered on `day` (each call gets a fresh id and ticker slot)."""
    i = next(_seq)
    e = LedgerEntry(source_type="playground", source_id=source,
                    ticker=ticker or desk.UNIVERSE[i % 6], direction=direction, hold_bars=hold,
                    confidence=0.6, position_usd=100.0, falsifier="stop", thesis=f"t{i}",
                    meta={"signal": {"prompt_version": "pv1", "llm": "fake"}})
    e.entry_id, e.created_at = f"e{i:04d}", f"{(day - timedelta(days=1)).isoformat()}T20:00:00Z"
    if status == "settled":
        exit_day = day + timedelta(days=hold)
        e.status, e.entry_date, e.exit_date, e.exit_reason = "settled", day.isoformat(), exit_day.isoformat(), "expiry"
        e.net_return = 0.02 if win else -0.02
        e.review = {"v": 2, "error_class": "win" if win else "thesis_wrong", "mfe": 0.03,
                    "mae": -0.01, "bars_held": hold, "regime": dict(regime)}
    else:
        e.status = status
    return e


def days(start: date, n: int, step: int = 2):
    """n distinct entry days; with the 6-ticker rotation the same ticker recurs >= 12 days apart."""
    return [start + timedelta(days=step * k) for k in range(n)]


def baseline(n=10, wins=6, start=D0):
    return [rec(d, k < wins, UP) for k, d in enumerate(days(start, n))]


def mem_with(records, today):
    mem = M.empty()
    M.sync(mem, records, today)
    return mem


# ── tiers, decay, independence ──────────────────────────────────────────────

def test_regime_tags_and_trading_days():
    assert M.regime_tags(DOWN) == ["ret20_down", "below_ma50", "above_ma200"]
    assert M.regime_tags({"ret_20d": None, "above_ma50": True}) == ["above_ma50"]
    assert M.add_trading_days(date(2026, 10, 2), 1) == date(2026, 10, 5)       # Fri -> Mon


def test_sync_tiers_decay_and_independence():
    today = date(2026, 10, 1)
    old = rec(today - timedelta(days=120), False)                  # exit ~115 days ago -> expired
    fresh = rec(today - timedelta(days=20), True)
    pending = rec(today - timedelta(days=1), False, status="pending")
    mem = M.empty()
    st = M.sync(mem, [old, fresh, pending], today)
    assert st == {"working": 1, "episodic": 1, "expired": 1}
    assert [e["id"] for e in mem["episodic"]] == [fresh.entry_id]
    assert mem["working"][0]["status"] == "pending"
    # same entry date, or the same ticker again within 7 days: not independent
    a, b = rec(D0, False, ticker="SPY"), rec(D0, False, ticker="QQQ")
    c = rec(D0 + timedelta(days=3), False, ticker="SPY")
    d = rec(D0 + timedelta(days=8), False, ticker="SPY")
    units = M.independent([M.episode(x) for x in (a, b, c, d)])
    assert [u["id"] for u in units] == [b.entry_id, c.entry_id]   # a: date taken; d: overlaps c


# ── lesson life cycle ───────────────────────────────────────────────────────

LID = "long|below_ma50"


def test_no_lesson_from_one_or_two_trades():
    recs = baseline() + [rec(d, False) for d in days(D0 + timedelta(days=1), 2)]
    mem = mem_with(recs, date(2026, 8, 1))
    M.update_lessons(mem, date(2026, 8, 1))
    assert LID not in mem["lessons"]


def test_candidate_then_active_only_after_out_of_sample_support():
    t1 = date(2026, 8, 1)
    recs = baseline() + [rec(d, False) for d in days(D0 + timedelta(days=1), 5)]
    mem = mem_with(recs, t1)
    assert M.update_lessons(mem, t1, "pv1") == []
    lesson = mem["lessons"][LID]
    assert lesson["status"] == "candidate" and lesson["claim"] == "lower"
    assert lesson["n"] == 5 and lesson["n_support"] == 5 and lesson["hit_rate"] == 0.0
    assert lesson["baseline"] == 0.6 and lesson["n_oos"] == 0          # in-sample only
    assert lesson["author_prompt_version"] == "pv1"
    assert M.retrieve(mem, {"SPY": ["below_ma50"]}) == []              # candidates never used
    # two new losing trades settle after creation -> validated out of sample -> active
    t2 = date(2026, 8, 20)
    recs += [rec(d, False) for d in days(date(2026, 8, 2), 2, step=3)]
    M.sync(mem, recs, t2)
    assert LID in M.update_lessons(mem, t2)
    lesson = mem["lessons"][LID]
    assert lesson["status"] == "active" and lesson["n_oos"] == 2 and lesson["oos_hit_rate"] == 0.0
    assert [e["event"] for e in mem["log"] if e["lesson"] == LID] == ["created", "activated"]


def test_counter_evidence_retires():
    t1 = date(2026, 8, 1)
    recs = baseline() + [rec(d, False) for d in days(D0 + timedelta(days=1), 3)]
    mem = mem_with(recs, t1)
    M.update_lessons(mem, t1)
    assert mem["lessons"][LID]["status"] == "candidate"
    recs += [rec(d, True) for d in days(date(2026, 8, 2), 6)]          # 6 wins of 9 > 60%
    t2 = date(2026, 8, 25)
    M.sync(mem, recs, t2)
    M.update_lessons(mem, t2)
    assert LID not in mem["lessons"]
    gone = [r for r in mem["retired"] if r["id"] == LID][-1]
    assert gone["status"] == "retired" and gone["retire_reason"].startswith("counter-evidence")
    # not re-created from the same evidence on the day it was retired
    M.update_lessons(mem, t2)
    assert LID not in mem["lessons"] or mem["lessons"][LID]["claim"] == "higher"


def test_out_of_sample_failure_retires_an_active_lesson():
    start = date(2026, 7, 1)                                 # nothing decays before 9-10
    recs = baseline(start=start) + [rec(d, False) for d in days(start + timedelta(days=1), 5)]
    mem = mem_with(recs, date(2026, 8, 1))
    M.update_lessons(mem, date(2026, 8, 1))
    recs += [rec(d, False) for d in days(date(2026, 8, 2), 2, step=3)]
    M.sync(mem, recs, date(2026, 8, 20))
    M.update_lessons(mem, date(2026, 8, 20))
    assert mem["lessons"][LID]["status"] == "active"
    recs += [rec(d, True) for d in days(date(2026, 8, 21), 3, step=3)]  # out of sample 3/5 = baseline
    M.sync(mem, recs, date(2026, 9, 10))
    M.update_lessons(mem, date(2026, 9, 10))
    assert LID not in mem["lessons"]
    assert any(r["id"] == LID and r["retire_reason"].startswith("out-of-sample")
               for r in mem["retired"])


def test_ttl_expiry_and_renewal_by_new_evidence():
    t1 = date(2026, 8, 3)
    recs = baseline() + [rec(d, False) for d in days(D0 + timedelta(days=1), 5)]
    mem = mem_with(recs, t1)
    M.update_lessons(mem, t1)
    assert mem["lessons"][LID]["expires"] == M.add_trading_days(t1, 60).isoformat()
    # renewal: a new supporting (losing) trade settles out of sample
    renewed = [rec(date(2026, 9, 20), False)]
    mem2 = json.loads(json.dumps(mem))
    M.sync(mem2, recs + renewed, date(2026, 10, 1))
    M.update_lessons(mem2, date(2026, 10, 1))
    exit_day = date.fromisoformat(renewed[0].exit_date)
    assert mem2["lessons"][LID]["expires"] == M.add_trading_days(exit_day, 60).isoformat()
    # no new evidence: expired 60 trading days after creation -> retired
    late = M.add_trading_days(t1, 61)
    M.update_lessons(mem, late)
    assert LID not in mem["lessons"]
    assert any(r["id"] == LID and r["retire_reason"].startswith("ttl") for r in mem["retired"])


def test_retrieval_active_matching_regime_max_five():
    mem = M.empty()
    for k in range(7):
        mem["lessons"][f"long|tag{k}"] = {
            "id": f"long|tag{k}", "condition": {"direction": "long", "tag": "below_ma50"},
            "claim": "lower", "status": "active", "edge": -0.1 * (k + 1), "n": 6, "hit_rate": 0.2,
            "baseline": 0.6, "n_support": 5, "n_oos": 2, "oos_hit_rate": 0.0}
    mem["lessons"]["SPY|short"] = {**mem["lessons"]["long|tag0"], "id": "SPY|short",
                                   "condition": {"ticker": "SPY", "direction": "short"},
                                   "status": "candidate"}
    mem["lessons"]["long|above_ma200"] = {**mem["lessons"]["long|tag0"], "id": "long|above_ma200",
                                          "condition": {"direction": "long", "tag": "above_ma200"},
                                          "edge": -0.9}
    got = M.retrieve(mem, {"SPY": ["below_ma50"], "GLD": ["above_ma50"]})
    assert len(got) == 5 and all(l["status"] == "active" for l in got)
    assert got[0]["id"] == "long|tag6" and got[0]["applies_to"] == ["SPY"]
    assert "long|above_ma200" not in {l["id"] for l in got}               # regime does not match
    assert M.retrieve(mem, {"GLD": ["above_ma50"]}) == []
    text = M.render(mem, got)
    assert "[long|tag6]" in text and "applies today to SPY" in text


def test_memory_store_is_atomic_and_tolerates_a_bad_file(tmp_path):
    p = tmp_path / "m" / "memory.json"
    assert M.load(p) == M.empty()
    mem = M.empty()
    mem["lessons"]["x"] = {"id": "x"}
    M.save(p, mem)
    assert M.load(p)["lessons"] == {"x": {"id": "x"}}
    assert not list(p.parent.glob(".*.tmp"))
    p.write_text("{broken", encoding="utf-8")
    assert M.load(p) == M.empty()


# ── adapter end to end (mocked LLM, synthetic bars and ledger) ──────────────

LAST = date(2026, 9, 30)
NOW1 = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
NOW2 = datetime(2026, 10, 2, 14, tzinfo=timezone.utc)


def bars(closes, last=LAST):
    start = last - timedelta(days=len(closes) - 1)
    return [Bar((start + timedelta(days=i)).isoformat(), c, c * 1.01, c * 0.99, c, 1e6)
            for i, c in enumerate(closes)]


def histories():
    up = [100 * 1.001 ** i for i in range(260)]
    spy = [100 + 0.2 * i for i in range(230)] + [146 - j for j in range(1, 31)]  # falls below MA50
    return {t: bars(spy if t == "SPY" else up) for t in desk.UNIVERSE}


def fetch_stub():
    calls = []

    async def fetch(tickers):
        calls.append(list(tickers))
        h = histories()
        return {t: h[t] for t in tickers}
    fetch.calls = calls
    return fetch


class FakeLLM:
    def __init__(self, calls=None, wording=None, fail=False):
        self.seen, self.calls, self.wording, self.fail = [], calls, wording, fail

    async def __call__(self, system, user):
        self.seen.append((system, user))
        if self.fail:
            raise RuntimeError("down")
        if system == P.WORDING_SYSTEM_PROMPT:
            content = json.dumps(self.wording or {}, ensure_ascii=False)
        else:
            content = json.dumps({"calls": self.calls if self.calls is not None else [
                {"ticker": "SPY", "direction": "short", "confidence": 0.95, "thesis": "跌破 MA50",
                 "lessons_used": [LID, "made-up"]},
                {"ticker": "GLD", "direction": "long", "confidence": 0.3, "thesis": "趋势向上"},
                {"ticker": "QQQ", "direction": "long", "confidence": 0.6, "thesis": "x"},
                {"ticker": "XYZ", "direction": "long", "confidence": 0.6, "thesis": "x"}]},
                ensure_ascii=False)
        result = {"content": content, "model": "fake-flash"}
        llm_trace.note(result)                     # as the gateway does
        return result

    def desk_prompts(self):
        return [u for s, u in self.seen if s == P.DESK_SYSTEM_PROMPT]


def seed_store(path):
    store = LedgerStore(path)
    for e in baseline(start=date(2026, 7, 1)) + [rec(d, False) for d in days(date(2026, 7, 2), 5)]:
        store.add(e, created_at=e.created_at)
    store.add(rec(date(2026, 9, 30), False, ticker="QQQ", status="pending"))       # QQQ is held
    # other sources: never memory, never in the prompt (information firewall)
    store.add(rec(date(2026, 7, 3), False, source="playground:tsmom"))
    shadow = rec(date(2026, 7, 5), False, source="lt_value")
    shadow.source_type, shadow.thesis = "shadow", "SHADOW_SECRET_THESIS"
    store.add(shadow)
    return store


@pytest.mark.asyncio
async def test_memory_desk_end_to_end_with_control_twin(tmp_path):
    store = seed_store(tmp_path / "ledger.db")
    fetch, llm = fetch_stub(), FakeLLM(wording={LID: "MA50 之下做多，净赚比例明显低于平时"})
    out1 = await desk.analyze({"news": [{"title": "Fed holds rates"}, {"title": "Cat video"}]},
                              fetch=fetch, llm=llm, now=NOW1, data_dir=tmp_path, store=store)
    mem = M.load(desk.memory_path(tmp_path))
    assert mem["lessons"][LID]["status"] == "candidate" and out1["memory"]["retrieved"] == []
    assert len(mem["episodic"]) == 15                                  # own records only
    # two more own losses in that regime settle -> out-of-sample validated -> active
    for d in (date(2026, 9, 10), date(2026, 9, 13)):
        store.add(rec(d, False, ticker="TLT" if d.day == 10 else "ETH-USD"))
    out = await desk.analyze({"news": [{"title": "Fed holds rates"}]}, fetch=fetch, llm=llm,
                             now=NOW2, data_dir=tmp_path, store=store)
    assert LID in out["memory"]["activated"] and LID in out["memory"]["retrieved"]
    mem = M.load(desk.memory_path(tmp_path))
    assert mem["lessons"][LID]["wording"].startswith("MA50") and mem["lessons"][LID]["wording_by"] == "fake-flash"
    prompt = llm.desk_prompts()[-1]
    section = prompt[prompt.index(P.MEMORY_BEGIN):prompt.index(P.MEMORY_END)]
    assert f"[{LID}] MA50 之下做多" in section and "applies today to SPY" in section
    assert "SHADOW_SECRET_THESIS" not in prompt and "Fed holds rates" in prompt
    # calls: code stops, capped confidence, held and unknown tickers skipped
    calls = {c["ticker"]: c for c in out["directional_calls"]}
    assert set(calls) == {"SPY", "GLD"}
    assert calls["SPY"]["confidence"] == 0.7 and calls["GLD"]["confidence"] == 0.5
    assert calls["SPY"]["falsifier_rule"]["type"] == "close_above"
    assert calls["GLD"]["falsifier_rule"]["type"] == "close_below"
    assert calls["SPY"]["hold_bars"] == 5 and calls["SPY"]["signal_key"] == "2026-10-02:SPY"
    sig = calls["SPY"]["signal"]
    assert sig["prompt_version"] == P.PROMPT_VERSION and sig["llm"] == "fake-flash"
    assert sig["memory"] is True and sig["lessons_used"] == [LID] and sig["raw_confidence"] == 0.95
    assert any(s.startswith("QQQ") for s in out["skipped"]) and any(s.startswith("XYZ") for s in out["skipped"])

    # control twin, same day: cached facts (no fetch), same system prompt, no memory section
    n_fetch = len(fetch.calls)
    before = desk.memory_path(tmp_path).read_text(encoding="utf-8")
    cllm = FakeLLM()
    cout = await control.analyze({"news": [{"title": "Fed holds rates"}]}, fetch=fetch, llm=cllm,
                                 now=NOW2, data_dir=tmp_path, store=store)
    assert len(fetch.calls) == n_fetch
    (csys, cuser), = cllm.seen
    assert csys == P.DESK_SYSTEM_PROMPT and P.MEMORY_BEGIN not in cuser
    stripped = prompt[:prompt.index(P.MEMORY_BEGIN) - 2] + prompt[prompt.index(P.MEMORY_END) + len(P.MEMORY_END):]
    assert cuser == stripped                                         # identical except memory
    assert cout["memory"] is None and cout["memory_enabled"] is False
    assert all(c["signal"]["memory"] is False for c in cout["directional_calls"])
    assert desk.memory_path(tmp_path).read_text(encoding="utf-8") == before
    assert {c["ticker"] for c in cout["directional_calls"]} == {"SPY", "GLD", "QQQ"}  # control holds nothing

    # both go to the ledger as separate Playground sources through the bridge
    async def hist_fn(tickers):
        h = histories()
        return {t: PriceHistory(t, "static", h[t], []) for t in tickers if t in h}
    decisions = [SimpleNamespace(agent_id=a, run_id="r", directional_calls=o["directional_calls"],
                                 metadata={"mock_mode": False})
                 for a, o in (("memory_desk", out), ("memory_desk_control", cout))]
    manifests = {m.agent_id: m for m in (load_manifest(AGENTS_DIR / "memory_desk"),
                                         load_manifest(AGENTS_DIR / "memory_desk_control"))}
    res = await lb.record_run(store, SimpleNamespace(decisions=decisions), manifests,
                              today="2026-10-02", tradable=lambda t: True, histories_fn=hist_fn)
    assert len(res["recorded"]["memory_desk"]) == 2 and len(res["recorded"]["memory_desk_control"]) == 3
    e = store.get(res["recorded"]["memory_desk"][0])
    assert e.source_id == "playground:memory_desk" and e.falsifier_rule is not None
    assert e.meta["signal"]["prompt_version"] == P.PROMPT_VERSION and e.meta["model"] == "memory_desk"
    assert 0.5 <= e.confidence <= 0.7


@pytest.mark.asyncio
async def test_control_keeps_no_memory_and_failures_are_no_call_days(tmp_path):
    store = seed_store(tmp_path / "ledger.db")
    cllm = FakeLLM()
    out = await control.analyze({}, fetch=fetch_stub(), llm=cllm, now=NOW1,
                                data_dir=tmp_path, store=store)
    assert not desk.memory_path(tmp_path).exists()
    assert P.MEMORY_BEGIN not in cllm.seen[0][1] and out["directional_calls"]
    # LLM down: no calls, a reason, memory still maintained by code
    out = await desk.analyze({}, fetch=fetch_stub(), llm=FakeLLM(fail=True), now=NOW1,
                             data_dir=tmp_path / "x", store=store)
    assert out["directional_calls"] == [] and out["no_calls_reason"].startswith("LLM call failed")
    assert M.load(desk.memory_path(tmp_path / "x"))["lessons"][LID]["status"] == "candidate"
    # no usable prices: no LLM call at all
    async def empty_fetch(tickers):
        return {t: None for t in tickers}
    llm = FakeLLM()
    out = await desk.analyze({}, fetch=empty_fetch, llm=llm, now=NOW1, data_dir=tmp_path / "y",
                             store=store)
    assert out["directional_calls"] == [] and llm.seen == []


@pytest.mark.asyncio
async def test_wording_failure_falls_back_to_code_template():
    mem = M.empty()
    mem["lessons"][LID] = {"id": LID, "condition": {"direction": "long", "tag": "below_ma50"},
                           "claim": "lower", "n": 7, "hit_rate": 0.0, "baseline": 0.6,
                           "error_classes": {"thesis_wrong": 7}, "wording": None}
    await desk.word_lessons(mem, [LID], FakeLLM(fail=True))
    assert mem["lessons"][LID]["wording"] is None
    assert M.describe(mem["lessons"][LID]) == "收盘在 MA50 之下时做多：净赚比例低于基准"


@pytest.mark.asyncio
async def test_manifests_mock_mode_and_token_budget():
    for aid in ("memory_desk", "memory_desk_control"):
        m = load_manifest(AGENTS_DIR / aid)
        assert m.agent_id == aid and m.domain_universe == list(desk.UNIVERSE)
        mod = importlib.import_module(f"marketmind.playground.agents.{aid}.adapter")
        assert (await mod.analyze({}, mock=True))["directional_calls"] == []
    # prompt size with a full memory section stays far below ~15k tokens a day
    facts = {"date": "2026-10-02", "unavailable": {},
             "headlines": ["x" * 140] * desk.MAX_HEADLINES,
             "tickers": {t: desk.ticker_facts(t, histories()[t], LAST)[0] for t in desk.UNIVERSE}}
    mem = M.empty()
    mem["working"] = [{"date": "2026-10-01", "ticker": "SPY", "direction": "long", "confidence": 0.6,
                       "status": "settled", "net_return": 0.01, "error_class": "win"}] * 10
    mem["episodic"] = [M.episode(rec(D0, False))] * 5
    lessons = [{"id": f"long|t{k}", "condition": {"direction": "long", "tag": "below_ma50"},
                "claim": "lower", "hit_rate": 0.2, "baseline": 0.6, "n": 9, "n_support": 7,
                "n_oos": 3, "oos_hit_rate": 0.0, "wording": "w" * 120,
                "applies_to": list(desk.UNIVERSE)} for k in range(5)]
    text = desk.P.DESK_SYSTEM_PROMPT + desk.user_prompt(facts, M.render(mem, lessons))
    assert len(text) < 12_000                                        # ~3k tokens in
