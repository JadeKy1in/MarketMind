"""Watch cards: parsed from the decision output, kept only when code-checkable (S10 §3)."""
import json

from marketmind.pipeline.decision import (
    WatchCard, _build_decision_prompt, _parse_decision_response, validate_watch_cards,
)
from marketmind.pipeline.layer1_narrative import Layer1Result
from marketmind.pipeline.layer2_fundamental import Layer2Result
from marketmind.pipeline.layer3_technical import Layer3BatchResult, unavailable_result
from marketmind.pipeline.red_team import RedTeamReport


def waiting(ticker="XLE", close=90.0):
    r = unavailable_result(ticker)
    r.light, r.data_available, r.recommendation, r.close = "yellow", True, "wait", close
    r.support_zone_low, r.support_zone_high = 85.0, 86.0
    r.resistance_zone_low, r.resistance_zone_high = 94.0, 95.0
    r.entry_zone_low, r.entry_zone_high, r.stop_loss, r.target_price = 88.0, 90.5, 84.0, 100.0
    return r


def watch(ticker="XLE", **kw):
    base = dict(ticker=ticker, direction="long", thesis="t",
                conditions=[{"type": "close_above", "value": 95.2}])
    base.update(kw)
    return WatchCard(**base)


def test_parser_reads_watch_cards():
    out = _parse_decision_response(json.dumps({
        "decision_cards": [], "summary": "s",
        "watch_cards": [{"ticker": "xle", "direction": "long", "thesis": "wait for breakout",
                         "conditions": [{"type": "close_above", "value": 95}],
                         "invalidation": [{"type": "close_below", "value": 84}], "expiry_days": 15},
                        "junk", {"no_ticker": 1}]}))
    assert len(out.watch_cards) == 1
    c = out.watch_cards[0]
    assert (c.ticker, c.direction, c.expiry_days) == ("XLE", "long", 15)
    assert c.conditions == [{"type": "close_above", "value": 95}]


def test_price_condition_snaps_to_l3_level():
    kept, dropped = validate_watch_cards([watch()], Layer3BatchResult(results=[waiting()]))
    assert dropped == [] and kept[0].conditions == [{"type": "close_above", "value": 95.0}]


def test_invented_price_or_unknown_type_drops_the_card():
    l3 = Layer3BatchResult(results=[waiting()])
    cards = [watch(conditions=[{"type": "close_above", "value": 97.3}]),
             watch(conditions=[{"type": "rsi_below", "value": 30}]),
             watch(conditions=[]),
             watch(ticker="TSLA")]
    kept, dropped = validate_watch_cards(cards, l3)
    assert kept == [] and len(dropped) == 4


def test_other_condition_types_and_limits():
    l3 = Layer3BatchResult(results=[waiting()])
    ok = watch(conditions=[{"type": "close_above_ma", "value": "50"},
                           {"type": "volume_ratio_at_least", "value": 1.5},
                           {"type": "after_date", "value": "2026-10-02"},
                           {"type": "breakout_20d"}],
               invalidation=[{"type": "close_below", "value": 84.1}, {"type": "made_up"}],
               expiry_days=400)
    kept, _ = validate_watch_cards([ok], l3)
    c = kept[0]
    assert [x["type"] for x in c.conditions] == ["close_above_ma", "volume_ratio_at_least",
                                                 "after_date", "breakout_20d"]
    assert c.invalidation == [{"type": "close_below", "value": 84.0}] and c.expiry_days == 60
    assert validate_watch_cards([watch(conditions=[{"type": "close_above_ma", "value": 30}])], l3)[0] == []
    many, dropped = validate_watch_cards([watch() for _ in range(7)], l3)
    assert len(many) == 5 and "limit" in dropped[-1]


def test_prompt_lists_wait_levels_and_discovery_without_llm_price_in():
    l1 = Layer1Result.__new__(Layer1Result)
    l1.matrix_quadrant, l1.sentiment_direction, l1.price_in_score = "q", "bullish", 0.9
    l2 = Layer2Result()
    prompt = _build_decision_prompt(l1, l2, Layer3BatchResult(results=[waiting()]), RedTeamReport(),
                                    discovery_text="- fred:WRESBAL z=-2.4, cold, not_priced")
    assert "XLE (yellow, wait)" in prompt and "resistance 94.00-95.00" in prompt
    assert "fred:WRESBAL" in prompt and "Price-in" not in prompt
