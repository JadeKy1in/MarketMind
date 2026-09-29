"""Pure-code quant Playground agents (docs/PLAYGROUND_AGENTS.md): signal rules on
synthetic bars, and their records through the ledger bridge. No network, no LLM."""
import importlib
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from marketmind.gateway.price_history import Bar, PriceHistory
from marketmind.ledger.store import LedgerStore
from marketmind.playground import ledger_bridge as lb
from marketmind.playground.agent_manifest import load_manifest
from marketmind.playground.agents import _quant as q

AGENTS_DIR = Path(lb.__file__).resolve().parent / "agents"
AGENT_IDS = ("tsmom", "short_term_reversal", "trend_state", "dual_momentum")
tsmom = importlib.import_module("marketmind.playground.agents.tsmom.adapter")
rev = importlib.import_module("marketmind.playground.agents.short_term_reversal.adapter")
trend = importlib.import_module("marketmind.playground.agents.trend_state.adapter")
dual = importlib.import_module("marketmind.playground.agents.dual_momentum.adapter")

LAST = date(2026, 10, 1)                      # last complete bar in the synthetic series
IN_WINDOW = datetime(2026, 10, 2, 14, tzinfo=timezone.utc)
OUT_WINDOW = datetime(2026, 10, 15, 14, tzinfo=timezone.utc)
HURDLE = 0.04


def bars_from(closes, last=LAST, wiggle=0.01):
    """Consecutive daily bars ending on `last`; high/low +-wiggle around the close."""
    start = last - timedelta(days=len(closes) - 1)
    return [Bar((start + timedelta(days=i)).isoformat(), c, c * (1 + wiggle), c * (1 - wiggle), c, 1e6)
            for i, c in enumerate(closes)]


def geometric(n, annual, start=100.0, noise=0.0):
    """n closes growing `annual` per 252 bars, with an alternating +-noise zig-zag."""
    g = (1 + annual) ** (1 / 252)
    return [start * g ** i * (1 + (noise if i % 2 else -noise)) for i in range(n)]


def fetch_stub(histories, hurdle=HURDLE, src="^IRX 252d mean (test)"):
    calls = []

    async def fetch(tickers):
        calls.append(list(tickers))
        return ({t: histories.get(t) for t in tickers},
                {t: "static" for t in tickers if histories.get(t)}, hurdle, src)
    fetch.calls = calls
    return fetch


# ── shared helpers ──────────────────────────────────────────────────────────

def test_helpers_confidence_stop_windows():
    assert q.confidence(0) == 0.5 and q.confidence(-5) == 0.65 and q.confidence(1) == 0.575
    b = bars_from([100.0] * 30, wiggle=0.01)                     # TR = 2 every bar
    lvl, atr = q.atr_stop(b, "long")
    assert atr == pytest.approx(2.0) and lvl == pytest.approx(94.0)
    assert q.atr_stop(b, "short")[0] == pytest.approx(106.0)
    assert q.atr_stop(b[:10], "long") is None
    assert q.month_rebalance_key(date(2026, 10, 7)) == "2026-10"
    assert q.month_rebalance_key(date(2026, 10, 8)) is None
    assert q.week_key(date(2026, 9, 29)) == "2026-W40"
    text, rule = q.falsifier("SPY", "short", 106.0, 2.0, 21)
    assert rule == {"type": "close_above", "price": 106.0} and "106" in text


def test_ewma_vol_matches_the_zigzag():
    b = bars_from(geometric(400, 0.0, noise=0.01))               # +-~2% daily swings
    vol = q.ewma_vol(b, "SPY")
    assert vol == pytest.approx(0.02 * math.sqrt(261), rel=0.05)
    assert q.ewma_vol(b, "BTC-USD") == pytest.approx(0.02 * math.sqrt(365), rel=0.05)
    assert q.ewma_vol(b[:30], "SPY") is None


def test_unavailable_reasons():
    b = bars_from([100.0] * 300)
    assert q.unavailable("SPY", None, 10, LAST).startswith("no price history")
    assert q.unavailable("SPY", b, 400, LAST).startswith("insufficient history")
    assert q.unavailable("SPY", b, 10, LAST + timedelta(days=8)).startswith("stale")
    assert q.unavailable("SPY", b, 10, LAST) is None


# ── tsmom ───────────────────────────────────────────────────────────────────

def _tsmom_histories():
    return {"SPY": bars_from(geometric(400, 0.20, noise=0.005)),
            "TLT": bars_from(geometric(400, -0.10, noise=0.005)),
            "GLD": bars_from(geometric(400, 0.02, noise=0.005)),        # below the 4% hurdle
            "BTC-USD": bars_from(geometric(500, 0.50, noise=0.02)),
            "EFA": bars_from(geometric(200, 0.20)),                     # too short
            "EEM": bars_from(geometric(400, 0.20), last=LAST - timedelta(days=20))}   # stale


