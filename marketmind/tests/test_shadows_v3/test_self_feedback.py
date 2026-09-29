"""Self-feedback experiment (docs/S3_DESIGN.md §8): arms, the YOUR RECORD block,
runner wiring, meta.news_sources and the read-only arm comparison."""
import itertools
import random
from dataclasses import replace
from datetime import date, timedelta

import pytest

from marketmind.gateway import llm_trace
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.shadows.v3 import roster, runner, self_feedback as sf
from marketmind.tests.test_shadows_v3.test_roster_context import news
from marketmind.tests.test_shadows_v3.test_runner import TODAY, entries, good, no_fred, reply

VEGA = "expert:vol:vega_trader"          # treatment
GOLD = "expert:gold:bullion_broker"      # control
_IDS = itertools.count()


def rec(sid, ticker="SPY", net=0.01, exit_day="2026-09-20", *, status="settled",
        direction="long", ec="win", above=True, hold=5, source_type="shadow",
        created="2026-09-10T12:00:00Z", pnl=None, brier=None, meta=None, reason="expiry",
        position=200.0):
    e = LedgerEntry(source_type=source_type, source_id=sid, ticker=ticker, direction=direction,
                    hold_bars=hold, confidence=0.6, position_usd=position, falsifier="f",
                    thesis="LLM thesis text that must never be fed back", meta=dict(meta or {}))
    e.created_at, e.status = created, status
    e.entry_id = f"{next(_IDS):06d}"
    if status == "settled":
        e.exit_date, e.net_return, e.exit_reason = exit_day, net, reason
        e.pnl_usd = net * position if pnl is None else pnl
        e.brier = brier
        e.review = {"error_class": ec, "bars_held": 3, "regime": {"above_ma200": above}}
    return e


# ── arms ────────────────────────────────────────────────────────────────

def test_frozen_split_is_the_balanced_rule_over_the_active_roster():
    active = {e.shadow_id for e in roster.active()}
    assert sf.EXPERIMENT_IDS == active and len(active) == 31
    pop = [e for e in roster.ROSTER if e.shadow_id in sf.EXPERIMENT_IDS]
    assert sf.balanced_split(pop) == sf.TREATMENT_IDS
    assert len(sf.TREATMENT_IDS) == 16 and sf.TREATMENT_IDS <= sf.EXPERIMENT_IDS
    for g in {e.group for e in pop}:
        ids = [e.shadow_id for e in pop if e.group == g]
        t = sum(i in sf.TREATMENT_IDS for i in ids)
        assert abs(t - (len(ids) - t)) <= 1, g
    assert sf.arm_for(VEGA) == "treatment" and sf.arm_for(GOLD) == "control"


def test_successors_inherit_and_temporary_shadows_are_excluded():
    assert sf.arm_for(VEGA + "@2") == "treatment" and sf.arm_for(GOLD + "@3") == "control"
    assert sf.arm_for("trial:abc123", "temp_shadow") is None
    assert sf.arm_for("temp_event:x", "temp_shadow") is None
    assert sf.arm_for("missed_path:SPY", "temp_shadow") is None
    assert sf.arm_for("derivatives:odds:odds_analyst") is None     # not in the frozen population
    # a trial variant of a treatment shadow is still control (not "on")
    trial = replace(roster.by_id()[VEGA], shadow_id="trial:abc", source_type="temp_shadow")
    assert not sf.is_on(trial) and sf.is_on(roster.by_id()[VEGA])


def test_switch_env_var(monkeypatch):
    assert sf.enabled()
    for v in ("0", "off", "False"):
        monkeypatch.setenv(sf.ENV_SWITCH, v)
        assert not sf.enabled() and not sf.is_on(roster.by_id()[VEGA])
    monkeypatch.setenv(sf.ENV_SWITCH, "1")
    assert sf.enabled()
    monkeypatch.setattr(sf, "SELF_FEEDBACK_ENABLED", False)
    assert not sf.enabled()


# ── the block ───────────────────────────────────────────────────────────

