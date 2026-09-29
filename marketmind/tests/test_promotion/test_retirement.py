"""Retirement -> successor (docs/S7_DESIGN.md §一 退役, owner decision 2026-09-29).

Offline: the LLM rewrite is a fake, no notifications, all files under tmp_path."""
from __future__ import annotations

import json

import numpy as np
import pytest

from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.promotion import retirement as R
from marketmind.promotion.__main__ import main as cli
from marketmind.promotion.ladder import evaluate, trial_ids
from marketmind.promotion.runner import run_promotion
from marketmind.shadows.v3 import roster, trials
from marketmind.shadows.v3.roster import ROSTER, RosterEntry
from marketmind.shadows.v3.trials import Trial

DAYS = [str(d) for d in np.arange(np.datetime64("2026-01-05"), np.datetime64("2026-12-31"),
                                  dtype="datetime64[D]") if np.is_busday(d)]
TODAY = DAYS[60]
OLD = "momentum:weekly:trend_rider"        # retired in the approval tests
DONOR = "momentum:sector:rotation_engine"  # same group, same 8-section template
OTHER = "expert:gold:bullion_broker"       # other group, higher score


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    return tmp_path


def _row(sid, i, net=0.01, excess=-0.005, st="shadow") -> LedgerEntry:
    return LedgerEntry(
        source_type=st, source_id=sid, ticker="SPY", direction="long", hold_bars=1,
        confidence=0.6, position_usd=1000.0, falsifier="x", created_at=f"{DAYS[i]}T12:00:00Z",
        status="settled", entry_date=DAYS[i], exit_date=DAYS[i + 1], net_return=net,
        pnl_usd=net * 1000, excess_domain=excess, brier=0.2, market_return=0.0)


def _rows(sid, excess, n=50):
    return [_row(sid, i, excess=excess) for i in range(n)]


def _trial(tid, parent, status, decided, kind="challenger", p_holm=0.4):
    return Trial(tid, kind, parent, "n", "2026-01-05", "2026-03-02", status,
                 {"p_holm": p_holm}, decided)


def _roster(*ids, group="momentum"):
    return [RosterEntry(s, s.split(":")[-1], s, group, "d", ("SPY",), "SPY") for s in ids]


def _state(**scores):
    return {"shadows": {sid: {"stage": "formal", "score": {"score": s}}
                        for sid, s in scores.items()}}


def _check(data, entries, roster_entries, state, trial_list, today=TODAY):
    return R.check(entries, roster_entries, state, today, trials=trial_list, data_dir=data)


# ── Proposal conditions ─────────────────────────────────────────────────

def test_proposed_after_two_failed_challengers_and_nonpositive_excess(data):
    ros = _roster("A", "B") + _roster("C", group="fundamental")
    state = _state(A=0.1, B=0.6, C=0.9)
    two_failed = [_trial("t1", "A", "failed", "2026-03-01"), _trial("t2", "A", "failed", "2026-05-01")]
    events = _check(data, _rows("A", -0.004), ros, state, two_failed)
    assert [e["type"] for e in events] == ["retire_proposed"]
    p = R.load(data)["proposals"][0]
    assert p["shadow_id"] == "A" and p["status"] == "pending"
    assert p["reason"]["challengers"] == ["t1", "t2"]
    assert p["reason"]["excess_domain_mean"] == pytest.approx(-0.004)
    assert p["reason"]["excess_n"] == 20                    # latest 20-day window only
    # donor: best same-group shadow (B), not the higher-scored shadow of another group
    assert p["successor"] == {**p["successor"], "shadow_id": "A@2", "donor_id": "B",
                              "donor_match": "group", "method": "donor_rewrite"}
    # one open proposal per shadow: the next day does not duplicate it
    assert _check(data, _rows("A", -0.004), ros, state, two_failed, DAYS[61]) == []
    assert len(R.load(data)["proposals"]) == 1


