"""Forced daily decision parsing/validation (docs/S3_DESIGN.md §3.2)."""
import json

import pytest

from marketmind.shadows.v3.decision import (
    MAX_DECISIONS, OUTPUT_INSTRUCTIONS, extract_json, parse_decisions, position_for,
)

CLOSES = {"SPY": 100.0, "GLD": 200.0, "BTC-USD": 50000.0}


def _d(**kw):
    base = {"ticker": "SPY", "direction": "long", "hold_days": 5, "confidence": 0.6,
            "thesis": "趋势向上", "falsifier": "收盘跌破 95 说明我错了"}
    base.update(kw)
    return base


def _text(*decisions, fenced=False):
    body = json.dumps({"decisions": list(decisions)}, ensure_ascii=False)
    return f"Here you go:\n```json\n{body}\n```" if fenced else body


def test_valid_decision_with_optional_fields():
    res = parse_decisions(_text(_d(stop=95, target=110,
                                   falsifier_rule={"type": "close_below", "price": 96})), CLOSES)
    assert res.ok and not res.errors and not res.warnings
    d = res.decisions[0]
    assert (d.ticker, d.direction, d.hold_days, d.stop, d.target) == ("SPY", "long", 5, 95, 110)
    assert d.falsifier_rule == {"type": "close_below", "price": 96.0}


def test_fenced_json_and_case_and_dollar_prefix():
    res = parse_decisions(_text(_d(ticker="$gld"), fenced=True), CLOSES)
    assert res.ok and res.decisions[0].ticker == "GLD"


@pytest.mark.parametrize("bad, fragment", [
    ({"ticker": "AAPL"}, "not in today's context"),
    ({"direction": "abstain"}, "no abstaining"),
    ({"confidence": 1.4}, "confidence"),
    ({"confidence": "high"}, "confidence"),
    ({"hold_days": 0}, "hold_days"),
    ({"hold_days": 61}, "hold_days"),
    ({"hold_days": 2.5}, "hold_days"),
    ({"falsifier": " "}, "falsifier is required"),
    ({"thesis": ""}, "thesis is required"),
])
def test_hard_errors_drop_the_decision(bad, fragment):
    res = parse_decisions(_text(_d(**bad)), CLOSES)
    assert not res.ok and fragment in res.errors[0]


def test_soft_errors_drop_only_the_field():
    res = parse_decisions(_text(
        _d(stop=105, target=90, falsifier_rule={"type": "close_above", "price": 120}),
        _d(ticker="GLD", direction="short", stop=190,
           falsifier_rule={"type": "close_above", "price": 210})), CLOSES)
    assert res.ok and len(res.decisions) == 2 and not res.errors
    long, short = res.decisions
    assert long.stop is None and long.target is None and long.falsifier_rule is None
    assert short.stop is None and short.falsifier_rule == {"type": "close_above", "price": 210.0}
    assert len(res.warnings) == 4


def test_limits_duplicates_and_empty():
    many = [_d(ticker=t, direction=dr) for t in ("SPY", "GLD") for dr in ("long", "short")]
    res = parse_decisions(_text(*many), CLOSES)
    assert len(res.decisions) == MAX_DECISIONS and "only the first" in res.warnings[0]
    dup = parse_decisions(_text(_d(), _d(confidence=0.7)), CLOSES)
    assert len(dup.decisions) == 1 and "duplicate" in dup.errors[0]
    assert not parse_decisions(_text(), CLOSES).ok
    assert "empty response" in parse_decisions("", CLOSES).errors[0]
    assert "no parseable JSON" in parse_decisions("I abstain today.", CLOSES).errors[0]


def test_fixed_hold_for_scalper():
    res = parse_decisions(_text(_d(hold_days=5)), CLOSES, fixed_hold=1)
    assert res.decisions[0].hold_days == 1 and "set to 1" in res.warnings[0]


def test_position_scales_with_confidence():
    assert position_for(0.3) == 100 and position_for(0.5) == 100
    assert position_for(0.75) == 550 and position_for(1.0) == 1000


def test_extract_json_bare_list_is_accepted():
    assert extract_json('[{"a": 1}]') == [{"a": 1}]
    res = parse_decisions(json.dumps([_d()]), CLOSES)
    assert res.ok


def test_output_instructions_forbid_abstaining():
    assert "abstaining is not" in OUTPUT_INSTRUCTIONS and '"decisions"' in OUTPUT_INSTRUCTIONS