def test_record_block_facts():
    own = [rec(VEGA, "VXX", 0.02, "2026-09-0%d" % i, ec="win", above=True) for i in range(1, 7)]
    own += [rec(VEGA, "SPY", -0.01, "2026-09-1%d" % i, ec="right_but_stopped", above=False,
                reason="stop", direction="short") for i in range(0, 6)]
    own += [rec(VEGA, "QQQ", status="open", created="2026-09-27T12:00:00Z"),
            rec(VEGA, "SVXY", status="pending", created="2026-09-28T12:00:00Z"),
            rec(VEGA, "UVXY", status="void")]
    base = [rec("random:" + VEGA, "SPY", -0.005, "2026-09-05", source_type="benchmark")]
    text = "\n".join(sf.record_lines(own, base))
    assert text.startswith(sf.BLOCK_TITLE) and text.rstrip().endswith(sf.BLOCK_CLOSE)
    assert "Settled trades: n=12, hit rate 50.0%, mean net +0.50%." in text
    assert "random baseline (same-domain random picks, one a day): n=1, hit rate 0.0%, " \
           "mean net -0.50% (n < 10: weak evidence)" in text
    assert "win 6, beta_carried 0, cost_flipped 0, right_but_stopped 6, thesis_wrong 0" in text
    assert "right_but_stopped share: 50.0%" in text
    assert "- above MA200: n=6, hit rate 100.0%, mean net +2.00% (n < 10: weak evidence)" in text
    assert "- below MA200: n=6, hit rate 0.0%, mean net -1.00% (n < 10: weak evidence)" in text
    last = [ln for ln in text.splitlines() if ln.startswith("- exit ")]
    assert len(last) == sf.LAST_N and last[0].startswith("- exit 2026-09-15 | SPY short")
    assert "| hold 5d, held 3 | net -1.00% | exit stop | right_but_stopped" in last[0]
    assert "Open positions (2):" in text and "- SVXY long, decided 2026-09-28, hold 5d, " \
           "awaiting entry" in text and "UVXY" not in text
    assert "LLM thesis" not in text                 # only code facts feed back


def test_empty_record_and_isolation():
    text = "\n".join(sf.record_lines([], []))
    assert "Settled trades: none yet." in text and "Open positions: none." in text
    rows = [rec(VEGA, "VXX", 0.01), rec(GOLD, "GDX", 0.5, reason="target"),
            rec(VEGA + "@2", "SPY", 0.3), rec(VEGA, "QQQ", 0.2, source_type="temp_shadow")]
    bench = [rec("random:" + GOLD, "GLD", 0.4, source_type="benchmark")]
    text = "\n".join(sf.lines_for(roster.by_id()[VEGA], rows, bench))
    assert "n=1," in text and "VXX" in text
    assert "GDX" not in text and "GLD" not in text and "QQQ" not in text and "+30" not in text


# ── runner ──────────────────────────────────────────────────────────────

@pytest.fixture
def prices(monkeypatch):
    from marketmind.tests.test_shadows_v3.test_roster_context import history

    async def fake_histories(tickers, years=5):
        return {t: history(t) for t in tickers}
    monkeypatch.setattr(runner, "get_price_histories", fake_histories)


def _seed(store):
    store.add(rec(VEGA, "VXX", 0.0123, "2026-09-18"), created_at="2026-09-10T12:00:00Z")
    store.add(rec(GOLD, "GDX", 0.0777, "2026-09-18"), created_at="2026-09-10T12:00:00Z")


async def _run(store, tmp_path):
    seen = {}

    async def call(system, user, stage):
        seen[stage] = (system, user)
        t = "VXX" if "vega" in stage else "GLD"
        return reply(good(t))
    items = [news("VIX jumps as volatility returns", source="Reuters"),
             news("Gold hits record", source="Kitco"), news("Gold ETF flows", source="Bloomberg"),
             news("Gold and silver rally", source="Kitco")]
    await runner.run_shadow_day(store, items, today=TODAY, entries=entries(VEGA, GOLD),
                                call=call, fred_fetch=no_fred, created_at=f"{TODAY}T12:00:00Z")
    return seen


@pytest.mark.asyncio
async def test_runner_treatment_sees_own_record_control_does_not(tmp_path, prices):
    store = LedgerStore(tmp_path / "l.db")
    _seed(store)
    seen = await _run(store, tmp_path)
    v_sys, v_user = seen["shadow:vega_trader"]
    g_sys, g_user = seen["shadow:bullion_broker"]
    assert sf.BLOCK_TITLE in v_user and "+1.23%" in v_user and "GDX" not in v_user
    assert "+7.77%" not in v_user and "## Your own record" in v_sys
    assert sf.BLOCK_TITLE not in g_user and "## Your own record" not in g_sys

    new = {e.source_id: e for e in store.list(source_type="shadow") if e.created_at.startswith(TODAY)}
    vm, gm = new[VEGA].meta, new[GOLD].meta
    assert vm["self_feedback"] == "on" and gm["self_feedback"] == "off"
    by = roster.by_id()
    assert vm["prompt_version"] == llm_trace.prompt_version(runner.system_prompt(by[VEGA], True))
    assert vm["prompt_version"] != llm_trace.prompt_version(runner.system_prompt(by[VEGA]))
    assert gm["prompt_version"] == llm_trace.prompt_version(runner.system_prompt(by[GOLD]))
    # news sources shown to each shadow (keyword-filtered), sorted and unique
    assert gm["news_sources"] == ["Bloomberg", "Kitco"]
    assert vm["news_sources"] == ["Reuters"]
    assert "self_feedback" not in store.list(source_type="benchmark")[0].meta


