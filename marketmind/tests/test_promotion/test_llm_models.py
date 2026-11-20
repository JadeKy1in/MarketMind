"""Per-LLM-model promotion diagnostic (docs/S7_DESIGN.md §三之二, owner 2026-11-20):
report only. Offline."""
from __future__ import annotations

import json

import pytest

from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.promotion.runner import (LLM_FLIP_MIN_DAYS, llm_breakdown, llm_family,
                                         read_diagnostics, run_promotion)
from marketmind.tests.test_promotion.test_diagnostics import DAYS, _Provider, _roster, _world


@pytest.mark.parametrize("value,family", [
    ("claude-sonnet-5-5", "claude"), ("Claude-Opus-5-5", "claude"),
    ("deepseek-flash", "deepseek"),
    ("deepseek-flash+deepseek-pro", "deepseek"),           # compound, one family
    ("deepseek-flash+claude-sonnet-5-5", "mixed"),         # compound, two families
    (["deepseek-flash", "deepseek-flash"], "deepseek"),    # list (memory_desk), unhashable
    (["claude-sonnet-5-5", "deepseek-flash"], "mixed"),
    (["claude-sonnet-5-5+deepseek-flash"], "mixed"),
    (None, "unknown"), ("", "unknown"), ([], "unknown"), ([None, " "], "unknown"),
    ("gpt-x", "other"), ("gpt-x+claude-sonnet-5-5", "mixed"),
])
def test_llm_family(value, family):
    assert llm_family(value) == family


def _row(day: str, net: float, llm=None, sid="S") -> LedgerEntry:
    meta = {} if llm is None else {"llm": llm}
    return LedgerEntry("shadow", sid, "X", "long", 1, 0.6, 1000.0, "x", status="settled",
                       created_at=day + "T00:00:00Z", exit_date=day, net_return=net, meta=meta)


def test_breakdown_numbers_and_missing_llm():
    rows = [_row(DAYS[0], 0.02, "deepseek-flash"), _row(DAYS[0], -0.01, "deepseek-flash"),
            _row(DAYS[1], 0.03, "deepseek-flash+deepseek-pro"),
            _row(DAYS[2], -0.04, ["claude-sonnet-5-5"]), _row(DAYS[3], 0.01),
            _row(DAYS[3], None, "claude-sonnet-5-5")]           # unsettled return: ignored
    out = llm_breakdown(rows)
    ds = out["by_family"]["deepseek"]
    assert ds["settled"] == 3 and ds["decision_days"] == 2
    assert ds["mean_net"] == pytest.approx(0.04 / 3) and ds["win_rate"] == pytest.approx(2 / 3)
    assert (ds["first_day"], ds["last_day"]) == (DAYS[0], DAYS[1])
    assert out["by_family"]["claude"]["settled"] == 1
    assert out["by_family"]["unknown"] == {"settled": 1, "decision_days": 1, "first_day": DAYS[3],
                                           "last_day": DAYS[3], "mean_net": 0.01, "win_rate": 1.0}
    assert out["sign_flip"] is None                   # too few decision days
    assert out["note"] and "confounded" in out["note"]
    one = llm_breakdown([_row(DAYS[0], 0.01, "deepseek-flash")])
    assert one["note"] is None and llm_breakdown([])["by_family"] == {}


def test_sign_flip_needs_both_families_with_enough_days():
    n = LLM_FLIP_MIN_DAYS
    ds = [_row(DAYS[i], 0.01, "deepseek-flash") for i in range(n)]
    cl = [_row(DAYS[n + i], -0.01, "claude-sonnet-5-5") for i in range(n)]
    flip = llm_breakdown(ds + cl)["sign_flip"]
    assert flip == {"positive": ["deepseek"], "negative": ["claude"], "min_days": n}
    # one family short of the minimum (many rows, few days) -> no flag
    short = [_row(DAYS[n], -0.01, "claude-sonnet-5-5")] * 30
    assert llm_breakdown(ds + short)["sign_flip"] is None
    # same sign -> no flag
    same = [_row(DAYS[n + i], 0.02, "claude-sonnet-5-5") for i in range(n)]
    assert llm_breakdown(ds + same)["sign_flip"] is None
    # "unknown" never takes part in the flag
    unk = [_row(DAYS[n + i], -0.01) for i in range(n)]
    assert llm_breakdown(ds + unk)["sign_flip"] is None


def _run(tmp_path, llm_of):
    bars, trades, _ = _world()
    store = LedgerStore(tmp_path / "ledger.db")
    for i, e in enumerate(trades):
        llm = llm_of(i)
        if llm is not None:
            e.meta = {"llm": llm}
        store.add(e, created_at=e.created_at)
    run_promotion(store, today=DAYS[125], data_dir=tmp_path, roster=_roster("S", "T"),
                  active_ids={"S", "T"}, price_source=StaticPriceSource(bars),
                  factor_provider=_Provider(bars))
    state = json.loads((tmp_path / "promotion" / "state.json").read_text(encoding="utf-8"))
    advisors = json.loads((tmp_path / "advisors.json").read_text(encoding="utf-8"))
    return state, advisors


def test_run_promotion_stores_llm_diagnostic_without_touching_the_ladder(tmp_path):
    split = lambda i: "deepseek-flash" if i < 60 else ["claude-sonnet-5-5"]
    state, adv = _run(tmp_path / "a", split)
    base, base_adv = _run(tmp_path / "b", lambda i: None)
    # report only: stages, gates, metrics, scores and advisors are identical without meta.llm
    assert state["shadows"] == base["shadows"] and adv == base_adv
    for rec in state["shadows"].values():
        assert "llm_models" not in json.dumps(rec)
    s = read_diagnostics(tmp_path / "a", "S")["llm_models"]
    assert s["by_family"]["deepseek"]["settled"] == 60
    assert s["by_family"]["claude"]["settled"] == 60
    assert s["by_family"]["deepseek"]["decision_days"] == 60 and s["note"]
    assert read_diagnostics(tmp_path / "b", "S")["llm_models"]["by_family"].keys() == {"unknown"}
    cohort = read_diagnostics(tmp_path / "a")["meta"]["llm_models"]
    assert cohort["by_family"]["deepseek"]["settled"] == 60
    assert isinstance(cohort["shadows_with_flip"], list)
    assert read_diagnostics(tmp_path / "a", "T")["llm_models"]["by_family"] == {}
