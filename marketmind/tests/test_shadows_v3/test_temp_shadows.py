"""Temporary shadows (docs/S7_DESIGN.md §二): temp_event, missed_path, trials."""
import json
from dataclasses import dataclass

import pytest

from marketmind.gateway.price_history import Bar, PriceHistory
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.shadows.v3 import missed_path, roster, temp_event, trials
from marketmind.shadows.v3.runner import run_shadow_day

TODAY = "2026-09-28"


@dataclass
class _News:
    id: str
    title: str
    source_name: str
    summary: str = ""
    priority_score: float = 1.0


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    return LedgerStore(tmp_path / "ledger.db"), tmp_path


# ── temp_event ──────────────────────────────────────────────────────────────

def test_prefilter_needs_two_keyword_groups():
    items = [_News("a", "Fed delivers surprise 50 basis point cut", "Reuters"),
             _News("b", "Fed chair speaks about the economy", "CNBC"),
             _News("c", "Missile attack escalates regional conflict", "AP"),
             _News("d", "Apple launches new phone", "Verge")]
    assert [n.id for n in temp_event.prefilter(items)] == ["a", "c"]


def test_parse_events_validates_sources_and_types():
    by_id = {"a": _News("a", "t", "Reuters"), "b": _News("b", "t", "Bloomberg"),
             "c": _News("c", "t", "MarketWatch"), "d": _News("d", "t", "WSJ")}
    reply = json.dumps({"events": [
        {"type": "E1", "title": "美联储意外降息 50 基点", "summary": "s", "news_ids": ["a", "b", "zz"],
         "watchlist": ["TLT", "SPY", "^GSPC", "tlt"]},
        {"type": "E2", "title": "只有一家报道", "news_ids": ["c"]},
        {"type": "E9", "title": "未知类型", "news_ids": ["a", "b"]},
        {"type": "E4", "title": "财长辞职", "news_ids": ["a", "d"], "watchlist": []}]})
    events, dropped = temp_event.parse_events(reply, by_id, TODAY, lambda t: not t.startswith("^"))
    assert [e.type for e in events] == ["E1", "E4"] and len(dropped) == 2
    e1 = events[0]
    assert e1.watchlist == ["TLT", "SPY"] and e1.news_ids == ["a", "b"]
    assert e1.impact == pytest.approx(0.8) and e1.expires == "2026-10-28"
    assert events[1].watchlist == list(temp_event.DEFAULT_WATCHLIST["E4"])


def _hist(ticker, last_move):
    closes = [100 + (i % 2) * 0.5 for i in range(70)]
    closes.append(closes[-1] * (1 + last_move))
    daily = [Bar(f"d{i:03d}", c, c, c, c, 1.0) for i, c in enumerate(closes)]
    return PriceHistory(ticker, "static", daily, [])


def test_vol_shock_is_pure_code():
    events = temp_event.vol_shocks({"USO": _hist("USO", -0.08), "SPY": _hist("SPY", 0.001)}, TODAY)
    assert [e.watchlist[0] for e in events] == ["USO"] and events[0].type == "E3"
    assert "暴跌" in events[0].title and events[0].impact > 0.7


def _ev(eid, t="E1", title="事件", impact=0.5, spawned=TODAY, wl=("SPY",)):
    return temp_event.Event(eid, t, title, "", list(wl), impact, spawned,
                            (__import__("datetime").date.fromisoformat(spawned)
                             + __import__("datetime").timedelta(days=30)).isoformat())


def test_refresh_caps_dedupes_and_retires():
    old = _ev("old", spawned="2026-08-20")                      # expires 09-19
    active = [_ev(f"a{i}", t="E2", title=f"冲突{i}号区域升级", wl=(f"X{i}",)) for i in range(3)]
    cands = [_ev("dup", t="E2", title="冲突0号区域升级", wl=("Q",), impact=0.9),
             _ev("n1", impact=0.8, title="央行加息", wl=("TLT",)),
             _ev("n2", impact=0.7, title="财政部长辞职", t="E4", wl=("UUP",)),
             _ev("n3", impact=0.6, title="波动", t="E3", wl=("USO",))]
    events, spawned = temp_event.refresh([old] + active, cands, TODAY)
    assert old.status == "retired"
    assert [e.event_id for e in spawned] == ["n1", "n2"]      # dup skipped, cap 5 reached
    assert sum(e.status == "active" for e in events) == temp_event.MAX_ACTIVE