def test_tsmom_signal_is_the_sign_of_the_12m_excess_return():
    rows, missing = tsmom.signals(_tsmom_histories(), HURDLE, LAST)
    assert rows["SPY"]["direction"] == "long" and rows["TLT"]["direction"] == "short"
    assert rows["GLD"]["direction"] == "short"                   # 2% < 4% T-bill
    assert rows["SPY"]["excess_12m"] == pytest.approx(0.20 - HURDLE, abs=0.01)
    assert rows["BTC-USD"]["ret_12m"] > 0.7                      # 365 UTC-day lookback
    assert rows["BTC-USD"]["vol_ann"] > rows["SPY"]["vol_ann"]
    assert missing["EFA"].startswith("insufficient") and missing["EEM"].startswith("stale")
    assert missing["QQQ"].startswith("no price history")


@pytest.mark.asyncio
async def test_tsmom_calls_only_in_the_rebalance_window():
    fetch = fetch_stub(_tsmom_histories())
    out = await tsmom.analyze({}, fetch=fetch, now=IN_WINDOW)
    calls = {c["ticker"]: c for c in out["directional_calls"]}
    assert set(calls) == {"SPY", "TLT", "GLD", "BTC-USD"}
    spy, tlt, btc = calls["SPY"], calls["TLT"], calls["BTC-USD"]
    assert spy["direction"] == "long" and spy["falsifier_rule"]["type"] == "close_below"
    assert spy["falsifier_rule"]["price"] < spy["signal"]["close"]
    assert tlt["direction"] == "short" and tlt["falsifier_rule"]["price"] > tlt["signal"]["close"]
    assert spy["hold_bars"] == 21 and btc["hold_bars"] == 30 and spy["signal_key"] == "2026-10:SPY"
    assert all(0.5 <= c["confidence"] <= 0.65 for c in calls.values())
    assert "Moskowitz" in spy["thesis"]
    quiet = fetch_stub(_tsmom_histories())
    out = await tsmom.analyze({}, fetch=quiet, now=OUT_WINDOW)
    assert out["directional_calls"] == [] and quiet.calls == []   # no fetch between rebalances
    out = await tsmom.analyze({}, fetch=fetch_stub(_tsmom_histories(), 0.0, "unavailable -> 0"),
                              now=IN_WINDOW)
    assert out["directional_calls"] == [] and "unavailable" in out["no_calls_reason"]


# ── short-term reversal ─────────────────────────────────────────────────────

def _sector_histories(week_moves):
    out = {}
    for t, move in week_moves.items():
        closes = [100.0] * 40 + [100.0 * (1 + move)]            # the last bar makes the week's move
        out[t] = bars_from(closes)
    return out


def test_reversal_buys_the_two_biggest_relative_losers():
    moves = dict(zip(rev.UNIVERSE, [0.01, 0.02, -0.05, 0.00, 0.01, 0.03, -0.02, 0.015, -0.01, 0.005, 0.02]))
    h = _sector_histories(moves)
    rows, missing, as_of = rev.signals(h, LAST)
    assert as_of == LAST.isoformat() and missing == {} and rows["XLE"]["rank"] == 1
    calls, _ = rev.build_calls(rows, h, "2026-W40")
    assert [c["ticker"] for c in calls] == ["XLE", "XLP"]
    assert all(c["direction"] == "long" and c["hold_bars"] == 5 for c in calls)
    assert all(c["signal_key"] == "2026-W40" for c in calls)      # one set per week
    assert calls[0]["confidence"] > calls[1]["confidence"] >= 0.5
    assert calls[0]["falsifier_rule"]["price"] < calls[0]["signal"]["close"]


def test_reversal_ranks_only_an_aligned_cross_section():
    moves = {t: 0.01 * i for i, t in enumerate(rev.UNIVERSE)}
    h = _sector_histories(moves)
    h["XLB"] = bars_from([100.0] * 41, last=LAST - timedelta(days=1))    # a day behind
    h["XLC"] = None
    rows, missing, _ = rev.signals(h, LAST)
    assert "XLB" not in rows and missing["XLB"].startswith("misaligned")
    assert missing["XLC"].startswith("no price history") and len(rows) == 9
    for t in ("XLE", "XLF"):
        h[t] = None
    rows, missing, _ = rev.signals(h, LAST)
    assert rows == {}                                            # 7 < 8 aligned ETFs


