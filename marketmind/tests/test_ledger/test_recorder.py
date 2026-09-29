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
                         "NVDA": [Bar("2026-09-01", 1, 1, 1, 225.0, 1)]})


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
    assert e.position_usd == 650.0 and e.stop_loss is None and "loses money" in e.falsifier


@pytest.mark.asyncio
async def test_nothing_to_record(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    assert await record_main_decision(DecisionOutput(), None, store, SRC) == []


@pytest.mark.asyncio
async def test_forced_trade_without_direction_is_not_recorded(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    out = DecisionOutput(paper_trade=PaperTrade("NVDA", "neutral", 0.0, "", "L2"))
    assert await record_main_decision(out, None, store, SRC) == []


@pytest.mark.asyncio
async def test_forced_trade_zero_or_percent_confidence(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    ids = await record_main_decision(DecisionOutput(paper_trade=PaperTrade("NVDA", "long", 0.0, "", "")),
                                     None, store, SRC)
    e = store.get(ids[0])
    assert e.confidence == 0.5 and e.confidence_is_default
    ids = await record_main_decision(DecisionOutput(paper_trade=PaperTrade("NVDA", "long", 65, "", "")),
                                     None, store, SRC, created_at=CREATED)   # another session
    assert store.get(ids[0]).confidence == 0.65


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