@pytest.mark.parametrize("trial_list, excess", [
    ([_trial("t1", "A", "failed", "2026-03-01")], -0.01),                         # only one
    ([_trial("t1", "A", "failed", "2026-03-01"),
      _trial("t2", "A", "insufficient", "2026-05-01")], -0.01),                   # insufficient
    ([_trial("t1", "A", "insufficient", "2026-03-01"),
      _trial("t2", "A", "insufficient", "2026-05-01")], -0.01),
    ([_trial("t1", "A", "failed", "2026-02-01"), _trial("t2", "A", "insufficient", "2026-03-01"),
      _trial("t3", "A", "failed", "2026-05-01")], -0.01),                         # run broken
    ([_trial("t1", "A", "failed", "2026-03-01"), _trial("t2", "A", "passed", "2026-05-01")], -0.01),
    ([_trial("t1", "A", "failed", "2026-03-01"),
      _trial("t2", "A", "failed", "2026-05-01", kind="beta")], -0.01),            # beta, not challenger
    ([_trial("t1", "A", "failed", "2026-03-01"), _trial("t2", "A", "failed", "2026-05-01")], 0.002),
])
def test_not_proposed(data, trial_list, excess):
    assert _check(data, _rows("A", excess), _roster("A"), _state(A=0.1), trial_list) == []
    assert R.load(data)["proposals"] == []


def test_not_proposed_without_domain_excess_data(data):
    two = [_trial("t1", "A", "failed", "2026-03-01"), _trial("t2", "A", "failed", "2026-05-01")]
    assert _check(data, _rows("A", None), _roster("A"), _state(A=0.1), two) == []


