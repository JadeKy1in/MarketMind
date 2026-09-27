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


def test_single_position_cap_and_zero_or_invalid_size_dropped():
    l3 = Layer3BatchResult(results=[green("SPY"), green("GLD"), green("USO")])
    rep = enforce([card("SPY", size=80), card("GLD", size=float("nan")), card("USO", size=0)], l3)
    sizes = {c.ticker: c.position_size_pct for c in rep.kept}
    assert sizes == {"SPY": 25.0}
    assert sum("size 0" in n for n in rep.notes) == 2


def test_foreign_listing_is_dropped_but_crypto_kept():
    l3 = Layer3BatchResult(results=[green("600900.SS"), green("BTC-USD")])
    rep = enforce([card("600900.SS"), card("BTC-USD")], l3)
    assert [c.ticker for c in rep.kept] == ["BTC-USD"]
    assert any("600900.SS" in n and "Robinhood" in n for n in rep.notes)


def test_total_heat_is_scaled_to_limit():
    # each card: 25% size * (99.25-50)/99.25 ~= 12.4% heat -> 3 cards ~37% > 25%
    l3 = Layer3BatchResult(results=[green(t, stop=50.0) for t in ("A", "B", "C")])
    rep = enforce([card(t, size=25) for t in ("A", "B", "C")], l3)
    total = sum(card_heat_pct(c) for c in rep.kept)
    assert total == pytest.approx(25.0, abs=0.05)
    assert any("heat" in n for n in rep.notes)


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
            {"ticker": "SLV", "action_en": "ENTER", "position_size_pct": 12, "why_cn": "白银对冲",
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
