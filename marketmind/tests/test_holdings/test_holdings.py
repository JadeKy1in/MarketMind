"""Owner holdings (docs/S6_DESIGN.md): entry, ledger mirror, inspection rules."""
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from marketmind.gateway.price_history import Bar, PriceHistory
from marketmind.holdings import inspect as hi
from marketmind.holdings import store as hs
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.pipeline.l3_indicators import TechnicalSnapshot

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    return LedgerStore(tmp_path / "ledger.db"), tmp_path


# ── entry ───────────────────────────────────────────────────────────────────

def test_add_mirrors_to_ledger_and_merges(env):
    store, tmp = env
    h = hs.add("aapl", 10, 100.0, opened="2026-09-01", stop=90, note="core", ledger=store)
    assert h.ticker == "AAPL" and len(h.ledger_ids) == 1
    e = store.get(h.ledger_ids[0])
    assert (e.source_type, e.direction, e.position_usd, e.hold_bars) == ("owner", "long", 1000.0, 60)
    assert e.confidence_is_default and e.falsifier_rule == {"type": "close_below", "price": 90.0}
    h2 = hs.add("AAPL", 10, 120.0, opened="2026-09-10", ledger=store)
    assert h2.quantity == 20 and h2.cost_basis == pytest.approx(110.0)
    assert h2.opened == "2026-09-01" and h2.stop == 90 and len(h2.ledger_ids) == 2
    assert len(hs.load()) == 1
    saved = json.loads((tmp / "holdings.json").read_text("utf-8"))
    assert saved["holdings"][0]["ticker"] == "AAPL"


def test_add_rejects_options_indices_and_bad_numbers(env):
    for bad in ("AAPL 261016C00200000", "AAPL261016C00200000", "^GSPC", ""):
        with pytest.raises(ValueError):
            hs.add(bad, 1, 1)
    with pytest.raises(ValueError):
        hs.add("AAPL", 0, 100)
    with pytest.raises(ValueError):
        hs.add("AAPL", 1, 100, stop=-1)
    assert hs.load() == []


def test_remove_keeps_ledger(env):
    store, _ = env
    h = hs.add("BTC-USD", 0.1, 60000, ledger=store)
    assert hs.remove("btc-usd") and not hs.remove("BTC-USD")
    assert hs.load() == [] and store.get(h.ledger_ids[0]) is not None


def test_cli_add_list_remove(env, capsys):
    from marketmind.holdings.__main__ import main
    assert main(["add", "MSFT", "2", "400", "--stop", "380"]) == 0
    assert main(["add", "SPY 261016P00500000", "1", "1"]) == 2
    main(["list"])
    out = capsys.readouterr().out
    assert "MSFT" in out and "止损 380" in out and "拒绝" in out
    assert main(["remove", "MSFT"]) == 0 and hs.load() == []


# ── rules ───────────────────────────────────────────────────────────────────

def _snap(**kw):
    base = dict(ticker="X", close=100.0, daily_return_pct=0.0, wma200=80.0, weekly_bars=260,
                above_200wma=True, structure_intact=True, key_resistance=None,
                resistance_distance_pct=None, near_key_resistance=False, atr14=2.0,
                support_low=95.0, support_high=96.0, entry_low=98.0, entry_high=100.5,
                stop_loss=96.0, target_price=110.0, reward_risk_ratio=2.5, light="green",
                recommendation="enter", as_of="2026-09-25", notes=[])
    base.update(kw)
    return TechnicalSnapshot(**base)


H = hs.Holding("X", 10, 120.0, "2026-09-01")


def test_decide_rules_in_order():
    alt = [hi.Alternative("Y", 3.0, "green", 50, 48, 56)]
    assert hi.decide(H, None, alt)[0] == hi.UNAVAILABLE
    assert hi.decide(replace(H, stop=101), _snap(), alt)[0] == hi.EXIT
    assert hi.decide(H, _snap(light="red"), alt)[0] == hi.EXIT
    assert hi.decide(H, _snap(light="yellow", above_200wma=False, structure_intact=False),
                     alt)[0] == hi.EXIT
    v, reason = hi.decide(H, _snap(light="yellow", reward_risk_ratio=0.5), alt)
    assert v == hi.SWITCH and "Y" in reason
    # alternative not better by >= 1 R/R -> hold
    assert hi.decide(H, _snap(light="yellow", reward_risk_ratio=0.9),
                     [hi.Alternative("Y", 1.8, "green", 1, 1, 1)])[0] == hi.HOLD
    assert hi.decide(H, _snap(light="yellow", reward_risk_ratio=0.5), [])[0] == hi.HOLD


