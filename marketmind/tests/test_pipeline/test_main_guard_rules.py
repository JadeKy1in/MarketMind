"""Main-pipeline guard rules (owner decision 2026-11-20): stop cooldown and bear-trend
protection downgrade long cards to watch items; missing trend data fails open."""
import json
from datetime import date

import pytest

from marketmind.pipeline.decision import DecisionCard
from marketmind.pipeline.decision_guard import (
    MainGuardContext, enforce, load_main_guard_context, load_open_counts, load_stop_exits,
    load_trend_states, trading_days_after,
)
from marketmind.pipeline.layer3_technical import Layer3BatchResult, unavailable_result


def green(ticker, close=100.0, stop=90.0, target=130.0):
    r = unavailable_result(ticker)
    r.light, r.data_available, r.recommendation = "green", True, "enter"
    r.entry_zone_low, r.entry_zone_high = close * 0.98, close * 1.005
    r.stop_loss, r.target_price, r.reward_risk_ratio, r.max_hold_days = stop, target, 3.0, 30
    r.close = close
    return r


def card(ticker):
    return DecisionCard(ticker=ticker, direction="long", position_size_pct=10.0,
                        entry_low=1.0, entry_high=2.0, stop_loss=1.0, target_price=999.0,
                        max_hold_days=5, reward_risk_ratio=9.9, thesis="t", risk_statement="r",
                        red_team_note="n", cash_reframing="c")


BULL = {"SPY": "TREND", "QQQ": "WATCH", "GLD": "TREND", "BTC-USD": "TREND"}


def ctx(today="2026-11-05", stops=None, trend=BULL, open_counts=None):
    return MainGuardContext(today=date.fromisoformat(today), stops=stops or {}, trend=trend,
                            open_counts=open_counts or {},
                            trend_file="2026-11-04" if trend is not None else None)


# ── stop cooldown ──────────────────────────────────────────────────────────

def test_trading_days_skip_weekends_and_count_every_day_for_crypto():
    thu, next_thu = date(2026, 10, 29), date(2026, 11, 5)
    assert trading_days_after(thu, next_thu) == 5
    assert trading_days_after(thu, next_thu, crypto=True) == 7


def test_cooldown_hit_downgrades_card_to_watch_with_chinese_reason():
    rep = enforce([card("XOM")], Layer3BatchResult(results=[green("XOM")]),
                  main=ctx(stops={"XOM": "2026-10-29"}))
    assert rep.kept == []
    (d,) = rep.downgraded
    assert d["rules"] == ["stop_cooldown"]
    assert "止损冷却：XOM 于 10-29 止损，10 个交易日内不再出卡（至 11-12）" in d["reason"]
    assert {"type": "after_date", "value": "2026-11-12"} in d["conditions"]
    assert d["invalidation"] == [{"type": "close_below", "value": 90.0}]
    rec = rep.main_record()
    assert rec["downgrades"][0]["ticker"] == "XOM" and rec["trend_available"] is True


def test_cooldown_miss_after_ten_trading_days_and_for_other_tickers():
    l3 = Layer3BatchResult(results=[green("XOM"), green("CVX")])
    # 10-29 + 10 weekdays = 11-12: still cooling that day, free on 11-13
    assert enforce([card("XOM")], l3, main=ctx("2026-11-12", {"XOM": "2026-10-29"})).downgraded
    rep = enforce([card("XOM"), card("CVX")], l3, main=ctx("2026-11-13", {"XOM": "2026-10-29"}))
    assert [c.ticker for c in rep.kept] == ["XOM", "CVX"] and rep.downgraded == []


# ── bear trend protection ──────────────────────────────────────────────────

def test_bear_group_downgrades_long_cards():
    trend = {"SPY": "CASH", "QQQ": "EXIT", "IWM": "CASH", "GLD": "CASH", "XLV": "TREND",
             "AAPL": "TREND"}
    l3 = Layer3BatchResult(results=[green(t) for t in ("XOM", "IAU", "XLV", "AAPL")])
    rep = enforce([card(t) for t in ("XOM", "IAU", "XLV", "AAPL")], l3, main=ctx(trend=trend))
    down = {d["ticker"]: d for d in rep.downgraded}
    # single stock -> US equity index group; IAU -> precious_metals (GLD)
    assert set(down) == {"XOM", "IAU"}
    assert "空头趋势保护：XOM 所属组 us_equity_index 趋势状态 CASH" in down["XOM"]["reason"]
    assert {"type": "close_above_ma", "value": 200} in down["IAU"]["conditions"]
    # XLV's own sector is in TREND; AAPL has its own trend state
    assert [c.ticker for c in rep.kept] == ["XLV", "AAPL"]


