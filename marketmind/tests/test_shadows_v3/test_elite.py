"""Elite participation: advisors' code-selected ledger opinions for the owner
(docs/S7_DESIGN.md §五). Offline: temp data dir, fake LLM only."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.shadows.v3 import elite
from marketmind.shadows.v3 import pending_signals as P

GOLD = "expert:gold:bullion_broker"
OIL = "expert:energy:oil_geologist"
TECH = "expert:tech:silicon_oracle"
TREND = "momentum:weekly:trend_rider"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKETMIND_BRIEF_DIR", str(tmp_path / "briefs"))
    monkeypatch.delenv("MARKETMIND_ELITE_SUMMARY", raising=False)
    return tmp_path


def _advisors(root, *ids):
    (root / "advisors.json").write_text(json.dumps({"advisors": list(ids)}), encoding="utf-8")


def _state(root, **stages_scores):
    shadows = {sid.replace("__", ":"): ({"stage": st, "score": {"score": sc}} if sc is not None
                                        else {"stage": st})
               for sid, (st, sc) in stages_scores.items()}
    (root / "promotion").mkdir(exist_ok=True)
    (root / "promotion" / "state.json").write_text(json.dumps({"shadows": shadows}),
                                                   encoding="utf-8")


def _add(store, sid, ticker, day, direction="long", status="pending", st="shadow", **meta):
    return store.add(LedgerEntry(
        source_type=st, source_id=sid, ticker=ticker, direction=direction, hold_bars=10,
        confidence=0.7, position_usd=500.0, falsifier="跌破支撑", thesis=f"{ticker} 论点 {day}",
        status=status, meta={"run_date": day, **meta}), created_at=f"{day}T08:00:00Z")


# ── who speaks ──────────────────────────────────────────────────────────

def test_participants_advisors_then_ranked_stand_ins_then_nobody(env):
    assert elite.participants(env) == (elite.NONE, [])
    _state(env, **{GOLD.replace(":", "__"): ("probation", None)})
    assert elite.participants(env) == (elite.NONE, [])      # probation: no composite score
    _state(env, **{GOLD.replace(":", "__"): ("formal", 0.4), OIL.replace(":", "__"): ("formal", 0.9),
                   TECH.replace(":", "__"): ("paused", 0.6), TREND.replace(":", "__"): ("formal", 0.1),
                   "x__y__z": ("probation", 0.99)})
    assert elite.participants(env) == (elite.NOT_YET, [OIL, TECH, GOLD])
    _advisors(env, GOLD)
    assert elite.participants(env) == (elite.ADVISORS, [GOLD])


# ── what is discussed ───────────────────────────────────────────────────

def test_asset_groups_from_tickers_words_and_chinese():
    assert elite.asset_groups_in("GLD 最近怎么样？") == ["precious_metals"]
    assert elite.asset_groups_in("what about gold and crude oil") == ["precious_metals", "energy"]
    assert elite.asset_groups_in("比特币还能涨吗") == ["crypto"]
    assert elite.asset_groups_in("nvda earnings") == ["NVDA"]
    assert elite.asset_groups_in("is it on the table, AI?") == []
    assert elite.asset_groups_in("", tickers=["GC=F", "IBIT"]) == ["precious_metals", "crypto"]


# ── opinions ────────────────────────────────────────────────────────────

def test_gather_selects_latest_decisions_on_the_group_with_ids_and_status(env):
    store = LedgerStore(env / "ledger.db")
    _advisors(env, GOLD, OIL, TREND)
    old = _add(store, GOLD, "GLD", "2026-09-20", status="settled")
    new1 = _add(store, GOLD, "GC=F", "2026-09-25", status="open")
    new2 = _add(store, GOLD, "SLV", "2026-09-25", direction="short",
                pending_signal_id="abc")
    _add(store, GOLD, "GDX", "2026-09-26", status="void")            # never filled: skipped
    _add(store, GOLD, "SPY", "2026-09-27")                            # other group
    _add(store, OIL, "USO", "2026-09-27")                             # not about gold
    _add(store, TECH, "GLD", "2026-09-27")                            # not a participant
    path = P.default_path(env)
    path.parent.mkdir(parents=True)
    P.save({"signals": [{"signal_id": "sig1", "status": "pending", "shadow_id": TREND,
                         "ticker": "GLD", "direction": "long",
                         "condition": {"type": "close_above", "level": 250.0},
                         "run_date": "2026-09-26", "expires_in_days": 10}]}, path)

    res = elite.gather("黄金现在能买吗", data_dir=env)
    assert res["basis"] == elite.ADVISORS and res["asset_groups"] == ["precious_metals"]
    by = {o["shadow_id"]: o for o in res["opinions"]}
    assert set(by) == {GOLD, TREND} and res["silent"] == [OIL]
    recs = by[GOLD]["records"]
    assert {r["entry_id"] for r in recs} == {new1, new2} and old not in {r["entry_id"] for r in recs}
    assert {r["status"] for r in recs} == {"open", "pending"}
    assert any(r.get("from_conditional_signal") for r in recs)
    assert by[GOLD]["name"] == "Bullion Broker"
    assert by[TREND]["records"] == [] and by[TREND]["pending_signals"][0]["condition"] == "收盘上破 250"

    text = elite.format_text(res)
    assert new1 in text and "顾问意见" in text and "无决策权" in text and "等待条件" in text
    assert elite.gather("黄金", data_dir=env, exclude_groups=["precious_metals"])["opinions"] == []


def test_labels_before_advisors_exist(env):
    store = LedgerStore(env / "ledger.db")
    _add(store, GOLD, "GLD", "2026-09-25")
    res = elite.gather("GLD", store=store, data_dir=env)
    assert res["basis"] == elite.NONE and res["opinions"] == []
    assert "暂不显示" in elite.format_text(res)
    _state(env, **{GOLD.replace(":", "__"): ("formal", 0.5)})
    res = elite.gather("GLD", store=store, data_dir=env)
    assert res["basis"] == elite.NOT_YET and "还不是顾问" in elite.format_text(res)
    assert elite.format_text(elite.gather("hello", store=store, data_dir=env)) == ""


# ── optional one-call summary ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_summary_is_one_call_and_keeps_only_given_ids(env):
    store = LedgerStore(env / "ledger.db")
    _advisors(env, GOLD)
    eid = _add(store, GOLD, "GLD", "2026-09-25")
    res = elite.gather("GLD", store=store, data_dir=env)
    calls = []

    async def good(system, user):
        calls.append(user)
        return f"Bullion Broker 看多黄金 [{eid}]，仅供参考。"
    assert eid in await elite.summarize(res, good) and len(calls) == 1

    async def invents(system, user):
        return "看多 [deadbeefdeadbeef]"
    assert await elite.summarize(res, invents) is None

    async def never(system, user):
        raise AssertionError("no call without opinions")
    assert await elite.summarize({"opinions": []}, never) is None


@pytest.mark.asyncio
async def test_owner_block_calls_the_llm_only_when_switched_on(env, monkeypatch):
    store = LedgerStore(env / "ledger.db")
    _advisors(env, GOLD)
    eid = _add(store, GOLD, "GLD", "2026-09-25")
    fake = AsyncMock(return_value=f"摘要 [{eid}]")
    block, groups = await elite.owner_block("GLD", store=store, data_dir=env, call=fake)
    assert eid in block and groups == ["precious_metals"] and fake.await_count == 0
    monkeypatch.setenv("MARKETMIND_ELITE_SUMMARY", "on")
    block, _ = await elite.owner_block("GLD", store=store, data_dir=env, call=fake)
    assert fake.await_count == 1 and "摘要" in block


# ── reporter ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reporter_adds_advisor_opinions_with_record_ids(env):
    from marketmind.api import reporter
    store = LedgerStore(env / "ledger.db")
    _advisors(env, GOLD)
    eid = _add(store, GOLD, "GLD", "2026-09-25")
    fake = AsyncMock(return_value={"content": f"顾问 Bullion Broker 看多 [{eid}]。"})
    with patch("marketmind.api.reporter._ensure_gateway"), \
         patch("marketmind.gateway.async_client.chat_flash", fake):
        r = await reporter.ask("GLD 顾问怎么看？")
    assert r["unknown_ids"] == [] and r["advisor_opinions"]["basis"] == elite.ADVISORS
    prompt = fake.call_args.args[1]
    assert "advisor_opinions" in prompt and eid in prompt
    assert fake.await_count == 1                          # no extra call per shadow

    with patch("marketmind.api.reporter._ensure_gateway", side_effect=RuntimeError("no key")):
        r = await reporter.ask("GLD 顾问怎么看？")
    assert r["error"] == "llm_unavailable"
    assert r["advisor_opinions"]["opinions"][0]["records"][0]["entry_id"] == eid


def test_reporter_hides_signal_ids_from_the_model(env):
    from marketmind.api import reporter
    view = reporter._for_model({"opinions": [{"records": [], "pending_signals": [
        {"signal_id": "0123456789abcdef", "ticker": "GLD"}]}]})
    assert view["opinions"][0]["pending_signals"] == [{"ticker": "GLD"}]
