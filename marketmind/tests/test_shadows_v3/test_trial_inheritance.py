"""Challengers inherit review facts (docs/S7_DESIGN.md §二 继承输入, owner decision 2026-09-29)."""
import json

import pytest

from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.promotion.review_facts import MAX_CHARS, format_facts, review_facts
from marketmind.shadows.v3 import roster, trials

TODAY = "2026-09-28"
PARENT = "momentum:weekly:trend_rider"
PEER = "momentum:sector:rotation_engine"
OUTSIDER = "expert:gold:bullion_broker"


def _rec(sid, net, cls, *, above=True, ret20=0.02, mfe_atr=1.5, mae_atr=-0.5,
         ambiguous=False, review=True, day="2026-09-01"):
    e = LedgerEntry("shadow", sid, "SPY", "long", 5, 0.6, 200, "x",
                    meta={"run_date": day}, created_at=f"{day}T10:00:00+00:00")
    e.status, e.net_return, e.pnl_usd = "settled", net, net * 200
    e.entry_date = e.exit_date = day
    if review:
        e.review = {"v": 2, "error_class": cls, "mfe_atr": mfe_atr, "mae_atr": mae_atr,
                    "ambiguous_bar": ambiguous,
                    "regime": {"ret_20d": ret20, "above_ma50": above, "above_ma200": above}}
    return e


def _sample():
    rows = [_rec("S", 0.02, "win") for _ in range(6)]
    rows += [_rec("S", 0.01, "beta_carried", above=False, ret20=-0.01) for _ in range(2)]
    rows += [_rec("S", -0.001, "cost_flipped", ambiguous=True)]
    rows += [_rec("S", -0.03, "right_but_stopped", above=False, ret20=-0.02,
                  mfe_atr=None, mae_atr=None) for _ in range(3)]
    rows += [_rec("S", -0.02, "thesis_wrong", above=None, ret20=None)]
    rows += [_rec("S", 0.5, "win", review=False)]                  # no review: ignored
    return rows


def test_review_facts_numbers_from_code():
    f = review_facts(_sample())
    assert f["n"] == 13
    assert f["error_class"] == {"win": 6, "beta_carried": 2, "cost_flipped": 1,
                                "right_but_stopped": 3, "thesis_wrong": 1}
    assert f["right_but_stopped_share"] == pytest.approx(3 / 13)
    assert f["ambiguous_bar_share"] == pytest.approx(1 / 13)
    assert f["atr_n"] == 10 and f["mfe_atr"] == pytest.approx(1.5) and f["mae_atr"] == pytest.approx(-0.5)
    above, below = f["by_ma200"]["above"], f["by_ma200"]["below"]
    assert (above["n"], below["n"], f["by_ma200"]["unknown"]["n"]) == (7, 5, 1)
    assert above["win_rate"] == pytest.approx(6 / 7)
    assert above["mean_net"] == pytest.approx((6 * 0.02 - 0.001) / 7)
    assert below["win_rate"] == pytest.approx(2 / 5)
    assert below["mean_net"] == pytest.approx((2 * 0.01 - 3 * 0.03) / 5)
    up, down = f["by_ret20"]["up"], f["by_ret20"]["down"]
    assert (up["n"], down["n"]) == (7, 5) and down["win_rate"] == pytest.approx(0.4)


def test_small_samples_are_labelled_weak_and_text_is_capped():
    text = format_facts(review_facts(_sample()))
    assert "settled records with review facts: 13 (n < 20, weak evidence)" in text
    assert "right_but_stopped 3 (23.1%)" in text and "above MA200: n=7" in text
    big = [_rec("S", 0.01, "win") for _ in range(25)]
    text = format_facts(review_facts(big))
    assert "settled records with review facts: 25\n" in text
    assert "above MA200: n=25, win rate 100.0%, mean net return 1.00%\n" in text
    assert "below MA200: no records" in text
    assert len(text) <= MAX_CHARS
    assert format_facts(review_facts([])) == "(no settled records with review facts yet)"


def _variant(parent_text):
    return parent_text.replace("## Exit", "Also require volume confirmation.\n\n## Exit", 1)


def _state(tmp, peer_stage="formal"):
    shadows = {PEER: {"stage": peer_stage, "score": {"score": 0.7}},
               OUTSIDER: {"stage": "advisor", "score": {"score": 0.99}},
               PARENT: {"stage": "formal", "score": {"score": 0.1}}}
    (tmp / "promotion").mkdir(exist_ok=True)
    (tmp / "promotion" / "state.json").write_text(json.dumps({"shadows": shadows}), encoding="utf-8")


@pytest.mark.asyncio
async def test_variant_prompt_carries_parent_and_peer_review_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    store = LedgerStore(tmp_path / "ledger.db")
    for e in [_rec(PARENT, -0.03, "right_but_stopped") for _ in range(4)] + \
             [_rec(PEER, 0.02, "win", above=False) for _ in range(30)] + \
             [_rec(OUTSIDER, 0.05, "win") for _ in range(3)]:
        store.add(e, created_at=e.created_at)
    _state(tmp_path)
    original = roster.load_prompt(roster.by_id()[PARENT])
    seen = {}

    async def call(system, user):
        seen["user"] = user
        return _variant(original)
    await trials.propose(PARENT, "challenger", "收紧止损", call=call, store=store, today=TODAY)
    u = seen["user"]
    own = u.split("## 该影子复盘事实")[1].split("## 参考")[0]
    assert "settled records with review facts: 4 (n < 20, weak evidence)" in own
    assert "right_but_stopped 4 (100.0%)" in own
    ref = u.split("## 参考")[1]
    assert "Rotation Engine" in ref and "不是它的方法论" in ref
    assert "settled records with review facts: 30\n" in ref and "below MA200: n=30" in ref
    peer_text = roster.load_prompt(roster.by_id()[PEER])
    assert peer_text.split("\n## ")[1][:200] not in u          # statistics, never its text
    assert "Bullion" not in u                                   # other group is not a reference
    tail = u.split("## 该影子账本成绩")[1]                      # summary + both facts sections
    assert len(tail) < 2 * MAX_CHARS + 1000                     # bounded prompt growth


@pytest.mark.asyncio
async def test_variant_prompt_without_ranked_peer(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    store = LedgerStore(tmp_path / "ledger.db")
    _state(tmp_path, peer_stage="probation")
    original = roster.load_prompt(roster.by_id()[PARENT])
    seen = {}

    async def call(system, user):
        seen["user"] = user
        return _variant(original)
    await trials.propose(PARENT, "beta", "x", call=call, store=store, today=TODAY)
    assert "(no settled records with review facts yet)" in seen["user"]
    assert "同组还没有进入综合排名的其他影子" in seen["user"]