def test_watch_group_is_not_bearish_and_uncovered_group_is_annotated():
    trend = {"SPY": "WATCH", "QQQ": "CASH"}
    l3 = Layer3BatchResult(results=[green("XOM"), green("UUP")])
    rep = enforce([card("XOM"), card("UUP")], l3, main=ctx(trend=trend))
    assert rep.downgraded == [] and len(rep.kept) == 2
    assert [a["ticker"] for a in rep.annotations] == ["UUP"]     # us_dollar: no trend member


def test_both_rules_combine_into_one_watch_item():
    rep = enforce([card("XOM")], Layer3BatchResult(results=[green("XOM")]),
                  main=ctx(stops={"XOM": "2026-11-04"}, trend={"SPY": "CASH"}))
    (d,) = rep.downgraded
    assert d["rules"] == ["stop_cooldown", "bear_trend"]
    assert d["reason"].endswith("降为观察")


# ── no stacking ────────────────────────────────────────────────────────────

def test_open_main_position_downgrades_new_card_for_same_ticker():
    l3 = Layer3BatchResult(results=[green("XLV"), green("XLP")])
    rep = enforce([card("XLV"), card("XLP")], l3, main=ctx(open_counts={"XLV": 2}))
    (d,) = rep.downgraded
    assert d["ticker"] == "XLV" and d["rules"] == ["no_stacking"]
    assert "不叠仓：XLV 已有 2 笔主管线持仓未平" in d["reason"]
    assert [c.ticker for c in rep.kept] == ["XLP"]


def test_open_counts_read_pending_and_open_main_records_only(tmp_path):
    from marketmind.ledger.store import LedgerStore
    store = LedgerStore(tmp_path / "ledger.db")
    for e, status in ((_entry("main", "XLV", None, None), "open"),
                      (_entry("main", "xlv", None, None), "pending"),
                      (_entry("main", "XOM", "stop", "2026-11-04"), "settled"),
                      (_entry("shadow", "XLP", None, None), "open"),
                      (_entry("main_forced", "SPY", None, None), "open")):
        e.status = status
        store.add(e)
    assert load_open_counts(tmp_path / "ledger.db") == ({"XLV": 2}, "")
    assert load_open_counts(tmp_path / "missing.db")[0] == {}        # fail open


def test_unreadable_ledger_fails_open(tmp_path):
    bad = tmp_path / "ledger.db"
    bad.write_text("not a database", encoding="utf-8")
    assert load_open_counts(bad)[0] == {} and load_stop_exits(bad)[0] == {}
    ctx_ = load_main_guard_context(tmp_path, today=date(2026, 11, 20))
    assert "账本读取失败" in ctx_.ledger_note
    assert len(enforce([card("XOM")], Layer3BatchResult(results=[green("XOM")]), main=ctx_).kept) == 1


# ── forced paper trade skips downgraded tickers ────────────────────────────

def test_forced_pick_excludes_downgraded_and_falls_back_when_none_left():
    from marketmind.pipeline.decision import _pick_paper_trade
    l3 = Layer3BatchResult(results=[green("XOM"), green("CVX")])
    l3.results[0].reward_risk_ratio = 5.0
    assert _pick_paper_trade(None, None, l3, None, None).ticker == "XOM"
    assert _pick_paper_trade(None, None, l3, None, None, exclude={"xom"}).ticker == "CVX"
    pt = _pick_paper_trade(None, None, l3, None, None, exclude={"XOM", "CVX"})
    assert pt.source == "fallback:SPY"                       # existing no-pick behaviour


# ── fail open ──────────────────────────────────────────────────────────────

def test_missing_trend_data_fails_open_with_annotation():
    rep = enforce([card("XOM")], Layer3BatchResult(results=[green("XOM")]), main=ctx(trend=None))
    assert [c.ticker for c in rep.kept] == ["XOM"] and rep.downgraded == []
    assert "趋势数据不可用" in rep.annotations[0]["note"]
    assert rep.main_record()["trend_available"] is False


def _trend_file(folder, day, states):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{day}.json").write_text(json.dumps(
        {"date": day, "full": {t: {"ticker": t, "state": s} for t, s in states.items()}}),
        encoding="utf-8")