@pytest.mark.asyncio
async def test_reversal_analyze_every_run_uses_the_week_key():
    moves = dict(zip(rev.UNIVERSE, [0.01, 0.02, -0.05, 0.00, 0.01, 0.03, -0.02, 0.015, -0.01, 0.005, 0.02]))
    out = await rev.analyze({}, fetch=fetch_stub(_sector_histories(moves)),
                            now=datetime(2026, 10, 2, tzinfo=timezone.utc))
    assert [c["ticker"] for c in out["directional_calls"]] == ["XLE", "XLP"]
    assert out["week"] == "2026-W40"
    assert (await rev.analyze({}, mock=True))["directional_calls"] == []


# ── trend state machine ─────────────────────────────────────────────────────

def _trend_series():
    """Rise, pull back hard enough for a chandelier exit, then break out again."""
    up = [100 * 1.002 ** i for i in range(320)]
    down = [up[-1] * 0.99 ** i for i in range(1, 16)]
    again = [down[-1] * 1.01 ** i for i in range(1, 80)]
    return up + down + again


def _cut_at_last_entry(extra=0):
    from marketmind.trend.rules import TrendConfig
    from marketmind.trend.state import simulate
    full = bars_from(_trend_series())
    sim = simulate("SPY", full, TrendConfig(), HURDLE)
    idx = sim.trades[-1].signal_idx
    assert idx > 330                                             # the re-entry, not the first
    return bars_from([b.close for b in full[:idx + 1 + extra]])


@pytest.mark.asyncio
async def test_trend_state_fresh_entry_becomes_one_long_call():
    fresh = _cut_at_last_entry()
    flat = bars_from([100.0] * len(fresh))
    fetch = fetch_stub({"SPY": fresh, "QQQ": flat})
    out = await trend.analyze({}, fetch=fetch, now=datetime(2026, 10, 2, tzinfo=timezone.utc))
    calls = out["directional_calls"]
    assert [c["ticker"] for c in calls] == ["SPY"] and out["in_trend"] == ["SPY"]
    c = calls[0]
    assert c["direction"] == "long" and c["hold_bars"] == 60 and c["confidence"] == 0.65
    assert c["signal_key"] == f"SPY:{LAST.isoformat()}"
    assert c["falsifier_rule"] == {"type": "close_below", "price": c["signal"]["stop_level"]}
    assert c["falsifier_rule"]["price"] < c["signal"]["close"]
    assert "DIA" in out["unavailable"]                           # no data for the rest


@pytest.mark.asyncio
async def test_trend_state_old_entry_is_not_a_call():
    old = _cut_at_last_entry(extra=5)
    out = await trend.analyze({}, fetch=fetch_stub({"SPY": old}),
                              now=datetime(2026, 10, 2, tzinfo=timezone.utc))
    assert out["in_trend"] == ["SPY"] and out["directional_calls"] == []


def test_trend_excess_rank():
    s = lambda r: SimpleNamespace(ret_12m=r, hurdle=0.04)
    ranks = trend.excess_ranks({"A": s(0.1), "B": s(0.3), "C": s(None), "D": s(-0.2)})
    assert ranks == {"D": 0.0, "A": 0.5, "B": 1.0}


# ── dual momentum ───────────────────────────────────────────────────────────

def _dual_histories(spy, efa, btc, ief=0.03, tlt=0.02):
    h = {"SPY": bars_from(geometric(400, spy, noise=0.003)),
         "EFA": bars_from(geometric(400, efa, noise=0.003)),
         "BTC-USD": bars_from(geometric(500, btc, noise=0.01)),
         "IEF": bars_from(geometric(400, ief, noise=0.002)),
         "TLT": bars_from(geometric(400, tlt, noise=0.002))}
    return h


def test_dual_momentum_relative_then_absolute():
    d = dual.decide(_dual_histories(0.20, 0.10, 0.05), HURDLE, LAST)
    assert d["pick"] == "SPY" and d["leg"] == "risk"
    d = dual.decide(_dual_histories(0.05, 0.10, 0.30), HURDLE, LAST)
    assert d["pick"] == "BTC-USD"
    d = dual.decide(_dual_histories(0.02, -0.10, -0.30), HURDLE, LAST)
    assert d["pick"] == "IEF" and d["leg"] == "bonds" and d["winner"] == "SPY"
    h = _dual_histories(0.02, -0.10, -0.30)
    h["IEF"] = None
    assert dual.decide(h, HURDLE, LAST)["pick"] == "TLT"
    h = _dual_histories(0.20, 0.10, 0.05)
    h["BTC-USD"] = None
    d = dual.decide(h, HURDLE, LAST)
    assert d["pick"] is None and "BTC-USD" in d["reason"]