@pytest.mark.asyncio
async def test_daily_events_runs_llm_once_per_day(env):
    _, tmp = env
    calls = []

    async def call(s, u):
        calls.append(u)
        return json.dumps({"events": [{"type": "E1", "title": "美联储意外降息", "summary": "s",
                                       "news_ids": ["a", "b"], "watchlist": ["TLT"]}]})
    news = [_News("a", "Fed surprise rate cut", "Reuters"),
            _News("b", "Federal Reserve unexpected cut of 50 basis points", "Bloomberg")]
    s1 = await temp_event.daily_events(news, {}, today=TODAY, call=call, tradable=lambda t: True)
    s2 = await temp_event.daily_events(news, {}, today=TODAY, call=call, tradable=lambda t: True)
    assert s1["spawned"] == ["美联储意外降息"] and s2["skipped"] and len(calls) == 1
    entries = temp_event.roster_entries(temp_event.load(), TODAY)
    assert entries[0].source_type == "temp_shadow" and entries[0].shadow_id.startswith("temp_event:")
    assert "美联储意外降息" in roster.load_prompt(entries[0]) and "{" not in entries[0].prompt_text[:200]


# ── runner with temp entries ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_runner_records_temp_shadow_without_random_benchmark(env, monkeypatch):
    store, _ = env
    entry = temp_event.roster_entries([_ev("e1", wl=("SPY",))], TODAY)[0]

    from marketmind.tests.test_shadows_v3.test_roster_context import history

    async def hist(tickers):
        return {t: history(t) for t in tickers}
    monkeypatch.setattr("marketmind.shadows.v3.runner.get_price_histories", hist)

    async def fred(_):
        return {}

    async def call(system, user, stage):
        assert "Event Shadow" in system
        return json.dumps({"decisions": [{"ticker": "SPY", "direction": "long", "instrument": "etf",
                                          "hold_days": 3, "confidence": 0.55, "position_usd": 200,
                                          "thesis": "event", "falsifier": "SPY closes lower"}]})
    report = await run_shadow_day(store, [], today=TODAY, entries=[entry], call=call, fred_fetch=fred)
    r = report.results[0]
    assert r.status == "submitted", r.errors
    rows = store.list()
    assert [e.source_type for e in rows] == ["temp_shadow"] and rows[0].meta["temp"] == "temp_event"
    again = await run_shadow_day(store, [], today=TODAY, entries=[entry], call=call, fred_fetch=fred)
    assert again.results[0].status == "skipped"


# ── missed_path ─────────────────────────────────────────────────────────────

def test_missed_path_records_untraded_candidates_once(env):
    store, _ = env
    brief = {"date": TODAY, "l3_green": ["NEM", "SLV"], "l2_ticker_candidates": ["GLD", "NEM", "600519.SS"],
             "decision_cards": [{"ticker": "SLV"}]}
    tradable = lambda t: "." not in t
    ids = missed_path.record(store, brief, today=TODAY, tradable=tradable)
    rows = {store.get(i).ticker: store.get(i) for i in ids}
    assert set(rows) == {"NEM", "GLD"}
    assert rows["NEM"].meta["reason"] == "L3 绿灯未成卡" and rows["NEM"].hold_bars == 30
    assert missed_path.record(store, brief, today=TODAY, tradable=tradable) == []


# ── trials ──────────────────────────────────────────────────────────────────

PARENT = "momentum:weekly:trend_rider"


def _variant(parent_text, extra=" Also require volume confirmation."):
    return parent_text.replace("## Exit", extra + "\n\n## Exit", 1)