def test_stale_or_missing_trend_file_is_unavailable(tmp_path):
    assert load_trend_states(tmp_path, date(2026, 11, 20))[0] is None
    _trend_file(tmp_path / "trend", "2026-11-10", {"SPY": "CASH"})
    states, newest, note = load_trend_states(tmp_path, date(2026, 11, 20))
    assert states is None and newest is None and "2026-11-10" in note
    ctx_ = load_main_guard_context(tmp_path, today=date(2026, 11, 20))
    rep = enforce([card("XOM")], Layer3BatchResult(results=[green("XOM")]), main=ctx_)
    assert len(rep.kept) == 1                                  # no ledger, no trend: no block


def test_weekend_crypto_files_do_not_hide_weekday_equity_states(tmp_path):
    folder = tmp_path / "trend"
    _trend_file(folder, "2026-11-20", {"SPY": "CASH", "BTC-USD": "CASH"})
    _trend_file(folder, "2026-11-21", {"BTC-USD": "TREND"})
    _trend_file(folder, "2026-11-22", {"BTC-USD": "TREND"})
    _trend_file(folder, "2026-11-24", {"SPY": "TREND"})          # after "today": ignored
    states, newest, _ = load_trend_states(tmp_path, date(2026, 11, 23))
    assert states == {"SPY": "CASH", "BTC-USD": "TREND"} and newest == "2026-11-22"


# ── ledger input: main stops only (shadows / forced trades never cool a ticker) ──

def _entry(source_type, ticker, exit_reason, exit_date):
    from marketmind.ledger.store import LedgerEntry
    e = LedgerEntry(source_type=source_type, source_id="x", ticker=ticker, direction="long",
                    hold_bars=5, confidence=0.6, position_usd=100.0, falsifier="f")
    e.status, e.exit_reason, e.exit_date = "settled", exit_reason, exit_date
    return e


def test_stop_exits_read_main_records_only(tmp_path):
    from marketmind.ledger.store import LedgerStore
    store = LedgerStore(tmp_path / "ledger.db")
    for e in (_entry("main", "XOM", "stop", "2026-11-04"), _entry("main", "XOM", "stop", "2026-10-30"),
              _entry("main", "CVX", "target", "2026-11-04"),
              _entry("shadow", "NVDA", "stop", "2026-11-04"),
              _entry("main_forced", "SPY", "stop", "2026-11-04")):
        store.add(e)                     # add() keeps the settled fields as given
    stops, note = load_stop_exits(tmp_path / "ledger.db")
    assert stops == {"XOM": "2026-11-04"} and note == ""


def test_without_main_context_enforce_is_unchanged():
    """Shadows, baselines and the interactive path call no main rules."""
    rep = enforce([card("XOM")], Layer3BatchResult(results=[green("XOM")]))
    assert len(rep.kept) == 1 and rep.downgraded == [] and rep.main_record() is None


# ── generate_decision plumbing ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_downgraded_card_becomes_watch_card_and_forced_trade_is_untouched():
    from unittest.mock import AsyncMock, patch
    from marketmind.pipeline.decision import generate_decision
    from marketmind.pipeline.layer1_narrative import Layer1Result
    from marketmind.pipeline.layer2_fundamental import Layer2Result
    from marketmind.pipeline.red_team import RedTeamReport

    raw = json.dumps({"decision_cards": [{
        "ticker": "XOM", "direction": "long", "thesis": "oil", "risk_statement": "r",
        "red_team_note": "n", "cash_reframing": "c", "invalidation": "below stop"}],
        "summary": "s"})
    l3 = Layer3BatchResult(results=[green("XOM")])
    with patch("marketmind.pipeline.decision.chat_pro", AsyncMock(return_value={"content": raw})), \
         patch("marketmind.pipeline.decision.generate_contrarian_challenges", AsyncMock(return_value=[])):
        out = await generate_decision(Layer1Result.empty_default(), Layer2Result(), l3, RedTeamReport(),
                                      guard_context=ctx(stops={"XOM": "2026-10-29"}))
        plain = await generate_decision(Layer1Result.empty_default(), Layer2Result(), l3, RedTeamReport())
    assert out.decision_cards == []
    (w,) = out.watch_cards
    assert w.ticker == "XOM" and w.guard_reason.startswith("止损冷却") and w.expiry_days == 30
    assert out.no_trade_card is not None and out.paper_trade is not None
    assert out.paper_trade.ticker == "SPY"         # XOM was downgraded: not the forced pick
    assert out.main_guard["downgrades"][0]["rules"] == ["stop_cooldown"]
    assert "[guard]" in out.summary and "止损冷却" in out.summary
    # no context (interactive path, tests, mock runs): unchanged behaviour
    assert [c.ticker for c in plain.decision_cards] == ["XOM"] and plain.main_guard is None
