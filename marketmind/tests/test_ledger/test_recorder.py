"""Main-pipeline output -> ledger entries."""
import pytest

from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.recorder import record_main_decision
from marketmind.ledger.store import LedgerStore
from marketmind.pipeline.decision import DecisionCard, DecisionOutput, PaperTrade
from marketmind.pipeline.layer3_technical import Layer3BatchResult

CREATED = "2026-09-01T21:00:00Z"
SRC = StaticPriceSource({"COIN": [Bar("2026-09-01", 1, 1, 1, 195.0, 1)],
                         "NVDA": [Bar("2026-09-01", 1, 1, 1, 225.0, 1)],
                         "SPY": [Bar("2026-09-01", 1, 1, 1, 650.0, 1)]})


def card(**kw):
    base = dict(ticker="coin", direction="long", position_size_pct=6.0, entry_low=191.2,
                entry_high=196.1, stop_loss=149.6, target_price=387.3, max_hold_days=30,
                reward_risk_ratio=4.2, thesis="t", risk_statement="r", red_team_note="n",
                cash_reframing="c", invalidation="wrong if COIN < 149.6", confidence=0.55)
    base.update(kw)
    return DecisionCard(**base)


@pytest.mark.asyncio
async def test_cards_recorded_with_zone_entry_and_snapshot(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    ids = await record_main_decision(DecisionOutput(decision_cards=[card()]), None, store, SRC,
                                     created_at=CREATED)
    e = store.get(ids[0])
    assert (e.source_type, e.ticker, e.entry_rule, e.hold_bars) == ("main", "COIN", "zone", 30)
    assert e.position_usd == 1800.0 and e.confidence == 0.55 and not e.confidence_is_default
    assert (e.entry_low, e.entry_high, e.stop_loss) == (191.2, 196.1, 149.6)
    assert store.snapshot(e.snapshot_id)["COIN"]["price"] == 195.0


@pytest.mark.asyncio
async def test_llm_size_is_kept_in_meta_but_not_used(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    ids = await record_main_decision(DecisionOutput(decision_cards=[card(llm_size_pct=0.2)]),
                                     None, store, SRC, created_at=CREATED)
    e = store.get(ids[0])
    assert e.position_usd == 1800.0                        # from position_size_pct 6.0
    assert e.meta["llm_size_pct"] == 0.2 and e.meta["position_size_pct"] == 6.0


@pytest.mark.asyncio
async def test_missing_confidence_and_falsifier_get_explicit_defaults(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    ids = await record_main_decision(
        DecisionOutput(decision_cards=[card(confidence=None, invalidation="")]), None, store, SRC)
    e = store.get(ids[0])
    assert e.confidence == 0.5 and e.confidence_is_default
    assert "149.60" in e.falsifier


@pytest.mark.asyncio
async def test_forced_paper_trade_recorded_when_no_cards(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    out = DecisionOutput(paper_trade=PaperTrade("NVDA", "long", 0.65, "green light", "L3"))
    ids = await record_main_decision(out, Layer3BatchResult(results=[]), store, SRC,
                                     created_at=CREATED)
    e = store.get(ids[0])
    assert (e.source_type, e.entry_rule, e.hold_bars) == ("main_forced", "next_open", 10)
    assert e.position_usd == 500.0 and e.stop_loss is None and "loses money" in e.falsifier
    assert e.meta["source"] == "L3"


@pytest.mark.asyncio
async def test_empty_decision_still_records_one_forced_spy_trade(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    ids = await record_main_decision(DecisionOutput(), None, store, SRC)
    assert len(ids) == 1
    e = store.get(ids[0])
    assert (e.source_type, e.ticker, e.direction) == ("main_forced", "SPY", "long")
    assert e.meta["source"] == "fallback:SPY"


@pytest.mark.asyncio
async def test_empty_decision_uses_the_l3_pick(tmp_path):
    from marketmind.tests.test_pipeline.test_decision_guard import green
    store = LedgerStore(tmp_path / "l.db")
    l3 = Layer3BatchResult(results=[green("NVDA", close=225.0, stop=200.0, target=300.0)])
    ids = await record_main_decision(DecisionOutput(), l3, store, SRC)
    e = store.get(ids[0])
    assert (e.ticker, e.stop_loss, e.target_price, e.meta["source"]) == ("NVDA", 200.0, 300.0, "L3")


@pytest.mark.asyncio
async def test_forced_trade_without_direction_falls_back_to_spy(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    out = DecisionOutput(paper_trade=PaperTrade("NVDA", "neutral", 0.0, "", "L2"))
    ids = await record_main_decision(out, None, store, SRC)
    assert len(ids) == 1 and store.get(ids[0]).ticker == "SPY"


@pytest.mark.asyncio
async def test_forced_trade_confidence_is_always_unstated(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    for pt_conf, created in ((None, None), (0.65, CREATED)):         # two sessions
        ids = await record_main_decision(
            DecisionOutput(paper_trade=PaperTrade("NVDA", "long", pt_conf, "", "L3")),
            None, store, SRC, created_at=created)
        e = store.get(ids[0])
        assert e.confidence == 0.5 and e.confidence_is_default
        assert e.meta["confidence_unstated"] is True


@pytest.mark.asyncio
async def test_spy_fallback_ignores_insane_spy_levels(tmp_path):
    from marketmind.tests.test_pipeline.test_decision_guard import green
    store = LedgerStore(tmp_path / "l.db")
    spy = green("SPY", close=650.0, stop=700.0)      # stop above entry: not usable
    spy.light = "red"
    ids = await record_main_decision(DecisionOutput(), Layer3BatchResult(results=[spy]), store, SRC)
    e = store.get(ids[0])
    assert e.ticker == "SPY" and e.stop_loss is None


@pytest.mark.asyncio
async def test_card_without_stop_or_invalidation_still_recorded(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    ids = await record_main_decision(
        DecisionOutput(decision_cards=[card(stop_loss=0.0, invalidation="")]), None, store, SRC)
    assert "loses money" in store.get(ids[0]).falsifier


@pytest.mark.asyncio
async def test_cards_carry_their_origin(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    origin = {"kind": "anomaly", "series": ["fred:WRESBAL"], "anomaly_id": "2026-09-28:fred:WRESBAL"}
    ids = await record_main_decision(DecisionOutput(decision_cards=[card()]), None, store, SRC,
                                     origins={card().ticker.upper(): origin})
    assert store.get(ids[0]).meta["origin"] == origin
    ids = await record_main_decision(DecisionOutput(decision_cards=[card()]), None, store, SRC,
                                     created_at=CREATED)                      # another session
    assert store.get(ids[0]).meta["origin"] == {"kind": "news"}