@pytest.mark.asyncio
async def test_runner_switched_off(tmp_path, prices, monkeypatch):
    monkeypatch.setenv(sf.ENV_SWITCH, "off")
    store = LedgerStore(tmp_path / "l.db")
    _seed(store)
    seen = await _run(store, tmp_path)
    v_sys, v_user = seen["shadow:vega_trader"]
    assert sf.BLOCK_TITLE not in v_user and "## Your own record" not in v_sys
    new = [e for e in store.list(source_type="shadow") if e.created_at.startswith(TODAY)]
    assert {e.meta["self_feedback"] for e in new} == {"off"}


# ── evaluation ──────────────────────────────────────────────────────────

def _days(n, start=date(2026, 10, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _arm_rows(sid, days, edge, rng, llm, flag):
    rows = []
    for i, d in enumerate(days[:-1]):
        net = edge + rng.gauss(0, 0.01)
        rows.append(rec(sid, "SPY", net, days[i + 1], hold=1, created=f"{d}T12:00:00Z",
                        brier=0.25 - edge * 5 + rng.gauss(0, 0.01),
                        meta={"run_date": d, "self_feedback": flag, "llm": llm}))
    return rows


def test_compare_arms_detects_a_better_treatment():
    rng = random.Random(7)
    days = _days(45)
    t_ids = sorted(sf.TREATMENT_IDS)[:3]
    c_ids = sorted(sf.EXPERIMENT_IDS - sf.TREATMENT_IDS)[:3]
    rows = []
    for k, sid in enumerate(t_ids):
        rows += _arm_rows(sid, days, 0.01, rng, "m-a" if k else "m-b", "on")
    for k, sid in enumerate(c_ids):
        rows += _arm_rows(sid, days, 0.0, rng, "m-a" if k else "m-b", "off")
    # ignored: pre-experiment rows, treatment rows made while switched off, trials
    rows.append(rec(t_ids[0], "SPY", -5.0, days[3], meta={"run_date": days[2]}))
    rows.append(rec(t_ids[0], "SPY", -5.0, days[3], meta={"run_date": days[2],
                                                          "self_feedback": "off"}))
    rows.append(rec("trial:x", "SPY", -5.0, days[3], source_type="temp_shadow",
                    meta={"run_date": days[2], "self_feedback": "off"}))
    res = sf.compare_arms(rows)
    o = res["overall"]
    assert res["treatment_unexposed_rows"] == 1
    assert o["rows"] == {"treatment": 132, "control": 132} and o["ready"]
    assert o["shadows"] == {"treatment": 3, "control": 3}
    pnl = o["pnl_per_dollar"]
    assert pnl["mean_diff"] > 0 and pnl["test"]["p_value"] < 0.01
    assert pnl["days"] == 44 and pnl["test"]["lag"] >= 1
    br = o["brier"]
    assert br["mean_diff"] > 0 and br["days"] == 44 and br["test"]["p_value"] < 0.01
    assert set(res["by_model"]) == {"m-a", "m-b"}
    assert res["by_model"]["m-a"]["rows"] == {"treatment": 88, "control": 88}
    assert res["by_model"]["m-a"]["pnl_per_dollar"]["mean_diff"] > 0


def test_compare_arms_null_and_small_samples():
    rng = random.Random(11)
    days = _days(15)
    t = sorted(sf.TREATMENT_IDS)[0]
    c = sorted(sf.EXPERIMENT_IDS - sf.TREATMENT_IDS)[0]
    rows = _arm_rows(t, days, 0.0, rng, "m", "on") + _arm_rows(c, days, 0.0, rng, "m", "off")
    o = sf.compare_arms(rows)["overall"]
    assert not o["ready"] and o["decision_days"] == 14
    assert o["pnl_per_dollar"]["test"]["p_value"] > 0.01
    assert 0 <= o["pnl_per_dollar"]["test"]["p_two_sided"] <= 1
    empty = sf.compare_arms([])
    assert empty["overall"]["pnl_per_dollar"]["mean_diff"] is None
    assert empty["overall"]["brier"]["test"] is None and empty["by_model"] == {}
    # per-dollar: a treatment trading 5x the size with the same returns is no better
    big = [replace(r, position_usd=r.position_usd * 5, pnl_usd=r.pnl_usd * 5)
           for r in _arm_rows(t, days, 0.001, random.Random(3), "m", "on")]
    same = _arm_rows(c, days, 0.001, random.Random(3), "m", "off")
    d = sf.compare_arms(big + same)["overall"]["pnl_per_dollar"]["mean_diff"]
    assert abs(d) < 1e-12
