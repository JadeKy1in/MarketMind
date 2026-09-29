"""Tests for the code-enforced decision guard (SPEC_v3 §5 step 6)."""
import pytest

from marketmind.pipeline.decision import DecisionCard, _pick_paper_trade
from marketmind.pipeline.decision_guard import card_heat_pct, enforce
from marketmind.pipeline.layer3_technical import Layer3BatchResult, unavailable_result


def green(ticker, close=100.0, stop=90.0, target=130.0):
    r = unavailable_result(ticker)
    r.light, r.data_available, r.recommendation = "green", True, "enter"
    r.entry_zone_low, r.entry_zone_high = close * 0.98, close * 1.005
    r.stop_loss, r.target_price, r.reward_risk_ratio, r.max_hold_days = stop, target, 3.0, 30
    r.close = close
    return r


def card(ticker, size=10.0, direction="long", stop=1.0, target=999.0):
    return DecisionCard(ticker=ticker, direction=direction, position_size_pct=size,
                        entry_low=1.0, entry_high=2.0, stop_loss=stop, target_price=target,
                        max_hold_days=5, reward_risk_ratio=9.9, thesis="t", risk_statement="r",
                        red_team_note="n", cash_reframing="c")


def test_llm_levels_are_overwritten_by_l3():
    l3 = Layer3BatchResult(results=[green("SPY")])
    rep = enforce([card("SPY")], l3)
    c = rep.kept[0]
    assert (c.stop_loss, c.target_price, c.reward_risk_ratio, c.max_hold_days) == (90.0, 130.0, 3.0, 30)
    assert c.entry_low == pytest.approx(98.0) and c.entry_high == pytest.approx(100.5)


def test_non_green_and_short_cards_are_dropped_with_reason():
    yellow = green("QQQ")
    yellow.light = "yellow"
    l3 = Layer3BatchResult(results=[green("SPY"), yellow])
    rep = enforce([card("QQQ"), card("SPY", direction="short"), card("TSLA")], l3)
    assert rep.kept == []
    assert any("QQQ" in n and "green" in n for n in rep.notes)
    assert any("SPY" in n and "long" in n for n in rep.notes)


def test_size_is_risk_budget_over_stop_distance_and_llm_size_ignored():
    # entry mid = (98 + 100.5) / 2 = 99.25; stop 90 -> 9.3199% -> 1% / 9.3199% = 10.73%
    l3 = Layer3BatchResult(results=[green("SPY"), green("GLD"), green("USO")])
    rep = enforce([card("SPY", size=80), card("GLD", size=float("nan")), card("USO", size=0)], l3)
    sizes = {c.ticker: c.position_size_pct for c in rep.kept}
    assert sizes == {"SPY": 10.73, "GLD": 10.73, "USO": 10.73}
    for c in rep.kept:
        assert card_heat_pct(c) == pytest.approx(1.0, abs=0.01)   # RISK_PER_TRADE_PCT


def test_risk_sizing_formula_and_constants():
    from marketmind.pipeline.decision_guard import (
        MAX_SINGLE_POSITION_PCT, RISK_PER_TRADE_PCT, risk_sized_pct, stop_distance_pct)
    assert (RISK_PER_TRADE_PCT, MAX_SINGLE_POSITION_PCT) == (1.0, 25.0)
    assert risk_sized_pct(5.0) == 20.0
    assert risk_sized_pct(2.0) == 25.0                 # 50% capped
    assert risk_sized_pct(8.0, max_single_pct=10.0) == 10.0
    c = card("X", stop=95.0)
    c.entry_low, c.entry_high = 99.0, 101.0
    assert stop_distance_pct(c) == pytest.approx(5.0)


def test_tight_stop_is_capped_at_single_position_limit():
    l3 = Layer3BatchResult(results=[green("SPY", stop=99.0)])     # 0.25% stop -> 400% raw
    rep = enforce([card("SPY", size=3)], l3)
    assert rep.kept[0].position_size_pct == 25.0
    assert any("single-position cap" in n for n in rep.notes)


