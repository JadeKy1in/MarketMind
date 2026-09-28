"""Playground → ledger and promotion (docs/S8_DESIGN.md "Playground 接回")."""
from types import SimpleNamespace

import pytest

from marketmind.gateway.price_history import Bar, PriceHistory
from marketmind.ledger.store import LedgerStore
from marketmind.playground import ledger_bridge as lb

TODAY = "2026-09-28"


def _hist(t):
    return PriceHistory(t, "static", [Bar("2026-09-25", 10, 11, 9, 10, 1e6)], [])


async def _histories(tickers):
    return {t: _hist(t) for t in tickers if t != "NODATA"}


def _decision(calls, agent="serenity_reply", mock=False):
    return SimpleNamespace(agent_id=agent, run_id="r1", directional_calls=calls,
                           metadata={"mock_mode": mock})


MANIFESTS = {"serenity_reply": SimpleNamespace(domain_benchmark="SOXX", domain_universe=["AXTI", "COHU"])}


def test_parse_call_normalises_and_rejects():
    ok = lambda t: not t.startswith("^")
    c, why = lb.parse_call({"ticker": "$axti", "direction": "Bullish", "confidence": 0.8,
                            "thesis": "bottleneck"}, ok)
    assert c["ticker"] == "AXTI" and c["direction"] == "long" and c["hold"] == 10 and why is None
    assert "净收益为负" in c["falsifier"]
    assert lb.parse_call({"ticker": "AXTI", "direction": "sideways", "confidence": 0.7}, ok)[0] is None
    assert lb.parse_call({"ticker": "AXTI", "direction": "long", "confidence": 1.4}, ok)[0] is None
    assert lb.parse_call({"ticker": "^SOX", "direction": "long", "confidence": 0.7}, ok)[0] is None
    assert lb._position(0.5) == 100 and lb._position(1.0) == 1000 and lb._position(0.75) == 550


@pytest.mark.asyncio
async def test_record_run_writes_calls_benchmark_once(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    result = SimpleNamespace(decisions=[
        _decision([{"ticker": "AXTI", "direction": "bullish", "confidence": 0.8, "thesis": "t"},
                   {"ticker": "NODATA", "direction": "bearish", "confidence": 0.7},
                   {"ticker": "", "direction": "bullish", "confidence": 0.7}]),
        _decision([{"ticker": "COHU", "direction": "bullish", "confidence": 0.9}], mock=True, agent="m")])
    s = await lb.record_run(store, result, MANIFESTS, today=TODAY, tradable=lambda t: True,
                            histories_fn=_histories)
    rows = store.list()
    calls = [e for e in rows if e.source_type == "playground"]
    bench = [e for e in rows if e.source_type == "benchmark"]
    assert [(e.ticker, e.direction, e.source_id) for e in calls] == [("AXTI", "long", "playground:serenity_reply")]
    assert calls[0].position_usd == 640.0 and calls[0].domain_benchmark == "SOXX"
    assert len(bench) == 1 and bench[0].source_id == "random:playground:serenity_reply"
    assert bench[0].ticker in ("AXTI", "COHU") and len(s["dropped"]) == 2
    again = await lb.record_run(store, result, MANIFESTS, today=TODAY, tradable=lambda t: True,
                                histories_fn=_histories)
    assert again["recorded"] == {} and len(store.list()) == 2


def test_manifest_carries_domain_fields():
    from marketmind.playground.agent_manifest import discover_agents
    from marketmind.playground.playground_runner import DEFAULT_PLAYGROUND_DIR
    m = {x.agent_id: x for x in discover_agents(DEFAULT_PLAYGROUND_DIR)}["serenity_reply"]
    assert m.domain_benchmark == "SOXX" and "AXTI" in m.domain_universe


def test_playground_enters_the_promotion_ladder(tmp_path):
    from marketmind.ledger.store import LedgerEntry
    from marketmind.pipeline.orchestration import playground_candidates
    from marketmind.promotion.runner import run_promotion
    from marketmind.shadows.v3 import roster
    store = LedgerStore(tmp_path / "l.db")
    store.add(LedgerEntry("playground", "playground:serenity_reply", "AXTI", "long", 10, 0.7, 500, "x"),
              created_at=f"{TODAY}T10:00:00+00:00")
    cands = playground_candidates()
    active = {r.shadow_id for r in roster.active()} | {c.shadow_id for c in cands}
    s = run_promotion(store, today=TODAY, data_dir=tmp_path,
                      roster=tuple(roster.ROSTER) + tuple(cands), active_ids=active)
    assert s["probation_progress"]["playground:serenity_reply"] == 1