def _hist(ticker, closes):
    daily = [Bar(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", c, c * 1.01, c * 0.99, c, 1e6)
             for i, c in enumerate(closes)]
    return PriceHistory(ticker, "static", daily, [])


@pytest.mark.asyncio
async def test_inspection_end_to_end(env, monkeypatch):
    store, tmp = env
    # shadows liked NVDA and SLV recently; LOSER is the owner's losing holding
    for t in ("NVDA", "SLV", "SLV"):
        store.add(LedgerEntry("shadow", f"s:{t}", t, "long", 5, 0.6, 200, "x"),
                  created_at="2026-09-27T10:00:00+00:00")
    store.add(LedgerEntry("shadow", "s:bear", "LOSER", "short", 5, 0.6, 200, "x"),
              created_at="2026-09-27T10:00:00+00:00")
    snaps = {"NVDA": _snap(ticker="NVDA", reward_risk_ratio=3.2),
             "SLV": _snap(ticker="SLV", reward_risk_ratio=2.4),
             "LOSER": _snap(ticker="LOSER", close=80.0, light="yellow", reward_risk_ratio=0.4),
             "WINNER": _snap(ticker="WINNER", close=150.0)}
    monkeypatch.setattr("marketmind.pipeline.l3_indicators.compute_snapshot",
                        lambda hist: snaps.get(hist.ticker))
    monkeypatch.setattr("marketmind.pipeline.decision_guard.is_robinhood_tradable", lambda t: True)

    async def history(t):
        return _hist(t, [1.0]) if t in snaps else None
    holdings = [hs.Holding("LOSER", 10, 100.0, "2026-09-01"), hs.Holding("WINNER", 1, 100.0, "2026-09-01"),
                hs.Holding("GONE", 1, 10.0, "2026-09-01")]
    reports = await hi.inspect_holdings(holdings, store=store, history_fn=history, now=NOW)
    by = {r.ticker: r for r in reports}
    assert by["LOSER"].verdict == hi.SWITCH and by["LOSER"].unrealized_return == pytest.approx(-0.2)
    assert [a["ticker"] for a in by["LOSER"].alternatives] == ["NVDA", "SLV"]
    assert by["LOSER"].shadow_views["short"] == 1
    assert by["WINNER"].verdict == hi.HOLD and by["WINNER"].reason.startswith("盈利中")
    assert by["WINNER"].alternatives == []
    assert by["GONE"].verdict == hi.UNAVAILABLE and by["GONE"].price is None

    hs.save(holdings)
    path = hi.write_report(reports, today="2026-09-28")
    from marketmind.api import whitebox
    d = whitebox.get_holdings()
    assert d["available"] and d["date"] == "2026-09-28" and len(d["items"]) == 3
    assert path.exists()
    hs.remove("WINNER")                      # removed holdings drop out of the page
    d = whitebox.get_holdings()
    assert len(d["items"]) == 2 and d["removed_since_report"] == 1

    sent = []
    monkeypatch.setattr("marketmind.notification.alert_manager.emit_alert",
                        lambda *a, **k: sent.append(a[3]))
    assert hi.alert_on(reports) == 1 and "LOSER" in sent[0]


def test_dashboard_without_holdings(env):
    from marketmind.api import whitebox
    d = whitebox.get_holdings()
    assert d["available"] is False and "录入" in d["reason"]


def test_add_rejects_nan_and_bad_dates(env):
    for q, c in ((float("nan"), 1.0), (1.0, float("inf"))):
        with pytest.raises(ValueError):
            hs.add("AAPL", q, c)
    with pytest.raises(ValueError):
        hs.add("AAPL", 1, 1, opened="28/09/2026")
    with pytest.raises(ValueError):
        hs.add("AAPL", 1, 1, stop=float("nan"))
    assert hs.load() == []


def test_short_history_is_not_an_exit():
    snap = _snap(light="yellow", wma200=None, above_200wma=False, structure_intact=False,
                 reward_risk_ratio=1.5)
    v, reason = hi.decide(H, snap, [])
    assert v == hi.HOLD and "不足 200 周" in reason