@pytest.mark.asyncio
async def test_propose_validates_variant_and_capacity(env):
    store, tmp = env
    parent = roster.by_id()[PARENT]
    original = roster.load_prompt(parent)

    async def good(s, u):
        assert "改动说明" in u
        return "```markdown\n" + _variant(original) + "\n```"

    async def bad(s, u):
        return "# too short\n\n## Only one section"
    with pytest.raises(ValueError, match="headings"):
        await trials.propose(PARENT, "beta", "加成交量确认", call=bad, today=TODAY)
    t = await trials.propose(PARENT, "beta", "加成交量确认", call=good, store=store, today=TODAY)
    assert t.ends == "2026-11-23" and trials.prompt_file(t.trial_id).exists()   # 40 trading days
    with pytest.raises(ValueError, match="already has"):
        await trials.propose(PARENT, "beta", "again", call=good, today=TODAY)
    entries = trials.roster_entries()
    assert entries[0].shadow_id == f"trial:{t.trial_id}" and "volume confirmation" in entries[0].prompt_text
    with pytest.raises(ValueError):
        await trials.propose("nope", "beta", "x", call=good, today=TODAY)


def _settled(store, source_type, source_id, day, net, exit_=None, hold=1):
    e = LedgerEntry(source_type, source_id, "SPY", "long", hold, 0.6, 200, "x",
                    meta={"run_date": day})
    e.status, e.net_return, e.pnl_usd = "settled", net, net * 200
    e.entry_date, e.exit_date = day, exit_ or day
    store.add(e, created_at=f"{day}T10:00:00+00:00")


TRIAL_END = trials.add_trading_days("2026-09-01", trials.TRIAL_BARS)


def _trial(tmp, status="running"):
    t = trials.Trial("t1", "challenger", PARENT, "n", "2026-09-01", TRIAL_END, status)
    trials.save([t])
    trials.prompt_file("t1").parent.mkdir(parents=True, exist_ok=True)
    trials.prompt_file("t1").write_text("## x", encoding="utf-8")
    return t


def _trial_days(n=trials.TRIAL_BARS):
    days, d = [], "2026-08-31"
    for _ in range(n):
        d = trials.add_trading_days(d, 1)
        days.append(d)
    return days


def test_evaluate_passes_a_clearly_better_variant(env):
    store, tmp = env
    _trial(tmp)
    for i, d in enumerate(_trial_days()):
        _settled(store, "shadow", PARENT, d, -0.01 + (i % 5) * 0.002)
        _settled(store, "temp_shadow", "trial:t1", d, 0.02 + (i % 3) * 0.002)
    decided = trials.evaluate(store, today="2026-11-20")
    r = decided[0].result
    assert decided[0].status == "passed" and r["pairs"] == 40 and r["test"] == "hac_t"
    assert r["p_value"] < 0.05 and r["p_holm"] == r["p_value"] and r["holm_family"] == 1
    assert r["wilcoxon_p"] < 0.05                                   # reported only


def test_evaluate_waits_for_open_records_and_flags_small_samples(env):
    store, tmp = env
    _trial(tmp)
    _settled(store, "shadow", PARENT, "2026-09-01", 0.01)
    store.add(LedgerEntry("temp_shadow", "trial:t1", "SPY", "long", 3, 0.6, 200, "x",
                          meta={"run_date": "2026-09-01"}), created_at="2026-09-01T10:00:00+00:00")
    assert trials.evaluate(store, today="2026-11-20") == []                 # still pending
    assert trials.evaluate(store, today="2027-01-20")[0].status == "insufficient"


def test_approve_writes_prompt_with_backup(env, tmp_path):
    store, tmp = env
    t = _trial(tmp, status="passed")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "trend_rider.md").write_text("old", encoding="utf-8")
    with pytest.raises(ValueError):
        trials.resolve("nope", True, prompt_dir=prompts)
    done = trials.resolve("t1", True, prompt_dir=prompts)
    assert done.status == "approved" and (prompts / "trend_rider.md").read_text("utf-8") == "## x"
    assert len(list(prompts.glob("trend_rider.md.*.bak"))) == 1
    with pytest.raises(ValueError, match="already"):
        trials.resolve("t1", False, prompt_dir=prompts)


def test_only_passed_trials_can_be_approved(env):
    _, tmp = env
    _trial(tmp, status="failed")
    with pytest.raises(ValueError, match="passed"):
        trials.resolve("t1", True)