@pytest.mark.asyncio
async def test_dual_momentum_one_call_per_month():
    out = await dual.analyze({}, fetch=fetch_stub(_dual_histories(0.20, 0.10, 0.05)), now=IN_WINDOW)
    [c] = out["directional_calls"]
    assert (c["ticker"], c["direction"], c["hold_bars"], c["signal_key"]) == ("SPY", "long", 21, "2026-10")
    assert 0.5 < c["confidence"] <= 0.65 and c["falsifier_rule"]["type"] == "close_below"
    out = await dual.analyze({}, fetch=fetch_stub(_dual_histories(0.02, -0.1, -0.3)), now=IN_WINDOW)
    assert out["directional_calls"][0]["ticker"] == "IEF"
    assert out["directional_calls"][0]["confidence"] == 0.5
    quiet = fetch_stub({})
    out = await dual.analyze({}, fetch=quiet, now=OUT_WINDOW)
    assert out["directional_calls"] == [] and quiet.calls == []


# ── manifests / contract ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manifests_and_mock_mode():
    cites = {"tsmom": "Moskowitz", "short_term_reversal": "Jegadeesh", "trend_state": "TREND_DESIGN",
             "dual_momentum": "Antonacci"}
    for aid in AGENT_IDS:
        m = load_manifest(AGENTS_DIR / aid)
        assert m is not None and m.agent_id == aid and m.domain_universe
        assert cites[aid] in m.description and "zero-llm" in m.tags
        mod = importlib.import_module(f"marketmind.playground.agents.{aid}.adapter")
        assert (await mod.analyze({}, mock=True))["directional_calls"] == []
        src = (AGENTS_DIR / aid / "adapter.py").read_text(encoding="utf-8")
        assert "async_client" not in src and "chat_" not in src          # never an LLM
    assert load_manifest(AGENTS_DIR / "_quant") is None                  # helpers, not an agent


# ── ledger bridge ───────────────────────────────────────────────────────────

def _decision(agent, calls):
    return SimpleNamespace(agent_id=agent, run_id="r", directional_calls=calls,
                           metadata={"mock_mode": False})


def _histories_from(h):
    async def fn(tickers):
        return {t: PriceHistory(t, "static", h[t], []) for t in tickers if h.get(t)}
    return fn


@pytest.mark.asyncio
async def test_tsmom_records_through_the_bridge_once_per_month(tmp_path):
    h = _tsmom_histories()
    out = await tsmom.analyze({}, fetch=fetch_stub(h), now=IN_WINDOW)
    store = LedgerStore(tmp_path / "l.db")
    manifests = {"tsmom": load_manifest(AGENTS_DIR / "tsmom")}
    res = SimpleNamespace(decisions=[_decision("tsmom", out["directional_calls"])])
    s = await lb.record_run(store, res, manifests, today="2026-10-02", tradable=lambda t: True,
                            histories_fn=_histories_from(h))
    rows = {e.ticker: e for e in store.list(source_type="playground")}
    assert set(rows) == {"SPY", "TLT", "GLD", "BTC-USD"} and s["dropped"] == []
    spy, tlt = rows["SPY"], rows["TLT"]
    assert spy.source_id == "playground:tsmom" and spy.hold_bars == 21 and rows["BTC-USD"].hold_bars == 30
    assert spy.falsifier_rule["type"] == "close_below" and tlt.direction == "short"
    assert tlt.falsifier_rule["type"] == "close_above"
    assert spy.meta["signal_key"] == "2026-10:SPY" and spy.meta["model"] == tsmom.MODEL
    assert spy.meta["signal"]["excess_12m"] == out["signals"]["SPY"]["excess_12m"]
    assert len(store.list(source_type="benchmark")) <= 1         # random pick may lack data
    # the next day's run inside the same window records nothing new
    s = await lb.record_run(store, res, manifests, today="2026-10-03", tradable=lambda t: True,
                            histories_fn=_histories_from(h))
    assert s["recorded"] == {} and len(s["dropped"]) == 4
    assert len(store.list(source_type="playground")) == 4


@pytest.mark.asyncio
async def test_bridge_hold_bars_and_misplaced_rule(tmp_path):
    h = {"AAA": bars_from([10.0] * 5)}
    store = LedgerStore(tmp_path / "l.db")
    calls = [{"ticker": "AAA", "direction": "long", "confidence": 0.6, "hold_bars": 5,
              "falsifier": "x", "falsifier_rule": {"type": "close_below", "price": 12.0}}]
    await lb.record_run(store, SimpleNamespace(decisions=[_decision("a", calls)]), {},
                        today="2026-10-02", tradable=lambda t: True, histories_fn=_histories_from(h))
    [e] = store.list(source_type="playground")
    assert e.hold_bars == 5 and e.falsifier_rule is None           # 12 is above the close 10
    assert "signal_key" not in e.meta
    c, _ = lb.parse_call({"ticker": "AAA", "direction": "long", "confidence": 0.6,
                          "falsifier_rule": {"type": "bogus", "price": 1}}, lambda t: True)
    assert c["falsifier_rule"] is None and c["hold"] == lb.DEFAULT_HOLD