def test_rejection_needs_a_newer_failed_challenger(data):
    two = [_trial("t1", "A", "failed", "2026-03-01"), _trial("t2", "A", "failed", "2026-05-01")]
    rows = _rows("A", -0.01)
    assert _check(data, rows, _roster("A"), _state(A=0.1), two)
    R.reject("A", data_dir=data, today="2026-06-01")
    assert R.load(data)["proposals"][0]["status"] == "rejected"
    assert _check(data, rows, _roster("A"), _state(A=0.1), two, DAYS[70]) == []
    three = two + [_trial("t3", "A", "failed", "2026-07-01")]
    assert _check(data, rows, _roster("A"), _state(A=0.1), three, DAYS[70])
    events = [json.loads(x)["type"] for x in
              (data / "promotion" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == ["retire_rejected"]      # proposals' events are written by run_promotion


def test_no_donor_when_nobody_in_group_or_domain_is_ranked(data):
    ros = _roster("A", "B") + [RosterEntry("C", "c", "C", "fundamental", "other", ("GLD",), "GLD")]
    state = {"shadows": {"A": {"stage": "formal", "score": {"score": 0.1}},
                         "B": {"stage": "probation", "score": None},
                         "C": {"stage": "formal", "score": {"score": 0.9}}}}
    two = [_trial("t1", "A", "failed", "2026-03-01"), _trial("t2", "A", "failed", "2026-05-01")]
    _check(data, _rows("A", -0.01), ros, state, two)
    s = R.load(data)["proposals"][0]["successor"]
    assert s["donor_id"] is None and s["method"] == "own_methodology"
    # same domain benchmark is the fallback when the group has no ranked shadow
    ros2 = _roster("A") + [RosterEntry("D", "d", "D", "fundamental", "other", ("SPY",), "SPY")]
    peer, score, match = R.best_peer(ros2[0], ros2, _state(A=0.1, D=0.5))
    assert (peer.shadow_id, score, match) == ("D", 0.5, "domain")


def test_successor_ids():
    assert R.successor_id("x:y:z") == "x:y:z@2" and R.successor_id("x:y:z@2") == "x:y:z@3"


# ── Approval ────────────────────────────────────────────────────────────

def _propose_real(data, donor_score=0.7):
    by = roster.by_id()
    ros = [by[OLD], by[DONOR], by[OTHER]]
    state = {"shadows": {OLD: {"stage": "formal", "score": {"score": 0.1}},
                         DONOR: {"stage": "formal", "score": {"score": donor_score}},
                         OTHER: {"stage": "advisor", "score": {"score": 0.95}}}}
    if donor_score is None:
        state["shadows"][DONOR] = {"stage": "probation"}
    two = [_trial("t1", OLD, "failed", "2026-03-01"), _trial("t2", OLD, "failed", "2026-05-01")]
    assert _check(data, _rows(OLD, -0.01), ros, state, two)


def _rewrite(donor_text):
    return donor_text.replace("## Signals", "Trade only the slot watchlist.\n\n## Signals", 1)


@pytest.mark.asyncio
async def test_approve_retires_and_starts_successor_from_donor(data):
    _propose_real(data)
    donor_text = roster.load_prompt(roster.by_id()[DONOR])
    seen = {}

    async def call(system, user):
        seen["system"], seen["user"] = system, user
        return "```markdown\n" + _rewrite(donor_text) + "\n```"
    prop = await R.approve(OLD, data_dir=data, call=call, today="2026-06-01")
    assert prop["status"] == "approved" and prop["successor"]["method"] == "donor_rewrite"
    assert "8 段" in seen["system"] and donor_text in seen["user"]
    assert "XLK" in seen["user"] and "domain benchmark: SPY" in seen["user"]   # slot watchlist

    assert roster.retired_ids(data) == {OLD}
    active = {r.shadow_id: r for r in roster.active(data)}
    assert OLD not in active and f"{OLD}@2" in active and DONOR in active
    succ = active[f"{OLD}@2"]
    old = roster.by_id(data)[OLD]
    assert (succ.watchlist, succ.domain, succ.group, succ.successor_of) == (
        old.watchlist, old.domain, old.group, OLD)
    text = roster.load_prompt(succ)
    assert "Trade only the slot watchlist." in text and len(trials.headings(text)) == 8
    assert succ.prompt_path == data / "promotion" / "successors" / "momentum_weekly_trend_rider_2.md"
    events = [json.loads(x) for x in
              (data / "promotion" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(e["type"], e["shadow_id"]) for e in events] == [
        ("retire", OLD), ("successor_start", f"{OLD}@2")]
    assert events[1]["to"] == "probation" and events[1]["detail"]["donor"] == DONOR
    with pytest.raises(ValueError, match="no pending"):
        await R.approve(OLD, data_dir=data, call=call)
    s = R.summary(data)
    assert s["pending"] == [] and s["retired"][0]["successor"] == f"{OLD}@2"


@pytest.mark.asyncio
async def test_approve_without_donor_copies_own_methodology(data):
    _propose_real(data, donor_score=None)

    async def call(system, user):
        raise AssertionError("no LLM call without a donor")
    prop = await R.approve(OLD, data_dir=data, call=call, today="2026-06-01")
    assert prop["successor"]["method"] == "own_methodology"
    succ = roster.by_id(data)[f"{OLD}@2"]
    assert roster.load_prompt(succ).strip() == roster.load_prompt(roster.by_id()[OLD]).strip()


@pytest.mark.asyncio
async def test_bad_rewrite_keeps_the_proposal_pending(data):
    _propose_real(data)

    async def call(system, user):
        return "# short\n\n## Only one section"
    with pytest.raises(ValueError, match="rejected"):
        await R.approve(OLD, data_dir=data, call=call)
    assert R.load(data)["proposals"][0]["status"] == "pending"
    assert roster.retired_ids(data) == set()
    assert not (data / "promotion" / "successors").exists()


def test_cli_list_and_reject(data, capsys):
    _propose_real(data)
    assert cli(["retire", "list"]) == 0
    assert OLD in capsys.readouterr().out
    assert cli(["retire", "reject", OLD]) == 0
    assert R.load(data)["proposals"][0]["status"] == "rejected"
    assert cli(["retire", "approve", OLD]) == 2               # nothing pending any more


# ── Runtime effects ─────────────────────────────────────────────────────

def _approved_file(data, sid=OTHER, text=None):
    succ = f"{sid}@2"
    rel = f"successors/{R._slug(succ)}.md"
    (data / "promotion" / "successors").mkdir(parents=True, exist_ok=True)
    (data / "promotion" / rel).write_text(
        text or roster.load_prompt(roster.by_id()[sid]), encoding="utf-8")
    R.save({"proposals": [{"shadow_id": sid, "status": "approved", "decided_at": "2026-06-01",
                           "successor": {"shadow_id": succ, "prompt_file": rel}}]}, data)
    return succ


@pytest.mark.asyncio
async def test_runner_skips_retired_shadow_and_runs_successor(data, monkeypatch):
    from marketmind.shadows.v3 import runner
    from marketmind.tests.test_shadows_v3.test_roster_context import history
    from marketmind.tests.test_shadows_v3.test_runner import good, no_fred, reply

    async def hist(tickers, years=5):
        return {t: history(t) for t in tickers}
    monkeypatch.setattr(runner, "get_price_histories", hist)
    succ = _approved_file(data)
    called = []

    async def call(system, user, stage):
        called.append(stage)
        return reply(good("GLD"))
    store = LedgerStore(data / "l.db")
    old = roster.by_id()[OTHER]
    report = await runner.run_shadow_day(store, [], today="2026-09-28",
                                         entries=[old, roster.by_id()[succ]], call=call,
                                         fred_fetch=no_fred, report_dir=data / "runs")
    assert [r.shadow_id for r in report.results] == [succ] and len(called) == 1
    assert {e.source_id for e in store.list(source_type="shadow")} == {succ}
    assert OTHER not in {r.shadow_id for r in roster.active()}          # env data dir


def test_running_trial_of_retired_parent_stops(data):
    t = Trial("t9", "challenger", OTHER, "n", "2026-09-01", "2026-12-01")
    trials.save([t], data / "trials")
    trials.prompt_file("t9", data / "trials").parent.mkdir(parents=True)
    trials.prompt_file("t9", data / "trials").write_text("## x", encoding="utf-8")
    assert len(trials.roster_entries(data / "trials", today="2026-09-28")) == 1
    _approved_file(data)
    assert trials.roster_entries(data / "trials", today="2026-09-28") == []


def test_ladder_retired_stage_and_dsr_trials_keep_history():
    rows = []
    for sid, mean in (("A", 0.02), ("B", 0.006)):
        rng = np.random.default_rng(len(sid) + int(mean * 1000))
        rows += [_row(sid, i, net=mean + 0.01 * rng.standard_normal(), excess=0.01)
                 for i in range(120)]
    ros = _roster("A", "B")
    base, _ = evaluate(rows, ros, DAYS[110], None, None, active_ids={"A", "B"})
    st, _ = evaluate(rows, ros, DAYS[111], base, None, active_ids={"B"}, retired_ids={"A"})
    a = st["shadows"]["A"]
    assert a["stage"] == "retired" and a["score"] is None and a["tier"] is None
    assert a["retired_from"] == base["shadows"]["A"]["stage"]
    assert a["metrics"] == base["shadows"]["A"]["metrics"]           # last evaluation kept
    assert "A" in trial_ids(rows) and st["dsr_trials"]["raw"] == base["dsr_trials"]["raw"] == 2
    again, _ = evaluate(rows, ros, DAYS[112], st, None, active_ids={"B"}, retired_ids={"A"})
    assert again["shadows"]["A"]["stage"] == "retired"


def test_run_promotion_adds_successor_at_probation(data):
    succ = _approved_file(data)
    store = LedgerStore(data / "ledger.db")
    for e in _rows(OTHER, 0.01, n=5):
        store.add(e, created_at=e.created_at)
    out = run_promotion(store, today="2026-09-28", data_dir=data)
    state = json.loads((data / "promotion" / "state.json").read_text(encoding="utf-8"))
    assert state["shadows"][OTHER]["stage"] == "retired"
    assert state["shadows"][succ]["stage"] == "probation"
    assert len(state["shadows"]) == len(ROSTER) + 1
    assert state["retirements"] == {"pending": [], "retired": [OTHER]}
    assert out["retirements"]["retired"][0]["successor"] == succ
    assert OTHER not in {r.shadow_id for r in roster.active(data)}
    # its history still counts as a DSR trial
    assert state["dsr_trials"]["raw"] == 1 and trial_ids(store.list()) == [OTHER]


def test_run_promotion_writes_retire_proposed_event(data, monkeypatch):
    """End to end through run_promotion: trials on disk + ledger -> proposal + event."""
    store = LedgerStore(data / "ledger.db")
    for e in _rows(OLD, -0.01):
        store.add(e, created_at=e.created_at)
    trials.save([_trial("t1", OLD, "failed", "2026-03-01"),
                 _trial("t2", OLD, "failed", "2026-05-01")], data / "trials")
    out = run_promotion(store, today=DAYS[60], data_dir=data, roster=(roster.by_id()[OLD],))
    assert [e["type"] for e in out["events"]] == ["retire_proposed"]
    lines = (data / "promotion" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["type"] == "retire_proposed"
    state = json.loads((data / "promotion" / "state.json").read_text(encoding="utf-8"))
    assert state["retirements"]["pending"] == [OLD]