@pytest.mark.parametrize("stop", [99.25, 120.0, 0.0, -5.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_stop_distance_is_dropped(stop):
    l3 = Layer3BatchResult(results=[green("SPY", stop=stop)])
    rep = enforce([card("SPY", size=10)], l3)
    assert rep.kept == []
    assert any("SPY" in n and "stop distance" in n for n in rep.notes)


def test_foreign_listing_is_dropped_but_crypto_kept():
    l3 = Layer3BatchResult(results=[green("600900.SS"), green("BTC-USD")])
    rep = enforce([card("600900.SS"), card("BTC-USD")], l3)
    assert [c.ticker for c in rep.kept] == ["BTC-USD"]
    assert any("600900.SS" in n and "Robinhood" in n for n in rep.notes)


def test_total_heat_is_scaled_to_limit():
    # risk sizing puts ~1% heat on each card; with a 2% heat cap three cards are scaled x2/3
    l3 = Layer3BatchResult(results=[green(t, stop=50.0) for t in ("A", "B", "C")])
    rep = enforce([card(t, size=25) for t in ("A", "B", "C")], l3, max_heat_pct=2.0)
    total = sum(card_heat_pct(c) for c in rep.kept)
    assert total == pytest.approx(2.0, abs=0.01)
    assert any("heat" in n for n in rep.notes)


def test_default_caps_hold_with_six_risk_sized_positions():
    tickers = [f"T{i}" for i in range(6)]
    rep = enforce([card(t) for t in tickers], Layer3BatchResult(results=[green(t) for t in tickers]))
    assert len(rep.kept) == 6
    assert sum(card_heat_pct(c) for c in rep.kept) == pytest.approx(6.0, abs=0.05)
    assert not any("heat" in n for n in rep.notes)


def test_position_count_limit():
    tickers = [f"T{i}" for i in range(8)]
    l3 = Layer3BatchResult(results=[green(t) for t in tickers])
    rep = enforce([card(t, size=1) for t in tickers], l3)
    assert len(rep.kept) == 6


@pytest.mark.asyncio
async def test_empty_llm_output_still_yields_explicit_no_trade_and_paper_trade():
    from unittest.mock import AsyncMock, patch
    from marketmind.pipeline.decision import generate_decision
    from marketmind.pipeline.layer1_narrative import Layer1Result
    from marketmind.pipeline.layer2_fundamental import Layer2Result
    from marketmind.pipeline.red_team import RedTeamReport

    l3 = Layer3BatchResult(results=[green("NVDA")])
    with patch("marketmind.pipeline.decision.chat_pro", AsyncMock(return_value={"content": "{}"})), \
         patch("marketmind.pipeline.decision.generate_contrarian_challenges", AsyncMock(return_value=[])):
        out = await generate_decision(Layer1Result.empty_default(), Layer2Result(), l3, RedTeamReport())
    assert out.decision_cards == []
    assert out.no_trade_card is not None
    assert out.paper_trade is not None and out.paper_trade.ticker == "NVDA"


def test_cash_equivalent_etf_is_not_a_trade():
    rep = enforce([card("SHV"), card("bil")], Layer3BatchResult(results=[green("SHV"), green("BIL")]))
    assert rep.kept == [] and sum("cash-equivalent" in n for n in rep.notes) == 2  # case-insensitive


def test_green_but_wait_is_dropped():
    g = green("NVDA")
    g.recommendation, g.reward_risk_ratio = "wait", 0.47
    rep = enforce([card("NVDA")], Layer3BatchResult(results=[g]))
    assert rep.kept == [] and any("wait" in n for n in rep.notes)


def test_parse_accepts_flash_aliases_and_respects_its_action():
    import json
    from marketmind.pipeline.decision import _parse_decision_response
    raw = json.dumps({
        "decision_cards": [
            {"ticker": "SLV", "action_en": "ENTER", "direction": "long", "position_size_pct": 12, "why_cn": "白银对冲",
             "invalidation_cn": "若跌破 54 则错", "red_team_response_cn": "回应"},
            {"ticker": "NVDA", "action_en": "WAIT", "position_size_pct": 8, "why_cn": "等待"},
        ],
        "no_trade_card": {"core_argument_cn": "持币理由", "no_trade_strength": 74},
        "summary": "s"})
    out = _parse_decision_response(raw)
    assert [c.ticker for c in out.decision_cards] == ["SLV"]
    c = out.decision_cards[0]
    assert c.thesis == "白银对冲" and c.invalidation == "若跌破 54 则错" and c.red_team_note == "回应"
    assert out.no_trade_card.thesis == "持币理由" and out.no_trade_card.no_trade_score == 74


def test_parse_decision_coerces_non_string_summary():
    from marketmind.pipeline.decision import _parse_decision_response
    out = _parse_decision_response('{"decision_cards": [], "summary": {"view": "neutral", "risk": "high"}}')
    assert isinstance(out.summary, str) and "neutral" in out.summary


def test_paper_trade_picks_l3_green_by_ticker():
    class L1: sentiment_direction = "neutral"
    class L2: ticker_candidates = []
    l3 = Layer3BatchResult(results=[green("NVDA")])
    paper = _pick_paper_trade(L1(), L2(), l3, None, None)
    assert paper is not None and paper.ticker == "NVDA" and paper.direction == "long"


def test_parse_reads_confidence_and_keeps_llm_size_for_the_record_only():
    import json
    from marketmind.pipeline.decision import _parse_decision_response
    raw = json.dumps({"decision_cards": [
        {"ticker": "COIN", "direction": "long", "position_size_pct": 0.06, "confidence": 0.55, "thesis": "t"},
        {"ticker": "SLV", "direction": "long", "position_size_pct": 12, "confidence": 60, "thesis": "t"},
        {"ticker": "GLD", "direction": "long", "position_size_pct": "big", "confidence": "high", "thesis": "t"},
    ]})
    cards = _parse_decision_response(raw).decision_cards
    assert [c.position_size_pct for c in cards] == [0.0, 0.0, 0.0]    # set later by the guard
    assert [c.llm_size_pct for c in cards] == [0.06, 12.0, None]      # as written, no unit guess
    assert [c.confidence for c in cards] == [0.55, 0.6, None]


def test_guard_size_ignores_llm_size():
    import json
    from marketmind.pipeline.decision import _parse_decision_response
    l3 = Layer3BatchResult(results=[green("A"), green("B")])
    raw = json.dumps({"decision_cards": [{"ticker": "A", "direction": "long", "position_size_pct": 0.5},
                                         {"ticker": "B", "direction": "long", "position_size_pct": 90}]})
    kept = enforce(_parse_decision_response(raw).decision_cards, l3).kept
    assert [(c.position_size_pct, c.llm_size_pct) for c in kept] == [(10.73, 0.5), (10.73, 90.0)]


def test_decision_prompts_no_longer_ask_the_llm_for_a_size():
    from marketmind.pipeline import decision as d
    d._rule_registry = None
    for prompt in (d.DECISION_OUTPUT_SCHEMA, d.DECISION_SYSTEM_PROMPT, d._get_decision_prompt()):
        assert "position_size_pct" not in prompt
        assert "conviction" not in prompt
    assert "computed by code from the L3 stop distance" in d.DECISION_OUTPUT_SCHEMA
    assert "computed by code from the stop distance" in d.DECISION_SYSTEM_PROMPT


def test_paper_trade_falls_back_to_long_spy_without_l3_candidates():
    class L1: sentiment_direction = "bearish"       # L1/L2 no longer steer the forced trade
    class L2: ticker_candidates = ["NVDA", "AMD"]
    for l3 in (Layer3BatchResult(results=[]), None):
        p = _pick_paper_trade(L1(), L2(), l3, None, None)
        assert (p.ticker, p.direction, p.confidence, p.source) == ("SPY", "long", None, "fallback:SPY")


def test_paper_trade_picks_best_reward_risk_then_ticker():
    a, b, c = green("BBB"), green("AAA"), green("CCC")
    a.reward_risk_ratio, b.reward_risk_ratio, c.reward_risk_ratio = 3.5, 3.5, 2.8
    yellow = green("ZZZ")
    yellow.light, yellow.reward_risk_ratio = "yellow", 9.0          # green light required
    for order in ([a, b, c, yellow], [yellow, c, b, a]):
        p = _pick_paper_trade(None, None, Layer3BatchResult(results=order), None, None)
        assert (p.ticker, p.direction, p.confidence, p.source) == ("AAA", "long", None, "L3")
        assert "3.50" in p.thesis


def test_paper_trade_skips_unusable_l3_levels():
    bad_stop, no_data, cash, nan_rr, ok = (green("A", stop=120.0), green("B"), green("SHV"),
                                           green("D"), green("E"))
    no_data.data_available = False
    for r in (bad_stop, no_data, cash):
        r.reward_risk_ratio = 50.0                    # would win if it were usable
    nan_rr.reward_risk_ratio = float("nan")
    l3 = Layer3BatchResult(results=[bad_stop, no_data, cash, nan_rr, ok])
    assert _pick_paper_trade(None, None, l3, None, None).ticker == "E"
    l3 = Layer3BatchResult(results=[bad_stop, no_data, cash, nan_rr])
    assert _pick_paper_trade(None, None, l3, None, None).source == "fallback:SPY"


@pytest.mark.asyncio
async def test_no_green_day_forces_spy_without_calling_the_llm():
    from unittest.mock import AsyncMock, patch
    from marketmind.pipeline.decision import generate_decision
    from marketmind.pipeline.layer1_narrative import Layer1Result
    from marketmind.pipeline.layer2_fundamental import Layer2Result
    from marketmind.pipeline.red_team import RedTeamReport
    llm = AsyncMock()
    with patch("marketmind.pipeline.decision.chat_pro", llm):
        out = await generate_decision(Layer1Result.empty_default(), Layer2Result(),
                                      Layer3BatchResult(results=[]), RedTeamReport())
    llm.assert_not_called()
    assert out.decision_cards == [] and out.paper_trade.ticker == "SPY"


def test_guard_uses_tradable_universe_when_loaded():
    from datetime import datetime, timezone
    from marketmind.universe import set_equity_universe
    from marketmind.universe.equities import EquityRecord, EquityUniverse
    set_equity_universe(EquityUniverse(
        symbols={"NVDA": EquityRecord("NVDA", "NVIDIA", "Q", False)},
        fetched_at=datetime(2026, 9, 25, tzinfo=timezone.utc), from_cache=True, stale=False))
    l3 = Layer3BatchResult(results=[green("NVDA"), green("ZZZZ"), green("FAKECOIN-USD")])
    rep = enforce([card("NVDA"), card("ZZZZ"), card("FAKECOIN-USD")], l3)
    assert [c.ticker for c in rep.kept] == ["NVDA"]
    assert sum("not tradable" in n for n in rep.notes) == 2


# --- action negations and direction normalisation (red-team 2026-09-29)

def _parse_actions(*actions, direction="long"):
    import json
    from marketmind.pipeline.decision import _parse_decision_response
    raw = json.dumps({"decision_cards": [
        {"ticker": f"T{i}", "action": a, "direction": direction, "position_size_pct": 5}
        for i, a in enumerate(actions)]}, ensure_ascii=False)
    return [c.ticker for c in _parse_decision_response(raw).decision_cards]


@pytest.mark.parametrize("action", [
    "DO NOT ENTER", "DON'T BUY", "DON’T BUY", "DONT ENTER", "NOT A BUY", "AVOID LONG",
    "NO ENTRY - BUY LATER", "WAIT", "WAIT TO ENTER", "SKIP", "PASS ON BUY", "HOLD OFF ON BUYING",
    "never buy", "avoid long exposure",
])
def test_english_negated_actions_are_not_entries(action):
    assert _parse_actions(action) == []


@pytest.mark.parametrize("action", ["不买入", "暂不执行", "勿买入", "别做多", "观望", "等待买入", "回避"])
def test_chinese_negated_actions_are_not_entries(action):
    assert _parse_actions(action) == []


@pytest.mark.parametrize("action", ["ENTER", "BUY", "enter long", "LONG", "执行", "买入", "做多"])
def test_positive_actions_are_entries(action):
    assert _parse_actions(action) == ["T0"]


@pytest.mark.parametrize("raw_dir", ["LONG", " Long ", "long"])
def test_direction_is_normalised(raw_dir):
    import json
    from marketmind.pipeline.decision import _parse_decision_response
    raw = json.dumps({"decision_cards": [{"ticker": "A", "direction": raw_dir, "position_size_pct": 5}]})
    assert [c.direction for c in _parse_decision_response(raw).decision_cards] == ["long"]


@pytest.mark.parametrize("card", [
    {"ticker": "A"},                                  # no direction, no action
    {"ticker": "A", "action": "ENTER"},               # action says nothing about side
    {"ticker": "A", "direction": "neutral"},
    {"ticker": "A", "direction": "hold", "action": "BUY"},
    {"ticker": "A", "direction": ""},
])
def test_missing_or_unknown_direction_drops_card(card, caplog):
    import json
    import logging
    from marketmind.pipeline.decision import _parse_decision_response
    with caplog.at_level(logging.WARNING, logger="marketmind.pipeline.decision"):
        out = _parse_decision_response(json.dumps({"decision_cards": [card]}))
    assert out.decision_cards == []
    assert "direction" in caplog.text


def test_direction_read_from_explicit_directional_action():
    import json
    from marketmind.pipeline.decision import _parse_decision_response
    raw = json.dumps({"decision_cards": [{"ticker": "A", "action": "BUY"},
                                         {"ticker": "B", "action": "买入"}]}, ensure_ascii=False)
    assert [(c.ticker, c.direction) for c in _parse_decision_response(raw).decision_cards] == [
        ("A", "long"), ("B", "long")]
